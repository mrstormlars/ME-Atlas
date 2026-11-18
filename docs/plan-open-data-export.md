# Plan: open data and citation export (idea I-05)

Idea I-05 in `docs/pm/IDEAS.md`. Guidelines for ideas: DECISIONS 2026-11-17 ("Idea bank"). Branch `feat/open-data-export`, one pull request, the founder merges.

## What the cards hold

Every study on a card has `id` (today always `pmid:<digits>`; the format also allows `doi:10.<rest>`), `title` and `year`, copied from the fetched record (credibility rule 1). The cards hold no authors, no journal, no volume, issue or pages, and no DOI next to a PMID. No study is a preprint today. The exports carry only these fields; nothing is looked up, and the build needs no cache. Adding authors and journal would be a change to the card format and to `cards/`, which this change does not make.

## Contract

Done means every clause holds.

### Dataset

D1. `uv run python -m me_atlas.site build` writes a folder `data/` at the top of the output directory (shared by both languages, like `static/`) with: `me-atlas.json`, `hypotheses.csv`, `studies.csv`, `links.csv`, `card-format.md` and `README.txt`.

D2. Everything in `data/` is derived by code from the cards the build shows and from the map content (`content/symptoms.yaml`, `content/open-questions.yaml`); `card-format.md` is a byte copy of `docs/card-format.md`. No text is written about any card. The files do not depend on `data/cache/`.

D3. `me-atlas.json` holds: a `dataset` block (title, build date as the version, site URL, repository URL, licence `CC-BY-4.0` with its URL, a note that article titles and quoted sentences stay with their rights holders, the citation text, the language note of D6, the statement that no medical or research expert has reviewed the content, and `counts`); `cards` (each card as the card model serialises it, every field of `docs/card-format.md`); `symptoms` and `questions` (id and English name or text).

D4. `hypotheses.csv` has one row per card (slug, name, level, layer, contested rungs, the two badge values, number of supporting, contradicting and other studies, number of links out, long COVID label); `studies.csv` one row per study per card (card slug and every study field of `docs/card-format.md`); `links.csv` one row per link (source slug, target, target kind card/symptom/question, target name, support, text, sources). Lists inside a cell are joined with `; `. CSV is UTF-8, RFC 4180 quoting, with a header row.

D5. `counts` in the JSON gives `cards`, `study_rows` (studies summed over cards), `distinct_studies` (distinct ids) and `links`. They equal the row counts of the CSV files, and `cards` and `links` equal what the gaps page of the same build shows (a test builds the fixture site and compares).

D6. The dataset is English only. English is authoritative; the Norwegian translations are in the repository under `translations/nb/` and are not part of the download. The JSON `dataset` block, `README.txt` and the data page say so.

D7. `README.txt` gives the build date, the licence, how to cite, the file list with one line per file, and points to `card-format.md` for the meaning of every field (no second field definition).

D8. A `--drafts` build marks the dataset as a draft preview in `me-atlas.json` (`"draft_preview": true`) and in `README.txt`; a public build has `"draft_preview": false`.

### Citation export

C1. For every card the build writes `data/citations/<slug>.bib` and `data/citations/<slug>.ris`, one entry per study on the card, in card order.

C2. BibTeX: `@misc` entries keyed by the study id with `:` replaced (`pmid12345678`), with `title`, `year`, `url` (the same URL the card page links), `note = {PMID: …}` for a `pmid:` id and `doi = {…}` for a `doi:` id. BibTeX special characters in titles (`{ } % & $ # _ ~ ^ \`) are escaped so that the file parses. No `author` or `journal` field is written.

C3. RIS: one record per study, `TY  - JOUR` (or `TY  - UNPB` for a study with `preprint: true`), `TI`, `PY`, `UR`, `AN  - PMID:<digits>` for a pmid or `DO  - <doi>` for a doi, ending with `ER  - `. Lines end with CRLF as the RIS specification requires.

C4. Each card page, in both languages, links to its two files under the studies heading (relative links that work from `file://`) and to the data page.

C5. A test parses one generated `.bib` with a small reader in the test (balanced braces, one entry per study, the expected keys and fields) and one `.ris` (every record starts with `TY`, ends with `ER`, tags are two characters followed by two spaces, a hyphen and a space). A title holding `{`, `%` and `&` in a fixture card is escaped in the `.bib` output (the negative input). In addition the worker or the evaluator parses one built `.bib` with `bibtexparser` through `uv run --with bibtexparser` (not a project dependency) and states the result.

### Data page

P1. A new page `data.html` (English) and `nb/data.html` (Norwegian), "Download the data", lists every file of D1 and C1 (the citation files as one line per card), says what the dataset is and is not (derived from the cards, English only, no expert review, describes and gives no treatment advice), gives the licence and the citation text, and links `card-format.md` for the fields.

P2. Every page's footer links to the data page (one new string). The page is not added to the main navigation.

P3. All new site text is keys in `content/i18n/en.yaml` and `nb.yaml`; the build's string checks pass and `uv run python -m me_atlas.translations check` reports no stale item.

P4. Neither the data page, `README.txt`, `me-atlas.json` nor `CITATION.cff` contains a DOI for the dataset or the word "Zenodo" (a test checks the built data page and data files for `10.5281` and `zenodo`, case-insensitive).

### DOI preparation

Z1. `CITATION.cff` at the repository root (CFF 1.2.0): title, authors as the entity "ME Atlas contributors", repository URL, site URL, licence, abstract taken from the site's lead text, no `doi`. `cffconvert` or a test reads it as valid YAML with the required keys `cff-version`, `message`, `title`, `authors`.

Z2. No `.zenodo.json`: Zenodo's GitHub integration reads `CITATION.cff` when no `.zenodo.json` exists, so one file is enough.

Z3. No account is created and nothing is published outside the repository.

### Scope and docs

S1. No change to `cards/`, `drafts/`, `translations/` or `audits/`. No new dependency. No JavaScript needed for any of it.

S2. `docs/site.md` describes the data folder, the citation files, the data page and the footer link. `docs/pm/IDEAS.md` sets I-05 to `in progress`. `docs/pm/STATUS.md` priority 1 replaces "I-05 waits for the founder's licence choice" with the actual state.

S3. The English golden tree (`tests/fixtures/site_en_golden`) is updated only by the lines this change adds.

### Verification scope

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python -m me_atlas.cards validate
uv run python -m me_atlas.translations check
uv run python -m me_atlas.site build --out <scratch dir>
uv run --with bibtexparser python -c "<parse one built .bib>"
```

## Steps

1. Export module: a new `src/me_atlas/export.py` that turns the cards and map content into the JSON, the three CSV files, the README text and the per-card BibTeX and RIS text. Pure functions, no file system access except through arguments.
2. Build: `site.build` calls it after the pages are rendered and writes `data/` next to `static/`; the path of `docs/card-format.md` is a build argument with a package-relative default, as `content_dir` is.
3. Page and links: the `data.html` template, the footer string, the two links under the studies heading of the card page, the strings in both languages.
4. `CITATION.cff`.
5. Tests: export functions against fixture cards (including the escaping case), the built tree (files exist, links resolve, counts equal the gaps page), the no-DOI check, `CITATION.cff` keys. Update the golden tree.
6. Docs: `docs/site.md`, IDEAS, STATUS.

## Founder's steps for a DOI (done 2026-11-18: release `v2026.11.18`, concept DOI 10.5281/zenodo.24333249, version DOI 10.5281/zenodo.24333250)

1. Create an account at <https://zenodo.org> by logging in with GitHub (the `mrstormlars` account).
2. In Zenodo, under "GitHub", switch on the repository `mrstormlars/ME-Atlas`.
3. On GitHub, make a release of `main` (for example tag `v2026.11.17`). Zenodo archives the release, reads `CITATION.cff` for the metadata and mints two DOIs: one for this version and one "concept" DOI for all versions.
4. Check the Zenodo record (title, authors, licence). The archive is the repository at that release: the cards are the source data; the built `data/` folder is not in it (it is generated at build time).
5. Tell an orchestrator session the concept DOI. A follow-up change then adds `doi` to `CITATION.cff` and the DOI to the data page and the citation text, and removes the no-DOI test.

Each later release gets its own version DOI automatically.

## Left out

- Authors, journal and DOI next to a PMID in the citation files: the cards do not hold them (card format change, not this idea).
- A Norwegian dataset (D6).
- One combined `.bib` of all cards.
- A DOI (founder's steps above).
