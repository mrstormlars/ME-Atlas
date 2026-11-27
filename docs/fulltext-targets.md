# Full-text targets

`uv run python -m me_atlas.fulltext needs` lists the studies on the cards whose full text, once read, could settle a case definition, a sample size or a measurement that a card now rests on without it. It is offline: it reads `cards/*.yaml` (not `changelog.yaml`), `config/fulltext_named.yaml` and the cache, and makes no request. It changes nothing; a card changes only through the pipeline.

```bash
uv run python -m me_atlas.fulltext needs [--markdown] [--cards-dir cards] [--config config/fulltext_named.yaml] [--cache-dir data/cache]
```

Exit code 0 when there is no error. It is 1 when a card fails to load (the file name is printed; the other cards are still listed), when a cached file cannot be read, when the config file is malformed, or when a named entry names a card that does not exist or a study that is not on that card.

## Categories

A study is listed in the first category that applies.

- `carrying`: the role is `supports`, `contradicts` or `early_signal`, and either `case_definition_source` is `abstract` or no full text is cached (status other than `fulltext_xml` or `pmc_page`). The reason says which applies, or both.
- `unverified`: the role is `context`, `case_definition` is `unverified`, `design` is not `other`, and the study is not a preprint and has no `corrects`. The reason names the rung a verified definition could count towards: `uncontrolled` level 1; `controlled` level 2-3 and the contested mark; `intervention_controlled` level 4; plus the `explains_pem` badge when `measures_pem` is true.
- `named`: a study named in the config file by id that falls in neither category above. It is listed anyway.

Every other study (a context review with `design: other`, or a carrying study whose definition was read from the full text and whose full text is cached) is not listed; it is counted ("Not listed").

The config file `config/fulltext_named.yaml` holds the items named in `docs/pm/STATUS.md` under "Content that could change a card when a source becomes available": a list `named:` of `{card, study, note}`. A listed study that matches an entry is marked `named in STATUS.md` with the note. `study: null` marks every listed study of that card. An entry for a study in neither category adds it to the list as `named`; a `null` entry never adds one.

## Status

Computed only from the cache. The PMC id is chosen as `citations check` chooses it: the Europe PMC lookup first, else the cached PubMed record; a `doi:` preprint takes it from the cached preprint record.

| Status | Meaning | Next step |
| --- | --- | --- |
| `fulltext_xml` | `<pmcid>.xml` is cached and is real full text | already cached; read with `europepmc casedef` |
| `pmc_page` | `<pmcid>.html` is cached (a page saved by hand or fetched) | same |
| `pdf_placeholder` | the cached XML is a placeholder (no body, or a note that it is a PDF) and no page is cached | not free on PMC |
| `open_access_not_cached` | the lookup says open access; the XML is not cached | `uv run python -m me_atlas.europepmc fulltext <pmid>` (`preprint <doi> --fulltext` for a preprint) |
| `free_on_pmc` | a PMC id is known, it is not open access, and the lookup says `inPMC` Y or the id comes from the PubMed record; no page cached | save the page by hand, then `import-saved` (`docs/fetch.md`, "Full texts saved by hand") |
| `pmc_id_not_in_pmc` | a PMC id is known, `inPMC` is not Y, nothing cached | not free on PMC |
| `no_pmc_id` | a lookup is cached and no PMC id is anywhere | not free on PMC |
| `no_lookup` | no cached lookup and no PMC id from PubMed (or a `doi:` study with no cached preprint record) | `europepmc fulltext <pmid>` |

The statuses `pdf_only` and `pmc_no_xml` that `europepmc fulltext` can report are not stored in the cache, so this command cannot know them and never prints them. A study that got one of them on its last fetch shows as `no_lookup`, `open_access_not_cached` or `pdf_placeholder` depending on what was left in the cache.

## Output

Grouped by card (slug order, studies in card order). Per study: the card, the study id, the role, the case definition and its source, the category and reason, what full text would settle (the case-definition sentence when unverified or read from the abstract; `n_patients` or `n_controls` when null; for `contradicts`, the patient count in the contradicting measurement; the PEM measurement when `measures_pem`), the status, the next step, and the addresses (the PMC article when a PMC id is known, the PubMed record for a `pmid:` study, `https://doi.org/<doi>` when the study has a `doi`). Then a summary: the count per category, the count per status among the listed studies, and "Not listed". `--markdown` prints the same as a table per card and a summary table.

## Reading the listed full texts

`scan-plan` and `scan-record` read the listed studies that have a cached full text (`fulltext_xml` or `pmc_page`) against their cards, offline, and write a result and draft correction requests into a run folder: `docs/pipeline.md`, "Full-text scan".

## Storing a page saved by hand

`import-saved --card <card.yaml> --pmid <digits> [--cache-dir data/cache] [--saved-dir data/hand-saved/fulltext]`: see `docs/fetch.md`, "Full texts saved by hand".
