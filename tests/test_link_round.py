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
from test_audit import CITED, CITED_TITLE, audit_data, level_pair, record, write_record
from test_pipeline import SLUG, Env, fulltext_loader
from test_publish_card import whole

from me_atlas import cards, link_round, pipeline
from me_atlas.operations import parse_ops

DATE = "2026-11-16"
TARGET = "other-fictional-card"
SECOND = "second-target"
THIRD = "third-target"
FIXED = "A fictional review proposes that A feeds B."
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
        for name in (TARGET, SECOND, THIRD):  # link targets: only the file name counts
            (env.cards / f"{name}.yaml").write_text("", encoding="utf-8")
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
                else [
                    {
                        "item": "links[0]",
                        "severity": "must_fix",
                        "class": "decisive",
                        "problem": "REVIEW-MARKER.",
                        "fix": "Lower it.",
                    }
                ]
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

    def accepted(self, *links: dict) -> None:
        """Round 1 applied and accepted by the map review, and the audit context written."""
        assert self.apply(data=proposal(*links) if links else None) == 0
        self.review()
        assert self.record_review() == 0
        assert self.run("link-audit-plan") == 0

    def card_links(self, second: bool = False) -> list[str]:
        """The `to` of every link in the text an audit read, in its numbering (`links[n]`)."""
        path = self.dir / "link-stage" / f"{SLUG}-links{'-second' if second else ''}" / f"{SLUG}.yaml"
        return [x["to"] for x in yaml.safe_load(path.read_text(encoding="utf-8"))["links"]]

    def stage_links(self, second: bool = False) -> list[str]:
        """The `to` of each link of the round in the text an audit read."""
        last = max((self.dir / "map").glob(f"{SLUG}-r*.json"))
        proposed = {x["to"] for x in json.loads(last.read_text(encoding="utf-8"))["links"]}
        return [to for to in self.card_links(second) if to in proposed]

    def audit_record(self, spec: str | dict[str, str], second: bool = False) -> dict:
        """An audit record of a link round. ``spec`` is one of accept / decisive / wording for every link of the audit
        context, or a dict of them by `to`. A rejected link has an objecting part naming it."""
        stage, numbered = self.stage_links(second), self.card_links(second)
        spec = dict.fromkeys(stage, spec) if isinstance(spec, str) else spec
        assert set(spec) == set(stage), (spec, stage)
        base = whole("accept")
        part = base["parts"][0]
        decision = "accept" if all(v == "accept" for v in spec.values()) else "reject"
        data = base | {
            "decision": decision,
            "link_decisions": [
                {"to": to, "decision": "accept" if v == "accept" else "reject"} for to, v in spec.items()
            ],
        }
        if decision == "reject":
            data["parts"] = [
                part | {"class": "none"}
                if v == "accept"
                else part
                | {"decision_part": f"OBJECTION to {to}.", "class": v, "target": f"links[{numbered.index(to)}]"}
                for to, v in spec.items()
            ]
        return data

    def audit(self, spec: str | dict[str, str], second: bool = False) -> int:
        self.write_audit(self.audit_record(spec, second), second)
        return self.run("record-link-audit", *(["--second"] if second else []))

    def audited(self, first: str | dict = "accept", second: str | dict | None = "accept", *links: dict) -> None:
        self.accepted(*links)
        assert self.audit(first) == 0
        if second is not None:
            assert self.run("link-audit-plan", "--second") == 0
            assert self.audit(second, second=True) == 0

    # -- the valve --
    def valve_file(self, stage: str, *ops: dict) -> Path:
        path = self.dir / "valve" / f"{SLUG}-links-{stage}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"card": SLUG, "paper": None, "operations": list(ops)}), encoding="utf-8")
        return path

    def valve_check(self, stage: str, *answers: tuple[str, bool, bool]) -> Path:
        path = self.dir / "valve" / f"{SLUG}-links-{stage}-check.json"
        fixes = [
            {"finding": f, "resolves": resolves, "new_claim": claim, "reason": f"REASON for {f}."}
            for f, resolves, claim in answers
        ]
        path.write_text(json.dumps({"card": SLUG, "fixes": fixes}), encoding="utf-8")
        return path

    def valve(self, stage: str, to: str, text: str, finding: str, ok: bool = True) -> None:
        """Apply a one-link fix and record its check."""
        self.valve_file(stage, {"op": "set_link_text", "to": to, "text": text})
        assert self.run("link-valve-apply", "--stage", stage) == 0
        self.valve_check(stage, (finding, ok, False))
        assert self.run("record-link-valve-check", "--stage", stage) == 0

    def target(self, name: str) -> None:
        (self.env.cards / f"{name}.yaml").write_text("", encoding="utf-8")

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
    lr.review("reject", [{"item": "links[7]", "severity": "must_fix", "class": "decisive", "problem": "P."}])
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
            {"item": "layer", "severity": "must_fix", "class": "decisive", "problem": "P."},
            {"item": "links[0]", "severity": "must_fix", "class": "decisive", "problem": "Q.", "fix": "R."},
        ],
    )
    assert lr.record_review() == 0
    wording = {"item": "links[0]", "severity": "must_fix", "class": "wording", "target": "links[0]", "problem": "W."}
    lr.review("reject", [wording, {"item": None, "severity": "advisory", "problem": "A."}])
    assert lr.record_review() == 0  # a wording must_fix on a link, and an advisory without a class


def must(item, **over) -> dict:
    return {"item": item, "severity": "must_fix", "class": "decisive", "problem": "P."} | over


@pytest.mark.parametrize(
    "verdict, findings, over, fragment",
    [
        ("accept", [must("links[0]")], {}, "accept with a must_fix finding"),
        ("reject", [], {}, "a reject needs at least one finding"),
        ("reject", [must("links[1]")], {}, "links[1]"),  # one link only
        ("reject", [must("link 0")], {}, "'link 0'"),
        ("reject", [must("links[0]")], {"extra": 1}, "malformed"),
        ("maybe", [], {}, "malformed"),
        ("reject", [must("links[0]", problem=None)], {}, "malformed"),  # no problem
        ("reject", [{"severity": "must_fix", "class": "decisive", "problem": "P."}], {}, "malformed"),  # no item
        ("accept", [], {"slug": "another-card"}, "expected"),
        # P1: a must_fix carries a class
        ("reject", [must("links[0]", **{"class": None})], {}, "needs `class`"),
        ("reject", [{"item": "links[0]", "severity": "must_fix", "problem": "P."}], {}, "needs `class`"),
        ("reject", [must("links[0]", **{"class": "none"})], {}, "`decisive` or `wording`"),
        ("reject", [must("links[0]", **{"class": "serious"})], {}, "malformed"),
        # a wording finding names its own link as target
        ("reject", [must("links[0]", **{"class": "wording"})], {}, "free-text item"),  # no target
        ("reject", [must("links[0]", **{"class": "wording", "target": "links[1]"})], {}, "is its `item`"),
        ("reject", [must("links[0]", **{"class": "wording", "target": "level_reason[0]"})], {}, "is its `item`"),
        # a finding on the proposal as a whole is decisive
        ("reject", [must(None, **{"class": "wording", "target": "core_claim"})], {}, "as a whole"),
        ("reject", [must("layer", **{"class": "wording", "target": "layer"})], {}, "free-text item"),
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
    assert lr.record_review() == 0
    assert lr.run("link-audit-plan") == 1  # the only link is dropped by a decisive finding: none left
    assert "map review rejected in round 1" in capsys.readouterr().err
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
    assert "This is a link round (the first audit)" in text and "link_decisions" in text
    assert f"- `links[0]`: `{TARGET}`" in text
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
    lr.write_audit(lr.audit_record("accept"), second=True)
    assert lr.run("record-link-audit", "--second") == 1
    assert "needs a valid first audit" in capsys.readouterr().err
    assert lr.run("link-audit-plan", "--second") == 1
    assert "needs a valid first audit" in capsys.readouterr().err
    assert lr.audit("decisive") == 0
    assert lr.run("record-link-audit", "--second") == 1
    assert "sequential audits" in capsys.readouterr().err
    assert lr.run("link-audit-plan", "--second") == 1  # no link is left
    assert "no link is left" in capsys.readouterr().err
    assert (lr.dir / "audit" / f"{SLUG}-links-second.yaml").is_file()  # untouched, not moved to .invalid-1
    assert not (lr.dir / "audit-context" / f"{SLUG}-links-second.md").exists()


def test_the_audit_record_needs_its_context(lr: Round, capsys):
    assert lr.apply() == 0
    lr.write_audit(whole("accept"))
    assert lr.run("record-link-audit") == 1
    assert "link-audit-plan" in capsys.readouterr().err
    assert (lr.dir / "audit" / f"{SLUG}-links.yaml").is_file()


def test_an_audit_record_with_a_paper_is_invalid_and_gets_one_format_retry(lr: Round, capsys):
    lr.accepted()
    lr.write_audit(lr.audit_record("accept") | {"paper": "pmid:90000101"})
    assert lr.run("record-link-audit") == 1
    err = capsys.readouterr().err
    assert "expected no paper" in err and "format retry" in err
    audit = lr.dir / "audit"
    assert (audit / f"{SLUG}-links.invalid-1.yaml").is_file() and (audit / f"{SLUG}-links.retry.md").is_file()
    lr.write_audit(lr.audit_record("accept") | {"paper": "pmid:90000101"})
    assert lr.run("record-link-audit") == 1
    assert (audit / f"{SLUG}-links.invalid-2.yaml").is_file()
    assert lr.run("record-link-audit") == 1 and "failed validation twice" in capsys.readouterr().err


def test_an_audit_quote_that_is_not_in_the_record_is_invalid(lr: Round, capsys):
    lr.accepted()
    data = lr.audit_record("accept")
    data["parts"][0]["evidence"][0]["quote"] = "A sentence the record does not hold."
    lr.write_audit(data)
    assert lr.run("record-link-audit") == 1
    assert "not found word for word" in capsys.readouterr().err


def two_link_round(lr: Round) -> None:
    lr.accepted(link(), link(SECOND))


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d.pop("link_decisions"), "link_decisions is missing"),
        (lambda d: d.update(link_decisions=d["link_decisions"][:1]), "no entry for `second-target`"),
        (
            lambda d: d["link_decisions"].append({"to": "stranger", "decision": "accept"}),
            "link_decisions has an entry for `stranger`",
        ),
        (
            lambda d: d["link_decisions"].append(d["link_decisions"][0]),
            "link_decisions has `other-fictional-card` twice",
        ),
        (lambda d: d.update(decision="reject"), "decision is reject, but the link_decisions give accept"),
        (lambda d: d["link_decisions"][1].update(decision="reject"), "decision is accept, but the link_decisions"),
        (lambda d: d.update(decision="accept_lower", accepted_level=1), "accept_lower is not available"),
    ],
)
def test_link_decisions_missing_incomplete_or_inconsistent_with_the_decision_are_refused(
    lr: Round, capsys, mutate, fragment
):
    two_link_round(lr)
    data = lr.audit_record("accept")
    mutate(data)
    lr.write_audit(data)
    assert lr.run("record-link-audit") == 1
    assert fragment in capsys.readouterr().err
    assert (lr.dir / "audit" / f"{SLUG}-links.invalid-1.yaml").is_file()  # the one format retry


def test_a_rejected_link_needs_an_objecting_part_naming_it_and_an_accepted_one_must_not_have_one(lr: Round, capsys):
    two_link_round(lr)
    data = lr.audit_record({TARGET: "decisive", SECOND: "accept"})
    data["parts"] = [data["parts"][1]]  # only the supporting part: nothing objects to the rejected link
    lr.write_audit(data)
    assert lr.run("record-link-audit") == 1
    err = capsys.readouterr().err
    assert f"the link `{TARGET}` is rejected but no objecting part names it" in err
    assert "a reject needs at least one part with class" in err
    data = lr.audit_record({TARGET: "decisive", SECOND: "accept"})
    data["parts"][1] |= {"class": "wording", "target": "links[1]"}  # objects to the link it accepts
    lr.write_audit(data)
    assert lr.run("record-link-audit") == 1
    assert f"the link `{SECOND}` is accepted but parts[1] objects to it" in capsys.readouterr().err


@pytest.mark.parametrize(
    "target, fragment",
    [(None, "is not `links[n]`"), ("links[5]", "not a link of this round"), ("core_claim", "is not `links[n]`")],
)
def test_an_objecting_part_must_name_a_link_of_the_round(lr: Round, capsys, target, fragment):
    two_link_round(lr)
    data = lr.audit_record({TARGET: "decisive", SECOND: "accept"})
    data["parts"][0].pop("target")
    if target:
        data["parts"][0]["target"] = target
    lr.write_audit(data)
    assert lr.run("record-link-audit") == 1
    assert fragment in capsys.readouterr().err


def test_a_reject_part_without_class_is_refused_in_a_link_round(lr: Round, capsys):
    two_link_round(lr)
    data = lr.audit_record({TARGET: "decisive", SECOND: "accept"})
    data["parts"][1].pop("class")
    lr.write_audit(data)
    assert lr.run("record-link-audit") == 1
    assert "parts[1] has no `class`" in capsys.readouterr().err


def test_the_format_retry_cannot_change_a_link_decision(lr: Round, capsys):
    two_link_round(lr)
    both = lr.audit_record({TARGET: "decisive", SECOND: "decisive"})
    lr.write_audit(both | {"paper": "pmid:90000101"})  # invalid: a paper
    assert lr.run("record-link-audit") == 1
    retry = lr.audit_record({TARGET: "decisive", SECOND: "accept"})  # still a reject, but another link's answer
    lr.write_audit(retry)
    assert lr.run("record-link-audit") == 1
    assert "a format retry cannot change the answer" in capsys.readouterr().err
    assert (lr.dir / "audit" / f"{SLUG}-links.invalid-2.yaml").is_file()


def test_link_decisions_are_for_a_link_round_only(tmp_path: Path, capsys):
    env = Env(tmp_path)
    env.prepare()
    assert env.classify() == 0
    level_pair(env)
    write_record(env, audit_data("accept") | {"link_decisions": [{"to": TARGET, "decision": "accept"}]})
    assert record(env) == 1
    assert "link_decisions is for the audit of a link round only" in capsys.readouterr().err


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
    two = proposal(link(SECOND), link(TARGET, sources=[CITED, "pmid:90000104"]))
    lr.audited("accept", "accept", *two["links"])
    assert lr.publish() == 0
    [entry] = lr.changelog()
    assert entry["change"] == f"Links added: {SECOND}, {TARGET}"
    assert entry["sources"] == [CITED, "pmid:90000104"]
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == [SECOND, TARGET]
    assert [x["outcome"] for x in lr.trail()["links"]] == ["published", "published"]


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


def test_a_first_reject_of_every_link_holds_back_with_no_second_audit(lr: Round):
    lr.audited("decisive", None)
    log_before = lr.log.exists()
    assert lr.publish() == 0
    lr.assert_held_back(link_round.SEQUENTIAL_REJECT)
    assert not log_before
    assert lr.audit_names() == [f"{DATE}-{SLUG}-links-trail.yaml", f"{DATE}-{SLUG}-links.yaml"]
    assert lr.trail()["audits_run"] == [f"{DATE}-{SLUG}-links.yaml"]
    assert lr.trail()["links"] == [{"to": TARGET, "outcome": f"rejected in audit (decisive): OBJECTION to {TARGET}."}]


def test_a_first_accept_lower_is_refused_by_the_record_check(lr: Round, capsys):
    lr.accepted()
    lr.write_audit(whole("accept_lower") | {"link_decisions": [{"to": TARGET, "decision": "reject"}]})
    assert lr.run("record-link-audit") == 1
    assert "accept_lower is not available in a link round" in capsys.readouterr().err


def test_a_second_audit_that_rejects_the_only_link_holds_back(lr: Round):
    lr.audited("accept", "decisive")
    assert lr.publish() == 0
    lr.assert_held_back("no link passed both audits")
    assert lr.trail()["links"][0]["outcome"].startswith("rejected in audit (decisive): OBJECTION")


def test_a_second_audit_that_is_needed_and_missing_is_a_refusal_and_writes_nothing(lr: Round, capsys):
    lr.audited("accept", None)
    assert lr.publish() == 1
    assert "a second audit is needed" in capsys.readouterr().err
    lr.assert_nothing_written()
    assert not (lr.dir / "link-report.md").exists()


def test_a_second_record_that_failed_twice_holds_back_and_names_the_links(lr: Round):
    lr.audited("accept", None)
    assert lr.run("link-audit-plan", "--second") == 0
    for _ in range(2):
        lr.write_audit(lr.audit_record("accept", True) | {"paper": "pmid:90000101"}, second=True)
        assert lr.run("record-link-audit", "--second") == 1
    assert lr.publish() == 0
    assert lr.trail()["outcome"].startswith("no valid second audit")
    assert lr.trail()["links"] == [{"to": TARGET, "outcome": "not audited a second time"}]
    assert lr.card.read_bytes() == lr.card_bytes and not lr.log.exists()


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
    assert lr.audit("accept") == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("accept", second=True) == 0
    assert lr.publish() == 0
    assert yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"][0]["text"].endswith("(revised)")
    assert [r["round"] for r in lr.trail()["rounds"]] == [1, 2]


def test_refusal_when_an_audits_target_exists_and_nothing_is_written(lr: Round, capsys):
    lr.audited()
    lr.audits.mkdir()
    taken = lr.audits / f"{DATE}-{SLUG}-links.yaml"
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
    lr.write_audit(lr.audit_record("accept") | {"paper": "pmid:90000101"})
    assert lr.run("record-link-audit") == 1
    capsys.readouterr()
    assert lr.publish() == 1
    assert "format retry is pending" in capsys.readouterr().err
    lr.assert_nothing_written()


def test_a_first_record_that_failed_twice_is_held_back_and_kept_as_invalid(lr: Round):
    lr.accepted()
    for _ in range(2):
        lr.write_audit(lr.audit_record("accept") | {"paper": "pmid:90000101"})
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


# --- each link on its own: the map review ----------------------------------------------------------------


def wording(index: int, **over) -> dict:
    return (
        must(f"links[{index}]", **{"class": "wording", "target": f"links[{index}]", "problem": "NAMES-A-PLACE."}) | over
    )


def test_round_2_is_refused_after_a_wording_only_round_1_reject(lr: Round, capsys):
    assert lr.apply() == 0
    lr.review("reject", [wording(0)])
    assert lr.record_review() == 0  # a reject (any must_fix), whose only finding is wording
    lr.propose(n=2)
    assert lr.run("link-apply", "--round", "2") == 1
    assert "has no decisive finding" in capsys.readouterr().err
    assert not (lr.dir / "checks" / f"{SLUG}-r2.json").exists()


def test_round_2_is_allowed_when_round_1_has_a_decisive_finding_beside_wording_ones(lr: Round):
    assert lr.apply(data=proposal(link(), link(SECOND))) == 0
    lr.review("reject", [wording(0), must("links[1]")])
    assert lr.record_review() == 0
    assert lr.apply(2, proposal(link(), link(SECOND, text=LINK_TEXT + " (revised)"))) == 0


def test_a_link_dropped_at_the_map_review_leaves_the_other_to_be_audited_and_published(lr: Round):
    assert lr.apply(data=proposal(link(), link(SECOND))) == 0
    lr.review("reject")  # a decisive finding on links[0]
    assert lr.record_review() == 0
    assert lr.run("link-audit-plan") == 0
    assert lr.audit("accept") == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("accept", second=True) == 0
    assert lr.stage_links() == [SECOND] and lr.stage_links(True) == [SECOND]
    assert lr.publish() == 0
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == [SECOND]
    [entry] = lr.changelog()
    assert entry["change"] == f"Links added: {SECOND}"
    assert lr.trail()["links"] == [
        {"to": TARGET, "outcome": "dropped at map review: REVIEW-MARKER."},
        {"to": SECOND, "outcome": "published"},
    ]
    assert lr.trail()["rounds"][0]["map_review"]["findings"][0]["class"] == "decisive"
    assert "## Links not added" in lr.report() and "dropped at map review" in lr.report()


def test_a_decisive_finding_on_the_proposal_as_a_whole_drops_every_link(lr: Round, capsys):
    assert lr.apply(data=proposal(link(), link(SECOND))) == 0
    lr.review("reject", [must(None, problem="The whole proposal is wrong.")])
    assert lr.record_review() == 0
    assert lr.run("link-audit-plan") == 1
    assert "map review rejected in round 1; no second round was applied" in capsys.readouterr().err
    assert lr.publish() == 0
    lr.assert_held_back("map review rejected in round 1; no second round was applied")
    assert [x["outcome"] for x in lr.trail()["links"]] == ["dropped at map review: The whole proposal is wrong."] * 2


# --- each link on its own: the audits --------------------------------------------------------------------


def three(lr: Round) -> None:
    lr.accepted(link(), link(SECOND), link(THIRD))


def test_the_first_audit_rejects_one_link_the_second_context_holds_the_other_two_and_two_are_published(lr: Round):
    three(lr)
    assert lr.audit({TARGET: "accept", SECOND: "decisive", THIRD: "accept"}) == 0
    assert lr.run("link-audit-plan", "--second") == 0
    text = (lr.dir / "audit-context" / f"{SLUG}-links-second.md").read_text(encoding="utf-8")
    assert "This is a link round (the second audit)" in text
    assert f"- `links[0]`: `{TARGET}`" in text and f"- `links[1]`: `{THIRD}`" in text and SECOND not in text
    assert lr.stage_links(True) == [TARGET, THIRD]
    assert lr.audit("accept", second=True) == 0
    assert lr.publish() == 0
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == [TARGET, THIRD]
    [entry] = lr.changelog()
    assert entry["change"] == f"Links added: {TARGET}, {THIRD}"
    assert lr.trail()["links"] == [
        {"to": TARGET, "outcome": "published"},
        {"to": SECOND, "outcome": f"rejected in audit (decisive): OBJECTION to {SECOND}."},
        {"to": THIRD, "outcome": "published"},
    ]
    assert not cards.validate_card_file(lr.card)


def test_the_second_audit_rejects_one_of_the_two_and_one_is_published(lr: Round):
    three(lr)
    assert lr.audit({TARGET: "accept", SECOND: "decisive", THIRD: "accept"}) == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit({TARGET: "decisive", THIRD: "accept"}, second=True) == 0
    assert lr.publish() == 0
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == [THIRD]
    assert lr.changelog()[0]["change"] == f"Links added: {THIRD}"
    outcomes = {x["to"]: x["outcome"] for x in lr.trail()["links"]}
    assert (
        outcomes[TARGET] == f"rejected in audit (decisive): OBJECTION to {TARGET}." and outcomes[THIRD] == "published"
    )
    assert lr.audit_names() == [
        f"{DATE}-{SLUG}-links-second.yaml",
        f"{DATE}-{SLUG}-links-trail.yaml",
        f"{DATE}-{SLUG}-links.yaml",
    ]


def test_a_second_audit_record_must_decide_exactly_the_links_of_its_context(lr: Round, capsys):
    three(lr)
    assert lr.audit({TARGET: "accept", SECOND: "decisive", THIRD: "accept"}) == 0
    assert lr.run("link-audit-plan", "--second") == 0
    lr.write_audit(
        lr.audit_record("accept")
        | {"link_decisions": [{"to": s, "decision": "accept"} for s in (TARGET, SECOND, THIRD)]},
        True,
    )
    assert lr.run("record-link-audit", "--second") == 1
    assert f"link_decisions has an entry for `{SECOND}`, which this audit does not decide" in capsys.readouterr().err


# --- the valve at the map review -------------------------------------------------------------------------


def test_a_wording_only_map_review_goes_through_the_valve_and_the_fixed_text_is_audited_and_published(
    lr: Round, capsys
):
    assert lr.apply(data=proposal(link(), link(SECOND))) == 0
    lr.review("reject", [wording(0, fix="Remove the place name.")])
    assert lr.record_review() == 0
    assert lr.run("link-audit-plan") == 1  # the valve is open and the operator has not finished it
    assert "valve fix not applied" in capsys.readouterr().err
    lr.valve_file("map-review", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    assert lr.run("link-valve-apply", "--stage", "map-review") == 0
    applied = yaml.safe_load(
        (lr.dir / "valve" / f"{SLUG}-links-map-review" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    )
    assert [x["text"] for x in applied["links"]] == [FIXED, LINK_TEXT]
    assert lr.run("link-valve-apply", "--stage", "map-review") == 1  # one valve per stage
    assert "one valve per stage" in capsys.readouterr().err
    assert lr.run("link-audit-plan") == 1
    assert "valve check missing" in capsys.readouterr().err
    assert lr.run("link-valve-check-plan", "--stage", "map-review") == 0
    context = (lr.dir / "valve-check-context" / f"{SLUG}-links-map-review.md").read_text(encoding="utf-8")
    assert "## Finding findings[0]" in context and f"- link: `{TARGET}`" in context
    assert f"- before: {LINK_TEXT}" in context and f"- after: {FIXED}" in context and "NAMES-A-PLACE." in context
    assert (
        "Remove the place name." in context
        and f"`{CITED}`" in context.replace("  - ", "`").replace("\n", "`")
        or CITED in context
    )
    lr.valve_check("map-review", ("findings[0]", True, False))
    assert lr.run("record-link-valve-check", "--stage", "map-review") == 0
    assert "fix check recorded: PASSED" in lr.output()
    assert lr.run("link-audit-plan") == 0
    audit_context = (lr.dir / "audit-context" / f"{SLUG}-links.md").read_text(encoding="utf-8")
    assert (
        FIXED in audit_context
        and "NAMES-A-PLACE." not in audit_context
        and "Remove the place name" not in audit_context
    )
    assert lr.audit("accept") == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("accept", second=True) == 0
    assert lr.publish() == 0
    links = yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]
    assert [(x["to"], x["text"]) for x in links] == [(TARGET, FIXED), (SECOND, LINK_TEXT)]
    assert lr.changelog()[0]["change"] == f"Links added: {TARGET}, {SECOND} after a wording fix"
    assert lr.trail()["links"] == [
        {"to": TARGET, "outcome": "published after a wording fix"},
        {"to": SECOND, "outcome": "published"},
    ]
    names = lr.audit_names()
    assert f"{DATE}-{SLUG}-links-valve-map-review.yaml" in names
    valve = yaml.safe_load((lr.audits / f"{DATE}-{SLUG}-links-valve-map-review.yaml").read_text(encoding="utf-8"))
    assert valve["classification"][0]["link"] == TARGET and valve["operations"][0]["text"] == FIXED
    assert valve["check"]["passed"] is True


def test_a_failed_fix_check_at_the_map_review_drops_that_link_and_the_others_go_on(lr: Round):
    assert lr.apply(data=proposal(link(), link(SECOND))) == 0
    lr.review("reject", [wording(0)])
    assert lr.record_review() == 0
    lr.valve("map-review", TARGET, FIXED, "findings[0]", ok=False)
    assert lr.run("link-audit-plan") == 0
    assert lr.stage_links() == [SECOND]
    assert lr.audit("accept") == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("accept", second=True) == 0
    assert lr.publish() == 0
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == [SECOND]
    first = lr.trail()["links"][0]["outcome"]
    assert first.startswith("wording fix did not pass its check: findings[0] does not resolve the finding")


def test_a_fix_that_adds_a_claim_drops_the_link(lr: Round):
    assert lr.apply() == 0
    lr.review("reject", [wording(0)])
    assert lr.record_review() == 0
    lr.valve_file("map-review", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    assert lr.run("link-valve-apply", "--stage", "map-review") == 0
    lr.valve_check("map-review", ("findings[0]", True, True))
    assert lr.run("record-link-valve-check", "--stage", "map-review") == 0
    assert lr.publish() == 0
    lr.assert_held_back("no link passed the wording fix check of the map-review")
    assert "adds a claim" in lr.trail()["links"][0]["outcome"]


def test_publish_is_refused_while_a_map_review_valve_is_open_and_unfinished(lr: Round, capsys):
    assert lr.apply() == 0
    lr.review("reject", [wording(0)])
    assert lr.record_review() == 0
    assert lr.publish() == 1
    assert "valve fix not applied" in capsys.readouterr().err
    lr.assert_nothing_written()
    lr.valve_file("map-review", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    assert lr.run("link-valve-apply", "--stage", "map-review") == 0
    assert lr.publish() == 1
    assert "valve check missing" in capsys.readouterr().err
    lr.assert_nothing_written()
    assert not (lr.dir / "link-report.md").exists()


def test_the_valve_check_answers_every_finding_once(lr: Round, capsys):
    assert lr.apply(data=proposal(link(), link(SECOND))) == 0
    lr.review("reject", [wording(0), wording(1)])
    assert lr.record_review() == 0
    lr.valve_file(
        "map-review",
        {"op": "set_link_text", "to": TARGET, "text": FIXED},
        {"op": "set_link_text", "to": SECOND, "text": FIXED},
    )
    assert lr.run("link-valve-apply", "--stage", "map-review") == 0
    lr.valve_check("map-review", ("findings[0]", True, False))
    assert lr.run("record-link-valve-check", "--stage", "map-review") == 1
    assert "no answer for the finding findings[1]" in capsys.readouterr().err
    lr.valve_check(
        "map-review", ("findings[0]", True, False), ("findings[1]", True, False), ("findings[0]", True, False)
    )
    assert lr.run("record-link-valve-check", "--stage", "map-review") == 1
    assert "answered twice" in capsys.readouterr().err
    lr.valve_check("map-review", ("findings[0]", True, False), ("findings[7]", True, False))
    assert lr.run("record-link-valve-check", "--stage", "map-review") == 1
    assert "no finding of this stage" in capsys.readouterr().err


# --- the valve at the audit -------------------------------------------------------------------------------


def test_a_wording_only_reject_in_one_audit_goes_through_the_valve_and_is_published_with_the_fixed_text(
    lr: Round, capsys
):
    lr.accepted()
    assert lr.audit("wording") == 0
    assert lr.run("link-audit-plan", "--second") == 0  # a wording-only reject does not end the audits
    assert lr.audit("accept", second=True) == 0
    assert lr.run("link-valve-apply", "--stage", "audit") == 1  # no valve file yet
    capsys.readouterr()
    assert lr.publish() == 1
    assert "valve fix not applied" in capsys.readouterr().err
    lr.valve("audit", TARGET, FIXED, "first.parts[0]")
    assert lr.run("link-valve-apply", "--stage", "audit") == 1  # one valve per stage: already applied
    assert lr.publish() == 0
    assert yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"][0]["text"] == FIXED
    assert lr.changelog()[0]["change"] == f"Links added: {TARGET} after a wording fix"
    assert lr.trail()["links"] == [{"to": TARGET, "outcome": "published after a wording fix"}]
    assert f"{DATE}-{SLUG}-links-valve-audit.yaml" in lr.audit_names()


def test_the_audit_valve_context_and_a_failed_check_drops_only_that_link(lr: Round):
    lr.accepted(link(), link(SECOND))
    assert lr.audit({TARGET: "wording", SECOND: "accept"}) == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("accept", second=True) == 0
    lr.valve_file("audit", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    assert lr.run("link-valve-apply", "--stage", "audit") == 0
    assert lr.run("link-valve-check-plan", "--stage", "audit") == 0
    context = (lr.dir / "valve-check-context" / f"{SLUG}-links-audit.md").read_text(encoding="utf-8")
    assert "## Finding first.parts[0]" in context and f"OBJECTION to {TARGET}." in context
    assert f"- before: {LINK_TEXT}" in context and f"- after: {FIXED}" in context
    lr.valve_check("audit", ("first.parts[0]", False, False))
    assert lr.run("record-link-valve-check", "--stage", "audit") == 0
    assert "FAILED" in lr.output()
    assert lr.publish() == 0
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == [SECOND]
    assert lr.changelog()[0]["change"] == f"Links added: {SECOND}"
    outcomes = {x["to"]: x["outcome"] for x in lr.trail()["links"]}
    assert outcomes[TARGET].startswith("wording fix did not pass its check: first.parts[0] does not resolve")


def test_a_link_with_a_wording_reject_in_one_audit_and_a_decisive_one_in_the_other_is_dropped(lr: Round):
    lr.accepted()
    assert lr.audit("wording") == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("decisive", second=True) == 0
    assert lr.run("link-valve-apply", "--stage", "audit") == 1  # no valve: the link is dropped, not fixed
    assert lr.publish() == 0
    lr.assert_held_back("no link passed both audits")


def test_the_audit_valve_is_refused_before_both_audits_are_valid_and_when_nothing_is_wording(lr: Round, capsys):
    lr.accepted()
    lr.valve_file("audit", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    assert lr.run("link-valve-apply", "--stage", "audit") == 1  # no audit at all
    capsys.readouterr()
    assert lr.audit("accept") == 0
    assert lr.run("link-valve-apply", "--stage", "audit") == 1  # a second audit is needed
    assert "a second audit is needed" in capsys.readouterr().err
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("accept", second=True) == 0
    assert lr.run("link-valve-apply", "--stage", "audit") == 1
    assert "the valve is not open for the audit" in capsys.readouterr().err
    assert lr.run("link-valve-apply", "--stage", "map-review") == 1
    assert "the valve is not open for the map-review" in capsys.readouterr().err
    assert not (lr.dir / "valve" / f"{SLUG}-links-audit").exists()


# --- set_link_text and the guard of the link valve -------------------------------------------------------


def open_valve(lr: Round, *links: dict) -> None:
    assert lr.apply(data=proposal(*links)) == 0
    lr.review("reject", [wording(0)])
    assert lr.record_review() == 0


@pytest.mark.parametrize(
    "op, fragment",
    [
        ({"op": "set_link_text", "to": SECOND, "text": FIXED}, f"changes `{SECOND}`, which no wording finding"),
        ({"op": "set_link_text", "to": "no-such-link", "text": FIXED}, "is not a link in play at this stage"),
        ({"op": "set_link_text", "to": TARGET, "text": LINK_TEXT}, "equals the old one"),
        ({"op": "set_link_text", "to": TARGET, "text": "  " + LINK_TEXT + "  "}, "equals the old one"),
        ({"op": "set_link_text", "to": TARGET, "text": "  "}, "not a valid operations file"),
        ({"op": "set_link_text", "to": TARGET, "support": "associated", "text": FIXED}, "not a valid operations file"),
        ({"op": "set_link_text", "to": TARGET, "sources": [CITED], "text": FIXED}, "not a valid operations file"),
        (
            {"op": "remove_link", "to": TARGET},
            "holds set_link_text only",
        ),
        (
            {"op": "add_link", "to": THIRD, "support": "proposed", "text": FIXED, "sources": [CITED]},
            "holds set_link_text only",
        ),
    ],
)
def test_the_link_valve_refuses_what_is_not_a_reworded_text_of_a_named_link(lr: Round, capsys, op, fragment):
    open_valve(lr, link(), link(SECOND))
    lr.valve_file("map-review", op)
    assert lr.run("link-valve-apply", "--stage", "map-review") == 1
    assert fragment in capsys.readouterr().err
    assert not (lr.dir / "valve" / f"{SLUG}-links-map-review").exists()


def test_the_link_valve_refuses_a_file_that_names_a_paper_or_another_card_or_the_same_link_twice(lr: Round, capsys):
    open_valve(lr)
    path = lr.valve_file("map-review", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data | {"paper": "pmid:90000101"}), encoding="utf-8")
    assert lr.run("link-valve-apply", "--stage", "map-review") == 1
    assert "names no paper" in capsys.readouterr().err
    path.write_text(json.dumps(data | {"card": "another-card"}), encoding="utf-8")
    assert lr.run("link-valve-apply", "--stage", "map-review") == 1
    assert "is for card 'another-card'" in capsys.readouterr().err
    lr.valve_file(
        "map-review",
        {"op": "set_link_text", "to": TARGET, "text": FIXED},
        {"op": "set_link_text", "to": TARGET, "text": FIXED + " Again."},
    )
    assert lr.run("link-valve-apply", "--stage", "map-review") == 1
    assert "is set twice" in capsys.readouterr().err
    lr.valve_file("map-review")
    assert lr.run("link-valve-apply", "--stage", "map-review") == 1
    assert "needs at least one operation" in capsys.readouterr().err


def test_the_link_valve_refuses_a_result_that_differs_in_anything_but_the_text(lr: Round, capsys, monkeypatch):
    open_valve(lr)
    lr.valve_file("map-review", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    real = link_round.apply_operations

    def changing(old: str, new: str):
        def patched(text, ops, **kw):
            out = real(text, ops, **kw)
            items = ops.operations if hasattr(ops, "operations") else ops
            return out.replace(old, new) if any(o.op == "set_link_text" for o in items) else out

        return patched

    for old, new in (
        ("support: proposed", "support: directional"),
        (f"sources: [{CITED}]", f"sources: [{CITED}, pmid:90000104]"),
        (f"- to: {TARGET}", "- to: another-target"),
    ):
        monkeypatch.setattr(link_round, "apply_operations", changing(old, new))
        assert lr.run("link-valve-apply", "--stage", "map-review") == 1
        assert "changes more than the text" in capsys.readouterr().err
    assert not (lr.dir / "valve" / f"{SLUG}-links-map-review").exists()


def test_set_link_text_keeps_every_other_line_byte_identical(lr: Round):
    open_valve(lr, link(), link(SECOND))
    lr.valve_file("map-review", {"op": "set_link_text", "to": TARGET, "text": FIXED})
    assert lr.run("link-valve-apply", "--stage", "map-review") == 0
    new = (lr.dir / "valve" / f"{SLUG}-links-map-review" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    old = link_round._stage_text(
        lr.card.read_text(encoding="utf-8"),
        link_round.load_proposal(
            pipeline.Config(run_dir=lr.dir, cards_dir=lr.env.cards, drafts_dir=lr.env.drafts), SLUG, 1
        ),
        [TARGET, SECOND],
        {},
    )
    changed = [ln for ln in old.split("\n") if ln not in new.split("\n")]
    assert all(LINK_TEXT[:20] in ln or "feeds B" in ln or "patients" in ln for ln in changed)
    assert old.split("\n")[0] == new.split("\n")[0] and old.split("\n")[-1] == new.split("\n")[-1]


def test_set_link_text_is_refused_outside_a_link_round(lr: Round, tmp_path: Path):
    op = {"op": "set_link_text", "to": TARGET, "text": FIXED}
    ops = parse_ops({"card": SLUG, "paper": None, "operations": [op]})
    # a correction round's ops file
    assert any("operations[0] is set_link_text" in p for p in pipeline.correction_ops_problems(ops, 2))
    # the correction valve
    text = lr.card.read_text(encoding="utf-8")
    new, problems = pipeline.apply_valve(text, ops, {"core_claim"})
    assert new is None and any("operations[0] is set_link_text" in p for p in problems)
    # the weekly apply
    (tmp_path / "weekly").mkdir()
    env = Env(tmp_path / "weekly")
    env.prepare()
    assert env.classify() == 0
    path = env.run / "ops" / f"{SLUG}-90000101-r1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"card": SLUG, "paper": "pmid:90000101", "operations": [op]}), encoding="utf-8")
    assert env.cli("apply", SLUG, str(path), "--round", "1") == 1
    assert "operations[0] is set_link_text: only a link round" in "\n".join(env.out)


# --- the names in audits/ of a second round on the same card and date ------------------------------------


def test_a_second_link_round_on_the_same_card_and_date_gets_names_with_an_attempt_suffix(lr: Round, tmp_path: Path):
    lr.audited()
    assert lr.publish() == 0
    first_names = lr.audit_names()
    assert first_names == [
        f"{DATE}-{SLUG}-links-second.yaml",
        f"{DATE}-{SLUG}-links-trail.yaml",
        f"{DATE}-{SLUG}-links.yaml",
    ]
    first_bytes = {n: (lr.audits / n).read_bytes() for n in first_names}
    lr.dir = tmp_path / "links" / f"{DATE}-{SLUG}-2"  # a new run folder; the card now holds the first link
    lr.card_bytes = lr.card.read_bytes()
    assert lr.apply(data=proposal(link(SECOND))) == 0
    lr.review()
    assert lr.record_review() == 0
    assert lr.run("link-audit-plan") == 0
    assert lr.audit("accept") == 0
    assert lr.run("link-audit-plan", "--second") == 0
    assert lr.audit("accept", second=True) == 0
    assert lr.publish() == 0
    assert [x["to"] for x in yaml.safe_load(lr.card.read_text(encoding="utf-8"))["links"]] == [TARGET, SECOND]
    assert lr.audit_names() == sorted(
        [
            *first_names,
            f"{DATE}-{SLUG}-links-2-second.yaml",
            f"{DATE}-{SLUG}-links-2-trail.yaml",
            f"{DATE}-{SLUG}-links-2.yaml",
        ]
    )
    assert {n: (lr.audits / n).read_bytes() for n in first_names} == first_bytes  # nothing overwritten
    trail = yaml.safe_load((lr.audits / f"{DATE}-{SLUG}-links-2-trail.yaml").read_text(encoding="utf-8"))
    assert trail["audits_run"] == [f"{DATE}-{SLUG}-links-2.yaml", f"{DATE}-{SLUG}-links-2-second.yaml"]
    assert [e["change"] for e in lr.changelog()] == [f"Links added: {TARGET}", f"Links added: {SECOND}"]
