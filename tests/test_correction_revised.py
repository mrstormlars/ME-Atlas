"""Tests for the one revised attempt after a review reject in a correction round (contract addendum 2, R1-R8).

Fictional card and agent output, temporary folders only. No network, no AI, no git.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from test_correction import CONTESTED_LAST, Corr, _loader, ops_data
from test_pipeline import SLUG, Env
from test_publish_card import PUB_DATE, Pub, whole

from me_atlas import pipeline

LATER = "2026-11-20"
EARLY_SIGNAL = {"op": "remove_paragraph", "field": "early_signals", "index": 0}
BAD = {"op": "remove_link", "to": "nowhere"}  # fails the checks


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def corr(env: Env, tmp_path: Path) -> Corr:
    c = Corr(Pub(env, tmp_path), tmp_path)
    c.hold_back()
    return c


def revised_ops(c: Corr, data: dict | None = None) -> Path:
    path = c.dir / "ops" / f"{SLUG}-rC1-revised.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ops_data(EARLY_SIGNAL) if data is None else data), encoding="utf-8")
    return path


def apply_revised(c: Corr, data: dict | None = None) -> int:
    path = revised_ops(c, data)
    return c.main("apply", SLUG, str(path), "--round", "C1", "--revised", "--run-dir", str(c.dir))


def review_revised(c: Corr, verdict: str = "accept") -> int:
    path = c.dir / "review" / f"{SLUG}-rC1-revised.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    findings = (
        []
        if verdict == "accept"
        else [{"operation": 0, "severity": "must_fix", "class": "decisive", "problem": "A problem."}]
    )
    path.write_text(json.dumps({"card": SLUG, "verdict": verdict, "findings": findings}), encoding="utf-8")
    return c.main("record-review", SLUG, "--round", "C1", "--revised", "--run-dir", str(c.dir))


def card_review_revised(c: Corr, verdict: str = "accept") -> int:
    return c.card_review(verdict, revised=True)


def first_rejected(c: Corr, ops: dict | None = None) -> None:
    assert c.plan() == 0 and c.apply(ops) == 0 and c.review("reject") == 0


def first_files(c: Corr) -> dict[str, bytes]:
    return {
        str(p.relative_to(c.dir)): p.read_bytes()
        for p in c.dir.rglob("*")
        if p.is_file()
        and "revised" not in str(p.relative_to(c.dir))
        and p.name != "log.jsonl"
        and "correction-context" not in p.parts
    }


def checks(c: Corr, name: str) -> dict:
    return json.loads((c.dir / "checks" / name).read_text(encoding="utf-8"))


def live_format_trail(c: Corr, verdict: str = "reject", date: str = PUB_DATE) -> Path:
    """A trail in the format the first version of the code wrote (the real record of a held-back correction)."""
    data = {
        "card": SLUG,
        "round": 1,
        "answered": [f"{PUB_DATE}-{SLUG}-second.yaml", f"{PUB_DATE}-{SLUG}.yaml"],
        "draft_sha256": hashlib.sha256(c.draft.read_bytes()).hexdigest(),
        "operations": [CONTESTED_LAST],
        "checks": {"passed": True, "errors": []},
        "review": {
            "verdict": verdict,
            "findings": [
                {"operation": 0, "severity": "must_fix", "class": "decisive", "problem": "A problem.", "fix": None}
            ],
        },
    }
    path = c.audits / f"{date}-{SLUG}-C1-correction.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    return path


# --- R1: the revised attempt -------------------------------------------------------------------------------


def test_a_revised_attempt_needs_a_first_attempt_rejected_in_review(corr: Corr, capsys):
    assert apply_revised(corr) == 1  # nothing applied yet
    assert "needs the first attempt's review" in capsys.readouterr().err
    assert corr.plan() == 0 and corr.apply() == 0
    assert apply_revised(corr) == 1  # no review yet
    assert corr.review("accept") == 0
    assert apply_revised(corr) == 1  # accepted: there is nothing to revise
    assert "must say reject" in capsys.readouterr().err
    assert not (corr.dir / "checks" / f"{SLUG}-rC1-revised.json").exists()


def test_the_revised_attempt_applies_to_the_draft_and_leaves_the_first_attempt_alone(corr: Corr):
    first_rejected(corr)
    before = first_files(corr)
    assert apply_revised(corr) == 0
    applied = corr.dir / "applied" / f"{SLUG}-rC1-revised" / f"{SLUG}.yaml"
    data = yaml.safe_load(applied.read_text(encoding="utf-8"))
    assert len(data["contested"]["reason"]) == 2 and data["early_signals"] == []  # the draft plus the revision only
    assert checks(corr, f"{SLUG}-rC1-revised.json")["round"] == "C1-revised"
    assert first_files(corr) == before  # nothing of the first attempt was renamed, moved or overwritten
    assert corr.draft.read_bytes() == corr.pub.draft_bytes


def test_a_revised_ops_file_must_obey_a2_and_may_not_be_applied_from_elsewhere(corr: Corr, capsys):
    first_rejected(corr)
    assert apply_revised(corr, ops_data(paper="pmid:90000101")) == 1
    assert "names no paper" in checks(corr, f"{SLUG}-rC1-revised.json")["ops_errors"][0]
    other = corr.dir / "elsewhere.json"
    other.write_text(json.dumps(ops_data(EARLY_SIGNAL)), encoding="utf-8")
    assert corr.main("apply", SLUG, str(other), "--round", "C1", "--revised", "--run-dir", str(corr.dir)) == 1
    assert "must be" in capsys.readouterr().err


def test_revised_is_only_for_a_correction_round(env: Env, capsys):
    env.prepare()
    assert env.classify() == 0
    path = env.run / "ops" / f"{SLUG}-90000101-r1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"card": SLUG, "paper": "pmid:90000101", "operations": []}), encoding="utf-8")
    assert env.cli("apply", SLUG, str(path), "--round", "1", "--revised") == 1
    assert "--revised is only for a correction round" in capsys.readouterr().err
    assert env.cli("record-review", SLUG, "90000101", "--round", "1", "--revised") == 1


def test_the_revised_review_is_validated_and_a_second_reject_ends_the_round(corr: Corr, capsys):
    first_rejected(corr)
    assert apply_revised(corr) == 0
    assert review_revised(corr, "reject") == 0
    assert "review recorded: reject" in corr.env.out[-1]
    assert corr.audit_plan() == 1 and "reviewer rejected correction round C1-revised" in capsys.readouterr().err
    assert corr.publish() == 0
    assert "Held back: correction rejected in review" in corr.report()
    assert "pending" not in corr.report()
    assert "Correction rounds used: 1 of 1" in corr.report()
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (1, None)


def test_no_third_attempt(corr: Corr, capsys):
    first_rejected(corr)
    assert apply_revised(corr) == 0
    assert apply_revised(corr) == 1
    assert "passed its checks" in capsys.readouterr().err


# --- R2: the two limits are separate and each used once ---------------------------------------------------


def test_the_check_retry_of_the_revised_attempt_is_allowed_when_the_first_did_not_use_its_own(corr: Corr, capsys):
    first_rejected(corr)
    assert apply_revised(corr, ops_data(BAD)) == 1
    assert apply_revised(corr) == 0  # the retry
    names = sorted(p.name for p in corr.dir.rglob("*revised*") if p.is_file())
    assert f"{SLUG}-rC1-revised-attempt1.json" in names  # ops and checks of the failed attempt are kept
    assert sum(1 for n in names if n == f"{SLUG}-rC1-revised-attempt1.json") == 2
    assert apply_revised(corr, ops_data(BAD)) == 1 and "both attempts" in capsys.readouterr().err
    first = checks(corr, f"{SLUG}-rC1-revised-attempt1.json")
    assert first["passed"] is False and checks(corr, f"{SLUG}-rC1-revised.json")["passed"] is True


def test_a_revised_attempt_that_fails_ends_the_round_when_the_first_attempt_used_the_retry(corr: Corr, capsys):
    assert corr.plan() == 0
    assert corr.apply(ops_data(BAD)) == 1 and corr.apply() == 0  # the check retry of the first attempt
    assert corr.review("reject") == 0
    assert apply_revised(corr, ops_data(BAD)) == 1
    assert apply_revised(corr) == 1  # no retry left
    assert "was used by the first attempt" in capsys.readouterr().err
    assert not (corr.dir / "checks" / f"{SLUG}-rC1-revised-attempt1.json").exists()
    assert corr.publish() == 0
    assert "Held back: correction failed checks:" in corr.report()
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (1, None)  # the revised trail closes the round


def test_the_check_retry_of_the_first_attempt_does_not_repeat(corr: Corr, capsys):
    assert corr.plan() == 0
    assert corr.apply(ops_data(BAD)) == 1 and corr.apply(ops_data(BAD)) == 1
    assert corr.apply() == 1 and "both attempts" in capsys.readouterr().err


# --- R3: the last attempt reaches the audit -------------------------------------------------------------


def test_audit_plan_uses_the_revised_attempt_and_refuses_while_it_is_pending(corr: Corr, capsys):
    first_rejected(corr)
    assert corr.audit_plan() == 1 and "revised attempt is pending" in capsys.readouterr().err
    assert apply_revised(corr) == 0
    assert corr.audit_plan() == 1 and "no valid review" in capsys.readouterr().err
    assert review_revised(corr) == 0 and corr.audit_plan() == 1  # the whole-card review is missing
    assert card_review_revised(corr) == 0 and corr.audit_plan() == 0
    context = (corr.dir / "audit-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert "A fictional small study reported a related change" not in context  # the revised removal
    assert "used the Fukuda criteria, which are accepted at every" in context  # the first removal is not in it
    for word in ("revised", "attempt", "rC1"):
        assert word not in context


def full_revised(c: Corr, first=None, second=None) -> None:
    first_rejected(c)
    assert apply_revised(c) == 0 and review_revised(c) == 0 and card_review_revised(c) == 0 and c.audit_plan() == 0
    c.write_audit(first if first is not None else whole())
    c.write_audit(second if second is not None else whole(), second=True)


def test_publish_after_a_revised_attempt_publishes_its_text_and_writes_both_trails(corr: Corr):
    full_revised(corr)
    assert corr.publish() == 0
    data = yaml.safe_load(corr.card.read_text(encoding="utf-8"))
    assert data["early_signals"] == [] and len(data["contested"]["reason"]) == 2
    assert not corr.draft.exists()
    [entry] = yaml.safe_load(corr.pub.log.read_text(encoding="utf-8"))
    assert entry["change"] == "First publication at level 2 after correction round 1"
    assert corr.names() == sorted(
        [
            f"{PUB_DATE}-{SLUG}.yaml",
            f"{PUB_DATE}-{SLUG}-second.yaml",
            f"{PUB_DATE}-{SLUG}-C1.yaml",
            f"{PUB_DATE}-{SLUG}-C1-second.yaml",
            f"{PUB_DATE}-{SLUG}-C1-correction.yaml",
            f"{PUB_DATE}-{SLUG}-C1-correction-revised.yaml",
        ]
    )
    first = corr.trail()
    revised = yaml.safe_load((corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction-revised.yaml").read_text("utf-8"))
    # the first attempt was rejected in the correction review, so it has no whole-card review (no card_review key)
    assert list(revised) == [*list(first)[:-1], "card_review", "audits_run"]
    assert first["review"]["verdict"] == "reject" and first["audits_run"] == []
    assert first["operations"] == [CONTESTED_LAST] and revised["operations"] == [EARLY_SIGNAL]
    assert revised["review"] == {"verdict": "accept", "findings": []} and revised["checks"]["passed"] is True
    assert revised["draft_sha256"] == first["draft_sha256"]


def test_audits_that_reject_the_revised_text_hold_the_card_back(corr: Corr):
    full_revised(corr, whole("reject"), whole("reject"))
    assert corr.publish() == 0
    assert corr.draft.read_bytes() == corr.pub.draft_bytes and not corr.card.exists()
    assert "Held back: both audits decided reject" in corr.report()
    assert "Correction rounds used: 1 of 1" in corr.report()


# --- R5: publish-card while the round is open ---------------------------------------------------------------


def test_publish_during_an_open_round_holds_back_writes_the_first_trail_and_does_not_count_the_round(corr: Corr):
    first_rejected(corr)
    assert corr.publish() == 0
    report = corr.report()
    assert (
        "Held back: correction rejected in review; the revised attempt is pending (round C1 is not used yet)" in report
    )
    assert "Correction rounds used" not in report
    assert corr.draft.read_bytes() == corr.pub.draft_bytes and not corr.card.exists() and not corr.pub.log.exists()
    assert corr.names() == sorted(
        [f"{PUB_DATE}-{SLUG}.yaml", f"{PUB_DATE}-{SLUG}-second.yaml", f"{PUB_DATE}-{SLUG}-C1-correction.yaml"]
    )
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (0, 1)


def test_the_round_then_continues_and_the_first_trail_is_not_written_again(corr: Corr):
    first_rejected(corr)
    assert corr.publish() == 0
    trail = corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction.yaml"
    before = trail.read_bytes()
    assert apply_revised(corr) == 0 and review_revised(corr) == 0 and card_review_revised(corr) == 0
    assert corr.audit_plan() == 0
    corr.write_audit(whole())
    corr.write_audit(whole(), second=True)
    assert corr.publish(date=LATER) == 0
    assert corr.card.exists()
    assert trail.read_bytes() == before
    assert not (corr.audits / f"{LATER}-{SLUG}-C1-correction.yaml").exists()
    assert (corr.audits / f"{LATER}-{SLUG}-C1-correction-revised.yaml").is_file()
    assert (corr.audits / f"{LATER}-{SLUG}-C1.yaml").is_file()


# --- R6 / R7: the real trail of the first version of the code ----------------------------------------------


def test_a_trail_in_the_format_of_the_first_version_is_an_open_round_and_the_run_continues(corr: Corr, capsys):
    first_rejected(corr)
    trail = live_format_trail(corr)
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (0, 1)
    other = corr.dir.parent / "other"
    assert corr.main("correction-plan", SLUG, "--out", str(other)) == 1
    assert "round C1 is open: the revised attempt is pending" in capsys.readouterr().err
    assert not other.exists()
    assert apply_revised(corr) == 0 and review_revised(corr) == 0 and card_review_revised(corr) == 0
    assert corr.audit_plan() == 0
    corr.write_audit(whole())
    corr.write_audit(whole(), second=True)
    before = trail.read_bytes()
    assert corr.publish(date=LATER) == 0
    assert trail.read_bytes() == before  # it matches the first attempt in the run folder: left as it is
    assert not (corr.audits / f"{LATER}-{SLUG}-C1-correction.yaml").exists()
    assert corr.card.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(card="another-card"),
        lambda d: d.update(round=2),
        lambda d: d.update(draft_sha256="0" * 64),
        lambda d: d.update(operations=[EARLY_SIGNAL]),
        lambda d: d.update(review={"verdict": "accept", "findings": []}),
    ],
)
def test_an_existing_first_trail_that_differs_from_the_run_folder_refuses_and_writes_nothing(corr: Corr, mutate):
    first_rejected(corr)
    trail = live_format_trail(corr)
    data = yaml.safe_load(trail.read_text(encoding="utf-8"))
    mutate(data)
    trail.write_text(yaml.safe_dump(data), encoding="utf-8")
    names = corr.names()
    assert corr.publish() == 1
    assert corr.names() == names and not (corr.dir / "publication-report.md").exists()
    assert corr.draft.exists() and not corr.card.exists()


def test_an_existing_revised_trail_refuses(corr: Corr, capsys):
    full_revised(corr)
    (corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction-revised.yaml").write_text(f"card: {SLUG}\n", encoding="utf-8")
    assert corr.publish(date=LATER) == 1
    assert "is not allowed" in capsys.readouterr().err  # a revised trail closes the round, whatever its date
    assert corr.draft.exists() and not corr.card.exists()


def state_of(env: Env, tmp_path: Path, **trails: dict | str) -> tuple[int, int | None]:
    audits = env.root / "audits"
    audits.mkdir(exist_ok=True)
    for name, content in trails.items():
        text = content if isinstance(content, str) else yaml.safe_dump(content)
        (audits / f"2026-11-14-{SLUG}-{name}.yaml").write_text(text, encoding="utf-8")
    cfg = pipeline.Config(tmp_path / "d", env.cards, env.drafts, env.cache, pipeline.DEFAULT_SPEC, audits_dir=audits)
    return pipeline.correction_round_state(cfg, SLUG)


def trail_data(verdict: object, **over) -> dict:
    return {"card": SLUG, "round": 1, "review": {"verdict": verdict, "findings": []}} | over


@pytest.mark.parametrize(
    "files, expected",
    [
        ({}, (0, None)),
        ({"C1-correction": trail_data("accept")}, (1, None)),
        ({"C1-correction": trail_data(None)}, (1, None)),  # the checks failed: no revised attempt is possible
        ({"C1-correction": trail_data("reject")}, (0, 1)),  # open
        ({"C1-correction": trail_data("reject"), "C1-correction-revised": trail_data("accept")}, (1, None)),
        ({"C1-correction": {"card": SLUG, "round": 1}}, (1, None)),  # undecidable: used
        ({"C1-correction": {"card": SLUG, "review": "unreadable"}}, (1, None)),
        ({"C1-correction-revised": trail_data("reject")}, (1, None)),
    ],
)
def test_round_counting_from_the_trails(env: Env, tmp_path: Path, files, expected):
    assert state_of(env, tmp_path, **files) == expected


# --- R8: the draft must be unchanged -----------------------------------------------------------------------


def test_a_changed_draft_refuses_the_revised_attempt_and_the_publication(corr: Corr, capsys):
    first_rejected(corr)
    original = corr.draft.read_bytes()
    changed = original.replace(b"year: 2020", b"year: 2019")
    corr.draft.write_bytes(changed)
    assert apply_revised(corr) == 1
    assert "not the one the first attempt was applied to" in capsys.readouterr().err
    assert not (corr.dir / "checks" / f"{SLUG}-rC1-revised.json").exists()
    corr.draft.write_bytes(original)
    assert apply_revised(corr) == 0 and review_revised(corr) == 0
    corr.draft.write_bytes(changed)
    names = corr.names()
    assert corr.publish() == 1
    assert "not the one the first attempt was applied to" in capsys.readouterr().err
    assert corr.names() == names


def test_a_trail_with_another_draft_sha_refuses_the_revised_attempt(corr: Corr, capsys):
    first_rejected(corr)
    trail = live_format_trail(corr)
    data = yaml.safe_load(trail.read_text(encoding="utf-8"))
    data["draft_sha256"] = "0" * 64
    trail.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert apply_revised(corr) == 1
    assert "sha256 differs" in capsys.readouterr().err


def _cfg(c: Corr) -> pipeline.Config:
    return pipeline.Config(c.dir, c.env.cards, c.env.drafts, c.env.cache, pipeline.DEFAULT_SPEC, audits_dir=c.audits)


def test_the_loader_helper_is_shared():
    assert callable(_loader)
