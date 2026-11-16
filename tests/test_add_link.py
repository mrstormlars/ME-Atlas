"""Tests for the ``add_link`` operation (link rounds only). Fictional card in tests/fixtures/pipeline."""

from __future__ import annotations

import pytest
import yaml
from test_correction_ops import with_links
from test_operations import blocks, card_text

from me_atlas.operations import OperationError, apply_operations, parse_ops, tiers
from me_atlas.pipeline import correction_ops_problems

LINK = {
    "op": "add_link",
    "to": "new-fictional-target",
    "support": "proposed",
    "text": "A fictional review proposes a link; it was not studied in patients.",
    "sources": ["pmid:90000100"],
}


def file(*operations: dict, card: str = "fictional-pipeline-card"):
    return parse_ops({"card": card, "paper": None, "operations": list(operations)})


def test_add_link_to_a_card_with_links_appends_and_keeps_every_existing_line():
    old = with_links(card_text())
    new = apply_operations(old, file(LINK), validate=False)
    assert [x["to"] for x in yaml.safe_load(new)["links"]] == [
        "other-fictional-card",
        "symptom:fictional-symptom",
        "new-fictional-target",
    ]
    [(removed, added)] = blocks(old, new)
    assert removed == [] and added[0] == "  - to: new-fictional-target" and "pmid:90000100" in added[-1]
    assert "  # a comment above the first link" in new  # nothing else moved


def test_add_link_to_a_card_with_no_links_writes_a_block_list():
    old = card_text()
    new = apply_operations(old, file(LINK), validate=False)
    assert yaml.safe_load(new)["links"][0]["to"] == "new-fictional-target"
    assert "links:\n  - to: new-fictional-target\n    support: proposed\n    text: >-\n" in new
    [(removed, _added)] = blocks(old, new)
    assert removed == []  # only inserted lines (no `links` key before)


def test_add_link_replaces_an_empty_links_list():
    old = card_text().replace("last_checked:\n", "links: []\nlast_checked:\n", 1)
    new = apply_operations(old, file(LINK), validate=False)
    assert "links: []" not in new and yaml.safe_load(new)["links"][0]["support"] == "proposed"
    [(removed, added)] = blocks(old, new)
    assert removed == ["links: []"] and added[0] == "links:"


def test_two_add_links_keep_the_order():
    second = {**LINK, "to": "symptom:another", "support": "proposed"}
    new = apply_operations(card_text(), file(LINK, second), validate=False)
    assert [x["to"] for x in yaml.safe_load(new)["links"]] == ["new-fictional-target", "symptom:another"]


def test_add_link_is_tier_2():
    assert tiers(file(LINK)) == [2]


def test_add_link_to_a_target_already_linked_is_refused():
    old = with_links(card_text())
    with pytest.raises(OperationError, match="already has a link to 'other-fictional-card'"):
        apply_operations(old, file({**LINK, "to": "other-fictional-card"}), validate=False)


def test_add_link_twice_to_the_same_target_is_refused():
    with pytest.raises(OperationError, match="already has a link"):
        apply_operations(card_text(), file(LINK, LINK), validate=False)


def test_add_link_to_the_cards_own_slug_is_refused():
    with pytest.raises(OperationError, match="cannot link to itself"):
        apply_operations(card_text(), file({**LINK, "to": "fictional-pipeline-card"}), validate=False)


@pytest.mark.parametrize(
    "change",
    [{"support": "strong"}, {"text": ""}, {"text": "   "}, {"sources": []}, {"to": ""}, {"extra": 1}],
)
def test_add_link_with_a_bad_field_is_refused(change):
    with pytest.raises(OperationError):
        file({**LINK, **change})


def test_a_refused_add_link_changes_nothing():
    old = with_links(card_text())
    with pytest.raises(OperationError):
        apply_operations(old, file(LINK, {**LINK, "to": "other-fictional-card"}), validate=False)
    assert old == with_links(card_text())  # pure: the input text is never changed


def test_the_weekly_apply_refuses_add_link_and_names_it(tmp_path):
    from test_pipeline import Env

    env = Env(tmp_path)
    env.prepare()
    assert env.classify() == 0
    path = env.run / "ops" / "fictional-pipeline-card-90000101-r1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps({"card": "fictional-pipeline-card", "paper": "pmid:90000101", "operations": [LINK]}))
    assert env.cli("apply", "fictional-pipeline-card", str(path), "--round", "1") == 1
    assert "operations[0] is add_link: only a link round" in "\n".join(env.out)


def test_a_correction_round_refuses_add_link_and_names_it():

    found = correction_ops_problems(file(LINK), 2)
    assert any("operations[0] is add_link" in p for p in found)
