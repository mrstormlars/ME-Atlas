"""Tests for the changes of the 2026-11-15/16 rulings: author facts and check C11, targets that a correction may
touch, and more revisions while the decisive findings fall.

Fictional records, cards and agent output in temporary folders. No network, no AI, no git.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_citations import add_record, make_study, write_card
from test_correction import Corr, ops_data
from test_pipeline import SLUG, Env
from test_pre_review import FLAGS, apply_refused, attempt
from test_publish_card import Pub

from me_atlas import citations, pipeline, pubmed
from me_atlas.citations import ERROR, WARNING, AuthorList, author_facts, shared_authors

P1, P2, P3 = "90000011", "90000012", "90000013"
SHARED = [("Smith", "J"), ("Jones", "K"), ("Lee", "A"), ("Wong", "B")]
A_AUTHORS = [*SHARED, ("Alpha", "X")]
B_AUTHORS = [*SHARED, ("Beta", "Y")]
C_AUTHORS = [("Gamma", "G"), ("Delta", "D")]


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    add_record(root, P1, authors=tuple(A_AUTHORS))
    add_record(root, P2, authors=tuple(B_AUTHORS))
    add_record(root, P3, authors=tuple(C_AUTHORS))
    return root


def c11(tmp_path: Path, cache: Path, *, reason: str | None = None, groups=(None, None), pmids=(P1, P2), level=WARNING):
    studies = [make_study(p, group=g) for p, g in zip(pmids, groups, strict=True)]
    path = write_card(tmp_path / "drafts", studies)
    if reason is not None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["level_reason"] = [{"text": reason, "sources": [s["id"] for s in studies]}]
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return [i for i in citations.check_paths([path], cache, level)[1] if i.code == "C11"]


# --- A1: affiliations in the record -------------------------------------------------------------------------------


def test_a_record_parses_the_affiliation_of_each_author_and_an_older_record_has_none():
    xml = (
        "<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>90000001</PMID><Article>"
        "<Journal><JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue><Title>J</Title></Journal>"
        "<ArticleTitle>T</ArticleTitle><AuthorList>"
        "<Author><LastName>Smith</LastName><Initials>J</Initials>"
        "<AffiliationInfo><Affiliation>Dept A, Fictional University.</Affiliation></AffiliationInfo>"
        "<AffiliationInfo><Affiliation>Institute B.</Affiliation></AffiliationInfo></Author>"
        "<Author><LastName>Jones</LastName><Initials>K</Initials></Author>"
        "</AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"
    )
    record = pubmed.parse_xml(xml)
    assert record.authors == ["Smith J", "Jones K"]
    assert record.affiliations == [["Dept A, Fictional University.", "Institute B."], []]
    assert pubmed.parse_xml(xml.replace("AffiliationInfo", "Other")).affiliations == [[], []]


# --- A2: author facts ---------------------------------------------------------------------------------------------


def test_two_lists_share_authors_by_an_exact_and_a_loose_match():
    a = AuthorList(("Smith J", "Jones K", "Müller A", "Park C"))
    b = AuthorList(("Smith J", "Jones KL", "Muller A", "Lee D"))
    exact, loose, names = shared_authors(a, b)
    assert exact == 2  # Smith J, and Müller A = Muller A once the marks are removed
    assert loose == 3  # and Jones K = Jones KL by last name and first initial
    assert names == ["Smith J", "Jones K (as Jones KL)", "Müller A"]
    assert shared_authors(a, AuthorList(("Lee D",))) == (0, 0, [])


def test_only_pairs_that_share_an_author_are_listed_and_a_collective_author_counts():
    lists = {
        "pmid:1": AuthorList(("Smith J", "Big Consortium")),
        "pmid:2": AuthorList(("Smith J",)),
        "pmid:3": AuthorList(("Big Consortium", "Other P")),
        "pmid:4": AuthorList(("Nobody Z",)),
    }
    pairs = {(p.first, p.second): (p.exact, p.loose) for p in author_facts(lists)}
    assert pairs == {("pmid:1", "pmid:2"): (1, 1), ("pmid:1", "pmid:3"): (1, 1)}


def test_the_facts_section_names_first_and_last_author_shared_pairs_and_studies_without_authors(tmp_path, cache):
    add_record(cache, "90000014")  # a record with no author list
    path = write_card(tmp_path / "drafts", [make_study(P1), make_study(P2), make_study(P3), make_study("90000014")])
    section = citations.author_facts_section(yaml_card(path), citations.CacheReader(cache))
    assert section.startswith("## Author facts (computed by code from the cached records)")
    assert f"pmid:{P1}: 5 author(s); first author Smith J; last author Alpha X" in section
    assert f"pmid:{P1} and pmid:{P2}: 4 exact, 4 loose: Smith J, Jones K, Lee A, Wong B" in section
    assert f"pmid:{P3} and" not in section.split("Every other pair")[0].split("loose:")[1]
    assert "Every other pair of cited studies shares no author by name in the records." in section
    assert "pmid:90000014" in section.split("No cached author list")[1]


def yaml_card(path: Path):
    from me_atlas.cards import load_card

    return load_card(path)


# --- A4: C11 ------------------------------------------------------------------------------------------------------


def test_c11a_a_stated_count_outside_the_records_counts_is_reported_and_a_right_one_is_not(tmp_path, cache):
    failing = c11(tmp_path, cache, reason="The two studies share three authors.")
    assert [i.code for i in failing] == ["C11"] and "share three authors" in failing[0].message
    assert c11(tmp_path, cache, reason="The two studies share 4 authors.") == []
    assert c11(tmp_path, cache, reason="They have four shared co-authors.") == []
    assert len(c11(tmp_path, cache, reason="They have 2 authors in common.")) == 1
    # a bound, an estimate or a study the item does not cite is not checked
    assert c11(tmp_path, cache, reason="The two studies share at least three authors.") == []
    assert c11(tmp_path, cache, reason="One shares two authors with the Swedish study.") == []
    assert c11(tmp_path, cache, reason="The two studies share three authors.", pmids=(P1, P3), groups=(None, None))


def test_c11b_no_shared_authors_for_studies_that_share_some_is_reported(tmp_path, cache):
    failing = c11(tmp_path, cache, reason="The two studies have no shared authors.")
    assert len(failing) == 1 and "shares at least one author" in failing[0].message
    assert len(c11(tmp_path, cache, reason="They are independent research groups.")) == 1
    # a statement about a study the item does not cite is not checked
    for text in (
        "No authors are shared with the earlier Swedish study.",
        "They share no authors with the third report.",
        "There are no authors in common with controls.",
    ):
        assert c11(tmp_path, cache, reason=text) == [], text
        assert len(c11(tmp_path, cache, reason=text.split(" with ")[0] + ".")) == 1, text
    # no pair of the cited studies that shares an author: the statement may be true
    assert c11(tmp_path, cache, reason="The two studies have no shared authors.", pmids=(P1, P3)) == []
    # a negation, a singular rubric phrase and a statement about a group of patients are not claims
    for text in (
        "They are not independent groups.",
        "No independent group has repeated this.",
        "Two independent groups of patients were compared.",
    ):
        assert c11(tmp_path, cache, reason=text) == []


def test_c11c_a_group_naming_the_wrong_first_or_last_author_is_reported(tmp_path, cache):
    wrong = c11(tmp_path, cache, groups=("Smith J, Fictional University (first author Alpha X)", None))
    assert len(wrong) == 1 and "first author of the record is Smith J" in wrong[0].message
    assert len(c11(tmp_path, cache, groups=("Smith J, Fictional University (last author Smith J)", None))) == 1
    for group in (
        "Smith J, Fictional University (first author Smith J)",
        "Alpha X (last author Alpha X, Fictional University)",
        "Smith J (first author J. Smith)",
        "Smith J, Fictional University (affiliation from first author)",
        "Smith J (first author's department)",
        "Smith J (first author at Fictional University)",
    ):
        assert c11(tmp_path, cache, groups=(group, None)) == [], group


def test_c11d_a_name_also_on_a_record_that_does_not_list_it_is_reported(tmp_path, cache):
    wrong = c11(tmp_path, cache, groups=(f"Smith J, Fictional University (Alpha X also on {P2})", None))
    assert len(wrong) == 1 and f"'Alpha X' is also on {P2}" in wrong[0].message
    assert len(c11(tmp_path, cache, groups=(f"Smith J (Smith J and Alpha X also on {P2})", None))) == 1
    for group in (
        f"Smith J (Smith J also on {P2})",
        f"Smith J (Jones K and Wong B also on {P2} and {P1})",
        "Smith J (Alpha X also on 99999999)",  # no cached author list for that record: not checked
        f"Smith J (same group as {P2}; Smith JA also on {P2})",
    ):
        assert c11(tmp_path, cache, groups=(group, None)) == [], group


def test_c11_is_an_error_where_c10_is_and_a_warning_in_the_command_line_check(tmp_path, cache, capsys):
    reason = "The two studies share three authors."
    assert [i.level for i in c11(tmp_path, cache, reason=reason)] == [WARNING]
    assert [i.level for i in c11(tmp_path, cache, reason=reason, level=ERROR)] == [ERROR]
    path = tmp_path / "drafts" / "fictional-card.yaml"
    assert citations.main(["check", str(path), "--cache-dir", str(cache)]) == 0
    assert "C11 WARNING" in capsys.readouterr().out


def test_the_c11_issue_does_not_depend_on_the_index_of_the_paragraph(tmp_path, cache):
    studies = [make_study(P1), make_study(P2)]
    path = write_card(tmp_path / "drafts", studies)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    bad = {"text": "The two studies share three authors.", "sources": [s["id"] for s in studies]}
    other = {"text": "Another fictional sentence.", "sources": [studies[0]["id"]]}
    found = []
    for paragraphs in ([bad], [other, bad]):
        data["level_reason"] = paragraphs
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        found.append([(i.study, i.message) for i in citations.check_paths([path], cache)[1] if i.code == "C11"])
    assert found[0] == found[1] and len(found[0]) == 1


# --- B: a correction touches only what a finding names -------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def corr(env: Env, tmp_path: Path) -> Corr:
    c = Corr(Pub(env, tmp_path), tmp_path)
    c.hold_back()
    return c


def record(c: Corr, *argv: str) -> int:
    return c.main("record-review", SLUG, *argv, "--run-dir", str(c.dir))


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def must_fix(**over) -> dict:
    return {"operation": None, "severity": "must_fix", "class": "decisive", "problem": "A problem."} | over


def test_b1_a_must_fix_of_the_correction_path_without_targets_is_refused(corr: Corr, capsys):
    assert corr.plan() == 0 and corr.apply() == 0
    cr = corr.dir / "review" / f"{SLUG}-rC1.json"
    write(cr, {"card": SLUG, "verdict": "reject", "findings": [must_fix(operation=0)]})
    assert record(corr, "--round", "C1") == 1
    assert "must_fix without `targets`" in capsys.readouterr().err
    write(cr, {"card": SLUG, "verdict": "reject", "findings": [must_fix(operation=0, targets=["core_claim"])]})
    assert record(corr, "--round", "C1") == 0
    # the review of the whole card and the one before drafting are bound the same way
    card = corr.dir / "review" / f"{SLUG}-card-C1.json"
    write(card, {"card": SLUG, "paper": None, "verdict": "reject", "findings": [must_fix()]})
    assert record(corr, "--card-review", "--round", "C1") == 1
    pre = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    held = json.loads(pre.read_text(encoding="utf-8")) | {"verdict": "reject", "findings": [must_fix()]}
    write(pre, held)
    assert record(corr, "--card-review", "--pre", "--round", "C1") == 1
    # an advisory finding needs none, and a target the finding names must be one of its targets
    write(card, {"card": SLUG, "paper": None, "verdict": "accept", "findings": [must_fix() | {"severity": "advisory"}]})
    assert record(corr, "--card-review", "--round", "C1") == 0
    both = must_fix(targets=["level"]) | {"target": "core_claim"}
    write(card, {"card": SLUG, "paper": None, "verdict": "reject", "findings": [both]})
    assert record(corr, "--card-review", "--round", "C1") == 1
    assert "is not one of its `targets`" in capsys.readouterr().err
    write(card, {"card": SLUG, "paper": None, "verdict": "reject", "findings": [must_fix(targets=["somewhere"])]})
    assert record(corr, "--card-review", "--round", "C1") == 1


def test_b2_the_pre_review_needs_one_audit_targets_entry_for_each_objecting_part_and_no_other(corr: Corr, capsys):
    assert corr.pre_review() == 0
    pre = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    good = json.loads(pre.read_text(encoding="utf-8"))
    entries = good["audit_targets"]
    assert entries and all(e["record"].startswith("2026") for e in entries)
    args = ("--card-review", "--pre", "--round", "C1")
    write(pre, good | {"audit_targets": entries[1:]})
    assert record(corr, *args) == 1
    assert f"audit_targets has no entry for {entries[0]['record']} part {entries[0]['part']}" in capsys.readouterr().err
    write(pre, good | {"audit_targets": None})
    assert record(corr, *args) == 1
    write(pre, good | {"audit_targets": [*entries, {"record": "nothing.yaml", "part": 0, "targets": ["level"]}]})
    assert record(corr, *args) == 1
    assert "is not an objecting audit part" in capsys.readouterr().err
    write(pre, good | {"audit_targets": [*entries, entries[0]]})
    assert record(corr, *args) == 1
    assert "repeats" in capsys.readouterr().err
    write(pre, good | {"audit_targets": [{**entries[0], "targets": []}, *entries[1:]]})
    assert record(corr, *args) == 1
    write(pre, good)
    assert record(corr, *args) == 0


def test_b2_the_pre_review_context_lists_the_objecting_audit_parts_and_the_author_facts(corr: Corr):
    assert corr.pre_review() == 0
    text = (corr.dir / "card-review-context" / f"{SLUG}-C1-pre.md").read_text(encoding="utf-8")
    assert "## 6. Targets (the `--pre` review)" in text and "- decision_part:" in text and "- evidence:" in text
    assert "## 5. Author facts (computed by code from the cached records)" in text
    plain = corr.dir / "card-review-context"
    assert corr.plan() == 0
    context = (corr.dir / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert "Targets the findings name (draft numbering" in context and "- `contested_reason[1]`" in context
    assert "## 8. Author facts (computed by code from the cached records)" in context
    assert plain.is_dir()


def ops_errors(c: Corr) -> str:
    return "; ".join(json.loads((c.dir / "checks" / f"{SLUG}-rC1.json").read_text(encoding="utf-8"))["ops_errors"])


def test_b3_an_operation_on_a_part_no_finding_names_is_refused(corr: Corr):
    assert corr.pre_review(targets=["core_claim"]) == 0
    assert corr.apply() == 1  # CONTESTED_LAST changes contested_reason[1]
    assert "operations[0] changes contested_reason[1], which no finding names" in ops_errors(corr)
    assert corr.apply(ops_data({"op": "remove_paragraph", "field": "early_signals", "index": 0})) == 1
    assert "operations[0] changes early_signals[0]" in ops_errors(corr)


def test_b3_the_target_of_an_operation_is_its_paragraph_in_the_drafts_numbering():
    draft = yaml.safe_load(
        (Path(__file__).parent / "fixtures" / "pipeline" / "drafts" / f"{SLUG}.yaml").read_text(encoding="utf-8")
    )
    card = pipeline.cards.Card.model_validate(draft)
    remove = {"op": "remove_paragraph", "field": "contested.reason", "index": 0}
    ops = pipeline.parse_ops(
        ops_data(remove, remove, {"op": "update_study", "id": "pmid:90000104", "set": {"direction": "mixed"}})
    )
    targets, survivors = pipeline._correction_op_targets(card, ops)
    assert targets == ["contested_reason[0]", "contested_reason[1]", "studies[pmid:90000104]"]
    assert survivors["contested_reason"] == []  # a removal does not shift the later index of the draft
    assert pipeline._map_to_draft("contested_reason[0]", {"contested_reason": [1]}) == "contested_reason[1]"
    assert pipeline._map_to_draft("contested_reason[3]", {"contested_reason": [1]}) is None
    assert pipeline._map_to_draft("level", {"contested_reason": [1]}) == "level"


def test_b3_two_removals_are_checked_in_the_drafts_numbering(corr: Corr):
    assert corr.pre_review(targets=["contested_reason[0]"]) == 0
    twice = {"op": "remove_paragraph", "field": "contested.reason", "index": 0}
    assert corr.apply(ops_data(twice, twice)) == 1  # the second removes the draft's paragraph 1
    assert "operations[1] changes contested_reason[1]" in ops_errors(corr)
    assert corr.apply(ops_data(twice)) == 0


def test_b3_a_revised_attempt_may_touch_what_the_earlier_review_named_in_the_applied_numbering(corr: Corr):
    assert corr.pre_review(targets=["contested_reason[0]"]) == 0
    assert corr.plan() == 0
    first = {"op": "remove_paragraph", "field": "contested.reason", "index": 0}
    assert corr.apply(ops_data(first)) == 0
    # in the applied text the draft's paragraph 1 is paragraph 0
    finding = must_fix(operation=0, targets=["contested_reason[0]"])
    write(corr.dir / "review" / f"{SLUG}-rC1.json", {"card": SLUG, "verdict": "reject", "findings": [finding]})
    assert record(corr, "--round", "C1") == 0
    revised = corr.dir / "ops" / f"{SLUG}-rC1-revised.json"
    args = ("apply", SLUG, str(revised), "--round", "C1", "--revised", "--run-dir", str(corr.dir))
    write(revised, ops_data({"op": "remove_paragraph", "field": "early_signals", "index": 0}))
    assert corr.main(*args) == 1  # nothing names early_signals[0]
    assert "operations[0] changes early_signals[0]" in ops_errors_revised(corr)
    write(revised, ops_data({"op": "remove_paragraph", "field": "contested.reason", "index": 1}))
    assert corr.main(*args) == 0  # the draft's paragraph 1, named as 0 in the applied numbering


def ops_errors_revised(c: Corr) -> str:
    path = c.dir / "checks" / f"{SLUG}-rC1-revised.json"
    return "; ".join(json.loads(path.read_text(encoding="utf-8"))["ops_errors"])


def test_b3_publish_card_checks_the_targets_again(corr: Corr):
    corr.round_to_audits()
    pre = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    data = json.loads(pre.read_text(encoding="utf-8"))
    for entry in data["audit_targets"]:
        entry["targets"] = ["core_claim"]
    write(pre, data)  # the targets the correction was applied under change afterwards
    assert corr.publish() == 0
    assert not corr.card.exists()
    assert "which no finding names" in corr.report()


# --- C: more revisions while the decisive findings fall --------------------------------------------------------------


def test_c1_the_attempts_the_flags_and_the_cap_come_from_one_constant():
    assert pipeline.MAX_REVISIONS == 4
    assert pipeline.ATTEMPT_SUFFIXES == ("", "-revised", "-revised2", "-revised3", "-revised4")
    assert [pipeline.attempt_tag("C2", i) for i in range(5)][-2:] == ["C2-revised3", "C2-revised4"]
    with pytest.raises(pipeline.PipelineError):
        pipeline.attempt_tag("C1", 5)
    assert pipeline._attempt_flag("C1-revised3") == " --revised3" and pipeline._attempt_flag("C1") == ""
    assert FLAGS["-revised4"] == ["--revised4"]


def test_c2_falling_decisive_findings_open_the_next_attempt_and_equal_ones_end_the_round(corr: Corr, capsys):
    assert corr.plan() == 0
    attempt(corr, "", "reject", decisive=3)
    attempt(corr, "-revised", "reject", decisive=2)  # 3, then 2: fewer, the next attempt is open
    assert pipeline._pending_flag(pipeline_cfg(corr), SLUG, "C1") == "--revised2"
    attempt(corr, "-revised2", "reject", decisive=2)  # 2, then 2: not fewer
    assert "did not fall (2, then 2)" in apply_refused(corr, "-revised3", capsys)
    assert corr.publish() == 0
    corr.assert_held_back(
        "correction rejected in review; the decisive findings did not fall (2, then 2)", corr.pub.draft_bytes
    )
    assert pipeline.correction_round_state(pipeline_cfg(corr), SLUG) == (1, None)


def test_c2_a_different_kind_of_reject_is_open_whatever_the_count(corr: Corr):
    assert corr.plan() == 0
    attempt(corr, "", "reject", decisive=1)
    attempt(corr, "-revised", "accept", "reject", decisive=5)  # a whole-card reject: no earlier one of that kind
    assert pipeline._pending_flag(pipeline_cfg(corr), SLUG, "C1") == "--revised2"


def test_c2_the_fifth_revision_is_refused_and_the_round_ends_after_four(corr: Corr, capsys):
    assert corr.plan() == 0
    for suffix, decisive in zip(pipeline.ATTEMPT_SUFFIXES, (5, 4, 3, 2, 1), strict=True):
        attempt(corr, suffix, "reject", decisive=decisive)
    assert pipeline._pending_flag(pipeline_cfg(corr), SLUG, "C1") is None
    assert corr.publish() == 0
    corr.assert_held_back("correction rejected in review; all 4 revisions are used", corr.pub.draft_bytes)
    assert pipeline.correction_round_state(pipeline_cfg(corr), SLUG) == (1, None)
    with pytest.raises(SystemExit):
        corr.main("apply", SLUG, "x.json", "--round", "C1", "--revised5", "--run-dir", str(corr.dir))
    assert "--revised5" in capsys.readouterr().err
    assert len(list(corr.audits.glob("*-C1-correction*.yaml"))) == 5  # all five attempts are in the trail


def test_c2_the_round_stays_open_while_the_findings_fall_in_the_trails(corr: Corr):
    assert corr.plan() == 0
    attempt(corr, "", "reject", decisive=3)
    attempt(corr, "-revised", "reject", decisive=2)
    assert corr.publish() == 0
    corr.assert_held_back(
        "correction rejected in review; the revised attempt is pending (round C1 is not used yet)",
        corr.pub.draft_bytes,
    )
    assert pipeline.correction_round_state(pipeline_cfg(corr), SLUG) == (0, 1)


def pipeline_cfg(c: Corr) -> pipeline.Config:
    return pipeline.Config(c.dir, c.env.cards, c.env.drafts, c.env.cache, pipeline.DEFAULT_SPEC, audits_dir=c.audits)


def test_c2_wording_findings_do_not_count_as_decisive():
    wording = {"severity": "must_fix", "class": "wording"}
    decisive = {"severity": "must_fix", "class": "decisive"}
    unclassified = {"severity": "must_fix"}
    advisory = {"severity": "advisory", "class": "decisive"}
    assert pipeline._decisive_count([wording, decisive, unclassified, advisory]) == 2
    assert pipeline._revision_state([("correction review", 3), ("correction review", 2)]) == (True, None)
    assert pipeline._revision_state([("correction review", 2), ("correction review", 2)])[0] is False
    assert pipeline._revision_state([("correction review", 2), ("whole-card review", 9)]) == (True, None)
    assert pipeline._revision_state([("correction review", 2), None]) == (False, None)


# --- C4: the reopened rounds -------------------------------------------------------------------------------------


def test_c4_one_new_round_for_each_of_the_seven_and_a_third_for_oxidative_nitrosative_stress():
    seven = [
        "mast-cell-activation",
        "brain-and-brainstem-mri-changes",
        "orthostatic-intolerance-cerebral-blood-flow",
        "hpa-axis-cortisol",
    ]
    assert all(pipeline.max_correction_rounds(slug) == 2 for slug in seven)
    assert (
        pipeline.max_correction_rounds("impaired-energy-production-after-exertion") == 5
    )  # DECISIONS 2026-11-16 (check retries; rubric clarifications)
    assert (
        pipeline.max_correction_rounds("herpesvirus-reactivation") == 3
    )  # DECISIONS 2026-11-16 (rubric clarifications)
    assert pipeline.max_correction_rounds("oxidative-nitrosative-stress") == 3
    assert pipeline.max_correction_rounds("small-fibre-neuropathy") == 2
    assert pipeline.max_correction_rounds("a-card-that-was-never-corrected") == 1


# --- rounds run before the falling-decisive rule stay as they were ----------------------------------------------------


def test_a_round_closed_under_the_old_rule_stays_used_and_the_same_trails_of_a_new_round_stay_open(corr: Corr):
    from test_pre_review import state, trail

    def reject(n: int) -> dict:
        return {
            "pre_card_review": {"verdict": "accept", "findings": []},
            "review": {
                "verdict": "reject",
                "findings": [{"severity": "must_fix", "class": "decisive", "problem": f"P{i}"} for i in range(n)],
            },
        }

    files = {"C1-correction": trail(**reject(2)), "C1-correction-revised": trail(**reject(1))}
    assert state(corr, **files) == (1, None)  # the revision of that kind was used: the round is closed
    assert pipeline.correction_round_state(pipeline_cfg(corr), SLUG)[0] == 1  # so the next round is C2
    marked = {k: v | {"revision_rule": pipeline.REVISION_RULE} for k, v in files.items()}
    assert state(corr, **marked) == (0, 1)  # 2 decisive, then 1: the next revision is open
    marked["C1-correction-revised"] = marked["C1-correction-revised"] | reject(2)
    assert state(corr, **marked) == (1, None)  # not fewer: closed


def test_every_trail_written_by_the_code_carries_the_revision_rule(corr: Corr):
    corr.round_to_audits()
    assert corr.publish() == 0
    assert corr.trail()["revision_rule"] == pipeline.REVISION_RULE


def test_a_pre_review_that_record_review_would_refuse_does_not_count(corr: Corr, capsys):
    assert corr.pre_review() == 0
    pre = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    data = json.loads(pre.read_text(encoding="utf-8"))
    write(pre, data | {"audit_targets": data["audit_targets"][1:]})  # an entry missing; recorded by hand
    out = corr.dir / "correction-context"
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir)) == 1
    assert "no valid whole-card review of the unchanged draft" in capsys.readouterr().err
    assert not out.exists()
    write(pre, data)
    assert corr.main("correction-plan", SLUG, "--out", str(corr.dir)) == 0
    text = (out / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert "Targets the findings name (draft numbering" in text  # B4: the allowed targets are written


def test_a_target_that_does_not_exist_on_the_card_is_refused(corr: Corr, capsys):
    assert corr.pre_review() == 0
    pre = corr.dir / "review" / f"{SLUG}-card-C1-pre.json"
    good = json.loads(pre.read_text(encoding="utf-8"))
    args = ("--card-review", "--pre", "--round", "C1")

    def with_targets(*targets: str) -> dict:
        entries = [e | {"targets": list(targets)} for e in good["audit_targets"]]
        return good | {"audit_targets": entries}

    write(pre, with_targets("links[3]"))  # the draft has no links
    assert record(corr, *args) == 1
    assert "target links[3] does not exist in the draft: links has 0 item(s)" in capsys.readouterr().err
    write(pre, with_targets("contested_reason[2]"))
    assert record(corr, *args) == 1
    assert "contested_reason has 2 item(s)" in capsys.readouterr().err
    write(pre, with_targets("studies[pmid:12345]"))
    assert record(corr, *args) == 1
    assert "study pmid:12345 is not on the card" in capsys.readouterr().err
    finding = must_fix(targets=["links[0]"])  # a finding names a missing item too
    write(pre, good | {"verdict": "reject", "findings": [finding]})
    assert record(corr, *args) == 1
    write(pre, with_targets("contested_reason[1]", "studies[pmid:90000100].finding", "level", "contested", "layer"))
    assert record(corr, *args) == 0  # what exists, and the always-present parts, pass
    assert pipeline.pre_targets(pipeline._load_card_review(pipeline_cfg(corr), SLUG, "C1-pre")) >= {"level"}


def test_a_correction_review_is_checked_against_the_applied_text_of_its_attempt(corr: Corr, capsys):
    assert corr.plan() == 0
    remove = {"op": "remove_paragraph", "field": "contested.reason", "index": 0}
    assert corr.apply(ops_data(remove)) == 0  # one contested paragraph is left
    cr = corr.dir / "review" / f"{SLUG}-rC1.json"
    write(cr, {"card": SLUG, "verdict": "reject", "findings": [must_fix(operation=0, targets=["contested_reason[1]"])]})
    assert record(corr, "--round", "C1") == 1
    assert "target contested_reason[1] does not exist in the applied text of C1" in capsys.readouterr().err
    write(cr, {"card": SLUG, "verdict": "reject", "findings": [must_fix(operation=0, targets=["contested_reason[0]"])]})
    assert record(corr, "--round", "C1") == 0
