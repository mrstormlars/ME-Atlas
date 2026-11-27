"""Tests for the founder's confirmations, the command line, C5 for ``fulltext_pdf`` and C14.

Helpers come from ``test_unpaywall``. Fictional data only; every request goes to an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml
from test_unpaywall import (
    DOI,
    EMAIL,
    MAIN_PDF,
    PDF_A,
    PMID,
    QUOTE_FOLLOW_UP,
    QUOTE_HYPHEN,
    QUOTE_LIGATURE,
    QUOTE_REFERENCE,
    TITLE,
    Clock,
    World,
    add_record,
    answer,
    loc,
    root,  # noqa: F401  (a fixture)
)

from me_atlas import citations, unpaywall
from me_atlas.unpaywall import UnpaywallCache


def entry(study: str = "pmid:1", quote: str = "A quote.", sha: str = "a" * 64) -> dict:
    return {"study": study, "field": "case_definition_quote", "quote": quote, "pdf_sha256": sha}


def test_is_confirmed_needs_same_study_quote_and_sha():
    entries = [entry()]
    assert unpaywall.is_confirmed(entries, "pmid:1", "A  quote.", "a" * 64)
    assert unpaywall.is_confirmed(entries, "pmid:1", "A quote.", None)  # PDF not cached: sha not compared
    assert not unpaywall.is_confirmed(entries, "pmid:2", "A quote.", "a" * 64)  # other study
    assert not unpaywall.is_confirmed(entries, "pmid:1", "A quote", "a" * 64)  # quote changed
    assert not unpaywall.is_confirmed(entries, "pmid:1", "A quote.", "b" * 64)  # other PDF
    assert not unpaywall.is_confirmed([], "pmid:1", "A quote.", None)


def test_append_confirmation_replaces_an_empty_list_and_never_touches_older_entries(tmp_path):
    path = tmp_path / "pdf-quotes.yaml"
    path.write_text("# header comment\n[]\n", encoding="utf-8")
    unpaywall.append_confirmation(path, entry("pmid:1"))
    first = path.read_text(encoding="utf-8")
    assert first.startswith("# header comment\n") and yaml.safe_load(first) == [entry("pmid:1")]
    unpaywall.append_confirmation(path, entry("pmid:2", "Another quote."))
    second = path.read_text(encoding="utf-8")
    assert second.startswith(first)  # the old text is untouched, the new entry is appended
    assert yaml.safe_load(second) == [entry("pmid:1"), entry("pmid:2", "Another quote.")]


def test_an_unreadable_confirmations_file_is_an_error(tmp_path):
    path = tmp_path / "pdf-quotes.yaml"
    path.write_text("{not: a list}\n", encoding="utf-8")
    with pytest.raises(unpaywall.UnpaywallError):
        unpaywall.load_confirmations(path)
    assert unpaywall.load_confirmations(tmp_path / "missing.yaml") == []


# --- cards, C5 and C14 ---------------------------------------------------------


def make_study(**over) -> dict:
    study = {
        "id": f"pmid:{PMID}",
        "title": TITLE,
        "year": 2021,
        "cohort": "me_cfs",
        "case_definition": "Fukuda",
        "case_definition_source": "fulltext_pdf",
        "case_definition_quote": QUOTE_HYPHEN,
        "design": "controlled",
        "n_patients": None,
        "n_controls": None,
        "measures_pem": False,
        "preregistered": None,
        "role": "context",
        "direction": "not_applicable",
        "finding": "A study found a fictional result.",
    }
    study.update(over)
    return study


def write_card(directory: Path, studies: list[dict], slug: str = "fictional-card") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    card = {
        "slug": slug,
        "name": "Fictional card",
        "core_claim": {"text": "A fictional sentence.", "sources": [studies[0]["id"]]},
        "level": 0,
        "level_reason": {"text": "Fictional: nothing yet.", "sources": []},
        "contested": None,
        "badges": {
            "diagnostic_marker": {"value": False, "reason": None},
            "explains_pem": {"value": False, "reason": None},
        },
        "subgroups": [],
        "working_on_it": [],
        "early_signals": [],
        "studies": studies,
        "last_checked": {"date": "2026-11-01", "by": "ai_pair"},
    }
    path = directory / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(card, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def cached(root) -> Path:  # noqa: F811
    """The record and a cached PDF copy (as ``fetch`` leaves them); returns the cache root."""
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, MAIN_PDF)
    assert world.finder(root).find(PMID).ok
    return root


def check(tmp_path: Path, cache_root: Path, study: dict, confirmations: Path | None = None):
    card = write_card(tmp_path / "drafts", [study])
    _, issues = citations.check_paths([card], cache_root, confirmations=confirmations or tmp_path / "none.yaml")
    return issues


def codes(issues, code: str):
    return [i for i in issues if i.code == code]


def confirmation_for(cache_root: Path, path: Path, quote: str = QUOTE_HYPHEN, sha: str | None = None) -> Path:
    meta = json.loads(UnpaywallCache(cache_root).meta_path(DOI).read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump([entry(f"pmid:{PMID}", quote, sha or meta["sha256"])]), encoding="utf-8")
    return path


def test_c5_fulltext_pdf_quote_in_the_cached_pdf_text_passes(tmp_path, cached):
    for quote in (QUOTE_HYPHEN, QUOTE_FOLLOW_UP, QUOTE_LIGATURE):
        assert codes(check(tmp_path, cached, make_study(case_definition_quote=quote)), "C5") == []


def test_c5_fulltext_pdf_quote_with_one_changed_word_fails(tmp_path, cached):
    study = make_study(case_definition_quote=QUOTE_FOLLOW_UP.replace("two", "ten"))
    issues = codes(check(tmp_path, cached, study), "C5")
    assert [i.level for i in issues] == ["ERROR"] and "PDF text" in issues[0].message


def test_c5_fulltext_pdf_quote_only_in_the_cut_reference_list_fails(tmp_path, cached):
    issues = codes(check(tmp_path, cached, make_study(case_definition_quote=QUOTE_REFERENCE)), "C5")
    assert [i.level for i in issues] == ["ERROR"]


def test_c5_fulltext_pdf_without_cached_pdf_names_the_fetch_command(tmp_path, root):  # noqa: F811
    issues = codes(check(tmp_path, root, make_study()), "C5")
    assert len(issues) == 1 and issues[0].level == "ERROR"
    assert f"uv run python -m me_atlas.unpaywall fetch --card <card> {PMID}" in issues[0].message


def test_c5_fulltext_pdf_for_a_record_without_a_doi_is_an_error(tmp_path):
    cache_root = tmp_path / "cache"
    add_record(cache_root, doi=None)
    issues = codes(check(tmp_path, cache_root, make_study()), "C5")
    assert len(issues) == 1 and "no DOI" in issues[0].message


def test_c14_a_confirmed_quote_passes(tmp_path, cached):
    path = confirmation_for(cached, tmp_path / "pdf-quotes.yaml")
    assert codes(check(tmp_path, cached, make_study(), path), "C14") == []


def test_c14_without_an_entry_fails_and_names_the_command(tmp_path, cached):
    issues = codes(check(tmp_path, cached, make_study()), "C14")
    assert len(issues) == 1 and issues[0].level == "ERROR" and "no founder confirmation" in issues[0].message
    assert f"unpaywall confirm --card <card> {PMID}" in issues[0].message


def test_c14_a_changed_quote_is_unconfirmed_again(tmp_path, cached):
    path = confirmation_for(cached, tmp_path / "pdf-quotes.yaml")
    issues = codes(check(tmp_path, cached, make_study(case_definition_quote=QUOTE_FOLLOW_UP), path), "C14")
    assert len(issues) == 1


def test_c14_a_different_pdf_is_unconfirmed_again(tmp_path, cached):
    path = confirmation_for(cached, tmp_path / "pdf-quotes.yaml", sha="f" * 64)
    issues = codes(check(tmp_path, cached, make_study(), path), "C14")
    assert len(issues) == 1 and "different PDF" in issues[0].message


def test_c14_an_unreadable_confirmations_file_is_an_error(tmp_path, cached):
    path = tmp_path / "pdf-quotes.yaml"
    path.write_text("[: not yaml", encoding="utf-8")
    assert len(codes(check(tmp_path, cached, make_study(), path), "C14")) == 1


def test_c14_does_not_apply_to_an_abstract_source(tmp_path, root):  # noqa: F811
    abstract = make_study(case_definition_source="abstract")
    assert codes(check(tmp_path, root, abstract), "C14") == []


# --- the command line ----------------------------------------------------------


def run_cli(world: World, *argv: str, env: dict | None = None) -> int:
    clock = Clock()
    return unpaywall.main(
        list(argv),
        env={"CONTACT_EMAIL": EMAIL} if env is None else env,
        transport=httpx.MockTransport(world.handler),
        clock=clock.now,
        sleep=clock.sleep,
        now=clock.now,
    )


def test_fetch_prints_one_line_per_study_with_version_and_host(tmp_path, root, capsys):  # noqa: F811
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, MAIN_PDF)
    card = write_card(tmp_path / "drafts", [make_study()])
    assert run_cli(world, "fetch", "--card", str(card), "--cache-dir", str(root)) == 0
    out = capsys.readouterr().out
    assert f"pmid:{PMID}" in out and "ok (fetched)" in out and "publishedVersion" in out and "publisher" in out
    assert EMAIL not in out


def test_a_pmid_not_on_the_card_is_refused_and_nothing_is_requested(tmp_path, root, capsys):  # noqa: F811
    world = World(answer(loc(PDF_A)))
    card = write_card(tmp_path / "drafts", [make_study()])
    assert run_cli(world, "fetch", "--card", str(card), "90009999", "--cache-dir", str(root)) == 1
    assert "not a pmid: study on" in capsys.readouterr().err and world.log == []


def test_fetch_without_an_email_exits_2_and_requests_nothing(tmp_path, root, capsys):  # noqa: F811
    world = World(answer(loc(PDF_A)))
    card = write_card(tmp_path / "drafts", [make_study()])
    assert run_cli(world, "fetch", "--card", str(card), "--cache-dir", str(root), env={}) == 2
    assert "no_contact_email" in capsys.readouterr().out and world.log == []


def test_casedef_prints_candidates_with_page_numbers_and_exclusion_marks(tmp_path, capsys):
    cache_root = tmp_path / "cache"
    add_record(cache_root)
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, MAIN_PDF)
    card = write_card(tmp_path / "drafts", [make_study()])
    assert run_cli(world, "casedef", "--card", str(card), "--cache-dir", str(cache_root)) == 0
    out = capsys.readouterr().out
    assert "[p. 1]" in out and "Fukuda" in out and "matched:" in out and "[exclusion]" not in out
    # a cached text with an exclusion sentence on page 2 is printed with the mark
    key = unpaywall.cache_key(DOI)
    text, _ = unpaywall.clean_pages(["Fictional page one.", "Patients with CFS were excluded from the cohort."])
    (cache_root / "unpaywall" / "pdf" / f"{key}.txt").write_text(text, encoding="utf-8")
    assert run_cli(World(), "casedef", "--card", str(card), "--cache-dir", str(cache_root)) == 0
    assert "[p. 2] [exclusion] Patients with CFS were excluded from the cohort." in capsys.readouterr().out


def test_pending_lists_an_unconfirmed_quote_and_is_empty_once_confirmed(tmp_path, cached, capsys):
    card = write_card(tmp_path / "drafts", [make_study()])
    confirmations = tmp_path / "pdf-quotes.yaml"
    confirmations.write_text("# header\n[]\n", encoding="utf-8")
    where = ["--cache-dir", str(cached), "--confirmations", str(confirmations)]
    assert run_cli(World(), "pending", "--card", str(card), *where) == 1
    out = capsys.readouterr().out
    assert f"pmid:{PMID}" in out and QUOTE_HYPHEN in out and "page: 1" in out
    assert f"pdf_url: {PDF_A}" in out and f"landing_page_url: {PDF_A}#landing" in out
    assert "version: publishedVersion" in out and "host_type: publisher" in out
    assert run_cli(World(), "confirm", "--card", str(card), PMID, *where) == 0
    capsys.readouterr()
    assert run_cli(World(), "pending", "--card", str(card), *where) == 0
    assert capsys.readouterr().out == ""


def test_pending_ignores_studies_with_other_sources(tmp_path, root, capsys):  # noqa: F811
    card = write_card(tmp_path / "drafts", [make_study(case_definition_source="abstract")])
    where = ["--cache-dir", str(root), "--confirmations", str(tmp_path / "x.yaml")]
    assert run_cli(World(), "pending", "--card", str(card), *where) == 0 and capsys.readouterr().out == ""


def test_confirm_appends_the_entry_with_every_field_and_is_idempotent(tmp_path, cached, capsys):
    card = write_card(tmp_path / "drafts", [make_study()])
    confirmations = tmp_path / "pdf-quotes.yaml"
    confirmations.write_text("# header\n[]\n", encoding="utf-8")
    argv = ["confirm", "--card", str(card), PMID, "--cache-dir", str(cached), "--confirmations", str(confirmations)]
    assert run_cli(World(), *argv) == 0
    [written] = yaml.safe_load(confirmations.read_text(encoding="utf-8"))
    meta = json.loads(UnpaywallCache(cached).meta_path(DOI).read_text(encoding="utf-8"))
    assert written == {
        "study": f"pmid:{PMID}",
        "field": "case_definition_quote",
        "quote": QUOTE_HYPHEN,
        "pdf_sha256": meta["sha256"],
        "pdf_url": PDF_A,
        "landing_page_url": PDF_A + "#landing",
        "version": "publishedVersion",
        "host_type": "publisher",
        "page": 1,
        "confirmed_by": "founder",
        "confirmed_on": "1970-01-01",
    }
    before = confirmations.read_text(encoding="utf-8")
    capsys.readouterr()
    assert run_cli(World(), *argv) == 0 and "already confirmed" in capsys.readouterr().out
    assert confirmations.read_text(encoding="utf-8") == before
    assert codes(check(tmp_path, cached, make_study(), confirmations), "C14") == []  # and the check now passes


def test_confirm_refuses_a_quote_that_is_not_in_the_cached_text(tmp_path, cached, capsys):
    card = write_card(tmp_path / "drafts", [make_study(case_definition_quote=QUOTE_REFERENCE)])
    confirmations = tmp_path / "pdf-quotes.yaml"
    argv = ["confirm", "--card", str(card), PMID, "--cache-dir", str(cached), "--confirmations", str(confirmations)]
    assert run_cli(World(), *argv) == 1
    assert "not found word for word" in capsys.readouterr().err and not confirmations.exists()


def test_confirm_refuses_another_source_and_a_missing_cached_pdf(tmp_path, root, capsys):  # noqa: F811
    confirmations = tmp_path / "pdf-quotes.yaml"
    abstract = write_card(tmp_path / "a", [make_study(case_definition_source="abstract")])
    where = ["--cache-dir", str(root), "--confirmations", str(confirmations)]
    assert run_cli(World(), "confirm", "--card", str(abstract), PMID, *where) == 1
    pdf_card = write_card(tmp_path / "b", [make_study()])
    assert run_cli(World(), "confirm", "--card", str(pdf_card), PMID, *where) == 1  # nothing cached
    assert "no cached PDF text" in capsys.readouterr().err and not confirmations.exists()


def _cached_text(cache_root: Path, pages: list[str]) -> None:
    text, _ = unpaywall.clean_pages(pages)
    (cache_root / "unpaywall" / "pdf" / f"{unpaywall.cache_key(DOI)}.txt").write_text(text, encoding="utf-8")


def test_casedef_survives_a_console_that_cannot_encode_the_text(tmp_path, cached, monkeypatch):
    import io
    import sys

    _cached_text(cached, ["Cases met the Fukuda criteria with a score ≥ 5 in the made-up clinic."])
    card = write_card(tmp_path / "drafts", [make_study()])
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    code = run_cli(World(), "casedef", "--card", str(card), "--cache-dir", str(cached))
    console.flush()
    assert code == 0
    assert b"score ? 5" in raw.getvalue()


def test_casedef_notes_a_missing_reference_cut_only_when_not_cut(tmp_path, cached, capsys):
    card = write_card(tmp_path / "drafts", [make_study()])
    meta_path = UnpaywallCache(cached).meta_path(DOI)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for cut, expected in ((True, False), (False, True)):
        meta["reference_list_cut"] = cut
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        assert run_cli(World(), "casedef", "--card", str(card), "--cache-dir", str(cached)) == 0
        out = capsys.readouterr().out
        assert ("note: no reference-list heading was found" in out) is expected
