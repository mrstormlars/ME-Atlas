# Plan: follow-ups to the full-text work of 2026-11-27

November 27, 2026 · For `/orchestrator`. Written by the `/brainstorm` role in a run where the founder could not be asked; every choice that would normally be put to the founder has a recommended default here and is listed under "Open questions for the founder" at the end.

## Goal

Close five open items from `docs/pm/STATUS.md` ("To build or fix") that came out of the full-text scan and the two correction rounds of 2026-11-27 (pull requests 115, 118, 119, 122):

1. Tune the full-text scan's flag rule.
2. Make the audit context readable when a full text sits on one very long line.
3. Leave a trail when `correct-apply` refuses an operations file (step 3), and say whether a refused file may be drafted again.
4. A new, founder-requested round for the three held-back cards (`infection-trigger`, `oxidative-nitrosative-stress`, `autonomic-imbalance`).
5. The three PDF full-text follow-ups: (a) audit context and `record-audit`, (b) C6 and C10, (c) the case-definition finder missing "Canada 2003 criteria".

Optional item 6: a cheap fix for the slow `correct-plan`.

v1 only, simple over clever, and each item changes only what it needs. No item touches `cards/`, `drafts/` or `translations/` except item 4, and item 4 only through the correction path.

## What was checked before writing this

- The code: `src/me_atlas/fulltext_scan.py` (`record_scan`, `FLAGGING`, `_draft_request`, `validate_scan_result`), `src/me_atlas/pipeline.py` (`_audit_record_lines`, `build_context`, `_record_quote_text`, `validate_audit_record`, `live_fulltext_loader`), `src/me_atlas/card_correction.py` (`correct_apply`, `ops_problems`, `_State`, `correct_publish`, `_round_trail`), `src/me_atlas/europepmc.py` (`article_text`, `pmc_page_text`, `CASE_DEFINITION_PATTERNS`), `src/me_atlas/citations.py` (`CacheReader`, `_check_quote`, `_check_sample_sizes`, `_record_text`).
- The data (local, gitignored): `data/pipeline/fulltext-scan/2026-11-27/` and the run folders `data/pipeline/corrections/published/2026-11-27-<slug>[-2]/`, plus `audits/2026-11-27-*`.
- Pull request bodies 115, 119 and 122.

Three findings that change the picture:

- **The tuned flag rule barely lowers the count on this data: 14 of 17 cards instead of 16.** Most flags come from real case-definition news (15 `adds` and 8 `differs` on `case_definition`, mostly cards at `unverified` where the full text names a definition) and from `carrying` verdicts (11 `differs`, 7 `adds`). The two cards the new rule drops, `circadian-rhythm-disruption` and `persistent-enterovirus-infection`, are exactly the two whose correction runs ended "unchanged, step 1 review found no error" in pull request 119. So the rule removes the wasted runs and loses no published change, but it is not a big saving on the first scan. Later scans, of cards already corrected, should flag far fewer.
- **The five "waiting" PDF studies are not waiting.** pmid:28694809, 29874259, 39435656, 32210306 and 41901562 all have Europe PMC open-access XML in the cache (PMC5483846, PMC5991397, PMC11529985, PMC7093502, PMC13027803). They were in the 2026-11-27 scan with status `fulltext_xml`, and the audit context already gives the auditor their XML full text. No card has `case_definition_source: fulltext_pdf`, and `confirmations/pdf-quotes.yaml` is empty. Items 5a and 5b have no study that needs them today (see item 5).
- **Every full text in every context is one line.** `europepmc.article_text` and `europepmc.pmc_page_text` collapse all whitespace, and `_audit_record_lines` writes the result as one line. In the second audit context of `oxidative-nitrosative-stress` eight full texts are single lines of 20,000 to 85,192 characters, and abstracts reach 2,480 characters. The same function feeds the weekly audit, the whole-card audit, the redraft and correction contexts, the published-card correction contexts (`correct-plan`, `correct-audit-plan`) and the scan contexts. The weekly drafter context (`build_context`) has the same one-line text, cut at 60,000 characters.

## Item 1: tune the full-text scan's flag rule

**Problem.** `record_scan` flags a study when any kept verdict is in `FLAGGING = (DIFFERS, ADDS)`, so a `finding` or `n_controls` `adds` alone flags the card. The first scan flagged 16 of 17 cards (`scan-report.md`).

**The new rule** (from STATUS). A study is flagged when a kept verdict is:

- `differs` on any field; or
- `adds` on `case_definition`, `role` or `carrying`.

`carrying` covers the level, the badges and the contested mark: its targets are `level_reason[n]`, `badge_reasons.<badge>[n]` and `contested_reason[n]`. So "adds that touch a level, badge, case definition or role" is `adds` on `case_definition`, `role` or `carrying`. An `adds` on `finding`, `n_patients` or `n_controls` no longer flags.

**Replay on the 2026-11-27 scan** (read from `scan-result.json`, nothing written):

| Rule | Cards flagged |
|---|---|
| Today (any `differs` or `adds`) | 16 |
| New rule | 14 |
| New rule, and `case_definition` `adds` only when the card has `unverified` | 14 (the same 14) |
| `differs` anywhere, `adds` only on `role` or `carrying` | 12 |

Dropped by the new rule: `circadian-rhythm-disruption` (only pmid:29874259 `finding` `adds`) and `persistent-enterovirus-infection` (only pmid:1433120 `finding` `adds`). Both ended unchanged in pull request 119.

**Change.**

- `src/me_atlas/fulltext_scan.py`:
  - Replace `FLAGGING` with a small function `flags(verdict) -> bool` (or a constant `ADDS_FLAGGING_FIELDS = ("case_definition", "role", "carrying")` used by it). `record_scan` sets `record["flagged"]` with it.
  - `_draft_request` writes request items only for flagging verdicts. A non-flagging `adds` on a flagged card does not become a request item. It does not flag, so it should not reach the reviewer as a claim to check either.
  - `_report`: per flagged card, list the flagging verdicts as now. Add one section, "Additions that do not flag", that lists the other kept `adds` (card, study, field, note, quote) for information. Nothing the scan found is hidden.
  - `scan-result.json` gains `"flag_rule": 2` (today's results have no such key and mean rule 1). The counts gain `adds_not_flagging`.
  - **`validate_scan_result` keeps its current check**: a flagged study has at least one kept `differs` or `adds`. This holds under both rules, so the scan result of 2026-11-27 still validates. The requests of the held-back cards point to it by sha256 (item 4). Do not tighten this check.
- `.claude/agents/fulltext-scanner.md`: **no change.** The scanner records every verdict faithfully. It is not told which verdicts flag, so the rule cannot steer what it reports.
- Docs: `docs/pipeline.md` "Full-text scan" step 3 ("A study is flagged when ..."), `docs/plan-fulltext-recheck.md` (one line noting the amended rule and the date), and a DECISIONS entry. The rule changes what reaches the correction path, so it is recorded as a ruling. The default is set in this plan, and the founder may overrule it (open question Q1).

**Done when.**

1. Under the new rule a study with only `finding`, `n_patients` or `n_controls` `adds` verdicts is not flagged and its card gets no request.
2. A `differs` on any field, or an `adds` on `case_definition`, `role` or `carrying`, flags the study and its card.
3. A flagged card's `request.json` holds items for flagging verdicts only. `scan-report.md` lists the non-flagging `adds` in their own section, and the counts show `adds_not_flagging`.
4. `scan-result.json` carries `flag_rule: 2`. A result without `flag_rule`, shaped like the 2026-11-27 one (a flagged study whose only verdict is a `finding` `adds`), still passes `validate_scan_result` and `load_scan_result`.
5. Replay: `scan-record` run on a **copy** of `data/pipeline/fulltext-scan/2026-11-27/` reports 14 cards flagged, without `circadian-rhythm-disruption` and `persistent-enterovirus-infection`. Never run it on the original folder. It would rewrite `scan-result.json` and the requests, whose sha256 the held-back cards' requests name.
6. `docs/pipeline.md` and the DECISIONS entry state the rule. `pytest` and `ruff` pass.

**Tests (offline, `tests/test_fulltext_scan.py`).** Hand-made scan files for one fictional card:

- a study with only `finding` `adds` (not flagged);
- one with `n_patients` `differs` (flagged);
- one with `case_definition` `adds` (flagged);
- one with `carrying` `adds` and targets (flagged);
- one with `role` `adds` (flagged).

Also test that the request items are exactly the flagging ones and that the report section exists. A fixture result without `flag_rule` loads.

**Risk to the credibility rules.** Low. The scan decides nothing. A non-flagging `adds` that would have improved a number or a finding now waits for a later scan or the weekly path, but it is still in the report. A sample-size `adds` where the card has `null` is a number. The rule leaves it out because it moves no level (open question Q2).

## Item 2: make long full texts readable in the audit context

**Problem.** The agents read context files with the Read tool, which pages a file by lines. A full text written as one line of 85,192 characters could not be read by the second auditor of `oxidative-nitrosative-stress` (pull request 122), and the auditor has no search tool. Its reject rests on that tool limit, not on the content. Every full text and every abstract is written as one line (see "What was checked").

**Proposed change: wrap, do not excerpt.** Excerpting would decide for the auditor which parts of a carrier it may see. It would also break the rule that a carrier's full text is given uncut, and that rule is what lets `record-audit` check quotes against the whole cached text. Wrapping changes no character. It only breaks the text into lines at spaces that are already there.

- `src/me_atlas/pipeline.py`:
  - A new helper `_wrapped(text: str) -> list[str]`: `textwrap.wrap(text, width=CONTEXT_LINE_WIDTH, break_long_words=False, break_on_hyphens=False)`, with `CONTEXT_LINE_WIDTH = 1000`. The texts are already whitespace-collapsed, so `" ".join(_wrapped(t)) == t` holds exactly. A token longer than the width (none is expected) stays whole.
  - `_audit_record_lines`: the abstract, the cached page text and the XML text are written through `_wrapped`. The line "Not truncated (N characters)." keeps N of the unwrapped text. The headings, `Source:` lines, `FULLTEXT_NOT_CACHED_NOTE` and the `Full text:` marker are unchanged.
  - `build_context` (the weekly drafter's section 5) and `_pdf_full_text_parts`: the same wrapping for the XML text and per PDF page. The budget and the `TRUNCATED` note count characters of the unwrapped text, as now. This goes beyond the auditor's context. Recommended because the drafter reads with the same tool and the same 60,000-character line could fail the same way (open question Q3).
- No change to the matchers. `citations.normalise_quote` collapses whitespace, so a quote copied across a line break still matches in:
  - `record-audit` (`_record_quote_text`, which checks against the cache, not the context);
  - `fulltext_scan.quote_in_fulltext` (which reads the context's `Full text:` part);
  - C5.
- `.claude/agents/auditor.md`, `fulltext-scanner.md` and `card-drafter.md`: one sentence each, under "What you read": "A context file can be longer than one read. Read it in parts, with offset and limit, to its end. A full text is broken into lines at spaces, so a quote that crosses a line break is copied with one space."
- `fulltext_scan.FULL_TEXT_MARKER` and `context_fulltext` stay as they are. The text after the marker is the wrapped text, and the quote check folds the line breaks.

**Done when.**

1. No line that `_audit_record_lines` writes is longer than `CONTEXT_LINE_WIDTH` characters, unless a single token without spaces is longer.
2. For every rendered abstract and full text, joining its lines with one space gives the unwrapped text exactly. "Not truncated (N characters)" and the `TRUNCATED` budget are unchanged for the same input.
3. A quote that spans a wrap point passes `validate_audit_record` and `fulltext_scan.quote_in_fulltext`. It also passes when the quote holds the line break itself.
4. The weekly drafter context (`build_context`) wraps its XML and PDF text the same way, if Q3 is taken as recommended.
5. Live check, offline: `correct-audit-plan oxidative-nitrosative-stress --second`, rebuilt from the `-2` run folder into a **scratch copy** of that folder, has no line over 2,000 characters. Its pmid:43027675 text is identical to the old one after whitespace folding. Never rebuild into the original folder, where the audit records already exist.
6. The three agent prompts carry the reading sentence. `pytest` and `ruff` pass. Existing tests that look for a long fixture sentence in a context are changed only where wrapping splits that sentence, by comparing whitespace-folded text.

**Tests (offline).** In `tests/test_audit.py` (or a new `tests/test_context_wrap.py`):

- a fictional XML and a fictional PMC page whose body is longer than 3 × the width;
- an abstract longer than the width;
- the round trip (join equals original);
- a quote across a wrap point, in `validate_audit_record` and in the scan's `quote_in_fulltext`;
- `build_context` with a long XML and with a long PDF page.

**Risk to the credibility rules.** Low, and it removes one. The auditor sees exactly the same characters, now readable to the end. One concern goes beyond this item. If the Read tool cuts long lines or long files rather than refusing them, an earlier audit may have rested on only the start of a long full text without saying so. This plan re-audits nothing. The founder may want the past audit records searched for "could not read" or similar wording (open question Q4).

## Item 3: a trail after a step 3 refusal, and the redraft rule

**Problem.** `correct_apply` raises `PipelineError` and writes nothing when `ops_problems` refuses the operations file, which covers the limits, the upgrade limits and the target guard. `correct_publish` then cannot run at all. `_State.__init__` raises "no round applied; run `correct-apply` first", so no trail reaches `audits/`. This happened to `autonomic-imbalance` on 2026-11-27. Its run folder `...-autonomic-imbalance-2/` holds only `request.json`, `card-review-context/`, `correction-context/`, `ops/autonomic-imbalance-r1.json` and `review/autonomic-imbalance-pre.json`. The refusal was "operations[2] changes level_reason[3], which no finding of the review of the published card names". The docs allow a retry after failed checks ("three tries in all") but say nothing about a refused operations file. The same gap exists when step 1 finds no error: `circadian-rhythm-disruption` and `persistent-enterovirus-infection` have no trail in `audits/` for 2026-11-27 either (open question Q6).

**Proposed change.**

- `src/me_atlas/card_correction.py`, `correct_apply`:
  - When the operations file is refused for its content, write `DIR/refused/<slug>-r<N>-<i>.json` before raising. Content refusals are: not a valid operations file (`parse_ops`), `ops_problems` (other card, limits, upgrade limits, target guard, `remove_comment` errors) and "the correction changes nothing". The record holds `round`, `try` (i), `ops_file`, `ops_sha256`, `operations` (the parsed or raw list), `problems` (the lines) and `date`.
  - Then exit 1 as now. Refusals about state (no review, a round already reviewed, audits begun, round 2 without a reject) write nothing, as now.
- **Redraft rule (recommended default, Q5).** A refused operations file counts as one try of its round, in the same budget as failed checks: three tries in all, refused or failed. A fresh `card-drafter` gets the correction context, its refused operations file and the refusal record, and it fixes exactly what the refusal names. `_keep_failed_try` counts `refused/<slug>-r<N>-*.json` together with `checks/<slug>-r<N>-attempt*.json`. The refused ops file is copied beside the refusal record, so the next try can overwrite `ops/<slug>-r<N>.json`.
- `correct_publish` and `_State`: when no round was applied but `refused/` holds a record for round 1 (or for round 2 after a round 1 reject), the card is held back. Card and change log stay byte-identical. The command:
  - writes the trail `audits/<stem>-trail.yaml`, with `rounds` entries `{round, operations, refused: [problems...], checks: null, review: null}`, `tier: null`, `audits_run: []` and `outcome: "held back: the operations file of round N was refused at step 3 (try i of 3): <first problem>"`;
  - writes `correction-report.md`, prints the trailer and exits 0.
  
  With no round applied and no refusal record it refuses as now.
- `.claude/agents/card-drafter.md`: one sentence beside "Check retry of a correction": a refusal retry gets the refusal record. Fix exactly the problems it names (usually an operation on a target no finding names: drop it, or fold the change into an allowed target). Change nothing else.
- Docs: `docs/pipeline.md` "Correcting a published card", steps 3 and 7 (the refusal record, the shared three tries, the trail of a refused round); `docs/plan-published-card-correction.md` (one line); a DECISIONS entry for the redraft rule.

**Done when.**

1. A content refusal by `correct-apply` writes one `refused/<slug>-r<N>-<i>.json` with the problems and exits 1. A state refusal writes nothing.
2. A refused file may be drafted again in the same round. Refusals and failed checks share three tries, and a fourth `correct-apply` on that round is refused with a message that names the count.
3. `correct-publish` on a run folder whose only round was refused writes `audits/<stem>-trail.yaml` (outcome names the refusal, `audits_run: []`) and `correction-report.md`, and leaves `cards/<slug>.yaml` and `cards/changelog.yaml` byte-identical, exit 0. `--dry-run` writes only the report.
4. A run with a refused try and then a passing try publishes or holds back as today. Its trail lists the refused try under that round.
5. The docs and the drafter prompt state the rule. `pytest` and `ruff` pass.

**Tests (offline, `tests/test_card_correction.py`).** A fictional published card and a step 1 review with one finding:

- an ops file that changes an unnamed paragraph (refusal record written, exit 1);
- a second try that passes;
- three refusals, then a fourth try refused;
- `correct-publish` after a refused-only round (trail content, card and change log bytes unchanged);
- a state refusal (nothing written).

**Risk to the credibility rules.** Low. The target guard still applies to every try, so a retry can only bring an operations file inside what the review named. The reviewer and both auditors still judge the result. The trail makes a stopped attempt visible, which the "restart rather than patch" rule needs.

## Item 4: a new round for the three held-back cards (founder ruling needed)

**This is not a routine step.** Each card has had two attempts (pull requests 119 and 122), and pull request 122 says they are not run again ("Restart rather than patch", CLAUDE.md). A third attempt needs the founder's explicit ruling, recorded in DECISIONS, before anything runs. This plan only prepares it (open question Q7).

**Why each card failed, and what a third attempt would need:**

| Card | Attempt 2 outcome | Cause | Needs before a new attempt |
|---|---|---|---|
| `oxidative-nitrosative-stress` | Review accepted round 2. First audit accepted, second rejected. | The second auditor could not read pmid:43027675 (one line of 85,192 characters). Its decisive parts say the role, the definition (IOM 2015) and the numbers "could not be matched to a sentence the auditor could read". | Item 2 |
| `autonomic-imbalance` | Step 1 rejected the published card (6 findings). `correct-apply` refused round 1 at the target guard (`level_reason[3]` named by no finding). No trail. | A process gap. The content was never reviewed or audited. | Item 3 |
| `infection-trigger` | Review accepted round 1. First audit rejected. | A content finding: one parenthetical in `level_reason[3]` says most college-cohort cases met only Fukuda, while the record says so only of the cases outside the severe group. | Nothing in code. Run with the others, for one ruling. |

**The round (if the founder rules yes):**

1. **Close the missing trail first** (after item 3 is merged). Run `correct-apply autonomic-imbalance --round 1 --run-dir .../2026-11-27-autonomic-imbalance-2` once. The same ops and the same review give the same refusal, and the refusal record is now written. Then run `correct-publish ... --date 2026-11-27` to write `audits/2026-11-27-autonomic-imbalance-correction-published-2-trail.yaml`. This changes no card. It only records the second attempt, as the other cards' trails do (open question Q8).
2. **The scan result stays.** All three cards are byte-identical to the sha256 that `data/pipeline/fulltext-scan/2026-11-27/scan-result.json` recorded (checked when this plan was written), so the upgrade variant still verifies. Reuse the scan requests. No new scan is needed (open question Q9). Re-check the sha256 at the start, because any merge that touches these cards voids the variant, and `correct-*` then refuses.
3. **New run folders**, `data/pipeline/corrections/published/<date>-<slug>/` (`-3` if run on 2026-11-27), with fresh agents at every step and the full path: steps 1 to 7 and the Norwegian step 8. The requests:
   - `oxidative-nitrosative-stress`: the attempt 2 request as it was (the scan items plus the round 2 review's `must_fix` items, copied word for word). The second audit's parts are not added. They say what could not be read, not what is wrong.
   - `autonomic-imbalance`: the attempt 2 request as it was (the scan items plus the first attempt's objecting audit parts). With item 3, a refusal now gets a retry within the three tries.
   - `infection-trigger`: the attempt 2 request plus one item, the attempt 2 first audit's objecting `decision_part` on the parenthetical in `level_reason[3]`, copied word for word.
4. **One attempt only.** If a card is held back again, it stays as published. It is not tried again unless a new source or a rule change gives a new reason, and that needs a new founder ruling. The pull request says this.
5. One pull request for the round, as pull request 122: the outcome per card, the trails, the checks (`cards validate`, `citations check`, `translations check`, `pytest`) and the trailer `ME-Atlas-Pipeline: weekly-run <date>`.

**Done when** (for the round's orchestrator contract):

1. A DECISIONS entry quotes the founder's ruling for a third attempt and its terms (which cards, one attempt).
2. The `autonomic-imbalance` attempt 2 trail is in `audits/`, if Q8 is taken as recommended.
3. Each card ran in a new run folder with fresh agents. Each `request.json` is as listed above, and its sha256 check passed.
4. A published card went through two agreeing audits (tier 2). A held-back card is byte-identical to `main` and has its trail.
5. The PR body has the outcome table and the "no further attempt" sentence. STATUS is updated by `/prosjektleder` afterwards.

**Tests.** None new: this is a run of existing code. The checks of step 5 are the gate.

**Risk to the credibility rules.** This is the item with real risk. Running a card again until an auditor accepts would be audit shopping. What makes this acceptable:

- the cause of each failure is named and fixed (a tool limit, a process gap) or answered (a named clause);
- every step is fresh and complete;
- there is one attempt;
- the founder rules on it first.

Without that ruling the round does not run.

## Item 5: the PDF full-text follow-ups

**Finding first.** The five studies named in STATUS have Europe PMC XML in the cache and were already read as XML: by the scan, and by the audit context (XML comes before the PDF). Their card quotes are from the abstract, say CCC, and agree with the XML. No study on any card has a PDF as its only full text, and no card quotes a PDF. So 5a and 5b would serve no study today. 5c is a gap in the shared finder and helps any full text.

**Recommended (Q10):** build 5c now; keep 5a and 5b planned but parked until `fulltext needs` lists a carrier whose only full text is a cached PDF. Correct the STATUS bullet (a `/prosjektleder` edit, not part of this plan's changes).

### 5c: "Canada 2003 criteria" in the case-definition finder (build now)

**Problem.** `europepmc.CASE_DEFINITION_PATTERNS` has `\bCanadian (?:Consensus|case|criteria|clinical)`, `\bCarruthers\b` and `\bCCC\b`. pmid:28694809 writes "fulfilling the Canada 2003 criteria for ME/CFS" (abstract) and "fulfilled Canada 2003 (2) criteria" (full text), so the finder gives no candidate (pull request 115). The scan's `_DEFINITION_WORDS` (CCC: `\bCanadian\b|\bCarruthers\b|\bCCC\b`) has the same gap, so step 0 cannot map such a sentence to CCC.

**Change.**

- `src/me_atlas/europepmc.py`: add `r"\bCanada\s+\(?2003\)?"` to `CASE_DEFINITION_PATTERNS`. "Canada" alone is not added, because it matches affiliations ("Toronto, Canada").
- `src/me_atlas/fulltext_scan.py`: the CCC entry of `_DEFINITION_WORDS` gains `|\bCanada\s+\(?2003\)?`.
- `unpaywall casedef` and `find_case_definitions_in_page` use the same list, so they gain it without a change.
- `docs/plan-fulltext-recheck.md` (CCC wordings) and `docs/fetch.md` / `docs/citation-check.md`, wherever the wordings are listed.

**Done when.**

1. A sentence with "Canada 2003 criteria", "Canada 2003 (2) criteria" or "Canada (2003) criteria" is a definition candidate.
2. "University of Toronto, Canada" alone is not.
3. Step 0 maps a "Canada 2003" sentence to CCC.
4. `uv run python -m me_atlas.europepmc casedef 28694809` (offline, from the cache) lists at least one candidate.
5. `pytest` and `ruff` pass.

**Tests (offline).** Unit tests on `_candidates` / `find_case_definitions` with a small fictional JATS fixture holding the three wordings and an affiliation line. A step 0 test where the card says CCC and the only candidate is "Canada 2003", giving `agrees`.

**Risk.** Very low. The finder only selects sentences for a reader and decides nothing.

### 5a: PDF text in the audit context and `record-audit` (parked; design for when it is needed)

**Problem.** A carrier whose only full text is a cached PDF is given to the auditor as abstract only, with `FULLTEXT_NOT_CACHED_NOTE` (`docs/plan-unpaywall-pdf.md`, section 5). So a `fulltext_pdf` case definition can be drafted and confirmed by the founder (C14), but no auditor can check it against the text. A level, badge, contested mark or link that rests on it cannot pass an audit.

**Change, when it is built.**

- `pipeline._audit_record_lines`: a third branch after the XML and the page. When neither is cached and `unpaywall.read_cached_pdf(cfg.cache_dir, record.doi)` gives a text, render it:
  - the source line of `_pdf_full_text_parts` (version, host type, PDF URL, the reference-list note);
  - "Not truncated (N characters)";
  - the pages as `[page N] ...`, wrapped as in item 2.
  
  Reuse `_pdf_full_text_parts`' wording, without the budget, since the audit gives a carrier uncut.
- `pipeline._record_quote_text` / `validate_audit_record`: for a source whose context rendered a PDF, a quote passes when it is in title, abstract or XML/page text under `normalise_quote` (as now), **or** when `unpaywall.quote_in_pdf_text(quote, pdf.text)` finds it (the C5 matcher, one page, line-break hyphen and slash readings).
- The scan (`fulltext.READ`) and the upgrade variant (`upgrade_problems` requires `fulltext` for a changed case definition) are **not** widened in this step. A PDF-only study can then be audited, but not upgraded by the scan path. Widening that is a separate decision.
- The founder's confirmation (C14) stays the gate for every `fulltext_pdf` quote. The auditor reading the PDF does not replace it.

**Done when.** A fixture carrier with only a cached PDF renders with its PDF text in an audit context. An audit quote from that PDF across a line-break hyphen passes `validate_audit_record`, and a quote not in it fails. A carrier with XML is rendered as before.

**Risk.** Medium. PDF extraction can reorder text in columns and tables. The one-page matcher and C14 keep a quote honest, but an auditor reading a jumbled PDF could misread it. This is why it should wait for a real case.

### 5b: PDF text in C6 and C10 (parked)

**Change, when it is built.** `citations.CacheReader` gains `pdf_text(pmid)`: the cached PDF text of the record's DOI, page breaks as spaces, or None. `_check_sample_sizes` (C6) and `_record_text` (C10, C11) use it only when `fulltext(pmid)` gives no text. XML and page come first, and C5 for source `fulltext` never reads a PDF.

**Done when.** A study whose only full text is a cached PDF has its `n_patients` found by C6 and a free-text numeral found by C10 in the PDF text. A study with XML is checked as before.

**Risk.** Medium-low. C10 is a weak "the numeral occurs somewhere" check. PDF text adds page numbers, running headers and table cells, so more numerals pass by chance. A number read from a PDF is not covered by the founder's check, which covers only the case-definition quote. Whether such numbers may pass without the founder is a ruling (open question Q11).

## Item 6 (optional): `correct-plan` is slow

**Probable cause** (from the code, not timed). `correct-plan` and `correct-audit-plan` use `live_fulltext_loader`. `europepmc.get_fulltext` requests a lookup again when it is older than 7 days and found no open-access full text. When a PMC id is known but the lookup gives no open-access record (every `pmc_page` study), it requests the XML "once per call". The `pmc_page` carriers are exactly the ones for which Europe PMC answered HTTP 500 after the cache loss, so each call can wait on retries.

**Cheap fix.** The published-card correction steps (`correct-review-plan`, `correct-plan`, `correct-audit-plan`) use the cache-only loader `fulltext_scan.cache_loader` instead of the live loader. `_audit_record_lines` already falls back to the cached page. The checks (`citations check`, `record-audit`) read only the cache, so the contexts would then show exactly what the checks check. A full text that is missing from the cache is fetched beforehand with the existing commands, as for the scan.

**Done when.** The three commands make no network request (a test with a loader that fails on any request). Their context for a card with an XML carrier and a page carrier is unchanged from today's for the same cache.

**Recommended:** do it with item 2 or 3 only if a quick timing of `correct-plan` on one card confirms that the time goes to Europe PMC requests. Otherwise leave it (Q12).

## Order and parallel work

- **Independent, can run in parallel** (separate branches, separate orchestrator sessions):
  - **A: items 1 and 5c together.** Both touch `fulltext_scan.py`, so they share one branch to avoid conflicts. 5c also touches `europepmc.py`.
  - **B: item 2** (`pipeline.py` rendering, three agent prompts).
  - **C: item 3** (`card_correction.py`, drafter prompt, `docs/pipeline.md` correction section).

  B and C both edit `docs/pipeline.md` and `card-drafter.md`, but in different sections. Whichever merges second rebases.
- **Then item 4**, after B and C are merged **and** the founder has ruled (Q7). It does not depend on A (it reuses the 2026-11-27 scan result), unless the founder chooses a new scan (Q9).
- **Items 5a and 5b** stay parked. If they are taken up, 5a comes after B (both change `_audit_record_lines`), and 5b is independent.
- **Item 6** is optional, inside B or C, only if the timing confirms the cause.

Recommended sequence when run one at a time: B (item 2), C (item 3), A (items 1 and 5c), then the founder's ruling and item 4. B and C come first because they unblock item 4. A only pays off at the next scan.

## Out of scope

- Any card, draft, translation or audit change outside item 4. Item 4 changes cards only through the correction path, after a founder ruling.
- Re-auditing earlier audits that may have met long lines (Q4 asks only whether to look).
- Widening the scan or the upgrade variant to PDF-only studies.
- Changing the scanner's verdict definitions.
- The other STATUS items: the comment-only correction, the `group` fields on `oxidative-nitrosative-stress`, links on held-back drafts, the proper-noun check, and the `pmc_no_xml` / `pdf_only` live paths.

## Open questions for the founder

Each has a recommended default that this plan assumes.

- **Q1. The flag rule.** (a) `differs` anywhere, or `adds` on case definition, role or carrying: 14 of 17 on the first scan. (b) Stricter: `adds` only on role or carrying, so a newly named case definition flags only as `differs`: 12. (c) Keep today's rule: 16. **Recommended: (a).** It matches STATUS and drops exactly the two cards that ended unchanged. (b) would miss real upgrades: a card at `unverified` whose full text names Fukuda is often recorded as `adds`.
- **Q2. A sample size the card lacks** (`n_patients`/`n_controls` `adds` where the card has `null`). (a) Does not flag; listed in the report. (b) Flags. **Recommended: (a).** It moves no level, and the weekly path or a later correction can take it.
- **Q3. Wrap the weekly drafter's context too.** (a) Yes, with the same helper. (b) The audit-family contexts only. **Recommended: (a).** The drafter reads with the same tool, and one shared helper is simpler than two rules.
- **Q4. Earlier audits that met long lines.** (a) Search the audit records in `audits/` for "could not read" or similar, and list any for the founder; re-audit nothing. (b) Re-audit every card whose audit context had a line over the limit. (c) Do nothing. **Recommended: (a).** It is cheap and answers the question without starting new rounds.
- **Q5. May a refused operations file be drafted again?** (a) Yes, within the round's three tries, shared with failed checks. (b) Once only, outside the three tries. (c) No: a refusal ends the attempt, with a trail. **Recommended: (a).** The target guard still binds every try, and one counter is simpler than two.
- **Q6. A trail when step 1 finds no error** (the path ends before any round). (a) Yes: `correct-publish` writes a trail with outcome "unchanged: the review of the published card found no error". (b) No: only refusals get a trail. **Recommended: (a).** It is the same code path and the same gap (`circadian-rhythm-disruption` and `persistent-enterovirus-infection` have none for 2026-11-27).
- **Q7. A third attempt for the three held-back cards.** (a) Yes, once, for all three, after items 2 and 3. (b) Only `oxidative-nitrosative-stress` and `autonomic-imbalance`, whose failures were a tool limit and a process gap. `infection-trigger` stays, because its reject was a content finding. (c) No: all three stay as published. **Recommended: (a)**, one attempt each, and no further attempt without a new reason. `infection-trigger`'s finding is one named clause, which a fresh attempt can remove and fresh auditors can judge. If the founder sees that as audit shopping, (b) is the safe choice.
- **Q8. Write the missing attempt 2 trail for `autonomic-imbalance`** by re-running `correct-apply` (refused again, now recorded) and `correct-publish` on the `-2` folder. (a) Yes. (b) No; note the gap in DECISIONS only. **Recommended: (a).** It changes no card and makes the record complete.
- **Q9. The scan for the new round.** (a) Reuse the 2026-11-27 scan result and requests (still valid by sha256). (b) A fresh scan of the three cards under the new rule and the wrapped contexts first. **Recommended: (a).** It is cheaper, keeps the requests that attempt 2 used, and does not wait for item 1.
- **Q10. The PDF follow-ups.** (a) Build 5c now and park 5a and 5b until a carrier has only a PDF. (b) Build all three now. (c) Build 5c and 5a, park 5b. **Recommended: (a).** No study needs 5a or 5b today: the five named studies have XML.
- **Q11. Numbers read from a PDF in C10, when 5b is built.** (a) May pass C10 without the founder's check (C10 is a weak check, and the founder checks case-definition quotes only). (b) A numeral found only in PDF text is a warning, never a pass. **Recommended: (a)** when it is built, but decide only then.
- **Q12. The slow `correct-plan`.** (a) Switch the published-card correction steps to the cache-only loader if a timing confirms the cause. (b) Leave it. **Recommended: (a)**, conditional on the timing.
