# Static site generator

Reference for the founder and for agents. Code: `src/me_atlas/site.py` (build), `src/me_atlas/glossary.py` (glossary model), templates in `src/me_atlas/templates/`, `src/me_atlas/static/site.css` and `site.js`. Plan: `docs/plan-site-generator.md`. Page content follows `docs/ME-Atlas-functional-spec.md` sections 3 to 6; where this page and the spec differ, the spec wins.

## Build and preview

```bash
uv run python -m me_atlas.site build                  # approved cards only, into build/
uv run python -m me_atlas.site build --drafts         # also drafts/, as a draft preview
uv run python -m me_atlas.site build --out some/dir   # another output directory
```

Open `build/index.html` in a browser. Every page works from `file://` (all links are relative); there is nothing to serve.

- The build validates every input card (the same rules as `uv run python -m me_atlas.cards validate`), the change log and the glossary first. If anything fails it prints every problem, exits with code 1 and writes nothing (an earlier build stays as it was).
- The output directory is emptied before each build. A directory that is not empty and not a previous build (no `.me-atlas-build` marker file) is never deleted; the build stops instead.
- The citation check (`me_atlas.citations`) is not part of the build; it needs the local cache.
- Without `--drafts` only `cards/` is read, and an invalid draft does not matter. With `--drafts` a draft replaces the card with the same slug, every page gets the banner "Draft preview — not published" and `<meta name="robots" content="noindex">`. Draft builds are never published.
- Unused glossary terms are printed as `warning:` lines. They do not fail the build.

## Pages

| File | Content |
| --- | --- |
| `index.html` | Intro, how to read the chart, the six-rung ladder with the draft notice, the pipeline chart (one bar per hypothesis, contested rungs hatched, badges and the long COVID label as words), and the same information as a table. Sorted by level, highest first, ties alphabetically by name. With no cards it says "No hypotheses published yet." |
| `hypotheses/<slug>.html` | One card: name, long COVID label, core claim, level with rung name and reason, contested state ("Not contested" when there is no contested mark), the two badges (a badge without a written reason says "Reason not yet written."), studies in three groups (supports, contradicts, other; the third carries a fixed line saying these studies are shown for context and do not count for or against the level), subgroups, who is working on it, early signals (only when there are any, under "Early signals: not yet repeated"), last checked. |
| `changes.html` | Entries from `cards/changelog.yaml`, newest first. Drafts never appear here, also not with `--drafts`, and card names come from the published card even when a draft replaces it. |
| `methods.html` | The ladder, accepted case definitions, badges, contested rule, the planned editorial flow and tiers (with a status line saying most of it is not running yet), and the statement that no medical or research expert has reviewed the content. Text is written in the template and follows the spec (change the spec first), except that the editorial flow is marked as planned, not current. |
| `glossary.html` | Every glossary term used on at least one built page, alphabetical, with links back to the pages that use it. |
| `static/site.css`, `static/site.js` | The only stylesheet and script. |

Every page has the navigation (front page, what changed, methods, glossary) and a footer with the not-expert-reviewed statement and the build date.

### Sources in text

Each sourced text (core claim, level reason, contested reason, badge reasons, subgroups, early signals) ends with numbered references such as `[1] [2]`. Numbers are per page, in order of first citation, and each links to that study's entry on the same page (`#study-pmid:12345678`). Studies link out to PubMed (`https://pubmed.ncbi.nlm.nih.gov/<pmid>/`) or `https://doi.org/<doi>`. Each study shows year, patients and controls ("not stated" when null; "none (uncontrolled study)" for an uncontrolled study without a control number), the case definition in plain words, design, direction and finding. The case-definition sentence quoted on the card is not shown on the page.

Case definitions in plain words: Fukuda and Holmes 1988 carry the flag "does not require PEM", Oxford the flag "broad"; `unverified` reads "case definition not yet checked", `none` "no case definition stated", `other` "other definition".

Replication status has no field of its own; it is carried by the level name ("Repeated by others") and the level reason.

## Glossary

`content/glossary.yaml` is a list of entries and the only source of explanations:

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

Body text is 18 px or more; the layout reflows at 200% text size and at 375 px width (tables become stacked lists); tap targets are at least 44 px (marked terms and reference links get an invisible 44 px hit area that does not change the line height); focus is outlined; reduced motion is respected; no pop-ups. Colours are CSS variables at the top of `site.css`; `tests/test_site.py` checks the text pairs against 4.5:1 and chart marks and the focus outline against 3:1. If you change a colour, run the tests. The browser check (375 px, keyboard, one glossary term by focus and click) is manual.

Not built: search, filters, other languages, dark mode, hosting. The generated `build/` directory is gitignored.
