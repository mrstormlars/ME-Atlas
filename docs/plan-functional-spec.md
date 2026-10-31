# Plan: ME Atlas functional specification and front-page mockup

October 31, 2026 · For `/orchestrator`

## Goal

Turn the idea sketch in `docs/ME-Atlas-v1-plan.md` into a **functional specification**: one document that says what the site shows, for whom, how a hypothesis gets on it, how it is graded, and how content moves from AI draft to published card. Then test the front page with a clickable mockup using fictional data, before the card data model is designed.

The specification comes before the data model because the data model must hold exactly what the pages need to show.

## Agreed direction (from brainstorm with the founder, 2026-10-31)

1. **Front page = pipeline chart.** One horizontal bar per hypothesis against fixed milestones (the status scale), like a drug-development pipeline chart. Sorted by how far the evidence has come. Contested evidence is shown as a hatched segment on the bar. No "momentum" or paper-count metric: volume is not evidence.
2. **Wording: "furthest along", never "most promising".** Ranking follows the published scale only, not editorial opinion.
3. **One axis plus two badges.** The bar shows *causal evidence*. Each card additionally carries two yes/no badges: "Diagnostic marker validated in an independent cohort" and "Explains post-exertional malaise (PEM)". Separate tracks for mechanism / diagnosis / treatment were rejected as harder to read.
4. **Treatment success is not proof of cause.** The draft level 5 ("treatment based on it works") must be reworded. A working treatment is one kind of experimental evidence, not confirmation of the root cause.
5. **Hypotheses are not mutually exclusive.** The site says so on the front page: they may be links in one chain or apply to different subgroups.
6. **Inclusion rule judges method, not origin.** A hypothesis is listed when it has at least one peer-reviewed study with data from an ME/CFS cohort defined by a recognised case definition. This admits any approach, conventional or alternative, that uses scientific method.
7. **Grading builds on established frameworks.** The rubric is anchored in the Bradford Hill criteria for causation plus the existing quality factors (case definition, sample size, controls, preregistration, conflicting results). It is marked as a draft until an external medical or research reviewer has gone through it.
8. **Scope: ME/CFS first.** Long COVID appears as a marker on cards where the evidence overlaps, since the two may share some root causes.
9. **No subgroup filtering in v1.** Subgroups are listed on each card; filtering can come later.
10. **Site language is English, plain words.** Avoid jargon and abbreviations. Where a technical term or abbreviation is needed, it is marked and shows a short plain-language explanation on hover, **and on tap or keyboard focus** (hover does not exist on phones). All explanations come from one shared glossary file, which also renders as a glossary page.

## Steps

1. **Write `docs/ME-Atlas-functional-spec.md`** (English) with these sections:
   - Purpose and readers: patients and carers with little energy, researchers who check sources. Two or three short usage scenarios each.
   - Inclusion rule for hypotheses (direction point 6), including what is excluded and why.
   - Evidence ladder: a revised draft scale 0–5 with plain-language names, what moves a hypothesis up or down, the Bradford Hill mapping, the two badges, how contested evidence is decided and shown. Marked "draft — pending expert review".
   - Pages: front page (pipeline chart), hypothesis card page, "What changed this week", methods page, glossary page. For each: what it shows and what it deliberately does not show.
   - Plain-language and glossary rules (direction point 10), including accessibility: contrast, text size, works on a phone, works without a mouse.
   - Editorial flow: from weekly fetch to published change, who decides what, and how a change is logged on the "What changed" page.
   - Out of scope for v1 (see below) and open questions.
2. **Build `docs/mockups/front-page.html`**: one self-contained static HTML file showing the pipeline chart with 5–6 **fictional** hypotheses ("Hypothesis A", "Hypothesis B", …), at least one with a contested segment and one with each badge, plus at least three glossary terms with hover/tap/focus explanations. A visible banner says the data is fictional. No real study, author, PMID or result appears anywhere in the mockup.
3. **Align existing documents**: in `docs/ME-Atlas-v1-plan.md`, add one line under the draft status scale pointing to the functional spec as the current version. In `docs/pm/STATUS.md`, make "functional specification and front-page mockup" priority 1, ahead of the data model.

## Done when

- [ ] `docs/ME-Atlas-functional-spec.md` exists and has every section listed in step 1.
- [ ] Every point under "Agreed direction" is reflected in the spec, with no point contradicted.
- [ ] The spec contains no real citations (no PMIDs, DOIs, author names or study results). Where an example is needed, it is clearly fictional or marked `TODO: verify`.
- [ ] The spec never uses "most promising" as a ranking label and contains no treatment advice.
- [ ] The evidence ladder is labelled as a draft pending expert review, and level 5 no longer equates treatment success with confirmed cause.
- [ ] `docs/mockups/front-page.html` opens in a browser offline (no external scripts or fonts), shows the fictional banner, the pipeline bars, a contested segment and both badges.
- [ ] Glossary explanations in the mockup appear on mouse hover, on tap, and on keyboard focus.
- [ ] The mockup is readable at 375 px width without horizontal scrolling.
- [ ] `docs/ME-Atlas-v1-plan.md` and `docs/pm/STATUS.md` changed only as described in step 3.
- [ ] No files outside `docs/` are changed.

## Out of scope

- The card data model (YAML vs JSON, field names): next task, built from this spec.
- Real evidence cards or real hypotheses with citations.
- Site generator, pipeline code, PubMed fetching.
- Subgroup filtering, search, user accounts, comments, donations.
- Long COVID as a separate section of the site.
- A white paper aimed at researchers and organisations: later, once real cards exist.
- Final approval of the grading scale: that needs the external reviewer.
