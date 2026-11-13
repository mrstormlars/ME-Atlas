# Plan: AI auditor in place of founder approval, and a wider purpose

Brainstorm 2026-11-13. For `/orchestrator`.

## Goal

Two changes of direction from the founder, on 2026-11-13:

1. **The founder stops approving medical content.** The founder has no medical background, so the approval adds no medical judgement and is the bottleneck that keeps `cards/` empty. Until a competent person is recruited, an independent Opus instance acts as **auditor** and takes the content decisions the founder takes today. The founder pays for the work and sets its direction.
2. **The purpose is raised:** ME Atlas aims to contribute to solving ME/CFS, by collecting and structuring what is known about its causal mechanisms so that researchers can see what is untested. The overview for patients and carers remains, as a sub-goal.

This plan changes rules in `CLAUDE.md` and the functional spec, and the founder ruled on every part on 2026-11-13 (last section). The rules change when this plan is implemented, not before.

## What does not change

- **Never cite from memory**, every claim links to its source, no treatment advice, grade only against the published rubric. These get more important with researchers as readers.
- **The mechanical checks in code** (validator rules, citation checks) stay the hard barrier against invented references. No AI verdict overrides a failed mechanical check.
- **v1 scope:** ME/CFS, static site, no database, no other diseases.
- **Git:** `main` is the published state and changes reach it through a pull request.

## Part 1: the auditor

### Roles after the change

| Role | Who | Decides |
| --- | --- | --- |
| Drafting agent | `card-drafter`, `link-drafter`, `hypothesis-surveyor` | Nothing; proposes |
| Review agent | `card-reviewer` | Whether a draft goes forward (two rounds, as today) |
| **Auditor** | new agent `auditor`, model Opus | Tier 2 and tier 3: levels, badges, contested marks, layer and links, preprint early signals, parked disputes, a new hypothesis against the inclusion rule |
| Founder | — | Direction: the rubric and its rules, the inclusion rule, scope, removing a hypothesis, which sources are searched, the agents' prompts. May overrule any auditor decision, as a logged correction |
| Expert reviewer | vacant | Replaces the auditor when recruited |

### How the auditor works

1. **Inputs, and nothing else:** the proposed change (the diff of the card), the card as it stands, the cached source records the change cites, the rubric (functional spec sections 2 and 3) and `docs/card-format.md`. It does **not** get the drafting agent's reasoning, the review agent's findings or earlier audit verdicts on the same change. A fresh context per card.
2. **Output:** one audit record per decision, written to `audits/<date>-<slug>.yaml` and validated by code: the decision (`accept`, `reject`, `accept_lower` with the level it does accept), the rubric clause each part of the decision rests on, the source ids and the verbatim quote behind every factual statement in the reasons, and what would change the decision. Every quote must be found in the cached record, as for the other agents.
3. **Conservative default.** A change is applied only when the mechanical checks pass, the review agent accepted the draft and the auditor accepts it. If the auditor rejects, the card is unchanged and the record says why. If a dispute is still open after the two agent rounds and the audit, the lower level stands and the disagreement is noted on the card, as spec section 6 already says for tier 3.
4. **The auditor does not write card text.** It accepts, rejects or accepts a lower level. A rejected change goes back through the normal drafting path at most once.
5. **Independence, stated honestly.** The auditor shares a model family with the agents it audits and may share their blind spots. Record in the plan's implementation which model each agent's frontmatter names; where the review agent and the auditor would run on the same model, say so in `docs/pipeline.md`. The independence that exists is in what the auditor is shown (point 1), not in the model.
6. **Consistency check.** For a sample of decisions (every level change, and one in five of the rest, chosen by a seeded script), a second auditor run with a fresh context decides the same change. A differing verdict is treated as a dispute (point 3) and counted. The count is reported in the weekly pull request; it is the measure of how reliable the auditor is, in place of the founder's calibration period.

### What the founder sees

- The weekly pull request lists every auditor decision with its one-line reason, the consistency-check count, and anything left unchanged because of a dispute. The founder merges the pull request as an operational step, without reviewing the content.
- **Trial period:** for the first four weekly runs the founder reads the list after the fact. The trial ends by a ruling in DECISIONS, which may also allow the weekly pull request to be merged without the founder.
- A founder overrule is a card change like any other, logged as a correction with `decided_by: founder`.

### Transparency on the site

- Footer and methods page: the content, including every evidence level, is drafted, checked and decided by AI tools; no medical or research expert has reviewed it. Replaces today's "checked by AI tools and by the founder".
- `last_checked.by` gets the value `ai_audit`. Change-log entries get `decided_by` (`ai_pair`, `ai_audit`, `founder`, later `expert`).
- A way for a reader to report an error (a contact address on the methods page; see rulings). A reported error is handled as a correction (spec section 6, point 9).

### First publication

Nothing is in `cards/` today. The drafts are audited one card at a time (the whole card: level, badge, contested mark, layer, links, preprints) and a card moves to `cards/` when its audit accepts it. A card whose level the auditor does not accept is published at the level it does accept, or stays in `drafts/` with the reason, according to the ruling below. The levels the founder ruled earlier are inputs the auditor does not see as authoritative; differences are listed in the pull request.

## Part 2: the purpose

### New purpose text (for `docs/ME-Atlas-v1-plan.md`, functional spec section 1 and `CLAUDE.md`)

> ME Atlas aims to contribute to solving ME/CFS. It collects and grades what is known about the causes of ME/CFS and long COVID, shows how the hypotheses connect, and makes visible what has not been tested, so that researchers can see where the next study would matter and patients and carers can follow the state of the evidence.

### What follows from it

- **Researchers become readers of equal weight** with patients and carers. Plain language and low reading effort stay; the gaps page, the causal map, null findings and the bridge search pilot (`docs/plan-wider-sources.md` part C) are the researcher-facing content.
- **A contribution is only real if a researcher can use it.** The order of work does not change: publish the cards, then show the site to researchers and Science for ME, then widen. A KPI is added: feedback from researchers received and acted on.
- **No claim of discovery.** The site lists untested connections; it never says a hypothesis is promising or a connection is new. The wording rules of the gaps page apply to everything researcher-facing.
- **The name.** "Solve ME" is, to the assistant's recollection, close to the name of an existing ME/CFS organisation; this is unverified. Check it before the phrase is used anywhere public. The plan uses the phrase "contribute to solving ME/CFS" in running text and no slogan.

## Steps

1. Record the rulings in `docs/pm/DECISIONS.md`. Rewrite `CLAUDE.md` rule 2 and "What this project is", spec sections 1 and 6, and the purpose in `docs/ME-Atlas-v1-plan.md`. Proposed rule 2:
   > **AI drafts, checks and audits; the founder sets direction.** Code and agents write to `drafts/`. A change reaches `cards/` only through the pipeline: mechanical checks passed, the review agent accepted the draft, and for a level, badge, contested mark, layer, link, preprint or new hypothesis the independent auditor accepted it (`docs/ME-Atlas-functional-spec.md` section 6). A dispute leaves the card unchanged. The founder decides the rubric, the inclusion rule, the scope and the removal of a hypothesis, and may overrule the auditor as a logged correction. In chat sessions, move content into `cards/` only through that path or when the founder explicitly asks.
2. Agent `.claude/agents/auditor.md` (model Opus), with the inputs and output of part 1. The prompt lives in the repo.
3. Code: `pipeline audit-plan` (assembles the auditor's context file per card and nothing more), `pipeline record-audit` (validates the record: known ids, verbatim quotes, a rubric clause per decision), the consistency-check sample, and the publish step that applies only audited changes. `last_checked.by: ai_audit`, `decided_by` on change-log entries, validator updated. Offline tests.
4. `/ukentlig`: the audit step after review; the pull request body lists the decisions, the consistency count and the disputes.
5. Site: footer and methods text in English and Norwegian; the error-report line.
6. First publication: audit the drafts, move accepted cards to `cards/`, one pull request with the list of differences from the earlier levels.
7. `docs/pipeline.md`, `docs/card-format.md`, `docs/site.md`, STATUS.

## Contract ("done" is)

1. `CLAUDE.md`, the spec (sections 1 and 6) and the v1 plan state the new roles and purpose; DECISIONS has the rulings with their reasons. No other rule in `CLAUDE.md` changes.
2. The auditor's context file contains the diff, the card, the cited cached records and the rubric, and a test shows it contains no drafter or reviewer output.
3. `record-audit` rejects a record with an unknown source id, a quote not found verbatim in the cached record, or a decision without a rubric clause (tests for each).
4. A change with a failed mechanical check, a rejected review or a rejected audit is not applied; a test covers each, and shows the card file byte-identical afterwards.
5. The consistency sample is reproducible from a seed, includes every level change, and a differing second verdict leaves the card unchanged and is counted in the report.
6. A published card has `last_checked.by: ai_audit`, and every change-log entry has `decided_by`; the validator rejects other values.
7. The footer and methods page say in both languages that levels are decided by AI and that no expert has reviewed the content; no page says the founder checks content.
8. First publication: every card in `cards/` has an audit record that accepts exactly what is in the file; the pull request lists each card whose level, badge or contested mark differs from the draft.
9. Tests never touch the network or an LLM; `ruff` and `pytest` clean; no new dependency.

## Out of scope

- Recruiting the expert reviewer, and any workflow for one.
- A different model vendor for the auditor (the project runs on the subscription; no API calls).
- Merging the weekly pull request without the founder (a later ruling, after the trial period).
- Showing full audit records on the site; a form or account for error reports.
- New researcher-facing features (data export, subgroup views, discovery scores). The purpose changes what is prioritised later, not what this plan builds.
- Other diseases; a slogan or rebranding.
- Changing the rubric.

## Founder rulings (2026-11-13)

The founder accepted every default ("Ja, alle standardene"); recorded in `docs/pm/DECISIONS.md`.

- The auditor takes over tier 2 and tier 3, as in the roles table.
- New hypotheses: the auditor decides them against the inclusion rule; removing one stays with the founder.
- First publication: when the auditor does not accept a draft's level, the card is published at the level the auditor accepts, with the difference listed.
- Trial period of four weekly runs with after-the-fact reading.
- Error reports: no contact address has been given, so the error-report line is left out until the founder names one.
- The purpose text above; no public slogan until the name is checked.
