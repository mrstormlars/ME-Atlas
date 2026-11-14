"""Tests for the correction-only operations: update_study, remove_paragraph, remove_link.

Fictional card in tests/fixtures/pipeline; no network, no LLM.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
import yaml
from test_operations import blocks, card_text, ops, real_drafts, validates

from me_atlas.operations import OperationError, OpsFile, apply_operations, parse_ops, tiers


def corr(*operations: dict, card: str = "fictional-pipeline-card") -> OpsFile:
    """An operations file of a correction round: it names no paper."""
    return parse_ops({"card": card, "paper": None, "operations": list(operations)})


def upd(study_id: str = "pmid:90000100", **fields) -> dict:
    return {"op": "update_study", "id": study_id, "set": fields}


def rem_par(field: str, index: int) -> dict:
    return {"op": "remove_paragraph", "field": field, "index": index}


def rem_link(to: str) -> dict:
    return {"op": "remove_link", "to": to}


LINKS = (
    "layer: mechanism\n"
    "links:\n"
    "  # a comment above the first link\n"
    "  - to: other-fictional-card\n"
    "    support: proposed\n"
    "    text: >-\n"
    "      A fictional review proposes a link.\n"
    "    sources: [pmid:90000100]\n"
    "  - to: symptom:fictional-symptom\n"
    "    support: proposed\n"
    "    text: A second fictional link.\n"
    "    sources: [pmid:90000100]\n"
)


def with_links(text: str) -> str:
    """The fixture card with a layer and two links, written before last_checked as the real cards do."""
    return text.replace("last_checked:\n", LINKS + "last_checked:\n", 1)


# --- update_study ----------------------------------------------------------------------------------------


def test_update_study_changes_only_the_named_lines(tmp_path):
    old = card_text()
    new = apply_operations(old, corr(upd(case_definition="Fukuda", case_definition_quote="Participants met Fukuda.")))
    assert validates(new, tmp_path) == []
    study = yaml.safe_load(new)["studies"][0]
    assert (study["case_definition"], study["case_definition_quote"]) == ("Fukuda", "Participants met Fukuda.")
    assert study["case_definition_source"] == "abstract"
    assert blocks(old, new) == [
        (["    case_definition: CCC"], ["    case_definition: Fukuda"]),
        (
            ["    case_definition_quote: Participants met the Canadian Consensus Criteria."],
            ["    case_definition_quote: Participants met Fukuda."],
        ),
    ]
    assert yaml.safe_load(new)["studies"][1] == yaml.safe_load(old)["studies"][1]


def test_update_study_rewrites_a_long_finding_and_a_scalar(tmp_path):
    old = card_text()
    long = "A study of n=20 patients and 20 controls found lower widget signalling in patients; a limit was added."
    new = apply_operations(old, corr(upd(finding=long, year=2019)))
    assert validates(new, tmp_path) == []
    study = yaml.safe_load(new)["studies"][0]
    assert study["finding"] == long and study["year"] == 2019
    assert "    year: 2019" in new and "    year: 2020" not in new
    # nothing outside the first study changed
    a, b = old.split("\n"), new.split("\n")
    start = a.index("  - id: pmid:90000104")
    assert b[-(len(a) - start) :] == a[start:]


def test_update_study_can_add_a_missing_optional_key(tmp_path):
    old = card_text()
    new = apply_operations(old, corr(upd("pmid:90000104", group="Another Fictional Group")))
    assert validates(new, tmp_path) == []
    assert yaml.safe_load(new)["studies"][1]["group"] == "Another Fictional Group"
    [(removed, added)] = blocks(old, new)
    assert removed == [] and added == ["    group: Another Fictional Group"]


def test_update_study_to_unverified_with_null_source_and_quote_is_accepted():
    # The card validator (V5, V9) then judges the card; the operation itself only checks the provenance rule.
    new = apply_operations(
        card_text(),
        corr(upd(case_definition="unverified", case_definition_source=None, case_definition_quote=None)),
        validate=False,
    )
    study = yaml.safe_load(new)["studies"][0]
    assert study["case_definition"] == "unverified" and study["case_definition_quote"] is None


@pytest.mark.parametrize(
    "operation, fragment",
    [
        (upd("pmid:90000999", year=2000), "is not on this card"),
        (upd(nonsense=1), "'nonsense' is not a field of a study"),
        (upd(id="pmid:90000100"), "'id' of a study cannot be set"),
        (upd(preprint=True), "'preprint' of a study cannot be set"),
        ({"op": "update_study", "id": "pmid:90000100", "set": {}}, "at least 1 item"),
        (upd(case_definition="CCC", case_definition_source=None), "needs case_definition_source"),
        (upd(case_definition="Fukuda", case_definition_quote=None), "needs case_definition_quote"),
        (upd(case_definition="unverified"), "must have null source and null quote"),
        (upd(year="not a year"), "does not validate"),
        (upd(role="not a role"), "does not validate"),
    ],
)
def test_update_study_negative_cases_are_rejected(operation, fragment):
    with pytest.raises(OperationError) as err:
        apply_operations(card_text(), corr(operation))
    assert fragment in str(err.value)


# --- remove_paragraph ------------------------------------------------------------------------------------


def test_remove_paragraph_from_a_list_removes_only_that_item(tmp_path):
    old = card_text()
    new = apply_operations(old, corr(rem_par("contested.reason", 1)))
    assert validates(new, tmp_path) == []
    assert len(yaml.safe_load(new)["contested"]["reason"]) == 1
    [(removed, added)] = blocks(old, new)
    assert added == [] and removed[0] == "    - text: >-"
    assert "    # a comment between two paragraphs" in new  # the comment sits before the removed item's neighbour


def test_remove_paragraph_may_empty_subgroups_or_early_signals(tmp_path):
    new = apply_operations(card_text(), corr(rem_par("early_signals", 0)))
    assert validates(new, tmp_path) == []
    assert yaml.safe_load(new)["early_signals"] == [] and "early_signals: []\nstudies:" in new


def test_remove_paragraph_of_a_false_badge_reason_leaves_null(tmp_path):
    new = apply_operations(card_text(), corr(rem_par("badges.explains_pem.reason", 0)))
    assert validates(new, tmp_path) == []
    assert yaml.safe_load(new)["badges"]["explains_pem"]["reason"] is None


@pytest.mark.parametrize(
    "operation, fragment",
    [
        (rem_par("level_reason", 0), "level_reason cannot be left empty"),
        (rem_par("early_signals", 3), "out of range"),
        (rem_par("subgroups", 0), "out of range"),
    ],
)
def test_remove_paragraph_refusals(operation, fragment):
    with pytest.raises(OperationError) as err:
        apply_operations(card_text(), corr(operation))
    assert fragment in str(err.value)


def test_remove_paragraph_refuses_to_empty_contested_reason():
    two = apply_operations(card_text(), corr(rem_par("contested.reason", 1)))
    with pytest.raises(OperationError, match="contested.reason cannot be left empty"):
        apply_operations(two, corr(rem_par("contested.reason", 0)))


def test_remove_paragraph_refuses_a_true_badge_without_a_reason():
    text = card_text().replace("explains_pem:\n    value: false", "explains_pem:\n    value: true")
    with pytest.raises(OperationError, match="cannot be left empty while the badge is true"):
        apply_operations(text, corr(rem_par("badges.explains_pem.reason", 0)), validate=False)


def test_remove_paragraph_on_a_card_that_is_not_contested_is_refused():
    no_contested = apply_operations(
        card_text(), ops({"op": "propose", "target": "contested", "value": None}), validate=False
    )
    with pytest.raises(OperationError, match="no 'contested'"):
        apply_operations(no_contested, corr(rem_par("contested.reason", 0)), validate=False)


# --- remove_link -----------------------------------------------------------------------------------------


def test_remove_link_removes_one_item_and_keeps_every_other_line():
    old = with_links(card_text())
    new = apply_operations(old, corr(rem_link("other-fictional-card")), validate=False)
    assert [x["to"] for x in yaml.safe_load(new)["links"]] == ["symptom:fictional-symptom"]
    [(removed, added)] = blocks(old, new)
    assert added == [] and removed[0] == "  - to: other-fictional-card" and len(removed) == 5
    assert "  # a comment above the first link" in new


def test_remove_the_last_link_leaves_an_empty_list():
    old = with_links(card_text())
    one = apply_operations(old, corr(rem_link("symptom:fictional-symptom")), validate=False)
    none = apply_operations(one, corr(rem_link("other-fictional-card")), validate=False)
    assert yaml.safe_load(none)["links"] == [] and "links: []\nlast_checked:" in none


def test_remove_link_to_an_unknown_target_is_rejected():
    with pytest.raises(OperationError, match="no link to 'nowhere'"):
        apply_operations(with_links(card_text()), corr(rem_link("nowhere")), validate=False)
    with pytest.raises(OperationError, match="no link to 'nowhere'"):
        apply_operations(card_text(), corr(rem_link("nowhere")), validate=False)


# --- tiers and the real drafts ---------------------------------------------------------------------------


def test_tiers_of_the_correction_operations():
    assert tiers(corr(upd(year=2019), rem_par("early_signals", 0), rem_link("x"))) == [1, 1, 2]


@pytest.mark.skipif(not real_drafts(), reason="no drafts in the repository")
@pytest.mark.parametrize("path", real_drafts(), ids=lambda p: p.stem)
def test_correction_operations_on_every_real_draft_change_only_their_block(path: Path):
    old = path.read_text(encoding="utf-8")
    data = yaml.safe_load(old)
    first = data["studies"][0]
    operations = [upd(first["id"], year=first["year"] + 1)]
    if data["links"]:
        operations.append(rem_link(data["links"][0]["to"]))
    new = apply_operations(old, corr(*operations, card=data["slug"]), validate=False)
    changed = yaml.safe_load(new)
    assert changed["studies"][0]["year"] == first["year"] + 1
    assert changed["studies"][1:] == data["studies"][1:]
    assert len(changed["links"]) == len(data["links"]) - (1 if data["links"] else 0)
    a, b = old.split("\n"), new.split("\n")
    changed_regions = [
        op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"
    ]
    assert len(changed_regions) <= 2
