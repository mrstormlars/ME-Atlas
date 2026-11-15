"""Tests for `publish-card`: the first publication of a draft from two whole-card audits (and a redraft).

Fictional card, papers and agent output (tests/fixtures/pipeline), temporary `cards/`, `drafts/` and `audits/`
folders. No test touches the network, an AI or git.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from test_audit import CITED, CITED_TITLE, RUBRIC, audit_data
from test_pipeline import FIXTURES, SLUG, Env, fulltext_loader

from me_atlas import cards, pipeline

PUB_DATE = "2026-11-14"
DRAFT_LEVEL = 2


def whole(decision: str = "accept", **over) -> dict:
    """A whole-card audit record (no paper). accept_lower accepts level 1 (the draft is at level 2)."""
    data = {k: v for k, v in audit_data(decision, **over).items() if k != "paper"}
    if decision == "accept_lower":
        data["accepted_level"] = over.get("accepted_level", 1)
    return data


class Pub:
    """A draft card in tmp ``drafts/`` and a whole-card audit folder DIR beside it."""

    def __init__(self, env: Env, tmp: Path):
        self.env = env
        self.dir = tmp / "card-audit"
        self.audits = env.root / "audits"
        self.draft = env.drafts / f"{SLUG}.yaml"
        self.card = env.cards / f"{SLUG}.yaml"
        self.log = env.cards / pipeline.CHANGELOG_NAME
        self.draft_bytes = self.draft.read_bytes()

    def main(self, *argv: str) -> int:
        return pipeline.main([*argv, *self.env.dir_args], fulltext=fulltext_loader(), out=self.env.out.append)

    def publish(self, *extra: str) -> int:
        return self.main("publish-card", SLUG, "--run-dir", str(self.dir), "--date", PUB_DATE, *extra)

    def plan(self, redraft: bool = False) -> None:
        rnd = ["--round", "L"] if redraft else []
        assert self.main("audit-plan", "--card", SLUG, "--out", str(self.dir), *rnd) == 0

    def write(self, data: dict | str, suffix: str = "") -> Path:
        path = self.dir / "audit" / f"{SLUG}{suffix}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def audits_of_card(self, first: dict | None, second: dict | None) -> None:
        self.plan()
        if first is not None:
            self.write(first)
        if second is not None:
            self.write(second, "-second")

    def redraft(self, mutate=None, *, checks: bool = True, review: str = "accept") -> None:
        """Round L as the pipeline leaves it: ops applied with --audit, reviewed, recorded."""
        ops = {
            "card": SLUG,
            "operations": [
                {
                    "op": "propose",
                    "target": "level",
                    "value": 1,
                    "reason": [
                        {"text": "A fictional controlled study found lower widget signalling.", "sources": [CITED]}
                    ],
                },
                {"op": "propose", "target": "contested", "value": None},
            ],
        }
        if mutate is not None:
            mutate(ops)
        ops_path = self.dir / "ops" / f"{SLUG}-rL.json"
        ops_path.parent.mkdir(parents=True, exist_ok=True)
        ops_path.write_text(json.dumps(ops), encoding="utf-8")
        if checks:
            code = self.main(
                "apply",
                SLUG,
                str(ops_path),
                "--round",
                "L",
                "--audit",
                str(self.dir / "audit" / f"{SLUG}.yaml"),
                "--run-dir",
                str(self.dir),
            )
            assert code == 0
        review_path = self.dir / "review" / f"{SLUG}-rL.json"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        findings = (
            []
            if review == "accept"
            else [{"operation": 0, "severity": "must_fix", "class": "decisive", "problem": "A fictional problem."}]
        )
        review_path.write_text(json.dumps({"card": SLUG, "verdict": review, "findings": findings}), encoding="utf-8")

    def audits_of_redraft(self, first: dict | None, second: dict | None) -> None:
        self.plan(redraft=True)
        if first is not None:
            self.write(first, "-L")
        if second is not None:
            self.write(second, "-L-second")

    def full_redraft(self, first: str = "accept", second: str | None = "accept", **kw) -> None:
        """Both first audits say accept_lower to level 1, then a redraft with the given round-L audits."""
        self.audits_of_card(whole("accept_lower"), whole("accept_lower"))
        self.redraft(**kw)
        low = {"accepted_level": 0}  # below the redraft's level 1
        self.audits_of_redraft(
            whole(first, **(low if first == "accept_lower" else {})),
            None if second is None else whole(second, **(low if second == "accept_lower" else {})),
        )

    def changelog(self) -> list[dict]:
        return yaml.safe_load(self.log.read_text(encoding="utf-8")) if self.log.is_file() else []

    def audit_names(self) -> list[str]:
        return sorted(p.name for p in self.audits.glob("*.yaml")) if self.audits.is_dir() else []

    def report(self) -> str:
        return (self.dir / "publication-report.md").read_text(encoding="utf-8")

    def assert_held_back(self, reason: str) -> None:
        assert self.draft.read_bytes() == self.draft_bytes
        assert not self.card.exists() and not self.log.exists()
        report = self.report()
        assert "Outcome: held back" in report
        assert f"Held back: {reason}" in report, report
        assert "Outcome: held back" in "\n".join(self.env.out)  # printed as well


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def pub(env: Env, tmp_path: Path) -> Pub:
    return Pub(env, tmp_path)


# --- accept ----------------------------------------------------------------------------------------------


def test_two_accepts_publish_the_draft_with_last_checked_set_and_the_draft_gone(pub: Pub):
    pub.audits_of_card(whole(), whole())
    assert pub.publish() == 0
    text = pub.card.read_text(encoding="utf-8")
    assert not pub.draft.exists()
    draft = pub.draft_bytes.decode("utf-8")
    assert (
        text != draft and text.replace("date: 2026-11-14\n  by: ai_audit", "date: 2026-10-01\n  by: ai_pair") == draft
    )
    data = yaml.safe_load(text)
    assert data["last_checked"] == {"date": dt.date(2026, 11, 14), "by": "ai_audit"}
    assert not cards.validate_card_file(pub.card)
    # One change-log entry with the F4 fields; it validates.
    [entry] = pub.changelog()
    assert entry == {
        "date": dt.date(2026, 11, 14),
        "card": SLUG,
        "change": "First publication at level 2",
        "reason": "The cited controlled study supports the proposed level.",
        "sources": [CITED],
        "tier": 2,
        "decided_by": "ai_audit",
    }
    assert not cards.validate_changelog_file(pub.log, today=dt.date(2026, 11, 14))
    # Both audit records are copied, and the report says there is no difference.
    assert pub.audit_names() == [f"{PUB_DATE}-{SLUG}-second.yaml", f"{PUB_DATE}-{SLUG}.yaml"]
    assert (pub.audits / f"{PUB_DATE}-{SLUG}.yaml").read_bytes() == (pub.dir / "audit" / f"{SLUG}.yaml").read_bytes()
    report = pub.report()
    assert "Outcome: published at level 2" in report and "No difference." in report
    assert "reasons_summary: The cited controlled study supports the proposed level." in report
    assert "would_change: A failed replication." in report
    assert "Outcome: published at level 2" in "\n".join(pub.env.out)
    assert f"ME-Atlas-Pipeline: weekly-run {PUB_DATE}" in pub.env.out[-1]


def test_the_change_log_keeps_its_earlier_entries_byte_for_byte(pub: Pub):
    existing = (
        "- date: 2026-10-30\n  card: other-card\n  change: An earlier change.\n  reason: Because.\n"
        "  sources: [pmid:90000100]\n  tier: 1\n  decided_by: ai_pair\n"
    )
    pub.env.cards.joinpath(pipeline.CHANGELOG_NAME).write_text(existing, encoding="utf-8", newline="\n")
    pub.audits_of_card(whole(), whole())
    assert pub.publish() == 0
    text = pub.log.read_text(encoding="utf-8")
    assert text.startswith(existing)
    assert [e["card"] for e in pub.changelog()] == ["other-card", SLUG]


# --- accept_lower and the redraft --------------------------------------------------------------------------


def test_accept_lower_with_a_redraft_accepted_at_every_step_publishes_the_redraft(pub: Pub):
    pub.full_redraft()
    assert pub.publish() == 0
    data = yaml.safe_load(pub.card.read_text(encoding="utf-8"))
    assert data["level"] == 1 and data["contested"] is None  # the auditors' accepted_level, not the draft's 2
    assert data["last_checked"] == {"date": dt.date(2026, 11, 14), "by": "ai_audit"}
    assert not pub.draft.exists()
    applied = (pub.dir / "applied" / f"{SLUG}-rL" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    assert (
        pub.card.read_text(encoding="utf-8")
        .replace("date: 2026-11-14", "date: 2026-10-01")
        .replace("by: ai_audit", "by: ai_pair")
        == applied
    )
    report = pub.report()
    assert "Outcome: published at level 1" in report
    assert "| level | 2 | 1 |" in report and "| contested | rungs 2 | null |" in report
    assert "diagnostic_marker.value" not in report.split("## The audits")[0]  # no badge difference
    [entry] = pub.changelog()
    assert (
        entry["change"] == "First publication at level 1; the draft had level 2; the draft had contested mark rungs 2"
    )
    assert entry["reason"] == "The cited controlled study supports the proposed level."
    assert pub.audit_names() == [
        f"{PUB_DATE}-{SLUG}-L-second.yaml",
        f"{PUB_DATE}-{SLUG}-L.yaml",
        f"{PUB_DATE}-{SLUG}-second.yaml",
        f"{PUB_DATE}-{SLUG}.yaml",
    ]


def test_the_differences_list_every_changed_field_and_nothing_else(pub: Pub):
    draft = pub.draft_bytes.decode("utf-8")
    other = draft.replace("\nlevel: 2\n", "\nlevel: 1\n", 1).replace("value: false", "value: true", 2)
    facts = pipeline._card_facts(other)
    assert pipeline._fact_differences(draft, facts) == [
        ("level", "2", "1"),
        ("diagnostic_marker.value", "false", "true"),
        ("explains_pem.value", "false", "true"),
    ]
    assert pipeline._fact_differences(draft, pipeline._card_facts(draft)) == []


# --- held back: the draft stays byte for byte, nothing else is written ----------------------------------


def test_a_reject_holds_the_card_back_and_still_copies_the_records(pub: Pub):
    pub.audits_of_card(whole("reject"), whole("reject"))
    assert pub.publish() == 0
    pub.assert_held_back("both audits decided reject")
    assert pub.audit_names() == [f"{PUB_DATE}-{SLUG}-second.yaml", f"{PUB_DATE}-{SLUG}.yaml"]
    assert "the audits give no card text" in pub.report()


def test_a_missing_second_audit_holds_the_card_back(pub: Pub):
    pub.audits_of_card(whole(), None)
    assert pub.publish() == 0
    pub.assert_held_back(f"no valid second audit: no audit record {SLUG}-second.yaml")
    assert pub.audit_names() == [f"{PUB_DATE}-{SLUG}.yaml"]


@pytest.mark.parametrize(
    "second",
    [
        whole("reject"),
        whole("accept_lower"),
        whole("accept", reasons_summary="A different line.") | {"decision": "reject"},
    ],
)
def test_a_second_audit_that_differs_holds_the_card_back(pub: Pub, second):
    pub.audits_of_card(whole(), second)
    assert pub.publish() == 0
    pub.assert_held_back("the two audits differ")


def test_two_accept_lower_audits_at_different_levels_differ(pub: Pub):
    pub.audits_of_card(whole("accept_lower", accepted_level=1), whole("accept_lower", accepted_level=0))
    assert pub.publish() == 0
    pub.assert_held_back("the two audits differ")


def test_an_invalid_first_record_holds_the_card_back(pub: Pub):
    bad = whole()
    bad["parts"][0]["evidence"][0]["quote"] = "A sentence that is not in the cached record."
    pub.audits_of_card(bad, whole())
    assert pub.publish() == 0
    pub.assert_held_back("no valid first audit: ")
    assert "is not found word for word in the cached record of " + CITED in pub.report()
    assert pub.audit_names() == [f"{PUB_DATE}-{SLUG}-second.yaml"]  # only the valid record is copied


def test_accept_lower_with_no_redraft_holds_the_card_back_and_reports_the_level(pub: Pub):
    pub.audits_of_card(whole("accept_lower"), whole("accept_lower"))
    assert pub.publish() == 0
    pub.assert_held_back("no redraft recorded")
    assert "| level | 2 | 1 |" in pub.report() and "accepted level 1" in pub.report()


def test_a_redraft_that_breaks_e4_holds_the_card_back(pub: Pub):
    # The checks file says passed, but the level is not the one the auditors accepted: the gate re-checks E4.
    pub.audits_of_card(whole("accept_lower"), whole("accept_lower"))

    def wrong_level(ops: dict) -> None:
        ops["operations"][0]["value"] = 0

    pub.redraft(wrong_level, checks=False)
    (pub.dir / "checks").mkdir()
    (pub.dir / "checks" / f"{SLUG}-rL.json").write_text(json.dumps({"passed": True, "card": SLUG}), encoding="utf-8")
    assert pub.publish() == 0
    pub.assert_held_back("redraft failed checks: the level proposed is 0, but the auditor accepted level 1")


def test_a_redraft_with_an_add_study_holds_the_card_back(pub: Pub):
    pub.audits_of_card(whole("accept_lower"), whole("accept_lower"))
    study = json.loads((FIXTURES / "agent" / "ops_add_study.json").read_text(encoding="utf-8"))["operations"][0]

    def add_study(ops: dict) -> None:
        ops["paper"] = "pmid:90000101"  # an add_study needs a paper to parse; a redraft names none
        ops["operations"].append(study)

    pub.redraft(add_study, checks=False)
    (pub.dir / "checks").mkdir()
    (pub.dir / "checks" / f"{SLUG}-rL.json").write_text(json.dumps({"passed": True, "card": SLUG}), encoding="utf-8")
    assert pub.publish() == 0
    held = [line for line in pub.report().splitlines() if line.startswith("Held back: ")]
    assert len(held) == 1 and held[0].startswith("Held back: redraft failed checks: ")
    assert "operations[2] is add_study: a redraft may hold propose operations only" in held[0]
    assert pub.draft.read_bytes() == pub.draft_bytes and not pub.card.exists() and not pub.log.exists()


def test_a_redraft_that_failed_its_checks_holds_the_card_back(pub: Pub):
    pub.full_redraft()
    checks = pub.dir / "checks" / f"{SLUG}-rL.json"
    data = json.loads(checks.read_text(encoding="utf-8"))
    checks.write_text(json.dumps({**data, "passed": False, "validator": ["V1 a fictional failure"]}), encoding="utf-8")
    assert pub.publish() == 0
    pub.assert_held_back("redraft failed checks: ")


def test_a_redraft_the_reviewer_rejected_holds_the_card_back(pub: Pub):
    pub.full_redraft(review="reject")
    assert pub.publish() == 0
    pub.assert_held_back("redraft rejected in review")


def test_a_redraft_the_auditor_rejects_holds_the_card_back(pub: Pub):
    pub.full_redraft(first="reject", second="reject")
    assert pub.publish() == 0
    pub.assert_held_back("redraft not accepted in audit: reject")


def test_a_redraft_the_auditor_lowers_again_holds_the_card_back(pub: Pub):
    pub.full_redraft(first="accept_lower", second="accept_lower")
    assert pub.publish() == 0
    pub.assert_held_back("redraft not accepted in audit: accept_lower")


def test_a_redraft_with_no_second_audit_holds_the_card_back(pub: Pub):
    pub.full_redraft(second=None)
    assert pub.publish() == 0
    pub.assert_held_back(
        f"redraft not accepted in audit: the second audit is not valid: no audit record {SLUG}-L-second.yaml"
    )


def test_a_redraft_whose_second_audit_does_not_accept_holds_the_card_back(pub: Pub):
    pub.full_redraft(second="reject")
    assert pub.publish() == 0
    pub.assert_held_back("redraft not accepted in audit: the second audit decided reject")


def test_an_applied_text_that_does_not_match_the_operations_holds_the_card_back(pub: Pub):
    pub.full_redraft()
    applied = pub.dir / "applied" / f"{SLUG}-rL" / f"{SLUG}.yaml"
    applied.write_text(
        applied.read_text(encoding="utf-8").replace("level: 1", "level: 0"), encoding="utf-8", newline="\n"
    )
    assert pub.publish() == 0
    pub.assert_held_back("redraft failed checks: its applied text does not match its operations")


def test_a_card_that_does_not_validate_as_a_published_card_is_held_back(pub: Pub, monkeypatch):
    pub.audits_of_card(whole(), whole())
    monkeypatch.setattr(pipeline, "_published_card_problems", lambda cfg, slug, text: ["V16: a fictional problem"])
    assert pub.publish() == 0
    pub.assert_held_back("the card to publish does not validate: V16: a fictional problem")


def test_the_card_check_for_a_published_card_applies_v16(pub: Pub):
    cfg = pipeline.Config(pub.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC)
    text = pub.draft_bytes.decode("utf-8")  # last_checked.by is ai_pair: allowed in a draft, not in cards/
    assert any("V16" in p for p in pipeline._published_card_problems(cfg, SLUG, text))
    fixed = pipeline._set_last_checked(text, PUB_DATE, "ai_audit")
    assert pipeline._published_card_problems(cfg, SLUG, fixed) == []


# --- dry run and refusals ----------------------------------------------------------------------------------


def test_a_dry_run_writes_only_the_report(pub: Pub):
    pub.audits_of_card(whole(), whole())
    before = {p.relative_to(pub.env.root) for p in pub.env.root.rglob("*") if p.is_file()}
    assert pub.publish("--dry-run") == 0
    after = {p.relative_to(pub.env.root) for p in pub.env.root.rglob("*") if p.is_file()}
    assert after - before == {Path("card-audit/publication-report.md")} and before <= after
    assert pub.draft.read_bytes() == pub.draft_bytes and not pub.card.exists() and not pub.log.exists()
    assert not pub.audits.exists()
    assert "Outcome: published at level 2" in pub.report()  # the report says what a real run would do


def test_it_refuses_when_the_card_already_exists_and_writes_nothing(pub: Pub):
    pub.audits_of_card(whole(), whole())
    pub.card.write_text("# an earlier card\n", encoding="utf-8")
    assert pub.publish() == 1
    assert pub.card.read_text(encoding="utf-8") == "# an earlier card\n"
    assert pub.draft.read_bytes() == pub.draft_bytes
    assert not (pub.dir / "publication-report.md").exists() and not pub.audits.exists() and not pub.log.exists()


def test_it_refuses_when_there_is_no_draft(pub: Pub):
    pub.audits_of_card(whole(), whole())
    pub.draft.unlink()
    assert pub.publish() == 1
    assert not (pub.dir / "publication-report.md").exists() and not pub.card.exists()


def test_it_refuses_to_overwrite_an_audit_record_and_writes_nothing(pub: Pub, capsys):
    pub.audits_of_card(whole(), whole())
    pub.audits.mkdir()
    target = pub.audits / f"{PUB_DATE}-{SLUG}-second.yaml"
    target.write_text("earlier: record\n", encoding="utf-8")
    assert pub.publish() == 1
    assert "never overwritten" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "earlier: record\n"
    assert pub.audit_names() == [target.name]
    assert pub.draft.read_bytes() == pub.draft_bytes and not pub.card.exists() and not pub.log.exists()
    assert not (pub.dir / "publication-report.md").exists()


def test_it_needs_a_run_dir(pub: Pub, capsys):
    assert pipeline.main(["publish-card", SLUG, *pub.env.dir_args]) == 1
    assert "needs --run-dir" in capsys.readouterr().err


def test_a_folder_with_no_audit_records_is_held_back_and_the_draft_is_untouched(pub: Pub):
    pub.dir.mkdir()
    assert pub.publish("--dry-run") == 0
    pub.assert_held_back(f"no valid first audit: no audit record {SLUG}.yaml")
    assert RUBRIC and CITED_TITLE  # the shared fixtures are in use
