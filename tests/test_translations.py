"""Tests for card translations: the mechanical check, staleness, the merge of translator output and the commands.

Every card and every Norwegian sentence here is fictional. Nothing touches the network or an AI.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
import yaml

from me_atlas import cards as cardlib
from me_atlas import translations as tr

FIXTURE_CARD = Path(__file__).parent / "fixtures" / "cards" / "fictional-hypothesis.yaml"
SLUG = "fictional-hypothesis"


def card_data() -> dict:
    return copy.deepcopy(yaml.safe_load(FIXTURE_CARD.read_text(encoding="utf-8")))


def load_card_from(data: dict, tmp_path: Path) -> cardlib.Card:
    path = tmp_path / "cards" / f"{data['slug']}.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return cardlib.load_card(path)


@pytest.fixture
def card(tmp_path) -> cardlib.Card:
    return load_card_from(card_data(), tmp_path)


def sidecar_for(card: cardlib.Card, **text_overrides: str) -> tr.TFile:
    """A complete fictional Norwegian sidecar: 'NB ' plus the English text (same numbers, same sources)."""
    items = {}
    for loc, en in tr.english_items(card).items():
        items[loc] = tr.TItem(
            text=text_overrides.get(loc, "NB " + en.text),
            source_hash=tr.text_hash(en.text),
            sources=list(en.sources) if en.sources is not None else None,
        )
    return tr.TFile(slug=card.slug, items=items)


def status(result: tr.CardCheck, locator: str) -> str:
    return result.items[locator].status


# --- the English side -----


def test_english_items_list_every_translatable_field_by_locator(card):
    assert list(tr.english_items(card)) == [
        "name",
        "core_claim",
        "level_reason[0]",
        "contested_reason[0]",
        "badge_reasons.diagnostic_marker[0]",
        "badge_reasons.explains_pem[0]",
        "subgroups[0]",
        "early_signals[0]",
        "studies[pmid:00000001].finding",
        "studies[pmid:00000002].finding",
        "studies[pmid:00000003].finding",
        "studies[pmid:00000004].finding",
        "studies[doi:10.0000/fictional.5].finding",
    ]


def test_a_card_without_a_contested_mark_or_badge_reason_has_no_such_items(tmp_path):
    data = card_data()
    data["contested"] = None
    data["badges"]["diagnostic_marker"] = {"value": False, "reason": None}
    items = tr.english_items(load_card_from(data, tmp_path))
    assert "contested_reason[0]" not in items and "badge_reasons.diagnostic_marker[0]" not in items


def test_paragraphs_are_separate_items_and_names_and_findings_have_no_sources(tmp_path):
    data = card_data()
    data["level_reason"] = [
        {"text": "First fictional paragraph.", "sources": ["pmid:00000001"]},
        {"text": "Second fictional paragraph.", "sources": ["pmid:00000002"]},
    ]
    items = tr.english_items(load_card_from(data, tmp_path))
    assert items["level_reason[1]"].sources == ["pmid:00000002"]
    assert items["name"].sources is None and items["studies[pmid:00000001].finding"].sources is None


# --- the check: fresh, stale, missing -----


def test_a_complete_matching_translation_is_fresh_everywhere(card):
    result = tr.check_card(card, sidecar_for(card), "nb")
    assert {r.status for r in result.items.values()} == {"fresh"}
    assert result.errors == []


def test_no_sidecar_means_every_item_is_missing(card):
    result = tr.check_card(card, None, "nb")
    assert not result.has_file and {r.status for r in result.items.values()} == {"missing"}


def test_an_item_missing_from_the_file_is_missing_and_the_rest_stay_fresh(card):
    side = sidecar_for(card)
    del side.items["subgroups[0]"]
    result = tr.check_card(card, side, "nb")
    assert status(result, "subgroups[0]") == "missing"
    assert status(result, "core_claim") == "fresh"


def test_changed_english_text_makes_the_translation_stale(tmp_path):
    original = load_card_from(card_data(), tmp_path)
    side = sidecar_for(original)
    data = card_data()
    data["core_claim"]["text"] = "The fictional hypothesis now says something a little different."
    changed = load_card_from(data, tmp_path)
    result = tr.check_card(changed, side, "nb")
    assert status(result, "core_claim") == "stale"
    assert status(result, "level_reason[0]") == "fresh"  # only the item that changed


def test_a_stale_item_is_not_judged_on_its_numbers(tmp_path):
    original = load_card_from(card_data(), tmp_path)
    side = sidecar_for(original)
    data = card_data()
    data["studies"][0]["finding"] = "A study of n=41 patients and 40 controls found a fictional difference."
    result = tr.check_card(load_card_from(data, tmp_path), side, "nb")
    item = result.items["studies[pmid:00000001].finding"]
    assert item.status == "stale" and item.problems == ()


# --- the check: sources, numbers, PMIDs, extra fields -----


def invalid(card, locator: str, **changes) -> tuple[str, ...]:
    """Change one translated item (keeping its hash) and return its problems; it must come back invalid."""
    side = sidecar_for(card)
    side.items[locator] = side.items[locator].model_copy(update=changes)
    result = tr.check_card(card, side, "nb")
    assert status(result, locator) == "invalid", result.items[locator]
    return result.items[locator].problems


def test_a_changed_sources_list_is_invalid(card):
    problems = invalid(card, "core_claim", sources=["pmid:00000002"])
    assert any("sources" in p and "differ" in p for p in problems)


def test_a_dropped_source_is_invalid(card):
    assert any("sources" in p for p in invalid(card, "level_reason[0]", sources=["pmid:00000001"]))


def test_a_source_list_in_another_order_is_invalid(card):
    assert any("sources" in p for p in invalid(card, "level_reason[0]", sources=["pmid:00000002", "pmid:00000001"]))


def test_missing_sources_on_a_sourced_item_are_invalid(card):
    assert any("'sources' is missing" in p for p in invalid(card, "core_claim", sources=None))


def test_sources_on_an_item_that_has_none_are_an_extra_field(card):
    problems = invalid(card, "name", sources=["pmid:00000001"])
    assert any("has none on the English card" in p for p in problems)


def test_a_number_added_is_invalid(card):
    problems = invalid(
        card, "studies[pmid:00000001].finding", text="NB n=40 pasienter og 40 kontroller, 7 forskjeller."
    )
    assert any("numbers differ" in p and "'7'" in p for p in problems)


def test_a_number_removed_is_invalid(card):
    problems = invalid(card, "studies[pmid:00000003].finding", text="NB n=120 pasienter, ingen kontroller.")
    assert any("numbers differ" in p and "'100'" in p for p in problems)


def test_a_number_changed_is_invalid(card):
    problems = invalid(card, "studies[pmid:00000001].finding", text="NB n=41 pasienter og 40 kontroller.")
    assert any("numbers differ" in p and "'41'" in p for p in problems)


FINDING = "studies[pmid:00000001].finding"


def finding_status(tmp_path, english: str, norwegian: str) -> str:
    data = card_data()
    data["studies"][0]["finding"] = english
    c = load_card_from(data, tmp_path)
    return status(tr.check_card(c, sidecar_for(c, **{FINDING: norwegian}), "nb"), FINDING)


def test_a_swapped_pair_of_numbers_is_invalid(tmp_path):
    english = "A study of n=170 patients and 73 controls found a fictional difference."
    assert finding_status(tmp_path, english, "Fiktiv studie: n=73 pasienter og 170 kontroller.") == "invalid"
    assert finding_status(tmp_path, english, "Fiktiv studie: n=170 pasienter og 73 kontroller.") == "fresh"


def test_a_repeated_number_dropped_once_is_invalid(tmp_path):
    english = "A study of n=40 patients and 40 controls found a fictional difference."
    assert finding_status(tmp_path, english, "Fiktiv studie: n=40 pasienter, ingen kontroller.") == "invalid"
    assert finding_status(tmp_path, english, "Fiktiv studie: n=40 pasienter og 40 kontroller.") == "fresh"


def test_a_number_added_a_second_time_is_invalid(tmp_path):
    english = "A study of n=40 patients found a fictional difference."
    assert finding_status(tmp_path, english, "Fiktiv studie: n=40 pasienter, 40 i alt.") == "invalid"


def test_a_reordered_sentence_with_the_same_numbers_is_invalid(tmp_path):
    english = "A study of n=12 patients, then n=30 controls, found a ratio of 0.5."
    reordered = "Forholdet var 0,5 i en studie med n=30 kontroller og n=12 pasienter."
    assert finding_status(tmp_path, english, reordered) == "invalid"
    assert (
        finding_status(tmp_path, english, "Fiktiv studie: n=12 pasienter, deretter n=30 kontroller, forhold 0,5.")
        == "fresh"
    )


def test_the_problem_text_shows_both_sequences_in_order(card):
    problems = invalid(card, "studies[pmid:00000003].finding", text="NB n=100 og 120.")
    assert any("English ['120', '100']" in p and "translation ['100', '120']" in p for p in problems)


@pytest.mark.parametrize(
    ("english", "norwegian"),
    [
        ("n=170 and 73", "n=73 and 170"),
        ("40 patients and 40 controls", "40 patients"),
        ("12 then 30", "30 then 12"),
    ],
)
def test_the_number_sequence_must_match(english, norwegian):
    assert tr.numbers(english, "en") != tr.numbers(norwegian, "nb")


def test_a_decimal_without_a_leading_zero_is_read_as_zero_point():
    assert tr.numbers("P = .76", "en") == tr.numbers("P = 0,76", "nb") == ["0.76"]
    assert tr.numbers("P = .76", "en") == tr.numbers("P = ,76", "nb")
    assert tr.numbers(".5", "en") == tr.numbers("0,5", "nb") == ["0.5"]


def test_a_sentence_ending_period_and_a_norwegian_list_are_not_decimals():
    assert tr.numbers("end. 5 patients", "en") == ["5"]
    assert tr.numbers("1, 2 og 3", "nb") == ["1", "2", "3"]


def test_the_same_numbers_in_other_words_pass(tmp_path):
    data = card_data()
    data["studies"][0]["finding"] = "A study of n=40 patients and 40 controls found a fictional difference."
    c = load_card_from(data, tmp_path)
    side = sidecar_for(c, **{"studies[pmid:00000001].finding": "Fiktiv studie: 40 kontroller og n=40 pasienter."})
    assert status(tr.check_card(c, side, "nb"), "studies[pmid:00000001].finding") == "fresh"


def test_a_decimal_comma_is_accepted_for_a_decimal_point(tmp_path):
    data = card_data()
    data["studies"][0]["finding"] = "A study of n=40 patients found a ratio of 0.5 and 1.25."
    c = load_card_from(data, tmp_path)
    ok = sidecar_for(c, **{"studies[pmid:00000001].finding": "Fiktiv studie: n=40 pasienter, forhold 0,5 og 1,25."})
    assert status(tr.check_card(c, ok, "nb"), "studies[pmid:00000001].finding") == "fresh"
    bad = sidecar_for(c, **{"studies[pmid:00000001].finding": "Fiktiv studie: n=40 pasienter, forhold 0,6 og 1,25."})
    assert status(tr.check_card(c, bad, "nb"), "studies[pmid:00000001].finding") == "invalid"


def test_a_decimal_point_is_also_fine_in_the_translation(tmp_path):
    data = card_data()
    data["studies"][0]["finding"] = "A study of n=40 patients found a ratio of 0.5."
    c = load_card_from(data, tmp_path)
    side = sidecar_for(c, **{"studies[pmid:00000001].finding": "Fiktiv studie: n=40 pasienter, forhold 0.5."})
    assert status(tr.check_card(c, side, "nb"), "studies[pmid:00000001].finding") == "fresh"


@pytest.mark.parametrize(
    ("english", "norwegian", "same"),
    [
        ("1,200 patients", "1 200 pasienter", True),
        ("1,200 patients", "1 200 pasienter", True),
        ("1,200 patients", "1 200 pasienter", True),
        ("1200 patients", "1 200 pasienter", True),
        ("1,200 patients", "1200 pasienter", True),
        ("1,200 patients", "1 300 pasienter", False),
        ("12 patients", "1 2 pasienter", False),
        ("0.50 ratio", "0,5 forhold", True),
        ("3-5 days", "3–5 dager", True),
        ("3-5 days", "3–6 dager", False),
        ("see pmid:123", "se pmid:123", True),
    ],
)
def test_numbers_are_compared_by_value(english, norwegian, same):
    assert (tr.numbers(english, "en") == tr.numbers(norwegian, "nb")) is same


def test_numbers_leave_identifiers_to_the_pmid_check():
    assert tr.numbers("see pmid:12345678 and doi:10.1000/x.5, n=3", "en") == ["3"]


def test_a_pmid_that_differs_is_invalid(tmp_path):
    data = card_data()
    data["core_claim"]["text"] = "The fictional hypothesis rests on pmid:00000001 and pmid:00000002."
    data["core_claim"]["sources"] = ["pmid:00000001", "pmid:00000002"]
    c = load_card_from(data, tmp_path)
    ok = sidecar_for(c, core_claim="Fiktiv hypotese bygger på pmid:00000001 og pmid:00000002.")
    assert status(tr.check_card(c, ok, "nb"), "core_claim") == "fresh"
    bad = sidecar_for(c, core_claim="Fiktiv hypotese bygger på pmid:00000001 og pmid:00000009.")
    result = tr.check_card(c, bad, "nb")
    assert status(result, "core_claim") == "invalid"
    assert any(p.startswith("PMIDs differ") for p in result.items["core_claim"].problems)


def test_a_dropped_pmid_is_invalid(tmp_path):
    data = card_data()
    data["core_claim"]["text"] = "The fictional hypothesis rests on pmid:00000001."
    c = load_card_from(data, tmp_path)
    side = sidecar_for(c, core_claim="Fiktiv hypotese bygger på en studie.")
    assert status(tr.check_card(c, side, "nb"), "core_claim") == "invalid"


def test_a_banned_word_in_the_core_claim_or_an_early_signal_is_invalid(card):
    for locator in ("core_claim", "early_signals[0]"):
        for word in ("lovende", "gjennombrudd", "kur", "håp", "bevist", "promising", "cure"):
            assert any(word in p for p in invalid(card, locator, text=f"NB et {word} funn.")), (locator, word)


def test_a_banned_word_is_not_checked_in_a_finding_like_the_english_rule(card):
    side = sidecar_for(card, **{"studies[pmid:00000003].finding": "NB n=120 og 100 uten forskjell, bevisst valg."})
    side.items["studies[pmid:00000003].finding"] = tr.TItem(
        text="NB A study of n=120 patients and 100 controls found no fictional difference, a cure.",
        source_hash=tr.text_hash(
            "A study of n=120 patients and 100 controls found no fictional difference in widget signalling."
        ),
    )
    assert status(tr.check_card(card, side, "nb"), "studies[pmid:00000003].finding") == "fresh"


def test_a_locator_the_english_card_lacks_is_an_error(tmp_path):
    data = card_data()
    data["contested"] = None
    with_contested = load_card_from(card_data(), tmp_path)
    side = sidecar_for(with_contested)
    result = tr.check_card(load_card_from(data, tmp_path), side, "nb")
    assert result.errors == [f"{SLUG}: item 'contested_reason[0]' does not exist on the English card"]


def test_a_study_the_card_does_not_cite_is_an_error(card):
    side = sidecar_for(card)
    side.items["studies[pmid:99999999].finding"] = side.items["name"]
    assert any("studies[pmid:99999999].finding" in e for e in tr.check_card(card, side, "nb").errors)


def test_more_paragraphs_than_the_english_has_is_an_error(card):
    side = sidecar_for(card)
    side.items["level_reason[1]"] = side.items["level_reason[0]"]
    assert any("level_reason[1]" in e for e in tr.check_card(card, side, "nb").errors)


# --- the sidecar file -----


def write_sidecar(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def good_item() -> dict:
    return {"text": "Fiktiv tekst.", "source_hash": "a" * 64}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"slug": SLUG, "items": {}, "level": 5}, "level: Extra inputs are not permitted"),
        ({"slug": SLUG, "items": {"name": {**good_item(), "level": 5}}}, "Extra inputs are not permitted"),
        ({"slug": SLUG, "items": {"name": {"text": "x"}}}, "source_hash"),
        ({"slug": SLUG, "items": {"name": {**good_item(), "source_hash": "xyz"}}}, "source_hash"),
        ({"slug": SLUG, "items": {"name": {**good_item(), "text": "  "}}}, "text"),
        ({"slug": "other-slug", "items": {}}, "must equal the file name"),
        ({"items": {}}, "slug"),
        ({"slug": SLUG, "items": {"core_claim": {**good_item(), "sources": ["not-an-id"]}}}, "sources"),
    ],
)
def test_a_malformed_sidecar_is_rejected(tmp_path, data, message):
    path = write_sidecar(tmp_path / "nb" / f"{SLUG}.yaml", data)
    with pytest.raises(tr.TranslationError, match=message):
        tr.load_sidecar(path)


def test_an_unreadable_or_non_mapping_sidecar_is_rejected(tmp_path):
    path = tmp_path / "nb" / f"{SLUG}.yaml"
    path.parent.mkdir()
    path.write_text("- a list\n", encoding="utf-8")
    with pytest.raises(tr.TranslationError, match="top level"):
        tr.load_sidecar(path)
    path.write_text("a: [unclosed\n", encoding="utf-8")
    with pytest.raises(tr.TranslationError, match="invalid YAML"):
        tr.load_sidecar(path)


def test_a_sidecar_round_trips_in_english_order(card, tmp_path):
    side = sidecar_for(card)
    path = tmp_path / "nb" / f"{SLUG}.yaml"
    path.parent.mkdir()
    path.write_text(tr.dump_sidecar(side, list(tr.english_items(card))), encoding="utf-8", newline="\n")
    assert tr.load_sidecar(path) == side
    assert list(yaml.safe_load(path.read_text(encoding="utf-8"))["items"])[:2] == ["name", "core_claim"]
    assert b"\r" not in path.read_bytes()


# --- the card as the language shows it -----


def test_localise_card_puts_fresh_text_in_place_and_keeps_levels_badges_and_titles(card):
    side = sidecar_for(card, name="Fiktiv hypotese", core_claim="Fiktiv hovedpåstand.")
    local = tr.localise_card(card, tr.check_card(card, side, "nb"))
    assert local.card.name == "Fiktiv hypotese" and local.card.core_claim.text == "Fiktiv hovedpåstand."
    assert local.card.core_claim.sources == card.core_claim.sources
    assert local.card.level == card.level and local.card.contested == card.contested.model_copy(
        update={"reason": local.card.contested.reason}
    )
    assert local.card.badges.diagnostic_marker.value is card.badges.diagnostic_marker.value
    assert [s.title for s in local.card.studies] == [s.title for s in card.studies]
    assert [s.case_definition_quote for s in local.card.studies] == [s.case_definition_quote for s in card.studies]
    assert local.card.studies[0].finding.startswith("NB ")
    assert local.fallback == frozenset() and not local.name_fallback and local.has_file


def test_localise_card_keeps_english_for_stale_missing_and_invalid_items(card):
    side = sidecar_for(card)
    side.items["core_claim"] = side.items["core_claim"].model_copy(update={"source_hash": "b" * 64})  # stale
    del side.items["subgroups[0]"]  # missing
    side.items["early_signals[0]"] = side.items["early_signals[0]"].model_copy(update={"sources": []})  # invalid
    del side.items["name"]
    local = tr.localise_card(card, tr.check_card(card, side, "nb"))
    assert local.card.core_claim.text == card.core_claim.text
    assert local.card.subgroups[0].text == card.subgroups[0].text
    assert local.card.early_signals[0].text == card.early_signals[0].text
    assert local.card.name == card.name and local.name_fallback
    assert {id(card.core_claim), id(card.subgroups[0]), id(card.early_signals[0])} <= local.fallback
    assert id(card.studies[0]) not in local.fallback


def test_localise_card_without_a_file_falls_back_everywhere(card):
    local = tr.localise_card(card, tr.check_card(card, None, "nb"))
    assert local.card == card and not local.has_file


def test_localise_card_keeps_the_single_object_form_of_a_reason(tmp_path):
    c = load_card_from(card_data(), tmp_path)
    assert isinstance(c.level_reason, cardlib.SourcedText)
    local = tr.localise_card(c, tr.check_card(c, sidecar_for(c), "nb"))
    assert isinstance(local.card.level_reason, cardlib.SourcedText) and local.card.level_reason.text.startswith("NB ")


# --- the merge of translator output -----


def translated(*pairs: tuple[str, str], slug: str = SLUG, lang: str = "nb") -> tr.TranslatedFile:
    return tr.TranslatedFile(slug=slug, lang=lang, items=[tr.TranslatedItem(item=i, text=t) for i, t in pairs])


def review(verdict="accept", findings=(), slug=SLUG) -> tr.TranslationReview:
    return tr.TranslationReview(slug=slug, lang="nb", verdict=verdict, findings=list(findings))


def finding(item, severity="must_fix") -> tr.TranslationFinding:
    return tr.TranslationFinding(item=item, severity=severity, problem="Fictional problem.")


def test_merge_takes_hash_and_sources_from_the_english_card_not_from_the_translator(card):
    merged = tr.merge(
        card, None, translated(("core_claim", "Fiktiv hovedpåstand."), ("name", "Fiktivt navn")), None, "nb"
    )
    item = merged.sidecar.items["core_claim"]
    assert item.source_hash == tr.text_hash(card.core_claim.text) and item.sources == card.core_claim.sources
    assert merged.sidecar.items["name"].sources is None
    assert merged.written == ["core_claim", "name"] and merged.left_out == {}


def test_merge_replaces_an_earlier_translation_and_keeps_the_others(card):
    first = tr.merge(card, None, translated(("core_claim", "Første."), ("name", "Navn")), None, "nb")
    second = tr.merge(card, first.sidecar, translated(("core_claim", "Andre.")), None, "nb")
    assert second.sidecar.items["core_claim"].text == "Andre." and second.sidecar.items["name"].text == "Navn"


def test_merge_leaves_out_an_item_whose_numbers_differ(card):
    merged = tr.merge(card, None, translated(("studies[pmid:00000001].finding", "Fiktiv studie, n=41.")), None, "nb")
    assert merged.written == [] and "numbers differ" in merged.left_out["studies[pmid:00000001].finding"][0]
    assert merged.sidecar.items == {}


def test_merge_leaves_out_an_item_the_english_card_does_not_have(card):
    merged = tr.merge(card, None, translated(("level", "5"), ("studies[pmid:1].finding", "x")), None, "nb")
    assert merged.written == [] and set(merged.left_out) == {"level", "studies[pmid:1].finding"}


def test_merge_leaves_out_an_item_listed_twice(card):
    merged = tr.merge(card, None, translated(("name", "En"), ("name", "To")), None, "nb")
    assert merged.written == ["name"] and "more than once" in merged.left_out["name"][0]


def test_merge_leaves_out_items_with_a_must_fix_finding_but_keeps_advisory_ones(card):
    rev = review("reject", [finding("core_claim"), finding("name", "advisory")])
    merged = tr.merge(
        card, None, translated(("core_claim", "Feil."), ("name", "Navn"), ("subgroups[0]", "Ok.")), rev, "nb"
    )
    assert merged.written == ["name", "subgroups[0]"]
    assert merged.left_out == {"core_claim": ["the reviewer has a must_fix finding on it"]}


def test_merge_leaves_out_everything_when_the_reviewer_rejects_the_whole_translation(card):
    merged = tr.merge(
        card, None, translated(("core_claim", "A."), ("name", "B.")), review("reject", [finding(None)]), "nb"
    )
    assert merged.written == [] and set(merged.left_out) == {"core_claim", "name"}


def test_merge_refuses_a_file_for_another_card_or_language(card):
    with pytest.raises(tr.TranslationError, match="not 'fictional-hypothesis'"):
        tr.merge(card, None, translated(("name", "x"), slug="other"), None, "nb")
    with pytest.raises(tr.TranslationError, match="language"):
        tr.merge(card, None, translated(("name", "x"), lang="sv"), None, "nb")
    with pytest.raises(tr.TranslationError, match="review is for"):
        tr.merge(card, None, translated(("name", "x")), review(slug="other"), "nb")


def test_a_merged_item_is_fresh_until_the_english_text_changes(card, tmp_path):
    merged = tr.merge(card, None, translated(("core_claim", "Fiktiv hovedpåstand.")), None, "nb")
    assert status(tr.check_card(card, merged.sidecar, "nb"), "core_claim") == "fresh"
    data = card_data()
    data["core_claim"]["text"] = "A changed fictional claim."
    assert status(tr.check_card(load_card_from(data, tmp_path), merged.sidecar, "nb"), "core_claim") == "stale"


def test_review_file_rules_match_the_english_pipeline():
    with pytest.raises(ValueError, match="at least one finding"):
        review("reject", [])
    with pytest.raises(ValueError, match="must_fix"):
        review("accept", [finding("name")])
    assert review("accept", [finding("name", "advisory")]).verdict == "accept"
    with pytest.raises(ValueError):
        tr.TranslationFinding(item="name", severity="maybe", problem="x")
    with pytest.raises(ValueError):
        tr.TranslationReview.model_validate(
            {"slug": SLUG, "lang": "nb", "verdict": "accept", "findings": [], "extra": 1}
        )


# --- the commands -----


class Project:
    def __init__(self, tmp_path: Path):
        self.cards = tmp_path / "cards"
        self.drafts = tmp_path / "drafts"
        self.translations = tmp_path / "translations"
        self.cards.mkdir()
        self.drafts.mkdir()
        self.card_path = self.drafts / f"{SLUG}.yaml"
        self.card_path.write_text(FIXTURE_CARD.read_text(encoding="utf-8"), encoding="utf-8")
        self.card = cardlib.load_card(self.card_path)

    @property
    def sidecar_path(self) -> Path:
        return self.translations / "nb" / f"{SLUG}.yaml"

    def put(self, side: tr.TFile) -> None:
        self.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        self.sidecar_path.write_text(
            tr.dump_sidecar(side, list(tr.english_items(self.card))), encoding="utf-8", newline="\n"
        )

    def run(self, *argv: str) -> int:
        return tr.main(
            [
                *argv,
                "--cards-dir",
                str(self.cards),
                "--drafts-dir",
                str(self.drafts),
                "--translations-dir",
                str(self.translations),
            ]
        )


@pytest.fixture
def project(tmp_path) -> Project:
    return Project(tmp_path)


def test_check_passes_when_there_are_no_translations(project, capsys):
    assert project.run("check") == 0
    assert "OK: 0 translation file(s)" in capsys.readouterr().out


def test_check_passes_a_complete_translation(project, capsys):
    project.put(sidecar_for(project.card))
    assert project.run("check") == 0
    assert "OK: 1 translation file(s) checked" in capsys.readouterr().out


def test_check_fails_on_a_changed_number_and_names_the_item(project, capsys):
    side = sidecar_for(project.card, **{"studies[pmid:00000001].finding": "NB n=41 pasienter og 40 kontroller."})
    project.put(side)
    assert project.run("check") == 1
    err = capsys.readouterr().err
    assert "studies[pmid:00000001].finding" in err and "numbers differ" in err and "FAILED" in err


def test_check_fails_on_changed_sources_a_wrong_pmid_and_an_extra_item(project, capsys):
    side = sidecar_for(project.card)
    side.items["core_claim"] = side.items["core_claim"].model_copy(update={"sources": ["pmid:00000002"]})
    side.items["subgroups[3]"] = side.items["subgroups[0]"]
    project.put(side)
    assert project.run("check") == 1
    err = capsys.readouterr().err
    assert "core_claim" in err and "sources" in err and "subgroups[3]" in err


def test_check_reports_a_stale_item_without_failing(project, capsys):
    side = sidecar_for(project.card)
    side.items["core_claim"] = side.items["core_claim"].model_copy(update={"source_hash": "c" * 64})
    project.put(side)
    assert project.run("check") == 0
    out = capsys.readouterr().out
    assert f"stale: nb: {SLUG}: core_claim" in out and "OK:" in out


def test_check_reports_how_many_items_are_missing(project, capsys):
    side = sidecar_for(project.card)
    del side.items["subgroups[0]"]
    project.put(side)
    assert project.run("check") == 0
    assert "missing: nb: fictional-hypothesis: 1 of 13 item(s) not translated yet" in capsys.readouterr().out


def test_check_fails_for_a_translation_of_a_card_that_does_not_exist(project, capsys):
    project.put(sidecar_for(project.card))
    project.card_path.unlink()
    assert project.run("check") == 1
    assert "there is no English card" in capsys.readouterr().err


def test_check_fails_for_an_unreadable_file_and_for_a_slug_that_is_not_the_file_name(project, capsys):
    project.sidecar_path.parent.mkdir(parents=True)
    project.sidecar_path.write_text("slug: other-name\nitems: {}\n", encoding="utf-8")
    assert project.run("check") == 1
    assert "must equal the file name" in capsys.readouterr().err


def test_check_compares_against_the_draft_when_a_draft_replaces_the_card(project, capsys):
    published = cardlib.load_card(project.card_path)
    (project.cards / f"{SLUG}.yaml").write_text(FIXTURE_CARD.read_text(encoding="utf-8"), encoding="utf-8")
    project.put(sidecar_for(published))
    data = card_data()
    data["core_claim"]["text"] = "The draft says something different."
    project.card_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert project.run("check") == 0
    assert "stale: nb: fictional-hypothesis: core_claim" in capsys.readouterr().out


def put_overlay(tmp_path: Path, data: dict) -> Path:
    overlay = tmp_path / "overlay"
    overlay.mkdir(exist_ok=True)
    (overlay / f"{data['slug']}.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return overlay


def test_check_with_overlay_compares_against_the_overlay_card_not_the_draft(project, tmp_path, capsys):
    data = card_data()
    data["subgroups"].append(
        {"text": "A new fictional subgroup added by the weekly run.", "sources": ["pmid:00000001"]}
    )
    overlay = put_overlay(tmp_path, data)
    project.put(sidecar_for(cardlib.load_card(overlay / f"{SLUG}.yaml")))  # translates the added item too
    assert project.run("check") == 1  # today's behaviour: the draft has no such item
    assert "subgroups[" in capsys.readouterr().err
    assert project.run("check", "--overlay", str(overlay)) == 0
    assert "OK: 1 translation file(s) checked" in capsys.readouterr().out


def test_check_with_overlay_checks_a_slug_that_exists_only_in_the_overlay(project, tmp_path, capsys):
    project.put(sidecar_for(project.card))
    project.card_path.unlink()
    assert project.run("check") == 1
    capsys.readouterr()
    overlay = put_overlay(tmp_path, card_data())
    assert project.run("check", "--overlay", str(overlay)) == 0


def test_check_with_an_overlay_that_is_not_a_folder_is_an_error(project, tmp_path, capsys):
    assert project.run("check", "--overlay", str(tmp_path / "nope")) == 1
    assert "overlay" in capsys.readouterr().err


def test_apply_writes_a_sidecar_with_hash_and_sources_and_the_check_passes(project, tmp_path, capsys):
    out = tmp_path / "translated.json"
    out.write_text(
        json.dumps({"slug": SLUG, "lang": "nb", "items": [{"item": "core_claim", "text": "Fiktiv hovedpåstand."}]}),
        encoding="utf-8",
    )
    assert project.run("apply", SLUG, str(out)) == 0
    data = yaml.safe_load(project.sidecar_path.read_text(encoding="utf-8"))
    assert data["items"]["core_claim"]["source_hash"] == tr.text_hash(project.card.core_claim.text)
    assert data["items"]["core_claim"]["sources"] == ["pmid:00000001"]
    assert "12 item(s) still fall back to English" in capsys.readouterr().out
    assert project.run("check") == 0


def test_apply_with_a_review_leaves_out_the_item_the_reviewer_rejected(project, tmp_path, capsys):
    out = tmp_path / "translated.json"
    out.write_text(
        json.dumps(
            {
                "slug": SLUG,
                "lang": "nb",
                "items": [{"item": "core_claim", "text": "Feil."}, {"item": "name", "text": "Fiktivt navn"}],
            }
        ),
        encoding="utf-8",
    )
    rev = tmp_path / "review.json"
    rev.write_text(
        json.dumps(
            {
                "slug": SLUG,
                "lang": "nb",
                "verdict": "reject",
                "findings": [{"item": "core_claim", "severity": "must_fix", "problem": "Says more than the English."}],
            }
        ),
        encoding="utf-8",
    )
    assert project.run("apply", SLUG, str(out), "--review", str(rev)) == 0
    items = yaml.safe_load(project.sidecar_path.read_text(encoding="utf-8"))["items"]
    assert list(items) == ["name"]
    assert "left out: core_claim: the reviewer has a must_fix finding on it" in capsys.readouterr().out


def test_apply_reports_malformed_agent_files_and_unknown_cards(project, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"slug": SLUG, "lang": "nb", "items": [{"item": "name"}]}), encoding="utf-8")
    assert project.run("apply", SLUG, str(bad)) == 1
    assert "is malformed" in capsys.readouterr().err
    assert project.run("apply", SLUG, str(tmp_path / "missing.json")) == 1
    assert "does not exist" in capsys.readouterr().err
    assert project.run("apply", "no-such-card", str(bad)) == 1
    assert "no card or draft" in capsys.readouterr().err
    bad.write_text("not json", encoding="utf-8")
    assert project.run("apply", SLUG, str(bad)) == 1
    assert "not readable JSON" in capsys.readouterr().err


def test_apply_translates_against_the_card_file_it_is_given(project, tmp_path):
    data = card_data()
    data["core_claim"]["text"] = "A newer fictional claim."
    newer = tmp_path / "final" / f"{SLUG}.yaml"
    newer.parent.mkdir()
    newer.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    out = tmp_path / "translated.json"
    out.write_text(
        json.dumps({"slug": SLUG, "lang": "nb", "items": [{"item": "core_claim", "text": "Nyere fiktiv påstand."}]}),
        encoding="utf-8",
    )
    assert project.run("apply", SLUG, str(out), "--card", str(newer)) == 0
    items = yaml.safe_load(project.sidecar_path.read_text(encoding="utf-8"))["items"]
    assert items["core_claim"]["source_hash"] == tr.text_hash("A newer fictional claim.")


# --- the agents and the command describe what the code validates -----

REPO = Path(__file__).resolve().parents[1]


def json_blocks(markdown: str) -> list[object]:

    return [json.loads(b.replace("<slug>", "example-card")) for b in re.findall(r"```json\n(.*?)```", markdown, re.S)]


def front_matter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---")[1])


def test_the_translator_agent_is_a_sonnet_agent_that_may_only_read_and_write():
    meta = front_matter(REPO / ".claude" / "agents" / "card-translator.md")
    assert meta["name"] == "card-translator" and meta["model"] == "sonnet"
    assert [t.strip() for t in meta["tools"].split(",")] == ["Read", "Write"]


def test_the_translator_agent_file_shows_the_shape_the_code_validates():
    text = (REPO / ".claude" / "agents" / "card-translator.md").read_text(encoding="utf-8")
    blocks = json_blocks(text)
    assert len(blocks) == 1
    parsed = tr.TranslatedFile.model_validate(blocks[0])
    assert parsed.lang == "nb" and [i.item for i in parsed.items][:2] == ["core_claim", "level_reason[0]"]
    assert "studies[pmid:12345678].finding" in [i.item for i in parsed.items]
    with pytest.raises(ValueError):
        tr.TranslatedFile.model_validate({**blocks[0], "reasoning": "x"})  # the file has no room for commentary


def test_the_reviewer_translation_mode_shows_the_shape_the_code_validates():
    text = (REPO / ".claude" / "agents" / "card-reviewer.md").read_text(encoding="utf-8")
    section = text.split("## Translation mode")[1]
    blocks = json_blocks(section)
    assert len(blocks) == 1
    # the example in the file is an accept with a must_fix finding, which the code refuses; the shape itself is valid
    shape = {**blocks[0], "verdict": "reject"}
    parsed = tr.TranslationReview.model_validate(shape)
    assert parsed.findings[0].severity == "must_fix" and parsed.findings[0].item == "core_claim"
    with pytest.raises(ValueError, match="must_fix"):
        tr.TranslationReview.model_validate(blocks[0])


def test_the_weekly_command_describes_the_translation_step_with_the_real_subcommands():
    text = (REPO / ".claude" / "commands" / "ukentlig.md").read_text(encoding="utf-8")
    for needle in (
        "translation-plan",
        "card-translator",
        "translations apply",
        "translations check",
        "--review",
        "translation-review",
        "RUN/final/<slug>.yaml",
        "Never a third attempt",
        "must not see the translator's reasoning",
    ):
        assert needle in text, needle
    assert text.index("6. **Translate.**") < text.index("7. **Report.**") < text.index("8. **Pull request.**")


def test_the_translation_doc_lists_every_locator_kind_the_code_produces(card):
    doc = (REPO / "docs" / "translation.md").read_text(encoding="utf-8")
    kinds = {re.sub(r"\[[^\]]*\]", "[i]", loc.replace("pmid:00000001", "<id>")) for loc in tr.english_items(card)}
    assert "studies[<id>].finding" in kinds or any(k.startswith("studies") for k in kinds)
    for name in (
        "name",
        "core_claim",
        "level_reason[i]",
        "contested_reason[i]",
        "badge_reasons.diagnostic_marker[i]",
        "badge_reasons.explains_pem[i]",
        "subgroups[i]",
        "early_signals[i]",
        "studies[<id>].finding",
    ):
        assert f"`{name}`" in doc, name
    for loc in tr.english_items(card):
        kind = re.sub(r"\[[^\]]*\]", "[i]", loc)
        kind = re.sub(r"\[i\]\.finding$", "[<id>].finding", kind) if loc.startswith("studies") else kind
        assert kind in {
            "name",
            "core_claim",
            "level_reason[i]",
            "contested_reason[i]",
            "badge_reasons.diagnostic_marker[i]",
            "badge_reasons.explains_pem[i]",
            "subgroups[i]",
            "early_signals[i]",
            "studies[<id>].finding",
        }, loc


# --- links (causal map) -----


def card_with_links(tmp_path) -> cardlib.Card:
    data = card_data()
    data["links"] = [
        {"to": "symptom:fatigue", "support": "proposed", "text": "A fictional link.", "sources": ["pmid:00000001"]},
        {
            "to": "other-fictional-card",
            "support": "associated",
            "text": "A fictional study of 40 patients found them related.",
            "sources": ["pmid:00000001", "pmid:00000002"],
        },
    ]
    return load_card_from(data, tmp_path)


def test_links_are_items_in_card_order_after_the_early_signals(tmp_path):
    items = tr.english_items(card_with_links(tmp_path))
    locators = list(items)
    assert locators[locators.index("early_signals[0]") + 1 :][:2] == ["links[0]", "links[1]"]
    assert items["links[1]"].text == "A fictional study of 40 patients found them related."
    assert items["links[1]"].sources == ["pmid:00000001", "pmid:00000002"]


def test_a_link_translation_whose_numbers_differ_is_reported_as_invalid(tmp_path):
    card = card_with_links(tmp_path)
    problems = invalid(card, "links[1]", text="NB En fiktiv studie av 400 pasienter fant sammenheng.")
    assert any("numbers differ" in p for p in problems)


def test_a_link_translation_with_other_sources_is_invalid(tmp_path):
    assert any("sources" in p for p in invalid(card_with_links(tmp_path), "links[1]", sources=["pmid:00000001"]))


def test_a_fresh_link_translation_is_used_and_a_missing_one_falls_back(tmp_path):
    card = card_with_links(tmp_path)
    side = sidecar_for(card, **{"links[0]": "En fiktiv lenke."})
    del side.items["links[1]"]
    local = tr.localise_card(card, tr.check_card(card, side, "nb"))
    assert local.card.links[0].text == "En fiktiv lenke."
    assert local.card.links[0].to == "symptom:fatigue" and local.card.links[0].support == "proposed"
    assert local.card.links[1].text == card.links[1].text
    assert id(card.links[1]) in local.fallback and id(card.links[0]) not in local.fallback


def test_a_stale_link_translation_is_stale_when_the_english_text_changes(tmp_path):
    card = card_with_links(tmp_path)
    side = sidecar_for(card)
    changed = card_data()
    changed["links"] = [card.links[0].model_dump(), {**card.links[1].model_dump(), "text": "A changed link."}]
    result = tr.check_card(load_card_from(changed, tmp_path), side, "nb")
    assert status(result, "links[1]") == "stale" and status(result, "links[0]") == "fresh"
