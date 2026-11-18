"""Tests for pages saved by hand (resources import-saved and what follows from it). Small made-up pages in
tests/fixtures/resources/; no network, no LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_resources import (
    ACCESS,
    DAY,
    HTML,
    LEADS,
    MAIN,
    all_routes,
    context,
    fixture,
    good_draft,
    good_entry,
    good_file,
    make_fetcher,
    named,
    stored_cache,
)

from me_atlas import resources

LEAD = "fictional-biobank"
SAVED_DAY = "2026-11-10"
TODAY = "2026-11-18"
LEADS_FILE = "leads.yaml"


@pytest.fixture
def env(tmp_path):
    """A leads file, an inbox with a good main and access page for ``fictional-biobank`` and an empty cache."""
    import yaml

    leads = tmp_path / LEADS_FILE
    leads.write_text(yaml.safe_dump({"leads": LEADS}), encoding="utf-8")
    inbox = tmp_path / "inbox"
    (inbox / LEAD).mkdir(parents=True)
    (inbox / LEAD / "main.html").write_bytes(fixture("saved-main.html"))
    (inbox / LEAD / "access.html").write_bytes(fixture("saved-access.html"))
    return tmp_path


def run(env: Path, *args: str) -> int:
    base = ["--leads-file", str(env / LEADS_FILE), "--cache-dir", str(env / "cache")]
    return resources.main([*base, "import-saved", "--saved-dir", str(env / "inbox"), *args])


def good_args(page: str = "main", url: str = MAIN, saved: str = SAVED_DAY, lead: str = LEAD) -> list[str]:
    return ["--lead", lead, "--page", page, "--url", url, "--saved", saved]


def stored(env: Path, lead: str = LEAD, day: str = SAVED_DAY) -> Path:
    return env / "cache" / day / lead


def cache_files(env: Path) -> list[Path]:
    root = env / "cache"
    return sorted(root.rglob("*")) if root.exists() else []


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    class FixedDate(resources.dt.date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(TODAY)

    monkeypatch.setattr(resources.dt, "date", FixedDate)


# --- H2, H3: storing ---------------------------------------------------------------------------------------------


def test_a_saved_main_page_is_stored_exactly_as_a_fetched_page_with_the_hand_saved_mark(env, capsys):
    assert run(env, *good_args()) == 0
    d = stored(env)
    assert (d / "main.html").read_bytes() == fixture("saved-main.html")
    assert (d / "main.txt").read_text(encoding="utf-8") == resources.extract_text(fixture("saved-main.html").decode())
    assert json.loads((d / "main.meta.json").read_text(encoding="utf-8")) == {
        "requested_url": MAIN,
        "final_url": MAIN,
        "http_status": None,
        "content_type": "text/html",
        "fetched": SAVED_DAY,
        "status": "ok",
        "obtained": "hand_saved",
    }
    assert "main ok" in capsys.readouterr().out


def test_a_saved_access_page_is_stored_under_the_access_name(env):
    assert run(env, *good_args("access", ACCESS)) == 0
    d = stored(env)
    assert (d / "access.html").read_bytes() == fixture("saved-access.html")
    assert resources.read_meta(d, "access")["obtained"] == "hand_saved"
    assert not (d / "main.meta.json").exists()


def test_a_saved_bot_check_page_is_stored_as_blocked_and_the_command_exits_1(env, capsys):
    (env / "inbox" / LEAD / "main.html").write_bytes(fixture("saved-bot-check.html"))
    assert run(env, *good_args()) == 1
    assert resources.read_meta(stored(env), "main")["status"] == "blocked"
    assert "main blocked" in capsys.readouterr().out


def test_a_saved_page_with_almost_no_text_is_no_text_and_exits_1(env):
    (env / "inbox" / LEAD / "main.html").write_text("<html><body><p>Short.</p></body></html>", encoding="utf-8")
    assert run(env, *good_args()) == 1
    assert resources.read_meta(stored(env), "main")["status"] == "no_text"


def test_a_declared_non_utf8_charset_is_decoded_with_that_charset(env):
    (env / "inbox" / LEAD / "main.html").write_bytes(fixture("saved-latin1.html"))
    assert run(env, *good_args()) == 0
    text = (stored(env) / "main.txt").read_text(encoding="utf-8")
    assert "Fiktive Studie für Müdigkeit" in text and "�" not in text
    assert (stored(env) / "main.html").read_bytes() == fixture("saved-latin1.html")


def test_a_page_with_no_declaration_that_is_not_utf8_falls_back_to_utf8_with_replacement():
    body = b"<p>Caf\xe9 " + b"x" * 300 + b"</p>"
    assert "Caf�" in resources.decode_saved(body)
    assert resources.decode_saved(b'<meta charset="no-such-charset"><p>caf\xc3\xa9</p>').endswith("café</p>")


# --- H4: the refusals; nothing is written under the cache ---------------------------------------------------------


def test_refuses_a_lead_not_in_the_leads_file(env, capsys):
    assert run(env, *good_args(lead="no-such-lead")) == 1
    assert "not in the leads file" in capsys.readouterr().err
    assert cache_files(env) == []


def test_refuses_the_access_page_of_a_lead_without_an_access_url(env, capsys):
    (env / "inbox" / "fictional-register").mkdir()
    (env / "inbox" / "fictional-register" / "access.html").write_bytes(fixture("saved-access.html"))
    assert run(env, *good_args("access", ACCESS, lead="fictional-register")) == 1
    assert "no access_url" in capsys.readouterr().err
    assert cache_files(env) == []


@pytest.mark.parametrize(
    ("page", "url"),
    [
        ("main", "https://www.decodeme.org.uk/researcher-access"),
        ("main", MAIN + "/"),
        ("main", ACCESS),
        ("access", MAIN),
    ],
)
def test_refuses_a_url_that_is_not_exactly_the_leads_address(env, capsys, page, url):
    assert run(env, *good_args(page, url)) == 1
    assert "--url must be exactly" in capsys.readouterr().err
    assert cache_files(env) == []


@pytest.mark.parametrize("saved", ["yesterday", "2026-13-01", "2026-11-19", "2027-01-01", "20261110"])
def test_refuses_a_saved_date_that_is_not_a_date_or_is_later_than_today(env, capsys, saved):
    assert run(env, *good_args(saved=saved)) == 1
    assert "--saved" in capsys.readouterr().err
    assert cache_files(env) == []


def test_today_itself_is_accepted_as_the_saved_date(env):
    assert run(env, *good_args(saved=TODAY)) == 0


def test_refuses_when_the_inbox_file_is_missing(env, capsys):
    (env / "inbox" / LEAD / "main.html").unlink()
    assert run(env, *good_args()) == 1
    assert "the saved page is missing" in capsys.readouterr().err
    assert cache_files(env) == []


def test_refuses_to_overwrite_a_stored_page_whatever_its_origin(env, capsys):
    assert run(env, *good_args()) == 0
    before = {p: p.read_bytes() for p in cache_files(env) if p.is_file()}
    assert run(env, *good_args()) == 1
    assert "not overwritten" in capsys.readouterr().err
    assert {p: p.read_bytes() for p in cache_files(env) if p.is_file()} == before
    # a fetched page counts too: any meta file present
    d = stored(env, day="2026-11-11")
    d.mkdir(parents=True)
    (d / "main.meta.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    assert run(env, *good_args(saved="2026-11-11")) == 1
    assert not (d / "main.html").exists()


# --- H5: fetch never overwrites a hand-saved page ----------------------------------------------------------------


def test_fetch_online_skips_a_hand_saved_page_and_reports_its_stored_status(env):
    assert run(env, *good_args(saved=DAY)) == 0
    d = stored(env, day=DAY)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    log: list = []
    refusing = {MAIN: (403, HTML, b"denied", {})}
    fetcher = make_fetcher({**all_routes(), **refusing}, log=log)
    out = env / "pipeline"
    report = resources.run_fetch(LEADS[:1], env / "cache", out, day=DAY, fetcher=fetcher)
    assert {p.name: p.read_bytes() for p in d.iterdir() if p.name.startswith("main")} == {
        k: v for k, v in before.items() if k.startswith("main")
    }
    assert report["leads"][LEAD]["main"] == "ok"
    assert MAIN not in [u for _, u in log]  # no request for the hand-saved page
    assert report["leads"][LEAD]["access"] == "ok"  # the other page is still fetched


def test_fetch_online_still_overwrites_a_page_it_fetched_itself(env):
    out = env / "pipeline"
    resources.run_fetch(LEADS[:1], env / "cache", out, day=DAY, fetcher=make_fetcher(all_routes()))
    refusing = {**all_routes(), MAIN: (403, HTML, b"denied", {})}
    report = resources.run_fetch(LEADS[:1], env / "cache", out, day=DAY, fetcher=make_fetcher(refusing))
    assert report["leads"][LEAD]["main"] == "blocked"


def test_a_stored_blocked_hand_saved_page_stays_blocked_in_the_report(env):
    (env / "inbox" / LEAD / "main.html").write_bytes(fixture("saved-bot-check.html"))
    run(env, *good_args(saved=DAY))
    report = resources.run_fetch(LEADS[:1], env / "cache", env / "p", day=DAY, fetcher=make_fetcher(all_routes()))
    assert report["leads"][LEAD]["main"] == "blocked" and report["fetchable"] == []


def test_fetch_offline_reads_hand_saved_pages_like_any_other(env):
    run(env, *good_args("main", MAIN, DAY))
    run(env, *good_args("access", ACCESS, DAY))
    log: list = []
    report = resources.run_fetch(
        LEADS[:1], env / "cache", env / "p", day=DAY, offline=True, fetcher=make_fetcher({}, log=log)
    )
    assert log == [] and report["leads"][LEAD] == {"main": "ok", "access": "ok"} and report["fetchable"] == [LEAD]


# --- H6: plan ---------------------------------------------------------------------------------------------------


def planned(env: Path) -> dict:
    out = env / "p"
    resources.run_fetch(LEADS[:1], env / "cache", out, day=DAY, offline=True)
    (path,) = resources.run_plan(LEADS[:1], env / "cache", out, day=DAY)
    return json.loads(path.read_text(encoding="utf-8"))


def test_plan_lists_the_hand_saved_page_keys_sorted_and_an_empty_list_when_none(env):
    run(env, *good_args("access", ACCESS, DAY))
    run(env, *good_args("main", MAIN, DAY))
    assert planned(env)["hand_saved"] == ["access", "main"]


def test_plan_names_only_the_hand_saved_page_when_the_other_was_fetched(env):
    run(env, *good_args("main", MAIN, DAY))
    resources.store_page(
        stored(env, day=DAY),
        "access",
        ACCESS,
        resources.Page("ok", 200, ACCESS, HTML, fixture("good-access.html"), "x" * 300),
        DAY,
    )
    assert planned(env)["hand_saved"] == ["main"]


def test_plan_reads_a_meta_without_the_obtained_key_as_fetched(env):
    run(env, *good_args("main", MAIN, DAY))
    run(env, *good_args("access", ACCESS, DAY))
    for key in ("main", "access"):
        path = stored(env, day=DAY) / f"{key}.meta.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        del meta["obtained"]
        path.write_text(json.dumps(meta), encoding="utf-8")
    assert planned(env)["hand_saved"] == []


# --- H7: the data file --------------------------------------------------------------------------------------------


def test_build_entry_writes_hand_saved_only_when_a_page_was_saved_by_hand():
    assert "hand_saved" not in good_entry()
    assert "hand_saved" not in resources.build_entry(context() | {"hand_saved": []}, named(good_draft(), LEAD))
    entry = resources.build_entry(context() | {"hand_saved": ["access", "main"]}, named(good_draft(), LEAD))
    assert entry["hand_saved"] == ["main", "access"]
    assert resources.check_data(good_file(entry)) == []


def with_saved(value) -> dict:
    return good_file({**good_entry(), "hand_saved": value})


@pytest.mark.parametrize(
    "value",
    [[], "main", ["main", "main"], ["elsewhere"], [1], None],
)
def test_check_data_refuses_a_hand_saved_that_is_not_a_non_empty_list_of_distinct_page_keys(value):
    found = resources.check_data(with_saved(value))
    assert any("hand_saved: must be a non-empty list of distinct page keys" in p for p in found), found


def test_check_data_refuses_a_hand_saved_key_that_is_not_in_text_hash():
    entry = good_entry()
    del entry["text_hash"]["access"]
    entry["quotes"]["access"]["page"] = "main"
    entry["quotes"]["covers"]["page"] = "main"
    found = resources.check_data(good_file({**entry, "hand_saved": ["access"]}))
    assert any("hand_saved: every page key must be a page in text_hash" in p for p in found), found
    assert resources.check_data(good_file({**entry, "hand_saved": ["main"]})) == []


def test_check_data_accepts_the_key_as_optional():
    assert resources.check_data(with_saved(["main"])) == []
    assert resources.check_data(with_saved(["main", "access"])) == []
    assert resources.check_data(good_file()) == []


def cache_with_meta(tmp_path, obtained: dict[str, str | None]) -> Path:
    root = stored_cache(tmp_path)
    d = root / DAY / LEAD
    for key, how in obtained.items():
        meta = {"status": "ok", "fetched": DAY}
        if how is not None:
            meta["obtained"] = how
        (d / f"{key}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return root


def test_check_cache_refuses_an_entry_that_says_hand_saved_when_the_meta_has_no_obtained_key(tmp_path):
    root = cache_with_meta(tmp_path, {"main": None, "access": None})
    found = resources.check_against_cache(with_saved(["main"]), root)
    assert found == [
        f"{LEAD}: page 'main': hand_saved in the entry disagrees with the stored metadata (obtained: fetched)"
    ]


def test_check_cache_refuses_a_meta_that_says_hand_saved_when_the_entry_does_not(tmp_path):
    root = cache_with_meta(tmp_path, {"main": "hand_saved", "access": "fetched"})
    found = resources.check_against_cache(good_file(), root)
    assert len(found) == 1 and "page 'main'" in found[0] and "obtained: hand_saved" in found[0]


def test_check_cache_passes_when_entry_and_metas_agree(tmp_path):
    root = cache_with_meta(tmp_path, {"main": "hand_saved", "access": "fetched"})
    assert resources.check_against_cache(with_saved(["main"]), root) == []
    root = cache_with_meta(tmp_path / "other", {"main": "fetched", "access": None})
    assert resources.check_against_cache(good_file(), root) == []


def test_check_cache_refuses_a_hand_saved_claim_with_no_stored_meta(tmp_path):
    found = resources.check_against_cache(with_saved(["main"]), stored_cache(tmp_path))
    assert any("hand_saved, but no stored metadata" in p for p in found)


def test_the_real_data_file_has_no_hand_saved_key_and_passes_check():
    data = resources.load_data(Path("registry/resources.yaml"))
    assert all("hand_saved" not in e for e in data["entries"])
    assert resources.check_data(data) == []


def test_the_whole_path_from_a_saved_page_to_the_entry(env):
    """import-saved -> fetch --offline -> plan: the context carries hand_saved and the entry is marked."""
    run(env, *good_args("main", MAIN, DAY))
    run(env, *good_args("access", ACCESS, DAY))
    ctx = planned(env)
    assert resources.build_entry(ctx, _draft_from(ctx))["hand_saved"] == ["main", "access"]


def _draft_from(ctx: dict) -> dict:
    main = ctx["pages"]["main"]
    access = ctx["pages"]["access"]
    assert "operated by the Imaginary Institute of Medicine" in main and "Access is granted by application" in access
    draft = good_draft()
    draft["id"] = ctx["id"]
    quotes = {
        "name": ("Fictional Saved Cohort", "main"),
        "operator": ("operated by the Imaginary Institute of Medicine", "main"),
        "countries": ("Freedonia", "main"),
        "access": ("Access is granted by application", "access"),
        "covers": ("people with ME/CFS", "main"),
    }
    for field, (quote, page_key) in quotes.items():
        draft[field]["quote"], draft[field]["page"] = quote, page_key
    draft["name"]["value"] = "Fictional Saved Cohort"
    draft["holds"] = [{"value": "questionnaires", "quote": "holds questionnaire data", "page": "main"}]
    assert resources.validate_draft(draft, ctx) == []
    return draft


def test_the_inbox_default_is_the_gitignored_folder():
    assert Path("data/hand-saved/resources") == resources.DEFAULT_SAVED_DIR
    assert "data/hand-saved/" in Path(".gitignore").read_text(encoding="utf-8").splitlines()


# --- amendments: .htm and a kept failed fetch --------------------------------------------------------------------


def test_an_htm_file_in_the_inbox_is_accepted(env):
    inbox = env / "inbox" / LEAD
    (inbox / "main.html").rename(inbox / "main.htm")
    assert run(env, *good_args()) == 0
    assert (stored(env) / "main.html").read_bytes() == fixture("saved-main.html")


def test_both_html_and_htm_for_one_page_is_refused_and_nothing_is_written(env, capsys):
    inbox = env / "inbox" / LEAD
    (inbox / "main.htm").write_bytes(fixture("saved-main.html"))
    assert run(env, *good_args()) == 1
    assert "both exist" in capsys.readouterr().err
    assert cache_files(env) == []


def store_fetched(env: Path, status: str, with_body: bool = False) -> Path:
    d = stored(env)
    d.mkdir(parents=True)
    (d / "main.meta.json").write_text(
        json.dumps({"requested_url": MAIN, "http_status": 403, "fetched": SAVED_DAY, "status": status}),
        encoding="utf-8",
    )
    if with_body:
        (d / "main.html").write_bytes(b"x")
        (d / "main.txt").write_text("x", encoding="utf-8")
    return d


def test_a_stored_failed_fetch_is_kept_under_a_new_name_and_the_saved_page_is_stored(env):
    d = store_fetched(env, "blocked")
    assert run(env, *good_args()) == 0
    assert json.loads((d / "main.fetch-refused.meta.json").read_text(encoding="utf-8"))["status"] == "blocked"
    assert resources.read_meta(d, "main")["obtained"] == "hand_saved"
    assert (d / "main.html").read_bytes() == fixture("saved-main.html")
    assert not (d / "main.fetch-refused.html").exists()


def test_a_failed_fetch_with_a_body_keeps_all_its_files_and_they_are_not_read_as_a_page(env):
    d = store_fetched(env, "no_text", with_body=True)
    assert run(env, *good_args("main", MAIN, SAVED_DAY)) == 0
    assert (d / "main.fetch-refused.html").read_bytes() == b"x"
    assert (d / "main.fetch-refused.txt").read_text(encoding="utf-8") == "x"
    assert resources.stored_text(env / "cache", SAVED_DAY, LEAD, "main") == resources.extract_text(
        fixture("saved-main.html").decode()
    )
    report = resources.run_fetch(LEADS[:1], env / "cache", env / "p", day=SAVED_DAY, offline=True)
    assert report["leads"][LEAD]["main"] == "ok"


def test_a_failed_fetch_already_kept_blocks_a_second_replacement(env, capsys):
    d = store_fetched(env, "blocked")
    (d / "main.fetch-refused.meta.json").write_text("{}", encoding="utf-8")
    assert run(env, *good_args()) == 1
    assert "already kept" in capsys.readouterr().err
    assert json.loads((d / "main.meta.json").read_text(encoding="utf-8"))["status"] == "blocked"


def test_a_stored_ok_page_or_a_hand_saved_page_still_refuses_without_renaming(env, capsys):
    d = store_fetched(env, "ok")
    assert run(env, *good_args()) == 1
    assert "not overwritten" in capsys.readouterr().err
    assert not list(d.glob("*.fetch-refused.*"))
    shutil_d = stored(env, day="2026-11-11")
    shutil_d.mkdir(parents=True)
    (shutil_d / "main.meta.json").write_text(
        json.dumps({"status": "blocked", "obtained": "hand_saved"}), encoding="utf-8"
    )
    assert run(env, *good_args(saved="2026-11-11")) == 1
    assert not list(shutil_d.glob("*.fetch-refused.*"))
