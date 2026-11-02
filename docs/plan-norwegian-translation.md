# Plan: Norwegian version of the site, with a language selector

November 2, 2026 · For `/orchestrator`

## Why

Many readers of ME Atlas are patients with little energy, and many read best in their own language. The founder wants a Norwegian version first; the structure must allow further languages later without rework. Credibility is the product: a translated finding that says something different from the source is an evidence error, so the translation is built to be checked mechanically and by a reviewer, and English stays authoritative.

## Design decisions (from brainstorm, 2026-11-02, accepted by the founder)

1. **The whole site in Norwegian, English authoritative.** Fixed text, ladder, glossary, methods page and all card text are translated. Study titles, case-definition quotes, PMIDs, author and group names stay in English. Every Norwegian page says it is a translation of the English page, which is the authoritative version, and links to it.
2. **Fixed text from string files.** All template text comes from `content/i18n/en.yaml` and `content/i18n/nb.yaml` (same keys; a missing key fails the build). This includes the rung names and meanings (the English ones must still match spec section 3, as tested today), the banner, labels, case-definition labels and flags, and footer text.
3. **Glossary per language.** `content/glossary.yaml` stays English; `content/glossary.nb.yaml` holds the same terms (keyed by the English term) with a Norwegian term, Norwegian aliases for auto-marking in Norwegian text, and a Norwegian explanation. Same validation as today (≤200 characters, banned words in both languages; add Norwegian equivalents of the banned words).
4. **Methods page per language.** `templates/methods.html` text moves to per-language content; the Norwegian methods page is a translation, reviewed like the cards.
5. **Card translations as sidecar files.** `translations/nb/<slug>.yaml` mirrors the translatable fields of `drafts/<slug>.yaml` (and later `cards/`): name, core claim, level reason, contested reason, badge reasons, subgroups, early signals (each paragraph separately), and each study's `finding`. Each translated paragraph or finding stores the SHA-256 of the English text it was translated from and the same `sources` list. Levels, badges, roles, numbers, ids and quotes are never copied into the translation: they always come from the English card.
6. **Mechanical translation check** (`uv run python -m me_atlas.translations check`): for every translated item, the sources list equals the English one; the numbers in the Norwegian text are the same as in the English text, in the same order and count (accepting decimal comma for decimal point and spaces in thousands); every `pmid:` mentioned matches; no field exists that the English card does not have. A translation whose hash no longer matches the English text is **stale**.
7. **Stale or missing translation falls back to English** for that item, with a short visible note ("Denne delen er ikke oversatt ennå"). Stale Norwegian is never shown. The build lists stale items as warnings.
8. **Build and selector.** The build writes English at `build/` and Norwegian at `build/nb/`, with `lang="nb"` and `hreflang` alternate links. Every page has a language selector (a plain link to the same page in the other language, labelled "Norsk" / "English"). Relative links keep working from both trees, so navigating within one language stays in that language.
   - **The choice sticks (founder, 2026-11-02).** Choosing a language makes it the default on all pages until the reader changes it again. The selector stores the choice in `localStorage` (key `me-atlas-lang`). On load, a page whose language differs from the stored choice goes to the same page in the stored language with `location.replace`, so the Back button is not trapped. Every storage access is wrapped in try/catch. With no stored choice, or no storage, or no JavaScript, the page simply shows its own language. No browser-language detection and no cookies.
9. **Agents.** A new `card-translator` agent (model sonnet) translates English card text into the sidecar file, using the Norwegian glossary terms and the drafting checklist's rules (neutral wording, no changed numbers, no claims beyond the English). `card-reviewer` gets a translation mode: it compares each Norwegian item with its English source for meaning, numbers and neutrality and returns must-fix / advisory findings. The founder reads the first full Norwegian set and later spot checks.
10. **Weekly pipeline.** After the review step, `pipeline` lists the items made stale by accepted changes; `/ukentlig` runs the translator and the reviewer on them, and the weekly PR contains both languages. A translation that fails the check or the review is left out and that item falls back to English.
11. **Rule change.** CLAUDE.md "Language" and spec section 5 ("English, plain words") are amended: site content is written in English, which is authoritative; reviewed translations are published alongside it. Recorded in DECISIONS.

## Steps

1. String files and template refactor: move all fixed template text to `content/i18n/en.yaml`; build the English site unchanged from them (existing tests stay green). Add `nb.yaml`.
2. Norwegian glossary file and loader; marking works per language.
3. Translation sidecar model, loader and `translations check` (step-by-step checks in decision 6), with fictional fixtures.
4. Build both languages, selector, fallback with note, hreflang, translation notice.
5. `card-translator` agent and the card-reviewer translation mode; pipeline subcommand listing stale items; `/ukentlig` updated.
6. First translation run (manual, after the code is merged): translator and reviewer on all 16 cards, the glossary and the methods page; findings fixed; founder reads the result before merge.
7. Docs: `docs/translation.md`; CLAUDE.md and spec section 5 amended; DECISIONS entry; STATUS.

## Done when

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` pass; no test touches the network or an AI.
- [ ] The English build is byte-identical in content to today's except for the added selector link and hreflang tags (tested on a fictional card).
- [ ] A missing key in `nb.yaml` fails the build with the key name (tested).
- [ ] `translations check` tests with negative inputs: changed sources list; a number added, removed or changed (and a decimal comma accepted as the same number); a PMID that differs; a field the English card lacks; a stale hash reported as stale.
- [ ] Build tests: a stale or missing item shows the English text with the note; a fresh item shows Norwegian; levels, badges, quotes and study titles on the Norwegian page come from the English card; every Norwegian page has `lang="nb"`, the translation notice, a working link to its English page and back.
- [ ] Language persistence: each page's selector link carries the target language so a script can store it; a test on the built HTML checks that every page in both trees includes the persistence script and the mapping to its counterpart page. The script handles a missing or throwing `localStorage` (no redirect, no error). Live check in the browser: choose Norsk on one page, open another English page directly, and it shows in Norwegian; choose English and it stays English.
- [ ] Glossary tests: Norwegian terms and aliases mark Norwegian text; banned-word check covers Norwegian equivalents.
- [ ] The pipeline lists stale items after an accepted change (tested with fixtures); `/ukentlig` describes the translation step.
- [ ] Docs and rule changes done (step 7). No new dependencies.
- [ ] Step 6 is a separate PR after this one, so the code can be reviewed apart from the translated content.

## Out of scope

- Languages other than Norwegian (the structure allows them; none is made now).
- Translating study titles, case-definition quotes or author names.
- Browser-language detection and cookies (the only redirect is to the reader's own stored choice, decision 8).
- Publishing or hosting the site.
