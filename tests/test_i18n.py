"""Tests for the fixed-text string files (content/i18n) and the Norwegian banned words. No network, no LLM."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from markupsafe import Markup

from me_atlas import cards as cardlib
from me_atlas import i18n

REPO_ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = REPO_ROOT / "content" / "i18n"
EN = i18n.load_strings(I18N_DIR / "en.yaml")
NB = i18n.load_strings(I18N_DIR / "nb.yaml")


def write(tmp_path: Path, text: str, name: str = "xx.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- the real files -----


def test_the_norwegian_file_has_exactly_the_english_keys_placeholders_and_glossary_terms():
    assert i18n.compare(EN, NB, "nb") == []


def test_every_language_file_names_its_own_language():
    assert EN[i18n.LANGUAGE_NAME_KEY] == "English" and NB[i18n.LANGUAGE_NAME_KEY] == "Norsk"


def test_no_banned_word_in_any_string_in_either_language():
    for name, strings in (("en", EN), ("nb", NB)):
        for key, text in strings.items():
            plain = re.sub(r"<[^>]+>", " ", text)
            for pattern in (cardlib._BANNED_RE, cardlib._BANNED_NB_RE):
                assert not pattern.search(plain), (name, key)


def test_every_language_has_six_rung_names_and_six_meanings():
    expected = {f"rung.{i}.{part}" for i in range(6) for part in ("name", "meaning")}
    for strings in (EN, NB):
        assert {k for k in strings if k.startswith("rung.")} == expected


# --- loading -----


def test_a_value_that_is_not_a_string_is_rejected_and_the_key_is_named(tmp_path):
    path = write(tmp_path, "answer.yes: yes\nother: 'fine'\n")
    with pytest.raises(i18n.I18nError) as exc:
        i18n.load_strings(path)
    assert "key 'answer.yes' must be a string, not bool (quote it)" in exc.value.problems[0]


def test_a_file_that_is_not_a_mapping_or_not_yaml_is_rejected(tmp_path):
    with pytest.raises(i18n.I18nError, match="mapping"):
        i18n.load_strings(write(tmp_path, "- a\n- b\n"))
    with pytest.raises(i18n.I18nError, match="invalid YAML"):
        i18n.load_strings(write(tmp_path, "a: [unclosed\n"))
    with pytest.raises(i18n.I18nError, match="cannot read"):
        i18n.load_strings(tmp_path / "missing.yaml")


# --- comparing a language with the reference -----


REFERENCE = {"a": "Plain", "b": "Level {level} of {total}", "c": "Explains [[PEM]]: {answer}"}


def test_a_missing_key_is_named():
    problems = i18n.compare(REFERENCE, {"a": "Enkel", "b": "Nivå {level} av {total}"}, "nb")
    assert problems == ["nb.yaml: missing key 'c'"]


def test_an_unknown_key_is_named():
    other = {**REFERENCE, "z": "Extra"}
    assert i18n.compare(REFERENCE, other, "nb") == ["nb.yaml: unknown key 'z' (not in the reference language)"]


def test_a_changed_placeholder_is_named():
    other = {**REFERENCE, "b": "Nivå {level} av {antall}"}
    problems = i18n.compare(REFERENCE, other, "nb")
    assert len(problems) == 1 and "key 'b'" in problems[0] and "antall" in problems[0]


def test_a_changed_glossary_term_is_named():
    other = {**REFERENCE, "c": "Forklarer [[post-exertional malaise|PEM]]: {answer}"}
    problems = i18n.compare(REFERENCE, other, "nb")
    assert len(problems) == 1 and "key 'c'" in problems[0] and "glossary terms" in problems[0]


def test_the_shown_text_of_a_glossary_term_may_differ():
    other = {**REFERENCE, "c": "Forklarer [[PEM|PEM-en]]: {answer}"}
    assert i18n.compare(REFERENCE, other, "nb") == []


def test_identical_files_have_no_problems():
    assert i18n.compare(REFERENCE, dict(REFERENCE), "nb") == []


# --- rendering -----


def term(key: str, shown: str | None) -> Markup:
    return Markup("<b>{}</b>").format(shown or key)


def test_render_escapes_values_but_not_the_string_itself():
    out = i18n.render({"k": "<em>{x}</em>"}, "k", term, {"x": "1 < 2 & <b>"})
    assert out == "<em>1 &lt; 2 &amp; &lt;b&gt;</em>"


def test_render_passes_markup_values_through():
    assert i18n.render({"k": "[{x}]"}, "k", term, {"x": Markup("<i>y</i>")}) == "[<i>y</i>]"


def test_render_marks_glossary_terms_with_and_without_shown_text():
    strings = {"k": "A [[PEM]] and [[long COVID|langvarig covid]]."}
    assert i18n.render(strings, "k", term, {}) == "A <b>PEM</b> and <b>langvarig covid</b>."


def test_render_names_a_missing_value_and_a_missing_key():
    with pytest.raises(i18n.I18nError, match=r"key 'k' needs a value for \{x\}"):
        i18n.render({"k": "{x}"}, "k", term, {})
    with pytest.raises(i18n.I18nError, match="missing key 'nope'"):
        i18n.render({"k": "x"}, "nope", term, {})


def test_a_single_bracket_is_plain_text():
    assert i18n.render({"k": "cited as [{n}]"}, "k", term, {"n": 3}) == "cited as [3]"


# --- the Norwegian banned words -----


@pytest.mark.parametrize(
    "text",
    [
        "et lovende funn",
        "Gjennombrudd i forskningen",
        "gjennombruddet",
        "en kur",
        "kuren",
        "ble kurert",
        "håp",
        "håpet",
        "håper",
        "håpefull",
        "bevist",
        "bevist sammenheng",
    ],
)
def test_norwegian_banned_words_are_found(text):
    assert cardlib._BANNED_NB_RE.search(text)


@pytest.mark.parametrize(
    "text",
    ["bevisst valg", "påvist", "kurve", "kursiv", "kurs", "håndtere", "bevisstløs", "gjennomgang", "lovet"],
)
def test_norwegian_words_that_only_look_like_banned_ones_are_not_found(text):
    assert not cardlib._BANNED_NB_RE.search(text)


# --- sorting -----


def test_norwegian_sorts_ae_oe_aa_after_z():
    words = ["åre", "ære", "zebra", "øre", "apple"]
    assert sorted(words, key=lambda w: i18n.sort_key("nb", w)) == ["apple", "zebra", "ære", "øre", "åre"]
    assert sorted(words, key=lambda w: i18n.sort_key("en", w)) != sorted(words, key=lambda w: i18n.sort_key("nb", w))
