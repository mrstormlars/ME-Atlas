"""Tests for the auditor's steps: audit-plan, record-audit, audit-sample, the audit gate in `pr` and the report.

Fictional papers, cards and agent output (tests/fixtures/pipeline). No test touches the network, an AI or git.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml
from test_pipeline import (
    DATE,
    FIXTURES,
    NEW_PMID,
    SLUG,
    SPEC,
    Env,
    FakeRunner,
    fulltext_loader,
    load,
)

from me_atlas import cards, pipeline

# A sentence of functional spec section 3, and a sentence of section 2: rubric clauses are copied from them.
RUBRIC = "Grading follows only this published ladder; editors do not add criteria."
CITED_TITLE = "Fictional controlled study of widget signalling."
CITED = "pmid:90000100"
PAPER = f"pmid:{NEW_PMID}"

# Markers that must never reach the auditor.
OPS_MARKER = "OPS-MARKER-4f1c"
OPS_OP_MARKER = "DRAFTER-OPERATION-TEXT-9b2e"
CHECKS_MARKER = "CHECKS-MARKER-77aa"
REVIEW_MARKER = "REVIEWER-FINDING-MARKER-31d0"
EARLIER_AUDIT_MARKER = "EARLIER-AUDIT-MARKER-c5e8"
FULLLINE_COMMENT_MARKER = "FULLLINE-COMMENT-MARKER-0a7d"
TRAILING_COMMENT_MARKER = "TRAILING-COMMENT-MARKER-6e19"


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def ready(env: Env) -> Env:
    """Prepared and classified, as in test_pipeline."""
    env.prepare()
    assert env.classify() == 0
    return env


def audit_data(decision: str = "accept", **over) -> dict:
    data = {
        "card": SLUG,
        "paper": PAPER,
        "decision": decision,
        "parts": [
            {
                "decision_part": "The proposed level 3.",
                "rubric": RUBRIC,
                "evidence": [{"source": CITED, "quote": CITED_TITLE}],
            }
        ],
        "reasons_summary": "The cited controlled study supports the proposed level.",
        "would_change": "A failed replication.",
    }
    if decision == "accept_lower":
        data["accepted_level"] = 2
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def write_record(env: Env, data: dict | str, *, second: bool = False, key: str = NEW_PMID) -> Path:
    path = env.run / "audit" / f"{SLUG}-{key}{'-second' if second else ''}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def level_pair(env: Env, *, plan: bool = True) -> None:
    """The reviewer accepted a change that proposes level 2 -> 3 (a tier 2 pair); its audit context is built."""
    assert env.apply("ops_propose_level.json") == 0
    env.put("review", "review_accept.json")
    if plan:
        assert env.cli("audit-plan", SLUG, NEW_PMID, fulltext=fulltext_loader()) == 0


def record(env: Env, *extra: str) -> int:
    return env.cli("record-audit", SLUG, NEW_PMID, *extra)


def cfg_of(env: Env) -> pipeline.Config:
    return pipeline.Config(env.run, env.cards, env.drafts, env.cache, SPEC, env.pipeline, env.translations)


def pr(env: Env, runner: FakeRunner | None = None) -> int:
    return env.cli("pr", "--no-pr", runner=runner or FakeRunner(branch="feat/anything"))


# --- audit-plan: the context file ----------------------------------------------------------------


def test_the_context_has_the_diff_the_card_a_cited_record_and_the_rubric_and_no_agent_output(ready: Env):
    # Comments in the draft carry earlier reasoning and rulings: full-line and trailing ones must not reach the auditor,
    # a "#" inside a text value is content and must stay.
    draft = ready.drafts / f"{SLUG}.yaml"
    text = draft.read_text(encoding="utf-8")
    text = text.replace("\nlevel: 2\n", f"\nlevel: 2  # {TRAILING_COMMENT_MARKER}\n", 1)
    text = text.replace("than in controls.", "than in controls (see #HASH-KEPT-IN-TEXT).", 1)
    draft.write_text(f"# {FULLLINE_COMMENT_MARKER}\n" + text, encoding="utf-8")
    assert ready.apply("ops_propose_level.json") == 0
    ready.put("review", "review_accept.json")
    # Unique markers in every file an agent wrote about this change, in places the card diff does not show.
    ops_path = ready.run / "ops" / f"{SLUG}-{NEW_PMID}-r1.json"
    ops = load(ops_path)
    ops["note"] = OPS_MARKER
    ops["operations"][0]["note"] = OPS_OP_MARKER
    ops_path.write_text(json.dumps(ops), encoding="utf-8")
    checks_path = ready.run / "checks" / f"{SLUG}-{NEW_PMID}-r1.json"
    checks = load(checks_path)
    checks["marker"] = CHECKS_MARKER
    checks_path.write_text(json.dumps(checks), encoding="utf-8")
    review_path = ready.run / "review" / f"{SLUG}-{NEW_PMID}-r1.json"
    review = load(review_path)
    review["findings"] = [{"operation": 0, "severity": "advisory", "problem": REVIEW_MARKER}]
    review_path.write_text(json.dumps(review), encoding="utf-8")
    write_record(ready, audit_data(reasons_summary=EARLIER_AUDIT_MARKER))

    assert ready.cli("audit-plan", SLUG, NEW_PMID, fulltext=fulltext_loader()) == 0
    text = (ready.run / "audit-context" / f"{SLUG}-{NEW_PMID}.md").read_text(encoding="utf-8")
    for marker in (
        OPS_MARKER,
        OPS_OP_MARKER,
        CHECKS_MARKER,
        REVIEW_MARKER,
        EARLIER_AUDIT_MARKER,
        FULLLINE_COMMENT_MARKER,
        TRAILING_COMMENT_MARKER,
        "a comment between two paragraphs",
        "a comment inside a badge",
    ):
        assert marker not in text, marker
    assert "#HASH-KEPT-IN-TEXT" in text  # a # inside a value is content
    # What it does hold: the diff, the card, a cited record, spec section 3 and the card format.
    assert "+level: 3" in text and "-level: 2" in text
    assert "slug: fictional-pipeline-card" in text  # the card as it stands
    assert f"### Record: {CITED}" in text and CITED_TITLE in text
    assert f"### Record: {PAPER}" in text  # the paper the change adds: the applied card cites it
    assert RUBRIC in text
    assert "## 4. The inclusion rule" in text and "## 5. The rubric" in text
    assert "### Evidence card format" in text  # docs/card-format.md, headings demoted
    assert [f"## {n}. " in text for n in range(1, 7)] == [True] * 6
    # The record of a paper whose full text is cached carries it, with the truncation stated as `context` does.
    assert "Not truncated" in text or "TRUNCATED" in text


def test_a_study_with_no_cached_record_is_named_and_cannot_be_cited(ready: Env):
    level_pair(ready)
    text = (ready.run / "audit-context" / f"{SLUG}-{NEW_PMID}.md").read_text(encoding="utf-8")
    assert "### Not cached: pmid:90000104" in text
    assert "### Record: pmid:90000104" not in text


def jats(*sentences: str) -> bytes:
    body = "".join(f"<p>{x}</p>" for x in sentences)
    return (
        f"<article><front><article-meta><title-group><article-title>T</article-title></title-group></article-meta>"
        f"</front><body><sec><title>Results</title>{body}</sec></body></article>"
    ).encode()


def loader_for(texts: dict[str, bytes]):
    """A full-text loader with a cached text only for the PMIDs in ``texts``; it records which it was asked for."""
    asked: list[str] = []

    def load_it(pmid: str, pmcid: str | None = None, **_kw) -> pipeline.FullTextResult:
        asked.append(pmid)
        if pmid in texts:
            return pipeline.FullTextResult(texts[pmid], f"fictional cache, PMC{pmid}")
        return pipeline.FullTextResult(None, "no open full text")

    load_it.asked = asked  # type: ignore[attr-defined]
    return load_it


LAST_SENTENCE = "LAST-SENTENCE-OF-A-LONG-FULL-TEXT-5d3a."


def record_block(text: str, study_id: str) -> str:
    return text.split(f"### Record: {study_id}")[1].split("\n### ")[0].split("\n## ")[0]


def test_a_carrier_full_text_longer_than_the_old_budget_appears_whole(ready: Env):
    long_text = jats(*(["A filler sentence about widget signalling."] * 600), LAST_SENTENCE)
    assert len(long_text) > 12_000
    ready.apply("ops_propose_level.json")
    text = pipeline.build_audit_context(cfg_of(ready), SLUG, NEW_PMID, loader_for({"90000100": long_text}))
    block = record_block(text, CITED)  # pmid:90000100 carries the level
    assert LAST_SENTENCE in block and "TRUNCATED" not in text
    assert "Not truncated (" in block and " characters)." in block


def early_signal_ops(env: Env) -> None:
    """A change whose new study is cited only in an early signal: not a carrier of the level, a badge or the mark."""
    ops = load(FIXTURES / "agent" / "ops_add_study.json")
    ops["operations"][1].update(field="early_signals", text="A fictional unreplicated signal.")
    path = env.run / "ops" / f"{SLUG}-{NEW_PMID}-r1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ops), encoding="utf-8")
    assert env.cli("apply", SLUG, str(path), "--round", "1") == 0


def test_a_non_carrier_with_a_cached_full_text_shows_the_abstract_only(ready: Env):
    early_signal_ops(ready)
    loader = loader_for({"90000100": jats("Carrier text."), "90000101": jats(LAST_SENTENCE)})
    text = pipeline.build_audit_context(cfg_of(ready), SLUG, NEW_PMID, loader)
    block = record_block(text, PAPER)
    assert "Abstract only (not a carrier of the level, a badge or the contested mark)" in block
    assert "A total of 60 patients and 55 controls were compared." in block  # the abstract is there
    assert LAST_SENTENCE not in text and "90000101" not in loader.asked
    assert "Carrier text." in record_block(text, CITED)


def test_a_carrier_without_a_cached_full_text_gets_the_abstract_and_the_plain_statement(ready: Env):
    ready.apply("ops_propose_level.json")
    text = pipeline.build_audit_context(cfg_of(ready), SLUG, NEW_PMID, loader_for({}))
    block = record_block(text, CITED)
    assert (
        "FULL TEXT NOT CACHED: only the abstract is given. A statement on the card that is not in this abstract may "
        "stand in the full text; it cannot be checked here."
    ) in block
    assert "Abstract:" in block


def test_an_id_the_change_newly_adds_to_level_reason_is_a_carrier(ready: Env):
    ready.apply("ops_propose_level.json")  # level_reason now cites pmid:90000101, which the card did not cite before
    loader = loader_for({"90000100": jats("Old carrier."), "90000101": jats(LAST_SENTENCE)})
    text = pipeline.build_audit_context(cfg_of(ready), SLUG, NEW_PMID, loader)
    assert LAST_SENTENCE in record_block(text, PAPER)
    assert "90000101" in loader.asked
    base = pipeline.carrier_ids(pipeline._load_card(ready.drafts / f"{SLUG}.yaml"))
    assert PAPER not in base and CITED in base


def test_a_quote_from_a_full_text_the_auditor_was_not_shown_is_refused(ready: Env, monkeypatch, capsys):
    early_signal_ops(ready)
    ready.put("review", "review_accept.json")
    full = "HIDDEN-FULLTEXT-SENTENCE-8c2f is only in the cached full text."
    monkeypatch.setattr(pipeline.citations.CacheReader, "fulltext", lambda self, pmid: full)
    assert ready.cli("audit-plan", SLUG, NEW_PMID, fulltext=loader_for({"90000100": jats("C.")})) == 0
    # PAPER is a non-carrier here: shown as abstract only, so its cached full text may not be quoted.
    quote = "HIDDEN-FULLTEXT-SENTENCE-8c2f is only in the cached full text."
    write_record(ready, audit_data(parts=part_with(evidence=[{"source": PAPER, "quote": quote}])))
    assert record(ready) == 1
    assert "is not found word for word in the cached record of " + PAPER in capsys.readouterr().err
    # The same quote from a carrier (CITED) is accepted: its full text was given whole.
    write_record(ready, audit_data(parts=part_with(evidence=[{"source": CITED, "quote": quote}])))
    assert record(ready) == 0


def test_a_whole_card_context_holds_the_card_file_and_goes_to_out(env: Env, tmp_path: Path):
    shutil.copy(FIXTURES / "pubmed" / "90000100.xml", env.cache / "pubmed" / "90000100.xml")
    out = tmp_path / "card-audit"
    code = pipeline.main(
        ["audit-plan", "--card", SLUG, "--out", str(out), *env.dir_args], fulltext=fulltext_loader(), out=env.out.append
    )
    assert code == 0
    text = (out / "audit-context" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert "whole card" in text and "```diff" not in text
    assert "a comment between two paragraphs" not in text and "a comment inside a badge" not in text
    assert text.count("slug: fictional-pipeline-card") == 1  # the card file appears once
    assert f"### Record: {CITED}" in text and RUBRIC in text


def test_audit_plan_needs_an_applied_result(ready: Env, capsys):
    assert ready.cli("audit-plan", SLUG, NEW_PMID, fulltext=fulltext_loader()) == 1
    assert "run `apply` first" in capsys.readouterr().err


# --- record-audit ------------------------------------------------------------------------------


def test_a_well_formed_record_passes(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data())
    assert record(ready) == 0
    assert "audit recorded: accept" in ready.out[-1]


def test_a_quote_may_differ_in_whitespace_and_quote_marks_only(ready: Env):
    level_pair(ready)
    quote = "Fictional  controlled\nstudy of widget signalling."
    write_record(
        ready, audit_data(parts=[{**audit_data()["parts"][0], "evidence": [{"source": CITED, "quote": quote}]}])
    )
    assert record(ready) == 0


def part_with(**over) -> list[dict]:
    part = {**audit_data()["parts"][0], **over}
    return [{k: v for k, v in part.items() if v is not None}]


NEGATIVES = {
    "a source that is not among the ids cited in the context file": (
        audit_data(parts=part_with(evidence=[{"source": "pmid:90000999", "quote": CITED_TITLE}])),
        "is not a record in the context file",
    ),
    "a record named in the card but not cached is not citable either": (
        audit_data(parts=part_with(evidence=[{"source": "pmid:90000104", "quote": "A fictional study of 100"}])),
        "is not a record in the context file",
    ),
    "a quote not found verbatim in the cached record": (
        audit_data(
            parts=part_with(evidence=[{"source": CITED, "quote": "Fictional widget study of controlled signalling."}])
        ),
        "is not found word for word in the cached record of pmid:90000100",
    ),
    "a quote that is only a paraphrase of another record": (
        audit_data(parts=part_with(evidence=[{"source": CITED, "quote": "Widget signalling was lower in patients."}])),
        "is not found word for word in the cached record of pmid:90000100",
    ),
    "a part with no rubric": (audit_data(parts=part_with(rubric=None)), "parts.0.rubric"),
    "a part with an empty rubric": (audit_data(parts=part_with(rubric="  ")), "parts.0.rubric"),
    "a rubric not found in spec sections 2 and 3": (
        audit_data(parts=part_with(rubric="Grading follows whatever the auditor thinks is fair.")),
        "rubric is not found word for word in functional spec section 2 or 3",
    ),
    "a rubric shorter than 20 characters": (audit_data(parts=part_with(rubric="Evidence ladder")), "shorter than 20"),
    "accept_lower without accepted_level": (
        audit_data("accept_lower", accepted_level=None),
        "accept_lower needs accepted_level",
    ),
    "accept_lower with a level that is not lower": (
        audit_data("accept_lower", accepted_level=3),
        "accepted_level 3 must be lower than the level 3",
    ),
    "accepted_level with accept": (audit_data("accept", accepted_level=2), "only for accept_lower"),
    "an unknown decision": (audit_data("maybe"), "decision"),
    "no parts": (audit_data(parts=[]), "parts"),
    "a record for another card": (audit_data(card="other-card"), "card is 'other-card'"),
    "a record for another paper": (audit_data(paper="pmid:90000102"), "paper is 'pmid:90000102'"),
    "a record with no paper (a whole-card record) for a change": (audit_data(paper=None), "paper is None"),
    "a multi-line summary": (audit_data(reasons_summary="one\ntwo"), "one line"),
    "no would_change": (audit_data(would_change=None), "would_change"),
}


@pytest.mark.parametrize("data, message", NEGATIVES.values(), ids=NEGATIVES.keys())
def test_record_audit_rejects(ready: Env, capsys, data, message):
    level_pair(ready)
    write_record(ready, data)
    assert record(ready) == 1
    assert message in capsys.readouterr().err


def test_a_record_that_is_not_yaml_or_is_missing_is_an_error(ready: Env, capsys):
    level_pair(ready)
    assert record(ready) == 1 and "does not exist" in capsys.readouterr().err
    write_record(ready, "decision: [unclosed")
    assert record(ready) == 1 and "not readable YAML" in capsys.readouterr().err


def test_record_audit_needs_the_context_file(ready: Env, capsys):
    ready.apply("ops_propose_level.json")
    write_record(ready, audit_data())
    assert record(ready) == 1 and "run `audit-plan` first" in capsys.readouterr().err


def test_accept_lower_below_the_level_passes(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("accept_lower"))
    assert record(ready) == 0 and "accepted level 2" in ready.out[-1]


def test_the_second_run_reads_its_own_file(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("reject"), second=True)
    assert record(ready, "--second") == 0 and "audit recorded: reject" in ready.out[-1]


def test_a_whole_card_record_is_checked_against_the_card_level(env: Env, tmp_path: Path):
    shutil.copy(FIXTURES / "pubmed" / "90000100.xml", env.cache / "pubmed" / "90000100.xml")
    out = tmp_path / "card-audit"
    pipeline.main(["audit-plan", "--card", SLUG, "--out", str(out), *env.dir_args], fulltext=fulltext_loader())
    good = {k: v for k, v in audit_data("accept_lower", accepted_level=1).items() if k != "paper"}
    bad = {**good, "accepted_level": 2}  # the card is at level 2: not lower
    for name, data, expected in (("good", good, 0), ("bad", bad, 1)):
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        argv = ["record-audit", "--card", SLUG, "--file", str(path), "--out", str(out), *env.dir_args]
        assert pipeline.main(argv, out=env.out.append) == expected, name


# --- the audit gate: apply a pair only when everything accepts -----------------------------------


def card_before(env: Env) -> bytes:
    return (env.drafts / f"{SLUG}.yaml").read_bytes()


def finish(env: Env) -> bytes:
    """Run `pr --no-pr` and return the draft card's bytes afterwards."""
    assert pr(env) == 0
    return card_before(env)


def scenario_failed_check(env: Env) -> None:
    assert env.apply("ops_bad_validator.json") == 1
    env.put("review", "review_accept.json")
    write_record(env, audit_data())
    write_record(env, audit_data(), second=True)


def scenario_review_reject(env: Env) -> None:
    env.apply("ops_propose_level.json")
    env.put("review", "review_reject.json")
    env.cli("audit-plan", SLUG, NEW_PMID, fulltext=fulltext_loader())
    write_record(env, audit_data())
    write_record(env, audit_data(), second=True)


def scenario_audit_reject(env: Env) -> None:
    level_pair(env)
    write_record(env, audit_data("reject"))
    write_record(env, audit_data("reject"), second=True)


def scenario_audit_accept_lower(env: Env) -> None:
    level_pair(env)
    write_record(env, audit_data("accept_lower"))
    write_record(env, audit_data("accept_lower"), second=True)


def scenario_audit_missing(env: Env) -> None:
    level_pair(env)


def scenario_second_rejects(env: Env) -> None:
    level_pair(env)
    write_record(env, audit_data("accept"))
    write_record(env, audit_data("reject"), second=True)


def scenario_second_missing(env: Env) -> None:
    level_pair(env)
    write_record(env, audit_data("accept"))


def scenario_invalid_record(env: Env) -> None:
    level_pair(env)
    write_record(env, audit_data(parts=part_with(rubric="Grading follows whatever the auditor thinks is fair.")))
    write_record(env, audit_data(), second=True)


NOT_APPLIED = {
    "a failed mechanical check": scenario_failed_check,
    "a reviewer reject": scenario_review_reject,
    "an audit reject": scenario_audit_reject,
    "an audit accept_lower": scenario_audit_accept_lower,
    "a missing audit": scenario_audit_missing,
    "an audit accept but a second run reject": scenario_second_rejects,
    "an audit accept and the second run missing": scenario_second_missing,
    "an audit record that does not validate": scenario_invalid_record,
}


@pytest.mark.parametrize("scenario", NOT_APPLIED.values(), ids=NOT_APPLIED.keys())
def test_the_card_is_byte_identical_after_pr_when(ready: Env, scenario):
    before = card_before(ready)
    scenario(ready)
    runner = FakeRunner(branch="feat/anything")
    code = ready.cli("pr", "--no-pr", runner=runner)
    assert code == 0
    assert card_before(ready) == before
    assert not (ready.cards / "changelog.yaml").exists()


def test_checks_pass_review_accept_audit_accept_changes_the_card(ready: Env):
    before = card_before(ready)
    level_pair(ready)
    write_record(ready, audit_data("accept"))
    write_record(ready, audit_data("accept"), second=True)  # a level change is always decided twice
    after = finish(ready)
    assert after != before
    data = yaml.safe_load(after)
    assert data["level"] == 3 and data["studies"][-1]["id"] == PAPER


def test_a_tier_1_pair_needs_no_audit(ready: Env):
    ready.apply("ops_add_study.json")
    ready.put("review", "review_accept.json")
    before = card_before(ready)
    assert finish(ready) != before
    [o] = pipeline.collect_outcomes(cfg_of(ready))
    assert o.audit_required is False and o.audit_state == "not_required" and o.applied


def test_a_level_change_is_decided_twice_even_when_the_sample_file_is_missing(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("accept"))
    [o] = pipeline.collect_outcomes(cfg_of(ready))
    assert o.sampled and o.audit_state == "missing" and not o.applied
    assert "second audit" in o.audit_note


def test_the_pr_commit_adds_the_audit_records(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("accept"))
    write_record(ready, audit_data("accept"), second=True)
    runner = FakeRunner(branch="feat/anything")
    assert ready.cli("pr", "--no-pr", runner=runner) == 0
    audits = ready.root / "audits"
    assert sorted(p.name for p in audits.glob("*.yaml")) == [
        f"{DATE.isoformat()}-{SLUG}-{NEW_PMID}-second.yaml",
        f"{DATE.isoformat()}-{SLUG}-{NEW_PMID}.yaml",
    ]
    add = next(c for c in runner.calls if c[:2] == ["git", "add"])
    assert any(str(audits) in part for part in add)
    assert (
        yaml.safe_load((audits / f"{DATE.isoformat()}-{SLUG}-{NEW_PMID}.yaml").read_text(encoding="utf-8"))["decision"]
        == "accept"
    )


def test_a_rejected_audit_is_still_copied_into_audits_and_committed(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("reject"))
    runner = FakeRunner(branch="feat/anything")
    assert ready.cli("pr", "--no-pr", runner=runner) == 0
    assert (ready.root / "audits" / f"{DATE.isoformat()}-{SLUG}-{NEW_PMID}.yaml").is_file()
    assert any(c[:2] == ["git", "commit"] for c in runner.calls)


# --- pr on a card in cards/: change log and last_checked ----------------------------------------


@pytest.fixture
def published(ready: Env) -> Env:
    """The card sits in cards/ (not drafts/), as after the first publication, last checked by the auditor."""
    text = (ready.drafts / f"{SLUG}.yaml").read_text(encoding="utf-8").replace("by: ai_pair", "by: ai_audit")
    (ready.cards / f"{SLUG}.yaml").write_text(text, encoding="utf-8")
    (ready.drafts / f"{SLUG}.yaml").unlink()
    return ready


def test_an_audited_change_on_a_card_in_cards_sets_last_checked_and_logs_ai_audit(published: Env):
    level_pair(published)
    write_record(published, audit_data("accept"))
    write_record(published, audit_data("accept"), second=True)
    assert pr(published) == 0
    card = yaml.safe_load((published.cards / f"{SLUG}.yaml").read_text(encoding="utf-8"))
    assert card["level"] == 3
    assert card["last_checked"] == {"date": DATE, "by": "ai_audit"}
    log = cards.load_changelog(published.cards / "changelog.yaml", today=DATE)
    [entry] = log
    assert (entry.card, entry.tier, entry.decided_by, entry.date) == (SLUG, 2, "ai_audit", DATE)
    assert "Proposed level 2 -> 3" in entry.change and PAPER in entry.sources
    assert entry.reason == "The cited controlled study supports the proposed level."
    assert not (published.drafts / f"{SLUG}.yaml").exists()  # nothing was written to drafts/
    _count, issues = cards.validate_paths(
        [published.cards], today=DATE, content_dir=published.root / "content", cards_dir=published.cards
    )
    assert issues == []


def test_a_tier_1_change_on_a_card_in_cards_logs_ai_pair_and_leaves_last_checked(published: Env):
    published.apply("ops_add_study.json")
    published.put("review", "review_accept.json")
    before = yaml.safe_load((published.cards / f"{SLUG}.yaml").read_text(encoding="utf-8"))["last_checked"]
    assert pr(published) == 0
    card = yaml.safe_load((published.cards / f"{SLUG}.yaml").read_text(encoding="utf-8"))
    assert card["last_checked"] == before and card["studies"][-1]["id"] == PAPER
    [entry] = cards.load_changelog(published.cards / "changelog.yaml", today=DATE)
    assert (entry.tier, entry.decided_by) == (1, "ai_pair")
    assert not (published.root / "audits").exists()


def test_new_change_log_entries_are_appended_to_the_existing_ones(published: Env):
    existing = [
        {
            "date": dt.date(2026, 10, 1),
            "card": SLUG,
            "change": "An earlier change.",
            "reason": "An earlier reason.",
            "sources": ["pmid:90000100"],
            "tier": 1,
            "decided_by": "ai_pair",
        }
    ]
    (published.cards / "changelog.yaml").write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
    published.apply("ops_add_study.json")
    published.put("review", "review_accept.json")
    assert pr(published) == 0
    log = cards.load_changelog(published.cards / "changelog.yaml", today=DATE)
    assert [e.change.startswith("An earlier") for e in log] == [True, False]


def test_a_card_in_drafts_gets_no_change_log_entry(ready: Env):
    ready.apply("ops_add_study.json")
    ready.put("review", "review_accept.json")
    assert pr(ready) == 0
    assert not (ready.cards / "changelog.yaml").exists()


# --- audit-sample --------------------------------------------------------------------------------


def fabricate(env: Env, key: str, *, target: str = "diagnostic_marker") -> None:
    """An accepted pair whose only operation proposes ``target`` (tier 2), with passing checks and a review."""
    cfg = cfg_of(env)
    op = {"op": "propose", "target": target, "value": 3 if target == "level" else False}
    if target == "level":
        op["reason"] = [{"text": "A fictional level reason.", "sources": ["pmid:90000100"]}]
    ops = {"card": SLUG, "paper": f"pmid:{key}", "operations": [op]}
    for path, body in (
        (cfg.ops_path(SLUG, key, 1), ops),
        (cfg.checks_path(SLUG, key, 1), {"passed": True, "card": SLUG, "citations": []}),
        (cfg.review_path(SLUG, key, 1), {"card": SLUG, "paper": f"pmid:{key}", "verdict": "accept", "findings": []}),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
    matches = load(env.run / "matches.json")
    matches["matches"].append({"slug": SLUG, "pmid": key})
    (env.run / "matches.json").write_text(json.dumps(matches), encoding="utf-8")


def sample(env: Env, *argv: str) -> dict:
    assert env.cli("audit-sample", *argv) == 0
    return load(env.run / "audit-sample.json")


def fake_outcomes(others: int, level_changes: int = 1) -> list[pipeline.Outcome]:
    """Accepted tier 2 pairs without files: ``level_changes`` proposals of a level and ``others`` other changes."""
    found = []
    for i in range(level_changes + others):
        key = f"9000{i:04d}"
        if i < level_changes:
            op = {
                "op": "propose",
                "target": "level",
                "value": 3,
                "reason": [{"text": "A fictional level reason.", "sources": [CITED]}],
            }
        else:
            op = {"op": "add_paragraph", "field": "early_signals", "text": "A fictional signal.", "sources": [CITED]}
        ops = pipeline.parse_ops({"card": SLUG, "paper": f"pmid:{key}", "operations": [op]})
        o = pipeline.Outcome(SLUG, key, "accepted", "", [pipeline.Round(1, ops, None, None, None)], f"pmid:{key}")
        o.audit_required = True
        found.append(o)
    return found


@pytest.fixture
def many(ready: Env, monkeypatch) -> Env:
    """Eleven audited pairs: one level change (key 90000000) and ten others."""
    outcomes = fake_outcomes(others=10)
    monkeypatch.setattr(pipeline, "collect_outcomes", lambda cfg, *, gate=True: outcomes)
    return ready


def test_the_same_seed_gives_the_same_sample(many: Env):
    first = sample(many, "--seed", "alpha")
    again = sample(many, "--seed", "alpha")
    assert first == again and first["seed"] == "alpha"


def test_every_level_change_is_in_the_sample_whatever_the_seed_and_one_in_five_of_the_rest(many: Env):
    seen: set[tuple[str, ...]] = set()
    for seed in ("a", "b", "c", "2026-11-01", "x", "y", "z"):
        result = sample(many, "--seed", seed)
        keys = [p["key"] for p in result["pairs"]]
        assert next(p for p in result["pairs"] if p["key"] == "90000000")["why"] == "level_change"
        assert len(keys) == 1 + 2  # ten others: one in five, two
        assert result["audited"] == 11
        seen.add(tuple(keys))
    assert len(seen) > 1  # the seed does change which of the others are chosen


def test_every_level_change_is_in_the_sample_even_when_there_are_many(ready: Env, monkeypatch):
    outcomes = fake_outcomes(others=3, level_changes=4)
    monkeypatch.setattr(pipeline, "collect_outcomes", lambda cfg, *, gate=True: outcomes)
    for seed in ("a", "b", "c"):
        keys = {p["key"] for p in sample(ready, "--seed", seed)["pairs"] if p["why"] == "level_change"}
        assert keys == {"90000000", "90000001", "90000002", "90000003"}


def test_the_sample_rounds_up_one_in_five(ready: Env, monkeypatch):
    for others, expected in ((0, 0), (1, 1), (5, 1), (6, 2), (11, 3)):
        outcomes = fake_outcomes(others=others)
        monkeypatch.setattr(pipeline, "collect_outcomes", lambda cfg, *, gate=True, o=outcomes: o)
        assert len(sample(ready)["pairs"]) == 1 + expected, others


def test_a_real_run_with_only_a_level_change_samples_just_that_pair(ready: Env):
    (ready.run / "matches.json").write_text(json.dumps({"matches": [], "stopped": [], "new_hypotheses": []}))
    fabricate(ready, "90000300", target="level")
    assert [p["why"] for p in sample(ready)["pairs"]] == ["level_change"]


def test_the_default_seed_is_the_run_date_and_seed_overrides_it(many: Env):
    assert sample(many)["seed"] == DATE.isoformat()
    assert sample(many, "--seed", "other")["seed"] == "other"


def test_tier_1_pairs_are_not_in_the_sample(ready: Env):
    ready.apply("ops_add_study.json")
    ready.put("review", "review_accept.json")
    result = sample(ready)
    assert result["audited"] == 0 and result["pairs"] == []


def test_pairs_that_failed_a_check_or_were_rejected_are_never_sampled(ready: Env):
    fabricate(ready, "90000401")
    cfg = cfg_of(ready)
    review = {
        "card": SLUG,
        "paper": "pmid:90000401",
        "verdict": "reject",
        "findings": [{"operation": 0, "severity": "must_fix", "problem": "Wrong."}],
    }
    cfg.review_path(SLUG, "90000401", 1).write_text(json.dumps(review), encoding="utf-8")
    assert sample(ready)["audited"] == 0


# --- the report ----------------------------------------------------------------------------------


def report_of(env: Env) -> str:
    assert env.cli("report") == 0
    return (env.run / "report.md").read_text(encoding="utf-8")


def section(report: str, title: str) -> str:
    return report.split(f"## {title}")[1].split("\n## ")[0]


def test_the_report_lists_each_decision_the_consistency_count_and_no_disputes_when_all_agree(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("accept"))
    write_record(ready, audit_data("accept"), second=True)
    report = report_of(ready)
    decisions = section(report, "Auditor decisions")
    assert "accept: The cited controlled study supports the proposed level." in decisions
    assert "Consistency check: 1 of 1 sampled decisions decided a second time; 0 differed." in decisions
    assert section(report, "Disputes (card unchanged)").strip() == "None."
    tier2 = report.split("### Tier 2")[1].split("### Tier 1")[0]
    assert "Propose level 2 -> 3" in tier2 and "audit: accept" in tier2


def test_a_differing_second_verdict_is_counted_listed_as_a_dispute_and_not_applied(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("accept"))
    write_record(ready, audit_data("reject", reasons_summary="The second reading found no support."), second=True)
    report = report_of(ready)
    assert "Consistency check: 1 of 1 sampled decisions decided a second time; 1 differed." in report
    disputes = section(report, "Disputes (card unchanged)")
    assert "the second audit decided reject, the first accept: not applied" in disputes
    tier2 = report.split("### Tier 2")[1].split("### Tier 1")[0]
    assert "Propose level" not in tier2  # held back: not in the applied changes
    [o] = pipeline.collect_outcomes(cfg_of(ready))
    assert o.audit_state == "differs" and o.second_differs and not o.applied


def park_a_pair(env: Env, key: str = "90000102") -> None:
    """A pair the reviewer rejected in both rounds."""
    cfg = cfg_of(env)
    for n in (1, 2):
        op = {"op": "add_paragraph", "field": "early_signals", "text": "T.", "sources": [CITED]}
        review = {
            "card": SLUG,
            "paper": f"pmid:{key}",
            "verdict": "reject",
            "findings": [{"operation": 0, "severity": "must_fix", "problem": "Wrong."}],
        }
        for path, body in (
            (cfg.ops_path(SLUG, key, n), {"card": SLUG, "paper": f"pmid:{key}", "operations": [op]}),
            (cfg.checks_path(SLUG, key, n), {"passed": True, "card": SLUG, "citations": []}),
            (cfg.review_path(SLUG, key, n), review),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(body), encoding="utf-8")
    matches = load(env.run / "matches.json")
    matches["matches"].append({"slug": SLUG, "pmid": key})
    (env.run / "matches.json").write_text(json.dumps(matches), encoding="utf-8")


def test_the_disputes_hold_parked_pairs_and_audit_rejects(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("reject", reasons_summary="No controlled study supports it."))
    park_a_pair(ready)
    report = report_of(ready)
    disputes = section(report, "Disputes (card unchanged)")
    assert "parked (rejected in round 2)" in disputes and "90000102" in disputes
    assert "the auditor rejected the change: No controlled study supports it." in disputes
    # a parked pair is never sent to the auditor: it has no entry among the decisions
    decisions = section(report, "Auditor decisions")
    assert "90000102" not in decisions and "reject: No controlled study supports it." in decisions


def test_the_disputes_hold_an_accept_lower_with_its_level(ready: Env):
    level_pair(ready)
    write_record(ready, audit_data("accept_lower", reasons_summary="Only level 2 is supported."))
    disputes = section(report_of(ready), "Disputes (card unchanged)")
    assert "the auditor accepts level 2 only, so nothing is applied: Only level 2 is supported." in disputes


def test_a_parked_pair_is_never_sent_to_the_auditor_or_applied(ready: Env):
    park_a_pair(ready)
    o = next(o for o in pipeline.collect_outcomes(cfg_of(ready)) if o.pmid == "90000102")
    assert o.status == "parked" and not o.audit_required and not o.applied
    assert pipeline.audit_sample(cfg_of(ready))["audited"] == 0


def test_the_report_says_none_when_nothing_needed_an_audit(ready: Env):
    ready.apply("ops_add_study.json")
    ready.put("review", "review_accept.json")
    report = report_of(ready)
    assert section(report, "Auditor decisions").strip().startswith("None.")
    assert "Consistency check" not in report
    assert section(report, "Disputes (card unchanged)").strip() == "None."


def test_a_pair_with_no_valid_audit_is_listed_as_not_applied(ready: Env):
    level_pair(ready)
    report = report_of(ready)
    assert "not applied, no valid audit record" in section(report, "Auditor decisions")


def test_a_valid_whole_card_record_is_copied_into_audits_on_pr(ready: Env):
    assert ready.cli("audit-plan", "--card", SLUG, fulltext=fulltext_loader()) == 0
    assert (ready.run / "audit-context" / f"{SLUG}.md").is_file()
    data = {k: v for k, v in audit_data().items() if k != "paper"}
    write_record(ready, data, key="x").rename(ready.run / "audit" / f"{SLUG}.yaml")
    ready.apply("ops_add_study.json")
    ready.put("review", "review_accept.json")
    assert pr(ready) == 0
    assert (ready.root / "audits" / f"{DATE.isoformat()}-{SLUG}.yaml").is_file()


def test_two_audited_pairs_that_overwrite_one_target_are_parked_and_a_rejected_one_does_not_conflict(
    ready: Env, monkeypatch
):
    for key in ("90000201", "90000202"):
        fabricate(ready, key, target="level")
    verdicts = {"90000201": "accept", "90000202": "accept"}

    def fake_load_audit(cfg, slug, key, *, second=False):
        return pipeline.AuditRecord.model_validate(audit_data(verdicts[key])), None

    monkeypatch.setattr(pipeline, "load_audit", fake_load_audit)
    outcomes = {o.pmid: o for o in pipeline.collect_outcomes(cfg_of(ready)) if o.pmid.startswith("900002")}
    assert [o.status for o in outcomes.values()] == ["parked", "parked"]
    assert all("conflicts with" in o.note for o in outcomes.values())
    verdicts["90000201"] = "reject"  # one of them is not accepted by the auditor: no conflict left
    outcomes = {o.pmid: o for o in pipeline.collect_outcomes(cfg_of(ready)) if o.pmid.startswith("900002")}
    assert outcomes["90000202"].applied and not outcomes["90000201"].applied
