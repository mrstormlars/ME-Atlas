"""Tests for the glossary model and validation. All inputs are fictional; no network, no LLM."""

from pathlib import Path

import pytest
import yaml

from me_atlas import glossary
from me_atlas.glossary import GlossaryError

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_GLOSSARY = REPO_ROOT / "content" / "glossary.yaml"


def entry(term="widget", explanation="A fictional thing.", aliases=None):
    e = {"term": term, "explanation": explanation}
    if aliases is not None:
        e["aliases"] = aliases
    return e


def problems(raw):
    return glossary.validate_entries(raw)[1]


def write(tmp_path, raw) -> Path:
    path = tmp_path / "glossary.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_valid_entries_have_no_problems():
    entries, found = glossary.validate_entries([entry("widget", aliases=["widgets"]), entry("gadget")])
    assert found == []
    assert [e.term for e in entries] == ["widget", "gadget"]


def test_duplicate_term_fails():
    found = problems([entry("widget"), entry("widget", "Another fictional thing.")])
    assert any("duplicate term 'widget'" in p for p in found)


def test_duplicate_alias_fails():
    found = problems([entry("widget", aliases=["thing"]), entry("gadget", aliases=["thing"])])
    assert any("duplicate alias 'thing'" in p for p in found)


def test_alias_equal_to_another_term_fails():
    found = problems([entry("widget"), entry("gadget", aliases=["widget"])])
    assert any("duplicate alias 'widget'" in p for p in found)


def test_alias_repeated_inside_one_entry_fails():
    found = problems([entry("widget", aliases=["thing", "thing"])])
    assert any("duplicate alias 'thing'" in p for p in found)


@pytest.mark.parametrize("explanation", ["", "   "])
def test_empty_explanation_fails(explanation):
    assert problems([entry(explanation=explanation)])


def test_missing_explanation_fails():
    assert problems([{"term": "widget"}])


def test_explanation_over_200_characters_fails_and_exactly_200_passes():
    assert problems([entry(explanation="x" * 200)]) == []
    found = problems([entry(explanation="x" * 201)])
    assert len(found) == 1 and "201 characters" in found[0]


@pytest.mark.parametrize("word", ["cure", "Promising", "breakthroughs", "hoped", "hopeful", "proven"])
def test_banned_word_in_explanation_fails(word):
    found = problems([entry(explanation=f"A fictional thing that is {word} here.")])
    assert any("banned word" in p and "explanation" in p for p in found)


def test_banned_word_in_term_or_alias_fails():
    assert any("banned word" in p for p in problems([entry("cure")]))
    assert any("banned word" in p for p in problems([entry("widget", aliases=["hope"])]))


def test_banned_word_inside_a_longer_word_is_not_banned():
    assert problems([entry(explanation="A fictional procure and shopeless thing.")]) == []


def test_unknown_field_fails():
    assert problems([{**entry(), "colour": "red"}])


def test_top_level_must_be_a_list():
    assert problems({"term": "widget"})


def test_empty_file_is_an_empty_glossary(tmp_path):
    path = tmp_path / "glossary.yaml"
    path.write_text("", encoding="utf-8")
    assert glossary.load_glossary(path).entries == ()


def test_load_glossary_raises_with_every_problem(tmp_path):
    path = write(tmp_path, [entry("widget"), entry("widget"), entry("gadget", explanation="x" * 300)])
    with pytest.raises(GlossaryError) as exc:
        glossary.load_glossary(path)
    assert len(exc.value.problems) == 2


def test_load_glossary_reports_missing_file(tmp_path):
    with pytest.raises(GlossaryError):
        glossary.load_glossary(tmp_path / "missing.yaml")


def test_slugs_are_unique_even_when_terms_collapse_to_the_same_text():
    g = glossary.Glossary(
        (
            glossary.GlossaryEntry(term="N-K cell", explanation="a"),
            glossary.GlossaryEntry(term="N K cell", explanation="b"),
        )
    )
    slugs = g.slugs()
    assert len(set(slugs.values())) == 2


def test_real_glossary_is_valid():
    g = glossary.load_glossary(REAL_GLOSSARY)
    assert len(g.entries) > 20
    assert all(len(e.explanation) <= glossary.MAX_EXPLANATION for e in g.entries)


# --- the Norwegian glossary (content/glossary.nb.yaml): fictional fixtures only -----


def nb_entry(en="widget", term="dings", explanation="Et oppdiktet ord.", aliases=None):
    e = {"en": en, "term": term, "explanation": explanation}
    if aliases is not None:
        e["aliases"] = aliases
    return e


def nb_problems(raw):
    return glossary.validate_entries(
        raw, model=glossary.LocalEntry, banned_in=(glossary._BANNED_RE, glossary._BANNED_NB_RE)
    )[1]


def base_glossary() -> glossary.Glossary:
    return glossary.Glossary(
        (
            glossary.GlossaryEntry(term="widget", aliases=["widgets"], explanation="A fictional thing."),
            glossary.GlossaryEntry(term="gadget", explanation="Another fictional thing."),
        )
    )


def write_nb(tmp_path, raw) -> Path:
    path = tmp_path / "glossary.nb.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def test_a_valid_norwegian_entry_has_no_problems():
    assert nb_problems([nb_entry(aliases=["dingser"])]) == []


@pytest.mark.parametrize("word", ["lovende", "gjennombrudd", "kur", "håp", "bevist", "kurert", "håpefull"])
def test_norwegian_banned_word_in_a_norwegian_explanation_fails(word):
    found = nb_problems([nb_entry(explanation=f"Et {word} oppdiktet ord.")])
    assert any(f"banned word '{word}'" in p and "explanation" in p for p in found)


def test_norwegian_banned_word_in_a_norwegian_term_or_alias_fails():
    assert any("banned word 'kur'" in p and "term" in p for p in nb_problems([nb_entry(term="kur")]))
    assert any("banned word 'håp'" in p and "alias" in p for p in nb_problems([nb_entry(aliases=["håp"])]))


def test_english_banned_word_in_a_norwegian_entry_fails_too():
    assert any("banned word 'cure'" in p for p in nb_problems([nb_entry(explanation="A fictional cure.")]))


def test_norwegian_banned_words_are_not_checked_in_the_english_glossary():
    assert problems([entry(explanation="Et oppdiktet håp.")]) == []


def test_a_norwegian_entry_needs_the_english_term_it_translates():
    assert any("en" in p for p in nb_problems([{"term": "dings", "explanation": "Et oppdiktet ord."}]))


def test_norwegian_entries_follow_the_same_length_and_duplicate_rules():
    assert any("201 characters" in p for p in nb_problems([nb_entry(explanation="x" * 201)]))
    assert nb_problems([nb_entry(explanation="x" * 200)]) == []
    assert any("duplicate term 'dings'" in p for p in nb_problems([nb_entry(), nb_entry(en="gadget")]))
    assert any(
        "duplicate alias" in p
        for p in nb_problems([nb_entry(aliases=["a"]), nb_entry(en="gadget", term="b", aliases=["a"])])
    )


def test_a_norwegian_entry_with_an_unknown_field_fails():
    assert nb_problems([{**nb_entry(), "extra": 1}])


def test_loading_a_norwegian_glossary_checks_the_english_term_exists_and_is_used_once(tmp_path):
    base = base_glossary()
    ok = glossary.load_local_glossary(write_nb(tmp_path, [nb_entry(), nb_entry(en="gadget", term="dippeditt")]), base)
    assert [e.en for e in ok] == ["widget", "gadget"]
    with pytest.raises(GlossaryError, match="'en' is 'nothing', which is not a term of the English glossary"):
        glossary.load_local_glossary(write_nb(tmp_path, [nb_entry(en="nothing")]), base)
    with pytest.raises(GlossaryError, match="translated more than once"):
        glossary.load_local_glossary(write_nb(tmp_path, [nb_entry(), nb_entry(term="annet")]), base)
    with pytest.raises(GlossaryError, match="banned word 'håp'"):
        glossary.load_local_glossary(write_nb(tmp_path, [nb_entry(explanation="Et håp.")]), base)


def test_an_alias_of_the_english_glossary_is_not_a_valid_english_key(tmp_path):
    with pytest.raises(GlossaryError, match="not a term of the English glossary"):
        glossary.load_local_glossary(write_nb(tmp_path, [nb_entry(en="widgets")]), base_glossary())


def test_localise_uses_the_norwegian_entry_where_there_is_one_and_english_elsewhere():
    base = base_glossary()
    local = [glossary.LocalEntry(en="widget", term="dings", aliases=["dingser"], explanation="Et oppdiktet ord.")]
    merged = glossary.localise(base, local)
    assert [e.term for e in merged.glossary.entries] == ["dings", "gadget"]
    assert merged.untranslated == frozenset({"gadget"}) and not merged.none_translated
    assert [e.key for e in merged.glossary.entries] == ["widget", "gadget"]


def test_localised_marking_finds_norwegian_words_and_still_finds_english_ones():
    local = [glossary.LocalEntry(en="widget", term="dings", aliases=["dingser"], explanation="Et oppdiktet ord.")]
    merged = glossary.localise(base_glossary(), local).glossary
    by_surface = merged.by_surface()
    assert by_surface["dingser"].explanation == "Et oppdiktet ord."
    assert by_surface["widgets"].explanation == "Et oppdiktet ord."  # English text left on a Norwegian page
    assert by_surface["gadget"].explanation == "Another fictional thing."


def test_a_template_names_a_term_by_its_english_spelling_in_every_language():
    local = [glossary.LocalEntry(en="widget", term="dings", explanation="Et oppdiktet ord.")]
    merged = glossary.localise(base_glossary(), local).glossary
    assert merged.lookup()["widget"].term == "dings" and merged.lookup()["widgets"].term == "dings"
    assert base_glossary().lookup()["widget"].term == "widget"


def test_slugs_follow_the_english_term_so_anchors_are_the_same_in_every_language():
    local = [glossary.LocalEntry(en="widget", term="ørret", explanation="Et oppdiktet ord.")]
    assert glossary.localise(base_glossary(), local).glossary.slugs() == {"widget": "widget", "gadget": "gadget"}


def test_no_translated_entry_at_all_is_reported_as_such():
    assert glossary.localise(base_glossary(), []).none_translated
