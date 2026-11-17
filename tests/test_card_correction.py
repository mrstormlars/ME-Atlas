"""Tests for the correction of a published card (``me_atlas.card_correction``) and ``remove_comment``.

Fictional card, papers and agent output (tests/fixtures/pipeline) in tmp ``cards/`` and ``audits/`` folders. No test
touches the network, an AI or git.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_pipeline import SLUG, Env, fulltext_loader
from test_publish_card import whole

from me_atlas import card_correction, link_round, pipeline
from me_atlas.operations import OperationError, apply_operations, comment_target, parse_ops

DATE = "2026-11-17"
STUDY = "pmid:90000100"
OTHER_STUDY = "pmid:90000104"
CTX = "pmid:90000105"  # a study whose role is context
TARGET = "other-fictional-card"
SECOND = "second-target"
FINDING_NEW = "A fictional study found widget signalling to be lower in the patients."
GROUP_NEW = "Reworded Fictional Group"
LINK_NEW = "A fictional review proposes that A feeds B."
STUDY_NOTE = "STALE-STUDY-NOTE the group was not checked"
LINK_NOTE = "LINK-NOTE written before the review"

CTX_BLOCK = """  - id: pmid:90000105
    title: Fictional background study of widget signalling.
    year: 2019
    cohort: me_cfs
    case_definition: unverified
    case_definition_source: null
    case_definition_quote: null
    design: other
    n_patients: null
    n_controls: null
    measures_pem: false
    preregistered: null
    role: context
    direction: not_applicable
    group: Context Group, Fictional University
    finding: A fictional background study described widget signalling without a patient comparison.
"""

LINKS = f"""layer: mechanism
links:
  # {LINK_NOTE}
  - to: {TARGET}
    support: proposed
    text: >-
      A fictional review proposes that A feeds B; it was not studied directly in patients.
    sources: [{STUDY}]
  - to: {SECOND}
    support: associated
    text: A second fictional link text.
    sources: [{STUDY}]
"""


def finding(targets: list[str], klass: str = "wording", target: str | None = None, **over) -> dict:
    data = {
        "operation": None,
        "severity": "must_fix",
        "class": klass,
        "targets": targets,
        "problem": f"PROBLEM about {targets[0]}.",
        "fix": "Say what the source says.",
    }
    if klass == "wording":
        data["target"] = target or targets[0]
    return data | over


STUDY_FINDING = finding(
    [f"studies[{CTX}].finding", f"studies[{CTX}].group", f"studies[{STUDY}].finding"], target=f"studies[{CTX}].finding"
)
LINK_FINDING = finding(["links[0]"])
OPS_TIER1 = [
    {"op": "update_study", "id": CTX, "set": {"finding": FINDING_NEW, "group": GROUP_NEW}},
    {"op": "set_link_text", "to": TARGET, "text": LINK_NEW},
]
ACCEPT = {"card": SLUG, "paper": None, "verdict": "accept", "findings": []}


class Corr:
    """A published card in tmp ``cards/`` (layer mechanism, two links, a comment line in a study and in the links) and a
    correction folder DIR beside it."""

    def __init__(self, env: Env, tmp: Path):
        self.env = env
        self.dir = tmp / "corrections" / f"{DATE}-{SLUG}"
        self.audits = env.root / "audits"
        self.card = env.cards / f"{SLUG}.yaml"
        self.log = env.cards / pipeline.CHANGELOG_NAME
        text = (env.drafts / f"{SLUG}.yaml").read_text(encoding="utf-8")
        text = text.replace("by: ai_pair", "by: ai_audit")
        text = text.replace("last_checked:\n", CTX_BLOCK + "last_checked:\n", 1)
        text = text.replace("    role: supports\n", f"    role: supports\n    # {STUDY_NOTE}\n", 1)
        text = text.replace("last_checked:\n", LINKS + "last_checked:\n", 1)
        self.card.write_text(text, encoding="utf-8", newline="\n")
        (env.drafts / f"{SLUG}.yaml").unlink()
        for name in (TARGET, SECOND):
            (env.cards / f"{name}.yaml").write_text("", encoding="utf-8")
        self.card_bytes = self.card.read_bytes()

    # -- running commands --
    def main(self, *argv: str) -> int:
        return pipeline.main([*argv, *self.env.dir_args], fulltext=fulltext_loader(), out=self.env.out.append)

    def run(self, command: str, *extra: str) -> int:
        return self.main(command, SLUG, "--run-dir", str(self.dir), *extra)

    def output(self) -> str:
        return "\n".join(self.env.out)

    # -- the files of the operator and the agents --
    def request(self, items: list[dict] | None = None, raw: str | None = None, **over) -> Path:
        path = self.dir / "request.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "card": SLUG,
            "origin": "an audit record of 2026-11-16 (fictional)",
            "items": items
            or [{"target": f"studies[{STUDY}].finding", "problem": "REQUEST-MARKER the finding is off."}],
        } | over
        path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        return path

    def pre(self, findings: list[dict] | None = None, **over) -> Path:
        path = self.dir / "review" / f"{SLUG}-pre.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        findings = [STUDY_FINDING, LINK_FINDING] if findings is None else findings
        data = {"card": SLUG, "paper": None, "verdict": "reject" if findings else "accept", "findings": findings}
        path.write_text(json.dumps(data | over), encoding="utf-8")
        return path

    def planned(self, findings: list[dict] | None = None) -> None:
        """Steps 0 to 2: the request, the reviewed card, the drafter's context."""
        self.request()
        assert self.run("correct-review-plan") == 0
        self.pre(findings)
        assert self.run("correct-record-review", "--pre") == 0
        assert self.run("correct-plan") == 0

    def ops(self, operations: list[dict] | None = None, n: int = 1) -> Path:
        path = self.dir / "ops" / f"{SLUG}-r{n}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"card": SLUG, "paper": None, "operations": OPS_TIER1 if operations is None else operations}),
            encoding="utf-8",
        )
        return path

    def apply(self, operations: list[dict] | None = None, n: int = 1) -> int:
        self.ops(operations, n)
        return self.run("correct-apply", "--round", str(n))

    def review(self, verdict: str = "accept", findings: list[dict] | None = None, n: int = 1) -> Path:
        if findings is None:
            findings = (
                []
                if verdict == "accept"
                else [finding(["links[0]"], "decisive", problem="REVIEW-MARKER.", fix="Lower it.")]
            )
        path = self.dir / "review" / f"{SLUG}-r{n}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"card": SLUG, "paper": None, "verdict": verdict, "findings": findings}), encoding="utf-8"
        )
        return path

    def accepted(self, findings: list[dict] | None = None, operations: list[dict] | None = None) -> None:
        """Round 1 applied and accepted."""
        self.planned(findings)
        assert self.apply(operations) == 0, self.output()
        self.review()
        assert self.run("correct-record-review", "--round", "1") == 0

    def write_audit(self, data: dict | str, second: bool = False) -> Path:
        path = self.dir / "audit" / f"{SLUG}{'-second' if second else ''}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def audit(self, decision: str = "accept", second: bool = False) -> int:
        """Plan (the context), write and record one audit."""
        assert self.run("correct-audit-plan", *(["--second"] if second else [])) == 0
        data = whole("accept") if decision == "accept" else whole("reject")
        self.write_audit(data, second)
        return self.run("correct-record-audit", *(["--second"] if second else []))

    def publish(self, *extra: str) -> int:
        return self.run("correct-publish", "--date", DATE, *extra)

    # -- reading results --
    def text(self) -> str:
        return self.card.read_text(encoding="utf-8")

    def report(self) -> str:
        return (self.dir / "correction-report.md").read_text(encoding="utf-8")

    def changelog(self) -> list[dict]:
        return yaml.safe_load(self.log.read_text(encoding="utf-8")) if self.log.is_file() else []

    def audit_names(self) -> list[str]:
        return sorted(p.name for p in self.audits.glob("*.yaml")) if self.audits.is_dir() else []

    def trail(self, stem: str = f"{DATE}-{SLUG}-correction-published") -> dict:
        return yaml.safe_load((self.audits / f"{stem}-trail.yaml").read_text(encoding="utf-8"))

    def assert_held_back(self, reason: str) -> None:
        assert self.card.read_bytes() == self.card_bytes and not self.log.exists()
        assert "Outcome: held back" in self.report() and f"Held back: {reason}" in self.report(), self.report()
        assert self.trail()["outcome"] == reason

    def assert_nothing_written(self) -> None:
        assert self.card.read_bytes() == self.card_bytes and not self.log.exists()
        assert not self.audits.exists() or not list(self.audits.iterdir())


@pytest.fixture
def corr(tmp_path: Path) -> Corr:
    return Corr(Env(tmp_path), tmp_path)


def written(corr: Corr, *folders: str) -> list[str]:
    return [f for f in folders if (corr.dir / f).exists()]


# --- step 0 and 1: the request and the review of the published card ----------------------------------------------


def test_review_plan_writes_the_card_the_request_the_checklist_and_the_author_facts(corr: Corr):
    corr.request()
    assert corr.run("correct-review-plan") == 0
    text = (corr.dir / "card-review-context" / f"{SLUG}-pre.md").read_text(encoding="utf-8")
    assert (
        "slug: fictional-pipeline-card" in text and "REQUEST-MARKER" in text and "an audit record of 2026-11-16" in text
    )
    assert "Case-definition labels" in text and "Author facts" in text  # the whole-card checklist, the author facts
    assert f"`{STUDY}`" not in text.split("## 1.")[0]  # the cited records are named by path in section 2
    assert "STALE-STUDY-NOTE" not in text and "LINK-NOTE" not in text and "a comment inside a badge" not in text
    assert f"{SLUG}-pre.json" in text and "`class`" in text
    assert corr.card.read_bytes() == corr.card_bytes


def test_review_plan_refuses_when_the_card_is_not_in_cards(corr: Corr, capsys):
    corr.card.unlink()
    corr.request()
    assert corr.run("correct-review-plan") == 1
    assert "no published card" in capsys.readouterr().err
    assert not (corr.dir / "card-review-context").exists()


def test_review_plan_refuses_when_a_draft_of_the_card_exists(corr: Corr, capsys):
    (corr.env.drafts / f"{SLUG}.yaml").write_text(corr.text(), encoding="utf-8")
    corr.request()
    assert corr.run("correct-review-plan") == 1
    assert "draft under way" in capsys.readouterr().err
    assert not (corr.dir / "card-review-context").exists()


@pytest.mark.parametrize(
    "raw, fragment",
    [
        (None, "does not exist"),
        ("{not json", "not readable JSON"),
        (json.dumps({"card": SLUG, "origin": "x"}), "malformed"),  # no items
        (json.dumps({"card": SLUG, "origin": "x", "items": []}), "malformed"),
        (json.dumps({"card": SLUG, "origin": "x\ny", "items": [{"target": "core_claim", "problem": "p"}]}), "one line"),
        (json.dumps({"card": SLUG, "origin": "x", "items": [{"target": "core_claim"}]}), "malformed"),
        (
            json.dumps({"card": "another-card", "origin": "x", "items": [{"target": "core_claim", "problem": "p"}]}),
            "expected",
        ),
        (
            json.dumps({"card": SLUG, "origin": "x", "items": [{"target": "level_reason[7]", "problem": "p"}]}),
            "does not exist",
        ),
        (
            json.dumps({"card": SLUG, "origin": "x", "items": [{"target": "studies[pmid:1]", "problem": "p"}]}),
            "not on the card",
        ),
        (
            json.dumps({"card": SLUG, "origin": "x", "items": [{"target": "links[5]", "problem": "p"}]}),
            "does not exist",
        ),
        (
            json.dumps({"card": SLUG, "origin": "x", "items": [{"target": "a nonsense", "problem": "p"}]}),
            "not a target",
        ),
        (
            json.dumps(
                {"card": SLUG, "origin": "x", "items": [{"target": f"studies[{STUDY}].nonfield", "problem": "p"}]}
            ),
            "not a field of a study",
        ),
    ],
)
def test_review_plan_refuses_a_missing_malformed_or_untargeted_request(corr: Corr, capsys, raw, fragment):
    if raw is not None:
        corr.request(raw=raw)
    assert corr.run("correct-review-plan") == 1
    assert fragment in capsys.readouterr().err
    assert not (corr.dir / "card-review-context").exists()


def test_record_pre_review_needs_targets_and_class_on_every_finding(corr: Corr, capsys):
    corr.request()
    bad = {"operation": None, "severity": "advisory", "problem": "P."}
    corr.pre([bad])
    assert corr.run("correct-record-review", "--pre") == 1
    err = capsys.readouterr().err
    assert "needs `targets`" in err and "needs `class`" in err  # an advisory finding too
    corr.pre([finding([f"studies[{STUDY}].finding"], "decisive") | {"operation": 0}])
    assert corr.run("correct-record-review", "--pre") == 1
    assert "operation must be null" in capsys.readouterr().err
    corr.pre([finding(["level_reason[9]"], "decisive")])
    assert corr.run("correct-record-review", "--pre") == 1
    assert "does not exist" in capsys.readouterr().err
    corr.pre([finding(["links[0]"], "wording", target="links[1]")])
    assert corr.run("correct-record-review", "--pre") == 1
    assert "not one of its `targets`" in capsys.readouterr().err
    corr.pre([finding(["level"], "wording")])  # a wording finding names a free-text item
    assert corr.run("correct-record-review", "--pre") == 1
    assert "wording finding needs a target naming a free-text item" in capsys.readouterr().err


def test_record_pre_review_accepts_an_advisory_finding_and_a_group_as_wording(corr: Corr):
    corr.request()
    corr.pre([finding([f"studies[{CTX}].group"], severity="advisory")])
    assert corr.run("correct-record-review", "--pre") == 0
    assert corr.run("correct-plan") == 0


def test_a_review_with_no_finding_ends_the_path(corr: Corr, capsys):
    corr.request()
    assert corr.run("correct-review-plan") == 0
    corr.pre([])
    assert corr.run("correct-record-review", "--pre") == 0
    assert "nothing to correct" in corr.output()
    assert corr.run("correct-plan") == 1
    assert "no finding" in capsys.readouterr().err
    assert not (corr.dir / "correction-context").exists()
    assert corr.card.read_bytes() == corr.card_bytes


# --- step 2: correct-plan ----------------------------------------------------------------------------------------


def test_plan_refuses_without_a_recorded_review(corr: Corr, capsys):
    corr.request()
    assert corr.run("correct-plan") == 1
    assert "no valid review" in capsys.readouterr().err
    corr.pre()  # written, not recorded: it is read as the file it is, so it is valid; but a missing one is refused
    (corr.dir / "review" / f"{SLUG}-pre.json").unlink()
    assert corr.run("correct-plan") == 1
    assert not (corr.dir / "correction-context").exists()


def test_plan_holds_the_card_the_findings_the_limits_and_the_targets(corr: Corr):
    corr.planned()
    text = (corr.dir / "correction-context" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert STUDY_NOTE in text  # the card is shown as it stands, comments included
    assert "PROBLEM about" in text and "class wording" in text and f"`studies[{CTX}].group`" in text
    assert "`set_link_text`" in text and "`remove_comment`" in text and "No `add_study`" in text
    assert "Functional Specification" in text or "Evidence ladder" in text  # sections 2 and 3
    assert "REQUEST-MARKER" not in text  # the request is data for the reviewer, not for the drafter


# --- step 3: correct-apply --------------------------------------------------------------------------------------


def test_apply_makes_applied_card_diff_and_checks_and_never_writes_cards(corr: Corr):
    corr.planned()
    assert corr.apply() == 0
    checks = json.loads((corr.dir / "checks" / f"{SLUG}-r1.json").read_text(encoding="utf-8"))
    assert checks["passed"] is True
    applied = corr.dir / "applied" / f"{SLUG}-r1"
    data = yaml.safe_load((applied / f"{SLUG}.yaml").read_text(encoding="utf-8"))
    assert data["studies"][2]["finding"] == FINDING_NEW and data["links"][0]["text"] == LINK_NEW
    assert "+    group: Reworded Fictional Group" in (applied / "changes.diff").read_text(encoding="utf-8")
    assert corr.card.read_bytes() == corr.card_bytes and not corr.log.exists()
    assert "PASSED" in corr.output()


@pytest.mark.parametrize(
    "operation",
    [
        {
            "op": "add_study",
            "study": {
                "id": "pmid:90000100",
                "title": "t",
                "year": 2020,
                "cohort": "me_cfs",
                "case_definition": "unverified",
                "case_definition_source": None,
                "case_definition_quote": None,
                "design": "controlled",
                "n_patients": 1,
                "n_controls": 1,
                "measures_pem": False,
                "preregistered": None,
                "role": "supports",
                "direction": "lower",
                "finding": "f",
            },
        },
        {"op": "add_paragraph", "field": "subgroups", "text": "A subgroup.", "sources": [STUDY]},
        {"op": "add_link", "to": "third-target", "support": "proposed", "text": "T.", "sources": [STUDY]},
        {
            "op": "add_sentence",
            "target": "level_reason[0]",
            "text": "A sentence.",
            "sources": [STUDY],
            "answers": {"record": "x.yaml", "part": 0},
        },
    ],
    ids=["add_study", "add_paragraph", "add_link", "add_sentence"],
)
def test_apply_refuses_an_operation_that_adds_and_writes_nothing(corr: Corr, capsys, operation):
    corr.planned()
    path = corr.ops([operation])
    if operation["op"] == "add_study":  # without a paper the file does not even parse; with one, the limits refuse it
        data = json.loads(path.read_text(encoding="utf-8")) | {"paper": STUDY}
        path.write_text(json.dumps(data), encoding="utf-8")
    assert corr.run("correct-apply", "--round", "1") == 1
    assert "the correction of a published card may hold" in capsys.readouterr().err
    assert written(corr, "checks", "applied") == []
    assert corr.card.read_bytes() == corr.card_bytes


def test_apply_refuses_an_operation_whose_target_no_finding_names(corr: Corr, capsys):
    corr.planned([LINK_FINDING])  # only links[0]
    assert corr.apply([OPS_TIER1[0]]) == 1  # update_study of a study
    assert f"changes studies[{CTX}], which no finding" in capsys.readouterr().err
    assert corr.apply([{"op": "set_link_text", "to": SECOND, "text": "Reworded."}]) == 1  # links[1]
    assert "changes links[1], which no finding" in capsys.readouterr().err
    assert (
        corr.apply([{"op": "replace_paragraph", "field": "level_reason", "index": 0, "text": "T.", "sources": [STUDY]}])
        == 1
    )
    assert "level_reason[0], which no finding" in capsys.readouterr().err
    assert written(corr, "checks", "applied") == []
    assert corr.apply([OPS_TIER1[1]]) == 0  # links[0] is named


def test_apply_refuses_the_limits_of_a_correction(corr: Corr, capsys):
    corr.planned([finding(["level"], "decisive"), finding(["badges.explains_pem"], "decisive")])
    rungs = {"op": "propose", "target": "level", "value": 3, "reason": [{"text": "T.", "sources": [STUDY]}]}
    assert corr.apply([rungs]) == 1  # level only lower (the card's is 2)
    assert "may only lower the level" in capsys.readouterr().err
    badge = {"op": "propose", "target": "explains_pem", "value": True, "reason": [{"text": "T.", "sources": [STUDY]}]}
    assert corr.apply([badge]) == 1
    assert "only set a badge to false" in capsys.readouterr().err
    assert corr.apply([]) == 1
    assert "at least one operation" in capsys.readouterr().err
    assert written(corr, "checks", "applied") == []


def test_apply_refuses_a_card_for_another_card_and_a_missing_ops_file(corr: Corr, capsys):
    corr.planned()
    assert corr.run("correct-apply", "--round", "1") == 1
    assert "does not exist" in capsys.readouterr().err
    path = corr.ops()
    path.write_text(json.dumps({"card": "another-card", "paper": None, "operations": OPS_TIER1}), encoding="utf-8")
    assert corr.run("correct-apply", "--round", "1") == 1
    assert "not 'fictional-pipeline-card'" in capsys.readouterr().err


def test_apply_refuses_a_correction_that_changes_nothing(corr: Corr, capsys):
    corr.planned()
    same = {
        "op": "set_link_text",
        "to": TARGET,
        "text": "A fictional review proposes that A feeds B; it was not studied directly in patients.",
    }
    assert corr.apply([same]) == 1
    assert "changes nothing" in capsys.readouterr().err
    assert written(corr, "checks") == []


def test_apply_refuses_without_a_recorded_review_of_the_card(corr: Corr, capsys):
    corr.ops()
    corr.request()
    assert corr.run("correct-apply", "--round", "1") == 1
    assert "no valid review of the published card" in capsys.readouterr().err
    corr.pre([])
    assert corr.run("correct-apply", "--round", "1") == 1
    assert "nothing to correct" in capsys.readouterr().err
    assert written(corr, "checks", "applied") == []


def test_a_failed_check_may_be_tried_again_three_times_in_all(corr: Corr, capsys):
    corr.planned()
    # the validator fails on a study whose recognised case definition has no source
    broken = {"op": "update_study", "id": STUDY, "set": {"case_definition": "CCC", "case_definition_source": None}}
    for _ in range(3):
        assert corr.apply([broken]) == 1
        assert "FAILED" in corr.output()
    assert corr.apply() == 1  # the fourth try is refused, even with a good file
    assert "failed its checks 3 times" in capsys.readouterr().err
    assert sorted(p.name for p in (corr.dir / "ops").glob("*attempt*")) == [
        f"{SLUG}-r1-attempt{i}.json" for i in (1, 2, 3)
    ]
    assert sorted(p.name for p in (corr.dir / "checks").glob("*attempt*")) == [
        f"{SLUG}-r1-attempt{i}.json" for i in (1, 2, 3)
    ]


def test_a_failed_check_that_is_fixed_in_a_later_try_passes(corr: Corr):
    corr.planned()
    broken = {"op": "update_study", "id": STUDY, "set": {"case_definition": "CCC", "case_definition_source": None}}
    assert corr.apply([broken]) == 1
    assert corr.apply() == 0
    checks = json.loads((corr.dir / "checks" / f"{SLUG}-r1.json").read_text(encoding="utf-8"))
    assert checks["passed"] is True and (corr.dir / "checks" / f"{SLUG}-r1-attempt1.json").is_file()


def test_a_round_that_passed_is_not_applied_again_and_a_reviewed_round_neither(corr: Corr, capsys):
    corr.planned()
    assert corr.apply() == 0
    assert corr.apply() == 1
    assert "passed its checks" in capsys.readouterr().err
    corr.review()
    assert corr.apply() == 1
    assert "already has a review" in capsys.readouterr().err


def test_round_2_without_a_rejecting_round_1_review_is_refused(corr: Corr, capsys):
    corr.planned()
    assert corr.apply(n=2) == 1  # no round 1 at all
    assert "round 2 needs a valid reject" in capsys.readouterr().err
    assert corr.apply() == 0
    corr.review("accept")
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert corr.apply(n=2) == 1  # round 1 was accepted
    assert "found: accept" in capsys.readouterr().err
    assert not (corr.dir / "checks" / f"{SLUG}-r2.json").exists()


def test_round_2_applies_to_the_card_after_a_rejecting_round_1(corr: Corr):
    corr.planned()
    assert corr.apply() == 0
    corr.review("reject")
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert corr.apply([OPS_TIER1[1]], n=2) == 0
    data = yaml.safe_load((corr.dir / "applied" / f"{SLUG}-r2" / f"{SLUG}.yaml").read_text(encoding="utf-8"))
    assert data["links"][0]["text"] == LINK_NEW and data["studies"][0]["group"].startswith(
        "Fictional Group"
    )  # not round 1


# --- step 4: the review of a round ------------------------------------------------------------------------------


def test_record_review_validates_the_round_review(corr: Corr, capsys):
    corr.planned()
    assert corr.apply() == 0
    corr.review("accept", [{"operation": 5, "severity": "advisory", "problem": "P."}])
    assert corr.run("correct-record-review", "--round", "1") == 1
    assert "out of range" in capsys.readouterr().err
    corr.review("reject", [{"operation": 0, "severity": "must_fix", "problem": "P."}])
    assert corr.run("correct-record-review", "--round", "1") == 1
    assert "needs `targets`" in capsys.readouterr().err
    (corr.dir / "review" / f"{SLUG}-r1.json").write_text(
        json.dumps({"card": SLUG, "paper": None, "verdict": "accept", "findings": [{"severity": "must_fix"}]}),
        encoding="utf-8",
    )
    assert corr.run("correct-record-review", "--round", "1") == 1
    corr.review("accept")
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert corr.run("correct-record-review") == 1  # neither --pre nor --round
    assert "--pre (step 1) or --round N" in capsys.readouterr().err


# --- tiers ------------------------------------------------------------------------------------------------------


def test_wording_only_change_with_wording_classes_is_tier_1_and_publishes_on_the_review_with_no_audit(corr: Corr):
    corr.accepted()
    assert corr.run("correct-audit-plan") == 1  # nothing to audit: tier 1
    assert not (corr.dir / "audit-context").exists()
    assert corr.publish() == 0
    assert "Outcome: published" in corr.report() and "Tier: 1" in corr.report()
    old = corr.card_bytes.decode().split("\n")
    new = corr.text().split("\n")
    changed = [line for line in new if line not in old]
    assert any(FINDING_NEW.split(" found ")[0] in x or "widget signalling to be lower" in x for x in changed)
    assert not any("last_checked" in x for x in changed)
    data = yaml.safe_load(corr.text())
    assert data["last_checked"]["by"] == "ai_audit" and str(data["last_checked"]["date"]) == "2026-10-01"  # unchanged
    assert data["studies"][2]["finding"] == FINDING_NEW and data["studies"][2]["group"] == GROUP_NEW
    assert data["links"][0]["text"] == LINK_NEW
    assert STUDY_NOTE in corr.text() and LINK_NOTE in corr.text()  # comments elsewhere are kept
    (entry,) = corr.changelog()
    assert (
        entry["change"]
        == f"Correction: the finding and group of {CTX} reworded; the text of the link to {TARGET} reworded"
    )
    assert entry["reason"] == (
        "The review agent found that 2 item(s) did not say what the cited source says: "
        f"studies[{CTX}].finding, links[0]."
    )
    assert "\n" not in entry["reason"] and "PROBLEM" not in entry["reason"]
    assert entry["tier"] == 1 and entry["decided_by"] == "ai_pair" and str(entry["date"]) == DATE
    assert entry["sources"] == [CTX, STUDY]
    assert corr.audit_names() == [f"{DATE}-{SLUG}-correction-published-trail.yaml"]  # no audit record: none was run
    trail = corr.trail()
    assert trail["outcome"] == "published" and trail["tier"]["tier"] == 1 and trail["audits_run"] == []
    assert trail["card"] == SLUG and len(trail["card_sha256"]) == 64 and trail["origin"].startswith("an audit record")
    assert trail["request"][0]["target"] == f"studies[{STUDY}].finding"
    assert trail["review"]["findings"][0]["class"] == "wording"
    assert (
        trail["rounds"][0]["operations"][0]["op"] == "update_study"
        and trail["rounds"][0]["review"]["verdict"] == "accept"
    )
    assert f"ME-Atlas-Pipeline: weekly-run {DATE}" in corr.output()


def test_the_same_change_classed_decisive_is_tier_2(corr: Corr, capsys):
    decisive = finding([f"studies[{CTX}].finding", f"studies[{CTX}].group"], "decisive")
    corr.accepted([decisive, LINK_FINDING])
    assert corr.publish() == 1  # tier 2: no audit yet
    assert "tier 2 needs two audits" in capsys.readouterr().err
    assert corr.run("correct-audit-plan") == 0  # the audit plan is open for it
    assert corr.card.read_bytes() == corr.card_bytes and not corr.log.exists()


def test_a_decisive_link_finding_alone_makes_it_tier_2(corr: Corr, capsys):
    corr.accepted([STUDY_FINDING, finding(["links[0]"], "decisive")])
    assert corr.publish("--dry-run") == 1
    assert "tier 2 needs two audits" in capsys.readouterr().err


def test_a_changed_case_definition_is_tier_2_even_with_wording_classes(corr: Corr, capsys):
    icc = {"case_definition": "ICC", "case_definition_quote": "Participants met the Canadian Consensus Criteria."}
    ops = [{"op": "update_study", "id": STUDY, "set": {"finding": FINDING_NEW} | icc}]
    corr.accepted(operations=ops)
    assert corr.publish() == 1
    assert "tier 2 needs two audits" in capsys.readouterr().err
    decision = card_correction.decide_tier(
        corr.text(),
        (corr.dir / "applied" / f"{SLUG}-r1" / f"{SLUG}.yaml").read_text(encoding="utf-8"),
        parse_ops({"card": SLUG, "paper": None, "operations": ops}),
        card_correction.load_pre_review(
            pipeline.Config(corr.dir, corr.env.cards, corr.env.drafts, corr.env.cache, pipeline.DEFAULT_SPEC), SLUG
        )[0],
        pipeline._load_card(corr.card),
    )
    assert decision.tier == 2 and any("case_definition" in r for r in decision.reasons)


def test_a_numeral_added_to_a_finding_is_tier_2_even_with_wording_classes(corr: Corr, capsys):
    plain = corr.text().replace(
        "A study of n=20 patients and 20 controls found lower widget signalling in patients.",
        "A study found lower widget signalling in patients.",
    )
    corr.card.write_text(plain, encoding="utf-8", newline="\n")
    corr.card_bytes = corr.card.read_bytes()
    ops = [
        {"op": "update_study", "id": STUDY, "set": {"finding": "A study of 20 patients found lower widget signalling."}}
    ]
    corr.accepted(operations=ops)
    assert corr.publish() == 1  # the numeral 20 is in the record, so the checks pass; it is new in this text: tier 2
    assert "tier 2 needs two audits" in capsys.readouterr().err
    new = yaml.safe_load(plain.replace("A study found lower", "A study of 20 patients found lower"))
    assert card_correction.structural_differences(yaml.safe_load(plain), new) == [
        f"studies[{STUDY}].finding: the numeral(s) 20 are new"
    ]


def test_structural_differences_name_what_is_more_than_wording(corr: Corr):
    old = yaml.safe_load(corr.card_bytes.decode())

    def changed(edit) -> list[str]:
        new = yaml.safe_load(corr.card_bytes.decode())
        edit(new)
        return card_correction.structural_differences(old, new)

    assert changed(lambda d: None) == []
    assert changed(lambda d: d["studies"][0].update(finding="A reworded finding of the fictional study.")) == []
    assert changed(lambda d: d["studies"][2].update(group="Another group")) == []
    assert changed(lambda d: d["studies"][0].update(group="Another group")) == [f"studies[{STUDY}].group differs"]
    assert changed(lambda d: d["links"][0].update(text="A reworded link text.")) == []
    assert changed(lambda d: d["level_reason"].update(text="A reworded reason of the fictional study.")) == []
    assert changed(lambda d: d.update(level=1)) == ["level differs beyond free text"]
    assert changed(lambda d: d["studies"][0].update(role="contradicts")) == [f"studies[{STUDY}].role differs"]
    assert changed(lambda d: d["links"][0].update(support="directional")) == [f"links[{TARGET}].support differs"]
    assert changed(lambda d: d["links"][0].update(sources=[OTHER_STUDY])) == [f"links[{TARGET}].sources differs"]
    assert changed(lambda d: d["core_claim"].update(text="A reworded core claim.")) == [
        "core_claim differs beyond free text"
    ]
    assert changed(lambda d: d["contested"].update(rungs=[3])) == ["contested differs beyond free text"]
    assert changed(lambda d: d["level_reason"].update(sources=[OTHER_STUDY])) == ["level_reason[0]: the sources differ"]
    assert changed(lambda d: d["contested"]["reason"].pop()) == [
        "contested_reason has 2 paragraph(s) before and 1 after"
    ]
    assert changed(lambda d: d["links"].pop()) == ["links differ (one added, removed or reordered)"]
    assert changed(lambda d: d["links"][1].update(text="A second fictional link text of 5 words.")) == [
        "links[1].text: the numeral(s) 5 are new"
    ]
    assert changed(lambda d: d["studies"][2].update(group="Group 12")) == [
        f"studies[{CTX}].group: the numeral(s) 12 are new"
    ]


def test_a_numeral_that_was_in_the_text_before_is_not_new(corr: Corr):
    old = yaml.safe_load(corr.card_bytes.decode())
    new = yaml.safe_load(corr.card_bytes.decode())
    new["studies"][0]["finding"] = "Among 20 patients and 20 controls, widget signalling was lower in patients (n=20)."
    assert card_correction.structural_differences(old, new) == []


# --- holds ------------------------------------------------------------------------------------------------------


def test_round_2_rejected_holds_the_card_back_and_writes_no_audit_context(corr: Corr):
    corr.planned()
    assert corr.apply() == 0
    corr.review("reject")
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert corr.apply([OPS_TIER1[1]], n=2) == 0
    corr.review("reject", n=2)
    assert corr.run("correct-record-review", "--round", "2") == 0
    assert corr.publish() == 0
    corr.assert_held_back("the review rejected round 2")
    assert not (corr.dir / "audit-context").exists() and "Held back" in corr.output()
    assert corr.run("correct-audit-plan") == 1  # never audited
    assert not (corr.dir / "audit-context").exists()
    assert [r["round"] for r in corr.trail()["rounds"]] == [1, 2]
    assert corr.trail()["audits_run"] == []


def test_round_1_rejected_and_no_round_2_holds_the_card_back(corr: Corr):
    corr.planned()
    assert corr.apply() == 0
    corr.review("reject")
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert corr.publish() == 0
    corr.assert_held_back("the review rejected round 1; no round 2 was applied")


def test_failed_checks_hold_the_card_back(corr: Corr):
    corr.planned()
    broken = {"op": "update_study", "id": STUDY, "set": {"case_definition": "CCC", "case_definition_source": None}}
    assert corr.apply([broken]) == 1
    assert corr.publish() == 0
    corr.assert_held_back("the checks of round 1 failed")


def test_a_missing_review_holds_the_card_back(corr: Corr):
    corr.planned()
    assert corr.apply() == 0
    assert corr.publish() == 0
    assert corr.trail()["outcome"].startswith("no valid review of round 1: no review")
    assert corr.card.read_bytes() == corr.card_bytes and not corr.log.exists()


def tier_2(corr: Corr) -> None:
    corr.accepted([finding([f"studies[{CTX}].finding", f"studies[{CTX}].group"], "decisive"), LINK_FINDING])


def test_tier_2_first_audit_reject_holds_the_card_back_with_no_second_audit(corr: Corr, capsys):
    tier_2(corr)
    assert corr.audit("reject") == 0
    assert corr.run("correct-audit-plan", "--second") == 1  # not needed
    assert "no second audit" in capsys.readouterr().err
    assert not (corr.dir / "audit-context" / f"{SLUG}-second.md").exists()
    assert corr.publish() == 0
    corr.assert_held_back("the first audit decided reject; no second audit was run (sequential audits)")
    assert corr.audit_names() == [
        f"{DATE}-{SLUG}-correction-published-trail.yaml",
        f"{DATE}-{SLUG}-correction-published.yaml",
    ]
    assert corr.trail()["audits_run"] == [f"{DATE}-{SLUG}-correction-published.yaml"]


def test_tier_2_first_accept_second_reject_holds_the_card_back(corr: Corr):
    tier_2(corr)
    assert corr.audit("accept") == 0
    assert corr.audit("reject", second=True) == 0
    assert corr.publish() == 0
    corr.assert_held_back("the second audit decided reject")
    assert len(corr.trail()["audits_run"]) == 2


def test_a_first_audit_that_failed_validation_twice_holds_the_card_back(corr: Corr):
    tier_2(corr)
    assert corr.run("correct-audit-plan") == 0
    corr.write_audit("not: an audit record\n")
    assert corr.run("correct-record-audit") == 1
    corr.write_audit("still: not one\n")
    assert corr.run("correct-record-audit") == 1
    assert corr.publish() == 0
    corr.assert_held_back(pipeline.FIRST_INVALID_TWICE)
    assert f"{DATE}-{SLUG}-correction-published-invalid.yaml" in corr.audit_names()


def test_publish_refuses_while_a_tier_2_audit_is_missing(corr: Corr, capsys):
    tier_2(corr)
    assert corr.publish() == 1
    assert "no first audit" in capsys.readouterr().err
    assert corr.audit("accept") == 0
    assert corr.publish() == 1
    assert "tier 2 needs a second audit" in capsys.readouterr().err
    assert corr.card.read_bytes() == corr.card_bytes and not corr.audits.exists() and not corr.log.exists()
    assert not (corr.dir / "correction-report.md").exists()


def test_publish_refuses_when_the_card_changed_since_the_round_was_applied(corr: Corr, capsys):
    corr.accepted()
    corr.card.write_text(corr.text().replace("A second fictional link text.", "A changed link text."), encoding="utf-8")
    before = corr.card.read_bytes()
    assert corr.publish() == 1
    assert "the card changed since the round was applied" in capsys.readouterr().err
    assert corr.card.read_bytes() == before and not corr.log.exists() and not corr.audits.exists()
    assert corr.run("correct-audit-plan") == 1


# --- publication ------------------------------------------------------------------------------------------------


def test_tier_2_publishes_after_two_accepts_with_last_checked_and_the_audit_record_copies(corr: Corr):
    tier_2(corr)
    assert corr.audit("accept") == 0
    assert corr.audit("accept", second=True) == 0
    ctx = (corr.dir / "audit-context" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert "the correction of the published card" in ctx and "Reworded Fictional Group" in ctx
    assert "PROBLEM about" not in ctx and "REQUEST-MARKER" not in ctx and "STALE-STUDY-NOTE" not in ctx
    assert corr.publish() == 0
    assert "Outcome: published" in corr.report() and "Tier: 2" in corr.report()
    expected = yaml.safe_load(corr.card_bytes.decode())  # only the named items differ from the published card
    expected["studies"][2].update(finding=FINDING_NEW, group=GROUP_NEW)
    expected["links"][0]["text"] = LINK_NEW
    expected["last_checked"] = {"date": yaml.safe_load(f"d: {DATE}")["d"], "by": "ai_audit"}
    assert yaml.safe_load(corr.text()) == expected
    assert STUDY_NOTE in corr.text() and LINK_NOTE in corr.text()
    data = yaml.safe_load(corr.text())
    assert data["last_checked"]["by"] == "ai_audit" and str(data["last_checked"]["date"]) == DATE
    assert data["studies"][2]["finding"] == FINDING_NEW and data["links"][0]["text"] == LINK_NEW
    (entry,) = corr.changelog()
    assert entry["tier"] == 2 and entry["decided_by"] == "ai_audit"
    assert (
        entry["reason"] == "The cited controlled study supports the proposed level."
    )  # the first audit's reasons_summary
    assert entry["change"].startswith(f"Correction: the finding and group of {CTX} reworded")
    assert entry["sources"] == [CTX, STUDY]
    stem = f"{DATE}-{SLUG}-correction-published"
    assert corr.audit_names() == [f"{stem}-second.yaml", f"{stem}-trail.yaml", f"{stem}.yaml"]
    assert (corr.audits / f"{stem}.yaml").read_bytes() == (corr.dir / "audit" / f"{SLUG}.yaml").read_bytes()
    trail = corr.trail()
    assert trail["outcome"] == "published" and trail["tier"]["tier"] == 2
    assert any("classed decisive" in why for why in trail["tier"]["why"])
    assert trail["audits_run"] == [f"{stem}.yaml", f"{stem}-second.yaml"]


def test_a_dry_run_writes_only_the_report(corr: Corr):
    corr.accepted()
    assert corr.publish("--dry-run") == 0
    assert (corr.dir / "correction-report.md").is_file() and "Dry run" in corr.output()
    assert corr.card.read_bytes() == corr.card_bytes and not corr.log.exists() and not corr.audits.exists()


def test_a_later_correction_of_the_same_card_and_date_uses_2_and_nothing_is_overwritten(corr: Corr):
    corr.accepted()
    stem = f"{DATE}-{SLUG}-correction-published"
    corr.audits.mkdir()
    (corr.audits / f"{stem}-trail.yaml").write_text("keep: me\n", encoding="utf-8")  # an earlier correction's trail
    assert corr.publish() == 0
    assert (corr.audits / f"{stem}-trail.yaml").read_text(encoding="utf-8") == "keep: me\n"
    assert corr.trail(f"{stem}-2")["outcome"] == "published"


def test_publish_refuses_to_overwrite_an_audit_record_and_writes_nothing(corr: Corr, capsys):
    tier_2(corr)
    assert corr.audit("accept") == 0 and corr.audit("accept", second=True) == 0
    corr.audits.mkdir()
    taken = corr.audits / f"{DATE}-{SLUG}-correction-published-second.yaml"
    taken.write_text("keep: me\n", encoding="utf-8")
    assert corr.publish() == 1
    assert "never overwritten" in capsys.readouterr().err
    assert taken.read_text(encoding="utf-8") == "keep: me\n" and corr.audit_names() == [taken.name]
    assert corr.card.read_bytes() == corr.card_bytes and not corr.log.exists()


# --- remove_comment ---------------------------------------------------------------------------------------------


CARD_WITH_COMMENTS = """slug: x
items:
  # a note on the list
  - id: a
    # NOTE-A inside the first item
    value: 1
  # between the items
  - id: b
    value: 2  # a trailing note
# a top-level note
other: 3
"""


def test_remove_comment_removes_exactly_the_line_and_leaves_the_parsed_data_equal():
    ops = parse_ops(
        {"card": "x", "paper": None, "operations": [{"op": "remove_comment", "text": "NOTE-A inside the first item"}]}
    )
    new = apply_operations(CARD_WITH_COMMENTS, ops, validate=False)
    assert new == CARD_WITH_COMMENTS.replace("    # NOTE-A inside the first item\n", "")
    assert yaml.safe_load(new) == yaml.safe_load(CARD_WITH_COMMENTS)


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("no such comment", "no whole-line comment reads"),
        ("a trailing note", "not a whole-line comment"),
        ("id: a", "no whole-line comment reads"),  # a content line, not a comment
    ],
)
def test_remove_comment_refuses_zero_matches_a_trailing_comment_and_a_content_line(text, fragment):
    ops = parse_ops({"card": "x", "paper": None, "operations": [{"op": "remove_comment", "text": text}]})
    with pytest.raises(OperationError, match=fragment):
        apply_operations(CARD_WITH_COMMENTS, ops, validate=False)


def test_remove_comment_refuses_two_matching_lines():
    text = CARD_WITH_COMMENTS.replace("# between the items", "# a note on the list")
    ops = parse_ops(
        {"card": "x", "paper": None, "operations": [{"op": "remove_comment", "text": "a note on the list"}]}
    )
    with pytest.raises(OperationError, match="2 comment lines read"):
        apply_operations(text, ops, validate=False)


def test_a_comment_in_a_block_scalar_is_content_and_is_not_removed():
    text = "slug: x\nnote: |\n  # kept: part of the text\n  more\n"
    ops = parse_ops(
        {"card": "x", "paper": None, "operations": [{"op": "remove_comment", "text": "kept: part of the text"}]}
    )
    with pytest.raises(OperationError, match="does not match the intended change"):
        apply_operations(text, ops, validate=False)


def test_remove_comment_is_tier_1_and_needs_a_nonempty_text():
    from me_atlas.operations import tiers

    ops = parse_ops({"card": "x", "paper": None, "operations": [{"op": "remove_comment", "text": "t"}]})
    assert tiers(ops) == [1]
    with pytest.raises(OperationError):
        parse_ops({"card": "x", "paper": None, "operations": [{"op": "remove_comment", "text": "  "}]})
    with pytest.raises(OperationError):
        parse_ops({"card": "x", "paper": None, "operations": [{"op": "remove_comment"}]})


def test_comment_target_names_the_study_or_link_whose_block_holds_the_comment(corr: Corr):
    assert comment_target(corr.text(), STUDY_NOTE) == f"studies[{STUDY}]"
    assert comment_target(corr.text(), LINK_NOTE) == "links[0]"
    assert comment_target(corr.text(), "--- contradicts ---") == f"studies[{OTHER_STUDY}]"  # before the item: its own
    with pytest.raises(OperationError, match="lies in no study's block"):
        comment_target(corr.text(), "a comment between two paragraphs")
    with pytest.raises(OperationError, match="lies in no study's block"):
        comment_target(corr.text(), "a comment inside a badge")


def test_a_published_correction_removes_a_comment_named_through_its_study_or_link(corr: Corr, capsys):
    corr.planned(
        [
            finding([f"studies[{STUDY}]", f"studies[{STUDY}].finding"], "wording", target=f"studies[{STUDY}].finding"),
            LINK_FINDING,
        ]
    )
    ops = [
        {"op": "remove_comment", "text": STUDY_NOTE},
        {"op": "remove_comment", "text": LINK_NOTE},
        {"op": "remove_comment", "text": "a comment inside a badge"},
    ]
    assert corr.apply(ops[:2] + ops[2:]) == 1  # the third lies in no study or link block
    assert "lies in no study's block" in capsys.readouterr().err
    assert written(corr, "checks", "applied") == []
    assert corr.apply(ops[:2]) == 0
    applied = (corr.dir / "applied" / f"{SLUG}-r1" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    assert applied == corr.text().replace(f"    # {STUDY_NOTE}\n", "").replace(f"  # {LINK_NOTE}\n", "")
    corr.review()
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert corr.publish() == 0  # comments only: wording classes, no structural difference: tier 1
    assert corr.text() == applied
    (entry,) = corr.changelog()
    assert entry["change"] == "Correction: 2 comment line(s) removed" and entry["tier"] == 1 and entry["sources"] == []


def test_a_comment_removal_is_refused_when_no_finding_names_its_block(corr: Corr, capsys):
    corr.planned([LINK_FINDING])  # links[0] only
    assert corr.apply([{"op": "remove_comment", "text": STUDY_NOTE}]) == 1
    assert f"changes studies[{STUDY}], which no finding" in capsys.readouterr().err
    assert corr.apply([{"op": "remove_comment", "text": "nothing like it"}]) == 1
    assert "no whole-line comment reads" in capsys.readouterr().err
    assert written(corr, "checks", "applied") == []


def test_apply_refuses_two_matching_comment_lines(corr: Corr, capsys):
    text = corr.text().replace("    role: contradicts\n", f"    role: contradicts\n    # {STUDY_NOTE}\n", 1)
    corr.card.write_text(text, encoding="utf-8", newline="\n")
    corr.card_bytes = corr.card.read_bytes()
    corr.planned(
        [finding([f"studies[{STUDY}]", f"studies[{STUDY}].finding"], "wording", target=f"studies[{STUDY}].finding")]
    )
    assert corr.apply([{"op": "remove_comment", "text": STUDY_NOTE}]) == 1
    assert "2 comment lines read" in capsys.readouterr().err


# --- the other paths refuse remove_comment (and the paths of this one are unchanged) -----------------------------


REMOVE = {"op": "remove_comment", "text": "a comment between two paragraphs"}


def test_the_weekly_apply_refuses_remove_comment(tmp_path: Path, capsys):
    env = Env(tmp_path)
    env.prepare()
    assert env.classify() == 0
    ops = env.run / "ops" / f"{SLUG}-90000101-r1.json"
    ops.parent.mkdir(parents=True, exist_ok=True)
    ops.write_text(json.dumps({"card": SLUG, "paper": "pmid:90000101", "operations": [REMOVE]}), encoding="utf-8")
    assert env.cli("apply", SLUG, str(ops), "--round", "1") == 1
    assert "only the correction of a published card" in "\n".join(env.out)


def test_a_correction_round_of_a_draft_refuses_remove_comment():
    ops = parse_ops({"card": SLUG, "paper": None, "operations": [REMOVE]})
    found = pipeline.correction_ops_problems(ops, 2)
    assert len(found) == 1 and "only the correction of a published card" in found[0]
    assert pipeline.correction_ops_problems(ops, 2, published=True) == []


def test_the_draft_valve_refuses_remove_comment(corr: Corr):
    ops = parse_ops({"card": SLUG, "paper": None, "operations": [REMOVE]})
    new, problems = pipeline.apply_valve(corr.text(), ops, {"level_reason[0]"})
    assert new is None and any("remove_comment" in p for p in problems)


def test_a_link_round_refuses_remove_comment(corr: Corr):
    ops = parse_ops({"card": SLUG, "paper": None, "operations": [REMOVE]})
    new, problems = link_round.apply_link_valve(corr.text(), ops, {TARGET})
    assert new is None and any("holds set_link_text only" in p for p in problems)


def test_a_correction_round_of_a_draft_still_refuses_set_link_text_and_the_published_path_allows_it():
    ops = parse_ops({"card": SLUG, "paper": None, "operations": [OPS_TIER1[1]]})
    assert any("set_link_text" in p for p in pipeline.correction_ops_problems(ops, 2))
    assert pipeline.correction_ops_problems(ops, 2, published=True) == []


# --- the group rule: wording only on a study whose role is context --------------------------------------------------


def test_a_group_change_on_a_context_study_with_wording_classes_is_tier_1(corr: Corr):
    ops = [{"op": "update_study", "id": CTX, "set": {"group": GROUP_NEW}}]
    corr.accepted([finding([f"studies[{CTX}].group"])], ops)
    assert corr.run("correct-audit-plan") == 1  # tier 1: no audit
    assert corr.publish() == 0
    assert "Tier: 1" in corr.report() and yaml.safe_load(corr.text())["studies"][2]["group"] == GROUP_NEW
    assert corr.trail()["review"]["findings"][0]["target"] == f"studies[{CTX}].group"


def test_the_same_group_change_on_a_supports_study_is_tier_2_whatever_the_classes_say(corr: Corr, capsys):
    ops = [{"op": "update_study", "id": STUDY, "set": {"group": GROUP_NEW}}]
    # the review cannot class it wording (refused at record time), so a decisive class carries it ...
    corr.planned([finding([f"studies[{STUDY}].group"], "decisive")])
    assert corr.apply(ops) == 0
    corr.review()
    assert corr.run("correct-record-review", "--round", "1") == 0
    assert corr.publish() == 1 and "tier 2 needs two audits" in capsys.readouterr().err
    # ... and the code's own comparison says tier 2 even with a wording class on the finding
    review, _ = card_correction.load_pre_review(
        pipeline.Config(corr.dir, corr.env.cards, corr.env.drafts, corr.env.cache, pipeline.DEFAULT_SPEC), SLUG
    )
    review.findings[0].klass = "wording"
    applied = (corr.dir / "applied" / f"{SLUG}-r1" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    decision = card_correction.decide_tier(
        corr.text(),
        applied,
        parse_ops({"card": SLUG, "paper": None, "operations": ops}),
        review,
        pipeline._load_card(corr.card),
    )
    assert decision.tier == 2 and decision.reasons == [f"studies[{STUDY}].group differs"]


def test_a_wording_finding_on_the_group_of_a_study_with_a_rung_role_is_refused_at_record_time(corr: Corr, capsys):
    corr.request()
    corr.pre([finding([f"studies[{STUDY}].group"])])
    assert corr.run("correct-record-review", "--pre") == 1
    err = capsys.readouterr().err
    assert "that study's role is supports" in err and "is `decisive`" in err
    corr.pre([finding([f"studies[{OTHER_STUDY}].group"])])  # a contradicts study too
    assert corr.run("correct-record-review", "--pre") == 1
    assert "role is contradicts" in capsys.readouterr().err
    corr.pre([finding([f"studies[{STUDY}].group"], "decisive")])
    assert corr.run("correct-record-review", "--pre") == 0


def test_the_draft_path_still_refuses_a_wording_finding_on_a_group(tmp_path: Path):
    """On the draft correction round and its valve the shared models accept what they did before: not `group`."""
    from pydantic import ValidationError

    wording = {"operation": None, "severity": "must_fix", "problem": "P.", "class": "wording"}
    target = f"studies[{STUDY}].group"
    with pytest.raises(ValidationError, match="wording finding needs a target naming a free-text item"):
        pipeline.Finding.model_validate(wording | {"target": target, "targets": [target]})
    assert pipeline.FREE_TEXT_TARGET.match(f"studies[{STUDY}].finding")
    assert pipeline.FREE_TEXT_TARGET.match(target) is None
    # a draft correction-round review is refused at record time (nothing in the pipeline path swaps the target)
    env = Env(tmp_path)
    review = {
        "card": SLUG,
        "paper": None,
        "verdict": "reject",
        "findings": [wording | {"target": target, "targets": [target]}],
    }
    path = env.run / "review" / f"{SLUG}-card-C1-pre.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(pipeline.PipelineError, match="malformed"):
        pipeline.record_review(
            pipeline.Config(env.run, env.cards, env.drafts, env.cache, pipeline.DEFAULT_SPEC),
            SLUG,
            None,
            "C1-pre",
            card_review=True,
            pre=True,
        )
