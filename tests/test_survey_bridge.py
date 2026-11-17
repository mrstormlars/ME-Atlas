"""Offline tests for the bridge search pilot (me_atlas.bridge, wired in as `survey bridge`)."""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import shutil
from pathlib import Path

import httpx
import pytest
import yaml

from me_atlas import survey
from me_atlas.bridge import SCREEN_LIMIT, validate_agent_file
from me_atlas.pubmed import RawCache

FIXTURES = Path(__file__).parent / "fixtures" / "bridge"
TODAY = dt.date(2026, 11, 16)
ENV = {"CONTACT_EMAIL": "tester@example.org"}

# Query strings of the test config, one per search the run makes.
Q = {
    "Q1g": ("Q1 general", "Q1 general restricted"),
    "Q1l": ("Q1 long covid", "Q1 long covid restricted"),
    "Q2g": ("Q2 general", "Q2 general restricted"),
    "Q2l": ("Q2 long covid", "Q2 long covid restricted"),
}
ORIGINALS = {"Q1": "Q1 originals", "Q2": "Q2 originals"}
GENERATED = [f"93{i:06d}" for i in range(1, 61)]  # 60 invented ids with generated records

CONFIG = """\
questions:
- id: Q1
  kind: founder
  from: card-a
  to: card-b
  arms:
    general: {query: "Q1 general", restricted: "Q1 general restricted"}
    long_covid: {query: "Q1 long covid", restricted: "Q1 long covid restricted", originals_count: "Q1 originals"}
- id: Q2
  kind: base_rate
  from: card-a
  to: card-c
  arms:
    general: {query: "Q2 general", restricted: "Q2 general restricted"}
    long_covid: {query: "Q2 long covid", restricted: "Q2 long covid restricted", originals_count: "Q2 originals"}
"""

# term -> (total count, ids PubMed would list in its default order)
RESULTS: dict[str, tuple[int, list[str]]] = {
    "Q1 general": (3, ["92000001", "92000002", "92000003"]),  # at most 40: all screened
    "Q1 long covid": (45, GENERATED[:45]),  # over 40 ...
    "Q1 long covid restricted": (2, ["92000002", "92000003"]),  # ... so the restricted form is used
    "Q1 originals": (7, []),
    "Q2 general": (60, GENERATED),  # over 40 ...
    "Q2 general restricted": (0, []),  # ... restricted finds nothing: fall back to the unrestricted ids
    "Q2 long covid": (0, []),
    "Q2 originals": (11, []),
}


def generated_xml(pmid: str) -> str:
    return (
        f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">{pmid}</PMID><Article>'
        f"<Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue><Title>J</Title></Journal>"
        f"<ArticleTitle>Invented review {pmid}.</ArticleTitle>"
        f"<Abstract><AbstractText>Invented abstract {pmid}.</AbstractText></Abstract>"
        f"<PublicationTypeList><PublicationType>Meta-Analysis</PublicationType></PublicationTypeList>"
        f"</Article></MedlineCitation><PubmedData><ArticleIdList>"
        f'<ArticleId IdType="pubmed">{pmid}</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
    )


class FakeClock:
    """A clock that only moves when sleep() is called, so the rate limiter never really waits."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class FakeEutils:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def terms(self) -> list[str]:
        return [r.url.params["term"] for r in self.requests if r.url.path.endswith("esearch.fcgi")]

    def fetched(self) -> list[str]:
        out: list[str] = []
        for r in self.requests:
            if r.url.path.endswith("efetch.fcgi"):
                out += r.url.params["id"].split(",")
        return out

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params
        if request.url.path.endswith("esearch.fcgi"):
            count, ids = RESULTS[params["term"]]
            body = {"esearchresult": {"count": str(count), "idlist": ids[: int(params["retmax"])]}}
            return httpx.Response(200, json=body)
        articles = []
        for pmid in params["id"].split(","):
            path = FIXTURES / f"{pmid}.xml"
            xml = path.read_text(encoding="utf-8") if path.is_file() else generated_xml(pmid)
            articles.append(xml.split("<PubmedArticleSet>")[1].split("</PubmedArticleSet>")[0])
        return httpx.Response(200, content=("<PubmedArticleSet>" + "".join(articles) + "</PubmedArticleSet>").encode())


@pytest.fixture
def setup(tmp_path: Path):
    config = tmp_path / "bridge.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    cards = tmp_path / "cards"
    cards.mkdir()
    for slug, name in (("card-a", "Card Alpha"), ("card-b", "Card Beta"), ("card-c", "Card Gamma")):
        (cards / f"{slug}.yaml").write_text(f"slug: {slug}\nname: {name}\n", encoding="utf-8")
    return {
        "config": config,
        "cards": cards,
        "cache": tmp_path / "cache",
        "out": tmp_path / "out",
        "eutils": FakeEutils(),
    }


def run_cli(setup, *, env=ENV, extra: list[str] | None = None) -> int:
    argv = [
        "bridge",
        "run",
        "--config",
        str(setup["config"]),
        "--cards",
        str(setup["cards"]),
        "--cache-dir",
        str(setup["cache"]),
        "--out",
        str(setup["out"]),
        *(extra or []),
    ]
    return survey.main(
        argv,
        env=env,
        transport=httpx.MockTransport(setup["eutils"].handler),
        clock=(clock := FakeClock()),
        sleep=clock.sleep,
        today=TODAY,
    )


def counts_of(setup) -> dict:
    return json.loads((setup["out"] / "counts.json").read_text(encoding="utf-8"))


def arm_of(setup, qid: str, arm: str) -> dict:
    q = next(q for q in counts_of(setup)["questions"] if q["id"] == qid)
    return q["arms"][arm]


# --- run -------------------------------------------------------------------------------------------------------------


def test_arm_with_40_or_fewer_is_screened_in_full(setup):
    assert run_cli(setup) == 0
    arm = arm_of(setup, "Q1", "general")
    assert arm["count"] == 3
    assert arm["rule"] == "all"
    assert arm["screened_pmids"] == ["92000001", "92000002", "92000003"]
    assert arm["restricted_count"] is None
    assert "Q1 general restricted" not in setup["eutils"].terms()


def test_arm_over_the_limit_uses_the_restricted_query(setup):
    assert run_cli(setup) == 0
    arm = arm_of(setup, "Q1", "long_covid")
    assert arm["count"] == 45
    assert arm["restricted_count"] == 2
    assert arm["restricted_query"] == "Q1 long covid restricted"
    assert arm["rule"] == "restricted"
    assert arm["screened_pmids"] == ["92000002", "92000003"]


def test_restricted_zero_falls_back_to_the_first_40_unrestricted(setup):
    assert run_cli(setup) == 0
    arm = arm_of(setup, "Q2", "general")
    assert arm["count"] == 60
    assert arm["restricted_count"] == 0
    assert arm["rule"] == "fallback_unrestricted"
    assert arm["screened_pmids"] == GENERATED[:SCREEN_LIMIT]
    text = (setup["out"] / "context" / "Q2-general.md").read_text(encoding="utf-8")
    assert "Screening rule: fallback_unrestricted" in text
    assert len(survey.context_pmids(text)) == 40


def test_originals_count_is_a_count_only_and_for_long_covid_only(setup):
    assert run_cli(setup) == 0
    assert arm_of(setup, "Q1", "long_covid")["originals_count"] == 7
    assert arm_of(setup, "Q2", "long_covid")["originals_count"] == 11
    assert arm_of(setup, "Q1", "general")["originals_count"] is None
    searches = [r for r in setup["eutils"].requests if r.url.params.get("term") == "Q1 originals"]
    assert [r.url.params["retmax"] for r in searches] == ["0"]


def test_records_are_cached_under_the_given_cache_dir_and_not_refetched(setup, tmp_path):
    assert run_cli(setup) == 0
    cache = RawCache(setup["cache"])
    assert cache.has("92000001")
    assert (setup["cache"] / "pubmed" / "92000001.xml").is_file()
    assert not (Path("data/cache/pubmed") / "92000001.xml").exists()
    first_fetches = setup["eutils"].fetched()
    assert sorted(first_fetches) == sorted(set(first_fetches))  # no PMID twice in one run
    assert set(first_fetches) == {"92000001", "92000002", "92000003", *GENERATED[:SCREEN_LIMIT]}

    setup["eutils"] = FakeEutils()
    assert run_cli(setup) == 0
    assert setup["eutils"].fetched() == []  # everything is cached


def test_counts_json_has_the_contract_fields(setup):
    assert run_cli(setup) == 0
    counts = counts_of(setup)
    assert counts["date"] == "2026-11-16"
    assert [q["id"] for q in counts["questions"]] == ["Q1", "Q2"]
    arm = arm_of(setup, "Q1", "long_covid")
    assert set(arm) >= {
        "query",
        "count",
        "restricted_query",
        "restricted_count",
        "originals_query",
        "originals_count",
        "rule",
        "screened_pmids",
    }
    assert arm["query"] == "Q1 long covid"
    assert arm["originals_query"] == "Q1 originals"


def test_context_file_header_and_records(setup):
    assert run_cli(setup) == 0
    text = (setup["out"] / "context" / "Q1-general.md").read_text(encoding="utf-8")
    assert "Question: Q1\n" in text
    assert "Arm: general\n" in text
    assert "A: card-a (Card Alpha)\n" in text
    assert "B: card-b (Card Beta)\n" in text
    assert "Query: Q1 general\n" in text
    assert "Records found by the query: 3\n" in text
    assert "Screened but not listed (not in the cache or not readable): none\n" in text
    assert survey.context_pmids(text) == {"92000001", "92000002", "92000003"}
    assert "Title: Fictional systematic review of alpha activity and beta outcomes in invented adults." in text
    assert "- year: 2022" in text
    assert "- publication types: Journal Article, Systematic Review" in text
    assert "- MeSH headings: Humans" in text
    assert "Twelve invented studies were pooled" in text
    assert "(no abstract in the record)" in text


def test_arm_with_no_records_gets_a_context_file_that_says_so(setup):
    assert run_cli(setup) == 0
    text = (setup["out"] / "context" / "Q2-long_covid.md").read_text(encoding="utf-8")
    assert "No records were screened" in text
    assert "Records found by the query: 0" in text
    assert survey.context_pmids(text) == set()
    assert len(list((setup["out"] / "context").glob("*.md"))) == 4


def test_unretrieved_record_is_named_in_the_header_not_dropped_silently(setup):
    original = setup["eutils"].handler

    def drop(request: httpx.Request) -> httpx.Response:
        response = original(request)
        if request.url.path.endswith("efetch.fcgi"):
            body = response.content.decode().replace(
                "92000003", "92999999", 1
            )  # the record comes back under another id
            return httpx.Response(200, content=body.encode())
        return response

    assert survey_run_with(setup, drop) == 0
    text = (setup["out"] / "context" / "Q1-general.md").read_text(encoding="utf-8")
    assert "not listed (not in the cache or not readable): 92000003" in text
    assert "92000003" not in survey.context_pmids(text)
    assert arm_of(setup, "Q1", "general")["not_listed_pmids"] == ["92000003"]


def survey_run_with(setup, handler) -> int:
    return survey.main(
        [
            "bridge",
            "run",
            "--config",
            str(setup["config"]),
            "--cards",
            str(setup["cards"]),
            "--cache-dir",
            str(setup["cache"]),
            "--out",
            str(setup["out"]),
        ],
        env=ENV,
        transport=httpx.MockTransport(handler),
        clock=(clock := FakeClock()),
        sleep=clock.sleep,
        today=TODAY,
    )


@pytest.mark.parametrize("env", [{}, {"CONTACT_EMAIL": "  "}])
def test_missing_contact_email_exits_nonzero_and_makes_no_request(setup, env, capsys):
    assert run_cli(setup, env=env) != 0
    assert "CONTACT_EMAIL" in capsys.readouterr().err
    assert setup["eutils"].requests == []
    assert not setup["out"].exists()


def test_default_out_directory_is_dated(setup, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    argv = ["bridge", "run", "--config", str(setup["config"]), "--cards", str(setup["cards"])]
    argv += ["--cache-dir", str(setup["cache"])]
    code = survey.main(
        argv,
        env=ENV,
        transport=httpx.MockTransport(setup["eutils"].handler),
        clock=(clock := FakeClock()),
        sleep=clock.sleep,
        today=TODAY,
    )
    assert code == 0
    assert (tmp_path / "data" / "pipeline" / "2026-11-16-bridge-pilot" / "counts.json").is_file()


# --- validate --------------------------------------------------------------------------------------------------------

YES_ROW = {
    "pmid": "92000001",
    "statement": "yes",
    "relation": "present",
    "population": "invented adults",
    "direction": "association",
    "meta_analysis": True,
    "studies_pooled": 12,
    "quote": "Alpha activity was associated with beta outcomes in invented adults.",
}


@pytest.fixture
def ran(setup):
    assert run_cli(setup) == 0
    context = setup["out"] / "context" / "Q1-general.md"
    return {"context": context, "cache": setup["cache"], "dir": setup["out"]}


def good_file() -> dict:
    return {
        "question": "Q1",
        "arm": "general",
        "rows": [
            dict(YES_ROW),
            {"pmid": "92000002", "statement": "animal_or_cell_only", "note": "mouse cells only"},
            {"pmid": "92000003", "statement": "no"},
        ],
    }


def problems(ran, data) -> list[str]:
    return validate_agent_file(data, ran["context"].read_text(encoding="utf-8"), RawCache(ran["cache"]))


def with_row(data: dict, **changes) -> dict:
    data["rows"][0] = {**data["rows"][0], **changes}
    return data


def test_valid_file_is_accepted_through_the_command_line(ran, capsys):
    path = ran["dir"] / "survey.json"
    path.write_text(json.dumps(good_file()), encoding="utf-8")
    code = survey.main(
        ["bridge", "validate", str(path), "--context", str(ran["context"]), "--cache-dir", str(ran["cache"])]
    )
    assert code == 0
    assert "OK" in capsys.readouterr().out


def test_invalid_file_exits_1_and_names_the_problem(ran, capsys):
    data = with_row(good_file(), pmid="99999999")
    path = ran["dir"] / "survey.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    code = survey.main(
        ["bridge", "validate", str(path), "--context", str(ran["context"]), "--cache-dir", str(ran["cache"])]
    )
    assert code == 1
    assert "pmid 99999999 is not in the context file" in capsys.readouterr().err


def test_valid_file_has_no_problems(ran):
    assert problems(ran, good_file()) == []


def test_quote_with_different_whitespace_is_accepted(ran):
    # the abstract has a line break and extra spaces between the two sentences
    quote = "Twelve invented studies were pooled in a meta-analysis. Alpha activity was associated"
    assert problems(ran, with_row(good_file(), quote=quote)) == []


def test_quote_from_the_title_is_accepted(ran):
    quote = "Fictional systematic review of alpha activity and beta outcomes in invented adults."
    assert problems(ran, with_row(good_file(), quote=quote)) == []


def test_unknown_top_level_key_is_rejected(ran):
    data = {**good_file(), "extra": 1}
    assert "unknown key 'extra'" in problems(ran, data)


def test_pmid_not_in_the_context_file_is_rejected(ran):
    errors = problems(ran, with_row(good_file(), pmid="99999999"))
    assert any("pmid 99999999 is not in the context file" in e for e in errors)


def test_quote_altered_by_one_word_is_rejected(ran):
    quote = YES_ROW["quote"].replace("associated", "linked")
    errors = problems(ran, with_row(good_file(), quote=quote))
    assert any("not found verbatim" in e for e in errors)


def test_quote_differing_only_in_case_is_rejected(ran):
    errors = problems(ran, with_row(good_file(), quote=YES_ROW["quote"].lower()))
    assert any("not found verbatim" in e for e in errors)


def test_quote_for_a_record_missing_from_the_cache_is_rejected(ran):
    (ran["cache"] / "pubmed" / "92000001.xml").unlink()
    errors = problems(ran, good_file())
    assert any("not in the cache" in e for e in errors)


def test_statement_outside_the_list_is_rejected(ran):
    errors = problems(ran, with_row(good_file(), statement="maybe"))
    assert any("statement: must be one of yes, no, animal_or_cell_only" in e for e in errors)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("relation", "unclear"),
        ("direction", "a_causes_b"),
        ("meta_analysis", "yes"),
        ("studies_pooled", 0),
        ("studies_pooled", True),
        ("studies_pooled", "12"),
        ("population", "  "),
        ("quote", ""),
    ],
)
def test_yes_row_with_an_invalid_value_is_rejected(ran, key, value):
    assert problems(ran, with_row(good_file(), **{key: value}))


@pytest.mark.parametrize("key", ["relation", "direction", "meta_analysis", "studies_pooled", "population", "quote"])
def test_yes_row_missing_a_key_is_rejected(ran, key):
    data = good_file()
    del data["rows"][0][key]
    assert f"rows[0]: missing key '{key}'" in problems(ran, data)


def test_studies_pooled_null_is_accepted(ran):
    assert problems(ran, with_row(good_file(), studies_pooled=None)) == []


def test_no_row_with_extra_keys_is_rejected(ran):
    data = good_file()
    data["rows"][2]["relation"] = "present"
    assert "rows[2]: unknown key 'relation'" in problems(ran, data)


def test_unknown_key_in_a_yes_row_is_rejected(ran):
    assert "rows[0]: unknown key 'confidence'" in problems(ran, with_row(good_file(), confidence="high"))


def test_pmid_listed_twice_is_rejected(ran):
    data = good_file()
    data["rows"][2]["pmid"] = "92000002"
    errors = problems(ran, data)
    assert any("listed twice" in e for e in errors)


def test_screened_pmid_without_a_row_is_rejected(ran):
    data = good_file()
    del data["rows"][2]
    assert "pmid 92000003 is in the context file but has no row" in problems(ran, data)


def test_question_and_arm_must_match_the_context_header(ran):
    data = {**good_file(), "question": "Q2", "arm": "long_covid"}
    errors = problems(ran, data)
    assert any("'question' must be 'Q1'" in e for e in errors)
    assert any("'arm' must be 'general'" in e for e in errors)


def test_banned_word_in_population_or_note_is_rejected(ran):
    errors = problems(ran, with_row(good_file(), population="a promising group"))
    assert any("banned word 'promising'" in e for e in errors)
    data = good_file()
    data["rows"][1]["note"] = "a cure"
    assert any("banned word 'cure'" in e for e in problems(ran, data))


def test_non_object_file_is_rejected(ran):
    assert problems(ran, []) == ["top level must be a JSON object"]


# --- pilot 2: --screened-from and --ends ----------------------------------------------------------------------------


AGENT = Path(__file__).parent.parent / ".claude" / "agents" / "bridge-surveyor.md"
P2_GENERAL = ["92100001", "92100002", "92100003", "92100004"]  # screened in Q1 general
ENDS_TEXT = """\
ends:
  card-a: >-
    Invented definition of alpha, kept on
    two source lines.
  card-b: Invented definition of beta.
  card-c: Invented definition of gamma.
"""


def counts_data() -> dict:
    """A pilot 1 counts.json for the test config; only Q1 general lists records."""
    questions = []
    for q in yaml.safe_load(CONFIG)["questions"]:
        arms = {}
        for arm in ("general", "long_covid"):
            cfg = q["arms"][arm]
            arms[arm] = {
                "query": cfg["query"],
                "count": 3 if arm == "general" else 45,
                "restricted_query": None if arm == "general" else cfg["restricted"],
                "restricted_count": None if arm == "general" else 2,
                "originals_query": cfg.get("originals_count"),
                "originals_count": 7 if arm == "long_covid" else None,
                "rule": "all" if arm == "general" else "restricted",
                "screened_pmids": P2_GENERAL if (q["id"], arm) == ("Q1", "general") else [],
                "warnings": [],
                "not_listed_pmids": [],
            }
        questions.append({"id": q["id"], "kind": q["kind"], "from": q["from"], "to": q["to"], "arms": arms})
    return {"date": "2026-11-16", "screen_limit": 40, "questions": questions}


@pytest.fixture
def p2(setup, tmp_path):
    counts = tmp_path / "pilot1" / "counts.json"
    counts.parent.mkdir()
    counts.write_text(json.dumps(counts_data()), encoding="utf-8")
    ends = tmp_path / "ends.yaml"
    ends.write_text(ENDS_TEXT, encoding="utf-8")
    cache_dir = setup["cache"] / "pubmed"
    cache_dir.mkdir(parents=True)
    for pmid in P2_GENERAL:
        shutil.copy(FIXTURES / f"{pmid}.xml", cache_dir / f"{pmid}.xml")
    setup["counts"] = counts
    setup["ends"] = ends
    setup["extra"] = ["--screened-from", str(counts), "--ends", str(ends)]
    return setup


def run_p2(p2, *, env=ENV, extra=None, handler=None) -> int:
    handler = handler or p2["eutils"].handler
    argv = [
        "bridge",
        "run",
        "--config",
        str(p2["config"]),
        "--cards",
        str(p2["cards"]),
        "--cache-dir",
        str(p2["cache"]),
        "--out",
        str(p2["out"]),
        *(p2["extra"] if extra is None else extra),
    ]
    return survey.main(
        argv,
        env=env,
        transport=httpx.MockTransport(handler),
        clock=(clock := FakeClock()),
        sleep=clock.sleep,
        today=dt.date(2026, 11, 17),
    )


def p2_context(p2, name="Q1-general") -> str:
    return (p2["out"] / "context" / f"{name}.md").read_text(encoding="utf-8")


def test_screened_from_makes_no_request_and_needs_no_email_when_all_cached(p2):
    seen: list[httpx.Request] = []

    def fail(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500)

    assert run_p2(p2, env={}, handler=fail) == 0
    assert seen == []
    assert survey.context_pmids(p2_context(p2)) == set(P2_GENERAL)
    arm = arm_of(p2, "Q1", "long_covid")
    assert (arm["count"], arm["rule"], arm["originals_count"], arm["restricted_count"]) == (45, "restricted", 7, 2)
    counts = counts_of(p2)
    assert counts["screened_from"] == str(p2["counts"])
    assert counts["fetched_pmids"] == []
    assert len(list((p2["out"] / "context").glob("*.md"))) == 4


def test_screened_from_makes_no_esearch_and_fetches_only_missing_records(p2):
    (p2["cache"] / "pubmed" / "92100003.xml").unlink()
    assert run_p2(p2) == 0
    assert p2["eutils"].terms() == []
    assert p2["eutils"].fetched() == ["92100003"]
    assert counts_of(p2)["fetched_pmids"] == ["92100003"]
    assert "pmid:92100003" in survey.context_pmids(p2_context(p2)) or "92100003" in survey.context_pmids(p2_context(p2))


def test_screened_from_with_a_missing_record_needs_the_contact_email(p2, capsys):
    (p2["cache"] / "pubmed" / "92100003.xml").unlink()
    assert run_p2(p2, env={}) == 2
    assert "CONTACT_EMAIL" in capsys.readouterr().err
    assert p2["eutils"].requests == []
    assert not p2["out"].exists()


@pytest.mark.parametrize(
    ("question", "arm", "key", "where"),
    [
        ("Q1", "general", "query", "question Q1, arm general"),
        ("Q2", "long_covid", "query", "question Q2, arm long_covid"),
        ("Q1", "long_covid", "restricted_query", "question Q1, arm long_covid"),
        ("Q2", "long_covid", "originals_query", "question Q2, arm long_covid"),
    ],
)
def test_query_differing_by_one_character_exits_1_and_writes_nothing(p2, capsys, question, arm, key, where):
    data = counts_data()
    entry = next(q for q in data["questions"] if q["id"] == question)["arms"][arm]
    entry[key] = entry[key] + "."
    p2["counts"].write_text(json.dumps(data), encoding="utf-8")
    assert run_p2(p2) == 1
    err = capsys.readouterr().err
    assert where in err
    assert key in err
    assert not p2["out"].exists()


def test_question_missing_from_the_counts_file_exits_1(p2, capsys):
    data = counts_data()
    data["questions"] = [q for q in data["questions"] if q["id"] != "Q2"]
    p2["counts"].write_text(json.dumps(data), encoding="utf-8")
    assert run_p2(p2) == 1
    assert "question Q2" in capsys.readouterr().err
    assert not p2["out"].exists()


def test_arm_missing_from_the_counts_file_exits_1(p2, capsys):
    data = counts_data()
    del data["questions"][0]["arms"]["long_covid"]
    p2["counts"].write_text(json.dumps(data), encoding="utf-8")
    assert run_p2(p2) == 1
    err = capsys.readouterr().err
    assert "question Q1, arm long_covid" in err
    assert not p2["out"].exists()


@pytest.mark.parametrize(
    "text", ["ends:\n  card-a: A\n  card-b: B\n", "ends:\n  card-a: A\n  card-b: B\n  card-c: '  '\n"]
)
def test_end_without_a_definition_exits_1(p2, capsys, text):
    p2["ends"].write_text(text, encoding="utf-8")  # card-c, the B end of Q2, is missing or blank
    assert run_p2(p2) == 1
    assert "card-c" in capsys.readouterr().err
    assert not p2["out"].exists()


def test_pilot_2_context_file(p2):
    assert run_p2(p2) == 0
    text = p2_context(p2)
    assert "Pilot: 2\n" in text
    assert "Definition of A: Invented definition of alpha, kept on two source lines.\n" in text
    assert "Definition of B: Invented definition of beta.\n" in text
    assert survey.context_pmids(text) == set(P2_GENERAL)
    entries = dict(re.findall(r"^## pmid:(\d+)\n(.*?)(?=^## pmid:|\Z)", text, re.MULTILINE | re.DOTALL))
    assert "- meta-analysis (PubMed publication type): yes\n" in entries["92100001"]
    assert "- meta-analysis (PubMed publication type): no\n" in entries["92100002"]  # a Systematic Review only
    assert "- abstract: structured\n" in entries["92100001"]
    assert "- abstract: unstructured\n" in entries["92100003"]
    one = entries["92100001"]
    assert "### BACKGROUND\n" in one
    assert "### RESULTS [FINDING SECTION]\n" in one
    assert "### CONCLUSIONS [FINDING SECTION]\n" in one
    assert "### METHODS\n" in one
    assert "Seven invented studies were pooled. Alpha activity was linked" in one  # whitespace collapsed
    assert "### AUTHORS' CONCLUSIONS [FINDING SECTION]" in entries["92100002"]
    four = entries["92100004"]
    assert "### OBJECTIVE\n" in four  # category OBJECTIVE is not a finding
    assert "### Main  Results [FINDING SECTION]" in four  # label matched without regard to case and spacing
    assert "### DISCUSSION\n" in four
    assert "### FINDINGS [FINDING SECTION]" in four  # NlmCategory RESULTS
    assert "###" not in entries["92100003"]
    assert "Invented narrative text. Epsilon was higher" in entries["92100003"]
    assert "Definition of A" in p2_context(p2, "Q2-general")


def test_screened_from_without_ends_writes_the_pilot_1_context(p2):
    assert run_p2(p2, extra=["--screened-from", str(p2["counts"])]) == 0
    text = p2_context(p2)
    assert "Pilot:" not in text
    assert "Definition of A" not in text
    assert "[FINDING SECTION]" not in text
    assert survey.context_pmids(text) == set(P2_GENERAL)


# --- pilot 2: validate ----------------------------------------------------------------------------------------------


def yes2(pmid: str, quote: str, **changes) -> dict:
    row = {
        "pmid": pmid,
        "statement": "yes",
        "relation": "present",
        "population": "invented adults",
        "direction": "association",
        "review_kind": "systematic",
        "quote_role": "finding",
        "quote": quote,
    }
    return {**row, **changes}


RESULTS_QUOTE = "Alpha activity was linked with beta outcomes."
CONCLUSION_QUOTE = "Invented evidence on gamma and delta is inconsistent across invented adults."
TITLE_QUOTE = "Fictional narrative review of epsilon and zeta in invented children."


def good2() -> dict:
    return {
        "question": "Q1",
        "arm": "general",
        "rows": [
            yes2("92100001", RESULTS_QUOTE),
            yes2("92100002", CONCLUSION_QUOTE, relation="inconsistent"),
            yes2("92100003", TITLE_QUOTE, review_kind="narrative"),
            {"pmid": "92100004", "statement": "no"},
        ],
    }


@pytest.fixture
def v2(p2):
    assert run_p2(p2) == 0
    return {"context": p2["out"] / "context" / "Q1-general.md", "cache": p2["cache"], "dir": p2["out"]}


def with_row2(data: dict, **changes) -> dict:
    data["rows"][0] = {**data["rows"][0], **changes}
    return data


def test_pilot_2_file_is_accepted(v2):
    assert problems(v2, good2()) == []


def test_pilot_2_file_is_accepted_through_the_command_line(v2, capsys):
    path = v2["dir"] / "survey.json"
    path.write_text(json.dumps(good2()), encoding="utf-8")
    argv = ["bridge", "validate", str(path), "--context", str(v2["context"]), "--cache-dir", str(v2["cache"])]
    assert survey.main(argv) == 0
    assert "OK (4 rows)" in capsys.readouterr().out


def test_quote_from_a_results_section_with_collapsed_whitespace_is_accepted(v2):
    quote = "Seven invented studies were pooled. Alpha activity"  # a line break and spaces in the record
    assert problems(v2, with_row2(good2(), quote=quote)) == []


def test_quote_from_a_conclusions_section_is_accepted(v2):
    assert problems(v2, with_row2(good2(), quote="Beta outcomes should be studied further")) == []


def test_quote_from_an_authors_conclusions_section_without_nlm_category_is_accepted(v2):
    assert problems(v2, good2()) == []  # row 1 quotes 92100002, whose section has a label but no NlmCategory


def test_quote_from_the_title_of_an_unstructured_abstract_is_accepted(v2):
    assert problems(v2, good2()) == []  # row 2


def test_quote_from_an_unstructured_abstract_body_is_accepted(v2):
    data = good2()
    data["rows"][2]["quote"] = "Epsilon was higher with zeta in invented children."
    assert problems(v2, data) == []


def test_pilot_1_schema_is_used_without_the_pilot_line(ran):
    # the pilot 1 context has no 'Pilot: 2' line: meta_analysis and studies_pooled are required, review_kind is unknown
    assert "Pilot:" not in ran["context"].read_text(encoding="utf-8")
    assert problems(ran, good_file()) == []
    errors = problems(ran, with_row(good_file(), review_kind="systematic", quote_role="finding"))
    assert "rows[0]: unknown key 'review_kind'" in errors


@pytest.mark.parametrize("key", ["meta_analysis", "studies_pooled"])
def test_pilot_2_rejects_meta_analysis_and_studies_pooled(v2, key):
    errors = problems(v2, with_row2(good2(), **{key: True if key == "meta_analysis" else 12}))
    assert f"rows[0]: unknown key '{key}'" in errors


@pytest.mark.parametrize("key", ["review_kind", "quote_role"])
def test_pilot_2_yes_row_missing_review_kind_or_quote_role_is_rejected(v2, key):
    data = good2()
    del data["rows"][0][key]
    assert f"rows[0]: missing key '{key}'" in problems(v2, data)


@pytest.mark.parametrize("value", ["meta_analysis", "Systematic", "", None, True])
def test_review_kind_outside_the_list_is_rejected(v2, value):
    errors = problems(v2, with_row2(good2(), review_kind=value))
    assert any("review_kind: must be one of systematic, narrative, not_a_review" in e for e in errors)


@pytest.mark.parametrize("value", ["conclusion", "", None, 1])
def test_quote_role_outside_the_list_is_rejected(v2, value):
    errors = problems(v2, with_row2(good2(), quote_role=value))
    assert any("quote_role: must be one of finding, background, aim" in e for e in errors)


@pytest.mark.parametrize("role", ["background", "aim"])
def test_yes_row_with_a_quote_role_other_than_finding_is_rejected(v2, role):
    errors = problems(v2, with_row2(good2(), quote_role=role))
    assert any("a yes row must quote a finding" in e for e in errors)


def test_quote_from_a_background_section_is_rejected(v2):
    quote = "Invented background says alpha activity might affect beta outcomes."
    errors = problems(v2, with_row2(good2(), quote=quote))
    assert any("not found verbatim inside one finding section" in e for e in errors)


def test_quote_from_a_methods_discussion_or_objective_section_is_rejected(v2):
    for pmid, quote in (
        ("92100001", "Invented databases were searched."),
        ("92100004", "Invented discussion on eta and theta."),
        ("92100004", "Invented aim to study eta and theta."),
    ):
        data = good2()
        data["rows"][0] = yes2(pmid, quote)
        data["rows"][3] = {"pmid": "92100004", "statement": "no"}
        if pmid == "92100004":
            data["rows"][3] = yes2("92100004", quote)
            data["rows"][0] = yes2("92100001", RESULTS_QUOTE)
        assert any("finding section" in e for e in problems(v2, data)), quote


def test_quote_from_the_title_of_a_structured_abstract_is_rejected(v2):
    quote = "Fictional meta-analysis of alpha activity and beta outcomes in invented adults."
    errors = problems(v2, with_row2(good2(), quote=quote))
    assert any("not found verbatim inside one finding section" in e for e in errors)


def test_quote_spanning_two_finding_sections_is_rejected(v2):
    quote = "linked with beta outcomes. Beta outcomes should be studied"  # end of RESULTS + start of CONCLUSIONS
    errors = problems(v2, with_row2(good2(), quote=quote))
    assert any("not found verbatim inside one finding section" in e for e in errors)


def test_quote_from_a_label_is_rejected(v2):
    errors = problems(v2, with_row2(good2(), quote="RESULTS: Seven invented studies were pooled."))
    assert any("finding section" in e for e in errors)


def test_quote_not_in_an_unstructured_record_is_rejected(v2):
    data = good2()
    data["rows"][2]["quote"] = "Epsilon was lower with zeta in invented children."
    errors = problems(v2, data)
    assert any("rows[2].quote: not found verbatim in the title or abstract" in e for e in errors)


def test_pilot_1_rejections_still_apply_in_pilot_2(v2):
    assert any("not in the context file" in e for e in problems(v2, with_row2(good2(), pmid="99999999")))
    data = good2()
    del data["rows"][3]
    assert "pmid 92100004 is in the context file but has no row" in problems(v2, data)
    assert any("banned word 'cure'" in e for e in problems(v2, with_row2(good2(), population="a cure")))
    data = good2()
    data["rows"][3]["relation"] = "present"
    assert "rows[3]: unknown key 'relation'" in problems(v2, data)


# --- pilot 2: the agent's example -----------------------------------------------------------------------------------


def test_agent_example_validates_under_the_pilot_2_schema(tmp_path):
    text = AGENT.read_text(encoding="utf-8")
    example = json.loads(re.search(r"```json\n(.*?)\n```", text, re.DOTALL).group(1))
    assert not any(k in text.split("## The file you write")[1] for k in ('meta_analysis": ', 'studies_pooled": '))
    rows = example["rows"]
    quote = rows[0]["quote"]
    cache = RawCache(tmp_path / "cache")
    cache.pubmed_dir.mkdir(parents=True)
    for row in rows:
        xml = (FIXTURES / "92100001.xml").read_text(encoding="utf-8")
        xml = xml.replace("92100001", row["pmid"]).replace("Alpha activity was linked with beta outcomes.", quote)
        (cache.pubmed_dir / f"{row['pmid']}.xml").write_text(xml, encoding="utf-8")
    context = "Question: Q1\nArm: general\nPilot: 2\n" + "".join(f"\n## pmid:{r['pmid']}\n" for r in rows)
    assert validate_agent_file(copy.deepcopy(example), context, cache) == []
    # the same example breaks if the quote is not in a finding section
    cache.path(rows[0]["pmid"]).write_text(xml.replace(quote, "Other text."), encoding="utf-8")
    assert validate_agent_file(example, context, cache) != []


def test_agent_prompt_describes_pilot_2():
    text = AGENT.read_text(encoding="utf-8")
    for needle in (
        "Definition of A",
        "Definition of B",
        "review_kind",
        "quote_role",
        "[FINDING SECTION]",
        "<run folder>",
        "never from memory",
        "promising, breakthrough, cure, hope, proven",
        "reply with the path you wrote and nothing else",
    ):
        assert needle in text, needle
    assert "data/pipeline/<date>-bridge-pilot" not in text
