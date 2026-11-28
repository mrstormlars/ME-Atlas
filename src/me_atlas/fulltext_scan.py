"""The full-text scan of published cards: step 0 (code compares case definitions) and step 1 (a scan agent per study).

Plan: ``docs/plan-fulltext-recheck.md``; commands in ``me_atlas.fulltext`` (``scan-plan``, ``scan-record``),
described in
``docs/pipeline.md``, "Full-text scan". Everything is offline and writes only into the run folder ``RUN``::

    RUN/step0.json                         step 0: a label per study and the candidate sentences     (``scan-plan``)
    RUN/scan-plan.json                     run id, date, each card's sha256, the studies and their files (``scan-plan``)
    RUN/scan-context/<slug>--<id>.md       the one file the scan agent reads                         (``scan-plan``)
    RUN/scan/<slug>--<id>.json             the scan agent's verdicts                                  (the agent)
    RUN/scan-result.json                   the validated result, with the flagged cards              (``scan-record``)
    RUN/scan-report.md                     counts and, per flagged card, the verdicts                (``scan-record``)
    RUN/requests/<slug>/request.json       a draft request for the correction path, flagged cards only (``scan-record``)

The scan decides nothing and publishes nothing. A request it drafts reaches ``cards/`` only through the correction of
a published card (``me_atlas.card_correction``), where its ``origin_kind`` makes the upgrade variant possible once code
has verified the scan result (``verify_scan_result``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from me_atlas import cards, europepmc
from me_atlas import fulltext as ft
from me_atlas.citations import CacheReader, normalise_quote
from me_atlas.europepmc import CaseDefinitionCandidate, EuropePmcCache, EuropePmcError
from me_atlas.pipeline import (
    FULLTEXT_NOT_CACHED_NOTE,
    Config,
    FullTextResult,
    PipelineError,
    _audit_record_lines,
    carrier_ids,
    fulltext_note,
)

AGREES, DIFFERS, NO_CANDIDATE = "agrees", "differs", "no_candidate"
LABELS = (AGREES, DIFFERS, NO_CANDIDATE)
FIELDS = ("case_definition", "n_patients", "n_controls", "finding", "role", "carrying")
CONFIRMED, ADDS, NOT_CITED = "confirmed", "adds", "not_cited"
VERDICTS = (CONFIRMED, DIFFERS, ADDS)
QUOTED = (DIFFERS, ADDS)  # verdicts that must carry a quote found in the full text
ADDS_FLAGGING_FIELDS = ("case_definition", "role", "carrying")
FLAG_RULE = 2  # 2026-11-28: differs on any field, or adds on case_definition, role or carrying
ORIGIN_KIND = "fulltext_scan"

STEP0_FILE = "step0.json"
PLAN_FILE = "scan-plan.json"
RESULT_FILE = "scan-result.json"
REPORT_FILE = "scan-report.md"
FULL_TEXT_MARKER = "\nFull text:\n"  # in a context file: the rendered full text follows (the audit context's heading)
FULL_TEXT_HEADING = "## 5. The full text"

# Which definition a matched wording names, in the card's vocabulary. This only sorts candidates; it decides nothing.
_DEFINITION_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("Fukuda", r"\bFukuda\b"),
        ("Holmes1988", r"\bHolmes\b"),
        ("CCC", r"\bCanadian\b|\bCarruthers\b|\bCCC\b|\bCanada\s+\(?2003\)?"),
        ("ICC", r"\bInternational Consensus Criteria\b|\bICC\b"),
        ("IOM2015", r"\bInstitute of Medicine\b|\bIOM\b|\bSEID\b|\bsystemic exertion intolerance\b"),
        ("Oxford", r"\bOxford\b|\bSharpe\b"),
    )
)
_CDC = re.compile(r"\bCDC\b|\bCenters? for Disease Control\b", re.IGNORECASE)


class ScanError(Exception):
    """A scan command cannot continue; the message says what to fix."""


# ---------------------------------------------------------------------------
# Step 0
# ---------------------------------------------------------------------------


def flags(verdict: dict[str, Any]) -> bool:
    """Whether a kept verdict flags its study: ``differs`` on any field, or ``adds`` on ``case_definition``, ``role``
    or ``carrying``. An ``adds`` on ``finding``, ``n_patients`` or ``n_controls`` is reported but does not flag."""
    kind = verdict.get("verdict")
    return kind == DIFFERS or (kind == ADDS and verdict.get("field") in ADDS_FLAGGING_FIELDS)


def named_definitions(matched: Sequence[str]) -> frozenset[str]:
    """The definitions (in the card's vocabulary) that the matched wordings of a candidate name. ``CDC`` alone,
    ``case definition``, ``diagnostic criteria`` and the like name none; 1994 or 1988 together with CDC name Fukuda or
    Holmes1988."""
    found: set[str] = set()
    for wording in matched:
        for name, pattern in _DEFINITION_WORDS:
            if pattern.search(wording):
                found.add(name)
        if _CDC.search(wording):
            if re.search(r"\b1994\b", wording):
                found.add("Fukuda")
            if re.search(r"\b1988\b", wording):
                found.add("Holmes1988")
    return frozenset(found)


@dataclass(frozen=True)
class Step0:
    label: str
    names: tuple[str, ...]
    candidates: tuple[CaseDefinitionCandidate, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "named_definitions": list(self.names),
            "candidates": [
                {
                    "section": c.section,
                    "scope": c.scope,
                    "kind": c.kind,
                    "sentence": c.sentence,
                    "matched": list(c.matched),
                    "names": sorted(named_definitions(c.matched)) if c.kind == "definition" else [],
                }
                for c in self.candidates
            ],
        }


def label_study(study: cards.Study, candidates: Sequence[CaseDefinitionCandidate], full_text: str) -> Step0:
    """The step 0 label of one study (plan, "Step 0"). ``agrees``: the card's quote is found word for word in the
    candidate sentences or the full text, or the named definitions are exactly the card's, and no candidate names
    another definition. ``differs``: a candidate names a definition that is not the card's. ``no_candidate``: none
    names a definition and the quote is not found. Exclusion candidates are listed but do not decide."""
    definitions = [c for c in candidates if c.kind == "definition"]
    named: set[str] = set()
    for c in definitions:
        named |= named_definitions(c.matched)
    names = tuple(sorted(named))
    if named - {study.case_definition}:
        return Step0(DIFFERS, names, tuple(candidates))
    quote = normalise_quote(study.case_definition_quote) if study.case_definition_quote else None
    found = quote is not None and (
        quote in normalise_quote(" ".join(c.sentence for c in definitions)) or quote in normalise_quote(full_text)
    )
    if found or named == {study.case_definition}:
        return Step0(AGREES, names, tuple(candidates))
    return Step0(NO_CANDIDATE, names, tuple(candidates))


def run_step0(study: cards.Study, status: ft.FullTextStatus, cache: CacheReader) -> Step0:
    """Step 0 for one study whose full text is cached as ``fulltext_xml`` or ``pmc_page``. Raises EuropePmcError or
    OSError when the cached file cannot be read; ValueError for another status."""
    assert status.pmcid is not None
    if status.status == ft.FULLTEXT_XML:
        content = cache.epmc.fulltext_path(status.pmcid).read_bytes()
        return label_study(study, europepmc.find_case_definitions(content), europepmc.article_text(content))
    if status.status == ft.PMC_PAGE:
        content = cache.epmc.page_path(status.pmcid).read_bytes()
        return label_study(study, europepmc.find_case_definitions_in_page(content), europepmc.pmc_page_text(content))
    raise ValueError(f"step 0 reads fulltext_xml and pmc_page only, not {status.status}")


# ---------------------------------------------------------------------------
# The full text as the audit context renders it
# ---------------------------------------------------------------------------


def cache_loader(cache_dir: Path):
    """A full-text loader that reads the cache only (no request, whatever the environment says). For a cached XML with
    a real body it answers as the live loader does on a cache hit; otherwise it says the full text is not cached, which
    the audit context then renders as ``FULLTEXT_NOT_CACHED_NOTE``."""
    epmc = EuropePmcCache(cache_dir)

    def load(
        pmid: str | None, pmcid: str | None = None, *, preprint: europepmc.PreprintRecord | None = None
    ) -> FullTextResult:
        known = pmcid
        lookup = None
        if preprint is None and pmid is not None and pmid.isdigit():
            try:
                lookup = europepmc.read_cached_lookup(epmc, pmid)
            except EuropePmcError as exc:
                return FullTextResult(None, f"cached Europe PMC lookup cannot be read: {exc}")
            known = (lookup.pmcid if lookup else None) or pmcid
        if known is None:
            if lookup is not None:  # a lookup was made and found no PMC id: the note the live loader gives
                return FullTextResult(None, fulltext_note(lookup.status, None))
            return FullTextResult(None, "no PMC id is known")
        try:
            path = epmc.fulltext_path(known)
            if path.is_file():
                content = path.read_bytes()
                if not europepmc.is_placeholder_fulltext(content):
                    return FullTextResult(content, fulltext_note(europepmc.STATUS_OPEN_ACCESS, known))
        except (EuropePmcError, OSError, ValueError) as exc:
            return FullTextResult(None, f"cached full text cannot be read: {exc}")
        return FullTextResult(None, f"full text not cached ({known} has no cached XML with a body)")

    return load


def render_record(cfg: Config, study_id: str) -> list[str]:
    """The record of ``study_id`` exactly as the audit context renders a carrier: fields, abstract and the full text,
    uncut (``pipeline._audit_record_lines`` with ``carrier=True``), from the cache only."""
    return _audit_record_lines(cfg, study_id, cache_loader(cfg.cache_dir), True)


def rendered_fulltext(lines: Sequence[str]) -> str | None:
    """The full-text part of a rendered record, or None when the audit context would say it is not cached."""
    text = "\n".join(lines)
    if FULLTEXT_NOT_CACHED_NOTE in text:
        return None
    head, marker, tail = text.partition(FULL_TEXT_MARKER)
    return tail if marker else None


def _file_safe(study_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", study_id).strip("-")


def stem(slug: str, study_id: str) -> str:
    return f"{slug}--{_file_safe(study_id)}"


# ---------------------------------------------------------------------------
# scan-plan
# ---------------------------------------------------------------------------


def _paras(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    return [value] if isinstance(value, dict) else [x for x in value if isinstance(x, dict)]


def card_items(data: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    """Every sourced text of a card as (target name, text, sources): the names of the correction path."""
    badges = data.get("badges") or {}
    contested = data.get("contested")
    found: list[tuple[str, str, list[str]]] = []
    core = data.get("core_claim") or {}
    found.append(("core_claim", str(core.get("text") or ""), list(core.get("sources") or [])))
    groups = {
        "level_reason": _paras(data.get("level_reason")),
        "contested_reason": _paras(contested.get("reason")) if isinstance(contested, dict) else [],
        "badge_reasons.diagnostic_marker": _paras((badges.get("diagnostic_marker") or {}).get("reason")),
        "badge_reasons.explains_pem": _paras((badges.get("explains_pem") or {}).get("reason")),
        "subgroups": _paras(data.get("subgroups")),
        "early_signals": _paras(data.get("early_signals")),
        "links": [x for x in data.get("links") or [] if isinstance(x, dict)],
    }
    for key, paras in groups.items():
        for i, p in enumerate(paras):
            found.append((f"{key}[{i}]", str(p.get("text") or ""), list(p.get("sources") or [])))
    return found


CARRYING_PREFIXES = ("level_reason[", "contested_reason[", "badge_reasons.")


def carrying_targets(data: dict[str, Any], study_id: str) -> list[str]:
    """The targets of the level, contested and badge reason paragraphs that cite the study."""
    return [t for t, _text, sources in card_items(data) if t.startswith(CARRYING_PREFIXES) and study_id in sources]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _flat(text: str) -> str:
    return " ".join(text.split())


def context_text(
    out: Path,
    slug: str,
    study: cards.Study,
    data: dict[str, Any],
    *,
    carrier: bool,
    targets: list[str],
    step0: Step0,
    status: ft.FullTextStatus,
    record: Sequence[str],
) -> str:
    entry = next(s for s in data["studies"] if s.get("id") == study.id)
    scan_file = (out / "scan" / f"{stem(slug, study.id)}.json").resolve()
    items = [(t, text, sources) for t, text, sources in card_items(data) if study.id in sources]
    lines = [
        f"# Full-text scan context: `{slug}`, `{study.id}`",
        "",
        f"Write your scan file to `{scan_file.as_posix()}` (the format is in your instructions). Read nothing but this "
        "file. This is everything you may rely on: the quotes you give must be copied word for word from section 5.",
        "",
        "## 1. The study's entry on the card",
        "",
        "```yaml",
        yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=100).rstrip("\n"),
        "```",
        "",
        "## 2. Card items that cite the study (each under its target name)",
        "",
    ]
    if items:
        for target, text, sources in items:
            lines += [f"- `{target}` (sources: {', '.join(sources)}): {_flat(text)}"]
    else:
        lines.append("No card item cites the study.")
    lines += [
        "",
        f"Carrier of the level, a badge, the contested mark or a link: {'yes' if carrier else 'no'}.",
        "Targets for the `carrying` field (the level, contested and badge reason paragraphs that cite the study): "
        + (", ".join(f"`{t}`" for t in targets) if targets else "none (the study is cited in no such reason)")
        + ".",
        "",
        "## 3. Step 0 (code's comparison of the case definition; a pointer, not a verdict)",
        "",
        f"- label: {step0.label}",
        f"- the card: case_definition `{study.case_definition}`, source `{study.case_definition_source}`, "
        f"quote: {study.case_definition_quote!r}",
        f"- definitions named by the candidates: {', '.join(step0.names) or 'none'}",
        f"- full-text status: {status.status} ({status.pmcid})",
        "",
    ]
    for c in step0.candidates:
        lines.append(f"- [{c.kind}] section `{c.section}`; matched {', '.join(c.matched)}: {c.sentence}")
    if not step0.candidates:
        lines.append("No candidate sentence was found.")
    lines += [
        "",
        "## 4. How to read section 5",
        "",
        "Section 5 is the record as the audit of a correction would see it. A quote you give is checked against its "
        "`Full text:` part only (after the usual whitespace, quote and dash folding), never against the card text "
        "above.",
        "",
        f"{FULL_TEXT_HEADING} (as the audit context renders a carrier)",
        "",
        *record,
    ]
    return "\n".join(lines) + "\n"


@dataclass
class PlanResult:
    studies: list[dict[str, Any]]
    errors: list[str]


def scan_plan(
    out: Path,
    cache_dir: Path,
    cards_dir: Path,
    *,
    carrying_only: bool = False,
    study_ids: Collection[str] = (),
    named: Sequence[ft.Named] = (),
    today: dt.date | None = None,
) -> PlanResult:
    """``scan-plan``: step 0 and the scan contexts. Reads the cache and the cards only; writes into ``out`` only."""
    report = ft.build_report(cards_dir, named, cache_dir)
    errors = list(report.errors)
    cache = CacheReader(cache_dir)
    cfg = Config(run_dir=out, cards_dir=cards_dir, cache_dir=cache_dir)
    rows = [r for r in report.rows if r.status.status in ft.READ]
    if carrying_only:
        rows = [r for r in rows if r.category == ft.CARRYING]
    if study_ids:
        rows = [r for r in rows if r.study.id in set(study_ids)]
        missing = sorted(set(study_ids) - {r.study.id for r in rows})
        errors += [f"--study {i}: no listed study with a cached full text (xml or page) has this id" for i in missing]
    card_data: dict[str, dict[str, Any]] = {}
    card_obj: dict[str, cards.Card] = {}
    plan_cards: dict[str, dict[str, str]] = {}
    for slug in sorted({r.card for r in rows}):
        path = Path(cards_dir) / f"{slug}.yaml"
        card_data[slug] = yaml.safe_load(path.read_text(encoding="utf-8"))
        card_obj[slug] = cards.load_card(path)
        plan_cards[slug] = {"file": str(path), "sha256": _sha256_file(path)}
    studies: list[dict[str, Any]] = []
    step0_rows: list[dict[str, Any]] = []
    for r in sorted(rows, key=lambda r: (r.card, r.study.id)):
        slug, study = r.card, r.study
        try:
            step0 = run_step0(study, r.status, cache)
            record = render_record(cfg, study.id)
        except (EuropePmcError, OSError, PipelineError) as exc:
            errors.append(f"{slug} {study.id}: {exc}")
            continue
        data = card_data[slug]
        carrier = study.id in carrier_ids(card_obj[slug])
        targets = carrying_targets(data, study.id)
        name = stem(slug, study.id)
        context = out / "scan-context" / f"{name}.md"
        context.parent.mkdir(parents=True, exist_ok=True)
        context.write_text(
            context_text(
                out, slug, study, data, carrier=carrier, targets=targets, step0=step0, status=r.status, record=record
            ),
            encoding="utf-8",
            newline="\n",
        )
        studies.append(
            {
                "card": slug,
                "study": study.id,
                "status": r.status.status,
                "pmcid": r.status.pmcid,
                "context": f"scan-context/{name}.md",
                "scan_file": f"scan/{name}.json",
                "carrier": carrier,
                "cited_in_reason": bool(targets),
                "carrying_targets": targets,
                "step0": step0.label,
                "fulltext_rendered": rendered_fulltext(record) is not None,
            }
        )
        step0_rows.append(
            {
                "card": slug,
                "study": study.id,
                "status": r.status.status,
                "card_fields": {
                    "case_definition": study.case_definition,
                    "case_definition_source": study.case_definition_source,
                    "case_definition_quote": study.case_definition_quote,
                },
                **step0.as_dict(),
            }
        )
    day = (today or dt.date.today()).isoformat()
    counts = {label: sum(1 for s in studies if s["step0"] == label) for label in LABELS}
    _write_json(out / STEP0_FILE, {"date": day, "counts": counts, "studies": step0_rows})
    _write_json(
        out / PLAN_FILE,
        {
            "run_id": Path(out).resolve().name,
            "date": day,
            "cache_dir": str(cache_dir),
            "cards_dir": str(cards_dir),
            "carrying_only": carrying_only,
            "cards": plan_cards,
            "studies": studies,
        },
    )
    return PlanResult(studies, errors)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# scan-record: validation of the scan files
# ---------------------------------------------------------------------------


def validate_scan_file(data: Any, entry: dict[str, Any]) -> list[str]:
    """What is wrong with the content of one scan file, for the plan entry of its study. Empty: valid."""
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    found: list[str] = []
    if set(data) - {"card", "study", "fields"}:
        found.append(f"unknown key(s): {', '.join(sorted(set(data) - {'card', 'study', 'fields'}))}")
    if data.get("card") != entry["card"]:
        found.append(f"card is {data.get('card')!r}, expected {entry['card']!r}")
    if data.get("study") != entry["study"]:
        found.append(f"study is {data.get('study')!r}, expected {entry['study']!r}")
    fields = data.get("fields")
    if not isinstance(fields, dict):
        return [*found, "`fields` is missing or not an object"]
    found += [f"fields lacks the key `{k}`" for k in FIELDS if k not in fields]
    found += [f"fields has the unknown key `{k}`" for k in fields if k not in FIELDS]
    for name in FIELDS:
        if name in fields:
            found += _field_problems(name, fields[name], entry)
    return found


def _field_problems(name: str, value: Any, entry: dict[str, Any]) -> list[str]:
    where = f"fields.{name}"
    if not isinstance(value, dict):
        return [f"{where} is not an object"]
    allowed = {"verdict", "quote", "note"} | ({"targets"} if name == "carrying" else set())
    found = [f"{where} lacks `{k}`" for k in ("verdict", "quote", "note") if k not in value]
    found += [f"{where} has the unknown key `{k}`" for k in value if k not in allowed]
    verdict, quote, note = value.get("verdict"), value.get("quote"), value.get("note")
    if "verdict" not in value:
        return found
    if verdict == NOT_CITED:
        if name != "carrying":
            return [*found, f"{where}: `not_cited` is only for `carrying`"]
        if entry["cited_in_reason"]:
            found.append(f"{where}: `not_cited`, but the study is cited in a level, badge or contested reason")
        if quote is not None or "targets" in value:
            found.append(f"{where}: a `not_cited` verdict has no quote and no targets")
        return found
    if verdict not in VERDICTS:
        return [*found, f"{where}: unknown verdict {verdict!r} (confirmed, differs, adds)"]
    if name == "carrying" and not entry["cited_in_reason"]:
        found.append(f"{where}: the study is cited in no level, badge or contested reason; the verdict is `not_cited`")
    if verdict == CONFIRMED:
        if quote is not None or "targets" in value:
            found.append(f"{where}: a `confirmed` verdict has quote null and no targets")
        return found
    if not isinstance(quote, str) or not quote.strip():
        found.append(f"{where}: `{verdict}` needs a `quote` copied from the full text")
    if not isinstance(note, str) or not note.strip() or "\n" in note.strip():
        found.append(f"{where}: `{verdict}` needs a one-line `note`")
    if name == "carrying":
        targets = value.get("targets")
        if not isinstance(targets, list) or not targets or not all(isinstance(t, str) for t in targets):
            found.append(f"{where}: `{verdict}` needs `targets`, a non-empty list of targets of the context")
        else:
            found += [
                f"{where}: target {t!r} is not listed by the context for this study"
                for t in targets
                if t not in entry["carrying_targets"]
            ]
    elif "targets" in value:
        found.append(f"{where}: `targets` belongs to `carrying` only")
    return found


def quote_in_fulltext(quote: str, full_text: str | None) -> bool:
    """Whether ``quote`` is found word for word (``normalise_quote``) in the rendered full text."""
    return full_text is not None and normalise_quote(quote) in normalise_quote(full_text)


def context_fulltext(context: Path) -> str | None:
    """The rendered full text of a scan context file (its section 5, after ``Full text:``), or None when the audit
    rendering said the full text is not cached."""
    text = context.read_text(encoding="utf-8")
    head, marker, body = text.partition(FULL_TEXT_HEADING)
    if not marker or FULLTEXT_NOT_CACHED_NOTE in body:
        return None
    _before, sep, tail = body.partition(FULL_TEXT_MARKER)
    return tail if sep else None


def _request_target(field: str, targets: list[str] | None, study_id: str) -> list[str]:
    return list(targets or []) if field == "carrying" else [f"studies[{study_id}].{field}"]


def _problem(verdict: str, note: str, quote: str) -> str:
    what = "differs from the card" if verdict == DIFFERS else "states something the card lacks"
    return f"The full-text scan found that the full text {what}: {_flat(note)} Quote from the full text: {_flat(quote)}"


@dataclass
class RecordResult:
    result: dict[str, Any]
    report: str
    requests: dict[str, dict[str, Any]]


def record_scan(out: Path, *, today: dt.date | None = None) -> RecordResult:
    """``scan-record``: validate every scan file against its plan entry and context, check each quote, and build the
    result, the report and the draft requests. Reads ``out`` only; ``write_record`` writes. Raises ScanError when
    ``scan-plan.json`` is missing."""
    plan_path = out / PLAN_FILE
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScanError(f"{plan_path} cannot be read ({exc}); run `scan-plan` first") from exc
    result_cards: dict[str, dict[str, Any]] = {
        slug: {"sha256": info["sha256"], "studies": {}} for slug, info in plan["cards"].items()
    }
    invalid: list[str] = []
    missing: list[str] = []
    dropped_lines: list[str] = []
    planned_files = set()
    for entry in plan["studies"]:
        slug, study_id = entry["card"], entry["study"]
        planned_files.add((out / entry["scan_file"]).resolve())
        record: dict[str, Any] = {
            "status": entry["status"],
            "step0": entry["step0"],
            "carrier": entry["carrier"],
            "cited_in_reason": entry["cited_in_reason"],
            "scanned": False,
            "invalid": None,
            "verdicts": [],
            "dropped": [],
            "flagged": False,
        }
        result_cards[slug]["studies"][study_id] = record
        path = out / entry["scan_file"]
        if not path.is_file():
            missing.append(f"{slug} {study_id}: no scan file {entry['scan_file']}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            record["invalid"] = [f"not JSON ({exc})"]
            invalid.append(f"{entry['scan_file']}: not JSON ({exc})")
            continue
        problems = validate_scan_file(data, entry)
        if problems:
            record["invalid"] = problems
            invalid += [f"{entry['scan_file']}: {p}" for p in problems]
            continue
        full_text = context_fulltext(out / entry["context"])
        record["scanned"] = True
        for field in FIELDS:
            value = data["fields"][field]
            kept = {"field": field, "verdict": value["verdict"], "quote": value["quote"], "note": value["note"]}
            if "targets" in value:
                kept["targets"] = list(value["targets"])
            if value["verdict"] in QUOTED and not quote_in_fulltext(value["quote"], full_text):
                why = (
                    "the audit rendering has no full text for this study"
                    if full_text is None
                    else "the quote is not found word for word in the rendered full text"
                )
                record["dropped"].append({**kept, "reason": why})
                dropped_lines.append(f"{slug} {study_id} {field} ({value['verdict']}): {why}: {_flat(value['quote'])}")
                continue
            record["verdicts"].append(kept)
        record["flagged"] = any(flags(v) for v in record["verdicts"])
    for stray in sorted((out / "scan").glob("*.json") if (out / "scan").is_dir() else []):
        if stray.resolve() not in planned_files:
            invalid.append(f"scan/{stray.name}: not a file of the plan")
    flagged = {
        slug: [sid for sid, rec in info["studies"].items() if rec["flagged"]] for slug, info in result_cards.items()
    }
    flagged = {slug: ids for slug, ids in flagged.items() if ids}
    records = [rec for info in result_cards.values() for rec in info["studies"].values()]
    not_flagging = [
        (slug, sid, v)
        for slug, info in result_cards.items()
        for sid, rec in info["studies"].items()
        for v in rec["verdicts"]
        if v["verdict"] == ADDS and not flags(v)
    ]
    counts = {
        "step0": {label: sum(1 for r in records if r["step0"] == label) for label in LABELS},
        "verdicts": {
            v: sum(1 for r in records for x in r["verdicts"] if x["verdict"] == v) for v in (*VERDICTS, NOT_CITED)
        },
        "quotes_dropped": len(dropped_lines),
        "files_invalid": len(invalid),
        "files_missing": len(missing),
        "cards_flagged": len(flagged),
        "adds_not_flagging": len(not_flagging),
    }
    day = (today or dt.date.today()).isoformat()
    result = {
        "run_id": plan["run_id"],
        "date": day,
        "plan_date": plan["date"],
        "flag_rule": FLAG_RULE,
        "counts": counts,
        "cards": result_cards,
        "flagged": flagged,
    }
    requests = {slug: _draft_request(slug, result, plan_path) for slug in flagged}
    report = _report(result, flagged, dropped_lines, invalid, missing, not_flagging)
    return RecordResult(result, report, requests)


def _draft_request(slug: str, result: dict[str, Any], plan_path: Path) -> dict[str, Any]:
    items: list[dict[str, str]] = []
    for study_id in result["flagged"][slug]:
        for v in result["cards"][slug]["studies"][study_id]["verdicts"]:
            if not flags(v):
                continue
            for target in _request_target(v["field"], v.get("targets"), study_id):
                items.append({"target": target, "problem": _problem(v["verdict"], v["note"], v["quote"])})
    return {
        "card": slug,
        "origin": f"the full-text scan {result['run_id']} of {result['date']} (docs/plan-fulltext-recheck.md)",
        "origin_kind": ORIGIN_KIND,
        "scan": {"result": "", "result_sha256": ""},  # filled by write_record: the path and the sha256 of the result
        "items": items,
    }


def _report(
    result: dict[str, Any],
    flagged: dict[str, list[str]],
    dropped: list[str],
    invalid: list[str],
    missing: list[str],
    not_flagging: list[tuple[str, str, dict[str, Any]]],
) -> str:
    c = result["counts"]
    lines = [
        f"# Full-text scan report: {result['run_id']}",
        "",
        f"Date: {result['date']}. The scan decides nothing and publishes nothing; a flagged card goes on to the "
        "correction path only if the founder decides so.",
        "",
        "## Counts",
        "",
        f"- step 0: agrees {c['step0'][AGREES]}, differs {c['step0'][DIFFERS]}, "
        f"no_candidate {c['step0'][NO_CANDIDATE]}",
        f"- verdicts: confirmed {c['verdicts'][CONFIRMED]}, differs {c['verdicts'][DIFFERS]}, "
        f"adds {c['verdicts'][ADDS]} (not_cited {c['verdicts'][NOT_CITED]})",
        f"- quotes dropped: {c['quotes_dropped']}",
        f"- files invalid: {c['files_invalid']} (no scan file: {c['files_missing']})",
        f"- cards flagged: {c['cards_flagged']}",
        f"- additions that do not flag: {c['adds_not_flagging']}",
        "",
    ]
    for title, rows in (
        ("Quotes dropped", dropped),
        ("Invalid files", invalid),
        ("Studies without a scan file", missing),
    ):
        if rows:
            lines += [f"## {title}", "", *[f"- {r}" for r in rows], ""]
    if not_flagging:
        lines += ["## Additions that do not flag", ""]
        for slug, sid, v in not_flagging:
            lines.append(f"- {slug} {sid} {v['field']}: {_flat(v['note'])}")
            lines.append(f"  - quote: {_flat(v['quote'])}")
        lines.append("")
    for slug, ids in flagged.items():
        lines += [f"## Flagged: {slug}", ""]
        for study_id in ids:
            rec = result["cards"][slug]["studies"][study_id]
            lines += [f"### {study_id} (step 0: {rec['step0']}, full text: {rec['status']})", ""]
            for v in rec["verdicts"]:
                if flags(v):
                    targets = f" targets {', '.join(v['targets'])};" if v.get("targets") else ""
                    lines.append(f"- {v['field']}: {v['verdict']};{targets} {_flat(v['note'])}")
                    lines.append(f"  - quote: {_flat(v['quote'])}")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_record(out: Path, record: RecordResult) -> Path:
    """Write ``scan-result.json``, ``scan-report.md`` and ``requests/<slug>/request.json`` into ``out``."""
    result_path = out / RESULT_FILE
    _write_json(result_path, record.result)
    sha = _sha256_file(result_path)
    requests_dir = out / "requests"
    if requests_dir.is_dir():
        for old in requests_dir.rglob("request.json"):
            old.unlink()
    for slug, request in record.requests.items():
        request["scan"] = {"result": str(result_path.resolve()), "result_sha256": sha}
        _write_json(requests_dir / slug / "request.json", request)
    (out / REPORT_FILE).write_text(record.report, encoding="utf-8", newline="\n")
    return result_path


# ---------------------------------------------------------------------------
# The scan result, read back by the correction path
# ---------------------------------------------------------------------------

_SHA = re.compile(r"^[0-9a-f]{64}$")


class ScanResultError(Exception):
    """A scan-result file that is not a valid scan result."""


def validate_scan_result(data: Any) -> list[str]:
    """What is wrong with a parsed ``scan-result.json`` (structure and consistency). Empty: valid."""
    if not isinstance(data, dict):
        return ["not a JSON object"]
    found = [f"lacks `{k}`" for k in ("run_id", "date", "counts", "cards", "flagged") if k not in data]
    if found:
        return found
    if not isinstance(data["cards"], dict) or not isinstance(data["flagged"], dict):
        return ["`cards` and `flagged` are objects"]
    for slug, info in data["cards"].items():
        if (
            not isinstance(info, dict)
            or not _SHA.match(str(info.get("sha256")))
            or not isinstance(info.get("studies"), dict)
        ):
            found.append(f"cards.{slug}: needs a sha256 and `studies`")
    for slug, ids in data["flagged"].items():
        info = data["cards"].get(slug)
        if info is None or not isinstance(ids, list) or not ids:
            found.append(f"flagged.{slug}: names no card of the result or no study")
            continue
        for study_id in ids:
            rec = (info.get("studies") or {}).get(study_id) if isinstance(info, dict) else None
            if not isinstance(rec, dict):
                found.append(f"flagged.{slug}: {study_id} is not a study of the card in the result")
            elif rec.get("status") not in ft.READ:
                found.append(f"flagged.{slug}: {study_id} has full text status {rec.get('status')!r}")
            elif not any(
                isinstance(v, dict) and v.get("verdict") in QUOTED and v.get("quote") for v in rec.get("verdicts", [])
            ):
                found.append(f"flagged.{slug}: {study_id} has no kept differs/adds verdict")
    return found


def load_scan_result(path: Path) -> dict[str, Any]:
    """The parsed scan result; ScanResultError when it is not JSON or not a valid result."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScanResultError(f"not readable JSON ({exc})") from exc
    if problems := validate_scan_result(data):
        raise ScanResultError("; ".join(problems))
    return data


def flagged_studies(result: dict[str, Any], slug: str) -> dict[str, str]:
    """The studies the scan flagged on card ``slug``: id to its full-text status (``fulltext_xml`` or ``pmc_page``)."""
    return {sid: result["cards"][slug]["studies"][sid]["status"] for sid in result["flagged"].get(slug, [])}
