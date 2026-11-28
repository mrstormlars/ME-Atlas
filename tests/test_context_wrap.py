"""Tests for the line wrapping of long texts in the agent contexts (``pipeline._wrapped``) and for the cache-only
loader of ``correct-plan`` and ``correct-audit-plan``.

Fictional records, texts and cards. No network, no LLM: a request of any kind fails the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_audit import (
    CITED,
    SLUG,
    audit_data,
    cfg_of,
    part_with,
    record,
    write_record,
)
from test_audit import env as env  # noqa: F401  (fixture)
from test_audit import ready as ready  # noqa: F401  (fixture)
from test_card_correction import CTX, LINK_FINDING, Corr, finding
from test_citations import add_fulltext, add_page, add_record
from test_pipeline import NEW_PMID, Env
from test_unpaywall_pipeline import NOTE, pdf_copy

from me_atlas import fulltext_scan, pipeline
from me_atlas.pipeline import CONTEXT_LINE_WIDTH, FullTextResult

WORDS = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"


def long_text(words: int, tag: str = "w") -> str:
    """A fictional text of single-spaced words with distinct tokens, well over the line width."""
    return " ".join(f"{tag}{i:05d}-{WORDS.split()[i % 12]}" for i in range(words))


def fold(text: str) -> str:
    return " ".join(text.split())


def jats(text: str) -> bytes:
    return (
        "<article><front><article-meta><title-group><article-title>T</article-title></title-group></article-meta>"
        f"</front><body><sec><title>Results</title><p>{text}</p></sec></body></article>"
    ).encode()


# --- _wrapped ------------------------------------------------------------------------------------------------


def test_wrapped_breaks_at_spaces_loses_nothing_and_keeps_every_line_within_the_width():
    text = long_text(900)
    assert len(text) > 3 * CONTEXT_LINE_WIDTH
    lines = pipeline._wrapped(text)
    assert len(lines) >= 4 and all(len(x) <= CONTEXT_LINE_WIDTH for x in lines)
    assert " ".join(lines) == text


def test_wrapped_of_an_empty_text_is_empty_and_of_a_short_text_one_line():
    assert pipeline._wrapped("") == []
    assert pipeline._wrapped("A short sentence.") == ["A short sentence."]


def test_wrapped_does_not_split_a_hyphen_or_a_long_token():
    token = "x" * 1500
    assert pipeline._wrapped(f"before {token} after") == ["before", token, "after"]
    hyphenated = "-".join(["abc"] * 400)
    assert pipeline._wrapped(hyphenated) == [hyphenated]


# --- the audit record -----------------------------------------------------------------------------------------


def record_lines(env: Env, study_id: str, loader, carrier: bool = True) -> list[str]:
    return pipeline._audit_record_lines(cfg_of(env), study_id, loader, carrier)


def xml_loader(xml: bytes):
    return lambda pmid, pmcid=None, **kw: FullTextResult(xml, "fictional cache, PMC9300001")


def no_xml(pmid, pmcid=None, **kw):
    return FullTextResult(None, "no XML")


def after_count(lines: list[str]) -> list[str]:
    """The wrapped text after the "Not truncated" or "TRUNCATED" line: up to the next blank line."""
    count = next(i for i, x in enumerate(lines) if x.startswith(("Not truncated", "TRUNCATED")))
    start = count + 2
    return lines[start : lines.index("", start)]


def test_an_xml_body_longer_than_three_widths_is_wrapped_and_joins_back_exactly(ready: Env):
    body = long_text(900)
    lines = record_lines(ready, CITED, xml_loader(jats(body)))
    assert all(len(x) <= CONTEXT_LINE_WIDTH for x in lines)
    text = pipeline.europepmc.article_text(jats(body))
    shown = after_count(lines)
    assert len(shown) >= 4 and " ".join(shown) == text
    assert f"Not truncated ({len(text)} characters)." in lines  # the count is of the unwrapped text


def test_a_pmc_page_body_longer_than_three_widths_is_wrapped_and_counted_unwrapped(ready: Env):
    add_page(ready.cache, "90000100", "PMC9300002", body=f"<p>{long_text(900, 'p')}</p>")
    lines = record_lines(ready, CITED, no_xml)
    assert all(len(x) <= CONTEXT_LINE_WIDTH for x in lines)
    page = pipeline._cached_page_text(cfg_of(ready), "PMC9300002")
    assert page is not None and len(page) > 3 * CONTEXT_LINE_WIDTH
    assert f"Not truncated ({len(page)} characters)." in lines
    shown = after_count(lines)
    assert len(shown) >= 4 and " ".join(shown) == page


def test_an_abstract_longer_than_the_width_is_wrapped_and_a_missing_one_keeps_its_placeholder(ready: Env, tmp_path):
    add_record(ready.cache, "90000199", abstract="Results: " + long_text(300, "a"))
    lines = record_lines(ready, "pmid:90000199", no_xml, carrier=False)
    start = lines.index("Abstract:") + 2
    shown = lines[start : lines.index("", start)]
    assert len(shown) >= 2 and all(len(x) <= CONTEXT_LINE_WIDTH for x in shown)
    assert " ".join(shown).startswith("Results: a00000-") or " ".join(shown).startswith("a00000-")
    add_record(ready.cache, "90000198", abstract=None)
    none = record_lines(ready, "pmid:90000198", no_xml, carrier=False)
    assert "(the record has no abstract)" in none


def test_a_body_of_one_overlong_token_gives_exactly_one_line_over_the_width_with_the_token_whole(ready: Env):
    token = "Q" * 1500
    lines = record_lines(ready, CITED, xml_loader(jats(token)))
    over = [x for x in lines if len(x) > CONTEXT_LINE_WIDTH]
    assert over == [token]


# --- quotes that cross a wrap point ---------------------------------------------------------------------------

SENTENCE = "Participants completed a fictional two-day exercise test and reported delayed symptoms."


def body_with_a_break_inside_the_sentence() -> tuple[bytes, str, list[str], int, int]:
    """A JATS body, its unwrapped text, its wrapped lines, the offset of ``SENTENCE`` and of the break."""
    for n in range(80, 200):
        xml = jats(f"{long_text(n)} {SENTENCE} the end.")
        text = pipeline.europepmc.article_text(xml)
        lines = pipeline._wrapped(text)
        at = text.index(SENTENCE)
        end = 0
        for line in lines[:-1]:
            end += len(line)
            if at < end < at + len(SENTENCE):
                return xml, text, lines, at, end
            end += 1
    raise AssertionError("no body found whose wrap falls inside the sentence")


def test_a_quote_across_a_wrap_point_is_accepted_with_a_space_or_a_line_break_and_a_false_one_is_rejected(
    ready: Env, monkeypatch, capsys
):
    xml, text, lines, at, cut = body_with_a_break_inside_the_sentence()
    assert not any(SENTENCE in line for line in lines)  # the wrap really splits it
    with_break = text[at:cut] + "\n" + text[cut + 1 : at + len(SENTENCE)]
    ready.apply("ops_propose_level.json")
    ready.put("review", "review_accept.json")
    monkeypatch.setattr(pipeline.citations.CacheReader, "fulltext", lambda self, pmid: text)
    assert ready.cli("audit-plan", SLUG, NEW_PMID, fulltext=xml_loader(xml)) == 0
    rendered = "\n".join(lines)
    for quote in (SENTENCE, with_break):
        write_record(ready, audit_data(parts=part_with(evidence=[{"source": CITED, "quote": quote}])))
        assert record(ready) == 0, capsys.readouterr().err
        assert fulltext_scan.quote_in_fulltext(quote, rendered)
    bad = "Participants completed a fictional three-day exercise test and reported delayed symptoms."
    write_record(ready, audit_data(parts=part_with(evidence=[{"source": CITED, "quote": bad}])))
    assert record(ready) == 1
    assert "is not found word for word in the cached record of " + CITED in capsys.readouterr().err
    assert not fulltext_scan.quote_in_fulltext(bad, rendered)


# --- build_context --------------------------------------------------------------------------------------------


def test_build_context_wraps_a_long_xml_text_and_counts_the_unwrapped_text(ready: Env):
    body = long_text(900)
    xml = jats(body)
    cfg = cfg_of(ready)
    text = pipeline.build_context(cfg, SLUG, NEW_PMID, xml_loader(xml))
    unwrapped = pipeline.europepmc.article_text(xml)
    assert f"Not truncated ({len(unwrapped)} characters)." in text
    section = text.split("## 5. Full text")[1].split("## 6.")[0]
    lines = section.splitlines()
    assert all(len(x) <= CONTEXT_LINE_WIDTH for x in lines)
    assert " ".join(after_count(lines)) == unwrapped
    assert "Source: fictional cache, PMC9300001. The reference list is left out." in lines


def test_build_context_cuts_at_the_budget_then_wraps(ready: Env):
    xml = jats(long_text(900))
    unwrapped = pipeline.europepmc.article_text(xml)
    text = pipeline.build_context(cfg_of(ready), SLUG, NEW_PMID, xml_loader(xml), budget=2500)
    note = f"TRUNCATED: the first 2500 of {len(unwrapped)} characters follow; the rest of the full text was left out."
    assert note in text
    section = text.split("## 5. Full text")[1].split("## 6.")[0]
    shown = after_count(section.splitlines())
    assert len(shown) == 3 and " ".join(shown) == unwrapped[:2500]


def test_build_context_wraps_each_pdf_page_and_keeps_the_markers_and_blank_lines(ready: Env):
    copy = pdf_copy()
    pages = ["Page one " + long_text(500, "a"), "Page two " + long_text(500, "b")]
    copy = type(copy)(copy.pmid, copy.status, copy.doi, meta=copy.meta, text="\f".join(pages))
    loader = lambda pmid, pmcid=None: FullTextResult(None, NOTE, pdf=copy)  # noqa: E731
    text = pipeline.build_context(cfg_of(ready), SLUG, NEW_PMID, loader)
    section = text.split("## 5. Full text")[1].split("## 6.")[0]
    lines = section.splitlines()
    assert all(len(x) <= CONTEXT_LINE_WIDTH for x in lines)
    first = next(i for i, x in enumerate(lines) if x.startswith("[page 1] "))
    second = next(i for i, x in enumerate(lines) if x.startswith("[page 2] "))
    assert lines[second - 1] == "" and second - first > 2
    assert " ".join(lines[first : second - 1]) == f"[page 1] {pages[0]}"
    assert " ".join(x for x in lines[second:] if x) == f"[page 2] {pages[1]}"
    joined = "\n\n".join(f"[page {n}] {p}" for n, p in enumerate(pages, start=1))
    assert f"Not truncated ({len(joined)} characters)." in text


def test_a_pdf_budget_cut_in_the_middle_of_a_page_still_wraps_that_page(ready: Env):
    copy = pdf_copy()
    pages = ["Page one " + long_text(500, "a"), "Page two " + long_text(500, "b")]
    copy = type(copy)(copy.pmid, copy.status, copy.doi, meta=copy.meta, text="\f".join(pages))
    loader = lambda pmid, pmcid=None: FullTextResult(None, NOTE, pdf=copy)  # noqa: E731
    text = pipeline.build_context(cfg_of(ready), SLUG, NEW_PMID, loader, budget=len(pages[0]) + 1500)
    section = text.split("## 5. Full text")[1].split("## 6.")[0]
    assert "TRUNCATED: the first " in section
    assert all(len(x) <= CONTEXT_LINE_WIDTH for x in section.splitlines())
    assert re.search(r"^\[page 2\] ", section, re.MULTILINE)


# --- the cache-only loader of correct-plan and correct-audit-plan ---------------------------------------------


@pytest.fixture
def no_http(monkeypatch):
    """Any HTTP request fails the test."""
    import httpx

    def boom(*a, **k):
        raise AssertionError("an HTTP request was made")

    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(httpx.Client, "request", boom)
    monkeypatch.setattr(pipeline, "load_dotenv", lambda *a, **k: {"CONTACT_EMAIL": "someone@example.org"})
    monkeypatch.setenv("CONTACT_EMAIL", "someone@example.org")


def run_without_loader(corr: Corr, command: str, *extra: str) -> int:
    """The command as the operator runs it: no injected full-text loader."""
    return pipeline.main(
        [command, SLUG, "--run-dir", str(corr.dir), *extra, *corr.env.dir_args], out=corr.env.out.append
    )


def test_correct_plan_and_correct_audit_plan_read_the_cache_only_and_match_the_live_loader_on_a_hit(
    tmp_path: Path, no_http, monkeypatch
):
    corr = Corr(Env(tmp_path), tmp_path)
    cache = corr.env.cache
    add_fulltext(cache, "90000100", "PMC9300100", (long_text(300, "x"),))  # an XML carrier
    add_record(cache, "90000104")
    add_page(cache, "90000104", "PMC9300104", body=f"<p>{long_text(300, 'p')}</p>")  # a PMC-page carrier
    decisive = finding([f"studies[{CTX}].finding", f"studies[{CTX}].group"], "decisive")
    corr.request()
    assert corr.run("correct-review-plan") == 0
    corr.pre([decisive, LINK_FINDING])
    assert corr.run("correct-record-review", "--pre") == 0
    plan = corr.dir / "correction-context" / f"{SLUG}.md"
    assert run_without_loader(corr, "correct-plan") == 0
    cached = plan.read_text(encoding="utf-8")
    assert "x00000-" in cached and "p00000-" in cached and pipeline.FULLTEXT_NOT_CACHED_NOTE not in cached
    monkeypatch.delenv("CONTACT_EMAIL")  # the live loader then reads the cache and makes no request either
    monkeypatch.setattr(pipeline, "load_dotenv", lambda *a, **k: {})
    live = pipeline.live_fulltext_loader(cache)
    assert (
        pipeline.main(
            ["correct-plan", SLUG, "--run-dir", str(corr.dir), *corr.env.dir_args],
            fulltext=live,
            out=corr.env.out.append,
        )
        == 0
    )
    assert plan.read_text(encoding="utf-8") == cached  # a cache hit: the same context as the live loader gives
    assert corr.apply() == 0
    corr.review()
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert run_without_loader(corr, "correct-audit-plan") == 0
    audit_context = corr.dir / "audit-context" / f"{SLUG}.md"
    first = audit_context.read_text(encoding="utf-8")
    assert "x00000-" in first and "p00000-" in first
    assert (
        pipeline.main(
            ["correct-audit-plan", SLUG, "--run-dir", str(corr.dir), *corr.env.dir_args],
            fulltext=live,
            out=corr.env.out.append,
        )
        == 0
    )
    assert audit_context.read_text(encoding="utf-8") == first


def test_an_uncached_carrier_gets_the_not_cached_note_instead_of_a_request(tmp_path: Path, no_http):
    corr = Corr(Env(tmp_path), tmp_path)
    corr.request()
    assert corr.run("correct-review-plan") == 0
    corr.pre()
    assert corr.run("correct-record-review", "--pre") == 0
    assert run_without_loader(corr, "correct-plan") == 0
    text = (corr.dir / "correction-context" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert pipeline.FULLTEXT_NOT_CACHED_NOTE in text
