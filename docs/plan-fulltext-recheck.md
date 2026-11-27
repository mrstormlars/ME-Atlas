# Plan: the full-text re-check of published cards

Founder ruling: DECISIONS 2026-11-27, "A cheap full-text scan first, and an upgrade path for published cards". This plan covers three parts: step 0 (code compares case definitions), step 1 (a cheap scan agent per study) and an upgrade variant of the correction of a published card. Part 3 changes a credibility rule for one origin only, so it is written down here before any code.

## Why

39 studies on 17 published cards have a cached full text (`fulltext_xml` or `pmc_page` in `uv run python -m me_atlas.fulltext needs`) that was never read against their card; 12 of them carry a level, badge, contested mark or link. The correction path for a published card only removes, rewords or lowers, and opens each card with an Opus whole-card review. The scan reads each study once, cheaply, and picks the few cards where the full text may change something; only those go on to the correction path. Without an upgrade variant the scan would find improvements no path could publish.

## What does not change

- The scan decides nothing and publishes nothing. It writes only into its own run folder. A study it misses stays as the card has it.
- No change to `cards/`, `drafts/`, `translations/` or `audits/` in this work; no correction round is run on any card. The founder decides that after seeing the scan.
- PDF-only studies (`fulltext_pdf`) are out: the audit context cannot read PDF text yet.
- Every path other than a correction whose request comes from the full-text scan keeps its limits, byte for byte in code and in prompts.

## Step 0: compare case definitions (code, no agent)

For each study that `needs` lists with status `fulltext_xml` or `pmc_page`, code runs the existing finder (`find_case_definitions` for the XML, `find_case_definitions_in_page` for a PMC page) on the cached file and labels the study:

- The definition candidates (kind `definition`; exclusion candidates are listed but do not decide the label) are mapped to the card's vocabulary by their matched wording: Fukuda (`Fukuda`, 1994 together with CDC), Holmes1988 (`Holmes`, 1988 together with CDC), CCC (`Canadian ...`, `Carruthers`, `CCC`), ICC (`International Consensus Criteria`, `ICC`), IOM2015 (`Institute of Medicine`, `IOM`, `SEID`, `systemic exertion intolerance`), Oxford (`Oxford`, `Sharpe`). Generic wordings (`CDC` alone, `case definition`, `diagnostic criteria`, `met ... criteria`, `diagnosed according ...`) name no definition. This mapping only sorts; it decides nothing on a card.
- `agrees`: the card's `case_definition_quote` is found word for word (`citations.normalise_quote`) in the candidate sentences or the full text, or the named definitions are exactly the card's `case_definition`; and no candidate names a definition other than the card's.
- `differs`: at least one candidate names a definition that is not the card's (this includes a card at `unverified`, `none` or `other` where the full text names a recognised definition, and a card at `CDC_unspecified` where the full text names Fukuda or Holmes).
- `no_candidate`: no candidate names a definition and the card's quote is not found.

The result per study (label, the card's three fields, the candidate sentences with section and matched wording) goes into the run folder as `step0.json` and into that study's scan context. Step 0 alone flags nothing: it is a pointer for the scan agent.

## Step 1: the scan agent (Sonnet, Read and Write only)

**Commands** (in `me_atlas.fulltext`, logic in a new module `src/me_atlas/fulltext_scan.py`):

- `scan-plan --out RUN [--cache-dir DIR] [--cards-dir DIR] [--carrying-only] [--study ID ...]` runs step 0 and writes, per listed study, `RUN/scan-context/<slug>--<id>.md` (the `:` of the id made file-safe), plus `RUN/step0.json` and `RUN/scan-plan.json` (run id, date, the cache dir, for each card its file's sha256, and for each study the context path and the full-text status). Offline: it reads the cache only. `--carrying-only` keeps the `carrying` category of `needs` (the 12 today).
- The agent `fulltext-scanner` (`.claude/agents/fulltext-scanner.md`) reads one context file and writes `RUN/scan/<slug>--<id>.json`.
- `scan-record --out RUN` validates every scan file, checks the quotes, and writes `RUN/scan-result.json`, `RUN/scan-report.md` and, per flagged card, `RUN/requests/<slug>/request.json`.

**The context file** holds, built by code from the card and the cache: the study's entry on the card (all fields); every card item that cites the study (paragraphs of `level_reason`, `contested.reason`, the badge reasons, `subgroups`, `early_signals`, `core_claim`, link texts and sources), each under its target name (`level_reason[n]` and so on); whether the study is a carrier (`pipeline.carrier_ids`); the step 0 result; and the cached full text, uncut, rendered as the audit context renders a carrier's full text (the same function, so that a quote the scan accepts is a quote the auditor can see).

**The scan file** (JSON): `card`, `study`, and `fields` with exactly the keys `case_definition`, `n_patients`, `n_controls`, `finding`, `role`, `carrying`. Each value is `{verdict, quote, note}`. `verdict` is `confirmed` (the full text gives nothing that differs from or adds to the card for this field), `differs` (the full text says something else) or `adds` (the full text states something the card lacks). `differs` and `adds` need a `quote` copied from the full text and a one-line `note`; `confirmed` has `quote` null. `carrying` is about whether the full text bears on a level, badge or contested reason that cites the study; when the study is cited in none of those, its verdict is `not_cited` and nothing else is allowed; a `differs`/`adds` on `carrying` also names `targets`, each a target the context lists for that study (`level_reason[n]`, `contested_reason[n]`, `badge_reasons.<badge>[n]`).

**Validation by code.** A file is invalid (reported, its study counted as not scanned, no verdict used) when it is not JSON, names another card or study, lacks a key, has an unknown key or verdict, or names a target that the context does not list. Each `differs`/`adds` quote is checked word for word against the rendered full text of that study (`normalise_quote`; not against the card text in the context). A verdict whose quote fails is dropped (it counts neither as confirmed nor as a flag) and listed in the report with the reason. A study is flagged when at least one `differs` or `adds` survives; a card is flagged when one of its studies is.

**Output.** `scan-result.json`: run id, per card the card's sha256 at scan time, per study the step 0 label, each verdict kept and each dropped, and the flagged list. `scan-report.md`: the counts (step 0: agrees, differs, no_candidate; verdicts: confirmed, differs, adds; quotes dropped; files invalid; cards flagged) and per flagged card the verdicts with their quotes. For each flagged card `requests/<slug>/request.json`, a draft for the correction path: `card`; `origin` one line naming the scan run; `origin_kind: "fulltext_scan"`; `scan: {result, result_sha256}` (the path of `scan-result.json` and its sha256); `items`, one per kept verdict, `target` the study field (`studies[<id>].case_definition`, `.n_patients`, `.n_controls`, `.finding`, `.role`) or, for `carrying`, each named target, and `problem` a generated line with the verdict, the agent's note and the quote. The operator copies the file into a correction run folder; the scan starts no correction.

## Part 3: the upgrade variant of the correction of a published card

**Which requests.** `Request` gains two optional fields, both or neither: `origin_kind` (only value `fulltext_scan`) and `scan` (`result` path, `result_sha256`). The variant applies only when they are present and code verifies them: the file exists, its sha256 matches, it validates as a scan result, it flags the card, and the card's sha256 it recorded equals the sha256 of `cards/<slug>.yaml` now. When `origin_kind` is given and any of these fails, every `correct-*` command of the card refuses (exit 1, nothing written) and names the check; it never falls back to the plain path silently. A request without the two fields is the plain path, unchanged.

**What the variant may do besides a correction.** In `correction_ops_problems` (with a new `upgrade` argument, off by default) and in `card_correction.ops_problems`:

- `propose` on `level` to a value higher than the card's, and on a badge to `true`. Its `reason` must cite at least one study that the scan flagged on the card and whose full text is cached as `fulltext_xml` or `pmc_page`.
- `update_study` of `case_definition`, `case_definition_source`, `case_definition_quote` and `role`, only on a study the scan flagged and whose full text is cached as above; a changed case definition needs `case_definition_source: fulltext` (not `abstract`, not `fulltext_pdf`), and its quote is checked word for word by the existing C5.
- A `replace_paragraph` or `propose` reason may state a fact or number taken from the full text of a flagged study, citing that study. (In the plain path the drafter prompt asks for no new number; the variant allows one from the full text, and the correction is tier 2 regardless.)

Unchanged: no `add_study`, no `add_paragraph`, no `add_link`, no `add_sentence`. The plan does not need them: a raised level or a badge set to true carries its new reason paragraphs inside `propose`, and a study's role and fields change by `update_study`. The target guard still holds (every operation changes a target a step 1 finding names).

**Tier.** A correction whose request is of the variant is always tier 2 (`decide_tier` says so and why), so two sequential audits, as today for tier 2.

**Full text in the contexts.**

- Step 1 (review of the published card): the context also lists, for each study the scan flagged, the path of its cached full text and the scan's kept verdicts as the request items; the reviewer may class a finding whose fix raises or adds `decisive`, never `wording`.
- Step 2 (drafter): the records of the flagged studies are given with their full text, uncut, and the limits text names the variant's added permissions.
- Step 6 (audits): for the variant, the full text is given uncut for the carriers of the applied card (the existing rule) and also for every study whose entry differs between the published and the corrected card and every study cited by a changed item. So a study whose role becomes `supports` or `contradicts` is given in full even when no reason cites it. The plain path keeps the existing rule.

**Prompts.** `card-drafter`, `card-reviewer` and `auditor` gain one short paragraph each on the variant, stated only where the context says the request comes from the full-text scan. The limits stated for every other path stay as they are.

**Docs.** `docs/pipeline.md`, "Correcting a published card": the variant (request fields, checks, permissions, tier, audit full text) and a new section "Full-text scan" for steps 0 and 1; the stage table row. `docs/ME-Atlas-functional-spec.md` section 6, "Correcting a published card": one paragraph on the variant, citing the ruling. `docs/fulltext-targets.md` or `docs/fetch.md`: one line pointing to the scan. `.claude/agents/` gets `fulltext-scanner.md`; the agents table in `docs/pipeline.md` lists it.

## Live run

On the main checkout's cache, read only: `scan-plan --carrying-only --cache-dir C:\Scripts\ME-Atlas\data\cache --out <run folder outside data/>`, the scan agent on each context, `scan-record`. The numbers go in the pull request. The run on all 39 waits for the founder.

## Open for the founder

- Whether the scan should later run on the remaining 27 studies (after seeing the 12).
- Whether the variant may ever add a paragraph or a study. This plan does not need either; if a correction round later shows it is unavoidable, it comes back to the founder.
