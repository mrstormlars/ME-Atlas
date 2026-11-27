"""Tests for the upgrade variant of the correction of a published card (a request from the full-text scan).

Fictional card, papers and agent output as in test_card_correction; the scan result is written by the tests in the
format ``me_atlas.fulltext_scan`` validates. No network, no AI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from test_card_correction import CTX, OTHER_STUDY, STUDY, Corr, finding
from test_citations import add_record
from test_pipeline import SLUG, Env, FullTextResult

from me_atlas import card_correction, fulltext_scan, pipeline
from me_atlas.operations import parse_ops

FULL = "FULLTEXT-TAIL-MARKER"


@pytest.fixture
def corr(tmp_path: Path) -> Corr:
    return Corr(Env(tmp_path), tmp_path)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_result(corr: Corr, flagged: dict[str, str], *, card_sha: str | None = None, name: str = "scan") -> Path:
    """A valid ``scan-result.json`` flagging the studies in ``flagged`` (id to full-text status) on the card."""
    studies = {}
    for sid in (STUDY, OTHER_STUDY, CTX):
        is_flagged = sid in flagged
        verdict = (
            {"field": "role", "verdict": "differs", "quote": "q", "note": "n"}
            if is_flagged
            else {"field": "finding", "verdict": "confirmed", "quote": None, "note": None}
        )
        studies[sid] = {
            "status": flagged.get(sid, "fulltext_xml"),
            "step0": "differs",
            "carrier": sid != CTX,
            "cited_in_reason": False,
            "scanned": True,
            "invalid": None,
            "verdicts": [verdict],
            "dropped": [],
            "flagged": is_flagged,
        }
    data = {
        "run_id": "fictional-run",
        "date": "2026-11-27",
        "plan_date": "2026-11-27",
        "counts": {},
        "cards": {SLUG: {"sha256": card_sha or sha(corr.card), "studies": studies}},
        "flagged": {SLUG: sorted(flagged)} if flagged else {},
    }
    assert fulltext_scan.validate_scan_result(data) == []
    path = corr.dir.parent / name / "scan-result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def variant_request(corr: Corr, path: Path, *, items: list[dict] | None = None, digest: str | None = None) -> Path:
    return corr.request(
        items=items or [{"target": f"studies[{STUDY}].role", "problem": "FULLTEXT-REQUEST-MARKER the role differs."}],
        origin_kind="fulltext_scan",
        scan={"result": str(path), "result_sha256": digest or sha(path)},
    )


def variant(corr: Corr, flagged: dict[str, str] | None = None) -> Path:
    path = scan_result(corr, flagged or {STUDY: "fulltext_xml"})
    variant_request(corr, path)
    return path


def planned(corr: Corr, findings: list[dict]) -> None:
    assert corr.run("correct-review-plan") == 0, corr.output()
    corr.pre(findings)
    assert corr.run("correct-record-review", "--pre") == 0, corr.output()
    assert corr.run("correct-plan") == 0, corr.output()


REASON = [{"text": "The full text of the fictional study supports the controlled finding.", "sources": [STUDY]}]
RAISE = {"op": "propose", "target": "level", "value": 3, "reason": REASON}
BADGE = {"op": "propose", "target": "diagnostic_marker", "value": True, "reason": REASON}
CTX_ROLE = {"op": "update_study", "id": CTX, "set": {"role": "early_signal"}}  # a study no reason cites
LEVEL_FINDING = finding(["level"], "decisive")
BADGE_FINDING = finding(["badges.diagnostic_marker"], "decisive")
ROLE_FINDING = finding([f"studies[{STUDY}].role", f"studies[{CTX}].role"], "decisive")


# --- U-1: the two request fields come together -------------------------------------------------------------------


def test_request_fields_come_together(corr: Corr, capsys):
    path = scan_result(corr, {STUDY: "fulltext_xml"})
    corr.request(origin_kind="fulltext_scan")
    assert corr.run("correct-review-plan") == 1
    assert "give both or neither" in capsys.readouterr().err
    corr.request(scan={"result": str(path), "result_sha256": sha(path)})
    assert corr.run("correct-review-plan") == 1
    assert "give both or neither" in capsys.readouterr().err
    corr.request(origin_kind="other_kind", scan={"result": str(path), "result_sha256": sha(path)})
    assert corr.run("correct-review-plan") == 1
    assert not (corr.dir / "card-review-context").exists()


def test_a_request_with_both_fields_loads(corr: Corr):
    variant(corr)
    card = card_correction._load_card(corr.card)
    request = card_correction.load_request(config(corr), SLUG, card)
    assert request.origin_kind == "fulltext_scan" and request.scan is not None


def config(corr: Corr) -> pipeline.Config:
    return pipeline.Config(corr.dir, corr.env.cards, corr.env.drafts, corr.env.cache, audits_dir=corr.audits)


# --- U-2: the variant is active only when code verifies the scan result ------------------------------------------

COMMANDS = [
    ("correct-review-plan",),
    ("correct-record-review", "--pre"),
    ("correct-plan",),
    ("correct-apply", "--round", "1"),
    ("correct-record-review", "--round", "1"),
    ("correct-audit-plan",),
    ("correct-record-audit",),
    ("correct-publish", "--date", "2026-11-27"),
]


def break_it(corr: Corr, how: str) -> str:
    path = scan_result(corr, {STUDY: "fulltext_xml"})
    if how == "missing":
        variant_request(corr, path)
        path.unlink()
        return "scan result file exists"
    if how == "sha":
        variant_request(corr, path, digest="0" * 64)
        return "scan result sha256"
    if how == "not flagged":
        path = scan_result(corr, {})
        variant_request(corr, path)
        return "scan result flags the card"
    if how == "not valid":
        path.write_text("{not json", encoding="utf-8")
        variant_request(corr, path)
        return "scan result validates"
    variant_request(corr, path)
    corr.card.write_text(corr.text().replace("by: ai_audit", "by: founder"), encoding="utf-8", newline="\n")
    return "card unchanged since the scan"


@pytest.mark.parametrize("how", ["missing", "sha", "not flagged", "not valid", "card changed"])
@pytest.mark.parametrize("command", COMMANDS, ids=[" ".join(c) for c in COMMANDS])
def test_a_failed_check_refuses_every_command_and_names_the_check(corr: Corr, capsys, how, command):
    check = break_it(corr, how)
    before = {p for p in corr.dir.parent.rglob("*") if p.is_file()}
    assert corr.run(*command) == 1
    err = capsys.readouterr().err
    assert f"the check '{check}' failed" in err and "no fallback to the plain path" in err
    assert {p for p in corr.dir.parent.rglob("*") if p.is_file()} == before  # nothing written
    assert not corr.log.exists() and not corr.audits.exists()


def test_a_verified_request_runs_the_review_plan_and_names_the_variant(corr: Corr):
    path = variant(corr)
    assert corr.run("correct-review-plan") == 0, corr.output()
    text = (corr.dir / "card-review-context" / f"{SLUG}-pre.md").read_text(encoding="utf-8")
    assert "This request comes from the full-text scan" in text and "FULLTEXT-REQUEST-MARKER" in text
    assert f"`{STUDY}` (fulltext_xml)" in text  # the flagged study; its cached full-text path is listed beside it
    assert "never `wording`" in text
    assert path.is_file()


def test_the_plain_review_context_does_not_mention_the_scan(corr: Corr):
    corr.request()
    assert corr.run("correct-review-plan") == 0
    text = (corr.dir / "card-review-context" / f"{SLUG}-pre.md").read_text(encoding="utf-8")
    assert "full-text scan" not in text and "never `wording`" not in text


# --- U-3: the plain path is unchanged -------------------------------------------------------------------------


def test_a_request_without_the_fields_keeps_the_plain_limits(corr: Corr, capsys):
    corr.request()
    assert corr.run("correct-review-plan") == 0
    corr.pre([LEVEL_FINDING, BADGE_FINDING, ROLE_FINDING])
    assert corr.run("correct-record-review", "--pre") == 0
    assert corr.run("correct-plan") == 0
    assert corr.apply([RAISE]) == 1
    assert "a correction may only lower the level" in capsys.readouterr().err
    assert corr.apply([BADGE]) == 1
    assert "a correction may only set a badge to false" in capsys.readouterr().err
    text = (corr.dir / "correction-context" / f"{SLUG}.md").read_text(encoding="utf-8")
    assert card_correction.LIMITS in text and "full-text scan" not in text


# --- U-4 and U-5: what the variant permits and refuses ---------------------------------------------------------


def test_variant_permits_a_raised_level_and_a_badge_true_citing_a_flagged_study(corr: Corr):
    variant(corr)
    planned(corr, [LEVEL_FINDING, BADGE_FINDING])
    assert corr.apply([RAISE, BADGE]) == 0, corr.output()
    data = yaml.safe_load((corr.dir / "applied" / f"{SLUG}-r1" / f"{SLUG}.yaml").read_text(encoding="utf-8"))
    assert data["level"] == 3 and data["badges"]["diagnostic_marker"]["value"] is True


@pytest.mark.parametrize(
    "operation, fragment", [(RAISE, "proposes level 3"), (BADGE, "proposes diagnostic_marker True")]
)
def test_variant_refuses_a_proposal_whose_reason_cites_only_an_unflagged_study(corr: Corr, capsys, operation, fragment):
    variant(corr)  # flags STUDY only
    planned(corr, [LEVEL_FINDING, BADGE_FINDING])
    unflagged = operation | {"reason": [{"text": "A fictional reason.", "sources": [OTHER_STUDY]}]}
    assert corr.apply([unflagged]) == 1
    err = capsys.readouterr().err
    assert fragment in err and "cites no study that the full-text scan flagged" in err
    assert not (corr.dir / "checks").exists()


def test_variant_refuses_a_lowered_nothing_else_changes_for_other_proposals(corr: Corr, capsys):
    variant(corr)
    planned(corr, [LEVEL_FINDING])
    same = {"op": "propose", "target": "level", "value": 2, "reason": REASON}
    assert corr.apply([same]) == 1  # not higher, not lower: refused as on the plain path
    assert "may only lower the level" in capsys.readouterr().err


def test_variant_permits_update_study_role_on_a_flagged_study(corr: Corr):
    variant(corr, {CTX: "pmc_page"})
    planned(corr, [ROLE_FINDING])
    assert corr.apply([CTX_ROLE]) == 0, corr.output()


def test_variant_refuses_update_study_role_on_a_study_that_is_not_flagged(corr: Corr, capsys):
    variant(corr, {STUDY: "fulltext_xml"})
    planned(corr, [ROLE_FINDING])
    assert corr.apply([CTX_ROLE]) == 1
    err = capsys.readouterr().err
    assert f"sets role of {CTX}" in err and "only a study the full-text scan flagged" in err
    assert not (corr.dir / "checks").exists()


def test_variant_refuses_a_changed_case_definition_whose_source_is_not_fulltext(corr: Corr, capsys):
    variant(corr)
    planned(corr, [finding([f"studies[{STUDY}].case_definition"], "decisive")])
    change = {
        "op": "update_study",
        "id": STUDY,
        "set": {
            "case_definition": "Fukuda",
            "case_definition_source": "abstract",
            "case_definition_quote": "Participants met the Fukuda criteria.",
        },
    }
    assert corr.apply([change]) == 1
    assert "a changed case definition needs `fulltext`" in capsys.readouterr().err
    pdf = change | {"set": {**change["set"], "case_definition_source": "fulltext_pdf"}}
    assert corr.apply([pdf]) == 1
    assert "'fulltext_pdf'" in capsys.readouterr().err


@pytest.mark.parametrize(
    "operation",
    [
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
    ids=["add_paragraph", "add_link", "add_sentence"],
)
def test_variant_still_refuses_what_adds(corr: Corr, capsys, operation):
    variant(corr)
    planned(corr, [LEVEL_FINDING])
    assert corr.apply([operation]) == 1
    assert "the correction of a published card may hold" in capsys.readouterr().err
    assert not (corr.dir / "checks").exists()


def test_variant_refuses_add_study(corr: Corr, capsys):
    variant(corr)
    planned(corr, [LEVEL_FINDING])
    study = {
        "id": STUDY,
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
    }
    path = corr.ops([{"op": "add_study", "study": study}])
    path.write_text(json.dumps(json.loads(path.read_text(encoding="utf-8")) | {"paper": STUDY}), encoding="utf-8")
    assert corr.run("correct-apply", "--round", "1") == 1
    assert "the correction of a published card may hold" in capsys.readouterr().err


def test_variant_target_guard_still_applies(corr: Corr, capsys):
    variant(corr)
    planned(corr, [BADGE_FINDING])  # names the badge only, not the level
    assert corr.apply([RAISE]) == 1
    assert "changes level, which no finding" in capsys.readouterr().err


# --- U-6: always tier 2 -----------------------------------------------------------------------------------------


def accepted(corr: Corr, findings: list[dict], operations: list[dict]) -> None:
    planned(corr, findings)
    assert corr.apply(operations) == 0, corr.output()
    corr.review()
    assert corr.run("correct-record-review", "--round", "1") == 0, corr.output()


def test_a_variant_correction_is_tier_2_even_for_wording_only_free_text(corr: Corr):
    variant(corr)
    wording = finding(["links[0]"])  # class wording
    accepted(corr, [wording], [{"op": "set_link_text", "to": "other-fictional-card", "text": "A reworded link text."}])
    state = card_correction._State(config(corr), SLUG)
    state.settle()
    assert state.tier is not None and state.tier.tier == 2
    assert state.tier.reasons[0] == card_correction.UPGRADE_TIER_REASON
    assert corr.run("correct-audit-plan") == 0  # a tier 2 correction has audits; a tier 1 one refuses them


def test_the_same_wording_only_correction_on_the_plain_path_is_tier_1(corr: Corr, capsys):
    corr.request()
    accepted(
        corr, [finding(["links[0]"])], [{"op": "set_link_text", "to": "other-fictional-card", "text": "Reworded."}]
    )
    assert corr.run("correct-audit-plan") == 1
    assert "wording only (tier 1)" in capsys.readouterr().err


def test_decide_tier_gives_the_reason_for_the_variant(corr: Corr):
    corr.request()
    text = corr.text()
    card = card_correction._load_card(corr.card)
    ops = parse_ops(
        {
            "card": SLUG,
            "paper": None,
            "operations": [{"op": "update_study", "id": STUDY, "set": {"finding": "Reworded."}}],
        }
    )
    review = card_correction.ReviewFile.model_validate(
        {
            "card": SLUG,
            "paper": None,
            "verdict": "reject",
            "findings": [finding([f"studies[{STUDY}].finding"], "wording")],
        }
    )
    new_text = text.replace(
        "A study of n=20 patients and 20 controls found lower", "A study of n=20 patients found lower"
    )
    assert card_correction.decide_tier(text, new_text, ops, review, card).tier == 1
    tier = card_correction.decide_tier(text, new_text, ops, review, card, upgrade=True)
    assert tier.tier == 2 and tier.reasons[0] == card_correction.UPGRADE_TIER_REASON


# --- U-7: the audit context gives the full text of every study the correction changes ----------------------------


def marker_loader():
    """A loader that returns a full text carrying the study's id, so the context shows which studies got one."""

    def load(pmid: str, pmcid: str | None = None, **_kw) -> FullTextResult:
        xml = f"<article><body><p>FULLTEXT-OF-{pmid} {FULL}</p></body></article>".encode()
        return FullTextResult(xml, "Europe PMC open access, PMC9000101")

    return load


def audit_context(corr: Corr) -> str:
    cfg = config(corr)
    assert card_correction.correct_audit_plan(cfg, SLUG, marker_loader()) == card_correction.context_path(
        cfg, SLUG, False
    )
    return card_correction.context_path(cfg, SLUG, False).read_text(encoding="utf-8")


def cache_context_study(corr: Corr) -> None:
    """The PubMed record of the context study, so that the audit and drafter contexts have a record to render."""
    add_record(
        corr.env.cache, CTX.removeprefix("pmid:"), title="Fictional background study of widget signalling.", year=2019
    )


def study_block(text: str, study_id: str) -> str:
    return text.split(f"### Record: {study_id}", 1)[1].split("### ", 1)[0]


def test_the_variant_audit_context_gives_the_full_text_of_a_study_whose_role_changed(corr: Corr):
    cache_context_study(corr)
    variant(corr, {CTX: "fulltext_xml"})
    accepted(corr, [ROLE_FINDING], [CTX_ROLE])
    text = audit_context(corr)
    assert f"FULLTEXT-OF-{CTX.removeprefix('pmid:')}" in study_block(text, CTX)  # the changed study: full text, uncut
    assert "Not truncated" in study_block(text, CTX)
    assert "the request comes from the full-text scan" in text.splitlines()[0]  # the heading names the variant
    assert "Abstract only" not in study_block(text, CTX)


def test_the_plain_audit_context_gives_that_study_the_abstract_only(corr: Corr):
    cache_context_study(corr)
    corr.request()
    accepted(corr, [ROLE_FINDING], [CTX_ROLE])
    text = audit_context(corr)
    assert "Abstract only" in study_block(text, CTX) and "FULLTEXT-OF-90000105" not in text
    assert "full-text scan" not in text.splitlines()[0]


def test_upgrade_fulltext_ids_names_changed_entries_and_the_sources_of_changed_items():
    old = {
        "core_claim": {"text": "c", "sources": ["pmid:1"]},
        "level_reason": {"text": "a", "sources": ["pmid:1"]},
        "contested": None,
        "badges": {
            "diagnostic_marker": {"value": False, "reason": None},
            "explains_pem": {"value": False, "reason": None},
        },
        "subgroups": [],
        "early_signals": [{"text": "e", "sources": ["pmid:3"]}],
        "links": [{"to": "x", "text": "t", "sources": ["pmid:4"]}],
        "studies": [{"id": "pmid:1", "role": "supports"}, {"id": "pmid:2", "role": "context"}, {"id": "pmid:5"}],
    }
    new = json.loads(json.dumps(old))
    assert card_correction.upgrade_fulltext_ids(old, new) == set()
    new["studies"][1]["role"] = "supports"
    new["level_reason"]["text"] = "b"
    new["early_signals"][0]["text"] = "f"
    new["links"][0]["text"] = "u"
    assert card_correction.upgrade_fulltext_ids(old, new) == {"pmid:1", "pmid:2", "pmid:3", "pmid:4"}


def test_build_audit_context_extra_fulltext_defaults_to_the_old_behaviour():
    import inspect

    assert inspect.signature(pipeline.build_audit_context).parameters["extra_fulltext"].default == ()
    assert inspect.signature(pipeline.correction_ops_problems).parameters["upgrade"].default is False


# --- U-8: the drafter's context ---------------------------------------------------------------------------------


def test_the_variant_drafter_context_gives_the_flagged_full_text_and_the_added_limits(corr: Corr):
    cache_context_study(corr)
    variant(corr, {CTX: "fulltext_xml"})
    planned(corr, [ROLE_FINDING])
    cfg = config(corr)
    review, _why = card_correction.load_pre_review(cfg, SLUG)
    upgrade = card_correction.upgrade_of(
        cfg, SLUG, card_correction.load_request(cfg, SLUG, card_correction._load_card(corr.card))
    )
    text = card_correction.build_plan_context(cfg, SLUG, marker_loader(), review, upgrade)
    assert card_correction.UPGRADE_LIMITS in text and text.count(card_correction.UPGRADE_LIMITS) == 2
    assert f"FULLTEXT-OF-{CTX.removeprefix('pmid:')}" in study_block(text, CTX)  # flagged: full text, uncut
    assert "The scan flagged these studies" in text and f"`{CTX}`" in text


def test_the_plain_drafter_context_text_is_unchanged(corr: Corr):
    cache_context_study(corr)
    corr.request()
    planned_plain = corr
    assert planned_plain.run("correct-review-plan") == 0
    corr.pre([ROLE_FINDING])
    assert corr.run("correct-record-review", "--pre") == 0
    cfg = config(corr)
    review, _why = card_correction.load_pre_review(cfg, SLUG)
    text = card_correction.build_plan_context(cfg, SLUG, marker_loader(), review)
    assert text == card_correction.build_plan_context(cfg, SLUG, marker_loader(), review, None)
    assert card_correction.UPGRADE_LIMITS not in text and "The scan flagged" not in text
    assert "Abstract only" in study_block(text, CTX)
