"""Tests for the whole-card review before drafting (--pre), the three attempts of a correction round (one revision per
review kind) and the per-slug round C2 (DECISIONS 2026-11-15).

Fictional card and agent output, temporary folders only. No network, no AI, no git.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_correction import CONTESTED_LAST, Corr, ops_data
from test_correction_revised import EARLY_SIGNAL
from test_pipeline import SLUG, Env
from test_publish_card import PUB_DATE, Pub, whole

from me_atlas import pipeline

FLAGS = {suffix: [suffix.replace("-", "--", 1)] if suffix else [] for suffix in pipeline.ATTEMPT_SUFFIXES}


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def corr(env: Env, tmp_path: Path) -> Corr:
    c = Corr(Pub(env, tmp_path), tmp_path)
    c.hold_back()
    return c


def cfg_of(c: Corr) -> pipeline.Config:
    return pipeline.Config(c.dir, c.env.cards, c.env.drafts, c.env.cache, pipeline.DEFAULT_SPEC, audits_dir=c.audits)


def pre_plan(c: Corr, k: int = 1, *extra: str) -> int:
    return c.main("card-review-plan", SLUG, "--pre", "--round", f"C{k}", "--out", str(c.dir), *extra)


def attempt(c: Corr, suffix: str, review: str = "accept", card: str | None = "accept", decisive: int = 1) -> None:
    """One attempt (``""``, ``-revised``, ``-revised2``): ops, apply, correction review and, when that accepts and
    ``card`` is given, the whole-card review. Every step must pass."""
    ops = ops_data(EARLY_SIGNAL if suffix else CONTESTED_LAST)
    ops_file = c.dir / "ops" / f"{SLUG}-rC1{suffix}.json"
    ops_file.parent.mkdir(parents=True, exist_ok=True)
    ops_file.write_text(json.dumps(ops), encoding="utf-8")
    flag = FLAGS[suffix]
    assert c.main("apply", SLUG, str(ops_file), "--round", "C1", *flag, "--run-dir", str(c.dir)) == 0
    bad = [
        {
            "operation": 0,
            "severity": "must_fix",
            "class": "decisive",
            "targets": ["core_claim"],
            "problem": f"A problem {i}.",
        }
        for i in range(decisive)
    ]
    review_file = c.dir / "review" / f"{SLUG}-rC1{suffix}.json"
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_file.write_text(
        json.dumps({"card": SLUG, "verdict": review, "findings": [] if review == "accept" else bad}), encoding="utf-8"
    )
    assert c.main("record-review", SLUG, "--round", "C1", *flag, "--run-dir", str(c.dir)) == 0
    if review == "accept" and card is not None:
        found = (
            []
            if card == "accept"
            else [
                {
                    "operation": None,
                    "severity": "must_fix",
                    "class": "decisive",
                    "targets": ["core_claim"],
                    "problem": f"A problem {i}.",
                }
                for i in range(decisive)
            ]
        )
        card_file = c.dir / "review" / f"{SLUG}-card-C1{suffix}.json"
        card_file.write_text(
            json.dumps({"card": SLUG, "paper": None, "verdict": card, "findings": found}), encoding="utf-8"
        )
        args = ["record-review", SLUG, "--card-review", "--round", "C1", *flag, "--run-dir", str(c.dir)]
        assert c.main(*args) == 0


def apply_refused(c: Corr, suffix: str, capsys) -> str:
    ops_file = c.dir / "ops" / f"{SLUG}-rC1{suffix}.json"
    ops_file.write_text(json.dumps(ops_data(EARLY_SIGNAL)), encoding="utf-8")
    assert c.main("apply", SLUG, str(ops_file), "--round", "C1", *FLAGS[suffix], "--run-dir", str(c.dir)) == 1
    ops_file.unlink()  # a refused attempt leaves no ops file behind: the later steps read the files that exist
    return capsys.readouterr().err


# --- P1: card-review-plan --pre ---------------------------------------------------------------------------------


def test_the_pre_review_context_is_built_from_the_unchanged_draft(corr: Corr):
    assert pre_plan(corr) == 0
    text = (corr.dir / "card-review-context" / f"{SLUG}-C1-pre.md").read_text(encoding="utf-8")
    assert "### pmid:90000100" in text and str(corr.env.cache / "pubmed" / "90000100.xml") in text
    assert "# a comment between two paragraphs" not in text  # comments stripped, as in the post-correction review
    assert "Evidence ladder" in text and "## 4. The checklist" in text and "Case-definition labels" in text
    assert str(corr.dir / "review" / f"{SLUG}-card-C1-pre.json") in text
    drafted = yaml.safe_load(corr.draft.read_text(encoding="utf-8"))
    assert yaml.safe_load(text.split("```yaml\n")[1].split("```")[0]) == drafted  # the draft, not a corrected copy
    assert corr.draft.read_bytes() == corr.pub.draft_bytes


def test_the_pre_review_is_refused_for_a_published_card_a_missing_draft_or_no_audit(corr: Corr, tmp_path: Path):
    corr.card.write_text("# a card\n", encoding="utf-8")
    assert pre_plan(corr) == 1 and not corr.dir.exists()
    corr.card.unlink()
    corr.draft.rename(corr.draft.with_name("moved.yaml"))
    assert pre_plan(corr) == 1 and not corr.dir.exists()
    corr.draft.with_name("moved.yaml").rename(corr.draft)
    audits = corr.audits.rename(tmp_path / "audits-away")
    corr.audits.mkdir()
    assert pre_plan(corr) == 1 and not corr.dir.exists()  # no whole-card audit record: it is not held back
    corr.audits.rmdir()
    audits.rename(corr.audits)
    assert pre_plan(corr) == 0


def test_the_pre_review_is_refused_unless_the_round_is_the_next_allowed_one(corr: Corr, capsys):
    assert pre_plan(corr, 2) == 1 and "not allowed" in capsys.readouterr().err and not corr.dir.exists()
    (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction.yaml").write_text(
        yaml.safe_dump({"card": SLUG, "round": 1, "review": {"verdict": "accept"}}), encoding="utf-8"
    )
    assert pre_plan(corr, 1) == 1 and pre_plan(corr, 2) == 1 and not corr.dir.exists()  # C1 used, C2 not allowed
    assert corr.main("card-review-plan", SLUG, "--pre", "--revised", "--round", "C1", "--out", str(corr.dir)) == 1


# --- P2: record-review --card-review --pre -----------------------------------------------------------------------


def test_record_review_pre_validates_like_the_other_whole_card_review(corr: Corr, capsys):
    assert corr.pre_review("reject") == 0
    assert "whole-card review recorded: reject, 1 finding(s)" in corr.env.out[-1]  # either verdict is valid
    path = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    must_fix = {
        "operation": None,
        "severity": "must_fix",
        "class": "decisive",
        "targets": ["core_claim"],
        "problem": "A link that its source does not state.",
    }
    recorded = json.loads(path.read_text(encoding="utf-8"))
    base = {
        "card": SLUG,
        "paper": None,
        "verdict": "reject",
        "findings": [must_fix],
        "audit_targets": recorded["audit_targets"],
    }

    def run(data: dict, *extra: str) -> int:
        path.write_text(json.dumps(data), encoding="utf-8")
        args = ["record-review", SLUG, "--card-review", "--pre", "--round", "C1", "--run-dir", str(corr.dir), *extra]
        return corr.main(*args)

    assert run(base) == 0
    assert run(base | {"verdict": "accept"}) == 1  # a must_fix forbids accept
    assert "accept with must_fix" in capsys.readouterr().err
    assert run(base | {"findings": []}) == 1  # a reject needs a finding
    assert run(base | {"paper": "pmid:90000101"}) == 1
    assert run(base | {"card": "another-card"}) == 1
    assert run(base | {"findings": [must_fix | {"operation": 0}]}) == 1  # there are no operations yet
    assert run(base, "--revised") == 1  # --pre takes no revised attempt
    assert run(base | {"verdict": "accept", "findings": []}) == 0
    assert corr.main("record-review", SLUG, "90000101", "--pre", "--round", "C1", "--run-dir", str(corr.dir)) == 1


# --- P3: correction-plan needs it and shows its findings -----------------------------------------------------------


def test_correction_plan_refuses_without_a_recorded_pre_review_and_names_the_steps(corr: Corr, capsys):
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir)) == 1
    err = capsys.readouterr().err
    assert "card-review-plan" in err and "--pre" in err and "record-review" in err and "--card-review --pre" in err
    assert not (corr.dir / "correction-context").exists()
    assert pre_plan(corr) == 0  # a context alone is not a recorded review
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir)) == 1
    review = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    review.parent.mkdir(exist_ok=True)
    review.write_text(json.dumps({"card": SLUG, "verdict": "accept", "findings": [], "extra": 1}), encoding="utf-8")
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir)) == 1  # not valid
    assert not (corr.dir / "correction-context").exists()


def test_correction_plan_includes_every_pre_review_finding_under_the_same_limits(corr: Corr):
    findings = [
        {
            "operation": None,
            "severity": "must_fix",
            "targets": ["studies[pmid:90000100]"],
            "problem": "The label Fukuda is not in the record.",
            "fix": "Relabel.",
        },
        {"operation": None, "severity": "advisory", "problem": "The wording is strong."},
    ]
    assert corr.pre_review("reject", findings=findings) == 0
    assert corr.plan() == 0
    text = (corr.dir / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    section = text.split("## 7. Review findings on the draft as it stands")[1]
    assert "- verdict: reject" in section
    assert "(must_fix): The label Fukuda is not in the record." in section and "- fix: Relabel." in section
    assert "(advisory): The wording is strong." in section
    assert "never add a fact" in section and "section 3" in section
    assert "## 5. The inclusion rule" in text and "## 6. The rubric" in text  # the numbering above is unchanged


def test_the_trail_records_the_pre_review_and_older_trails_still_read(corr: Corr):
    findings = [{"operation": None, "severity": "advisory", "problem": "Wording."}]
    assert corr.pre_review("accept", findings=findings) == 0 and corr.plan() == 0
    corr.round_to_audits()
    assert corr.publish() == 0
    assert corr.trail()["pre_card_review"] == {
        "verdict": "accept",
        "findings": [{"operation": None, "severity": "advisory", "problem": "Wording.", "fix": None}],
    }
    assert pipeline.correction_round_state(cfg_of(corr), SLUG) == (1, None)


def trail(**over) -> dict:
    return {"card": SLUG, "round": 1, "review": {"verdict": "accept", "findings": []}} | over


def state(c: Corr, **files: dict) -> tuple[int, int | None]:
    for name, data in files.items():
        (c.audits / f"{PUB_DATE}-{SLUG}-{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return pipeline.correction_round_state(cfg_of(c), SLUG)


def test_a_revised_trail_closes_an_older_round_but_not_one_with_a_pre_review_and_an_unused_revision(corr: Corr):
    pre = {"pre_card_review": {"verdict": "accept", "findings": []}}
    reject_card = {"card_review": {"verdict": "reject", "findings": []}}
    # the 2026-11-14 round (no pre_card_review): the revised trail closes it, as before
    older = state(corr, **{"C1-correction": trail(), "C1-correction-revised": trail(**reject_card)})
    assert older == (1, None)
    for path in corr.audits.glob("*-C1-correction*.yaml"):
        path.unlink()
    # a round with a pre-drafting review: a revised attempt rejected for the other kind leaves the second open
    first = trail(**pre, review={"verdict": "reject", "findings": []})
    assert state(corr, **{"C1-correction": first, "C1-correction-revised": trail(**pre, **reject_card)}) == (0, 1)
    (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction-revised2.yaml").write_text(
        yaml.safe_dump(trail(**pre, **reject_card)), encoding="utf-8"
    )
    assert pipeline.correction_round_state(cfg_of(corr), SLUG) == (1, None)  # the last attempt closes the round


# --- P4 / P5: three attempts, one revision per review kind ---------------------------------------------------------


def test_cr_reject_then_wcr_reject_then_a_third_attempt_that_is_accepted_goes_to_audit_and_publishes(corr: Corr):
    assert corr.plan() == 0
    attempt(corr, "", "reject")
    attempt(corr, "-revised", "accept", "reject")  # the second kind of reject opens the third attempt
    assert corr.audit_plan() == 1  # not audited
    assert corr.main("card-review-plan", SLUG, "--round", "C1", "--revised2", "--out", str(corr.dir)) == 1  # no ops
    attempt(corr, "-revised2")
    assert corr.main("card-review-plan", SLUG, "--round", "C1", "--revised2", "--out", str(corr.dir)) == 0
    names = {p.name for p in (corr.dir / "card-review-context").iterdir()}
    assert names == {f"{SLUG}-C1-pre.md", f"{SLUG}-C1-revised2.md"}
    assert corr.audit_plan() == 0
    revised2 = corr.dir / "applied" / f"{SLUG}-rC1-revised2" / f"{SLUG}.yaml"
    draft = yaml.safe_load(corr.draft.read_text(encoding="utf-8"))
    assert yaml.safe_load(revised2.read_text(encoding="utf-8"))["early_signals"] == draft["early_signals"][1:]
    corr.write_audit(whole())
    corr.write_audit(whole(), second=True)
    assert corr.publish() == 0 and corr.card.exists()
    for suffix in ("", "-revised", "-revised2"):
        assert (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction{suffix}.yaml").is_file()
    last = yaml.safe_load((corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction-revised2.yaml").read_text("utf-8"))
    assert last["audits_run"] == [f"{PUB_DATE}-{SLUG}-C1.yaml", f"{PUB_DATE}-{SLUG}-C1-second.yaml"]
    assert corr.trail()["audits_run"] == [] and last["pre_card_review"]["verdict"] == "accept"
    assert pipeline.correction_round_state(cfg_of(corr), SLUG) == (1, None)


def test_cr_reject_then_cr_reject_ends_the_round_with_no_audit(corr: Corr, capsys):
    assert corr.plan() == 0
    attempt(corr, "", "reject")
    attempt(corr, "-revised", "reject")
    assert "did not fall (1, then 1)" in apply_refused(corr, "-revised2", capsys)
    assert corr.publish() == 0
    corr.assert_held_back(
        "correction rejected in review; the decisive findings did not fall (1, then 1)", corr.pub.draft_bytes
    )
    assert "Correction rounds used: 1 of 1" in corr.report()
    assert pipeline.correction_round_state(cfg_of(corr), SLUG) == (1, None)
    assert not any("-C1.yaml" in n for n in corr.names())


def test_wcr_reject_then_wcr_reject_ends_the_round_with_no_audit(corr: Corr, capsys):
    assert corr.plan() == 0
    attempt(corr, "", "accept", "reject")
    attempt(corr, "-revised", "accept", "reject")
    assert "did not fall (1, then 1)" in apply_refused(corr, "-revised2", capsys)
    assert corr.publish() == 0
    corr.assert_held_back(
        "whole-card review rejected; the decisive findings did not fall (1, then 1)", corr.pub.draft_bytes
    )
    assert "Correction rounds used: 1 of 1" in corr.report()
    assert pipeline.correction_round_state(cfg_of(corr), SLUG) == (1, None)


def test_wcr_reject_then_cr_reject_allows_a_third_attempt_and_a_reject_of_it_ends_the_round(corr: Corr, capsys):
    assert corr.plan() == 0
    attempt(corr, "", "accept", "reject")
    attempt(corr, "-revised", "reject")
    attempt(corr, "-revised2", "reject")
    assert corr.publish() == 0
    corr.assert_held_back(
        "correction rejected in review; the decisive findings did not fall (1, then 1)", corr.pub.draft_bytes
    )
    assert pipeline.correction_round_state(cfg_of(corr), SLUG) == (1, None)
    verdicts = []
    for suffix in ("", "-revised", "-revised2"):
        path = corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction{suffix}.yaml"
        verdicts.append(yaml.safe_load(path.read_text(encoding="utf-8"))["review"]["verdict"])
    assert verdicts == ["accept", "reject", "reject"]


def test_a_third_attempt_needs_a_second_one_and_a_reject_of_a_kind_not_yet_used(corr: Corr, capsys):
    assert corr.plan() == 0
    attempt(corr, "", "reject")
    assert "needs the review of C1-revised" in apply_refused(corr, "-revised2", capsys)
    assert not (corr.dir / "checks" / f"{SLUG}-rC1-revised2.json").exists()
    attempt(corr, "-revised", "accept", "accept")  # accepted: nothing to revise
    assert "must say reject" in apply_refused(corr, "-revised2", capsys)


def test_a_publish_between_attempts_keeps_the_round_open_and_the_earlier_trails_are_not_rewritten(corr: Corr):
    assert corr.plan() == 0
    attempt(corr, "", "reject")
    attempt(corr, "-revised", "accept", "reject")
    assert corr.publish() == 0  # held back with the third attempt pending
    corr.assert_held_back(
        "whole-card review rejected; the revised attempt is pending (round C1 is not used yet)", corr.pub.draft_bytes
    )
    assert pipeline.correction_round_state(cfg_of(corr), SLUG) == (0, 1)
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir / "other")) == 1  # the round is open
    first = (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction.yaml").read_bytes()
    attempt(corr, "-revised2")
    assert corr.audit_plan() == 0
    corr.write_audit(whole())
    corr.write_audit(whole(), second=True)
    assert corr.publish() == 0 and corr.card.exists()
    assert (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction.yaml").read_bytes() == first


# --- P6: the two reopened rounds ------------------------------------------------------------------------------------


def test_only_the_named_cards_may_run_round_c2_and_oxidative_round_c3():
    assert pipeline.REOPENED_ROUNDS == {
        "oxidative-nitrosative-stress": 3,
        "small-fibre-neuropathy": 2,
        "mast-cell-activation": 2,
        "impaired-energy-production-after-exertion": 4,
        "brain-and-brainstem-mri-changes": 2,
        "orthostatic-intolerance-cerebral-blood-flow": 2,
        "hpa-axis-cortisol": 2,
        "herpesvirus-reactivation": 2,
    }
    assert pipeline.max_correction_rounds("oxidative-nitrosative-stress") == 3
    assert pipeline.max_correction_rounds("mast-cell-activation") == 2
    assert pipeline.max_correction_rounds("small-fibre-neuropathy") == 2
    assert pipeline.max_correction_rounds("any-other-card") == pipeline.MAX_CORRECTION_ROUNDS == 1


def used_c1(c: Corr) -> None:
    (c.audits / f"{PUB_DATE}-{SLUG}-C1-correction.yaml").write_text(
        yaml.safe_dump(trail(operations=[CONTESTED_LAST])), encoding="utf-8"
    )


def test_a_card_with_a_used_c1_gets_c2_only_when_it_is_one_of_the_two(corr: Corr, monkeypatch, capsys):
    used_c1(corr)
    assert corr.plan() == 1 and "gets at most 1 correction round" in capsys.readouterr().err  # another card
    assert pre_plan(corr, 2) == 1 and not corr.dir.exists()
    monkeypatch.setitem(pipeline.REOPENED_ROUNDS, SLUG, 2)
    assert corr.pre_review(k=2) == 0
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir)) == 0
    assert (corr.dir / "correction-context" / f"{SLUG}-C2.md").is_file()
    ops_file = corr.dir / "ops" / f"{SLUG}-rC2.json"
    ops_file.parent.mkdir(parents=True, exist_ok=True)
    ops_file.write_text(json.dumps(ops_data(CONTESTED_LAST)), encoding="utf-8")
    assert corr.main("apply", SLUG, str(ops_file), "--round", "C2", "--run-dir", str(corr.dir)) == 0
    assert (corr.dir / "applied" / f"{SLUG}-rC2" / f"{SLUG}.yaml").is_file()
    assert corr.main("card-review-plan", SLUG, "--pre", "--round", "C3", "--out", str(corr.dir)) == 1  # not C3
