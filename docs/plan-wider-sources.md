# Plan: wider sources (query recall, preprints, bridge search pilot)

Brainstorm 2026-11-13. For `/orchestrator`.

## Goal

Collect more of what is known about ME/CFS mechanisms, and surface **untested questions** a researcher could pick up, without weakening the evidence ladder. Three parts, in this order:

- **A. Query recall check:** find out whether the PubMed query misses ME/CFS papers, and fix it if it does.
- **B. Preprints:** take in preprints as labelled early signals that can never move a level.
- **C. Bridge search pilot:** for a handful of links the map lists as "not yet tested in patients", search the literature *outside* ME/CFS (general human physiology and other conditions, and long COVID papers that do not mention ME/CFS) for systematic reviews on the same relation. A manual-scale pilot that ends in a report, not a pipeline feature.

Founder rulings behind this plan (2026-11-13, see DECISIONS): an "indirect" kind of evidence is introduced, shown but never counted in a level; preprints come in as early signals; the pilot covers both general literature and long COVID without ME/CFS mention.

This does not displace STATUS priority 1 (live check of the weekly pipeline). Part A and B touch the fetch step, so they are done after that live check has passed.

## Principles (apply to all three parts)

1. **Indirect evidence never moves a `level`, a badge, a contested mark or a link's `support` step.** The rubric (functional spec section 3) requires an ME/CFS cohort with a recognised case definition; that is unchanged. Indirect means: the population was not selected by an ME/CFS case definition.
2. **Question-driven, not exploratory.** Every bridge search starts from a question written down before the search is run. No open-ended mining for "new connections", no co-occurrence score, no ranking (consistent with the gaps page ruling of 2026-11-08).
3. **Reproducible searches.** Query text, database, filters, run date and hit counts are stored. A search with no relevant hit is recorded as such; a null is a result.
4. **Framed as a question, never as a finding about ME/CFS.** Fixed wording, for example: "Reported in other conditions (systematic review, population: …). Not studied in ME/CFS." No "promising", "suggests that ME", "should be studied", and none of the gaps page's banned words.
5. **No treatment advice.** A review about an intervention in another condition is described only as evidence on the mechanism; no therapy is named as an option for ME/CFS.
6. **Credibility rules as always:** every record is fetched and cached before it is cited; every extracted statement keeps its source id and a verbatim quote.

## Part A: query recall check

Mechanical, no AI.

1. **Cited-but-not-found sample.** List every study id cited in `drafts/` that the query in `config/pubmed_query.txt` does not return (those fetched with `pubmed fetch --ids`). For each, record from the cached record why it is outside: a legitimately non-ME source (a `context` review, a case definition paper) or an ME/CFS paper the query should have caught, and which title/abstract term would have caught it.
2. **Candidate terms.** For each candidate term, count on live PubMed the records matching `term[Title/Abstract] NOT (current query)`. Start list (extend from step 1): "CFS/ME", "post-viral fatigue syndrome", "postviral fatigue syndrome", "post-infectious fatigue syndrome", "chronic fatigue immune dysfunction syndrome". The terms are candidates to test, not known gaps.
3. **Precision sample.** For each term with added records, fetch up to 20 of them (the most recent) and note per record whether it is about ME/CFS, from title and abstract. A term is proposed for the query when most of its sample is about ME/CFS; the founder approves the query change in the PR.
4. Record the counts, the sample and the outcome in `docs/fetch.md` under "The query, and why", and change `config/pubmed_query.txt` in the same PR if any term is accepted. If nothing is missed, say so there.

New code: at most a small `pubmed` subcommand (for example `pubmed query-diff --term …`) that prints the count and writes the sample ids; reuse the existing client, cache and rate limiting.

## Part B: preprints as early signals

1. **Source.** Europe PMC indexes preprints; search it with the ME/CFS terms of block 1 of the PubMed query, restricted to preprints, by first-indexed date. Check the exact source filter and the field that links a preprint to its published version against the live Europe PMC documentation on the first run, and record both in `docs/fetch.md`. Cache raw responses under `data/cache/europepmc/` like the existing lookups.
2. **De-duplication.** A preprint whose published version is in PubMed is dropped in favour of the published record. A preprint already on a card whose published version later appears is flagged in the weekly run for replacement (a draft operation; the study's role is then re-decided as for any new paper).
3. **Card format.** One new optional study field `preprint: true` (id is `doi:…`, already allowed). New validator rule: a study with `preprint: true` may only have `role: early_signal`, and may not appear in the sources of `level_reason`, `contested.reason`, a badge reason or a link. So a preprint cannot raise or contest a level, set a badge or carry a link, whatever it found.
4. **Citation check.** Extend the mechanical check so a preprint's title, year and DOI are verified against the cached Europe PMC record (today's checks read the PubMed cache). Case definition quotes come from the preprint's abstract or, where Europe PMC has it, its full text; otherwise `unverified`.
5. **Display.** On the card, a preprint early signal carries a fixed label (i18n string, both languages): "Preprint: not peer reviewed." No change to the front page, the map or the gaps page.
6. **Pipeline.** `pipeline fetch` gains the preprint search as a second source; `paper-classifier` and `card-drafter` get one sentence each in their prompts: a record marked preprint can only be proposed as an early signal. Review tier: tier 2 (founder approves) until the founder rules otherwise.
7. **Live check.** One run over the last 90 days: report the number of preprints found, how many survive de-duplication and how many the classifier assigns to a card. If the volume is more than the weekly review can absorb, stop and report before anything is drafted.

## Part C: bridge search pilot

A pilot at manual scale. It produces a report; it does not change cards, the site or the weekly pipeline.

### Protocol (written and committed before any search is run)

File `docs/pm/bridge-pilot.md`, section "Protocol":

1. **Questions.** Eight relations A → B:
   - five chosen by the founder from "Links not yet tested in patients" in `uv run python -m me_atlas.map report --drafts` (links at step `proposed`), preferring pairs where both ends are measurable quantities;
   - one **positive control**: a link already at step `associated`, where a review outside ME/CFS is expected to exist;
   - two **base-rate pairs**: card pairs with no link in either direction, drawn at random by a seeded script. They show how often the method returns a hit for an arbitrary pair; if it returns hits for those as readily as for the five, a hit carries little information, and the report must say so.
2. **Search terms.** For each end of each relation, the MeSH headings and title/abstract terms, taken from `config/card_themes.yaml` where the card has them.
3. **Two arms per question**, both on PubMed:
   - **General:** (A terms) AND (B terms), humans, publication type systematic review or meta-analysis, NOT the ME/CFS block of the query.
   - **Long COVID:** (A terms) AND (B terms) AND the long COVID block, NOT the ME/CFS block; same publication types. The count of original studies in this arm is recorded as a number only.
4. **Screening limit.** All records are screened when an arm returns 40 or fewer; above that, restrict both ends to MeSH major topic and screen the 40 most recent, recording the total. The limit is part of the protocol and is not changed after the first search.
5. **What is extracted per record:** does the review make a statement on the relation A → B in humans (yes / no / only in animals or cells); the population; the direction; whether it is a meta-analysis and the number of studies pooled, as the record states; the verbatim sentence. Review quality is **not** graded: the project has no published criteria for that, and none are invented here. The report states this limitation.

### Execution

1. Code: a `survey bridge` subcommand that reads the protocol's queries (a YAML file under `config/`), runs them through the existing PubMed client, caches the records, and writes one context file per question and arm plus the hit counts into `data/pipeline/<date>-bridge-pilot/`. Offline tests with recorded fixtures.
2. A new agent `.claude/agents/bridge-surveyor.md`, modelled on `hypothesis-surveyor`: reads one context file, writes one JSON file with the fields of protocol point 5, each row keyed by PMID. It works from abstracts; it does not propose links, levels or card text.
3. Code validates the JSON: every PMID is in the context file, every quote is found verbatim in the cached record.
4. `card-reviewer` (fresh context) checks every "yes" row against the cached record: is the statement about humans, about this relation and this direction, and is the population stated correctly.
5. Report in `docs/pm/bridge-pilot.md`, section "Results": per question and arm, the query, the counts, and one outcome: *reported in other conditions* (with sources, populations and quotes), *mixed*, *only animal or cell evidence*, or *no review found*; then the positive control and base-rate results, drafter/reviewer disagreements, and the limitations (abstract-only screening, review quality not graded, publication bias, a relation shown in one condition need not hold in ME/CFS).

### How the pilot is judged (fixed in the protocol)

- The positive control returns at least one verified review. If not, the method is not working and the rest is not interpreted.
- The base-rate pairs return clearly fewer verified hits than the five questions. If not, see protocol point 1.
- The reviewer rejects no more than about one in five "yes" rows. More means abstract screening is too unreliable to scale.
- The founder reads the five results and rules whether they are useful enough to show; ideally one researcher or Science for ME reader is asked the same.

## Follow-up, not this plan: showing indirect evidence

Only after the pilot is judged, as its own plan. Agreed direction, so the pilot's output fits it later:

- On a link: an optional sourced note beside the step ("reported in other conditions; not studied in ME/CFS"), which leaves `support` unchanged.
- On a card: a separate, clearly headed list of indirect sources, outside `level_reason`.
- A study field for the population (for example `cohort: other`) and a validator rule mirroring the preprint rule: indirect sources cannot support a level, a contested mark, a badge or a link step.
- Long COVID: studies whose cohort was also selected by an ME/CFS case definition count as today; long COVID studies without one are indirect.

## Documents to update

- `docs/fetch.md`: recall check results; the preprint source.
- `docs/card-format.md`: the `preprint` field and its validator rule.
- `docs/citation-check.md`, `docs/pipeline.md`: preprint handling.
- `docs/ME-Atlas-functional-spec.md` section 3: one paragraph on preprints (early signal only) and one on indirect evidence (principle 1), and section 6: the review tier for preprints.
- `docs/survey.md`: the `bridge` subcommand and the agent.
- `docs/pm/bridge-pilot.md`: protocol, then results.
- `docs/pm/STATUS.md` and `docs/pm/DECISIONS.md` as parts land.

## Contract ("done" is)

Each part is its own PR and can be accepted on its own.

**A**
1. `docs/fetch.md` lists every cited study outside the query with the reason, and every candidate term with its added-record count and precision sample.
2. The query is changed only for terms the founder accepted in the PR; `docs/fetch.md` states the hit count before and after.

**B**
3. A study with `preprint: true` and any role other than `early_signal`, or cited in a level reason, contested reason, badge reason or link, fails `cards validate`; offline tests cover each case.
4. The citation check passes a correctly cited preprint and fails one with a wrong title, year or DOI, from recorded Europe PMC fixtures.
5. A preprint whose published version is in the PubMed cache is not offered to the classifier (test).
6. The card page shows the fixed preprint label in English and Norwegian; no other page changes.
7. The live check's counts are reported to the founder before any preprint is drafted onto a card.

**C**
8. The protocol section of `docs/pm/bridge-pilot.md`, with all eight questions, terms, both queries per question and the judging criteria, is committed before the first search; the git history shows it.
9. `survey bridge` runs offline in tests from fixtures, caches records, and writes context files and hit counts; the JSON validator rejects an unknown PMID and a quote not found in the record.
10. Every "yes" row in the results has a PMID, a verbatim quote and a `card-reviewer` verdict; every question and arm has an outcome, including "no review found".
11. Nothing in `cards/`, `drafts/`, `content/` or the site templates changes in part C. No level, badge, contested mark, layer or link is touched.
12. The results use the fixed framing (principle 4) and contain no treatment suggestion.

**All**
13. Tests never touch the network or an LLM; `ruff check`, `ruff format` and `pytest` clean; no new dependency.

## Out of scope

- Broad ingestion of non-ME literature (whole mechanism fields, all long COVID papers) into the weekly pipeline.
- Any automatic discovery score, co-occurrence ranking or "new connection" detector.
- Changing a level, badge, contested mark or link step on the strength of a preprint or indirect source.
- Card format and site display for indirect evidence (the follow-up plan above).
- Trial registries (ClinicalTrials.gov), Embase, Scopus, conference abstracts, forums and other grey literature.
- Grading the quality of reviews found in the pilot.
- Original studies outside ME/CFS (the pilot reads reviews and meta-analyses only).
- Moving anything into `cards/`.

## Founder ruling needed before implementation

- The five pilot questions (chosen from the map report when part C starts).
- Review tier for preprint early signals. Default: tier 2, founder approves each, until a later ruling.
- Whether a preprint with a null result may be shown. Default: yes, as an early signal with the same label; it cannot contest a level.
