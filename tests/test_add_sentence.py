"""Tests for `add_sentence` (DECISIONS 2026-11-16): one added sentence an objecting audit part asks for.

Fictional card, records and agent output in temporary folders. No network, no AI, no git.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_correction import Corr, ops_data
from test_pipeline import SLUG, Env
from test_publish_card import Pub, whole

from me_atlas import pipeline
from me_atlas.operations import OperationError, parse_ops

TITLE_100 = "Fictional controlled study of widget signalling."
SENTENCE = "The larger study did not state which case definition applied to its comparison group."


def part(source: str, quote: str, **extra) -> dict:
    return {
        "decision_part": "A statement is missing.",
        "rubric": whole()["parts"][0]["rubric"],
        "evidence": [{"source": source, "quote": quote}],
    } | extra


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def corr(env: Env, tmp_path: Path) -> Corr:
    c = Corr(Pub(env, tmp_path), tmp_path)
    parts = [
        part("pmid:90000100", TITLE_100, **{"class": "wording", "target": "early_signals[0]"}),
        part("pmid:90000100", "20 patients and 20 controls were compared.", **{"class": "decisive"}),
    ]
    c.pub.audits_of_card(whole("reject", parts=parts), whole("reject"))
    assert c.pub.publish() == 0 and not c.card.exists()
    return c


def cfg_of(c: Corr) -> pipeline.Config:
    return pipeline.Config(c.dir, c.env.cards, c.env.drafts, c.env.cache, pipeline.DEFAULT_SPEC, audits_dir=c.audits)


def answers(c: Corr, index: int) -> dict:
    """The audit part of the fixture: 0 is the wording part with its own target, 1 the decisive one without."""
    wanted = "A statement is missing."
    mine = [
        (name, i, p)
        for name, i, p, _d in pipeline.objecting_audit_parts(cfg_of(c), SLUG, 1)
        if p.decision_part == wanted
    ]
    name, i, _p = sorted(mine, key=lambda x: x[2].target is None)[index]
    return {"record": name, "part": i}


def sentence(c: Corr, part_index: int = 0, **over) -> dict:
    data = {
        "op": "add_sentence",
        "target": "early_signals[0]",
        "text": SENTENCE,
        "sources": ["pmid:90000100"],
        "answers": answers(c, part_index),
    }
    return data | over


def errors(c: Corr) -> str:
    record = json.loads((c.dir / "checks" / f"{SLUG}-rC1.json").read_text(encoding="utf-8"))
    return "; ".join(record["ops_errors"]) + " " + " ".join(f"{r['code']} {r['level']}" for r in record["citations"])


def applied(c: Corr) -> dict:
    return yaml.safe_load((c.dir / "applied" / f"{SLUG}-rC1" / f"{SLUG}.yaml").read_text(encoding="utf-8"))


def test_a_sentence_answering_an_objecting_part_is_appended_to_the_parts_target(corr: Corr):
    assert corr.pre_review() == 0
    assert corr.apply(ops_data(sentence(corr))) == 0
    paragraph = applied(corr)["early_signals"][0]
    assert paragraph["text"].endswith(" " + SENTENCE) and paragraph["sources"] == ["pmid:90000100"]
    before = yaml.safe_load(corr.draft.read_text(encoding="utf-8"))
    after = applied(corr)
    for key in ("level", "badges", "links", "studies", "layer"):
        assert after.get(key) == before.get(key)  # nothing but the text of the item changed
    assert len(after["early_signals"]) == 1


def test_a_target_the_pre_review_gives_the_part_is_allowed_and_a_new_source_joins_the_paragraph(corr: Corr):
    assert corr.pre_review() == 0  # every part gets the broad targets, contested_reason[1] among them
    op = sentence(corr, 1, target="contested_reason[1]", text="A second statement is given.")
    assert corr.apply(ops_data(op)) == 0
    paragraph = applied(corr)["contested"]["reason"][1]
    assert paragraph["text"].endswith(" A second statement is given.")
    assert paragraph["sources"] == ["pmid:90000104", "pmid:90000100"]  # the part's source joins the paragraph


def test_a_removal_earlier_in_the_file_does_not_move_the_target_of_the_sentence(corr: Corr):
    assert corr.pre_review() == 0
    remove = {"op": "remove_paragraph", "field": "contested.reason", "index": 0}
    op = sentence(corr, 1, target="contested_reason[1]")
    assert corr.apply(ops_data(remove, op)) == 0  # the draft's paragraph 1 is paragraph 0 now
    reason = applied(corr)["contested"]["reason"]
    assert len(reason) == 1 and reason[0]["text"].endswith(SENTENCE)


def test_a_sentence_for_a_paragraph_the_same_file_removed_is_refused(corr: Corr):
    assert corr.pre_review() == 0
    op = sentence(corr, 1, target="contested_reason[1]")
    gone = {"op": "remove_paragraph", "field": "contested.reason", "index": 1}
    assert corr.apply(ops_data(gone, op)) == 1
    assert "removed" in errors(corr)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"answers": {"record": "nothing.yaml", "part": 0}}, "not an objecting part"),
        ({"answers": {"record": "x", "part": 9}}, "not an objecting part"),
        ({"sources": ["pmid:90000104"]}, "does not quote"),
        ({"sources": ["pmid:90000100", "pmid:99999999"]}, "does not quote"),
        ({"target": "contested_reason[1]"}, "neither the target of that audit part"),
    ],
)
def test_a_sentence_that_breaks_a_condition_is_refused_as_an_ops_problem(corr: Corr, change, fragment):
    assert corr.pre_review(targets=["core_claim"]) == 0
    assert corr.apply(ops_data(sentence(corr) | change)) == 1
    assert fragment in errors(corr)


def test_two_sentences_for_one_part_are_refused(corr: Corr):
    assert corr.pre_review() == 0
    second = sentence(corr, text="Another statement is given.")
    assert corr.apply(ops_data(sentence(corr), second)) == 1
    assert "second added sentence" in errors(corr)
    other = sentence(corr, 1, target="contested_reason[1]", text="A statement is given.")
    assert corr.apply(ops_data(sentence(corr), other)) == 0  # one for each part is fine


def test_a_part_that_does_not_object_is_not_answerable(corr: Corr):
    assert corr.pre_review() == 0
    accept_record = whole("accept", parts=[part("pmid:90000100", TITLE_100, **{"class": "none"})])
    (corr.audits / "2026-11-14-fictional-pipeline-card-C1.yaml").write_text(
        yaml.safe_dump(accept_record), encoding="utf-8"
    )
    data = sentence(corr) | {"answers": {"record": "2026-11-14-fictional-pipeline-card-C1.yaml", "part": 0}}
    assert corr.apply(ops_data(data)) == 1
    assert "not an objecting part" in errors(corr)  # the round's own records and accepting ones are left out


@pytest.mark.parametrize(
    "change",
    [
        {"text": "One statement is given. A second one follows."},
        {"text": "A statement without an end"},
        {"text": "A statement that ends twice.."},
        {"target": "core_claim"},
        {"target": "links[0]"},
        {"target": "links[0].reason"},
    ],
)
def test_the_text_is_one_sentence_and_the_target_is_a_free_text_item_that_is_no_core_claim_or_link(corr: Corr, change):
    assert corr.pre_review() == 0
    assert corr.apply(ops_data(sentence(corr) | change)) == 1
    with pytest.raises(OperationError):
        parse_ops(ops_data(sentence(corr) | change))


def test_a_number_the_quoted_source_does_not_have_is_refused(corr: Corr):
    assert corr.pre_review() == 0
    assert corr.apply(ops_data(sentence(corr, text="A further 777 patients were seen."))) == 1
    assert "states the number(s) 777" in errors(corr)


def test_only_a_correction_round_may_add_a_sentence(corr: Corr):
    assert "add_sentence" in pipeline.CORRECTION_ONLY_OPS


def test_the_trail_carries_the_sentence_and_the_quotes_of_the_part(corr: Corr):
    corr.round_to_audits(data=ops_data(sentence(corr)))
    assert corr.publish() == 0 and corr.card.exists()
    added = corr.trail()["added_sentences"]
    assert added == [
        {
            "target": "early_signals[0]",
            "text": SENTENCE,
            "answers": answers(corr, 0),
            "quotes": [{"source": "pmid:90000100", "quote": TITLE_100}],
        }
    ]


def test_publish_card_checks_the_condition_again(corr: Corr):
    corr.round_to_audits(data=ops_data(sentence(corr)))
    ops = corr.dir / "ops" / f"{SLUG}-rC1.json"
    data = json.loads(ops.read_text(encoding="utf-8"))
    data["operations"][0]["sources"] = ["pmid:90000104"]  # not quoted by the part
    ops.write_text(json.dumps(data), encoding="utf-8")
    assert corr.publish() == 0
    assert not corr.card.exists()
    assert "does not quote" in corr.report()


def test_a_number_must_be_in_the_quotes_of_the_part_not_merely_in_another_cited_source(corr: Corr):
    assert corr.pre_review() == 0
    text = "It had 20 controls."  # 20 is in the abstract of pmid:90000100, which early_signals[0] cites
    assert corr.apply(ops_data(sentence(corr, 0, text=text))) == 1  # part 0 quotes only the title
    assert "not in the quotes of that audit part" in errors(corr)
    assert corr.apply(ops_data(sentence(corr, 1, target="early_signals[0]", text=text))) == 0  # part 1 quotes it


@pytest.fixture
def two_paragraphs(env: Env, tmp_path: Path) -> Corr:
    """The draft's level_reason has two paragraphs; the audit part is decisive and has no target of its own."""
    draft = yaml.safe_load(env.drafts.joinpath(f"{SLUG}.yaml").read_text(encoding="utf-8"))
    first = draft["level_reason"]
    draft["level_reason"] = [first, {"text": "A second fictional reason.", "sources": ["pmid:90000100"]}]
    env.drafts.joinpath(f"{SLUG}.yaml").write_text(yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
    c = Corr(Pub(env, tmp_path), tmp_path)
    c.pub.draft_bytes = c.draft.read_bytes()
    c.pub.audits_of_card(
        whole("reject", parts=[part("pmid:90000100", TITLE_100, **{"class": "decisive"})]), whole("reject")
    )
    assert c.pub.publish() == 0 and not c.card.exists()
    return c


def mine(c: Corr) -> dict:
    wanted = "A statement is missing."
    name, i, _p, _d = next(
        x for x in pipeline.objecting_audit_parts(cfg_of(c), SLUG, 1) if x[2].decision_part == wanted
    )
    return {"record": name, "part": i}


def test_a_part_tied_to_layer_or_level_may_add_to_the_last_level_reason_paragraph_only(two_paragraphs: Corr):
    c = two_paragraphs
    assert c.pre_review(targets=["layer"]) == 0
    last = sentence(c, target="level_reason[1]") | {"answers": mine(c)}
    earlier = sentence(c, target="level_reason[0]") | {"answers": mine(c)}
    assert c.apply(ops_data(earlier)) == 1
    assert "neither the target of that audit part" in errors(c)
    assert c.apply(ops_data(last)) == 0
    assert applied(c)["level_reason"][1]["text"].endswith(SENTENCE)


def test_contested_maps_to_the_last_contested_paragraph_and_a_study_to_its_finding(corr: Corr):
    assert corr.pre_review(targets=["contested", "studies[pmid:90000100].case_definition"]) == 0
    earlier = sentence(corr, 1, target="contested_reason[0]")
    assert corr.apply(ops_data(earlier)) == 1
    finding = sentence(corr, 1, target="studies[pmid:90000100].finding")
    assert corr.apply(ops_data(finding)) == 0  # the second attempt after a failed first
    assert applied(corr)["studies"][0]["finding"].endswith(SENTENCE)


def test_a_link_target_is_not_mapped_and_the_mapping_is_listed_in_the_context(corr: Corr):
    cfg = cfg_of(corr)
    from me_atlas import cards

    card = cards.load_card(corr.draft)
    assert pipeline.sentence_targets(card, ["contested", "badges.explains_pem", "links[0]", "layer"]) == [
        "contested",
        "contested_reason[1]",
        "badges.explains_pem",
        "badge_reasons.explains_pem[0]",
        "links[0]",
        "layer",
        "level_reason[0]",
    ]
    assert corr.pre_review(targets=["contested"]) == 0 and corr.plan() == 0
    text = (corr.dir / "correction-context" / f"{SLUG}-C1.md").read_text(encoding="utf-8")
    assert "`contested_reason[1]`" in text.split("## 9. Added sentences")[1]
    assert cfg
