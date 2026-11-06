# Decisions

Append-only, newest first. One entry per ruling: date, decision, why.

## 2026-11-06 — Causal map: second pass with review full texts

- Six new step-1 (proposed) links accepted by the founder after `link-drafter` on all 16 cards with the three cached review full texts as plain text with numbered paragraphs, and two `card-reviewer` rounds (run files in `data/pipeline/2026-11-06-map-pass2/`, list in `decisions.md` there): gut microbiome to neuroinflammation and to oxidative and nitrosative stress; small fibre neuropathy to the orthostatic intolerance symptom (observations in POTS, said in the text); HPA axis and cortisol to sleep disturbance, to neurocognitive impairment and to the open question "What keeps the illness going". Why: the first pass could not read the full texts; these links are stated in them.
- The reviews cited are added as `context` studies, per the earlier ruling: pmid:31330791 on gut microbiome and HPA axis, pmid:41516296 on HPA axis, pmid:37054777 on small fibre neuropathy. No level changes.
- Rejected on review: links to impaired energy production after exertion from endothelial dysfunction and from oxidative stress (the reviews speak of oxygen delivery or cellular mitochondria, not the card's two-day exercise test finding), and HPA axis to gut microbiome (the review has the gut upstream). Layer notes from the reviews are kept in the run files only, except the HPA axis note, which goes with its link to the open question.
- Plan for the drawn map written: `docs/plan-drawn-map.md` (defaults for the founder to confirm at the bottom).

## 2026-11-06 — Causal map: first mapping

- All 16 cards placed (founder ruling on the agents' proposals after two rounds of `link-drafter` and `card-reviewer`, run files in `data/pipeline/2026-11-06-map/`): 11 measurable dysfunction, 4 perpetuating mechanism (autoimmunity, gut microbiome, herpesvirus reactivation, persistent enterovirus), 1 predisposition (inherited genetic risk), none in trigger. 17 links accepted: 6 at step 2 (associated), 11 at step 1 (proposed), none at step 3. A card's other possible reading is kept as a comment above `layer:` in the draft.
- A study whose case definition is unverified may be the source of a step-1 (proposed) link, never of step 2 or 3; same for reviews. Why: like a review, it can state a hypothesis but cannot carry patient evidence under the ladder's rules.
- A review cited by a link is added to the card as a `context` study (`design: other`, `case_definition: none`) so the citation check covers it; it never counts towards the level. Three reviews added this way (pmid:32247028, 41516296, 37054777).
- Symptom nodes are the 14 symptom categories of the ICC 2011 (pmid:21777306, full text cached). IOM 2015 and CCC 2003 are not yet cached as verifiable records (the IOM JAMA summary pmid:25668027 has no abstract; CCC is not in PubMed), so they are not cited; nothing is cited from memory. Open questions: four editorial questions, one per layer except symptom.

## 2026-11-06 — Causal map: rubric, layer and links

- The link rubric is published: five layers (predisposition, trigger, perpetuating mechanism, measurable dysfunction, symptom) and three link steps (proposed, associated, direction supported), in the functional spec section 3, "Causal map and links". A link grades "A drives B in ME/CFS patients" on its own scale; it never raises a card's level; every link has a source at every step. Why: the sixteen hypotheses sit at different depths of one possible chain, and a place on the chain is information the bar chart cannot give; the scale had to be published before it is used.
- Setting a card's `layer` and adding or changing a link are founder decisions, like levels, badges and contested marks (CLAUDE.md rule 2). Agents draft (`link-drafter`), `card-reviewer` checks (map mode), the founder rules.
- Refinements for the first implementation (D1-D4): (D1) `layer` is optional until the cards are placed; a card without one is listed as "Not yet placed"; (D2) symptom names and open-question texts are translated in per-language content files like the glossary, link texts through the card sidecars; (D3) the two English content files are optional, absent means no symptom and question nodes; (D4) `links[].to` is a card slug, `symptom:<id>` or `question:<id>`.
- Convergence is counted, not judged: "candidate common mechanisms" and "candidate roots" are lists with counts. The map page is lists only; the drawn map is a later plan. Plan: `docs/plan-causal-map.md`; reference: `docs/map.md`.

## 2026-11-03 — Private preview on Azure

- The draft build is hosted as an Azure Storage static website in the founder's StormSolutions subscription (`rg-me-atlas`, Norway East, account `meatlaslpr4z`), shared by link with a few readers who should not need an account. Why: a Claude artifact needs a claude.ai account, which is too much for a patient with little energy.
- Published unchanged: the draft banner, the translation notice and `noindex` already on every page are enough warning (founder). It is not the public launch; the cards stay drafts, and the domain and public hosting are still open. Updated by hand after merges; commands in `docs/site.md`.

## 2026-11-02 — Norwegian terms

- Norwegian uses "diagnosekriterier" for "case definition" (not "kasusdefinisjon"). Why: patients and carers know the word.
- "PEM" is used as the term in every language, explained in the glossary; no long Norwegian paraphrase in running text. Why: PEM is the established term among patients.

## 2026-11-02 — Norwegian version of the site

- The whole site is also published in Norwegian (bokmål) with a language selector; the structure allows further languages (a string file per language). English stays authoritative: every Norwegian page says it is a translation of the English page and links to it. Why: many readers are patients with little energy who read best in their own language; credibility still comes first, so a translation is checked and never replaces the source.
- Fixed template text comes from `content/i18n/<lang>.yaml` (same keys; a missing key fails the build and names it). The glossary has a file per language (`content/glossary.nb.yaml`, keyed by the English term); the methods page has a text per language; card text is translated in sidecar files `translations/nb/<slug>.yaml` that hold only the translatable text, each item with the SHA-256 of the English text it was translated from and the same `sources`. Levels, badges, the contested mark, roles, numbers, ids, study titles, case-definition quotes and group names always come from the English card and are never in a translation file.
- A mechanical check (`uv run python -m me_atlas.translations check`) compares each item with the English: same sources list, same numbers in the same order and count (decimal comma accepted), same PMIDs, no item the English card lacks. A translation whose hash no longer matches is stale. A stale, missing or failing item shows the English text with the note "Denne delen er ikke oversatt ennå"; stale Norwegian is never shown. Norwegian banned words (lovende, gjennombrudd, kur, håp, bevist) are checked next to the English ones.
- AI: a `card-translator` agent (sonnet) translates; `card-reviewer` gets a translation mode (opus, compares meaning, numbers and neutrality with the English). The weekly pipeline lists the items accepted changes made stale (`pipeline translation-plan`) and `/ukentlig` runs translator and reviewer on them; the weekly pull request carries both languages; an item that fails the check or the review is left out and stays English. A card's first translation is a manual run (all 16 cards, the glossary and the methods page), read by the founder before merge, then spot checks. Translations carry no level, badge or contested mark, so they are not a tier decision.
- The choice of language sticks (founder, 2026-11-02): choosing a language stores it in `localStorage` (`me-atlas-lang`); a page in another language than the stored one goes to the same page in the stored language with `location.replace`, so Back is not trapped. Every storage access is in try/catch; with nothing stored, no storage or no JavaScript the page shows its own language. No browser-language detection, no cookies.
- Rule change: CLAUDE.md "Language" and functional spec section 5 ("English, plain words") now say that site content is written in English, which is authoritative, and that reviewed translations are published alongside it. Code and repository documents stay in English. Details: `docs/translation.md`, plan `docs/plan-norwegian-translation.md`.

## 2026-11-02 — Cards fourteen to sixteen

- Three new hypotheses added as draft cards, each checked by `card-reviewer` and fixed: mast cell activation (level 2, not contested, long COVID label kept), persistent enterovirus infection (level 0), small fibre neuropathy (level 1). Both badges no on all three.
- Studies whose case definition is not stated or not yet checked count at no rung, including rung 1 (spec section 3: "Not accepted"). A card can therefore stand at level 0 while citing patient data; the card says so.
- "Previously diagnosed or meeting the X criteria" does not verify a case definition when the prior-diagnosis route names none; such studies are recorded `unverified`.
- A null result at rung 1 is not a contested mark.
- The long COVID label needs a study whose cohort met an ME/CFS definition; a cohort chosen by long COVID plus another condition, with a comorbid ME/CFS diagnosis in some and results not split, does not carry it.

## 2026-11-02 — Cards ten to thirteen

- Four new hypotheses added as draft cards, each checked by `card-reviewer` and fixed: oxidative and nitrosative stress (level 2, not contested), tryptophan and kynurenine metabolism (level 3, contested at rung 3), brain and brainstem MRI changes (level 2, not contested), inherited genetic risk (level 2, not contested). Both badges no on all four.
- Tryptophan: a ratio measured in serum and in plasma counts as the same result; a null read from a figure's significance marks may contradict when the card says so and names the figure.
- Brain MRI: an opposite-direction result in a subgroup, in partly overlapping regions, with a different method, does not contradict the rung; a later whole-brain study that reports no result for the region either way is a non-repeat, not a contradiction.
- Genetics: a genetic association can carry rung 2 as an association; going beyond association needs level 4.

## 2026-11-02 — Cards six to nine

- Four new hypotheses added as draft cards, each checked by `card-reviewer` and fixed: orthostatic intolerance and cerebral blood flow (level 2, not contested), herpesvirus reactivation (level 2, not contested), HPA axis and cortisol (level 2, contested at rung 2), endothelial dysfunction (level 3, not contested). Both badges no on all four.
- HPA axis: the London CRH study (pmid:11502777, 37 patients) contradicts the Dublin rung-2 finding (pmid:9669518) at comparable quality; no independent study repeats the same result, so no level 3.
- Herpesvirus: the London saliva study (pmid:34422848) measures DNA load in saliva and is read by its authors as persistent infection, so it does not repeat the Riga finding; rung 2 rests on the herpesvirus-only result of pmid:36653846.
- Endothelium: renamed "Endothelial dysfunction"; clotting studies stay as context because none has a verified case definition. pmid:29426834 recorded as Fukuda (the definition it applied), not ICC (its label).
- "1994 case definition" counts as Fukuda when the reference or the CDC authorship makes it clear. A case definition named only by reference number counts when the reference list resolves it. A passive tilt test is not a direct PEM measure.

## 2026-11-01 — Weekly pipeline: AI as Claude Code subagents

- AI steps (classify, draft, review) run as Claude Code subagents on the founder's subscription, started by `/ukentlig`. Model choice lives in each agent's frontmatter in `.claude/agents/` (`paper-classifier`: haiku, `card-drafter`: sonnet, `card-reviewer`: opus), prompts are files in the repo. No direct API calls, no API key, while the project runs on the subscription. This replaces the CLAUDE.md rule "LLM calls go through one module with model ids and token budgets in config"; every AI output still keeps its source ids. Why: the founder runs the pipeline in a session he already pays for; the review step stays on a different model from the drafter (spec section 6, step 4).
- The drafter writes operations (`add_study`, `add_paragraph`, `replace_paragraph`, `propose`), not whole cards. Code validates and applies them as text splices, so lines the drafter did not name stay byte-identical. `propose` (level, contested mark, badge) is always tier 2: it reaches a draft only as a proposal in the weekly pull request, marked for the founder. Why: CLAUDE.md rule 2.
- The weekly list is a pull request on branch `pipeline/<date>`; the founder approves by merging. Nothing is published and the calibration period continues. The pipeline updates existing cards only; a paper that suggests a new hypothesis is listed in the report and no card is drafted.
- The mechanical checks gate review: citation errors already on the card are reported as pre-existing and do not block a new paper. Two rounds at most, then the parking lot. `pr --no-pr` stops after the local commit (no push). Reference: `docs/pipeline.md`. Plan: `docs/plan-weekly-pipeline.md`. Lessons from the first five cards: `docs/drafting-checklist.md`.

## 2026-11-01 — Cards four and five (autoimmunity; gut microbiome)

- Autoimmunity (autoantibodies and B cells): draft level 3, not contested. The 151-patient placebo-controlled CCC rituximab trial (pmid:30934066), larger and stricter than the 30-patient trial (pmid:22039471) that met rung 4 as written, settles rung 4: it is not reached. General reading of spec section 3 "a larger study settles it": when a larger study of the same or stricter case definition with a control group contradicts the only study on a rung, the rung is not reached rather than contested. Rung 3 rests on Azcue 2026 (beta-2 antibodies only, same commercial test). Germain 2025 (pmid:40141440) may contest rungs 2-3 once its full text is cached and verified; to be decided then.
- Long COVID label: "modified CCC" counts as CCC (autoimmunity keeps the label). A study whose case definition is unverified cannot carry the label; the gut microbiome card drops its only long COVID study (pmid:39592468).
- Gut microbiome: draft level 3, not contested, resting on lower stool butyrate in two independent cohorts (pmid:36758522 CCC; pmid:41387992 IOM 2015). Conflicting gut-wall marker results do not bear on that finding. Diagnostic marker no: the validation cohort came from the same group and sites.

## 2026-11-01 — Third card (impaired energy production after exertion)

- Draft level 3, contested at rung 3. The replication rests on Vermeulen 2010 (Fukuda), which the 2026 two-day study of 53 patients (Fukuda, no difference) contradicts at comparable quality, and on van Campen 2021, whose ICC reading is unconfirmed and whose comparison group has chronic fatigue without ME/CFS. Lien 2019 is a partial replication (work at the threshold, not oxygen use). Rung 2 rests on the 84-patient CCC study and is not contested.
- pmid:42212259 is recorded as Fukuda, from its own sentence; the card states that a companion paper on what appears to be the same cohort names the 2015 IOM definition, and that PEM was required.
- PEM badge rule clarified (spec section 3): the link must connect the mechanism to symptoms after exertion in the same patients; a measured change that is itself the hypothesised abnormality does not on its own explain PEM. This card: Explains PEM no. Why: a day-2 fall is both the PEM measure and the hypothesis, so the badge would be true by definition.

## 2026-11-01 — Rulings from the site review

- Level 2 needs a controlled study with a **recognised** case definition (the accepted table in spec section 3), not a "strict" one. Fukuda and Holmes 1988 count, flagged "does not require PEM". Why: the spec contradicted itself (Fukuda accepted at every rung, but level 2 said "strict"); this keeps the rule the cards were graded by.
- A study that cites "CDC criteria" without naming the version is accepted like Fukuda and Holmes 1988: flagged "does not require PEM", ranked equal to Fukuda. New card format value for it. Why: both CDC versions are accepted on the same terms, so the unnamed version is not weaker evidence than either.
- `last_checked.by` stays `ai_pair` on both drafts for now.
- Long sourced texts may be split into paragraphs, each with its own sources, so a reader can see which sentence rests on which study. Why: the NK level reason ended with 11 references in one block.
- NK card: the 21-patient CDC study (pmid:7983659) that found no difference is named in the contested reason as a second comparable contradiction of the 39-patient study. Rung 2 is not contested (it rests on the Miami study); levels unchanged. Why: under the CDC ruling it ranks equal to Fukuda and 21 is at least half of 39; the abstract does not say how many patients were measured, which the card states.

## 2026-11-01 — Site layout revised at founder request

- Site layout revised at founder request; ladder key under the chart; table behind a disclosure; secondary text minimum 16 px. The front page now opens with a short heading and one lead sentence, then the chart in one panel, the legend, the ladder key (rung names and meanings copied from spec section 3) and the table inside a closed "Show the chart as a table" disclosure. Calmer type: smaller headings, a 46 rem column, one compact header bar.
- Spec section 5 "Text size" amended: body text at least 18 px equivalent; secondary text (keys, labels, study details) at least 16 px; layout holds at 200%. Why: the founder found the first view too text-heavy and large-typed; 16 px for secondary text keeps it readable while letting the main text lead.

## 2026-11-01 — Static site generator

- The site is plain static HTML written by `uv run python -m me_atlas.site build` with Jinja2 (already a dependency): one CSS file, one small JavaScript file for the glossary explanations, no external fonts, scripts or styles, every page works from `file://`. Output goes to `build/` (gitignored). Why: no server, database or build tooling to maintain; readers on poor connections and the founder can open the files directly.
- Drafts are built only with `--drafts`, and then every page carries the banner "Draft preview — not published" and `<meta name="robots" content="noindex">`. Without the flag only `cards/` is read, so a draft cannot reach a page by accident. "What changed" never shows drafts. The build runs the card validator first and writes nothing if any input fails. Why: CLAUDE.md rule 2; only the editorial team moves content into `cards/`.
- Glossary: one file, `content/glossary.yaml` (term, aliases, explanation of at most 200 characters, none of the banned words). The generator marks the first occurrence on each page of every glossary term or alias in sourced text and study findings (whole word, case-sensitive, longest match wins, never in study titles, links or headings); template labels are marked through one macro. No change to the card format. Founder ruling: option a. Why: card authors do not mark terms by hand and the explanation stays in one place.
- Replication status has no card field of its own; the page shows it through the level name and the level reason. Why: the format backlog stays closed until a card needs a field.
- Plan: `docs/plan-site-generator.md`. Reference: `docs/site.md`.

## 2026-11-01 — Mechanical citation check

- The citation check is its own offline command, `uv run python -m me_atlas.citations check`, not part of `cards validate`. It reads only the cache and never makes a request. Why: the cache is gitignored, so it cannot run on GitHub as the validator can; it runs locally and later in the weekly pipeline.
- Seven checks per study, C1-C7: record exists, title, year, not retracted, case-definition quote verbatim in the stated source, sample size, DOI-only id. Matching is exact after a stated, narrow normalisation (NFKC, whitespace, case for titles; quotes and dashes for quotes), nothing looser. Reference: `docs/citation-check.md`. Plan: `docs/plan-citation-check.md`.
- Sample size (C6) is a warning, not an error. Why: a correct number may be written as a word, be a sum of cohorts or belong to one measurement, so a person looks instead of the check blocking.
- A `doi:` study id is an error for now ("cite by PMID"). Why: only PubMed records are fetched, so a DOI-only id cannot be checked; every current study has a PMID.
- `pubmed fetch --ids <pmid>...` fetches exactly the given records (no search, no retraction query), so a card can cite a paper outside the search query. It writes a run manifest with the mode and ids.

## 2026-11-01 — Rulings from the first two draft cards

- Comparable quality uses the number of patients in the measurement that bears on the finding, not the whole study. Why: stricter and more honest when only part of a study measured the outcome. Added to spec section 3.
- A rung that rests on more than one study is contested when a study of comparable quality contradicts any study the rung needs. Why: the rubric compared single studies only. Added to spec section 3.
- Early signals come only from studies with a confirmed recognised case definition. Why: the inclusion rule says that without one we cannot tell whether the patients had ME/CFS. Added to spec section 4.
- NK card: the Miami group (20520837) counts as independent of the 39-patient Australian study (27099524) for level 3; their author lists and cohorts are separate, and the indirect co-authorship link is stated on the card. The ADCC study (33777500) stays background, since it measures a different kind of NK killing.
- Neuroinflammation card: a diagnosis "consistent with the Canadian Consensus Criteria, confirmed by two clinicians" (41834684) counts as CCC; the verbatim quote is shown on the card.
- Proposed levels accepted as draft levels: reduced NK cell function level 3, contested at rung 3; neuroinflammation level 2, not contested. Both stay in `drafts/` until publication.

## 2026-10-31 — Card format v2, Holmes 1988, Europe PMC on demand

- Card format v2 (rule V13 added): `case_definition` gains `unverified` (not yet checked) and `Holmes1988`; `none` now means the source was checked and states no case definition. New study fields `case_definition_source` (abstract, fulltext or null) and `case_definition_quote` (the verbatim sentence), `direction` (lower, higher, no_difference, mixed, not_applicable; required for every role) and optional `group` (research group label). `unverified` cannot support or contradict, like `none`. Why: the first two draft cards could not say "not checked yet", which way a background study points, or which group did a study. Reference: `docs/card-format.md`. Plan: `docs/plan-fulltext-and-format-v2.md`.
- Holmes 1988 (the 1988 CDC definition) is accepted like Fukuda: allowed at every rung, flagged on the card as "does not require PEM", ranked equal to Fukuda in the comparable-quality rule. Added to the case-definition table in the functional spec, section 3. Why: founder ruling when the plan was approved.
- Europe PMC full text is fetched on demand, only for PMIDs on a card or draft (or given on the command line), never in bulk, and only for open-access records. Full text stays in the gitignored cache; a card quotes at most the one sentence that states the case definition. The finder suggests sentences; a person or agent decides which definition a sentence means. Why: the case definition is normally in the methods section, not the abstract, and bulk download is neither needed nor polite.
- The two existing drafts were migrated: every study whose abstract wording is quoted in the draft's comments got source `abstract` and the verbatim sentence; every study that was `none` ("not stated in abstract") is now `unverified`, because the full text has not been read. No level, contested mark, badge or text field changed.

## 2026-10-31 — PubMed fetch

- PubMed only for now. It is the canonical source for PMIDs, titles, publication types and retraction flags. Europe PMC (preprints, full-text links) is added only if a concrete need appears.
- The search query lives in `config/pubmed_query.txt`, not in code, so changes are reviewed in a pull request. Why: the query decides what the Atlas can ever see.
- ME/CFS by MeSH heading plus title/abstract terms; long COVID only when the record also mentions ME/CFS (the AND clause). Why: long COVID alone is far larger and out of v1 scope; the overlap studies are what the long COVID label needs. The MeSH headings are checked against live PubMed on the first live run, not taken on trust.
- Full backfill once, then weekly runs by entry date over the last 14 days, de-duplicated by PMID. Why: fetching costs requests, not money; classification cost is controlled later.
- Retraction check on every run: the query plus the "Retracted Publication" filter, not limited by the date window, with a stale cached copy downloaded again. Why: a card citing a later-retracted study must be caught (spec section 3).
- No filtering at fetch time; deciding what counts as evidence belongs to classification. Details: `docs/fetch.md`, plan `docs/plan-fetch-script.md`.

## 2026-10-31 — Card data model

- Cards are YAML, one file per hypothesis (`cards/<slug>.yaml`), validated by pydantic models in `src/me_atlas/cards.py`. Why: YAML reads well in a pull request diff and allows comments; pydantic and PyYAML were already dependencies.
- Studies are listed inline on each card, with no shared registry. A study cited by two cards appears twice; the later citation check compares both against the fetched record. Every free-text field is `{text, sources}`, so "every claim links to its source" is checkable.
- Drafts use the same schema as cards (`drafts/<slug>.yaml`); the change is the diff against the card. No separate patch format.
- Derived, not stored: the long COVID label (any cited long COVID cohort), the hatched contested segment (`contested.rungs`) and ranking (`level`).
- One change log, `cards/changelog.yaml`, an append-only list of entries (date, card, change, reason, sources, tier).
- Twelve mechanical rules (V1–V12) are enforced by `uv run python -m me_atlas.cards validate`; reference in `docs/card-format.md`. Plan: `docs/plan-card-data-model.md`.

## 2026-10-31 — Tiered AI review and open questions

- Review runs mostly on AI: a drafting agent and an independent review agent, with mechanical citation checks in code. Two failed rounds send a change to a parking lot for the founder. Tier 1 changes (new study on a card, factual text) may publish automatically after a calibration period; levels, badges, contested marks and new hypotheses always need the founder. CLAUDE.md rule 2 amended to match. Why: no medical reviewer yet; keeps the founder's workload small while a human still decides everything that moves the chart.
- No external reviewer before launch; recruit after showing the site publicly. The site says openly that content is AI-reviewed, not expert-reviewed.
- Oxford-only evidence capped at level 1; Fukuda flagged "does not require PEM". PEM badge needs a study that measures PEM directly. Contested = same or stricter case definition, controlled, at least half the sample size. Early signals on cards only, fixed wording. Long COVID label on the card. v1 stands alone from MEpedia.
- Details: `docs/ME-Atlas-functional-spec.md` sections 3, 6 and 8.

## 2026-10-31 — Front page and evidence display

- Front page is a pipeline chart: one bar per hypothesis against the status scale, ranked as "furthest along", never "most promising". Contested evidence shown on the bar. No momentum or paper-count metric. Why: honest, familiar format; volume is not evidence.
- One axis (causal evidence) plus two card badges: validated diagnostic marker, explains PEM. Treatment success alone is not proof of cause. Why: easier to read than three tracks, and scientifically accurate.
- v1 covers ME/CFS; long COVID is marked where evidence overlaps. No subgroup filtering in v1. Why: keep scope small.
- Site is in English, plain language; technical terms explained from one shared glossary on hover, tap and focus. Why: international audience with limited energy.
- Details and next steps: `docs/plan-functional-spec.md`.

## 2026-10-31 — Repository setup

- Python with `uv`, `ruff` and `pytest`; static site generated from card files, no database.
- Approved cards live in `cards/`, AI drafts in `drafts/`; only the editorial team moves content between them.
- Agent roles adapted from Kunnskapsbanken in a lean form: prosjektleder, brainstorm, orchestrator → worker → evaluator, plus a domain `card-reviewer` that fact-checks citations.
