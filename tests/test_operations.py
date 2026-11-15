"""Tests for the card operations. Fictional card in tests/fixtures/pipeline; no network, no LLM."""

from __future__ import annotations

import copy
import difflib
from pathlib import Path

import pytest
import yaml

from me_atlas import cards
from me_atlas.operations import (
    OperationError,
    OpsFile,
    apply_operations,
    parse_ops,
    preprint_ids,
    tier,
    tiers,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pipeline"
CARD = FIXTURES / "drafts" / "fictional-pipeline-card.yaml"
REPO_DRAFTS = Path(__file__).resolve().parents[1] / "drafts"
PAPER = "pmid:90000101"
PARA = {"text": "A fictional reason.", "sources": ["pmid:90000100"]}

NEW_STUDY = {
    "id": PAPER,
    "title": "Fictional replication of widget signalling in a larger cohort.",
    "year": 2026,
    "cohort": "me_cfs",
    "case_definition": "Fukuda",
    "case_definition_source": "abstract",
    "case_definition_quote": "Participants met the Fukuda criteria.",
    "design": "controlled",
    "n_patients": 60,
    "n_controls": 55,
    "measures_pem": False,
    "preregistered": None,
    "role": "supports",
    "direction": "lower",
    "finding": "A study of n=60 patients and 55 controls found lower widget signalling in patients.",
}


def card_text() -> str:
    return CARD.read_text(encoding="utf-8")


def ops(*operations: dict, card: str = "fictional-pipeline-card", paper: str = PAPER) -> OpsFile:
    return parse_ops({"card": card, "paper": paper, "operations": list(operations)})


def add_study() -> dict:
    return {"op": "add_study", "study": copy.deepcopy(NEW_STUDY)}


def add_par(field: str, text: str = "A new fictional paragraph.", sources: list[str] | None = None) -> dict:
    return {"op": "add_paragraph", "field": field, "text": text, "sources": sources or ["pmid:90000100"]}


def rep_par(
    field: str, index: int, text: str = "A replaced fictional paragraph.", sources: list[str] | None = None
) -> dict:
    return {
        "op": "replace_paragraph",
        "field": field,
        "index": index,
        "text": text,
        "sources": sources or ["pmid:90000100"],
    }


def validates(text: str, tmp_path: Path) -> list[cards.Issue]:
    path = tmp_path / "fictional-pipeline-card.yaml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return cards.validate_card_file(path)


def blocks(old: str, new: str) -> list[tuple[list[str], list[str]]]:
    """The changed regions between two texts, as (old lines, new lines); everything else is identical."""
    a, b = old.split("\n"), new.split("\n")
    return [
        (a[i1:i2], b[j1:j2])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes()
        if tag != "equal"
    ]


def apply_ok(tmp_path: Path, *operations: dict) -> tuple[str, str]:
    old = card_text()
    new = apply_operations(old, ops(*operations))
    assert validates(new, tmp_path) == []
    return old, new


# --- each operation applies and the result validates ------------------------


def test_add_study_appends_before_last_checked(tmp_path):
    old, new = apply_ok(tmp_path, add_study())
    [(removed, added)] = blocks(old, new)
    assert removed == []
    assert added[0] == "  - id: pmid:90000101"
    assert yaml.safe_load(new)["studies"][-1]["id"] == PAPER
    new_lines = new.split("\n")
    assert new_lines[new_lines.index("last_checked:") - 1] == added[-1]


def test_add_study_to_an_empty_studies_list(tmp_path):
    text = card_text().split("studies:")[0] + "studies: []\nlast_checked:\n  date: 2026-10-01\n  by: ai_pair\n"
    new = apply_operations(text, ops(add_study()), validate=False)
    assert yaml.safe_load(new)["studies"][0]["id"] == PAPER


def test_add_paragraph_to_list_form_keeps_comment_and_inserts_after_last_item(tmp_path):
    old, new = apply_ok(tmp_path, add_par("contested.reason"))
    [(removed, added)] = blocks(old, new)
    assert removed == []
    assert added[0] == "    - text: >-"
    assert "    # a comment between two paragraphs" in new
    assert len(yaml.safe_load(new)["contested"]["reason"]) == 3


def test_add_paragraph_to_single_form_converts_it_to_a_list_without_changing_its_words(tmp_path):
    old, new = apply_ok(tmp_path, add_par("level_reason", "A second fictional paragraph about the level."))
    data = yaml.safe_load(new)
    assert data["level_reason"][0] == yaml.safe_load(old)["level_reason"]
    assert data["level_reason"][1]["text"] == "A second fictional paragraph about the level."


def test_add_paragraph_to_null_reason_and_to_empty_list(tmp_path):
    old, new = apply_ok(
        tmp_path,
        add_par("badges.diagnostic_marker.reason", "A fictional marker reason."),
        add_par("subgroups", "A fictional subgroup."),
    )
    data = yaml.safe_load(new)
    assert data["badges"]["diagnostic_marker"]["reason"] == [
        {"text": "A fictional marker reason.", "sources": ["pmid:90000100"]}
    ]
    assert data["subgroups"] == [{"text": "A fictional subgroup.", "sources": ["pmid:90000100"]}]
    assert "# a comment inside a badge" in new


def test_add_paragraph_to_early_signals_and_badge_list_keeps_the_badge_comment(tmp_path):
    _, new = apply_ok(tmp_path, add_par("early_signals"), add_par("badges.explains_pem.reason"))
    data = yaml.safe_load(new)
    assert len(data["early_signals"]) == 2
    assert len(data["badges"]["explains_pem"]["reason"]) == 2
    assert "    # a comment inside a badge" in new


def test_replace_paragraph_in_list_and_in_single_form(tmp_path):
    old, new = apply_ok(tmp_path, rep_par("contested.reason", 1), rep_par("level_reason", 0))
    data = yaml.safe_load(new)
    assert data["contested"]["reason"][1]["text"] == "A replaced fictional paragraph."
    assert data["contested"]["reason"][0] == yaml.safe_load(old)["contested"]["reason"][0]
    assert data["level_reason"] == {"text": "A replaced fictional paragraph.", "sources": ["pmid:90000100"]}
    assert "    # a comment between two paragraphs" in new


def test_propose_level_replaces_level_and_its_reason(tmp_path):
    op = {
        "op": "propose",
        "target": "level",
        "value": 3,
        "reason": [{"text": "A fictional independent group found the same.", "sources": ["pmid:90000100"]}],
    }
    old, new = apply_ok(tmp_path, op)
    data = yaml.safe_load(new)
    assert data["level"] == 3 and len(data["level_reason"]) == 1
    assert all(removed and added for removed, added in blocks(old, new))
    assert ["level: 2"] in [r for r, _ in blocks(old, new)]


def test_propose_contested_remove_then_set(tmp_path):
    old, removed_text = apply_ok(tmp_path, {"op": "propose", "target": "contested", "value": None})
    assert yaml.safe_load(removed_text)["contested"] is None
    assert "contested: null" in removed_text

    reason = [{"text": "A fictional study contradicts it.", "sources": ["pmid:90000104"]}]
    new = apply_operations(
        removed_text, ops({"op": "propose", "target": "contested", "value": [1, 2], "reason": reason})
    )
    assert yaml.safe_load(new)["contested"] == {"rungs": [1, 2], "reason": reason}
    assert validates(new, tmp_path) == []


def test_propose_badge_true_sets_value_and_reason_and_keeps_badge_comment(tmp_path):
    reason = [{"text": "A fictional marker held in a second cohort.", "sources": ["pmid:90000100"]}]
    _, new = apply_ok(tmp_path, {"op": "propose", "target": "diagnostic_marker", "value": True, "reason": reason})
    badge = yaml.safe_load(new)["badges"]["diagnostic_marker"]
    assert badge == {"value": True, "reason": reason}
    _, new2 = apply_ok(tmp_path, {"op": "propose", "target": "explains_pem", "value": False})
    assert yaml.safe_load(new2)["badges"]["explains_pem"] == {"value": False, "reason": None}


def test_tier_of_operations():
    parsed = ops(add_study(), add_par("early_signals"), {"op": "propose", "target": "contested", "value": None})
    assert [tier(o) for o in parsed.operations] == [1, 1, 2]


# --- text not named in an operation is byte-identical ----------------------


def test_untouched_text_is_byte_identical_for_every_operation():
    old_par = [
        "    - text: A fictional study of 100 patients found no difference in widget signalling.",
        "      sources: [pmid:90000104]",
    ]
    cases = [
        (add_study(), []),
        (add_par("contested.reason"), []),
        (add_par("subgroups"), ["subgroups: []"]),
        (rep_par("contested.reason", 0), old_par),
    ]
    for op, expected_removed in cases:
        old = card_text()
        new = apply_operations(old, ops(op))
        changed = blocks(old, new)
        assert len(changed) == 1, op["op"]  # one contiguous region; every other line is identical
        assert changed[0][0] == expected_removed, op["op"]


def test_two_operations_in_a_row_see_each_others_result(tmp_path):
    _, new = apply_ok(tmp_path, add_par("level_reason"), rep_par("level_reason", 1, "Replaced the added one."))
    assert [p["text"] for p in yaml.safe_load(new)["level_reason"]][1] == "Replaced the added one."


# --- invalid operations are rejected and leave the card unchanged ----------


def reject(operations: list[dict], match: str, text: str | None = None) -> None:
    """Applying must raise OperationError mentioning ``match``; the text passed in stays as it was."""
    old = text if text is not None else card_text()
    snapshot = str(old)
    with pytest.raises(OperationError, match=match):
        apply_operations(old, ops(*operations))
    assert old == snapshot
    if text is None:
        assert card_text() == snapshot


def test_unknown_field_name_is_rejected():
    reject([add_par("level")], "field")
    reject([add_par("badges.explains_pem.value")], "field")


def test_unknown_key_in_an_operation_is_rejected():
    bad = add_par("level_reason")
    bad["confidence"] = "high"
    reject([bad], "confidence")
    study = add_study()
    study["study"]["sample"] = 5
    reject([study], "sample")


def test_unknown_operation_is_rejected():
    reject([{"op": "delete_study", "id": "pmid:1"}], "op")


def test_paragraph_index_out_of_range_is_rejected():
    reject([rep_par("level_reason", 1)], r"paragraph index 1 is out of range for level_reason \(1 paragraph;")
    reject([rep_par("contested.reason", 2)], r"paragraph index 2 is out of range for contested.reason \(2 paragraphs")
    reject([rep_par("subgroups", 0)], "out of range for subgroups")
    reject([rep_par("badges.diagnostic_marker.reason", 0)], "out of range")


def test_negative_paragraph_index_is_rejected():
    reject([rep_par("level_reason", -1)], "index")


def test_editing_contested_reason_on_a_card_with_no_contested_mark_is_rejected():
    text = apply_operations(card_text(), ops({"op": "propose", "target": "contested", "value": None}))
    reject([add_par("contested.reason")], "no 'contested'", text=text)


def test_duplicate_study_id_is_rejected():
    first = apply_operations(card_text(), ops(add_study()))
    reject([add_study()], "already on this card", text=first)
    dup = add_study()
    dup["study"]["id"] = "pmid:90000100"
    reject([dup], "add_study may only add the paper")
    same_paper = parse_ops({"card": "fictional-pipeline-card", "paper": "pmid:90000100", "operations": [dup]})
    with pytest.raises(OperationError, match="already on this card"):
        apply_operations(card_text(), same_paper)


def test_add_study_without_a_case_definition_quote_is_rejected():
    for definition in ("CCC", "ICC", "IOM2015", "Fukuda", "Holmes1988", "CDC_unspecified", "Oxford"):
        op = add_study()
        op["study"]["case_definition"] = definition
        op["study"]["case_definition_quote"] = None
        reject([op], "case_definition_quote")


def test_add_study_provenance_rules():
    op = add_study()
    op["study"]["case_definition"] = "unverified"
    reject([op], "unverified")  # still has a source and a quote
    op["study"]["case_definition_source"] = None
    op["study"]["case_definition_quote"] = None
    op["study"]["role"] = "context"
    op["study"]["direction"] = "not_applicable"
    assert ops(op).operations  # a properly unverified study is accepted
    op = add_study()
    op["study"]["case_definition_source"] = None
    reject([op], "case_definition_source")


def test_malformed_propose_is_rejected():
    reject([{"op": "propose", "target": "level", "value": 6, "reason": [PARA]}], "value")
    reject([{"op": "propose", "target": "level", "value": 3}], "reason")
    reject([{"op": "propose", "target": "level", "value": True, "reason": [PARA]}], "value")
    reject([{"op": "propose", "target": "contested", "value": []}], "rungs")
    reject([{"op": "propose", "target": "explains_pem", "value": "yes"}], "true or false")
    reject([{"op": "propose", "target": "explains_pem", "value": True}], "reason")
    reject([{"op": "propose", "target": "mood", "value": True}], "target")


def test_paragraph_with_no_sources_is_rejected():
    op = add_par("level_reason")
    op["sources"] = []
    reject([op], "sources")


def test_a_card_that_would_not_validate_afterwards_is_refused_with_the_rule():
    # level 5 without an intervention-controlled study breaks V6
    op = {
        "op": "propose",
        "target": "level",
        "value": 5,
        "reason": [{"text": "A fictional claim.", "sources": ["pmid:90000100"]}],
    }
    reject([op], r"\[V6\]")
    # a source that is not on the card breaks V3
    reject([add_par("early_signals", sources=["pmid:99999999"])], r"\[V3\]")


def test_flow_style_field_is_refused_rather_than_mangled():
    text = (
        card_text()
        .replace(
            "    value: false\n    reason: null\n  explains_pem:",
            "    value: false\n    reason: null\n  explains_pem:",
        )
        .replace("subgroups: []", "subgroups: [{text: A, sources: [pmid:90000100]}]")
    )
    reject([add_par("subgroups")], "flow style", text=text)


def test_crlf_text_is_refused():
    reject([add_par("subgroups")], "CRLF", text=card_text().replace("\n", "\r\n"))


# --- real drafts: every shape in the repository ----------------------------


def real_drafts() -> list[Path]:
    return sorted(REPO_DRAFTS.glob("*.yaml"))


@pytest.mark.skipif(not real_drafts(), reason="no drafts in the repository")
@pytest.mark.parametrize("path", real_drafts(), ids=lambda p: p.stem)
def test_operations_on_every_real_draft_change_only_the_named_field(path, tmp_path):
    old = path.read_text(encoding="utf-8")
    data = yaml.safe_load(old)
    source = data["studies"][0]["id"]
    new = apply_operations(
        old,
        ops(
            add_par("level_reason", "A fictional added paragraph.", [source]),
            rep_par("level_reason", 0, "A fictional replacement.", [source]),
            card=data["slug"],
        ),
    )
    changed = yaml.safe_load(new)
    unchanged_keys = [k for k in data if k not in ("level_reason",)]
    assert all(changed[k] == data[k] for k in unchanged_keys)
    out = tmp_path / path.name
    out.write_text(new, encoding="utf-8", newline="\n")
    assert cards.validate_card_file(out) == []
    # everything outside the level_reason block is byte-identical
    a, b = old.split("\n"), new.split("\n")
    start = a.index("level_reason:")
    end = next(i for i in range(start + 1, len(a)) if a[i] and not a[i].startswith(" "))
    assert b[:start] == a[:start] and b[-(len(a) - end) :] == a[end:]


def test_splice_self_check_fails_safely_when_a_column_zero_comment_sits_between_studies():
    marker = "# --- contradicts ---"
    text = card_text().replace("  " + marker + chr(10), marker + chr(10))
    assert (chr(10) + marker + chr(10)) in text
    snapshot = str(text)
    with pytest.raises(OperationError, match="does not match the intended change"):
        apply_operations(text, ops(add_study()))
    assert text == snapshot


# --- preprints: tier 2 --------------------------------------------------------

PREPRINT = "doi:10.99999/fictional.pre"


def add_preprint_study() -> dict:
    study = {
        **copy.deepcopy(NEW_STUDY),
        "id": PREPRINT,
        "role": "early_signal",
        "case_definition": "other",
        "case_definition_quote": None,
        "preprint": True,
    }
    return {"op": "add_study", "study": study}


def preprint_ops(*operations: dict) -> OpsFile:
    return ops(*operations, paper=PREPRINT)


def test_an_operation_that_adds_a_preprint_study_is_tier_2():
    parsed = preprint_ops(add_preprint_study())
    assert [tier(o, preprint_ids(parsed)) for o in parsed.operations] == [2]


def test_a_paragraph_citing_a_preprint_added_in_the_same_file_is_tier_2_but_one_citing_a_journal_paper_is_tier_1():
    parsed = preprint_ops(
        add_preprint_study(),
        add_par("early_signals", sources=[PREPRINT]),
        add_par("early_signals", sources=["pmid:90000100"]),
    )
    found = preprint_ids(parsed)
    assert found == {PREPRINT}
    assert [tier(o, found) for o in parsed.operations] == [2, 2, 1]


def test_a_paragraph_citing_a_preprint_already_on_the_card_is_tier_2():
    data = yaml.safe_load(card_text())
    data["studies"].append({**copy.deepcopy(NEW_STUDY), "id": PREPRINT, "role": "early_signal", "preprint": True})
    parsed = ops(add_par("early_signals", sources=[PREPRINT]), add_par("early_signals"))
    found = preprint_ids(parsed, data)
    assert [tier(o, found) for o in parsed.operations] == [2, 1]


def test_a_doi_paper_must_add_its_study_with_preprint_true():
    plain = {**copy.deepcopy(NEW_STUDY), "id": "doi:10.99999/fictional.plain"}
    with pytest.raises(OperationError, match="needs preprint: true"):
        ops({"op": "add_study", "study": plain}, paper=plain["id"])


def test_every_operation_of_a_file_for_a_doi_preprint_is_tier_2_even_one_citing_a_journal_paper():
    parsed = preprint_ops(add_preprint_study(), add_par("early_signals", sources=["pmid:90000100"]))
    assert tiers(parsed) == [2, 2]


def test_tiers_of_a_pubmed_file_are_per_operation():
    parsed = ops(add_study(), add_par("early_signals"), {"op": "propose", "target": "contested", "value": None})
    assert tiers(parsed) == [1, 1, 2]


def test_a_preprint_study_is_written_with_preprint_true_and_a_plain_study_without_the_key(tmp_path):
    parsed = preprint_ops(add_preprint_study())
    new = apply_operations(card_text(), parsed, validate=False)
    assert yaml.safe_load(new)["studies"][-1]["preprint"] is True
    assert "    preprint: true" in new
    plain = apply_operations(card_text(), ops(add_study()), validate=False)
    assert "preprint" not in plain


# --- core_claim: reworded by a correction or a valve fix, never removed, never given a new source -----------------


def test_replace_core_claim_changes_only_its_lines():
    old = card_text().splitlines()
    new = apply_operations(card_text(), ops(rep_par("core_claim", 0, "A reworded claim."), paper=None), validate=False)
    assert yaml.safe_load(new)["core_claim"] == {"text": "A reworded claim.", "sources": ["pmid:90000100"]}
    after = new.splitlines()
    start = old.index("core_claim:")
    end = old.index("level: 2")  # the key after core_claim
    tail = len(old) - end
    assert after[:start] == old[:start] and after[len(after) - tail :] == old[end:]  # the rest is byte-identical


def test_replace_core_claim_refuses_any_index_but_0():
    with pytest.raises(OperationError, match="only valid index is 0"):
        ops(rep_par("core_claim", 1), paper=None)


def test_replace_core_claim_refuses_a_new_source():
    with pytest.raises(OperationError, match="no new source"):
        apply_operations(
            card_text(), ops(rep_par("core_claim", 0, sources=["pmid:90000104"]), paper=None), validate=False
        )


def test_remove_paragraph_refuses_core_claim():
    op = {"op": "remove_paragraph", "field": "core_claim", "index": 0}
    with pytest.raises(OperationError, match="core_claim cannot be removed"):
        apply_operations(card_text(), ops(op, paper=None), validate=False)


def test_add_paragraph_refuses_core_claim_and_replacing_it_is_tier_2():
    with pytest.raises(OperationError):
        ops(add_par("core_claim"))
    assert tier(ops(rep_par("core_claim", 0), paper=None).operations[0]) == 2
