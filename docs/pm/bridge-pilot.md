# Bridge search pilot

Part C of `docs/plan-wider-sources.md`. A manual-scale pilot that ends in this report. It changes no card, no draft, no site text and not the weekly pipeline, and it sets no level, badge, contested mark, layer or link.

## Protocol

Written and committed on 2026-11-16, before any search was run. Nothing below is changed after the first search; a deviation is recorded under "Results" as a deviation.

Choices that the plan leaves open are marked **(orchestrator default)**.

### 1. Questions

Eight relations A → B. The founder chose the five on 2026-11-16 (DECISIONS). On the same day, `uv run python -m me_atlas.map report` listed each of the five at step `proposed` (`drafts/` is empty, so `--drafts` gives the same report).

| Id | Kind | A (from) | B (to) | Step in the map on 2026-11-16 |
|---|---|---|---|---|
| Q1 | founder | oxidative-nitrosative-stress | endothelial-dysfunction | proposed |
| Q2 | founder | autonomic-imbalance | orthostatic-intolerance-cerebral-blood-flow | proposed |
| Q3 | founder | reduced-nk-cell-function | herpesvirus-reactivation | proposed |
| Q4 | founder | tryptophan-kynurenine-metabolism | neuroinflammation | proposed |
| Q5 | founder | autoimmunity-autoantibodies-b-cells | orthostatic-intolerance-cerebral-blood-flow | proposed |
| C1 | positive control | autoimmunity-autoantibodies-b-cells | autonomic-imbalance | associated |
| B1 | base rate | circadian-rhythm-disruption | orthostatic-intolerance-cerebral-blood-flow | no link either way |
| B2 | base rate | circadian-rhythm-disruption | oxidative-nitrosative-stress | no link either way |

**Positive control (orchestrator default).** The map has two card-to-card links at step `associated` whose two ends both have theme entries: autoimmunity → HPA axis and autoimmunity → autonomic imbalance. The second was chosen because autonomic dysfunction is studied in many autoimmune conditions outside ME/CFS, so a systematic review on it is expected to exist. It shares its A end with Q5; this is a limitation of the control.

**Base-rate pairs.** Drawn from the 169 unordered pairs of the 20 cards in `cards/` with no link in either direction, by this script, run once on 2026-11-16 from the repository root:

```python
import itertools, random
from pathlib import Path
from me_atlas import cards as cardlib

cards = sorted(
    (cardlib.load_card(p) for p in Path("cards").glob("*.yaml") if p.name != "changelog.yaml"), key=lambda c: c.slug
)
by = {c.slug: c for c in cards}


def linked(a, b):
    return any(l.to == b for l in by[a].links) or any(l.to == a for l in by[b].links)


pairs = [(a, b) for a, b in itertools.combinations(sorted(by), 2) if not linked(a, b)]
print(len(by), "cards;", len(pairs), "unlinked pairs")
print(random.Random(20261116).sample(pairs, 2))
```

Output: `20 cards; 169 unlinked pairs` and `[('circadian-rhythm-disruption', 'orthostatic-intolerance-cerebral-blood-flow'), ('circadian-rhythm-disruption', 'oxidative-nitrosative-stress')]`. The seed is the date. A is the slug that sorts first. Both pairs share the circadian card; that is how the draw fell and it is kept.

### 2. Search terms

Each end is the card's entry in `config/card_themes.yaml`, unchanged: every `mesh` heading as `"<heading>"[MeSH Terms]` and every `terms` entry as `"<term>"[Title/Abstract]`, joined with OR. The `related` headings are not used. The terms are the card's, not tailored to the question; some are broad or are methods (for example `Magnetic Resonance Spectroscopy` for neuroinflammation, `Rituximab` for autoimmunity). They are kept as they are, so that no question is tuned by hand.

| Card | Headings and terms |
|---|---|
| oxidative-nitrosative-stress | Oxidative Stress, Antioxidants, Reactive Oxygen Species, Glutathione; nitrosative |
| endothelial-dysfunction | Endothelium, Vascular, Microcirculation, Blood Coagulation; endothelial, endothelium |
| autonomic-imbalance | Sympathetic Nervous System, Parasympathetic Nervous System, Vagus Nerve, Baroreflex; heart rate variability, vagal, sympathovagal, parasympathetic |
| orthostatic-intolerance-cerebral-blood-flow | Tilt-Table Test, Hypotension, Orthostatic, Cerebrovascular Circulation, Orthostatic Intolerance, Postural Orthostatic Tachycardia Syndrome; orthostatic |
| reduced-nk-cell-function | Killer Cells, Natural, Cytotoxicity, Immunologic; natural killer, NK cell, NK cells |
| herpesvirus-reactivation | Herpesvirus 4, Human, Herpesvirus 6, Human, Herpesviridae Infections, Epstein-Barr Virus Infections, Cytomegalovirus; herpesvirus, herpesviruses, Epstein-Barr |
| tryptophan-kynurenine-metabolism | Tryptophan, Kynurenine; kynurenine, indoleamine |
| neuroinflammation | Neuroinflammatory Diseases, Microglia, Magnetic Resonance Spectroscopy; neuroinflammation, microglial |
| autoimmunity-autoantibodies-b-cells | Autoantibodies, Autoimmune Diseases, B-Lymphocytes, Rituximab; autoimmunity, autoantibody |
| circadian-rhythm-disruption | Circadian Rhythm, Melatonin, Chronobiology Disorders, Activity Cycles; circadian, melatonin, chronobiology |

The **ME/CFS block** is block 1 of `config/pubmed_query.txt`; the **long COVID block** is the first half of its block 2 (the long COVID headings and terms, without the ME/CFS clause).

### 3. Two arms per question, both on PubMed

The literal query text of every question and arm is in `config/bridge_pilot.yaml`, committed with this protocol and run verbatim. The forms:

- **General:** (A) AND (B) AND (systematic review OR meta-analysis as publication type) NOT (ME/CFS block) NOT (animals NOT humans).
- **Long COVID:** (A) AND (B) AND (long COVID block) AND (same publication types) NOT (ME/CFS block) NOT (animals NOT humans).
- **Long COVID original studies, count only:** (A) AND (B) AND (long COVID block) NOT (ME/CFS block) NOT (animals NOT humans) NOT (Review, Systematic Review, Meta-Analysis, Letter, Comment, Editorial or Case Reports as publication type). Only the number is recorded; no record is fetched or read.

**Humans filter (orchestrator default):** `NOT ("Animals"[MeSH Terms] NOT "Humans"[MeSH Terms])`, not `"Humans"[MeSH Terms]`, so that recent records not yet indexed with MeSH are kept. Animal-only reviews that slip through are caught by the extraction (point 5).

### 4. Screening limit

- An arm that returns 40 or fewer records is screened in full.
- An arm that returns more is run again in its `restricted` form: each end's headings as `[MeSH Major Topic]` and its terms in `[Title]` only (the same idea as "core match" in `docs/survey.md`) **(orchestrator default: the plan says "MeSH major topic"; terms have no major-topic form, so they are restricted to the title)**. The 40 most recent records of the restricted result are screened, "most recent" being PubMed's default ESearch order (newest entry date first) **(orchestrator default)**. Both totals are recorded.
- If the restricted form returns 0, the 40 most recent records of the unrestricted result are screened instead, and the report says so **(orchestrator default)**.
- The limit is not changed after the first search.

### 5. Extraction per record

The `bridge-surveyor` agent reads the title and abstract of each screened record and writes, per PMID:

- `statement`: does the review make a statement on the relation A → B in humans: `yes`, `no`, or `animal_or_cell_only`;
- for `yes` rows: `relation` (`present`, `absent` or `inconsistent`, as the review reports it), `population` (the condition or group, as the record states it), `direction` (`a_to_b`, `b_to_a`, `association`, or `not_stated`) **(orchestrator default: the value lists)**, `meta_analysis` (true or false), `studies_pooled` (the number of studies as the record states it, or null), and `quote` (one sentence copied verbatim from the title or abstract).

Code rejects a file that names a PMID not in the context file or whose quote is not found verbatim in the cached record. A fresh `card-reviewer` then checks every `yes` row against the cached record: is it about humans, about this relation and this direction, and is the population stated correctly.

**Review quality is not graded.** The project has no published criteria for that, and none are invented here.

### 6. Outcome per question and arm

From the rows the reviewer accepted **(orchestrator default: the rule)**:

- *reported in other conditions*: at least one accepted `yes` row, and all accepted `yes` rows say `present`;
- *mixed*: accepted `yes` rows that include `absent` or `inconsistent`;
- *only animal or cell evidence*: no accepted `yes` row and at least one `animal_or_cell_only` row;
- *no review found*: anything else, including an arm with no hits.

Results are written in the fixed framing: "Reported in other conditions (systematic review, population: …). Not studied in ME/CFS." No result is a finding about ME/CFS, and no treatment in another condition is named as an option for ME/CFS.

### 7. How the pilot is judged

- **Positive control:** C1 has at least one accepted `yes` row with `relation: present` in either arm. If not, the method is not working and the other results are not interpreted.
- **Base rate:** the base-rate pairs return clearly fewer accepted hits than the five. Made checkable **(orchestrator default)**: met when (a) the share of base-rate pairs whose general arm has outcome *reported in other conditions* or *mixed* is lower than the share among the five, and (b) the mean number of accepted `yes` rows per base-rate pair (both arms) is at most half the mean per founder question. The raw numbers are reported whatever the outcome. If the criterion is not met, the report says that a hit carries little information.
- **Reviewer agreement:** the reviewer rejects no more than one in five `yes` rows. More means abstract screening is too unreliable to scale.
- **Usefulness:** the founder reads the five results and rules whether they are useful enough to show.

### 8. Where things are

- Queries: `config/bridge_pilot.yaml`.
- Records: `data/cache/bridge/pubmed/<pmid>.xml`, apart from the ME/CFS cache `data/cache/pubmed/`, so that the survey census and the weekly pipeline do not see them **(orchestrator default)**.
- Context files, hit counts and the agent's JSON: `data/pipeline/<date>-bridge-pilot/` (generated, not committed).

## Results

Run on 2026-11-16, after the protocol commit (`ecc84a9`), with `uv run python -m me_atlas.survey bridge run` and the queries in `config/bridge_pilot.yaml` unchanged. The `bridge-surveyor` agent read one context file per arm with hits (10 files, 127 records); every file passed `survey bridge validate`. A fresh `card-reviewer` checked the 21 `yes` rows against the cached records: 12 accepted, 9 rejected. No deviation from the protocol.

Every source below is a record fetched from PubMed and cached under `data/cache/bridge/pubmed/`; titles are as PubMed gives them, and every quote is copied from the record's title or abstract. **Review quality is not graded**: the project has no published criteria for it. Nothing here is a finding about ME/CFS, and no intervention studied in another condition is an option for ME/CFS.

### Counts

| Question | General: hits | General: screened | Long COVID: reviews | Long COVID: original studies (count only) |
|---|---|---|---|---|
| Q1 oxidative stress → endothelial dysfunction | 94 | 10 (restricted form, 10 hits) | 1 | 8 |
| Q2 autonomic imbalance → orthostatic intolerance | 26 | 26 | 1 | 29 |
| Q3 NK cell function → herpesvirus reactivation | 13 | 13 | 0 | 3 |
| Q4 tryptophan/kynurenine → neuroinflammation | 17 | 17 | 0 | 2 |
| Q5 autoimmunity → orthostatic intolerance | 7 | 7 | 0 | 6 |
| C1 autoimmunity → autonomic imbalance (positive control) | 17 | 17 | 0 | 3 |
| B1 circadian rhythm / orthostatic intolerance (base rate) | 6 | 6 | 0 | 1 |
| B2 circadian rhythm / oxidative stress (base rate) | 90 | 29 (restricted form, 29 hits) | 0 | 0 |

Each long COVID arm with one hit was screened in full. The query text of every arm is in `config/bridge_pilot.yaml`.

### Outcome per question and arm

Rows: `yes` / `no` / `animal_or_cell_only` as the surveyor wrote them; "accepted" is after the reviewer.

**Q1 oxidative-nitrosative-stress → endothelial-dysfunction.**
- General (10 screened; 3 yes, 6 no, 1 animal or cell only; 1 accepted): *reported in other conditions.* Reported in other conditions (review, population: critically ill patients). Not studied in ME/CFS.
  - pmid:17713412, "Antioxidant therapy in critical care--is the microcirculation the primary target?" (2007): "The microcirculation is particularly susceptible to oxidative stress that causes hemodynamic instability, leading to multiple organ failure due to systemic inflammatory response syndrome." Direction A → B; not a meta-analysis. PubMed tags it Systematic Review, but the record calls itself "not a systematic review of the clinical evidence".
- Long COVID (1 screened; 1 no): *no review found.*

**Q2 autonomic-imbalance → orthostatic-intolerance-cerebral-blood-flow.**
- General (26 screened; 9 yes, 17 no; 5 accepted, one of them `inconsistent`): *mixed.* Reported in other conditions (systematic reviews, populations below), with one meta-analysis reporting the relation for one kind of measure and not another. Not studied in ME/CFS.
  - pmid:31888497, "Heart rate and heart rate variability comparison between postural orthostatic tachycardia syndrome versus healthy participants; a systematic review and meta-analysis." (2019). Population: people with POTS compared with healthy participants; meta-analysis, 20 studies. "POTS patients have a higher HR than healthy patients after HUTT and lower HRV in terms of time domain measure but not in terms of frequency domain measure." Relation inconsistent.
  - pmid:39538129, "Postural orthostatic tachycardia syndrome after COVID-19 vaccination: A systematic review." (2024). Population: people with POTS after COVID-19 vaccination; 10 studies, 7 of them case reports or case series. "Diagnostic findings across studies included elevated norepinephrine levels and reduced heart rate variability."
  - pmid:37531984, "Cardiovascular disease in space: A systematic review." (2023). Population: astronauts after spaceflight; 35 studies in the whole review. "Orthostatic intolerance studies found astronauts experienced altered heart rate variability, baroreflex response, and blood pressure changes post-flight."
  - pmid:35863181, "Varicella-zoster virus infection and autonomic dysfunction." (2022). Population: people with varicella-zoster virus infection; 45 studies, 2 of them on cardiovascular dysfunction. "(1) VZV infection rarely produces orthostatic hypotension, which involves diffuse sympathetic dysfunction by polyneuropathy." Direction A → B.
  - pmid:33947784, "Natural History of Afferent Baroreflex Failure in Adults." (2021). Population: adults with afferent baroreflex failure. "ABF should be suspected in patients with prior head and neck cancer treated by radiation or surgery who present with labile hypertension and orthostatic hypotension." PubMed tags it Systematic Review; the reviewer notes the record describes a single-centre retrospective chart review, not a review of studies.
- Long COVID (1 screened; 1 no): *no review found.*

**Q3 reduced-nk-cell-function → herpesvirus-reactivation.**
- General (13 screened; 13 no): *no review found.*
- Long COVID (0 hits): *no review found.*

**Q4 tryptophan-kynurenine-metabolism → neuroinflammation.**
- General (17 screened; 4 yes, 11 no, 2 animal or cell only; 2 accepted, one of them `inconsistent`): *mixed.* Reported in other conditions (systematic reviews, populations: affective and psychotic disorders; treatment-resistant depression and suicidality), with localized and inconsistent findings in one of them. Not studied in ME/CFS.
  - pmid:42014469, "Multimodal microglial and kynurenine pathway alterations across the affective-psychosis spectrum: a systematic review of patterns, heterogeneity, and dimensional implications." (2026). Population: major depressive disorder, bipolar disorder and schizophrenia. "KP findings were localized and regionally dissociated, including cingulate QUIN-related microglial signals and reduced hippocampal QUIN immunoreactivity in single cohorts." Relation inconsistent.
  - pmid:28412922, "Abnormalities in Kynurenine Pathway Metabolism in Treatment-Resistant Depression and Suicidality: A Systematic Review." (2017). Population: people with treatment-resistant depression and suicidality. "Several lines of evidence suggest that neuroinflammation is accompanied by a dysregulation of the kynurenine pathway (KP) in both TRD and suicidal individuals, resulting in an imbalance of neuroactive metabolites." Direction B → A (neuroinflammation acting on the pathway), the reverse of the map's proposed link. The reviewer notes the sentence is the abstract's framing; the abstract reports no results of its own.
- Long COVID (0 hits): *no review found.*

**Q5 autoimmunity-autoantibodies-b-cells → orthostatic-intolerance-cerebral-blood-flow.**
- General (7 screened; 1 yes, 6 no; 1 accepted): *reported in other conditions.* Reported in other conditions (systematic review, population: patients with POTS and neurogenic orthostatic hypotension). Not studied in ME/CFS.
  - pmid:28738696, "The role of autoantibodies in the syndromes of orthostatic intolerance: a systematic review." (2017): "Recent evidence has shown the presence of adrenergic and cholinergic receptor antibodies in patients with POTS and orthostatic hypotension." Association; no direction stated.
- Long COVID (0 hits): *no review found.*

### Positive control

**C1 autoimmunity-autoantibodies-b-cells → autonomic-imbalance.** General (17 screened; 4 yes, 13 no; 3 accepted, all `present`): *reported in other conditions.* Long COVID (0 hits): *no review found.* The control passes, so the other results are interpreted.
- pmid:29697012, "Heart rate variability in patients with systemic lupus erythematosus: a systematic review and methodological considerations." (2018). Population: patients with systemic lupus erythematosus; 11 studies. "Patients with systemic lupus erythematosus have abnormal heart rate variability, which reflects cardiac autonomic dysfunction and may be related to inflammatory cytokines but not necessarily to disease activity."
- pmid:29291895, "Evidence of reduced parasympathetic autonomic regulation in inflammatory joint disease: A meta-analyses study." (2018). Population: adults with rheumatoid arthritis or spondyloarthritis compared with healthy controls; meta-analysis, 35 studies. "Patients with IJD have cardiac parasympathetic AD which is related to inflammation." The reviewer notes the result rests on rheumatoid arthritis; the pooled differences for spondyloarthritis were not significant.
- pmid:25151910, "Autonomic function and rheumatoid arthritis: a systematic review." (2014). Population: patients with rheumatoid arthritis; 40 studies. "ANS dysfunction is prevalent in ~60% of RA patients."

### Base-rate pairs

B1 (6 screened) and B2 (29 screened): every row `no`, both long COVID arms 0 hits. Outcome *no review found* in all four arms.

Against the criterion (protocol point 7):
- (a) General arm with outcome *reported in other conditions* or *mixed*: 0 of 2 base-rate pairs, against 4 of 5 founder questions (Q1, Q2, Q4, Q5).
- (b) Accepted `yes` rows per pair: 0 for the base-rate pairs, against a mean of 1.8 per founder question (1, 5, 0, 2, 1).

The criterion is met: the arbitrary pairs drew hits from PubMed (B2 had 90) but no accepted statement on the relation. Two pairs, both with the circadian card at one end, are a very small sample; this is a weak check, not a measured false-positive rate.

### Reviewer agreement

The reviewer rejected **9 of 21 `yes` rows (43%)**, above the protocol's limit of about one in five. By the protocol's own rule, **abstract screening as done here is too unreliable to scale.** The rejections:

- Wrong field only (4): studies pooled not given where the record states it (pmid:32281951, C1, 20 publications; pmid:42359947, Q2, 21 studies; pmid:40332237, Q1, 197 articles, also direction should be A → B); meta-analysis flag false where PubMed lists Meta-Analysis (pmid:11296464, Q2). These four were on the relation; strict rejection removes them from the counts. Counting them as accepted would not change any outcome.
- Substance (5):
  - pmid:29673103 (Q1): the quote is the review's background premise, not its finding. Its finding concerns an intervention trial with a result that differed by population, and the record does not show the effect runs through oxidative stress.
  - pmid:34409762 (Q2): about a change in autonomic function after surgery; the only sentence linking it to orthostatic intolerance is speculative.
  - pmid:20552588 (Q2): the record only says the association "needs further investigation"; it reports no finding.
  - pmid:32244523 and pmid:32061259 (Q4): "inflammation" there means cytokines measured mostly in blood, not neuroinflammation as the card's themes define it.

The reviewer also flagged five accepted rows as weaker than the row suggests (noted with each source above): one record that calls itself not a systematic review, one single-centre chart review tagged Systematic Review, one review of mostly case reports, one result resting on one of its two conditions, and one framing sentence with no results.

### Limitations

- Abstract-only screening, by one agent, with a reject rate of 43% at review.
- Review quality is not graded; PubMed's publication type was taken as given, and two accepted records are not reviews of studies.
- The end terms are the cards' theme entries, not tuned to the question. Some pull in neighbouring topics (cytokine "inflammation" for neuroinflammation; surgery and spaceflight for autonomic imbalance).
- Publication bias: reviews that found nothing are less likely to be published.
- A relation shown in one condition need not hold in ME/CFS. In several accepted sources the autonomic change has a cause specific to that population (nerve damage after varicella-zoster infection, baroreflex failure after head and neck treatment, spaceflight).
- The long COVID arm returned almost nothing: 2 reviews over 8 questions, both screened `no`. The originals counts (0 to 29) show some primary studies exist; reviews without ME/CFS mention on these relations had not appeared by the run date.
- The positive control shares its A end with Q5, and both base-rate pairs share the circadian card.

### For the founder to judge

Whether the results for Q1, Q2, Q4 and Q5 are useful enough to show (protocol point 7). Ideally one researcher or Science for ME reader is asked the same.

## Pilot 2: protocol

Plan: `docs/plan-bridge-pilot-2.md`, agreed with the founder on 2026-11-17 (DECISIONS). Written and committed before any agent reads a record for pilot 2. Nothing below is changed after the first agent run; a deviation is recorded under "Pilot 2: results" as a deviation. Choices the plan leaves open are marked **(orchestrator default)**.

Pilot 2 asks one thing: does a tighter reading bring the reviewer's reject rate to one in five or lower, on the same eight questions and the same records as pilot 1? Only the reading changes. Pilot 1's files (`data/pipeline/2026-11-16-bridge-pilot/`) and its sections above are not changed.

### P2.1 Same questions, same records

- The eight questions of protocol point 1 and the queries in `config/bridge_pilot.yaml`, unchanged. No query tuning.
- **The screened records are pilot 1's** **(orchestrator default)**: `bridge run` takes the screened PMIDs and the counts of every question and arm from pilot 1's `counts.json` instead of searching PubMed again, after checking that each arm's query there is the query in `config/bridge_pilot.yaml` character for character. Why: a new search a day later can return records that did not exist on 2026-11-16, and then more than the reading would change. `counts.json` holds the searches and the screened ids only, no rows or verdicts.
- Records are read from `data/cache/bridge/pubmed/`; a record missing there is fetched again from PubMed and the report says which.
- Run folder: `data/pipeline/2026-11-17-bridge-pilot-2/` (context files, survey files, review file; generated, not committed).

### P2.2 Code fills what the record states

- `meta_analysis` is not written by the agent. The context file states, per record, whether PubMed lists `Meta-Analysis` among its publication types, and the report takes the flag from there.
- `studies_pooled` is dropped from the extraction.

### P2.3 The quote must be a finding

- A record's abstract is **structured** when at least one of its `AbstractText` sections has a non-empty `Label`; otherwise it is **unstructured**.
- In a structured abstract, a section is a **finding section** when its `NlmCategory` is `RESULTS` or `CONCLUSIONS`, or when its `Label`, compared without regard to case and with whitespace collapsed, is one of: `RESULTS`, `MAIN RESULTS`, `METHODS AND RESULTS`, `CONCLUSION`, `CONCLUSIONS`, `AUTHORS' CONCLUSIONS`, `REVIEWER'S CONCLUSIONS`, `DISCUSSION AND CONCLUSION`, `INTERPRETATION`. Every other section (background, objective, methods, limitations, discussion alone, and unlabelled sections without one of those categories) is not. The list covers every label in the 123 cached records that is a result or a conclusion; it was drawn up by reading the labels only, not the texts.
- For a structured abstract, code accepts the quote of a `yes` row only when it is found verbatim (whitespace collapsed, nothing else) inside the text of one finding section. A quote from the title, from another section, or across two sections is rejected.
- For an unstructured abstract, the quote may come from the title or the abstract, as in pilot 1.
- Every `yes` row carries `quote_role`: `finding` (the sentence reports what the review found or concludes), `background` (what was known or assumed before) or `aim` (what the review set out to do). Code rejects a `yes` row whose `quote_role` is not `finding`. For an unstructured abstract the reviewer checks that the sentence is a finding.
- The context file shows each section of a structured abstract with its label and marks the finding sections.

### P2.4 Is it a review of studies?

Every `yes` row carries `review_kind`, read from what the title and abstract say about the record itself, not from PubMed's publication type alone:

- `systematic`: the record describes a literature search (databases searched, search dates or a protocol) or states a number of included studies, or reports a meta-analysis;
- `narrative`: a review of the literature that describes neither;
- `not_a_review`: not a review of studies (for example a single cohort, a chart review, a case report, a guideline or a trial).

Only accepted `yes` rows with `review_kind: systematic` count towards an outcome (founder ruling 2026-11-17). Accepted `yes` rows with `narrative` or `not_a_review` are listed apart as **leads**, with no outcome drawn from them.

### P2.5 Each end has a written definition

The surveyor and the reviewer both get these, in the context file header. They are taken from each card's core claim (`core_claim` in `cards/<slug>.yaml`) and kept in `config/bridge_ends.yaml`, committed with this protocol.

| Card | What counts |
|---|---|
| oxidative-nitrosative-stress | Reactive oxygen or nitrogen species outweighing the body's antioxidant defences, measured as markers of oxidative or nitrosative stress or of the damage they do to fats, proteins, DNA or other molecules. The clinical effect of an antioxidant given as treatment, with no measure of oxidative stress, does not count. |
| endothelial-dysfunction | Impaired function of the endothelium, the lining of the blood vessels: for example vessels widening less well when the tissues need more blood flow, or markers of endothelial damage or activation. Changes in blood clotting or in the microcirculation count only when the record ties them to the endothelium. |
| autonomic-imbalance | A shift in the balance of the autonomic nervous system towards less parasympathetic (vagal) and relatively more sympathetic activity, measured for example as lower heart rate variability, a higher resting heart rate or a weaker baroreflex. It is the balance itself, not the fall in blood flow to the brain or the drop in blood pressure on standing. |
| orthostatic-intolerance-cerebral-blood-flow | Blood flow to the brain falling more than normal on sitting up, standing or being tilted upright, or orthostatic intolerance such as postural orthostatic tachycardia syndrome (POTS) or orthostatic hypotension. |
| reduced-nk-cell-function | Natural killer (NK) cells less able to kill target cells (lower NK cell cytotoxicity or activity). NK cell numbers alone, with no measure of their function, do not count. |
| herpesvirus-reactivation | A herpesvirus that stays in the body after a first infection (such as Epstein-Barr virus, cytomegalovirus or human herpesvirus 6 or 7) becoming active again, as the record shows it (for example viral DNA in blood or antibody patterns of reactivation). A first infection does not count. |
| tryptophan-kynurenine-metabolism | Altered breakdown of the amino acid tryptophan, mostly along the kynurenine pathway: the levels of tryptophan, kynurenine or its products (such as kynurenic acid or quinolinic acid), or the activity of the pathway's enzymes (such as indoleamine 2,3-dioxygenase). |
| neuroinflammation | Inflammation in the brain or spinal cord, including activation of microglia or astrocytes, measured in the central nervous system (brain imaging, brain tissue or cerebrospinal fluid). Cytokines or other inflammation markers measured in blood do not count. |
| autoimmunity-autoantibodies-b-cells | The immune system attacking the body's own tissues: autoantibodies (for example against adrenergic or muscarinic receptors), the B cells that make them, or a disease the record names as autoimmune. |
| circadian-rhythm-disruption | The body's 24-hour timing system disturbed: daily rhythms of rest and activity, body temperature, melatonin or light exposure weaker, less regular or out of step. Sleep quality itself does not count, nor the daily rhythm of cortisol. |

The autoimmunity definition includes diseases the record names as autoimmune, which is wider than the card's focus on receptor autoantibodies; it follows the card's own theme terms (`Autoimmune Diseases` in `config/card_themes.yaml`), which drew the records **(orchestrator default)**.

### P2.6 The extraction and the reviewer's verdict

The surveyor writes, per screened PMID, `statement` (`yes`, `no`, `animal_or_cell_only`) as in pilot 1, judged against the end definitions. A `yes` row carries `relation`, `population`, `direction` (value lists as in protocol point 5), `review_kind`, `quote_role` and `quote`; `meta_analysis` and `studies_pooled` are no longer written. Code (`survey bridge validate`) rejects the file on the pilot 1 rules (PMIDs, verbatim quote, value lists) and on points P2.2 to P2.4.

A fresh `card-reviewer` checks every `yes` row, whatever its `review_kind`, against the cached record and the end definitions, and gives `accept` or `reject`. A rejection carries one reason code, the first that applies in this order:

| Code | Meaning |
|---|---|
| `not_humans` | the statement rests on animal or cell studies |
| `wrong_review_kind` | `review_kind` is wrong for what the record says about itself |
| `not_this_relation` | the record is not about A and B as the end definitions mean them |
| `not_a_finding` | the quote is background, aim or speculation, or the record reports no finding on the relation |
| `wrong_direction` | `direction` or `relation` does not match the record |
| `wrong_population` | `population` does not match the record |
| `other` | anything else, explained in a note |

**(orchestrator default: the order, and that `relation` errors go under `wrong_direction`.)** The reviewer writes `data/pipeline/2026-11-17-bridge-pilot-2/review.json`: `{"rows": [{"question", "arm", "pmid", "verdict", "reason", "note"}]}`, `reason` null for `accept`. Neither the surveyor nor the reviewer is given pilot 1's rows, verdicts or report: the reviewer is told not to read this file or pilot 1's run folder, and the context files hold no pilot 1 result.

One agent at a time: a fresh `bridge-surveyor` per context file with records, then one fresh `card-reviewer` over all `yes` rows.

### P2.7 Outcome per question and arm

The rule of protocol point 6, applied to accepted `yes` rows with `review_kind: systematic` only: *reported in other conditions*, *mixed*, *only animal or cell evidence* (no accepted systematic `yes` row and at least one `animal_or_cell_only` row) or *no review found*. Leads are listed under the arm with no outcome. The fixed framing is unchanged: "Reported in other conditions (systematic review, population: …). Not studied in ME/CFS." No treatment in another condition is named as an option for ME/CFS.

### P2.8 How pilot 2 is judged

- **Reviewer agreement (the test this pilot exists for):** rejected `yes` rows divided by all `yes` rows, over all questions and arms, is at most 1 in 5 (20%). The number is reported with its reason codes whatever it is, and this test is not redefined after the run.
- **Positive control:** C1 gives at least one accepted `systematic` `yes` row with `relation: present`, in either arm. If not, the other results are not interpreted.
- **Base rate:** criterion (a) and (b) of protocol point 7, counted on accepted `systematic` `yes` rows.
- **Nothing lost silently:** each of the 12 rows pilot 1's reviewer accepted is reported as kept (accepted, `systematic`), moved to leads (accepted, `narrative` or `not_a_review`) or dropped, with the reason (the surveyor's `statement`, or the reviewer's reason code). Accepted `systematic` rows that pilot 1 did not accept are listed as new. This comparison is made by the orchestrator after the review, from the two run folders.

## Pilot 2: results

Run on 2026-11-17, after the pilot 2 protocol commit (`8d641a4`) and the code commit (`5905528`), with `uv run python -m me_atlas.survey bridge run --screened-from data/pipeline/2026-11-16-bridge-pilot/counts.json --ends config/bridge_ends.yaml --out data/pipeline/2026-11-17-bridge-pilot-2`. No search was made; every arm's query matched `config/bridge_pilot.yaml`; all 123 screened records were in the cache and none was fetched again. The counts are pilot 1's (table "Counts" above). A fresh `bridge-surveyor` read each of the 10 context files with records (127 rows); every file passed `survey bridge validate`. One fresh `card-reviewer` checked the 8 `yes` rows: 5 accepted, 3 rejected.

**Deviation.** The reviewer was pointed at the cached XML records but judged from the context files, which hold the same titles and abstracts rendered from those records, section by section. It did not read pilot 1's files.

Every source below is a record fetched from PubMed and cached under `data/cache/bridge/pubmed/`; titles are as PubMed gives them and every quote is copied from the record's abstract. **Review quality is not graded.** Nothing here is a finding about ME/CFS, and no intervention studied in another condition is an option for ME/CFS.

### Reviewer agreement

The reviewer rejected **3 of 8 `yes` rows (37.5%)**. The limit was one in five (20%). **The reject-rate test was not met.** All three rejections have the reason code `not_a_finding`; no row was rejected for a wrong field, wrong review kind, wrong population, wrong direction or for not being about humans.

- pmid:42359947 (Q2, amyotrophic lateral sclerosis): the quote lists reduced heart rate variability and absent blood pressure regulation on orthostatic stress side by side as features of the disease; the record reports no relation between the two.
- pmid:37531984 (Q2, astronauts): heart rate variability changes and orthostatic intolerance are reported as parallel effects of spaceflight, not as a relation between them, and "altered" gives no direction towards less vagal activity.
- pmid:42014469 (Q4, affective and psychotic disorders): the quote reports kynurenine pathway changes in single cohorts; the record proposes the link to brain inflammation as a framework and reports no finding on it.

The surveyor wrote far fewer `yes` rows than in pilot 1 (8 against 21 on the same 127 records), so the rate rests on a small number: one rejection more or less moves it by 12.5 points. The reviewer checks `yes` rows only, so a `yes` wrongly written as `no` is not measured by this test (see "Limitations").

### Outcome per question and arm

Outcomes are drawn from accepted `yes` rows with `review_kind: systematic` only (P2.7). Leads are accepted rows with another review kind, listed with no outcome. Every long COVID arm and every arm not named below had no `yes` row and the outcome *no review found* (Q1 and Q2 long COVID: 1 record each, `no`; the other long COVID arms: 0 hits).

**Q1 oxidative-nitrosative-stress → endothelial-dysfunction.** General (10 screened; 9 no, 1 animal or cell only): *only animal or cell evidence.* The one such row, pmid:28215178, "Oxidative Stress and Cardiovascular Aging: Interaction Between NRF-2 and ADMA." (2017), was noted by the surveyor as resting mostly on animal studies; `animal_or_cell_only` rows are not reviewed.

**Q2 autonomic-imbalance → orthostatic-intolerance-cerebral-blood-flow.** General (26 screened; 5 yes, 21 no; 2 accepted systematic, 1 lead): *reported in other conditions.* Reported in other conditions (systematic reviews, populations below). Not studied in ME/CFS.
- pmid:31888497, "Heart rate and heart rate variability comparison between postural orthostatic tachycardia syndrome versus healthy participants; a systematic review and meta-analysis." (2019). Population: people with POTS compared with healthy participants; meta-analysis (PubMed publication type). "POTS patients have a higher HR than healthy patients after HUTT and lower HRV in terms of time domain measure but not in terms of frequency domain measure." Association. The reviewer notes that only the time-domain differences were significant, and that heart rate after tilt partly overlaps with how POTS is defined.
- pmid:39538129, "Postural orthostatic tachycardia syndrome after COVID-19 vaccination: A systematic review." (2024). Population: people with POTS after COVID-19 vaccination; not a meta-analysis. "Diagnostic findings across studies included elevated norepinephrine levels and reduced heart rate variability." Association. The reviewer notes that the included studies are mostly case reports and case series, with no comparison group for heart rate variability.
- Lead (`not_a_review`): pmid:33947784, "Natural History of Afferent Baroreflex Failure in Adults." (2021). A single-centre chart review of adults with afferent baroreflex failure that PubMed tags Systematic Review. "The most common findings were hypertension (87.5%), fluctuating blood pressure (78.8%), orthostatic hypotension (91.3%), syncope (58.6%), headache (22.1%), and tachycardia (20.2%)." No comparison group.

**Q3 reduced-nk-cell-function → herpesvirus-reactivation.** General (13 screened; 13 no): *no review found.*

**Q4 tryptophan-kynurenine-metabolism → neuroinflammation.** General (17 screened; 1 yes, 15 no, 1 animal or cell only; the `yes` row rejected): *only animal or cell evidence.* The animal or cell row, pmid:40289452, "Edible and Medicinal Fungi as Candidate Natural Antidepressants: Mechanisms and Nutritional Implications." (2025), was noted by the surveyor as resting on preclinical studies.

**Q5 autoimmunity-autoantibodies-b-cells → orthostatic-intolerance-cerebral-blood-flow.** General (7 screened; 1 yes, 6 no; 0 accepted systematic, 1 lead): *no review found.*
- Lead (`narrative`): pmid:28738696, "The role of autoantibodies in the syndromes of orthostatic intolerance: a systematic review." (2017). Population: patients with POTS and orthostatic hypotension. "Recent evidence has shown the presence of adrenergic and cholinergic receptor antibodies in patients with POTS and orthostatic hypotension." The title says systematic review, but the abstract describes no search and gives no number of included studies, so under P2.4 it is narrative; the reviewer notes the sentence could be read as background.

### Positive control

**C1 autoimmunity-autoantibodies-b-cells → autonomic-imbalance.** General (17 screened; 1 yes, 16 no; 1 accepted systematic): *reported in other conditions.* The control passes, so the other results are interpreted.
- pmid:32281951, "Electrocardiogram and heart rate variability assessment in patients with common autoimmune diseases: a methodological review." (2020). Population: patients with rheumatoid arthritis, systemic lupus erythematosus, Behcet's disease and systemic sclerosis; not a meta-analysis. "Time-frequency domain analysis revealed that HRV parameters were lower in patients with the selected ADs in comparison with control groups." Association. The reviewer notes that the A end is met through diseases the record names as autoimmune, not through autoantibody levels.

### Base-rate pairs

B1 (6 screened) and B2 (29 screened): every row `no`. Outcome *no review found* in all four arms. Against the criterion (protocol point 7, on accepted systematic rows):
- (a) General arm *reported in other conditions* or *mixed*: 0 of 2 base-rate pairs, against 1 of 5 founder questions (Q2).
- (b) Accepted systematic `yes` rows per pair: 0 for the base-rate pairs, against a mean of 0.4 per founder question (0, 2, 0, 0, 0).

The criterion is met, but with so few accepted rows on either side it says little.

### Comparison with pilot 1

Each of the 12 rows pilot 1's reviewer accepted:

| Pilot 1 row | Pilot 2 | Reason |
|---|---|---|
| Q1 pmid:17713412 | dropped | surveyor `no`: a rationale for antioxidant treatment, not a reported finding on the relation |
| Q2 pmid:31888497 | kept | accepted, systematic |
| Q2 pmid:39538129 | kept | accepted, systematic |
| Q2 pmid:37531984 | dropped | reviewer: `not_a_finding` |
| Q2 pmid:35863181 | dropped | surveyor `no` (no note) |
| Q2 pmid:33947784 | moved to leads | accepted, `not_a_review` |
| Q4 pmid:42014469 | dropped | reviewer: `not_a_finding` |
| Q4 pmid:28412922 | dropped | surveyor `no` (no note) |
| Q5 pmid:28738696 | moved to leads | accepted, `narrative` |
| C1 pmid:29697012 | dropped | surveyor `no`: lupus is not named as autoimmune in the abstract |
| C1 pmid:29291895 | dropped | surveyor `no`: inflammatory joint disease is not named as autoimmune in the abstract |
| C1 pmid:25151910 | dropped | surveyor `no`: rheumatoid arthritis is not named as autoimmune in the abstract |

New: one accepted systematic row that pilot 1 did not accept, C1 pmid:32281951 (pilot 1 had it as `yes` but rejected it for a missing studies count). Of pilot 1's three other wrong-field rejections, pmid:42359947 (Q2) was written `yes` again and rejected as `not_a_finding`; pmid:40332237 (Q1, noted as stating the link only as background) and pmid:11296464 (Q2) were written `no`.

As a result, outcomes changed: Q1 and Q4 went from *reported in other conditions* and *mixed* to *only animal or cell evidence*; Q2 from *mixed* to *reported in other conditions*; Q5 from *reported in other conditions* to *no review found* with one lead.

### Limitations

- **The reject rate measures precision only.** The reviewer sees `yes` rows, not `no` rows. The surveyor wrote 13 fewer `yes` rows than in pilot 1, and some `no` rows are doubtful: the three C1 rows above were dropped because the abstract does not use the word "autoimmune" for lupus, inflammatory joint disease or rheumatoid arthritis, a literal reading of the end definition ("a disease the record names as autoimmune"). How many relevant records are lost this way is not measured.
- Small numbers: 8 `yes` rows, 5 accepted, over eight questions.
- One surveyor and one reviewer, both AI, abstract only.
- The quote rule follows PubMed's section labels. Some abstracts put results under a METHODS label (for example pmid:41927192 in Q5), so a finding there cannot be quoted.
- Review quality is not graded; `review_kind` is read from the abstract, so a systematic review whose abstract does not describe its search counts as narrative.
- The limitations of pilot 1 (end terms not tuned, publication bias, population-specific causes, almost no long COVID reviews, shared ends in the control and base-rate pairs) apply unchanged.

### For the founder to judge

The reject-rate test was not met in either pilot (43% and 37.5%). The remaining rejections are all of one kind: two things reported side by side in one condition, read as a relation between them. Whether to try a third reading, read full texts (direction B), or stop the bridge search at this scale is the founder's ruling; nothing here changes a card, a link or a link's step.
