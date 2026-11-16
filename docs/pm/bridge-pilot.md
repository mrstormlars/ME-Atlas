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
