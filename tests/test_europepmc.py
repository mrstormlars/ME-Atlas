"""Tests for the Europe PMC full-text client and the case-definition finder.

Fictional PMIDs, PMCIDs and articles; the HTTP layer is an ``httpx.MockTransport``; no network, no sleeping.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from me_atlas import europepmc
from me_atlas.europepmc import (
    EuropePmcCache,
    EuropePmcClient,
    EuropePmcError,
    find_case_definitions,
    find_case_definitions_in_page,
    get_fulltext,
    get_pmc_page,
    parse_lookup,
    pmc_page_text,
    split_sentences,
)

FIXTURES = Path(__file__).parent / "fixtures" / "europepmc"
CARD_FIXTURE = Path(__file__).parent / "fixtures" / "cards" / "fictional-hypothesis.yaml"
EMAIL = "tester@example.org"
OA_PMID, OA_PMCID = "90000001", "PMC9000001"
CLOSED_PMID, CLOSED_PMCID = "90000002", "PMC9000002"
UNKNOWN_PMID = "90000003"
FREE_PMID, FREE_PMCID = "90000004", "PMC9000004"  # free to read on PMC, not open access
WRONG_PMID, WRONG_PMCID = "90000005", "PMC9000005"  # its page says it is for another PMID
NOBODY_PMID, NOBODY_PMCID = "90000006", "PMC9000006"  # its page has no main article body


def fulltext_xml() -> str:
    return (FIXTURES / f"{OA_PMCID}.xml").read_text(encoding="utf-8")


def page_html() -> str:
    return (FIXTURES / f"{FREE_PMCID}.html").read_text(encoding="utf-8")


def search_json(pmid: str, pmcid: str | None, open_access: str | None, in_pmc: bool = False) -> str:
    if pmcid is None and open_access is None:
        return json.dumps({"hitCount": 0, "resultList": {"result": []}})
    hit = {
        "id": pmid,
        "source": "MED",
        "pmid": pmid,
        "title": "Fictional widget study",
        "isOpenAccess": open_access,
        "inEPMC": "Y" if pmcid else "N",
        "inPMC": "Y" if in_pmc else "N",
    }
    if pmcid:
        hit["pmcid"] = pmcid
    return json.dumps({"hitCount": 1, "resultList": {"result": [hit]}})


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class FakeEuropePmc:
    """Stands in for www.ebi.ac.uk/europepmc. Records every request with the fake clock's time."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.lookups = {
            OA_PMID: search_json(OA_PMID, OA_PMCID, "Y"),
            CLOSED_PMID: search_json(CLOSED_PMID, CLOSED_PMCID, "N"),
            UNKNOWN_PMID: search_json(UNKNOWN_PMID, None, None),
            FREE_PMID: search_json(FREE_PMID, FREE_PMCID, "N", in_pmc=True),
            WRONG_PMID: search_json(WRONG_PMID, WRONG_PMCID, "N", in_pmc=True),
            NOBODY_PMID: search_json(NOBODY_PMID, NOBODY_PMCID, "N", in_pmc=True),
        }
        self.fulltexts = {OA_PMCID: fulltext_xml()}
        page = page_html()
        self.pages = {
            FREE_PMCID: page,
            WRONG_PMCID: page,  # says citation_pmid 90000004
            NOBODY_PMCID: page.replace("main-article-body", "something-else"),
        }
        self.statuses: list[int] = []  # forced status codes, consumed one per request
        self.requests: list[tuple[httpx.Request, float]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request, self.clock.t))
        if self.statuses:
            return httpx.Response(self.statuses.pop(0))
        path = request.url.path
        if path.endswith("/search"):
            query = request.url.params["query"]
            pmid = query.removeprefix("EXT_ID:").split(" ")[0]
            body = self.lookups.get(pmid, search_json(pmid, None, None))
            return httpx.Response(200, text=body, headers={"content-type": "application/json"})
        if path.startswith("/articles/"):
            page = self.pages.get(path.split("/")[2])
            return httpx.Response(200, text=page) if page else httpx.Response(404)
        pmcid = path.split("/")[-2]
        if pmcid in self.fulltexts:
            return httpx.Response(200, text=self.fulltexts[pmcid])
        return httpx.Response(404)

    def client(self, **kwargs) -> EuropePmcClient:
        return EuropePmcClient(
            EMAIL,
            transport=httpx.MockTransport(self.handler),
            clock=self.clock,
            sleep=self.clock.sleep,
            **kwargs,
        )

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r, _ in self.requests]


# --- lookup and full text ---------------------------------------------------


def test_open_access_hit_downloads_and_caches_full_text(tmp_path):
    server = FakeEuropePmc()
    cache = EuropePmcCache(tmp_path)
    result = get_fulltext(server.client(), cache, OA_PMID)
    assert result.lookup.status == "open_access"
    assert result.lookup.pmcid == OA_PMCID
    assert result.requests_made == 2
    assert result.path == tmp_path / "europepmc" / f"{OA_PMCID}.xml"
    assert result.path.read_text(encoding="utf-8") == fulltext_xml()
    assert (tmp_path / "europepmc" / f"{OA_PMID}.json").is_file()
    assert server.paths[1].endswith(f"/{OA_PMCID}/fullTextXML")


def test_requests_identify_the_caller_with_the_contact_email(tmp_path):
    server = FakeEuropePmc()
    get_fulltext(server.client(), EuropePmcCache(tmp_path), OA_PMID)
    assert all(EMAIL in r.headers["user-agent"] for r, _ in server.requests)


def test_not_open_access_is_reported_and_no_full_text_is_requested(tmp_path):
    server = FakeEuropePmc()
    cache = EuropePmcCache(tmp_path)
    result = get_fulltext(server.client(), cache, CLOSED_PMID)
    assert result.lookup.status == "not_open_access"
    assert result.lookup.pmcid == CLOSED_PMCID
    assert result.path is None
    assert len(server.requests) == 1 and server.paths[0].endswith("/search")
    assert not (tmp_path / "europepmc" / f"{CLOSED_PMCID}.xml").exists()


def test_pmid_unknown_to_europe_pmc(tmp_path):
    server = FakeEuropePmc()
    result = get_fulltext(server.client(), EuropePmcCache(tmp_path), UNKNOWN_PMID)
    assert result.lookup.status == "not_found"
    assert result.lookup.pmcid is None
    assert result.path is None
    assert len(server.requests) == 1


def test_cached_result_is_not_requested_again(tmp_path):
    server = FakeEuropePmc()
    cache = EuropePmcCache(tmp_path)
    get_fulltext(server.client(), cache, OA_PMID)
    get_fulltext(server.client(), cache, CLOSED_PMID)
    before = len(server.requests)
    again = get_fulltext(server.client(), cache, OA_PMID)
    again_closed = get_fulltext(server.client(), cache, CLOSED_PMID)
    assert len(server.requests) == before
    assert again.requests_made == 0 and again.path is not None
    assert again_closed.lookup.status == "not_open_access" and again_closed.requests_made == 0


def test_refresh_requests_again(tmp_path):
    server = FakeEuropePmc()
    cache = EuropePmcCache(tmp_path)
    get_fulltext(server.client(), cache, OA_PMID)
    result = get_fulltext(server.client(), cache, OA_PMID, refresh=True)
    assert result.requests_made == 2
    assert len(server.requests) == 4


def test_429_then_200_succeeds(tmp_path):
    server = FakeEuropePmc()
    server.statuses.append(429)
    result = get_fulltext(server.client(), EuropePmcCache(tmp_path), CLOSED_PMID)
    assert result.lookup.status == "not_open_access"
    assert len(server.requests) == 2
    assert server.clock.sleeps == [1.0]


def test_repeated_500_fails_with_a_clear_error_and_caches_nothing(tmp_path):
    server = FakeEuropePmc()
    server.statuses.extend([500] * 10)
    with pytest.raises(EuropePmcError, match=r"search for pmid:90000001 failed after 3 attempts.*HTTP 500"):
        get_fulltext(server.client(max_retries=2), EuropePmcCache(tmp_path), OA_PMID)
    assert not (tmp_path / "europepmc").exists()


def test_other_client_error_is_not_retried(tmp_path):
    server = FakeEuropePmc()
    server.statuses.append(400)
    with pytest.raises(EuropePmcError, match=r"HTTP 400 .*not retried"):
        get_fulltext(server.client(), EuropePmcCache(tmp_path), OA_PMID)
    assert len(server.requests) == 1


def test_unreadable_search_response_is_an_error_and_is_not_cached(tmp_path):
    server = FakeEuropePmc()
    server.lookups[OA_PMID] = "<html>not json</html>"
    with pytest.raises(EuropePmcError, match="unreadable Europe PMC search response"):
        get_fulltext(server.client(), EuropePmcCache(tmp_path), OA_PMID)
    assert not (tmp_path / "europepmc" / f"{OA_PMID}.json").exists()


def test_open_access_record_without_full_text_is_an_error(tmp_path):
    server = FakeEuropePmc()
    server.fulltexts.clear()
    with pytest.raises(EuropePmcError, match="HTTP 404"):
        get_fulltext(server.client(), EuropePmcCache(tmp_path), OA_PMID)
    assert not (tmp_path / "europepmc" / f"{OA_PMCID}.xml").exists()


def test_rate_limit_is_three_requests_per_second(tmp_path):
    server = FakeEuropePmc()
    cache = EuropePmcCache(tmp_path)
    client = server.client()
    for pmid in (f"9100000{i}" for i in range(7)):
        get_fulltext(client, cache, pmid)
    times = [t for _, t in server.requests]
    assert len(times) == 7
    for i, start in enumerate(times):
        assert sum(1 for t in times if start <= t < start + 1.0) <= 3, f"more than 3 requests in the second from #{i}"
    assert times[3] - times[0] >= 1.0


# --- case-definition finder -------------------------------------------------


def article(*sections: tuple[str, str], body_text: str = "") -> str:
    """A minimal JATS article: ``sections`` are (title, paragraph) pairs; ``body_text`` is a loose paragraph."""
    secs = "".join(f"<sec><title>{title}</title><p>{text}</p></sec>" for title, text in sections)
    loose = f"<p>{body_text}</p>" if body_text else ""
    return f"<article><body>{loose}{secs}</body></article>"


def test_finds_a_fukuda_wording_in_the_methods_section():
    xml = article(
        ("Introduction", "Fictional background."),
        ("Methods", "Patients were recruited in 2001. All met the Fukuda criteria for fictional fatigue."),
    )
    found = find_case_definitions(xml)
    assert len(found) == 1
    assert found[0].section == "Methods"
    assert found[0].scope == "methods"
    assert found[0].sentence == "All met the Fukuda criteria for fictional fatigue."
    assert "Fukuda" in found[0].matched


def test_finds_a_canadian_consensus_wording_in_the_methods_section():
    xml = article(
        ("Methods", "Fictional participants fulfilled the Canadian Consensus Criteria. Blood was drawn at 9 am.")
    )
    found = find_case_definitions(xml)
    assert [c.sentence for c in found] == ["Fictional participants fulfilled the Canadian Consensus Criteria."]
    assert found[0].section == "Methods"


def test_finds_an_oxford_wording_in_the_methods_section():
    xml = article(
        ("Patients and methods", "Cases were selected using the Oxford case definition. Controls were healthy.")
    )
    found = find_case_definitions(xml)
    assert [c.sentence for c in found] == ["Cases were selected using the Oxford case definition."]
    assert found[0].section == "Patients and methods"
    assert found[0].scope == "methods"


def test_finds_a_holmes_wording():
    xml = article(("Methods", "Cases met the 1988 CDC definition proposed by Holmes and colleagues."))
    found = find_case_definitions(xml)
    assert len(found) == 1 and "Holmes" in found[0].matched


def test_returns_nothing_for_a_methods_section_without_a_case_definition():
    xml = article(
        ("Introduction", "Earlier fictional work used the Fukuda criteria."),
        ("Methods", "Blood was drawn at 9 am. Widget signalling was measured twice. Samples were frozen at -80 C."),
        ("Discussion", "The Canadian Consensus Criteria might give another result."),
    )
    assert find_case_definitions(xml) == []


def test_falls_back_to_the_body_when_there_is_no_methods_section():
    xml = article(
        ("Introduction", "Fictional background."),
        ("Cohort", "Patients fulfilled the International Consensus Criteria."),
    )
    found = find_case_definitions(xml)
    assert len(found) == 1
    assert found[0].scope == "body"
    assert found[0].section == "Cohort"
    assert found[0].sentence == "Patients fulfilled the International Consensus Criteria."


def test_fallback_also_reads_text_outside_any_section():
    found = find_case_definitions(article(body_text="Patients met the IOM 2015 criteria."))
    assert [(c.section, c.scope) for c in found] == [("body", "body")]


def test_methods_are_preferred_over_mentions_elsewhere():
    xml = article(
        ("Introduction", "The Oxford criteria are broad."),
        ("Methods", "Participants met the Fukuda criteria."),
    )
    assert [c.scope for c in find_case_definitions(xml)] == ["methods"]


def test_finder_returns_sentences_not_enum_values():
    xml = article(("Methods", "Participants met the Fukuda criteria."))
    candidate = find_case_definitions(xml)[0]
    assert set(vars(candidate)) == {"section", "scope", "sentence", "matched"}
    assert candidate.sentence in "Participants met the Fukuda criteria."


def test_finder_on_the_fixture_article_finds_only_the_methods_sentence():
    found = find_case_definitions(fulltext_xml())
    assert [c.sentence for c in found] == [
        "All met the Fukuda criteria (Fukuda et al., 1994) for fictional fatigue syndrome."
    ]
    assert found[0].section == "Materials and methods"


def test_article_without_a_body_gives_no_candidates():
    assert find_case_definitions("<article><front/></article>") == []


def test_unreadable_xml_is_an_error():
    with pytest.raises(EuropePmcError, match="unreadable full-text XML"):
        find_case_definitions("<article><body>")


def test_sentence_splitting_keeps_et_al_together():
    text = "Patients met the criteria of Fukuda et al. (1994) for fatigue. Controls were healthy."
    assert split_sentences(text) == [
        "Patients met the criteria of Fukuda et al. (1994) for fatigue.",
        "Controls were healthy.",
    ]


# --- command line -----------------------------------------------------------


def run_cli(argv, server, tmp_path, env=None):
    return europepmc.main(
        [*argv, "--cache-dir", str(tmp_path)],
        env={"CONTACT_EMAIL": EMAIL} if env is None else env,
        transport=httpx.MockTransport(server.handler),
        clock=server.clock,
        sleep=server.clock.sleep,
    )


def test_cli_without_contact_email_exits_nonzero_and_names_it(tmp_path, capsys):
    server = FakeEuropePmc()
    code = run_cli(["fulltext", OA_PMID], server, tmp_path, env={})
    assert code != 0
    assert "CONTACT_EMAIL" in capsys.readouterr().err
    assert server.requests == []


def test_cli_fulltext_reports_each_pmid(tmp_path, capsys):
    server = FakeEuropePmc()
    code = run_cli(["fulltext", OA_PMID, CLOSED_PMID, UNKNOWN_PMID], server, tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert f"pmid:{OA_PMID}  open access  {OA_PMCID}" in out
    assert f"pmid:{CLOSED_PMID}  no open full text  {CLOSED_PMCID}" in out
    assert f"pmid:{UNKNOWN_PMID}  not found in Europe PMC" in out


def test_cli_casedef_prints_the_verbatim_sentence_and_section(tmp_path, capsys):
    server = FakeEuropePmc()
    code = run_cli(["casedef", f"pmid:{OA_PMID}"], server, tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "1 candidate sentence(s)" in out
    sentence = "All met the Fukuda criteria (Fukuda et al., 1994) for fictional fatigue syndrome."
    assert f"[Materials and methods] {sentence}" in out


def test_cli_casedef_card_reads_the_pubmed_ids_of_a_card(tmp_path, capsys):
    server = FakeEuropePmc()
    code = run_cli(["casedef", "--card", str(CARD_FIXTURE)], server, tmp_path)
    captured = capsys.readouterr()
    assert code == 0
    searched = [r.url.params["query"] for r, _ in server.requests]
    assert searched == [f"EXT_ID:0000000{i} AND SRC:MED" for i in (1, 2, 3, 4)]
    assert "doi:10.0000/fictional.5" in captured.err  # skipped, and says so


def test_cli_a_failing_pmid_does_not_stop_the_others_but_sets_the_exit_code(tmp_path, capsys):
    server = FakeEuropePmc()
    server.lookups[CLOSED_PMID] = "not json"
    code = run_cli(["fulltext", CLOSED_PMID, OA_PMID], server, tmp_path)
    captured = capsys.readouterr()
    assert code == 1
    assert f"pmid:{CLOSED_PMID}  error" in captured.err
    assert f"pmid:{OA_PMID}  open access" in captured.out


def test_cli_needs_pmids_or_a_card(tmp_path):
    with pytest.raises(SystemExit):
        run_cli(["casedef"], FakeEuropePmc(), tmp_path)


def test_cli_rejects_a_non_numeric_pmid(tmp_path):
    with pytest.raises(SystemExit):
        run_cli(["fulltext", "abc"], FakeEuropePmc(), tmp_path)


# --- PMC article page (free to read, not open access) -----------------------


def page_cache_path(tmp_path, pmcid=FREE_PMCID):
    return tmp_path / "europepmc" / f"{pmcid}.html"


def make_card(tmp_path, ids=(FREE_PMID, WRONG_PMID, NOBODY_PMID, CLOSED_PMID)):
    """A copy of the fictional card fixture whose first four pmid: studies have the given ids."""
    text = CARD_FIXTURE.read_text(encoding="utf-8")
    for old, new in zip(("00000001", "00000002", "00000003", "00000004"), ids, strict=True):
        text = text.replace(f"pmid:{old}", f"pmid:{new}")
    path = tmp_path / "fictional-hypothesis.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_lookup_reads_the_in_pmc_flag():
    free = parse_lookup(FREE_PMID, search_json(FREE_PMID, FREE_PMCID, "N", in_pmc=True))
    assert free.in_pmc is True and free.status == "not_open_access"
    assert parse_lookup(CLOSED_PMID, search_json(CLOSED_PMID, CLOSED_PMCID, "N")).in_pmc is False


def test_a_good_page_is_fetched_once_cached_and_the_second_call_makes_no_request(tmp_path):
    server = FakeEuropePmc()
    cache = EuropePmcCache(tmp_path)
    first = get_pmc_page(server.client(), cache, FREE_PMID)
    assert first.outcome == "fetched" and first.requests_made == 2
    assert first.path == page_cache_path(tmp_path)
    assert server.paths[1] == f"/articles/{FREE_PMCID}/"
    assert "pmc.ncbi.nlm.nih.gov" in str(server.requests[1][0].url)
    before = len(server.requests)
    second = get_pmc_page(server.client(), cache, FREE_PMID)
    assert second.outcome == "cached" and second.requests_made == 0
    assert len(server.requests) == before
    third = get_pmc_page(server.client(), cache, FREE_PMID, refresh=True)
    assert third.outcome == "fetched" and len(server.requests) == before + 2


def test_page_requests_carry_the_contact_email_and_are_retried_on_the_fake_clock(tmp_path):
    server = FakeEuropePmc()
    get_pmc_page(server.client(), EuropePmcCache(tmp_path), FREE_PMID)
    for request, _ in server.requests:
        assert EMAIL in request.headers["user-agent"]
    cache = EuropePmcCache(tmp_path / "other")
    cache.write(cache.lookup_path(FREE_PMID), server.lookups[FREE_PMID].encode())
    server.statuses = [500]
    get_pmc_page(server.client(), cache, FREE_PMID)
    assert server.clock.sleeps


def test_open_access_record_fetches_no_page(tmp_path):
    server = FakeEuropePmc()
    result = get_pmc_page(server.client(), EuropePmcCache(tmp_path), OA_PMID)
    assert result.outcome == "open_access" and result.path is None
    assert server.paths == ["/europepmc/webservices/rest/search"]  # the lookup only


def test_record_not_in_pmc_or_without_pmcid_fetches_no_page(tmp_path):
    server = FakeEuropePmc()
    closed = get_pmc_page(server.client(), EuropePmcCache(tmp_path), CLOSED_PMID)
    unknown = get_pmc_page(server.client(), EuropePmcCache(tmp_path), UNKNOWN_PMID)
    assert closed.outcome == "not_in_pmc" and closed.path is None
    assert unknown.outcome == "no_pmcid" and unknown.path is None
    assert all(p.endswith("/search") for p in server.paths)


def test_a_page_for_another_pmid_is_not_cached(tmp_path):
    server = FakeEuropePmc()
    with pytest.raises(EuropePmcError, match="pmid:90000004, not pmid:90000005"):
        get_pmc_page(server.client(), EuropePmcCache(tmp_path), WRONG_PMID)
    assert not page_cache_path(tmp_path, WRONG_PMCID).exists()


def test_a_page_without_a_main_article_body_is_not_cached(tmp_path):
    server = FakeEuropePmc()
    server.pages[NOBODY_PMCID] = server.pages[NOBODY_PMCID].replace('content="90000004"', 'content="90000006"')
    with pytest.raises(EuropePmcError, match="no main article body"):
        get_pmc_page(server.client(), EuropePmcCache(tmp_path), NOBODY_PMID)
    assert not page_cache_path(tmp_path, NOBODY_PMCID).exists()


def test_a_page_without_citation_pmid_is_not_cached(tmp_path):
    server = FakeEuropePmc()
    server.pages[FREE_PMCID] = server.pages[FREE_PMCID].replace('name="citation_pmid"', 'name="other"')
    with pytest.raises(EuropePmcError, match="no citation_pmid"):
        get_pmc_page(server.client(), EuropePmcCache(tmp_path), FREE_PMID)
    assert not page_cache_path(tmp_path).exists()


def test_page_text_has_the_abstract_and_body_but_not_references_navigation_or_scripts():
    text = pmc_page_text(page_html())
    assert "31 fictional patients" in text  # abstract
    assert "62 fictional patients and 41 fictional controls" in text  # body
    assert "fictional fatigue1." in text  # footnote link flattens as in the XML path
    assert "Fictional table row 58" in text
    for left_out in (
        "Canadian Consensus",
        "999 patients",
        "4242",
        "5151",
        "6161",
        "Fictional navigation",
        "color: red",
    ):
        assert left_out not in text
    assert "  " not in text


def test_page_finder_reads_only_the_methods_sections():
    found = find_case_definitions_in_page(page_html())
    assert [(c.section, c.scope) for c in found] == [("Methods", "methods")]
    assert found[0].sentence.startswith("All fictional patients met the Fukuda criteria")
    # not the introduction's Oxford sentence, the abstract's "Participants:" or the reference list
    assert all("Oxford" not in c.sentence and "Canadian" not in c.sentence for c in found)


def test_page_finder_falls_back_to_the_body_without_a_methods_section():
    page = page_html().replace("Methods</h2>", "Fictional design</h2>").replace("Participants</h3>", "Cohort</h3>")
    found = find_case_definitions_in_page(page)
    assert found and all(c.scope == "body" for c in found)
    assert any("Oxford" in c.sentence for c in found)


def test_cli_pmcpage_stops_before_any_request_for_a_pmid_not_on_the_card(tmp_path, capsys):
    server = FakeEuropePmc()
    card = make_card(tmp_path)
    code = run_cli(["pmcpage", "--card", str(card), FREE_PMID, "90000009"], server, tmp_path)
    err = capsys.readouterr().err
    assert code == 1 and "pmid:90000009" in err and "Nothing was requested" in err
    assert server.requests == []
    assert not (tmp_path / "europepmc").exists()


def test_cli_pmcpage_requires_a_card(tmp_path):
    server = FakeEuropePmc()
    with pytest.raises(SystemExit):
        run_cli(["pmcpage", FREE_PMID], server, tmp_path)
    assert server.requests == []


def test_cli_pmcpage_reports_each_outcome_and_prints_candidates(tmp_path, capsys):
    server = FakeEuropePmc()
    card = make_card(tmp_path, ids=(FREE_PMID, CLOSED_PMID, OA_PMID, UNKNOWN_PMID))
    code = run_cli(["pmcpage", "--card", str(card), FREE_PMID, CLOSED_PMID, OA_PMID, UNKNOWN_PMID], server, tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert f"pmid:{FREE_PMID}  free to read on PMC (page fetched)  {FREE_PMCID}" in out
    assert "1 candidate sentence(s)" in out and "[Methods] All fictional patients met the Fukuda criteria" in out
    assert f"pmid:{CLOSED_PMID}  not in PubMed Central" in out
    assert f"pmid:{OA_PMID}  open access; use `fulltext`" in out
    assert f"pmid:{UNKNOWN_PMID}  no PMCID" in out
    assert [p for p in server.paths if p.startswith("/articles/")] == [f"/articles/{FREE_PMCID}/"]


def test_cli_pmcpage_a_bad_page_sets_the_exit_code_and_caches_nothing(tmp_path, capsys):
    server = FakeEuropePmc()
    card = make_card(tmp_path)
    code = run_cli(["pmcpage", "--card", str(card), WRONG_PMID, FREE_PMID], server, tmp_path)
    captured = capsys.readouterr()
    assert code == 1
    assert f"pmid:{WRONG_PMID}  error" in captured.err
    assert not page_cache_path(tmp_path, WRONG_PMCID).exists()
    assert page_cache_path(tmp_path).is_file()
