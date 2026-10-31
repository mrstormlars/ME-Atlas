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
    get_fulltext,
    split_sentences,
)

FIXTURES = Path(__file__).parent / "fixtures" / "europepmc"
CARD_FIXTURE = Path(__file__).parent / "fixtures" / "cards" / "fictional-hypothesis.yaml"
EMAIL = "tester@example.org"
OA_PMID, OA_PMCID = "90000001", "PMC9000001"
CLOSED_PMID, CLOSED_PMCID = "90000002", "PMC9000002"
UNKNOWN_PMID = "90000003"


def fulltext_xml() -> str:
    return (FIXTURES / f"{OA_PMCID}.xml").read_text(encoding="utf-8")


def search_json(pmid: str, pmcid: str | None, open_access: str | None) -> str:
    if pmcid is None and open_access is None:
        return json.dumps({"hitCount": 0, "resultList": {"result": []}})
    hit = {
        "id": pmid,
        "source": "MED",
        "pmid": pmid,
        "title": "Fictional widget study",
        "isOpenAccess": open_access,
        "inEPMC": "Y" if pmcid else "N",
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
        }
        self.fulltexts = {OA_PMCID: fulltext_xml()}
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
