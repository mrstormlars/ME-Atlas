"""Tests for the whole-card review gate at the first publication of a draft (no correction round).

Fictional card and agent output, temporary folders only. No network, no AI, no git.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_correction import Corr
from test_pipeline import SLUG, Env
from test_publish_card import PUB_DATE, Pub, whole

from me_atlas import pipeline

REJECT = [
    {
        "operation": None,
        "severity": "must_fix",
        "class": "decisive",
        "targets": ["core_claim"],
        "problem": "A fictional unsupported claim.",
    }
]
TRAIL = f"{PUB_DATE}-{SLUG}-card-review.yaml"


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def pub(env: Env, tmp_path: Path) -> Pub:
    return Pub(env, tmp_path)


def plan_audit(pub: Pub) -> int:
    return pub.main("audit-plan", "--card", SLUG, "--out", str(pub.dir))


def trail(pub: Pub) -> dict:
    return yaml.safe_load((pub.audits / TRAIL).read_text(encoding="utf-8"))


def nothing_written(pub: Pub) -> None:
    assert not pub.dir.exists() or not (pub.dir / "publication-report.md").exists()
    assert pub.all_audit_names() == [] and not pub.card.exists() and pub.draft.read_bytes() == pub.draft_bytes


# --- card-review-plan and record-review without a round ---------------------------------------------------


def test_the_first_review_context_is_built_from_the_draft(pub: Pub):
    assert pub.main("card-review-plan", SLUG, "--out", str(pub.dir)) == 0
    text = (pub.dir / "card-review-context" / f"{SLUG}-first.md").read_text(encoding="utf-8")
    assert "first publication" in text and "## 4. The checklist" in text and "### pmid:90000100" in text
    assert str(pub.dir / "review" / f"{SLUG}-card-first.json") in text
    assert pub.draft.read_bytes() == pub.draft_bytes


def test_the_first_review_plan_is_refused_for_a_card_a_missing_draft_a_trail_or_an_audit_record(pub: Pub):
    plan = ("card-review-plan", SLUG, "--out", str(pub.dir))
    pub.card.write_text("# a card\n", encoding="utf-8")
    assert pub.main(*plan) == 1 and not pub.dir.exists()
    pub.card.unlink()
    pub.draft.rename(pub.draft.with_name("moved.yaml"))
    assert pub.main(*plan) == 1 and not pub.dir.exists()
    pub.draft.with_name("moved.yaml").rename(pub.draft)
    pub.audits.mkdir()
    (pub.audits / f"{PUB_DATE}-{SLUG}-card-review.yaml").write_text(
        f"card: {SLUG}\nverdict: accept\n", encoding="utf-8"
    )
    assert pub.main(*plan) == 1 and not pub.dir.exists()  # a trail: the correction path applies
    (pub.audits / f"{PUB_DATE}-{SLUG}-card-review.yaml").unlink()
    (pub.audits / f"{PUB_DATE}-{SLUG}.yaml").write_text(yaml.safe_dump(whole()), encoding="utf-8")
    assert pub.main(*plan) == 1 and not pub.dir.exists()  # an audit record
    (pub.audits / f"{PUB_DATE}-{SLUG}.yaml").unlink()
    assert pub.main(*plan) == 0


def test_record_review_validates_the_first_review_like_the_other_whole_card_reviews(pub: Pub, capsys):
    path = pub.dir / "review" / f"{SLUG}-card-first.json"
    path.parent.mkdir(parents=True)
    bad = {"card": SLUG, "paper": None, "verdict": "reject", "findings": [{**REJECT[0], "targets": None}]}
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert pub.main("record-review", SLUG, "--card-review", "--run-dir", str(pub.dir)) == 1
    assert "without `targets`" in capsys.readouterr().err
    bad["findings"] = [{**REJECT[0], "targets": ["early_signals[9]"]}]  # names something the draft lacks
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert pub.main("record-review", SLUG, "--card-review", "--run-dir", str(pub.dir)) == 1
    bad["findings"] = REJECT
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert pub.main("record-review", SLUG, "--card-review", "--run-dir", str(pub.dir)) == 0


# --- audit-plan is gated -----------------------------------------------------------------------------------


def test_audit_plan_is_refused_without_a_review_and_with_a_rejecting_one(pub: Pub, capsys):
    assert plan_audit(pub) == 1
    assert "no valid whole-card review" in capsys.readouterr().err
    assert not (pub.dir / "audit-context").exists()
    pub.first_review("reject", REJECT)
    assert plan_audit(pub) == 1
    assert "rejected the draft" in capsys.readouterr().err
    assert not (pub.dir / "audit-context").exists()


def test_audit_plan_works_after_an_accepting_review(pub: Pub):
    pub.first_review()
    assert plan_audit(pub) == 0
    assert (pub.dir / "audit-context" / f"{SLUG}.md").is_file()


# --- publish-card ------------------------------------------------------------------------------------------


def test_publish_card_without_a_review_raises_and_writes_nothing(pub: Pub, capsys):
    pub.audits_of_card(None, None)  # audit-plan needs the review: record it, then remove it again
    (pub.dir / "review" / f"{SLUG}-card-first.json").unlink()
    pub.write(whole())
    pub.write(whole(), "-second")
    assert pub.publish() == 1
    assert "no valid whole-card review" in capsys.readouterr().err
    assert not (pub.dir / "publication-report.md").exists()
    assert pub.all_audit_names() == [] and not pub.card.exists() and pub.draft.read_bytes() == pub.draft_bytes


def test_publish_card_holds_the_draft_back_on_a_rejecting_review_and_writes_the_trail(pub: Pub):
    pub.first_review("reject", REJECT)
    assert pub.publish() == 0
    pub.assert_held_back("whole-card review rejected")
    assert pub.all_audit_names() == [TRAIL]
    data = trail(pub)
    assert data["card"] == SLUG and data["verdict"] == "reject"
    assert data["must_fix_count"] == 1 and data["decisive_count"] == 1
    assert data["findings"][0]["problem"] == "A fictional unsupported claim."
    assert data["draft_sha256"] == pipeline._sha256(pub.draft_bytes)


def test_a_dry_run_writes_no_trail(pub: Pub):
    pub.first_review("reject", REJECT)
    assert pub.publish("--dry-run") == 0
    assert pub.all_audit_names() == []


def test_publish_card_publishes_on_an_accepting_review_and_writes_the_trail(pub: Pub):
    pub.audits_of_card(whole(), whole())
    assert pub.publish() == 0
    assert pub.card.exists() and not pub.draft.exists()
    assert pub.all_audit_names() == [TRAIL, f"{PUB_DATE}-{SLUG}-second.yaml", f"{PUB_DATE}-{SLUG}.yaml"]
    data = trail(pub)
    assert data["verdict"] == "accept" and data["must_fix_count"] == 0 and data["findings"] == []
    assert data["draft_sha256"] == pipeline._sha256(pub.draft_bytes)


def test_an_accepting_review_with_rejecting_audits_still_holds_back_and_writes_the_trail(pub: Pub):
    pub.audits_of_card(whole("reject"), whole("reject"))
    assert pub.publish() == 0
    assert not pub.card.exists() and pub.draft.exists()
    assert TRAIL in pub.all_audit_names() and f"{PUB_DATE}-{SLUG}.yaml" in pub.all_audit_names()


def test_a_second_first_publication_is_refused_once_a_trail_exists(pub: Pub):
    pub.first_review("reject", REJECT)
    assert pub.publish() == 0
    before = pub.all_audit_names()
    assert pub.main("publish-card", SLUG, "--run-dir", str(pub.dir), "--date", "2026-11-15") == 1
    assert pub.all_audit_names() == before
    assert plan_audit(pub) == 1  # nor is the draft audited
    assert pub.main("card-review-plan", SLUG, "--out", str(pub.dir / "again")) == 1


def test_the_trail_is_not_an_audit_record_nor_a_correction_trail(pub: Pub):
    pub.first_review("reject", REJECT)
    assert pub.publish() == 0
    cfg = pipeline.Config(
        pub.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC, audits_dir=pub.audits
    )
    assert pipeline.whole_card_audit_files(cfg, SLUG) == [] and pipeline.correction_trails(cfg, SLUG) == []
    assert [p.name for p in pipeline.first_review_trails(cfg, SLUG)] == [TRAIL]
    assert pipeline.correction_round_state(cfg, SLUG) == (0, None)


# --- the correction path accepts a draft held back by the review ------------------------------------------


def test_correction_plan_accepts_a_draft_held_back_by_the_first_review(pub: Pub, tmp_path: Path):
    pub.first_review("reject", REJECT)
    assert pub.publish() == 0
    corr = Corr(pub, tmp_path)
    assert corr.plan() == 0  # the review of the unchanged draft, then correction-plan
    text = (corr.dir / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert f"### {TRAIL}" in text and "A fictional unsupported claim." in text and "targets: core_claim" in text
    cfg = pipeline.Config(
        corr.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC, audits_dir=pub.audits
    )
    assert "core_claim" in pipeline.first_review_targets(cfg, SLUG)


def test_a_correction_round_after_the_first_review_publishes_and_names_the_trail_as_answered(pub: Pub, tmp_path: Path):
    pub.first_review("reject", [{**REJECT[0], "targets": ["contested_reason[1]"]}])  # what the default ops remove
    assert pub.publish() == 0
    corr = Corr(pub, tmp_path)
    corr.round_to_audits()
    assert corr.publish() == 0
    assert corr.card.exists()
    assert corr.trail()["answered"] == [TRAIL]


# --- the draft published is the draft reviewed -------------------------------------------------------------


def test_audit_plan_and_publish_card_refuse_a_draft_changed_after_its_review(pub: Pub, capsys):
    pub.first_review()
    pub.draft.write_bytes(pub.draft_bytes + b"# edited after the review\n")
    assert plan_audit(pub) == 1
    assert "changed after its whole-card review" in capsys.readouterr().err
    assert not (pub.dir / "audit-context").exists()
    pub.write(whole())
    pub.write(whole(), "-second")
    assert pub.publish() == 1
    assert "changed after its whole-card review" in capsys.readouterr().err
    assert not (pub.dir / "publication-report.md").exists()
    assert pub.all_audit_names() == [] and not pub.card.exists()


def test_a_missing_sha_sidecar_is_refused_at_both_commands(pub: Pub, capsys):
    pub.first_review()
    (pub.dir / "review" / f"{SLUG}-card-first.sha256").unlink()
    assert plan_audit(pub) == 1 and "is missing" in capsys.readouterr().err
    assert pub.publish() == 1 and "is missing" in capsys.readouterr().err
    assert not (pub.dir / "publication-report.md").exists() and pub.all_audit_names() == []


def test_the_trail_carries_the_recorded_draft_sha256(pub: Pub):
    pub.first_review("reject", REJECT)
    recorded = (pub.dir / "review" / f"{SLUG}-card-first.sha256").read_text(encoding="utf-8").strip()
    assert recorded == pipeline._sha256(pub.draft_bytes)
    assert pub.publish() == 0 and trail(pub)["draft_sha256"] == recorded
