# Plan: evidence card data model

October 31, 2026 · For `/orchestrator`

## Goal

Define the file format for evidence cards and a validator that enforces the rules of `docs/ME-Atlas-functional-spec.md` that can be checked mechanically. Everything later (fetch, AI drafting, review agent, site generator) reads and writes this format, so it must hold exactly what the pages in spec section 4 need and nothing more.

## Design decisions (from brainstorm, 2026-10-31)

1. **YAML, one file per hypothesis**: `cards/<slug>.yaml`. YAML reads well in a pull request diff and allows comments for the founder. Validated by **pydantic** models (already a dependency, as is `pyyaml`). No new dependencies.
2. **Drafts use the same schema.** A draft is a full proposed card at `drafts/<slug>.yaml`; the change is the diff against `cards/<slug>.yaml`. No separate patch format.
3. **Studies inline on the card**, not in a shared registry. Each card lists the studies it cites. A study cited by two cards appears twice; the mechanical citation check (later task) compares both against the fetched record, so they cannot drift silently.
4. **Every text field carries its sources.** Free text is an object `{text, sources: [study ids]}`, never a bare string. This makes "every claim links to its source" checkable.
5. **Derive, don't store, what can be derived.** The long COVID label is derived from the studies (any cited study with a long COVID cohort). The contested hatched segment is derived from `contested.rungs`. Ranking is derived from `level`.
6. **One change log file**: `cards/changelog.yaml`, append-only list of entries (date, card slug, change, one-line reason, source ids, tier). It renders "What changed this week".

## Schema (field list; exact names are the worker's choice if these are kept recognisable)

**Card**
- `slug` (must equal the file name), `name`
- `core_claim`: sourced text
- `level`: integer 0–5; `level_reason`: sourced text
- `contested`: null, or `{rungs: [int], reason: sourced text}`
- `badges.diagnostic_marker` and `badges.explains_pem`: each `{value: bool, reason: sourced text | null}`
- `subgroups`: list of sourced text
- `working_on_it`: list of `{name, url}` (research groups, funders)
- `early_signals`: list of sourced text
- `studies`: list of Study
- `last_checked`: `{date, by: ai_pair | founder}`

**Study**
- `id`: `pmid:<digits>` or `doi:<doi>`; `title`; `year`
- `cohort`: `me_cfs | long_covid`
- `case_definition`: `CCC | ICC | IOM2015 | Fukuda | Oxford | other | none`
- `design`: `controlled | uncontrolled | intervention_controlled | other`
- `n_patients`, `n_controls` (int or null)
- `measures_pem`: bool; `preregistered`: bool or null
- `role`: `supports | contradicts | early_signal | context`
- `finding`: one neutral sentence ("A study of n=… found …")

**Change log entry**: `date`, `card`, `change`, `reason`, `sources`, `tier` (1, 2 or 3).

## Validation rules (each needs a test with an input that fails it)

- V1 Schema: types, enums, required fields; `level` outside 0–5 fails.
- V2 `slug` equals the file name.
- V3 Every source id used in any sourced text exists in the card's `studies`.
- V4 Every sourced text has at least one source, except `level_reason` at level 0.
- V5 Level ≥ 2 requires at least one `supports` study with design `controlled` or `intervention_controlled` and case definition CCC, ICC, IOM2015 or Fukuda (Oxford-only cap from spec section 3).
- V6 Level ≥ 4 requires at least one `supports` study with design `intervention_controlled`.
- V7 `explains_pem.value: true` requires a cited `supports` study with `measures_pem: true` and level-2-eligible design and case definition.
- V8 `contested` not null requires at least one `contradicts` study among the reason's sources; `rungs` lie within 1..`level`.
- V9 Studies with `case_definition: none` cannot have role `supports` or `contradicts`.
- V10 Early signals and core claim contain none of a small banned word list ("promising", "breakthrough", "cure", "hope", "proven"), case-insensitive.
- V11 Change log: `card` exists in `cards/`; `tier` in 1–3; dates not in the future.

The validator reports all errors in a file at once, with file and field path, and exits non-zero.

## Steps

1. Pydantic models and loader in `src/me_atlas/cards.py` (V1, V2).
2. Cross-field validators V3–V11.
3. CLI: `uv run python -m me_atlas.cards validate [paths]`, default `cards/` and `drafts/`.
4. Tests in `tests/test_cards.py` with **fictional** fixture cards in `tests/fixtures/cards/`: one valid card exercising every field, and one failing input per rule V1–V11. Fixture ids use an obviously fake form (e.g. `pmid:00000001`) and titles say "Fictional study".
5. `docs/card-format.md`: a short reference for the founder and agents, with the field list, the rules in plain English, and a fictional example.
6. Append a DECISIONS entry (YAML + pydantic, inline studies, same schema for drafts, derived fields). Update STATUS: data model done, next is the fetch script.

## Done when

- [ ] `uv run pytest` passes and `uv run ruff check .` reports nothing.
- [ ] The fictional valid fixture card passes validation.
- [ ] For each rule V1–V11 there is a test whose input fails that rule, and the validator reports that rule for it.
- [ ] The CLI exits 0 on a directory of valid cards and non-zero on a directory containing an invalid card, printing file and field path for every error.
- [ ] An empty `cards/` (only `.gitkeep`) validates with exit 0.
- [ ] No real PMIDs, DOIs, titles, authors or results appear anywhere in the change; `cards/` and `drafts/` gain no files.
- [ ] `docs/card-format.md` exists and matches the models.
- [ ] No new dependencies.

## Out of scope

- Real evidence cards. They come after the fetch script, from fetched records only.
- The mechanical citation check against fetched PubMed records (needs the fetch script).
- Fetch, AI drafting, review agents, site generator.
- Checking that a level change was approved by the founder (that is the PR and tier process, not the validator).
- JSON Schema export, a database, or a shared study registry.
