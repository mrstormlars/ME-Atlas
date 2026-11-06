# ME Atlas – Functional Specification (v1)

October 31, 2026 · Working document · Status: draft

This document says what the site shows, for whom, how a hypothesis gets on it, how it is graded, and how content moves from AI draft to published card. It builds on `docs/ME-Atlas-v1-plan.md` and supersedes its draft status scale (see "Evidence ladder"). The card data model is designed after this spec, from what the pages need to show.

Examples in this document are fictional ("Hypothesis A") and carry no real citations.

## 1. Purpose and readers

ME Atlas gives an honest, evidence-graded overview of the serious hypotheses about what causes ME/CFS. It describes the state of the evidence. It does not give treatment advice.

Scope is ME/CFS first. Long COVID appears as a marker on a card where the evidence overlaps, because the two conditions may share some root causes. It is not a separate section in v1.

### Patients and carers (little energy)

- **Scenario 1.** A newly diagnosed patient wants to know what researchers think is going on. They open the front page, read the one-sentence intro, and see at a glance which ideas have the most evidence behind them. They leave after two minutes without having read a paper.
- **Scenario 2.** A carer hears about a hypothesis in a support group. They find it on the front page, open its card, and read the plain-language core claim and what is contradicted or unreplicated.
- **Scenario 3.** A patient on a bad day reads on a phone, in bed, with large text. They look up one unfamiliar word by tapping it.

### Researchers

- **Scenario 1.** A researcher checks whether a hypothesis has been replicated. They open the card and go straight to the linked studies, with sample size and case definition beside each.
- **Scenario 2.** A reviewer disagrees with a grade. They open the methods page, read the rule that was applied, and see on the card why the level was set.
- **Scenario 3.** A researcher returns after a month and opens "What changed this week" to see which cards moved, and why.

## 2. Inclusion rule for hypotheses

A hypothesis is listed when it has **at least one peer-reviewed study with data from an ME/CFS cohort defined by a recognised case definition** (see "Accepted case definitions" in section 3).

The rule judges **method, not origin**. Any approach, conventional or alternative, that uses scientific method and meets the rule is admitted.

Excluded, and why:

- **Ideas with no peer-reviewed cohort data yet.** They cannot be graded on any rung; they may be tracked internally as candidates.
- **Studies of healthy people, animals or cells only.** These can support plausibility on a card but do not admit a hypothesis alone.
- **Cohorts without a stated case definition.** Without one we cannot tell whether the patients had ME/CFS.
- **Claims backed only by opinion, anecdote, patient surveys without a clinical comparison, or non-peer-reviewed material.** Not enough to check.
- **Treatment products and commercial claims.** The site lists hypotheses about causes, not remedies.

Hypotheses are **not mutually exclusive**. They may be links in one causal chain, or may apply to different patient subgroups. The front page says so.

## 3. Evidence ladder

**Draft — pending expert review.** No external medical or research reviewer is attached yet; one will be recruited once the site can be shown. Until then the ladder is applied as written and the site says it has not been expert-reviewed. Grading follows only this published ladder; editors do not add criteria.

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

Down or held back: failed replications; a finding that rests only on a broad case definition (Oxford-only cohorts) or a very small sample; no control group; no preregistration; results that conflict with equally strong studies (see "Contested evidence"). A retracted study is removed from the evidence and the level is re-assessed.

Volume is not evidence. The number of papers, citations or news items never moves a hypothesis.

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

### The two badges

Shown on every card, separate from the bar, each yes or no:

1. **Diagnostic marker validated in an independent cohort.** Yes only when a measurable marker linked to the hypothesis has been tested in a second, independent patient group, with a stated case definition.
2. **Explains post-exertional malaise (PEM).** Yes only when at least one study at level 2 or above measures PEM directly (for example a repeated exercise test on two consecutive days, or a controlled exertion challenge with symptoms tracked afterwards) and links it to the hypothesis. The link must connect the proposed mechanism to the symptoms after exertion in the same patients; a measured change that is itself the hypothesised abnormality (for example a fall in oxygen use on the second test) does not on its own explain PEM. A cohort of ME/CFS patients alone is not enough. (PEM is the worsening of symptoms after physical or mental effort.)

Separate tracks for mechanism, diagnosis and treatment were rejected because they are harder to read.

### Contested evidence

A level is **contested** when at least one study of comparable or higher quality contradicts the finding that supports it. Comparable quality means all three: the same or a stricter case definition (CCC, ICC and IOM 2015 rank above Fukuda and Holmes 1988, which rank equal and above Oxford), a control group, and at least half the sample size of the study it contradicts. Sample size here means the number of patients in the measurement that bears on the finding, not the whole study when only part of it was measured. A rung that rests on more than one study (for example an original finding and its independent replication at level 3) is contested when a study of comparable quality contradicts any study the rung needs.

- **Who decides:** the founder, as a tier 2 decision (see section 6), with the contradicting study linked on the card and the reason written in plain sentences, split into short paragraphs with their own sources when it needs more than two. AI may propose a conflict; it never sets one.
- **How it is shown:** the bar is filled up to the highest uncontested rung; the rung or rungs under dispute are drawn as a **hatched segment**. The card lists both sides.
- **How it ends:** a contested mark is removed when the conflict is resolved (for example a larger study settles it), recorded on "What changed this week".

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

The first four layers hold hypothesis cards. The symptom layer is not hypotheses: it is a fixed list taken from the accepted case definitions, each symptom sourced to the document that lists it. A card that could sit in two layers (for example herpesvirus reactivation as trigger or as consequence of immune dysfunction) gets one layer and a link that expresses the other reading; the ambiguity is written out, not hidden.

**Links.** A link from one node to another grades a narrower claim than the ladder: "A drives B in ME/CFS patients". It has three steps:

| Step | Key | Requires |
| --- | --- | --- |
| 1 Proposed | `proposed` | A peer-reviewed source (a review counts) that states the link. Not studied directly in patients. |
| 2 Associated | `associated` | A study in an ME/CFS cohort with a recognised case definition that measured both ends in the same patients and reports a relation between them. |
| 3 Direction supported | `directional` | In patients: temporal order (A before B), an intervention on A that changes B, or a mediation analysis. A review alone never reaches this step. |

- **Case definitions** are the ladder's: Oxford-only evidence stays at step 1, and a source that is a review (`design: other`) cannot carry step 2 or 3.
- **No link without a source, at every step.** "Proposed by [review]" is a source; the editorial team's own reasoning is not. Links may run both ways and form loops.
- **A link never raises a card's level.** A study that measured both ends and found no relation is recorded as a `context` study and the link text says so. Links have no contested mark in v1.
- **Open questions** are empty boxes, never claims: a question sourced to a publication that asks it, or marked as the editorial team's own question.
- **Convergence is counted, not judged.** A node with two or more incoming links from different cards is listed as a *candidate common mechanism*; a card with two or more links out as a *candidate root*. Nobody writes "the common cause is".
- **Who decides:** setting a card's layer and adding or changing a link are founder decisions, like levels, badges and contested marks (section 6). AI may propose and the `card-reviewer` checks each link against its sources; it never sets either.

## 4. Pages

### Front page

- **Shows:** one-sentence intro; a pipeline chart with one horizontal bar per hypothesis against the six rungs of the ladder; contested segments hatched; the two badges as small marks; a long COVID marker where evidence overlaps; the sentence that hypotheses are not mutually exclusive; a draft notice on the ladder. Sorted by **furthest along** on the published ladder (ties alphabetically).
- **Does not show:** "most promising" or any editorial ranking; paper counts, trends or momentum; subgroup filters (none in v1); treatment suggestions; anything unsourced.

### Hypothesis card page

- **Shows:** name; core claim in plain words; level, badges and contested state, with the reason for each; key supporting studies (link, sample size, case definition, year); contradicting studies; replication status; subgroups it may apply to; who is working on it; early signals; a small "Also studied in long COVID" label at the top of the card when at least one long COVID study that meets the inclusion rule points to the same mechanism; last checked (date, and whether by the AI review pair or by the founder).
- **Early signals** come only from studies with a recognised case definition confirmed in the abstract or full text; a study whose case definition is unverified or not stated is not shown as an early signal. They appear only on the card, under the fixed heading "Early signals: not yet repeated", in a fixed sentence pattern ("A study of n=… found …"). They never appear on the front page, and words such as "promising", "breakthrough" or "hope" are not used.
- **Does not show:** advice on what a patient should do; a verdict that a hypothesis is "right" or "wrong"; any sentence without a source link.

### What changed this week

- **Shows:** the dated log of published changes: new hypotheses, level changes, new or removed contested marks, new studies added; each entry with a one-line reason and a link to the card and source.
- **Does not show:** unreviewed AI drafts; rejected suggestions; commentary on individual researchers.

### Methods page

- **Shows:** the evidence ladder and its draft status; the inclusion rule; the Bradford Hill mapping; the badge definitions; how contested evidence is decided; the editorial flow and its review tiers; the role of AI and how its work is checked; who makes human decisions; a plain statement that no medical or research expert has reviewed the content yet (until one has); known limits.
- **Does not show:** private reviewer discussions; claims about accuracy that are not measured.

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

The pipeline runs mostly on AI, with mechanical checks in code and a human for high-impact changes and disputes.

1. **Weekly fetch.** The pipeline fetches new papers from PubMed and Europe PMC and stores raw responses.
2. **Drafting agent.** One AI agent classifies papers by hypothesis, extracts study data (sample size, case definition) and writes a draft card update. Each AI output keeps the source id it came from. Output goes to `drafts/` only.
3. **Mechanical checks (code, not AI).** Every cited id exists in a fetched record; title, year, sample size and case definition match that record; every sentence has a source link. A draft that fails is sent back to the drafting agent.
4. **Review agent.** A second, independent AI agent checks the draft against the sources, the inclusion rule and the ladder. It sees the draft and the source records, not the drafting agent's reasoning. Where possible it runs on a different model or prompt family, so the two do not share the same blind spots.
5. **Second round.** If the review agent rejects the draft, the drafting agent gets one revised attempt, which is checked again (steps 3–4). If they still disagree after two rounds, the change goes to the **parking lot** for the founder.
6. **Decision by tier.**

   | Tier | Change | Who decides |
   | --- | --- | --- |
   | 1 | Adding a study to a card, factual text, change-log entry | Published automatically when the mechanical checks pass and both agents agree |
   | 2 | Setting or changing a level, a badge or a contested mark; adding or removing a hypothesis | The founder, yes or no, in a weekly list |
   | 3 | Anything still disputed after two agent rounds | The founder, from the parking lot. If unresolved, the lower level stands and the disagreement is noted on the card |

   **Calibration period:** for the first weeks the founder approves every change, including tier 1, to measure how often the agents are wrong. Tier 1 auto-publishing starts only when the founder rules the error rate acceptable, recorded in `docs/pm/DECISIONS.md`.
7. **Publication.** Approved changes are published in the weekly site update. The card shows when it was last checked and whether by the AI review pair or by the founder.
8. **Logging.** Every published change gets an entry on "What changed this week" (date, card, change, one-line reason, source link, and which tier decided it). The change log is public and kept permanently.
9. **Corrections.** An error found later, including one reported by a reader, is corrected the same way and logged as a correction.

AI drafts and checks; a human decides every level, badge, contested mark and new hypothesis. The site states openly that content is AI-reviewed and not yet expert-reviewed.

## 7. Out of scope for v1

- The card data model (YAML vs JSON, field names): next task, built from this spec.
- Real evidence cards or real hypotheses with citations (this spec and the mockup use none).
- Site generator, pipeline code, PubMed fetching.
- Subgroup filtering, search, user accounts, comments, donations.
- Long COVID as a separate section.
- A white paper for researchers and organisations.
- Final approval of the ladder (needs the external reviewer).
- Other diseases and the long-term vision.

## 8. Open questions

- Recruit a medical or research reviewer once the site can be shown (planned: share on X and in ME forums and Facebook groups for feedback and volunteers).
- Are the six rungs and their names clear to patients? Test with readers at that point.
- When to end the calibration period and turn on tier 1 auto-publishing.
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
