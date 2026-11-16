"""Tests for up to three check retries per correction round (DECISIONS 2026-11-16): the per-round count, the kept
files, the errors file, the limit text, and the extra round of the energy card.

Fictional card and agent output, temporary folders only. No network, no AI, no git.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_correction import Corr, ops_data
from test_correction_revised import BAD, _cfg, apply_revised, checks, env, first_rejected  # noqa: F401
from test_pipeline import SLUG
from test_publish_card import Pub

from me_atlas import pipeline


@pytest.fixture
def corr(env, tmp_path: Path) -> Corr:  # noqa: F811
    c = Corr(Pub(env, tmp_path), tmp_path)
    c.hold_back()
    return c


def names(c: Corr, folder: str) -> list[str]:
    return sorted(p.name for p in (c.dir / folder).iterdir())


def errors_text(c: Corr, tag: str) -> str:
    return (c.dir / "checks" / f"{SLUG}-r{tag}-errors.md").read_text(encoding="utf-8")


def test_three_failures_then_a_pass_on_the_fourth_try_keeps_every_try(corr: Corr, capsys):
    assert corr.plan() == 0
    for _ in range(3):
        assert corr.apply(ops_data(BAD)) == 1
    assert corr.apply() == 0
    assert pipeline.MAX_CHECK_RETRIES == 3
    assert pipeline._check_retries_used(_cfg(corr), SLUG, "C1") == 3
    stem = f"{SLUG}-rC1"
    assert names(corr, "ops") == [f"{stem}-attempt{i}.json" for i in (1, 2, 3)] + [f"{stem}.json"]
    kept = [f"{stem}-attempt{i}{ext}" for i in (1, 2, 3) for ext in ("-errors.md", ".json")]
    assert names(corr, "checks") == sorted(kept + [f"{stem}.json"])
    assert [checks(corr, f"{stem}-attempt{i}.json")["attempt"] for i in (1, 2, 3)] == [1, 2, 3]
    assert checks(corr, f"{stem}.json")["passed"] is True and checks(corr, f"{stem}.json")["attempt"] == 4
    assert "Check retries left in round C1: 3 of 3." in (corr.dir / "checks" / f"{stem}-attempt1-errors.md").read_text(
        encoding="utf-8"
    )
    assert "Check retries left in round C1: 1 of 3." in (corr.dir / "checks" / f"{stem}-attempt3-errors.md").read_text(
        encoding="utf-8"
    )
    assert not (corr.dir / "checks" / f"{stem}-errors.md").exists()  # the passing try writes none


def test_a_fourth_failure_refuses_a_further_apply_and_holds_the_round_back_with_the_limit(corr: Corr, capsys):
    assert corr.plan() == 0
    for _ in range(4):
        assert corr.apply(ops_data(BAD)) == 1
    assert "none (all 3 are used)" in errors_text(corr, "C1")
    before = (corr.dir / "checks" / f"{SLUG}-rC1.json").read_bytes()
    assert corr.apply(ops_data(BAD)) == 1
    assert "all 3 check retries of round C1 are used" in capsys.readouterr().err
    assert (corr.dir / "checks" / f"{SLUG}-rC1.json").read_bytes() == before
    assert not (corr.dir / "ops" / f"{SLUG}-rC1-attempt4.json").exists()
    assert corr.publish() == 0
    assert "Held back: correction failed checks:" in corr.report()
    assert "; all 3 check retries of the round are used" in corr.report()


def test_a_held_back_report_names_no_limit_while_retries_are_left(corr: Corr):
    assert corr.plan() == 0
    assert corr.apply(ops_data(BAD)) == 1
    assert corr.publish() == 0
    assert "check retries of the round are used" not in corr.report()


def test_retries_are_shared_by_the_attempts_and_the_next_failure_ends_the_round(corr: Corr, capsys):
    assert corr.plan() == 0
    assert corr.apply(ops_data(BAD)) == 1 and corr.apply(ops_data(BAD)) == 1 and corr.apply() == 0  # two used by C1
    assert corr.review("reject") == 0
    cfg = _cfg(corr)
    assert pipeline._check_retries_used(cfg, SLUG, "C1") == 2
    assert apply_revised(corr, ops_data(BAD)) == 1  # first try of C1-revised: not a retry
    assert apply_revised(corr, ops_data(BAD)) == 1  # the one retry left, the third of the round
    assert pipeline._check_retries_used(cfg, SLUG, "C1") == 3
    assert "none (all 3 are used)" in errors_text(corr, "C1-revised")
    capsys.readouterr()
    assert apply_revised(corr, ops_data(BAD)) == 1
    assert "all 3 check retries of round C1 are used" in capsys.readouterr().err
    assert corr.publish() == 0
    assert "; all 3 check retries of the round are used" in corr.report()


def test_an_old_style_single_attempt1_counts_as_one_retry(corr: Corr):
    assert corr.plan() == 0
    assert corr.apply(ops_data(BAD)) == 1
    stem = f"{SLUG}-rC1"
    # what the one-retry rule left: the first try kept as -attempt1 (no errors file), the second try fresh
    (corr.dir / "checks" / f"{stem}.json").replace(corr.dir / "checks" / f"{stem}-attempt1.json")
    (corr.dir / "checks" / f"{stem}-errors.md").unlink()
    assert pipeline._check_retries_used(_cfg(corr), SLUG, "C1") == 1
    assert corr.apply(ops_data(BAD)) == 1
    assert checks(corr, f"{stem}.json")["attempt"] == 2
    assert "Check retries left in round C1: 2 of 3." in errors_text(corr, "C1")
    assert corr.apply(ops_data(BAD)) == 1 and corr.apply(ops_data(BAD)) == 1
    assert corr.apply() == 1  # three retries used: the old attempt1 plus two


def test_the_errors_file_lists_each_error_and_omits_warnings_and_preexisting_problems(corr: Corr):
    result = {
        "ops_errors": ["operations[2] changes core_claim[0], which no finding names", "the ops file is not valid"],
        "validator": ["drafts/x.yaml: studies[1].finding: [V14] reader text holds TODO"],
        "citations": [
            {
                "study": "pmid:1",
                "code": "C10",
                "level": "ERROR",
                "message": "the number 84 is in no record",
                "preexisting": False,
            },
            {"study": "pmid:2", "code": "C3", "level": "ERROR", "message": "an old error", "preexisting": True},
            {"study": "pmid:3", "code": "C5", "level": "WARNING", "message": "a warning", "preexisting": False},
        ],
    }
    text = pipeline._check_errors_text(_cfg(corr), SLUG, "C1", "C1", result, 2)
    assert "1. rule: ops\n   location: operations[2]\n   message: operations[2] changes core_claim[0]" in text
    assert "2. rule: ops\n   location: (the ops file)\n   message: the ops file is not valid" in text
    assert (
        "3. rule: validator\n   location: studies[1].finding\n"
        "   message: drafts/x.yaml: studies[1].finding: [V14] reader text holds TODO"
    ) in text
    assert "4. rule: C10\n   location: pmid:1\n   message: the number 84 is in no record" in text
    assert "old error" not in text and "a warning" not in text and "5." not in text
    assert "Check retries left in round C1: 2 of 3." in text


def test_a_real_failed_check_writes_an_errors_file_and_prints_its_path(corr: Corr, capsys):
    assert corr.plan() == 0
    assert corr.apply(ops_data(BAD)) == 1
    text = errors_text(corr, "C1")
    assert "rule: ops" in text and "no link to 'nowhere'" in text and "Check retries left in round C1: 3 of 3." in text
    assert f"{SLUG}-rC1-errors.md" in " ".join(corr.env.out)


def test_the_energy_card_gets_a_fifth_round_and_no_sixth():
    slug = "impaired-energy-production-after-exertion"
    assert pipeline.REOPENED_ROUNDS[slug] == 5
    assert pipeline.max_correction_rounds(slug) == 5
    assert pipeline.max_correction_rounds("a-card-not-named") == pipeline.MAX_CORRECTION_ROUNDS
    assert 5 <= pipeline.max_correction_rounds(slug) < 6  # C5 is allowed, C6 is refused (k > max)
