# ME Atlas – Functional Specification (v1)

Written October 31, 2026; last updated November 17, 2026 · Status: draft. The site is built and published. The rules below are applied as written, and no medical or research expert has reviewed them.

This document says what the site shows, for whom, how a hypothesis gets on it, how it is graded, and how content moves from AI draft to published card. It builds on `docs/ME-Atlas-v1-plan.md` and supersedes its draft status scale (see "Evidence ladder"). The card data model is in `docs/card-format.md`.

Examples in this document are fictional ("Hypothesis A") and carry no real citations.

## 1. Purpose and readers

ME Atlas aims to contribute to solving ME/CFS. It collects and grades what is known about the causes of ME/CFS and long COVID, shows how the hypotheses connect, and makes visible what has not been tested, so that researchers can see where the next study would matter and patients and carers can follow the state of the evidence. It describes the state of the evidence. It does not give treatment advice, and it makes no claim of discovery: it lists untested connections and never says that a hypothesis is promising or that a connection is new.

Researchers and patients and carers are readers of equal weight. Plain language and low reading effort stay for everyone; the gaps page, the causal map and the null findings are the content aimed at researchers.

Scope is ME/CFS first. Long COVID appears as a marker on a card where the evidence overlaps, because the two conditions may share some root causes. It is not a separate section in v1.

### Patients and carers (little energy)

- **Scenario 1.** A newly diagnosed patient wants to know what researchers think is going on. They open the front page, read the one-sentence intro, and see at a glance which ideas have the most evidence behind them. They leave after two minutes without having read a paper.
- **Scenario 2.** A carer hears about a hypothesis in a support group. They find it on the front page, open its card, and read the plain-language core claim and what is contradicted or unreplicated.
- **Scenario 3.** A patient on a bad day reads on a phone, in bed, with large text. They look up one unfamiliar word by tapping it.

### Researchers

- **Scenario 1.** A researcher checks whether a hypothesis has been replicated. They open the card and go straight to the linked studies, with sample size and case definition beside each.
- **Scenario 2.** A reviewer disagrees with a grade. They open the methods page, read the rule that was applied, and see on the card why the level was set.
- **Scenario 3.** A researcher returns after a month and opens "What changed" to see which cards moved, and why.

## 2. Inclusion rule for hypotheses

A hypothesis is listed when it has **at least one peer-reviewed study with data from an ME/CFS cohort defined by a recognised case definition** (see "Accepted case definitions" in section 3).

The rule judges **method, not origin**. Any approach, conventional or alternative, that uses scientific method and meets the rule is admitted.

Excluded, and why:

- **Ideas with no peer-reviewed cohort data yet.** They cannot be graded on any rung; they may be tracked internally as candidates. Candidates are tracked in `docs/pm/candidates.md`.
- **Studies of healthy people, animals or cells only.** These can support plausibility on a card but do not admit a hypothesis alone.
- **Cohorts without a stated case definition.** Without one we cannot tell whether the patients had ME/CFS.
- **Claims backed only by opinion, anecdote, patient surveys without a clinical comparison, or non-peer-reviewed material.** Not enough to check.
- **Treatment products and commercial claims.** The site lists hypotheses about causes, not remedies.
- **Refuted hypotheses.** No card, and not surveyed; each is named with the reason and its sources in `docs/pm/excluded-hypotheses.md` (founder ruling 2026-11-08).

Hypotheses are **not mutually exclusive**. They may be links in one causal chain, or may apply to different patient subgroups. The front page says so.

## 3. Evidence ladder

**Draft — pending expert review.** No external medical or research reviewer has been recruited yet. Until one has, the ladder is applied as written, it is a draft, and the site says it has not been expert-reviewed. Grading follows only this published ladder; editors do not add criteria.

The bar for a hypothesis shows **causal evidence**, rung 0 to 5.

| Level | Plain-language name | What it means |
| --- | --- | --- |
| 0 | Proposed | An idea with a reasoned argument, but no direct patient data yet. |
| 1 | First signs | One or more small or uncontrolled studies point towards it. |
| 2 | Backed in a defined group | A controlled study in patients with a recognised case definition supports it. |
| 3 | Repeated by others | An independent group has reproduced the finding in a separate cohort. |
| 4 | Tested by intervention | Changing the proposed factor changes the outcome in a controlled experiment, so the link goes beyond association. |
| 5 | Causal case built | Several independent lines of evidence, including experimental evidence, together meet most of the Bradford Hill criteria, with no unresolved major contradiction. |

**Level 5 and treatments.** A treatment that works is one kind of experimental evidence and can count towards level 4. It does not, on its own, confirm the root cause: a treatment can help without acting on the cause. Level 5 requires the whole causal case, not a treatment result.

### What moves a hypothesis up or down

Up: a new study meeting the criteria of the next rung; an independent replication; a better-defined cohort; a larger sample; a controlled design with a comparison group; a preregistered protocol.

Down or held back: failed replications; a finding that rests only on a broad case definition (Oxford-only cohorts) or a very small sample; no control group; no preregistration; results that conflict with equally strong studies (see "Contested evidence"). A retracted study is removed from the evidence and the level is re-assessed. Code only flags a newly retracted cited paper; removing it, or changing a level because of it, is a card change that goes through drafting, review and audit (section 6).

Volume is not evidence. The number of papers, citations or news items never moves a hypothesis.

**Preprints.** A preprint (not peer reviewed) is an early signal and nothing more. It never moves a level, sets or changes a badge, creates or changes a contested mark, or supports a link, whatever it found, and it is shown with the fixed label "Preprint: not peer reviewed." When its published version appears in PubMed, the weekly report flags it. Replacing the preprint with the published paper is a card change that goes through the pipeline (checks, review and, for a preprint, the auditor).

### Mapping to the Bradford Hill criteria

| Bradford Hill criterion | Where it counts |
| --- | --- |
| Strength of association | Levels 2–3 |
| Consistency (repeated by different groups) | Level 3 |
| Specificity | Levels 2–5 (weighed, not required) |
| Temporality (cause comes before effect) | Levels 4–5 |
| Biological gradient (dose–response) | Levels 4–5 |
| Plausibility (a credible mechanism) | Level 0 upward |
| Coherence (fits other knowledge) | Levels 1–5 |
| Experiment (change the factor, outcome changes) | Level 4 |
| Analogy | Level 0–1 only; never enough to raise a level |

Quality factors applied at every rung: case definition, sample size, controls, preregistration, conflicting results.

### Accepted case definitions

| Case definition | Treatment on the ladder |
| --- | --- |
| CCC, ICC, IOM 2015 | Accepted at every rung. |
| Fukuda | Accepted, flagged on the card as "does not require PEM". |
| Holmes 1988 (the 1988 CDC definition) | Accepted like Fukuda: flagged on the card as "does not require PEM", ranked equal to Fukuda. |
| CDC criteria, version not stated | Accepted like Fukuda and Holmes 1988, since neither CDC version requires PEM: flagged on the card as "does not require PEM", ranked equal to Fukuda. The card quotes the sentence that names the CDC criteria. |
| Oxford (only) | Flagged as broad. Evidence resting only on Oxford-defined cohorts cannot raise a hypothesis above level 1. |
| None stated, or not yet checked | Not accepted (see the inclusion rule). A card records which of the two applies, and for any named definition the sentence it was read from. |

**Whose text the definition comes from.** A study is recorded with the definition its own text states. Another article's description is carried over only when a source says the patient group is the same. Comparability is judged by the recorded definition, and the uncertainty is written out on the card. (Founder ruling 2026-11-16.)

### The two badges

Shown on every card, separate from the bar, each yes or no:

1. **Diagnostic marker validated in an independent cohort.** Yes only when a measurable marker linked to the hypothesis has been tested in a second, independent patient group, with a stated case definition.
2. **Explains post-exertional malaise (PEM).** Yes only when at least one study at level 2 or above measures PEM directly (for example a repeated exercise test on two consecutive days, or a controlled exertion challenge with symptoms tracked afterwards) and links it to the hypothesis. The link must connect the proposed mechanism to the symptoms after exertion in the same patients; a measured change that is itself the hypothesised abnormality (for example a fall in oxygen use on the second test) does not on its own explain PEM. A cohort of ME/CFS patients alone is not enough. (PEM is the worsening of symptoms after physical or mental effort.)

Separate tracks for mechanism, diagnosis and treatment were rejected because they are harder to read.

### Contested evidence

A level is **contested** when at least one study of comparable or higher quality contradicts the finding that supports it. Comparable quality means all three: the same or a stricter case definition (CCC, ICC and IOM 2015 rank above Fukuda and Holmes 1988, which rank equal and above Oxford), a control group, and at least half the sample size of the study it contradicts. Sample size here means the number of patients in the measurement that bears on the finding, not the whole study when only part of it was measured. A rung that rests on more than one study (for example an original finding and its independent replication at level 3) is contested when a study of comparable quality contradicts any study the rung needs.

**Unknown patient count.** When the sources do not state the number of patients in the measurement that contradicts the finding, the contested mark is not set, but the contradicting finding and the missing number are written out on the card. (Founder ruling 2026-11-16.)

- **Who decides:** the auditor, as a tier 2 decision (see section 6), with the contradicting study linked on the card and the reason written in plain sentences, split into short paragraphs with their own sources when it needs more than two. AI may propose a conflict; it never sets one.
- **How it is shown:** the bar is filled up to the highest uncontested rung; the rung or rungs under dispute are drawn as a **hatched segment**. The card lists both sides.
- **How it ends:** a contested mark is removed when the conflict is resolved (for example a larger study settles it), recorded on "What changed".

### Causal map and links

The ladder grades one thing: how far the evidence for a hypothesis has come. A second view, the causal map, gives every hypothesis a *place* in a possible chain from vulnerability to symptoms, and grades the *links* between hypotheses on a scale of their own. The map is a second view: the bar chart keeps answering "how far has the evidence come"; the map answers "where in the chain does this belong". ME/CFS may be several conditions with different triggers that meet downstream, and the map does not assume one chain.

**Layers.** Every node sits in exactly one layer, from root to experience:

| Layer | Key | The question it answers |
| --- | --- | --- |
| Predisposition | `predisposition` | Who is vulnerable? |
| Trigger | `trigger` | What starts it? |
| Perpetuating mechanism | `mechanism` | Why does it not resolve? |
| Measurable dysfunction | `dysfunction` | What goes wrong in the body? |
| Symptom | `symptom` | What does the patient experience? |

The first four layers hold hypothesis cards. The symptom layer is not hypotheses: it is a fixed list taken from the accepted case definitions, each symptom sourced to the document that lists it. A card that could sit in two layers (for example herpesvirus reactivation as trigger or as consequence of immune dysfunction) gets one layer and a link that expresses the other reading; the ambiguity is written out, not hidden. When no source carries a link for the other reading, it is enough that the ambiguity is written out with a source (founder ruling 2026-11-16).

**Links.** A link from one node to another grades a narrower claim than the ladder: "A drives B in ME/CFS patients". It has three steps:

| Step | Key | Requires |
| --- | --- | --- |
| 1 Proposed | `proposed` | A peer-reviewed source (a review counts) that states the link. Not studied directly in patients. |
| 2 Associated | `associated` | A study in an ME/CFS cohort with a recognised case definition that measured both ends in the same patients and reports a relation between them. |
| 3 Direction supported | `directional` | In patients: temporal order (A before B), an intervention on A that changes B, or a mediation analysis. A review alone never reaches this step. |

- **Case definitions** are the ladder's: Oxford-only evidence stays at step 1, and a source that is a review (`design: other`) cannot carry step 2 or 3.
- **No link without a source, at every step.** "Proposed by [review]" is a source; an agent's or the founder's own reasoning is not. Links may run both ways and form loops.
- **A link never raises a card's level.** A study that measured both ends and found no relation is recorded as a `context` study and the link text says so. Links have no contested mark in v1.
- **Open questions** are empty boxes, never claims: a question sourced to a publication that asks it, or marked as the project's own question (no publication asks it). The four current ones were set in the first mapping (founder ruling, 2026-11-06); no ruling yet says who decides a new one.
- **Convergence is counted, not judged.** A node with two or more incoming links from different cards is listed as a *candidate common mechanism*; a card with two or more links out as a *candidate root*. Nobody writes "the common cause is".
- **Gaps are counted and listed, never judged.** Symptoms with no link, links not yet tested in patients (step 1) and what the next rung requires are shown as lists with counts; no gap is ranked, weighted or called important.
- **Who decides:** setting a card's layer and adding or changing a link are tier 2 decisions taken by the auditor, like levels, badges and contested marks (section 6). AI may propose and the `card-reviewer` checks each link against its sources; it never sets either.

## 4. Pages

### Front page

- **Shows:** one-sentence intro; a pipeline chart with one horizontal bar per hypothesis against the six rungs of the ladder; contested segments hatched; the two badges as small marks; a long COVID marker where evidence overlaps; the sentence that hypotheses are not mutually exclusive; a draft notice on the ladder. Sorted by **furthest along** on the published ladder (ties alphabetically).
- **Does not show:** "most promising" or any editorial ranking; paper counts, trends or momentum; subgroup filters (none in v1); treatment suggestions; anything unsourced.

### Hypothesis card page

- **Shows:** name; core claim in plain words; level, badges and contested state, with the reason for each; key supporting studies (link, sample size, case definition, year); contradicting studies; replication status; subgroups it may apply to; who is working on it; early signals; a small "Also studied in long COVID" label at the top of the card when at least one long COVID study that meets the inclusion rule points to the same mechanism; last checked (date, and whether by the AI auditor or, after an overrule, by the founder).
- **Early signals** come only from studies with a recognised case definition confirmed in the abstract or full text; a study whose case definition is unverified or not stated is not shown as an early signal. They appear only on the card, under the fixed heading "Early signals: not yet repeated", in a fixed sentence pattern ("A study of n=… found …"). They never appear on the front page, and words such as "promising", "breakthrough" or "hope" are not used.
- **Does not show:** advice on what a patient should do; a verdict that a hypothesis is "right" or "wrong"; any sentence without a source link.

### Gaps page

- **Shows:** under the title "What is missing" (Norwegian "Hva mangler"), tables derived from the cards and the symptom list: a summary of links into each symptom, links by support step and hypotheses by level; every hypothesis by current level with its contested rungs and the counts of supporting studies, research groups, contradicting studies and links, with the ladder's wording for each rung shown once; the level 2 group as its own list ("not yet repeated by an independent group"), each row linking to the level reason on the card; every link at step 1, by target and source, linking to the map page for its text and sources. No card text is copied onto the page.
- **Also shows:** above the lists, "At a glance": a table of links into each symptom by support step, one bar of all links by step, and the hypotheses by level 0 to 5 (with the contested count), all counted from the same data as the lists and written out as numbers.
- **Does not show:** a score, weight or ranking of hypotheses or gaps; which gap matters most or what should be studied; the absence of a link as a finding (it only means nobody has mapped it here yet); any sentence without the same sources as elsewhere on the site.

### What changed

- **Shows:** the dated log of published changes: new hypotheses, level changes, new or removed contested marks, new studies added; each entry with a one-line reason, the tier and a link to the card and source.
- **Does not show:** unreviewed AI drafts; rejected suggestions; commentary on individual researchers.

### Methods page

- **Shows:** the evidence ladder and its draft status; the inclusion rule; the Bradford Hill mapping; the badge definitions; how contested evidence is decided; the editorial flow and its review tiers; the role of AI and how its work is checked; who decides (the AI auditor; the founder sets direction and may overrule); a plain statement that no medical or research expert has reviewed the content yet (until one has); known limits.
- **Does not show:** private reviewer discussions; claims about accuracy that are not measured.

### Registered ongoing studies page

- **Shows:** only when the reliability test has passed (`registry/reliability.yaml`, `passed: true`): the studies of ClinicalTrials.gov that are ongoing, matched to a card and accepted by the review agent, one table per hypothesis (hypotheses by name, rows by registry number) with registry number (linked), title as registered, study type, status, countries and planned enrolment; the number of distinct studies; the number of other ongoing studies not listed; the date of the last fetch. A card page shows one line with the number of studies for that card and a link to its table.
- **Does not show:** contact details, a ranking, a "recruiting now" list of its own, any sentence about a study that is not the registry's own title, or any wording that invites taking part or judges an intervention.

### Data resources page

- **Shows:** only when `registry/resources-reliability.yaml` says `passed: true` and `registry/resources.yaml` has at least one entry: an intro (what the list is, that the site holds no patient data, that every value is taken from the resource's own page on the date shown, that the list is not an invitation to take part, that a resource is not evidence and changes nothing on a card); table 1, data and samples (name linked to the resource's page, what it holds, access, what it covers, date checked); table 2, registers of research (name, date checked). There is no operator or country column. Both sorted by name; a table with no rows is not shown. Linked from the gaps page and the data page, not from the main navigation.
- **Does not show:** any sentence about a resource, a quote, a ranking, contact details, or any wording that invites taking part or signing up.

### Glossary page

- **Shows:** every term from the shared glossary file, in alphabetical order, with a plain-language explanation, and links back to the pages that use it.
- **Does not show:** terms that no page uses; explanations that differ from the hover/tap text (same source).

## 5. Plain language and accessibility

- **English, plain words; reviewed translations alongside.** The site is written in English, which is authoritative. Reviewed translations (Norwegian first) are published alongside it; each translated page says it is a translation and links to the English page, and each language has its own glossary file (the English one is the reference). Short sentences. Avoid jargon and abbreviations. Where a technical term or abbreviation is needed, it is marked visibly (dotted underline) and shows a short explanation.
- **One glossary file** is the single source for all explanations. It renders the glossary page and every in-page explanation. No explanation is written inline.
- **Explanation behaviour.** The explanation appears on mouse hover, on tap or click, and on keyboard focus. Terms are focusable controls described by their explanation. Escape, or tapping elsewhere, closes a tapped explanation. Hover is never the only way to read it.
- **Contrast.** Text and chart marks meet WCAG 2.2 AA contrast at least (4.5:1 for body text). Meaning is never carried by colour alone: levels have text labels, contested segments use a hatch pattern, badges use words.
- **Text size.** Body text at least 18 px equivalent; secondary text (keys, labels, study details) at least 16 px; layout holds when the user enlarges text to 200%.
- **Phone.** Works at 375 px width with no horizontal scrolling; tap targets at least 44 px.
- **No mouse.** Everything reachable and operable by keyboard, with a visible focus outline and a logical order; the chart has a text equivalent (a list or table with each hypothesis, level and badges).
- **Calm.** No animation needed to understand anything; respect reduced-motion settings; no pop-ups.

## 6. Editorial flow

The pipeline runs on AI, with mechanical checks in code. The founder sets the direction; no person decides the content of a card. The site says so openly (section 5 and the methods page).

### Roles

| Role | Who | Decides |
| --- | --- | --- |
| Drafting agent | `card-drafter`, `link-drafter`, `hypothesis-surveyor` | Nothing; proposes |
| Review agent | `card-reviewer` | Whether a draft goes forward (two rounds) |
| Auditor | `auditor`, an independent AI agent | Tier 2: levels, badges, contested marks, layer and links, preprint early signals, and a new hypothesis against the inclusion rule. Never a change the review agent rejected in two rounds (tier 3 has no AI step) |
| Founder | the founder | Direction: the rubric and its rules, the inclusion rule, the scope, removing a hypothesis, which sources are searched, the agents' prompts. May overrule any auditor decision, as a logged correction (`decided_by: founder`) |
| Expert reviewer | vacant | Replaces the auditor when recruited |

### Steps

1. **Weekly fetch.** The pipeline fetches new papers from PubMed and Europe PMC and stores raw responses.
2. **Drafting agent.** One AI agent classifies papers by hypothesis, extracts study data (sample size, case definition) and writes a draft card update. Each AI output keeps the source id it came from. Output goes to `drafts/` only.
3. **Mechanical checks (code, not AI).** Every cited id exists in a fetched record; title, year, sample size and case definition match that record; every sentence has a source link. A draft that fails is sent back to the drafting agent. No AI verdict overrides a failed mechanical check.
4. **Review agent.** A second AI agent checks the draft against the sources, the inclusion rule and the ladder. It sees the draft and the source records, not the drafting agent's reasoning.
5. **Second round.** If the review agent rejects the draft, the drafting agent gets one revised attempt, which is checked again (steps 3 and 4). If it is rejected again, the change goes to the **parking lot**: it is not applied and not sent to the auditor, and the report lists it as a dispute.
6. **Audit and decision by tier.**

   | Tier | Change | Who decides |
   | --- | --- | --- |
   | 1 | Adding a study to a card, factual text, change-log entry | Applied when the mechanical checks pass and the drafting and review agents agree |
   | 2 | Setting or changing a level, a badge or a contested mark; a card's layer and links; adding a hypothesis; any change that adds or cites a preprint | The auditor, accept or reject, after the checks and the review |
   | 3 | A change the review agent rejected in two rounds (a parked dispute) | No AI step. The card is unchanged and the change is listed in the report; it is never sent to the auditor. The founder may overrule it, as a logged correction (`decided_by: founder`) |

   Changes that add or cite a preprint are tier 2: the auditor decides preprint changes. Removing a hypothesis stays with the founder.

   **What the auditor sees, and nothing else:** the proposed change (the diff of the card), the card as it stands, the cached source records the change cites (the full text, uncut, of every source that carries the level, a badge, the contested mark or a link; the abstract only for the others; a carrier with no cached full text is given as an abstract with a statement that the full text could not be checked), the rubric (sections 2 and 3 of this document) and `docs/card-format.md`. It does not see the drafting agent's reasoning, the review agent's findings or any earlier audit of the same change, and each audit starts in a fresh context.

   **What the auditor writes:** one audit record per decision, validated by code: the decision (`accept`, `reject`, or `accept_lower` with the level it does accept), the rubric clause each part of the decision rests on, the source id and the verbatim quote behind every factual statement in its reasons, and what would change the decision. Code rejects a record with an unknown source id, a quote that is not found word for word in the cached record, or a decision part without a rubric clause. The auditor writes no card text.

   **Conservative default.** A change is applied only when the mechanical checks passed, the review agent accepted the draft and, for a tier 2 change, the auditor accepted it. If the auditor rejects, or accepts only a lower level, the card is unchanged and the record says why. A dispute that is still open leaves the card unchanged. A change the review agent rejected in two rounds is never sent to the auditor and never applied, even if an audit record accepting it were present.

   **A lower level (`accept_lower`).** Nothing is applied at once. The drafting agent writes one redraft (round L, at most once) that proposes only the level the auditor accepted, with its reason rewritten at that level, and a contested mark or badge only where the lower level makes it inconsistent. The redraft goes through the checks and the review agent again, and a fresh auditor audits it (a level change, so a second auditor decides it too). It is applied only when every step accepts; otherwise the card is unchanged and the report lists the dispute with the reason. There is no further round.

   **The whole-card review at first publication.** A new draft is reviewed as a whole by the review agent against its cached sources (the same checks as in a correction round, applied to the draft as it stands) before any audit; only an `accept` sends it to the auditors. A `reject` holds the card back with the reason "whole-card review rejected" and the draft stays in `drafts/`; the safety valve below does not apply here. The review is kept in `audits/<date>-<slug>-card-review.yaml` (verdict, findings, the sha256 of the draft reviewed), and a draft with that record is not reviewed or audited again unchanged. A draft held back by a rejecting review is corrected like one held back by the audits: its findings are findings to answer.

   **Correcting a held-back draft.** A draft whose two whole-card audits did not accept it stays in `drafts/` and is not audited again unchanged. Before it drafts, the review agent reviews the unchanged draft as a whole against its cached sources (the same checks as below); its findings, with the audit records, are what the correction answers, and it is input to the drafter, not a gate. The drafting agent may then propose one correction (round C1, at most once per card; further rounds only for the cards named in DECISIONS 2026-11-15 and 2026-11-15/16) from the audit records, those findings and the cited records: it may only correct, remove or weaken what is on the card (replace or remove a paragraph, update a study, remove a link, lower the level, set a badge to false, change the contested mark), and only what an audit or review finding names (every finding carries the targets it is about, and code refuses an operation on anything else); it prefers removing to rewriting, and it may not add a study or a paragraph. The one addition is a single sentence, in an existing free-text item, that an objecting audit part expressly asks for as a missing statement, citing only the sources that part quotes and saying no more than its quotes (at most one per part; code checks the part, the sources, the target and the form, and the review agent checks the sentence against the quotes; DECISIONS 2026-11-16). Authors, shared-author counts and positions come from facts computed by code from the cached records, and a deterministic check rejects text that contradicts them. The correction goes through the mechanical checks (a failed check may be tried again up to three times per round, the drafter being given the exact errors; DECISIONS 2026-11-16) and the review agent; after the review, a whole-card review by the review agent checks the corrected card against its cached sources (case-definition labels, each link's text against its source, each claim in the reasons and early signals, a missing contested mark, group and place names), and only an accept in both sends the card to the auditors. A reject in the correction review or in the whole-card review gives the drafting agent a revised attempt (each reviewed again in the same order) as long as the number of decisive `must_fix` findings is lower than at the previous reject of the same review, up to four revisions per round; otherwise the round ends with no audit. Then fresh auditors audit the corrected card as a whole card, seeing only the card and the cited records, with nothing that tells them it was corrected; they run in sequence, and a first `reject` ends the audits without a second one (unless every objecting part of it is `wording`: see the safety valve below). It is published only when the checks passed, both reviews accepted it and both audits say `accept`. If any step fails, the card is unchanged, the correction and its outcome are logged, and the card stays held back and is listed for the founder.

   **A safety valve for wording-only findings (correction rounds only; DECISIONS 2026-11-15).** The review agent and the auditor classify each `must_fix` finding and each objecting audit part as `decisive` or `wording`; the orchestrator never classifies. A finding is `wording` only if resolving it touches none of level, badges, contested mark, layer, links, case definition, a study's role, or any number. A reject whose every `must_fix` finding is `wording` (in the correction review or the whole-card review) does not use up a revised attempt: the orchestrator fixes the named sentences with operations that reword or remove them (`replace_paragraph`, `remove_paragraph`, `update_study` of `finding`); code refuses a fix that changes anything but free text or touches a paragraph no wording finding names. At the audit stage the valve is open when both audits are valid, neither is `accept_lower`, one at least is a `reject`, and every objecting part of both is `wording`: an `accept` and a reject with only wording findings qualify, and so do two such rejects. In every case the `card-reviewer`, in a narrow fix-check mode, sees only each finding, the paragraph before and after and the cited cached records, and answers per fix whether it resolves the finding without adding a claim; if every answer is yes the card goes on (or is published, at the audit stage, with the fix), and if any is no it is held back, with no further round and no new whole-card audit. The classification, the fix and the check are kept in `audits/`, and the change log says the card was published after a wording fix. Any decisive finding, an `accept_lower` or a record without a classification takes the normal path above.

   **Consistency check.** For a sample of audited changes, a second auditor with a fresh context decides the same change: every level change, and one in five of the others, chosen by a script from a recorded seed. A second verdict that differs from the first leaves the card unchanged, is treated as a dispute and is counted. For a whole-card audit the second auditor is run only when the first record is valid and does not say `reject`: a first `reject` is a complete outcome, and the card is held back. The count is reported with every weekly pull request; it is the measure of how reliable the auditor is.

   **Independence, stated honestly.** The auditor shares a model family with the agents it audits and may share their blind spots. The independence that exists lies in what the auditor is shown, not in the model. The model of each agent is listed in `docs/pipeline.md`.

   **Adding links to a published card (link round).** A link on a published card is added through a link round on that card, not through a draft (`docs/pipeline.md`, "Adding links to a published card"; DECISIONS 2026-11-16). Each link is decided on its own: a link that fails at a stage is dropped and the others go on. Each published link needs two agreeing audits, run in sequence. The wording valve applies to link texts, with the limits above. A link round adds no study and does not change the card's layer.

   **Correcting a published card.** An error found in a card that is already published is corrected through a correction round on that card, not through a draft (`docs/pipeline.md`, "Correcting a published card"; DECISIONS 2026-11-17). The path follows steps 2 to 6 above and the tiers: a request from a recorded origin, a review of the published card against its sources (the gate; no finding, no correction), a correction that removes or rewords and adds nothing, mechanical checks, a review of the correction with one revised attempt, and then the tier. A correction that differs from the published card in free text only (a paragraph of a reason, a study's finding, the group of a study that only gives context, a link's text, comments), adds no number and answers only findings the review agent classed as wording is tier 1 and is decided on the checks and the accepting review. Every other correction (a changed group on a study that carries a rung, a level, badge, contested mark, layer, a link's target, step or sources, a case definition, a study role, the core claim, a removed paragraph or a number) is tier 2 and needs two agreeing audits, run in sequence. The default stays conservative: a dispute, a reject in the second round or a card that changed in the meantime leaves the published card unchanged. Each correction is logged as a correction on "What changed", with its tier.

   **Merging.** The founder merges the weekly pull request as an operational step, without reviewing the content. There is no trial period of after-the-fact reading (founder ruling 2026-11-17).
7. **Publication.** Applied changes are published in the weekly site update. The card shows when it was last audited and by whom: the AI auditor, or the founder after an overrule.
8. **Logging.** Every published change gets an entry on "What changed" (date, card, change, one-line reason, source link and the tier). The change log file also records who decided it (`decided_by`); the page does not print that. The change log is public and kept permanently.
9. **Corrections.** An error found later is corrected the same way and logged as a correction. A founder overrule of an auditor decision is a correction with `decided_by: founder`.

AI drafts, checks and audits; the founder sets the direction and the rubric. The site states openly that every level is decided by AI tools and that no medical or research expert has reviewed the content.

### Registry records (registered ongoing studies)

ClinicalTrials.gov records are a second kind of source, used only for the page of registered ongoing studies (`trials.html`, `docs/site.md`). The source rule (founder-agreed in the plan `docs/plan-trial-registry.md`):

- The only registry is ClinicalTrials.gov, read through its public API. Raw responses are cached in `data/cache/`; rate limits are respected.
- Every field about a study, on the page or in the downloadable data (registry number, title, study type, status, countries, planned enrolment, start date, date the record was last updated), is copied by code from the fetched record. Nothing about a study is written by a model or from memory.
- A registered study is not evidence. It is never a study on a card, never a source of a level, badge, contested mark, layer or link, and it changes no file in `cards/`.
- The only AI judgement is which card or cards a study bears on. It is made by the `trial-mapper` agent and checked by the `card-reviewer` (registry mode) before it is published; no auditor decides it, because a mapping moves nothing on a card. A reliability test before first publication (at most one mapping in five rejected) gates the page.
- The list states facts. It does not recommend taking part, names no contact person, and says nothing about whether an intervention works.

### Data resources (the catalogue of ME/CFS data resources)

The page of data resources (`resources.html`, `docs/site.md`) is a third kind of source. The source rule (founder-agreed in the plan `docs/plan-data-catalogue.md`, settled points in its contract):

- **Inclusion rule.** A resource is listed when it holds data or samples from people with ME/CFS, researchers outside the owning group can get access to it, and a public page says how. Registers of research projects, groups or publications are listed too, as a separate category (`register`). Resources for long COVID alone are out; a resource that covers long COVID is in only when its page expressly covers both.
- **Source.** The source of an entry is the resource's own public page (and, when it is a separate page, the page that says how to get access). The page is stored in `data/cache/resources/<date>/<id>/` with its URL and fetch date; the fetch sends a generic client name, reads `robots.txt` first and never works around a bot check or a login. When a host refuses an automated request, the source is instead a copy of the page that the founder saved by hand from a browser (`resources import-saved`): stored in the same folder with its URL and the save date, marked `obtained: hand_saved` and, in the entry, `hand_saved`, and shown on the page as saved by hand. The same checks apply to it, and nothing is done by code to get past a bot check or a login. A resource described only in a journal article, with no page of its own that states how outsiders get access, does not meet the rule, and no PubMed or Europe PMC record is used as a source of an entry. A resource whose page can be neither fetched nor saved by hand in this way is not shown. The candidate list in `docs/pm/IDEAS.md` is a list of leads only; the leads are in `registry/resource-leads.yaml` and hold no value about a resource.
- **Fields.** An entry has only fixed-value fields, a name and links (no operator, no countries): `category` (`data` or `register`), `holds` (`genotypes`, `questionnaires`, `biospecimens`, `molecular`, `clinical`, `sensor`; none for a register), `access` (`open_download`, `registration`, `application`, `not_stated`), `covers` (`me_cfs`, `me_cfs_and_long_covid`) and the page language. Every value other than `not_stated` carries a quote from the stored page, kept in the page's language, and the name of the page it comes from. A value the page does not state is `not_stated` and is not shown; it is never filled from model knowledge or from the candidate list.
- **Checks.** An AI agent (`resource-drafter`) proposes the values and quotes. Code checks that every quote is found in the stored text of its page (Unicode NFKC, whitespace and straight or curly quotation marks folded). The `card-reviewer` (resource mode) judges each value of an entry (`category`, `name`, `covers`, `access` when stated, and each `holds` value) on its own: does its quote support it. Code applies the verdicts and no agent rewrites a value: a rejected value is not shown (a rejected `holds` value is dropped; a register's rejected `access` is not shown); an entry is left out when its name, kind (`category`), coverage or, for data and samples, access is rejected, or no `holds` value is accepted. A left-out entry leaves an existing entry unchanged. An exclusion is judged as a whole. No auditor decides it: an entry moves nothing on a card. Every drafter output goes to the reviewer. Every run has a reliability test that counts values: every judged value of every entry draft plus one value per exclusion draft; when more than one value in five is rejected, nothing new from that run is published. The test gates the page. (The first publication, in November 2026, was tested per entry, under the earlier rule.)
- **Not evidence.** A resource is not a study on a card and never a source of a level, badge, contested mark, layer or link; it changes no file in `cards/`. The page recommends nothing and does not invite anyone to take part in or sign up to a resource. The site holds no patient data.
- **Upkeep.** The weekly run checks that each address still answers and reports those that do not; it changes no entry. Re-reading the content is a separate command, run on request (about quarterly); only an entry whose stored page changed is drafted and reviewed again.

## 7. Out of scope for v1

- Subgroup filtering, search, user accounts, comments, donations.
- Long COVID as a separate section.
- A white paper for researchers and organisations.
- Final approval of the ladder (needs the external reviewer).
- Other diseases and the long-term vision.

## 8. Open questions

- Recruiting a medical or research reviewer. None has been recruited. Until one has, the rules are applied as written and are a draft. No plan for how or when is recorded.
- Are the six rungs and their names clear to patients? Test with readers.
- Whether the review agent can run on a different model family, and at what cost.
- Collaboration with MEpedia or Science for ME. v1 stands alone and links out; contact can come later.

### Resolved 2026-10-31

- Case definitions and Oxford-only evidence: see "Accepted case definitions".
- "Comparable quality" for contested evidence: see "Contested evidence".
- PEM badge: requires a study that measures PEM directly.
- Early signals: card only, fixed heading and sentence pattern, no hype words.
- Long COVID marker: a label at the top of the card, shown with at least one qualifying long COVID study on the same mechanism.
- MEpedia: v1 stands alone.
- External reviewer: not required before launch; replaced for now by the tiered review model in section 6.

### Resolved 2026-11-17

- Tier 1 changes already apply on the mechanical checks and the review agent, without the auditor. The calibration period of 2026-10-31 was replaced on 2026-11-13, and the trial period that replaced it ended on 2026-11-17 (DECISIONS 2026-11-17).
