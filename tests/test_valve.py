"""Tests for the safety valve for wording-only findings (DECISIONS 2026-11-15): the classification in review findings
and audit parts, the valve at the review stages and at the audit stage, the guard of the fix, the fix check, the
publication and its trail, and the classification exception of one card.

Fictional card, papers and agent output (tests/fixtures/pipeline), temporary folders only. No test touches the
network, an AI or git.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_correction import Corr, ops_data
from test_pipeline import SLUG, SPEC, Env
from test_publish_card import PUB_DATE, Pub, whole

from me_atlas import pipeline
from me_atlas.operations import parse_ops
from me_atlas.pipeline import AuditRecord, ReviewFile, apply_valve

LATER = "2026-11-20"
DRAFT = (Path(__file__).parent / "fixtures" / "pipeline" / "drafts" / f"{SLUG}.yaml").read_text(encoding="utf-8")
EARLY = "early_signals[0]"
REMOVE_EARLY = {"op": "remove_paragraph", "field": "early_signals", "index": 0}
CONTESTED_TEXT = "A fictional study of 100 patients found no clear difference in widget signalling."
REWORD_CONTESTED = {
    "op": "replace_paragraph",
    "field": "contested.reason",
    "index": 0,
    "text": CONTESTED_TEXT,
    "sources": ["pmid:90000104"],
}
FINDING = "A fictional study of n=20 patients and 20 controls found lower widget signalling in patients."
REWORD_FINDING = {"op": "update_study", "id": "pmid:90000100", "set": {"finding": FINDING.replace("lower", "less")}}


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def pub(env: Env, tmp_path: Path) -> Pub:
    return Pub(env, tmp_path)


@pytest.fixture
def corr(pub: Pub, tmp_path: Path) -> Corr:
    c = Corr(pub, tmp_path)
    c.hold_back()
    return c


def classed(record: dict, klass: str | None, target: str | None = None, part: int = 0) -> dict:
    """A copy of an audit record whose part ``part`` carries a class (and a target)."""
    out = json.loads(json.dumps(record))
    if klass is not None:
        out["parts"][part]["class"] = klass
    if target is not None:
        out["parts"][part]["target"] = target
    return out


def wording_reject(target: str = EARLY) -> dict:
    return classed(whole("reject"), "wording", target)


def finding(klass: str | None = "wording", target: str | None = "contested_reason[0]", **over) -> dict:
    data = {
        "operation": 0,
        "severity": "must_fix",
        "problem": "The place name is not in the record.",
        "fix": "Remove it.",
    }
    if klass is not None:
        data["class"] = klass
    if target is not None:
        data["target"] = target
    return data | over


def write_review(corr: Corr, findings: list[dict], *, card: bool = False, verdict: str = "reject") -> int:
    name = f"{SLUG}-card-C1.json" if card else f"{SLUG}-rC1.json"
    path = corr.dir / "review" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"card": SLUG, "verdict": verdict, "findings": findings} | ({"paper": None} if card else {})
    path.write_text(json.dumps(data), encoding="utf-8")
    argv = ["record-review", SLUG, *(["--card-review"] if card else []), "--round", "C1", "--run-dir", str(corr.dir)]
    return corr.main(*argv)


def valve(corr: Corr, command: str, stage: str, *extra: str) -> int:
    return corr.main(command, SLUG, "--stage", stage, "--round", "C1", *extra, "--run-dir", str(corr.dir))


def write_valve(corr: Corr, key: str, *operations: dict) -> None:
    path = corr.dir / "valve" / f"{SLUG}-{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ops_data(*operations)), encoding="utf-8")


def write_check(corr: Corr, key: str, ids: list[str], *, resolves: bool = True, new_claim: bool = False) -> None:
    fixes = [{"finding": i, "resolves": resolves, "new_claim": new_claim, "reason": "One line."} for i in ids]
    (corr.dir / "valve" / f"{SLUG}-{key}-check.json").write_text(json.dumps({"card": SLUG, "fixes": fixes}), "utf-8")


def whole_fix(corr: Corr, stage: str, key: str, ids: list[str], *operations: dict, **check) -> None:
    """The orchestrator's fix, valve-apply, the fix-check context, the reviewer's answers and record-valve-check."""
    write_valve(corr, key, *operations)
    assert valve(corr, "valve-apply", stage) == 0
    assert valve(corr, "valve-check-plan", stage) == 0
    write_check(corr, key, ids, **check)
    assert valve(corr, "record-valve-check", stage) == 0


def audit_round(corr: Corr, first: dict, second: dict | None) -> None:
    """A good round up to the audit records; no second record when ``second`` is None."""
    corr.round_to_audits(first, second)
    if second is None:
        (corr.dir / "audit" / f"{SLUG}-C1-second.yaml").unlink()


# --- V1: the classification in the records ----------------------------------------------------------------------


def test_a_must_fix_of_a_correction_review_needs_a_class(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0
    assert write_review(corr, [finding(klass=None, target=None)]) == 1
    assert "must_fix without `class`" in capsys.readouterr().err
    assert write_review(corr, [finding(klass="decisive", target=None)]) == 0
    assert write_review(corr, [finding(), finding(severity="advisory", klass=None, target=None)]) == 0


def test_a_must_fix_of_the_whole_card_review_needs_a_class_but_the_review_before_drafting_does_not(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0
    assert write_review(corr, [finding(klass=None, target=None, operation=None)], card=True) == 1
    assert "must_fix without `class`" in capsys.readouterr().err
    assert write_review(corr, [finding(operation=None)], card=True) == 0
    pre = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    pre.write_text(
        json.dumps(
            json.loads(pre.read_text(encoding="utf-8"))
            | {"findings": [{"operation": None, "severity": "must_fix", "problem": "P."}], "verdict": "reject"}
        ),
        encoding="utf-8",
    )
    args = ["record-review", SLUG, "--card-review", "--pre", "--round", "C1", "--run-dir", str(corr.dir)]
    assert corr.main(*args) == 0


@pytest.mark.parametrize("target", [None, "level", "links[0].support", "studies[pmid:90000100].case_definition", "x"])
def test_a_wording_class_is_refused_when_the_target_is_not_free_text(target):
    data = {"card": SLUG, "paper": None, "verdict": "reject", "findings": [finding(target=target, operation=None)]}
    with pytest.raises(ValueError, match="needs a target naming a free-text item"):
        ReviewFile.model_validate(data)


@pytest.mark.parametrize(
    "target",
    ["core_claim", "level_reason[3]", "contested_reason[1]", "badge_reasons.explains_pem[0]", "links[2].reason",
     "studies[pmid:90000100].finding", "early_signals[0]", "subgroups[1]"],
)  # fmt: skip
def test_the_free_text_targets_are_accepted(target):
    ReviewFile.model_validate({"card": SLUG, "verdict": "reject", "findings": [finding(target=target, operation=None)]})


def test_a_record_written_before_the_valve_reads_as_unclassified():
    review = ReviewFile.model_validate(
        {"card": SLUG, "verdict": "reject", "findings": [{"operation": 0, "severity": "must_fix", "problem": "P."}]}
    )
    assert review.findings[0].klass is None and pipeline._review_valve_findings(review) is None
    record = AuditRecord.model_validate(whole("reject"))
    assert record.parts[0].klass is None
    classes = [(p.klass, p.target) for p in record.parts]
    assert pipeline._audit_valve_findings([("first", record, classes)]) is None  # normal path
    assert pipeline._audit_valve_findings([("first", record, classes), ("second", record, classes)]) is None


@pytest.mark.parametrize(
    "record, fragment",
    [
        (whole("reject"), "parts[0] has no `class`"),
        (classed(whole("reject"), "none"), "a reject needs at least one part"),
    ],
)
def test_a_new_audit_record_of_a_correction_round_needs_the_class(corr: Corr, capsys, record, fragment):
    corr.round_to_audits(record, whole())
    assert corr.record_audit() == 1 and fragment in capsys.readouterr().err


def test_a_classified_audit_record_of_a_correction_round_is_recorded(corr: Corr):
    corr.round_to_audits(wording_reject(), whole())
    assert corr.record_audit() == 0


def test_an_audit_part_with_a_wording_class_needs_a_free_text_target(corr: Corr, capsys):
    corr.round_to_audits(whole("reject"), whole())
    corr.write_audit(classed(whole("reject"), "wording", "level"))
    assert corr.record_audit() == 1 and "needs a target naming a free-text item" in capsys.readouterr().err


def test_an_accept_has_no_objecting_part(corr: Corr, capsys):
    corr.round_to_audits(whole(), whole())
    corr.write_audit(classed(whole(), "wording", EARLY))
    assert corr.record_audit() == 1 and "has no objecting part" in capsys.readouterr().err
    (corr.dir / "audit" / f"{SLUG}-C1.invalid-1.yaml").unlink()
    corr.write_audit(classed(whole(), "none"))
    assert corr.record_audit() == 0


# --- V2: the valve at the audit stage ---------------------------------------------------------------------------


def test_the_audit_valve_is_open_for_an_accept_and_a_wording_reject_and_for_two_wording_rejects():
    accept = AuditRecord.model_validate(whole())
    reject = AuditRecord.model_validate(wording_reject())
    other = AuditRecord.model_validate(wording_reject("level_reason[0]"))

    def classes(r: AuditRecord) -> list:
        return [(p.klass, p.target) for p in r.parts]

    found = pipeline._audit_valve_findings([("first", reject, classes(reject)), ("second", accept, classes(accept))])
    assert found is not None and [(f.id, f.target) for f in found] == [("first.parts[0]", EARLY)]
    both = pipeline._audit_valve_findings([("first", reject, classes(reject)), ("second", other, classes(other))])
    assert both is not None and [f.target for f in both] == [EARLY, "level_reason[0]"]


def test_the_audit_valve_is_closed_by_a_decisive_part_an_accept_lower_or_no_reject():
    accept = AuditRecord.model_validate(whole())
    reject = AuditRecord.model_validate(wording_reject())
    decisive = AuditRecord.model_validate(classed(whole("reject"), "decisive"))
    lower = AuditRecord.model_validate(whole("accept_lower"))

    def c(r: AuditRecord) -> list:
        return [(p.klass, p.target) for p in r.parts]

    assert pipeline._audit_valve_findings([("a", reject, c(reject)), ("b", decisive, c(decisive))]) is None
    assert pipeline._audit_valve_findings([("a", decisive, c(decisive)), ("b", accept, c(accept))]) is None
    assert pipeline._audit_valve_findings([("a", reject, c(reject)), ("b", lower, c(lower))]) is None
    assert pipeline._audit_valve_findings([("a", accept, c(accept)), ("b", accept, c(accept))]) is None


def test_a_wording_only_first_reject_does_not_end_the_audits_publish_card_waits_for_the_second(corr: Corr, capsys):
    audit_round(corr, wording_reject(), None)
    assert corr.publish() == 1
    assert "run the second audit before `publish-card`" in capsys.readouterr().err
    assert not corr.card.exists() and not (corr.dir / "publication-report.md").exists()


def test_a_decisive_first_reject_still_ends_the_audits(corr: Corr):
    audit_round(corr, classed(whole("reject"), "decisive"), None)
    draft = corr.draft.read_bytes()
    assert corr.publish() == 0
    corr.assert_held_back("the first audit decided reject; no second audit was run (sequential audits)", draft)


def test_a_wording_valve_with_one_invalid_audit_is_the_normal_hold_back(corr: Corr):
    corr.round_to_audits(wording_reject(), whole())
    (corr.dir / "audit" / f"{SLUG}-C1-second.yaml").write_text("card: [", encoding="utf-8")
    draft = corr.draft.read_bytes()
    assert corr.publish() == 0
    assert not corr.card.exists() and corr.draft.read_bytes() == draft
    assert "Held back: one audit decided reject and the other audit record is missing or invalid" in corr.report()


# --- V4: the guard of the fix -----------------------------------------------------------------------------------


def guard(*operations: dict, targets: set[str] | None = None) -> tuple[str | None, list[str]]:
    return apply_valve(DRAFT, parse_ops(ops_data(*operations)), targets if targets is not None else {EARLY})


def test_the_guard_applies_a_targeted_removal_a_rewording_and_a_study_finding():
    text, problems = guard(
        REMOVE_EARLY,
        REWORD_CONTESTED,
        REWORD_FINDING,
        targets={EARLY, "contested_reason[0]", "studies[pmid:90000100].finding"},
    )
    assert problems == [] and text is not None
    data = yaml.safe_load(text)
    assert data["early_signals"] == [] and data["contested"]["reason"][0]["text"] == CONTESTED_TEXT
    assert "less widget signalling" in data["studies"][0]["finding"] and data["level"] == 2


STUDY = "pmid:90000100"
PARA = {"text": "T.", "sources": [STUDY]}


def update(**set_: object) -> dict:
    return {"op": "update_study", "id": STUDY, "set": set_}


@pytest.mark.parametrize(
    "operation, fragment",
    [
        ({"op": "propose", "target": "level", "value": 1, "reason": [PARA]}, "is propose"),
        ({"op": "remove_link", "to": "x"}, "is remove_link"),
        ({"op": "add_paragraph", "field": "early_signals", **PARA}, "is add_paragraph"),
        (update(role="context"), "sets ['role']"),
        (update(finding="F.", n_patients=21), "sets ['finding', 'n_patients']"),
        (update(case_definition="other"), "sets ['case_definition']"),
        (
            {
                "op": "replace_paragraph",
                "field": "early_signals",
                "index": 0,
                "text": "T.",
                "sources": ["pmid:90000104"],
            },
            "adds no source",
        ),
    ],
)
def test_the_guard_refuses_an_operation_that_is_not_free_text(operation, fragment):
    text, problems = guard(operation, targets={EARLY, "studies[pmid:90000100].finding"})
    assert text is None and any(fragment in p for p in problems), problems


def test_the_guard_applies_a_core_claim_rewording_but_not_a_change_of_its_sources_or_its_removal():
    claim = {"op": "replace_paragraph", "field": "core_claim", "index": 0, "text": "Reworded.", "sources": [STUDY]}
    text, problems = guard(claim, targets={"core_claim"})
    assert problems == [] and text is not None and yaml.safe_load(text)["core_claim"]["text"] == "Reworded."
    _, problems = guard(claim, targets={EARLY})
    assert any("changes core_claim, which no wording finding" in p for p in problems)
    # dropping a cited source is a subset, but sources are structured: refused by the free-text comparison
    base = DRAFT.replace("sources: [pmid:90000100]", "sources: [pmid:90000100, pmid:90000104]", 1)
    assert base != DRAFT
    fewer = parse_ops(ops_data(claim))
    text, problems = apply_valve(base, fewer, {"core_claim"})
    assert text is None and any("more than free text" in p for p in problems), problems
    gone = {"op": "remove_paragraph", "field": "core_claim", "index": 0}
    text, problems = guard(gone, targets={"core_claim"})
    assert text is None and any("core_claim cannot be removed" in p for p in problems)


def test_the_guard_refuses_a_paragraph_no_wording_finding_names():
    text, problems = guard(REWORD_CONTESTED)  # the finding names early_signals[0] only
    assert text is None and "changes contested_reason[0], which no wording finding of this stage names" in problems[0]
    text, problems = guard(REMOVE_EARLY, REMOVE_EARLY)
    assert text is None and "early_signals has no paragraph 0" in problems[0]


def test_the_guard_names_paragraphs_in_the_numbering_of_the_text_before_the_fix():
    first = {"op": "remove_paragraph", "field": "contested.reason", "index": 0}
    second = {
        "op": "replace_paragraph",
        "field": "contested.reason",
        "index": 0,
        "text": "T.",
        "sources": ["pmid:90000104"],
    }
    text, problems = guard(first, second, targets={"contested_reason[0]", "contested_reason[1]"})
    assert problems == [] and text is not None  # the second operation is on what was paragraph 1
    text, problems = guard(first, second, targets={"contested_reason[0]"})
    assert text is None and "contested_reason[1]" in problems[0]


def test_the_guard_refuses_a_file_that_names_a_paper_or_has_no_operation():
    assert guard(REMOVE_EARLY, targets={EARLY})[0] is not None
    _text, problems = apply_valve(DRAFT, parse_ops(ops_data(REMOVE_EARLY, paper="pmid:90000100")), {EARLY})
    assert "names no paper" in problems[0]
    _text, problems = apply_valve(DRAFT, parse_ops({"card": SLUG, "paper": None, "operations": []}), {EARLY})
    assert "at least one operation" in problems[0]


def test_valve_apply_refuses_a_fix_that_fails_the_validator_and_writes_nothing(corr: Corr, capsys):
    audit_round(corr, wording_reject("contested_reason[0]"), whole())
    gone = {"op": "remove_paragraph", "field": "contested.reason", "index": 0}  # the contested mark would lack a reason
    write_valve(corr, "audit", gone)
    assert valve(corr, "valve-apply", "audit") == 1
    assert "cannot be left empty" in capsys.readouterr().err
    assert not (corr.dir / "valve" / f"{SLUG}-audit" / f"{SLUG}.yaml").exists()


def test_valve_apply_refuses_an_untargeted_paragraph_and_a_second_valve_for_the_stage(corr: Corr, capsys):
    audit_round(corr, wording_reject(), whole())
    write_valve(corr, "audit", REWORD_CONTESTED)
    assert valve(corr, "valve-apply", "audit") == 1
    assert "which no wording finding of this stage names" in capsys.readouterr().err
    assert not (corr.dir / "valve" / f"{SLUG}-audit" / f"{SLUG}.yaml").exists()
    write_valve(corr, "audit", REMOVE_EARLY)
    assert valve(corr, "valve-apply", "audit") == 0
    assert valve(corr, "valve-apply", "audit") == 1 and "one valve per stage and attempt" in capsys.readouterr().err


def test_valve_apply_is_refused_when_the_valve_is_not_open(corr: Corr, capsys):
    audit_round(corr, classed(whole("reject"), "decisive"), whole())
    write_valve(corr, "audit", REMOVE_EARLY)
    assert valve(corr, "valve-apply", "audit") == 1 and "the valve is not open" in capsys.readouterr().err
    assert valve(corr, "valve-apply", "card-review") == 1  # the whole-card review accepted: nothing to fix there


# --- V5: the fix check ------------------------------------------------------------------------------------------


def test_the_fix_check_context_holds_the_finding_the_text_before_and_after_and_the_cached_record_paths(corr: Corr):
    audit_round(corr, wording_reject(), whole())
    write_valve(corr, "audit", REMOVE_EARLY)
    assert valve(corr, "valve-apply", "audit") == 0 and valve(corr, "valve-check-plan", "audit") == 0
    text = (corr.dir / "valve-check-context" / f"{SLUG}-audit.md").read_text(encoding="utf-8")
    assert "## Finding first.parts[0]" in text and f"- target: `{EARLY}`" in text
    assert "- before: A fictional small study reported a related change, not yet replicated." in text
    assert "- after: (the paragraph is removed)" in text
    assert "record: `" in text and "90000100.xml" in text  # named by path
    assert "Fictional controlled study of widget signalling." not in text  # no record embedded
    assert "level_reason" not in text and "core_claim" not in text  # nothing else of the card


def test_record_valve_check_validates_the_answers(corr: Corr, capsys):
    audit_round(corr, wording_reject(), whole())
    write_valve(corr, "audit", REMOVE_EARLY)
    assert valve(corr, "valve-apply", "audit") == 0
    assert valve(corr, "record-valve-check", "audit") == 1  # no file
    for ids, fragment in (
        ([], "List should have at least 1 item"),
        (["x"], "no answer for the finding first.parts[0]"),
    ):
        (corr.dir / "valve" / f"{SLUG}-audit-check.json").write_text(
            json.dumps(
                {
                    "card": SLUG,
                    "fixes": [{"finding": i, "resolves": True, "new_claim": False, "reason": "R."} for i in ids],
                }
            ),
            encoding="utf-8",
        )
        assert valve(corr, "record-valve-check", "audit") == 1 and fragment in capsys.readouterr().err
    write_check(corr, "audit", ["first.parts[0]", "first.parts[0]"])
    assert valve(corr, "record-valve-check", "audit") == 1 and "answered twice" in capsys.readouterr().err
    write_check(corr, "audit", ["first.parts[0]"], resolves=False)
    assert valve(corr, "record-valve-check", "audit") == 0 and "FAILED" in corr.env.out[-1]
    write_check(corr, "audit", ["first.parts[0]"])
    assert valve(corr, "record-valve-check", "audit") == 0 and "PASSED" in corr.env.out[-1]


# --- V6, V7: publishing and the trail ---------------------------------------------------------------------------


def test_a_passed_audit_valve_publishes_the_audited_text_with_the_fix_and_keeps_the_trail(corr: Corr):
    audit_round(corr, wording_reject(), whole())
    whole_fix(corr, "audit", "audit", ["first.parts[0]"], REMOVE_EARLY)
    assert corr.publish() == 0
    data = yaml.safe_load(corr.card.read_text(encoding="utf-8"))
    assert data["early_signals"] == [] and len(data["contested"]["reason"]) == 1  # the correction and the fix
    assert data["last_checked"]["by"] == "ai_audit" and not corr.draft.exists()
    assert "published after a wording fix" in corr.report()
    entry = yaml.safe_load((corr.card.parent / "changelog.yaml").read_text(encoding="utf-8"))[-1]
    assert entry["change"] == "First publication at level 2 after correction round 1 and a wording fix"
    names = corr.names()
    assert f"{PUB_DATE}-{SLUG}-C1-valve-audit.yaml" in names and f"{PUB_DATE}-{SLUG}-C1-correction.yaml" in names
    trail = yaml.safe_load((corr.audits / f"{PUB_DATE}-{SLUG}-C1-valve-audit.yaml").read_text(encoding="utf-8"))
    assert trail["stage"] == "audit" and trail["classification"][0]["finding"] == "first.parts[0]"
    assert trail["classification"][0]["target"] == EARLY and trail["operations"] == [REMOVE_EARLY]
    assert trail["check"]["passed"] is True and trail["check"]["fixes"][0]["resolves"] is True
    assert corr.trail()["valve"] == {"audit": {"file": f"{PUB_DATE}-{SLUG}-C1-valve-audit.yaml", "passed": True}}


def test_a_failed_fix_check_holds_the_card_back_naming_the_failed_fix_and_keeps_the_trail(corr: Corr):
    audit_round(
        corr,
        whole("reject") | {"parts": wording_reject()["parts"]},
        whole("reject") | {"parts": wording_reject()["parts"]},
    )
    whole_fix(corr, "audit", "audit", ["first.parts[0]", "second.parts[0]"], REMOVE_EARLY, new_claim=True)
    draft = corr.draft.read_bytes()
    assert corr.publish() == 0
    corr.assert_held_back("the wording fix did not pass its check: first.parts[0]: adds a claim (One line.)", draft)
    assert "second.parts[0]: adds a claim" in corr.report()
    assert f"{PUB_DATE}-{SLUG}-C1-valve-audit.yaml" in corr.names()
    assert corr.trail()["valve"]["audit"]["passed"] is False
    assert pipeline.correction_round_state(_cfg(corr), SLUG)[0] == 1  # the round is used


def _cfg(corr: Corr) -> pipeline.Config:
    return pipeline.Config(
        corr.dir, corr.env.cards, corr.env.drafts, corr.env.cache, SPEC, corr.env.pipeline,
        corr.env.translations, corr.audits,
    )  # fmt: skip


@pytest.mark.parametrize(
    "state, fragment", [("not applied", "valve fix not applied"), ("no check", "valve check missing")]
)
def test_an_unfinished_audit_valve_is_a_refusal_and_the_round_stays_open(corr: Corr, capsys, state, fragment):
    audit_round(corr, wording_reject(), whole())
    before = corr.names()
    if state == "no check":
        write_valve(corr, "audit", REMOVE_EARLY)
        assert valve(corr, "valve-apply", "audit") == 0
    assert corr.publish() == 1 and fragment in capsys.readouterr().err
    assert corr.names() == before and not corr.card.exists()
    assert not (corr.dir / "publication-report.md").exists()


# --- V3: the valve at the review stages -------------------------------------------------------------------------


def test_a_wording_only_correction_review_reject_uses_the_valve_not_a_revised_attempt(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0
    assert write_review(corr, [finding()]) == 0
    assert corr.audit_plan() == 1  # not accepted yet
    assert corr.main("card-review-plan", SLUG, "--round", "C1", "--out", str(corr.dir)) == 1
    path = corr.write_ops(ops_data(REMOVE_EARLY), "-revised")
    assert corr.main("apply", SLUG, str(path), "--round", "C1", "--revised", "--run-dir", str(corr.dir)) == 1
    assert "wording only: it goes through the valve" in capsys.readouterr().err
    whole_fix(corr, "correction-review", "correction-review", ["findings[0]"], REWORD_CONTESTED)
    assert corr.main("card-review-plan", SLUG, "--round", "C1", "--out", str(corr.dir)) == 0
    context = (corr.dir / "card-review-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert CONTESTED_TEXT in context  # the whole-card review reads the fixed text


def test_a_decisive_finding_among_wording_ones_takes_the_normal_path(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0
    assert write_review(corr, [finding(), finding(klass="decisive", target=None)]) == 0
    write_valve(corr, "correction-review", REWORD_CONTESTED)
    assert valve(corr, "valve-apply", "correction-review") == 1 and "the valve is not open" in capsys.readouterr().err
    path = corr.write_ops(ops_data(REMOVE_EARLY), "-revised")  # the revised attempt is allowed
    assert corr.main("apply", SLUG, str(path), "--round", "C1", "--revised", "--run-dir", str(corr.dir)) == 0


def test_the_review_stage_valves_publish_with_both_fixes_and_no_revised_attempt(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0
    assert write_review(corr, [finding()]) == 0
    whole_fix(corr, "correction-review", "correction-review", ["findings[0]"], REWORD_CONTESTED)
    assert corr.main("card-review-plan", SLUG, "--round", "C1", "--out", str(corr.dir)) == 0
    assert write_review(corr, [finding(target="studies[pmid:90000100].finding", operation=None)], card=True) == 0
    whole_fix(corr, "card-review", "card-review", ["findings[0]"], REWORD_FINDING)
    assert corr.audit_plan() == 0
    context = (corr.dir / "audit-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert CONTESTED_TEXT in context and "less widget signalling" in context and "wording fix" not in context
    corr.write_audit(whole())
    corr.write_audit(whole(), second=True)
    assert not (corr.dir / "ops" / f"{SLUG}-rC1-revised.json").exists()
    assert corr.publish() == 0
    data = yaml.safe_load(corr.card.read_text(encoding="utf-8"))
    assert data["contested"]["reason"][0]["text"] == CONTESTED_TEXT and "less widget" in data["studies"][0]["finding"]
    entry = yaml.safe_load((corr.card.parent / "changelog.yaml").read_text(encoding="utf-8"))[-1]
    assert entry["change"].endswith("after correction round 1 and a wording fix")
    for key in ("correction-review", "card-review"):
        assert f"{PUB_DATE}-{SLUG}-C1-valve-{key}.yaml" in corr.names()
    assert set(corr.trail()["valve"]) == {"correction-review", "card-review"}
    assert corr.trail()["review"]["verdict"] == "reject" and corr.trail()["review"]["findings"][0]["class"] == "wording"


def test_a_failed_review_stage_check_holds_the_card_back_and_the_round_is_used(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and write_review(corr, [finding()]) == 0
    whole_fix(corr, "correction-review", "correction-review", ["findings[0]"], REWORD_CONTESTED, resolves=False)
    assert corr.audit_plan() == 1
    draft = corr.draft.read_bytes()
    assert corr.publish() == 0
    corr.assert_held_back("correction rejected in review: the wording fix did not pass its check", draft)
    path = corr.write_ops(ops_data(REMOVE_EARLY), "-revised")
    assert corr.main("apply", SLUG, str(path), "--round", "C1", "--revised", "--run-dir", str(corr.dir)) == 1  # used
    assert pipeline.correction_round_state(_cfg(corr), SLUG)[0] == 1


def test_an_unfinished_review_stage_valve_is_a_refusal(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and write_review(corr, [finding()]) == 0
    assert corr.publish() == 1 and "valve fix not applied" in capsys.readouterr().err
    write_valve(corr, "correction-review", REWORD_CONTESTED)
    assert valve(corr, "valve-apply", "correction-review") == 0
    assert corr.publish() == 1 and "valve check missing" in capsys.readouterr().err
    assert (
        corr.names() == sorted(p.name for p in corr.audits.glob("*.yaml"))
        and f"{PUB_DATE}-{SLUG}-C1-correction.yaml" not in corr.names()
    )


# --- V8: the classification exception of one card ---------------------------------------------------------------


def classification(*first: tuple[str, str | None], second: list | None = None) -> dict:
    def part(c: tuple[str, str | None]) -> dict:
        return {"class": c[0]} | ({"target": c[1]} if c[1] else {})

    return {"card": SLUG, "round": "C1", "first": [part(c) for c in first], "second": second or [{"class": "none"}]}


def write_classification(corr: Corr, data: dict) -> int:
    path = corr.dir / "valve" / f"{SLUG}-classification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return corr.main("record-audit-classification", SLUG, "--round", "C1", "--run-dir", str(corr.dir))


def closed_round(corr: Corr) -> None:
    """A round C1 whose two audit records predate the classification (a reject and an accept), held back and used."""
    audit_round(corr, whole("reject"), whole())
    assert corr.publish() == 0 and not corr.card.exists()


def test_the_exception_is_for_the_named_slug_only(corr: Corr, monkeypatch, capsys):
    closed_round(corr)
    assert pipeline.CLASSIFICATION_EXCEPTION == {"orthostatic-intolerance-cerebral-blood-flow": 1}
    assert write_classification(corr, classification((("wording"), EARLY))) == 1
    assert "no classification exception for fictional-pipeline-card round C1" in capsys.readouterr().err
    write_valve(corr, "audit", REMOVE_EARLY)
    assert valve(corr, "valve-apply", "audit") == 1  # the round is used and this slug has no exception
    assert corr.publish(date=LATER) == 1
    assert not corr.card.exists()


def test_the_exception_lets_a_wording_classification_open_the_audit_valve_on_the_closed_round(corr: Corr, monkeypatch):
    monkeypatch.setattr(pipeline, "CLASSIFICATION_EXCEPTION", {SLUG: 1})
    closed_round(corr)
    before = {p.name: p.read_bytes() for p in corr.audits.glob("*.yaml")}
    assert write_classification(corr, classification(("wording", EARLY))) == 0
    recorded = corr.audits / f"{PUB_DATE}-{SLUG}-C1-classification.yaml"
    assert yaml.safe_load(recorded.read_text(encoding="utf-8"))["first"] == [{"class": "wording", "target": EARLY}]
    assert write_classification(corr, classification(("wording", EARLY))) == 1  # never overwritten
    whole_fix(corr, "audit", "audit", ["first.parts[0]"], REMOVE_EARLY)
    assert corr.publish(date=LATER) == 0
    assert yaml.safe_load(corr.card.read_text(encoding="utf-8"))["early_signals"] == []
    after = {p.name: p.read_bytes() for p in corr.audits.glob("*.yaml")}
    assert {k: v for k, v in after.items() if k in before} == before  # the closed round's records are untouched
    assert f"{LATER}-{SLUG}-C1-valve-audit.yaml" in after and f"{LATER}-{SLUG}-C1-correction.yaml" not in after


def test_a_decisive_classification_is_recorded_and_the_card_stays_held_back(corr: Corr, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "CLASSIFICATION_EXCEPTION", {SLUG: 1})
    closed_round(corr)
    assert write_classification(corr, classification(("decisive", None))) == 0
    write_valve(corr, "audit", REMOVE_EARLY)
    assert valve(corr, "valve-apply", "audit") == 1 and "the valve is not open" in capsys.readouterr().err
    assert corr.publish(date=LATER) == 1 and "the card stays held back" in capsys.readouterr().err
    assert not corr.card.exists() and corr.draft.exists()


def test_the_classification_must_fit_the_records(corr: Corr, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "CLASSIFICATION_EXCEPTION", {SLUG: 1})
    closed_round(corr)
    assert write_classification(corr, classification(("wording", "level"))) == 1  # not a free-text target
    assert write_classification(corr, classification(("wording", EARLY), ("none", None))) == 1  # one part too many
    assert write_classification(corr, classification(("none", None))) == 1  # a reject needs an objecting part
    err = capsys.readouterr().err
    assert "free-text item" in err and "one class for each of the 1 part(s)" in err and "at least one part" in err
    assert not list(corr.audits.glob("*classification*"))


def test_a_classification_is_not_read_for_another_round_or_slug(corr: Corr, monkeypatch):
    monkeypatch.setattr(pipeline, "CLASSIFICATION_EXCEPTION", {SLUG: 1})
    closed_round(corr)
    assert write_classification(corr, classification(("wording", EARLY))) == 0
    cfg = _cfg(corr)
    assert pipeline._exception_classes(cfg, SLUG, 1) is not None
    assert pipeline._exception_classes(cfg, SLUG, 2) is None
    assert pipeline._exception_classes(cfg, "another-card", 1) is None


# --- gaps found in the evaluation of the valve ------------------------------------------------------------------


def _with(change):
    """An ``apply_operations`` that applies the operations as usual and then makes ``change`` to the data."""
    real = pipeline.apply_operations

    def apply(text, ops, **kw):
        data = yaml.safe_load(real(text, ops, **kw))
        change(data)
        return yaml.safe_dump(data, sort_keys=False)

    return apply


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(level=3),
        lambda d: d["studies"][0].update(n_patients=21),
        lambda d: d["studies"][0].update(role="contradicts"),
        lambda d: d["badges"]["explains_pem"].update(value=not d["badges"]["explains_pem"]["value"]),
        lambda d: d.update(layer="trigger"),
    ],
)
def test_the_guard_refuses_by_comparison_when_a_permitted_operation_changes_a_structured_field(change, monkeypatch):
    """The operation is a permitted kind on a named target, so only the free-text-blanked comparison can refuse it."""
    assert guard(REMOVE_EARLY)[0] is not None  # the same ops file passes when the code leaves the rest alone
    monkeypatch.setattr(pipeline, "apply_operations", _with(change))
    text, problems = guard(REMOVE_EARLY)
    assert text is None
    assert problems == ["the fix changes more than free text (a structured field differs); nothing applied"]


def two_parts(decision: str, first: tuple[str | None, str | None], second: tuple[str | None, str | None]):
    """A valid audit record with two objecting parts and their (class, target); parts that carry no class are None."""
    data = whole(decision)
    data["parts"] = [data["parts"][0], data["parts"][0]]
    record = AuditRecord.model_validate(data)
    return record, [first, second]


def test_a_reject_that_mixes_a_wording_part_with_a_decisive_part_keeps_the_valve_closed():
    accept = AuditRecord.model_validate(whole())
    wording = (("wording", EARLY), ("decisive", None))
    mixed, classes = two_parts("reject", *wording)
    assert pipeline._audit_valve_findings([("a", mixed, classes), ("b", accept, [(None, None)])]) is None
    mixed, classes = two_parts("reject", *reversed(wording))
    assert pipeline._audit_valve_findings([("a", accept, [(None, None)]), ("b", mixed, classes)]) is None
    only, classes = two_parts("reject", ("wording", EARLY), ("wording", "level_reason[0]"))
    found = pipeline._audit_valve_findings([("a", only, classes), ("b", accept, [(None, None)])])
    assert found is not None and len(found) == 2  # the same record with two wording parts keeps it open


def test_a_reject_that_mixes_a_wording_part_with_an_unclassified_part_keeps_the_valve_closed():
    accept = AuditRecord.model_validate(whole())
    mixed, classes = two_parts("reject", ("wording", EARLY), (None, None))
    assert pipeline._audit_valve_findings([("a", mixed, classes), ("b", accept, [(None, None)])]) is None
    mixed, classes = two_parts("reject", (None, None), ("wording", EARLY))
    assert pipeline._audit_valve_findings([("a", accept, [(None, None)]), ("b", mixed, classes)]) is None


def test_a_valve_text_changed_after_valve_apply_holds_the_audit_stage_card_back(corr: Corr):
    audit_round(corr, wording_reject(), whole())
    whole_fix(corr, "audit", "audit", ["first.parts[0]"], REMOVE_EARLY)
    stored = pipeline.Config.valve_text_path(_cfg(corr), SLUG, "audit")
    stored.write_text(stored.read_text(encoding="utf-8").replace("lower", "higher", 1), encoding="utf-8")
    draft = corr.draft.read_bytes()
    assert corr.publish() == 0
    corr.assert_held_back("correction failed checks: the wording fix does not match its operations", draft)


def test_a_valve_text_changed_after_valve_apply_holds_the_review_stage_card_back(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and write_review(corr, [finding()]) == 0
    whole_fix(corr, "correction-review", "correction-review", ["findings[0]"], REWORD_CONTESTED)
    stored = _cfg(corr).valve_text_path(SLUG, "correction-review")
    text = stored.read_text(encoding="utf-8")
    assert CONTESTED_TEXT in text
    stored.write_text(text.replace("no clear difference", "a clear difference"), encoding="utf-8")
    assert corr.main("card-review-plan", SLUG, "--round", "C1", "--out", str(corr.dir)) == 0
    assert write_review(corr, [], card=True, verdict="accept") == 0
    assert corr.audit_plan() == 0
    corr.write_audit(whole())
    corr.write_audit(whole(), second=True)
    draft = corr.draft.read_bytes()
    assert corr.publish() == 0
    corr.assert_held_back("correction failed checks: a wording fix does not match its operations", draft)


def test_valve_apply_fails_a_number_that_no_cited_record_has_and_passes_one_that_it_has(corr: Corr, capsys):
    """C10 is an error for newly applied text (the contested text of this study says 100 patients, as its record)."""
    bad = REWORD_CONTESTED | {"text": "A fictional study of 7777 patients found no clear difference."}
    assert corr.plan() == 0 and corr.apply() == 0 and write_review(corr, [finding()]) == 0
    write_valve(corr, "correction-review", bad)
    assert valve(corr, "valve-apply", "correction-review") == 1
    err = capsys.readouterr().err
    assert "C10" in err and "the number 7777" in err
    assert not (corr.dir / "valve" / f"{SLUG}-correction-review" / f"{SLUG}.yaml").exists()
    write_valve(corr, "correction-review", REWORD_CONTESTED)
    assert valve(corr, "valve-apply", "correction-review") == 0
