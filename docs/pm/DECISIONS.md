# Decisions

Append-only, newest first. One entry per ruling: date, decision, why.

## 2026-11-01 — Rulings from the site review

- Level 2 needs a controlled study with a **recognised** case definition (the accepted table in spec section 3), not a "strict" one. Fukuda and Holmes 1988 count, flagged "does not require PEM". Why: the spec contradicted itself (Fukuda accepted at every rung, but level 2 said "strict"); this keeps the rule the cards were graded by.
- A study that cites "CDC criteria" without naming the version is accepted like Fukuda and Holmes 1988: flagged "does not require PEM", ranked equal to Fukuda. New card format value for it. Why: both CDC versions are accepted on the same terms, so the unnamed version is not weaker evidence than either.
- `last_checked.by` stays `ai_pair` on both drafts for now.
- Long sourced texts may be split into paragraphs, each with its own sources, so a reader can see which sentence rests on which study. Why: the NK level reason ended with 11 references in one block.
- NK card: the 21-patient CDC study (pmid:7983659) that found no difference is named in the contested reason as a second comparable contradiction of the 39-patient study. Rung 2 is not contested (it rests on the Miami study); levels unchanged. Why: under the CDC ruling it ranks equal to Fukuda and 21 is at least half of 39; the abstract does not say how many patients were measured, which the card states.

## 2026-11-01 — Site layout revised at founder request

- Site layout revised at founder request; ladder key under the chart; table behind a disclosure; secondary text minimum 16 px. The front page now opens with a short heading and one lead sentence, then the chart in one panel, the legend, the ladder key (rung names and meanings copied from spec section 3) and the table inside a closed "Show the chart as a table" disclosure. Calmer type: smaller headings, a 46 rem column, one compact header bar.
- Spec section 5 "Text size" amended: body text at least 18 px equivalent; secondary text (keys, labels, study details) at least 16 px; layout holds at 200%. Why: the founder found the first view too text-heavy and large-typed; 16 px for secondary text keeps it readable while letting the main text lead.

## 2026-11-01 — Static site generator

- The site is plain static HTML written by `uv run python -m me_atlas.site build` with Jinja2 (already a dependency): one CSS file, one small JavaScript file for the glossary explanations, no external fonts, scripts or styles, every page works from `file://`. Output goes to `build/` (gitignored). Why: no server, database or build tooling to maintain; readers on poor connections and the founder can open the files directly.
- Drafts are built only with `--drafts`, and then every page carries the banner "Draft preview — not published" and `<meta name="robots" content="noindex">`. Without the flag only `cards/` is read, so a draft cannot reach a page by accident. "What changed" never shows drafts. The build runs the card validator first and writes nothing if any input fails. Why: CLAUDE.md rule 2; only the editorial team moves content into `cards/`.
- Glossary: one file, `content/glossary.yaml` (term, aliases, explanation of at most 200 characters, none of the banned words). The generator marks the first occurrence on each page of every glossary term or alias in sourced text and study findings (whole word, case-sensitive, longest match wins, never in study titles, links or headings); template labels are marked through one macro. No change to the card format. Founder ruling: option a. Why: card authors do not mark terms by hand and the explanation stays in one place.
- Replication status has no card field of its own; the page shows it through the level name and the level reason. Why: the format backlog stays closed until a card needs a field.
- Plan: `docs/plan-site-generator.md`. Reference: `docs/site.md`.

## 2026-11-01 — Mechanical citation check

- The citation check is its own offline command, `uv run python -m me_atlas.citations check`, not part of `cards validate`. It reads only the cache and never makes a request. Why: the cache is gitignored, so it cannot run on GitHub as the validator can; it runs locally and later in the weekly pipeline.
- Seven checks per study, C1-C7: record exists, title, year, not retracted, case-definition quote verbatim in the stated source, sample size, DOI-only id. Matching is exact after a stated, narrow normalisation (NFKC, whitespace, case for titles; quotes and dashes for quotes), nothing looser. Reference: `docs/citation-check.md`. Plan: `docs/plan-citation-check.md`.
- Sample size (C6) is a warning, not an error. Why: a correct number may be written as a word, be a sum of cohorts or belong to one measurement, so a person looks instead of the check blocking.
- A `doi:` study id is an error for now ("cite by PMID"). Why: only PubMed records are fetched, so a DOI-only id cannot be checked; every current study has a PMID.
- `pubmed fetch --ids <pmid>...` fetches exactly the given records (no search, no retraction query), so a card can cite a paper outside the search query. It writes a run manifest with the mode and ids.

## 2026-11-01 — Rulings from the first two draft cards

- Comparable quality uses the number of patients in the measurement that bears on the finding, not the whole study. Why: stricter and more honest when only part of a study measured the outcome. Added to spec section 3.
- A rung that rests on more than one study is contested when a study of comparable quality contradicts any study the rung needs. Why: the rubric compared single studies only. Added to spec section 3.
- Early signals come only from studies with a confirmed recognised case definition. Why: the inclusion rule says that without one we cannot tell whether the patients had ME/CFS. Added to spec section 4.
- NK card: the Miami group (20520837) counts as independent of the 39-patient Australian study (27099524) for level 3; their author lists and cohorts are separate, and the indirect co-authorship link is stated on the card. The ADCC study (33777500) stays background, since it measures a different kind of NK killing.
- Neuroinflammation card: a diagnosis "consistent with the Canadian Consensus Criteria, confirmed by two clinicians" (41834684) counts as CCC; the verbatim quote is shown on the card.
- Proposed levels accepted as draft levels: reduced NK cell function level 3, contested at rung 3; neuroinflammation level 2, not contested. Both stay in `drafts/` until publication.

## 2026-10-31 — Card format v2, Holmes 1988, Europe PMC on demand

- Card format v2 (rule V13 added): `case_definition` gains `unverified` (not yet checked) and `Holmes1988`; `none` now means the source was checked and states no case definition. New study fields `case_definition_source` (abstract, fulltext or null) and `case_definition_quote` (the verbatim sentence), `direction` (lower, higher, no_difference, mixed, not_applicable; required for every role) and optional `group` (research group label). `unverified` cannot support or contradict, like `none`. Why: the first two draft cards could not say "not checked yet", which way a background study points, or which group did a study. Reference: `docs/card-format.md`. Plan: `docs/plan-fulltext-and-format-v2.md`.
- Holmes 1988 (the 1988 CDC definition) is accepted like Fukuda: allowed at every rung, flagged on the card as "does not require PEM", ranked equal to Fukuda in the comparable-quality rule. Added to the case-definition table in the functional spec, section 3. Why: founder ruling when the plan was approved.
- Europe PMC full text is fetched on demand, only for PMIDs on a card or draft (or given on the command line), never in bulk, and only for open-access records. Full text stays in the gitignored cache; a card quotes at most the one sentence that states the case definition. The finder suggests sentences; a person or agent decides which definition a sentence means. Why: the case definition is normally in the methods section, not the abstract, and bulk download is neither needed nor polite.
- The two existing drafts were migrated: every study whose abstract wording is quoted in the draft's comments got source `abstract` and the verbatim sentence; every study that was `none` ("not stated in abstract") is now `unverified`, because the full text has not been read. No level, contested mark, badge or text field changed.

## 2026-10-31 — PubMed fetch

- PubMed only for now. It is the canonical source for PMIDs, titles, publication types and retraction flags. Europe PMC (preprints, full-text links) is added only if a concrete need appears.
- The search query lives in `config/pubmed_query.txt`, not in code, so changes are reviewed in a pull request. Why: the query decides what the Atlas can ever see.
- ME/CFS by MeSH heading plus title/abstract terms; long COVID only when the record also mentions ME/CFS (the AND clause). Why: long COVID alone is far larger and out of v1 scope; the overlap studies are what the long COVID label needs. The MeSH headings are checked against live PubMed on the first live run, not taken on trust.
- Full backfill once, then weekly runs by entry date over the last 14 days, de-duplicated by PMID. Why: fetching costs requests, not money; classification cost is controlled later.
- Retraction check on every run: the query plus the "Retracted Publication" filter, not limited by the date window, with a stale cached copy downloaded again. Why: a card citing a later-retracted study must be caught (spec section 3).
- No filtering at fetch time; deciding what counts as evidence belongs to classification. Details: `docs/fetch.md`, plan `docs/plan-fetch-script.md`.

## 2026-10-31 — Card data model

- Cards are YAML, one file per hypothesis (`cards/<slug>.yaml`), validated by pydantic models in `src/me_atlas/cards.py`. Why: YAML reads well in a pull request diff and allows comments; pydantic and PyYAML were already dependencies.
- Studies are listed inline on each card, with no shared registry. A study cited by two cards appears twice; the later citation check compares both against the fetched record. Every free-text field is `{text, sources}`, so "every claim links to its source" is checkable.
- Drafts use the same schema as cards (`drafts/<slug>.yaml`); the change is the diff against the card. No separate patch format.
- Derived, not stored: the long COVID label (any cited long COVID cohort), the hatched contested segment (`contested.rungs`) and ranking (`level`).
- One change log, `cards/changelog.yaml`, an append-only list of entries (date, card, change, reason, sources, tier).
- Twelve mechanical rules (V1–V12) are enforced by `uv run python -m me_atlas.cards validate`; reference in `docs/card-format.md`. Plan: `docs/plan-card-data-model.md`.

## 2026-10-31 — Tiered AI review and open questions

- Review runs mostly on AI: a drafting agent and an independent review agent, with mechanical citation checks in code. Two failed rounds send a change to a parking lot for the founder. Tier 1 changes (new study on a card, factual text) may publish automatically after a calibration period; levels, badges, contested marks and new hypotheses always need the founder. CLAUDE.md rule 2 amended to match. Why: no medical reviewer yet; keeps the founder's workload small while a human still decides everything that moves the chart.
- No external reviewer before launch; recruit after showing the site publicly. The site says openly that content is AI-reviewed, not expert-reviewed.
- Oxford-only evidence capped at level 1; Fukuda flagged "does not require PEM". PEM badge needs a study that measures PEM directly. Contested = same or stricter case definition, controlled, at least half the sample size. Early signals on cards only, fixed wording. Long COVID label on the card. v1 stands alone from MEpedia.
- Details: `docs/ME-Atlas-functional-spec.md` sections 3, 6 and 8.

## 2026-10-31 — Front page and evidence display

- Front page is a pipeline chart: one bar per hypothesis against the status scale, ranked as "furthest along", never "most promising". Contested evidence shown on the bar. No momentum or paper-count metric. Why: honest, familiar format; volume is not evidence.
- One axis (causal evidence) plus two card badges: validated diagnostic marker, explains PEM. Treatment success alone is not proof of cause. Why: easier to read than three tracks, and scientifically accurate.
- v1 covers ME/CFS; long COVID is marked where evidence overlaps. No subgroup filtering in v1. Why: keep scope small.
- Site is in English, plain language; technical terms explained from one shared glossary on hover, tap and focus. Why: international audience with limited energy.
- Details and next steps: `docs/plan-functional-spec.md`.

## 2026-10-31 — Repository setup

- Python with `uv`, `ruff` and `pytest`; static site generated from card files, no database.
- Approved cards live in `cards/`, AI drafts in `drafts/`; only the editorial team moves content between them.
- Agent roles adapted from Kunnskapsbanken in a lean form: prosjektleder, brainstorm, orchestrator → worker → evaluator, plus a domain `card-reviewer` that fact-checks citations.
