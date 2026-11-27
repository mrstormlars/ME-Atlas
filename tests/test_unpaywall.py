"""Tests for the Unpaywall open PDF path: choice of copy, lookup, download, cache, text and the quote matcher.

Fictional DOIs, PMIDs and titles ("Fictional ..."); the PDFs are the generated files of ``fixtures/unpaywall/``.
No network: every request goes to an ``httpx.MockTransport``. The command line, C5 and C14 are in
``test_unpaywall_cli.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape

import httpx
import pytest

from me_atlas import unpaywall
from me_atlas.unpaywall import CopyFinder, UnpaywallCache, cache_key

FIX = Path(__file__).parent / "fixtures" / "unpaywall"
MAIN_PDF = (FIX / "fictional_main.pdf").read_bytes()
TWO_COLUMN_PDF = (FIX / "fictional_two_column.pdf").read_bytes()
OTHER_PDF = (FIX / "fictional_other_title.pdf").read_bytes()
SCAN_PDF = (FIX / "fictional_scan.pdf").read_bytes()

EMAIL = "tester-9f3a@fictional-mail.example"
PMID = "90000201"
DOI = "10.9999/fictional.pdf(1);a"
TITLE = "Fictional study of open copies in a made-up cohort."
PDF_A = "https://publisher.example/paper.pdf"
PDF_B = "https://repo.example/accepted.pdf"
QUOTE_HYPHEN = "Participants were diagnosed according to the Fukuda criteria in a made-up clinic."
QUOTE_FOLLOW_UP = "Each person had a median follow-up of two fictional years."
QUOTE_LIGATURE = "The final sample was a fictional filter of ten invented people."
QUOTE_COLUMN = (
    "Right column text states that cases met the Canadian Consensus Criteria in a made-up clinic and were counted "
    "by invented staff during the fictional study period."
)
QUOTE_REFERENCE = "The Fictional Reference Criteria were applied only in a made-up list."


class Clock:
    """A fake clock: sleeping moves it, so the rate limiter never really waits."""

    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def pubmed_xml(pmid: str, title: str, doi: str | None, abstract: str = "Fictional abstract.") -> str:
    ids = f'<ArticleIdList><ArticleId IdType="doi">{escape(doi)}</ArticleId></ArticleIdList>' if doi else ""
    return (
        f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">{pmid}</PMID><Article>'
        "<Journal><JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue><Title>Fictional Journal</Title>"
        f"</Journal><ArticleTitle>{escape(title)}</ArticleTitle><Abstract><AbstractText>{escape(abstract)}"
        "</AbstractText></Abstract><PublicationTypeList><PublicationType>Journal Article</PublicationType>"
        f"</PublicationTypeList></Article></MedlineCitation><PubmedData>{ids}</PubmedData></PubmedArticle>"
        "</PubmedArticleSet>"
    )


def add_record(root: Path, pmid: str = PMID, title: str = TITLE, doi: str | None = DOI) -> None:
    folder = root / "pubmed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pmid}.xml").write_text(pubmed_xml(pmid, title, doi), encoding="utf-8")


def loc(url: str | None, version: str = "publishedVersion", host: str = "publisher", **extra) -> dict:
    return {
        "url_for_pdf": url,
        "url_for_landing_page": (url or "https://landing.example/x") + "#landing",
        "host_type": host,
        "version": version,
        "license": "cc-by",
        "is_best": False,
        **extra,
    }


def answer(*locations: dict) -> dict:
    return {"doi": DOI.lower(), "is_oa": bool(locations), "oa_status": "hybrid", "oa_locations": list(locations)}


class World:
    """The mock web: an Unpaywall answer, PDF bodies by URL, robots.txt by host, and a log of every request."""

    def __init__(self, unpaywall_answer: dict | int | None = None) -> None:
        self.unpaywall_answer = unpaywall_answer
        self.files: dict[str, tuple[int, bytes, str]] = {}
        self.robots: dict[str, str] = {}
        self.log: list[httpx.Request] = []

    def serve(self, url: str, body: bytes, status: int = 200, content_type: str = "application/pdf") -> None:
        self.files[url] = (status, body, content_type)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.log.append(request)
        url = str(request.url).split("?")[0]
        host = request.url.host
        if host == "api.unpaywall.org":
            if isinstance(self.unpaywall_answer, int):
                return httpx.Response(self.unpaywall_answer, json={"error": True})
            return httpx.Response(200, json=self.unpaywall_answer)
        if request.url.path == "/robots.txt":
            if host in self.robots:
                return httpx.Response(200, text=self.robots[host])
            return httpx.Response(404, text="")
        if url in self.files:
            status, body, content_type = self.files[url]
            return httpx.Response(status, content=body, headers={"content-type": content_type})
        return httpx.Response(404, text="not here")

    def requested(self, host: str) -> list[httpx.Request]:
        return [r for r in self.log if r.url.host == host and r.url.path != "/robots.txt"]

    def finder(self, root: Path, email: str | None = EMAIL, clock: Clock | None = None, **kw) -> CopyFinder:
        clock = clock or Clock()
        return CopyFinder(
            root,
            email,
            transport=httpx.MockTransport(self.handler),
            clock=clock.now,
            sleep=clock.sleep,
            now=clock.now,
            **kw,
        )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "cache"
    add_record(path)
    return path


def pdf_files(root: Path) -> list[Path]:
    folder = root / "unpaywall" / "pdf"
    return sorted(folder.glob("*")) if folder.is_dir() else []


# --- the cache key ----------------------------------------------------------


def test_cache_key_lowercases_and_percent_encodes_everything_outside_the_safe_set():
    assert cache_key("10.9999/Fictional.PDF(1);a") == "10.9999%2Ffictional.pdf%281%29%3Ba"
    assert cache_key("10.1000/a_b-c.d") == "10.1000%2Fa_b-c.d"
    assert cache_key("10.1/é") == "10.1%2F%C3%A9"


def test_cache_paths_use_the_key(tmp_path):
    cache = UnpaywallCache(tmp_path)
    key = cache_key(DOI)
    assert cache.answer_path(DOI) == tmp_path / "unpaywall" / f"{key}.json"
    assert cache.pdf_path(DOI) == tmp_path / "unpaywall" / "pdf" / f"{key}.pdf"
    assert cache.text_path(DOI).name == f"{key}.txt" and cache.meta_path(DOI).name == f"{key}.meta.json"


# --- the choice of location -------------------------------------------------


def test_locations_are_ordered_version_then_host_then_best_then_given_order():
    ranked = json.loads((FIX / "answer_ranked.json").read_text(encoding="utf-8"))
    urls = [item["url_for_pdf"] for item in unpaywall.choose_locations(ranked)]
    assert urls == [
        "https://publisher.example/paper.pdf",  # published, publisher
        "https://repo2.example/published.pdf",  # published, repository, is_best
        "https://repo3.example/published.pdf",  # published, repository
        "https://repo.example/accepted.pdf",  # accepted
    ]


def test_every_rejected_location_is_absent_from_the_ranked_answer():
    ranked = json.loads((FIX / "answer_ranked.json").read_text(encoding="utf-8"))
    urls = " ".join(item["url_for_pdf"] for item in unpaywall.choose_locations(ranked))
    assert "ncbi.nlm.nih.gov" not in urls and "europepmc.org" not in urls  # PMC and Europe PMC hosts
    assert "submitted" not in urls  # submittedVersion
    assert "embargoed" not in urls  # oa_locations_embargoed
    assert "landing-only" not in urls  # no url_for_pdf


@pytest.mark.parametrize(
    "url",
    [
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/pdf/x.pdf",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/pdf/x.pdf",
        "https://ncbi.nlm.nih.gov/x.pdf",
        "https://europepmc.org/articles/PMC1?pdf=render",
        "https://www.ebi.ac.uk/europepmc/x.pdf",
    ],
)
def test_pmc_and_europe_pmc_hosts_are_rejected(url):
    assert unpaywall.choose_locations(answer(loc(url))) == []


@pytest.mark.parametrize(
    "url",
    ["https://fakeebi.ac.uk/x.pdf", "https://ncbi.nlm.nih.gov.example/x.pdf", "https://europepmc.org.example/x.pdf"],
)
def test_a_host_that_only_looks_like_a_rejected_host_is_kept(url):
    assert [item["url_for_pdf"] for item in unpaywall.choose_locations(answer(loc(url)))] == [url]


def test_submitted_version_and_null_pdf_and_embargoed_are_rejected_one_by_one():
    assert unpaywall.choose_locations(answer(loc(PDF_A, version="submittedVersion"))) == []
    assert unpaywall.choose_locations(answer(loc(None))) == []
    embargoed = {"oa_locations": [], "oa_locations_embargoed": [loc(PDF_A)]}
    assert unpaywall.choose_locations(embargoed) == []
    assert unpaywall.choose_locations(answer(loc("not a url"))) == []
    assert unpaywall.choose_locations({"oa_locations": None}) == []


def test_is_best_decides_within_a_rank_and_otherwise_the_given_order():
    first, second = loc("https://a.example/1.pdf", host="repository"), loc("https://b.example/2.pdf", host="repository")
    assert [x["url_for_pdf"] for x in unpaywall.choose_locations(answer(first, second))] == [
        "https://a.example/1.pdf",
        "https://b.example/2.pdf",
    ]
    second["is_best"] = True
    assert [x["url_for_pdf"] for x in unpaywall.choose_locations(answer(first, second))] == [
        "https://b.example/2.pdf",
        "https://a.example/1.pdf",
    ]


# --- the lookup, the download, the cache -------------------------------------


def test_a_usable_copy_is_cached_with_its_meta_and_the_email_is_written_nowhere(root):
    world = World(answer(loc(PDF_A, license="cc-by")))
    world.serve(PDF_A, MAIN_PDF)
    finder = world.finder(root)
    result = finder.find(PMID)
    finder.close()
    assert result.ok and result.status == "ok" and not result.from_cache
    assert result.attempts == [(PDF_A, "ok")]
    key = cache_key(DOI)
    meta = json.loads((root / "unpaywall" / "pdf" / f"{key}.meta.json").read_text(encoding="utf-8"))
    assert meta["doi"] == DOI and meta["pmid"] == PMID and meta["pdf_url"] == PDF_A
    assert meta["final_url"] == PDF_A and meta["landing_page_url"] == PDF_A + "#landing"
    assert meta["host_type"] == "publisher" and meta["version"] == "publishedVersion" and meta["license"] == "cc-by"
    assert meta["sha256"] == hashlib.sha256(MAIN_PDF).hexdigest() and meta["fetched"] == "1970-01-01"
    assert meta["extractor"]["name"] == "pdfminer.six" and meta["extractor"]["version"]
    assert (root / "unpaywall" / "pdf" / f"{key}.pdf").read_bytes() == MAIN_PDF
    assert (root / "unpaywall" / "pdf" / f"{key}.txt").read_text(encoding="utf-8") == result.text
    assert (root / "unpaywall" / f"{key}.json").is_file()
    # the address went to Unpaywall (so this test means something) and into no file
    sent = world.requested("api.unpaywall.org")
    assert len(sent) == 1 and parse_qs(urlsplit(str(sent[0].url)).query)["email"] == [EMAIL]
    for path in (root / "unpaywall").rglob("*"):
        if path.is_file():
            assert EMAIL.encode() not in path.read_bytes(), path
    assert world.requested("publisher.example")[0].headers["user-agent"] == "me-atlas-research-client"
    assert "cookie" not in world.requested("publisher.example")[0].headers


def test_the_email_is_scrubbed_from_a_raw_answer_that_echoes_it(root):
    world = World({**answer(loc(PDF_A)), "echo": f"requested by {EMAIL}"})
    world.serve(PDF_A, MAIN_PDF)
    world.finder(root).find(PMID)
    assert EMAIL not in (root / "unpaywall" / f"{cache_key(DOI)}.json").read_text(encoding="utf-8")


def test_without_a_contact_email_nothing_is_requested(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, MAIN_PDF)
    result = world.finder(root, email=None).find(PMID)
    assert result.status == "no_contact_email" and not result.ok
    assert world.log == [] and not (root / "unpaywall").exists()


def test_without_a_contact_email_a_cached_pdf_is_still_read(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, MAIN_PDF)
    world.finder(root).find(PMID)
    world.log.clear()
    result = world.finder(root, email="").find(PMID)
    assert result.ok and result.from_cache and world.log == []


def test_a_record_without_a_doi_asks_nothing(tmp_path):
    root = tmp_path / "cache"
    add_record(root, doi=None)
    world = World(answer(loc(PDF_A)))
    result = world.finder(root).find(PMID)
    assert result.status == "no_doi" and world.log == []


def test_a_pmid_without_a_cached_record_asks_nothing(tmp_path):
    world = World(answer(loc(PDF_A)))
    result = world.finder(tmp_path / "cache").find(PMID)
    assert result.status == "no_pubmed_record" and world.log == []


def test_http_404_is_not_in_unpaywall(root):
    world = World(404)
    result = world.finder(root).find(PMID)
    assert result.status == "not_in_unpaywall" and not result.ok
    assert (root / "unpaywall" / f"{cache_key(DOI)}.json").is_file() and pdf_files(root) == []


def test_an_answer_without_a_pdf_copy_is_no_oa_pdf(root):
    world = World(answer(loc(None), loc(PDF_A, version="submittedVersion")))
    result = world.finder(root).find(PMID)
    assert result.status == "no_oa_pdf" and world.requested("publisher.example") == []


def test_a_server_error_is_reported_without_the_email(root):
    world = World(500)
    result = world.finder(root).find(PMID)
    assert result.status == "unpaywall_error" and EMAIL not in result.message


def test_a_cached_answer_is_reused_for_seven_days_then_asked_again_and_refresh_asks_at_once(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, b"<html>not a pdf</html>", content_type="text/html")  # no usable copy
    clock = Clock()
    world.finder(root, clock=clock).find(PMID)
    assert len(world.requested("api.unpaywall.org")) == 1
    path = root / "unpaywall" / f"{cache_key(DOI)}.json"
    os.utime(path, (clock.t, clock.t))
    clock.t += 6 * 86400
    world.finder(root, clock=clock).find(PMID)
    assert len(world.requested("api.unpaywall.org")) == 1  # still fresh: reused
    clock.t += 2 * 86400  # now 8 days old
    world.finder(root, clock=clock).find(PMID)
    assert len(world.requested("api.unpaywall.org")) == 2
    world.finder(root, clock=clock).find(PMID, refresh=True)
    assert len(world.requested("api.unpaywall.org")) == 3


def test_a_cached_pdf_is_not_requested_again_unless_refresh_is_given(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, MAIN_PDF)
    world.finder(root).find(PMID)
    count = len(world.log)
    again = world.finder(root).find(PMID)
    assert again.ok and again.from_cache and len(world.log) == count
    refreshed = world.finder(root).find(PMID, refresh=True)
    assert refreshed.ok and not refreshed.from_cache and len(world.log) > count


def test_the_rate_limit_is_one_request_a_second_to_unpaywall(root):
    world = World(500)  # three attempts in a row (the retries) must be a second apart or more
    clock = Clock()
    stamps: list[float] = []

    def stamping(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.unpaywall.org":
            stamps.append(clock.t)
        return world.handler(request)

    finder = CopyFinder(
        root, EMAIL, transport=httpx.MockTransport(stamping), clock=clock.now, sleep=clock.sleep, now=clock.now
    )
    finder.find(PMID)
    assert len(stamps) == 3 and all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:], strict=False))


# --- download negatives ------------------------------------------------------


def bad_html(world: World) -> None:
    world.serve(PDF_A, b"<html><body>Please log in</body></html>", content_type="text/html")


def forbidden(world: World) -> None:
    world.serve(PDF_A, b"no", status=403, content_type="text/html")


def disallowed(world: World) -> None:
    world.robots["publisher.example"] = "User-agent: *\nDisallow: /\n"
    world.serve(PDF_A, MAIN_PDF)


def too_big(world: World) -> None:
    world.serve(PDF_A, MAIN_PDF + b"0" * 5000)


@pytest.mark.parametrize(
    ("setup", "status"),
    [
        (bad_html, "not_pdf"),
        (forbidden, "blocked"),
        (disallowed, "robots_disallowed"),
        (too_big, "too_large"),
    ],
)
def test_a_download_that_is_not_a_usable_pdf_writes_nothing_under_pdf(root, monkeypatch, setup, status):
    monkeypatch.setattr(unpaywall, "MAX_PDF_BYTES", len(MAIN_PDF) + 100)
    world = World(answer(loc(PDF_A)))
    setup(world)
    result = world.finder(root).find(PMID)
    assert result.status == status and not result.ok
    assert result.attempts == [(PDF_A, status)]
    assert pdf_files(root) == []
    if status == "robots_disallowed":
        assert world.requested("publisher.example") == []  # the PDF itself was never requested


def test_an_html_page_with_status_200_is_not_a_pdf_even_under_a_pdf_content_type(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, b"<html>cookie wall</html>", content_type="application/pdf")
    assert world.finder(root).find(PMID).status == "not_pdf"


def test_the_next_location_is_tried_when_the_first_is_blocked(root):
    world = World(answer(loc(PDF_A), loc(PDF_B, version="acceptedVersion", host="repository")))
    world.serve(PDF_A, b"no", status=403, content_type="text/html")
    world.serve(PDF_B, MAIN_PDF)
    result = world.finder(root).find(PMID)
    assert result.ok and result.attempts == [(PDF_A, "blocked"), (PDF_B, "ok")]
    assert result.meta["pdf_url"] == PDF_B and result.meta["version"] == "acceptedVersion"
    assert result.meta["host_type"] == "repository"
    assert len(pdf_files(root)) == 3


def test_a_redirect_hop_is_checked_against_its_own_robots_file(root):
    world = World(answer(loc(PDF_A)))
    world.robots["other.example"] = "User-agent: *\nDisallow: /\n"

    def redirecting(request: httpx.Request) -> httpx.Response:
        if str(request.url) == PDF_A:
            world.log.append(request)
            return httpx.Response(302, headers={"location": "https://other.example/real.pdf"})
        return world.handler(request)

    world.serve("https://other.example/real.pdf", MAIN_PDF)
    clock = Clock()
    finder = CopyFinder(
        root, EMAIL, transport=httpx.MockTransport(redirecting), clock=clock.now, sleep=clock.sleep, now=clock.now
    )
    assert finder.find(PMID).status == "robots_disallowed"
    assert world.requested("other.example") == []


def test_a_pdf_of_another_title_is_not_used_and_nothing_is_cached(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, OTHER_PDF)
    result = world.finder(root).find(PMID)
    assert result.status == "title_not_found" and result.attempts == [(PDF_A, "title_not_found")]
    assert pdf_files(root) == []


def test_a_pdf_without_a_text_layer_is_no_text(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, SCAN_PDF)
    result = world.finder(root).find(PMID)
    assert result.status == "no_text" and pdf_files(root) == []


def test_a_damaged_pdf_is_not_used_and_nothing_is_cached(root):
    world = World(answer(loc(PDF_A)))
    world.serve(PDF_A, b"%PDF-1.4\nthis is not a pdf at all\n")
    result = world.finder(root).find(PMID)
    assert result.status in {"unreadable_pdf", "no_text"} and pdf_files(root) == []


# --- text, hyphens, ligatures, columns, references -----------------------------


def text_of(pdf: bytes) -> str:
    return unpaywall.clean_pages(unpaywall.extract_pdf_pages(pdf))[0]


def test_a_sentence_split_by_a_line_break_hyphen_inside_a_word_matches_joined():
    text = text_of(MAIN_PDF)
    assert unpaywall.LINE_BREAK_HYPHEN in text
    assert unpaywall.quote_in_pdf_text(QUOTE_HYPHEN, text)


def test_follow_up_split_at_its_hyphen_matches_with_the_hyphen():
    assert unpaywall.quote_in_pdf_text(QUOTE_FOLLOW_UP, text_of(MAIN_PDF))


def test_a_sentence_with_a_ligature_matches_with_plain_letters():
    pages = unpaywall.extract_pdf_pages(MAIN_PDF)
    assert "ﬁ" in pages[0]  # the PDF really holds the ligature glyph (U+FB01)
    text = unpaywall.clean_pages(pages)[0]
    assert "ﬁ" not in text and unpaywall.quote_in_pdf_text(QUOTE_LIGATURE, text)


def test_a_sentence_from_the_second_column_matches():
    text = text_of(TWO_COLUMN_PDF)
    assert unpaywall.quote_in_pdf_text(QUOTE_COLUMN, text)
    assert unpaywall.quote_page(QUOTE_COLUMN, text) == 1


def test_a_quote_with_one_changed_word_does_not_match():
    text = text_of(MAIN_PDF)
    assert not unpaywall.quote_in_pdf_text(QUOTE_FOLLOW_UP.replace("two", "three"), text)
    assert not unpaywall.quote_in_pdf_text(QUOTE_HYPHEN.replace("Fukuda", "Fukada"), text)
    assert not unpaywall.quote_in_pdf_text("", text)


def test_a_quote_that_lies_only_in_the_cut_reference_list_does_not_match():
    pages = unpaywall.extract_pdf_pages(MAIN_PDF)
    assert QUOTE_REFERENCE in " ".join(pages[1].split())  # it is in the PDF ...
    text, cut = unpaywall.clean_pages(pages)
    assert cut is True and not unpaywall.quote_in_pdf_text(QUOTE_REFERENCE, text)  # ... but not in the text


def test_the_page_number_is_that_of_the_page_holding_the_quote():
    text = text_of(MAIN_PDF)
    assert unpaywall.quote_page(QUOTE_LIGATURE, text) == 1
    assert unpaywall.quote_page("Nothing real was measured in this invented paper at all.", text) == 2


def test_a_sentence_broken_by_a_page_break_does_not_match():
    text, _ = unpaywall.clean_pages(["Fictional text that ends in the middle of a", "sentence and goes on. More."])
    assert unpaywall.quote_in_pdf_text("ends in the middle of a", text)
    assert not unpaywall.quote_in_pdf_text("ends in the middle of a sentence and goes on.", text)


def test_a_reference_heading_in_the_first_half_is_not_cut():
    body = "Fictional body sentence. " * 30
    text, cut = unpaywall.clean_pages([f"References\nsee list\n{body}"])
    assert cut is False and "Fictional body sentence." in text


def test_the_last_reference_heading_is_the_cut_and_only_a_heading_line_counts():
    body = "Fictional body sentence. " * 10
    pages = [f"{body}\nReferences\nolder list entry", f"{body}\nBibliography\ncited entry\nMore about References here"]
    text, cut = unpaywall.clean_pages(pages)
    assert cut and "cited entry" not in text and "older list entry" in text
    text2, cut2 = unpaywall.clean_pages([f"{body}\nLiterature Cited\nentry one"])
    assert cut2 and "entry one" not in text2
    text3, cut3 = unpaywall.clean_pages([f"{body}\nThe references are discussed below.\nstill body"])
    assert not cut3 and "still body" in text3


def test_soft_hyphens_ligatures_and_numeric_hyphens():
    raw = "Fu­\nkuda criteria and ca­se. Years 2019-\n2020 and ab-\ncd and ﬁne"
    text, _ = unpaywall.clean_pages([raw])
    assert "Fukuda criteria and case." in text and "2019- 2020" in text and "fine" in text
    assert text.count(unpaywall.LINE_BREAK_HYPHEN) == 1  # only "ab-|cd": a hyphen between letters


def test_an_empty_or_scanned_text_has_no_text_layer():
    assert not unpaywall.has_text_layer("")
    assert not unpaywall.has_text_layer(text_of(SCAN_PDF))
    assert unpaywall.has_text_layer(text_of(MAIN_PDF))


def test_the_title_check_reads_only_the_first_two_pages_and_ignores_case_and_punctuation():
    text, _ = unpaywall.clean_pages(["Cover", "Fictional: study", "Fictional Title Of A Paper"])
    assert unpaywall.title_in_first_pages("Fictional Title of a PAPER.", "Fictional Title of\fa paper y\fmore")
    assert not unpaywall.title_in_first_pages("Fictional Title Of A Paper", text)  # only on page 3
    assert unpaywall.title_in_first_pages(TITLE, text_of(MAIN_PDF))
    assert not unpaywall.title_in_first_pages("", text_of(MAIN_PDF))


def test_candidates_carry_page_numbers_and_their_sentences_match():
    text, _ = unpaywall.clean_pages(
        ["Intro text here.", "Patients met the Fukuda criteria. Patients with CFS were excluded from the study."]
    )
    found = unpaywall.pdf_candidates(text)
    assert {(n, c.kind) for n, c in found} == {(2, "definition"), (2, "exclusion")}
    assert all(unpaywall.quote_in_pdf_text(c.sentence, text) for _, c in found)
    main = text_of(MAIN_PDF)
    assert any("Fukuda" in c.sentence and n == 1 for n, c in unpaywall.pdf_candidates(main))
    assert all(unpaywall.quote_in_pdf_text(c.sentence, main) for _, c in unpaywall.pdf_candidates(main))
    assert unpaywall.pdf_candidates("Nothing relevant on this page.") == []
