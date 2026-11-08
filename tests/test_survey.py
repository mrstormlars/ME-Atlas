"""Tests for the survey of the cached literature: themes, pairs, the theme file and record-candidates.

Fictional records (``tests/fixtures/survey/``, PMIDs 91000001-91000010) and fictional cards built in ``tmp_path``;
no network, no AI.
"""

import ast
import datetime as dt
import json
import re
import shutil
import socket
from pathlib import Path

import pytest
import yaml

from me_atlas import survey

HERE = Path(__file__).parent
RECORDS = HERE / "fixtures" / "survey"
CARD_FIXTURE = HERE / "fixtures" / "cards" / "fictional-hypothesis.yaml"

# card-alpha cites 91000001, 91000002, 91000004 and 99999999 (not in the cache)
ID_MAP = {"00000001": "91000001", "00000002": "91000002", "00000003": "99999999", "00000004": "91000004"}


def card_data(slug: str, links=(), id_map: dict[str, str] | None = None) -> dict:
    text = CARD_FIXTURE.read_text(encoding="utf-8")
    for old, new in (id_map or ID_MAP).items():
        text = text.replace(f"pmid:{old}", f"pmid:{new}")
    data = yaml.safe_load(text)
    data["slug"] = slug
    data["name"] = slug.replace("-", " ").title()
    data["layer"] = "mechanism"
    data["links"] = [
        {"to": to, "support": "proposed", "text": "A fictional link.", "sources": ["pmid:91000001"]} for to in links
    ]
    return data


def put(directory: Path, data: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{data['slug']}.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


THEMES = {
    "card-alpha": {"mesh": ["Alpha Pathway"], "terms": []},
    "card-beta": {"mesh": ["Beta Signalling"], "terms": ["widget"]},
    "card-gamma": {"mesh": ["Gamma Axis"], "terms": []},
    "card-zeta": {"mesh": ["Zeta Claimed"]},
}
LINKS = {
    "card-alpha": ["card-beta"],  # alpha -> beta: "a->b"
    "card-gamma": ["card-beta", "card-zeta"],  # gamma -> beta: "b->a" for (beta, gamma); gamma <-> zeta: "both"
    "card-zeta": ["card-gamma"],
}


@pytest.fixture
def world(tmp_path: Path) -> Path:
    """cards/, drafts/, a cache of the fictional records, a stoplist and a theme file, all in tmp_path."""
    for slug in ("card-alpha", "card-beta"):
        put(tmp_path / "cards", card_data(slug, LINKS.get(slug, ())))
    for slug in ("card-gamma", "card-zeta"):
        put(tmp_path / "drafts", card_data(slug, LINKS.get(slug, ())))
    shutil.copytree(RECORDS, tmp_path / "cache")
    (tmp_path / "stoplist.txt").write_text("# generic headings\n\nhumans\n", encoding="utf-8")
    (tmp_path / "themes.yaml").write_text(yaml.safe_dump(THEMES), encoding="utf-8")
    return tmp_path


def run(world: Path, *argv: str, out: Path | None = None) -> int:
    common = ["--cards", str(world / "cards"), "--drafts", str(world / "drafts")]
    cmd = argv[0]
    extra: list[str] = []
    if cmd in ("themes", "pairs"):
        extra = ["--cache", str(world / "cache"), "--out", str(out or world / "out")]
    if cmd in ("themes", "pairs", "check-themes"):
        extra += ["--themes", str(world / "themes.yaml"), "--stoplist", str(world / "stoplist.txt")]
    if cmd == "themes":
        extra += ["--domains", str(world / "domains.yaml")]
    if cmd == "record-candidates":
        extra += ["--candidates", str(world / "candidates.md")]
    return survey.main([cmd, *common, *extra, *argv[1:]])


def table(capsys) -> list[list[str]]:
    return [line.split() for line in capsys.readouterr().out.splitlines()]


# ---------------------------------------------------------------------------
# themes (T1-T3)
# ---------------------------------------------------------------------------


def census(out: str) -> dict[str, dict]:
    """The printed census by heading: records, reviews, letters, originals, recent, newest, domain, near."""
    rows = {}
    for line in out.splitlines()[1:]:
        t = line.split()
        rows[" ".join(t[8:])] = {
            "records": int(t[0]),
            "reviews": int(t[1]),
            "letters": int(t[2]),
            "originals": int(t[3]),
            "recent": int(t[4]),
            "newest": t[5],
            "domain": t[6],
            "near": t[7],
        }
    return rows


def test_themes_drops_stoplisted_and_claimed_headings_and_keeps_the_rest_with_its_count(world, capsys):
    assert run(world, "themes") == 0
    out = capsys.readouterr().out
    for dropped in ("Humans", "Zeta Claimed", "Alpha Pathway", "Gamma Axis", "Beta Signalling"):
        assert dropped not in out  # stoplist (case-insensitive) or claimed by a card
    rows = census(out)
    assert list(rows) == ["Delta Unrelated"]
    assert rows["Delta Unrelated"]["records"] == 4
    data = json.loads((world / "out" / "themes.json").read_text(encoding="utf-8"))
    assert [(h["heading"], h["records"], h["pmids"]) for h in data["headings"]] == [
        ("Delta Unrelated", 4, ["91000007", "91000008", "91000012", "91000013"])
    ]


def test_themes_counts_split_and_order_without_a_theme_file(world, capsys):
    (world / "themes.yaml").unlink()
    assert run(world, "themes") == 0  # no theme file: nothing is claimed
    captured = capsys.readouterr()
    assert "no theme file" in captured.err
    rows = census(captured.out)
    # originals descending, then heading name (replaces the order by records)
    assert list(rows) == ["Gamma Axis", "Alpha Pathway", "Beta Signalling", "Delta Unrelated", "Zeta Claimed"]
    data = {h["heading"]: h for h in json.loads((world / "out" / "themes.json").read_text("utf-8"))["headings"]}
    alpha = data["Alpha Pathway"]
    assert (alpha["records"], alpha["reviews"], alpha["letters_comments_case_reports"], alpha["newest_year"]) == (
        5,
        2,
        1,
        2025,
    )
    assert alpha["pmids"] == ["91000001", "91000002", "91000003", "91000004", "91000009"]
    gamma = data["Gamma Axis"]
    assert (gamma["records"], gamma["reviews"], gamma["letters_comments_case_reports"], gamma["newest_year"]) == (
        5,
        1,
        1,
        2023,
    )
    beta = data["Beta Signalling"]
    assert (beta["reviews"], beta["letters_comments_case_reports"], beta["newest_year"]) == (0, 0, 2021)


def test_originals_exclude_reviews_meta_analyses_editorials_letters_and_case_reports(world, capsys):
    (world / "themes.yaml").unlink()
    run(world, "themes")
    data = {h["heading"]: h for h in json.loads((world / "out" / "themes.json").read_text("utf-8"))["headings"]}
    # Delta: 91000007 and 91000008 are original; 91000012 is a meta-analysis and 91000013 an editorial.
    assert data["Delta Unrelated"]["records"] == 4 and data["Delta Unrelated"]["originals"] == 2
    # Alpha: 1 and 4 are original; 2 and 9 reviews, 3 a letter. Gamma: 6, 10 and 11; 2 review, 5 case report.
    assert data["Alpha Pathway"]["originals"] == 2 and data["Gamma Axis"]["originals"] == 3
    assert data["Zeta Claimed"]["originals"] == 1
    assert next(iter(census(capsys.readouterr().out))) == "Gamma Axis"  # most originals first


def test_originals_recent_counts_from_the_module_year(world, capsys, monkeypatch):
    (world / "themes.yaml").unlink()
    run(world, "themes")
    rows = census(capsys.readouterr().out)
    assert rows["Alpha Pathway"]["recent"] == 2 and rows["Delta Unrelated"]["recent"] == 2  # 2016 and later
    monkeypatch.setattr(survey, "RECENT_FROM_YEAR", 2020)
    run(world, "themes")
    rows = census(capsys.readouterr().out)
    assert rows["Alpha Pathway"]["recent"] == 1  # 2021 counts, 2019 does not
    assert rows["Delta Unrelated"]["recent"] == 1  # 2020 counts, 2018 does not
    data = json.loads((world / "out" / "themes.json").read_text(encoding="utf-8"))
    assert data["recent_from_year"] == 2020
    assert {h["heading"]: h["originals_recent"] for h in data["headings"]}["Alpha Pathway"] == 1


# ---------------------------------------------------------------------------
# themes --suggest (T4)
# ---------------------------------------------------------------------------


def test_suggest_lists_headings_of_cited_records_and_names_the_uncached_id(world, capsys):
    assert run(world, "themes", "--suggest", "card-alpha") == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    counts = {line.split(maxsplit=1)[1].replace("  (stoplist)", ""): int(line.split()[0]) for line in lines[1:]}
    # 91000001 (Humans, Alpha, Beta), 91000002 (Humans, Alpha, Gamma), 91000004 (Alpha, Beta)
    assert counts == {"Alpha Pathway": 3, "Beta Signalling": 2, "Humans": 2, "Gamma Axis": 1}
    assert lines[1].endswith("Alpha Pathway")  # most first
    assert "pmid:99999999 is not in the cache" in captured.err


def test_suggest_unknown_slug_fails(world, capsys):
    assert run(world, "themes", "--suggest", "no-such-card") == 1
    assert "no-such-card" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# themes --context (T5)
# ---------------------------------------------------------------------------


def context_text(world: Path, name: str) -> str:
    return (world / "out" / "context" / f"{name}.md").read_text(encoding="utf-8")


def test_context_orders_reviews_first_then_newest_original_then_title_only(world):
    assert run(world, "themes", "--context", "Alpha Pathway") == 0
    text = context_text(world, "alpha-pathway")
    order = [text.index(f"pmid:{p}") for p in ("91000009", "91000002", "91000001", "91000003", "91000004")]
    assert order == sorted(order)
    assert "Left out: 0" in text
    # The letter and the record without an abstract are listed by title only: no "Abstract:" block for them.
    assert text.count("Abstract:") == 3
    assert "- pmid:91000003 (2024) Fictional letter about the alpha pathway." in text
    assert "no abstract" in text.split("pmid:91000004")[1].splitlines()[0]
    for field_ in ("publication types:", "MeSH headings:", "year: 2021"):
        assert field_ in text


def test_context_respects_the_limit_and_says_what_was_left_out(world):
    assert run(world, "themes", "--context", "Alpha Pathway", "--limit", "2") == 0
    text = context_text(world, "alpha-pathway")
    assert "Shown: 2" in text
    assert "Left out: 3 matching record(s)" in text
    assert "pmid:91000009" in text and "pmid:91000002" in text
    assert "pmid:91000001" not in text


def test_context_respects_the_character_budget(world, monkeypatch):
    monkeypatch.setattr(survey, "SURVEY_CHAR_BUDGET", 700)
    assert run(world, "themes", "--context", "Alpha Pathway") == 0
    text = context_text(world, "alpha-pathway")
    shown = int(text.split("Shown: ")[1].split(".")[0])
    left = int(text.split("Left out: ")[1].split(" ")[0])
    assert 1 <= shown < 5
    assert shown + left == 5
    assert "budget 700 characters" in text


def test_context_unknown_heading_fails_with_a_message(world, capsys):
    assert run(world, "themes", "--context", "No Such Heading") == 1
    assert "No Such Heading" in capsys.readouterr().err
    assert not (world / "out" / "context").exists()


# ---------------------------------------------------------------------------
# Theme file (F1, F2)
# ---------------------------------------------------------------------------


def write_themes(world: Path, data) -> None:
    (world / "themes.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_check_themes_accepts_the_valid_file(world, capsys):
    assert run(world, "check-themes") == 0
    assert "OK: 4 cards" in capsys.readouterr().out


def test_unknown_slug_is_an_error(world, capsys):
    write_themes(world, {**THEMES, "card-nowhere": {"mesh": ["Alpha Pathway"]}})
    assert run(world, "check-themes") == 1
    assert "card-nowhere" in capsys.readouterr().err


def test_card_without_an_entry_is_an_error(world, capsys):
    write_themes(world, {k: v for k, v in THEMES.items() if k != "card-zeta"})
    assert run(world, "check-themes") == 1
    assert "card-zeta" in capsys.readouterr().err


def test_empty_mesh_is_an_error(world, capsys):
    write_themes(world, {**THEMES, "card-alpha": {"mesh": [], "terms": ["alpha"]}})
    assert run(world, "check-themes") == 1
    assert "card-alpha.mesh" in capsys.readouterr().err


def test_seven_mesh_headings_is_an_error(world, capsys):
    write_themes(world, {**THEMES, "card-alpha": {"mesh": [f"Heading {i}" for i in range(7)]}})
    assert run(world, "check-themes") == 1
    assert "1 to 6" in capsys.readouterr().err


def test_five_terms_is_an_error(world, capsys):
    write_themes(world, {**THEMES, "card-alpha": {"mesh": ["Alpha Pathway"], "terms": list("abcde")}})
    assert run(world, "check-themes") == 1
    assert "at most 4" in capsys.readouterr().err


@pytest.mark.parametrize("bad", [{"mesh": ["Alpha Pathway", " "]}, {"mesh": ["Alpha Pathway"], "terms": [""]}])
def test_empty_strings_are_an_error(world, capsys, bad):
    write_themes(world, {**THEMES, "card-alpha": bad})
    assert run(world, "check-themes") == 1
    assert "non-empty string" in capsys.readouterr().err


def test_unknown_key_in_an_entry_is_an_error(world, capsys):
    write_themes(world, {**THEMES, "card-alpha": {"mesh": ["Alpha Pathway"], "mash": []}})
    assert run(world, "check-themes") == 1
    assert "mash" in capsys.readouterr().err


def test_heading_claimed_by_two_cards_is_a_warning_naming_both(world, capsys):
    write_themes(world, {**THEMES, "card-gamma": {"mesh": ["Gamma Axis", "alpha pathway"]}})
    assert run(world, "check-themes") == 0
    err = capsys.readouterr().err
    assert "warning" in err and "card-alpha" in err and "card-gamma" in err


def test_stoplist_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / "s.txt"
    path.write_text("# comment\n\n  Humans  \n#Other\nCountry X\n", encoding="utf-8")
    assert survey.load_stoplist(path) == {"humans", "country x"}


# ---------------------------------------------------------------------------
# pairs (P1-P4)
# ---------------------------------------------------------------------------


def rec(pmid: str):
    return next(r for r in survey.load_records(RECORDS)[0] if r.pmid == pmid)


def test_matches_by_mesh_heading():
    m = survey.Matcher(survey.CardTheme(("Alpha Pathway",), ()))
    assert m.matches(rec("91000001"))
    assert not m.matches(rec("91000007"))


def test_matches_by_term_in_abstract_case_insensitively():
    m = survey.Matcher(survey.CardTheme(("Nothing Here",), ("widget",)))
    assert m.matches(rec("91000010"))  # "Widget level" in the abstract


def test_a_term_inside_a_longer_word_does_not_match():
    m = survey.Matcher(survey.CardTheme(("Nothing Here",), ("widget",)))
    assert not m.matches(rec("91000008"))  # "subwidgets and widgetry"


def pair_rows(capsys) -> dict[tuple[str, str], list[str]]:
    rows = {}
    for cols in table(capsys)[1:]:
        # core, originals, reviews, newest, link, "a", "/", "b", then the label if any
        rows[(cols[5], cols[7])] = [*cols[:5], " ".join(cols[8:])]
    return rows


def test_pairs_counts_and_link_status(world, capsys):
    assert run(world, "pairs") == 0
    rows = pair_rows(capsys)
    assert len(rows) == 6
    assert rows[("card-alpha", "card-beta")] == ["1", "2", "0", "2021", "a->b", ""]  # 91000001, 91000004 (core)
    assert rows[("card-beta", "card-gamma")] == ["1", "2", "0", "2020", "b->a", ""]  # 91000010, 91000011 (core)
    assert rows[("card-gamma", "card-zeta")] == ["0", "1", "0", "2022", "both", "mentions only"]  # 91000006
    assert rows[("card-alpha", "card-gamma")] == ["0", "0", "1", "2023", "none", ""]  # the review 91000002
    assert rows[("card-alpha", "card-zeta")] == ["0", "0", "0", "-", "none", ""]


def test_pairs_are_sorted_by_core_then_originals_then_slugs(world, capsys):
    run(world, "pairs")
    order = [(c[5], c[7]) for c in table(capsys)[1:]]
    assert order == [
        ("card-alpha", "card-beta"),
        ("card-beta", "card-gamma"),
        ("card-gamma", "card-zeta"),  # core 0 but one original: after both pairs with a core match
        ("card-alpha", "card-gamma"),
        ("card-alpha", "card-zeta"),
        ("card-beta", "card-zeta"),
    ]


def test_a_core_match_removes_the_mentions_only_label(world, capsys):
    write_themes(world, {**THEMES, "card-zeta": {"mesh": ["Zeta Claimed", "Gamma Axis"]}})
    run(world, "pairs")
    rows = pair_rows(capsys)
    # 91000011 has Gamma Axis as major topic, so zeta (via Gamma Axis) and gamma both core-match it
    assert rows[("card-gamma", "card-zeta")][0] == "1"
    assert rows[("card-gamma", "card-zeta")][5] == ""  # no "mentions only" label when a core match exists


def test_a_match_through_non_major_mesh_counts_as_originals_not_core(world, capsys):
    run(world, "pairs")
    rows = pair_rows(capsys)
    # 91000001 has Alpha and Beta as ordinary headings; only 91000004 has both as major topics
    assert rows[("card-alpha", "card-beta")][:2] == ["1", "2"]
    data = json.loads((world / "out" / "pairs.json").read_text(encoding="utf-8"))
    pair = next(p for p in data if (p["a"], p["b"]) == ("card-alpha", "card-beta"))
    assert pair["pmids"]["core"] == ["91000004"] and pair["pmids"]["originals"] == ["91000001", "91000004"]
    assert pair["core"] == 1 and pair["label"] is None
    zeta = next(p for p in data if (p["a"], p["b"]) == ("card-gamma", "card-zeta"))
    assert zeta["core"] == 0 and zeta["label"] == "mentions only" and zeta["pmids"]["core"] == []


def test_a_title_term_counts_toward_core_and_an_abstract_term_does_not(world):
    run(world, "pairs")
    data = json.loads((world / "out" / "pairs.json").read_text(encoding="utf-8"))
    pair = next(p for p in data if (p["a"], p["b"]) == ("card-beta", "card-gamma"))
    # 91000011: "Widget" in the title and Gamma Axis as major topic: core. 91000010: "Widget" only in the abstract.
    assert pair["pmids"]["core"] == ["91000011"]
    assert pair["pmids"]["originals"] == ["91000010", "91000011"]


def test_core_term_rule_uses_the_title_and_whole_words():
    m = survey.Matcher(survey.CardTheme(("Nothing Here",), ("widget",)))
    assert m.core(rec("91000011"))  # title term
    assert not m.core(rec("91000010"))  # abstract only
    assert not m.core(rec("91000008"))  # "subwidgets" is not the word


def test_pairs_unlinked_prints_only_pairs_with_no_link(world, capsys):
    assert run(world, "pairs", "--unlinked") == 0
    rows = pair_rows(capsys)
    assert set(rows) == {("card-alpha", "card-gamma"), ("card-alpha", "card-zeta"), ("card-beta", "card-zeta")}
    assert {r[4] for r in rows.values()} == {"none"}
    written = json.loads((world / "out" / "pairs.json").read_text(encoding="utf-8"))
    assert len(written) == 3


def test_pairs_json_holds_the_pmids_per_pair(world):
    run(world, "pairs")
    data = json.loads((world / "out" / "pairs.json").read_text(encoding="utf-8"))
    pair = next(p for p in data if (p["a"], p["b"]) == ("card-alpha", "card-beta"))
    assert pair["pmids"]["originals"] == ["91000001", "91000004"]
    assert pair["link"] == "a->b"
    gamma = next(p for p in data if (p["a"], p["b"]) == ("card-alpha", "card-gamma"))
    assert gamma["pmids"]["reviews"] == ["91000002"] and gamma["pmids"]["originals"] == []


def test_a_draft_replaces_the_card_with_the_same_slug(world, capsys):
    put(world / "drafts", card_data("card-alpha", ["card-zeta"]))  # the draft has a different link
    run(world, "pairs")
    rows = pair_rows(capsys)
    assert rows[("card-alpha", "card-beta")][4] == "none"
    assert rows[("card-alpha", "card-zeta")][4] == "a->b"


def test_pairs_context_labels_which_card_cites_each_record(world):
    assert run(world, "pairs", "--context", "card-alpha", "card-beta") == 0
    text = (world / "out" / "context" / "card-alpha--card-beta.md").read_text(encoding="utf-8")
    # both fictional cards cite 91000001, 91000002 and 91000004 (same fixture); the context holds 91000001 and 91000004
    assert "cited by: card-alpha, card-beta" in text
    assert "pmid:91000001" in text and "pmid:91000004" in text
    assert "Existing link between the two cards: a->b" in text


def test_pairs_context_lists_core_records_first_and_marks_them(world):
    assert run(world, "pairs", "--context", "card-beta", "card-gamma") == 0
    text = (world / "out" / "context" / "card-beta--card-gamma.md").read_text(encoding="utf-8")
    # 91000010 is newer (2020) but only mentions; 91000011 (2017) is core and comes first
    assert text.index("pmid:91000011") < text.index("pmid:91000010")
    core_block = text.split("pmid:91000011")[1].split("## pmid:91000010")[0]
    assert "match: core" in core_block
    assert "match: core" not in text.split("## pmid:91000010")[1]
    assert text.count("match: core") == 1


def test_pairs_context_core_first_also_holds_under_a_limit(world):
    assert run(world, "pairs", "--context", "card-beta", "card-gamma", "--limit", "1") == 0
    text = (world / "out" / "context" / "card-beta--card-gamma.md").read_text(encoding="utf-8")
    assert "pmid:91000011" in text and "pmid:91000010" not in text and "Left out: 1" in text


def test_pairs_context_names_the_card_that_alone_cites_a_record_or_neither(world):
    other = {"00000001": "91000005", "00000002": "91000006", "00000003": "99999998", "00000004": "91000007"}
    put(world / "cards", card_data("card-beta", id_map=other))  # card-beta now cites none of the pair's records
    assert run(world, "pairs", "--context", "card-alpha", "card-beta") == 0
    path = world / "out" / "context" / "card-alpha--card-beta.md"
    text = path.read_text(encoding="utf-8")
    assert re.findall(r"cited by: ([a-z-]+)", text) == ["card-alpha", "card-alpha"]
    put(world / "cards", card_data("card-alpha", id_map=other))  # and now neither cites them
    assert run(world, "pairs", "--context", "card-alpha", "card-beta") == 0
    assert re.findall(r"cited by: ([a-z-]+)", path.read_text(encoding="utf-8")) == ["neither", "neither"]


def test_pairs_context_unknown_slug_fails(world, capsys):
    assert run(world, "pairs", "--context", "card-alpha", "card-nowhere") == 1
    assert "card-nowhere" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Cache, offline (G5, C2)
# ---------------------------------------------------------------------------


def test_an_unparsable_cached_file_is_counted_and_reported_not_fatal(world, capsys):
    (world / "cache" / "91999999.xml").write_text("<not-xml", encoding="utf-8")
    assert run(world, "themes") == 0
    err = capsys.readouterr().err
    assert "91999999.xml" in err and "1 cached file(s) could not be parsed" in err


def test_missing_cache_is_an_error(world, capsys):
    shutil.rmtree(world / "cache")
    assert run(world, "themes") == 1
    assert "cache directory not found" in capsys.readouterr().err


def test_no_subcommand_touches_the_network(world, monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx, "Client", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    assert run(world, "check-themes") == 0
    assert run(world, "themes") == 0
    assert run(world, "themes", "--context", "Alpha Pathway") == 0
    assert run(world, "pairs") == 0
    assert run(world, "pairs", "--context", "card-alpha", "card-beta") == 0
    ctx = world / "out" / "context" / "alpha-pathway.md"
    agent = world / "agent.json"
    agent.write_text(json.dumps({"heading": "Alpha Pathway", "candidates": []}), encoding="utf-8")
    assert run(world, "record-candidates", str(agent), "--context", str(ctx)) == 0


def test_survey_module_imports_no_http_client():
    tree = ast.parse((Path(survey.__file__)).read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"httpx", "requests", "urllib", "http", "socket", "anthropic"}
    assert "me_atlas.http" not in {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}


# ---------------------------------------------------------------------------
# Domains and near coverage (B1-B9)
# ---------------------------------------------------------------------------

RECORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID>{pmid}</PMID>
<Article><Journal><JournalIssue><PubDate><Year>{year}</Year></PubDate></JournalIssue><Title>J</Title></Journal>
<ArticleTitle>Fictional record {pmid}.</ArticleTitle>
<Abstract><AbstractText>Fictional abstract.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article>
<MeshHeadingList>{mesh}</MeshHeadingList>
</MedlineCitation></PubmedArticle></PubmedArticleSet>
"""


def add_records(world: Path, counts: dict[str, int], year: int = 2020) -> None:
    """Fictional original studies: ``counts`` maps a heading to the number of records that carry only it."""
    n = 92000000 + len(list((world / "cache").glob("92*.xml")))
    for heading, count in counts.items():
        for _ in range(count):
            n += 1
            mesh = f'<MeshHeading><DescriptorName MajorTopicYN="N">{heading}</DescriptorName></MeshHeading>'
            xml = RECORD_XML.format(pmid=n, year=year, mesh=mesh)
            (world / "cache" / f"{n}.xml").write_text(xml, encoding="utf-8")


def write_domains(world: Path, data) -> None:
    (world / "domains.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


DOMAINS = {
    "immune": {"label": "Immune system", "survey": True, "headings": ["Epsilon One", "Epsilon Two", "Epsilon Three"]},
    "nervous_system": {"label": "Nervous system", "survey": True, "headings": ["Epsilon Four"]},
    "treatment": {"label": "Treatment", "survey": False, "headings": ["Delta Unrelated", "Epsilon Five"]},
}


def test_domains_file_loads_in_order(world):
    write_domains(world, DOMAINS)
    domains = survey.load_domains(world / "domains.yaml", set(), set())
    assert [d.key for d in domains] == ["immune", "nervous_system", "treatment"]
    assert [d.survey for d in domains] == [True, True, False]


@pytest.mark.parametrize(
    ("label", "domains", "needle"),
    [
        (
            "heading in two domains",
            {**DOMAINS, "treatment": {"label": "T", "survey": False, "headings": ["epsilon one"]}},
            "epsilon one",
        ),
        ("unknown key", {**DOMAINS, "immune": {**DOMAINS["immune"], "colour": "red"}}, "unknown key 'colour'"),
        (
            "heading in the stoplist",
            {**DOMAINS, "treatment": {"label": "T", "survey": False, "headings": ["Humans"]}},
            "Humans",
        ),
        (
            "heading claimed by a card",
            {**DOMAINS, "treatment": {"label": "T", "survey": False, "headings": ["Alpha Pathway"]}},
            "Alpha Pathway",
        ),
        ("survey is not a boolean", {"immune": {"label": "I", "survey": "yes", "headings": []}}, "survey"),
    ],
)
def test_a_bad_domain_file_exits_1_naming_the_problem(world, capsys, label, domains, needle):
    write_domains(world, domains)
    assert run(world, "themes") == 1, label
    assert needle in capsys.readouterr().err


def test_census_shows_domain_and_unassigned(world, capsys):
    add_records(world, {"Epsilon One": 1})
    write_domains(world, DOMAINS)
    run(world, "themes")
    rows = census(capsys.readouterr().out)
    assert rows["Epsilon One"]["domain"] == "immune"
    assert rows["Delta Unrelated"]["domain"] == "treatment"
    add_records(world, {"Epsilon Six": 1})
    run(world, "themes")
    assert census(capsys.readouterr().out)["Epsilon Six"]["domain"] == "unassigned"
    data = json.loads((world / "out" / "themes.json").read_text(encoding="utf-8"))
    assert {h["heading"]: h["domain"] for h in data["headings"]}["Epsilon Six"] == "unassigned"


def by_domain_output(world: Path, capsys, *extra: str) -> str:
    assert run(world, "themes", "--by-domain", *extra) == 0
    return capsys.readouterr().out


def test_by_domain_prints_k_headings_of_a_domain_with_more(world, capsys):
    # immune holds four headings here (Epsilon Four is moved in) with 4, 3, 2 and 1 original studies
    add_records(world, {"Epsilon One": 4, "Epsilon Two": 3, "Epsilon Three": 2, "Epsilon Four": 1})
    data = {
        **DOMAINS,
        "immune": {**DOMAINS["immune"], "headings": ["Epsilon One", "Epsilon Two", "Epsilon Three", "Epsilon Four"]},
    }
    del data["nervous_system"]
    write_domains(world, data)
    out = by_domain_output(world, capsys, "--per-domain", "3")
    assert "Epsilon One" in out and "Epsilon Two" in out and "Epsilon Three" in out
    assert "Epsilon Four" not in out  # the fourth, below the top 3
    assert "Epsilon Four" not in out.split("Not selected")[0]


def test_by_domain_default_is_three_and_k_can_change(world, capsys):
    add_records(world, {"Epsilon One": 4, "Epsilon Two": 3, "Epsilon Three": 2, "Epsilon Four": 1})
    write_domains(
        world,
        {
            "immune": {
                "label": "Immune",
                "survey": True,
                "headings": ["Epsilon One", "Epsilon Two", "Epsilon Three", "Epsilon Four"],
            }
        },
    )
    assert "Epsilon Three" in by_domain_output(world, capsys) and "Epsilon Four" not in by_domain_output(world, capsys)
    assert "Epsilon Four" in by_domain_output(world, capsys, "--per-domain", "4")


def test_by_domain_does_not_select_from_a_non_survey_domain(world, capsys):
    add_records(world, {"Epsilon One": 1, "Epsilon Five": 9})
    write_domains(world, DOMAINS)
    out = by_domain_output(world, capsys)
    selected, rest = out.split("Not selected")
    assert "Epsilon One" in selected and "Epsilon Five" not in selected and "Delta Unrelated" not in selected
    assert "treatment (Treatment): 2 headings in the census" in rest
    saved = json.loads((world / "out" / "themes.json").read_text(encoding="utf-8"))["selection"]
    assert saved == {"immune": ["Epsilon One"], "nervous_system": []}


def test_by_domain_lists_an_unassigned_heading_in_the_top_60(world, capsys):
    add_records(world, {"Epsilon One": 1, "Epsilon Six": 5})
    write_domains(world, DOMAINS)
    out = by_domain_output(world, capsys)
    unassigned = out.split("Unassigned headings among the top 60")[1]
    assert "Epsilon Six" in unassigned and "Epsilon One" not in unassigned


def test_by_domain_says_none_when_every_top_heading_has_a_domain(world, capsys):
    write_domains(world, DOMAINS)
    assert by_domain_output(world, capsys).rstrip().endswith("none")


def test_unassigned_heading_below_the_top_60_is_not_listed(world, capsys, monkeypatch):
    monkeypatch.setattr(survey, "TOP_N", 1)
    add_records(world, {"Epsilon One": 5, "Epsilon Six": 1})
    write_domains(world, DOMAINS)
    assert "Epsilon Six" not in by_domain_output(world, capsys)


def test_by_domain_without_a_domain_file_is_an_error(world, capsys):
    assert run(world, "themes", "--by-domain") == 1
    assert "domain file not found" in capsys.readouterr().err


# --- related / near -----------------------------------------------------------


def with_related(world: Path, **related) -> None:
    data = {slug: dict(entry) for slug, entry in THEMES.items()}
    for slug, headings in related.items():
        data[slug.replace("_", "-")]["related"] = headings
    write_themes(world, data)


def test_near_lists_every_card_that_names_the_heading_sorted(world, capsys):
    with_related(world, card_gamma=["Delta Unrelated"], card_alpha=["Delta Unrelated"])
    run(world, "themes")
    rows = census(capsys.readouterr().out)
    assert rows["Delta Unrelated"]["near"] == "card-alpha,card-gamma"  # the heading stays in the census
    data = json.loads((world / "out" / "themes.json").read_text(encoding="utf-8"))
    assert data["headings"][0]["near"] == ["card-alpha", "card-gamma"]


def test_a_heading_with_no_near_card_shows_a_dash(world, capsys):
    run(world, "themes")
    assert census(capsys.readouterr().out)["Delta Unrelated"]["near"] == "-"


def test_related_heading_in_a_cards_mesh_is_an_error(world, capsys):
    with_related(world, card_alpha=["Gamma Axis"])  # claimed by card-gamma
    assert run(world, "check-themes") == 1
    assert "Gamma Axis" in capsys.readouterr().err


def test_related_heading_in_the_stoplist_is_an_error(world, capsys):
    with_related(world, card_alpha=["Humans"])
    assert run(world, "check-themes") == 1
    assert "stoplist" in capsys.readouterr().err


def test_more_than_eight_related_headings_is_an_error(world, capsys):
    with_related(world, card_alpha=[f"Related {i}" for i in range(9)])
    assert run(world, "check-themes") == 1
    assert "at most 8" in capsys.readouterr().err


def test_eight_related_headings_is_accepted(world):
    with_related(world, card_alpha=[f"Related {i}" for i in range(8)])
    assert run(world, "check-themes") == 0


def test_context_for_a_near_heading_starts_with_the_near_cards(world):
    with_related(world, card_gamma=["Delta Unrelated"], card_alpha=["Delta Unrelated"])
    assert run(world, "themes", "--context", "Delta Unrelated") == 0
    text = context_text(world, "delta-unrelated")
    assert "## Near existing cards" in text
    block = text.split("## Near existing cards")[1].split("Matching records")[0]
    claim = "The fictional hypothesis proposes that widget signalling is altered in patients."
    assert f"- `card-alpha` (Card Alpha): {claim}" in block  # read from the card file in cards/
    assert f"- `card-gamma` (Card Gamma): {claim}" in block  # read from the draft in drafts/
    assert block.index("card-alpha") < block.index("card-gamma")
    assert text.index("## Near existing cards") < text.index("## pmid:")
    assert "fits_existing_card" in block


def test_context_without_near_cards_has_no_near_block(world):
    assert run(world, "themes", "--context", "Delta Unrelated") == 0
    assert "Near existing cards" not in context_text(world, "delta-unrelated")


def test_the_near_block_reads_a_draft_in_place_of_the_card(world):
    data = card_data("card-alpha")
    data["core_claim"]["text"] = "A draft claim that replaces the card claim."
    put(world / "drafts", data)
    with_related(world, card_gamma=["Delta Unrelated"], card_alpha=["Delta Unrelated"])
    run(world, "themes", "--context", "Delta Unrelated")
    assert "A draft claim that replaces the card claim." in context_text(world, "delta-unrelated")


def test_the_surveyor_agent_reads_the_near_block():
    text = (HERE.parent / ".claude" / "agents" / "hypothesis-surveyor.md").read_text(encoding="utf-8")
    assert "Near existing cards" in text and "fits_existing_card" in text


# ---------------------------------------------------------------------------
# record-candidates (A2, A3)
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx(world) -> Path:
    run(world, "themes", "--context", "Alpha Pathway")
    return world / "out" / "context" / "alpha-pathway.md"


def candidate(**over) -> dict:
    base = {
        "name": "Altered alpha pathway",
        "mechanism": "The alpha pathway is claimed to be altered in patients.",
        "fits_existing_card": None,
        "cohort_studies": [
            {"pmid": "91000001", "case_definition_in_abstract": "Fukuda", "n": 12, "finding": "A fictional finding."},
            {"pmid": "91000004", "case_definition_in_abstract": "unverified", "n": None, "finding": "Another one."},
        ],
        "reviews": ["91000002"],
        "meets_inclusion_rule_on_abstracts": True,
        "why": "91000001 carries the rule; the case definition of 91000004 is unknown.",
    }
    base.update(over)
    return base


def agent_file(world: Path, *cands: dict, name: str = "agent.json", **top) -> Path:
    path = world / name
    path.write_text(json.dumps({"heading": "Alpha Pathway", "candidates": list(cands), **top}), encoding="utf-8")
    return path


def record(world: Path, file: Path, ctx: Path) -> int:
    return run(world, "record-candidates", str(file), "--context", str(ctx))


def test_context_pmids_reads_full_and_title_only_entries(ctx):
    assert survey.context_pmids(ctx.read_text(encoding="utf-8")) == {
        "91000001",
        "91000002",
        "91000003",
        "91000004",
        "91000009",
    }


def test_record_candidates_writes_a_section_per_candidate(world, ctx):
    assert record(world, agent_file(world, candidate()), ctx) == 0
    text = (world / "candidates.md").read_text(encoding="utf-8")
    assert text.startswith("# Candidates\n")
    assert "\n## Altered alpha pathway\n" in text
    assert "- Source heading: Alpha Pathway" in text
    assert "- Records: 2 cohort studies, 1 reviews (of 5 records read)" in text
    assert "  - pmid:91000001: Fukuda, n=12. A fictional finding." in text
    assert "  - pmid:91000004: unverified, n not stated. Another one." in text
    assert "- Reviews: pmid:91000002" in text
    assert "- Meets inclusion rule on abstracts: yes" in text
    assert "- Status: candidate" in text and "- Date: " in text
    assert text.index("## Altered alpha pathway") < text.index("# Gaps on existing cards")


def test_record_candidates_is_idempotent(world, ctx):
    f = agent_file(world, candidate(), candidate(name="Gap on a card", fits_existing_card="card-beta"))
    assert record(world, f, ctx) == 0
    first = (world / "candidates.md").read_bytes()
    assert record(world, f, ctx) == 0
    assert (world / "candidates.md").read_bytes() == first


def test_a_fits_existing_card_candidate_goes_under_gaps(world, ctx):
    f = agent_file(world, candidate(name="Gap on a card", fits_existing_card="card-beta"))
    assert record(world, f, ctx) == 0
    text = (world / "candidates.md").read_text(encoding="utf-8")
    gaps = text.split("# Gaps on existing cards")[1]
    assert "- **Gap on a card**" in gaps and "Fits existing card: `card-beta`" in gaps
    assert "## Gap on a card" not in text


def test_a_hand_set_status_is_kept_on_update(world, ctx):
    f = agent_file(world, candidate(), candidate(name="Gap on a card", fits_existing_card="card-beta"))
    record(world, f, ctx)
    path = world / "candidates.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("- Status: candidate", "- Status: to draft", 1)  # the first one: the candidate section
    text = text.replace("  - Status: candidate", "  - Status: declined: not specific", 1)
    path.write_text(text, encoding="utf-8")
    changed = agent_file(world, candidate(mechanism="A reworded mechanism."), name="again.json")
    changed_gap = agent_file(
        world, candidate(name="Gap on a card", fits_existing_card="card-beta", why="New why."), name="again2.json"
    )
    assert record(world, changed, ctx) == 0 and record(world, changed_gap, ctx) == 0
    new = path.read_text(encoding="utf-8")
    assert "A reworded mechanism." in new and "New why." in new  # updated
    assert "- Status: to draft" in new and "  - Status: declined: not specific" in new  # kept
    assert new.count("## Altered alpha pathway") == 1


def test_update_keeps_other_entries_and_the_first_date(world, ctx):
    record(world, agent_file(world, candidate()), ctx)
    path = world / "candidates.md"
    today = dt.date.today().isoformat()
    path.write_text(
        path.read_text(encoding="utf-8").replace(f"- Date: {today}", "- Date: 2020-01-01", 1), encoding="utf-8"
    )
    other = agent_file(world, candidate(name="A second one"), name="b.json")
    assert record(world, other, ctx) == 0
    text = path.read_text(encoding="utf-8")
    assert text.index("## Altered alpha pathway") < text.index("## A second one")
    assert "- Date: 2020-01-01" in text


@pytest.mark.parametrize(
    ("label", "payload", "needle"),
    [
        (
            "unknown pmid in cohort_studies",
            candidate(
                cohort_studies=[{"pmid": "91555555", "case_definition_in_abstract": "CCC", "n": 5, "finding": "x"}]
            ),
            "91555555",
        ),
        ("unknown pmid in reviews", candidate(reviews=["91666666"]), "91666666"),
        ("unknown candidate key", {**candidate(), "extra": 1}, "unknown key 'extra'"),
        (
            "unknown study key",
            candidate(
                cohort_studies=[
                    {"pmid": "91000001", "case_definition_in_abstract": "CCC", "n": 5, "finding": "x", "p": 1}
                ]
            ),
            "unknown key 'p'",
        ),
        (
            "case definition not in the card format",
            candidate(
                cohort_studies=[{"pmid": "91000001", "case_definition_in_abstract": "Canadian", "n": 5, "finding": "x"}]
            ),
            "case_definition_in_abstract",
        ),
        ("fits_existing_card is not a slug", candidate(fits_existing_card="card-nowhere"), "card-nowhere"),
        ("banned word in name", candidate(name="A promising pathway"), "banned word 'promising'"),
        ("banned word in mechanism", candidate(mechanism="This could cure it."), "banned word 'cure'"),
        (
            "banned word in finding",
            candidate(
                cohort_studies=[
                    {"pmid": "91000001", "case_definition_in_abstract": "CCC", "n": 5, "finding": "A proven result."}
                ]
            ),
            "banned word 'proven'",
        ),
        ("banned word in why", candidate(why="Gives hope."), "banned word 'hope'"),
        ("missing key", {k: v for k, v in candidate().items() if k != "why"}, "missing key 'why'"),
    ],
)
def test_a_bad_agent_file_exits_1_and_writes_nothing(world, ctx, capsys, label, payload, needle):
    f = agent_file(world, payload)
    assert record(world, f, ctx) == 1, label
    assert needle in capsys.readouterr().err
    assert not (world / "candidates.md").exists()


def test_a_bad_agent_file_leaves_an_existing_candidates_file_untouched(world, ctx):
    record(world, agent_file(world, candidate()), ctx)
    before = (world / "candidates.md").read_bytes()
    bad = agent_file(world, candidate(name="Another"), candidate(reviews=["91666666"]), name="bad.json")
    assert record(world, bad, ctx) == 1
    assert (world / "candidates.md").read_bytes() == before


def test_unknown_top_level_key_is_an_error(world, ctx, capsys):
    assert record(world, agent_file(world, candidate(), note="x"), ctx) == 1
    assert "unknown key 'note'" in capsys.readouterr().err


def test_the_repository_candidates_file_has_the_two_sections_and_no_entries():
    text = (HERE.parent / "docs" / "pm" / "candidates.md").read_text(encoding="utf-8")
    assert text.startswith("# Candidates\n") and "\n# Gaps on existing cards\n" in text
    assert "\n## " not in text and "\n- **" not in text


def test_the_surveyor_agent_is_restricted_to_read_and_write_on_sonnet():
    head = (HERE.parent / ".claude" / "agents" / "hypothesis-surveyor.md").read_text(encoding="utf-8").split("---")[1]
    meta = yaml.safe_load(head)
    assert meta["model"] == "sonnet" and meta["tools"] == "Read, Write"
