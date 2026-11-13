# Weekly pipeline

How new papers reach the draft cards. Plan: `docs/plan-weekly-pipeline.md`. Code: `src/me_atlas/pipeline.py` (the steps code can do) and `src/me_atlas/operations.py` (what the drafter may change). Rules: functional spec section 6.

If this page and the code disagree, the code is right and this page is a bug.

## How to run it

In a Claude Code session in the repository, type:

```
/ukentlig                          # the last 14 days
/ukentlig --since 2026-10-01       # a longer window
/ukentlig --no-pr                  # everything except pushing and opening the pull request
```

The command (`.claude/commands/ukentlig.md`) drives the stages below. AI work is done by subagents on the subscription (table under "Agents and models"): no API key and no `anthropic` calls. A change is applied only when the mechanical checks passed, the review agent accepted it and, for a tier 2 change, the auditor accepted it (spec section 6). The result is a pull request; the founder merges it as an operational step, without reviewing the content. During the trial period (the first four weekly runs) the founder reads the auditor decisions in the report after the fact; a ruling in `docs/pm/DECISIONS.md` ends it. Moving the first cards into `cards/` is a separate step (the plan's step 6) that is not built yet; until then a pair is applied to the card file the pipeline works on, which is a draft in `drafts/`.

## Stages

| # | Command | Who | Output in `data/pipeline/<date>/` |
| --- | --- | --- | --- |
| 1 | `prepare [--since] [--reprocess]` | code | `papers.json` (papers in the fetch window that no earlier run processed, and preprints that survive de-duplication), `cards.json` (slug, name, core claim), `prepare.json` (counts, newly retracted PMIDs cited on a card, the preprint counts and every dropped preprint with its reason, cards that cite a preprint with a published version) |
| 2 | `paper-classifier` agent, then `record-classification` | haiku, code | `classify.json`, then `matches.json` (card/paper pairs to draft, papers stopped, possible new hypotheses) |
| 3 | `context <slug> <key>`, then `card-drafter` agent | code, sonnet | `context/<slug>-<key>.md`, `ops/<slug>-<key>-r<N>.json` |
| 4 | `apply <slug> <ops> [--round N]` | code | `checks/...-r<N>.json`, `applied/<slug>-<key>-r<N>/<slug>.yaml` and `changes.diff` |
| 5 | `card-reviewer` agent (pipeline mode), then `record-review <slug> <key> [--round N]` | opus, code | `review/<slug>-<key>-r<N>.json` |
| 6 | `audit-plan <slug> <key>`, then `auditor` agent, then `record-audit <slug> <key>`; then `audit-sample [--seed S]`, a second `auditor` agent per sampled pair and `record-audit <slug> <key> --second` | code, opus, code | `audit-context/<slug>-<key>.md`, `audit/<slug>-<key>.yaml`, `audit-sample.json`, `audit/<slug>-<key>-second.yaml` |
| 7 | `translation-plan [--lang nb]`, then `card-translator` agent, `card-reviewer` agent (translation mode) and `translations apply` | code, sonnet, opus, code | `final/<slug>.yaml`, `translate/<slug>.json`, `translation-plan.json`, `translated/<slug>.json`, `translation-review/<slug>.json`; writes `translations/nb/<slug>.yaml` |
| 8 | `report` | code | `report.md` |
| 9 | `pr [--dry-run] [--no-pr]` | code | writes the applied results to the card file (`drafts/<slug>.yaml`, or `cards/<slug>.yaml`), change-log entries and `last_checked` for a card in `cards/`, copies valid audit records into `audits/`, branch `pipeline/<date>`, commit, push, `gh pr create` with `report.md` as the description (a report over GitHub's 65,536-character limit is split at `## ` headings into `report-part-k.md`: part 1 is the description, the rest are `gh pr comment`s) |

`log.jsonl` in the run directory records each `prepare`, `apply`, `record-classification` and `record-review` call. The whole directory is gitignored (`data/pipeline/`); the audit records that matter are copied into `audits/` by `pr`, and the consistency count is in the report.

By default each command after `prepare` works on the newest run in `data/pipeline/`: the newest folder whose name is exactly a valid ISO date (`YYYY-MM-DD`) and which holds `papers.json`. A folder with any other name (`2026-11-13-livecheck`, `nb-first-run`) is never chosen by default; if no folder qualifies the command stops with a message naming `--run-dir`, which takes any folder. Options on every command: `--run-dir`, `--pipeline-dir`, `--cards-dir`, `--drafts-dir`, `--cache-dir`, `--spec`, `--translations-dir`, `--audits-dir` (default `audits`). `prepare` also takes `--date` (the name of the run directory, default today) and `--force` (start a run of the same date again).

## What `prepare` selects

The papers in the fetch window (`window_pmids` of the run manifest, cached or not) that no earlier run has processed, minus any that are marked retracted. "Processed" is kept in a ledger, `data/pipeline/processed.json` (gitignored, shared by all runs: PMID to the date of the run). Only `report` writes to it, so a run that is aborted before `report` can be repeated and selects the same papers again. `prepare --reprocess` ignores the ledger. `prepare` prints how many papers it selected and how many it skipped as already processed. Retracted papers are never selected, and a newly retracted paper that a card cites is still flagged whatever the ledger says. A newly retracted paper that a card cites is listed in the report; it is the founder's decision how the card changes (spec section 3: a retracted study is removed from the evidence and the level re-assessed).

### Classifying an explicit list of PMIDs

`prepare --ids PMID [PMID ...]` (or `--ids-file PATH`, one PMID per line, a `pmid:` prefix allowed, blank lines and `#` comments ignored) replaces the fetch window with the given ids. It is mutually exclusive with `--since`. Only the listed ids that are not in the cache are fetched, through the same injected fetch as `pubmed fetch --ids ... --cache-dir ...` (nothing is fetched when all are cached), and `papers.json` holds exactly the listed records whatever their entry date. The ledger and retraction rules are those of a window run: an id already processed is skipped unless `--reprocess`, a retracted record is excluded (`excluded_retracted`) and an id whose record is missing or unreadable is listed in `unreadable_records`. No preprint search is made. `prepare.json` records `"mode": "ids"` and the `ids`; `preprints.searched` is false, and the report header says the papers were given by id (not a fetch window) and that no preprint search was made. Everything after `prepare` is unchanged.

Use it for papers the query does not return. For the 9 "CFS/ME" records found by the recall check (`docs/fetch.md`), take the ids from the `sample_pmids` of the term "CFS/ME" in the newest `data/cache/query-diff/*.json` that has it, put them one per line in a file and run `prepare --ids-file <file>`. They are cached already, so nothing is fetched.

## Preprints

`prepare` (in window mode) also searches Europe PMC for preprints first indexed in the same window (`config/europepmc_preprint_query.txt`; the facts about the API and the cache are in `docs/fetch.md`, "Preprints (Europe PMC)"). The search is a function that tests inject, like the PubMed fetch; a failed search fails `prepare` before anything is written. Each preprint is dropped for the first matching reason, and `prepare.json` lists every drop under `preprints.dropped` (PPR id, DOI, reason and details) with `preprints.counts` (found, dropped per reason, offered):

| Reason | Meaning |
| --- | --- |
| `published` | it has a "Preprint of" link to a PubMed record (the PMID, whether it is in the PubMed cache, and the link's note are listed) |
| `in_pubmed` | its DOI (case-insensitive) is the DOI of a record in this run's PubMed window or in the PubMed cache |
| `superseded` | a higher version, whose PPR id is in the same search, exists |
| `duplicate_doi` | several records share this DOI (case-insensitive); the one with the highest version number, then the highest PPR number, is kept and the others are dropped (judged after `published` and `in_pubmed`; the row names the one kept) |
| `no_doi` | no DOI, so it cannot be cited |
| `processed` | the ledger has its PPR id (unless `--reprocess`) |

Survivors are added to `papers.json` after the PubMed papers: `id` `doi:<doi>`, `pmid` null, `preprint` true, `ppr_id`, `journal` the preprint server, `publication_types` ["Preprint"] and `entry_date` the first index date. Every PubMed paper also has `preprint` (true for a PubMed record with the publication type "Preprint", such as pmid:42996068; that record keeps its PMID and flows as any other paper). The ledger holds a preprint under its PPR id, in the same file; PMIDs come first, in numeric order, so a ledger written before preprints reads unchanged.

A classification names its paper by exactly one of `pmid` or `id` (`doi:<doi>`, for a preprint with no PMID); both, neither, an unknown id, a repeated paper and a missing paper are rejected. A DOI-only preprint that matches a card goes into `matches` as `{slug, id}` (a PubMed pair is `{slug, pmid}`) and is drafted, checked and reviewed like any other pair, with the differences below. A preprint that PubMed also holds is a PubMed paper; its context file says it is a preprint and that it can only be added with `preprint: true` and `role: early_signal`.

**The paper key.** Every file of a pair is named `<slug>-<key>…` (`context/`, `ops/`, `checks/`, `review/`, `applied/`). The key is the PMID digits for a PubMed paper (unchanged) and the PPR id (`PPR<digits>`) for a DOI-only preprint, read from `papers.json`. `context`, `apply` and `record-review` take the paper as `<pmid>`, `pmid:<pmid>`, `doi:<doi>` or the PPR id and resolve it against this run's `papers.json`; a `doi:` or PPR id that is not a DOI-only preprint of this run is an error naming it. In an ops file and a review file the paper is `doi:<doi>`.

**Context for a DOI-only preprint.** Built only from its cached Europe PMC record (`europepmc preprint <doi>` caches it; without it `context` stops and names the DOI and that command): id, Europe PMC id, title, server, year, first index date, version, abstract (HTML tags removed), the preprint rule, and the note that the case definition comes from the abstract or the full text, otherwise `unverified`. Full text goes through `get_fulltext(..., preprint=record)` with the same status notes as for a PubMed paper, and the same case-definition sentence lists when there is text.

**Apply, review, report.** An ops file whose `paper` is `doi:<doi>` is checked like any other (validator including V15, citation check against the cached preprint record: C1, C2, C3, C5, C6); its `add_study` must have `preprint: true`, and every operation in it is tier 2. `record-review` expects `paper: "doi:<doi>"` for that pair. The report links the paper to `https://doi.org/<doi>` with the title from the cached record. Conflict parking and the final card text treat the pair as any other.

A study marked `preprint: true` on a card or draft whose cached preprint record (or this run's search result) has a "Preprint of" link is listed in `prepare.json` under `preprints_published` and in the report under "Preprints on cards with a published version". No operation is written; the founder decides.

**Tier 2.** An operation that adds a study with `preprint: true`, or cites a study marked `preprint: true` (on the card or in the same file) in its sources, is tier 2; so is every operation of an ops file whose paper is a `doi:` preprint (the auditor decides). `apply` counts it in `tiers` and the report lists it under tier 2.

## The context file

`context/<slug>-<pmid>.md` is the only thing the drafter and the reviewer read about the paper. It holds six sections, numbered 1 to 6 with no number repeated: (1) the card as it is now; (2) the inclusion rule (spec section 2); (3) the rubric, the evidence ladder (spec section 3); (4) the paper's PubMed record (or, for a DOI-only preprint, its Europe PMC record) with an `- authors:` line (the record's authors in record order, or `not stated`; the drafter takes the names in `group` only from it) and the abstract; (5) the Europe PMC full text when the paper has open full text, without its reference list; (6) sentences from the full text, in two lists under their own labels: sentences that may name a case definition, and sentences that may exclude people with the illness (an exclusion wording together with ME/CFS, CFS or the illness's full name). The second list tells the reader to check whether ME/CFS itself was what the study excluded. The spec excerpts keep their text, but their headings are one level lower, so the only level-2 headings are the six above. If the spec has no section 2 followed by section 3, `context` stops with a message. "Oxford" in a sentence counts as a case definition only when it is not an affiliation, publisher, place or vendor ("University of Oxford", "Oxford University Press", "Oxford, UK", "Oxford Instruments").

The full text note depends on what Europe PMC gave. The PMC id from the cached PubMed record is passed on, because Europe PMC can lack it for a while. `open_access`: the XML has a real body and is used. `pdf_only`: a PMC record exists (with its id), but its full text is a PDF only and it was not read; nothing is cached. `pmc_no_xml`: a PMC record exists (with its id) and Europe PMC has no full-text XML for it. With no PMC id anywhere the file says there is no open full text. A cached lookup that found no open full text is asked again after 7 days (`LOOKUP_MAX_AGE_DAYS`). No PDF is ever downloaded or parsed. The full text is cut at `FULLTEXT_CHAR_BUDGET` (60,000 characters, a constant in `pipeline.py`); the file says `TRUNCATED` with both numbers when it cuts, and says so when there is no full text. It contains nothing the drafter wrote.

## Operations

The drafter writes a list of operations, not a card (`operations.py`). All keys are checked; an unknown key, an unknown field name, a duplicate study id, a paragraph index out of range or an `add_study` without a case-definition quote for a recognised definition is rejected with a message, and nothing is changed.

| Operation | Tier | What it does |
| --- | --- | --- |
| `add_study` | 1 (2 with `preprint: true`) | Appends a study (all Study fields; the id must be the paper itself). `preprint` is written only when true. |
| `add_paragraph` | 1 (2 if it cites a preprint study) | Appends a sourced paragraph to `level_reason`, `contested.reason`, `badges.*.reason`, `subgroups` or `early_signals`. |
| `replace_paragraph` | 1 (2 if it cites a preprint study) | Replaces paragraph `index` of such a field. |
| `propose` | 2 | Sets the level, the contested mark or a badge, with the complete new reason. |

**How operations are applied.** As text splices, not through a YAML library, because round-tripping would lose this repository's comments and folded text. Only the lines of the named field are replaced or inserted; every other line stays byte-identical. After each operation the edited text is parsed again and compared with the same change made on the parsed data; any difference stops the run. Limits: a field written in flow style on one line, and CRLF line endings, are refused with a message; comments inside a field that is rewritten (a `propose` reason, one replaced paragraph) are lost, comments elsewhere stay. Adding a paragraph to a reason written as a single sourced text turns it into a list of two paragraphs, keeping the first one's words.

## Checks and the two rounds

`apply` never touches `drafts/`. It applies the operations to a copy, then runs the card validator (`cards validate`) and the citations check (`citations check`) on that copy and writes both results. A citation error that the card already had before the change is marked `preexisting` and does not fail the pair; warnings (C6) never do, with one exception: a new (not `preexisting`) C9 warning (the study's `group` names no author of the record, see `docs/citation-check.md`) fails the pair and counts in `citation_errors`, so a drafter cannot add an author name the record does not support. A "TODO" in the name, a sourced text or a study's `finding` fails the pair through the validator rule V14. `group` stays optional, but when every study already on the card has a `group` and an added study has none, `apply` adds one line to the `warnings` list of the checks record for that study and prints it as `warning: ...`. A warning never changes `passed` or the exit code. It is shown in the report next to the reviewer notes of an accepted pair. Because the copy sits alone, a link from it to another card (rule M2) is resolved against the card files in `--drafts-dir` and `--cards-dir`; a link to a slug found in neither fails the check.

- A failed check: the drafter gets one retry with the errors. Still failing: the pair is skipped and the report says why.
- A passed check goes to the reviewer. The reviewer reads the context file, the operations and the applied result, never the drafter's reasoning (the operations file has no field for any).
- The reviewer gives every finding a severity. `must_fix`: wrong against the sources, the rubric or the checklist; a TODO or internal note in reader-facing text; a field missing that the card's other studies have; a study outside the card's scope; a missing limit that changes how a reader would read the result. `advisory`: wording that does not change meaning. Any `must_fix` means `reject`; `record-review` refuses an `accept` with a `must_fix` finding. A `reject` with only advisory findings is allowed.
- Reviewer says `reject`: the drafter gets one revised attempt (round 2) with the review. Rejected again, or the second attempt cannot pass the checks: **parking lot**. The change is not applied, is never sent to the auditor (no AI step overrides a review rejection) and is listed under disputes in the report. Never a third round. If round 2 passes the checks with no operations after a rejection in round 1, the drafter has withdrawn the change: the pair is `withdrawn`, not `no_change`, and the report keeps the reviewer's findings and what was proposed in round 1. Nothing is applied for it, and `pr` and `translation-plan` write nothing for it. A review file may carry an optional `not_on_card`, one non-empty line: the reviewer's reason to list the paper in the card header's "Not on the card" list (set when a `must_fix` finding says the study is outside the card's scope or stated exclusions). `record-review` refuses an empty string. The report prints it on its own line for the pair.
- `accept`: a pair with only tier 1 operations goes into the pull request; a pair with a tier 2 operation goes to the auditor first (next section). If two papers that may be applied touch one card, `pr` applies their operations in turn to the draft and validates the combined result. If two accepted papers overwrite the same target (the same `replace_paragraph` field and index, or the same `propose` target), neither is applied and both go to the parking lot; other papers on the card are still applied. A pair the auditor did not accept does not count in this comparison.

## The audit

The `auditor` agent decides every tier 2 change (spec section 6, steps 6 and 7). Code: `build_audit_context`, `validate_audit_record`, `audit_sample` and the gate in `collect_outcomes` in `src/me_atlas/pipeline.py`. Contract decisions D1 to D6 are in `docs/pm/DECISIONS.md` (2026-11-13).

**Who is audited (D1, D2).** Every pair whose final round passed the mechanical checks, was accepted by the reviewer and contains at least one tier 2 operation. A pair with only tier 1 operations is applied on the checks and the review and is not audited. A parked pair (rejected twice, or failed the checks after a rejection) is never sent to the auditor and never applied; the report lists it under disputes. The decision covers the whole operations file: anything but `accept` means none of its operations is applied.

**`audit-plan <slug> <key>`** writes `audit-context/<slug>-<key>.md`, the only file the auditor reads: (1) the diff of the last round (`changes.diff`), (2) the card as it stands, (3) the cached records of every study the card or the applied card cites (title, authors, year, abstract, and the full text where cached, cut at `AUDIT_FULLTEXT_CHAR_BUDGET` characters per record with the cut stated; a study with no cached record is named under "Not cached" and cannot be cited), (4) functional spec section 2, (5) section 3, (6) `docs/card-format.md`. It contains nothing the drafter or the reviewer wrote, and no earlier audit. The card in it (section 1 of a whole-card audit, section 2 of a change audit) and the diff have their YAML comments removed: the card is parsed and dumped again (`strip_yaml_comments`), and the diff is built from the comment-free base and applied texts, not read from `changes.diff`. Why: comments in a draft carry earlier drafter and reviewer reasoning and earlier rulings, which the auditor must not see. Parsing drops full-line and trailing comments and keeps a `#` that is part of a value. The dumped card is therefore in a stable form that can differ from the file in line wrapping and quoting; its content is the same. `audit-plan --card <slug> [--out DIR]` does the same for a whole card (the card file takes the diff's place) and writes `<DIR or RUN>/audit-context/<slug>.md`.

**`record-audit <slug> <key>`** validates `audit/<slug>-<key>.yaml` (`--second`: `...-second.yaml`; `--card <slug> --file PATH [--out DIR]` for a whole card). The record has `card`, `paper` (left out for a whole card), `decision` (`accept`, `reject` or `accept_lower`), `accepted_level` (required for and only for `accept_lower`, 0 to 5 and lower than the proposed level, or the card's level for a whole card), `parts` (a non-empty list of `decision_part`, `rubric` and `evidence`, a list of `source` and `quote`), `reasons_summary` (one line, shown in the report) and `would_change`. It is rejected when: a `source` is not a record in the context file; a `quote` is not found word for word in that source's cached record (title, abstract or full text; the same narrow normalisation as the citation check: Unicode NFKC, whitespace collapsed, curly quotes and dashes read as straight, nothing else); a part has no `rubric`, or its `rubric` is shorter than 20 characters after normalisation or not found word for word in functional spec section 2 or 3 (D5); `accept_lower` has no `accepted_level` or one that is not lower; the decision is unknown; the card or paper differs from the pair.

**`audit-sample [--seed S]`** writes `audit-sample.json` (the seed and the pairs): every audited pair with a `propose` on `level`, plus one in five of the other audited pairs (rounded up when there are any), chosen with `random.Random(seed)`. The seed is the run date string unless `--seed` is given (D6). Each sampled pair is audited a second time by a fresh auditor (`audit/<slug>-<key>-second.yaml`). A level change needs the second audit even if `audit-sample.json` is missing.

**The gate (conservative apply).** A pair is applied (`Outcome.applied`) only when: its last round passed the mechanical checks; the reviewer accepted it; and, if it has a tier 2 operation, a valid first record says `accept` and, if the pair is sampled, a valid second record also says `accept`. Not applied, and the card file unchanged: `reject`; `accept_lower` (D3: never applied automatically, because the auditor writes no card text; the report lists the level the auditor accepts); a missing or invalid record (the report says why); a second verdict that differs from the first (counted, and listed as a dispute). A redraft at the lower level goes through the normal drafting path at most once; how that is done is decided with the first publication or in a later run.

**What `pr` writes (D4).** The applied operations go to the card's base file, as `_base_card` picks it: `cards/<slug>.yaml` when that is the card in use, else `drafts/<slug>.yaml`. For a target in `cards/`, `pr` appends one entry per applied pair to `cards/changelog.yaml` with `decided_by: ai_audit` (audited; `reason` is the auditor's `reasons_summary`) or `ai_pair` (tier 1 only), and an audited change sets `last_checked` to the run date with `by: ai_audit`; a tier 1 only change leaves `last_checked` as it is. Every valid audit record of the run, rejects included, is copied to `audits/<date>-<slug>-<key>.yaml` (`...-second.yaml` for the second run; a whole-card record in `audit/<slug>.yaml` becomes `audits/<date>-<slug>.yaml`) and staged in the same commit. A commit with only audit records and no card change is possible. Nothing is written to `cards/` today: the cards are still in `drafts/`.

## Agents and models

Every subagent in `.claude/agents/` and the model its frontmatter names:

| Agent | Model | Tools | Role |
| --- | --- | --- | --- |
| `paper-classifier` | haiku | Read, Write | classifies new papers |
| `card-drafter` | sonnet | Read, Write | drafts operations for one pair |
| `card-reviewer` | opus | Read, Glob, Grep, Bash, WebFetch, Write | reviews a draft; also translation and map modes |
| `auditor` | opus | Read, Write | decides tier 2 and tier 3 changes |
| `card-translator` | sonnet | Read, Write | translates card text to Norwegian |
| `link-drafter` | sonnet | Read, Write | proposes a card's layer and links |
| `hypothesis-surveyor` | sonnet | Read, Write | assesses candidate hypotheses from the survey |
| `worker` | sonnet | Read, Edit, Write, Glob, Grep, Bash | implements a contract (development) |
| `evaluator` | sonnet | Read, Glob, Grep, Bash | grades a diff against a contract (development) |

`card-reviewer` and `auditor` both run on Opus. Their independence therefore lies in what the auditor is shown (the diff, the card, the cited cached records, the rubric and the card format, and nothing the drafter or the reviewer wrote), not in the model: the auditor shares a model family with the agents it audits and may share their blind spots. The consistency check (a second auditor on a sample of decisions) measures how often two audits of the same change disagree.

## Translations

Stage 7, after the audit and before the report, keeps the Norwegian text in step with the accepted English changes. Details, file shapes and the checks are in `docs/translation.md`. `translation-plan` takes each card with an accepted change and a file in `translations/nb/`, builds the card as it will be after the change (`final/<slug>.yaml`) and lists, in `translate/<slug>.json`, the items that need translating: `made_stale` (the English of a translated item changed), `new` (the change added the item), `already_stale`, `already_missing` or `already_invalid` (not caused by this run). A card with no translation file is listed under `untranslated_cards` and not planned: its first translation is a manual run. The translator writes `translated/<slug>.json`; the reviewer writes `translation-review/<slug>.json` without seeing the translator's reasoning; `translations apply` merges what passed the mechanical check and the review into `translations/nb/<slug>.yaml`; one second attempt for what was left out; the rest stays English on the site with a note. Before `pr`, `translations check --overlay RUN/final` checks the sidecars against the final cards (they are not in `drafts/` until `pr` copies them). `pr` stages `translations/` with the drafts. A translation carries no level, badge or contested mark, so none of this is a tier decision.

## Reading the report

`report.md` (also the pull request description), in this order:

1. **Tier 2**, decided by the auditor: the applied level, contested mark or badge changes, and anything that adds or cites a preprint, each with the new reason, sources, the review verdict and the audit decision. A tier 2 pair the auditor did not accept is not here; it is under "Auditor decisions" and "Disputes".
2. **Tier 1**: added studies and paragraphs, applied on the checks and the review.
   **Auditor decisions** (after the tier lists): each audited pair with its decision, the one-line `reasons_summary` and, for a sampled pair, the second decision; the line "Consistency check: N of M sampled decisions decided a second time; K differed" (always present when anything was audited, K = 0 included); a pair with no valid audit record is listed as not applied. **Disputes (card unchanged)**: parked pairs, audit rejects, `accept_lower` (with the level the auditor accepts) and differing second verdicts.
3. **Parking lot**: changes still rejected after two rounds (not sent to the auditor), with the reviewer's findings (severity shown, `must_fix` first) and what the drafter proposed. Accepted changes show the reviewer's remaining notes with their severity in the same way, and any `group` warnings from `apply`. The parking lot also shows `not_on_card` when the reviewer set it.
4. **Rejected by the reviewer, then withdrawn**: pairs where round 1 was rejected and round 2 proposed nothing. For each: the round of the rejection, every finding of the rejecting review (severity shown, `must_fix` first, problem and suggested fix in full), what the drafter proposed in the rejected round, and the reviewer's `not_on_card` line when there is one. `None.` when there is no such pair. The summary sentence at the top counts these pairs on their own.
5. **Possible new hypotheses**: papers that fit no card. No card is drafted.
6. **Preprints on cards with a published version** (see "Preprints"). A preprint pair that was drafted is in the tier lists above, always tier 2.
7. **Retracted papers cited on cards.**
8. **Skipped**: failed checks, no operations file, no review, papers stopped as reviews or off-topic.
9. **Pre-existing problems on cards**: citation-check errors the card already had (they do not block a new paper).
10. A table of every new paper and how it was classified.

When stage 6 ran, a **Translations** section sits between the parking lot / new hypotheses and the retraction list: per card, the items made stale by accepted changes, the items the changes added and how many were already stale or missing, and the cards with no translation yet.

## `pr`

`pr --dry-run` prints the `git` and `gh` commands and the files it would write, and runs nothing. `pr` checks that the current branch is `main`, creates `pipeline/<date>`, writes the applied cards (see "What `pr` writes" under "The audit"), commits only those files, the change log and the audit records it wrote, and the `translations/` folder when there is one (the commit message ends with a blank line and `Co-Authored-By: Claude <noreply@anthropic.com>`, with no model named because the agents run on model aliases), pushes and runs `gh pr create --body-file report.md`. A report longer than 65,536 characters (GitHub's limit) is split into `report-part-1.md`, `report-part-2.md`, … at level-2 headings (at line boundaries inside a section that is too long by itself); part 1 becomes the description and each further part is posted with `gh pr comment`. `pr --no-pr` creates the branch and the commit and stops there. With no applied change and no audit record it does nothing. The `.githooks/pre-push` hook still forbids pushing to `main`.

## Tests

`tests/test_operations.py`, `tests/test_pipeline.py` and `tests/test_audit.py` (the audit steps, the gate and its byte-identical-card tests, the sample and the report sections), with fictional papers and agent outputs in `tests/fixtures/pipeline/`. The fetch, the preprint search, the full-text loader and the subprocess runner are injected; no test touches the network, an AI or git.
