# Evidence card format

Reference for the founder and for agents. The models live in `src/me_atlas/cards.py`; if this page and the code disagree, the code is right and this page is a bug.

## Files

| File | What it is |
| --- | --- |
| `cards/<slug>.yaml` | An approved evidence card, one per hypothesis. |
| `drafts/<slug>.yaml` | A proposed card, **same format**. The change is the diff against `cards/<slug>.yaml`. |
| `cards/changelog.yaml` | The public change log: one append-only list of entries. |

Check everything with:

```bash
uv run python -m me_atlas.cards validate            # cards/ and drafts/ in the current directory
uv run python -m me_atlas.cards validate path ...   # specific files or directories
```

It prints every error (file, field path, rule id) and exits non-zero if there is one. An empty `cards/` is valid.

## Sourced text

Every piece of free text is an object, never a bare string:

```yaml
text: One plain sentence.
sources: [pmid:00000001]
```

`sources` lists ids of studies in the same card's `studies` list.

### Paragraphs

The long reasons (`level_reason`, `contested.reason` and `badges.*.reason`) may be written either as one sourced text (above) or as a non-empty list of them, one per paragraph, so a reader can see which sentence rests on which study. An empty list is not allowed. The site shows each paragraph as its own paragraph with its own numbered references.

```yaml
level_reason:
  - text: A fictional controlled study found a difference in widget signalling.
    sources: [pmid:00000001]
  - text: A second fictional study found the same difference in a separate cohort.
    sources: [pmid:00000002]
```

The rules apply per paragraph: every source must be in `studies` (V3) and every paragraph needs at least one source (V4; at level 0 none is needed in `level_reason`). V8 looks at all paragraphs of `contested.reason` together: one `contradicts` study in any paragraph is enough. Error paths name the paragraph, for example `level_reason[1].sources`. `core_claim`, `subgroups` and `early_signals` stay single sourced texts.

## Card fields

| Field | Meaning |
| --- | --- |
| `slug` | Lower-case words joined by hyphens. Must equal the file name without `.yaml`. |
| `name` | Display name of the hypothesis. |
| `core_claim` | Sourced text: what the hypothesis says. |
| `level` | Integer 0-5, the rung on the evidence ladder (functional spec section 3). |
| `level_reason` | Sourced text, or a list of them (paragraphs): why the card is at this level. |
| `contested` | `null`, or `rungs` (list of rung numbers under dispute) and `reason` (sourced text, or a list of them). |
| `badges.diagnostic_marker`, `badges.explains_pem` | Each `value` (true/false) and `reason` (sourced text, a list of them, or `null`). |
| `subgroups` | List of sourced text. |
| `working_on_it` | List of `name` and `url` (research groups, funders). |
| `early_signals` | List of sourced text. Unreplicated findings only. |
| `studies` | List of studies (below). |
| `last_checked` | `date` and `by` (`ai_pair` or `founder`). |

Unknown fields are errors. `level`, the numbers in `contested.rungs` and the change-log `tier` must be whole numbers: `true` and `2.0` are rejected (V1).

## Study fields

| Field | Values |
| --- | --- |
| `id` | `pmid:<digits>` or `doi:10.<rest>` |
| `title`, `year` | As in the fetched record. |
| `cohort` | `me_cfs` or `long_covid` |
| `case_definition` | `CCC`, `ICC`, `IOM2015`, `Fukuda`, `Holmes1988`, `CDC_unspecified`, `Oxford`, `other`, `none`, `unverified` (see below) |
| `case_definition_source` | `abstract`, `fulltext`, or `null` (only while `unverified`) |
| `case_definition_quote` | The verbatim sentence from that source that states the case definition, or `null` |
| `design` | `controlled`, `uncontrolled`, `intervention_controlled`, `other` |
| `n_patients`, `n_controls` | Whole number, or `null` if not applicable or not stated. |
| `measures_pem` | true if the study measures post-exertional malaise directly. |
| `preregistered` | true, false, or `null` if unknown. |
| `role` | `supports`, `contradicts`, `early_signal`, `context` |
| `direction` | `lower`, `higher`, `no_difference`, `mixed`, `not_applicable`: patients compared with controls, on the card's measure. Required for every role, so a background study still shows which way it points. Use `not_applicable` when the source gives no patient-control comparison. |
| `finding` | One neutral sentence: "A study of n=... found ...". |
| `group` | Optional. A short label for the research group, taken from the fetched record (for example the last author and institution as PubMed gives them), or `null`/omitted. Not validated beyond being non-empty when present. Meant for the "independent group" test at level 3. |

All of these are required except `group`; use `null` where the value is allowed to be unknown.

### Case definition provenance (format v2)

- `unverified` means the case definition has not been checked yet (for example the abstract does not state it and the full text has not been read). Both `case_definition_source` and `case_definition_quote` must be `null`.
- `none` means the source was checked and states no case definition. It needs a `case_definition_source` (where it was checked).
- Every other value needs a `case_definition_source`. The named definitions (`CCC`, `ICC`, `IOM2015`, `Fukuda`, `Holmes1988`, `CDC_unspecified`, `Oxford`) also need a non-empty `case_definition_quote`: the verbatim sentence, so a reader can check it. `other` may leave the quote `null`.
- `Holmes1988` is the 1988 CDC definition. It is accepted like `Fukuda` (counts at every rung), is flagged on the card as "does not require PEM", and ranks equal to `Fukuda` in the comparable-quality rule.
- `CDC_unspecified` is for a study that cites "CDC criteria" without naming the version. It is treated exactly like `Fukuda` and `Holmes1988`: counts at every rung, flagged "does not require PEM", ranked equal to `Fukuda`. The quote is the sentence that names the CDC criteria.
- To find the sentence, `uv run python -m me_atlas.europepmc casedef <pmid>...` shows candidate sentences from open-access full text. It only suggests; the person or agent drafting the card decides which definition a sentence means.

## Change log entries

`date`, `card` (slug of a file in `cards/`), `change`, `reason` (one line), `sources` (study ids) and `tier` (1, 2 or 3, see functional spec section 6).

## Derived, not stored

- **Long COVID label:** shown when any cited study has `cohort: long_covid`.
- **Hatched segment on the bar:** the rungs listed in `contested.rungs`.
- **Ranking:** from `level`.

## Rules the validator enforces

| Rule | In plain English |
| --- | --- |
| V1 | Right types, allowed values, required fields present. `level` must be 0-5. |
| V2 | `slug` equals the file name. |
| V3 | Every source id used in any sourced text (every paragraph) is in the card's `studies`. |
| V4 | Every sourced text, and every paragraph of a reason written as a list, has at least one source, except `level_reason` at level 0. |
| V5 | Level 2 or higher needs a `supports` study with design `controlled` or `intervention_controlled` and case definition CCC, ICC, IOM2015, Fukuda, Holmes1988 or CDC_unspecified. Oxford-only evidence therefore stops at level 1. |
| V6 | Level 4 or higher needs a `supports` study with design `intervention_controlled`. |
| V7 | `explains_pem: true` needs the badge's `reason` to cite a `supports` study that has `measures_pem: true` and meets the V5 design and case-definition test. |
| V8 | `contested` needs its `reason` (all paragraphs together) to cite at least one `contradicts` study, and every rung lies between 1 and `level`. |
| V9 | A study with `case_definition: none` or `unverified` cannot have role `supports` or `contradicts`. |
| V10 | `core_claim` and `early_signals` contain none of: promising, breakthrough, cure, hope, proven (whole words, any case; plain plural and past forms such as "cured" and "hopeful" count). |
| V11 | Change log: `card` exists in `cards/`, `tier` is 1-3, the date is not in the future. |
| V12 | Study ids are unique within a card; a repeated id is reported on its second occurrence. |
| V13 | Case definition provenance: `unverified` has `null` source and quote; every other value has a source; the named definitions (CCC, ICC, IOM2015, Fukuda, Holmes1988, CDC_unspecified, Oxford) also have a quote. |

The validator reports all errors it finds in a file. If the file fails V1 (schema), the cross-field rules V2-V10, V12 and V13 are not checked until the schema errors are fixed. It also reports `YAML` (file does not parse) and `IO` (path missing or unreadable).

What it does not check: that titles, years, sample sizes and case definitions match the PubMed record (a later task, needs the fetch script), that the level is right for the evidence, or that a founder approved a change.

## Fictional example

Every id, title and result below is invented. The full version is `tests/fixtures/cards/fictional-hypothesis.yaml`.

```yaml
slug: fictional-hypothesis
name: Fictional hypothesis about widget signalling
core_claim:
  text: The fictional hypothesis proposes that widget signalling is altered in patients.
  sources: [pmid:00000001]
level: 2
level_reason:
  text: A fictional controlled study supports the hypothesis.
  sources: [pmid:00000001]
contested: null
badges:
  diagnostic_marker: {value: false, reason: null}
  explains_pem: {value: false, reason: null}
subgroups: []
working_on_it:
  - name: Fictional Research Group
    url: https://example.org/fictional-group
early_signals:
  - text: A fictional small uncontrolled study reported a related change, not yet replicated.
    sources: [pmid:00000004]
studies:
  - id: pmid:00000001
    title: Fictional study of widget signalling in a controlled cohort
    year: 2001
    cohort: me_cfs
    case_definition: CCC
    case_definition_source: abstract
    case_definition_quote: Fictional participants met the Canadian Consensus Criteria.
    design: controlled
    n_patients: 40
    n_controls: 40
    measures_pem: false
    preregistered: true
    role: supports
    direction: lower
    finding: A study of n=40 patients and 40 controls found a fictional difference in widget signalling.
  - id: pmid:00000004
    title: Fictional small uncontrolled study in a long COVID cohort
    year: 2004
    cohort: long_covid
    case_definition: other
    case_definition_source: abstract
    case_definition_quote: null
    design: uncontrolled
    n_patients: 12
    n_controls: null
    measures_pem: false
    preregistered: null
    role: early_signal
    direction: mixed
    finding: A study of n=12 patients found a fictional related change.
last_checked:
  date: 2026-10-01
  by: ai_pair
```

Change log entry:

```yaml
- date: 2026-10-01
  card: fictional-hypothesis
  change: Added a fictional study to the card.
  reason: A fictional new paper met the criteria.
  sources: [pmid:00000004]
  tier: 1
```
