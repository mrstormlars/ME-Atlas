"""Tests for the card data model and validator. All inputs are fictional; no network, no LLM."""

import copy
import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from me_atlas import cards
from me_atlas.cards import CardValidationError, Issue

FIXTURES = Path(__file__).parent / "fixtures" / "cards"
VALID_CARD = FIXTURES / "fictional-hypothesis.yaml"
VALID_CHANGELOG = FIXTURES / "changelog.yaml"
REPO_ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 31)


# --- helpers ---------------------------------------------------------------


def base() -> dict:
    return copy.deepcopy(yaml.safe_load(VALID_CARD.read_text(encoding="utf-8")))


def study(data: dict, study_id: str) -> dict:
    return next(s for s in data["studies"] if s["id"] == study_id)


def write_card(directory: Path, data: dict, filename: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename or f"{data['slug']}.yaml")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def rules(issues: list[Issue]) -> set[str]:
    return {i.rule for i in issues}


def check(tmp_path: Path, data: dict, filename: str | None = None) -> list[Issue]:
    return cards.validate_card_file(write_card(tmp_path / "cards", data, filename))


def changelog_in(tmp_path: Path, entries: list[dict], card_slugs=("fictional-hypothesis",)) -> list[Issue]:
    directory = tmp_path / "cards"
    directory.mkdir()
    for slug in card_slugs:
        write_card(directory, {**base(), "slug": slug})
    path = directory / "changelog.yaml"
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    return cards.validate_changelog_file(path, today=TODAY)


def entry(**overrides) -> dict:
    e = {
        "date": dt.date(2026, 10, 1),
        "card": "fictional-hypothesis",
        "change": "Added a fictional study.",
        "reason": "A fictional paper qualified.",
        "sources": ["pmid:00000004"],
        "tier": 1,
    }
    return {**e, **overrides}


# --- valid fixtures (C3) ---------------------------------------------------


def test_valid_fixture_card_has_no_errors():
    assert cards.validate_card_file(VALID_CARD) == []


def test_valid_fixture_card_loads_and_exercises_every_field():
    card = cards.load_card(VALID_CARD)
    assert card.level == 4
    assert card.contested is not None and card.contested.rungs == [4]
    assert card.badges.diagnostic_marker.value and card.badges.explains_pem.value
    assert card.subgroups and card.working_on_it and card.early_signals
    assert {s.role for s in card.studies} == {"supports", "contradicts", "early_signal", "context"}
    assert {s.design for s in card.studies} == {"controlled", "intervention_controlled", "uncontrolled", "other"}
    assert card.last_checked.by == "ai_pair"


def test_fixture_ids_and_titles_are_obviously_fake():
    for s in cards.load_card(VALID_CARD).studies:
        assert s.title.startswith("Fictional")
        assert s.id.startswith(("pmid:0000000", "doi:10.0000/fictional"))


def test_derived_fields():
    card = cards.load_card(VALID_CARD)
    assert card.long_covid is True  # one cited study has a long COVID cohort
    assert card.hatched_rungs == [4]
    data = base()
    study(data, "pmid:00000004")["cohort"] = "me_cfs"
    data["contested"] = None
    card = cards.Card.model_validate(data)
    assert card.long_covid is False and card.hatched_rungs == []


def test_valid_changelog_has_no_errors(tmp_path):
    directory = tmp_path / "cards"
    directory.mkdir()
    write_card(directory, base())
    (directory / "changelog.yaml").write_text(VALID_CHANGELOG.read_text(encoding="utf-8"), encoding="utf-8")
    assert cards.validate_changelog_file(directory / "changelog.yaml", today=TODAY) == []
    entries = cards.load_changelog(directory / "changelog.yaml", today=TODAY)
    assert [e.tier for e in entries] == [1, 2]


def test_drafts_use_the_same_schema(tmp_path):
    path = write_card(tmp_path / "drafts", base())
    assert cards.validate_card_file(path) == []


# --- V1 schema -------------------------------------------------------------


def test_v1_level_above_5(tmp_path):
    data = base()
    data["level"] = 6
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert any(i.path == "level" for i in issues)


def test_v1_level_below_0(tmp_path):
    data = base()
    data["level"] = -1
    assert rules(check(tmp_path, data)) == {"V1"}


@pytest.mark.parametrize(
    ("mutate", "expected_path"),
    [
        (lambda d: d.pop("core_claim"), "core_claim"),
        (lambda d: d.update(early_signals="a bare string"), "early_signals"),
        (lambda d: d["core_claim"].update(sources="pmid:00000001"), "core_claim.sources"),
        (lambda d: d["studies"][0].update(case_definition="Canadian"), "studies[0].case_definition"),
        (lambda d: d["studies"][0].update(id="not-an-id"), "studies[0].id"),
        (lambda d: d["last_checked"].update(by="robot"), "last_checked.by"),
        (lambda d: d["studies"][0].update(n_patients=-5), "studies[0].n_patients"),
        (lambda d: d.update(surprise_field=1), "surprise_field"),
    ],
)
def test_v1_other_schema_violations(tmp_path, mutate, expected_path):
    data = base()
    mutate(data)
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert expected_path in {i.path for i in issues}


def test_v1_top_level_not_a_mapping(tmp_path):
    directory = tmp_path / "cards"
    directory.mkdir()
    path = directory / "x.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    assert rules(cards.validate_card_file(path)) == {"V1"}


def test_unparseable_yaml_is_reported_not_raised(tmp_path):
    directory = tmp_path / "cards"
    directory.mkdir()
    path = directory / "x.yaml"
    path.write_text("a: [unclosed\n", encoding="utf-8")
    assert rules(cards.validate_card_file(path)) == {"YAML"}


@pytest.mark.parametrize("bad", [True, 2.0, "2"])
def test_v1_level_must_be_a_strict_integer(tmp_path, bad):
    data = base()
    data["level"] = bad
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert [i.path for i in issues] == ["level"]


@pytest.mark.parametrize("bad", [True, 4.0])
def test_v1_contested_rungs_must_be_strict_integers(tmp_path, bad):
    data = base()
    data["contested"]["rungs"] = [bad]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert [i.path for i in issues] == ["contested.rungs[0]"]


@pytest.mark.parametrize("bad", [True, 1.0])
def test_v1_changelog_tier_must_be_a_strict_integer(tmp_path, bad):
    issues = changelog_in(tmp_path, [entry(tier=bad)])
    assert rules(issues) == {"V1"}
    assert [i.path for i in issues] == ["[0].tier"]


# --- V2 slug ---------------------------------------------------------------


def test_v2_slug_differs_from_file_name(tmp_path):
    issues = check(tmp_path, base(), filename="some-other-name.yaml")
    assert rules(issues) == {"V2"}
    assert issues[0].path == "slug"


# --- V12 unique study ids ---------------------------------------------------


def test_v12_duplicate_study_id(tmp_path):
    data = base()
    data["studies"].append(copy.deepcopy(data["studies"][0]))
    issues = check(tmp_path, data)
    assert rules(issues) == {"V12"}
    assert [i.path for i in issues] == [f"studies[{len(data['studies']) - 1}].id"]


def test_v12_reports_each_extra_occurrence(tmp_path):
    data = base()
    data["studies"] += [copy.deepcopy(data["studies"][0]), copy.deepcopy(data["studies"][0])]
    assert [i.path for i in check(tmp_path, data)] == ["studies[5].id", "studies[6].id"]


# --- V3 sources exist in studies -------------------------------------------


def test_v3_source_not_in_studies(tmp_path):
    data = base()
    data["core_claim"]["sources"] = ["pmid:00000001", "pmid:09999999"]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V3"}
    assert issues[0].path == "core_claim.sources[1]"


@pytest.mark.parametrize(
    "where",
    ["level_reason", "contested.reason", "badges.explains_pem.reason", "subgroups[0]", "early_signals[0]"],
)
def test_v3_applies_to_every_sourced_text(tmp_path, where):
    data = base()
    node = data
    for part in where.replace("]", "").replace("[", ".").split("."):
        node = node[int(part)] if part.isdigit() else node[part]
    node["sources"] = node["sources"] + ["pmid:09999999"]
    issues = check(tmp_path, data)
    assert "V3" in rules(issues)
    assert any(i.path.startswith(where) for i in issues if i.rule == "V3")


# --- V4 at least one source ------------------------------------------------


def test_v4_empty_sources_at_level_above_0(tmp_path):
    data = base()
    data["level_reason"]["sources"] = []
    issues = check(tmp_path, data)
    assert rules(issues) == {"V4"}
    assert issues[0].path == "level_reason.sources"


def test_v4_empty_sources_in_early_signal(tmp_path):
    data = base()
    data["early_signals"][0]["sources"] = []
    assert rules(check(tmp_path, data)) == {"V4"}


def _level_zero() -> dict:
    data = base()
    data.update(level=0, contested=None)
    data["badges"]["explains_pem"] = {"value": False, "reason": None}
    return data


def test_v4_level_reason_may_be_unsourced_at_level_0(tmp_path):
    data = _level_zero()
    data["level_reason"]["sources"] = []
    assert check(tmp_path, data) == []


def test_v4_exception_does_not_cover_other_texts_at_level_0(tmp_path):
    data = _level_zero()
    data["level_reason"]["sources"] = []
    data["core_claim"]["sources"] = []
    issues = check(tmp_path, data)
    assert rules(issues) == {"V4"}
    assert [i.path for i in issues] == ["core_claim.sources"]


# --- V5 level 2 needs a strict controlled supporter -------------------------


def _level_two(data: dict) -> dict:
    data.update(level=2, contested=None)
    data["badges"]["explains_pem"] = {"value": False, "reason": None}
    return data


def test_v5_level_2_with_only_oxford_controlled_support(tmp_path):
    data = _level_two(base())
    for sid in ("pmid:00000001", "pmid:00000002"):
        study(data, sid)["case_definition"] = "Oxford"
    issues = check(tmp_path, data)
    assert rules(issues) == {"V5"}
    assert issues[0].path == "level"


def test_v5_level_2_with_only_uncontrolled_support(tmp_path):
    data = _level_two(base())
    for sid in ("pmid:00000001", "pmid:00000002"):
        study(data, sid)["design"] = "uncontrolled"
    assert rules(check(tmp_path, data)) == {"V5"}


def test_v5_level_1_with_only_oxford_is_allowed(tmp_path):
    data = _level_two(base())
    data["level"] = 1
    for sid in ("pmid:00000001", "pmid:00000002"):
        study(data, sid)["case_definition"] = "Oxford"
    assert check(tmp_path, data) == []


def test_v5_one_strict_controlled_study_is_enough(tmp_path):
    data = _level_two(base())
    study(data, "pmid:00000002")["case_definition"] = "Oxford"  # pmid:00000001 stays CCC
    assert check(tmp_path, data) == []


# --- V6 level 4 needs an intervention_controlled supporter ------------------


def test_v6_level_4_without_intervention_controlled_support(tmp_path):
    data = base()
    study(data, "pmid:00000002")["design"] = "controlled"
    issues = check(tmp_path, data)
    assert rules(issues) == {"V6"}
    assert issues[0].path == "level"


def test_v6_contradicting_intervention_study_does_not_count(tmp_path):
    data = base()
    study(data, "pmid:00000002")["role"] = "contradicts"
    study(data, "pmid:00000002")["design"] = "intervention_controlled"
    study(data, "pmid:00000002")["measures_pem"] = False
    data["badges"]["explains_pem"] = {"value": False, "reason": None}
    assert "V6" in rules(check(tmp_path, data))


def test_v6_level_3_does_not_need_intervention(tmp_path):
    data = base()
    data["level"] = 3
    data["contested"]["rungs"] = [3]
    study(data, "pmid:00000002")["design"] = "controlled"
    assert check(tmp_path, data) == []


# --- V7 explains_pem -------------------------------------------------------


def test_v7_explains_pem_without_a_study_measuring_pem(tmp_path):
    data = base()
    study(data, "pmid:00000002")["measures_pem"] = False
    issues = check(tmp_path, data)
    assert rules(issues) == {"V7"}
    assert issues[0].path == "badges.explains_pem"


def test_v7_pem_study_with_oxford_case_definition_does_not_count(tmp_path):
    data = base()
    study(data, "pmid:00000002")["case_definition"] = "Oxford"
    assert "V7" in rules(check(tmp_path, data))


def test_v7_pem_study_that_is_only_context_does_not_count(tmp_path):
    data = base()
    study(data, "pmid:00000002")["role"] = "context"
    assert "V7" in rules(check(tmp_path, data))


def test_v7_true_with_no_reason_fails(tmp_path):
    data = base()
    data["badges"]["explains_pem"]["reason"] = None
    assert rules(check(tmp_path, data)) == {"V7"}


def test_v7_pem_study_must_be_cited_by_the_badge(tmp_path):
    data = base()
    data["badges"]["explains_pem"]["reason"]["sources"] = ["pmid:00000001"]  # does not measure PEM
    assert rules(check(tmp_path, data)) == {"V7"}


def test_v7_false_badge_needs_nothing(tmp_path):
    data = base()
    data["badges"]["explains_pem"] = {"value": False, "reason": None}
    assert check(tmp_path, data) == []


# --- V8 contested ----------------------------------------------------------


def test_v8_contested_without_a_contradicting_source(tmp_path):
    data = base()
    data["contested"]["reason"]["sources"] = ["pmid:00000001"]  # a supports study
    issues = check(tmp_path, data)
    assert rules(issues) == {"V8"}
    assert issues[0].path == "contested.reason"


def test_v8_rungs_above_level(tmp_path):
    data = base()
    data["contested"]["rungs"] = [4, 5]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V8"}
    assert [i.path for i in issues] == ["contested.rungs[1]"]


def test_v8_rung_zero_is_not_allowed(tmp_path):
    data = base()
    data["contested"]["rungs"] = [0]
    assert rules(check(tmp_path, data)) == {"V8"}


def test_v8_contested_null_needs_nothing(tmp_path):
    data = base()
    data["contested"] = None
    assert check(tmp_path, data) == []


# --- V9 case definition none ------------------------------------------------


@pytest.mark.parametrize("role", ["supports", "contradicts"])
def test_v9_case_definition_none_cannot_support_or_contradict(tmp_path, role):
    data = base()
    data["studies"].append(
        {
            **study(data, "pmid:00000001"),
            "id": "pmid:00000009",
            "title": "Fictional study with no stated case definition",
            "case_definition": "none",
            "role": role,
        }
    )
    issues = check(tmp_path, data)
    assert rules(issues) == {"V9"}
    assert issues[0].path == f"studies[{len(data['studies']) - 1}].case_definition"


@pytest.mark.parametrize("role", ["early_signal", "context"])
def test_v9_case_definition_none_is_fine_as_early_signal_or_context(tmp_path, role):
    data = base()
    study(data, "pmid:00000004")["case_definition"] = "none"
    study(data, "pmid:00000004")["role"] = role
    assert check(tmp_path, data) == []


# --- V10 banned words ------------------------------------------------------


def test_v10_promising_in_early_signal(tmp_path):
    data = base()
    data["early_signals"][0]["text"] = "A fictional small study reported a promising change."
    issues = check(tmp_path, data)
    assert rules(issues) == {"V10"}
    assert issues[0].path == "early_signals[0].text"


def test_v10_is_case_insensitive_and_covers_core_claim(tmp_path):
    data = base()
    data["core_claim"]["text"] = "A fictional Breakthrough in widget signalling."
    issues = check(tmp_path, data)
    assert rules(issues) == {"V10"}
    assert issues[0].path == "core_claim.text"


@pytest.mark.parametrize("word", ["cure", "hope", "proven"])
def test_v10_other_banned_words(tmp_path, word):
    data = base()
    data["early_signals"][0]["text"] = f"A fictional report that mentions a {word}."
    assert rules(check(tmp_path, data)) == {"V10"}


def test_v10_does_not_match_inside_other_words(tmp_path):
    data = base()
    data["early_signals"][0]["text"] = "A fictional report on secure signalling and the Hopewell fictional site."
    assert check(tmp_path, data) == []


# --- V11 change log --------------------------------------------------------


def test_v11_entry_for_missing_card(tmp_path):
    issues = changelog_in(tmp_path, [entry(card="no-such-card")])
    assert rules(issues) == {"V11"}
    assert issues[0].path == "[0].card"


def test_v11_tier_4(tmp_path):
    issues = changelog_in(tmp_path, [entry(tier=4)])
    assert rules(issues) == {"V11"}
    assert issues[0].path == "[0].tier"


def test_v11_tier_0(tmp_path):
    assert rules(changelog_in(tmp_path, [entry(tier=0)])) == {"V11"}


def test_v11_future_date(tmp_path):
    issues = changelog_in(tmp_path, [entry(date=dt.date(2999, 1, 1))])
    assert rules(issues) == {"V11"}
    assert issues[0].path == "[0].date"


def test_v11_today_is_not_future(tmp_path):
    assert changelog_in(tmp_path, [entry(date=TODAY)]) == []


def test_v11_reports_every_bad_entry(tmp_path):
    issues = changelog_in(tmp_path, [entry(tier=9), entry(), entry(card="gone")])
    assert [i.path for i in issues] == ["[0].tier", "[2].card"]


def test_changelog_schema_error_is_v1(tmp_path):
    issues = changelog_in(tmp_path, [entry(sources="pmid:00000004")])
    assert rules(issues) == {"V1"}
    assert issues[0].path == "[0].sources"


def test_changelog_top_level_must_be_a_list(tmp_path):
    directory = tmp_path / "cards"
    directory.mkdir()
    path = directory / "changelog.yaml"
    path.write_text("entries: []\n", encoding="utf-8")
    assert rules(cards.validate_changelog_file(path, today=TODAY)) == {"V1"}


def test_empty_changelog_file_is_valid(tmp_path):
    directory = tmp_path / "cards"
    directory.mkdir()
    path = directory / "changelog.yaml"
    path.write_text("", encoding="utf-8")
    assert cards.validate_changelog_file(path, today=TODAY) == []


# --- C4: all errors at once, with file and path -----------------------------


def test_all_errors_in_a_file_are_collected(tmp_path):
    data = base()
    data["early_signals"][0]["text"] = "A fictional promising change."  # V10
    data["level_reason"]["sources"] = []  # V4
    data["core_claim"]["sources"] = ["pmid:09999999"]  # V3
    data["contested"]["rungs"] = [5]  # V8
    issues = check(tmp_path, data, filename="wrong-name.yaml")  # V2
    assert rules(issues) == {"V2", "V3", "V4", "V8", "V10"}
    assert all(i.file.endswith("wrong-name.yaml") and i.path for i in issues)


def test_several_schema_errors_are_collected(tmp_path):
    data = base()
    data["level"] = 9
    del data["name"]
    data["studies"][1]["design"] = "bogus"
    issues = check(tmp_path, data)
    assert {i.path for i in issues} == {"level", "name", "studies[1].design"}


def test_issue_string_has_file_path_and_rule(tmp_path):
    data = base()
    data["level"] = 6
    text = str(check(tmp_path, data)[0])
    assert "level" in text and "[V1]" in text and ".yaml" in text


def test_load_card_raises_with_all_issues(tmp_path):
    data = base()
    data["core_claim"]["sources"] = []
    data["level_reason"]["sources"] = ["pmid:09999999"]
    path = write_card(tmp_path / "cards", data)
    with pytest.raises(CardValidationError) as exc:
        cards.load_card(path)
    assert {i.rule for i in exc.value.issues} == {"V3", "V4"}


def test_load_cards_skips_changelog(tmp_path):
    directory = tmp_path / "cards"
    write_card(directory, base())
    (directory / "changelog.yaml").write_text("[]\n", encoding="utf-8")
    assert [c.slug for c in cards.load_cards(directory)] == ["fictional-hypothesis"]


# --- C5: command line ------------------------------------------------------


def test_cli_valid_directory_exits_0(tmp_path, capsys):
    write_card(tmp_path / "cards", base())
    assert cards.main(["validate", str(tmp_path / "cards")]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_invalid_card_exits_nonzero_and_prints_every_error(tmp_path, capsys):
    data = base()
    data["level"] = 6
    data["early_signals"][0]["text"] = "A fictional promising change."
    write_card(tmp_path / "cards", data)
    assert cards.main(["validate", str(tmp_path / "cards")]) != 0
    err = capsys.readouterr().err
    assert "fictional-hypothesis.yaml" in err
    assert "level" in err and "[V1]" in err


def test_cli_prints_errors_from_every_file(tmp_path, capsys):
    bad1, bad2 = base(), {**base(), "slug": "second-fictional"}
    bad1["core_claim"]["sources"] = ["pmid:09999999"]
    bad2["core_claim"]["sources"] = ["pmid:09999998"]
    write_card(tmp_path / "cards", bad1)
    write_card(tmp_path / "cards", bad2)
    assert cards.main(["validate", str(tmp_path / "cards")]) == 1
    err = capsys.readouterr().err
    assert "fictional-hypothesis.yaml" in err and "second-fictional.yaml" in err
    assert "pmid:09999999" in err and "pmid:09999998" in err


def test_cli_missing_path_exits_nonzero(tmp_path, capsys):
    assert cards.main(["validate", str(tmp_path / "nope")]) != 0
    assert "does not exist" in capsys.readouterr().err


def test_cli_checks_changelog_in_a_directory(tmp_path, capsys):
    write_card(tmp_path / "cards", base())
    (tmp_path / "cards" / "changelog.yaml").write_text(
        yaml.safe_dump([entry(tier=4)], sort_keys=False), encoding="utf-8"
    )
    assert cards.main(["validate", str(tmp_path / "cards")]) == 1
    assert "[V11]" in capsys.readouterr().err


def test_cli_empty_cards_directory_exits_0(tmp_path, monkeypatch, capsys):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / "drafts").mkdir()
    monkeypatch.chdir(tmp_path)
    assert cards.main(["validate"]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_defaults_to_cards_and_drafts(tmp_path, monkeypatch, capsys):
    write_card(tmp_path / "cards", base())
    bad = base()
    bad["level"] = 6
    write_card(tmp_path / "drafts", bad)
    monkeypatch.chdir(tmp_path)
    assert cards.main(["validate"]) == 1
    assert "drafts" in capsys.readouterr().err


def test_cli_via_python_dash_m_subprocess(tmp_path):
    write_card(tmp_path / "cards", base())
    ok = subprocess.run(
        [sys.executable, "-m", "me_atlas.cards", "validate", str(tmp_path / "cards")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr
    bad = base()
    bad["level"] = 6
    write_card(tmp_path / "bad", bad)
    fail = subprocess.run(
        [sys.executable, "-m", "me_atlas.cards", "validate", str(tmp_path / "bad")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fail.returncode != 0 and "[V1]" in fail.stderr


def test_repository_cards_and_drafts_validate():
    count, issues = cards.validate_paths([REPO_ROOT / "cards", REPO_ROOT / "drafts"])
    assert issues == [], "\n".join(map(str, issues))
