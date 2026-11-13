"""Tests for the Europe PMC preprint search, record parser, DOI lookup and preprint full text.

Fictional records in tests/fixtures/europepmc (the shape of live responses checked on 2026-11-13); the HTTP layer
is an ``httpx.MockTransport``; no network, no sleeping.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest

from me_atlas import europepmc
from me_atlas.europepmc import (
    EuropePmcCache,
    EuropePmcClient,
    EuropePmcError,
    get_fulltext,
    get_preprint,
    parse_preprint,
    preprint_query,
    preprint_term_block,
    read_cached_preprint,
)
from me_atlas.pubmed import read_query

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "europepmc"
EMAIL = "tester@example.org"
SINCE, UNTIL = dt.date(2026, 8, 15), dt.date(2026, 11, 13)
MAIN_DOI = "10.99999/fictional.2026.001"
PUBLISHED_DOI = "10.99999/fictional.2026.002"
PMCID = "PMC9000010"
OA_XML = (FIXTURES / "PMC9000001.xml").read_text(encoding="utf-8")
PLACEHOLDER = "<article><body><p>The Full Text of this preprint is available as a PDF (204.8 KB).</p></body></article>"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def raw_records() -> list[dict]:
    return (
        fixture("preprint_page1.json")["resultList"]["result"] + fixture("preprint_page2.json")["resultList"]["result"]
    )


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class FakePpr:
    """Stands in for the Europe PMC search: two pages by cursor, a DOI search, and full text by PMC id."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.requests: list[httpx.Request] = []
        self.pages = {"*": "preprint_page1.json", "CURSOR2": "preprint_page2.json"}
        self.fulltexts: dict[str, str] = {}
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(500)
        if request.url.path.endswith("/search"):
            query = request.url.params["query"]
            if query.startswith("DOI:"):
                doi = query.split('"')[1]
                hits = [r for r in raw_records() if str(r.get("doi", "")).lower() == doi.lower()]
                body = {"hitCount": len(hits), "resultList": {"result": hits}}
            else:
                body = fixture(self.pages[request.url.params["cursorMark"]])
            return httpx.Response(200, json=body)
        pmcid = request.url.path.split("/")[-2]
        if pmcid in self.fulltexts:
            return httpx.Response(200, text=self.fulltexts[pmcid])
        return httpx.Response(404)

    def client(self) -> EuropePmcClient:
        return EuropePmcClient(
            EMAIL,
            transport=httpx.MockTransport(self.handler),
            clock=self.clock,
            sleep=self.clock.sleep,
            max_retries=1,
            backoff=0.0,
        )


# --- the record ------------------------------------------------------------


def test_a_preprint_record_carries_the_fields_later_steps_rely_on():
    record = parse_preprint(raw_records()[0])
    assert record.ppr_id == "PPR9000001"
    assert record.doi == MAIN_DOI
    assert record.id == f"doi:{MAIN_DOI}"
    assert record.title.startswith("A fictional preprint of widget signalling")
    assert "1994 Fukuda criteria" in (record.abstract or "")
    assert record.year == 2026
    assert record.first_index_date == "2026-10-20"
    assert record.server == "FictionRxiv"
    assert record.version_number == 1
    assert [(v.ppr_id, v.number) for v in record.versions] == [("PPR9000001", 1)]
    assert record.published == ()
    assert record.pmcid == PMCID  # the PPR id in fullTextIdList is not a PMC id


def test_a_record_without_a_pmc_id_has_none_even_though_fulltextidlist_names_the_ppr_id():
    record = parse_preprint(raw_records()[1])
    assert record.pmcid is None
    assert record.in_pmc is False


def test_the_published_version_is_the_preprint_of_link_to_a_med_record_with_its_note():
    record = parse_preprint(raw_records()[1])
    assert [(link.pmid, link.note) for link in record.published] == [("90000100", "CrossRef Pre-print loader")]


def test_a_record_without_a_doi_has_no_doi_and_no_study_id():
    record = parse_preprint(raw_records()[2])
    assert record.doi is None
    with pytest.raises(ValueError):
        _ = record.id


def test_the_version_list_names_every_version_with_its_number():
    record = parse_preprint(fixture("preprint_versions.json")["resultList"]["result"][0])
    assert [(v.ppr_id, v.number) for v in record.versions] == [("PPR9000004", 1), ("PPR9000005", 2)]


def test_a_record_that_is_not_a_preprint_is_refused():
    with pytest.raises(EuropePmcError):
        parse_preprint({"id": "90000001", "source": "MED", "pmid": "90000001"})


# --- the query -------------------------------------------------------------


def _quoted_terms(text: str, field: str) -> list[str]:
    import re

    return (
        re.findall(rf'{field}:"([^"]+)"', text) if field == "TITLE_ABS" else re.findall(rf'"([^"]+)"\[{field}\]', text)
    )


def test_the_preprint_terms_are_the_title_abstract_terms_of_block_one_of_the_pubmed_query():
    pubmed_block_one = read_query(REPO / "config" / "pubmed_query.txt").split(") OR (")[0]
    pubmed_terms = _quoted_terms(pubmed_block_one, "Title/Abstract")
    epmc_terms = _quoted_terms(preprint_term_block(REPO / "config" / "europepmc_preprint_query.txt"), "TITLE_ABS")
    assert epmc_terms == pubmed_terms
    assert len(epmc_terms) >= 5


def test_the_query_adds_the_preprint_source_and_the_first_index_date_range():
    query = preprint_query(SINCE, UNTIL, '(TITLE_ABS:"x")')
    assert query == '(TITLE_ABS:"x") AND SRC:PPR AND FIRST_IDATE:[2026-08-15 TO 2026-11-13]'


# --- the search ------------------------------------------------------------


def test_the_search_joins_the_pages_until_every_hit_is_read(tmp_path):
    server = FakePpr()
    found = server.client().search_preprints(SINCE, UNTIL, cache=EuropePmcCache(tmp_path))
    assert [r.ppr_id for r in found] == ["PPR9000001", "PPR9000002", "PPR9000003"]
    assert [r.url.params["cursorMark"] for r in server.requests] == ["*", "CURSOR2"]


def test_the_sent_query_has_the_source_filter_the_date_clause_and_the_core_result_type(tmp_path):
    server = FakePpr()
    server.client().search_preprints(SINCE, UNTIL)
    params = server.requests[0].url.params
    assert "AND SRC:PPR AND FIRST_IDATE:[2026-08-15 TO 2026-11-13]" in params["query"]
    assert 'TITLE_ABS:"myalgic encephalomyelitis"' in params["query"]
    assert params["resultType"] == "core"
    assert params["format"] == "json"
    assert EMAIL in server.requests[0].headers["user-agent"]


def test_every_raw_page_and_every_record_is_cached(tmp_path):
    server = FakePpr()
    server.client().search_preprints(SINCE, UNTIL, cache=EuropePmcCache(tmp_path))
    folder = tmp_path / "europepmc" / "preprints"
    assert sorted(p.name for p in folder.glob("search-*")) == [
        "search-2026-08-15_2026-11-13-1.json",
        "search-2026-08-15_2026-11-13-2.json",
    ]
    assert sorted(p.name for p in folder.glob("PPR*.json")) == ["PPR9000001.json", "PPR9000002.json", "PPR9000003.json"]
    assert json.loads((folder / "PPR9000001.json").read_text(encoding="utf-8"))["doi"] == MAIN_DOI
    assert json.loads((folder / "search-2026-08-15_2026-11-13-1.json").read_text(encoding="utf-8"))["hitCount"] == 3


def test_the_search_stops_when_the_next_cursor_repeats(tmp_path):
    server = FakePpr()
    page = fixture("preprint_versions.json")
    page["hitCount"] = 50  # more hits than the pages ever deliver
    page["nextCursorMark"] = "SAME"

    def handler(request: httpx.Request) -> httpx.Response:
        server.requests.append(request)
        return httpx.Response(200, json=page)

    client = EuropePmcClient(
        EMAIL, transport=httpx.MockTransport(handler), clock=server.clock, sleep=server.clock.sleep
    )
    found = client.search_preprints(SINCE, UNTIL)
    assert len(found) == 2  # the same two records on both pages, kept once
    assert [r.url.params["cursorMark"] for r in server.requests] == ["*", "SAME"]  # then "SAME" repeats: stop


def test_a_failed_page_raises_europepmc_error():
    server = FakePpr()
    server.fail = True
    with pytest.raises(EuropePmcError):
        server.client().search_preprints(SINCE, UNTIL)


# --- lookup by DOI and the command line -------------------------------------


def test_get_preprint_fetches_by_doi_caches_it_and_then_reads_the_cache(tmp_path):
    server = FakePpr()
    cache = EuropePmcCache(tmp_path)
    record = get_preprint(server.client(), cache, f"doi:{MAIN_DOI.upper()}")
    assert record is not None and record.ppr_id == "PPR9000001"
    assert server.requests[0].url.params["query"] == f'DOI:"{MAIN_DOI.upper()}" AND SRC:PPR'
    assert (tmp_path / "europepmc" / "preprints" / "PPR9000001.json").is_file()
    again = get_preprint(server.client(), cache, MAIN_DOI)
    assert again == record and len(server.requests) == 1
    assert read_cached_preprint(cache, MAIN_DOI.upper()) == record


def test_get_preprint_returns_none_for_an_unknown_doi_and_caches_nothing(tmp_path):
    server = FakePpr()
    cache = EuropePmcCache(tmp_path)
    assert get_preprint(server.client(), cache, "10.99999/nothing.here") is None
    assert not (tmp_path / "europepmc" / "preprints").exists()


def test_cli_preprint_without_contact_email_exits_2_and_makes_no_request(tmp_path, capsys):
    server = FakePpr()
    code = europepmc.main(
        ["preprint", MAIN_DOI, "--cache-dir", str(tmp_path)], env={}, transport=httpx.MockTransport(server.handler)
    )
    assert code == 2
    assert server.requests == []
    assert "CONTACT_EMAIL" in capsys.readouterr().err


def test_cli_preprint_fetches_and_caches_each_doi_and_reports_a_published_version(tmp_path, capsys):
    server = FakePpr()
    code = europepmc.main(
        ["preprint", MAIN_DOI, f"doi:{PUBLISHED_DOI}", "--cache-dir", str(tmp_path)],
        env={"CONTACT_EMAIL": EMAIL},
        transport=httpx.MockTransport(server.handler),
        clock=server.clock,
        sleep=server.clock.sleep,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "PPR9000001" in out and "PPR9000002" in out
    assert "published version: pmid:90000100 (CrossRef Pre-print loader)" in out
    assert len(list((tmp_path / "europepmc" / "preprints").glob("PPR*.json"))) == 2


def test_cli_preprint_exits_1_for_a_doi_europe_pmc_does_not_have(tmp_path, capsys):
    server = FakePpr()
    code = europepmc.main(
        ["preprint", "10.99999/nothing.here", "--cache-dir", str(tmp_path)],
        env={"CONTACT_EMAIL": EMAIL},
        transport=httpx.MockTransport(server.handler),
        clock=server.clock,
        sleep=server.clock.sleep,
    )
    assert code == 1
    assert "no preprint record" in capsys.readouterr().err


# --- preprint full text goes through get_fulltext -----------------------------


def _cached_main(tmp_path, server) -> tuple[EuropePmcCache, europepmc.PreprintRecord]:
    cache = EuropePmcCache(tmp_path)
    record = get_preprint(server.client(), cache, MAIN_DOI)
    assert record is not None
    server.requests.clear()
    return cache, record


def test_preprint_full_text_with_real_xml_is_open_access_and_cached_as_pmcid_xml(tmp_path):
    server = FakePpr()
    server.fulltexts[PMCID] = OA_XML
    cache, record = _cached_main(tmp_path, server)
    result = get_fulltext(server.client(), cache, None, preprint=record)
    assert result.status == "open_access"
    assert result.pmcid == PMCID
    assert result.path == tmp_path / "europepmc" / f"{PMCID}.xml"
    assert result.path.read_text(encoding="utf-8") == OA_XML
    assert [r.url.path for r in server.requests] == [f"/europepmc/webservices/rest/{PMCID}/fullTextXML"]


def test_preprint_full_text_that_is_a_pdf_placeholder_is_pdf_only_and_nothing_is_cached(tmp_path):
    server = FakePpr()
    server.fulltexts[PMCID] = PLACEHOLDER
    cache, record = _cached_main(tmp_path, server)
    result = get_fulltext(server.client(), cache, None, preprint=record)
    assert result.status == "pdf_only"
    assert result.path is None
    assert not (tmp_path / "europepmc" / f"{PMCID}.xml").exists()


def test_preprint_full_text_answered_with_404_is_pmc_no_xml(tmp_path):
    server = FakePpr()
    cache, record = _cached_main(tmp_path, server)
    result = get_fulltext(server.client(), cache, None, preprint=record)
    assert result.status == "pmc_no_xml"
    assert result.path is None


def test_a_preprint_without_a_pmc_id_is_not_open_access_and_nothing_is_requested(tmp_path):
    server = FakePpr()
    record = parse_preprint(raw_records()[1])
    result = get_fulltext(server.client(), EuropePmcCache(tmp_path), None, preprint=record)
    assert result.status == "not_open_access"
    assert server.requests == []


def test_get_fulltext_needs_a_pmid_or_a_preprint(tmp_path):
    with pytest.raises(ValueError):
        get_fulltext(FakePpr().client(), EuropePmcCache(tmp_path), None)


# --- two cached records with one DOI ------------------------------------------------------


def _two_records_one_doi(tmp_path) -> EuropePmcCache:
    cache = EuropePmcCache(tmp_path)
    first = raw_records()[0]
    second = {**first, "id": "PPR9000099", "doi": first["doi"].upper()}
    cache.write_preprint(first)
    cache.write_preprint(second)
    return cache


def test_a_doi_lookup_with_two_cached_records_raises_an_error_naming_both_ppr_ids(tmp_path):
    cache = _two_records_one_doi(tmp_path)
    for lookup in (
        lambda: read_cached_preprint(cache, MAIN_DOI),
        lambda: get_preprint(FakePpr().client(), cache, MAIN_DOI),
    ):
        with pytest.raises(EuropePmcError, match="PPR9000001 and PPR9000099"):
            lookup()


def test_a_search_by_doi_that_returns_two_records_raises_the_same_error(tmp_path):
    server = FakePpr()
    first = raw_records()[0]
    page = {"hitCount": 2, "resultList": {"result": [first, {**first, "id": "PPR9000099"}]}}
    client = EuropePmcClient(
        EMAIL,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=page)),
        clock=server.clock,
        sleep=server.clock.sleep,
    )
    with pytest.raises(EuropePmcError, match="PPR9000001 and PPR9000099"):
        get_preprint(client, EuropePmcCache(tmp_path), MAIN_DOI)
