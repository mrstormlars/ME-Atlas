"""Bridge search pilot: PubMed searches for systematic reviews of a relation A -> B outside ME/CFS.

Command line (wired in as ``survey bridge``; protocol in ``docs/pm/bridge-pilot.md``, queries in
``config/bridge_pilot.yaml``)::

    uv run python -m me_atlas.survey bridge run [--config FILE] [--cache-dir DIR] [--out DIR]
    uv run python -m me_atlas.survey bridge validate FILE --context CONTEXT-FILE [--cache-dir DIR]

``run`` searches every question and arm, applies the screening limit (protocol point 4), caches the
records under ``<cache-dir>/pubmed/`` and writes ``counts.json`` and one context file per question and arm
to ``<out>``. ``validate`` checks the agent's JSON against the context file and the cached records. The
PubMed requests use ``pubmed.PubMedClient`` (``CONTACT_EMAIL`` required, ``NCBI_API_KEY`` optional).
Nothing here writes to ``cards/``, ``drafts/``, ``content/``, ``translations/`` or ``docs/``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import yaml

from me_atlas import cards as cardlib
from me_atlas.http import load_dotenv
from me_atlas.pubmed import ParseError, PubMedClient, PubMedError, PubMedRecord, RawCache, _text
from me_atlas.survey import DEFAULT_CARDS, SurveyError, context_pmids

SCREEN_LIMIT = 40
ARMS = ("general", "long_covid")
DEFAULT_CONFIG = Path("config/bridge_pilot.yaml")
DEFAULT_BRIDGE_CACHE = Path("data/cache/bridge")

STATEMENTS = ("yes", "no", "animal_or_cell_only")
RELATIONS = ("present", "absent", "inconsistent")
DIRECTIONS = ("a_to_b", "b_to_a", "association", "not_stated")
FILE_KEYS = {"question", "arm", "rows"}
YES_KEYS = {"pmid", "statement", "relation", "population", "direction", "meta_analysis", "studies_pooled", "quote"}
OTHER_KEYS = {"pmid", "statement"}
OPTIONAL_KEYS = {"note"}

_QUESTION_LINE = re.compile(r"^Question: (\S+)\s*$", re.MULTILINE)
_ARM_LINE = re.compile(r"^Arm: (\S+)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config(path: Path) -> list[dict[str, Any]]:
    """The questions of the config file, checked for the keys ``run`` needs."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SurveyError(f"cannot read {path}: {exc}") from exc
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or not questions:
        raise SurveyError(f"{path}: needs a non-empty 'questions' list")
    errors: list[str] = []
    for i, q in enumerate(questions):
        at = f"questions[{i}]"
        if not isinstance(q, dict):
            errors.append(f"{at}: must be a mapping")
            continue
        for key in ("id", "kind", "from", "to"):
            if not isinstance(q.get(key), str) or not q[key].strip():
                errors.append(f"{at}.{key}: must be a non-empty string")
        arms = q.get("arms")
        if not isinstance(arms, dict):
            errors.append(f"{at}.arms: must be a mapping")
            continue
        for arm in ARMS:
            entry = arms.get(arm)
            needed = ("query", "restricted") + (("originals_count",) if arm == "long_covid" else ())
            if not isinstance(entry, dict):
                errors.append(f"{at}.arms.{arm}: missing")
                continue
            for key in needed:
                if not isinstance(entry.get(key), str) or not entry[key].strip():
                    errors.append(f"{at}.arms.{arm}.{key}: must be a non-empty string")
    if errors:
        raise SurveyError("\n".join(f"{path}: {e}" for e in errors))
    return questions


def card_name(cards_dir: Path, slug: str) -> str:
    path = Path(cards_dir) / f"{slug}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return str(data["name"])
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise SurveyError(f"cannot read the name of card '{slug}' from {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Search and screening
# ---------------------------------------------------------------------------


def screen_arm(client: PubMedClient, arm: Mapping[str, Any], *, has_originals: bool) -> dict[str, Any]:
    """Run one arm (protocol point 4): all ids if at most SCREEN_LIMIT, else the restricted form's first ids."""
    first = client.search(arm["query"], retmax=SCREEN_LIMIT)
    warnings = list(first.warnings)
    out: dict[str, Any] = {
        "query": arm["query"],
        "count": first.count,
        "restricted_query": None,
        "restricted_count": None,
        "originals_query": None,
        "originals_count": None,
    }
    if first.count <= SCREEN_LIMIT:
        out["rule"] = "all"
        pmids = first.ids
    else:
        restricted = client.search(arm["restricted"], retmax=SCREEN_LIMIT)
        warnings += restricted.warnings
        out["restricted_query"] = arm["restricted"]
        out["restricted_count"] = restricted.count
        if restricted.count == 0:
            out["rule"] = "fallback_unrestricted"
            pmids = first.ids[:SCREEN_LIMIT]
        else:
            out["rule"] = "restricted"
            pmids = restricted.ids[:SCREEN_LIMIT]
    if has_originals:
        originals = client.search(arm["originals_count"], retmax=0)
        warnings += originals.warnings
        out["originals_query"] = arm["originals_count"]
        out["originals_count"] = originals.count
    out["screened_pmids"] = list(dict.fromkeys(pmids))
    out["warnings"] = warnings
    return out


def cache_records(client: PubMedClient, cache: RawCache, pmids: Sequence[str]) -> list[str]:
    """Download the PMIDs not yet cached; return those that were asked for and are still not cached."""
    wanted = [p for p in dict.fromkeys(pmids) if not cache.has(p)]
    asked = set(wanted)
    for article in client.fetch_articles(wanted):
        pmid = _text(article.find("MedlineCitation/PMID"))
        if pmid in asked:
            cache.write(pmid, article)
    return [p for p in wanted if not cache.has(p)]


# ---------------------------------------------------------------------------
# Context files
# ---------------------------------------------------------------------------


def _entry(r: PubMedRecord) -> str:
    lines = [
        f"## {r.id}",
        "",
        f"Title: {r.title}",
        f"- year: {r.year if r.year is not None else 'not stated'}",
        f"- publication types: {', '.join(r.publication_types) or 'not stated'}",
        f"- MeSH headings: {'; '.join(r.mesh_terms) or 'none'}",
        "",
        "Abstract:",
        "",
        r.abstract or "(no abstract in the record)",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_arm_context(
    question: Mapping[str, Any],
    arm_name: str,
    result: Mapping[str, Any],
    records: Sequence[PubMedRecord],
    unavailable: Sequence[str],
    names: tuple[str, str],
) -> str:
    """The one file the agent reads for one question and arm. Every screened record is listed in full."""
    cut = ", ".join(unavailable) if unavailable else "none"
    restricted = result["restricted_count"]
    header = [
        f"# Bridge context: {question['id']} {arm_name}",
        "",
        f"Question: {question['id']}",
        f"Arm: {arm_name}",
        f"A: {question['from']} ({names[0]})",
        f"B: {question['to']} ({names[1]})",
        f"Query: {result['query']}",
        f"Records found by the query: {result['count']}",
        f"Records found by the restricted query: {'not run' if restricted is None else restricted}",
        f"Screening rule: {result['rule']}",
        f"Screened records listed below: {len(records)}",
        f"Screened but not listed (not in the cache or not readable): {cut}",
        "",
        "Cite only the ids in this file; if something is not here, it is not known. "
        "Records appear in PubMed's default order.",
        "",
    ]
    if not records:
        header.append("No records were screened for this question and arm.")
        header.append("")
    return "\n".join(header) + "\n" + "".join(_entry(r) for r in records)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def run(
    client: PubMedClient,
    questions: Sequence[Mapping[str, Any]],
    cache: RawCache,
    out: Path,
    cards_dir: Path,
    today: dt.date,
) -> dict[str, Any]:
    names = {q["id"]: (card_name(cards_dir, q["from"]), card_name(cards_dir, q["to"])) for q in questions}
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for q in questions:
        for arm in ARMS:
            results[(q["id"], arm)] = screen_arm(client, q["arms"][arm], has_originals=arm == "long_covid")
    all_pmids = [p for r in results.values() for p in r["screened_pmids"]]
    not_cached = set(cache_records(client, cache, all_pmids))

    counts: dict[str, Any] = {
        "date": today.isoformat(),
        "protocol": "docs/pm/bridge-pilot.md",
        "screen_limit": SCREEN_LIMIT,
        "questions": [],
    }
    for q in questions:
        arms_out: dict[str, Any] = {}
        for arm in ARMS:
            result = results[(q["id"], arm)]
            records: list[PubMedRecord] = []
            unavailable: list[str] = []
            for pmid in result["screened_pmids"]:
                try:
                    if pmid in not_cached:
                        raise ParseError("not retrieved")
                    records.append(cache.read_record(pmid))
                except (ParseError, OSError):
                    unavailable.append(pmid)
            text = render_arm_context(q, arm, result, records, unavailable, names[q["id"]])
            path = out / "context" / f"{q['id']}-{arm}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            arms_out[arm] = {**result, "not_listed_pmids": unavailable}
        counts["questions"].append(
            {"id": q["id"], "kind": q["kind"], "from": q["from"], "to": q["to"], "arms": arms_out}
        )
    out.mkdir(parents=True, exist_ok=True)
    (out / "counts.json").write_text(json.dumps(counts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return counts


def cmd_run(
    args: argparse.Namespace,
    env: Mapping[str, str],
    transport: httpx.BaseTransport | None,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    today: dt.date,
) -> int:
    email = (env.get("CONTACT_EMAIL") or "").strip()
    if not email:
        print(
            "error: CONTACT_EMAIL is not set. NCBI requires a contact email; set CONTACT_EMAIL in .env "
            "or the environment (see .env.example). No request was made.",
            file=sys.stderr,
        )
        return 2
    questions = load_config(args.config)
    out = args.out or Path("data/pipeline") / f"{today.isoformat()}-bridge-pilot"
    client = PubMedClient(
        email, (env.get("NCBI_API_KEY") or "").strip() or None, transport=transport, clock=clock, sleep=sleep
    )
    try:
        counts = run(client, questions, RawCache(args.cache_dir), out, args.cards, today)
    finally:
        client.close()
    for q in counts["questions"]:
        for arm, r in q["arms"].items():
            print(f"{q['id']} {arm}: {r['count']} found, {len(r['screened_pmids'])} screened ({r['rule']})")
            for w in r["warnings"]:
                print(f"warning: PubMed says {w} ({q['id']} {arm})", file=sys.stderr)
            if r["not_listed_pmids"]:
                print(f"warning: not listed: {', '.join(r['not_listed_pmids'])} ({q['id']} {arm})", file=sys.stderr)
    print(f"wrote {out / 'counts.json'} and {len(counts['questions']) * len(ARMS)} context files in {out / 'context'}")
    return 0


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    """Whitespace collapsed; nothing else changes (case and punctuation count)."""
    return " ".join(text.split())


def validate_agent_file(data: object, context_text: str, cache: RawCache) -> list[str]:
    """Every problem with an agent's survey file; empty if it is acceptable."""
    if not isinstance(data, dict):
        return ["top level must be a JSON object"]
    errors = [f"unknown key '{k}'" for k in data if k not in FILE_KEYS]
    ids = context_pmids(context_text)
    question = _QUESTION_LINE.search(context_text)
    arm = _ARM_LINE.search(context_text)
    if question is None or arm is None:
        errors.append("the context file has no 'Question:' and 'Arm:' header lines")
    else:
        if data.get("question") != question.group(1):
            errors.append(f"'question' must be {question.group(1)!r} (the context file header)")
        if data.get("arm") != arm.group(1):
            errors.append(f"'arm' must be {arm.group(1)!r} (the context file header)")
    rows = data.get("rows")
    if not isinstance(rows, list):
        return [*errors, "'rows' must be a list"]

    def banned(where: str, value: object) -> None:
        if isinstance(value, str):
            errors.extend(f"{where}: banned word '{m.group(0)}'" for m in cardlib._BANNED_RE.finditer(value))

    seen: set[str] = set()
    for i, row in enumerate(rows):
        at = f"rows[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{at}: must be an object")
            continue
        pmid = row.get("pmid")
        if not isinstance(pmid, str) or not pmid.isdigit():
            errors.append(f"{at}.pmid: must be a PMID as a string of digits")
            pmid = None
        else:
            if pmid not in ids:
                errors.append(f"{at}.pmid: pmid {pmid} is not in the context file")
            if pmid in seen:
                errors.append(f"{at}.pmid: pmid {pmid} is listed twice")
            seen.add(pmid)
        statement = row.get("statement")
        if statement not in STATEMENTS:
            errors.append(f"{at}.statement: must be one of {', '.join(STATEMENTS)}")
            continue
        allowed = (YES_KEYS if statement == "yes" else OTHER_KEYS) | OPTIONAL_KEYS
        errors.extend(f"{at}: unknown key '{k}'" for k in row if k not in allowed)
        if "note" in row:
            if not isinstance(row["note"], str):
                errors.append(f"{at}.note: must be a string")
            banned(f"{at}.note", row["note"])
        if statement != "yes":
            continue
        errors.extend(f"{at}: missing key '{k}'" for k in sorted(YES_KEYS - set(row)))
        if "relation" in row and row["relation"] not in RELATIONS:
            errors.append(f"{at}.relation: must be one of {', '.join(RELATIONS)}")
        if "direction" in row and row["direction"] not in DIRECTIONS:
            errors.append(f"{at}.direction: must be one of {', '.join(DIRECTIONS)}")
        if "meta_analysis" in row and not isinstance(row["meta_analysis"], bool):
            errors.append(f"{at}.meta_analysis: must be true or false")
        if "studies_pooled" in row:
            n = row["studies_pooled"]
            if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 1):
                errors.append(f"{at}.studies_pooled: must be a whole number of at least 1, or null")
        if "population" in row:
            if not isinstance(row["population"], str) or not row["population"].strip():
                errors.append(f"{at}.population: must be a non-empty string")
            banned(f"{at}.population", row["population"])
        if "quote" in row:
            quote = row["quote"]
            if not isinstance(quote, str) or not quote.strip():
                errors.append(f"{at}.quote: must be a non-empty string")
            elif pmid is not None:
                try:
                    record = cache.read_record(pmid)
                except (FileNotFoundError, ParseError, ValueError):
                    errors.append(
                        f"{at}.quote: the record pmid:{pmid} is not in the cache, so the quote cannot be checked"
                    )
                else:
                    if _norm(quote) not in _norm(record.title) and _norm(quote) not in _norm(record.abstract or ""):
                        errors.append(f"{at}.quote: not found verbatim in the title or abstract of pmid:{pmid}")
    errors.extend(f"pmid {p} is in the context file but has no row" for p in sorted(ids - seen, key=int))
    return errors


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SurveyError(f"cannot read {args.file}: {exc}") from exc
    if not args.context.is_file():
        raise SurveyError(f"context file not found: {args.context}")
    errors = validate_agent_file(data, args.context.read_text(encoding="utf-8"), RawCache(args.cache_dir))
    if errors:
        raise SurveyError("\n".join(f"{args.file}: {e}" for e in errors))
    print(f"{args.file}: OK ({len(data['rows'])} rows)")
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.survey bridge", description="Bridge search pilot.")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="search PubMed for every question and arm, cache records, write context files")
    run_p.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="default: %(default)s")
    run_p.add_argument("--cache-dir", type=Path, default=DEFAULT_BRIDGE_CACHE, help="default: %(default)s")
    run_p.add_argument("--cards", type=Path, default=DEFAULT_CARDS, help="default: %(default)s")
    run_p.add_argument("--out", type=Path, default=None, help="default: data/pipeline/<today>-bridge-pilot")
    val = sub.add_parser("validate", help="check an agent's JSON file against its context file and the cache")
    val.add_argument("file", type=Path, help="the agent's JSON file")
    val.add_argument("--context", type=Path, required=True, help="the context file the agent was given")
    val.add_argument("--cache-dir", type=Path, default=DEFAULT_BRIDGE_CACHE, help="default: %(default)s")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    today: dt.date | None = None,
) -> int:
    """Entry point. ``env``, ``transport``, ``clock``, ``sleep`` and ``today`` are given by tests."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return cmd_validate(args)
        if env is None:
            env = {**load_dotenv(), **os.environ}
        return cmd_run(args, env, transport, clock, sleep, today or dt.date.today())
    except (SurveyError, PubMedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
