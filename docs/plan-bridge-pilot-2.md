# Plan: bridge search pilot 2 (tighter reading of the same records)

Follows `docs/plan-wider-sources.md` part C and the first pilot (`docs/pm/bridge-pilot.md`, 2026-11-16). Agreed with the founder in a brainstorm on 2026-11-17. To be handed to `/orchestrator`.

## Why

The first pilot's searches and controls worked: the positive control passed and the two base-rate pairs gave no accepted statement. Its reading did not: the reviewer rejected 9 of 21 `yes` rows (43%), against a limit of one in five, so by the protocol's own rule the method is too unreliable to scale. The rejections were of two kinds:

- 4 were wrong fields (`studies_pooled`, `meta_analysis`) on rows that were about the relation;
- 5 were substance: the quote was the review's background and not its finding, the record reported no finding, or a term was read more widely than the card means it (cytokines in blood read as neuroinflammation).

In addition, two accepted rows were records PubMed tags as Systematic Review that are not reviews of studies.

## Goal

Find out whether a tighter extraction brings the reviewer's reject rate to one in five or lower, **on the same eight questions and the same cached records**, so that the only thing that changes is the reading. The founder wants to map whether such findings exist, and to have something a medical reader can assess; this pilot decides whether the method is good enough to run on more links.

## What changes from pilot 1

1. **Same queries, same records.** `config/bridge_pilot.yaml` is run unchanged and the records come from `data/cache/bridge/` (re-fetched only if missing). No query tuning in this pilot: tuning would change the hits and hide whether the reading improved.
2. **Code fills what the record states.** `meta_analysis` comes from the PubMed publication types, not from the agent. `studies_pooled` is dropped from the extraction; it does not decide an outcome.
3. **The quote must be a finding.** For a structured abstract, code accepts a quote only from a section labelled as results or conclusions (the labels PubMed gives in `AbstractText`); the exact label list is fixed in the protocol. For an unstructured abstract the agent states `quote_role` (`finding`, `background` or `aim`), only `finding` can carry a `yes` row, and the reviewer checks it.
4. **Is it a review of studies?** A new field `review_kind`: `systematic` (the record itself describes a search or a number of included studies, or is a meta-analysis), `narrative`, or `not_a_review`. It is read from what the record says about itself, not from PubMed's tag alone. Only `systematic` rows count towards an outcome. `narrative` and `not_a_review` rows are listed separately as leads, with no outcome drawn from them.
5. **Each end has a written definition.** For every end of every question the protocol gives one or two sentences on what counts, taken from the card's core claim (for example: neuroinflammation means inflammation or glial activation in the brain or spinal cord, not cytokines measured in blood). The surveyor and the reviewer both get it.
6. **The reviewer's verdict has a reason code**, so the report can say what kind of rejection remains: `not_this_relation`, `not_a_finding`, `not_humans`, `wrong_population`, `wrong_direction`, `wrong_review_kind`, `other`.

## Steps

1. **Protocol first.** Add a section "Pilot 2: protocol" to `docs/pm/bridge-pilot.md` and commit it before any agent reads a record: the six changes above, the label list for point 3, the end definitions for point 5, and how the pilot is judged (below). Record the founder's go-ahead in `docs/pm/DECISIONS.md`.
2. **Code** (contract, `worker`, independent `evaluator`; tests offline with fixtures): `survey bridge run` writes the new context files (publication types, abstract sections with their labels, end definitions); `survey bridge validate` enforces the new schema and the quote rule; the `bridge-surveyor` prompt is updated. Pilot 1's files and results are not overwritten: a new run folder and a new results section.
3. **Run**, one agent at a time: a fresh `bridge-surveyor` per context file, then a fresh `card-reviewer` over every `yes` row. Neither sees pilot 1's rows or verdicts.
4. **Report** in `docs/pm/bridge-pilot.md`, section "Pilot 2: results": per question and arm the counts and the outcome from accepted `systematic` rows, the leads listed apart, the reject rate with its reason codes, and a comparison with pilot 1 (which accepted rows stayed, which went, which are new). The same fixed framing as before: reported in other conditions, not studied in ME/CFS, no treatment named as an option.

## How it is judged

- **Reviewer agreement:** at most one in five `yes` rows rejected. This is the test the pilot exists for. The number is reported whatever it is; it is not re-defined after the run.
- **Positive control** still gives at least one accepted `systematic` row with `relation: present`.
- **Base rate:** the two base-rate pairs still give clearly fewer accepted rows than the five (same criterion as pilot 1).
- **Nothing lost silently:** every row pilot 1's reviewer accepted is accounted for (kept, moved to leads, or dropped with the reason).

## Done when

- The protocol commit precedes the first agent run in the git log.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run python -m me_atlas.cards validate` and `uv run python -m me_atlas.site build` pass; the evaluator has passed the code against the contract.
- `docs/pm/bridge-pilot.md` has the pilot 2 protocol and results; `docs/survey.md` and `docs/pm/STATUS.md` are updated.
- The report states plainly whether the reject-rate test was met.

## Out of scope

- Reading full texts (direction B), more links than the eight questions (direction C), and query tuning. Each waits for this pilot's result and a founder ruling.
- Following a narrative review's references to the original studies.
- Showing any result on the site or the map.
- **Any change to a card, a link or a link's step.** Whether evidence from other conditions may ever move a link's step is a question about the rubric (functional spec section 3, and the 2026-11-13 ruling that indirect evidence is shown but never counted in a level). It is the founder's to decide, preferably with a medical reader, and it is not decided or prepared here.
- Grading the quality of reviews: the project has no published criteria for it, and none are invented here.
