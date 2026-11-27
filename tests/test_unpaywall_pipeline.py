"""The pipeline `context` step with an open PDF copy: section 5 and 6, the loader's fallback, nothing else changed.

No network and no Unpaywall request: the finder is injected, the Europe PMC lookup is read from a fictional cache.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_europepmc import NOID_PMID, OA_PMCID, OA_PMID, _cache_lookup, fulltext_xml, search_json
from test_pipeline import NEW_PMID, SLUG, SPEC, Env
from test_unpaywall import MAIN_PDF, PDF_A, QUOTE_HYPHEN

from me_atlas import europepmc, pipeline, unpaywall
from me_atlas.pipeline import FullTextResult


@pytest.fixture
def ready(tmp_path: Path) -> Env:
    """Prepared and classified, as in test_pipeline."""
    env = Env(tmp_path)
    env.prepare()
    assert env.classify() == 0
    return env


@pytest.fixture
def no_email(monkeypatch):
    """No CONTACT_EMAIL anywhere, and any Europe PMC client construction fails the test."""
    monkeypatch.setattr(pipeline, "load_dotenv", lambda *a, **k: {})
    monkeypatch.delenv("CONTACT_EMAIL", raising=False)

    def no_client(*a, **k):
        raise AssertionError("a client was built, but no request may be made")

    monkeypatch.setattr(europepmc, "EuropePmcClient", no_client)


NOTE = "no open full text (Europe PMC: no open full text)"


def pdf_copy(pmid: str = NEW_PMID) -> unpaywall.CopyResult:
    text, cut = unpaywall.clean_pages(unpaywall.extract_pdf_pages(MAIN_PDF))
    meta = {
        "pdf_url": PDF_A,
        "landing_page_url": PDF_A + "#landing",
        "version": "acceptedVersion",
        "host_type": "repository",
        "reference_list_cut": cut,
    }
    return unpaywall.CopyResult(pmid, "ok", "10.9999/x", meta=meta, text=text)


def render(ready: Env, result: FullTextResult, **kw) -> str:
    assert ready.cli("context", SLUG, NEW_PMID, fulltext=lambda pmid, pmcid=None: result) == 0
    return (ready.run / "context" / f"{SLUG}-{NEW_PMID}.md").read_text(encoding="utf-8")


def test_context_with_a_pdf_names_the_source_the_version_and_the_confirmation_rule(ready: Env):
    text = render(ready, FullTextResult(None, NOTE, pdf=pdf_copy()))
    assert "## 5. Full text" in text and "No full text is available" not in text
    assert "an open PDF copy found through Unpaywall" in text
    assert "version: acceptedVersion" in text and "host type: repository" in text and f"PDF: {PDF_A}" in text
    assert "`case_definition_source: fulltext_pdf`" in text and "founder has confirmed" in text
    assert "No agent runs that command" in text
    assert "The reference list is left out." in text
    assert "[page 1] Fictional study of open copies" in text and "Not truncated" in text
    assert "The Fictional Reference Criteria" not in text  # the cut reference list is not shown


def test_context_with_a_pdf_lists_candidate_sentences_with_pages_that_match_the_text(ready: Env):
    copy = pdf_copy()
    text = render(ready, FullTextResult(None, NOTE, pdf=copy))
    section6 = text.split("## 6. Sentences found in the full text (verbatim)")[1]
    line = next(x for x in section6.splitlines() if x.startswith("- [page 1]") and QUOTE_HYPHEN in x)
    sentence = line.removeprefix("- [page 1] ")
    assert unpaywall.quote_in_pdf_text(sentence, copy.text)  # a copied sentence always passes the matcher
    assert unpaywall.quote_in_pdf_text(QUOTE_HYPHEN, copy.text)


def test_context_with_a_pdf_states_truncation_with_the_numbers(ready: Env):
    cfg = pipeline.Config(ready.run, ready.cards, ready.drafts, ready.cache, SPEC)
    loader = lambda pmid, pmcid=None: FullTextResult(None, NOTE, pdf=pdf_copy())  # noqa: E731
    text = pipeline.build_context(cfg, SLUG, NEW_PMID, loader, budget=40)
    assert "TRUNCATED: the first 40 of " in text and "Not truncated" not in text


@pytest.mark.parametrize("status", ["blocked", "no_oa_pdf", "no_contact_email", "title_not_found"])
def test_context_without_a_usable_pdf_is_the_plain_no_full_text_context(ready: Env, status):
    plain = render(ready, FullTextResult(None, NOTE))
    failed = render(ready, FullTextResult(None, NOTE, pdf=unpaywall.CopyResult(NEW_PMID, status)))
    assert failed == plain and "No full text is available" in plain and "Unpaywall" not in plain


def test_an_xml_full_text_is_never_replaced_by_a_pdf(ready: Env):
    xml = fulltext_loader_xml()
    text = render(ready, FullTextResult(xml, "Europe PMC open access, PMC9000101", pdf=pdf_copy()))
    assert "Unpaywall" not in text and "fulltext_pdf" not in text and "FULLTEXT-TAIL-MARKER" in text


def fulltext_loader_xml() -> bytes:
    return (Path(__file__).parent / "fixtures" / "pipeline" / "agent" / "fulltext-90000101.xml").read_bytes()


# --- the loader --------------------------------------------------------------------


class Finder:
    def __init__(self, result: unpaywall.CopyResult) -> None:
        self.result, self.calls = result, []

    def __call__(self, pmid: str) -> unpaywall.CopyResult:
        self.calls.append(pmid)
        return self.result


def test_loader_asks_for_a_pdf_only_when_europe_pmc_has_no_xml_and_the_context_asks(tmp_path, no_email):
    _cache_lookup(tmp_path, NOID_PMID, search_json(NOID_PMID, None, "N"))
    finder = Finder(pdf_copy(NOID_PMID))
    plain = pipeline.live_fulltext_loader(tmp_path, pdf_finder=finder)(NOID_PMID)
    assert plain.pdf is None and finder.calls == []  # not asked for: audit, redraft and correction stay as they are
    asked = pipeline.live_fulltext_loader(tmp_path, with_pdf=True, pdf_finder=finder)(NOID_PMID)
    assert asked.xml is None and asked.pdf is not None and asked.pdf.ok and finder.calls == [NOID_PMID]
    assert asked.note == plain.note  # the Europe PMC note is unchanged


def test_loader_drops_a_pdf_result_that_is_not_ok(tmp_path, no_email):
    _cache_lookup(tmp_path, NOID_PMID, search_json(NOID_PMID, None, "N"))
    finder = Finder(unpaywall.CopyResult(NOID_PMID, "no_doi"))
    result = pipeline.live_fulltext_loader(tmp_path, with_pdf=True, pdf_finder=finder)(NOID_PMID)
    assert result.xml is None and result.pdf is None and finder.calls == [NOID_PMID]


def test_loader_does_not_look_for_a_pdf_when_the_xml_is_there(tmp_path, no_email):
    cache = _cache_lookup(tmp_path, OA_PMID, search_json(OA_PMID, OA_PMCID, "Y"))
    cache.write(cache.fulltext_path(OA_PMCID), fulltext_xml().encode("utf-8"))
    finder = Finder(pdf_copy(OA_PMID))
    result = pipeline.live_fulltext_loader(tmp_path, with_pdf=True, pdf_finder=finder)(OA_PMID)
    assert result.xml is not None and result.pdf is None and finder.calls == []


def test_the_default_finder_makes_no_request_without_a_contact_email(tmp_path, no_email, monkeypatch):
    _cache_lookup(tmp_path, NOID_PMID, search_json(NOID_PMID, None, "N"))

    def no_client(*args, **kwargs):
        raise AssertionError("Unpaywall was asked, but no request may be made")

    monkeypatch.setattr(unpaywall.CopyFinder, "_lookup", no_client)
    result = pipeline.live_fulltext_loader(tmp_path, with_pdf=True)(NOID_PMID)
    assert result.xml is None and result.pdf is None  # no PubMed record, so no DOI: nothing to ask either
