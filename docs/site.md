# Static site generator

Reference for the founder and for agents. Code: `src/me_atlas/site.py` (build), `src/me_atlas/glossary.py` (glossary model), templates in `src/me_atlas/templates/`, `src/me_atlas/static/site.css` and `site.js`. Plan: `docs/plan-site-generator.md`. Page content follows `docs/ME-Atlas-functional-spec.md` sections 3 to 6; where this page and the spec differ, the spec wins.

## Build and preview

```bash
uv run python -m me_atlas.site build                  # approved cards only, into build/
uv run python -m me_atlas.site build --drafts         # also drafts/, as a draft preview
uv run python -m me_atlas.site build --out some/dir   # another output directory
```

Open `build/index.html` in a browser. Every page works from `file://` (all links are relative); there is nothing to serve.

The site is built in every language that has a file in `content/i18n/`: English at the top of the output directory and Norwegian in `build/nb/`, same pages, one shared `static/`. All fixed text comes from the string files; see `docs/translation.md` for the string files, the Norwegian glossary, card translations, the language selector and what a page shows when a translation is missing or out of date. Where this page says "the page says X", that is the English text; the Norwegian string is in `content/i18n/nb.yaml`.

- The build validates every input card (the same rules as `uv run python -m me_atlas.cards validate`), the change log and the glossary first. If anything fails it prints every problem, exits with code 1 and writes nothing (an earlier build stays as it was).
- The output directory is emptied before each build. A directory that is not empty and not a previous build (no `.me-atlas-build` marker file) is never deleted; the build stops instead.
- The citation check (`me_atlas.citations`) is not part of the build; it needs the local cache.
- Without `--drafts` only `cards/` is read, and an invalid draft does not matter. With `--drafts` a draft replaces the card with the same slug, every page gets the banner "Draft preview — not published" and `<meta name="robots" content="noindex">`. A draft build is shared only as the private preview below, never as the public site.
- Unused glossary terms are printed as `warning:` lines. They do not fail the build.

## Private preview on Azure

A draft build is hosted for a few readers (founder ruling 2026-11-03) as an Azure Storage static website in the StormSolutions subscription: resource group `rg-me-atlas` (Norway East), storage account `meatlaslpr4z`, address <https://meatlaslpr4z.z1.web.core.windows.net/> (Norwegian: `/nb/`). Anyone with the link can read it; it is not listed anywhere, and every draft page carries the banner and `noindex`. It is not updated automatically. To update it after a change is merged to `main`:

```bash
uv run python -m me_atlas.site build --drafts
az storage blob upload-batch --account-name meatlaslpr4z --auth-mode key -s build -d '$web' --pattern '[!.]*' --overwrite
```

The pattern leaves out the `.me-atlas-build` marker. Files removed from the build stay online until deleted from the `$web` container (`az storage blob delete-batch --account-name meatlaslpr4z --auth-mode key -s '$web'` empties it before an upload). Needs the Azure CLI signed in to the StormSolutions tenant.

## Pages

| File | Content |
| --- | --- |
| `index.html` | One heading and a short lead sentence; the pipeline chart in one panel (one header row of rung numbers on wide screens, one row per hypothesis with name, badges and the long COVID label as chips, the bar and a one-line readout; contested rungs hatched); the legend directly under the chart; "How to read the ladder" (the six rungs with the "What it means" text copied from the spec, the draft notice, the not-mutually-exclusive sentence and the "furthest along" sentence); and the same information as a table inside a closed "Show the chart as a table" disclosure. Sorted by level, highest first, ties alphabetically by name. With no cards it says "No hypotheses published yet." |
| `hypotheses/<slug>.html` | One card: name; a summary panel with the bar, the level line and chips (contested state, marker validated yes/no, explains PEM yes/no, the long COVID label); core claim; why this level; contested state ("Not contested" when there is no contested mark); the two badges with reasons (a badge without a written reason says "Reason not yet written."); studies in three groups (supports, contradicts, other, each group in one panel with a thin divider between studies, and each study as a title link, one metadata line and the finding; the third carries a fixed line saying these studies are shown for context and do not count for or against the level), subgroups, who is working on it, early signals (only when there are any, under "Early signals: not yet repeated"), and last checked: the date and who, with the label from `by.<value>` in the string files (`ai_audit` "the AI auditor", `ai_pair` "the AI review pair" on a draft, `founder` "the founder" after a logged overrule; Norwegian in `nb.yaml`). |
| `changes.html` | Entries from `cards/changelog.yaml`, newest first. Drafts never appear here, also not with `--drafts`, and card names come from the published card even when a draft replaces it. |
| `gaps.html` | "What is missing": five counted lists from the causal map data (symptoms with no link, symptoms linked only at step 1, links at step 1 grouped by target, what the next rung requires per level, hypotheses with no links), same counts as `map report`; no score or ranking. Sits after the causal map in the navigation. |
| `methods.html` | The ladder, accepted case definitions, badges, contested rule, the editorial flow with the review agent, the auditor, the consistency check and the tier table (spec section 6), the statement that the content, including every evidence level, is drafted, checked and decided by AI tools and that no medical or research expert has reviewed it, and the known limits (the auditor shares a model family with the agents it audits). The text is `content/methods/<lang>.html` (a Jinja fragment per language, English first) and follows the spec (change the spec first). It says the founder sets the rubric, the scope and the direction and may overrule an auditor decision as a logged correction; it never says the founder checks, approves or decides content or levels (a test checks every built page in both languages). |
| `glossary.html` | Every glossary term used on at least one built page, alphabetical, with links back to the pages that use it. |
| `static/site.css`, `static/site.js` | The only stylesheet and script. |

Every page has the navigation (front page, what changed, methods, glossary), a language selector, `hreflang` links, a small script that remembers the chosen language, and a footer (`footer.review`) saying that the content, including every evidence level, is drafted, checked and decided by AI tools and that no medical or research expert has reviewed it, with the build date. There is no error-report or contact line: none is added until the founder names a contact address. The glossary entry for "contested" says an AI auditor decides it and that no expert has reviewed it (`content/glossary.yaml`, Norwegian in `content/glossary.nb.yaml`).

### Sources in text

Each sourced text (core claim, level reason, contested reason, badge reasons, subgroups, early signals) ends with numbered references such as `[1] [2]`. A level reason, contested reason or badge reason written as paragraphs (see `docs/card-format.md`) is shown as one paragraph per item, each with its own references; numbering still follows page order. Numbers are per page, in order of first citation, and each links to that study's entry on the same page (`#study-pmid:12345678`). Studies link out to PubMed (`https://pubmed.ncbi.nlm.nih.gov/<pmid>/`) or `https://doi.org/<doi>`. Each study shows its title, one metadata line (year, id, patients and controls, the case definition in plain words with its flag, design, direction, and "cited as [n]") and the finding. Missing numbers read "patients: not stated" and "controls: not stated"; an uncontrolled study without a control number reads "controls: none (uncontrolled study)". The case-definition sentence quoted on the card is not shown on the page.

Case definitions in plain words: Fukuda, Holmes 1988 and `CDC_unspecified` ("CDC criteria (version not stated)") carry the flag "does not require PEM", Oxford the flag "broad"; `unverified` reads "case definition not yet checked", `none` "no case definition stated", `other` "other definition".

Replication status has no field of its own; it is carried by the level name ("Repeated by others") and the level reason.

## Glossary

`content/glossary.yaml` is a list of entries and the only source of English explanations (the Norwegian ones are in `content/glossary.nb.yaml`, see `docs/translation.md`):

```yaml
- term: PEM
  aliases: [post-exertional malaise]
  explanation: Post-exertional malaise. Symptoms get worse after physical or mental effort, often a day or more later.
```

Rules (checked on every build and in `tests/test_glossary.py`): terms and aliases are unique across the file (exact spelling); the explanation is not empty and at most 200 characters; none of the banned words (promising, breakthrough, cure, hope, proven) appears anywhere in an entry. Explanations describe concepts; they do not state findings or causes. A new entry should be read by `card-reviewer` for accuracy and plain language.

**Auto-marking.** In sourced texts and study findings the generator marks the first occurrence on each page of each term or alias. Matching is whole-word and case-sensitive ("Widget" does not match "widget"; add a capitalised alias if you need one). Where matches overlap, the longest wins. Study titles, links and headings are never marked. A term already marked on a page is plain text afterwards. Technical words that are not in the glossary are simply left unmarked.

**Template labels** (ladder names, "contested", "PEM", case definitions and so on) are marked in the templates through one macro, `gloss("term")`, which also follows the first-occurrence rule. A template that names a term missing from the glossary stops the build.

**Behaviour.** A marked term is a `<button>` with a dotted underline and `aria-describedby` pointing at an element on the same page that holds the explanation. It opens on hover, focus and click or tap; Escape or a click elsewhere closes it. Without JavaScript the explanations are listed at the end of the page. The glossary page repeats the same text.

## Accessibility and limits

Body text is 18 px; secondary text (ladder key, legend, readouts, study details, chips, footer, banner) is 16 px (0.889rem) and never smaller, which a test enforces on the stylesheet (only the visually hidden `.sr` rule is exempt); the layout reflows at 200% text size and at 375 px width (tables become stacked lists); tap targets are at least 44 px (marked terms and reference links get an invisible 44 px hit area that does not change the line height); focus is outlined; reduced motion is respected; no pop-ups. Colours are CSS variables at the top of `site.css`; `tests/test_site.py` checks the text pairs against 4.5:1 and chart marks and the focus outline against 3:1. If you change a colour, run the tests. The browser check (375 px, keyboard, one glossary term by focus and click) is manual.

Not built: search, filters, languages other than English and Norwegian, dark mode, hosting of the public site (only the private preview above). The generated `build/` directory is gitignored.
