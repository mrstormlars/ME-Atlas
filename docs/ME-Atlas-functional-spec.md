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

A hypothesis is listed when it has **at least one peer-reviewed study with data from an ME/CFS cohort defined by a recognised case definition** (for example Fukuda, CCC, ICC, IOM 2015; Oxford counts but is flagged as broad).

The rule judges **method, not origin**. Any approach, conventional or alternative, that uses scientific method and meets the rule is admitted.

Excluded, and why:

- **Ideas with no peer-reviewed cohort data yet.** They cannot be graded on any rung; they may be tracked internally as candidates.
- **Studies of healthy people, animals or cells only.** These can support plausibility on a card but do not admit a hypothesis alone.
- **Cohorts without a stated case definition.** Without one we cannot tell whether the patients had ME/CFS.
- **Claims backed only by opinion, anecdote, patient surveys without a clinical comparison, or non-peer-reviewed material.** Not enough to check.
- **Treatment products and commercial claims.** The site lists hypotheses about causes, not remedies.

Hypotheses are **not mutually exclusive**. They may be links in one causal chain, or may apply to different patient subgroups. The front page says so.

## 3. Evidence ladder

**Draft — pending expert review.** Not final until an external medical or research reviewer has gone through it. Grading follows only this published ladder; editors do not add criteria.

The bar for a hypothesis shows **causal evidence**, rung 0 to 5.

| Level | Plain-language name | What it means |
| --- | --- | --- |
| 0 | Proposed | An idea with a reasoned argument, but no direct patient data yet. |
| 1 | First signs | One or more small or uncontrolled studies point towards it. |
| 2 | Backed in a defined group | A controlled study in patients with a strict, recognised case definition supports it. |
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

### The two badges

Shown on every card, separate from the bar, each yes or no:

1. **Diagnostic marker validated in an independent cohort.** Yes only when a measurable marker linked to the hypothesis has been tested in a second, independent patient group, with a stated case definition.
2. **Explains post-exertional malaise (PEM).** Yes only when at least one study at level 2 or above examines PEM in connection with the hypothesis. (PEM is the worsening of symptoms after physical or mental effort.)

Separate tracks for mechanism, diagnosis and treatment were rejected because they are harder to read.

### Contested evidence

A level is **contested** when at least one study of comparable or higher quality (same or stricter case definition, similar or larger sample, controlled design) contradicts the finding that supports it.

- **Who decides:** the editorial team, with the contradicting study linked on the card and the reason written in one or two plain sentences. AI may suggest a conflict; it never sets one.
- **How it is shown:** the bar is filled up to the highest uncontested rung; the rung or rungs under dispute are drawn as a **hatched segment**. The card lists both sides.
- **How it ends:** a contested mark is removed when the conflict is resolved (for example a larger study settles it), recorded on "What changed this week".

## 4. Pages

### Front page

- **Shows:** one-sentence intro; a pipeline chart with one horizontal bar per hypothesis against the six rungs of the ladder; contested segments hatched; the two badges as small marks; a long COVID marker where evidence overlaps; the sentence that hypotheses are not mutually exclusive; a draft notice on the ladder. Sorted by **furthest along** on the published ladder (ties alphabetically).
- **Does not show:** "most promising" or any editorial ranking; paper counts, trends or momentum; subgroup filters (none in v1); treatment suggestions; anything unsourced.

### Hypothesis card page

- **Shows:** name; core claim in plain words; level, badges and contested state, with the reason for each; key supporting studies (link, sample size, case definition, year); contradicting studies; replication status; subgroups it may apply to; who is working on it; early signals, labelled unreplicated; long COVID marker; last reviewed (date and reviewer).
- **Does not show:** advice on what a patient should do; a verdict that a hypothesis is "right" or "wrong"; any sentence without a source link.

### What changed this week

- **Shows:** the dated log of published changes: new hypotheses, level changes, new or removed contested marks, new studies added; each entry with a one-line reason and a link to the card and source.
- **Does not show:** unreviewed AI drafts; rejected suggestions; commentary on individual researchers.

### Methods page

- **Shows:** the evidence ladder and its draft status; the inclusion rule; the Bradford Hill mapping; the badge definitions; how contested evidence is decided; the editorial flow; the role of AI; who is on the editorial team; known limits.
- **Does not show:** private reviewer discussions; claims about accuracy that are not measured.

### Glossary page

- **Shows:** every term from the shared glossary file, in alphabetical order, with a plain-language explanation, and links back to the pages that use it.
- **Does not show:** terms that no page uses; explanations that differ from the hover/tap text (same source).

## 5. Plain language and accessibility

- **English, plain words.** Short sentences. Avoid jargon and abbreviations. Where a technical term or abbreviation is needed, it is marked visibly (dotted underline) and shows a short explanation.
- **One glossary file** is the single source for all explanations. It renders the glossary page and every in-page explanation. No explanation is written inline.
- **Explanation behaviour.** The explanation appears on mouse hover, on tap or click, and on keyboard focus. Terms are focusable controls described by their explanation. Escape, or tapping elsewhere, closes a tapped explanation. Hover is never the only way to read it.
- **Contrast.** Text and chart marks meet WCAG 2.2 AA contrast at least (4.5:1 for body text). Meaning is never carried by colour alone: levels have text labels, contested segments use a hatch pattern, badges use words.
- **Text size.** Body text at least 18 px equivalent; layout holds when the user enlarges text to 200%.
- **Phone.** Works at 375 px width with no horizontal scrolling; tap targets at least 44 px.
- **No mouse.** Everything reachable and operable by keyboard, with a visible focus outline and a logical order; the chart has a text equivalent (a list or table with each hypothesis, level and badges).
- **Calm.** No animation needed to understand anything; respect reduced-motion settings; no pop-ups.

## 6. Editorial flow

1. **Weekly fetch.** The pipeline fetches new papers from PubMed and Europe PMC and stores raw responses.
2. **AI sorting and drafting.** AI classifies papers by hypothesis, extracts study data (sample size, case definition) and writes a draft card update. Each AI output keeps the source id it came from. Output goes to `drafts/` only.
3. **Human review.** An editor checks every claim against the source, the inclusion rule and the ladder.
4. **Decision.** Editors alone set or change a level, a badge or a contested mark, and approve moving a draft into `cards/`. Disagreement goes to the medical or research reviewer. If still unresolved, the lower level stands and the disagreement is noted.
5. **Publication.** Approved changes are published in the weekly site update, with the card's last-reviewed date and reviewer set by the editor.
6. **Logging.** Every published change gets an entry on "What changed this week" (date, card, change, one-line reason, source link). The change log is public and kept permanently.
7. **Corrections.** An error found later is corrected the same way and logged as a correction.

AI drafts, humans decide. No grade is published without human approval.

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

- Who is the external medical or research reviewer, and what review process do they want?
- Are the six rungs and their names clear to patients? Test with a few readers.
- Exact threshold for "comparable quality" when deciding contested evidence.
- Which recognised case definitions are accepted, and how is Oxford-only evidence capped (flag only, or limit to level 1)?
- Does the PEM badge need a stricter rule (a study that measures PEM directly)?
- How are "early signals" shown without becoming treatment hype?
- Where should the long COVID marker sit on a card, and what is the minimum overlap to show it?
- Should the site live inside MEpedia, beside it, or stand alone?
