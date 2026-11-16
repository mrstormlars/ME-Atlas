"""Tests for the link round: add links to a published card with an audit trail (``me_atlas.link_round``).

Fictional card, papers and agent output (tests/fixtures/pipeline) in tmp ``cards/`` and ``audits/`` folders.
No test touches the network, an AI or git.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from test_audit import CITED, CITED_TITLE
from test_pipeline import SLUG, Env, fulltext_loader
from test_publish_card import whole

from me_atlas import cards, pipeline

DATE = "2026-11-16"
TARGET = "other-fictional-card"
WHY = "WHY-MARKER step 1 Proposed: the review states the link."
LINK_TEXT = "A fictional review proposes that A feeds B; it was not studied directly in patients."


def link(to: str = TARGET, **over) -> dict:
    return {"to": to, "support": "proposed", "text": LINK_TEXT, "sources": [CITED], "why": WHY} | over


def proposal(*links: dict, **over) -> dict:
    return {"slug": SLUG, "layer": "mechanism", "links": list(links) or [link()]} | over


class Round:
    """A published card in tmp ``cards/`` (layer mechanism, no links) and a link-round folder DIR beside it."""

    def __init__(self, env: Env, tmp: Path):
        self.env = env
        self.dir = tmp / "links" / f"{DATE}-{SLUG}"
        self.audits = env.root / "audits"
        self.card = env.cards / f"{SLUG}.yaml"
        self.log = env.cards / pipeline.CHANGELOG_NAME
        text = (env.drafts / f"{SLUG}.yaml").read_text(encoding="utf-8")
        text = text.replace("by: ai_pair", "by: ai_audit").replace(
            "last_checked:\n", "layer: mechanism\nlinks: []\nlast_checked:\n", 1
        )
        self.card.write_text(text, encoding="utf-8", newline="\n")
        (env.drafts / f"{SLUG}.yaml").unlink()
        (env.cards / f"{TARGET}.yaml").write_text("", encoding="utf-8")  # a link target: only the file name counts
        self.card_bytes = self.card.read_bytes()

    # -- running commands --
    def main(self, *argv: str) -> int:
        return pipeline.main([*argv, *self.env.dir_args], fulltext=fulltext_loader(), out=self.env.out.append)

    def run(self, command: str, *extra: str) -> int:
        return self.main(command, SLUG, "--run-dir", str(self.dir), *extra)

    def output(self) -> str:
        return "\n".join(self.env.out)

    # -- the files of the agents --
    def propose(self, data: dict | str | None = None, n: int = 1) -> Path:
        path = self.dir / "map" / f"{SLUG}-r{n}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data or proposal()), encoding="utf-8")
        return path

    def apply(self, n: int = 1, data: dict | str | None = None) -> int:
        if data is not None or not (self.dir / "map" / f"{SLUG}-r{n}.json").exists():
            self.propose(data, n)
        return self.run("link-apply", "--round", str(n))

    def review(self, verdict: str = "accept", findings: list | None = None, n: int = 1, **over) -> Path:
        if findings is None:
            findings = (
                []
                if verdict == "accept"
                else [{"item": "links[0]", "severity": "must_fix", "problem": "REVIEW-MARKER.", "fix": "Lower it."}]
            )
        path = self.dir / "map-review" / f"{SLUG}-r{n}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"slug": SLUG, "verdict": verdict, "findings": findings} | over), encoding="utf-8")
        return path

    def record_review(self, n: int = 1) -> int:
        return self.run("record-map-review", "--round", str(n))

    def write_audit(self, data: dict | str, second: bool = False) -> Path:
        path = self.dir / "audit" / f"{SLUG}-links{'-second' if second else ''}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def accepted(self) -> None:
        """Round 1 applied and accepted by the map review, and the audit context written."""
        assert self.apply() == 0
        self.review()
        assert self.record_review() == 0
        assert self.run("link-audit-plan") == 0

    def audited(self, first: str | dict = "accept", second: str | dict | None = "accept") -> None:
        self.accepted()
        for data, second_flag in ((first, False), (second, True)):
            if data is None:
                continue
            self.write_audit(whole(data) if isinstance(data, str) else data, second_flag)
            assert self.run("record-link-audit", *(["--second"] if second_flag else [])) == 0

    def publish(self, *extra: str) -> int:
        return self.run("link-publish", "--date", DATE, *extra)

    # -- reading results --
    def report(self) -> str:
        return (self.dir / "link-report.md").read_text(encoding="utf-8")

    def changelog(self) -> list[dict]:
        return yaml.safe_load(self.log.read_text(encoding="utf-8")) if self.log.is_file() else []

    def audit_names(self) -> list[str]:
        return sorted(p.name for p in self.audits.glob("*.yaml")) if self.audits.is_dir() else []

    def trail(self) -> dict:
        return yaml.safe_load((self.audits / f"{DATE}-{SLUG}-links-trail.yaml").read_text(encoding="utf-8"))

    def assert_held_back(self, reason: str) -> None:
        assert self.card.read_bytes() == self.card_bytes and not self.log.exists()
        assert "Outcome: held back" in self.report() and f"Held back: {reason}" in self.report(), self.report()
        assert f"Held back: {reason}" in self.output()
        assert self.trail()["outcome"] == reason

    def assert_nothing_written(self) -> None:
        assert self.card.read_bytes() == self.card_bytes and not self.log.exists()
        assert not self.audits.exists() or not list(self.audits.iterdir())


@pytest.fixture
def lr(tmp_path: Path) -> Round:
    return Round(Env(tmp_path), tmp_path)


# --- C2 link-apply ---------------------------------------------------------------------------------------


def test_apply_makes_ops_applied_card_diff_and_checks_and_never_writes_cards(lr: Round):
    assert lr.apply() == 0
    ops = json.loads((lr.dir / "ops" / f"{SLUG}-r1.json").read_text(encoding="utf-8"))
    assert ops == {
        "card": SLUG,
        "paper": None,
        "operations": [{"op": "add_link", "to": TARGET, "support": "proposed", "text": LINK_TEXT, "sources": [CITED]}],
    }
    checks = json.loads((lr.dir / "checks" / f"{SLUG}-r1.json").read_text(encoding="utf-8"))
    assert checks["passed"] is True and checks["tiers"] == {"1": 0, "2": 1}
    applied = lr.dir / "applied" / f"{SLUG}-r1"
    assert yaml.safe_load((applied / f"{SLUG}.yaml").read_text(encoding="utf-8"))["links"][0]["to"] == TARGET
    diff = (applied / "changes.diff").read_text(encoding="utf-8")
    assert f"+  - to: {TARGET}" in diff and "-links: []" in diff
    assert "WHY-MARKER" not in json.dumps(ops)
    assert lr.card.read_bytes() == lr.card_bytes and not lr.log.exists()
    assert "PASSED" in lr.output()


def test_apply_refuses_when_the_card_is_not_in_cards(lr: Round, capsys):
    lr.card.unlink()
    assert lr.apply() == 1
    assert "no published card" in capsys.readouterr().err
    assert not (lr.dir / "ops").exists() and not (lr.dir / "checks").exists()


def test_apply_refuses_when_a_draft_exists(lr: Round, capsys):
    (lr.env.drafts / f"{SLUG}.yaml").write_text(lr.card.read_text(encoding="utf-8"), encoding="utf-8")
    assert lr.apply() == 1
    assert "draft under way" in capsys.readouterr().err
    assert not (lr.dir / "ops").exists() and not (lr.dir / "checks").exists()


def test_apply_refuses_a_layer_that_differs_from_the_cards(lr: Round, capsys):
    assert lr.apply(data=proposal(layer="trigger")) == 1
    assert "does not change the layer" in capsys.readouterr().err
    assert not (lr.dir / "ops").exists()


@pytest.mark.parametrize(
    "data, fragment",
    [
        ("{not json", "not readable JSON"),
        ({"slug": SLUG, "layer": "mechanism"}, "malformed"),  # no links key
        (proposal(extra=1), "malformed"),  # an unknown key
        (proposal(link(extra=1)), "malformed"),
        ({k: v for k, v in proposal().items() if k != "layer"}, "malformed"),
        (proposal(link(why=None)), "malformed"),
        (proposal(link(support="strong")), "malformed"),
        (proposal(link(sources=[])), "malformed"),
        (proposal(slug="another-card"), "is for card 'another-card'"),
        ({"slug": SLUG, "layer": "mechanism", "links": []}, "proposes no link"),
    ],
)
def test_apply_refuses_a_malformed_proposal_and_writes_nothing(lr: Round, capsys, data, fragment):
    assert lr.apply(data=data) == 1
    assert fragment in capsys.readouterr().err
    assert not (lr.dir / "ops").exists() and not (lr.dir / "checks").exists()


def test_a_proposal_missing_is_refused(lr: Round, capsys):
    assert lr.run("link-apply", "--round", "1") == 1
    assert "does not exist" in capsys.readouterr().err


def test_round_2_without_a_round_1_reject_is_refused(lr: Round, capsys):
    lr.propose(n=2)
    assert lr.run("link-apply", "--round", "2") == 1  # no round 1 at all
    assert "round 2 needs a valid reject" in capsys.readouterr().err
    assert lr.apply() == 0
    lr.review("accept")
    assert lr.record_review() == 0
    assert lr.run("link-apply", "--round", "2") == 1  # round 1 was accepted
    assert "found: accept" in capsys.readouterr().err
    assert not (lr.dir / "checks" / f"{SLUG}-r2.json").exists()


def test_round_2_after_an_invalid_reject_is_refused(lr: Round, capsys):
    assert lr.apply() == 0
    lr.review("reject", [{"item": "links[7]", "severity": "must_fix", "problem": "P."}])  # out of range
    lr.propose(n=2)
    assert lr.run("link-apply", "--round", "2") == 1
    assert "round 2 needs a valid reject" in capsys.readouterr().err


def test_a_round_with_a_map_review_is_not_applied_again(lr: Round, capsys):
    assert lr.apply() == 0
    lr.review("reject")
    assert lr.apply() == 1
    assert "already has a map review" in capsys.readouterr().err


def test_round_2_applies_after_a_valid_round_1_reject(lr: Round):
    assert lr.apply() == 0
    lr.review("reject")
    assert lr.record_review() == 0
    assert lr.apply(2, proposal(link(text=LINK_TEXT + " (revised)"))) == 0
    assert (lr.dir / "checks" / f"{SLUG}-r2.json").is_file()


def test_a_source_that_is_not_a_study_on_the_card_fails_the_checks(lr: Round):
    assert lr.apply(data=proposal(link(sources=["pmid:99999999"]))) == 1
    checks = json.loads((lr.dir / "checks" / f"{SLUG}-r1.json").read_text(encoding="utf-8"))
    assert checks["passed"] is False and checks["validator"], checks
    assert "FAILED" in lr.output()
    assert lr.card.read_bytes() == lr.card_bytes


def test_a_duplicate_target_fails_the_checks_through_the_operation(lr: Round):
    assert lr.apply(data=proposal(link(), link())) == 1
    checks = json.loads((lr.dir / "checks" / f"{SLUG}-r1.json").read_text(encoding="utf-8"))
    assert any("already has a link" in e for e in checks["ops_errors"]) and checks["applied"] is None


def test_a_failed_try_is_kept_and_the_round_can_be_applied_again_up_to_three_times(lr: Round, capsys):
    bad = proposal(link(sources=["pmid:99999999"]))
    assert lr.apply(data=bad) == 1
    assert lr.apply(data=bad) == 1
    names = sorted(p.name for p in (lr.dir / "checks").iterdir())
    assert names == [f"{SLUG}-r1-attempt1.json", f"{SLUG}-r1.json"]
    assert (lr.dir / "ops" / f"{SLUG}-r1-attempt1.json").is_file()
    assert lr.apply(data=bad) == 1
    assert lr.apply(data=bad) == 1  # the fourth try is refused (exit 1 as well), and writes nothing
    assert "failed its checks 3 times" in capsys.readouterr().err
    assert sorted(p.name for p in (lr.dir / "checks").iterdir()) == [
        f"{SLUG}-r1-attempt1.json",
        f"{SLUG}-r1-attempt2.json",
        f"{SLUG}-r1.json",
    ]


def test_a_fixed_proposal_passes_after_a_failed_try_and_a_passed_round_is_not_applied_again(lr: Round, capsys):
    assert lr.apply(data=proposal(link(sources=["pmid:99999999"]))) == 1
    assert lr.apply(data=proposal()) == 0
    assert json.loads((lr.dir / "checks" / f"{SLUG}-r1.json").read_text(encoding="utf-8"))["passed"] is True
    assert (lr.dir / "checks" / f"{SLUG}-r1-attempt1.json").is_file()
    assert lr.run("link-apply", "--round", "1") == 1
    assert "already passed its checks" in capsys.readouterr().err


# --- C3 record-map-review --------------------------------------------------------------------------------


def test_a_valid_accept_and_a_valid_reject_are_recorded(lr: Round):
    assert lr.apply() == 0
    lr.review("accept", [{"item": None, "severity": "advisory", "problem": "A remark."}])
    assert lr.record_review() == 0 and "map review recorded: accept, 1 finding(s)" in lr.output()
    lr.review(
        "reject",
        [
            {"item": "layer", "severity": "must_fix", "problem": "P."},
            {"item": "links[0]", "severity": "must_fix", "problem": "Q.", "fix": "R."},
        ],
    )
    assert lr.record_review() == 0


@pytest.mark.parametrize(
    "verdict, findings, over, fragment",
    [
        (
            "accept",
            [{"item": "links[0]", "severity": "must_fix", "problem": "P."}],
            {},
            "accept with a must_fix finding",
        ),
        ("reject", [], {}, "a reject needs at least one finding"),
        ("reject", [{"item": "links[1]", "severity": "must_fix", "problem": "P."}], {}, "links[1]"),  # one link only
        ("reject", [{"item": "link 0", "severity": "must_fix", "problem": "P."}], {}, "'link 0'"),
        ("reject", [{"item": "links[0]", "severity": "must_fix", "problem": "P."}], {"extra": 1}, "malformed"),
        ("maybe", [], {}, "malformed"),
        ("reject", [{"item": "links[0]", "severity": "must_fix"}], {}, "malformed"),  # no problem
        ("reject", [{"severity": "must_fix", "problem": "P."}], {}, "malformed"),  # no item
        ("accept", [], {"slug": "another-card"}, "expected"),
    ],
)
def test_record_map_review_refuses(lr: Round, capsys, verdict, findings, over, fragment):
    assert lr.apply() == 0
    lr.review(verdict, findings, **over)
    assert lr.record_review() == 1
    assert fragment in capsys.readouterr().err


def test_record_map_review_refuses_a_round_without_passed_checks(lr: Round, capsys):
    lr.propose()
    lr.review("accept")  # round 1 was never applied
    assert lr.record_review() == 1
    assert "no checks record" in capsys.readouterr().err


def test_record_map_review_refuses_a_round_whose_checks_failed(lr: Round, capsys):
    assert lr.apply(data=proposal(link(sources=["pmid:99999999"]))) == 1
    lr.review("accept")
    assert lr.record_review() == 1
    assert "did not pass" in capsys.readouterr().err


def test_record_map_review_refuses_a_missing_file(lr: Round, capsys):
    assert lr.apply() == 0
    assert lr.record_review() == 1
    assert "no map review" in capsys.readouterr().err


# --- C4 link-audit-plan ----------------------------------------------------------------------------------


def test_audit_plan_is_refused_without_an_accepted_map_review(lr: Round, capsys):
    assert lr.run("link-audit-plan") == 1  # nothing applied
    assert "no round applied" in capsys.readouterr().err
    assert lr.apply() == 0
    assert lr.run("link-audit-plan") == 1  # no review
    assert "no valid map review" in capsys.readouterr().err
    lr.review("reject")
    assert lr.run("link-audit-plan") == 1  # a reject
    assert "a reject" in capsys.readouterr().err
    assert not (lr.dir / "audit-context").exists()


def test_audit_plan_is_refused_when_the_checks_failed(lr: Round, capsys):
    assert lr.apply(data=proposal(link(sources=["pmid:99999999"]))) == 1
    assert lr.run("link-audit-plan") == 1
    assert "checks of round 1 did not pass" in capsys.readouterr().err


def test_the_audit_context_holds_the_diff_and_the_sources_in_full_and_nothing_of_the_proposals_reasoning(lr: Round):
    lr.accepted()
    text = (lr.dir / "audit-context" / f"{SLUG}-links.md").read_text(encoding="utf-8")
    assert f"+  - to: {TARGET}" in text.replace("+- to:", "+  - to:") or f"- to: {TARGET}" in text
    assert "## 1. The proposed change (the diff of the card)" in text and "```diff" in text
    assert "the links added to the published card" in text
    assert f"### Record: {CITED}" in text and CITED_TITLE in text
    assert "FULLTEXT-TAIL-MARKER" in text and "Not truncated" in text  # the link's source is a carrier: full text
    assert "REFERENCE-LIST-MARKER" not in text
    assert "Evidence ladder" in text and "Repeated by others" in text  # spec sections 2 and 3
    assert "# a comment inside a badge" not in text and "# a comment between two paragraphs" not in text
    for forbidden in ("WHY-MARKER", "REVIEW-MARKER", "Lower it."):
        assert forbidden not in text


def test_a_source_not_cached_is_named_in_the_context(lr: Round):
    # pmid:90000104 is cited by the card but not cached in the fixture cache: named as such
    lr.accepted()
    text = (lr.dir / "audit-context" / f"{SLUG}-links.md").read_text(encoding="utf-8")
    assert "### Not cached: pmid:90000104" in text


# --- C5 record-link-audit --------------------------------------------------------------------------------


def test_a_valid_first_and_second_audit_are_recorded(lr: Round):
    lr.audited("accept", "accept")
    assert "audit recorded: accept" in lr.output()


def test_second_is_refused_without_a_first_and_after_a_first_reject(lr: Round, capsys):
    lr.accepted()
    lr.write_audit(whole("accept"), second=True)
    assert lr.run("record-link-audit", "--second") == 1
    assert "needs a valid first audit" in capsys.readouterr().err
    lr.write_audit(whole("reject"))
    assert lr.run("record-link-audit") == 0
    assert lr.run("record-link-audit", "--second") == 1
    assert "sequential audits" in capsys.readouterr().err
    assert (lr.dir / "audit" / f"{SLUG}-links-second.yaml").is_file()  # untouched, not moved to .invalid-1


def test_the_audit_record_needs_its_context(lr: Round, capsys):
    assert lr.apply() == 0
    lr.write_audit(whole("accept"))
    assert lr.run("record-link-audit") == 1
    assert "link-audit-plan" in capsys.readouterr().err
    assert (lr.dir / "audit" / f"{SLUG}-links.yaml").is_file()


def test_an_audit_record_with_a_paper_is_invalid_and_gets_one_format_retry(lr: Round, capsys):
    lr.accepted()
    lr.write_audit(whole("accept") | {"paper": "pmid:90000101"})
    assert lr.run("record-link-audit") == 1
    err = capsys.readouterr().err
    assert "expected no paper" in err and "format retry" in err
    audit = lr.dir / "audit"
    assert (audit / f"{SLUG}-links.invalid-1.yaml").is_file() and (audit / f"{SLUG}-links.retry.md").is_file()
    lr.write_audit(whole("accept") | {"paper": "pmid:90000101"})
    assert lr.run("record-link-audit") == 1
    assert (audit / f"{SLUG}-links.invalid-2.yaml").is_file()
    assert lr.run("record-link-audit") == 1 and "failed validation twice" in capsys.readouterr().err


def test_an_audit_quote_that_is_not_in_the_record_is_invalid(lr: Round, capsys):
    lr.accepted()
    data = whole("accept")
    data["parts"][0]["evidence"][0]["quote"] = "A sentence the record does not hold."
    lr.write_audit(data)
    assert lr.run("record-link-audit") == 1
    assert "not found word for word" in capsys.readouterr().err


# --- C6 link-publish -------------------------------------------------------------------------------------


def test_two_accepts_publish_the_links(lr: Round):
    lr.audited("accept", "accept")
    assert lr.publish() == 0
    applied = (lr.dir / "applied" / f"{SLUG}-r1" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    text = lr.card.read_text(encoding="utf-8")
    assert text.replace("date: 2026-11-16", "date: 2026-10-01") == applied  # only last_checked differs
    data = yaml.safe_load(text)
    assert data["last_checked"] == {"date": dt.date(2026, 11, 16), "by": "ai_audit"}
    assert [x["to"] for x in data["links"]] == [TARGET]
    assert not cards.validate_card_file(lr.card)
    [entry] = lr.changelog()
    assert entry == {
        "date": dt.date(2026, 11, 16),
        "card": SLUG,
        "change": f"Links added: {TARGET}",
        "reason": "The cited controlled study supports the proposed level.",
        "sources": [CITED],
        "tier": 2,
        "decided_by": "ai_audit",
    }
    assert lr.audit_names() == [
        f"{DATE}-{SLUG}-links-second.yaml",
        f"{DATE}-{SLUG}-links-trail.yaml",
        f"{DATE}-{SLUG}-links.yaml",
    ]
    assert (lr.audits / f"{DATE}-{SLUG}-links.yaml").read_bytes() == (
        lr.dir / "audit" / f"{SLUG}-links.yaml"
    ).read_bytes()
    trail = lr.trail()
    assert trail["card"] == SLUG and trail["outcome"] == "published"
    assert trail["card_sha256"] == pipeline._sha256(lr.card_bytes)
    assert trail["audits_run"] == [f"{DATE}-{SLUG}-links.yaml", f"{DATE}-{SLUG}-links-second.yaml"]
    [rnd] = trail["rounds"]
    assert rnd["round"] == 1 and rnd["checks"] == {"passed": True, "errors": []}
    assert rnd["proposal"] == [{"to": TARGET, "support": "proposed", "text": LINK_TEXT, "sources": [CITED]}]
    assert rnd["map_review"] == {"verdict": "accept", "findings": []}
    for forbidden in ("WHY-MARKER", "REVIEW-MARKER"):
        assert forbidden not in yaml.safe_dump(trail)
    report = lr.report()
    assert "Outcome: published" in report and TARGET in report and "first audit: accept" in report
    assert "The cited controlled study supports the proposed level." in report
    assert f"ME-Atlas-Pipeline: weekly-run {DATE}" in lr.env.out[-1]


def test_two_links_are_logged_in_order_and_sources_are_distinct(lr: Round):
    (lr.env.cards / "second-target.yaml").write_text("", encoding="utf-8")
    two = proposal(link("second-target"), link(TARGET, sources=[CITED, "pmid:90000104"]))
    assert lr.apply(data=two) == 0
    lr.review()
    assert lr.record_review() == 0
    assert lr.run("link-audit-plan") == 0
    for second in (False, True):
        lr.write_audit(whole("accept"), second)
        assert lr.run("record-link-audit", *(["--second"] if second else [])) == 0
    assert lr.publish() == 0
    [entry] = lr.changelog()
    assert entry["change"] == f"Links added: second-target, {TARGET}"
    assert entry["sources"] == [CITED, "pmid:90000104"]
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == ["second-target", TARGET]


def test_the_change_log_keeps_its_earlier_entries_byte_for_byte(lr: Round):
    existing = (
        "- date: 2026-10-30\n  card: other-card\n  change: An earlier change.\n  reason: Because.\n"
        "  sources: [pmid:90000100]\n  tier: 1\n  decided_by: ai_pair\n"
    )
    lr.log.write_text(existing, encoding="utf-8", newline="\n")
    lr.audited()
    assert lr.publish() == 0
    assert lr.log.read_text(encoding="utf-8").startswith(existing)
    assert [e["card"] for e in lr.changelog()] == ["other-card", SLUG]


def test_a_first_reject_holds_back_with_no_second_audit(lr: Round):
    lr.audited("reject", None)
    log_before = lr.log.exists()
    assert lr.publish() == 0
    lr.assert_held_back(pipeline.SEQUENTIAL_REJECT)
    assert not log_before
    assert lr.audit_names() == [f"{DATE}-{SLUG}-links-trail.yaml", f"{DATE}-{SLUG}-links.yaml"]
    assert lr.trail()["audits_run"] == [f"{DATE}-{SLUG}-links.yaml"]


def test_a_first_accept_lower_holds_back(lr: Round):
    lr.audited("accept_lower", None)
    assert lr.publish() == 0
    lr.assert_held_back("the first audit decided accept_lower; a link round changes no level")


def test_two_audits_that_differ_hold_back(lr: Round):
    lr.audited("accept", "reject")
    assert lr.publish() == 0
    lr.assert_held_back("the two audits differ: one decided accept, the other reject")


def test_a_missing_second_audit_holds_back(lr: Round):
    lr.audited("accept", None)
    assert lr.publish() == 0
    lr.assert_held_back("no valid second audit: no audit record " + f"{SLUG}-links-second.yaml")


def test_a_card_that_changed_since_the_round_was_applied_is_held_back(lr: Round):
    lr.audited()
    changed = lr.card.read_text(encoding="utf-8").replace("level: 2\n", "level: 2  # touched\n", 1)
    lr.card.write_text(changed, encoding="utf-8", newline="\n")
    lr.card_bytes = lr.card.read_bytes()
    assert lr.publish() == 0
    lr.assert_held_back("the card changed since the round was applied")
    assert lr.audit_names() == [
        f"{DATE}-{SLUG}-links-second.yaml",
        f"{DATE}-{SLUG}-links-trail.yaml",
        f"{DATE}-{SLUG}-links.yaml",
    ]


def test_a_round_whose_checks_failed_is_held_back(lr: Round):
    assert lr.apply(data=proposal(link(sources=["pmid:99999999"]))) == 1
    assert lr.publish() == 0
    lr.assert_held_back("checks failed")
    assert lr.trail()["rounds"][0]["checks"]["passed"] is False and lr.trail()["rounds"][0]["checks"]["errors"]


def test_a_round_2_map_review_reject_holds_back(lr: Round):
    assert lr.apply() == 0
    lr.review("reject")
    assert lr.record_review() == 0
    assert lr.apply(2, proposal(link(text=LINK_TEXT + " (revised)"))) == 0
    lr.review("reject", n=2)
    assert lr.record_review(2) == 0
    assert lr.publish() == 0
    lr.assert_held_back("map review rejected in round 2")
    assert [r["round"] for r in lr.trail()["rounds"]] == [1, 2]
    assert lr.trail()["rounds"][0]["map_review"]["findings"][0]["problem"] == "REVIEW-MARKER."


def test_a_round_2_that_is_accepted_is_the_one_audited_and_published(lr: Round):
    assert lr.apply() == 0
    lr.review("reject")
    assert lr.record_review() == 0
    assert lr.apply(2, proposal(link(text=LINK_TEXT + " (revised)"))) == 0
    lr.review("accept", n=2)
    assert lr.record_review(2) == 0
    assert lr.run("link-audit-plan") == 0
    for second in (False, True):
        lr.write_audit(whole("accept"), second)
        assert lr.run("record-link-audit", *(["--second"] if second else [])) == 0
    assert lr.publish() == 0
    assert yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"][0]["text"].endswith("(revised)")
    assert [r["round"] for r in lr.trail()["rounds"]] == [1, 2]


def test_refusal_when_an_audits_target_exists_and_nothing_is_written(lr: Round, capsys):
    lr.audited()
    lr.audits.mkdir()
    taken = lr.audits / f"{DATE}-{SLUG}-links-trail.yaml"
    taken.write_text("card: x\n", encoding="utf-8")
    assert lr.publish() == 1
    assert "already exists" in capsys.readouterr().err
    assert lr.card.read_bytes() == lr.card_bytes and not lr.log.exists()
    assert [p.name for p in lr.audits.iterdir()] == [taken.name] and taken.read_text(encoding="utf-8") == "card: x\n"
    assert not (lr.dir / "link-report.md").exists()


def test_refusal_when_no_round_was_applied(lr: Round, capsys):
    assert lr.publish() == 1
    assert "no round applied" in capsys.readouterr().err
    lr.assert_nothing_written()


def test_refusal_when_the_first_audit_awaits_its_format_retry(lr: Round, capsys):
    lr.accepted()
    lr.write_audit(whole("accept") | {"paper": "pmid:90000101"})
    assert lr.run("record-link-audit") == 1
    capsys.readouterr()
    assert lr.publish() == 1
    assert "format retry is pending" in capsys.readouterr().err
    lr.assert_nothing_written()


def test_a_first_record_that_failed_twice_is_held_back_and_kept_as_invalid(lr: Round):
    lr.accepted()
    for _ in range(2):
        lr.write_audit(whole("accept") | {"paper": "pmid:90000101"})
        assert lr.run("record-link-audit") == 1
    assert lr.publish() == 0
    lr.assert_held_back(pipeline.FIRST_INVALID_TWICE)
    assert f"{DATE}-{SLUG}-links-invalid.yaml" in lr.audit_names()


def test_dry_run_writes_only_the_report(lr: Round):
    lr.audited()
    assert lr.publish("--dry-run") == 0
    assert "Outcome: published" in lr.report() and f"Dry run: only {lr.dir / 'link-report.md'}" in lr.output()
    assert lr.card.read_bytes() == lr.card_bytes and not lr.log.exists() and lr.audit_names() == []
    assert "ME-Atlas-Pipeline" not in lr.output()


def test_a_card_with_a_draft_is_refused_by_every_step_that_reads_the_card(lr: Round, capsys):
    lr.audited()
    (lr.env.drafts / f"{SLUG}.yaml").write_text(lr.card.read_text(encoding="utf-8"), encoding="utf-8")
    assert lr.publish() == 1
    assert "draft under way" in capsys.readouterr().err
    lr.assert_nothing_written()
