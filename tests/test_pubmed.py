"""Tests for the PubMed fetch script. Fictional fixtures and a mocked HTTP layer; no network, no sleeping."""

from __future__ import annotations

import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter

from me_atlas import pubmed
from me_atlas.cards import StudyId
from me_atlas.pubmed import (
    ParseError,
    PubMedClient,
    PubMedError,
    RateLimiter,
    RawCache,
    Window,
    load_dotenv,
    parse_xml,
    read_query,
    retraction_term,
    run_fetch,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pubmed"
TODAY = dt.date(2026, 10, 31)
NOW = dt.datetime(2026, 10, 31, 12, 0, 0, tzinfo=dt.UTC)
ALL_FIXTURES = [f"9000000{i}" for i in range(1, 9)]


def fixture_text(pmid: str) -> str:
    return (FIXTURES / f"{pmid}.xml").read_text(encoding="utf-8")


def record(pmid: str):
    return parse_xml(fixture_text(pmid))


# --- fakes -----------------------------------------------------------------


class FakeClock:
    """A clock that only moves when sleep() is called, so tests never wait."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class FakePubMed:
    """Stands in for eutils.ncbi.nlm.nih.gov. Records every request with the fake clock's time."""

    def __init__(self, clock: FakeClock | None = None, articles: dict[str, str] | None = None):
        self.clock = clock or FakeClock()
        self.articles = articles if articles is not None else {p: fixture_text(p) for p in ALL_FIXTURES}
        self.window_ids = ["90000001", "90000002", "90000003"]
        self.retracted_ids = ["90000006"]
        self.search_fn: Callable[[dict[str, str]], list[str]] | None = None
        self.statuses: deque[int] = deque()  # forced status codes, consumed one per request
        self.extra_search: dict[str, object] = {}
        self.requests: list[tuple[str, dict[str, str], float]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        self.requests.append((endpoint, params, self.clock()))
        if self.statuses:
            return httpx.Response(self.statuses.popleft())
        if endpoint == "esearch.fcgi":
            if self.search_fn:
                ids = self.search_fn(params)
            elif "Retracted Publication" in params["term"]:
                ids = self.retracted_ids
            else:
                ids = self.window_ids
            body = {
                "esearchresult": {
                    "count": str(len(ids)),
                    "retmax": params.get("retmax"),
                    "idlist": ids[: int(params["retmax"])],
                    "querykey": "1",
                    "webenv": "FAKE_WEBENV",
                    **self.extra_search,
                }
            }
            return httpx.Response(200, json=body)
        if endpoint == "efetch.fcgi":
            root = ET.Element("PubmedArticleSet")
            for pmid in params["id"].split(","):
                if pmid in self.articles:
                    root.extend(ET.fromstring(self.articles[pmid]).findall("PubmedArticle"))
            return httpx.Response(200, content=ET.tostring(root, encoding="utf-8"))
        return httpx.Response(404)

    def of(self, endpoint: str) -> list[dict[str, str]]:
        return [p for e, p, _ in self.requests if e == endpoint]

    def times(self) -> list[float]:
        return [t for _, _, t in self.requests]

    def client(self, api_key: str | None = None, **kwargs) -> PubMedClient:
        return PubMedClient(
            "tester@example.org",
            api_key,
            transport=httpx.MockTransport(self.handler),
            clock=self.clock,
            sleep=self.clock.sleep,
            **kwargs,
        )


# --- parser (C2) -----------------------------------------------------------


def test_parse_normal_record():
    rec = record("90000001")
    assert rec.id == "pmid:90000001"
    assert rec.pmid == "90000001"
    assert rec.doi == "10.9999/fictional.0001"
    assert rec.title == "Fictional study of a made-up marker in a made-up cohort."
    assert rec.abstract is not None and rec.abstract.startswith("This fictional abstract")
    assert rec.journal == "Fictional Journal of Fatigue Research"
    assert rec.year == 2021
    assert rec.authors == ["Testperson AB", "Exempel C", "Fictional Fatigue Study Group"]
    assert rec.publication_types == ["Journal Article", "Observational Study"]
    assert rec.mesh_terms == ["Fictional Heading One", "Fictional Heading Two"]  # descriptors only, no qualifiers
    assert rec.retracted is False
    assert rec.entry_date == "2021-02-13"


def test_mesh_major_holds_major_descriptors_and_descriptors_with_a_major_qualifier():
    xml = fixture_text("90000001")
    start = xml.index("<MeshHeadingList>")
    end = xml.index("</MeshHeadingList>") + len("</MeshHeadingList>")
    headings = (
        "<MeshHeadingList>"
        '<MeshHeading><DescriptorName UI="D1" MajorTopicYN="Y">Major Descriptor</DescriptorName></MeshHeading>'
        '<MeshHeading><DescriptorName UI="D2" MajorTopicYN="N">Major Qualifier</DescriptorName>'
        '<QualifierName UI="Q1" MajorTopicYN="N">minor</QualifierName>'
        '<QualifierName UI="Q2" MajorTopicYN="Y">major</QualifierName></MeshHeading>'
        '<MeshHeading><DescriptorName UI="D3" MajorTopicYN="N">Not Major</DescriptorName>'
        '<QualifierName UI="Q3" MajorTopicYN="N">minor</QualifierName></MeshHeading>'
        "</MeshHeadingList>"
    )
    rec = parse_xml(xml[:start] + headings + xml[end:])
    assert rec.mesh_terms == ["Major Descriptor", "Major Qualifier", "Not Major"]
    assert rec.mesh_major == ["Major Descriptor", "Major Qualifier"]  # "Not Major" is left out


def test_mesh_major_is_empty_without_major_headings():
    assert record("90000001").mesh_major == []
    assert record("90000002").mesh_major == []


def test_pmcid_is_read_from_the_articles_own_id_list():
    xml = fixture_text("90000001").replace(
        '<ArticleId IdType="doi">10.9999/fictional.0001</ArticleId>',
        '<ArticleId IdType="doi">10.9999/fictional.0001</ArticleId><ArticleId IdType="pmc">PMC9000001</ArticleId>',
    )
    assert parse_xml(xml).pmcid == "PMC9000001"


def test_pmcid_is_none_without_a_pmc_id():
    assert record("90000001").pmcid is None


def test_pmcid_in_a_reference_list_only_is_not_taken():
    xml = fixture_text("90000001").replace(
        "</PubmedData>",
        "<ReferenceList><Reference><Citation>Fictional reference.</Citation>"
        '<ArticleIdList><ArticleId IdType="pmc">PMC9000999</ArticleId></ArticleIdList></Reference></ReferenceList>'
        "</PubmedData>",
    )
    assert "PMC9000999" in xml
    assert parse_xml(xml).pmcid is None


def test_record_id_is_valid_study_id():
    adapter = TypeAdapter(StudyId)
    for pmid in ALL_FIXTURES:
        assert adapter.validate_python(record(pmid).id) == f"pmid:{pmid}"


def test_parse_no_abstract():
    rec = record("90000002")
    assert rec.abstract is None
    assert rec.doi == "10.9999/fictional.0002"
    assert rec.mesh_terms == []


def test_parse_no_doi():
    rec = record("90000003")
    assert rec.doi is None
    assert rec.abstract is not None


def test_parse_structured_abstract_joins_labelled_sections_and_keeps_inline_text():
    rec = record("90000004")
    assert rec.abstract == (
        "BACKGROUND: Invented background text.\n"
        "METHODS: Invented methods with CO2 measured in 5 fictional people.\n"
        "RESULTS: Invented results."
    )
    assert rec.title == "Fictional trial of a made-up in vitro assay."


def test_parse_year_from_medline_date_when_year_is_absent():
    assert record("90000005").year == 2019


def test_parse_year_is_none_when_no_date_at_all():
    xml = re.sub(r"<PubDate>.*?</PubDate>", "<PubDate></PubDate>", fixture_text("90000001"))
    assert parse_xml(xml).year is None


def test_parse_retracted_by_publication_type():
    assert record("90000006").retracted is True


def test_parse_retracted_by_retraction_in_link_alone():
    rec = record("90000007")
    assert "Retracted Publication" not in rec.publication_types
    assert rec.retracted is True


def test_parse_record_without_retraction_markers_is_not_retracted():
    for pmid in ("90000001", "90000002", "90000003", "90000004", "90000005"):
        assert record(pmid).retracted is False


def test_retraction_notice_itself_is_not_a_retracted_study():
    rec = record("90000008")
    assert rec.publication_types == ["Retraction of Publication"]
    assert rec.retracted is False


def test_parse_errata_links_both_ways():
    study = record("90000020")
    assert study.errata == ["90000021"]
    assert study.erratum_for == []
    assert study.other_ref_types == []  # CommentIn is a known type
    notice = record("90000021")
    assert notice.erratum_for == ["90000020"]
    assert notice.errata == []
    assert "Published Erratum" in notice.publication_types


def test_parse_record_without_links_has_empty_erratum_lists():
    rec = record("90000001")
    assert rec.errata == []
    assert rec.erratum_for == []
    assert rec.other_ref_types == []


def test_parse_errata_are_deduplicated_in_record_order():
    link = '<CommentsCorrections RefType="ErratumIn"><PMID Version="1">%s</PMID></CommentsCorrections>'
    xml = fixture_text("90000020").replace(
        "</CommentsCorrectionsList>",
        link % "90000099" + link % "90000021" + link % "90000099" + "</CommentsCorrectionsList>",
    )
    assert parse_xml(xml).errata == ["90000021", "90000099"]


def test_parse_unknown_ref_type_is_exposed():
    xml = fixture_text("90000020").replace(
        "</CommentsCorrectionsList>",
        '<CommentsCorrections RefType="ExpressionOfConcernIn"><PMID Version="1">90000023</PMID></CommentsCorrections>'
        "</CommentsCorrectionsList>",
    )
    assert parse_xml(xml).other_ref_types == ["ExpressionOfConcernIn"]


def test_parse_accepts_bare_article_element():
    bare = ET.fromstring(fixture_text("90000001")).find("PubmedArticle")
    assert bare is not None
    assert pubmed.parse_article(bare).pmid == "90000001"


def test_parse_rejects_invalid_xml():
    with pytest.raises(ParseError, match="invalid XML"):
        parse_xml("<PubmedArticleSet><oops")


def test_parse_rejects_record_without_title():
    xml = re.sub(r"<ArticleTitle>.*?</ArticleTitle>", "", fixture_text("90000001"))
    with pytest.raises(ParseError, match="no article title"):
        parse_xml(xml)


def test_parse_rejects_non_numeric_pmid():
    xml = fixture_text("90000001").replace('<PMID Version="1">90000001</PMID>', '<PMID Version="1">../evil</PMID>')
    with pytest.raises(ParseError, match="PMID"):
        parse_xml(xml)


def test_parse_rejects_wrong_root():
    with pytest.raises(ParseError):
        parse_xml("<Something/>")


def test_parse_rejects_set_with_two_articles():
    two = f"<PubmedArticleSet>{'<PubmedArticle/>' * 2}</PubmedArticleSet>"
    with pytest.raises(ParseError, match="found 2"):
        parse_xml(two)


# --- rate limit (C3) -------------------------------------------------------


def assert_no_more_than(times: list[float], limit: int) -> None:
    """No `limit + 1` requests start within a single second."""
    for i in range(len(times) - limit):
        assert times[i + limit] - times[i] >= 1.0, f"{limit + 1} requests started within one second at index {i}"


def test_rate_limit_without_key_is_three_per_second():
    server = FakePubMed()
    client = server.client()
    for _ in range(10):
        client.search("x")
    times = server.times()
    assert len(times) == 10
    assert_no_more_than(times, 3)
    assert times[2] == times[0], "the first three requests should not be delayed"
    assert times[3] - times[0] == 1.0, "the fourth request waits exactly until the window has passed"


def test_rate_limit_with_key_is_ten_per_second():
    server = FakePubMed()
    client = server.client(api_key="KEY")
    for _ in range(25):
        client.search("x")
    times = server.times()
    assert_no_more_than(times, 10)
    assert times[9] == times[0]
    assert times[10] - times[0] == 1.0
    assert not (len(times) > 3 and times[3] - times[0] >= 1.0), "with a key the 4th request is not held back"


def test_rate_limiter_does_not_sleep_under_the_limit():
    clock = FakeClock()
    limiter = RateLimiter(3, clock, clock.sleep)
    for _ in range(3):
        limiter.wait()
    assert clock.sleeps == []
    clock.t = 5.0  # a long pause: the window is empty again
    for _ in range(3):
        limiter.wait()
    assert clock.sleeps == []


def test_rate_limit_applies_to_retries_too():
    server = FakePubMed()
    server.statuses.extend([429, 429, 429])
    client = server.client(backoff=0.0)  # no backoff: only the limiter can space the requests
    client.search("x")
    assert len(server.requests) == 4
    assert_no_more_than(server.times(), 3)


# --- retries (C4) ----------------------------------------------------------


def test_retry_429_then_200_succeeds():
    server = FakePubMed()
    server.statuses.append(429)
    result = server.client().search("x")
    assert result.ids == server.window_ids
    assert len(server.requests) == 2
    assert server.clock.sleeps == [1.0]


def test_repeated_500_fails_with_clear_error_after_retry_limit():
    server = FakePubMed()
    server.statuses.extend([500] * 20)
    client = server.client(max_retries=4)
    with pytest.raises(PubMedError, match=r"esearch\.fcgi failed after 5 attempts; last error: HTTP 500"):
        client.search("x")
    assert len(server.requests) == 5
    assert server.clock.sleeps == [1.0, 2.0, 4.0, 8.0]  # exponential backoff, and no sleep after the last attempt


def test_client_error_other_than_429_is_not_retried():
    server = FakePubMed()
    server.statuses.append(400)
    with pytest.raises(PubMedError, match="HTTP 400 .*not retried"):
        server.client().search("x")
    assert len(server.requests) == 1


def test_transport_error_is_retried_then_reported():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("boom")

    clock = FakeClock()
    client = PubMedClient(
        "tester@example.org", transport=httpx.MockTransport(handler), clock=clock, sleep=clock.sleep, max_retries=2
    )
    with pytest.raises(PubMedError, match="after 3 attempts.*ConnectError"):
        client.search("x")
    assert len(calls) == 3


def test_retry_after_header_is_honoured():
    clock = FakeClock()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})

    client = PubMedClient("t@example.org", transport=httpx.MockTransport(handler), clock=clock, sleep=clock.sleep)
    client.search("x")
    assert clock.sleeps == [7.0]


def test_esearch_error_body_raises():
    server = FakePubMed()
    server.extra_search = {"ERROR": "Invalid query"}
    with pytest.raises(PubMedError, match="Invalid query"):
        server.client().search("x")


def test_esearch_unreadable_body_raises():
    client = PubMedClient(
        "t@example.org", transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>oops</html>"))
    )
    with pytest.raises(PubMedError, match="unreadable ESearch"):
        client.search("x")


def test_efetch_unreadable_body_raises():
    client = PubMedClient("t@example.org", transport=httpx.MockTransport(lambda r: httpx.Response(200, text="nope")))
    with pytest.raises(PubMedError, match="unreadable EFetch"):
        list(client.fetch_articles(["90000001"]))


def test_search_without_email_is_refused():
    with pytest.raises(ValueError, match="email"):
        PubMedClient("")


# --- contact parameters (C6) ----------------------------------------------


def test_every_request_carries_tool_and_email_and_key_when_set():
    server = FakePubMed()
    client = server.client(api_key="SECRETKEY")
    client.search("x")
    list(client.fetch_articles(["90000001"]))
    assert len(server.requests) == 2
    for _, params, _ in server.requests:
        assert params["tool"] == "me-atlas"
        assert params["email"] == "tester@example.org"
        assert params["api_key"] == "SECRETKEY"


def test_no_api_key_parameter_without_a_key():
    server = FakePubMed()
    client = server.client()
    client.search("x")
    list(client.fetch_articles(["90000001"]))
    for _, params, _ in server.requests:
        assert "api_key" not in params
        assert params["email"] == "tester@example.org"


def test_search_uses_history_server_and_returns_it():
    server = FakePubMed()
    result = server.client().search("x")
    assert server.of("esearch.fcgi")[0]["usehistory"] == "y"
    assert (result.webenv, result.query_key) == ("FAKE_WEBENV", "1")


def test_fetch_batches_ids(monkeypatch):
    monkeypatch.setattr(pubmed, "FETCH_BATCH_SIZE", 3)
    server = FakePubMed()
    articles = list(server.client().fetch_articles(ALL_FIXTURES))
    assert len(articles) == 8
    assert [len(p["id"].split(",")) for p in server.of("efetch.fcgi")] == [3, 3, 2]


# --- cache (C5) ------------------------------------------------------------


def run_cli(server, tmp_path, *args, env=None, query="(fictional query)", today=TODAY):
    """Run the CLI against the fake server with an isolated cache dir and query file."""
    qfile = tmp_path / "query.txt"
    if query is not None and not qfile.exists():
        qfile.write_text(query, encoding="utf-8")
    env = {"CONTACT_EMAIL": "tester@example.org"} if env is None else env
    return pubmed.main(
        ["fetch", "--query-file", str(qfile), "--cache-dir", str(tmp_path / "cache"), *args],
        env=env,
        transport=httpx.MockTransport(server.handler),
        clock=server.clock,
        sleep=server.clock.sleep,
        today=today,
        now=lambda: NOW,
    )


def test_cached_pmid_is_not_requested_again_and_refresh_requests_it(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--since", "2026-01-01") == 0
    first = server.of("efetch.fcgi")
    assert sorted(i for p in first for i in p["id"].split(",")) == ["90000001", "90000002", "90000003", "90000006"]
    for pmid in ("90000001", "90000002", "90000003", "90000006"):
        assert (tmp_path / "cache" / "pubmed" / f"{pmid}.xml").is_file()

    server.requests.clear()
    assert run_cli(server, tmp_path, "--since", "2026-01-01") == 0
    assert server.of("efetch.fcgi") == []

    server.requests.clear()
    assert run_cli(server, tmp_path, "--since", "2026-01-01", "--refresh") == 0
    again = server.of("efetch.fcgi")
    assert sorted(i for p in again for i in p["id"].split(",")) == ["90000001", "90000002", "90000003", "90000006"]


def test_cached_file_is_parseable_and_root_is_configurable(tmp_path):
    server = FakePubMed()
    run_cli(server, tmp_path, "--since", "2026-01-01")
    cache = RawCache(tmp_path / "cache")
    assert cache.read_record("90000001") == record("90000001")
    assert cache.read_record("90000006").retracted is True


def test_cache_default_root_is_data_cache():
    cache = RawCache()
    assert cache.path("90000001") == Path("data/cache/pubmed/90000001.xml")


def test_cache_refuses_non_numeric_pmid(tmp_path):
    with pytest.raises(ValueError, match="digits"):
        RawCache(tmp_path).path("../../evil")


def test_reading_an_uncached_pmid_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        RawCache(tmp_path).read_record("90000001")


def test_cached_copy_of_a_since_retracted_paper_is_refetched(tmp_path):
    server = FakePubMed()
    server.window_ids = []  # the paper is old: nothing new in the window
    stale = fixture_text("90000006")
    stale = stale.replace('<PublicationType UI="D016441">Retracted Publication</PublicationType>', "")
    stale = re.sub(r"<CommentsCorrectionsList>.*?</CommentsCorrectionsList>", "", stale, flags=re.S)
    cache = RawCache(tmp_path / "cache")
    cache.pubmed_dir.mkdir(parents=True)
    (cache.pubmed_dir / "90000006.xml").write_text(stale, encoding="utf-8")
    assert cache.read_record("90000006").retracted is False

    assert run_cli(server, tmp_path, "--weekly") == 0

    assert cache.read_record("90000006").retracted is True
    manifest = json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))
    assert manifest["newly_flagged_retracted_pmids"] == ["90000006"]
    assert manifest["new_pmids"] == []  # it was cached before, just stale
    assert manifest["retracted_pmids"] == ["90000006"]


def test_already_retracted_cached_copy_is_not_refetched(tmp_path):
    server = FakePubMed()
    server.window_ids = []
    cache = RawCache(tmp_path / "cache")
    cache.pubmed_dir.mkdir(parents=True)
    (cache.pubmed_dir / "90000006.xml").write_text(fixture_text("90000006"), encoding="utf-8")
    assert run_cli(server, tmp_path, "--weekly") == 0
    assert server.of("efetch.fcgi") == []


# --- query config (C8) -----------------------------------------------------


def test_query_comes_from_the_config_file_and_changing_it_changes_the_request(tmp_path):
    server = FakePubMed()
    qfile = tmp_path / "query.txt"
    qfile.write_text("alpha[Title]", encoding="utf-8")
    run_cli(server, tmp_path, "--weekly", query=None)
    first = [p["term"] for p in server.of("esearch.fcgi")]
    assert first == ["alpha[Title]", f"(alpha[Title]) AND {pubmed.RETRACTION_FILTER}"]

    server.requests.clear()
    qfile.write_text("# a comment\nbeta[Title]\n\n  OR gamma[Title]\n", encoding="utf-8")
    run_cli(server, tmp_path, "--weekly", query=None)
    second = [p["term"] for p in server.of("esearch.fcgi")]
    assert second == ["beta[Title] OR gamma[Title]", f"(beta[Title] OR gamma[Title]) AND {pubmed.RETRACTION_FILTER}"]


def test_read_query_rejects_missing_and_empty_files(tmp_path):
    with pytest.raises(PubMedError, match="cannot read query file"):
        read_query(tmp_path / "missing.txt")
    empty = tmp_path / "empty.txt"
    empty.write_text("# only a comment\n\n", encoding="utf-8")
    with pytest.raises(PubMedError, match="is empty"):
        read_query(empty)


def test_repository_query_file_is_readable_and_has_the_planned_parts():
    query = read_query(Path(__file__).parents[1] / "config" / "pubmed_query.txt")
    assert query.count("(") == query.count(")")
    for part in ("[MeSH Terms]", "myalgic encephalomyelitis", "chronic fatigue syndrome", "ME/CFS", "AND"):
        assert part in query
    assert "#" not in query


def test_cli_missing_query_file_exits_nonzero(tmp_path, capsys):
    server = FakePubMed()
    code = run_cli(server, tmp_path, "--weekly", query=None)
    assert code == 1
    assert "cannot read query file" in capsys.readouterr().err
    assert server.requests == []


# --- CLI, windows and manifest (C6, C7) ------------------------------------


@pytest.mark.parametrize("env", [{}, {"CONTACT_EMAIL": ""}, {"CONTACT_EMAIL": "   "}, {"NCBI_API_KEY": "K"}])
def test_run_without_contact_email_exits_nonzero_naming_the_variable(tmp_path, capsys, env):
    server = FakePubMed()
    code = run_cli(server, tmp_path, "--weekly", env=env)
    assert code != 0
    assert "CONTACT_EMAIL" in capsys.readouterr().err
    assert server.requests == [], "nothing may be sent to NCBI without a contact email"


def test_every_cli_request_carries_tool_email_and_key(tmp_path):
    server = FakePubMed()
    env = {"CONTACT_EMAIL": "tester@example.org", "NCBI_API_KEY": "K123"}
    assert run_cli(server, tmp_path, "--weekly", env=env) == 0
    assert len(server.requests) >= 3
    for _, params, _ in server.requests:
        assert (params["tool"], params["email"], params["api_key"]) == ("me-atlas", "tester@example.org", "K123")


def test_cli_without_key_uses_three_per_second(tmp_path):
    server = FakePubMed()
    server.window_ids = [f"9000000{i}" for i in range(1, 9)]
    server.retracted_ids = []
    assert run_cli(server, tmp_path, "--weekly") == 0
    assert_no_more_than(server.times(), 3)


def test_weekly_uses_the_last_14_days_by_entry_date(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--weekly") == 0
    main_search, retraction_search = server.of("esearch.fcgi")
    assert main_search["datetype"] == "edat"
    assert (main_search["mindate"], main_search["maxdate"]) == ("2026/10/17", "2026/10/31")
    manifest = json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))
    assert manifest["window"] == {"mode": "weekly", "datetype": "edat", "since": "2026-10-17", "until": "2026-10-31"}
    # The retraction query is not limited by the window.
    assert "mindate" not in retraction_search and "datetype" not in retraction_search


def test_since_and_until(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--since", "2025-01-01", "--until", "2025-06-30") == 0
    main_search = server.of("esearch.fcgi")[0]
    assert (main_search["mindate"], main_search["maxdate"]) == ("2025/01/01", "2025/06/30")


def test_since_without_until_ends_today(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--since", "2025-01-01") == 0
    assert server.of("esearch.fcgi")[0]["maxdate"] == "2026/10/31"


def test_backfill_has_no_date_limit(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--backfill") == 0
    for params in server.of("esearch.fcgi"):
        assert "mindate" not in params and "maxdate" not in params
    manifest = json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))
    assert manifest["window"]["mode"] == "backfill"
    assert manifest["window"]["since"] is None and manifest["window"]["until"] is None


def test_manifest_contents(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--weekly") == 0
    runs = list((tmp_path / "cache" / "runs").glob("*.json"))
    assert [p.name for p in runs] == ["20261031T120000Z.json"]
    m = json.loads(runs[0].read_text(encoding="utf-8"))
    assert m["query"] == "(fictional query)"
    assert m["retraction_query"] == f"((fictional query)) AND {pubmed.RETRACTION_FILTER}"
    assert m["refresh"] is False
    assert m["counts"] == {
        "window_hits": 3,
        "retraction_hits": 1,
        "requested": 4,
        "fetched": 4,
        "new": 4,
        "skipped_cached": 0,
        "missing": 0,
        "unparsable": 0,
    }
    assert m["new_pmids"] == ["90000001", "90000002", "90000003", "90000006"]
    assert m["window_pmids"] and m["window_pmids"] == sorted(m["window_pmids"], key=int)
    assert m["retracted_pmids"] == ["90000006"]
    assert m["missing_pmids"] == [] and m["unparsable_pmids"] == [] and m["warnings"] == []


def test_second_run_manifest_reports_cached_and_no_new(tmp_path):
    server = FakePubMed()
    run_cli(server, tmp_path, "--weekly")
    (tmp_path / "cache" / "runs" / "20261031T120000Z.json").unlink()
    run_cli(server, tmp_path, "--weekly")
    m = json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))
    assert m["new_pmids"] == []
    assert m["counts"]["skipped_cached"] == 4 and m["counts"]["fetched"] == 0
    assert m["retracted_pmids"] == ["90000006"], "retracted PMIDs are reported on every run"


def test_pmid_missing_from_efetch_is_reported_not_fatal(tmp_path, capsys):
    server = FakePubMed()
    server.window_ids = ["90000001", "90009999"]
    server.retracted_ids = []
    assert run_cli(server, tmp_path, "--weekly") == 0
    m = json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))
    assert m["missing_pmids"] == ["90009999"]
    assert m["new_pmids"] == ["90000001"]
    assert "90009999" in capsys.readouterr().err


def test_unparsable_record_is_cached_and_reported(tmp_path):
    server = FakePubMed()
    server.articles["90000001"] = re.sub(r"<ArticleTitle>.*?</ArticleTitle>", "", fixture_text("90000001"))
    server.window_ids = ["90000001"]
    server.retracted_ids = []
    assert run_cli(server, tmp_path, "--weekly") == 0
    m = json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))
    assert m["unparsable_pmids"] == ["90000001"]
    assert (tmp_path / "cache" / "pubmed" / "90000001.xml").is_file()


def test_pubmed_warnings_are_recorded_in_the_manifest(tmp_path, capsys):
    server = FakePubMed()
    server.extra_search = {"warninglist": {"phrasesnotfound": ["fictional phrase"], "outputmessages": []}}
    assert run_cli(server, tmp_path, "--weekly") == 0
    m = json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))
    assert m["warnings"] == ["phrasesnotfound: fictional phrase"] * 2
    assert "fictional phrase" in capsys.readouterr().err


def test_failed_run_exits_nonzero_and_writes_no_manifest(tmp_path, capsys):
    server = FakePubMed()
    server.statuses.extend([500] * 50)
    assert run_cli(server, tmp_path, "--weekly") == 1
    assert "after 5 attempts" in capsys.readouterr().err
    assert not (tmp_path / "cache" / "runs").exists()


@pytest.mark.parametrize(
    "args",
    [
        [],  # no mode
        ["--weekly", "--backfill"],
        ["--since", "2025-01-01", "--weekly"],
        ["--weekly", "--until", "2025-01-01"],
        ["--backfill", "--until", "2025-01-01"],
        ["--since", "not-a-date"],
    ],
)
def test_invalid_argument_combinations_are_rejected(tmp_path, args):
    server = FakePubMed()
    with pytest.raises(SystemExit) as exc:
        run_cli(server, tmp_path, *args)
    assert exc.value.code == 2
    assert server.requests == []


def test_load_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# c\nCONTACT_EMAIL='a@example.org'\nNCBI_API_KEY=\nNOEQUALS\n", encoding="utf-8")
    assert load_dotenv(env_file) == {"CONTACT_EMAIL": "a@example.org", "NCBI_API_KEY": ""}
    assert load_dotenv(tmp_path / "absent.env") == {}


# --- search over the ESearch cap ------------------------------------------


def test_search_over_the_cap_is_split_by_entry_date(monkeypatch):
    monkeypatch.setattr(pubmed, "MAX_UIDS", 2)
    entered = {
        "90000001": dt.date(2020, 1, 5),
        "90000002": dt.date(2021, 6, 1),
        "90000003": dt.date(2022, 3, 3),
        "90000004": dt.date(2023, 9, 9),
        "90000005": dt.date(2024, 12, 24),
    }

    def search(params: dict[str, str]) -> list[str]:
        lo = dt.datetime.strptime(params.get("mindate", "1900/01/01"), "%Y/%m/%d").date()
        hi = dt.datetime.strptime(params.get("maxdate", "2100/01/01"), "%Y/%m/%d").date()
        return [p for p, d in entered.items() if lo <= d <= hi]

    server = FakePubMed()
    server.search_fn = search
    result = server.client().search_all("x")
    assert sorted(result.ids) == sorted(entered)
    assert len(result.ids) == 5 and result.warnings == []
    assert len(server.of("esearch.fcgi")) > 1


def test_search_within_the_cap_is_a_single_request():
    server = FakePubMed()
    result = server.client().search_all("x")
    assert result.ids == server.window_ids
    assert len(server.requests) == 1


def test_search_over_the_cap_on_one_day_fails_clearly(monkeypatch):
    monkeypatch.setattr(pubmed, "MAX_UIDS", 1)
    server = FakePubMed()
    server.search_fn = lambda params: ["90000001", "90000002"]
    with pytest.raises(PubMedError, match="cannot split further"):
        server.client().search_all("x", mindate=dt.date(2025, 1, 1), maxdate=dt.date(2025, 1, 2))


# --- run_fetch directly ----------------------------------------------------


def test_run_fetch_returns_manifest_and_path(tmp_path):
    server = FakePubMed()
    manifest, path = run_fetch(
        server.client(),
        "q",
        Window("since", dt.date(2026, 1, 1), TODAY),
        RawCache(tmp_path),
        now=lambda: NOW,
        query_file="config/pubmed_query.txt",
    )
    assert path == tmp_path / "runs" / "20261031T120000Z.json"
    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    assert manifest["query_file"] == "config/pubmed_query.txt"


def test_retraction_term_wraps_the_query():
    assert retraction_term("a OR b") == '(a OR b) AND "Retracted Publication"[Publication Type]'


# --- fetch --ids ------------------------------------------------------------


def efetched_ids(server: FakePubMed) -> list[str]:
    return sorted(i for p in server.of("efetch.fcgi") for i in p["id"].split(","))


def only_manifest(tmp_path: Path) -> dict:
    return json.loads(next((tmp_path / "cache" / "runs").glob("*.json")).read_text(encoding="utf-8"))


def test_ids_fetches_exactly_those_ids_without_any_search(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--ids", "90000004", "90000005") == 0
    assert [e for e, _, _ in server.requests] == ["efetch.fcgi"], "no ESearch, no retraction query"
    assert efetched_ids(server) == ["90000004", "90000005"]
    for pmid in ("90000004", "90000005"):
        assert RawCache(tmp_path / "cache").read_record(pmid) == record(pmid)
    assert not (tmp_path / "cache" / "pubmed" / "90000001.xml").exists()


def test_ids_accepts_the_pmid_prefix_and_ignores_the_query_file(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--ids", "pmid:90000004", query=None) == 0
    assert efetched_ids(server) == ["90000004"]


def test_ids_skips_cached_records_and_refresh_fetches_them_again(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--ids", "90000004") == 0

    server.requests.clear()
    assert run_cli(server, tmp_path, "--ids", "90000004", "90000005") == 0
    assert efetched_ids(server) == ["90000005"], "the cached record is not requested again"

    server.requests.clear()
    assert run_cli(server, tmp_path, "--ids", "90000004", "90000005") == 0
    assert server.requests == [], "everything cached: no request at all"

    server.requests.clear()
    assert run_cli(server, tmp_path, "--ids", "90000004", "90000005", "--refresh") == 0
    assert efetched_ids(server) == ["90000004", "90000005"]


def test_ids_writes_a_manifest_with_mode_and_ids(tmp_path):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--ids", "90000005", "90000004", "90000005") == 0
    m = only_manifest(tmp_path)
    assert m["mode"] == "ids"
    assert m["ids"] == ["90000005", "90000004"], "in the order given, without duplicates"
    assert m["refresh"] is False
    assert m["new_pmids"] == ["90000004", "90000005"]
    assert m["counts"]["fetched"] == 2 and m["counts"]["skipped_cached"] == 0
    assert "query" not in m and "retraction_query" not in m


def test_ids_reports_a_pmid_pubmed_does_not_return(tmp_path, capsys):
    server = FakePubMed()
    assert run_cli(server, tmp_path, "--ids", "90000004", "90009999") == 0
    assert only_manifest(tmp_path)["missing_pmids"] == ["90009999"]
    assert "90009999" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["--ids", "90000001", "--since", "2025-01-01"],
        ["--ids", "90000001", "--weekly"],
        ["--ids", "90000001", "--backfill"],
        ["--ids", "90000001", "--until", "2025-01-01"],
        ["--ids"],  # no ids given
        ["--ids", "not-a-pmid"],
    ],
)
def test_ids_cannot_be_combined_with_a_window_mode(tmp_path, args):
    server = FakePubMed()
    with pytest.raises(SystemExit) as exc:
        run_cli(server, tmp_path, *args)
    assert exc.value.code == 2
    assert server.requests == []


# --- query-diff ---------------------------------------------------------------


def diff_articles(pmids: list[str]) -> dict[str, str]:
    """Fictional records: fixture 90000001 with the PMID swapped."""
    return {p: fixture_text("90000001").replace("90000001", p) for p in pmids}


def run_diff(server, tmp_path, *args, env=None, query="(fictional query)"):
    qfile = tmp_path / "query.txt"
    if query is not None and not qfile.exists():
        qfile.write_text(query, encoding="utf-8")
    env = {"CONTACT_EMAIL": "tester@example.org"} if env is None else env
    return pubmed.main(
        ["query-diff", "--query-file", str(qfile), "--cache-dir", str(tmp_path / "cache"), *args],
        env=env,
        transport=httpx.MockTransport(server.handler),
        clock=server.clock,
        sleep=server.clock.sleep,
        now=lambda: NOW,
    )


def only_diff_result(tmp_path: Path) -> dict:
    files = list((tmp_path / "cache" / "query-diff").glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def diff_server(added: dict[str, list[str]], inside: set[str] = frozenset()) -> FakePubMed:
    """Term searches (``... NOT (``) return ``added[term]``; id checks return ids in ``inside``."""
    all_ids = sorted({i for ids in added.values() for i in ids} | set(inside))
    server = FakePubMed(articles=diff_articles(all_ids))

    def search(params: dict[str, str]) -> list[str]:
        term = params["term"]
        if " NOT (" in term:
            return added.get(term.split('"')[1], [])
        if "[uid]" in term:
            return [i for i in re.findall(r"(\d+)\[uid\]", term) if i in inside]
        return ["90000001", "90000002", "90000003"]  # the plain query: three hits

    server.search_fn = search
    return server


def test_query_diff_term_counts_all_hits_samples_the_newest_n_and_caches_them(tmp_path, capsys):
    hits = [f"9100{i:04d}" for i in range(7, 0, -1)]  # 7 hits, newest first
    server = diff_server({"CFS/ME": hits})
    assert run_diff(server, tmp_path, "--term", "CFS/ME", "--sample", "3") == 0

    term_searches = [p for p in server.of("esearch.fcgi") if " NOT (" in p["term"]]
    assert [p["term"] for p in term_searches] == ['"CFS/ME"[Title/Abstract] NOT ((fictional query))']
    assert efetched_ids(server) == sorted(hits[:3])
    for pmid in hits[:3]:
        assert (tmp_path / "cache" / "pubmed" / f"{pmid}.xml").is_file()
    assert not (tmp_path / "cache" / "pubmed" / f"{hits[3]}.xml").exists()

    result = only_diff_result(tmp_path)
    assert result["query"] == "(fictional query)" and result["query_hits"] == 3
    (item,) = result["terms"]
    assert item["search"] == '"CFS/ME"[Title/Abstract] NOT ((fictional query))'
    assert (item["count"], item["sample_size"], item["sample_pmids"]) == (7, 3, hits[:3])
    assert item["warnings"] == []
    out = capsys.readouterr().out
    assert "'CFS/ME': 7 added, sample 3" in out and "query-diff" in out


def test_query_diff_does_not_download_cached_records_again(tmp_path):
    hits = ["91000002", "91000001"]
    server = diff_server({"a": hits})
    assert run_diff(server, tmp_path, "--term", "a") == 0
    server.requests.clear()
    (tmp_path / "cache" / "query-diff" / "20261031T120000Z.json").unlink()
    assert run_diff(server, tmp_path, "--term", "a") == 0
    assert server.of("efetch.fcgi") == []


def test_query_diff_term_with_no_hits_is_count_zero_and_makes_no_efetch(tmp_path):
    server = diff_server({"none": []})
    assert run_diff(server, tmp_path, "--term", "none") == 0
    assert server.of("efetch.fcgi") == []
    (item,) = only_diff_result(tmp_path)["terms"]
    assert (item["count"], item["sample_size"], item["sample_pmids"]) == (0, 0, [])


def test_query_diff_prints_and_stores_pubmed_warnings(tmp_path, capsys):
    server = diff_server({"odd term": []})
    server.extra_search = {"warninglist": {"phrasesnotfound": ["odd term"], "outputmessages": []}}
    assert run_diff(server, tmp_path, "--term", "odd term") == 0
    (item,) = only_diff_result(tmp_path)["terms"]
    assert item["warnings"] == ["phrasesnotfound: odd term"]
    assert "odd term" in capsys.readouterr().err


def test_query_diff_ids_lists_only_the_id_the_query_does_not_return(tmp_path, capsys):
    server = diff_server({}, inside={"91000001"})
    assert run_diff(server, tmp_path, "--ids", "91000001", "91000002") == 0
    check = only_diff_result(tmp_path)["ids_check"]
    assert check["ids"] == ["91000001", "91000002"]
    assert check["outside"] == ["91000002"], "the id the query returns must not be listed as outside"
    restricted = [p["term"] for p in server.of("esearch.fcgi") if "[uid]" in p["term"]]
    assert restricted == ["((fictional query)) AND (91000001[uid] OR 91000002[uid])"]
    assert "outside: 91000002" in capsys.readouterr().out
    assert server.of("efetch.fcgi") == []


def test_query_diff_ids_are_sent_in_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(pubmed, "IDS_BATCH_SIZE", 2)
    server = diff_server({}, inside={"91000001", "91000004"})
    ids = ["91000001", "91000002", "91000003", "91000004", "91000005"]
    assert run_diff(server, tmp_path, "--ids", *ids) == 0
    assert len([p for p in server.of("esearch.fcgi") if "[uid]" in p["term"]]) == 3
    assert only_diff_result(tmp_path)["ids_check"]["outside"] == ["91000002", "91000003", "91000005"]


def test_cited_pmids_picks_ids_out_of_yaml_files_only(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.yaml").write_text("studies:\n  - id: pmid:91000002\n  - id: doi:10.1/x\n", encoding="utf-8")
    (tmp_path / "sub" / "b.yml").write_text("- id: pmid:91000001\n- id: pmid:91000002\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("pmid:91000009", encoding="utf-8")
    assert pubmed.cited_pmids(tmp_path) == ["91000001", "91000002"]


def test_query_diff_cited_in_checks_the_ids_in_the_directory(tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "card.yaml").write_text("- id: pmid:91000001\n- id: pmid:91000002\n", encoding="utf-8")
    server = diff_server({}, inside={"91000001"})
    assert run_diff(server, tmp_path, "--cited-in", str(drafts)) == 0
    check = only_diff_result(tmp_path)["ids_check"]
    assert check["ids"] == ["91000001", "91000002"] and check["outside"] == ["91000002"]


def test_query_diff_cited_in_a_missing_directory_fails(tmp_path, capsys):
    server = diff_server({})
    assert run_diff(server, tmp_path, "--cited-in", str(tmp_path / "nope")) == 1
    assert "not a directory" in capsys.readouterr().err


@pytest.mark.parametrize("env", [{}, {"CONTACT_EMAIL": ""}, {"CONTACT_EMAIL": "  "}])
def test_query_diff_without_contact_email_exits_2_and_sends_nothing(tmp_path, capsys, env):
    server = diff_server({"a": ["91000001"]})
    assert run_diff(server, tmp_path, "--term", "a", env=env) == 2
    assert "CONTACT_EMAIL" in capsys.readouterr().err
    assert server.requests == []
    assert not (tmp_path / "cache").exists()


def test_query_diff_writes_under_query_diff_and_never_under_runs(tmp_path, capsys):
    server = diff_server({"a": ["91000001"]}, inside={"91000002"})
    assert run_diff(server, tmp_path, "--term", "a", "--ids", "91000002") == 0
    assert [p.name for p in (tmp_path / "cache" / "query-diff").glob("*.json")] == ["20261031T120000Z.json"]
    assert not (tmp_path / "cache" / "runs").exists()
    assert str(tmp_path / "cache" / "query-diff" / "20261031T120000Z.json") in capsys.readouterr().out


def test_query_diff_needs_something_to_do_and_a_positive_sample(tmp_path):
    for args in ([], ["--term", "a", "--sample", "0"]):
        server = diff_server({})
        with pytest.raises(SystemExit) as exc:
            run_diff(server, tmp_path, *args)
        assert exc.value.code == 2
        assert server.requests == []


# --- preprints -------------------------------------------------------------


def test_a_record_with_the_preprint_publication_type_is_a_preprint_whatever_its_journal_says():
    rec = record("90000009")
    assert rec.publication_types == ["Journal Article", "Preprint"]
    assert rec.preprint is True


def test_a_plain_journal_article_is_not_a_preprint():
    assert record("90000001").preprint is False


def test_a_journal_that_calls_itself_a_preprint_server_is_not_enough():
    xml = fixture_text("90000009").replace('<PublicationType UI="D000076942">Preprint</PublicationType>', "")
    rec = parse_xml(xml)
    assert "preprint server" in (rec.journal or "")
    assert rec.preprint is False
