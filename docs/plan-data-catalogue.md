# Plan: catalogue of ME/CFS data resources (idea I-14)

Agreed with the founder in a brainstorm on 2026-11-18. Follows the seven guidelines for ideas (DECISIONS 2026-11-17, "Idea bank"). To be handed to `/orchestrator`.

> Later change (founder ruling 2026-11-18): `operator` and `countries` are no longer part of an entry, the reviewer judges each value on its own and reliability is counted per value. This plan keeps its original text as history; the rules now in force are in `docs/ME-Atlas-functional-spec.md` ("Data resources") and `docs/pipeline.md`.

## Why

ME/CFS datasets, registries and biobanks exist but are scattered. A researcher who wants to test a gap needs to know which data can be had and how. The site describes and links; it holds no patient data.

## Founder rulings in the brainstorm

1. **Inclusion rule.** A resource is in the catalogue when (a) it holds data or samples from people with ME/CFS, (b) researchers outside the owning group can get access, and (c) it has a public page that says how. Registers of research projects, groups or publications (for example the ME/CFS Research Register in Hamburg) are also included, as a separate category, when they have a public page.
2. **Long COVID.** ME/CFS resources first, plus resources that expressly cover both ME/CFS and long COVID. Resources for long COVID alone are out.
3. **No link from a resource to a hypothesis** in this round.
4. **A resource with no verifiable source page is not shown** (not listed as "unconfirmed").

## Goal

A page on the site lists the data resources as tables, with every value backed by a quote from a stored copy of the resource's own page. No sentence about a resource is written for the site.

## Source rule for data resources (new source type)

To be written into `docs/ME-Atlas-functional-spec.md` and the methods text, in these terms:

- The source of an entry is the resource's own public page, or a PubMed / Europe PMC record that describes the resource. The fetched page is stored in `data/cache/` with its URL and fetch date; a PubMed record goes through the existing fetch.
- An entry has only fixed-value fields, a name, an operator, countries and links. Every fixed-value field carries the quote from the stored page that supports it. A field the page does not state gets the value "not stated"; it is never filled from model knowledge or from the candidate list in `docs/pm/IDEAS.md`, which is a list of leads only.
- An AI agent proposes the values and quotes; the review agent checks each quote against the stored page (the quote must be found in it by a mechanical check, and must support the value). A rejected entry is not published.
- A resource is not evidence and changes nothing on a card. The page recommends nothing, and does not invite anyone to take part in or sign up to a resource.

## Design

1. **Candidates.** Start from the nine leads in `docs/pm/IDEAS.md` ("Existing data banks"). The orchestrator may add leads found by web search, at most about twenty entries in all; each lead still has to pass the inclusion rule on its own page.
2. **Fetch.** A small fetch step stores each candidate's page (and the access page, when it is a separate one): raw response in `data/cache/`, a text extraction for the agents. It sends a generic client name, respects robots rules, and does not work around a bot check or a login; a page that cannot be fetched means the entry is not shown, and the report names it.
3. **Published data file** in the repository (for example `registry/resources.yaml`), with a validator. One entry per resource:
   - `name`, `operator`, `countries`, `url`, `access_url` (optional), `checked` (date of the stored page);
   - `category`: `data` (data or samples) or `register` (research projects, groups, publications);
   - `holds`: any of `genotypes`, `questionnaires`, `biospecimens`, `molecular`, `clinical`, `sensor`, each with its quote; empty for a `register`;
   - `access`: one of `open_download`, `registration`, `application`, `not_stated`, with its quote;
   - `covers`: `me_cfs` or `me_cfs_and_long_covid`, with its quote;
   - `source`: the URL or the PubMed id the quotes come from.
4. **Agents.** A drafter subagent in `.claude/agents/` (new, or an existing one if its prompt fits; settle in the contract) reads the stored text and writes the entry as JSON for code to validate. The `card-reviewer` gets a mode for checking an entry against the stored text. No auditor.
5. **Reliability** (guideline 3): the reviewer may reject at most one entry in five. With so few entries the test is the whole set: if more than one in five is rejected, nothing is published and the session reports why, without tuning the prompt more than twice.
6. **The page** (`resources.html`, `nb/resources.html`):
   - Intro in the terms of the source rule: what the list is, that the site holds no patient data, that every value is taken from the resource's own page on the date shown, and that the list is not an invitation to take part.
   - Table 1, data and samples: name (link), operator, countries, what it holds, access, covers, date checked. Sorted by name.
   - Table 2, registers of research: name (link), operator, countries, date checked.
   - No ranking, no free text about a resource, no contact details. No JavaScript requirement.
   - Linked from the gaps page and the data page; the orchestrator settles whether it goes in the main navigation.
7. **Dataset** (I-05): the catalogue is added to the downloads as its own CSV and to `me-atlas.json`.
8. **Upkeep.** The weekly run gets a step in which code checks that each `url` and `access_url` still answers and reports the ones that do not; it changes no entry. Re-reading the content is a separate command the founder runs on request (about quarterly); it re-fetches, and only an entry whose stored page changed goes through the drafter and the reviewer again.
9. **Strings and Norwegian:** site strings and the fixed values in `content/i18n/en.yaml` and `nb.yaml` through the translation path. Names and operators are shown as the source gives them.
10. **Documents:** the source rule in the functional spec and the methods text (English and Norwegian), `docs/fetch.md`, `docs/site.md`, `docs/pipeline.md`, `docs/pm/IDEAS.md` (I-14; replace the "Existing data banks" notes with a pointer to the data file once it is published), `docs/pm/STATUS.md`.

## Done

- Every published entry passed the reviewer, and every quote in the data file is found in the stored page by the mechanical check.
- The reject share is at most one in five, and the numbers are in the pull request description; or nothing is published and the report says why.
- No entry is shown without a stored source page; the leads that were not published are named in the pull request description with the reason (failed the inclusion rule, page not fetchable, rejected).
- The page contains no sentence about a resource, and no wording that invites taking part or signing up.
- No file in `cards/`, `drafts/` or card content in `translations/nb/` changes.
- The numbers on the page and in the dataset agree.
- `uv run pytest` (offline, recorded pages in `tests/fixtures/`), `uv run ruff check .`, `cards validate` and `translations check` pass; the site builds in both languages.
- The `evaluator` returned PASS on the contract. One branch (`feat/data-catalogue`), one pull request; the founder merges.

## Out of scope

- Links from a resource to a hypothesis card.
- Resources for long COVID alone; general biobanks and repositories that are not ME/CFS resources.
- Per-study data deposits (idea I-18) and any reanalysis of data (idea I-13).
- Holding, downloading or redistributing any patient-level data.
- Free-text descriptions of a resource.

## Open points for the orchestrator to settle in the contract

- Whether a resource described only in a journal article (no page of its own that states access) meets clause (c) of the inclusion rule; the default is no.
- How a page in a language other than English is handled: the quote is kept in the original language, and the reviewer must be able to read it; otherwise the entry is not shown.
- Whether the page goes in the main navigation.
