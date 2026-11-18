"""Tests for the data-resource catalogue (me_atlas.resources). Recorded fictional pages in
tests/fixtures/resources/; no network, no LLM, no sleeping."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
import yaml

from me_atlas import resources
from me_atlas.resources import USER_AGENT

REAL_FETCHER = resources.Fetcher

FIX = Path(__file__).parent / "fixtures" / "resources"
DAY = "2026-11-18"
HOST = "https://example.test"
MAIN = f"{HOST}/biobank"
ACCESS = f"{HOST}/biobank/access"
HTML = "text/html; charset=utf-8"


def fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


def page(name: str, content_type: str = HTML, status: int = 200, headers: dict | None = None):
    return (status, content_type, fixture(name), headers or {})


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def make_fetcher(routes: dict, clock: Clock | None = None, log: list | None = None) -> resources.Fetcher:
    """A fetcher over a mock server. ``routes`` maps a URL to (status, content type, body, headers); a URL not in it
    answers 404. ``log`` collects (clock time, URL) per request."""
    clock = clock or Clock()

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if log is not None:
            log.append((clock(), url))
        if isinstance(routes.get(url), Exception):
            raise routes[url]
        if url not in routes:
            return httpx.Response(404, text="not found")
        status, content_type, body, headers = routes[url]
        return httpx.Response(status, content=body, headers={"content-type": content_type, **headers})

    client = httpx.Client(transport=httpx.MockTransport(handle), headers={"User-Agent": USER_AGENT})
    return REAL_FETCHER(client, clock=clock, sleep=clock.sleep, max_retries=1, backoff=0.0)


def main_text() -> str:
    return resources.extract_text(fixture("good-main.html").decode())


# --- text --------------------------------------------------------------------------------------------------------


def test_extract_text_keeps_visible_text_drops_script_style_and_head_and_collapses_whitespace():
    text = main_text()
    assert text.startswith("Home Fictional ME/CFS Biobank The Fictional ME/CFS Biobank is operated by")
    assert "script text" not in text and "style text" not in text and "hidden title" not in text
    assert "  " not in text and "\n" not in text
    assert "Open download of summary tables is possible" in text  # &nbsp; became a space


def test_quote_is_found_after_nfkc_quote_folding_and_whitespace_collapsing():
    text = main_text()
    assert resources.quote_in_text('by "registering an account" on the portal', text)  # straight vs curly quotes
    assert resources.quote_in_text("blood   samples\nand questionnaire", text)
    assert resources.quote_in_text("ＭＥ/CFS", "ME/CFS")  # full-width letters fold under NFKC


def test_a_quote_with_one_word_changed_or_missing_is_not_found():
    text = main_text()
    assert resources.quote_in_text("blood samples and questionnaire data", text)
    assert not resources.quote_in_text("blood samples and interview data", text)
    assert not resources.quote_in_text("blood samples questionnaire data", text)
    assert not resources.quote_in_text("", text)


# --- leads (F1) --------------------------------------------------------------------------------------------------


def test_the_real_leads_file_is_valid():
    resources.load_leads(Path("registry/resource-leads.yaml"))


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        ({"leads": [{"id": "a", "url": MAIN, "name": "A name"}]}, "unknown field(s) name"),
        ({"leads": [{"id": "a", "url": MAIN, "description": "x"}]}, "unknown field(s) description"),
        ({"leads": [{"id": "Not A Slug", "url": MAIN}]}, "kebab-case"),
        ({"leads": [{"id": "a", "url": MAIN}, {"id": "a", "url": MAIN}]}, "duplicate id"),
        ({"leads": [{"id": "a", "url": "ftp://x"}]}, "url must be an http"),
        ({"leads": [{"id": "a", "url": MAIN, "access_url": "nowhere"}]}, "access_url must be an http"),
        ({"leads": [{"id": "a"}]}, "url must be an http"),
        ({"leads": {}}, "one key"),
        ({"leads": [], "extra": 1}, "one key"),
    ],
)
def test_a_leads_file_with_extra_fields_or_bad_values_is_refused(data, problem):
    assert any(problem in p for p in resources.check_leads(data))


def test_leads_load_with_and_without_an_access_page(tmp_path):
    path = tmp_path / "leads.yaml"
    leads = [{"id": "a", "url": MAIN, "access_url": ACCESS}, {"id": "b", "url": ACCESS}]
    path.write_text(yaml.safe_dump({"leads": leads}))
    loaded = resources.load_leads(path)
    assert resources.page_urls(loaded[0]) == {"main": MAIN, "access": ACCESS}
    assert resources.page_urls(loaded[1]) == {"main": ACCESS}


# --- fetch: statuses (F5), each from a recorded fixture ----------------------------------------------------------


def fetch_status(routes: dict, url: str = MAIN, **kw):
    return make_fetcher(routes, **kw).fetch(url)


def test_a_good_page_is_ok_and_carries_the_text():
    got = fetch_status({MAIN: page("good-main.html")})
    assert got.status == "ok" and got.http_status == 200 and got.final_url == MAIN
    assert "Imaginary Institute" in got.text


def test_status_http_code_for_a_missing_page():
    assert fetch_status({}).status == "http_404"


def test_status_http_code_for_a_server_error_after_the_retry():
    log: list = []
    got = fetch_status({MAIN: (503, HTML, b"down", {})}, log=log)
    assert got.status == "http_503"
    assert [u for _, u in log].count(MAIN) == 2  # one retry (max_retries=1), then it gives up


def test_status_not_html():
    got = fetch_status({MAIN: (200, "application/json", fixture("data.json"), {})})
    assert got.status == "not_html"


def test_status_no_text_for_a_page_with_less_than_200_characters():
    assert fetch_status({MAIN: page("short.html")}).status == "no_text"


@pytest.mark.parametrize("code", [401, 403, 429])
def test_status_blocked_for_an_http_refusal(code):
    assert fetch_status({MAIN: (code, HTML, b"no", {})}).status == "blocked"


@pytest.mark.parametrize("name", ["captcha.html", "login.html"])
def test_status_blocked_for_a_bot_check_or_a_login_page_even_with_http_200(name):
    got = fetch_status({MAIN: page(name)})
    assert got.status == "blocked" and got.http_status == 200


def test_css_and_form_settings_in_the_source_do_not_make_a_real_page_blocked():
    # the raw body holds input[type="password"]:focus, a recaptcha class and a captcha setting; the text is real
    html = fixture("css-and-recaptcha.html").decode()
    assert "recaptchaSiteKey" in html and 'input[type="password"]' in html
    got = fetch_status({MAIN: page("css-and-recaptcha.html")})
    assert got.status == "ok"


def test_a_long_page_that_says_just_a_moment_in_its_text_is_not_blocked_but_a_short_one_is():
    body = (
        "<html><body><p>"
        + "Real text about a fictional register. " * 40
        + "Wait just a moment, please.</p></body></html>"
    ).encode()
    assert fetch_status({MAIN: (200, HTML, body, {})}).status == "ok"


def test_a_real_password_input_on_a_short_page_is_blocked_but_not_on_a_long_page():
    form = "<form><input type='PASSWORD' name='pw'></form>"
    short = f"<html><body><p>{'Members only. ' * 20}</p>{form}</body></html>".encode()
    assert fetch_status({MAIN: (200, HTML, short, {})}).status == "blocked"
    long = f"<html><body><p>{'Plenty of real text on this page. ' * 40}</p>{form}</body></html>".encode()
    assert fetch_status({MAIN: (200, HTML, long, {})}).status == "ok"


def test_status_network_error():
    got = fetch_status({MAIN: httpx.ConnectError("refused")})
    assert got.status == "network_error"


def test_a_blocked_page_is_not_retried_with_other_headers():
    log: list = []
    fetch_status({MAIN: (403, HTML, b"no", {})}, log=log)
    assert [u for _, u in log].count(MAIN) == 1


# --- fetch: robots (F3) ------------------------------------------------------------------------------------------


def test_robots_disallowed_means_the_page_is_not_requested():
    log: list = []
    robots = (200, "text/plain", fixture("robots-disallow.txt"), {})
    got = fetch_status({f"{HOST}/robots.txt": robots, MAIN: page("good-main.html")}, log=log)
    assert got.status == "robots_disallowed" and got.body is None
    assert MAIN not in [u for _, u in log]


def test_robots_allow_rules_are_read_for_the_generic_user_agent():
    robots = (200, "text/plain", fixture("robots-allow.txt"), {})
    routes = {f"{HOST}/robots.txt": robots, MAIN: page("good-main.html"), f"{HOST}/private/x": page("good-main.html")}
    fetcher = make_fetcher(routes)
    assert fetcher.fetch(MAIN).status == "ok"
    assert fetcher.fetch(f"{HOST}/private/x").status == "robots_disallowed"


def test_robots_missing_with_a_4xx_means_allowed():
    routes = {f"{HOST}/robots.txt": (404, "text/plain", b"", {}), MAIN: page("good-main.html")}
    assert fetch_status(routes).status == "ok"
    routes = {f"{HOST}/robots.txt": (403, "text/plain", b"", {}), MAIN: page("good-main.html")}
    assert fetch_status(routes).status == "ok"


def test_robots_unavailable_on_a_5xx_or_a_network_error_means_not_fetched():
    log: list = []
    routes = {f"{HOST}/robots.txt": (500, "text/plain", b"", {}), MAIN: page("good-main.html")}
    got = fetch_status(routes, log=log)
    assert got.status == "robots_unavailable" and MAIN not in [u for _, u in log]
    routes = {f"{HOST}/robots.txt": httpx.ConnectError("refused"), MAIN: page("good-main.html")}
    assert fetch_status(routes).status == "robots_unavailable"


def test_a_robots_redirect_is_followed_and_the_final_file_is_parsed():
    routes = {
        f"{HOST}/robots.txt": (301, "text/plain", b"", {"location": "https://other.test/robots.txt"}),
        "https://other.test/robots.txt": (200, "text/plain", fixture("robots-allow.txt"), {}),
        MAIN: page("good-main.html"),
        f"{HOST}/private/x": page("good-main.html"),
    }
    fetcher = make_fetcher(routes)
    assert fetcher.fetch(MAIN).status == "ok"
    assert fetcher.fetch(f"{HOST}/private/x").status == "robots_disallowed"  # the redirected file's rules apply


def test_a_robots_redirect_loop_or_too_many_hops_is_robots_unavailable():
    loop = {
        f"{HOST}/robots.txt": (301, "text/plain", b"", {"location": f"{HOST}/robots.txt"}),
        MAIN: page("good-main.html"),
    }
    assert fetch_status(loop).status == "robots_unavailable"
    chain = {f"{HOST}/robots.txt": (301, "text/plain", b"", {"location": f"{HOST}/r1"}), MAIN: page("good-main.html")}
    for i in range(1, 8):
        chain[f"{HOST}/r{i}"] = (301, "text/plain", b"", {"location": f"{HOST}/r{i + 1}"})
    chain[f"{HOST}/r8"] = (200, "text/plain", b"", {})
    assert fetch_status(chain).status == "robots_unavailable"


def test_a_redirect_is_followed_and_the_target_host_robots_file_is_respected():
    other = "https://other.test"
    routes = {
        MAIN: (301, HTML, b"", {"location": f"{other}/moved"}),
        f"{other}/moved": page("good-main.html"),
    }
    got = fetch_status(routes)
    assert got.status == "ok" and got.final_url == f"{other}/moved"
    routes[f"{other}/robots.txt"] = (200, "text/plain", fixture("robots-disallow.txt"), {})
    assert fetch_status(routes).status == "robots_disallowed"


def test_at_most_one_request_a_second_per_host_and_hosts_are_independent():
    clock = Clock()
    log: list = []
    other = "https://other.test"
    routes = {MAIN: page("good-main.html"), ACCESS: page("good-access.html"), f"{other}/p": page("good-main.html")}
    fetcher = make_fetcher(routes, clock=clock, log=log)
    for url in (MAIN, ACCESS, f"{other}/p"):
        assert fetcher.fetch(url).status == "ok"
    mine = [t for t, u in log if u.startswith(HOST)]
    assert len(mine) == 3  # robots.txt and the two pages
    assert all(b - a >= 1.0 for a, b in zip(mine, mine[1:], strict=False))
    theirs = [t for t, u in log if u.startswith(other)]
    assert theirs[0] == mine[-1]  # the other host did not have to wait for the first one's quota


def test_the_default_client_sends_the_generic_user_agent_and_keeps_no_cookies():
    fetcher = REAL_FETCHER()
    try:
        assert fetcher.http.headers["user-agent"] == USER_AGENT == "me-atlas-research-client"
        assert "@" not in USER_AGENT and "cookie" not in {k.lower() for k in fetcher.http.headers}
    finally:
        fetcher.close()


# --- fetch: the store (F4, F6) -----------------------------------------------------------------------------------


LEADS = [
    {"id": "fictional-biobank", "url": MAIN, "access_url": ACCESS},
    {"id": "fictional-register", "url": f"{HOST}/register"},
    {"id": "fictional-blocked", "url": f"{HOST}/blocked"},
    {"id": "fictional-half", "url": f"{HOST}/half", "access_url": f"{HOST}/half-access"},
]


def all_routes() -> dict:
    return {
        MAIN: page("good-main.html"),
        ACCESS: page("good-access.html"),
        f"{HOST}/register": page("register-main.html"),
        f"{HOST}/blocked": page("captcha.html"),
        f"{HOST}/half": page("good-main.html"),
        # /half-access answers 404
    }


def do_fetch(tmp_path, fetcher=None):
    out = tmp_path / "pipeline" / DAY / "resources"
    fetcher = fetcher or make_fetcher(all_routes())
    report = resources.run_fetch(LEADS, tmp_path / "cache", out, day=DAY, fetcher=fetcher)
    return report, out


def test_fetch_stores_raw_body_meta_and_text_before_anything_reads_them(tmp_path):
    do_fetch(tmp_path)
    d = tmp_path / "cache" / DAY / "fictional-biobank"
    assert (d / "main.html").read_bytes() == fixture("good-main.html")
    assert (d / "access.html").read_bytes() == fixture("good-access.html")
    meta = json.loads((d / "main.meta.json").read_text(encoding="utf-8"))
    assert meta == {
        "requested_url": MAIN,
        "final_url": MAIN,
        "http_status": 200,
        "content_type": HTML,
        "fetched": DAY,
        "status": "ok",
    }
    assert (d / "main.txt").read_text(encoding="utf-8") == main_text()
    assert not (tmp_path / "cache" / DAY / "fictional-register" / "access.html").exists()


def test_the_report_names_the_status_of_every_page_and_lists_the_fetchable_leads(tmp_path):
    report, out = do_fetch(tmp_path)
    assert json.loads((out / "fetch-report.json").read_text(encoding="utf-8")) == report
    assert report["leads"] == {
        "fictional-biobank": {"main": "ok", "access": "ok"},
        "fictional-register": {"main": "ok"},
        "fictional-blocked": {"main": "blocked"},
        "fictional-half": {"main": "ok", "access": "http_404"},
    }
    assert report["fetchable"] == ["fictional-biobank", "fictional-register"]  # a bad access page blocks the lead


def test_offline_with_the_cache_present_makes_no_request_and_gives_the_same_report(tmp_path):
    report, out = do_fetch(tmp_path)
    log: list = []
    fetcher = make_fetcher({}, log=log)
    again = resources.run_fetch(LEADS, tmp_path / "cache", out, day=DAY, offline=True, fetcher=fetcher)
    assert log == [] and again == report


def test_offline_without_a_cached_page_says_not_cached(tmp_path):
    out = tmp_path / "out"
    report = resources.run_fetch(LEADS[:1], tmp_path / "cache", out, day=DAY, offline=True)
    assert report["leads"] == {"fictional-biobank": {"main": "not_cached", "access": "not_cached"}}
    assert report["fetchable"] == []


# --- plan (A1) ---------------------------------------------------------------------------------------------------


def test_plan_writes_a_context_file_per_fetchable_lead_with_the_stored_text(tmp_path):
    _, out = do_fetch(tmp_path)
    written = resources.run_plan(LEADS, tmp_path / "cache", out, day=DAY)
    assert [p.name for p in written] == ["context-fictional-biobank.json", "context-fictional-register.json"]
    ctx = json.loads(written[0].read_text(encoding="utf-8"))
    assert ctx == {
        "id": "fictional-biobank",
        "url": MAIN,
        "access_url": ACCESS,
        "fetched": DAY,
        "pages": {
            "main": main_text(),
            "access": resources.extract_text(fixture("good-access.html").decode()),
        },
    }
    assert json.loads(written[1].read_text(encoding="utf-8"))["access_url"] is None


def test_plan_without_a_fetch_report_fails(tmp_path):
    with pytest.raises(resources.ResourcesError, match="no fetch report"):
        resources.run_plan(LEADS, tmp_path / "cache", tmp_path / "nowhere", day=DAY)


def test_plan_changed_skips_leads_whose_stored_text_is_the_text_the_entry_was_drafted_from(tmp_path):
    _, out = do_fetch(tmp_path)
    first = resources.run_plan(LEADS, tmp_path / "cache", out, day=DAY)[0]
    data = {"checked": DAY, "entries": [resources.build_entry(json.loads(first.read_text("utf-8")), good_draft())]}
    same = resources.run_plan(LEADS, tmp_path / "cache", out, day=DAY, data=data, changed_only=True)
    assert [p.name for p in same] == ["context-fictional-register.json"]  # the register has no entry yet: new
    # the page changes: the next fetch stores other text, and that lead is planned again
    routes = {**all_routes(), MAIN: page("good-main-changed.html")}
    new_out = tmp_path / "pipeline2"
    later = "2027-02-18"
    resources.run_fetch(LEADS, tmp_path / "cache2", new_out, day=later, fetcher=make_fetcher(routes))
    got = resources.run_plan(LEADS, tmp_path / "cache2", new_out, day=later, data=data, changed_only=True)
    assert "context-fictional-biobank.json" in [p.name for p in got]


# --- drafts (A2, A3) ---------------------------------------------------------------------------------------------


def context() -> dict:
    return {
        "id": "fictional-biobank",
        "url": MAIN,
        "access_url": ACCESS,
        "fetched": DAY,
        "pages": {
            "main": main_text(),
            "access": resources.extract_text(fixture("good-access.html").decode()),
        },
    }


def q(value, quote, page_key="main") -> dict:
    return {"value": value, "quote": quote, "page": page_key}


def good_draft() -> dict:
    return {
        "id": "fictional-biobank",
        "include": True,
        "language": "en",
        "category": "data",
        "name": q("Fictional ME/CFS Biobank", "The Fictional ME/CFS Biobank is operated by"),
        "operator": q("Imaginary Institute of Medicine", "operated by the Imaginary Institute of Medicine"),
        "countries": q(["Freedonia"], "Institute of Medicine in Freedonia"),
        "holds": [
            q("biospecimens", "It holds blood samples"),
            q("questionnaires", "questionnaire data from people with ME/CFS"),
        ],
        "access": q("application", "granted by application to the Fictional Biobank steering committee", "access"),
        "covers": q("me_cfs", "people with ME/CFS diagnosed under the Canadian Consensus Criteria"),
    }


def good_exclusion() -> dict:
    return {
        "id": "fictional-biobank",
        "include": False,
        "reason": "no_outside_access",
        "quote": "Researchers outside the Imaginary Institute can obtain access",
        "page": "main",
    }


def problems_of(draft) -> list[str]:
    return resources.validate_draft(draft, context())


def test_a_good_entry_draft_and_a_good_exclusion_have_no_problems():
    assert problems_of(good_draft()) == []
    assert problems_of(good_exclusion()) == []


def test_a_value_the_page_does_not_state_is_not_stated_with_an_empty_quote():
    draft = good_draft()
    draft["operator"] = q("not_stated", "")
    draft["countries"] = q("not_stated", "")
    assert problems_of(draft) == []


def mutate(draft, path: list, value):
    draft = copy.deepcopy(draft)
    node = draft
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return draft


NEGATIVE = {
    "unknown category": (mutate(good_draft(), ["category"], "dataset"), "category: unknown value"),
    "unknown access": (mutate(good_draft(), ["access", "value"], "free"), "access.value: unknown value"),
    "unknown covers": (mutate(good_draft(), ["covers", "value"], "long_covid"), "covers.value: unknown value"),
    "not_stated covers": (mutate(good_draft(), ["covers"], q("not_stated", "")), "covers.value: unknown value"),
    "unknown holds": (mutate(good_draft(), ["holds", 0, "value"], "imaging"), "holds[0].value: unknown value"),
    "unknown reason": (mutate(good_exclusion(), ["reason"], "too_small"), "reason: unknown value"),
    "bad language": (mutate(good_draft(), ["language"], "eng"), "language: must be a two-letter"),
    "page not in context": (mutate(good_draft(), ["name", "page"], "elsewhere"), "name.page"),
    "exclusion page not in context": (mutate(good_exclusion(), ["page"], "elsewhere"), "exclusion.page"),
    "empty quote for a stated value": (mutate(good_draft(), ["operator", "quote"], ""), "operator.quote"),
    "quote for a not_stated value": (
        mutate(good_draft(), ["operator"], q("not_stated", "operated by")),
        "operator.quote: a 'not_stated' value has an empty quote",
    ),
    "exclusion without quote": (mutate(good_exclusion(), ["quote"], ""), "exclusion.quote"),
    "quote absent by one word": (
        mutate(good_draft(), ["holds", 0, "quote"], "It holds blood samples and tissue"),
        "holds[0].quote: not found",
    ),
    "quote on the wrong page": (mutate(good_draft(), ["access", "page"], "main"), "access.quote: not found"),
    "register with holds": (mutate(good_draft(), ["category"], "register"), "a register has no holds"),
    "data without holds": (mutate(good_draft(), ["holds"], []), "a data entry needs at least one holds value"),
    "data with access not_stated": (
        mutate(good_draft(), ["access"], q("not_stated", "")),
        "a data entry needs a stated access",
    ),
    "not_stated name": (mutate(good_draft(), ["name"], q("not_stated", "")), "name: an entry needs a stated name"),
    "repeated holds": (
        mutate(good_draft(), ["holds", 1], q("biospecimens", "It holds blood samples")),
        "listed twice",
    ),
    "empty countries list": (mutate(good_draft(), ["countries", "value"], []), "countries.value"),
    "countries not a list": (mutate(good_draft(), ["countries", "value"], "Freedonia"), "countries.value"),
    "wrong id": (mutate(good_draft(), ["id"], "other"), "id is 'other'"),
    "include missing": ({k: v for k, v in good_draft().items() if k != "include"}, "include must be true or false"),
}


@pytest.mark.parametrize("case", sorted(NEGATIVE))
def test_a_draft_with_this_fault_is_refused_naming_the_id_and_field(case):
    draft, expected = NEGATIVE[case]
    found = problems_of(draft)
    assert any(expected in p for p in found), found
    assert all(p.startswith(("fictional-biobank", "other")) for p in found)


def test_a_missing_or_an_extra_key_is_refused():
    draft = good_draft()
    del draft["covers"]
    assert any("missing key(s) covers" in p for p in problems_of(draft))
    draft = good_draft()
    draft["summary"] = "a free-text sentence about the resource"
    assert any("extra key(s) summary" in p for p in problems_of(draft))
    value = good_draft()
    value["name"]["note"] = "x"
    assert any("name: extra key(s) note" in p for p in problems_of(value))
    exclusion = good_exclusion()
    exclusion["extra"] = 1
    assert any("extra key(s) extra" in p for p in problems_of(exclusion))


# --- record-draft / record-review (A3, A4, A5) -------------------------------------------------------------------


def write_run(base: Path, drafts: dict, reviews: dict, contexts=None) -> Path:
    run = base / "run"
    run.mkdir(parents=True)
    for lid in contexts if contexts is not None else drafts:
        (run / f"context-{lid}.json").write_text(json.dumps(context() | {"id": lid}), encoding="utf-8")
    for lid, draft in drafts.items():
        (run / f"draft-{lid}.json").write_text(json.dumps(draft), encoding="utf-8")
    for lid, review in reviews.items():
        (run / f"review-{lid}.json").write_text(json.dumps(review), encoding="utf-8")
    return run


def accept(lid: str) -> dict:
    return {"id": lid, "verdict": "accept"}


def reject(lid: str) -> dict:
    return {"id": lid, "verdict": "reject", "finding": "The quote does not support the value."}


def named(draft: dict, lid: str) -> dict:
    return {**copy.deepcopy(draft), "id": lid}


def test_record_draft_accepts_valid_drafts(tmp_path):
    run = write_run(tmp_path, {"b-res": named(good_draft(), "b-res"), "a-res": named(good_exclusion(), "a-res")}, {})
    assert resources.record_draft(run) == []


def test_record_draft_names_the_id_and_field_of_an_invalid_draft(tmp_path):
    bad = named(good_draft(), "c-res")
    bad["holds"][0]["quote"] = "It holds blood samples and tissue"
    found = resources.record_draft(write_run(tmp_path, {"c-res": bad}, {}))
    assert found and found[0].startswith("c-res: holds[0].quote")


def test_record_draft_exits_non_zero_on_the_command_line(tmp_path, capsys):
    bad = named(good_draft(), "c-res")
    bad["category"] = "dataset"
    run = write_run(tmp_path, {"c-res": bad}, {})
    assert resources.main(["record-draft", "--run", str(run)]) == 1
    assert "c-res: category: unknown value" in capsys.readouterr().err


def test_record_draft_reports_a_context_without_a_draft_and_an_empty_run(tmp_path):
    run = write_run(tmp_path, {}, {}, contexts=["a-res"])
    assert any("a-res: the draft file" in p for p in resources.record_draft(run))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert resources.record_draft(empty) == [f"{empty}: no context files"]


def test_record_review_writes_only_accepted_inclusions_sorted_with_the_code_added_fields(tmp_path):
    drafts = {
        "z-res": named(good_draft(), "z-res"),
        "m-res": named(good_exclusion(), "m-res"),
        "a-res": named(good_draft(), "a-res"),
        "r-res": named(good_draft(), "r-res"),
    }
    reviews = {"z-res": accept("z-res"), "m-res": accept("m-res"), "a-res": accept("a-res"), "r-res": reject("r-res")}
    new, problems = resources.record_review(None, write_run(tmp_path, drafts, reviews), DAY)
    assert problems == []
    assert [e["id"] for e in new["entries"]] == ["a-res", "z-res"]  # the exclusion and the reject are not written
    assert new["checked"] == DAY
    entry = new["entries"][0]
    assert entry["url"] == MAIN and entry["access_url"] == ACCESS and entry["checked"] == DAY
    assert entry["source"] == [MAIN, ACCESS]  # the quotes come from both pages
    assert entry["text_hash"] == {k: resources.text_hash(t) for k, t in context()["pages"].items()}
    assert entry["holds"] == ["biospecimens", "questionnaires"]
    assert entry["quotes"]["access"] == {
        "quote": "granted by application to the Fictional Biobank steering committee",
        "page": "access",
    }
    assert entry["quotes"]["holds"]["biospecimens"] == {"quote": "It holds blood samples", "page": "main"}
    assert resources.check_data(new) == []


def test_record_review_refuses_a_reject_without_a_finding_and_writes_nothing(tmp_path):
    run = write_run(
        tmp_path,
        {"a-res": named(good_draft(), "a-res"), "b-res": named(good_draft(), "b-res")},
        {"a-res": accept("a-res"), "b-res": {"id": "b-res", "verdict": "reject"}},
    )
    old = {"checked": "2026-01-01", "entries": []}
    new, problems = resources.record_review(old, run, DAY)
    assert any("b-res: a reject needs a finding" in p for p in problems)
    assert new == old


@pytest.mark.parametrize(
    ("review", "problem"),
    [
        ({"id": "a-res", "verdict": "accept", "finding": "x"}, "an accept has no finding"),
        ({"id": "a-res", "verdict": "maybe"}, "verdict must be"),
        ({"id": "a-res", "verdict": "accept", "note": "x"}, "extra key(s) note"),
        ({"id": "other", "verdict": "accept"}, "id is 'other'"),
    ],
)
def test_a_malformed_review_is_refused(tmp_path, review, problem):
    run = write_run(tmp_path, {"a-res": named(good_draft(), "a-res")}, {"a-res": review})
    assert any(problem in p for p in resources.record_review(None, run, DAY)[1])


def test_record_review_needs_a_review_for_every_draft(tmp_path):
    run = write_run(tmp_path, {"a-res": named(good_draft(), "a-res")}, {})
    assert any("a-res: the review file" in p for p in resources.record_review(None, run, DAY)[1])


def test_record_review_revalidates_the_quotes_even_for_an_accepted_draft(tmp_path):
    bad = named(good_draft(), "a-res")
    bad["name"]["quote"] = "The Fictional ME/CFS Biobank is run by"
    run = write_run(tmp_path, {"a-res": bad}, {"a-res": accept("a-res")})
    assert any("a-res: name.quote: not found" in p for p in resources.record_review(None, run, DAY)[1])


def test_a_rejected_redraft_keeps_the_old_entry_and_an_accepted_exclusion_removes_it(tmp_path):
    old_entry = resources.build_entry(context() | {"id": "a-res"}, named(good_draft(), "a-res"))
    old_entry["name"] = "Old name"
    other = resources.build_entry(context() | {"id": "b-res"}, named(good_draft(), "b-res"))
    old = {"checked": "2026-08-18", "entries": [old_entry, other]}
    run = write_run(tmp_path / "one", {"a-res": named(good_draft(), "a-res")}, {"a-res": reject("a-res")})
    new, problems = resources.record_review(old, run, DAY)
    assert problems == [] and new["entries"][0]["name"] == "Old name" and len(new["entries"]) == 2
    run2 = write_run(tmp_path / "two", {"a-res": named(good_exclusion(), "a-res")}, {"a-res": accept("a-res")})
    new, problems = resources.record_review(old, run2, DAY)
    assert problems == [] and [e["id"] for e in new["entries"]] == ["b-res"]


def test_record_review_command_writes_the_data_file_atomically(tmp_path):
    run = write_run(tmp_path, {"a-res": named(good_draft(), "a-res")}, {"a-res": accept("a-res")})
    path = tmp_path / "resources.yaml"
    assert resources.main(["--data-file", str(path), "record-review", "--run", str(run)]) == 0
    assert [e["id"] for e in resources.load_data(path)["entries"]] == ["a-res"]
    assert not list(tmp_path.glob("*.tmp"))


# --- reliability (A6) --------------------------------------------------------------------------------------------


def reliability_run(tmp_path, total: int, rejects: int, excluded: int = 0) -> Path:
    drafts, reviews = {}, {}
    for i in range(total):
        lid = f"res-{i:02d}"
        drafts[lid] = named(good_exclusion() if i < excluded else good_draft(), lid)
        reviews[lid] = reject(lid) if i >= total - rejects else accept(lid)
    return write_run(tmp_path, drafts, reviews)


@pytest.mark.parametrize(
    ("total", "rejects", "passed"),
    [(14, 3, False), (15, 3, True), (10, 2, True), (5, 2, False), (5, 1, True)],
)
def test_reliability_passes_only_when_rejects_times_five_are_at_most_the_total(tmp_path, total, rejects, passed):
    result, problems = resources.reliability(reliability_run(tmp_path, total, rejects), DAY)
    assert problems == [] and result["total"] == total and result["rejects"] == rejects
    assert result["passed"] is passed
    assert result["reject_rate"] == round(rejects / total, 4)


def test_reliability_counts_proposed_exclusions_too_and_reports_the_split(tmp_path):
    result, _ = resources.reliability(reliability_run(tmp_path, 10, 1, excluded=4), DAY)
    assert result["total"] == 10 and result["included"] == {"total": 6, "rejects": 1}
    assert result["excluded"] == {"total": 4, "rejects": 0}
    assert result["date"] == DAY and result["run"].endswith("run")


def test_reliability_of_nothing_is_not_a_pass():
    assert resources.reliability_passed(0, 0) is False


def test_reliability_with_a_missing_review_gives_problems_and_no_numbers(tmp_path):
    run = write_run(tmp_path, {"a-res": named(good_draft(), "a-res")}, {})
    result, problems = resources.reliability(run, DAY)
    assert result == {} and problems


def test_reliability_command_writes_the_file(tmp_path):
    run = reliability_run(tmp_path, 15, 3)
    path = tmp_path / "rel.yaml"
    assert resources.main(["--reliability-file", str(path), "reliability", "--run", str(run)]) == 0
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert written["passed"] is True and written["total"] == 15 and written["rejects"] == 3


# --- the data file (D1, D2) --------------------------------------------------------------------------------------


def good_entry(lid: str = "fictional-biobank") -> dict:
    return resources.build_entry(context() | {"id": lid}, named(good_draft(), lid))


def good_file(*entries: dict) -> dict:
    return {"checked": DAY, "entries": list(entries) or [good_entry()]}


def test_the_real_data_file_is_valid():
    assert resources.check_data(resources.load_data(Path("registry/resources.yaml"))) == []


def test_a_good_file_round_trips_through_yaml(tmp_path):
    data = good_file(good_entry("a-res"), good_entry("b-res"))
    path = tmp_path / "r.yaml"
    path.write_text(resources.dump_data(data), encoding="utf-8")
    assert resources.load_data(path) == data and resources.check_data(data) == []


def entry_with(path: list, value) -> dict:
    return good_file(mutate(good_entry(), path, value))


def with_fields(**over) -> dict:
    return good_file({**good_entry(), **over})


def register_entry(**over) -> dict:
    e = good_entry()
    e["category"], e["holds"], e["quotes"]["holds"] = "register", [], {}
    e.update(over)
    return e


NO_HOLD_QUOTE = {**good_entry(), "quotes": {**good_entry()["quotes"], "holds": {}}}

DATA_NEGATIVE = {
    "unknown category": (entry_with(["category"], "dataset"), "category: unknown value"),
    "unknown access": (entry_with(["access"], "free"), "access: unknown value"),
    "unknown covers": (entry_with(["covers"], "long_covid"), "covers: unknown value"),
    "unknown holds value": (entry_with(["holds"], ["biospecimens", "imaging"]), "holds: must be a list of distinct"),
    "repeated holds value": (
        entry_with(["holds"], ["biospecimens", "biospecimens"]),
        "holds: must be a list of distinct",
    ),
    "unknown field": (entry_with(["description"], "free text"), "unknown field(s) description"),
    "bad language": (entry_with(["language"], "english"), "language: must be"),
    "bad url": (entry_with(["url"], "biobank"), "url: must be an http"),
    "bad access_url": (entry_with(["access_url"], "biobank"), "access_url: must be null or an http"),
    "bad checked date": (entry_with(["checked"], "yesterday"), "checked: must be a date"),
    "bad countries": (entry_with(["countries"], []), "countries: must be a non-empty list"),
    "empty source": (entry_with(["source"], []), "source: must be a non-empty list"),
    "bad hash": (entry_with(["text_hash", "main"], "abc"), "text_hash: every hash"),
    "quote page not stored": (entry_with(["quotes", "name", "page"], "elsewhere"), "quotes.name: page 'elsewhere'"),
    "stated name without quote": (entry_with(["quotes", "name", "quote"], ""), "quotes.name: a value other than"),
    "stated operator without quote": (
        entry_with(["quotes", "operator", "quote"], ""),
        "quotes.operator: a value other",
    ),
    "stated countries without quote": (
        entry_with(["quotes", "countries", "quote"], ""),
        "quotes.countries: a value other",
    ),
    "stated access without quote": (entry_with(["quotes", "access", "quote"], ""), "quotes.access: a value other"),
    "stated covers without quote": (entry_with(["quotes", "covers", "quote"], ""), "quotes.covers: a value other"),
    "hold without quote": (
        entry_with(["quotes", "holds", "biospecimens", "quote"], ""),
        "quotes.holds.biospecimens: a value other",
    ),
    "hold without a quote entry": (good_file(NO_HOLD_QUOTE), "quotes.holds.biospecimens"),
    "quote for not_stated": (
        with_fields(operator="not_stated"),
        "quotes.operator: a 'not_stated' value has an empty quote",
    ),
    "missing field": (
        good_file({k: v for k, v in good_entry().items() if k != "covers"}),
        "missing field(s) covers",
    ),
    "register with holds": (with_fields(category="register"), "a register has no holds"),
    "data with empty holds": (with_fields(holds=[]), "a data entry needs at least one holds value"),
    "data with access not_stated": (with_fields(access="not_stated"), "a data entry needs a stated access"),
    "duplicate id": (good_file(good_entry("a-res"), good_entry("a-res")), "a-res: id: duplicate id"),
    "unsorted ids": (good_file(good_entry("b-res"), good_entry("a-res")), "a-res: id: ids are not sorted"),
    "entries with no run date": (
        {"checked": None, "entries": [good_entry()]},
        "'checked' is null but there are entries",
    ),
    "no entries key": ({"checked": DAY}, "missing top-level field 'entries'"),
    "not a mapping": ([], "top level must be a mapping"),
}


@pytest.mark.parametrize("case", sorted(DATA_NEGATIVE))
def test_a_data_file_with_this_fault_fails_naming_the_entry(case):
    data, expected = DATA_NEGATIVE[case]
    found = resources.check_data(data)
    assert any(expected in p for p in found), found


def test_a_register_with_no_holds_and_access_not_stated_is_valid():
    e = register_entry(access="not_stated")
    e["quotes"]["access"]["quote"] = ""
    assert resources.check_data(good_file(e)) == []


def test_check_cli_exits_non_zero_for_a_bad_file_and_zero_for_a_good_one(tmp_path, capsys):
    path = tmp_path / "r.yaml"
    path.write_text(resources.dump_data(good_file()), encoding="utf-8")
    assert resources.main(["--data-file", str(path), "check"]) == 0
    path.write_text(resources.dump_data(with_fields(access="free")), encoding="utf-8")
    assert resources.main(["--data-file", str(path), "check"]) == 1
    assert "fictional-biobank: access: unknown value" in capsys.readouterr().err
    assert resources.main(["--data-file", str(tmp_path / "missing.yaml"), "check"]) == 1


# --- check --cache (D3) ------------------------------------------------------------------------------------------


def stored_cache(tmp_path) -> Path:
    root = tmp_path / "cache"
    d = root / DAY / "fictional-biobank"
    d.mkdir(parents=True)
    for key, text in context()["pages"].items():
        (d / f"{key}.txt").write_text(text, encoding="utf-8")
    return root


def test_check_cache_passes_when_every_quote_is_in_its_stored_page(tmp_path):
    assert resources.check_against_cache(good_file(), stored_cache(tmp_path)) == []


def test_check_cache_names_the_id_and_field_of_a_quote_changed_by_one_character(tmp_path):
    root = stored_cache(tmp_path)
    data = entry_with(["quotes", "operator", "quote"], "operated by the Imaginary Institute of Medicinx")
    found = resources.check_against_cache(data, root)
    assert found == ["fictional-biobank: quotes.operator: quote not found in the stored text of page 'main'"]
    data = entry_with(["quotes", "holds", "biospecimens", "quote"], "It holds blood samplez")
    assert "fictional-biobank: quotes.holds.biospecimens" in resources.check_against_cache(data, root)[0]


def test_check_cache_names_a_missing_cached_page(tmp_path):
    root = stored_cache(tmp_path)
    (root / DAY / "fictional-biobank" / "access.txt").unlink()
    found = resources.check_against_cache(good_file(), root)
    assert any("fictional-biobank: page 'access': no stored text" in p for p in found)
    assert any("quotes.access: page 'access' is not in the cache" in p for p in found)
    assert resources.check_against_cache(good_file(), tmp_path / "no-cache")


def test_check_cache_notices_a_stored_text_that_changed_since_the_entry_was_written(tmp_path):
    root = stored_cache(tmp_path)
    path = root / DAY / "fictional-biobank" / "main.txt"
    path.write_text(path.read_text(encoding="utf-8") + " Added later.", encoding="utf-8")
    found = resources.check_against_cache(good_file(), root)
    assert any("has changed since the entry was written" in p for p in found)


def test_check_cli_with_cache(tmp_path):
    root = stored_cache(tmp_path)
    path = tmp_path / "r.yaml"
    path.write_text(resources.dump_data(good_file()), encoding="utf-8")
    args = ["--data-file", str(path), "--cache-dir", str(root), "check", "--cache"]
    assert resources.main(args) == 0
    (root / DAY / "fictional-biobank" / "main.txt").unlink()
    assert resources.main(args) == 1


# --- links (U1) --------------------------------------------------------------------------------------------------


def test_links_names_the_address_that_does_not_answer_200_and_changes_no_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "r.yaml"
    path.write_text(resources.dump_data(good_file(good_entry("a-res"), good_entry("b-res"))), encoding="utf-8")
    before = path.read_bytes()
    routes = {MAIN: page("good-main.html")}  # the access page answers 404
    monkeypatch.setattr(resources, "Fetcher", lambda: make_fetcher(routes))
    assert resources.main(["--data-file", str(path), "links"]) == 0
    out = capsys.readouterr().out
    assert f"a-res: {ACCESS}: HTTP 404" in out and f"b-res: {ACCESS}: HTTP 404" in out
    assert f"{MAIN}:" not in out and "2 address(es)" in out
    assert path.read_bytes() == before


def test_links_reports_a_robots_refusal_and_a_network_error_and_is_silent_when_all_answer():
    data = good_file()
    robots = (200, "text/plain", fixture("robots-disallow.txt"), {})
    assert resources.run_links(data, make_fetcher({f"{HOST}/robots.txt": robots})) == [
        ("fictional-biobank", MAIN, "robots_disallowed"),
        ("fictional-biobank", ACCESS, "robots_disallowed"),
    ]
    ok = {MAIN: page("good-main.html"), ACCESS: page("good-access.html")}
    assert resources.run_links(data, make_fetcher(ok)) == []
    down = {MAIN: httpx.ConnectError("x"), ACCESS: page("good-access.html")}
    assert resources.run_links(data, make_fetcher(down)) == [("fictional-biobank", MAIN, "network_error")]
