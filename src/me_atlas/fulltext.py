"""Which studies on the cards need their full text read, and storing a PMC page saved by hand.

Command line::

    uv run python -m me_atlas.fulltext needs [--markdown] [--cards-dir cards] [--config config/fulltext_named.yaml]
                                             [--cache-dir data/cache]
    uv run python -m me_atlas.fulltext import-saved --card <card.yaml> --pmid <digits>
                                             [--cache-dir data/cache] [--saved-dir data/hand-saved/fulltext]
    uv run python -m me_atlas.fulltext scan-plan --out RUN [--cache-dir DIR] [--cards-dir DIR] [--carrying-only]
                                             [--study ID ...] [--config FILE]
    uv run python -m me_atlas.fulltext scan-record --out RUN

``needs`` is offline: it reads the cards, the config file and the cache, and lists the studies whose case
definition or numbers a reader of the full text could settle. ``import-saved`` copies a PMC article page saved by
hand into the cache, where ``citations check`` and ``europepmc casedef`` read it. Neither makes a request.
``scan-plan`` and ``scan-record`` are the full-text scan (``me_atlas.fulltext_scan``, ``docs/pipeline.md``): offline,
they write only into the run folder ``RUN``. The reference is ``docs/fulltext-targets.md``.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from me_atlas.cards import Card, CardValidationError, Study, load_card
from me_atlas.citations import CacheReader
from me_atlas.europepmc import (
    DEFAULT_CACHE_ROOT,
    EuropePmcError,
    _print_candidates,
    find_case_definitions_in_page,
    is_placeholder_fulltext,
    parse_pmc_page,
    read_cached_lookup,
)
from me_atlas.pubmed import PubMedRecord

DEFAULT_CARDS_DIR = Path("cards")
DEFAULT_CONFIG = Path("config/fulltext_named.yaml")
DEFAULT_SAVED_DIR = Path("data/hand-saved/fulltext")
CHANGELOG_NAME = "changelog.yaml"

FULLTEXT_XML = "fulltext_xml"
PMC_PAGE = "pmc_page"
PDF_PLACEHOLDER = "pdf_placeholder"
OPEN_ACCESS_NOT_CACHED = "open_access_not_cached"
FREE_ON_PMC = "free_on_pmc"
PMC_ID_NOT_IN_PMC = "pmc_id_not_in_pmc"
NO_PMC_ID = "no_pmc_id"
NO_LOOKUP = "no_lookup"

STATUSES = (
    FULLTEXT_XML,
    PMC_PAGE,
    PDF_PLACEHOLDER,
    OPEN_ACCESS_NOT_CACHED,
    FREE_ON_PMC,
    PMC_ID_NOT_IN_PMC,
    NO_PMC_ID,
    NO_LOOKUP,
)
READ = frozenset({FULLTEXT_XML, PMC_PAGE})

CARRYING = "carrying"
UNVERIFIED = "unverified"
NAMED = "named"
CATEGORIES = (CARRYING, UNVERIFIED, NAMED)
CARRYING_ROLES = frozenset({"supports", "contradicts", "early_signal"})

RUNG = {
    "uncontrolled": "level 1",
    "controlled": "level 2-3 and the contested mark",
    "intervention_controlled": "level 4",
}

NAMED_LABEL = "named in STATUS.md"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FullTextStatus:
    status: str
    pmcid: str | None


def study_status(study: Study, cache: CacheReader) -> FullTextStatus:
    """The full-text status of one study, from the cache only.

    The PMC id is chosen as in ``citations.CacheReader``: the Europe PMC lookup first, else the PubMed record.
    A ``doi:`` study takes it from the cached preprint record. Raises EuropePmcError or OSError when a cached
    file cannot be read.
    """
    epmc = cache.epmc
    from_pubmed = False
    if study.id.startswith("doi:"):
        record = cache.preprint(study.id)
        if record is None:
            return FullTextStatus(NO_LOOKUP, None)
        pmcid, open_access, in_pmc, have_lookup = record.pmcid, record.is_open_access, record.in_pmc, True
    else:
        pmid = study.id.removeprefix("pmid:")
        lookup = read_cached_lookup(epmc, pmid)
        pmcid = lookup.pmcid if lookup else None
        open_access = bool(lookup and lookup.open_access)
        in_pmc = bool(lookup and lookup.in_pmc)
        have_lookup = lookup is not None
        if pmcid is None:
            record = cache.record(pmid)
            if isinstance(record, PubMedRecord) and record.pmcid:
                pmcid, from_pubmed = record.pmcid, True
    if pmcid is None:
        return FullTextStatus(NO_PMC_ID if have_lookup else NO_LOOKUP, None)

    xml, page = epmc.fulltext_path(pmcid), epmc.page_path(pmcid)
    placeholder = False
    if xml.is_file():
        if not is_placeholder_fulltext(xml.read_bytes()):
            return FullTextStatus(FULLTEXT_XML, pmcid)
        placeholder = True
    if page.is_file():
        return FullTextStatus(PMC_PAGE, pmcid)
    if placeholder:
        return FullTextStatus(PDF_PLACEHOLDER, pmcid)
    if open_access:
        return FullTextStatus(OPEN_ACCESS_NOT_CACHED, pmcid)
    if in_pmc or from_pubmed:
        return FullTextStatus(FREE_ON_PMC, pmcid)
    return FullTextStatus(PMC_ID_NOT_IN_PMC, pmcid)


def next_step(status: str, study_id: str) -> str:
    pmid = study_id.removeprefix("pmid:")
    if status == FREE_ON_PMC:
        return "save the PMC page by hand, then `import-saved` (docs/fetch.md, full texts saved by hand)"
    if status in {OPEN_ACCESS_NOT_CACHED, NO_LOOKUP}:
        arg = pmid if study_id.startswith("pmid:") else study_id.removeprefix("doi:")
        command = "fulltext" if study_id.startswith("pmid:") else "preprint"
        suffix = "" if study_id.startswith("pmid:") else " --fulltext"
        return f"`uv run python -m me_atlas.europepmc {command} {arg}{suffix}`"
    if status in READ:
        return "already cached; read it with `europepmc casedef`"
    return "not free on PMC; no route in the pipeline"


def addresses(study: Study, pmcid: str | None) -> list[str]:
    out = []
    if pmcid:
        out.append(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/")
    if study.id.startswith("pmid:"):
        out.append(f"https://pubmed.ncbi.nlm.nih.gov/{study.id.removeprefix('pmid:')}/")
    if study.doi:
        out.append(f"https://doi.org/{study.doi}")
    return out


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def carrying_reason(study: Study, status: str) -> str | None:
    """Why a supports/contradicts/early_signal study needs its full text, or None if it does not."""
    if study.role not in CARRYING_ROLES:
        return None
    reasons = []
    if study.case_definition_source == "abstract":
        reasons.append("its case definition was read from the abstract")
    if status not in READ:
        reasons.append("no full text is cached")
    return " and ".join(reasons) or None


def unverified_reason(study: Study) -> str | None:
    """Why a context study with an unverified case definition could matter, or None if it is out of scope."""
    if (
        study.role != "context"
        or study.case_definition != "unverified"
        or study.design == "other"
        or study.preprint
        or study.corrects is not None
    ):
        return None
    reason = f"unverified case definition; verified, it could count towards {RUNG[study.design]}"
    if study.measures_pem:
        reason += " and the explains_pem badge"
    return reason


def settles(study: Study, from_abstract: bool) -> list[str]:
    out = []
    if study.case_definition == "unverified" or from_abstract:
        out.append("the case-definition sentence")
    nulls = [n for n, v in (("n_patients", study.n_patients), ("n_controls", study.n_controls)) if v is None]
    if nulls:
        out.append(" and ".join(nulls))
    if study.role == "contradicts":
        count = "not recorded" if study.n_patients is None else str(study.n_patients)
        out.append(f"the patient count in the contradicting measurement (card n_patients: {count})")
    if study.measures_pem:
        out.append("the PEM measurement")
    return out


# ---------------------------------------------------------------------------
# The named items
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Named:
    card: str
    study: str | None
    note: str


def load_named(path: Path) -> list[Named]:
    """Read ``config/fulltext_named.yaml``: ``named:`` is a list of ``{card, study, note}``. Raises ValueError."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{path}: cannot read ({exc})") from exc
    items = data.get("named") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"{path}: top level must have a list `named:`")
    out = []
    for i, item in enumerate(items):
        where = f"{path}: named[{i}]"
        if not isinstance(item, dict) or set(item) != {"card", "study", "note"}:
            raise ValueError(f"{where}: must have exactly the keys card, study, note")
        card, study, note = item["card"], item["study"], item["note"]
        if not isinstance(card, str) or not card:
            raise ValueError(f"{where}: card must be a slug")
        if study is not None and not (isinstance(study, str) and study.startswith(("pmid:", "doi:"))):
            raise ValueError(f"{where}: study must be null or an id like pmid:123")
        if not isinstance(note, str) or not note.strip():
            raise ValueError(f"{where}: note must be text")
        out.append(Named(card, study, note.strip()))
    return out


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------


@dataclass
class Row:
    card: str
    study: Study
    category: str
    reason: str
    status: FullTextStatus
    settles: list[str]
    notes: list[str] = field(default_factory=list)

    @property
    def addresses(self) -> list[str]:
        return addresses(self.study, self.status.pmcid)

    @property
    def next_step(self) -> str:
        return next_step(self.status.status, self.study.id)


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    not_listed: int = 0
    errors: list[str] = field(default_factory=list)


def _card_files(cards_dir: Path) -> list[Path]:
    return sorted(p for p in Path(cards_dir).glob("*.yaml") if p.name != CHANGELOG_NAME)


def build_report(cards_dir: Path, named: Sequence[Named], cache_dir: Path) -> Report:
    report = Report()
    cache = CacheReader(Path(cache_dir))
    cards: dict[str, Card] = {}
    failed: set[str] = set()
    for path in _card_files(cards_dir):
        try:
            card = load_card(path)
        except (CardValidationError, OSError) as exc:
            report.errors.append(f"{path.name}: card cannot be loaded: {exc}")
            failed.add(path.stem)
            continue
        cards[card.slug] = card

    for entry in named:
        card = cards.get(entry.card)
        if card is None:
            if entry.card not in failed:
                report.errors.append(f"config names card {entry.card}, which does not exist in {cards_dir}")
        elif entry.study is not None and entry.study not in {s.id for s in card.studies}:
            report.errors.append(f"config names {entry.study} on card {entry.card}, but it is not a study on that card")

    for slug in sorted(cards):
        for study in cards[slug].studies:
            marks = [n.note for n in named if n.card == slug and n.study in (None, study.id)]
            forced = any(n.card == slug and n.study == study.id for n in named)
            try:
                status = study_status(study, cache)
            except (EuropePmcError, OSError) as exc:
                report.errors.append(f"{slug} {study.id}: cached file cannot be read: {exc}")
                continue
            reason, category = carrying_reason(study, status.status), CARRYING
            if reason is None:
                reason, category = unverified_reason(study), UNVERIFIED
            if reason is None and forced:
                reason, category = "no other rule lists it", NAMED
            if reason is None:
                report.not_listed += 1
                continue
            from_abstract = study.case_definition_source == "abstract"
            report.rows.append(
                Row(
                    slug,
                    study,
                    category,
                    reason,
                    status,
                    settles(study, from_abstract),
                    marks,
                )
            )
    return report


def _case_definition(study: Study) -> str:
    return f"{study.case_definition} (source: {study.case_definition_source or 'none'})"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _summary_lines(report: Report) -> list[tuple[str, str]]:
    by_cat = Counter(r.category for r in report.rows)
    by_status = Counter(r.status.status for r in report.rows)
    lines = [("Listed", str(len(report.rows)))]
    lines += [(f"Category {c}", str(by_cat[c])) for c in CATEGORIES]
    lines += [(f"Status {s}", str(by_status[s])) for s in STATUSES]
    lines.append(("Not listed", str(report.not_listed)))
    return lines


def render_text(report: Report) -> str:
    out: list[str] = []
    for slug in sorted({r.card for r in report.rows}):
        out.append(f"== {slug}")
        for r in (r for r in report.rows if r.card == slug):
            s = r.study
            out.append(f"{s.id}  role: {s.role}  case definition: {_case_definition(s)}")
            out.append(f"  category: {r.category}: {r.reason}")
            for note in r.notes:
                out.append(f"  {NAMED_LABEL}: {note}")
            out.append(f"  full text would settle: {'; '.join(r.settles) or 'nothing specific recorded'}")
            out.append(f"  status: {r.status.status}")
            out.append(f"  next step: {r.next_step}")
            out.append(f"  addresses: {' '.join(r.addresses) or 'none'}")
        out.append("")
    out.append("Summary")
    out += [f"  {label}: {value}" for label, value in _summary_lines(report)]
    return "\n".join(out)


def render_markdown(report: Report) -> str:
    out: list[str] = ["# Full-text targets", ""]
    columns = ["Study", "Role", "Case definition", "Category and reason", "Full text would settle"]
    columns += ["Status", "Next step", "Addresses"]
    head = "| " + " | ".join(columns) + " |"
    for slug in sorted({r.card for r in report.rows}):
        out += [f"## {slug}", "", head, "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in (r for r in report.rows if r.card == slug):
            category = f"{r.category}: {r.reason}"
            if r.notes:
                category += "; " + "; ".join(f"{NAMED_LABEL}: {n}" for n in r.notes)
            cells = [
                f"`{r.study.id}`",
                r.study.role,
                _case_definition(r.study),
                category,
                "; ".join(r.settles) or "nothing specific recorded",
                f"`{r.status.status}`",
                r.next_step,
                " ".join(f"<{a}>" for a in r.addresses) or "none",
            ]
            out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        out.append("")
    out += ["## Summary", "", "| Item | Count |", "| --- | --- |"]
    out += [f"| {label} | {value} |" for label, value in _summary_lines(report)]
    return "\n".join(out)


def run_needs(args: argparse.Namespace) -> int:
    try:
        named = load_named(args.config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = build_report(args.cards_dir, named, args.cache_dir)
    print(render_markdown(report) if args.markdown else render_text(report))
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if report.errors else 0


# ---------------------------------------------------------------------------
# import-saved
# ---------------------------------------------------------------------------


def run_import_saved(args: argparse.Namespace) -> int:
    def refuse(message: str) -> int:
        print(f"refused: pmid:{args.pmid}: {message}; nothing written", file=sys.stderr)
        return 1

    pmid = args.pmid
    if not pmid.isdigit():
        return refuse("the PMID must be digits")
    try:
        card = load_card(args.card)
    except (CardValidationError, OSError) as exc:
        return refuse(f"the card {args.card} cannot be loaded ({exc})")
    if f"pmid:{pmid}" not in {s.id for s in card.studies}:
        return refuse(f"it is not a pmid: study on the card {args.card}")

    found = [p for p in (args.saved_dir / f"{pmid}.html", args.saved_dir / f"{pmid}.htm") if p.is_file()]
    if not found:
        return refuse(f"no saved page: put it at {args.saved_dir / f'{pmid}.html'} (or .htm)")
    if len(found) == 2:
        return refuse(f"both {found[0].name} and {found[1].name} exist; keep one")

    cache = CacheReader(args.cache_dir)
    try:
        lookup = read_cached_lookup(cache.epmc, pmid)
        pmcid = lookup.pmcid if lookup else None
        if pmcid is None:
            record = cache.record(pmid)
            pmcid = record.pmcid if isinstance(record, PubMedRecord) else None
        if pmcid is None:
            return refuse("no PMC id is known (no cached Europe PMC lookup or PubMed record names one)")
        xml, page = cache.epmc.fulltext_path(pmcid), cache.epmc.page_path(pmcid)
        if xml.is_file() and not is_placeholder_fulltext(xml.read_bytes()):
            return refuse(f"{pmcid} already has full text cached at {xml}")
        if page.is_file():
            return refuse(f"{pmcid} already has a page cached at {page}")
        content = found[0].read_bytes()
        parse_pmc_page(content, pmid)
        candidates = find_case_definitions_in_page(content)
    except (EuropePmcError, OSError) as exc:
        return refuse(str(exc))
    cache.epmc.write(page, content)
    print(f"pmid:{pmid}  {pmcid}  stored {page}  {len(candidates)} candidate sentence(s)")
    _print_candidates(candidates)
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.fulltext", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    needs = sub.add_parser("needs", help="list the studies whose full text would settle something (offline)")
    needs.add_argument("--markdown", action="store_true", help="print Markdown tables instead of text")
    needs.add_argument("--cards-dir", type=Path, default=DEFAULT_CARDS_DIR, help="default: %(default)s")
    needs.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="default: %(default)s")
    needs.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    imp = sub.add_parser("import-saved", help="store a PMC article page saved by hand in the cache")
    imp.add_argument("--card", type=Path, required=True, help="the card or draft that cites the study")
    imp.add_argument("--pmid", required=True, help="digits only")
    imp.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    imp.add_argument("--saved-dir", type=Path, default=DEFAULT_SAVED_DIR, help="default: %(default)s")
    plan = sub.add_parser("scan-plan", help="full-text scan, step 0 and the scan contexts (offline; writes into --out)")
    plan.add_argument("--out", type=Path, required=True, help="the run folder")
    plan.add_argument("--cards-dir", type=Path, default=DEFAULT_CARDS_DIR, help="default: %(default)s")
    plan.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT, help="default: %(default)s")
    plan.add_argument("--carrying-only", action="store_true", help="only the `carrying` category of `needs`")
    plan.add_argument("--study", nargs="+", action="extend", default=[], help="only these study ids")
    plan.add_argument("--config", type=Path, default=None, help="a `needs` config file; its named studies are added")
    rec = sub.add_parser("scan-record", help="validate the scan files and write the result, report and requests")
    rec.add_argument("--out", type=Path, required=True, help="the run folder of `scan-plan`")
    return parser


def run_scan_plan(args: argparse.Namespace) -> int:
    from me_atlas import fulltext_scan

    try:
        named = load_named(args.config) if args.config else []
        result = fulltext_scan.scan_plan(
            args.out,
            args.cache_dir,
            args.cards_dir,
            carrying_only=args.carrying_only,
            study_ids=args.study,
            named=named,
        )
    except (ValueError, CardValidationError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    counts = Counter(s["step0"] for s in result.studies)
    print(f"scan-plan: {len(result.studies)} stud(ies) in {args.out}")
    print("  step 0: " + ", ".join(f"{label} {counts[label]}" for label in fulltext_scan.LABELS))
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if result.errors else 0


def run_scan_record(args: argparse.Namespace) -> int:
    from me_atlas import fulltext_scan

    try:
        record = fulltext_scan.record_scan(args.out)
        path = fulltext_scan.write_record(args.out, record)
    except (fulltext_scan.ScanError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(record.report.rstrip())
    print(f"scan-record: wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "needs":
        return run_needs(args)
    if args.command == "scan-plan":
        return run_scan_plan(args)
    if args.command == "scan-record":
        return run_scan_record(args)
    return run_import_saved(args)


if __name__ == "__main__":
    raise SystemExit(main())
