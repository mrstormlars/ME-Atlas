"""Tests for the weekly pipeline steps. Fictional papers and agent outputs in tests/fixtures/pipeline.

The PubMed fetch, the full-text loader and the subprocess runner are injected; nothing touches the network,
an AI, or git.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml

from me_atlas import cards, pipeline, translations
from me_atlas.pipeline import FullTextResult

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "pipeline"
SPEC = REPO / "docs" / "ME-Atlas-functional-spec.md"
SLUG = "fictional-pipeline-card"
DATE = dt.date(2026, 11, 1)
NEW_PMID = "90000101"
REVIEW_PMID = "90000102"


class Env:
    """A fictional repository layout in tmp_path with one draft card and one cached (old) paper."""

    def __init__(self, tmp: Path):
        self.root = tmp
        self.cache = tmp / "cache"
        self.drafts = tmp / "drafts"
        self.cards = tmp / "cards"
        self.pipeline = tmp / "pipeline"
        self.translations = tmp / "translations"
        self.cards.mkdir()
        self.drafts.mkdir()
        shutil.copy(FIXTURES / "drafts" / f"{SLUG}.yaml", self.drafts / f"{SLUG}.yaml")
        (self.cache / "pubmed").mkdir(parents=True)
        shutil.copy(FIXTURES / "pubmed" / "90000100.xml", self.cache / "pubmed" / "90000100.xml")
        self.fetch_calls: list[list[str]] = []
        self.window = ["90000101", "90000102", "90000103"]
        self.out: list[str] = []

    @property
    def run(self) -> Path:
        return self.pipeline / DATE.isoformat()

    def fetch(self, argv):
        """Stands in for pubmed.main: caches three new records and writes a run manifest."""
        self.fetch_calls.append(list(argv))
        for pmid in ("90000101", "90000102", "90000103"):
            shutil.copy(FIXTURES / "pubmed" / f"{pmid}.xml", self.cache / "pubmed" / f"{pmid}.xml")
        runs = self.cache / "runs"
        runs.mkdir(exist_ok=True)
        manifest = {
            "counts": {"new": 3},
            "new_pmids": ["90000101", "90000102", "90000103"],
            "window_pmids": self.window,
            "retracted_pmids": ["90000100", "90000103"],
            "newly_flagged_retracted_pmids": ["90000100"],
        }
        name = f"2026110{len(self.fetch_calls)}T000000Z.json"
        (runs / name).write_text(json.dumps(manifest), encoding="utf-8")
        return 0

    def cli(self, *argv: str, fulltext=None, runner=None, fetch=None) -> int:
        command = argv[0]
        extra = ["--date", DATE.isoformat()] if command == "prepare" else ["--run-dir", str(self.run)]
        return pipeline.main(
            [
                *argv,
                *extra,
                "--pipeline-dir",
                str(self.pipeline),
                "--cards-dir",
                str(self.cards),
                "--drafts-dir",
                str(self.drafts),
                "--cache-dir",
                str(self.cache),
                "--spec",
                str(SPEC),
                "--translations-dir",
                str(self.translations),
            ],
            fetch=fetch or self.fetch,
            fulltext=fulltext,
            runner=runner,
            out=self.out.append,
        )

    def prepare(self) -> None:
        assert self.cli("prepare") == 0

    def classify(self, name: str = "classify_good.json") -> int:
        shutil.copy(FIXTURES / "agent" / name, self.run / "classify.json")
        return self.cli("record-classification")

    def put(self, folder: str, fixture: str, pmid: str = NEW_PMID, n: int = 1) -> Path:
        target = self.run / folder / f"{SLUG}-{pmid}-r{n}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "agent" / fixture, target)
        return target

    def apply(self, fixture: str, n: int = 1) -> int:
        ops = self.put("ops", fixture, n=n)
        return self.cli("apply", SLUG, str(ops), "--round", str(n))

    def checks(self, n: int = 1) -> dict:
        return json.loads((self.run / "checks" / f"{SLUG}-{NEW_PMID}-r{n}.json").read_text(encoding="utf-8"))

    def draft_text(self) -> str:
        return (self.drafts / f"{SLUG}.yaml").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def ready(env: Env) -> Env:
    """Prepared and classified (90000101 original, 90000102 review with a possible new hypothesis)."""
    env.prepare()
    assert env.classify() == 0
    return env


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- prepare ----------------------------------------------------------------


def test_prepare_selects_the_papers_of_the_fetch_window(env: Env):
    env.prepare()
    papers = load(env.run / "papers.json")
    assert [p["pmid"] for p in papers] == ["90000101", "90000102"]  # 90000100 is old and cached; 90000103 is retracted
    assert set(papers[0]) >= {"pmid", "title", "abstract", "publication_types", "year", "doi", "entry_date"}
    assert papers[0]["title"] == "Fictional replication of widget signalling in a larger cohort."
    cards = load(env.run / "cards.json")
    assert cards[0]["slug"] == SLUG and cards[0]["core_claim"].startswith("The fictional hypothesis")


def test_prepare_flags_a_newly_retracted_paper_cited_on_a_card(env: Env):
    env.prepare()
    summary = load(env.run / "prepare.json")
    assert summary["retractions_on_cards"] == [
        {"pmid": "90000100", "title": "Fictional controlled study of widget signalling.", "cards": [SLUG]}
    ]
    assert summary["excluded_retracted"] == ["90000103"]  # new but retracted and cited nowhere: not classified
    assert any("RETRACTED" in line and SLUG in line for line in env.out)


def test_prepare_passes_weekly_or_since_to_the_fetch(env: Env):
    env.prepare()
    assert env.fetch_calls[0][:1] == ["fetch"] and "--weekly" in env.fetch_calls[0]
    assert ["--cache-dir", str(env.cache)] == env.fetch_calls[0][-2:]
    assert env.cli("prepare", "--since", "2026-10-01", "--force") == 0
    assert env.fetch_calls[1][:3] == ["fetch", "--since", "2026-10-01"]


def test_prepare_refuses_to_overwrite_a_run_and_reports_a_failed_fetch(env: Env, capsys):
    env.prepare()
    assert env.cli("prepare") == 1
    assert "already holds a run" in capsys.readouterr().err
    assert env.cli("prepare", "--force", fetch=lambda argv: 2) == 1
    assert "fetch failed" in capsys.readouterr().err


# --- record-classification ----------------------------------------------------


def test_record_classification_accepts_a_valid_file_and_writes_the_matches(ready: Env):
    matches = load(ready.run / "matches.json")
    assert matches["matches"] == [{"slug": SLUG, "pmid": NEW_PMID}]
    assert matches["stopped"] == [{"pmid": REVIEW_PMID, "why": "article type: review"}]
    assert matches["new_hypotheses"][0]["hypothesis"] == "A fictional gizmo pathway hypothesis"


def test_record_classification_rejects_wrong_types(env: Env, capsys):
    env.prepare()
    assert env.classify("classify_wrong_type.json") == 1
    err = capsys.readouterr().err
    assert "malformed" in err and "article_type" in err and "cards" in err
    assert not (env.run / "matches.json").exists()


def test_record_classification_rejects_an_unknown_slug(env: Env, capsys):
    env.prepare()
    assert env.classify("classify_unknown_slug.json") == 1
    assert "unknown card slug 'no-such-card'" in capsys.readouterr().err
    assert not (env.run / "matches.json").exists()


def test_record_classification_rejects_missing_unknown_and_repeated_papers(env: Env, capsys):
    env.prepare()
    good = load(FIXTURES / "agent" / "classify_good.json")
    item = good["papers"][0]
    cases = {
        "not classified": {"papers": [item]},
        "not one of this run's papers": {"papers": [*good["papers"], {**item, "pmid": "12345678"}]},
        "classified more than once": {"papers": [*good["papers"], item]},
    }
    for message, body in cases.items():
        (env.run / "classify.json").write_text(json.dumps(body), encoding="utf-8")
        assert env.cli("record-classification") == 1
        assert message in capsys.readouterr().err
    (env.run / "classify.json").write_text("{not json", encoding="utf-8")
    assert env.cli("record-classification") == 1
    assert "not readable JSON" in capsys.readouterr().err


# --- context ----------------------------------------------------------------


def fulltext_loader(budget_text: str | None = None):
    xml = (FIXTURES / "agent" / "fulltext-90000101.xml").read_bytes()

    def load_it(pmid: str) -> FullTextResult:
        return FullTextResult(xml, "Europe PMC open access, PMC9000101")

    return load_it


def test_context_holds_card_rubric_record_and_fulltext_without_references(ready: Env):
    assert ready.cli("context", SLUG, NEW_PMID, fulltext=fulltext_loader()) == 0
    text = (ready.run / "context" / f"{SLUG}-{NEW_PMID}.md").read_text(encoding="utf-8")
    assert "slug: fictional-pipeline-card" in text  # the card YAML, verbatim
    assert "# a comment inside a badge" in text
    assert (
        "Evidence ladder" in text and "Repeated by others" in text and "## 4. Pages" not in text
    )  # spec section 3 only
    assert "Fictional replication of widget signalling in a larger cohort." in text  # the record
    assert "A total of 60 patients and 55 controls were compared." in text  # the abstract
    assert "FULLTEXT-TAIL-MARKER" in text and "REFERENCE-LIST-MARKER" not in text
    assert "Not truncated" in text and "TRUNCATED:" not in text
    assert "All fictional participants met the Fukuda criteria." in text  # candidate case-definition sentence


def test_context_states_truncation_with_the_numbers(ready: Env):
    cfg = pipeline.Config(ready.run, ready.cards, ready.drafts, ready.cache, SPEC)
    text = pipeline.build_context(cfg, SLUG, NEW_PMID, fulltext_loader(), budget=50)
    assert "TRUNCATED: the first 50 of " in text and "characters follow" in text
    assert "FULLTEXT-TAIL-MARKER" not in text
    assert pipeline.FULLTEXT_CHAR_BUDGET == 60_000


def test_context_says_so_when_there_is_no_full_text(ready: Env):
    loader = lambda pmid: FullTextResult(None, "no open full text (Europe PMC: no open full text)")  # noqa: E731
    assert ready.cli("context", SLUG, NEW_PMID, fulltext=loader) == 0
    text = (ready.run / "context" / f"{SLUG}-{NEW_PMID}.md").read_text(encoding="utf-8")
    assert "No full text is available" in text and "unverified" in text


def test_context_contains_no_drafter_output(ready: Env):
    ops = ready.put("ops", "ops_add_study.json")
    marker = "DRAFTER-REASONING-MARKER"
    body = load(ops)
    body["operations"][1]["text"] = marker
    ops.write_text(json.dumps(body), encoding="utf-8")
    review = ready.put("review", "review_reject.json")
    review.write_text(review.read_text(encoding="utf-8").replace("Say that", "REVIEWER-MARKER"), encoding="utf-8")
    assert ready.cli("context", SLUG, NEW_PMID, fulltext=fulltext_loader()) == 0
    text = (ready.run / "context" / f"{SLUG}-{NEW_PMID}.md").read_text(encoding="utf-8")
    assert marker not in text and "REVIEWER-MARKER" not in text


def test_context_for_an_unknown_card_or_uncached_paper_is_an_error(ready: Env, capsys):
    assert ready.cli("context", "no-such-card", NEW_PMID, fulltext=fulltext_loader()) == 1
    assert "no card or draft 'no-such-card'" in capsys.readouterr().err
    assert ready.cli("context", SLUG, "99999999", fulltext=fulltext_loader()) == 1
    assert "no cached PubMed record" in capsys.readouterr().err


# --- apply ------------------------------------------------------------------


def test_apply_applies_to_a_copy_runs_the_checks_and_leaves_the_draft_alone(ready: Env):
    before = ready.draft_text()
    assert ready.apply("ops_add_study.json") == 0
    checks = ready.checks()
    assert checks["passed"] is True and checks["validator"] == [] and checks["citation_errors"] == 0
    assert checks["tiers"] == {"1": 2, "2": 0}
    applied = Path(checks["applied"])
    assert applied.name == f"{SLUG}.yaml"
    data = yaml.safe_load(applied.read_text(encoding="utf-8"))
    assert data["studies"][-1]["id"] == "pmid:90000101" and len(data["level_reason"]) == 2
    assert "+  - id: pmid:90000101" in Path(checks["diff"]).read_text(encoding="utf-8")
    assert ready.draft_text() == before  # the draft in drafts/ is untouched


def test_apply_reports_a_validator_failure(ready: Env):
    before = ready.draft_text()
    assert ready.apply("ops_bad_validator.json") == 1
    checks = ready.checks()
    assert checks["passed"] is False
    assert any("V6" in line for line in checks["validator"])
    assert any("V6" in line for line in ready.out) and ready.out[-1] == "FAILED"
    assert ready.draft_text() == before


def test_apply_reports_a_citations_error(ready: Env):
    assert ready.apply("ops_bad_quote.json") == 1
    checks = ready.checks()
    assert checks["passed"] is False and checks["validator"] == []
    new_errors = [r for r in checks["citations"] if r["level"] == "ERROR" and not r["preexisting"]]
    assert [(r["study"], r["code"]) for r in new_errors] == [("pmid:90000101", "C5")]
    assert any("C5 ERROR" in line for line in ready.out)


def test_apply_does_not_blame_the_new_paper_for_citation_errors_already_on_the_card(ready: Env):
    assert ready.apply("ops_add_study.json") == 0
    old = [r for r in ready.checks()["citations"] if r["preexisting"]]
    assert [(r["study"], r["code"]) for r in old] == [("pmid:90000104", "C1")]  # its record is not in the cache


def test_apply_rejects_invalid_operations_without_writing_a_card(ready: Env):
    before = ready.draft_text()
    assert ready.apply("ops_unknown_field.json") == 1
    checks = ready.checks()
    assert checks["applied"] is None and "field" in checks["ops_errors"][0]
    assert ready.draft_text() == before


def test_apply_rejects_an_ops_file_for_another_card(ready: Env):
    other = ready.draft_text().replace(f"slug: {SLUG}", "slug: other-card")
    (ready.drafts / "other-card.yaml").write_text(other, encoding="utf-8")
    ops = ready.put("ops", "ops_add_study.json")
    assert ready.cli("apply", "other-card", str(ops)) == 1
    checks = load(ready.run / "checks" / f"other-card-{NEW_PMID}-r1.json")
    assert "is for card 'fictional-pipeline-card', not 'other-card'" in checks["ops_errors"][0]
    assert checks["applied"] is None


def test_apply_with_no_operations_passes_as_no_change(ready: Env):
    assert ready.apply("ops_empty.json") == 0
    checks = ready.checks()
    assert checks["no_change"] is True and checks["applied"] is None


# --- record-review ----------------------------------------------------------


def test_record_review_accepts_valid_files(ready: Env):
    ready.put("ops", "ops_add_study.json")
    ready.put("review", "review_accept.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 0
    ready.put("review", "review_reject.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 0
    assert "reject, 1 finding" in ready.out[-1]


def test_record_review_rejects_a_reject_without_findings(ready: Env, capsys):
    ready.put("ops", "ops_add_study.json")
    ready.put("review", "review_reject_no_findings.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 1
    assert "at least one finding" in capsys.readouterr().err


def test_record_review_rejects_a_finding_about_an_operation_that_does_not_exist(ready: Env, capsys):
    ready.put("ops", "ops_add_study.json")
    ready.put("review", "review_bad_operation.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 1
    assert "out of range (2 operation(s)" in capsys.readouterr().err


def test_record_review_rejects_a_review_of_another_paper_or_malformed_file(ready: Env, capsys):
    ready.put("ops", "ops_add_study.json")
    target = ready.put("review", "review_accept.json")
    target.write_text(target.read_text(encoding="utf-8").replace("90000101", "90000102"), encoding="utf-8")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 1
    assert "expected 'pmid:90000101'" in capsys.readouterr().err
    target.write_text('{"verdict": "maybe"}', encoding="utf-8")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 1
    assert "malformed" in capsys.readouterr().err


# --- outcomes and report ----------------------------------------------------


def outcome(env: Env):
    [o] = pipeline.collect_outcomes(pipeline.Config(env.run, env.cards, env.drafts, env.cache, SPEC))
    return o


def test_outcomes_for_each_state_of_a_pair(ready: Env):
    assert (outcome(ready).status, "no operations file" in outcome(ready).note) == ("skipped", True)
    ready.apply("ops_bad_validator.json")
    assert outcome(ready).status == "skipped" and "mechanical checks failed" in outcome(ready).note
    ready.apply("ops_empty.json")
    assert outcome(ready).status == "no_change"
    ready.apply("ops_add_study.json")
    assert outcome(ready).status == "skipped" and outcome(ready).note == "no review was recorded"
    ready.put("review", "review_accept.json")
    assert outcome(ready).status == "accepted"
    ready.put("review", "review_reject.json")
    assert outcome(ready).status == "parked" and "no second attempt" in outcome(ready).note
    ready.apply("ops_bad_validator.json", n=2)
    assert outcome(ready).status == "parked"  # a rejected first round is never forgotten
    ready.apply("ops_add_study.json", n=2)
    ready.put("review", "review_accept.json", n=2)
    assert outcome(ready).status == "accepted" and outcome(ready).last.n == 2
    ready.put("review", "review_reject.json", n=2)
    assert outcome(ready).status == "parked" and outcome(ready).note == "rejected in round 2"


def test_report_puts_tier_2_first_then_parking_lot_new_hypotheses_and_retractions(ready: Env):
    ready.apply("ops_propose_level.json")
    ready.put("review", "review_accept.json")
    # a second card/paper pair that ends in the parking lot
    parked = pipeline.Config(ready.run, ready.cards, ready.drafts, ready.cache, SPEC)
    matches = load(ready.run / "matches.json")
    matches["matches"].append({"slug": SLUG, "pmid": REVIEW_PMID})
    (ready.run / "matches.json").write_text(json.dumps(matches), encoding="utf-8")
    for n in (1, 2):
        ops = parked.ops_path(SLUG, REVIEW_PMID, n)
        ops.parent.mkdir(exist_ok=True)
        body = load(FIXTURES / "agent" / "ops_add_study.json")
        body["paper"] = "pmid:90000102"
        body["operations"] = [body["operations"][1]]
        body["operations"][0]["sources"] = ["pmid:90000100"]
        ops.write_text(json.dumps(body), encoding="utf-8")
        parked.checks_path(SLUG, REVIEW_PMID, n).parent.mkdir(exist_ok=True)
        parked.checks_path(SLUG, REVIEW_PMID, n).write_text(json.dumps({"passed": True}), encoding="utf-8")
        review = load(FIXTURES / "agent" / "review_reject.json")
        review["paper"] = "pmid:90000102"
        review["findings"][0]["operation"] = 0
        parked.review_path(SLUG, REVIEW_PMID, n).parent.mkdir(exist_ok=True)
        parked.review_path(SLUG, REVIEW_PMID, n).write_text(json.dumps(review), encoding="utf-8")

    assert ready.cli("report") == 0
    report = (ready.run / "report.md").read_text(encoding="utf-8")
    heads = [
        report.index("### Tier 2"),
        report.index("### Tier 1"),
        report.index("## Parking lot"),
        report.index("## Possible new hypotheses"),
        report.index("## Retracted papers cited on cards"),
        report.index("## Skipped"),
    ]
    assert heads == sorted(heads)
    tier2 = report[heads[0] : heads[1]]
    assert "Propose level 2 -> 3" in tier2 and "review: accept (round 1)" in tier2
    tier1 = report[heads[1] : heads[2]]
    assert "Add study `pmid:90000101`" in tier1
    parking = report[heads[2] : heads[3]]
    assert "pmid:90000102" in parking and "rejected in round 2" in parking
    assert "round 1, operation 0 (must_fix): The paragraph says the finding was repeated" in parking
    assert "A fictional gizmo pathway hypothesis" in report[heads[3] : heads[4]]
    assert "pmid:90000100" in report[heads[4] : heads[5]] and SLUG in report[heads[4] : heads[5]]
    assert "pmid:90000103" in report[heads[5] :]  # new but retracted
    assert "| pmid:90000101" in report  # classification table


def test_report_with_nothing_proposed_says_none(ready: Env):
    assert ready.cli("report") == 0
    report = (ready.run / "report.md").read_text(encoding="utf-8")
    assert report.count("None.") >= 3


# --- pr ---------------------------------------------------------------------


class FakeRunner:
    def __init__(self, branch: str = "main", fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.branch = branch
        self.fail_on = fail_on

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, self.branch
        if self.fail_on and cmd[0] == self.fail_on:
            return 1, "boom"
        return 0, ""


@pytest.fixture
def accepted(ready: Env) -> Env:
    ready.apply("ops_add_study.json")
    ready.put("review", "review_accept.json")
    return ready


def test_pr_dry_run_prints_the_git_and_gh_commands_and_runs_nothing(accepted: Env):
    runner = FakeRunner()
    before = accepted.draft_text()
    assert accepted.cli("pr", "--dry-run", runner=runner) == 0
    assert runner.calls == []
    commands = [line for line in accepted.out if line.startswith("$ ")]
    assert "$ git switch -c pipeline/2026-11-01" in commands
    assert any(c.startswith("$ git add -- ") and f"{SLUG}.yaml" in c for c in commands)
    assert any(c.startswith("$ git commit -m ") for c in commands)
    assert "$ git push -u origin pipeline/2026-11-01" in commands
    gh = [c for c in commands if c.startswith("$ gh pr create")]
    assert len(gh) == 1 and "--base main" in gh[0] and "--head pipeline/2026-11-01" in gh[0] and "report.md" in gh[0]
    assert accepted.draft_text() == before  # dry run writes nothing
    assert (accepted.run / "report.md").exists()


def test_pr_copies_accepted_results_into_drafts_and_runs_the_commands_in_order(accepted: Env):
    runner = FakeRunner()
    assert accepted.cli("pr", runner=runner) == 0
    assert [c[:2] for c in runner.calls] == [
        ["git", "rev-parse"],
        ["git", "switch"],
        ["git", "add"],
        ["git", "commit"],
        ["git", "push"],
        ["gh", "pr"],
    ]
    data = yaml.safe_load(accepted.draft_text())
    assert data["studies"][-1]["id"] == "pmid:90000101"


def test_pr_no_pr_commits_locally_without_pushing(accepted: Env):
    runner = FakeRunner(branch="feat/anything")
    assert accepted.cli("pr", "--no-pr", runner=runner) == 0
    assert [c[:2] for c in runner.calls] == [["git", "switch"], ["git", "add"], ["git", "commit"]]
    assert "yaml" in " ".join(runner.calls[1])


def test_pr_refuses_to_cut_a_pull_request_from_another_branch(accepted: Env):
    runner = FakeRunner(branch="feat/other")
    before = accepted.draft_text()
    assert accepted.cli("pr", runner=runner) == 1
    assert runner.calls == [["git", "rev-parse", "--abbrev-ref", "HEAD"]]
    assert accepted.draft_text() == before


def test_pr_stops_when_a_command_fails(accepted: Env):
    def failing(cmd):
        return (0, "main") if cmd[1] == "rev-parse" else (1, "boom")

    assert accepted.cli("pr", runner=failing) == 1
    assert any("exit code 1" in line for line in accepted.out)


def test_pr_with_nothing_accepted_does_nothing(ready: Env):
    runner = FakeRunner()
    assert ready.cli("pr", runner=runner) == 0
    assert runner.calls == [] and "nothing to commit" in ready.out[-1]


def test_pr_leaves_out_a_pair_the_reviewer_rejected(ready: Env):
    ready.apply("ops_add_study.json")
    ready.put("review", "review_reject.json")
    runner = FakeRunner()
    assert ready.cli("pr", runner=runner) == 0
    assert runner.calls == []
    assert "Parking lot" in (ready.run / "report.md").read_text(encoding="utf-8")


def test_files_written_by_the_pipeline_use_lf_line_endings(accepted: Env):
    accepted.cli("report")
    for path in [accepted.run / "report.md", accepted.run / "matches.json", Path(accepted.checks()["applied"])]:
        assert b"\r" not in path.read_bytes(), path


def test_apply_output_and_report_show_pre_existing_citation_errors(ready: Env):
    assert ready.apply("ops_add_study.json") == 0
    assert any("already on the card, not blocking" in line and "pmid:90000104" in line for line in ready.out)
    assert ready.cli("report") == 0
    report = (ready.run / "report.md").read_text(encoding="utf-8")
    section = report.split("## Pre-existing problems on cards")[1].split("## New papers")[0]
    assert "**fictional-pipeline-card**, pmid:90000104: C1:" in section


def test_report_says_none_when_cards_have_no_pre_existing_problems(ready: Env):
    assert ready.cli("report") == 0
    report = (ready.run / "report.md").read_text(encoding="utf-8")
    assert report.split("## Pre-existing problems on cards")[1].split("## New papers")[0].strip() == "None."


def accept_replacing(env: Env, pmid: str, index: int = 0, field: str = "contested.reason", sources=None) -> None:
    """Make (card, pmid) an accepted pair whose only operation replaces one paragraph."""
    cfg = pipeline.Config(env.run, env.cards, env.drafts, env.cache, SPEC)
    ops = {
        "card": SLUG,
        "paper": f"pmid:{pmid}",
        "operations": [
            {
                "op": "replace_paragraph",
                "field": field,
                "index": index,
                "text": f"Replaced by {pmid}.",
                "sources": sources or ["pmid:90000104"],
            }
        ],
    }
    for path, body in (
        (cfg.ops_path(SLUG, pmid, 1), ops),
        (cfg.checks_path(SLUG, pmid, 1), {"passed": True, "card": SLUG, "citations": []}),
        (cfg.review_path(SLUG, pmid, 1), {"card": SLUG, "paper": f"pmid:{pmid}", "verdict": "accept", "findings": []}),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
    matches = load(env.run / "matches.json")
    matches["matches"].append({"slug": SLUG, "pmid": pmid})
    (env.run / "matches.json").write_text(json.dumps(matches), encoding="utf-8")


def test_two_accepted_papers_replacing_the_same_paragraph_are_both_parked_and_not_applied(ready: Env):
    ready.apply("ops_add_study.json")  # pmid 90000101: add_study + add_paragraph, no conflict
    ready.put("review", "review_accept.json")
    accept_replacing(ready, "90000201")
    accept_replacing(ready, "90000202")  # same field and index as 90000201
    accept_replacing(ready, "90000203", index=1)  # a different paragraph: fine
    cfg = pipeline.Config(ready.run, ready.cards, ready.drafts, ready.cache, SPEC)
    status = {o.pmid: o for o in pipeline.collect_outcomes(cfg)}
    assert status[NEW_PMID].status == "accepted" and status["90000203"].status == "accepted"
    for pmid, other in (("90000201", "90000202"), ("90000202", "90000201")):
        assert status[pmid].status == "parked"
        assert f"conflicts with pmid:{other} on replace_paragraph contested.reason 0" in status[pmid].note
    texts = pipeline.final_card_texts(cfg, list(status.values()))
    reasons = [p["text"] for p in yaml.safe_load(texts[SLUG])["contested"]["reason"]]
    assert reasons == [
        "A fictional study of 100 patients found no difference in widget signalling.",
        "Replaced by 90000203.",
    ]
    assert yaml.safe_load(texts[SLUG])["studies"][-1]["id"] == "pmid:90000101"  # the other paper still applied
    assert ready.cli("report") == 0
    parking = (ready.run / "report.md").read_text(encoding="utf-8").split("## Parking lot")[1].split("## Possible")[0]
    assert "pmid:90000201" in parking and "pmid:90000202" in parking and "not applied, conflicts with" in parking


def test_two_accepted_papers_proposing_the_same_kind_conflict(ready: Env):
    cfg = pipeline.Config(ready.run, ready.cards, ready.drafts, ready.cache, SPEC)
    accept_replacing(ready, "90000201")
    accept_replacing(ready, "90000202")
    for pmid in ("90000201", "90000202"):
        path = cfg.ops_path(SLUG, pmid, 1)
        body = load(path)
        body["operations"] = [
            {"op": "propose", "target": "level", "value": 3, "reason": [{"text": "x.", "sources": ["pmid:90000100"]}]}
        ]
        path.write_text(json.dumps(body), encoding="utf-8")
    outcomes = pipeline.collect_outcomes(cfg)
    assert [o.status for o in outcomes if o.pmid.startswith("900002")] == ["parked", "parked"]
    assert "propose level" in outcomes[-1].note


# --- the ledger of processed papers -------------------------------------------


def ledger(env: Env) -> dict:
    return load(env.pipeline / "processed.json")["processed"]


def test_prepare_selects_cached_papers_in_the_window_that_no_run_has_processed(env: Env):
    env.window = ["90000100", "90000101"]  # 90000100 was cached before this fetch
    env.prepare()
    assert [p["pmid"] for p in load(env.run / "papers.json")] == ["90000100", "90000101"]
    summary = load(env.run / "prepare.json")
    assert (summary["in_window"], summary["selected"], summary["skipped_processed"]) == (2, 2, 0)
    assert any("2 paper(s) selected, 0 skipped as already processed" in line for line in env.out)


def test_ledger_is_written_by_report_only(ready: Env):
    assert not (ready.pipeline / "processed.json").exists()  # prepare and record-classification do not write it
    ready.apply("ops_add_study.json")
    assert not (ready.pipeline / "processed.json").exists()  # nor does apply
    assert ready.cli("report") == 0
    assert ledger(ready) == {"90000101": "2026-11-01", "90000102": "2026-11-01"}
    assert any("ledger updated: 2 paper(s)" in line for line in ready.out)


def test_an_aborted_run_can_be_repeated(env: Env):
    env.prepare()
    assert env.cli("prepare", "--force") == 0  # no report in between, so nothing is marked processed
    assert load(env.run / "prepare.json")["selected"] == 2


def test_prepare_skips_papers_an_earlier_run_processed(ready: Env):
    assert ready.cli("report") == 0
    assert ready.cli("prepare", "--force") == 0
    assert load(ready.run / "papers.json") == []
    summary = load(ready.run / "prepare.json")
    assert (summary["selected"], summary["skipped_processed"]) == (0, 2)
    assert any("0 paper(s) selected, 2 skipped as already processed" in line for line in ready.out)
    assert summary["excluded_retracted"] == ["90000103"]  # retracted papers are still excluded and reported


def test_reprocess_ignores_the_ledger(ready: Env):
    assert ready.cli("report") == 0
    assert ready.cli("prepare", "--force", "--reprocess") == 0
    summary = load(ready.run / "prepare.json")
    assert (summary["selected"], summary["skipped_processed"], summary["reprocess"]) == (2, 0, True)


def test_a_retracted_card_citation_is_still_flagged_when_the_ledger_skips_everything(ready: Env):
    assert ready.cli("report") == 0
    assert ready.cli("prepare", "--force") == 0
    assert load(ready.run / "prepare.json")["retractions_on_cards"][0]["pmid"] == "90000100"


def test_a_malformed_ledger_is_an_error(env: Env, capsys):
    env.pipeline.mkdir()
    (env.pipeline / "processed.json").write_text("[]", encoding="utf-8")
    assert env.cli("prepare") == 1
    assert "not a ledger" in capsys.readouterr().err


# --- severity of review findings ------------------------------------------------


def test_accept_with_a_must_fix_finding_is_not_allowed(ready: Env, capsys):
    ready.put("ops", "ops_add_study.json")
    ready.put("review", "review_accept_must_fix.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 1
    assert "accept with must_fix findings is not allowed; verdict must be reject" in capsys.readouterr().err


def test_accept_with_only_advisory_findings_and_reject_with_only_advisory_findings_are_allowed(ready: Env):
    ready.put("ops", "ops_add_study.json")
    ready.put("review", "review_accept_advisory.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 0
    ready.put("review", "review_reject_advisory_only.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 0


def test_a_finding_without_severity_is_rejected(ready: Env, capsys):
    ready.put("ops", "ops_add_study.json")
    ready.put("review", "review_no_severity.json")
    assert ready.cli("record-review", SLUG, NEW_PMID) == 1
    assert "severity" in capsys.readouterr().err


def test_report_shows_severity_with_must_fix_first_and_a_natural_window_sentence(ready: Env):
    ready.apply("ops_add_study.json")
    review = ready.put("review", "review_accept_advisory.json")
    body = load(review)
    body["findings"] = [
        {"operation": 0, "severity": "advisory", "problem": "ADVISORY-NOTE"},
        {"operation": 1, "severity": "advisory", "problem": "SECOND-NOTE"},
    ]
    review.write_text(json.dumps(body), encoding="utf-8")
    assert ready.cli("report") == 0
    report = (ready.run / "report.md").read_text(encoding="utf-8")
    assert "reviewer note (advisory) on operation 0: ADVISORY-NOTE" in report
    assert "selected from the weekly fetch window (the last 14 days)" in report
    # parking lot: must_fix before advisory
    review.write_text(
        json.dumps(
            {
                **body,
                "verdict": "reject",
                "findings": [
                    {"operation": 0, "severity": "advisory", "problem": "ADVISORY-NOTE"},
                    {"operation": 1, "severity": "must_fix", "problem": "MUST-NOTE"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert ready.cli("report") == 0
    report = (ready.run / "report.md").read_text(encoding="utf-8")
    assert report.index("(must_fix): MUST-NOTE") < report.index("(advisory): ADVISORY-NOTE")
    assert ready.cli("prepare", "--force", "--since", "2026-10-02") == 0
    assert ready.cli("report") == 0
    assert "from the fetch window since 2026-10-02" in (ready.run / "report.md").read_text(encoding="utf-8")


# --- translation-plan ---------------------------------------------------------


def write_norwegian(env: Env, *, skip: tuple[str, ...] = ()) -> dict[str, translations.TItem]:
    """A fictional, complete Norwegian file for the draft: every item is 'NB ' plus the English text, so the numbers
    and sources match. Items named in ``skip`` are left out."""
    card = cards.load_card(env.drafts / f"{SLUG}.yaml")
    items = {
        loc: translations.TItem(
            text="NB " + en.text,
            source_hash=translations.text_hash(en.text),
            sources=list(en.sources) if en.sources is not None else None,
        )
        for loc, en in translations.english_items(card).items()
        if loc not in skip
    }
    target = env.translations / "nb" / f"{SLUG}.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(
        translations.dump_sidecar(translations.TFile(slug=SLUG, items=items), list(items)), encoding="utf-8"
    )
    return items


def plan_items(env: Env) -> dict[str, str]:
    plan = load(env.run / "translation-plan.json")
    assert [c["slug"] for c in plan["cards"]] == [SLUG]
    return {i["item"]: i["reason"] for i in plan["cards"][0]["items"]}


def test_translation_plan_lists_the_items_an_accepted_change_made_stale(ready: Env):
    write_norwegian(ready)
    accept_replacing(ready, "90000201")  # replaces contested.reason[0]
    assert ready.cli("translation-plan") == 0
    assert plan_items(ready) == {"contested_reason[0]": "made_stale"}
    entry = load(ready.run / "translate" / f"{SLUG}.json")
    assert set(entry) == {"slug", "lang", "card", "items"}  # the shape card-translator.md describes
    assert set(entry["items"][0]) == {"item", "reason", "english", "sources", "previous_translation"}
    assert entry["lang"] == "nb" and entry["items"][0]["english"] == "Replaced by 90000201."
    assert entry["items"][0]["previous_translation"].startswith("NB A fictional study of 100 patients")
    # the English text the translator and `translations apply` work from is the card as it will be after the change
    final = cards.load_card(Path(entry["card"]))
    assert final.contested.reason[0].text == "Replaced by 90000201."
    assert "stale" in "\n".join(ready.out) or "made stale" in "\n".join(ready.out)
    assert ready.draft_text() == (FIXTURES / "drafts" / f"{SLUG}.yaml").read_text(encoding="utf-8")  # drafts untouched


def test_translation_plan_lists_items_the_change_added_as_new(accepted: Env):
    write_norwegian(accepted)
    assert accepted.cli("translation-plan") == 0
    assert plan_items(accepted) == {"level_reason[1]": "new", "studies[pmid:90000101].finding": "new"}


def test_translation_plan_lists_a_link_the_change_added_as_new(ready: Env, monkeypatch):
    write_norwegian(ready)
    accept_replacing(ready, "90000201")
    original = pipeline.final_card_texts
    link = (
        "links:\n"
        "  - to: symptom:fictional-fatigue\n"
        "    support: proposed\n"
        "    text: A fictional review proposes a link to fatigue.\n"
        "    sources: [pmid:90000100]\n"
    )

    def with_link(cfg, outcomes):  # operations cannot add a link yet; the final text gets one
        return {slug: text.rstrip("\n") + "\n" + link for slug, text in original(cfg, outcomes).items()}

    monkeypatch.setattr(pipeline, "final_card_texts", with_link)
    assert ready.cli("translation-plan") == 0
    assert plan_items(ready) == {"contested_reason[0]": "made_stale", "links[0]": "new"}
    entry = load(ready.run / "translate" / f"{SLUG}.json")
    added = next(i for i in entry["items"] if i["item"] == "links[0]")
    assert added["english"] == "A fictional review proposes a link to fatigue."
    assert added["sources"] == ["pmid:90000100"] and added["previous_translation"] is None


def test_translation_plan_keeps_an_earlier_stale_item_apart_from_the_new_ones(ready: Env):
    write_norwegian(ready, skip=("subgroups[0]", "early_signals[0]"))
    accept_replacing(ready, "90000201")
    assert ready.cli("translation-plan") == 0
    assert plan_items(ready) == {"contested_reason[0]": "made_stale", "early_signals[0]": "already_missing"}


def test_translation_plan_does_not_plan_a_card_with_no_translation_file(ready: Env):
    accept_replacing(ready, "90000201")
    assert ready.cli("translation-plan") == 0
    plan = load(ready.run / "translation-plan.json")
    assert plan["cards"] == [] and plan["untranslated_cards"] == [SLUG]
    assert not (ready.run / "translate").exists()


def test_translation_plan_is_empty_when_nothing_was_accepted(ready: Env):
    ready.apply("ops_add_study.json")
    ready.put("review", "review_reject.json")
    write_norwegian(ready)
    assert ready.cli("translation-plan") == 0
    plan = load(ready.run / "translation-plan.json")
    assert plan["cards"] == [] and plan["untranslated_cards"] == []


def test_translation_plan_stops_on_an_unreadable_translation_file(ready: Env, capsys):
    write_norwegian(ready)
    (ready.translations / "nb" / f"{SLUG}.yaml").write_text("slug: wrong-name\nitems: {}\n", encoding="utf-8")
    accept_replacing(ready, "90000201")
    assert ready.cli("translation-plan") == 1
    assert "must equal the file name" in capsys.readouterr().err


def test_report_has_a_translation_section_only_after_the_plan_was_made(ready: Env):
    write_norwegian(ready)
    accept_replacing(ready, "90000201")
    assert ready.cli("report") == 0
    assert "## Translations" not in (ready.run / "report.md").read_text(encoding="utf-8")
    assert ready.cli("translation-plan") == 0
    assert ready.cli("report") == 0
    report = (ready.run / "report.md").read_text(encoding="utf-8")
    assert "## Translations (nb)" in report and "made stale by accepted changes: contested_reason[0]" in report


def test_pr_stages_the_translations_folder_when_there_is_one(accepted: Env):
    write_norwegian(accepted)
    runner = FakeRunner()
    assert accepted.cli("pr", runner=runner) == 0
    adds = [c for c in runner.calls if c[:2] == ["git", "add"]]
    assert len(adds) == 2 and adds[1][-1] == str(accepted.translations)
