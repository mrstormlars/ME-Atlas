"""Tests for the correction path of a held-back draft (correction-plan, apply/record-review/audit-plan/record-audit
with --round C1, publish-card --round C1), the B1 console fix, the B2 order-independent reason and the B3 format
retry of an invalid audit record.

Fictional card, papers and agent output (tests/fixtures/pipeline), temporary folders only. No test touches the
network, an AI or git.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml
from test_audit import CITED
from test_pipeline import SLUG, Env
from test_publish_card import PUB_DATE, Pub, whole

from me_atlas import cards, pipeline
from me_atlas.operations import parse_ops

LATER = "2026-11-20"
CONTESTED_LAST = {"op": "remove_paragraph", "field": "contested.reason", "index": 1}


def ops_data(*operations: dict, **over) -> dict:
    return {"card": SLUG, "paper": None, "operations": list(operations or [CONTESTED_LAST])} | over


class Corr:
    """A held-back draft (two rejects, copied to audits/) and a correction folder DIR beside it."""

    def __init__(self, pub: Pub, tmp: Path):
        self.pub = pub
        self.env = pub.env
        self.dir = tmp / "correction"
        self.audits = pub.audits
        self.draft = pub.draft
        self.card = pub.card

    def hold_back(self, first: str = "reject", second: str = "reject") -> None:
        """The first publication run: the draft stays held back and its audit records are copied into audits/."""
        self.pub.audits_of_card(whole(first), whole(second))
        assert self.pub.publish() == 0
        assert not self.card.exists() and self.draft.exists()

    def main(self, *argv: str) -> int:
        return pipeline.main([*argv, *self.env.dir_args], fulltext=_loader(), out=self.env.out.append)

    def plan(self) -> int:
        return self.main("correction-plan", SLUG, "--out", str(self.dir))

    def write_ops(self, data: dict | None = None, attempt: str = "") -> Path:
        path = self.dir / "ops" / f"{SLUG}-rC1{attempt}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ops_data() if data is None else data), encoding="utf-8")
        return path

    def apply(self, data: dict | None = None) -> int:
        path = self.write_ops(data)
        return self.main("apply", SLUG, str(path), "--round", "C1", "--run-dir", str(self.dir))

    def review(self, verdict: str = "accept") -> int:
        path = self.dir / "review" / f"{SLUG}-rC1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        findings = [] if verdict == "accept" else [{"operation": 0, "severity": "must_fix", "problem": "A problem."}]
        path.write_text(json.dumps({"card": SLUG, "verdict": verdict, "findings": findings}), encoding="utf-8")
        return self.main("record-review", SLUG, "--round", "C1", "--run-dir", str(self.dir))

    def card_review(self, verdict: str = "accept", revised: bool = False) -> int:
        """The whole-card review of the attempt: the card-reviewer's file, then record-review --card-review."""
        tag = "C1-revised" if revised else "C1"
        path = self.dir / "review" / f"{SLUG}-card-{tag}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        findings = [] if verdict == "accept" else [{"operation": None, "severity": "must_fix", "problem": "A problem."}]
        path.write_text(
            json.dumps({"card": SLUG, "paper": None, "verdict": verdict, "findings": findings}), encoding="utf-8"
        )
        more = ["--revised"] if revised else []
        return self.main("record-review", SLUG, "--card-review", "--round", "C1", *more, "--run-dir", str(self.dir))

    def audit_plan(self) -> int:
        return self.main("audit-plan", "--card", SLUG, "--round", "C1", "--out", str(self.dir))

    def write_audit(self, data: dict, second: bool = False) -> Path:
        path = self.dir / "audit" / f"{SLUG}-C1{'-second' if second else ''}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def record_audit(self, second: bool = False) -> int:
        path = self.dir / "audit" / f"{SLUG}-C1{'-second' if second else ''}.yaml"
        return self.main("record-audit", "--card", SLUG, "--round", "C1", "--file", str(path), "--out", str(self.dir))

    def round_to_audits(self, first: dict | None = None, second: dict | None = None, **ops_kw) -> None:
        """plan, ops, apply, review, audit-plan and the two audit records of a good round."""
        assert self.plan() == 0
        assert self.apply(ops_kw.get("data")) == 0
        assert self.review() == 0
        assert self.card_review() == 0
        assert self.audit_plan() == 0
        self.write_audit(first if first is not None else whole())
        self.write_audit(second if second is not None else whole(), second=True)

    def publish(self, *extra: str, date: str = PUB_DATE) -> int:
        return self.main("publish-card", SLUG, "--run-dir", str(self.dir), "--round", "C1", "--date", date, *extra)

    def report(self) -> str:
        return (self.dir / "publication-report.md").read_text(encoding="utf-8")

    def names(self) -> list[str]:
        return sorted(p.name for p in self.audits.glob("*.yaml")) if self.audits.is_dir() else []

    def trail(self, date: str = PUB_DATE) -> dict:
        return yaml.safe_load((self.audits / f"{date}-{SLUG}-C1-correction.yaml").read_text(encoding="utf-8"))

    def assert_held_back(self, reason: str, draft_bytes: bytes) -> None:
        assert self.draft.read_bytes() == draft_bytes
        assert not self.card.exists()
        assert f"Held back: {reason}" in self.report(), self.report()


def _loader():
    from test_pipeline import fulltext_loader

    return fulltext_loader()


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


# --- A1: the new operations are for a correction round only ---------------------------------------------


@pytest.mark.parametrize(
    "operation, name",
    [
        ({"op": "remove_paragraph", "field": "early_signals", "index": 0}, "remove_paragraph"),
        ({"op": "update_study", "id": "pmid:90000100", "set": {"year": 2019}}, "update_study"),
        ({"op": "remove_link", "to": "somewhere"}, "remove_link"),
    ],
)
def test_a_normal_round_rejects_a_correction_only_operation_and_names_it(env: Env, operation, name, capsys):
    env.prepare()
    assert env.classify() == 0
    path = env.run / "ops" / f"{SLUG}-90000101-r1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"card": SLUG, "paper": "pmid:90000101", "operations": [operation]}), encoding="utf-8")
    assert env.cli("apply", SLUG, str(path), "--round", "1") == 1
    assert f"operations[0] is {name}: only a correction round" in "\n".join(env.out)
    checks = json.loads((env.run / "checks" / f"{SLUG}-90000101-r1.json").read_text(encoding="utf-8"))
    assert checks["passed"] is False and checks["applied"] is None


# --- A2: what a correction ops file may hold --------------------------------------------------------------

STUDY = json.loads(
    (Path(__file__).parent / "fixtures" / "pipeline" / "agent" / "ops_add_study.json").read_text(encoding="utf-8")
)["operations"][0]
PARA = {"text": "A fictional paragraph.", "sources": [CITED]}


def problems(*operations: dict, level: int = 2, **over) -> list[str]:
    return pipeline.correction_ops_problems(parse_ops(ops_data(*operations, **over)), level)


def level(value: int) -> dict:
    return {"op": "propose", "target": "level", "value": value, "reason": [PARA]}


def test_a_correction_names_no_paper():
    assert any("names no paper" in p for p in problems(CONTESTED_LAST, paper="pmid:90000101"))


def test_a_correction_needs_at_least_one_operation():
    empty = parse_ops({"card": SLUG, "paper": None, "operations": []})
    assert any("at least one operation" in p for p in pipeline.correction_ops_problems(empty, 2))


def test_a_correction_may_not_add_a_study_or_a_paragraph():
    study = parse_ops({"card": SLUG, "paper": "pmid:90000101", "operations": [STUDY]})
    found = pipeline.correction_ops_problems(study, 2)
    assert any("operations[0] is add_study" in p for p in found) and any("names no paper" in p for p in found)
    para = {"op": "add_paragraph", "field": "early_signals", **PARA}
    assert any("operations[0] is add_paragraph" in p for p in problems(para))


@pytest.mark.parametrize("value", [2, 3])
def test_a_proposed_level_must_be_lower_than_the_drafts(value):
    assert any("may only lower the level" in p for p in problems(level(value)))


def test_a_lower_level_a_contested_proposal_and_a_badge_set_to_false_are_allowed():
    contested = {"op": "propose", "target": "contested", "value": [2], "reason": [PARA]}
    badge = {"op": "propose", "target": "explains_pem", "value": False}
    removed = {"op": "propose", "target": "contested", "value": None}
    replace = {"op": "replace_paragraph", "field": "early_signals", "index": 0, **PARA}
    update = {"op": "update_study", "id": "pmid:90000100", "set": {"year": 2019}}
    link = {"op": "remove_link", "to": "x"}
    assert problems(level(1), contested, badge, removed, replace, CONTESTED_LAST, update, link) == []


def test_a_badge_may_only_be_set_to_false():
    found = problems({"op": "propose", "target": "diagnostic_marker", "value": True, "reason": [PARA]})
    assert any("may only set a badge to false" in p for p in found)


# --- A3: correction-plan ----------------------------------------------------------------------------------


def test_correction_plan_writes_the_context_for_the_drafter(corr: Corr):
    assert corr.plan() == 0
    text = (corr.dir / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert corr.draft.read_text(encoding="utf-8").rstrip("\n") in text  # the draft as it stands, comments included
    for name in (f"{PUB_DATE}-{SLUG}.yaml", f"{PUB_DATE}-{SLUG}-second.yaml"):
        assert f"### {name}" in text
    assert "- decision: reject" in text and "reasons_summary: The cited controlled study supports" in text
    assert "would_change: A failed replication." in text and "Rubric clause:" in text
    assert "### Record: pmid:90000100" in text and "Not truncated" in text  # a carrier in full
    assert "Not cached: pmid:90000104" in text  # named, not hidden
    assert "## 5. The inclusion rule" in text and "## 6. The rubric" in text
    assert "never by adding a fact" in text and "`remove_link`" in text and "may only lower the level" in text
    assert corr.draft.read_bytes() == corr.pub.draft_bytes


def test_correction_plan_refuses_when_the_card_is_already_published(corr: Corr):
    corr.card.write_text("# a card\n", encoding="utf-8")
    assert corr.plan() == 1
    assert not corr.dir.exists()


def test_correction_plan_refuses_without_a_draft(corr: Corr):
    corr.draft.unlink()
    assert corr.plan() == 1
    assert not corr.dir.exists()


def test_correction_plan_refuses_without_an_audit_record_and_a_longer_slug_is_no_match(pub: Pub, tmp_path: Path):
    c = Corr(pub, tmp_path)
    assert c.plan() == 1 and not c.dir.exists()  # no audits/ at all
    pub.audits.mkdir()
    other = f"{PUB_DATE}-{SLUG}-extra.yaml"  # the record of a card whose slug starts with this one
    (pub.audits / other).write_text(yaml.safe_dump(whole() | {"card": f"{SLUG}-extra"}), encoding="utf-8")
    assert c.plan() == 1 and not c.dir.exists()
    (pub.audits / f"{PUB_DATE}-{SLUG}-90000101.yaml").write_text("card: x\n", encoding="utf-8")  # a pair record
    assert c.plan() == 1 and not c.dir.exists()


def test_correction_plan_refuses_a_round_beyond_the_limit(corr: Corr):
    assert pipeline.MAX_CORRECTION_ROUNDS == 1
    (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction.yaml").write_text(f"card: {SLUG}\n", encoding="utf-8")
    assert corr.plan() == 1
    assert not corr.dir.exists()


# --- A4: apply --round C1 ---------------------------------------------------------------------------------


def test_apply_applies_to_the_draft_and_writes_the_round_files(corr: Corr):
    assert corr.apply() == 0
    checks = json.loads((corr.dir / "checks" / f"{SLUG}-rC1.json").read_text(encoding="utf-8"))
    assert checks["passed"] is True and checks["round"] == "C1" and checks["attempt"] == 1
    applied = corr.dir / "applied" / f"{SLUG}-rC1"
    new = (applied / f"{SLUG}.yaml").read_text(encoding="utf-8")
    assert len(yaml.safe_load(new)["contested"]["reason"]) == 1
    assert (applied / "changes.diff").read_text(encoding="utf-8").startswith("---")
    assert corr.draft.read_bytes() == corr.pub.draft_bytes


@pytest.mark.parametrize(
    "data, fragment",
    [
        (ops_data(paper="pmid:90000101"), "names no paper"),
        (ops_data(*[]) | {"operations": []}, "at least one operation"),
        (ops_data(STUDY, paper="pmid:90000101"), "operations[0] is add_study"),
        (ops_data(level(2)), "may only lower the level"),
        (ops_data({"op": "propose", "target": "explains_pem", "value": True, "reason": [PARA]}), "badge to false"),
        (
            ops_data({"op": "update_study", "id": "pmid:90000100", "set": {"year": 2020}}),
            "the correction changes nothing",
        ),
        (ops_data({"op": "remove_link", "to": "nowhere"}), "no link to 'nowhere'"),
    ],
)
def test_apply_enforces_a2_and_a_correction_that_changes_nothing_fails(corr: Corr, data, fragment, capsys):
    assert corr.apply(data) == 1
    checks = json.loads((corr.dir / "checks" / f"{SLUG}-rC1.json").read_text(encoding="utf-8"))
    assert checks["passed"] is False and fragment in "; ".join(checks["ops_errors"])
    assert not (corr.dir / "applied" / f"{SLUG}-rC1" / f"{SLUG}.yaml").exists()


def test_apply_allows_a_second_attempt_after_a_failed_first_and_keeps_the_first(corr: Corr):
    bad = ops_data({"op": "remove_link", "to": "nowhere"})
    assert corr.apply(bad) == 1
    assert corr.apply(ops_data()) == 0
    names = sorted(p.name for p in (corr.dir / "ops").iterdir()) + sorted(
        p.name for p in (corr.dir / "checks").iterdir()
    )
    assert names == [
        f"{SLUG}-rC1-attempt1.json",
        f"{SLUG}-rC1.json",
        f"{SLUG}-rC1-attempt1.json",
        f"{SLUG}-rC1.json",
    ]
    first = json.loads((corr.dir / "checks" / f"{SLUG}-rC1-attempt1.json").read_text(encoding="utf-8"))
    assert first["passed"] is False and first["attempt"] == 1
    assert json.loads((corr.dir / "ops" / f"{SLUG}-rC1-attempt1.json").read_text(encoding="utf-8")) == bad
    second = json.loads((corr.dir / "checks" / f"{SLUG}-rC1.json").read_text(encoding="utf-8"))
    assert second["passed"] is True and second["attempt"] == 2


def test_apply_refuses_a_third_attempt_and_an_apply_after_a_passed_attempt(corr: Corr, capsys):
    bad = ops_data({"op": "remove_link", "to": "nowhere"})
    assert corr.apply(bad) == 1 and corr.apply(bad) == 1
    before = (corr.dir / "checks" / f"{SLUG}-rC1.json").read_bytes()
    assert corr.apply(ops_data()) == 1
    assert "both attempts" in capsys.readouterr().err
    assert (corr.dir / "checks" / f"{SLUG}-rC1.json").read_bytes() == before


def test_apply_after_a_passed_attempt_is_refused(corr: Corr, capsys):
    assert corr.apply() == 0
    before = (corr.dir / "checks" / f"{SLUG}-rC1.json").read_bytes()
    assert corr.apply() == 1
    assert "passed its checks" in capsys.readouterr().err
    assert (corr.dir / "checks" / f"{SLUG}-rC1.json").read_bytes() == before
    assert not (corr.dir / "checks" / f"{SLUG}-rC1-attempt1.json").exists()


def test_a_second_attempt_leaves_no_applied_text_of_the_first(corr: Corr):
    # The first attempt applies but fails the validator (V14: TODO in reader text); the second fails earlier.
    todo = ops_data(
        {"op": "replace_paragraph", "field": "early_signals", "index": 0, "text": "TODO: verify", "sources": [CITED]}
    )
    assert corr.apply(todo) == 1
    assert (corr.dir / "applied" / f"{SLUG}-rC1" / f"{SLUG}.yaml").is_file()
    assert corr.apply(ops_data({"op": "remove_link", "to": "nowhere"})) == 1
    assert not (corr.dir / "applied" / f"{SLUG}-rC1").exists()


def test_apply_refuses_a_second_correction_round_beyond_the_limit(corr: Corr, capsys):
    (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction.yaml").write_text(f"card: {SLUG}\n", encoding="utf-8")
    assert corr.apply() == 1
    assert "correction round C1 is not allowed" in capsys.readouterr().err


def test_apply_round_c2_is_not_the_next_round(corr: Corr, capsys):
    path = corr.write_ops()
    assert corr.main("apply", SLUG, str(path), "--round", "C2", "--run-dir", str(corr.dir)) == 1
    assert "not allowed" in capsys.readouterr().err


# --- A5, A6: review and the audit context ---------------------------------------------------------------


def test_record_review_validates_the_round_c1_review(corr: Corr):
    assert corr.apply() == 0
    assert corr.review() == 0
    assert "review recorded: accept, 0 finding(s)" in corr.env.out[-1]
    path = corr.dir / "review" / f"{SLUG}-rC1.json"
    path.write_text(
        json.dumps(
            {"card": SLUG, "verdict": "accept", "findings": [{"operation": 5, "severity": "advisory", "problem": "x"}]}
        ),
        encoding="utf-8",
    )
    assert corr.main("record-review", SLUG, "--round", "C1", "--run-dir", str(corr.dir)) == 1  # operation out of range


def test_the_audit_context_equals_the_first_publication_context_of_the_corrected_text(corr: Corr, tmp_path: Path):
    assert corr.apply() == 0 and corr.review() == 0 and corr.card_review() == 0 and corr.audit_plan() == 0
    context = (corr.dir / "audit-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    corrected = (corr.dir / "applied" / f"{SLUG}-rC1" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    # The same text given to the first-publication function (with empty audits/) gives the same file, byte for byte.
    other_drafts = tmp_path / "other-drafts"
    other_drafts.mkdir()
    (other_drafts / f"{SLUG}.yaml").write_text(corrected, encoding="utf-8", newline="\n")
    out = tmp_path / "first"
    args = ["audit-plan", "--card", SLUG, "--out", str(out), *corr.env.dir_args, "--drafts-dir", str(other_drafts)]
    assert (
        pipeline.main([*args, "--audits-dir", str(tmp_path / "no-audits")], fulltext=_loader(), out=lambda _l: None)
        == 0
    )
    first = (out / "audit-context" / f"{SLUG}.md").read_text(encoding="utf-8")
    # The only difference allowed is the path of the card file shown in the heading of section 2.
    assert context.replace(f"{corr.env.drafts}", f"{other_drafts}") == first
    lowered = context.lower()
    for word in ("-rc1", "round c", "applied/", "correction round", "audits/", "attempt"):
        assert word not in lowered
    for marker in ("# a comment between two paragraphs", "# a comment inside a badge"):
        assert marker not in context  # comments are stripped


def test_the_audit_context_is_refused_unless_the_checks_passed_and_the_review_accepts(corr: Corr, capsys):
    assert corr.audit_plan() == 1  # no checks at all
    assert corr.apply(ops_data({"op": "remove_link", "to": "nowhere"})) == 1
    assert corr.audit_plan() == 1 and "did not pass its checks" in capsys.readouterr().err
    assert corr.apply(ops_data()) == 0
    assert corr.audit_plan() == 1 and "no valid review" in capsys.readouterr().err  # no review yet
    assert corr.review("reject") == 0
    assert corr.audit_plan() == 1 and "reviewer rejected" in capsys.readouterr().err
    assert not (corr.dir / "audit-context").exists()


# --- A7: audit records ------------------------------------------------------------------------------------


def test_round_c_audit_records_are_validated_and_accept_lower_must_be_below_the_corrected_level(corr: Corr, capsys):
    assert corr.apply() == 0 and corr.review() == 0 and corr.card_review() == 0 and corr.audit_plan() == 0
    corr.write_audit(whole())
    assert corr.record_audit() == 0
    corr.write_audit(whole("accept_lower", accepted_level=2), second=True)  # the corrected card is at level 2
    assert corr.record_audit(second=True) == 1
    assert "accepted_level 2 must be lower than the level 2" in capsys.readouterr().err
    corr.write_audit(whole("accept_lower", accepted_level=1), second=True)  # a format retry may not change the answer
    assert corr.record_audit(second=True) == 1
    assert "a format retry cannot change the answer" in capsys.readouterr().err


def test_a_correction_audit_for_a_pair_is_refused(corr: Corr, capsys):
    assert corr.main("record-audit", SLUG, "90000101", "--round", "C1", "--run-dir", str(corr.dir)) == 1
    assert "whole card only" in capsys.readouterr().err


# --- A8: publish-card --round C1 --------------------------------------------------------------------------


def test_publish_after_a_correction_publishes_the_corrected_text_and_writes_the_trail(corr: Corr):
    corr.round_to_audits()
    before = corr.draft.read_bytes()
    assert corr.publish() == 0
    text = corr.card.read_text(encoding="utf-8")
    assert not corr.draft.exists()
    data = yaml.safe_load(text)
    assert data["last_checked"] == {"date": dt.date(2026, 11, 14), "by": "ai_audit"}
    assert len(data["contested"]["reason"]) == 1 and data["level"] == 2
    applied = (corr.dir / "applied" / f"{SLUG}-rC1" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    assert text.replace("date: 2026-11-14", "date: 2026-10-01").replace("by: ai_audit", "by: ai_pair") == applied
    assert not cards.validate_card_file(corr.card)
    [entry] = yaml.safe_load(corr.pub.log.read_text(encoding="utf-8"))
    assert entry == {
        "date": dt.date(2026, 11, 14),
        "card": SLUG,
        "change": "First publication at level 2 after correction round 1",
        "reason": "The cited controlled study supports the proposed level.",
        "sources": [CITED],
        "tier": 2,
        "decided_by": "ai_audit",
    }
    assert not cards.validate_changelog_file(corr.pub.log, today=dt.date(2026, 11, 14))
    assert "Outcome: published at level 2" in corr.report() and "after correction round 1" in corr.report()
    # The valid audit records and the trail are copied; the first publication's records are untouched.
    assert corr.names() == [
        f"{PUB_DATE}-{SLUG}-C1-correction.yaml",
        f"{PUB_DATE}-{SLUG}-C1-second.yaml",
        f"{PUB_DATE}-{SLUG}-C1.yaml",
        f"{PUB_DATE}-{SLUG}-second.yaml",
        f"{PUB_DATE}-{SLUG}.yaml",
    ]
    trail = corr.trail()
    keys = ["card", "round", "answered", "draft_sha256", "operations", "checks", "review", "card_review", "audits_run"]
    assert list(trail) == keys
    assert trail["card_review"] == {"verdict": "accept", "findings": []}
    assert trail["audits_run"] == [f"{PUB_DATE}-{SLUG}-C1.yaml", f"{PUB_DATE}-{SLUG}-C1-second.yaml"]
    assert trail["card"] == SLUG and trail["round"] == 1
    assert trail["answered"] == [f"{PUB_DATE}-{SLUG}-second.yaml", f"{PUB_DATE}-{SLUG}.yaml"]
    assert trail["draft_sha256"] == hashlib.sha256(before).hexdigest()
    assert trail["operations"] == [CONTESTED_LAST]
    assert trail["checks"] == {"passed": True, "errors": []}
    assert trail["review"] == {"verdict": "accept", "findings": []}


def test_a_dry_run_after_a_correction_writes_only_the_report(corr: Corr):
    corr.round_to_audits()
    before = {p for p in corr.env.root.rglob("*") if p.is_file()}
    assert corr.publish("--dry-run") == 0
    assert {p for p in corr.env.root.rglob("*") if p.is_file()} - before == {corr.dir / "publication-report.md"}
    assert corr.draft.read_bytes() == corr.pub.draft_bytes and not corr.card.exists()


def held(corr: Corr, reason: str, names: list[str]) -> None:
    corr.assert_held_back(reason, corr.pub.draft_bytes)
    assert not corr.pub.log.exists()
    assert corr.names() == sorted(names)
    trail = corr.trail()
    assert trail["round"] == 1  # the round counts even when it failed


BASE = [f"{PUB_DATE}-{SLUG}-second.yaml", f"{PUB_DATE}-{SLUG}.yaml"]
BOTH = [f"{PUB_DATE}-{SLUG}-C1-second.yaml", f"{PUB_DATE}-{SLUG}-C1.yaml"]
TRAIL = [f"{PUB_DATE}-{SLUG}-C1-correction.yaml"]


def test_a_reject_after_a_correction_holds_the_card_back_and_names_the_last_round(corr: Corr):
    corr.round_to_audits(whole("reject"), whole("reject"))
    assert corr.publish() == 0
    held(corr, "both audits decided reject", BASE + BOTH + TRAIL)
    assert "Correction rounds used: 1 of 1; the card stays held back and is listed for the founder." in corr.report()
    assert corr.trail()["checks"]["passed"] is True


def test_audits_that_differ_after_a_correction_hold_the_card_back(corr: Corr):
    corr.round_to_audits(whole("accept"), whole("reject"))
    assert corr.publish() == 0
    held(corr, "the two audits differ: one decided accept, the other reject", BASE + BOTH + TRAIL)


def test_two_agreeing_accept_lower_after_a_correction_hold_the_card_back_with_no_round_l(corr: Corr):
    corr.round_to_audits(whole("accept_lower", accepted_level=1), whole("accept_lower", accepted_level=1))
    assert corr.publish() == 0
    held(corr, "the audits of the corrected draft agree on accept_lower (level 1)", BASE + BOTH + TRAIL)
    assert "no further redraft" in corr.report()


def test_a_review_reject_holds_the_card_back_and_the_trail_records_the_finding(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review("reject") == 0
    assert corr.publish() == 0
    held(corr, "correction rejected in review", BASE + TRAIL)
    assert corr.trail()["review"] == {
        "verdict": "reject",
        "findings": [{"operation": 0, "severity": "must_fix", "problem": "A problem.", "fix": None}],
    }


def test_failed_checks_hold_the_card_back_and_the_trail_records_the_error_lines(corr: Corr):
    assert corr.plan() == 0
    assert corr.apply(ops_data({"op": "remove_link", "to": "nowhere"})) == 1
    assert corr.publish() == 0
    held(corr, "correction failed checks: ", BASE + TRAIL)
    trail = corr.trail()
    assert trail["checks"]["passed"] is False and any("no link to 'nowhere'" in e for e in trail["checks"]["errors"])
    assert trail["review"] == {"verdict": None, "findings": []}
    assert trail["operations"] == [{"op": "remove_link", "to": "nowhere"}]


def test_a_missing_review_holds_the_card_back(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0
    assert corr.publish() == 0
    held(corr, "correction rejected in review: no review was recorded", BASE + TRAIL)


def test_a_tampered_applied_text_holds_the_card_back(corr: Corr):
    corr.round_to_audits()
    applied = corr.dir / "applied" / f"{SLUG}-rC1" / f"{SLUG}.yaml"
    applied.write_text(
        applied.read_text(encoding="utf-8").replace("level: 2", "level: 0"), encoding="utf-8", newline="\n"
    )
    assert corr.publish() == 0
    held(corr, "correction failed checks: its applied text does not match its operations", BASE + BOTH + TRAIL)


def test_tampered_operations_hold_the_card_back_by_the_a2_rules_even_when_the_checks_say_passed(corr: Corr):
    corr.round_to_audits()
    corr.write_ops(ops_data(level(2)))  # not lower than the draft: A2 is checked again here
    assert corr.publish() == 0
    held(corr, "correction failed checks: operations[0] proposes level 2", BASE + BOTH + TRAIL)


def test_ops_changed_after_the_apply_do_not_match_the_applied_text(corr: Corr):
    corr.round_to_audits()
    corr.write_ops(ops_data({"op": "remove_paragraph", "field": "early_signals", "index": 0}))
    assert corr.publish() == 0
    held(corr, "correction failed checks: its applied text does not match its operations", BASE + BOTH + TRAIL)


def test_a_missing_second_audit_holds_the_card_back(corr: Corr):
    corr.round_to_audits()
    (corr.dir / "audit" / f"{SLUG}-C1-second.yaml").unlink()
    assert corr.publish() == 0
    held(corr, f"no valid second audit: no audit record {SLUG}-C1-second.yaml", BASE + BOTH[1:] + TRAIL)


def test_there_is_nothing_to_publish_when_no_correction_was_recorded(corr: Corr, capsys):
    assert corr.publish() == 1
    assert "no correction recorded" in capsys.readouterr().err
    assert corr.names() == BASE and not (corr.dir / "publication-report.md").exists()


def test_publish_after_a_correction_refuses_an_unknown_round(corr: Corr, capsys):
    corr.round_to_audits()
    assert corr.main("publish-card", SLUG, "--run-dir", str(corr.dir), "--round", "C2", "--date", PUB_DATE) == 1
    assert "not allowed" in capsys.readouterr().err
    assert corr.main("publish-card", SLUG, "--run-dir", str(corr.dir), "--round", "L", "--date", PUB_DATE) == 1
    assert corr.names() == BASE


def test_first_publication_and_correction_files_of_one_date_coexist(corr: Corr):
    corr.round_to_audits()
    assert corr.publish(date=PUB_DATE) == 0
    assert len(corr.names()) == 5 and len(set(corr.names())) == 5


def test_a_later_date_names_the_correction_files_with_that_date(corr: Corr):
    corr.round_to_audits()
    assert corr.publish(date=LATER) == 0
    assert corr.names() == sorted(
        BASE + [f"{LATER}-{SLUG}-C1-second.yaml", f"{LATER}-{SLUG}-C1.yaml", f"{LATER}-{SLUG}-C1-correction.yaml"]
    )
    assert corr.trail(LATER)["answered"] == BASE
    [entry] = yaml.safe_load(corr.pub.log.read_text(encoding="utf-8"))
    assert entry["date"] == dt.date(2026, 11, 20)


@pytest.mark.parametrize("target", ["-C1", "-C1-second"])
def test_an_existing_target_is_never_overwritten_and_nothing_is_written(corr: Corr, target, capsys):
    corr.round_to_audits()
    path = corr.audits / f"{PUB_DATE}-{SLUG}{target}.yaml"
    path.write_text(f"card: {SLUG}\nearlier: record\n", encoding="utf-8")
    names = corr.names()
    assert corr.publish() == 1
    assert "never overwritten" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == f"card: {SLUG}\nearlier: record\n" and corr.names() == names
    assert corr.draft.exists() and not corr.card.exists() and not corr.pub.log.exists()
    assert not (corr.dir / "publication-report.md").exists()


# --- A9: no re-audit of an unchanged draft --------------------------------------------------------------


def test_publish_without_a_round_refuses_when_the_draft_was_audited_and_names_correction_plan(corr: Corr, capsys):
    before = corr.names()
    assert corr.main("publish-card", SLUG, "--run-dir", str(corr.dir), "--date", LATER) == 1
    err = capsys.readouterr().err
    assert "correction-plan" in err and SLUG in err
    assert corr.names() == before and not (corr.dir / "publication-report.md").exists()


def test_audit_plan_without_a_round_refuses_when_the_draft_was_audited(corr: Corr, capsys):
    assert corr.main("audit-plan", "--card", SLUG, "--out", str(corr.dir)) == 1
    assert "correction-plan" in capsys.readouterr().err
    assert not (corr.dir / "audit-context").exists()


def test_a_longer_slug_does_not_make_the_first_publication_refuse(pub: Pub, tmp_path: Path):
    pub.audits.mkdir()
    (pub.audits / f"{PUB_DATE}-{SLUG}-extra.yaml").write_text(yaml.safe_dump(whole()), encoding="utf-8")
    (pub.audits / f"{PUB_DATE}-{SLUG}-extra-second.yaml").write_text(yaml.safe_dump(whole()), encoding="utf-8")
    pub.audits_of_card(whole(), whole())  # audit-plan --card must not refuse
    assert pub.publish() == 0
    assert pub.card.exists()


def test_the_whole_card_audit_files_match_the_known_suffixes_exactly(pub: Pub):
    cfg = pipeline.Config(
        pub.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC, audits_dir=pub.audits
    )
    pub.audits.mkdir()
    good = [
        "",
        "-second",
        "-L",
        "-L-second",
        "-C1",
        "-C1-second",
        "-C12",
    ]
    for suffix in good:
        (pub.audits / f"2026-11-13-{SLUG}{suffix}.yaml").write_text("card: " + SLUG + "\n", encoding="utf-8")
    for name in (
        f"2026-11-13-{SLUG}-C1-correction.yaml",  # the trail is not an audit record
        f"2026-11-13-{SLUG}-extra.yaml",
        f"2026-11-13-{SLUG}-C1x.yaml",
        f"2026-11-13-{SLUG}-90000101.yaml",
        f"2026-11-13-x{SLUG}.yaml",
        f"{SLUG}.yaml",
        f"2026-11-13-{SLUG}-second.yaml.bak",
    ):
        (pub.audits / name).write_text("card: " + SLUG + "\n", encoding="utf-8")
    found = [p.name for p in pipeline.whole_card_audit_files(cfg, SLUG)]
    assert found == sorted(f"2026-11-13-{SLUG}{s}.yaml" for s in good)
    assert [p.name for p in pipeline.correction_trails(cfg, SLUG)] == [f"2026-11-13-{SLUG}-C1-correction.yaml"]


# --- B1: a cp1252 console --------------------------------------------------------------------------------


def test_publish_card_does_not_crash_on_a_cp1252_console(pub: Pub, monkeypatch):
    pub.audits_of_card(whole(reasons_summary="Lower beta signalling (β) at ≥ 2 rungs."), whole())
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="")
    monkeypatch.setattr("sys.stdout", console)
    code = pipeline.main(
        ["publish-card", SLUG, "--run-dir", str(pub.dir), "--date", PUB_DATE, *pub.env.dir_args],
        fulltext=_loader(),
    )
    console.flush()
    assert code == 0
    assert "β".encode() in raw.getvalue() or b"?" in raw.getvalue()  # UTF-8 (or a replacement), never a crash
    assert pub.card.exists() and not pub.draft.exists()
    assert "β" in pub.report()


# --- B2: the held-back reason does not depend on the order of the audits ----------------------------------


def reason_of(pub: Pub, first: dict | None, second: dict | None) -> str:
    pub.audits_of_card(first, second)
    assert pub.publish("--dry-run") == 0
    return next(line for line in pub.report().splitlines() if line.startswith("Held back: "))


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (whole("reject"), whole("accept"), "the two audits differ: one decided accept, the other reject"),
        (
            whole("reject"),
            whole("accept_lower", accepted_level=1),
            "the two audits differ: one decided accept_lower at level 1, the other reject",
        ),
        (
            whole("accept"),
            whole("accept_lower", accepted_level=1),
            "the two audits differ: one decided accept, the other accept_lower at level 1",
        ),
        (whole("reject"), whole("reject"), "both audits decided reject"),
    ],
)
def test_the_reason_is_the_same_in_either_order(env: Env, tmp_path: Path, a, b, expected):
    one = reason_of(Pub(env, tmp_path / "one"), a, b)
    two = reason_of(Pub(env, tmp_path / "two"), b, a)
    assert one == two == f"Held back: {expected}"


def test_one_valid_reject_and_one_missing_record_name_both_facts_in_either_order(env: Env, tmp_path: Path):
    one = reason_of(Pub(env, tmp_path / "one"), whole("reject"), None)
    two = reason_of(Pub(env, tmp_path / "two"), None, whole("reject"))
    bad = whole("reject")
    bad["parts"][0]["evidence"][0]["quote"] = "A sentence that is not in the cached record."
    three = reason_of(Pub(env, tmp_path / "three"), whole("reject"), bad)
    four = reason_of(Pub(env, tmp_path / "four"), bad, whole("reject"))
    prefix = "Held back: one audit decided reject and the other audit record is missing or invalid: "
    # S1: a first reject with no second audit run is a complete outcome (it no longer says the second is missing).
    assert one == f"Held back: {pipeline.SEQUENTIAL_REJECT}"
    assert two.startswith(prefix) and three.startswith(prefix) and four.startswith(prefix)
    assert f"no audit record {SLUG}.yaml" in two


# --- B3: the format retry of an invalid audit record ------------------------------------------------------


def invalid(**quote) -> dict:
    data = whole()
    data["parts"][0]["evidence"][0]["quote"] = "A sentence that is not in the cached record."
    return data | quote


class Retry:
    def __init__(self, pub: Pub):
        self.pub = pub
        pub.plan()
        self.path = pub.write(invalid())

    def record(self, *extra: str) -> int:
        return self.pub.main(
            "record-audit", "--card", SLUG, "--file", str(self.path), "--out", str(self.pub.dir), *extra
        )

    def sibling(self, ending: str) -> Path:
        return self.path.with_name(self.path.stem + ending)


def test_an_invalid_record_is_moved_aside_and_the_retry_instructions_are_written(pub: Pub, capsys):
    r = Retry(pub)
    original = r.path.read_bytes()
    assert r.record() == 1
    err = capsys.readouterr().err
    assert "is not found word for word" in err and "fictional-pipeline-card.invalid-1.yaml" in err
    assert not r.path.exists() and r.sibling(".invalid-1.yaml").read_bytes() == original
    note = r.sibling(".retry.md").read_text(encoding="utf-8")
    assert "is not found word for word" in note
    assert str(pub.dir / "audit-context" / f"{SLUG}.md") in note and str(r.sibling(".invalid-1.yaml")) in note
    assert "decision" in note and "format only" in note


def test_a_valid_retry_is_accepted(pub: Pub, capsys):
    r = Retry(pub)
    assert r.record() == 1
    pub.write(whole())
    assert r.record("--retry") == 0
    assert "audit recorded: accept" in pub.env.out[-1]
    assert r.sibling(".invalid-1.yaml").exists() and not r.sibling(".invalid-2.yaml").exists()


def test_a_retry_that_changes_the_decision_is_refused_and_final(pub: Pub, capsys):
    r = Retry(pub)
    assert r.record() == 1
    capsys.readouterr()
    pub.write(whole("reject"))
    assert r.record("--retry") == 1
    err = capsys.readouterr().err
    assert "a format retry cannot change the answer" in err and "invalid-2" in err
    assert r.sibling(".invalid-2.yaml").exists() and not r.path.exists()


def test_a_retry_that_changes_the_accepted_level_is_refused(pub: Pub, capsys):
    pub.plan()
    path = pub.write(invalid(decision="accept_lower", accepted_level=1))
    r = Retry.__new__(Retry)
    r.pub, r.path = pub, path
    assert r.record() == 1
    pub.write(whole("accept_lower", accepted_level=0))
    assert r.record("--retry") == 1
    assert "accepted level 1" in capsys.readouterr().err


def test_a_second_failure_is_final_and_no_further_retry_is_accepted(pub: Pub, capsys):
    r = Retry(pub)
    assert r.record() == 1
    pub.write(invalid())
    assert r.record("--retry") == 1
    assert "final" in capsys.readouterr().err
    assert r.sibling(".invalid-2.yaml").exists() and not r.path.exists()
    pub.write(whole())
    assert r.record("--retry") == 1  # no third attempt, whatever the file holds
    assert "failed validation twice" in capsys.readouterr().err
    assert r.path.exists()  # not consumed, not accepted


def test_retry_without_an_earlier_failure_is_refused(pub: Pub, capsys):
    pub.plan()
    path = pub.write(whole())
    assert pub.main("record-audit", "--card", SLUG, "--file", str(path), "--out", str(pub.dir), "--retry") == 1
    assert "needs an earlier invalid record" in capsys.readouterr().err


def test_publish_card_and_the_report_name_a_record_that_failed_twice(pub: Pub):
    r = Retry(pub)
    assert r.record() == 1
    pub.write(invalid())
    assert r.record("--retry") == 1
    pub.write(whole(), "-second")
    assert pub.publish() == 0
    report = pub.report()
    assert f"the record {SLUG}.yaml failed validation twice" in report
    assert pub.audit_names() == [f"{PUB_DATE}-{SLUG}-second.yaml"]  # only valid records are copied


def test_a_pair_record_gets_the_same_format_retry(ready: Env):
    ready.put("ops", "ops_propose_level.json")
    # the pair record path: invalid, moved aside, retry note written
    from test_audit import audit_data, write_record

    assert ready.apply("ops_propose_level.json") == 0
    ready.put("review", "review_accept.json")
    assert ready.cli("audit-plan", SLUG, "90000101", fulltext=_loader()) == 0
    bad = audit_data()
    bad["parts"][0]["evidence"][0]["quote"] = "Not in the record."
    path = write_record(ready, bad)
    assert ready.cli("record-audit", SLUG, "90000101") == 1
    assert not path.exists() and path.with_name(path.stem + ".invalid-1.yaml").exists()
    assert path.with_name(path.stem + ".retry.md").exists()
    # a second failure is final, and the pair's audit note (shown in the report of `pr`) names it
    write_record(ready, bad)
    assert ready.cli("record-audit", SLUG, "90000101", "--retry") == 1
    cfg = pipeline.Config(ready.run, ready.cards, ready.drafts, ready.cache, pipeline.DEFAULT_SPEC)
    record, why = pipeline.load_audit(cfg, SLUG, "90000101")
    assert record is None and "failed validation twice" in str(why)


@pytest.fixture
def ready(env: Env) -> Env:
    env.prepare()
    assert env.classify() == 0
    return env


# --- review findings: slug collisions, broken records, neutral wording, both records missing --------------


def _cfg(pub: Pub) -> pipeline.Config:
    return pipeline.Config(
        pub.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC, audits_dir=pub.audits
    )


@pytest.mark.parametrize("suffix", ["-second", "-L", "-C1"])
def test_a_record_of_a_card_whose_slug_ends_like_a_suffix_is_not_counted_for_the_shorter_slug(pub: Pub, suffix):
    pub.audits.mkdir()
    longer = f"{SLUG}{suffix}"
    (pub.audits / f"2026-11-13-{longer}.yaml").write_text(yaml.safe_dump(whole() | {"card": longer}), encoding="utf-8")
    cfg = _cfg(pub)
    assert pipeline.whole_card_audit_files(cfg, SLUG) == []
    # and the reverse: the record of SLUG is not counted for the longer slug
    own = pub.audits / f"2026-11-14-{SLUG}{suffix}.yaml"
    own.write_text(yaml.safe_dump(whole()), encoding="utf-8")
    assert pipeline.whole_card_audit_files(cfg, SLUG) == [own]
    assert pipeline.whole_card_audit_files(cfg, longer) == [pub.audits / f"2026-11-13-{longer}.yaml"]


def test_a_longer_card_whose_record_is_named_like_a_suffix_does_not_block_the_first_publication(pub: Pub):
    pub.audits.mkdir()
    for suffix in ("-second", "-L", "-C1"):
        longer = f"{SLUG}{suffix}"
        (pub.audits / f"2026-11-13-{longer}.yaml").write_text(
            yaml.safe_dump(whole() | {"card": longer}), encoding="utf-8"
        )
    pub.audits_of_card(whole(), whole())  # audit-plan --card must not refuse
    assert pub.publish() == 0 and pub.card.exists()


def test_a_trail_record_of_another_card_is_not_counted(pub: Pub):
    pub.audits.mkdir()
    (pub.audits / f"2026-11-13-{SLUG}-C1-correction.yaml").write_text(
        yaml.safe_dump({"card": "another-card"}), encoding="utf-8"
    )
    assert pipeline.correction_trails(_cfg(pub), SLUG) == []
    own = pub.audits / f"2026-11-14-{SLUG}-C1-correction.yaml"
    own.write_text(yaml.safe_dump({"card": SLUG}), encoding="utf-8")
    assert pipeline.correction_trails(_cfg(pub), SLUG) == [own]


@pytest.mark.parametrize("content", ["card: [unclosed\n", "just a string\n", "decision: accept\n"])
def test_a_broken_record_in_audits_is_a_refusal_naming_the_file_not_a_skip(pub: Pub, capsys, content):
    pub.audits.mkdir()
    bad = pub.audits / f"2026-11-13-{SLUG}-second.yaml"
    bad.write_text(content, encoding="utf-8")
    with pytest.raises(pipeline.PipelineError, match=bad.name):
        pipeline.whole_card_audit_files(_cfg(pub), SLUG)
    trail = pub.audits / f"2026-11-13-{SLUG}-C1-correction.yaml"
    trail.write_text(content, encoding="utf-8")
    with pytest.raises(pipeline.PipelineError, match=trail.name):
        pipeline.correction_trails(_cfg(pub), SLUG)
    # the commands refuse and write nothing: the draft cannot be audited again around a broken record
    assert pub.main("audit-plan", "--card", SLUG, "--out", str(pub.dir)) == 1
    assert bad.name in capsys.readouterr().err and not (pub.dir / "audit-context").exists()
    assert pub.publish() == 1 and not pub.card.exists() and not (pub.dir / "publication-report.md").exists()
    assert pub.main("correction-plan", SLUG, "--out", str(pub.dir / "c")) == 1 and not (pub.dir / "c").exists()


def test_both_records_missing_or_invalid_are_both_named(pub: Pub):
    pub.dir.mkdir()
    assert pub.publish("--dry-run") == 0
    line = next(x for x in pub.report().splitlines() if x.startswith("Held back: "))
    assert f"no audit record {SLUG}.yaml" in line and f"no audit record {SLUG}-second.yaml" in line
    bad = whole()
    bad["parts"][0]["evidence"][0]["quote"] = "A sentence that is not in the cached record."
    pub.audits_of_card(bad, bad)
    assert pub.publish("--dry-run") == 0
    line = next(x for x in pub.report().splitlines() if x.startswith("Held back: "))
    assert line.count("is not found word for word") == 2
