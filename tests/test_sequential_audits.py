"""Tests for sequential whole-card audits (S1-S6) and the whole-card review gate of a correction round (W1-W3).

Fictional card, papers and agent output (tests/fixtures/pipeline), temporary folders only. No test touches the
network, an AI or git.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from test_correction import Corr, _loader, ops_data
from test_correction_revised import (
    EARLY_SIGNAL,
    apply_revised,
    card_review_revised,
    review_revised,
    state_of,
    trail_data,
)
from test_pipeline import FIXTURES, SLUG, Env
from test_publish_card import PUB_DATE, Pub, whole

from me_atlas import pipeline

INVALID_QUOTE = "A sentence that is not in the cached record."
CLEAN_FIRST = f"{PUB_DATE}-{SLUG}.yaml"
CLEAN_SECOND = f"{PUB_DATE}-{SLUG}-second.yaml"


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def pub(env: Env, tmp_path: Path) -> Pub:
    return Pub(env, tmp_path)


@pytest.fixture
def corr(env: Env, tmp_path: Path) -> Corr:
    c = Corr(Pub(env, tmp_path), tmp_path)
    c.hold_back()
    return c


def bad(**over) -> dict:
    data = whole()
    data["parts"][0]["evidence"][0]["quote"] = INVALID_QUOTE
    return data | over


def fail_record(pub: Pub, times: int, second: bool = False) -> Path:
    """Record the first audit (whole-card, first publication) so that it fails validation ``times`` times."""
    pub.plan()
    path = pub.write(bad(), "-second" if second else "")
    for i in range(times):
        if i:
            pub.write(bad(), "-second" if second else "")
        args = ["record-audit", "--card", SLUG, "--file", str(path), "--out", str(pub.dir)]
        assert pub.main(*args, *(["--retry"] if i else [])) == 1
    return path


# --- S1, S2: a single valid first reject is a complete outcome ---------------------------------------------


def test_a_first_reject_alone_holds_the_card_back_and_copies_the_record(pub: Pub):
    pub.audits_of_card(whole("reject"), None)
    assert pub.publish() == 0
    pub.assert_held_back(pipeline.SEQUENTIAL_REJECT)
    assert pipeline.SEQUENTIAL_REJECT == "the first audit decided reject; no second audit was run (sequential audits)"
    assert pub.audit_names() == [CLEAN_FIRST]


def test_a_second_record_after_a_first_reject_is_not_an_error(pub: Pub):
    pub.audits_of_card(whole("reject"), whole("accept"))
    assert pub.publish() == 0
    pub.assert_held_back("the two audits differ: one decided accept, the other reject")
    assert pub.audit_names() == sorted([CLEAN_FIRST, CLEAN_SECOND])


def test_two_rejects_still_say_both_audits_decided_reject(pub: Pub):
    pub.audits_of_card(whole("reject"), whole("reject"))
    assert pub.publish() == 0
    pub.assert_held_back("both audits decided reject")
    assert pub.audit_names() == sorted([CLEAN_FIRST, CLEAN_SECOND])


@pytest.mark.parametrize("first", ["accept", "accept_lower"])
def test_a_first_audit_that_is_not_a_reject_still_needs_a_second_audit(pub: Pub, first):
    pub.audits_of_card(whole(first), None)
    assert pub.publish() == 0
    pub.assert_held_back(f"no valid second audit: no audit record {SLUG}-second.yaml")
    assert pub.audit_names() == [CLEAN_FIRST]


def test_publishing_still_needs_two_agreeing_valid_records(pub: Pub):
    pub.audits_of_card(whole(), whole())
    assert pub.publish() == 0 and pub.card.exists()


def test_a_second_reject_without_a_first_record_is_not_a_sequential_reject(pub: Pub):
    pub.audits_of_card(None, whole("reject"))
    assert pub.publish() == 0
    held = next(x for x in pub.report().splitlines() if x.startswith("Held back: "))
    assert held.startswith("Held back: one audit decided reject and the other audit record is missing or invalid")


def test_a_first_reject_alone_after_a_correction_holds_the_card_back_and_the_round_counts_as_used(corr: Corr):
    corr.round_to_audits(whole("reject"), None)
    (corr.dir / "audit" / f"{SLUG}-C1-second.yaml").unlink(missing_ok=True)
    before = corr.draft.read_bytes()
    assert corr.publish() == 0
    corr.assert_held_back(pipeline.SEQUENTIAL_REJECT, before)
    first = f"{PUB_DATE}-{SLUG}-C1.yaml"
    assert corr.names() == sorted([CLEAN_FIRST, CLEAN_SECOND, first, f"{PUB_DATE}-{SLUG}-C1-correction.yaml"])
    assert corr.trail()["audits_run"] == [first]
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (1, None)
    assert "Correction rounds used: 1 of 1" in corr.report()


def test_a_second_record_after_a_first_reject_after_a_correction_gives_the_b2_text(corr: Corr):
    corr.round_to_audits(whole("reject"), whole("accept"))
    assert corr.publish() == 0
    corr.assert_held_back("the two audits differ: one decided accept, the other reject", corr.pub.draft_bytes)
    assert corr.trail()["audits_run"] == [f"{PUB_DATE}-{SLUG}-C1.yaml", f"{PUB_DATE}-{SLUG}-C1-second.yaml"]


# --- S3: the second auditor never sees the first record -----------------------------------------------------


def test_the_audit_context_is_the_same_whether_or_not_a_first_record_exists(pub: Pub):
    pub.plan()
    context = pub.dir / "audit-context" / f"{SLUG}.md"
    alone = context.read_bytes()
    pub.write(whole("reject"))
    pub.plan()
    assert context.read_bytes() == alone
    assert "reject" not in alone.decode("utf-8").lower().split("## 3. cited records")[0].split("## 1.")[0]


def test_the_correction_audit_context_is_the_same_whether_or_not_a_first_record_exists(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review() == 0
    assert corr.audit_plan() == 0
    context = corr.dir / "audit-context" / f"{SLUG}-C1.md"
    alone = context.read_bytes()
    corr.write_audit(whole("reject"))
    assert corr.audit_plan() == 0
    assert context.read_bytes() == alone


# --- S4: an invalid first record ----------------------------------------------------------------------------


def test_a_first_record_that_failed_twice_holds_the_card_back_and_is_kept_as_invalid(pub: Pub):
    path = fail_record(pub, 2)
    final = path.with_name(path.stem + ".invalid-2.yaml")
    assert final.is_file() and not path.exists()
    assert pub.publish() == 0
    pub.assert_held_back(pipeline.FIRST_INVALID_TWICE)
    assert pipeline.FIRST_INVALID_TWICE == "the first audit record failed validation twice; no second audit was run"
    kept = pub.audits / f"{PUB_DATE}-{SLUG}-invalid.yaml"
    assert pub.audit_names() == [kept.name] and kept.read_bytes() == final.read_bytes()


def test_the_invalid_copy_counts_as_an_audit_record_for_the_guard_and_correction_plan(pub: Pub, capsys):
    path = fail_record(pub, 2)
    assert pub.publish() == 0
    cfg = pipeline.Config(pub.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC)
    cfg = pipeline.Config(
        pub.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC, audits_dir=pub.audits
    )
    assert [p.name for p in pipeline.whole_card_audit_files(cfg, SLUG)] == [f"{PUB_DATE}-{SLUG}-invalid.yaml"]
    assert pub.main("audit-plan", "--card", SLUG, "--out", str(pub.dir / "again")) == 1
    assert "correction-plan" in capsys.readouterr().err
    assert pub.publish() == 1  # the same draft is not audited again
    assert path.with_name(path.stem + ".invalid-2.yaml").is_file()
    plan = pub.main("correction-plan", SLUG, "--out", str(pub.dir / "c"))
    assert plan == 0
    text = (pub.dir / "c" / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert f"### {PUB_DATE}-{SLUG}-invalid.yaml" in text and "failed validation twice" in text


def test_a_first_record_that_failed_once_with_no_retry_makes_publish_card_refuse(pub: Pub, capsys):
    fail_record(pub, 1)
    assert pub.publish() == 1
    assert "format retry is pending" in capsys.readouterr().err
    assert not (pub.dir / "publication-report.md").exists() and not pub.audits.exists() and not pub.card.exists()
    assert pub.draft.read_bytes() == pub.draft_bytes


def test_a_first_record_that_failed_twice_and_a_valid_second_keep_the_b2_text_and_copy_no_invalid_record(pub: Pub):
    fail_record(pub, 2)
    pub.write(whole(), "-second")
    assert pub.publish() == 0
    assert "the record " + SLUG + ".yaml failed validation twice" in pub.report()
    assert pub.audit_names() == [CLEAN_SECOND]


def test_an_existing_invalid_copy_is_never_overwritten(pub: Pub, capsys):
    fail_record(pub, 2)
    pub.audits.mkdir()
    target = pub.audits / f"{PUB_DATE}-{SLUG}-invalid.yaml"
    target.write_text("earlier: record\n", encoding="utf-8")
    assert pub.publish() == 1
    assert "never overwritten" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "earlier: record\n"


@pytest.mark.parametrize("content", ["card: [unclosed\n", "just text\n", "card: another-card\n"])
def test_an_unreadable_invalid_record_is_kept_in_a_form_the_guard_can_read(pub: Pub, content):
    pub.plan()
    path = pub.write(content)
    assert pub.main("record-audit", "--card", SLUG, "--file", str(path), "--out", str(pub.dir)) == 1
    pub.write(content)
    assert pub.main("record-audit", "--card", SLUG, "--file", str(path), "--out", str(pub.dir), "--retry") == 1
    assert pub.publish() == 0
    kept = pub.audits / f"{PUB_DATE}-{SLUG}-invalid.yaml"
    data = yaml.safe_load(kept.read_text(encoding="utf-8"))
    assert data["card"] == SLUG and data["raw_text"] == content


def test_a_round_c_first_record_that_failed_twice_is_kept_and_the_round_counts_as_used(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review() == 0
    assert corr.audit_plan() == 0
    path = corr.write_audit(bad())
    for extra in ([], ["--retry"]):
        corr.write_audit(bad())
        args = ["record-audit", "--card", SLUG, "--round", "C1", "--file", str(path), "--out", str(corr.dir)]
        assert corr.main(*args, *extra) == 1
    before = corr.draft.read_bytes()
    assert corr.publish() == 0
    corr.assert_held_back(pipeline.FIRST_INVALID_TWICE, before)
    kept = f"{PUB_DATE}-{SLUG}-C1-invalid.yaml"
    assert kept in corr.names()
    assert corr.trail()["audits_run"] == [kept]
    assert corr.trail()["answered"] == sorted([CLEAN_FIRST, CLEAN_SECOND])
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (1, None)


def test_a_round_c_first_record_that_failed_once_makes_publish_card_refuse(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review() == 0
    assert corr.audit_plan() == 0
    path = corr.write_audit(bad())
    assert corr.main("record-audit", "--card", SLUG, "--round", "C1", "--file", str(path), "--out", str(corr.dir)) == 1
    names = corr.names()
    assert corr.publish() == 1
    assert "format retry is pending" in capsys.readouterr().err
    assert corr.names() == names and not (corr.dir / "publication-report.md").exists()


# --- S5: the round count and the trail ------------------------------------------------------------------------


def _cfg(c: Corr) -> pipeline.Config:
    return pipeline.Config(c.dir, c.env.cards, c.env.drafts, c.env.cache, pipeline.DEFAULT_SPEC, audits_dir=c.audits)


@pytest.mark.parametrize(
    "files, expected",
    [
        ({"C1-correction": trail_data("accept")}, (1, None)),  # an old-format trail: no audits_run, no card_review
        ({"C1-correction": trail_data("accept", audits_run=["x-C1.yaml"])}, (1, None)),
        ({"C1-correction": trail_data("accept", audits_run=[])}, (1, None)),
        ({"C1-correction": trail_data("accept", card_review={"verdict": "accept", "findings": []})}, (1, None)),
        ({"C1-correction": trail_data("accept", card_review={"verdict": "reject", "findings": []})}, (0, 1)),
        (
            {
                "C1-correction": trail_data("accept", card_review={"verdict": "reject", "findings": []}),
                "C1-correction-revised": trail_data("accept"),
            },
            (1, None),
        ),
        ({"C1-correction": trail_data("accept", card_review="unreadable")}, (1, None)),
    ],
)
def test_the_round_count_reads_trails_with_and_without_the_new_keys(env: Env, tmp_path: Path, files, expected):
    assert state_of(env, tmp_path, **files) == expected


# --- S6: correction-plan shows a single-reject card like a two-audit card -----------------------------------


def test_correction_plan_presents_a_single_reject_card_like_any_other(pub: Pub):
    pub.audits_of_card(whole("reject"), None)
    assert pub.publish() == 0
    assert pub.main("correction-plan", SLUG, "--out", str(pub.dir / "c")) == 0
    text = (pub.dir / "c" / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert f"### {CLEAN_FIRST}" in text and "- decision: reject" in text and CLEAN_SECOND not in text


def test_correction_plan_labels_an_invalid_record_and_shows_its_errors_when_the_file_has_them(pub: Pub):
    pub.audits.mkdir()
    name = f"{PUB_DATE}-{SLUG}-invalid.yaml"
    (pub.audits / name).write_text(yaml.safe_dump({"card": SLUG, "validation_errors": ["quote not found"]}), "utf-8")
    assert pub.main("correction-plan", SLUG, "--out", str(pub.dir / "c")) == 0
    text = (pub.dir / "c" / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert f"### {name}" in text and "failed validation twice" in text and "quote not found" in text
    other = pub.dir / "d"
    (pub.audits / name).write_text(yaml.safe_dump({"card": SLUG}), encoding="utf-8")
    assert pub.main("correction-plan", SLUG, "--out", str(other)) == 0
    text = (other / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert f"### {name}" in text and "failed validation twice" in text and "Validation errors" not in text


def test_the_invalid_suffixes_are_known_audit_files_and_nothing_longer(pub: Pub):
    pub.audits.mkdir()
    cfg = pipeline.Config(
        pub.dir, pub.env.cards, pub.env.drafts, pub.env.cache, pipeline.DEFAULT_SPEC, audits_dir=pub.audits
    )
    for suffix in ("-invalid", "-C1-invalid", "-invalidx", "-C1-invalid-2", "-L-invalid"):
        (pub.audits / f"2026-11-13-{SLUG}{suffix}.yaml").write_text(f"card: {SLUG}\n", encoding="utf-8")
    found = [p.name for p in pipeline.whole_card_audit_files(cfg, SLUG)]
    assert found == sorted(f"2026-11-13-{SLUG}{s}.yaml" for s in ("-invalid", "-C1-invalid"))


# --- W1: card-review-plan and record-review --card-review ------------------------------------------------------


def cache_fulltext(env: Env) -> str:
    """Cache a full text (with a marker) for the carrier study pmid:90000100, as Europe PMC's cache holds it."""
    folder = env.cache / "europepmc"
    folder.mkdir(parents=True, exist_ok=True)
    hit = {"id": "90000100", "pmid": "90000100", "pmcid": "PMC9000100", "isOpenAccess": "Y", "inPMC": "Y"}
    (folder / "90000100.json").write_text(json.dumps({"resultList": {"result": [hit]}}), encoding="utf-8")
    shutil.copy(FIXTURES / "agent" / "fulltext-90000101.xml", folder / "PMC9000100.xml")
    return "FULLTEXT-TAIL-MARKER"


def card_review_plan(c: Corr, *extra: str) -> int:
    return c.main("card-review-plan", SLUG, "--round", "C1", "--out", str(c.dir), *extra)


def context_text(c: Corr, name: str = f"{SLUG}-C1.md") -> str:
    return (c.dir / "card-review-context" / name).read_text(encoding="utf-8")


def test_card_review_plan_writes_the_context_without_a_full_text(corr: Corr):
    marker = cache_fulltext(corr.env)
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0
    assert card_review_plan(corr) == 0
    text = context_text(corr)
    corrected = (corr.dir / "applied" / f"{SLUG}-rC1" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(corrected)["level"] == 2 and "level: 2" in text
    assert "# a comment between two paragraphs" not in text  # comments are stripped
    assert "### pmid:90000100" in text and "### pmid:90000104" in text
    assert str(corr.env.cache / "pubmed" / "90000100.xml") in text
    assert f"cached, `{corr.env.cache / 'europepmc' / 'PMC9000100.xml'}`" in text  # a cached full text is named
    assert "- record: not usable (missing)" in text and "full text: none cached" in text
    assert marker not in text and "Not truncated" not in text  # and not embedded
    assert "Evidence ladder" in text and "## 4. The checklist" in text
    for part in ("Case-definition labels", "Links", "Claims", "Contested mark", "Names"):
        assert part in text
    assert str(corr.dir / "review" / f"{SLUG}-card-C1.json") in text
    assert "# Correction context" not in text and "audit" not in text.lower().split("## 3.")[0]


def test_the_card_review_context_is_bounded_by_the_number_of_cited_studies(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0
    assert card_review_plan(corr) == 0
    plain = len(context_text(corr))
    cache_fulltext(corr.env)
    assert card_review_plan(corr) == 0
    with_full = len(context_text(corr))
    full_xml = (FIXTURES / "agent" / "fulltext-90000101.xml").stat().st_size
    assert with_full - plain < 200 < full_xml  # naming a cached full text adds a path, not the text
    studies = len(yaml.safe_load(corr.draft.read_text(encoding="utf-8"))["studies"])
    assert plain < 30_000 + 400 * studies


def test_card_review_plan_for_a_revised_attempt_names_its_files(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review("reject") == 0
    assert apply_revised(corr) == 0 and review_revised(corr) == 0
    assert card_review_plan(corr, "--revised") == 0
    text = context_text(corr, f"{SLUG}-C1-revised.md")
    assert str(corr.dir / "review" / f"{SLUG}-card-C1-revised.json") in text
    assert yaml.safe_load(text.split("```yaml\n")[1].split("```")[0])["early_signals"] == []


def test_card_review_plan_refuses_without_checks_review_or_a_rejected_first_attempt(corr: Corr, capsys):
    assert card_review_plan(corr) == 1 and "no checks" in capsys.readouterr().err
    assert corr.plan() == 0 and corr.apply(ops_data({"op": "remove_link", "to": "nowhere"})) == 1
    assert card_review_plan(corr) == 1 and "did not pass its checks" in capsys.readouterr().err
    assert corr.apply(ops_data()) == 0
    assert card_review_plan(corr) == 1 and "no valid review" in capsys.readouterr().err
    assert corr.review("reject") == 0
    assert card_review_plan(corr) == 1 and "reviewer rejected" in capsys.readouterr().err
    assert not (corr.dir / "card-review-context").exists()


def test_card_review_plan_refuses_a_revised_attempt_when_the_first_was_not_rejected(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0
    assert apply_revised(corr) == 1  # not allowed either
    path = corr.dir / "checks" / f"{SLUG}-rC1-revised.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert card_review_plan(corr, "--revised") == 1
    assert not (corr.dir / "card-review-context").exists()


def test_record_review_validates_the_card_review_file(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0
    assert corr.card_review() == 0
    assert "whole-card review recorded: accept, 0 finding(s)" in corr.env.out[-1]
    path = corr.dir / "review" / f"{SLUG}-card-C1.json"
    must_fix = {"operation": None, "severity": "must_fix", "problem": "A link that its source does not state."}

    def run(data: dict) -> int:
        path.write_text(json.dumps(data), encoding="utf-8")
        return corr.main("record-review", SLUG, "--card-review", "--round", "C1", "--run-dir", str(corr.dir))

    base = {"card": SLUG, "paper": None, "verdict": "reject", "findings": [must_fix]}
    assert run(base) == 0
    assert run(base | {"verdict": "accept"}) == 1  # a must_fix forbids accept
    assert "accept with must_fix" in capsys.readouterr().err
    assert run(base | {"findings": []}) == 1  # a reject needs a finding
    assert run(base | {"card": "another-card"}) == 1
    assert run(base | {"paper": "pmid:90000101"}) == 1
    assert run(base | {"findings": [must_fix | {"operation": 9}]}) == 1  # out of range of the operations file
    assert corr.main("record-review", SLUG, "--card-review", "--round", "1", "--run-dir", str(corr.dir)) == 1
    assert corr.main("record-review", SLUG, "90000101", "--card-review", "--round", "C1") == 1


def test_a_card_review_that_does_not_validate_does_not_count(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0
    path = corr.dir / "review" / f"{SLUG}-card-C1.json"
    path.write_text(json.dumps({"card": SLUG, "verdict": "accept", "findings": [], "extra": 1}), encoding="utf-8")
    assert corr.audit_plan() == 1 and "no valid whole-card review" in capsys.readouterr().err
    path.write_text("not json", encoding="utf-8")
    assert corr.audit_plan() == 1


# --- W2: the gate and the feedback ------------------------------------------------------------------------------


def test_the_correction_review_alone_no_longer_lets_a_correction_go_to_audit(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0
    assert corr.audit_plan() == 1
    assert "no valid whole-card review" in capsys.readouterr().err
    assert not (corr.dir / "audit-context").exists()
    assert corr.card_review() == 0 and corr.audit_plan() == 0


def test_a_whole_card_review_reject_blocks_the_audit_and_allows_the_revised_attempt(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review("reject") == 0
    assert corr.audit_plan() == 1 and "whole-card review rejected correction round C1" in capsys.readouterr().err
    assert apply_revised(corr) == 0  # a card-review reject is a trigger, though the correction review accepted
    assert review_revised(corr) == 0 and card_review_revised(corr) == 0 and corr.audit_plan() == 0


def test_a_revised_attempt_is_refused_when_both_reviews_of_the_first_attempt_accept(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review() == 0
    assert apply_revised(corr) == 1
    assert "must say reject" in capsys.readouterr().err


def test_publish_card_holds_back_without_a_whole_card_review_and_still_copies_the_audits(corr: Corr):
    corr.round_to_audits()
    (corr.dir / "review" / f"{SLUG}-card-C1.json").unlink()
    assert corr.publish() == 0
    corr.assert_held_back(
        "whole-card review missing: no valid whole-card review of the last attempt was recorded", corr.pub.draft_bytes
    )
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (1, None)
    assert "card_review" not in corr.trail()


def test_a_first_attempt_card_review_reject_leaves_the_round_open_and_the_trail_records_it(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review("reject") == 0
    assert corr.publish() == 0
    corr.assert_held_back(
        "whole-card review rejected; the revised attempt is pending (round C1 is not used yet)", corr.pub.draft_bytes
    )
    assert "Correction rounds used" not in corr.report()
    assert corr.trail()["card_review"] == {
        "verdict": "reject",
        "findings": [{"operation": None, "severity": "must_fix", "problem": "A problem.", "fix": None}],
    }
    assert corr.trail()["audits_run"] == []
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (0, 1)
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir / "other")) == 1  # the round is open


def test_a_card_review_reject_with_the_revised_attempt_used_ends_the_round_with_no_audit(corr: Corr):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review("reject") == 0
    assert apply_revised(corr) == 0 and review_revised(corr) == 0 and card_review_revised(corr, "reject") == 0
    assert corr.publish() == 0
    corr.assert_held_back("whole-card review rejected; the revised attempt is used", corr.pub.draft_bytes)
    assert "Correction rounds used: 1 of 1" in corr.report()
    assert not corr.pub.log.exists()
    names = corr.names()
    assert not any("-C1.yaml" in n or "-C1-second" in n for n in names)  # no audit was run or copied
    revised = yaml.safe_load((corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction-revised.yaml").read_text("utf-8"))
    assert revised["card_review"]["verdict"] == "reject" and revised["audits_run"] == []
    assert corr.trail()["card_review"]["verdict"] == "reject"
    assert pipeline.correction_round_state(_cfg(corr), SLUG) == (1, None)
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir / "other")) == 1


def test_audit_after_a_card_review_reject_of_a_revised_attempt_is_refused(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review("reject") == 0
    assert apply_revised(corr) == 0 and review_revised(corr) == 0 and card_review_revised(corr, "reject") == 0
    assert (
        corr.audit_plan() == 1 and "whole-card review rejected correction round C1-revised" in capsys.readouterr().err
    )


def test_the_full_path_through_a_card_review_reject_and_a_revised_attempt_publishes_and_records_both_reviews(
    corr: Corr,
):
    assert corr.plan() == 0 and corr.apply() == 0 and corr.review() == 0 and corr.card_review("reject") == 0
    assert apply_revised(corr, ops_data(EARLY_SIGNAL)) == 0
    assert review_revised(corr) == 0 and card_review_revised(corr) == 0 and corr.audit_plan() == 0
    corr.write_audit(whole())
    corr.write_audit(whole(), second=True)
    assert corr.publish() == 0
    assert corr.card.exists() and not corr.draft.exists()
    first = corr.trail()
    revised = yaml.safe_load((corr.audits / f"{PUB_DATE}-{SLUG}-C1-correction-revised.yaml").read_text("utf-8"))
    assert first["card_review"]["verdict"] == "reject" and first["audits_run"] == []  # the audits belong to the last
    assert revised["card_review"] == {"verdict": "accept", "findings": []}
    assert revised["audits_run"] == [f"{PUB_DATE}-{SLUG}-C1.yaml", f"{PUB_DATE}-{SLUG}-C1-second.yaml"]


def test_the_first_publication_has_no_whole_card_review_gate(pub: Pub):
    pub.audits_of_card(whole(), whole())
    assert pub.publish() == 0 and pub.card.exists()


def test_the_loader_helper_is_shared():
    assert callable(_loader)
