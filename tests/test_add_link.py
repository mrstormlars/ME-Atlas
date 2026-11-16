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


# --- set_link_text (the wording valve of a link round) ----------------------------------------------------

SET = {"op": "set_link_text", "to": "other-fictional-card", "text": "A reworded fictional link text."}


def test_set_link_text_replaces_only_the_text_lines_of_the_named_link():
    old = with_links(card_text())
    new = apply_operations(old, file(SET), validate=False)
    before, after = yaml.safe_load(old)["links"], yaml.safe_load(new)["links"]
    assert after[0]["text"] == SET["text"] and after[1] == before[1]
    assert {k: v for k, v in after[0].items() if k != "text"} == {k: v for k, v in before[0].items() if k != "text"}
    assert blocks(old, new) == [
        (["      A fictional review proposes a link."], ["      A reworded fictional link text."])
    ]
    assert "  # a comment above the first link" in new
    assert yaml.safe_load(new)["studies"] == yaml.safe_load(old)["studies"]


def test_set_link_text_of_the_second_link_leaves_the_first_alone():
    old = with_links(card_text())
    new = apply_operations(old, file({**SET, "to": "symptom:fictional-symptom"}), validate=False)
    assert yaml.safe_load(new)["links"][0] == yaml.safe_load(old)["links"][0]
    assert yaml.safe_load(new)["links"][1]["text"] == SET["text"]


def test_set_link_text_gives_the_text_an_add_link_would_have_written():
    base = card_text()
    added = apply_operations(base, file({**LINK, "text": SET["text"]}), validate=False)
    fixed = apply_operations(
        apply_operations(base, file(LINK), validate=False), file({**SET, "to": LINK["to"]}), validate=False
    )
    assert added == fixed  # byte for byte: a stage text can be re-derived either way


def test_set_link_text_is_tier_2_and_refuses_an_unknown_link_and_bad_fields():
    assert tiers(file(SET)) == [2]
    with pytest.raises(OperationError, match="has no link to 'no-such-link'"):
        apply_operations(with_links(card_text()), file({**SET, "to": "no-such-link"}), validate=False)
    with pytest.raises(OperationError, match="has no link to"):
        apply_operations(card_text(), file(SET), validate=False)  # a card without links
    for change in ({"text": ""}, {"text": "  "}, {"support": "proposed"}, {"sources": ["pmid:90000100"]}, {"to": ""}):
        with pytest.raises(OperationError):
            file({**SET, **change})
