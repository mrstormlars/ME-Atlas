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
