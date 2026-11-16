"""Offline tests for the bridge search pilot (me_atlas.bridge, wired in as `survey bridge`)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest

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
