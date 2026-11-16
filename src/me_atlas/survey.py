"""Survey of the cached PubMed literature: themes without a card, pairs of cards, candidate hypotheses.

Command line (all offline; reads ``data/cache/pubmed/`` and ``config/``; see ``docs/survey.md``)::

    uv run python -m me_atlas.survey check-themes
    uv run python -m me_atlas.survey themes [--suggest SLUG | --context HEADING [--limit N]]
    uv run python -m me_atlas.survey pairs [--unlinked] [--context SLUG-A SLUG-B [--limit N]]
    uv run python -m me_atlas.survey record-candidates FILE --context CONTEXT-FILE
    uv run python -m me_atlas.survey bridge run | validate    (PubMed searches; see me_atlas.bridge)

Code counts and sorts; an agent reads only the context files written here; the founder decides. Nothing here
writes to ``cards/`` or ``drafts/``. Counting uses MeSH headings and whole-word terms only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from me_atlas import cards as cardlib
from me_atlas.map import _card_paths
from me_atlas.pubmed import ParseError, PubMedRecord, parse_xml

# Context files hold at most this many characters of records (the file says how many matching records were cut).
SURVEY_CHAR_BUDGET = 60_000
DEFAULT_LIMIT = 40
MIN_MESH, MAX_MESH, MAX_TERMS, MAX_RELATED = 1, 6, 4, 8
# Counts of original studies since this year show which themes are still being studied.
RECENT_FROM_YEAR = 2016
UNASSIGNED = "unassigned"
TOP_N = 60  # --by-domain lists every unassigned heading among this many headings with most original studies
DEFAULT_PER_DOMAIN = 3

DEFAULT_CACHE = Path("data/cache/pubmed")
DEFAULT_CARDS = Path("cards")
DEFAULT_DRAFTS = Path("drafts")
DEFAULT_THEMES = Path("config/card_themes.yaml")
DEFAULT_STOPLIST = Path("config/survey_stoplist.txt")
DEFAULT_DOMAINS = Path("config/survey_domains.yaml")
DEFAULT_CANDIDATES = Path("docs/pm/candidates.md")

REVIEW = "Review"
NOT_ORIGINAL = frozenset({"Letter", "Comment", "Case Reports"})
# A record with none of these publication types is an original study.
REVIEW_LIKE = frozenset({REVIEW, "Systematic Review", "Meta-Analysis"})
NOT_AN_ORIGINAL = REVIEW_LIKE | NOT_ORIGINAL | {"Editorial"}
CASE_DEFINITION_VALUES = (
    "Fukuda",
    "CCC",
    "ICC",
    "IOM2015",
    "Oxford",
    "Holmes1988",
    "CDC_unspecified",
    "unverified",
    "none",
    "other",
)
AGENT_KEYS = {"heading", "candidates"}
CANDIDATE_KEYS = {
    "name",
    "mechanism",
    "fits_existing_card",
    "cohort_studies",
    "reviews",
    "meets_inclusion_rule_on_abstracts",
    "why",
}
STUDY_KEYS = {"pmid", "case_definition_in_abstract", "n", "finding"}


class SurveyError(Exception):
    """Something the user must fix; the message says what."""


# ---------------------------------------------------------------------------
# Cache, stoplist, records
# ---------------------------------------------------------------------------


def load_records(cache: Path) -> tuple[list[PubMedRecord], int]:
    """Every parsable cached record (through ``pubmed.parse_xml``) and the number of files that failed."""
    if not cache.is_dir():
        raise SurveyError(f"cache directory not found: {cache}")
    records: list[PubMedRecord] = []
    failed = 0
    for path in sorted(cache.glob("*.xml")):
        try:
            records.append(parse_xml(path.read_bytes()))
        except (ParseError, OSError) as exc:
            failed += 1
            print(f"warning: cannot parse {path.name}: {exc}", file=sys.stderr)
    if failed:
        print(f"warning: {failed} cached file(s) could not be parsed and are left out", file=sys.stderr)
    return records, failed


def load_stoplist(path: Path) -> set[str]:
    """Headings (case-folded) from a file with one heading per line; ``#`` comments and blank lines are ignored."""
    if not path.is_file():
        print(f"warning: no stoplist at {path}; no heading is dropped", file=sys.stderr)
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line.casefold())
    return out


def is_review(r: PubMedRecord) -> bool:
    return REVIEW in r.publication_types


def is_minor(r: PubMedRecord) -> bool:
    """A letter, comment or case report."""
    return bool(NOT_ORIGINAL & set(r.publication_types))


def is_review_like(r: PubMedRecord) -> bool:
    return bool(REVIEW_LIKE & set(r.publication_types))


def is_original(r: PubMedRecord) -> bool:
    return not NOT_AN_ORIGINAL & set(r.publication_types)


def _newest(years: Iterable[int | None]) -> int | None:
    known = [y for y in years if y is not None]
    return max(known) if known else None


def _pmid_sort(pmids: Iterable[str]) -> list[str]:
    return sorted(set(pmids), key=lambda p: (len(p), p))


def heading_slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.casefold()).strip("-") or "heading"


# ---------------------------------------------------------------------------
# Theme file
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardTheme:
    mesh: tuple[str, ...]
    terms: tuple[str, ...]
    related: tuple[str, ...] = ()


@dataclass
class Themes:
    by_slug: dict[str, CardTheme] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def claimed(self) -> set[str]:
        return {h.casefold() for t in self.by_slug.values() for h in t.mesh}

    def near(self, heading: str) -> list[str]:
        """The cards that name this heading as ``related``, sorted."""
        key = heading.casefold()
        return sorted(slug for slug, t in self.by_slug.items() if key in {h.casefold() for h in t.related})


def _string_list(value: object, where: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{where}: must be a list")
        return []
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{where}[{i}]: must be a non-empty string")
        else:
            out.append(item.strip())
    return out


def load_themes(path: Path, card_slugs: Iterable[str], stoplist: set[str] | None = None) -> Themes:
    """Read and validate the theme file against the slugs of the cards in cards/ and drafts/."""
    slugs = set(card_slugs)
    if not path.is_file():
        raise SurveyError(f"theme file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SurveyError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SurveyError(f"{path}: top level must be a mapping of card slug to {{mesh, terms}}")
    errors: list[str] = []
    themes = Themes()
    for slug, entry in data.items():
        where = f"{path}: {slug}"
        if slug not in slugs:
            errors.append(f"{where}: no card with this slug in cards/ or drafts/")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping with 'mesh' and 'terms'")
            continue
        for key in entry:
            if key not in ("mesh", "terms", "related"):
                errors.append(f"{where}: unknown key '{key}'")
        mesh = _string_list(entry.get("mesh", []), f"{where}.mesh", errors)
        terms = _string_list(entry.get("terms", []), f"{where}.terms", errors)
        related = _string_list(entry.get("related", []), f"{where}.related", errors)
        if len(related) > MAX_RELATED:
            errors.append(f"{where}.related: at most {MAX_RELATED} headings, found {len(related)}")
        if not MIN_MESH <= len(mesh) <= MAX_MESH:
            errors.append(f"{where}.mesh: needs {MIN_MESH} to {MAX_MESH} headings, found {len(mesh)}")
        if len(terms) > MAX_TERMS:
            errors.append(f"{where}.terms: at most {MAX_TERMS} terms, found {len(terms)}")
        themes.by_slug[slug] = CardTheme(tuple(mesh), tuple(terms), tuple(related))
    for slug in sorted(slugs - set(data)):
        errors.append(f"{path}: card '{slug}' has no entry")
    mesh_owner = {h.casefold(): slug for slug, t in themes.by_slug.items() for h in t.mesh}
    for slug, theme in themes.by_slug.items():
        for h in theme.related:
            if h.casefold() in mesh_owner:
                errors.append(
                    f"{path}: {slug}.related: '{h}' is in the mesh list of card '{mesh_owner[h.casefold()]}'; "
                    "a heading is either covered or near a card"
                )
            if stoplist and h.casefold() in stoplist:
                errors.append(f"{path}: {slug}.related: '{h}' is in the stoplist")
    if errors:
        raise SurveyError("\n".join(errors))
    owners: dict[str, list[str]] = {}
    for slug, theme in themes.by_slug.items():
        for h in theme.mesh:
            owners.setdefault(h.casefold(), []).append(slug)
    for h, who in sorted(owners.items()):
        who = sorted(set(who))
        if len(who) > 1:
            themes.warnings.append(f"MeSH heading '{h}' is claimed by {' and '.join(who)}")
    return themes


@dataclass(frozen=True)
class Domain:
    key: str
    label: str
    survey: bool
    headings: tuple[str, ...]


def load_domains(path: Path, stoplist: set[str], claimed: set[str]) -> list[Domain]:
    """The domain file, in file order. Errors name the heading or key at fault."""
    if not path.is_file():
        raise SurveyError(f"domain file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SurveyError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SurveyError(f"{path}: top level must be a mapping of domain key to {{label, survey, headings}}")
    errors: list[str] = []
    domains: list[Domain] = []
    seen: dict[str, str] = {}
    for key, entry in data.items():
        where = f"{path}: {key}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping with 'label', 'survey' and 'headings'")
            continue
        errors.extend(f"{where}: unknown key '{k}'" for k in entry if k not in ("label", "survey", "headings"))
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"{where}.label: must be a non-empty string")
        if not isinstance(entry.get("survey"), bool):
            errors.append(f"{where}.survey: must be true or false")
        headings = _string_list(entry.get("headings", []), f"{where}.headings", errors)
        for h in headings:
            low = h.casefold()
            if low in seen:
                errors.append(f"{where}: heading '{h}' is also in domain '{seen[low]}'")
            seen.setdefault(low, key)
            if low in stoplist:
                errors.append(f"{where}: heading '{h}' is in the stoplist")
            if low in claimed:
                errors.append(f"{where}: heading '{h}' is in the mesh list of a card")
        domains.append(Domain(str(key), str(label), entry.get("survey") is True, tuple(headings)))
    if errors:
        raise SurveyError("\n".join(errors))
    return domains


def _slugs(cards_dir: Path, drafts_dir: Path) -> list[str]:
    return [p.stem for p in _card_paths(cards_dir, drafts_dir)]


def _themes_for(args: argparse.Namespace) -> Themes:
    stoplist = load_stoplist(args.stoplist) if args.stoplist.is_file() else None
    themes = load_themes(args.themes, _slugs(args.cards, args.drafts), stoplist)
    for w in themes.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return themes


# ---------------------------------------------------------------------------
# Context files (shared by themes --context and pairs --context)
# ---------------------------------------------------------------------------


def _group(r: PubMedRecord) -> int:
    if is_minor(r) or not r.abstract:
        return 2  # listed by title only
    return 0 if is_review_like(r) else 1


def _order(records: Iterable[PubMedRecord], first: Callable[[PubMedRecord], bool] | None = None) -> list[PubMedRecord]:
    """Reviews with an abstract, then original studies with one, newest first; the title-only records last."""
    return sorted(
        records,
        key=lambda r: (not (first and first(r)), _group(r), -(r.year or 0), len(r.pmid), r.pmid),
    )


def _full_entry(r: PubMedRecord, notes: list[str]) -> str:
    lines = [
        f"## {r.id}: {r.title}",
        "",
        f"- year: {r.year if r.year is not None else 'not stated'}",
        f"- publication types: {', '.join(r.publication_types) or 'not stated'}",
        f"- MeSH headings: {'; '.join(r.mesh_terms) or 'none'}",
    ]
    lines += [f"- {n}" for n in notes]
    lines += ["", "Abstract:", "", r.abstract or "", ""]
    return "\n".join(lines) + "\n"


def _title_entry(r: PubMedRecord, notes: list[str]) -> str:
    kinds = ", ".join(r.publication_types) or "no publication type"
    extra = "".join(f"; {n}" for n in notes)
    no_abs = "" if r.abstract else "; no abstract"
    return f"- {r.id} ({r.year if r.year is not None else 'year not stated'}) {r.title} [{kinds}{no_abs}{extra}]\n"


def render_context(
    title: str,
    intro: Sequence[str],
    records: Sequence[PubMedRecord],
    *,
    limit: int = DEFAULT_LIMIT,
    budget: int | None = None,
    notes: Callable[[PubMedRecord], list[str]] | None = None,
    first: Callable[[PubMedRecord], bool] | None = None,
) -> str:
    """The one file an agent reads. Stops at ``limit`` records or ``budget`` characters; says how many it left out."""
    budget = SURVEY_CHAR_BUDGET if budget is None else budget
    ordered = _order(records, first)
    shown: list[tuple[PubMedRecord, str]] = []
    used = 0
    for r in ordered:
        if len(shown) >= limit:
            break
        text = (_title_entry if _group(r) == 2 else _full_entry)(r, notes(r) if notes else [])
        if used + len(text) > budget:
            break
        shown.append((r, text))
        used += len(text)
    left_out = len(ordered) - len(shown)
    parts = [
        f"# {title}",
        "",
        *intro,
        "",
        f"Matching records: {len(ordered)}. Shown: {len(shown)}. "
        f"Left out: {left_out} matching record(s) (limit {limit} records, budget {budget} characters).",
        "",
        ("Records marked core come first. " if first else "")
        + "Within each part, reviews come first, then original studies, newest first. Cite only the ids in this file; "
        "if something is not here, it is not known.",
        "",
    ]
    body = ""
    title_only_started = False
    for r, text in shown:
        if _group(r) == 2 and not title_only_started:
            body += "Listed by title only (letters, comments, case reports and records without an abstract):\n\n"
            title_only_started = True
        body += text
    return "\n".join(parts) + "\n" + body


def _write_context(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path}")


# ---------------------------------------------------------------------------
# themes
# ---------------------------------------------------------------------------


@dataclass
class HeadingStats:
    heading: str
    pmids: list[str] = field(default_factory=list)
    reviews: int = 0
    minor: int = 0
    newest: int | None = None
    originals: int = 0
    recent: int = 0
    domain: str = UNASSIGNED
    near: list[str] = field(default_factory=list)

    @property
    def records(self) -> int:
        return len(self.pmids)


def count_headings(records: Iterable[PubMedRecord]) -> dict[str, HeadingStats]:
    stats: dict[str, HeadingStats] = {}
    for r in records:
        for h in set(r.mesh_terms):
            s = stats.setdefault(h, HeadingStats(h))
            s.pmids.append(r.pmid)
            s.reviews += is_review(r)
            s.minor += is_minor(r)
            if is_original(r):
                s.originals += 1
                s.recent += (r.year or 0) >= RECENT_FROM_YEAR
            s.newest = _newest([s.newest, r.year])
    return stats


def uncovered_headings(records: Iterable[PubMedRecord], stoplist: set[str], claimed: set[str]) -> list[HeadingStats]:
    """Headings not on the stoplist and not claimed by a card, most original studies first, then by name."""
    dropped = stoplist | claimed
    found = [s for h, s in count_headings(records).items() if h.casefold() not in dropped]
    for s in found:
        s.pmids = _pmid_sort(s.pmids)
    return sorted(found, key=lambda s: (-s.originals, s.heading))


def cited_pmids(card: cardlib.Card) -> list[str]:
    return [s.id.removeprefix("pmid:") for s in card.studies if s.id.startswith("pmid:")]


def suggest_headings(card: cardlib.Card, by_pmid: dict[str, PubMedRecord]) -> tuple[list[tuple[str, int]], list[str]]:
    """MeSH headings of the records the card cites, by count; and the cited PMIDs that are not in the cache."""
    counts: Counter[str] = Counter()
    missing: list[str] = []
    for pmid in cited_pmids(card):
        r = by_pmid.get(pmid)
        if r is None:
            missing.append(pmid)
            continue
        counts.update(set(r.mesh_terms))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])), missing


def _load_card_by_slug(args: argparse.Namespace, slug: str) -> cardlib.Card:
    for p in _card_paths(args.cards, args.drafts):
        if p.stem == slug:
            try:
                return cardlib.load_card(p)
            except cardlib.CardValidationError as exc:
                raise SurveyError(f"{p}: {exc}") from exc
    raise SurveyError(f"no card '{slug}' in {args.cards} or {args.drafts}")


def near_block(args: argparse.Namespace, slugs: Sequence[str]) -> list[str]:
    """The "Near existing cards" block of a context file: slug, name and core claim, read from the card files."""
    paths = {p.stem: p for p in _card_paths(args.cards, args.drafts)}
    lines = [
        "## Near existing cards",
        "",
        "These cards name this heading as near their theme. If the records below belong on one of them rather than "
        "on a new card, set `fits_existing_card` to its slug.",
        "",
    ]
    for slug in slugs:
        try:
            card = cardlib.load_card(paths[slug])
        except (KeyError, cardlib.CardValidationError) as exc:
            raise SurveyError(f"cannot read card '{slug}' for the near block: {exc}") from exc
        lines.append(f"- `{slug}` ({card.name}): {card.core_claim.text}")
    return lines


def print_by_domain(rows: list[HeadingStats], domains: list[Domain], per_domain: int) -> dict[str, list[str]]:
    """Print the balanced selection; return the selected headings by domain key."""
    selection: dict[str, list[str]] = {}
    for d in domains:
        if not d.survey:
            continue
        top = [r for r in rows if r.domain == d.key][:per_domain]
        selection[d.key] = [r.heading for r in top]
        print(f"{d.key} ({d.label}): top {per_domain} by original studies")
        for r in top:
            print(f"  {r.originals:5d} {r.recent:5d}  {r.heading}")
        if not top:
            print("  none")
    print()
    print("Not selected (not surveyed):")
    for d in domains:
        if not d.survey:
            n = sum(1 for r in rows if r.domain == d.key)
            print(f"  {d.key} ({d.label}): {n} headings in the census")
    print()
    print(f"Unassigned headings among the top {TOP_N} by original studies:")
    loose = [r for r in rows[:TOP_N] if r.domain == UNASSIGNED]
    for r in loose:
        print(f"  {r.originals:5d} {r.recent:5d}  {r.heading}")
    if not loose:
        print("  none")
    return selection


def cmd_themes(args: argparse.Namespace) -> int:
    records, _ = load_records(args.cache)
    stoplist = load_stoplist(args.stoplist)
    if args.suggest:
        card = _load_card_by_slug(args, args.suggest)
        by_pmid = {r.pmid: r for r in records}
        found, missing = suggest_headings(card, by_pmid)
        for pmid in missing:
            print(f"warning: cited pmid:{pmid} is not in the cache", file=sys.stderr)
        print(
            f"MeSH headings of the cached records that '{card.slug}' cites ({len(cited_pmids(card)) - len(missing)}):"
        )
        for h, n in found:
            print(f"{n:4d}  {h}" + ("  (stoplist)" if h.casefold() in stoplist else ""))
        return 0
    themes: Themes | None = None
    if args.themes.is_file():
        themes = _themes_for(args)
    else:
        print(f"warning: no theme file at {args.themes}; no heading counts as covered", file=sys.stderr)
    claimed = themes.claimed() if themes else set()
    if args.context:
        match = next((h for h in count_headings(records) if h.casefold() == args.context.casefold()), None)
        if match is None:
            raise SurveyError(f"no cached record has the MeSH heading '{args.context}'")
        chosen = [r for r in records if match in r.mesh_terms]
        intro = [f"Cached PubMed records with the MeSH heading '{match}'. This heading is not claimed by any card."]
        near = themes.near(match) if themes else []
        if near:
            intro += ["", *near_block(args, near)]
        text = render_context(f"Context: MeSH heading '{match}'", intro, chosen, limit=args.limit)
        _write_context(args.out / "context" / f"{heading_slug(match)}.md", text)
        return 0
    domains: list[Domain] = []
    if args.domains.is_file():
        domains = load_domains(args.domains, stoplist, claimed)
    elif args.by_domain:
        raise SurveyError(f"domain file not found: {args.domains}")
    else:
        print(f"warning: no domain file at {args.domains}; every heading is unassigned", file=sys.stderr)
    domain_of = {h.casefold(): d.key for d in domains for h in d.headings}
    rows = uncovered_headings(records, stoplist, claimed)
    for r in rows:
        r.domain = domain_of.get(r.heading.casefold(), UNASSIGNED)
        r.near = themes.near(r.heading) if themes else []
    selection: dict[str, list[str]] | None = None
    if args.by_domain:
        selection = print_by_domain(rows, domains, args.per_domain)
    else:
        print(
            f"{'records':>7} {'reviews':>7} {'letters etc.':>12} {'originals':>9} "
            f"{'since ' + str(RECENT_FROM_YEAR):>10} {'newest':>6}  {'domain':<25} {'near':<24} heading"
        )
        for s in rows:
            print(
                f"{s.records:7d} {s.reviews:7d} {s.minor:12d} {s.originals:9d} {s.recent:10d} {s.newest or '-':>6}  "
                f"{s.domain:<25} {','.join(s.near) or '-':<24} {s.heading}"
            )
    args.out.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "recent_from_year": RECENT_FROM_YEAR,
        "headings": [
            {
                "heading": s.heading,
                "records": s.records,
                "reviews": s.reviews,
                "letters_comments_case_reports": s.minor,
                "originals": s.originals,
                "originals_recent": s.recent,
                "domain": s.domain,
                "near": s.near,
                "newest_year": s.newest,
                "pmids": s.pmids,
            }
            for s in rows
        ],
    }
    if selection is not None:
        payload["selection"] = selection
    (args.out / "themes.json").write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'themes.json'}", file=sys.stderr)
    return 0


def cmd_check_themes(args: argparse.Namespace) -> int:
    themes = _themes_for(args)
    print(f"OK: {len(themes.by_slug)} cards in {args.themes}")
    return 0


# ---------------------------------------------------------------------------
# pairs
# ---------------------------------------------------------------------------


def term_regex(term: str) -> re.Pattern[str]:
    """The term as a whole word (or phrase), case-insensitive: not inside a longer word."""
    return re.compile(rf"(?<!\w){re.escape(term.strip())}(?!\w)", re.IGNORECASE)


class Matcher:
    def __init__(self, theme: CardTheme):
        self.mesh = {h.casefold() for h in theme.mesh}
        self.terms = [term_regex(t) for t in theme.terms]

    def matches(self, r: PubMedRecord) -> bool:
        if any(m.casefold() in self.mesh for m in r.mesh_terms):
            return True
        if not self.terms:
            return False
        text = f"{r.title}\n{r.abstract or ''}"
        return any(t.search(text) for t in self.terms)

    def core(self, r: PubMedRecord) -> bool:
        """The card is the record's main subject: one of its headings is a major topic, or a term is in the title."""
        if any(m.casefold() in self.mesh for m in r.mesh_major):
            return True
        return any(t.search(r.title) for t in self.terms)


def link_status(a: cardlib.Card, b: cardlib.Card) -> str:
    ab = any(link.to == b.slug for link in a.links)
    ba = any(link.to == a.slug for link in b.links)
    if ab and ba:
        return "both"
    if ab:
        return "a->b"
    if ba:
        return "b->a"
    return "none"


@dataclass
class PairStats:
    a: str
    b: str
    link: str
    records: list[PubMedRecord] = field(default_factory=list)
    core_records: list[PubMedRecord] = field(default_factory=list)  # of any type; a subset of ``records``

    @property
    def originals(self) -> list[PubMedRecord]:
        return [r for r in self.records if is_original(r)]

    @property
    def reviews(self) -> list[PubMedRecord]:
        return [r for r in self.records if is_review_like(r)]

    @property
    def core(self) -> list[PubMedRecord]:
        """Original studies that core-match both cards."""
        return [r for r in self.core_records if is_original(r)]

    @property
    def label(self) -> str | None:
        return "mentions only" if not self.core and self.originals else None

    @property
    def newest(self) -> int | None:
        return _newest(r.year for r in self.records)


def compute_pairs(cards: Sequence[cardlib.Card], themes: Themes, records: Iterable[PubMedRecord]) -> list[PairStats]:
    by_slug = {c.slug: c for c in sorted(cards, key=lambda c: c.slug)}
    matchers = {slug: Matcher(themes.by_slug[slug]) for slug in by_slug}
    pairs = {
        (a, b): PairStats(a, b, link_status(by_slug[a], by_slug[b])) for a, b in itertools.combinations(by_slug, 2)
    }
    for r in records:
        hit = [slug for slug, m in matchers.items() if m.matches(r)]
        core_hit = {slug for slug in hit if matchers[slug].core(r)}
        for a, b in itertools.combinations(hit, 2):  # `hit` follows the sorted slug order
            pairs[(a, b)].records.append(r)
            if a in core_hit and b in core_hit:
                pairs[(a, b)].core_records.append(r)
    return sorted(pairs.values(), key=lambda p: (-len(p.core), -len(p.originals), p.a, p.b))


def _load_cards(args: argparse.Namespace) -> list[cardlib.Card]:
    out = []
    for p in _card_paths(args.cards, args.drafts):
        try:
            out.append(cardlib.load_card(p))
        except cardlib.CardValidationError as exc:
            raise SurveyError(f"{p}: {exc}") from exc
    return out


def cmd_pairs(args: argparse.Namespace) -> int:
    themes = _themes_for(args)
    cards = _load_cards(args)
    records, _ = load_records(args.cache)
    pairs = compute_pairs(cards, themes, records)
    if args.context:
        a, b = args.context
        found = next((p for p in pairs if {p.a, p.b} == {a, b} and a != b), None)
        if found is None:
            raise SurveyError(f"no pair of cards '{a}' and '{b}' (both must be cards with a theme entry)")
        cites = {c.slug: set(cited_pmids(c)) for c in cards}

        core_ids = {r.pmid for r in found.core_records}

        def notes(r: PubMedRecord) -> list[str]:
            who = [s for s in (a, b) if r.pmid in cites[s]]
            out = ["match: core"] if r.pmid in core_ids else []
            return [*out, f"cited by: {', '.join(who) if who else 'neither'}"]

        name = {c.slug: c.name for c in cards}
        text = render_context(
            f"Context: records matching both '{a}' and '{b}'",
            [
                f"Cached PubMed records that match the themes of both cards: {name[a]} (`{a}`) and {name[b]} (`{b}`). "
                f"A record matches a card by one of its MeSH headings or one of its terms in the title or abstract; "
                "it is marked core when the heading is a major topic or a term is in the title.",
                f"Existing link between the two cards: {found.link} (a is `{found.a}`, b is `{found.b}`).",
            ],
            found.records,
            limit=args.limit,
            notes=notes,
            first=lambda r: r.pmid in core_ids,
        )
        _write_context(args.out / "context" / f"{a}--{b}.md", text)
        return 0
    shown = [p for p in pairs if p.link == "none"] if args.unlinked else pairs
    print(f"{'core':>5} {'originals':>9} {'reviews':>7} {'newest':>6}  {'link':<4}  card a / card b")
    for p in shown:
        mark = f"  {p.label}" if p.label else ""
        print(
            f"{len(p.core):5d} {len(p.originals):9d} {len(p.reviews):7d} {p.newest or '-':>6}  {p.link:<4}  "
            f"{p.a} / {p.b}{mark}"
        )
    args.out.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "a": p.a,
            "b": p.b,
            "core": len(p.core),
            "label": p.label,
            "originals": len(p.originals),
            "reviews": len(p.reviews),
            "newest_year": p.newest,
            "link": p.link,
            "pmids": {
                "core": _pmid_sort(r.pmid for r in p.core),
                "originals": _pmid_sort(r.pmid for r in p.originals),
                "reviews": _pmid_sort(r.pmid for r in p.reviews),
                "other": _pmid_sort(r.pmid for r in p.records if not is_original(r) and not is_review_like(r)),
            },
        }
        for p in shown
    ]
    (args.out / "pairs.json").write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'pairs.json'}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# record-candidates
# ---------------------------------------------------------------------------

_CONTEXT_PMID = re.compile(r"^(?:## |- )pmid:(\d+)\b", re.MULTILINE)
GAPS_TITLE = "# Gaps on existing cards"
CANDIDATES_TITLE = "# Candidates"
CANDIDATES_TEMPLATE = f"""{CANDIDATES_TITLE}

Tracked list of candidate hypotheses found by the survey of the cached literature (`docs/survey.md`), and of
records that belong on an existing card. A candidate is not a card: the founder decides which to draft, through
the manual card process. Case definitions below were read from abstracts only and are unverified until a card is
drafted. Status is one of `candidate`, `to draft`, `drafted as <slug>`, `declined: <reason>`; set it by hand.

{GAPS_TITLE}

Records from the survey that fit an existing card; the weekly pipeline or a manual pass can pick them up.
"""


def context_pmids(text: str) -> set[str]:
    return set(_CONTEXT_PMID.findall(text))


def validate_agent_file(data: object, context_ids: set[str], known_slugs: set[str]) -> list[str]:
    """Every problem with an agent's candidate file; empty if it is acceptable."""
    if not isinstance(data, dict):
        return ["top level must be a JSON object"]
    errors = [f"unknown key '{k}'" for k in data if k not in AGENT_KEYS]
    if not isinstance(data.get("heading"), str) or not data["heading"].strip():
        errors.append("'heading' must be a non-empty string")
    cands = data.get("candidates")
    if not isinstance(cands, list):
        return [*errors, "'candidates' must be a list"]

    def banned(where: str, value: object) -> None:
        if isinstance(value, str):
            errors.extend(f"{where}: banned word '{m.group(0)}'" for m in cardlib._BANNED_RE.finditer(value))

    def text_field(where: str, value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{where}: must be a non-empty string")
        banned(where, value)

    def pmid_in_context(where: str, value: object) -> None:
        if not isinstance(value, str) or not value.isdigit():
            errors.append(f"{where}: must be a PMID as a string of digits")
        elif value not in context_ids:
            errors.append(f"{where}: pmid {value} is not in the context file")

    for i, c in enumerate(cands):
        at = f"candidates[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{at}: must be an object")
            continue
        errors.extend(f"{at}: unknown key '{k}'" for k in c if k not in CANDIDATE_KEYS)
        errors.extend(f"{at}: missing key '{k}'" for k in sorted(CANDIDATE_KEYS - set(c)))
        for key in ("name", "mechanism", "why"):
            if key in c:
                text_field(f"{at}.{key}", c[key])
        fits = c.get("fits_existing_card")
        if fits is not None and fits not in known_slugs:
            errors.append(f"{at}.fits_existing_card: '{fits}' is not a card slug")
        if "meets_inclusion_rule_on_abstracts" in c and not isinstance(c["meets_inclusion_rule_on_abstracts"], bool):
            errors.append(f"{at}.meets_inclusion_rule_on_abstracts: must be true or false")
        studies = c.get("cohort_studies", [])
        if not isinstance(studies, list):
            errors.append(f"{at}.cohort_studies: must be a list")
            studies = []
        for j, s in enumerate(studies):
            sat = f"{at}.cohort_studies[{j}]"
            if not isinstance(s, dict):
                errors.append(f"{sat}: must be an object")
                continue
            errors.extend(f"{sat}: unknown key '{k}'" for k in s if k not in STUDY_KEYS)
            errors.extend(f"{sat}: missing key '{k}'" for k in sorted(STUDY_KEYS - set(s)))
            pmid_in_context(f"{sat}.pmid", s.get("pmid"))
            if s.get("case_definition_in_abstract") not in CASE_DEFINITION_VALUES:
                errors.append(f"{sat}.case_definition_in_abstract: must be one of {', '.join(CASE_DEFINITION_VALUES)}")
            n = s.get("n")
            if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 0):
                errors.append(f"{sat}.n: must be a whole number or null")
            if "finding" in s:
                text_field(f"{sat}.finding", s["finding"])
        reviews = c.get("reviews", [])
        if not isinstance(reviews, list):
            errors.append(f"{at}.reviews: must be a list")
            reviews = []
        for j, p in enumerate(reviews):
            pmid_in_context(f"{at}.reviews[{j}]", p)
    return errors


def _entry_lines(c: dict, heading: str, n_context: int, status: str, date: str) -> list[str]:
    studies = c["cohort_studies"]
    lines = [f"- Source heading: {heading}", f"- Mechanism: {c['mechanism']}"]
    if c["fits_existing_card"]:
        lines.append(f"- Fits existing card: `{c['fits_existing_card']}`")
    lines.append(f"- Records: {len(studies)} cohort studies, {len(c['reviews'])} reviews (of {n_context} records read)")
    lines.append("- Cohort studies (case definition read from the abstract only):")
    for s in studies:
        n = f"n={s['n']}" if s["n"] is not None else "n not stated"
        lines.append(f"  - pmid:{s['pmid']}: {s['case_definition_in_abstract']}, {n}. {s['finding']}")
    if not studies:
        lines.append("  - none")
    lines.append("- Reviews: " + (", ".join(f"pmid:{p}" for p in c["reviews"]) or "none"))
    lines.append(f"- Meets inclusion rule on abstracts: {'yes' if c['meets_inclusion_rule_on_abstracts'] else 'no'}")
    lines.append(f"- Why: {c['why']}")
    lines.append(f"- Status: {status}")
    lines.append(f"- Date: {date}")
    return lines


def _split_blocks(lines: list[str], marker: str) -> tuple[list[str], list[list[str]]]:
    """Lines before the first one starting with ``marker``, and the blocks that start at each such line."""
    pre: list[str] = []
    blocks: list[list[str]] = []
    for line in lines:
        if line.startswith(marker):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
        else:
            pre.append(line)
    return pre, blocks


def _trim(lines: list[str]) -> list[str]:
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    while out and not out[0].strip():
        out.pop(0)
    return out


def _kept(block: list[str], label: str, default: str) -> str:
    for line in block:
        if line.startswith(f"- {label}: ") or line.startswith(f"  - {label}: "):
            return line.split(": ", 1)[1].strip()
    return default


def update_candidates_text(existing: str | None, agent: dict, n_context: int, today: str) -> str:
    """The candidates file with the agent's candidates added or updated. A hand-set status and the first date stay."""
    text = existing if existing and existing.strip() else CANDIDATES_TEMPLATE
    lines = text.splitlines()
    try:
        cut = next(i for i, line in enumerate(lines) if line.strip() == GAPS_TITLE)
    except StopIteration:
        lines = [*lines, "", GAPS_TITLE, ""]
        cut = len(lines) - 2
    top, bottom = lines[:cut], lines[cut + 1 :]
    cand_pre, cand_blocks = _split_blocks(top, "## ")
    gap_pre, gap_blocks = _split_blocks(bottom, "- ")
    cand_pre, gap_pre = _trim(cand_pre), _trim(gap_pre)
    if not cand_pre:
        cand_pre = [CANDIDATES_TITLE]

    def key_of(block: list[str]) -> str:
        return block[0].lstrip("#- *").rstrip("* ").casefold()

    for c in agent["candidates"]:
        name = c["name"].strip()
        is_gap = bool(c["fits_existing_card"])
        blocks = gap_blocks if is_gap else cand_blocks
        old = next((b for b in blocks if key_of(b) == name.casefold()), None)
        status = _kept(old or [], "Status", "candidate")
        date = _kept(old or [], "Date", today)
        body = _entry_lines(c, agent["heading"], n_context, status, date)
        new = [f"- **{name}**", *("  " + ln for ln in body)] if is_gap else [f"## {name}", "", *body]
        if old is None:
            blocks.append(new)
        else:
            blocks[blocks.index(old)] = new

    out = [*cand_pre, ""]
    for b in cand_blocks:
        out += [*_trim(b), ""]
    out += [GAPS_TITLE, ""]
    if gap_pre:
        out += [*gap_pre, ""]
    for b in gap_blocks:
        out += [*_trim(b), ""]
    return "\n".join(_trim(out)) + "\n"


def cmd_record_candidates(args: argparse.Namespace) -> int:
    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SurveyError(f"cannot read {args.file}: {exc}") from exc
    if not args.context.is_file():
        raise SurveyError(f"context file not found: {args.context}")
    context_text = args.context.read_text(encoding="utf-8")
    ids = context_pmids(context_text)
    errors = validate_agent_file(data, ids, set(_slugs(args.cards, args.drafts)))
    if errors:
        raise SurveyError("\n".join(f"{args.file}: {e}" for e in errors) + "\nnothing was written")
    existing = args.candidates.read_text(encoding="utf-8") if args.candidates.is_file() else None
    new = update_candidates_text(existing, data, len(ids), dt.date.today().isoformat())
    if not data["candidates"]:
        print(f"{args.file}: no candidates for '{data['heading']}'; nothing to record")
        return 0
    args.candidates.parent.mkdir(parents=True, exist_ok=True)
    args.candidates.write_text(new, encoding="utf-8", newline="\n")
    print(f"recorded {len(data['candidates'])} candidate(s) in {args.candidates}")
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.survey", description="Survey of the cached literature.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, cache=False, cards=False, themes=False, out=False, candidates=False):
        if cache:
            p.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="default: %(default)s")
        if cards:
            p.add_argument("--cards", type=Path, default=DEFAULT_CARDS, help="default: %(default)s")
            p.add_argument("--drafts", type=Path, default=DEFAULT_DRAFTS, help="default: %(default)s")
        if themes:
            p.add_argument("--themes", type=Path, default=DEFAULT_THEMES, help="default: %(default)s")
            p.add_argument("--stoplist", type=Path, default=DEFAULT_STOPLIST, help="default: %(default)s")
        if out:
            p.add_argument(
                "--out",
                type=Path,
                default=Path("data/pipeline") / f"{dt.date.today().isoformat()}-survey",
                help="default: %(default)s",
            )
        if candidates:
            p.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES, help="default: %(default)s")

    check = sub.add_parser("check-themes", help="validate the theme file against the cards")
    common(check, cards=True, themes=True)

    th = sub.add_parser("themes", help="count MeSH headings that no card claims")
    common(th, cache=True, cards=True, themes=True, out=True)
    th.add_argument("--domains", type=Path, default=DEFAULT_DOMAINS, help="default: %(default)s")
    th.add_argument("--by-domain", action="store_true", help="the balanced selection: top headings per domain")
    th.add_argument(
        "--per-domain", type=int, default=DEFAULT_PER_DOMAIN, help="headings per survey domain (default: %(default)s)"
    )
    what = th.add_mutually_exclusive_group()
    what.add_argument("--suggest", metavar="SLUG", help="headings of the records this card cites")
    what.add_argument("--context", metavar="HEADING", help="write a context file for this MeSH heading")
    th.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="records in a context file (default: %(default)s)")

    pr = sub.add_parser("pairs", help="records that match two cards, and whether the cards are linked")
    common(pr, cache=True, cards=True, themes=True, out=True)
    pr.add_argument("--unlinked", action="store_true", help="only pairs with no link in either direction")
    pr.add_argument("--context", nargs=2, metavar=("SLUG_A", "SLUG_B"), help="write a context file for this pair")
    pr.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="records in a context file (default: %(default)s)")

    rc = sub.add_parser("record-candidates", help="validate an agent's candidate file and record it")
    rc.add_argument("file", type=Path, help="the agent's JSON file")
    rc.add_argument("--context", type=Path, required=True, help="the context file the agent was given")
    common(rc, cards=True, candidates=True)

    sub.add_parser("bridge", help="bridge search pilot: `bridge run` and `bridge validate` (see `bridge --help`)")
    return parser


def main(argv: Sequence[str] | None = None, **bridge_options) -> int:
    """Entry point. ``survey bridge ...`` goes to ``me_atlas.bridge`` (``bridge_options`` are its test hooks)."""
    words = sys.argv[1:] if argv is None else list(argv)
    if words[:1] == ["bridge"]:
        from me_atlas import bridge

        return bridge.main(words[1:], **bridge_options)
    args = build_parser().parse_args(words)
    handlers = {
        "check-themes": cmd_check_themes,
        "themes": cmd_themes,
        "pairs": cmd_pairs,
        "record-candidates": cmd_record_candidates,
    }
    try:
        return handlers[args.command](args)
    except SurveyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
