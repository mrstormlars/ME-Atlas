"""Fixed site text per language.

``content/i18n/<lang>.yaml`` is a flat mapping of key to string. ``en.yaml`` is the reference: every other language
must have exactly the same keys, the same ``{placeholders}`` and the same ``[[glossary]]`` terms in each string, or
the build fails and names the key. See ``docs/translation.md``.

A string is trusted HTML (it lives in the repository, like a template). Two kinds of markup are expanded when it is
rendered:

- ``{name}``: a value given by the template, HTML-escaped.
- ``[[Term]]`` or ``[[Term|shown text]]``: a glossary term, marked like any other (the first use on a page gets the
  dotted underline). ``Term`` is always the English term; the explanation comes from the page's language.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path

import yaml
from markupsafe import Markup, escape

DEFAULT_LANGUAGE = "en"
LANGUAGE_NAME_KEY = "lang.name"  # each file names its own language ("English", "Norsk")

_TOKEN = re.compile(r"\[\[(.+?)\]\]|\{(\w+)\}")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_GLOSS = re.compile(r"\[\[(.+?)\]\]")


class I18nError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def load_strings(path: Path) -> dict[str, str]:
    """Read one string file. Every value must be a string (an unquoted yes or no would be read as a boolean)."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise I18nError([f"{path}: cannot read file: {exc}"]) from exc
    except yaml.YAMLError as exc:
        raise I18nError([f"{path}: invalid YAML: {str(exc).splitlines()[0] if str(exc) else exc}"]) from exc
    if not isinstance(raw, dict):
        raise I18nError([f"{path}: top level must be a mapping of key to string"])
    problems = [
        f"{path}: key '{k}' must be a string, not {type(v).__name__} (quote it)"
        for k, v in raw.items()
        if not isinstance(v, str)
    ]
    problems += [f"{path}: key {k!r} must be a string" for k in raw if not isinstance(k, str)]
    if problems:
        raise I18nError(problems)
    return dict(raw)


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def glossary_keys(text: str) -> set[str]:
    return {m.partition("|")[0] for m in _GLOSS.findall(text)}


def compare(reference: Mapping[str, str], other: Mapping[str, str], lang: str, file: str | None = None) -> list[str]:
    """Problems of a language file against the reference: missing keys (named), unknown keys, and strings whose
    placeholders or glossary terms differ."""
    where = file or f"{lang}.yaml"
    problems = [f"{where}: missing key '{k}'" for k in reference if k not in other]
    problems += [f"{where}: unknown key '{k}' (not in the reference language)" for k in other if k not in reference]
    for key in reference:
        if key not in other:
            continue
        if placeholders(reference[key]) != placeholders(other[key]):
            problems.append(
                f"{where}: key '{key}' uses placeholders {sorted(placeholders(other[key]))}, "
                f"the reference uses {sorted(placeholders(reference[key]))}"
            )
        if glossary_keys(reference[key]) != glossary_keys(other[key]):
            problems.append(
                f"{where}: key '{key}' marks glossary terms {sorted(glossary_keys(other[key]))}, "
                f"the reference marks {sorted(glossary_keys(reference[key]))}"
            )
    return problems


def render(
    strings: Mapping[str, str],
    key: str,
    term: Callable[[str, str | None], Markup],
    values: Mapping[str, object],
) -> Markup:
    """The string as HTML: values escaped and glossary terms marked."""
    try:
        text = strings[key]
    except KeyError as exc:
        raise I18nError([f"missing key '{key}'"]) from exc
    out: list[Markup | str] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        out.append(Markup(text[pos : m.start()]))
        if m.group(1) is not None:
            name, _, shown = m.group(1).partition("|")
            out.append(term(name, shown or None))
        else:
            name = m.group(2)
            if name not in values:
                raise I18nError([f"key '{key}' needs a value for {{{name}}}"])
            out.append(escape(values[name]))
        pos = m.end()
    out.append(Markup(text[pos:]))
    return Markup("").join(out)


# Alphabetical order of a language, for sorting the glossary page. Norwegian puts æ, ø, å after z.
_AFTER_Z = {"nb": {"æ": "{", "ø": "|", "å": "}"}}


def sort_key(lang: str, text: str) -> str:
    folded = text.casefold()
    table = _AFTER_Z.get(lang)
    return folded.translate(str.maketrans(table)) if table else folded
