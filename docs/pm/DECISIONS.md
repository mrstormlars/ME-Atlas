# Decisions

Append-only, newest first. One entry per ruling: date, decision, why.

## 2026-11-17 — The held-back correction of the autoimmunity card is run again with the full texts (founder ruling)

- The first run of the published-card correction on `autoimmunity-autoantibodies-b-cells` was held back after its two audits disagreed. The second audit rejected on abstracts only: the worktree had no `.env`, and the loader then skipped full texts that were already cached. Told this, the founder said: "Flett 84 og 85, og kjør rettingen på nytt".
- The loader was fixed first (pull request 86: a cached full text loads without the contact email; a fetch still needs it). The new run used fresh agents that were not shown the earlier audit records. It was agreed beforehand that a second disagreement would leave the card unchanged with no third attempt.
- Outcome (pull request 87): the review found two wording points, the correction was classed wording-only and applied on the checks and the review, with no audit. The stale YAML comment on pmid:40703261 stays, because a comment-only removal always goes to two audits that cannot see the comment (listed in STATUS.md, "To build or fix").
- Why: the reject rested on missing source access, not on a disagreement about the content.

## 2026-11-17 — A path for correcting the text of a published card is to be built (founder ruling)

- The weekly run of 2026-11-17 left three wording points on published cards (`reduced-nk-cell-function`, `autoimmunity-autoantibodies-b-cells`, `oxidative-nitrosative-stress`), and the clean-up found that the pipeline has no way to make them: the correction round and its wording valve work only on a held-back draft, the weekly `apply` refuses `update_study`, and no step changes the text of a link already on a card. The functional spec (section 6, point 9) expects corrections to go "the same way".
- Asked to choose between building that path (A) and asking for the three fixes explicitly as a founder-requested change (B), the founder answered: "gå for alternativ A". The three fixes wait for the path and go through it.
- Why (the project manager's recommendation, accepted): wrong wording on a published card will come again, most of all when readers start reporting errors, and the path should exist before then; none of the three points changes a number or a finding, so they can wait.

## 2026-11-17 — The whole-card review gate also holds for first publication

- A new draft reaches `cards/` only with an accepting whole-card review by the review agent of the draft as it stands; the review is tied to the draft by a sha256 written by code, so a draft changed after the review is refused (`docs/pipeline.md`, "First publication"; pull request 74, merged by the founder's instruction "Please flett alle 3 PR-ene"). This replaces the earlier statement in this file that the gate covers correction rounds only.
- Why: the founder ruled on 2026-11-17 that the known gaps in the pipeline stay a priority, and this was the gap that bore most directly on credibility: a first publication could pass with only its parts reviewed.

## 2026-11-17 — Errata and corrections to a cited paper: three founder rulings

- The plan `docs/plan-errata.md` (pull request 75) asked three questions; the founder answered: "Følger dine anbefalinger for alle tre spørsmålene." The recommendations were the plan's A(a), B(a) and C(a):
- **A. The pipeline decides the card change.** An erratum or published correction to a cited study goes through drafter → review → audit like a new paper, not to the founder as a retraction does.
- **B. An erratum can move a level, a badge or the contested mark only by changing the corrected study** (its numbers, its role, its finding). The erratum itself never counts as a study for the ladder and is never a source of a level or badge reason.
- **C. Other notices are out of scope until one occurs.** Expressions of concern and "corrected and republished" notices have no case in the cache; the parser records unknown notice types in the run manifest so the first one is seen.
- Why: an erratum is published text about a study the card already cites, and the audit already guards every level, badge and link move; the founder is not a subject expert and should not be the one to judge what a correction means for a finding.

## 2026-11-17 — Idea bank: seven guidelines, maintenance leaves the priority list, wave 1 is the "What is missing" page (founder rulings)

- **Seven guidelines for every idea from `docs/pm/IDEAS.md`.** Proposed by the project manager; the founder answered: "De 7 føringene er OK."
  1. No new claims: a page built on the cards is derived from the cards by code and carries no text of its own that is not on a card.
  2. A new kind of source needs a source rule first: every fact comes from a fetched, cached and dated copy, otherwise `TODO: verify`.
  3. A new AI reading step needs a reliability test before it is scaled, with the limit of the bridge pilot (at most one in five rejected).
  4. Lists, never advice: no ranking as "most promising", no call to take part in a study.
  5. Norwegian follows: a new page goes through the translation path before it counts as done.
  6. One branch and one pull request per idea; the founder merges; orchestrators run on Opus.
  7. At most two ideas in work at the same time.
- **Maintenance is not a priority.** The founder said: "Ukentlig oppdatering og svare på henvendelser er jo ikke noe som hører hjemme i en slik prioriteringslister, da det er vedlikehold og ikke utvikling av ME Atlas." The weekly run and answering issues, Discussions and replies move to a "Running upkeep" section in STATUS.md. Closing the known gaps in the pipeline stays a priority: "Hvis det fortsatt er huller, burde vi beholde som prioritet å tette dem."
- **Wave 1 is I-01 together with a rebuild of the "What is missing" page.** The founder said that the page is already too crowded with text, that the replication list belongs on it, and that the rest must shrink: "Jeg foreslår at all tekst fra kortene fjernes, og at vi kun bruker lenker til kortene. Hvis dette blir for knapt, brukes 1 setning som oppsummerer innholdet. Grafer og tabeller er bedre enn 'wall of text'." I-05 (open data and citation export) waits; its licence is not decided.
- Why: the idea bank adds pages and data sources faster than they can be checked unless the same rules hold for all of them; a priority list that holds upkeep hides what is being developed.

## 2026-11-17 — Site text and spec brought in line with the current state; three founder rulings

- **Who decided: not shown.** The founder said: "Det er lite relevant foreløpig hvem som har lagt til hva, siden det er KI-agenter som uansett sjekker før noe publiseres. Utelat dette foreløpig." The change log page does not print `decided_by`; the methods text no longer promises "who decided it" and says nothing about the one founder-requested change. The field stays in `cards/changelog.yaml`.
- **The trial period ends.** The founder said: "Fjern også setningen om de fire første ukene, jeg leser ikke listene og det gir ingen mening fordi jeg ikke er fagperson. Når fagperson(er) blir involvert får vi lage nye prosedyrer for kvalitetssikring, om nødvendig." The trial period of four weekly runs (2026-11-13) is over; no document states it as in force. The founder still merges the weekly pull request as an operational step, without reviewing the content.
- **The disagreement count is mentioned.** The founder said: "Antall uenigheter kan gjerne nevnes i oppdateringen, så leserne får litt innblikk i prosessen som førte til publikasjon (evt. ikke publikasjon)." The methods text says that the count is in the description of each weekly pull request in the public repository (the report has the line "Consistency check: N of M sampled decisions decided a second time; K differed"). A count on the site itself would need new data and is not built.
- **Not a new ruling: the spec is aligned with rulings that already stand.** The functional spec's roles table gave the auditor tier 3. Tier 3 (a change the review agent rejected in two rounds) has no AI step: a parked change never goes to the auditor (2026-11-13, D2, and "A parked change never goes to the auditor (D2 stands)"). The table now says so.
- Also in this change: the methods text, the README and the spec say that no external reviewer has been recruited (they said one "is to be recruited"), describe first publication, correction rounds, the wording-only valve and link rounds, and the methods text says that every card shown was audited as a whole card by two auditor runs; the Norwegian text and the site strings follow.

## 2026-11-17 — A second bridge search pilot with a tighter reading; only systematic reviews count (founder ruling)

- After pilot 1 (reviewer rejected 9 of 21 `yes` rows, above the limit of one in five), the founder agreed in a brainstorm to a second pilot on the same eight questions and records, with only the reading changed (`docs/plan-bridge-pilot-2.md`): "Ja, la oss kjøre en ny pilot (alt A) først." On starting it: "Ja, start piloten".
- Only systematic reviews and meta-analyses count towards an outcome; narrative reviews (and records that are not reviews of studies) are listed as leads, with no outcome drawn from them.
- The reject-rate test (at most one in five `yes` rows rejected) is the test the pilot exists for and is not redefined after the run. Protocol: `docs/pm/bridge-pilot.md`, section "Pilot 2: protocol".
- Why: pilot 1's searches and controls worked but its reading did not; changing only the reading shows whether it can be made reliable before the method is run on more links.

## 2026-11-17 — The local data folder is backed up to a private repository (founder ruling)

- The founder said: "Forsikre deg om at cachen ikke slettes ved et uhell igjen (hva med en backup, f.eks. til github?)". `data/cache/` and `data/pipeline/` are backed up as a separate git repository whose git directory lies beside the project folder, pushed to a private repository of the founder's; `/ukentlig` ends with a backup step (`docs/fetch.md`, "Backup of the local data").
- Private, not public (orchestrator's choice within the ruling): the cache holds full texts that are free to read on PubMed Central but not open access, and publishing copies of them would be redistribution.
- Why: on 2026-11-16 the cache was deleted by accident during a clean-up of old worktrees. It is described as reproducible, but 16 full texts could not be fetched again by code and had to be saved by hand.

## 2026-11-16 — Link rounds: each link decided on its own, the wording valve applies; the nine links get one new attempt (founder ruling)

- After the link round of 2026-11-16 restored two of the eleven removed links, nine were still out: `brain-and-brainstem-mri-changes` (1), `hpa-axis-cortisol` (3) and `gut-microbiome` (4 proposed; the link to `tryptophan-kynurenine-metabolism` was not proposed, no record states it). The auditors had found six of them supported but rejected each card's round as a whole over one link or one clause.
- Asked "Skal de ni gjenværende lenkene få et nytt forsøk med endrede regler? Jeg anbefaler ja, med to endringer: hver lenke avgjøres for seg, og sikkerhetsventilen gjelder også for lenkerunder.", the founder answered: "Ja til begge".
- **Each link is decided on its own.** The audit record of a link round gives a decision per link; an accepted link is published even when another link of the same card is rejected. Each published link still needs two agreeing audits; the second audit runs for the links the first did not reject.
- **The wording-only safety valve applies to link texts** at the map review and at the audit, as it exists for correction rounds (the finder classifies `decisive` or `wording`; the orchestrator removes or rewords only the named sentence of the link text, removal when in doubt; code refuses a fix that touches anything but that text; one fix check by `card-reviewer`). Nothing else about the valve changes.
- **One new attempt** for the nine links, through the changed link round.
- Changes: the orchestrator defaults of 2026-11-16 "one audit decides all links of a card together" and "no wording valve in a link round". The other link-round defaults stand as defaults.
- Why: the conclusions a reader relies on still need two agreeing audits per link, but a supported link should not fall with another link, or with a clause that removing it resolves.

## 2026-11-16 — The eleven links removed in the correction rounds get a new trial (founder ruling)

- Eleven links on five cards were removed in the correction rounds of 2026-11-14/15: `gut-microbiome` (5: symptom:gastrointestinal-symptoms, symptom:cognitive-impairment, tryptophan-kynurenine-metabolism, neuroinflammation, oxidative-nitrosative-stress), `hpa-axis-cortisol` (3: symptom:sleep-disturbance, symptom:cognitive-impairment, question:what-keeps-it-going), `endothelial-dysfunction` (1: orthostatic-intolerance-cerebral-blood-flow), `small-fibre-neuropathy` (1: symptom:orthostatic-intolerance), `brain-and-brainstem-mri-changes` (1: symptom:cognitive-impairment). Most went because the auditor then saw only the abstract of a link's source and could not match the statement to it, and a correction could only remove. Since 2026-11-16 the audit context gives the cached full text of link sources.
- Asked "Skal de elleve fjernede lenkene prøves på nytt når del C er ferdig?", the founder answered: "Ja, prøv dem på nytt".
- Each link is tried again through the link path (`link-drafter` from cached records, `card-reviewer` in map mode, the auditor's tier 2 decision). The old link text is a starting point only. A link comes back only when a cached record states what it rests on and the reviewer and the auditor accept it; otherwise it stays out, with the reason recorded. No level, badge, contested mark or layer changes.
- Why: the links were removed as unverifiable from an abstract, not shown false; the auditor can now read the full text.

## 2026-11-16 — The five links for the bridge search pilot (founder ruling)

- The founder said: "Jeg følger din anbefaling, test ut de 5 forbindelsene du foreslo for del C". The five links searched in Part C of `docs/plan-wider-sources.md` are: oxidative-nitrosative-stress → endothelial-dysfunction; autonomic-imbalance → orthostatic-intolerance-cerebral-blood-flow; reduced-nk-cell-function → herpesvirus-reactivation; tryptophan-kynurenine-metabolism → neuroinflammation; autoimmunity-autoantibodies-b-cells → orthostatic-intolerance-cerebral-blood-flow. All five were at step `proposed` in the map report that day.
- Why: they were proposed as pairs where both ends are measurable quantities. The pilot produces a report only (`docs/pm/bridge-pilot.md`); it changes no card, the site or the weekly pipeline. The positive control, the base-rate pairs and the other choices the plan left open are recorded in the protocol as orchestrator defaults.

## 2026-11-16 — The orchestrator defaults in use are confirmed; the domain waits (founder rulings)

- **The orchestrator defaults that were used are permanent.** The founder said: "Bekrefter standardvalgene vi brukte, la dem bli permanent." This is read as covering every choice recorded in this file or in a plan as an orchestrator default or as "for the founder to confirm" that was in use when the 20 cards were published, among them: the cap of four revised attempts per correction round while the decisive findings fall (2026-11-15/16); the three check retries being shared by a round's attempts, not three per attempt (2026-11-16); the valve removing a sentence rather than rewording it when in doubt (2026-11-15); and the defaults listed at the bottom of `docs/plan-causal-map.md`, `docs/plan-drawn-map.md` and `docs/plan-hypothesis-and-link-survey.md`. They are rulings from now on; the founder changes them like any other ruling. The reading of the scope is the orchestrator's, not the founder's words.
- **The domain me-atlas.org is not registered for now.** The founder said: "Vi venter med domene til jeg ser om dette vekker noen interesse." The site stays at its GitHub Pages address.
- **The empty Azure resource group is deleted** on the founder's request ("Slett den tomme ressursgruppen i Azure."), after the storage account in it was removed earlier the same day.

## 2026-11-16 — The Azure draft preview is deleted (founder ruling)

- The founder said: "Slett gjerne Azure-nettsiden, den trenger vi ikke lengre nå." The storage account that hosted the draft preview was deleted on 2026-11-16; the public site on GitHub Pages replaces it. Why: with all 20 cards published and the site public, a second address with an older draft build could only mislead a reader.
- This ends the 2026-11-03 ruling on the private preview. The preview address in earlier entries and in the history is dead.

## 2026-11-16 — Hosting on GitHub Pages; error reports through GitHub issues (founder ruling)

The founder, on where to host the public site: "Ja, da bruker vi Github Pages." And on the contact address for error reports: "Kontaktadresse kan vel være lenke til Github issues."

- **The public site is hosted on GitHub Pages**, built from `main` by `.github/workflows/pages.yml` (approved cards only, never drafts). Why: free, no account or server to run, and the repository is already on GitHub. It goes live only when the repository is public and Pages is enabled with source "GitHub Actions"; the private Azure preview is unchanged.
- **Error reports go through GitHub issues.** Every page's footer links to the issue chooser and to the repository. Why: no personal address is published, and the issue forms (`.github/ISSUE_TEMPLATE/`) already collect what a correction needs. The site promises no response time.

## 2026-11-16 — The auditor gets the full text of link sources; one more round for the energy card (founder ruling)

Proposed to the founder: "Gi revisoren fulltekst også for lenkekilder, og kjør én runde til på energikortet (C6)." The founder: "Ja, merge og ny runde".

- **Full text for link sources.** The audit context gives the cached full text, uncut, of every study a link on the card cites, as it already does for the studies that carry the level, a badge or the contested mark. A link source with no cached full text is given with its abstract and the same "full text not cached" statement as such a study.
- **One more round for `impaired-energy-production-after-exertion`** (round C6, a logged exception, as `REOPENED_ROUNDS`).
- Changes: the 2026-11-13 ruling "Source text for the auditor" (full text only for the sources that carry a level, a badge or a contested mark; `carrier_ids`, `docs/pipeline.md`, "Full text for carriers") now covers the sources of links too. The review contexts already name the cached full text of every cited study and do not change.
- Why: the energy card's round C5 audit rejected a link because the statement it rests on is not in the review's abstract; the statement is in the cached full text, which the audit context did not give, because a link's source was not a carrier.

## 2026-11-16 — Three rubric clarifications; one more round for the last two cards (founder ruling)

The founder: "Jeg godtar de tre presiseringene. Prøv på nytt." The three clarifications, proposed to the founder in Norwegian and written into functional spec section 3 in English (every review, drafting and audit context embeds that section):

1. **Case definition.** A study is recorded with the definition its own text states. Another article's description is carried over only when a source says the patient group is the same. Comparability is judged by the recorded definition, and the uncertainty is written out on the card.
2. **Unknown patient count.** When the sources do not state the number of patients in the measurement that contradicts the finding, the contested mark is not set, but the contradicting finding and the missing number are written out on the card.
3. **Layer without a link.** When no source carries a link for the other reading, it is enough that the ambiguity is written out with a source.

- **One more round each** (logged exceptions, as `REOPENED_ROUNDS`): `impaired-energy-production-after-exertion` round C5, then `herpesvirus-reactivation` round C3, one card and one agent at a time.
- Changes: section 3 "Accepted case definitions", "Contested evidence" (the comparable-quality rule, for a contradicting measurement whose patient count no source states) and "Causal map and links" (the rule that a card in two possible layers gets a link expressing the other reading). Everything else stands.
- Why: the last two cards were held back on these three questions. The round C2 and C4 audits of the energy card disagreed on how to treat a case definition known only from a companion paper, and the herpesvirus audit asked for a count and a link that no cached record gives.

## 2026-11-16 — Up to three check retries per correction round; one more round for the energy card (founder ruling)

The founder: "Ja, bygg inn endringen og gi energikortet en ny runde", accepting the proposal "feilede mekaniske sjekker får inntil tre nye forsøk per runde, og drafteren får den nøyaktige feilmeldingen ... Energikortet får da én runde til som loggført unntak."

- **Up to three check retries per correction round.** When a correction attempt fails the mechanical checks (ops problems, the target guard, the validator, the citation checks C1-C11), the drafter may write it again, up to three times per round, shared by the round's attempts. Each retry's ops and checks files are kept in the trail. The drafter of a retry is given the exact check output: rule, location and message of every failed check. Reviews, revisions and audits are unchanged.
- **One more round for `impaired-energy-production-after-exertion`** (round C4, a logged exception, as `REOPENED_ROUNDS`).
- Changes: the rule "one check retry per round" (the 2026-11-14 correction path; `docs/pipeline.md`, "The revised attempts": "if the check retry was used by the first attempt, a revised attempt that fails its checks ends the round") now allows three. Everything else stands.
- Why: the checks are deterministic and involve no judgement, so a retry cannot buy a different answer from a reviewer or auditor. The energy card's round C3 ended on check failures without its correction reaching a reviewer or auditor: the first attempt failed the target guard and its one retry failed the number check on 84.

## 2026-11-16 — Where an added sentence may go when the audit part names a structured item (orchestrator correction, not a new ruling)

The clause that an added sentence must go in a free-text field the audit part's target names, or that the pre-drafting review ties the part to, was the orchestrator's (contract clause (c)), not the founder's. The founder's words limit the addition to an audit finding that expressly asks for it and to the source and quote the auditor gave; they do not say where the sentence goes. For `herpesvirus-reactivation` round C2 the pre-drafting review tied the audit part that asks for the trigger-or-consequence reading only to `layer`, so the code refused the very sentence the ruling allows. Corrected to match the ruling: when the audit part is tied only to structured items, the sentence may go in the free-text field where the card explains that item: `layer` and `level` in the last paragraph of `level_reason`, `contested` in the last paragraph of `contested.reason`, a badge in the last paragraph of its reason, `studies[<id>]` in that study's `finding`. All other conditions stand. The drafter's first operations file of that round, written from the context before this correction and never applied, is kept under the round folder as superseded; the round's attempt is drafted from the corrected context.

## 2026-11-16 — A correction may add one sentence an audit finding asks for; one more round for the last two cards (founder rulings)

After the runs of 2026-11-15/16, two drafts were still held back: `impaired-energy-production-after-exertion` (its round C2 audit found rung 2 cannot be called uncontested while the records do not settle which case definition the contradicting New York cohort met) and `herpesvirus-reactivation` (its round C1 audit asked for the trigger-or-consequence reading to be written out, with two quoted sources, and the link path found no supported link target). The founder said: "Enig i ditt forslag til regelendring: En korreksjon får legge til én setning når et revisjonsfunn uttrykkelig etterlyser den, og bare med kilden og sitatet revisoren selv har oppgitt." The founder also agreed that both cards get one more round.

- **One added sentence per audit finding.** A correction may add one sentence when an objecting part of an audit record the round answers expressly asks for a missing statement, citing only sources that part quotes, in an existing free-text field that part's target names or the pre-drafting review ties it to, at most once per part. Code refuses anything else; the added sentence never adds a study, a link or a number not in the quoted source, and never changes the level, a badge, the contested mark or the layer. The quotes are carried into the trail, and the review agent checks the sentence against them like any other claim.
- **One more round each**: `impaired-energy-production-after-exertion` round C3 and `herpesvirus-reactivation` its unused round C2 (logged exceptions, as `REOPENED_ROUNDS`).
- Changes: the 2026-11-14 default "what a correction may do" ("it may not add a study or a paragraph", "it never adds a fact") and the 2026-11-15/16 rule that a correction deletes rather than rewrites now have this one exception. Everything else stands.
- Why: a held-back card should be able to answer an auditor who names the missing statement and its source, without the drafter choosing what to add.

## 2026-11-15/16 — Author facts by code, deletion-only corrections, more revisions while findings shrink, one more round for the last seven cards (founder rulings)

Seven drafts were still held back after the correction rounds of 2026-11-15. None stranded on a disagreement about the level; almost all stranded before any audit because the drafter introduced a new error while fixing an old one, most often an author or group fact (a shared-author count, a group naming the last author as first, site names used for independence), and the attempts ran out at the review stages while the number of findings was falling. Four points were put to the founder, who answered: "Enig i anbefalingene tine". Standing instruction for the runs: "Kjør ett om gangen, ikke flere parallelt, slik at ikke 5-timerskvoten overskrides (om den likevel overskrides, fortsett når den er nullsilt)."

- **Author facts are computed by code.** From the cached records, code computes for the studies on a card the authors two studies share (count and names), each study's first and last author, and affiliations where the record has them. The drafter and the reviewer get these facts in their context, and a deterministic check stops card text that contradicts them (a stated count of shared authors, a claim that two studies share no authors or are independent groups when they share authors, a `group` that names an author in the wrong position). Like C9 and C10 it is built for no false failures: an error for new and changed text, a warning for existing content; published cards are not edited to pass.
- **A correction deletes rather than rewrites, and touches only what a finding names.** The `card-drafter` prompt says so; code refuses a correction operation on a paragraph, study, link, level, badge or contested mark that no audit or review finding names.
- **More drafter-reviewer attempts while the findings shrink.** At the correction review and the whole-card review a further revised attempt is allowed as long as the number of decisive `must_fix` findings is lower than at the previous reject of the same review, up to a cap (orchestrator default: four revisions per round). The audit limit is unchanged: one sequential pair of audits per round, never re-run on an unchanged card.
- **One new round for each of the seven** (`mast-cell-activation`, `impaired-energy-production-after-exertion`, `brain-and-brainstem-mri-changes`, `orthostatic-intolerance-cerebral-blood-flow`, `hpa-axis-cortisol`, `oxidative-nitrosative-stress`, `herpesvirus-reactivation`), run strictly one card and one agent at a time. Logged exception per slug, as `REOPENED_ROUNDS`: the path changed, and for `mast-cell-activation` the lost round was the orchestrator's mistake. For `herpesvirus-reactivation` the missing link first goes through the existing link path (`link-drafter`, `card-reviewer` in map mode, the auditor's decision); if that path cannot produce a supported link from cached records, the card stays held back.
- Changes: the 2026-11-14 default "one correction round per card" gets these seven exceptions; the 2026-11-14 limits "one revised attempt after a review reject" and the 2026-11-15 rule "each limit is used at most once per round" now allow further revisions while the decisive findings fall, up to the cap; the 2026-11-14 default "what a correction may do" is narrowed to targets a finding names. The valve, the number check and the sequential audits stand as ruled.
- Why: the conclusions still need two agreeing audits, but a card should not lose its round to an author fact code can compute, to a rewrite nobody asked for, or to an attempt limit reached while the reviewer's findings were still falling.

## 2026-11-15 — A safety valve for wording-only findings, and a deterministic number check (founder rulings)

After five cards under the correction path, most hold-backs came from small findings that do not change a card's conclusions (a place name not in the record, a sentence an abstract does not state), and each new review found new ones. The founder said: "Når avviket som hindrer publisering er språklige detaljer som ikke endrer hovedkonklusjoner (nivåer for selve kortet eller årsaksforbindelsene), så rettes dette av orkestratoren direkte og sendes til en begrenset evaluering før publisering." Six points were put to the founder, who answered: "Ja, sett i gang slik du foreslår, men vurder også dette med tall. Det bør kunne sjekkes med kode (deterministisk) slik at tall-avvik unngås helt?"

- **Whoever finds a problem classifies it.** The auditor and the reviewer mark each finding `decisive` or `wording`. A finding is `wording` only if resolving it touches none of: level, badges, contested mark, layer, links, case definition, a study's role, or any number. The orchestrator never classifies.
- **Only wording findings open the valve.** At the audit stage: both audits valid, no decisive finding in either, and they agree on the level (an `accept` and a reject with only wording findings qualify; so do two such rejects). Any decisive finding, or an `accept_lower`, takes the normal path.
- **The orchestrator fixes directly**, with operations that remove or reword the named sentences (removal when in doubt), applied by the pipeline's operation code. A guard in code refuses a fix that changes anything but free text, or touches a paragraph no finding names.
- **A limited evaluation, once.** The `card-reviewer` in a narrow fix-check mode gets only each finding, the paragraph before and after, and the cited cached records, and answers per fix: does it resolve the finding without adding a claim? All yes: publish. Any no: held back. No further round and no new whole-card audit.
- **The same valve at the review stages.** Wording findings in the correction review and the whole-card review are fixed the same way and do not use up a revised attempt.
- **Trail.** The classification, the fix operations and the fix check are kept in `audits/`; the change log says the card was published after a wording fix.
- **Numbers.** A deterministic check: every numeral in a card's free text must occur in the cached text of a source that the paragraph cites, or equal a structured field of a cited study. It is an error for new or changed text (drafts, corrections, valve fixes); existing cards are counted first, not edited to pass. It verifies that a number occurs in the source, not that it is attached to the right thing. A proper-noun check (institution and place names in a cited cached record) is built as a warning only if it is low-noise.
- **`orthostatic-intolerance-cerebral-blood-flow`**: its audit records of 2026-11-15 predate the classification. As a logged exception, a `card-reviewer` classifies the second audit's findings once; if all are wording and the valve conditions hold, the valve runs on that card. `oxidative-nitrosative-stress` and `small-fibre-neuropathy` keep their round C2 under the new rules.
- Changes: the 2026-11-13 rule that a card publishes only when two audits accept (spec section 6) now has this exception; the 2026-11-14 and 2026-11-15 rule that a review reject uses a revised attempt no longer holds for a reject whose findings are all wording. CLAUDE.md rule 2 ("a dispute leaves the card unchanged") reads as before for decisive findings.
- Why: the conclusions a reader relies on (levels, badges, contested marks, links) still need two agreeing audits; a wording slip that removing a sentence resolves should not cost a card its only round.

## 2026-11-15 — Whole-card review before drafting, its own revised attempt, a new round for two cards (founder rulings)

The first two corrections run under the 2026-11-14 path (`oxidative-nitrosative-stress`, `small-fibre-neuropathy`) were both held back the same way: the first attempt was rejected in the correction review, so it never got a whole-card review; the revised attempt was accepted in the correction review and then rejected in the whole-card review, which ended the only round with no audit. The whole-card findings were in the draft before the correction and had not been raised by the audits, so the drafter never saw them. Three points were put to the founder, who answered: "Forslagene dine aksepteres".

- **A whole-card review of the unchanged draft before drafting.** The `card-reviewer` reviews the held-back draft as it is, with the same context as the whole-card review (cached records named by path, no full texts embedded). The correction context then holds both the audit findings and these review findings, so one drafting pass answers both. The pre-drafting review is input to the drafter, not a gate. Changes the 2026-11-14 sequence ("correcting a held-back draft"), which started with the drafter.
- **The whole-card review after the correction stays the gate before the audits and gets its own single revised attempt**, separate from the correction review's. Each limit is used at most once per round: the check retry, one revision after a correction-review reject, one revision after a whole-card-review reject. A second reject of the same kind ends the round with no audit. Changes the 2026-11-14 rule that a whole-card review reject counts against the one revised attempt of the round.
- **`oxidative-nitrosative-stress` and `small-fibre-neuropathy` get a new round, C2, under the new path.** They stranded on the sequence, not on their content, and no auditor has seen a corrected version. This is a logged exception for these two cards only, coded per slug; it is not a rule that a used round can be reopened. Their C1 trails in `audits/` stay as they are. Every other card keeps one round.
- Why: the 2026-11-14 order showed the drafter the whole-card findings only when the first attempt passed the correction review, so most cards would spend their only round without the drafter seeing the reviewer's findings.

## 2026-11-14 — Two agreeing auditors override the founder's earlier card rulings; orchestrator defaults confirmed (founder rulings)

- **The founder's earlier rulings about the content of a card no longer bind the audit.** The founder said: "Vi må se bort fra mine tidligere avgjørelser når det gjelder kortene. Når to revisorer er enige så overstyrer det mine tidligere avgjørelser." Where two auditors agree on a card, their decision stands over an earlier founder ruling on that card's content (a study's role, a level, a badge, a contested mark, a link). A correction may therefore change what such a ruling fixed, and a comment in a draft that records one is history, not a constraint. Why: the founder has no medical background and has handed the judgement of medical content to the auditor (entry "AI auditor and wider purpose", 2026-11-13). First case: `brain-and-brainstem-mri-changes`, where both audits want pmid:40624094 counted as contradicting with a contested mark, against a founder ruling of 2026-11-02 that kept it as context; the card may run without a new ruling. Unchanged: the founder still decides the rubric, the inclusion rule, the scope and the removal of a hypothesis, and may overrule the auditor from now on as a logged correction (`CLAUDE.md`, credibility rule 2).
- **The orchestrator defaults of 2026-11-14 are confirmed.** The founder said: "Dine forslag til øktens standardvalg aksepteres." This is read as covering the defaults in the three entries below (cheaper whole-card audits; the two separate limits inside a correction round; correcting a held-back draft), except the one the founder already changed (a review reject gives one revised attempt). They are rulings from now on.

## 2026-11-14 — Cheaper whole-card audits before the twelve held-back drafts (founder rulings)

The first publication used about 5.5M tokens on 40 whole-card audits; in 9 of 20 cards the first audit rejected, so the second could not change the outcome, and many rejects were for simple errors a reviewer can find. Three points were put to the founder, who answered: "Enig i alle punktene dine, gjør forberedelsene nå, men vent med å sette i gang selve kjøringene til jeg sier ifra."

1. **Whole-card audits run one after the other; the second runs only if the first does not reject.** A valid first `reject` holds the card back on its own. `accept` and `accept_lower` still need the second audit, and publishing still needs two valid, agreeing audits; the strictness for publishing is unchanged. The second auditor never sees the first record. Applies to first publications and to correction rounds.
2. **The `card-reviewer` reads the whole card before the auditors get it.** In a correction round, after the correction review accepts, a whole-card review pass (case-definition labels against the cached records, every link and claim against its cited source, the contested mark) must accept before audits are allowed. It works from the cached records, not the auditors' full-text context.
3. **Small batches, simplest findings first.** The twelve held-back drafts run three at a time in the order in `docs/pm/STATUS.md`; the founder stops between batches. No run starts until the founder says so.

Orchestrator defaults inside these rulings, for the founder to confirm:

- A first audit record that fails validation twice (after its one format retry) holds the card back without a second audit; the final invalid record is kept in `audits/` as `<date>-<slug>[-C<k>]-invalid.yaml`, so the draft counts as audited (it is not audited again unchanged) and a correction round closed this way counts as used.
- A correction round closed by a single valid reject counts as used, like one closed by two audits.
- Whole-card review findings count as review findings inside the same round: if the revised attempt is unused, a whole-card review reject triggers it (the drafter answers its `must_fix` findings, and the revision goes through checks, the correction review and a fresh whole-card review); if it is used, the card stays held back with no audit and the round counts as used.
- A missing or invalid whole-card review is an operator's missed step, not an agent's decision: `publish-card` refuses and writes nothing, and the round stays open.
- The whole-card review gate applies to correction rounds only; the first publication of a new draft does not have it yet.
- The `card-reviewer` stays on Opus for both review passes.

## 2026-11-14 — Correcting a held-back draft: one revised attempt after a review reject (founder ruling)

- **A correction the review agent rejects gets one revised attempt by the drafting agent before the round counts as used.** The founder's answer to "Skal en korreksjon som granskeren avviser, få ett nytt forsøk hos drafteren før runden regnes som brukt?" was "Ja, ett nytt forsøk". The drafter sees the reviewer's findings, as in the weekly path's second attempt; the revised correction passes the mechanical checks and the review agent again; a second reject ends the round and the card stays held back. Both attempts are kept in the trail (`audits/<date>-<slug>-C<k>-correction.yaml` and `...-correction-revised.yaml`). Why: the first live correction (reduced NK cell function) was rejected on two findings that a revision could answer, and the weekly path already gives a rejected draft one revised attempt.
- This changes the default "a review reject ends the round" in the entry below (orchestrator defaults, 2026-11-14). The other defaults in that entry are still defaults awaiting the founder's confirmation.
- Orchestrator default, for the founder to confirm: the retry after failed mechanical checks and the revised attempt after a review reject are separate limits, each used at most once per round, in either order.

## 2026-11-14 — Correcting a held-back draft: orchestrator defaults (founder to confirm)

Defaults chosen when the correction path was built (`docs/pipeline.md`, "Correcting a held-back draft"). Each is the orchestrator's default, not a founder ruling; the founder confirms or changes them.

- **One correction round per card** (`MAX_CORRECTION_ROUNDS = 1`). After it the card stays held back and is listed for the founder. Why: an audit is never re-run on an unchanged draft, and repeated rounds would let drafting keep trying until an auditor agrees.
- **The auditors of a corrected draft see exactly what a first-publication auditor sees**: the whole corrected card, comments stripped, its cached records, spec sections 2 and 3 and the card format. No earlier audit, finding or correction, and nothing that says the card was corrected. Why: the second pair of audits must be as independent as the first.
- **What a correction may do**: replace or remove a paragraph, change fields of an existing study (`update_study`), remove a link, lower the level, set a badge to false, add, change or remove the contested mark. It may not add a study or a paragraph, raise a level or set a badge to true. Why: a correction answers audit findings by removing, weakening or relabelling; it never adds a fact. Re-sourcing a link to another cached record is not an operation yet; such a link is removed.
- **Inside the round**: the drafter gets a second attempt only when the first fails the mechanical checks (the failed files are kept as `-attempt1`); a review reject ends the round. Why: checks are mechanical; a reviewer's reject is a content verdict and should not be argued away.
- **No redraft at a lower level (round L) after a correction.** Two agreeing `accept_lower` audits of a corrected draft hold the card back. Why: the correction itself may lower the level, and round L would be a second drafting round.
- **The trail** of a correction round is `audits/<date>-<slug>-C<k>-correction.yaml` (operations, check result, review verdict and findings, the audit files it answered, the draft's hash), next to its audit records `-C<k>.yaml` and `-C<k>-second.yaml`. It is written also when the round ends before the audits, so the round counts. `drafts/<slug>.yaml` stays unchanged unless the corrected card is published.
- **A first publication is refused** for a draft that already has a whole-card audit in `audits/`; such a draft can only go through the correction path.
- **Format retry** of an invalid audit record: one retry by a fresh auditor that sees its context, its invalid record and the errors, and must keep the same decision and level; a second failure is final.

## 2026-11-13 — Opening the repository: preparation rulings

Phase 1 of `docs/plan-open-repository.md`, prepared while the repository is private.

- **Copyright holder:** "ME Atlas contributors" (MIT for code, CC BY 4.0 for content; `LICENSE`, `LICENSE-CONTENT`).
- **Discussions will be on** when the repository is opened. Issues are for errors on cards, suggested papers and hypotheses, and bugs; questions and general talk go to Discussions.
- **Preview address** stays in `docs/site.md` (the preview may be public). The Azure account names are taken out of the text of `docs/site.md`; they remain in the history and in the 2026-11-03 entry, which is append-only; this is accepted.
- **The content-path check** (`pipeline content-paths`) and the marker trailer `ME-Atlas-Pipeline: weekly-run YYYY-MM-DD` on every commit `pipeline pr` makes are a review aid, not a security boundary. The boundary is the founder: an outside pull request comes from a fork; a genuine pipeline pull request has head branch `pipeline/<date>` in this repository, is opened by the repository owner and has the run report as its body.

## 2026-11-13 — AI auditor: three rulings before the first publication

After the auditor's dry run on the neuroinflammation draft (it accepted the level, badges, layer and links, and rejected the card over two statements it could not find in the text it was given).

- **Source text for the auditor.** The sources that carry a level, a badge or a contested mark are given to the auditor in full; the other sources as abstracts. Why: the context was cut at 12,000 characters per source, so the auditor rejected statements that stand further into the full text. A statement whose source is not in the cache (the dry run found one, on a published correction) is not a truncation problem: it is corrected in the draft through the normal drafting path.
- **A lower level is reached through a new draft round (D3 stands).** When the auditor answers `accept_lower`, nothing is applied automatically; the drafting agent rewrites the level reasons at the lower level, and the result goes through review and audit again. Why: the auditor does not write card text, and applying only the number would leave reasons that argue for the higher level. The outcome is the one ruled earlier the same day: the card is published at the level the auditor accepts.
- **A parked change never goes to the auditor (D2 stands).** A change the review agent rejected in two rounds leaves the card unchanged and is listed; no AI step overrules a rejection. This narrows the ruling below, which gave parked disputes to the auditor. Why: it is the most conservative reading. The founder may still overrule, as a logged correction.
- To build before the first publication: the full-text rule, the redraft path, and two stale sentences (`docs/ME-Atlas-v1-plan.md` "a human approves every change", `docs/pipeline.md` on who decides retractions).

## 2026-11-13 — AI auditor: contract decisions D1-D6 (steps 1-5 and 7 of the plan)

Taken when the plan `docs/plan-ai-auditor-and-purpose.md` was turned into a contract; the plan left these open. They are the implementation rulings of the entry below, not changes to it.

- **D1. Which changes are audited.** In a weekly run, every pair whose final round passed the mechanical checks, was accepted by the reviewer and contains at least one tier 2 operation. A pair with only tier 1 operations is applied on checks and review, as before, and is not audited. The audit decision covers the whole operations file: anything but `accept` means none of its operations is applied. Why: the founder's ruling moves tier 2 and tier 3 to the auditor and leaves tier 1 where it was; an operations file is applied as a unit, so it is decided as a unit.
- **D2. Parked pairs.** A pair that was rejected twice, or failed the checks after a rejection, is never sent to the auditor and never applied; it is listed under disputes. No AI step overrides a review rejection. Why: the conservative default of the plan (a dispute leaves the card unchanged), and an auditor that could revive a rejected draft would weaken the second reader.
- **D3. `accept_lower` is never applied automatically.** The auditor writes no card text, so the change stays as it is and the report lists the level the auditor accepts. A redraft at that level goes through the normal drafting path at most once; how that is done is decided with the first publication or a later run. Why: applying a lower level would need card text that nobody has drafted or reviewed.
- **D4. Where `pr` writes.** An accepted (and, where D1 requires, audited) change is written to the card's base file, as the pipeline already picks it (`cards/<slug>.yaml` when it is the card in use, else `drafts/<slug>.yaml`). When the target is in `cards/`, `pr` appends a change-log entry per accepted pair to `cards/changelog.yaml` with `decided_by: ai_audit` (audited) or `ai_pair` (tier 1 only). `last_checked` records the last audit: an audited change on a card in `cards/` sets it to the run date with `by: ai_audit`; a tier 1 only change leaves it as it is. Why: `last_checked` must say who last decided, and a tier 1 change is not an audit.
- **D5. Rubric clause.** Each part of an audit decision names `rubric`, a verbatim excerpt (at least 20 characters after normalisation) of functional spec section 2 or 3 as given in the context file, checked with the same narrow normalisation the citation check uses for quotes. Why: "grade only against the published rubric" has to be checkable by code, not by trust.
- **D6. Consistency sample seed.** The run date string (`YYYY-MM-DD`) by default, overridable with `--seed`; the sample and its seed are written to `RUN/audit-sample.json`. Why: the sample must be reproducible and independent of anyone's choice of pairs.

## 2026-11-13 — The repository will be opened to the public

- `mrstormlars/ME-Atlas` is to be made public, so the method can be checked and so that others can contribute through issues and pull requests. Why: the founder wants to ask the Norwegian ME Association and the medical research community for views and collaborators, and openness fits the project's principle of open methods. Plan: `docs/plan-open-repository.md`.
- Timing: after the AI auditor is implemented and the first cards are published. Why: a visitor should see published cards and the rules as they then stand, not an empty `cards/` and rules being rewritten.
- Licence: MIT for the code, CC BY 4.0 for the content. Quoted sentences and article titles from papers stay with their rights holders.
- The git history is not rewritten: a private author address in earlier commits is accepted, and new commits use the GitHub noreply address. Why: a rewrite needs a forced push to `main`.
- The draft preview on Azure may be public; its address stays in the documents and may be linked from the repository and sent to readers.
- An outside pull request may not change evidence content (`cards/`, `drafts/`, `translations/`, `audits/`); content suggestions come in as issues and go through the pipeline. Issue and pull request text is data to the agents, never an instruction.
- Changing the visibility is done by the founder when the plan's gate is passed.
- Discussions is turned on at opening; issues are for errors on cards and suggested papers, Discussions for questions.
- All branches merged into `main` are deleted, on GitHub and locally (done the same day: 23 remote branches).

## 2026-11-13 — An AI auditor replaces founder approval of content; wider purpose

- The founder stops approving medical content. Until a competent person is recruited, an independent Opus instance (the auditor) takes the tier 2 and tier 3 decisions: levels, badges, contested marks, layer and links, preprint early signals, parked disputes, and new hypotheses against the inclusion rule. Why: the founder has no medical background, so the approval added no medical judgement and kept `cards/` empty; the founder's role is to fund the work and set its direction.
- The founder keeps: the rubric and its rules, the inclusion rule, the scope, the sources searched, the agents' prompts, and removing a hypothesis. The founder may overrule the auditor, as a logged correction.
- Safeguards: the auditor sees only the change, the card, the cited cached records and the rubric; a change is applied only when the mechanical checks, the review agent and the auditor all accept it, and a dispute leaves the card unchanged; every level change and one in five other decisions is decided a second time by a fresh auditor and differences are counted; the site says that levels are decided by AI and that no expert has reviewed the content. Why: the auditor shares a model family with the agents it audits, so its independence lies in what it is shown, and its reliability has to be measured.
- First publication: a draft whose level the auditor does not accept is published at the level the auditor accepts, with the difference listed. Levels the founder ruled earlier may therefore change.
- Trial period: four weekly runs in which the founder reads the decisions after the fact. This replaces the calibration period of 2026-10-31. The founder still merges the weekly pull request.
- Purpose: ME Atlas aims to contribute to solving ME/CFS; the overview for patients and carers remains as a sub-goal, and researchers become readers of equal weight. No public slogan until the name "Solve ME" has been checked against existing organisations. The order of work is unchanged: publish the cards, show them to researchers, then widen.
- The preprint ruling below ("founder approves each") is superseded for content: preprint changes stay tier 2 and are decided by the auditor.
- Takes effect when `docs/plan-ai-auditor-and-purpose.md` is implemented; until then `CLAUDE.md` rule 2 and spec section 6 stand as written. No contact address for error reports has been given yet.

## 2026-11-13 — Preprints: founder approves each; null results are shown

- Every card change that comes from a preprint is tier 2: the founder approves each one. Why: nothing unreviewed should reach a card without a person having looked at it; the live check of the last 90 days found about two preprints a week, which the weekly review can absorb.
- A preprint with a null result is shown like any other preprint early signal, with the same "not peer reviewed" label. It cannot contest a level. Why: leaving out null results would tilt the cards towards positive findings.
- A preprint may be cited only under `early_signals` (validator rule V15; `docs/card-format.md` lists every sourced text). Preprints are recognised by the PubMed publication type "Preprint" and by the Europe PMC source `PPR`; a preprint with a published version, or with a newer version, is dropped (`docs/fetch.md`).
- Not yet ruled: whether the preprints that two drafts left out before this ruling (comments in `drafts/inherited-genetic-risk.yaml` and `drafts/tryptophan-kynurenine-metabolism.yaml`) are reconsidered as early signals.

## 2026-11-13 — Query recall check: "CFS/ME" added to the PubMed query

- `"CFS/ME"[Title/Abstract]` is added to block 1 of `config/pubmed_query.txt`. Hit count 9,403 before and 9,412 after (live, 2026-11-13). Why: the recall check (part A of `docs/plan-wider-sources.md`, results in `docs/fetch.md`) found 9 records the query missed, 7 of 9 about ME/CFS by their title.
- The four other candidate terms ("post-viral fatigue syndrome", "postviral fatigue syndrome", "post-infectious fatigue syndrome", "chronic fatigue immune dysfunction syndrome") were tested and not accepted (founder: "Bare CFS/ME"). Why: no sampled record of any of them was judged to be about ME/CFS from its title and abstract (0 "yes" in each sample; the rest "unclear" or "no").
- The query returns all 279 studies cited in `drafts/`. The 9 newly matched records are not ingested by this change.

## 2026-11-13 — After the first live pipeline run: `group` stays optional, TODO rule V14

- A study's `group` field stays optional. A missing `group` is a warning in `pipeline apply` and in the run report, and does not fail the pair. Why: 12 studies in 7 drafts lack it, so requiring it would be a format change; whether the warning should stop the tier 1 path is left for the ruling that ends the calibration period.
- "TODO" in reader-facing text is rejected by a validator rule (V14, `docs/card-format.md`), not only by a pipeline check. Why: the live run's mechanical check passed a draft with "TODO: verify" in a finding; such text must never reach a reader, whatever path wrote it.

## 2026-11-13 — Wider sources: indirect evidence, preprints, bridge search pilot

- A kind of evidence called "indirect" is introduced: sources whose population was not selected by an ME/CFS case definition (general human physiology, other conditions, long COVID without an ME/CFS definition). It may be shown on cards and the map but never moves a level, a badge, a contested mark or a link step. Why: the rubric requires an ME/CFS cohort; a mechanism shown elsewhere is a question for ME/CFS, not a finding about it.
- Preprints come in (via Europe PMC) as early signals only, with a fixed "not peer reviewed" label; the validator keeps them out of level reasons, contested reasons, badges and links. Why: the field publishes there first, but nothing unreviewed may move the chart.
- A bridge search pilot is run before anything is built into the weekly pipeline: for links at step `proposed`, pre-registered searches for systematic reviews outside the ME/CFS literature, in two arms (general, and long COVID without ME/CFS mention), with a positive control and base-rate pairs. Searches are question-driven; no discovery score or ranking. Why: literature-based discovery generates hypotheses and finds something for almost any pair if run broadly; the pilot shows whether a hit carries information.
- This ends the hold of 2026-11-08 on sources outside the ME/CFS literature. Plan: `docs/plan-wider-sources.md`. Not yet ruled: the five pilot questions, the review tier for preprints, whether null-result preprints are shown.

## 2026-11-08 — Gaps page ("What is missing"); no weighted symptom score

- New page `gaps.html` / `nb/gaps.html` ("What is missing" / "Hva mangler"), in the navigation after the causal map, and the same five lists in `uv run python -m me_atlas.map report`: symptoms with no link, symptoms linked only at step 1, links not yet tested in patients (grouped by target), what the next rung requires (cards by level with the ladder's own wording and contested marks), and hypotheses with no links. Everything is derived mechanically from existing card fields and the symptom list; nothing is scored or judged. Founder ruling: the plan's defaults (`docs/plan-gaps-page.md`), including keeping the next-rung list and the page name.
- Rejected: ranking hypotheses by the number of symptoms they explain directly or indirectly, weighted by link step. Why: today the count would mostly measure how thorough one cached review was (one review supplies five of the gut microbiome card's links), it saturates over a graph with loops, the weights would have no source in the rubric, and the spec allows no "most promising" ranking. Gaps are counted and listed, like convergence; which hypotheses are promising remains for the reader and the founder.
- Wording rule for the page's own strings: no "promising", "hopeful", "needs funding", "should be studied", "most", "best", "priority". Quoted rubric text is exempt (the level 5 meaning says "most of the Bradford Hill criteria").

## 2026-11-08 — Map gaps: links into the three new cards and out of the brain MRI card

- Eleven new links, from a second pair search (42 unlinked pairs with autonomic imbalance, circadian rhythm disruption or immune-cell gene expression) and a search of the brain MRI card's own studies for symptom links, checked by `card-reviewer` in map mode (run files in `data/pipeline/2026-11-08-map-gaps/`). Into the new cards: inherited genetic risk → immune-cell gene expression, infection → circadian rhythm, neuroinflammation → circadian rhythm, infection → autonomic imbalance, oxidative stress → autonomic imbalance (all step 1), autoimmunity → autonomic imbalance (step 2: β2 receptor antibodies correlated with the sympathovagal index in a Fukuda cohort; the patients did not differ from controls on the balance measures, and controls showed similar correlations, which the text says). Out of the brain MRI card, all step 2 from the card's own studies, all from one research group and uncorrected for the many correlations: breathing difficulty, cognitive impairment (self-ratings), sleep disturbance, and pain (no direction given, because the studies disagree; one null study cited). Also oxidative stress → sleep disturbance (step 1, retargeted from the circadian card because the source names sleep). Each new source is a `context` study; levels are unchanged. Rejected by the reviewer: immune-cell gene expression → NK cells (inside the NK card's scope), autonomic imbalance → energy production (single exercise test), oxidative stress → immune-cell gene expression (cell lines). Left out before review: endothelial dysfunction → circadian rhythm (founder ruling on the circadian card: no endothelial link now).

## 2026-11-08 — Circadian card: Rahman 2011 verified from its PMC page

- First use of the free-to-read PMC page rule (entry below): Rahman 2011 (pmid:21532961) is recorded as Fukuda from its PMC page ("international diagnostic criteria for CFS" with reference 1, the Fukuda 1994 definition) and is now `contradicts` on `drafts/circadian-rhythm-disruption.yaml`. Level 2 and "not contested" are unchanged: Fukuda ranks below the ICC of the level 2 study, and 15 patients are below half of its up to 94. The card now also states the authors' limits: patients recruited at the start of a graded-activity cognitive-behavioural therapy programme, possibly motivated to change activity-rest patterns, a sample that may not be representative, results to be repeated in a larger sample. Founder request 2026-11-08 ("Oppdater Rahman 2011 når PR 30 er flettet inn").

## 2026-11-08 — Free-to-read PMC article pages as a full-text source

- When Europe PMC has no open-access full text for a PMID that a card or draft cites, and its lookup shows the article is in PubMed Central (`inPMC` "Y"), the article page on pmc.ncbi.nlm.nih.gov may be fetched with `uv run python -m me_atlas.europepmc pmcpage --card <card> <pmid>`: on demand, only for PMIDs on that card, never in bulk, never from a publisher site. The page is cached like other full text and used only to find and check the case-definition sentence (C5) and sample sizes (C6); on the card it counts as `case_definition_source: fulltext`. Why: some articles are free for anyone to read on PMC but are not in the open-access subset, so neither Europe PMC's API nor NCBI EFetch gives their text (example: Rahman 2011, pmid:21532961); one cited article at a time, cached once, is reading, not crawling, and the sentence is still checked mechanically against a cached copy. Plan and contract: `docs/plan-pmc-free-fulltext.md`. Amends the open-access-only rule of 2026-11-01 for this case only.

## 2026-11-08 — New hypothesis: disrupted daily (circadian) rhythms

- New draft card `drafts/circadian-rhythm-disruption.yaml` (20th hypothesis), the third survey candidate drafted. Founder ruling on the drafter's recommendations after two `card-reviewer` rounds (run files in `data/pipeline/2026-11-08-circadian/`): level 2 (Cambras 2026, ICC, 100 patients and 56 controls, actigraphy in up to 94 and 53: less light exposure, lower and more fragmented activity and a more fragmented wrist temperature rhythm; unadjusted for age and body mass index, which the card states); not contested (no contradicting study with ICC, CCC or IOM 2015 and at least 47 patients); both badges no; no long COVID label; layer `dysfunction`; links to sleep disturbance (associated, minimal: one exploratory comparison), cognitive impairment (proposed) and the open question "What keeps the illness going" (proposed, for the mechanism reading). Rung 3 not met: the other verified studies come from the same Barcelona group, partly with reused data. Boundary: the card is about the timing system (activity, temperature, melatonin, light, sleep-wake timing); the cortisol rhythm stays on `hpa-axis-cortisol`, blood pressure and heart-rate rhythms on `autonomic-imbalance`, sleep quality is a symptom. "Circadian Rhythm" moved from the `nervous_system` survey domain to this card's theme.
- When an abstract and the full-text tables disagree, the card follows the tables and says so in the text. Why: two studies on this card (29874259, 36902264) report the opposite direction in the abstract; the first was at first proposed as the level 2 study from its abstract.
- A study's `role` follows its bearing on the card's level; when the same study found no relation for a link, the link text says so (36902264 stays `supports` and is named as a null in the sleep link). Why: recording it as `context` would hide its contribution to the level, and spec section 3 asks above all that the null is visible.
- The NPAS2 study (pmid:21912186, one of 65 nominal hits among 116,204 variants, unverified definition) is left out here, as on the inherited genetic risk card. No early signals: the remaining candidate (pmid:12213500, activity rhythm after a maximal exercise test) has an unverified case definition (spec section 4), so it is `context`.
- Next check that could move the level: Tryon 2004 (pmid:15451649) has no open full text. If a person reads it and finds a recognised definition and the same measure as the 2026 study, it would be the earlier original and the 2026 study an independent repeat (rung 3).

## 2026-11-08 — New hypothesis: altered gene expression in blood immune cells

- New draft card `drafts/immune-cell-gene-expression.yaml` (19th hypothesis), the second survey candidate drafted. Founder ruling on the drafter's recommendations after two `card-reviewer` rounds (run files in the drafting worktree's `data/pipeline/2026-11-08-immune-genes/`): level 2; contested at rung 2; both badges no; long COVID label; layer dysfunction; one proposed link to the post-exertional malaise symptom node.
- Level 2, not 3: three controlled CCC studies from three groups and two CDC studies from a fourth find altered expression, but each points to different genes and pathways (T-cell activation, inflammation, lower interferon and immunoglobulin genes, T-cell exhaustion). "Some immune genes differ" does not count as the finding an independent group must reproduce. The exhaustion reading is contradicted on the card itself (fewer estimated exhausted CD8 cells in pmid:39435656; no exhaustion signature in the re-analysis pmid:41822518).
- Contested at rung 2: pmid:28172519 (CCC, 25 and 25, no differentially expressed genes) and pmid:21479222 (Fukuda, 64 and 64, no difference in the earlier genes) together are of comparable quality to every study rung 2 rests on. Whole blood against mononuclear cells is stated, not graded (not a rubric criterion).
- Diagnostic marker no: the ESRRA check in pmid:39394558 used a public dataset whose own paper states no case definition; a definition is not carried across from another paper on the same cohort.
- Layer dysfunction, not mechanism: the card measures a pattern in blood; exhaustion "maintained by chronic stimulation" is the authors' unreplicated reading. No incoming link from herpesvirus reactivation: the source names only "chronic viral infections" in general.

## 2026-11-08 — New hypothesis: autonomic nervous system imbalance

- New draft card `drafts/autonomic-imbalance.yaml` (18th hypothesis), the first survey candidate drafted (see the entry below). Founder ruling on the drafter's proposal after two `card-reviewer` rounds (run files in `data/pipeline/2026-11-08-autonomic/`): level 3 (lower high-frequency heart rate variability at rest in a Fukuda study of 68 patients and 68 controls, found again later by two other groups in separate cohorts, Fukuda and Fukuda/CCC/IOM 2015); contested at rung 3 (Duprez 1998, Holmes, 38 against 38, found no major change in RR-interval variability; rung 2 rests on the stricter definition and is not contested); both badges no; layer `dysfunction`; three step-1 links (sleep disturbance, cognitive impairment, orthostatic intolerance and cerebral blood flow). Boundary: this card is about autonomic tone itself (heart rate variability, resting heart rate, baroreflex, catecholamines); the orthostatic card keeps the fall in brain blood flow on standing.

## 2026-11-08 — First survey run: candidates to draft and eleven new links

- Census of 21 headings (top three of each survey domain): 46 candidate hypotheses and 40 gaps on existing cards, recorded in `docs/pm/candidates.md` (abstract level only). XMRV came up again under "DNA, Viral" and is marked declined (refuted, see the ruling below).
- To draft, one card at a time through the manual process: autonomic nervous system imbalance (reduced vagal tone, raised sympathetic activity; to be set apart from the orthostatic intolerance card), altered immune-cell gene expression in blood mononuclear cells (exhaustion or chronic activation), and disrupted circadian rhythms. Why: among the candidates not on an existing card, the ones whose abstracts carry the inclusion rule with a recognised case definition (IOM 2015, CCC, Fukuda); the two "Affect" candidates were not chosen (mood may be a reaction to illness; one study for serotonergic signalling).
- Eleven new links, from the pair search (53 unlinked pairs: the 20 with most core matches and every pair with brain MRI, endothelial dysfunction, NK cells or tryptophan), checked by `card-reviewer` in map mode: energy production → neuroinflammation, endothelial dysfunction → orthostatic intolerance, NK cells → autoimmunity, NK cells → herpesvirus, tryptophan → neuroinflammation, tryptophan → oxidative stress, oxidative stress → endothelial dysfunction, oxidative stress → HPA axis, herpesvirus → endothelial dysfunction, infection → autoimmunity, all step 1 (proposed); autoimmunity → HPA axis, step 2 (associated). Each source is added to its card as a `context` study; levels are unchanged. Five proposals were rejected by the reviewer (wrong target or no stated link). Run files: `data/pipeline/2026-11-08-survey/`.
- Autoimmunity → HPA axis rests on antipituitary and antihypothalamic antibodies (pmid:34254637), outside the receptor scope of the autoimmunity card's studies. The founder accepted the link; the card's claim, scope and level are unchanged, and a comment on the card says so.

## 2026-11-08 — Hypothesis and link survey of the cached literature

- Grow the content from the ME/CFS literature already fetched before looking anywhere else: a theme census for MeSH headings no card covers, and a pair search for records that mention two cards. Code counts, an agent (`hypothesis-surveyor`) reads only the records the code selected, the founder decides. Candidates are tracked in `docs/pm/candidates.md`; v1 stays at 15 to 20 cards. Plan: `docs/plan-hypothesis-and-link-survey.md`; reference: `docs/survey.md`. Sources outside the ME/CFS literature wait for a separate ruling. Why: the whole PubMed query is cached but only the weekly window was ever read, and four cards had no link.
- Balance: the census is read per domain (the top three headings of each of seven mechanism areas, psychological and behavioural models included, with the same number of places as the others), not by raw count. Headings close to a card are marked "near" that card instead of hidden; pairs are ranked by core matches (the card's heading is a major topic, or its term is in the title). Why: raw counts were led by comorbid diagnoses and older psychiatric headings, and broad headings inflated pair counts.
- "Adaptation, Psychological" (coping) is a reaction to the illness, not a causal model: it is not surveyed (domain `reaction_to_illness`).
- Refuted hypotheses get no card and are not surveyed; each is named, with the reason and its sources, in `docs/pm/excluded-hypotheses.md`. First case: XMRV (the 2009 study is retracted; blinded multi-site studies found no association). Its census headings are in the domain `refuted`. Why: the founder's ruling; a reader should still be able to see that it was left out and why.

## 2026-11-06 — New hypothesis: infection as a trigger

- New draft card `drafts/infection-trigger.yaml` (17th hypothesis), added at the founder's request because the causal map's trigger layer held no card: herpesvirus and enterovirus sit in the mechanism layer as reactivation and persistence. Founder ruling on the drafter's proposal after two `card-reviewer` rounds (run files in `data/pipeline/2026-11-06-infection-trigger/`): level 2 (RECOVER-Adult, IOM 2015 from self-reported symptoms, ME/CFS more frequent after SARS-CoV-2 than in matched uninfected people); not contested (INSPIRE compared SARS-CoV-2 with other acute illness, not with no infection, and measured fewer than half as many); both badges no; long COVID label; layer trigger; one proposed link to the open question on who is vulnerable. The older post-infection cohorts (glandular fever, Q fever, Ross River virus) have no verifiable case definition and do not count.
- The trigger open question now reads "What starts ME/CFS?" (id `what-starts-it`); the old wording assumed infection was already covered.

## 2026-11-06 — Drawn causal map

- The defaults in `docs/plan-drawn-map.md` are accepted ("we adjust when we see the result"): bands from predisposition at the top to symptoms at the bottom, evidence level and contested mark in each card box, line style carries the link step, unlinked symptoms muted, on phones a neighbourhood drawing per card with the whole map behind "Show the whole map".
- The whole map is an overview: 12 px text and smaller boxes, scaled down to fit the screen width from 40em (founder ruling 2026-11-06, "too big to get an overview even on a large PC screen"). The 16 px minimum for text still holds everywhere else, including the neighbourhood drawings and the lists.
- Pointing at or focusing a box dims everything not on its chain: the box, everything it leads to and everything that leads to it, at any depth, and the links between them (founder request). Why: with 23 links the whole drawing is too dense to follow one chain by eye.

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
