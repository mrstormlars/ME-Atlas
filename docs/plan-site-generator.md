# Plan: static site generator

November 1, 2026 · For `/orchestrator`

## Why

The two draft cards exist only as YAML. The founder, future reviewers and the people we want to recruit need to see them as readers will: the front page with the pipeline chart, and one page per hypothesis. Spec section 4 defines the pages and section 5 the plain-language and accessibility rules; `docs/mockups/front-page.html` shows the intended look of the front page.

## Design decisions (from brainstorm, 2026-11-01, accepted by the founder)

1. **Build command.** `uv run python -m me_atlas.site build [--drafts] [--out build]` writes plain static HTML to `build/` (gitignored). Jinja2 (already a dependency) with autoescape on; one CSS file; a small vanilla JS file only for opening glossary explanations on tap and closing them with Escape. No external fonts, scripts, styles or CDNs; every page works from `file://` with relative links. No new dependencies.
2. **Inputs.** By default only `cards/`; with no cards the front page says plainly that no hypotheses are published yet. `--drafts` adds `drafts/` (a draft replaces the card with the same slug) and puts a prominent banner on every page ("Draft preview — not published") plus `<meta name="robots" content="noindex">`. The build runs the card validator first and refuses to build (non-zero exit, errors printed) if any input card fails. The citation check is not part of the build (it needs the cache).
3. **Pages.**
   - **Front page** (`index.html`): one-sentence intro; the pipeline chart, one horizontal bar per hypothesis against the six rungs (names from spec section 3), built in HTML/CSS following the mockup; contested rungs hatched; the two badges as words; the "Also studied in long COVID" label from `Card.long_covid`; the sentence that hypotheses are not mutually exclusive; the draft notice on the ladder ("Draft — pending expert review"). Sorted by level, highest first, ties alphabetically by name. Below the chart, a table with the same content (name, level and rung name, contested, badges) as the text equivalent. Each name links to its card page.
   - **Card page** (`hypotheses/<slug>.html`): name; long COVID label; core claim; level with rung name and level reason; badges with reasons; contested state with reason; studies in three groups: "Studies that support it" (`supports`), "Studies that contradict it" (`contradicts`), "Other studies" (`context`, `early_signal`). Each study shows title, year, link (PubMed `https://pubmed.ncbi.nlm.nih.gov/<digits>/` or `https://doi.org/<doi>`), number of patients and controls ("not stated" for null), case definition in plain words (Fukuda and Holmes 1988 flagged "does not require PEM", Oxford flagged "broad", `unverified` shown as "case definition not yet checked", `none` as "no case definition stated", `other` as "other definition"), design, direction and finding. Subgroups; who is working on it (external links); early signals under the fixed heading "Early signals: not yet repeated" (omitted when empty); last checked (date, and "AI review pair" or "founder"). Replication status is carried by the level name and the level reason; no new card field.
   - **Sources in text.** Every sourced text renders its sources as numbered references, numbered per page in order of first citation, each linking to that study's entry on the same page (`#study-<id>`).
   - **Glossary page** (`glossary.html`): every glossary term used on at least one built page, alphabetical, with its explanation and links back to the pages that use it. Unused terms are left out and listed as a build warning.
   - **What changed** (`changes.html`): entries from `cards/changelog.yaml`, newest first, with date, card link, change, reason, source links and tier. Empty state when there are none. Drafts are never shown here, also not with `--drafts`.
   - **Methods page** (`methods.html`): short plain-language account of the ladder (spec section 3 table), accepted case definitions, the two badges, the contested rule, the editorial flow and its tiers (spec section 6), and the plain statement that the content is checked by AI and the founder and has not been reviewed by a medical or research expert. It must not contradict the spec; where the two would differ, the spec wins.
   - **Every page:** navigation to front page, methods, glossary, what changed; footer with the not-expert-reviewed statement and the build date.
4. **Glossary.** One file, `content/glossary.yaml`: list of `{term, aliases, explanation}`, validated with pydantic (unique terms and aliases, non-empty explanation of at most 200 characters, none of the banned words from `cards.py`). It is the only source of explanations.
   - **Auto-marking in card text (founder ruling: option a):** the generator marks the first occurrence on each page of each term or alias in rendered sourced text and study findings. Whole-word, case-sensitive match; the longest match wins where terms overlap; never inside study titles, links or headings. No change to the card format.
   - **Template labels** (rung names, "contested", "case definition", "PEM", badge names and similar) are marked explicitly in the templates through one macro, from the same file.
   - **Behaviour** as spec section 5: the term is a focusable control described by its explanation (`aria-describedby`), shown on hover, focus and tap; Escape or tapping elsewhere closes a tapped explanation; hover is never the only way.
   - **Content:** the worker drafts the initial glossary (terms the two drafts and the templates need) in plain English; `card-reviewer` checks it for medical accuracy and plain language; the founder approves in the PR.
5. **Accessibility** (spec section 5): text and chart marks at least WCAG 2.2 AA (4.5:1 body text, 3:1 for non-text marks and large text); meaning never by colour alone (level text labels, hatch pattern, badges in words); body text at least 18 px; layout holds at 200% text size; 375 px width without horizontal scrolling; tap targets at least 44 px; visible focus outline, logical tab order; `prefers-reduced-motion` respected; no pop-ups.

## Steps

1. `content/glossary.yaml` model and loader (with validation) in `src/me_atlas/glossary.py`.
2. `src/me_atlas/site.py`: load and validate cards (and drafts with `--drafts`), changelog and glossary; build context (sorting, reference numbering, study grouping, case-definition labels, glossary marking); render templates; write to the output directory (cleared of previous output first). Templates in `src/me_atlas/templates/`, CSS and JS in `src/me_atlas/static/`, copied to the output.
3. Templates and CSS for the five pages, following the mockup's look.
4. Initial glossary content and methods page text.
5. Tests `tests/test_site.py` with fictional fixture cards (reuse or extend `tests/fixtures/cards/`): build into `tmp_path` and assert on the HTML.
6. Live check (manual): build with `--drafts`, open the pages in the browser pane at 375 px and at desktop width, tab through one card page with the keyboard, check one glossary term by focus and by click, and send the founder screenshots of the front page and both card pages. Run `card-reviewer` on the rendered card pages against the drafts and on the glossary and methods text.
7. Short `docs/site.md` (how to build and preview, page list, glossary file and auto-marking). Add `content/` to the layout in `CLAUDE.md`. DECISIONS entry (static Jinja site, drafts only behind `--drafts` with banner, glossary auto-marking, replication status via level). STATUS update.

## Done when

- [ ] `uv run pytest` passes; `uv run ruff check .` and `uv run ruff format --check .` clean; no test touches the network.
- [ ] Build tests with fictional cards:
  - front page lists hypotheses sorted by level then name (test with a tie);
  - a card with `contested.rungs` renders hatched rungs on the front page and the contested reason on the card; a card without contested renders neither;
  - a card with a `long_covid` study shows the long COVID label; a card without one does not;
  - every numbered reference on a card page links to a study anchor that exists on that page, and every study cited in text appears in the studies list;
  - each case-definition value renders its plain-word label and flag (Fukuda, Holmes1988, Oxford, unverified, none, other);
  - early signals section is absent when the list is empty and has the fixed heading when not;
  - no built page contains the banned words outside quoted study titles;
  - an empty `cards/` builds a front page with the "no hypotheses published yet" text and exit 0;
  - an invalid input card makes the build exit non-zero and writes no pages;
  - without `--drafts` no draft appears and no draft banner is present; with `--drafts` the draft appears and every page has the banner and `noindex`;
  - `changes.html` never contains draft entries.
- [ ] Glossary tests: duplicate term, duplicate alias, empty explanation, explanation over 200 characters and a banned word each fail validation; auto-marking marks only the first occurrence on a page, matches whole words case-sensitively, prefers the longer overlapping term, and never marks inside a study title; every marked term has a focusable element with `aria-describedby` pointing at an element holding its explanation; the glossary page lists only used terms, with back-links; an unused term is reported as a warning.
- [ ] A test parses the colour tokens in the CSS and checks a named list of foreground/background pairs: body text at least 4.5:1, chart marks and large text at least 3:1.
- [ ] A test asserts that no built page loads anything from another host (no external `src`, stylesheet or script URL; external `href` only for study links and `working_on_it` links).
- [ ] The live check ran: screenshots of the front page and both draft card pages at 375 px and desktop width sent to the founder; no horizontal scroll at 375 px; keyboard focus visible; one glossary explanation opened by focus and by click and closed with Escape. `card-reviewer` findings on the rendered pages, glossary and methods text are fixed or reported.
- [ ] `build/` stays gitignored; nothing added to `cards/`; `drafts/` unchanged; no new dependencies.

## Out of scope

- Publishing or hosting the site, the domain, any deployment workflow. Draft builds are never published.
- Search, subgroup filters, multiple languages, dark mode, RSS, analytics, cookies.
- New card fields (replication status, per-measurement sample size and the rest of the format backlog).
- The weekly pipeline and AI drafting.
