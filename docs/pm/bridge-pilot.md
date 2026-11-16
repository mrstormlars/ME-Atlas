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
cards = sorted((cardlib.load_card(p) for p in Path("cards").glob("*.yaml") if p.name != "changelog.yaml"), key=lambda c: c.slug)
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

Not yet run.
