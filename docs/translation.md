# Translations

How the site is published in Norwegian (bokmål) next to English, and how a translation is kept honest. Plan and design decisions: `docs/plan-norwegian-translation.md`. Ruling: `docs/pm/DECISIONS.md`, 2026-11-02. Code: `src/me_atlas/i18n.py`, `translations.py`, `glossary.py`, `site.py`, `pipeline.py` (`translation-plan`).

If this page and the code disagree, the code is right and this page is a bug.

## The principle

English is authoritative. A translated finding that says something different from the source is an evidence error, so a translation is checked by code and by a reviewer, and whatever is not translated, is out of date or fails a check shows the English text with a short note: never stale or unchecked Norwegian. Every Norwegian page says it is a translation of the English page and links to it. Levels, badges, the contested mark, roles, numbers, ids, study titles, case-definition quotes, group and author names always come from the English card; they cannot be translated because they are not in a translation file.

## What is where

| Path | Content |
| --- | --- |
| `content/i18n/en.yaml`, `nb.yaml` | All fixed text of the templates, one key per string. `en.yaml` is the reference. |
| `content/glossary.yaml` | The English glossary (reference). |
| `content/glossary.nb.yaml` | Norwegian glossary, keyed by the English term. Optional: a term with no entry falls back to the English entry. |
| `content/methods/en.html`, `nb.html` | The methods page body of each language, a Jinja fragment. `nb.html` is optional: without it the Norwegian methods page is the English text with a note. |
| `translations/nb/<slug>.yaml` | The Norwegian text of one card, item by item. Optional per card. |
| `build/` and `build/nb/` | The built site: English at the top, Norwegian in `nb/`. Both use `build/static/`. |

## String files

`content/i18n/<lang>.yaml` is a flat mapping of key to string. Every string is single-quoted (an unquoted `yes` would be read as a boolean; the loader rejects a value that is not a string and names the key). A string is trusted HTML. Two kinds of markup are expanded when a page is rendered:

- `{name}`: a value the template supplies, escaped. `{lroot}` (the way back to the root of this language's tree), `{root}` (the way back to the root of the build) and `{built}` are always available.
- `[[Term]]` or `[[Term|shown text]]`: a glossary term, marked like any other (dotted underline on the first use on the page). `Term` is always the English term; the explanation comes from the page's language. `[[PEM]]` in the Norwegian file shows the Norwegian term of PEM.

**The build fails and names the key** when a language file lacks a key the reference has, has a key the reference lacks, uses different `{placeholders}` or marks different glossary terms, holds a banned word (English or Norwegian) or a value that is not a string, or marks a term the English glossary does not have. The first line of each file, `lang.name`, is the language's own name for the selector ("English", "Norsk").

The six rung names and meanings (`rung.N.name`, `rung.N.meaning`) must keep the meaning of the evidence ladder in `docs/ME-Atlas-functional-spec.md` section 3. A test compares the English strings with the spec word for word; the Norwegian ones are translations and are read by the founder with the rest.

## Glossary in Norwegian

`content/glossary.nb.yaml` lists entries like the English file, plus `en`, the English term the entry translates:

```yaml
- en: PEM
  term: PEM
  aliases: [post-eksertusjonell uvelhet]
  explanation: …
```

Same rules as the English file (explanation at most 200 characters, terms and aliases unique) with the banned words of both languages (see below). `en` must be a term of the English glossary (not an alias) and used once. Norwegian text is marked with the Norwegian terms and aliases (whole word, case-sensitive, longest match wins, first use per page). English text left on a Norwegian page (an untranslated item) is still marked with its English spellings, and shows the Norwegian explanation when there is one. Anchors (`#use-pem`, `#term-pem`) follow the English term, so they are the same in both languages. The glossary page is sorted in Norwegian order (æ, ø, å after z). A term with no Norwegian entry shows the English entry and the note "Ikke oversatt ennå."; with no Norwegian glossary at all the page says so once.

## Banned words

The English list is unchanged: promising, breakthrough, cure, hope, proven (and plain forms). The Norwegian equivalents are lovende, gjennombrudd, kur, håp, bevist and their forms (kuren, kurert, håpet, håpefull, gjennombruddet, …). "Bevisst" (conscious) and "påvist" (detected) are not banned. They are checked in the Norwegian glossary, in the string files, in translated `core_claim` and `early_signals` text (the same texts rule V10 covers in English) and, in tests, on every built page outside study titles.

## Card translations

`translations/nb/<slug>.yaml`:

```yaml
slug: fictional-hypothesis
items:
  name:
    text: …
    source_hash: <sha256 of the English name>
  core_claim:
    text: …
    sources: [pmid:00000001]
    source_hash: <sha256 of the English text>
  level_reason[0]: {text: …, sources: […], source_hash: …}
  studies[pmid:00000001].finding: {text: …, source_hash: …}
```

The names of the items (locators) are fixed by `translations.english_items`:

| Locator | English field |
| --- | --- |
| `name` | `name` |
| `core_claim` | `core_claim.text` |
| `level_reason[i]` | paragraph i of `level_reason` (a single text is paragraph 0) |
| `contested_reason[i]` | paragraph i of `contested.reason` (only while the card is contested) |
| `badge_reasons.diagnostic_marker[i]`, `badge_reasons.explains_pem[i]` | paragraph i of the badge's reason (only when there is one) |
| `links[i]` | the text of link i in `links` |
| `subgroups[i]` | subgroup i |
| `early_signals[i]` | early signal i |
| `studies[<id>].finding` | the `finding` of the study with that id |

Levels, badges, roles, numbers, ids and quotes have no locator, so they cannot be set from a translation. A file that is not valid YAML, has a key other than `slug` and `items`, an item field other than `text`, `sources` and `source_hash`, or a slug different from the file name stops the build with the file named. An item whose locator the English card lacks is ignored and reported (a warning in the build, an error from `translations check`).

`source_hash` is the SHA-256 of the English text the item was translated from. Code writes it (`translations apply`); an agent never computes a hash.

### The mechanical check

For every item, `uv run python -m me_atlas.translations check` (and the build, for each item) decides one of four states:

- **missing**: no item in the file. Shown: English, with a note.
- **stale**: the hash no longer matches the English text, or the item's `sources` differ from the English item's (the text is unchanged but the English now cites other sources), so the English changed after the translation. `check` names the reason: "the English text changed after it was translated" or "the English sources changed after it was translated". Shown: English, with a note. Reported by `check` and the build as stale; `check` does not fail on it, because a stale item after an accepted English change is expected and is what the weekly run fixes.
- **invalid**: the hash matches but a check fails: the `sources` list differs from the English one (any change, drop or reordering), the sequence of numbers differs (same numbers, same count of each, same order), a `pmid:` differs, the item has `sources` where the English has none (or lacks them where the English has them), or a banned word is in `core_claim` or an early signal. Shown: English, with a note. `check` exits non-zero.
- **fresh**: all checks pass. Shown: Norwegian.

An item for a list position past the end of that list on the English card (a link or paragraph a correction removed: `links[k]`, `level_reason[k]`, `contested_reason[k]`, `badge_reasons.*[k]`, `subgroups[k]`, `early_signals[k]`) is **obsolete**: `check` and the build warn, nothing shows it, it does not fail `check`, and `translations apply` drops it the next time the file is written. A key on any other field, or a malformed key, is still an error.

Numbers are compared as the ordered sequence of values as they occur in the text. So "n=170 patients and 73 controls" must stay "170 … 73" (swapping them fails), a number that occurs twice must occur twice, and a sentence that is reordered so that the numbers come in another order fails: the translator rephrases to keep the English order. A decimal comma matches a decimal point (0,5 = 0.5), a thousands separator (a space, a no-break space, or the English comma) is removed (1 200 = 1,200 = 1200), trailing zeros do not matter, and `pmid:` and `doi:` identifiers are left out (they have their own check). Limits, so the reviewer knows what code does not see: a changed sign, or a number written out in words. The check cannot tell which noun a number belongs to; the reviewer does.

## What the site does

`uv run python -m me_atlas.site build` writes English to `build/` and every other language in `content/i18n/` to `build/<lang>/`, with the same pages. Every page has `<html lang>`, `hreflang` alternate links to every language and an `x-default` for English, and a language selector in the header (a plain link to the same page in the other language, labelled in that language's own name). Every Norwegian page starts with a notice that it is a translation, with a link to the English page. English text on a Norwegian page is marked `lang="en"`. All links are relative, so navigating inside a tree stays in that language and both trees work from `file://`.

For each Norwegian card page: a fresh item is shown in Norwegian; any other item is shown in English followed by "Denne delen er ikke oversatt ennå." A card with no file at all gets one note under the heading ("Dette kortet er ikke oversatt ennå…") instead of a note on every paragraph. A card name that falls back to English gets the note under the heading. The front page and the glossary page use the translated names and terms, and sort in English order (the order is the same in both languages). The change log is English only, and the Norwegian page says so.

The build prints `warning:` lines for stale and left-out items, for items the English card does not have, for a translation file whose card is not in the build and, in one line, for the cards that have no translation file yet. It does not fail on them. It does fail when a language file lacks a key, a translation file is malformed, or a Norwegian glossary entry is invalid.

### The language choice sticks

The selector stores the choice in `localStorage` under `me-atlas-lang`. Each page has a small inline script in `<head>` that, on load, reads the stored value and, when it is a language other than the page's own, goes to the same page in that language with `location.replace` (so the Back button is not trapped). The same script stores the choice when a selector link is clicked. Every storage access is inside `try/catch`: with no stored choice, no storage, blocked storage or no JavaScript the page simply shows its own language. No cookies, no browser-language detection, no network. The script contains a table from language to the counterpart page, written per page by the build. `tests/test_site_languages.py` checks the script and the table on every built page and, when Node is installed, runs the script against a stub `localStorage` that works, is empty, throws or is missing.

## Adding a language

Add `content/i18n/<code>.yaml` with the same keys (and `lang.name`). The build then writes `build/<code>/` and adds the language to every selector and `hreflang` list. Optional: `content/glossary.<code>.yaml`, `content/methods/<code>.html`, `translations/<code>/`. `_AFTER_Z` in `i18n.py` holds a language's alphabetical order if it differs from Python's. Nothing else is code.

## Weekly run and agents

After the review step of `/ukentlig`, `pipeline translation-plan` compares each card that has an accepted change (and a file in `translations/nb/`) with the card as it will be after the change, and lists the items that change made stale or added. It writes `RUN/final/<slug>.yaml` (the card after the change), `RUN/translate/<slug>.json` (the items to translate, with the English text, sources and, for a stale item, the previous Norwegian) and `RUN/translation-plan.json`, and the report gets a "Translations" section. A card with no translation file is listed but not planned.

- **`card-translator`** (sonnet) reads the plan file, the glossaries, `content/i18n/nb.yaml` and the drafting checklist, and writes `RUN/translated/<slug>.json`: `{"slug", "lang": "nb", "items": [{"item", "text"}]}`. It leaves out an item it cannot translate faithfully.
- **`card-reviewer`** in translation mode (opus) reads the plan file and the translated file, not the translator's reasoning, and writes `RUN/translation-review/<slug>.json`: `{"slug", "lang", "verdict", "findings": [{"item", "severity", "problem", "fix"}]}`, with the same `must_fix` / `advisory` rule as in the English pipeline. It compares each item with its English source for meaning, numbers, neutrality, glossary terms and plain Norwegian.
- **`translations apply <slug> <translated.json> [--review <review.json>] [--card <card file>]`** is the only step that writes `translations/<lang>/<slug>.yaml`. It takes the hash and the sources from the English card, runs the mechanical check on each item, and leaves out an item that fails it, has a `must_fix` finding, is not an item of the card or is listed twice. Items already in the file stay. One second attempt for the items left out; then they stay English.
- **`translations check [--lang nb] [--overlay DIR]`** compares every sidecar with its English card from `cards/` and `drafts/` (a draft wins). `--overlay DIR` makes each `DIR/<slug>.yaml` replace the English card of that slug for the check, and a slug found only there is checked too. The weekly run uses `--overlay RUN/final` before `pr`: the translations were made against the final cards, which are only copied into `drafts/` by `pr`, so a check against `drafts/` alone would report new items as having no English counterpart.
- `pr` stages `translations/` with the drafts, so the weekly pull request contains both languages.

An AI step never decides what a level, badge or contested mark is: translations carry none of them.

## The first translation run (step 6 of the plan)

Not part of the code change. The same agents and `translations apply`, run by hand on all cards, the glossary and the methods page, with `--card drafts/<slug>.yaml`. The plan file for a first run lists every item of the card (`reason: missing`). Findings are fixed, then the founder reads the whole Norwegian set before merge, and later spot-checks. Until then `translations/` does not exist and the Norwegian site shows the Norwegian frame around English content, with notes.

## Tests

`tests/test_i18n.py` (string files, placeholders, banned words), `tests/test_glossary.py` (Norwegian glossary), `tests/test_translations.py` (sidecar, check, merge, commands, agent file shapes), `tests/test_site_languages.py` (both trees, fallback, notes, selector, script), `tests/test_site.py` (the English tree compared with `tests/fixtures/site_en_golden`, the English build as it was before this work, with the added lines taken out) and `tests/test_pipeline.py` (`translation-plan`). All fixtures are fictional; the Norwegian of a test is "NB " plus the English text. No test touches the network or an AI.
