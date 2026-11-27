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
        "decided_by": "ai_pair",
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
    assert card.last_checked.by == "ai_audit"


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


# --- V16 and decided_by (the AI auditor) -----------------------------------


def validate_in_cards_dir(tmp_path: Path, by: str, folder: str = "cards") -> list[Issue]:
    data = base()
    data["last_checked"] = {"date": dt.date(2026, 10, 1), "by": by}
    write_card(tmp_path / folder, data)
    _count, issues = cards.validate_paths(
        [tmp_path / folder], today=TODAY, content_dir=tmp_path / "content", cards_dir=tmp_path / "cards"
    )
    return issues


def test_last_checked_by_allows_ai_audit_and_founder_and_ai_pair_on_a_draft(tmp_path):
    for by in ("ai_pair", "ai_audit", "founder"):
        assert check(tmp_path / by, {**base(), "last_checked": {"date": dt.date(2026, 10, 1), "by": by}}) == []


def test_last_checked_by_rejects_other_values(tmp_path):
    issues = check(tmp_path, {**base(), "last_checked": {"date": dt.date(2026, 10, 1), "by": "editor"}})
    assert rules(issues) == {"V1"} and issues[0].path == "last_checked.by"


def test_v16_a_card_in_cards_with_ai_pair_is_rejected(tmp_path):
    issues = validate_in_cards_dir(tmp_path, "ai_pair")
    assert rules(issues) == {"V16"}
    assert issues[0].path == "last_checked.by" and "ai_audit" in issues[0].message


def test_v16_a_card_in_cards_with_ai_audit_or_founder_passes(tmp_path):
    assert validate_in_cards_dir(tmp_path / "a", "ai_audit") == []
    assert validate_in_cards_dir(tmp_path / "b", "founder") == []


def test_v16_does_not_apply_to_a_draft(tmp_path):
    assert validate_in_cards_dir(tmp_path, "ai_pair", folder="drafts") == []


def test_changelog_entry_without_decided_by_is_rejected(tmp_path):
    e = entry()
    del e["decided_by"]
    issues = changelog_in(tmp_path, [e])
    assert rules(issues) == {"V1"} and issues[0].path == "[0].decided_by"


def test_changelog_entry_with_decided_by_editor_is_rejected(tmp_path):
    issues = changelog_in(tmp_path, [entry(decided_by="editor")])
    assert rules(issues) == {"V1"} and issues[0].path == "[0].decided_by"


def test_changelog_decided_by_accepts_the_four_values(tmp_path):
    values = ["ai_pair", "ai_audit", "founder", "expert"]
    assert changelog_in(tmp_path, [entry(decided_by=v) for v in values]) == []


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


# --- format v2: case definition provenance, direction, group ------------------


def add_study(data: dict, **overrides) -> int:
    """Append a copy of the first fictional study with the overrides applied; returns its index."""
    new = {**copy.deepcopy(study(data, "pmid:00000001")), "id": "pmid:00000009", "title": "Fictional added study"}
    new.update(overrides)
    data["studies"].append(new)
    return len(data["studies"]) - 1


def paths(issues: list[Issue]) -> set[str]:
    return {i.path for i in issues}


def test_v2_unverified_study_as_context_is_valid(tmp_path):
    data = base()
    add_study(
        data,
        case_definition="unverified",
        case_definition_source=None,
        case_definition_quote=None,
        role="context",
    )
    assert check(tmp_path, data) == []


@pytest.mark.parametrize("role", ["supports", "contradicts"])
def test_v9_unverified_cannot_support_or_contradict(tmp_path, role):
    data = base()
    i = add_study(
        data, case_definition="unverified", case_definition_source=None, case_definition_quote=None, role=role
    )
    issues = check(tmp_path, data)
    assert rules(issues) == {"V9"}
    assert paths(issues) == {f"studies[{i}].case_definition"}


def test_v13_recognised_definition_without_quote(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = "Fukuda"
    study(data, "pmid:00000001")["case_definition_quote"] = None
    issues = check(tmp_path, data)
    assert rules(issues) == {"V13"}
    assert paths(issues) == {"studies[0].case_definition_quote"}


def test_v13_recognised_definition_without_source(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = "Fukuda"
    study(data, "pmid:00000001")["case_definition_source"] = None
    issues = check(tmp_path, data)
    assert rules(issues) == {"V13"}
    assert paths(issues) == {"studies[0].case_definition_source"}


@pytest.mark.parametrize("definition", ["CCC", "ICC", "IOM2015", "Fukuda", "Holmes1988", "CDC_unspecified", "Oxford"])
def test_v13_every_recognised_definition_needs_a_quote(tmp_path, definition):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = definition
    study(data, "pmid:00000001")["case_definition_quote"] = None
    assert rules(check(tmp_path, data)) == {"V13"}


def test_v13_fulltext_pdf_is_a_source_like_fulltext_and_needs_the_quote(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = "Fukuda"
    study(data, "pmid:00000001")["case_definition_source"] = "fulltext_pdf"
    study(data, "pmid:00000001")["case_definition_quote"] = None
    issues = check(tmp_path, data)
    assert rules(issues) == {"V13"}
    assert paths(issues) == {"studies[0].case_definition_quote"}
    study(data, "pmid:00000001")["case_definition_quote"] = "A fictional sentence naming the Fukuda criteria."
    assert check(tmp_path, data) == []


def test_v13_an_unknown_source_is_still_refused(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition_source"] = "pdf"
    assert check(tmp_path, data) != []


def test_v13_none_without_source(tmp_path):
    data = base()
    study(data, "pmid:00000004")["case_definition"] = "none"
    study(data, "pmid:00000004")["case_definition_source"] = None
    issues = check(tmp_path, data)
    assert rules(issues) == {"V13"}
    assert paths(issues) == {"studies[3].case_definition_source"}


def test_v13_none_with_a_source_and_no_quote_is_valid(tmp_path):
    data = base()
    study(data, "pmid:00000004")["case_definition"] = "none"
    study(data, "pmid:00000004")["case_definition_source"] = "fulltext"
    study(data, "pmid:00000004")["case_definition_quote"] = None
    assert check(tmp_path, data) == []


def test_v13_unverified_with_a_quote(tmp_path):
    data = base()
    study(data, "pmid:00000004")["case_definition"] = "unverified"
    study(data, "pmid:00000004")["case_definition_source"] = None
    study(data, "pmid:00000004")["case_definition_quote"] = "A sentence that should not be here."
    issues = check(tmp_path, data)
    assert rules(issues) == {"V13"}
    assert paths(issues) == {"studies[3].case_definition_quote"}


def test_v13_unverified_with_a_source(tmp_path):
    data = base()
    study(data, "pmid:00000004")["case_definition"] = "unverified"
    study(data, "pmid:00000004")["case_definition_quote"] = None
    issues = check(tmp_path, data)  # source stays "abstract"
    assert rules(issues) == {"V13"}
    assert paths(issues) == {"studies[3].case_definition_source"}


def test_v1_case_definition_source_outside_the_enum(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition_source"] = "pdf"
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert "studies[0].case_definition_source" in paths(issues)


def test_v1_missing_direction(tmp_path):
    data = base()
    del study(data, "pmid:00000001")["direction"]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert paths(issues) == {"studies[0].direction"}


def test_v1_direction_outside_the_enum(tmp_path):
    data = base()
    study(data, "pmid:00000001")["direction"] = "decreased"
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert paths(issues) == {"studies[0].direction"}


@pytest.mark.parametrize("direction", ["lower", "higher", "no_difference", "mixed", "not_applicable"])
def test_direction_accepts_every_enum_value_for_a_background_study(tmp_path, direction):
    data = base()
    study(data, "pmid:00000004")["direction"] = direction  # role early_signal
    assert check(tmp_path, data) == []


def test_v1_empty_group(tmp_path):
    data = base()
    study(data, "pmid:00000001")["group"] = ""
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert paths(issues) == {"studies[0].group"}


def test_group_is_optional_and_may_be_null(tmp_path):
    data = base()
    assert "group" not in study(data, "pmid:00000001")  # omitted: valid
    study(data, "pmid:00000001")["group"] = None
    assert check(tmp_path, data) == []


# --- Holmes 1988 is treated like Fukuda --------------------------------------


def test_holmes1988_study_satisfies_v5_at_level_2(tmp_path):
    data = _level_two(base())
    for sid in ("pmid:00000001", "pmid:00000002"):
        study(data, sid)["case_definition"] = "Holmes1988"
    assert check(tmp_path, data) == []


def test_holmes1988_study_satisfies_v7_like_fukuda(tmp_path):
    data = base()
    study(data, "pmid:00000002")["case_definition"] = "Holmes1988"
    assert "V7" not in rules(check(tmp_path, data))


def test_holmes1988_ranks_equal_to_fukuda_above_oxford_below_ccc():
    rank = cards.case_definition_rank
    assert rank("Holmes1988") == rank("Fukuda")
    assert rank("Holmes1988") > rank("Oxford")
    assert rank("Holmes1988") < rank("CCC") == rank("ICC") == rank("IOM2015")
    assert rank("unverified") == rank("none") == rank("other") < rank("Oxford")
    assert set(cards.CASE_DEFINITION_RANK) == set(cards.Study.model_fields["case_definition"].annotation.__args__)


# --- "CDC criteria, version not stated" is treated like Fukuda and Holmes 1988 -----


def test_cdc_unspecified_without_a_quote_fails_v13(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = "CDC_unspecified"
    study(data, "pmid:00000001")["case_definition_quote"] = None
    issues = check(tmp_path, data)
    assert rules(issues) == {"V13"}
    assert {i.path for i in issues} == {"studies[0].case_definition_quote"}


def test_cdc_unspecified_without_a_source_fails_v13(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = "CDC_unspecified"
    study(data, "pmid:00000001")["case_definition_source"] = None
    issues = check(tmp_path, data)
    assert rules(issues) == {"V13"}
    assert {i.path for i in issues} == {"studies[0].case_definition_source"}


def test_cdc_unspecified_with_source_and_quote_is_valid(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = "CDC_unspecified"
    study(data, "pmid:00000001")["case_definition_quote"] = "Fictional participants met the CDC criteria."
    assert check(tmp_path, data) == []


def test_cdc_unspecified_study_satisfies_v5_at_level_2(tmp_path):
    data = _level_two(base())
    for sid in ("pmid:00000001", "pmid:00000002"):
        study(data, sid)["case_definition"] = "CDC_unspecified"
    assert check(tmp_path, data) == []


def test_other_definition_alone_still_fails_v5_at_level_2(tmp_path):
    data = _level_two(base())
    for sid in ("pmid:00000001", "pmid:00000002"):
        study(data, sid)["case_definition"] = "other"
        study(data, sid)["case_definition_quote"] = None
    issues = check(tmp_path, data)
    assert rules(issues) == {"V5"}


def test_cdc_unspecified_study_satisfies_v7_like_fukuda(tmp_path):
    data = base()
    study(data, "pmid:00000002")["case_definition"] = "CDC_unspecified"
    assert "V7" not in rules(check(tmp_path, data))


def test_cdc_unspecified_ranks_equal_to_fukuda_and_holmes():
    rank = cards.case_definition_rank
    assert rank("CDC_unspecified") == rank("Fukuda") == rank("Holmes1988")
    assert rank("Oxford") < rank("CDC_unspecified") < rank("CCC")
    assert "CDC_unspecified" in cards.STRICT_CASE_DEFINITIONS
    assert "CDC_unspecified" in cards.RECOGNISED_CASE_DEFINITIONS


# --- paragraphs: level_reason, contested.reason and badges.*.reason may be lists ---------------


def para(text: str, *sources: str) -> dict:
    return {"text": text, "sources": list(sources)}


def test_paragraph_list_form_validates_and_loads(tmp_path):
    data = base()
    data["level_reason"] = [para("First fictional paragraph.", "pmid:00000001"), para("Second.", "pmid:00000002")]
    data["badges"]["explains_pem"]["reason"] = [para("Fictional PEM paragraph.", "pmid:00000002")]
    data["badges"]["diagnostic_marker"]["reason"] = [para("Fictional marker paragraph.", "pmid:00000001")]
    data["contested"]["reason"] = [para("Fictional dispute paragraph.", "pmid:00000003")]
    assert check(tmp_path, data) == []
    card = cards.load_card(write_card(tmp_path / "again", data))
    assert [p.text for p in cards.paragraphs(card.level_reason)] == ["First fictional paragraph.", "Second."]
    assert cards.reason_sources(card.level_reason) == ["pmid:00000001", "pmid:00000002"]


def test_single_form_still_validates_and_is_one_paragraph():
    card = cards.load_card(VALID_CARD)
    assert len(cards.paragraphs(card.level_reason)) == 1
    assert cards.reason_sources(None) == []


@pytest.mark.parametrize(
    ("where", "expected_path"),
    [
        (("level_reason",), "level_reason"),
        (("contested", "reason"), "contested.reason"),
        (("badges", "explains_pem", "reason"), "badges.explains_pem.reason"),
    ],
)
def test_empty_paragraph_list_fails_v1(tmp_path, where, expected_path):
    data = base()
    node = data
    for part in where[:-1]:
        node = node[part]
    node[where[-1]] = []
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert expected_path in {i.path for i in issues}


def test_paragraph_schema_errors_name_the_paragraph(tmp_path):
    data = base()
    data["level_reason"] = [para("Fine.", "pmid:00000001"), {"text": "", "sources": ["pmid:00000001"]}]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"}
    assert {i.path for i in issues} == {"level_reason[1].text"}


def test_a_bare_string_reason_still_fails_v1(tmp_path):
    data = base()
    data["level_reason"] = "A bare string."
    assert rules(check(tmp_path, data)) == {"V1"}


def test_paragraph_without_sources_fails_v4(tmp_path):
    data = base()
    data["level_reason"] = [para("Sourced.", "pmid:00000001"), para("Not sourced.")]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V4"}
    assert [i.path for i in issues] == ["level_reason[1].sources"]


def test_unsourced_paragraphs_in_level_reason_pass_at_level_0(tmp_path):
    data = _level_zero()
    data["level_reason"] = [para("Fictional reasoning only."), para("More fictional reasoning.")]
    assert check(tmp_path, data) == []


def test_level_0_exception_does_not_cover_paragraphs_of_other_reasons(tmp_path):
    data = _level_zero()
    data["level_reason"] = [para("Fictional reasoning only.")]
    data["badges"]["diagnostic_marker"] = {"value": False, "reason": [para("Unsourced.")]}
    issues = check(tmp_path, data)
    assert rules(issues) == {"V4"}
    assert [i.path for i in issues] == ["badges.diagnostic_marker.reason[0].sources"]


def test_paragraph_citing_an_unknown_id_fails_v3(tmp_path):
    data = base()
    data["level_reason"] = [para("Sourced.", "pmid:00000001"), para("Unknown.", "pmid:00000001", "pmid:09999999")]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V3"}
    assert [i.path for i in issues] == ["level_reason[1].sources[1]"]


def test_contradicting_study_only_in_the_second_paragraph_passes_v8(tmp_path):
    data = base()
    data["contested"]["reason"] = [para("A supporting study.", "pmid:00000001"), para("A conflict.", "pmid:00000003")]
    assert check(tmp_path, data) == []


def test_no_contradicting_study_in_any_paragraph_fails_v8(tmp_path):
    data = base()
    data["contested"]["reason"] = [para("One.", "pmid:00000001"), para("Two.", "pmid:00000002")]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V8"}
    assert [i.path for i in issues] == ["contested.reason"]


def test_v7_reads_the_union_of_badge_paragraphs(tmp_path):
    data = base()
    data["badges"]["explains_pem"]["reason"] = [para("Context.", "pmid:00000001"), para("PEM.", "pmid:00000002")]
    assert check(tmp_path, data) == []
    data["badges"]["explains_pem"]["reason"] = [para("Context.", "pmid:00000001")]  # no PEM study cited
    assert rules(check(tmp_path, data)) == {"V7"}


# --- causal map: layer and links (M1, M3, M4, M5) ---------------------------


def link(to="other-fictional-card", support="proposed", sources=("pmid:00000001",), text="A fictional link."):
    return {"to": to, "support": support, "text": text, "sources": list(sources)}


def test_a_card_without_layer_or_links_is_valid_and_has_none():
    card = cards.load_card(VALID_CARD)
    assert card.layer is None and card.links == []


def test_a_card_with_a_layer_and_a_link_is_valid(tmp_path):
    data = base()
    data["layer"] = "mechanism"
    data["links"] = [link(support="associated")]
    assert check(tmp_path, data) == []
    card = cards.Card.model_validate(data)
    assert card.layer == "mechanism" and card.links[0].to == "other-fictional-card"


def test_m1_layer_outside_the_enum(tmp_path):
    data = base()
    data["layer"] = "symptom"  # a layer of the map, but not one a hypothesis card can have
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"} and [i.path for i in issues] == ["layer"]


def test_m1_an_empty_layer_is_not_accepted(tmp_path):
    data = base()
    data["layer"] = ""
    assert [i.path for i in check(tmp_path, data)] == ["layer"]


def test_link_with_an_unknown_key_is_rejected(tmp_path):
    data = base()
    data["links"] = [{**link(), "why": "because"}]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V1"} and issues[0].path == "links[0].why"


def test_link_with_an_unknown_support_is_rejected(tmp_path):
    data = base()
    data["links"] = [link(support="causal")]
    assert [i.path for i in check(tmp_path, data)] == ["links[0].support"]


def test_link_source_not_in_studies_fails_v3_with_the_link_path(tmp_path):
    data = base()
    data["links"] = [link(sources=("pmid:09999999",))]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V3"} and [i.path for i in issues] == ["links[0].sources[0]"]


def test_link_without_sources_fails_v4(tmp_path):
    data = base()
    data["links"] = [link(sources=())]
    issues = check(tmp_path, data)
    assert rules(issues) == {"V4"} and [i.path for i in issues] == ["links[0].sources"]


def test_m3_a_link_to_the_cards_own_slug(tmp_path):
    data = base()
    data["links"] = [link(to="fictional-hypothesis")]
    issues = check(tmp_path, data)
    assert rules(issues) == {"M3"} and [i.path for i in issues] == ["links[0].to"]


def test_m4_the_same_target_twice_on_one_card(tmp_path):
    data = base()
    data["links"] = [link(), link(text="Another fictional link."), link(to="third-fictional-card")]
    issues = check(tmp_path, data)
    assert rules(issues) == {"M4"} and [i.path for i in issues] == ["links[1].to"]


@pytest.mark.parametrize("support", ["associated", "directional"])
def test_m5_a_review_only_source_cannot_carry_more_than_proposed(tmp_path, support):
    data = base()
    data["links"] = [link(support=support, sources=("doi:10.0000/fictional.5",))]  # design: other
    issues = check(tmp_path, data)
    assert rules(issues) == {"M5"} and issues[0].path == "links[0].support"
    assert "recognised case definition" in issues[0].message


def test_m5_a_study_without_a_recognised_case_definition_is_not_enough(tmp_path):
    data = base()
    data["links"] = [link(support="associated", sources=("pmid:00000004",))]  # case_definition: other
    assert rules(check(tmp_path, data)) == {"M5"}


def test_m5_an_oxford_only_source_is_not_enough(tmp_path):
    data = base()
    study(data, "pmid:00000001")["case_definition"] = "Oxford"
    data["links"] = [link(support="associated", sources=("pmid:00000001",))]
    assert rules(check(tmp_path, data)) == {"M5"}


def test_m5_proposed_may_rest_on_a_review_only(tmp_path):
    data = base()
    data["links"] = [link(support="proposed", sources=("doi:10.0000/fictional.5",))]
    assert check(tmp_path, data) == []


def test_m5_one_qualifying_study_among_weak_ones_is_enough(tmp_path):
    data = base()
    data["links"] = [link(support="directional", sources=("doi:10.0000/fictional.5", "pmid:00000002"))]
    assert check(tmp_path, data) == []


# --- V14: no TODO in reader-facing text -------------------------------------


def _todo_in_name(data):
    data["name"] = "Fictional hypothesis (TODO: verify name)"


def _todo_in_core_claim(data):
    data["core_claim"]["text"] += " TODO: verify"


def _todo_in_level_reason(data):
    data["level_reason"]["text"] += " todo: check"


def _todo_in_contested(data):
    data["contested"]["reason"]["text"] += " TODO"


def _todo_in_badge(data):
    data["badges"]["explains_pem"]["reason"]["text"] += " (TODO: verify)"


def _todo_in_subgroup(data):
    data["subgroups"][0]["text"] += " TODO: verify"


def _todo_in_early_signal(data):
    data["early_signals"][0]["text"] += " TODO: verify"


def _todo_in_link(data):
    data["links"] = [link(text="A fictional link. TODO: verify")]


def _todo_in_finding(data):
    data["studies"][0]["finding"] += " (TODO: verify)"


@pytest.mark.parametrize(
    ("edit", "path"),
    [
        (_todo_in_name, "name"),
        (_todo_in_core_claim, "core_claim.text"),
        (_todo_in_level_reason, "level_reason.text"),
        (_todo_in_contested, "contested.reason.text"),
        (_todo_in_badge, "badges.explains_pem.reason.text"),
        (_todo_in_subgroup, "subgroups[0].text"),
        (_todo_in_early_signal, "early_signals[0].text"),
        (_todo_in_link, "links[0].text"),
        (_todo_in_finding, "studies[0].finding"),
    ],
)
def test_v14_todo_in_reader_facing_text_is_an_error_naming_the_field(tmp_path, edit, path):
    data = base()
    edit(data)
    issues = [i for i in check(tmp_path, data) if i.rule == "V14"]
    assert [i.path for i in issues] == [path]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("group", "Ponting CP (affiliation TODO: verify)"),
        ("title", "A fictional title (TODO: verify)"),
        ("case_definition_quote", "Patients met the fictional criteria. TODO: verify"),
    ],
)
def test_v14_todo_in_other_free_text_study_fields_is_an_error(tmp_path, field, value):
    data = base()
    data["studies"][0][field] = value
    issues = [i for i in check(tmp_path, data) if i.rule == "V14"]
    assert [i.path for i in issues] == [f"studies[0].{field}"]


def test_v14_todo_in_a_yaml_comment_next_to_group_is_accepted(tmp_path):
    data = base()
    data["studies"][0]["group"] = "Fictional Group"
    path = write_card(tmp_path / "cards", data)
    path.write_text(
        path.read_text(encoding="utf-8").replace("group: Fictional Group", "group: Fictional Group  # TODO: verify", 1),
        encoding="utf-8",
    )
    assert cards.validate_card_file(path) == []


def test_v14_a_study_finding_with_todo_verify_fails(tmp_path):
    data = base()
    data["studies"][0]["finding"] = "A study of n=40 patients found a fictional difference (TODO: verify)."
    assert rules(check(tmp_path, data)) == {"V14"}


def test_v14_todo_only_in_yaml_comments_passes(tmp_path):
    path = write_card(tmp_path / "cards", base())
    path.write_text(
        path.read_text(encoding="utf-8").replace("level: 4\n", "level: 4  # TODO: verify the level reason\n", 1),
        encoding="utf-8",
    )
    assert cards.validate_card_file(path) == []


def test_v14_a_word_that_only_contains_todo_is_not_a_marker(tmp_path):
    data = base()
    data["core_claim"]["text"] += " The mastodon fictional result is unrelated."
    assert [i for i in check(tmp_path, data) if i.rule == "V14"] == []


# --- preprints (V15) ---------------------------------------------------------

PREPRINT_ID = "doi:10.99999/fictional.pre"


def with_preprint(data: dict, role: str = "early_signal") -> dict:
    """The fixture card plus one preprint study, cited in no text yet."""
    data["studies"].append(
        {
            "id": PREPRINT_ID,
            "title": "Fictional preprint of widget signalling",
            "year": 2026,
            "cohort": "me_cfs",
            "case_definition": "other",
            "case_definition_source": "abstract",
            "case_definition_quote": None,
            "design": "uncontrolled",
            "n_patients": 12,
            "n_controls": None,
            "measures_pem": False,
            "preregistered": None,
            "role": role,
            "direction": "mixed",
            "finding": "A preprint of n=12 patients reported a fictional change.",
            "preprint": True,
        }
    )
    return data


def v15(issues: list[Issue]) -> list[str]:
    return [i.path for i in issues if i.rule == "V15"]


def test_a_study_is_not_a_preprint_unless_it_says_so():
    assert {s.preprint for s in cards.load_card(VALID_CARD).studies} == {False}


def test_v15_a_preprint_early_signal_cited_only_in_early_signals_passes(tmp_path):
    data = with_preprint(base())
    data["early_signals"].append(
        {"text": "A fictional preprint reported a change, not yet replicated.", "sources": [PREPRINT_ID]}
    )
    assert check(tmp_path, data) == []


def test_v15_a_preprint_study_that_is_not_cited_anywhere_passes(tmp_path):
    assert check(tmp_path, with_preprint(base())) == []


@pytest.mark.parametrize("role", ["supports", "contradicts", "context"])
def test_v15_a_preprint_with_a_role_other_than_early_signal_fails_at_its_role(tmp_path, role):
    issues = check(tmp_path, with_preprint(base(), role=role))
    assert "studies[5].role" in v15(issues)


def test_v15_a_preprint_in_the_level_reason_fails_at_that_paragraph(tmp_path):
    data = with_preprint(base())
    data["level_reason"] = [
        data["level_reason"],
        {"text": "A fictional preprint also pointed this way.", "sources": [PREPRINT_ID]},
    ]
    assert v15(check(tmp_path, data)) == ["level_reason[1].sources[0]"]


def test_v15_a_preprint_in_a_single_level_reason_fails(tmp_path):
    data = with_preprint(base())
    data["level_reason"]["sources"].append(PREPRINT_ID)
    assert v15(check(tmp_path, data)) == ["level_reason.sources[2]"]


def test_v15_a_preprint_in_the_contested_reason_fails(tmp_path):
    data = with_preprint(base())
    data["contested"]["reason"]["sources"].append(PREPRINT_ID)
    assert v15(check(tmp_path, data)) == ["contested.reason.sources[1]"]


def test_v15_a_preprint_in_the_diagnostic_marker_reason_fails(tmp_path):
    data = with_preprint(base())
    data["badges"]["diagnostic_marker"]["reason"]["sources"].append(PREPRINT_ID)
    assert v15(check(tmp_path, data)) == ["badges.diagnostic_marker.reason.sources[1]"]


def test_v15_a_preprint_in_the_explains_pem_reason_fails(tmp_path):
    data = with_preprint(base())
    data["badges"]["explains_pem"]["reason"]["sources"].append(PREPRINT_ID)
    assert v15(check(tmp_path, data)) == ["badges.explains_pem.reason.sources[1]"]


def test_v15_a_preprint_in_a_link_fails_at_that_link(tmp_path):
    data = with_preprint(base())
    data["links"] = [link(sources=(PREPRINT_ID,))]
    assert v15(check(tmp_path, data)) == ["links[0].sources[0]"]


def test_v15_a_preprint_in_the_core_claim_fails(tmp_path):
    data = with_preprint(base())
    data["core_claim"]["sources"].append(PREPRINT_ID)
    assert v15(check(tmp_path, data)) == ["core_claim.sources[1]"]


def test_v15_a_preprint_in_a_subgroup_fails_at_that_subgroup(tmp_path):
    data = with_preprint(base())
    data["subgroups"].append({"text": "A fictional preprint reported a subgroup.", "sources": [PREPRINT_ID]})
    assert v15(check(tmp_path, data)) == ["subgroups[1].sources[0]"]


# --- errata (V17) ------------------------------------------------------------

ERRATUM_ID = "pmid:90000021"


def with_erratum(data: dict, **changes) -> dict:
    """The fixture card plus an erratum study that corrects its first study."""
    data["studies"].append(
        {
            "id": ERRATUM_ID,
            "title": "Fictional erratum to a made-up study",
            "year": 2026,
            "cohort": "me_cfs",
            "case_definition": "none",
            "case_definition_source": "fulltext",
            "case_definition_quote": None,
            "design": "other",
            "n_patients": None,
            "n_controls": None,
            "measures_pem": False,
            "preregistered": None,
            "role": "context",
            "direction": "not_applicable",
            "finding": "An erratum corrects a table value in the study.",
            "corrects": data["studies"][0]["id"],
            **changes,
        }
    )
    return data


def v17(issues: list[Issue]) -> list[str]:
    return [i.path for i in issues if i.rule == "V17"]


def test_a_study_corrects_nothing_unless_it_says_so():
    assert {s.corrects for s in cards.load_card(VALID_CARD).studies} == {None}


def test_v17_a_valid_erratum_study_passes(tmp_path):
    assert check(tmp_path, with_erratum(base())) == []


def test_v17_an_erratum_may_be_cited_in_text_that_is_not_a_level_contested_or_badge_reason(tmp_path):
    data = with_erratum(base())
    data["subgroups"].append({"text": "A fictional erratum corrected a value.", "sources": [ERRATUM_ID]})
    assert check(tmp_path, data) == []


def test_v17_an_unknown_target_fails(tmp_path):
    data = with_erratum(base(), corrects="pmid:90000099")
    assert v17(check(tmp_path, data)) == ["studies[5].corrects"]


def test_v17_a_study_correcting_itself_fails(tmp_path):
    data = with_erratum(base(), corrects=ERRATUM_ID)
    assert v17(check(tmp_path, data)) == ["studies[5].corrects"]


@pytest.mark.parametrize("change", [{"role": "supports"}, {"case_definition": "other"}])
def test_v17_wrong_role_or_case_definition_fails(tmp_path, change):
    data = with_erratum(base(), **change)
    assert "studies[5]" in v17(check(tmp_path, data))


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("level_reason", "level_reason.sources[2]"),
        ("contested", "contested.reason.sources[1]"),
        ("diagnostic_marker", "badges.diagnostic_marker.reason.sources[1]"),
        ("explains_pem", "badges.explains_pem.reason.sources[1]"),
    ],
)
def test_v17_an_erratum_as_a_level_contested_or_badge_reason_source_fails(tmp_path, path, expected):
    data = with_erratum(base())
    if path == "level_reason":
        data["level_reason"]["sources"].append(ERRATUM_ID)
    elif path == "contested":
        data["contested"]["reason"]["sources"].append(ERRATUM_ID)
    else:
        data["badges"][path]["reason"]["sources"].append(ERRATUM_ID)
    assert v17(check(tmp_path, data)) == [expected]
