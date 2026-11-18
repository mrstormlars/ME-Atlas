"""Tests for the registry module (me_atlas.trials). Recorded or fictional responses in tests/fixtures/clinicaltrials/;
no network, no LLM, no sleeping."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
import yaml

from me_atlas import cards as cardlib
from me_atlas import trials
from me_atlas.http import RateLimiter

FIXTURES = Path(__file__).parent / "fixtures" / "clinicaltrials"
CARD_FIXTURE = Path(__file__).parent / "fixtures" / "cards" / "fictional-hypothesis.yaml"
DAY = "2026-11-18"
SLUGS = {"fictional-hypothesis", "second-idea"}


def page(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def handler_for(requests: list[httpx.Request], *, fail: str | None = None, mutate=None):
    """A mock registry: the fixture pages by search and page token."""

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = request.url.params
        name = "me_cfs" if params["query.cond"] == trials.SEARCHES["me_cfs"] else "long_covid"
        if fail == name:
            return httpx.Response(500)
        number = 2 if params.get("pageToken") == "FICTIONAL-TOKEN-2" else 1
        body = page(f"{name}-{number:03d}.json")
        if mutate:
            body = mutate(name, number, body)
        return httpx.Response(200, json=body)

    return handle


def client(requests: list[httpx.Request], **kw) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler_for(requests, **kw)), headers={"User-Agent": trials.USER_AGENT}
    )


def fast_fetch(data_file: Path, cache: Path, requests: list[httpx.Request], *, day: str = DAY, **kw):
    clock = Clock()
    return trials.run_fetch(
        data_file,
        cache,
        day=day,
        http=client(requests, **kw),
        limiter=RateLimiter(1, clock=clock, sleep=clock.sleep),
        sleep=lambda s: None,
        max_retries=1,
    )


@pytest.fixture
def fetched(tmp_path):
    data_file, cache = tmp_path / "registry" / "trials.yaml", tmp_path / "cache"
    requests: list[httpx.Request] = []
    fast_fetch(data_file, cache, requests)
    return data_file, cache, requests


def entry(data: dict, nct: str) -> dict:
    return next(e for e in data["studies"] if e["nct_id"] == nct)


def cards_dir(tmp_path: Path, slugs=SLUGS) -> Path:
    path = tmp_path / "cards"
    path.mkdir(exist_ok=True)
    for slug in slugs:
        (path / f"{slug}.yaml").write_text("x: 1\n", encoding="utf-8")
    return path


# --- parsing ---------------------------------------------------------------


def test_copied_fields_come_from_the_record_with_countries_unique_and_sorted():
    fields = trials.copied_fields(page("me_cfs-001.json")["studies"][0])
    assert fields == {
        "nct_id": "NCT90000001",
        "title": "Fictional exercise study in ME/CFS",
        "study_type": "INTERVENTIONAL",
        "status": "RECRUITING",
        "countries": ["Germany", "Norway"],
        "enrollment": {"count": 120, "type": "ESTIMATED"},
        "start_date": "2025-03",
        "last_update": "2026-10-01",
    }


def test_a_record_without_locations_enrolment_or_start_date_gets_empty_list_and_nulls():
    fields = trials.copied_fields(page("long_covid-001.json")["studies"][1])  # NCT90000005
    assert fields["countries"] == [] and fields["enrollment"] is None and fields["start_date"] is None


def test_a_record_without_status_is_an_error():
    raw = copy.deepcopy(page("me_cfs-001.json")["studies"][0])
    del raw["protocolSection"]["statusModule"]["overallStatus"]
    with pytest.raises(trials.TrialsError, match="NCT90000001"):
        trials.copied_fields(raw)


def test_context_fields_hold_titles_conditions_summary_interventions_and_model():
    raws = {r["protocolSection"]["identificationModule"]["nctId"]: r for r in page("me_cfs-001.json")["studies"]}
    a = trials.context_fields(raws["NCT90000001"])
    assert set(a) == {
        "nct_id",
        "brief_title",
        "official_title",
        "conditions",
        "keywords",
        "brief_summary",
        "study_type",
        "interventions",
        "observational_model",
    }
    assert a["official_title"].startswith("A fictional official title")
    assert a["interventions"] == [{"type": "BEHAVIORAL", "name": "Fictional pacing programme"}]
    b = trials.context_fields(raws["NCT90000002"])
    assert b["observational_model"] == "Cohort" and b["interventions"] == [] and b["official_title"] is None


# --- fetch (F1-F4) ------------------------------------------------------------


def test_fetch_pages_both_searches_and_merges_a_study_found_by_both(fetched):
    data_file, cache, requests = fetched
    data = trials.load_data(data_file)
    assert data["fetched"] == DAY and data["searches"] == trials.SEARCHES
    assert [e["nct_id"] for e in data["studies"]] == [f"NCT9000000{i}" for i in range(1, 9)]
    assert entry(data, "NCT90000004")["searches"] == ["me_cfs", "long_covid"]
    assert entry(data, "NCT90000001")["searches"] == ["me_cfs"]
    assert entry(data, "NCT90000008")["searches"] == ["long_covid"]
    assert all(e["hypotheses"] == [] and e["mapping"] == "not_mapped" for e in data["studies"])
    assert len(requests) == 3
    long_covid = [r for r in requests if r.url.params["query.cond"] == trials.SEARCHES["long_covid"]]
    assert "pageToken" not in long_covid[0].url.params and long_covid[1].url.params["pageToken"] == "FICTIONAL-TOKEN-2"
    for r in requests:
        assert r.url.params["pageSize"] == "1000"
        assert "filter.overallStatus" not in r.url.params  # all statuses
        assert str(r.url).startswith("https://clinicaltrials.gov/api/v2/studies")


def test_fetch_sends_a_generic_user_agent_and_no_key_or_email(fetched):
    _, _, requests = fetched
    for r in requests:
        assert r.headers["user-agent"] == "me-atlas-research-client"
        assert not {"authorization", "x-api-key", "from"} & set(r.headers)
        assert "@" not in str(r.url) and "key" not in str(r.url.params).lower()


def test_fetch_keeps_to_one_request_a_second():
    assert trials.MAX_PER_SECOND == 1
    clock = Clock()
    limiter = RateLimiter(trials.MAX_PER_SECOND, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.wait()
    assert sum(clock.sleeps) >= 2.0


def test_every_page_is_cached_and_offline_makes_no_request(fetched):
    data_file, cache, _ = fetched
    assert sorted(p.name for p in (cache / DAY).iterdir()) == [
        "long_covid-001.json",
        "long_covid-002.json",
        "me_cfs-001.json",
    ]
    before = data_file.read_bytes()

    def forbidden(request):
        raise AssertionError("a request was made")

    http = httpx.Client(transport=httpx.MockTransport(forbidden))
    again = trials.run_fetch(data_file, cache, day=DAY, offline=True, http=http)
    assert len(again["studies"]) == 8
    assert data_file.read_bytes() == before


def test_a_page_is_cached_even_when_it_cannot_be_used(tmp_path):
    cache = tmp_path / "cache"
    with pytest.raises(trials.TrialsError):
        fast_fetch(tmp_path / "t.yaml", cache, [], mutate=lambda n, i, b: {"error": "x"})
    assert (cache / DAY / "me_cfs-001.json").is_file()


def test_offline_with_no_cache_fails(tmp_path):
    with pytest.raises(trials.TrialsError, match="missing"):
        trials.run_fetch(tmp_path / "t.yaml", tmp_path / "cache", day=DAY, offline=True)


@pytest.mark.parametrize("fail", ["me_cfs", "long_covid"])
def test_a_failed_fetch_exits_non_zero_and_leaves_the_data_file_byte_identical(tmp_path, monkeypatch, fail):
    data_file, cache = tmp_path / "registry" / "trials.yaml", tmp_path / "cache"
    fast_fetch(data_file, cache, [])
    before = data_file.read_bytes()
    clock = Clock()
    real = trials.run_fetch
    requests: list[httpx.Request] = []

    def wrapped(*args, **kwargs):
        return real(
            *args,
            **kwargs,
            http=client(requests, fail=fail),
            limiter=RateLimiter(1, clock=clock, sleep=clock.sleep),
            sleep=lambda s: None,
            max_retries=2,
        )

    monkeypatch.setattr(trials, "run_fetch", wrapped)
    code = trials.main(["--data-file", str(data_file), "--cache-dir", str(cache), "fetch", "--date", "2026-11-25"])
    assert code != 0
    assert data_file.read_bytes() == before
    assert any(r.url.params["query.cond"] == trials.SEARCHES[fail] for r in requests)


def test_a_page_without_studies_fails_and_leaves_the_data_file_alone(tmp_path):
    data_file, cache = tmp_path / "registry" / "trials.yaml", tmp_path / "cache"
    fast_fetch(data_file, cache, [])
    before = data_file.read_bytes()
    with pytest.raises(trials.TrialsError, match="studies"):
        fast_fetch(data_file, cache, [], day="2026-11-25", mutate=lambda n, i, b: {"totalCount": 0})
    assert data_file.read_bytes() == before


def test_a_total_count_that_does_not_match_the_records_received_fails(tmp_path):
    def wrong_total(name, number, body):
        return {**body, "totalCount": 99} if number == 1 else body

    with pytest.raises(trials.TrialsError, match="reports 99"):
        fast_fetch(tmp_path / "t.yaml", tmp_path / "cache", [], mutate=wrong_total)
    assert not (tmp_path / "t.yaml").exists()


# --- refresh keeps the mapping; absent studies stay (D2, D5) --------------------


def test_a_refresh_replaces_copied_fields_and_keeps_hypotheses_and_mapping(fetched):
    data_file, cache, _ = fetched
    data = trials.load_data(data_file)
    entry(data, "NCT90000001").update(hypotheses=["second-idea"], mapping="accepted", mapping_source="run/r.json")
    data_file.write_text(trials.dump_data(data), encoding="utf-8")

    def changed(name, number, body):
        body = copy.deepcopy(body)
        for s in body["studies"]:
            if s["protocolSection"]["identificationModule"]["nctId"] == "NCT90000001":
                s["protocolSection"]["statusModule"]["overallStatus"] = "ACTIVE_NOT_RECRUITING"
        return body

    fast_fetch(data_file, cache, [], day="2026-11-25", mutate=changed)
    new = entry(trials.load_data(data_file), "NCT90000001")
    assert new["status"] == "ACTIVE_NOT_RECRUITING"
    assert (new["hypotheses"], new["mapping"], new["mapping_source"]) == (["second-idea"], "accepted", "run/r.json")


def test_a_study_absent_from_the_latest_fetch_stays_with_its_last_values_and_is_not_listed(fetched):
    data_file, cache, _ = fetched
    data = trials.load_data(data_file)
    e = entry(data, "NCT90000001")
    e.update(hypotheses=["second-idea"], mapping="accepted")
    assert trials.is_listed(e)
    data_file.write_text(trials.dump_data(data), encoding="utf-8")

    def without(name, number, body):
        body = copy.deepcopy(body)
        body["studies"] = [
            s for s in body["studies"] if s["protocolSection"]["identificationModule"]["nctId"] != "NCT90000001"
        ]
        body.pop("totalCount", None)
        return body

    fast_fetch(data_file, cache, [], day="2026-11-25", mutate=without)
    new = trials.load_data(data_file)
    gone = entry(new, "NCT90000001")
    assert gone["title"] == e["title"] and gone["status"] == "RECRUITING" and gone["searches"] == []
    assert not trials.is_listed(gone)
    assert "second-idea" not in trials.listed_by_card(new)
    assert trials.check_data(new, SLUGS) == []


# --- validator (D3) --------------------------------------------------------------


def set_entry(data, nct, **changes):
    entry(data, nct).update(changes)


BREAKS = {
    "unknown slug": (
        lambda d: set_entry(d, "NCT90000002", hypotheses=["no-such-card"], mapping="accepted"),
        "NCT90000002",
    ),
    "hypotheses with mapping not_mapped": (
        lambda d: set_entry(d, "NCT90000003", hypotheses=["second-idea"], mapping="not_mapped"),
        "NCT90000003",
    ),
    "hypotheses with a rejected mapping": (
        lambda d: set_entry(d, "NCT90000003", hypotheses=["second-idea"], mapping="rejected"),
        "NCT90000003",
    ),
    "duplicate id": (lambda d: d["studies"].insert(1, copy.deepcopy(d["studies"][0])), "NCT90000001"),
    "unsorted ids": (lambda d: d["studies"].reverse(), "not sorted"),
    "unknown status": (lambda d: set_entry(d, "NCT90000004", status="ON_HOLD"), "NCT90000004"),
    "unknown study type": (lambda d: set_entry(d, "NCT90000005", study_type="SURVEY"), "NCT90000005"),
    "missing field": (lambda d: entry(d, "NCT90000006").pop("countries"), "NCT90000006"),
    "unknown mapping state": (lambda d: set_entry(d, "NCT90000007", mapping="maybe"), "NCT90000007"),
    "search name not in searches": (lambda d: set_entry(d, "NCT90000008", searches=["other"]), "NCT90000008"),
    "missing top-level field": (lambda d: d.pop("fetched"), "fetched"),
}


def test_the_validator_accepts_a_fresh_fetch(fetched, tmp_path):
    data = trials.load_data(fetched[0])
    assert trials.check_data(data, SLUGS) == []
    assert trials.main(["--data-file", str(fetched[0]), "--cards-dir", str(cards_dir(tmp_path)), "check"]) == 0


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_validator_fails_and_names_the_entry(fetched, name, tmp_path):
    data = trials.load_data(fetched[0])
    change, expected = BREAKS[name]
    change(data)
    problems = trials.check_data(data, SLUGS)
    assert problems and any(expected in p for p in problems), problems
    path = tmp_path / "bad.yaml"
    path.write_text(trials.dump_data(data), encoding="utf-8")
    assert trials.main(["--data-file", str(path), "--cards-dir", str(cards_dir(tmp_path)), "check"]) == 1


# --- check against the cache (D4) ---------------------------------------------------


def check_cache_args(data_file, cache, tmp_path):
    return ["--data-file", str(data_file), "--cache-dir", str(cache), "--cards-dir", str(cards_dir(tmp_path))]


def test_check_cache_passes_on_an_unchanged_file(fetched, tmp_path):
    data_file, cache, _ = fetched
    assert trials.check_against_cache(trials.load_data(data_file), trials.latest_cache_records(cache)) == []
    assert trials.main([*check_cache_args(data_file, cache, tmp_path), "check", "--cache"]) == 0


def test_a_title_changed_by_one_character_fails_the_cache_check_and_names_the_study_and_field(
    fetched, tmp_path, capsys
):
    data_file, cache, _ = fetched
    data = trials.load_data(data_file)
    e = entry(data, "NCT90000002")
    e["title"] = e["title"].replace("marker", "markes")
    data_file.write_text(trials.dump_data(data), encoding="utf-8")
    assert trials.main([*check_cache_args(data_file, cache, tmp_path), "check", "--cache"]) == 1
    err = capsys.readouterr().err
    assert "NCT90000002" in err and "'title'" in err


def test_every_copied_field_is_compared_with_the_cache(fetched):
    data_file, cache, _ = fetched
    records = trials.latest_cache_records(cache)
    for field, value in (
        ("study_type", "OBSERVATIONAL"),
        ("status", "COMPLETED"),
        ("countries", ["Atlantis"]),
        ("enrollment", None),
        ("start_date", "1999-01"),
        ("last_update", "1999-01-01"),
    ):
        data = trials.load_data(data_file)
        entry(data, "NCT90000001")[field] = value
        problems = trials.check_against_cache(data, records)
        assert len(problems) == 1 and "NCT90000001" in problems[0] and f"'{field}'" in problems[0]


def test_a_study_with_no_cached_record_fails_the_cache_check(fetched):
    assert trials.check_against_cache(trials.load_data(fetched[0]), {}) != []


def test_the_newest_cached_record_wins_and_an_older_only_record_is_kept(tmp_path):
    cache = tmp_path / "cache"
    for day, status in (("2026-11-18", "RECRUITING"), ("2026-11-25", "COMPLETED")):
        body = copy.deepcopy(page("me_cfs-001.json"))
        body["studies"][0]["protocolSection"]["statusModule"]["overallStatus"] = status
        (cache / day).mkdir(parents=True)
        (cache / day / "me_cfs-001.json").write_text(json.dumps({"studies": body["studies"][:1]}), encoding="utf-8")
    (cache / "2026-11-18" / "long_covid-001.json").write_text(
        json.dumps({"studies": page("me_cfs-001.json")["studies"][1:2]}), encoding="utf-8"
    )
    records = trials.latest_cache_records(cache)
    assert records["NCT90000001"]["protocolSection"]["statusModule"]["overallStatus"] == "COMPLETED"
    assert "NCT90000002" in records


# --- listing -------------------------------------------------------------------------


def test_listed_means_ongoing_in_latest_fetch_accepted_and_with_a_card(fetched):
    data = trials.load_data(fetched[0])
    for nct in ("NCT90000001", "NCT90000002", "NCT90000003", "NCT90000004", "NCT90000007"):
        set_entry(data, nct, hypotheses=["second-idea"], mapping="accepted")
    set_entry(data, "NCT90000004", mapping="rejected", hypotheses=[])
    set_entry(data, "NCT90000002", searches=[])
    listed = trials.listed_by_card(data)
    # 02 is absent from the latest fetch, 03 and 07 are not ongoing, 04 is rejected
    assert [e["nct_id"] for e in listed["second-idea"]] == ["NCT90000001"]
    # ongoing and in the latest fetch but not listed: 04, 05, 06 and 08
    assert trials.unlisted_ongoing(data) == 4


# --- mapping plan, mapping and review (M1-M3) -------------------------------------------


@pytest.fixture
def card_list():
    return [cardlib.load_card(CARD_FIXTURE)]


def plan(fetched, out, card_list, **kw):
    data_file, cache, _ = fetched
    trials.map_plan(trials.load_data(data_file), trials.latest_cache_records(cache), card_list, out, **kw)
    return out


def batch_ids(out, n=1):
    return [s["nct_id"] for s in json.loads((out / f"batch-{n}.json").read_text(encoding="utf-8"))]


def test_map_plan_selects_ongoing_not_mapped_studies_in_batches_of_at_most_20(fetched, tmp_path, card_list):
    assert trials.BATCH_SIZE == 20
    out = plan(fetched, tmp_path / "run", card_list)
    assert batch_ids(out) == [f"NCT9000000{i}" for i in (1, 2, 4, 5, 6, 8)]
    cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
    assert cards == [
        {"slug": "fictional-hypothesis", "name": card_list[0].name, "core_claim": card_list[0].core_claim.text}
    ]
    assert not (out / "batch-2.json").exists()


def test_map_plan_splits_into_several_batches(fetched, tmp_path, card_list, monkeypatch):
    monkeypatch.setattr(trials, "BATCH_SIZE", 4)
    out = plan(fetched, tmp_path / "run", card_list)
    assert [len(batch_ids(out, n)) for n in (1, 2)] == [4, 2] and trials.batch_numbers(out) == [1, 2]


def test_map_plan_skips_mapped_studies_and_takes_a_given_list(fetched, tmp_path, card_list):
    data_file = fetched[0]
    data = trials.load_data(data_file)
    set_entry(data, "NCT90000001", mapping="accepted")
    data_file.write_text(trials.dump_data(data), encoding="utf-8")
    assert "NCT90000001" not in batch_ids(plan(fetched, tmp_path / "a", card_list))
    out = plan(fetched, tmp_path / "b", card_list, ids=["NCT90000003", "NCT90000001"])
    assert batch_ids(out) == ["NCT90000001", "NCT90000003"]


def test_map_plan_refuses_an_unknown_registry_number(fetched, tmp_path, card_list):
    with pytest.raises(trials.TrialsError, match="NCT00000000"):
        plan(fetched, tmp_path / "run", card_list, ids=["NCT00000000"])


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def good_map(out: Path) -> list[dict]:
    rows = [{"nct_id": i, "cards": [], "reason": "The record names no mechanism."} for i in batch_ids(out)]
    rows[0]["cards"] = ["fictional-hypothesis"]
    return rows


SLUGS_WITH_CARD = SLUGS | {"fictional-hypothesis"}


def test_record_mapping_accepts_a_valid_file_and_writes_nothing(fetched, tmp_path, card_list):
    out = plan(fetched, tmp_path / "run", card_list)
    write_json(out / "map-1.json", good_map(out))
    before = fetched[0].read_bytes()
    assert trials.record_mapping(out, SLUGS_WITH_CARD) == []
    assert fetched[0].read_bytes() == before


MAP_BREAKS = {
    "unknown slug": (lambda rows: rows[0].update(cards=["no-such-card"]), "unknown card slug"),
    "missing nct id": (lambda rows: rows.pop(), "is missing"),
    "repeated nct id": (lambda rows: rows.append(dict(rows[0])), "more than once"),
    "extra nct id": (
        lambda rows: rows.append({"nct_id": "NCT90000003", "cards": [], "reason": "x"}),
        "not in the batch",
    ),
    "extra key": (lambda rows: rows[1].update(confidence=0.9), "extra key"),
    "missing reason": (lambda rows: rows[1].update(reason=""), "reason"),
    "cards not a list": (lambda rows: rows[1].update(cards="fictional-hypothesis"), "'cards' must be a list"),
}


@pytest.mark.parametrize("name", sorted(MAP_BREAKS))
def test_record_mapping_rejects(fetched, tmp_path, card_list, name):
    out = plan(fetched, tmp_path / "run", card_list)
    rows = good_map(out)
    change, expected = MAP_BREAKS[name]
    change(rows)
    write_json(out / "map-1.json", rows)
    problems = trials.record_mapping(out, SLUGS_WITH_CARD)
    assert any(expected in p for p in problems), problems


def test_record_mapping_reports_a_missing_mapping_file(fetched, tmp_path, card_list):
    out = plan(fetched, tmp_path / "run", card_list)
    assert any("missing" in p for p in trials.record_mapping(out, SLUGS))


def reviewed(fetched, tmp_path, card_list, verdicts: dict[str, str] | None = None):
    out = plan(fetched, tmp_path / "run", card_list)
    mapping = good_map(out)
    write_json(out / "map-1.json", mapping)
    review = []
    for row in mapping:
        verdict = (verdicts or {}).get(row["nct_id"], "accept")
        item = {"nct_id": row["nct_id"], "verdict": verdict}
        if verdict == "reject":
            item["finding"] = "The record does not bear on the card."
        review.append(item)
    write_json(out / "review-1.json", review)
    return out, mapping


def test_record_review_writes_accepted_and_rejected_mappings_and_only_those(fetched, tmp_path, card_list):
    out, mapping = reviewed(fetched, tmp_path, card_list, {"NCT90000002": "reject"})
    mapping[1]["cards"] = ["second-idea"]  # NCT90000002 is rejected: this must not reach the file
    write_json(out / "map-1.json", mapping)
    new, problems = trials.record_review(trials.load_data(fetched[0]), out, SLUGS_WITH_CARD)
    assert problems == []
    first = entry(new, "NCT90000001")
    assert first["hypotheses"] == ["fictional-hypothesis"] and first["mapping"] == "accepted"
    assert first["mapping_source"].endswith("review-1.json")
    rejected = entry(new, "NCT90000002")
    assert rejected["hypotheses"] == [] and rejected["mapping"] == "rejected"
    matched_nothing = entry(new, "NCT90000004")
    assert matched_nothing["mapping"] == "accepted" and matched_nothing["hypotheses"] == []
    assert entry(new, "NCT90000003")["mapping"] == "not_mapped"  # not in the batch: untouched
    assert trials.check_data(new, SLUGS_WITH_CARD) == []


def test_the_record_review_command_writes_the_data_file(fetched, tmp_path, card_list):
    out, _ = reviewed(fetched, tmp_path, card_list, {"NCT90000002": "reject"})
    args = ["--data-file", str(fetched[0]), "--cards-dir", str(cards_dir(tmp_path, SLUGS_WITH_CARD))]
    assert trials.main([*args, "record-review", "--run", str(out)]) == 0
    data = trials.load_data(fetched[0])
    assert entry(data, "NCT90000002")["mapping"] == "rejected"
    assert entry(data, "NCT90000001")["hypotheses"] == ["fictional-hypothesis"]


REVIEW_BREAKS = {
    "reject without a finding": (lambda rows: rows[0].update(verdict="reject"), "needs a finding"),
    "reject with an empty finding": (lambda rows: rows[0].update(verdict="reject", finding=" "), "needs a finding"),
    "unknown verdict": (lambda rows: rows[0].update(verdict="maybe"), "verdict must be"),
    "accept with a finding": (lambda rows: rows[0].update(finding="x"), "an accept has no finding"),
    "missing study": (lambda rows: rows.pop(), "is missing"),
    "repeated study": (lambda rows: rows.append(dict(rows[0])), "more than once"),
    "extra study": (lambda rows: rows.append({"nct_id": "NCT90000003", "verdict": "accept"}), "not in the batch"),
    "extra key": (lambda rows: rows[0].update(score=1), "extra key"),
}


@pytest.mark.parametrize("name", sorted(REVIEW_BREAKS))
def test_record_review_refuses_and_leaves_the_data_unchanged(fetched, tmp_path, card_list, name):
    out, _ = reviewed(fetched, tmp_path, card_list)
    rows = json.loads((out / "review-1.json").read_text(encoding="utf-8"))
    change, expected = REVIEW_BREAKS[name]
    change(rows)
    write_json(out / "review-1.json", rows)
    data = trials.load_data(fetched[0])
    new, problems = trials.record_review(data, out, SLUGS_WITH_CARD)
    assert any(expected in p for p in problems), problems
    assert new == data
    before = fetched[0].read_bytes()
    args = ["--data-file", str(fetched[0]), "--cards-dir", str(cards_dir(tmp_path, SLUGS_WITH_CARD))]
    assert trials.main([*args, "record-review", "--run", str(out)]) == 1
    assert fetched[0].read_bytes() == before


def test_record_review_refuses_when_the_mapping_is_invalid(fetched, tmp_path, card_list):
    out, mapping = reviewed(fetched, tmp_path, card_list)
    mapping[0]["cards"] = ["no-such-card"]
    write_json(out / "map-1.json", mapping)
    _, problems = trials.record_review(trials.load_data(fetched[0]), out, SLUGS_WITH_CARD)
    assert any("unknown card slug" in p for p in problems)


def test_map_plan_and_the_files_of_the_agents_change_nothing_in_the_data_file(fetched, tmp_path, card_list):
    before = fetched[0].read_bytes()
    reviewed(fetched, tmp_path, card_list)
    assert fetched[0].read_bytes() == before


# --- sample and reliability (M4, M5) ---------------------------------------------------------


def test_the_sample_holds_all_ongoing_me_cfs_and_a_deterministic_draw_of_long_covid_only(fetched):
    data = trials.load_data(fetched[0])
    # ongoing me_cfs: 01, 02, 04 (04 is also found by long_covid). Ongoing long_covid-only: 05, 06, 08.
    one = trials.sample_ids(data, seed=7, n=1)
    assert one == trials.sample_ids(data, seed=7, n=1)
    assert {"NCT90000001", "NCT90000002", "NCT90000004"} <= set(one) and len(one) == 4
    assert one == sorted(one)
    assert len({tuple(trials.sample_ids(data, seed=s, n=1)) for s in range(20)}) > 1  # the seed matters
    assert set(trials.sample_ids(data, seed=7, n=50)) == {f"NCT9000000{i}" for i in (1, 2, 4, 5, 6, 8)}
    assert len(trials.sample_ids(data, seed=7, n=2)) == 5


@pytest.mark.parametrize(
    ("total", "rejects", "passed"),
    [(103, 21, False), (100, 20, True), (100, 0, True), (5, 1, True), (5, 2, False), (0, 0, False)],
)
def test_the_reliability_rule_is_rejects_times_five_at_most_the_total(total, rejects, passed):
    assert trials.reliability_passed(total, rejects) is passed


def test_reliability_counts_rejects_per_search_and_writes_the_file(fetched, tmp_path, card_list):
    out, _ = reviewed(
        fetched, tmp_path, card_list, {"NCT90000002": "reject", "NCT90000005": "reject", "NCT90000006": "reject"}
    )
    rel_file = tmp_path / "registry" / "reliability.yaml"
    args = ["--data-file", str(fetched[0]), "--reliability-file", str(rel_file)]
    assert trials.main([*args, "reliability", "--run", str(out), "--seed", "42"]) == 0
    result = yaml.safe_load(rel_file.read_text(encoding="utf-8"))
    assert (result["total"], result["rejects"], result["sample_seed"]) == (6, 3, 42)
    assert result["reject_rate"] == 0.5 and result["passed"] is False and result["date"]
    # me_cfs: 01, 02, 04 (one reject); long_covid: 04, 05, 06, 08 (two rejects); 04 is in both
    assert result["per_search"]["me_cfs"] == {"total": 3, "rejects": 1, "reject_rate": 0.3333}
    assert result["per_search"]["long_covid"] == {"total": 4, "rejects": 2, "reject_rate": 0.5}


def test_reliability_passes_when_at_most_one_in_five_is_rejected(fetched, tmp_path, card_list):
    out, _ = reviewed(fetched, tmp_path, card_list)
    result, problems = trials.reliability(trials.load_data(fetched[0]), out, 1, "2026-11-18")
    assert problems == [] and result["passed"] is True and result["rejects"] == 0


def test_reliability_refuses_an_invalid_review_and_writes_no_file(fetched, tmp_path, card_list):
    out, _ = reviewed(fetched, tmp_path, card_list)
    write_json(out / "review-1.json", [{"nct_id": "NCT90000001", "verdict": "reject"}])
    rel_file = tmp_path / "registry" / "reliability.yaml"
    args = ["--data-file", str(fetched[0]), "--reliability-file", str(rel_file)]
    assert trials.main([*args, "reliability", "--run", str(out), "--seed", "1"]) == 1
    assert not rel_file.exists()


def test_the_sample_command_writes_the_registry_numbers(fetched, tmp_path):
    out = tmp_path / "ids.txt"
    args = ["--data-file", str(fetched[0]), "sample", "--seed", "3", "--n", "2", "--out", str(out)]
    assert trials.main(args) == 0
    assert out.read_text(encoding="utf-8").split() == trials.sample_ids(trials.load_data(fetched[0]), 3, 2)


def test_the_gate_reads_passed_from_the_reliability_file(tmp_path):
    path = tmp_path / "reliability.yaml"
    assert trials.load_reliability(path) is False
    path.write_text("passed: true\n", encoding="utf-8")
    assert trials.load_reliability(path) is True
    path.write_text("passed: false\n", encoding="utf-8")
    assert trials.load_reliability(path) is False
    path.write_text("passed: yes please\n", encoding="utf-8")
    with pytest.raises(trials.TrialsError):
        trials.load_reliability(path)
