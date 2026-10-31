# ME Atlas – Version 1 Plan

*Mapping the evidence on ME/CFS and long COVID*

October 31, 2026 · Draft v1

## Purpose

ME Atlas gives patients, carers and researchers one continuously updated, evidence-graded overview of every serious hypothesis about what causes ME/CFS and long COVID.

Today that knowledge is scattered across thousands of papers, forums and wikis. Patients and carers have little energy to follow it, and it is hard for anyone to see which hypotheses are actually gaining ground. ME Atlas uses AI to do most of the collecting and sorting, and human reviewers to make the judgement calls.

The goal is not to give treatment advice. The goal is to make the state of the evidence visible, honest and easy to follow.

## Existing landscape

The building blocks exist, but no one combines them into a structured, evidence-graded hypothesis overview. That combination is the gap ME Atlas fills.

| Resource | What it does | What it lacks |
| --- | --- | --- |
| [MEpedia](https://me-pedia.org/wiki/Category:Medical_hypotheses) (#MEAction) | Crowd-sourced wiki, about 56 hypothesis pages | No evidence grading or ranking |
| [Science for ME](https://www.s4me.info/) | Patient-scientist forum with critical evidence review | Forum format, hard to get an overview |
| [EPPI long COVID living map](https://eppi.ioe.ac.uk/cms/Default.aspx?tabid=3930) (UCL) | Automated bibliography of about 6,700 papers, sorted by topic | No hypothesis view; last update found was January 2025 |
| [mapMECFS / searchMECFS](https://www.ninds.nih.gov/news-events/directors-messages/all-directors-messages/new-resources-large-scale-mecfs-research) (NIH) | Research data and biospecimen sharing | Built for researchers, not patients |
| Generic AI literature tools | Knowledge graphs and summaries over PubMed | Not ME-specific, no curated grading |

Recent anchor: [DecodeME](https://institute-genetics-cancer.ed.ac.uk/decodeme-the-worlds-largest-mecfs-study/initial-decodeme-dna-results) (2025) linked ME/CFS to genes in the immune and nervous systems, giving the field concrete targets.

We aim to partner with MEpedia and Science for ME rather than compete with them.

## Scope of version 1

Version 1 covers 15 to 20 hypotheses about ME/CFS and long COVID, each with one evidence card, updated weekly.

Candidate hypotheses to start with:

- Immune dysregulation and autoimmunity
- Mitochondrial and energy metabolism dysfunction
- Endothelial dysfunction and reduced blood flow
- Neuroinflammation and glial dysfunction
- Viral persistence or reactivation (EBV, SARS-CoV-2)
- Genetic findings from DecodeME

We frame the content as competing and possibly overlapping hypotheses, not a race to one root cause. ME is likely heterogeneous, so each card also notes which patient subgroups a hypothesis may apply to.

## Evidence card and grading

Every hypothesis gets one evidence card with the same fields and a transparent status level. The grading rubric is public so anyone can check it.

| Field | Content |
| --- | --- |
| Core claim | The hypothesis in one or two plain sentences |
| Key supporting studies | Link, sample size, case definition, year |
| Contradicting studies | Failed replications and negative findings |
| Replication status | Independent replications, yes or no, and by whom |
| Subgroups | Which patients the hypothesis may apply to |
| Who is working on it | Research groups and funders, with links |
| Early signals | Promising but unreplicated findings, clearly labelled |
| Status level | See the draft scale below |
| Last reviewed | Date and reviewer |

Draft status scale (to be refined with expert input):

| Level | Meaning |
| --- | --- |
| 0 | Proposed: theoretical, no direct data yet |
| 1 | Early signal: one or more small or uncontrolled studies |
| 2 | Supported: controlled study with strict case definition |
| 3 | Replicated: independently reproduced by another group |
| 4 | Mechanism shown: causal link demonstrated, e.g. by intervention |
| 5 | Confirmed: treatment based on it works in a robust trial |

Quality factors that move a finding up or down: case definition used, sample size, proper controls, preregistration and conflicting results.

## AI pipeline

A weekly Python job finds new papers and lets AI do the sorting and first draft; a human approves every change before it goes live.

```mermaid
flowchart LR
    A["Fetch new papers<br/>(PubMed, Europe PMC)"] --> B["Sort by hypothesis<br/>(AI classifies)"]
    B --> C["Extract study data<br/>(n, case definition)"]
    C --> D["Draft card update<br/>(AI writes draft)"]
    D --> E["Human review<br/>(editorial team)"]
    E --> F{Approved?}
    F -- yes --> G["Publish to site<br/>(weekly update)"]
    F -- "no, revise" --> C
```

AI handles search, classification, data extraction and drafting. Grading and publishing stay with the editorial team, and every claim links to its source.

## Frontend

Version 1 is a simple static website generated from the evidence card data. No user accounts, no database server.

- An overview page listing all hypotheses, sortable by status level
- One page per hypothesis showing its evidence card
- A "What changed this week" page
- A public page explaining the grading rubric and methods

The site must be calm and easy to read for people with limited energy: short text, no clutter, good contrast.

## Principles and governance

Credibility is the product, so these rules come before features.

- **Every claim links to its source.** No unsourced statements.
- **AI drafts, humans decide.** No evidence grade is published without human approval.
- **No treatment advice.** Early signals are labelled as such and never presented as recommendations.
- **No money handling in version 1.** We link to existing research funders instead of collecting donations.
- **Open methods.** The grading rubric and change log are public.

Start with a small editorial team of two to three people: the founder, someone with a medical or research background, and ideally a patient with experience from Science for ME or MEpedia.

## KPIs

Version 1 measures the quality and use of the platform, not global suffering.

| KPI | What it shows |
| --- | --- |
| Hypotheses with at least one independent replication | How far the field has come |
| Days from publication to reviewed entry | How current the overview is |
| Share of claims sourced and human-approved | How trustworthy the content is |
| Links from researchers, patient organisations and clinicians | Whether the overview is used and trusted |

For disease burden, use established measures (DALY and YLD) rather than a new scale, so ME can be compared with other diseases.

## Long-term vision (out of scope for version 1)

If the ME model works, the same structure can be reused for other diseases, and eventually for a wider map of suffering.

- **Level 2 – all diseases (endalldisease):** one sub-project per disease (e.g. "Long COVID Atlas"), built on the same evidence card and pipeline.
- **Level 3 – all suffering (endallsuffering):** a root-cause map of suffering for humans and other sentient beings, building on existing work such as global burden of disease and cross-species welfare research.
- **Funding overview:** show who funds each research direction, possibly with donation links, once legal and governance questions are settled.

Version 1 is built so it can be generalised later, but we do not build for these levels now.

## Next steps

- [ ] Decide whether to register me-atlas.org (free as of October 2026; meatlas.com is taken)
- [ ] Define the evidence card data model (JSON or YAML)
- [ ] Write 2–3 evidence cards by hand to test the format
- [ ] Build a first PubMed / Europe PMC fetch script in Python
- [ ] Add AI classification and extraction of key study data
- [ ] Generate a simple static site from the cards
- [ ] Show the prototype to Science for ME, MEpedia and a patient organisation for feedback

## Open questions

- Who can be the medical or research reviewer?
- Should the content live inside MEpedia, beside it, or stand alone?
- Should version 1 cover ME/CFS and long COVID together, or ME/CFS first?
- How should "early signals" be shown without becoming treatment hype?
