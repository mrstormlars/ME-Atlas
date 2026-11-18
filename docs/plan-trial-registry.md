# Plan: registered ongoing studies per hypothesis (idea I-03, with I-15)

Agreed with the founder in a brainstorm on 2026-11-18. Follows the seven guidelines for ideas (DECISIONS 2026-11-17, "Idea bank"). To be handed to `/orchestrator`.

## Why

A researcher or funder who looks at a gap wants to know whether someone is already working on it. The cards show published studies only. Trial registries show what is under way.

## What was counted (ClinicalTrials.gov API v2, 2026-11-18)

Counts from the public API, by condition search; they are a sizing aid, not site content.

| Search | All | Ongoing | Ongoing, interventional | Completed |
| --- | --- | --- | --- | --- |
| ME/CFS ("chronic fatigue syndrome" OR "myalgic encephalomyelitis") | 222 | 53 | 37 | 114 |
| Long COVID (five terms) | 727 | 210 | 147 | 326 |
| Both together | 910 | 246 | not counted | not counted |

"Ongoing" is the four statuses recruiting, not yet recruiting, active not recruiting and enrolling by invitation. Of the 114 completed ME/CFS studies, 101 have no results posted in the registry; that says nothing about publication in a journal, which is why "no published result" is out of scope here.

## Founder rulings in the brainstorm

1. Long COVID studies are included if they are not far too many. The project manager's reading of the count: 246 ongoing studies is workable, on the condition in "The page" below that only studies matched to a card are listed.
2. Intervention trials are shown as well as observational studies.
3. Country and recruitment status are shown; they are neutral facts a patient can find anyway.
4. The step runs as part of the weekly run (`/ukentlig`), not as a separate command.

## Goal

A page on the site lists the registered ongoing ME/CFS and long COVID studies that bear on a hypothesis card, grouped by hypothesis, with every field copied by code from the registry record. Each card page shows how many such studies there are and links to its group. The list is kept current by the weekly run.

## Source rule for registry records (new source type)

To be written into `docs/ME-Atlas-functional-spec.md` and the methods text, in these terms:

- The only registry is ClinicalTrials.gov, read through its public API. Raw responses are cached in `data/cache/`; rate limits are respected.
- Every shown field (registry number, title, study type, status, countries, planned enrolment, start date, date the record was last updated) is copied by code from the fetched record. Nothing about a study is written by a model or from memory.
- A registered study is not evidence. It is never a study on a card, never a source of a level, badge, contested mark, layer or link, and it changes no file in `cards/`.
- The only AI judgement is which card or cards a study bears on. It is checked by the review agent before it is published.
- The list states facts. It does not recommend taking part, names no contact person, and says nothing about whether an intervention works.

## Design

1. **Fetch** (`src/me_atlas/`, new module): the condition search above, all statuses, with paging; cached. Verify the API parameters against the live API documentation, not from memory.
2. **Published data file** in the repository (for example `registry/trials.yaml`), because the site is built in GitHub Actions where the cache does not exist. One entry per study: the copied fields, the fetch date, and `hypotheses` (a list of card slugs, possibly empty). Code writes the copied fields; only the reviewed mapping fills `hypotheses`. A validator checks the file.
3. **Mapping step.** A subagent defined in `.claude/agents/` (the existing `paper-classifier` if its prompt fits a registry record, otherwise a new agent; settle in the contract) reads the registry record and the list of cards and names zero, one or more cards. The `card-reviewer` checks each mapping against the registry record. A rejected mapping is not published. No auditor: a mapping moves nothing on a card.
4. **Reliability test before anything is published** (guideline 3): run the mapping on all ongoing ME/CFS studies and a sample of 50 ongoing long COVID studies; the reviewer may reject at most one mapping in five. If it fails, the page is not published, and the session reports the reject reasons to the founder instead of patching the prompt more than twice.
5. **Weekly run.** `/ukentlig` gets a step that fetches registry records changed since the last run. Status, countries and enrolment of known studies are refreshed by code alone. A new study goes through mapping and review. A study that is no longer ongoing leaves the page and stays in the data file. Zero new records is a normal outcome.
6. **The page** (`trials.html`, `nb/trials.html`):
   - Intro, in the terms of the source rule: what the list is, that a registered study is not evidence, that the list is no invitation to take part and gives no treatment advice, the date of the last fetch.
   - One table per hypothesis that has at least one ongoing study, hypotheses sorted by name, rows sorted by registry number. Columns: registry number (link to the registry record), title as the registry gives it, study type (interventional or observational), status, countries, planned enrolment.
   - Studies matched to no card are not listed; the page gives their number and says they are in the downloadable data.
   - No ranking, no "recruiting now" list of its own, no contact details. No JavaScript requirement.
7. **Card page:** one line with the number of registered ongoing studies and a link to the hypothesis's table; nothing when the number is zero.
8. **Dataset** (I-05): the registry list is added to the downloads as its own CSV and to `me-atlas.json`, with the unmatched studies included.
9. **Strings and Norwegian:** site strings in `content/i18n/en.yaml` and `nb.yaml` through the translation path. Registry titles are shown as the registry gives them, in English, on both language versions.
10. **Documents:** `docs/pipeline.md`, `docs/site.md`, `docs/fetch.md`, the functional spec and methods text (source rule), `docs/pm/IDEAS.md` (I-03 and I-15), `docs/pm/STATUS.md`.

## Done

- The reliability test passed (at most one mapping in five rejected) and its numbers are in the pull request description; or it failed, nothing is published, and the report says why.
- Every field of every listed study equals the cached registry record (a mechanical check, run in the tests on fixtures and against the cache before publishing).
- No file in `cards/` or `translations/nb/` card content changes; no level, badge, mark, layer or link changes.
- The page contains no sentence about a study that is not the registry's own title, and no wording that invites taking part or judges an intervention.
- The numbers on the page, on the card pages and in the dataset agree.
- `uv run pytest` (offline, recorded registry responses in `tests/fixtures/`), `uv run ruff check .`, `cards validate` and `translations check` pass; the site builds in both languages.
- The `evaluator` returned PASS on the contract. One branch (`feat/trial-registry`), one pull request; the founder merges.

## Out of scope

- Completed studies with no published result. It needs each study matched against PubMed, and a wrong "unpublished" is an accusation against named researchers; it is its own round with its own reliability test.
- Other registries (WHO ICTRP, EU CTIS, ISRCTN and national registries).
- A separate list of recruiting studies per country, filters, search, contact details.
- Any use of a registry record as evidence on a card.

## Open points for the orchestrator to settle in the contract

- The exact long COVID search terms, checked against what the registry's own condition vocabulary returns.
- Which model the mapping agent runs on (the classifier runs on haiku today).
- How a study matched to several cards is shown (the plan assumes one row under each card).
