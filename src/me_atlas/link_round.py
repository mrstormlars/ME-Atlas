"""A link round on one published card: add the links a ``link-drafter`` proposed, with an audit trail.

The weekly path works per (card, paper) and has no operation that adds a link; a card in ``cards/`` changes only
through the pipeline. A link round is that path for links (``docs/pipeline.md``, "Adding links to a published card").
Everything lives in one run folder ``DIR`` (normally ``data/pipeline/links/<date>-<slug>/``)::

    map/<slug>-r<N>.json          the link-drafter's proposal (round N = 1 or 2)
    ops/<slug>-r<N>.json          the proposal as ``add_link`` operations         (``link-apply``)
    applied/<slug>-r<N>/          the card with the links added, and changes.diff (``link-apply``)
    checks/<slug>-r<N>.json       the card validator and the citations check      (``link-apply``)
    map-review/<slug>-r<N>.json   the card-reviewer's map-mode review             (``record-map-review``)
    audit-context/<slug>-links.md the change audit's context                      (``link-audit-plan``)
    audit/<slug>-links[-second].yaml  the two sequential audits                   (``record-link-audit``)
    link-report.md                the outcome                                     (``link-publish``)

It reuses the helpers of ``me_atlas.pipeline`` (the checks, the audit context and its record validation, the change
log) and changes no rule of the weekly path. ``cards/`` is written by ``link-publish`` only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from me_atlas.cards import NonEmptyStr, Slug, StudyId
from me_atlas.operations import AddLink, OperationError, apply_operations, parse_ops, tiers
from me_atlas.pipeline import (
    _M,
    AuditRecord,
    Config,
    FullTextLoader,
    PipelineError,
    _check_applied,
    _check_error_lines,
    _finish_checks,
    _load_card_audit,
    _pair_hold_reasons,
    _pending_retry,
    _published_card_problems,
    _read_json,
    _record_started,
    _set_last_checked,
    _sibling,
    _write_invalid_copy,
    _write_json,
    _write_text,
    append_changelog_entry,
    build_audit_context,
    pipeline_marker,
    record_audit,
)

ROUNDS = (1, 2)
MAX_TRIES = 3  # failed tries of one round (as the correction rounds' check retries)
LINKS = "links"  # the audit's round tag: audit/<slug>-links.yaml, audit-context/<slug>-links.md
ACCEPT_LOWER_HELD = "the first audit decided accept_lower; a link round changes no level"
REPORT = "link-report.md"
_ITEM = re.compile(r"^links\[(\d+)\]$")


# ---------------------------------------------------------------------------
# The files the agents write
# ---------------------------------------------------------------------------


class ProposedLink(_M):
    to: NonEmptyStr
    support: Literal["proposed", "associated", "directional"]
    text: NonEmptyStr
    sources: Annotated[list[StudyId], Field(min_length=1)]
    why: NonEmptyStr  # for the reviewer; never copied into the ops, the audit context or the trail


class Proposal(_M):
    slug: Slug
    layer: NonEmptyStr | None
    links: list[ProposedLink]


class MapFinding(_M):
    item: str | None
    severity: Literal["must_fix", "advisory"]
    problem: NonEmptyStr
    fix: NonEmptyStr | None = None


class MapReview(_M):
    slug: Slug
    verdict: Literal["accept", "reject"]
    findings: list[MapFinding]

    @model_validator(mode="after")
    def _verdict_fits_findings(self) -> MapReview:
        if self.verdict == "accept" and any(f.severity == "must_fix" for f in self.findings):
            raise ValueError("accept with a must_fix finding is not allowed; the verdict must be reject")
        if self.verdict == "reject" and not self.findings:
            raise ValueError("a reject needs at least one finding saying what is wrong")
        return self


def _lines(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}" for e in exc.errors())


# ---------------------------------------------------------------------------
# Paths and state
# ---------------------------------------------------------------------------


def _check_round(n: int) -> int:
    if n not in ROUNDS:
        raise PipelineError(f"a link round has rounds 1 and 2, not {n}")
    return n


def proposal_path(cfg: Config, slug: str, n: int) -> Path:
    return cfg.f("map", f"{slug}-r{n}.json")


def review_path(cfg: Config, slug: str, n: int) -> Path:
    return cfg.f("map-review", f"{slug}-r{n}.json")


def load_proposal(cfg: Config, slug: str, n: int) -> Proposal:
    """The link-drafter's proposal of round ``n``; PipelineError when it is missing, malformed, for another card or
    has no link."""
    path = proposal_path(cfg, slug, n)
    raw = _read_json(path)
    try:
        proposal = Proposal.model_validate(raw)
    except ValidationError as exc:
        raise PipelineError(f"{path} is malformed: {_lines(exc)}") from exc
    if proposal.slug != slug:
        raise PipelineError(f"{path} is for card '{proposal.slug}', not '{slug}'")
    if not proposal.links:
        raise PipelineError(f"{path} proposes no link; there is nothing to apply")
    return proposal


def _round_checks(cfg: Config, slug: str, n: int) -> dict[str, Any] | None:
    path = cfg.checks_path(slug, None, n)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def last_round(cfg: Config, slug: str) -> int | None:
    """The last round that was applied (it has a checks record), or None."""
    for n in reversed(ROUNDS):
        if cfg.checks_path(slug, None, n).is_file():
            return n
    return None


def load_map_review(cfg: Config, slug: str, n: int) -> tuple[MapReview | None, str | None]:
    """The valid map review of round ``n``, or (None, why it is missing or invalid).

    Valid: the map-mode shape; the verdict fits the findings; every ``item`` is ``null``, ``layer`` or ``links[i]``
    with ``i`` in range of the round's proposal; and the round's checks exist and passed."""
    path = review_path(cfg, slug, n)
    if not path.is_file():
        return None, f"no map review {path.name}"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name} is not readable JSON: {exc}"
    try:
        review = MapReview.model_validate(raw)
    except ValidationError as exc:
        return None, f"{path.name} is malformed: {_lines(exc)}"
    problems: list[str] = []
    if review.slug != slug:
        problems.append(f"slug is '{review.slug}', expected '{slug}'")
    try:
        count = len(load_proposal(cfg, slug, n).links)
    except PipelineError as exc:
        return None, str(exc)
    for i, f in enumerate(review.findings):
        if f.item is None or f.item == "layer":
            continue
        m = _ITEM.match(f.item)
        if m is None or int(m.group(1)) >= count:
            problems.append(
                f"findings[{i}].item {f.item!r} must be null, 'layer' or 'links[i]' with i below {count} "
                f"(the links of the round's proposal)"
            )
    checks = _round_checks(cfg, slug, n)
    if checks is None:
        problems.append(f"round {n} has no checks record; run `link-apply` first")
    elif not checks.get("passed"):
        problems.append(f"the checks of round {n} did not pass; a map review is for a round that passed them")
    if problems:
        return None, f"{path.name} is not valid: " + "; ".join(problems)
    return review, None


def _card_paths(cfg: Config, slug: str) -> tuple[Path, Path]:
    card, draft = cfg.cards_dir / f"{slug}.yaml", cfg.drafts_dir / f"{slug}.yaml"
    if not card.is_file():
        raise PipelineError(f"no published card {card}; a link round is for a card in cards/")
    if draft.exists():
        raise PipelineError(f"{draft} exists; the card has a draft under way and a link round is not run beside it")
    return card, draft


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# link-apply
# ---------------------------------------------------------------------------


def _keep_failed_try(cfg: Config, slug: str, n: int) -> None:
    """The round's last try failed its checks: keep its ops and checks as ``...-r<N>-attempt<i>.json``. At most
    ``MAX_TRIES`` failed tries in all; a passed round is not applied again."""
    checks = cfg.checks_path(slug, None, n)
    kept = sorted(checks.parent.glob(f"{slug}-r{n}-attempt*.json")) if checks.parent.is_dir() else []
    record = _round_checks(cfg, slug, n)
    if record is not None and record.get("passed"):
        raise PipelineError(f"round {n} already passed its checks; it is not applied again")
    failed = len(kept) + (1 if checks.is_file() else 0)
    if failed >= MAX_TRIES:
        raise PipelineError(f"round {n} failed its checks {failed} times; there is no further try")
    if checks.is_file():
        i = len(kept) + 1
        ops = cfg.ops_path(slug, None, n)
        if ops.is_file():
            ops.replace(ops.with_name(f"{slug}-r{n}-attempt{i}.json"))
        checks.replace(checks.with_name(f"{slug}-r{n}-attempt{i}.json"))


def link_apply(cfg: Config, slug: str, n: int) -> dict[str, Any]:
    """Apply the proposal of round ``n`` to a copy of ``cards/<slug>.yaml`` and run the checks. Writes ``ops/``,
    ``applied/`` and ``checks/`` in the run folder; ``cards/`` is never written. Returns the checks record.

    Refusals (PipelineError, nothing written): no card in ``cards/``, a draft beside it, a proposal that is missing,
    malformed, for another card or without a link, a layer other than the card's, a round 2 without a valid round-1
    ``reject``, a round that already has a map review or passed its checks, a round that failed three times."""
    _check_round(n)
    card_path, _draft = _card_paths(cfg, slug)
    proposal = load_proposal(cfg, slug, n)
    base_text = card_path.read_text(encoding="utf-8")
    data = yaml.safe_load(base_text)
    layer = data.get("layer") if isinstance(data, dict) else None
    if proposal.layer != layer:
        raise PipelineError(
            f"the proposal's layer is {proposal.layer!r} and the card's is {layer!r}; a link round does not change "
            "the layer"
        )
    if review_path(cfg, slug, n).exists():
        raise PipelineError(f"round {n} already has a map review ({review_path(cfg, slug, n).name})")
    if n == 2:
        review, why = load_map_review(cfg, slug, 1)
        if review is None or review.verdict != "reject":
            found = review.verdict if review is not None else why
            raise PipelineError(f"round 2 needs a valid reject of the map review of round 1; found: {found}")
    _keep_failed_try(cfg, slug, n)

    operations = [
        {"op": "add_link", "to": x.to, "support": x.support, "text": x.text, "sources": list(x.sources)}
        for x in proposal.links
    ]
    ops_path = cfg.ops_path(slug, None, n)
    _write_json(ops_path, {"card": slug, "paper": None, "operations": operations})
    try:
        ops = parse_ops(json.loads(ops_path.read_text(encoding="utf-8")))
    except OperationError as exc:  # the proposal model has the same shape; unreachable in practice
        raise PipelineError(f"the proposal does not make a valid ops file: {exc}") from exc
    out_dir = cfg.applied_dir(slug, None, n)
    if out_dir.exists():
        shutil.rmtree(out_dir)  # the applied text of an earlier failed try
    op_tiers = tiers(ops, data if isinstance(data, dict) else None)
    result: dict[str, Any] = {
        "card": slug,
        "paper": None,
        "key": None,
        "round": n,
        "ops_file": str(ops_path),
        "ops_errors": [],
        "validator": [],
        "citations": [],
        "applied": None,
        "diff": None,
        "no_change": False,
        "tiers": {str(t): op_tiers.count(t) for t in (1, 2)},
        "warnings": [],
    }
    ops_errors: list[str] = result["ops_errors"]
    new_text: str | None = None
    try:
        new_text = apply_operations(base_text, ops, validate=False)
    except OperationError as exc:
        ops_errors.append(str(exc))
    if new_text is not None:
        _check_applied(cfg, slug, card_path, base_text, new_text, out_dir, result)
    _finish_checks(cfg, result, ops_errors, None, n)
    return result


# ---------------------------------------------------------------------------
# record-map-review
# ---------------------------------------------------------------------------


def record_map_review(cfg: Config, slug: str, n: int) -> MapReview:
    _check_round(n)
    review, why = load_map_review(cfg, slug, n)
    if review is None:
        raise PipelineError(why or "the map review is not valid")
    return review


# ---------------------------------------------------------------------------
# link-audit-plan, record-link-audit
# ---------------------------------------------------------------------------


def _accepted_round(cfg: Config, slug: str) -> int:
    """The last applied round, when its checks passed and its map review is valid and says ``accept``."""
    n = last_round(cfg, slug)
    if n is None:
        raise PipelineError("no round applied; run `link-apply` first")
    checks = _round_checks(cfg, slug, n)
    if checks is None or not checks.get("passed"):
        raise PipelineError(f"the checks of round {n} did not pass")
    review, why = load_map_review(cfg, slug, n)
    if review is None:
        raise PipelineError(f"round {n} has no valid map review: {why}")
    if review.verdict != "accept":
        raise PipelineError(f"the map review of round {n} is a reject; the links are not audited")
    return n


def link_audit_plan(cfg: Config, slug: str, loader: FullTextLoader) -> Path:
    """Write ``audit-context/<slug>-links.md``: the change audit of the last round, built by the code that builds a
    weekly change audit. It holds nothing from the proposal's ``why``, the map review or an earlier audit."""
    _card_paths(cfg, slug)
    n = _accepted_round(cfg, slug)
    text = build_audit_context(cfg, slug, None, loader, applied_round=n)
    path = cfg.audit_context_path(slug, None, LINKS)
    _write_text(path, text)
    return path


def record_link_audit(cfg: Config, slug: str, *, second: bool = False) -> AuditRecord:
    """Validate ``audit/<slug>-links.yaml`` (``-second``) against the context, with the one format retry of the weekly
    path. A second audit needs a valid first one that did not reject (sequential audits)."""
    if not cfg.audit_context_path(slug, None, LINKS).is_file():
        raise PipelineError(
            f"no audit context {cfg.audit_context_path(slug, None, LINKS)}; run `link-audit-plan` first"
        )
    if second:
        first, _path, why = _load_card_audit(cfg, slug, second=False, redraft=LINKS)
        if first is None:
            raise PipelineError(f"a second audit needs a valid first audit record: {why}")
        if first.decision == "reject":
            raise PipelineError("the first audit decided reject; no second audit is run (sequential audits)")
    return record_audit(cfg, slug, None, second=second, file=cfg.audit_path(slug, None, second, LINKS), redraft=LINKS)


# ---------------------------------------------------------------------------
# link-publish
# ---------------------------------------------------------------------------


def _finding_dicts(findings: list[MapFinding]) -> list[dict[str, Any]]:
    return [f.model_dump(mode="json", exclude_none=True) for f in findings]


def _round_trail(cfg: Config, slug: str, n: int) -> dict[str, Any]:
    try:
        proposal = [
            {"to": x.to, "support": x.support, "text": x.text, "sources": list(x.sources)}
            for x in load_proposal(cfg, slug, n).links
        ]
    except PipelineError:
        proposal = []
    record = _round_checks(cfg, slug, n)
    checks = (
        {"passed": bool(record.get("passed")), "errors": _check_error_lines(record)}
        if record is not None
        else {"passed": None, "errors": ["there is no checks record"]}
    )
    review, _why = load_map_review(cfg, slug, n)
    if review is None:
        # an invalid or missing review is recorded as what it is: no verdict
        map_review: dict[str, Any] = {"verdict": None, "findings": []}
    else:
        map_review = {"verdict": review.verdict, "findings": _finding_dicts(review.findings)}
    return {"round": n, "proposal": proposal, "checks": checks, "map_review": map_review}


def _hold_reason(
    cfg: Config,
    slug: str,
    n: int,
    first: AuditRecord | None,
    second: AuditRecord | None,
    first_why: str | None,
    second_why: str | None,
) -> str | None:
    """Why the card is held back, or None when the round, the map review and both audits allow it."""
    checks = _round_checks(cfg, slug, n)
    if checks is None or not checks.get("passed"):
        return "checks failed"
    review, why = load_map_review(cfg, slug, n)
    if review is None:
        return f"no valid map review: {why}"
    if review.verdict != "accept":
        return f"map review rejected in round {n}" + ("" if n == 2 else "; no second round was applied")
    first_path = cfg.audit_path(slug, None, False, LINKS)
    second_path = cfg.audit_path(slug, None, True, LINKS)
    if first is not None and first.decision == "accept_lower":
        return ACCEPT_LOWER_HELD
    second_run = _record_started(second_path)
    final_invalid = first is None and not second_run and _sibling(first_path, ".invalid-2.yaml").is_file()
    reasons = _pair_hold_reasons(
        first, second, first_why, second_why, second_run=second_run, first_invalid_final=final_invalid
    )
    return reasons[0] if reasons else None


def _report(
    slug: str,
    outcome: str,
    reason: str | None,
    links: list[AddLink],
    records: dict[str, AuditRecord],
) -> str:
    lines = [f"# Link round: {slug}", "", f"Outcome: {outcome}"]
    if reason is not None:
        lines.append(f"Held back: {reason}")
    lines += ["", "## Links " + ("added" if reason is None else "proposed (not added)"), ""]
    lines += [f"- {x.to} ({x.support}); sources {', '.join(x.sources)}" for x in links] or ["- none"]
    lines += ["", "## The audits", ""]
    for label, record in records.items():
        level = "" if record.accepted_level is None else f" at level {record.accepted_level}"
        lines += [f"- {label}: {record.decision}{level}", f"  reasons_summary: {record.reasons_summary}"]
    if not records:
        lines.append("- no valid audit record")
    return "\n".join(lines) + "\n"


def link_publish(cfg: Config, slug: str, date: str, *, dry_run: bool, out: Callable[[str], None] = print) -> int:
    """Publish the links of the last round into ``cards/<slug>.yaml`` when every step allows it, else hold the card
    back (both cards files byte-identical). Exit 0 for a decision, PipelineError (exit 1) for a refusal."""
    card_path, _draft = _card_paths(cfg, slug)
    n = last_round(cfg, slug)
    if n is None:
        raise PipelineError("no round applied; run `link-apply` first")
    first, first_path, first_why = _load_card_audit(cfg, slug, second=False, redraft=LINKS)
    second, second_path, second_why = _load_card_audit(cfg, slug, second=True, redraft=LINKS)
    if first is None and (pending := _pending_retry(first_path)) is not None:
        raise PipelineError(pending.replace("record-audit --card ... --retry", "record-link-audit"))
    invalid = _sibling(first_path, ".invalid-2.yaml")
    invalid_copy = invalid if first is None and not _record_started(second_path) and invalid.is_file() else None
    records: dict[str, tuple[Path, AuditRecord]] = {}
    if first is not None:
        records[""] = (first_path, first)
    if second is not None:
        records["-second"] = (second_path, second)
    copies = [(src, cfg.audits_dir / f"{date}-{slug}-{LINKS}{suffix}.yaml") for suffix, (src, _r) in records.items()]
    invalid_copies = (
        [] if invalid_copy is None else [(invalid_copy, cfg.audits_dir / f"{date}-{slug}-{LINKS}-invalid.yaml")]
    )
    trail_path = cfg.audits_dir / f"{date}-{slug}-{LINKS}-trail.yaml"
    if not dry_run:
        for dest in [*(d for _s, d in (*copies, *invalid_copies)), trail_path]:
            if dest.exists():
                raise PipelineError(f"{dest} already exists; an audit record is never overwritten")

    card_bytes = card_path.read_bytes()
    reason = _hold_reason(cfg, slug, n, first, second, first_why, second_why)
    added: list[AddLink] = []
    new_text: str | None = None
    ops = None
    try:
        ops = parse_ops(_read_json(cfg.ops_path(slug, None, n)))
        added = [op for op in ops.operations if isinstance(op, AddLink)]
    except (PipelineError, OperationError) as exc:
        reason = reason or f"the ops file cannot be read: {str(exc).splitlines()[0]}"
    if reason is None:
        assert ops is not None
        applied_path = cfg.applied_dir(slug, None, n) / f"{slug}.yaml"
        try:
            rederived = apply_operations(card_bytes.decode("utf-8"), ops, validate=False)
            stored = applied_path.read_text(encoding="utf-8")
        except (OperationError, OSError):
            rederived, stored = "", None
        if stored is None or rederived != stored:
            reason = "the card changed since the round was applied"
        else:
            new_text = _set_last_checked(stored, date, "ai_audit")
            if issues := _published_card_problems(cfg, slug, new_text):
                reason = "the card to publish does not validate: " + "; ".join(issues)
                new_text = None
    assert first is not None or reason is not None
    changelog = None
    if reason is None:
        assert new_text is not None and first is not None
        entry = {
            "date": dt.date.fromisoformat(date),
            "card": slug,
            "change": "Links added: " + ", ".join(x.to for x in added),
            "reason": first.reasons_summary,
            "sources": list(dict.fromkeys(s for x in added for s in x.sources)),
            "tier": 2,
            "decided_by": "ai_audit",
        }
        changelog = append_changelog_entry(cfg, entry, date)

    labels = {f"{'second' if k else 'first'} audit": r for k, (_p, r) in records.items()}
    report = _report(slug, "published" if reason is None else "held back", reason, added, labels)
    _write_text(cfg.f(REPORT), report)
    out(report.rstrip("\n"))
    if dry_run:
        out(f"Dry run: only {cfg.f(REPORT)} was written.")
        return 0
    if reason is None:
        assert new_text is not None and changelog is not None
        _write_text(card_path, new_text)
        _write_text(changelog[0], changelog[1])
    for src, dest in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    for src, dest in invalid_copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_invalid_copy(src, dest, slug)
    audits_run = [dest.name for _s, dest in (*copies, *invalid_copies)]
    trail = {
        "card": slug,
        "card_sha256": _sha256(card_bytes),
        "rounds": [_round_trail(cfg, slug, r) for r in ROUNDS if cfg.checks_path(slug, None, r).is_file()],
        "audits_run": audits_run,
        "outcome": "published" if reason is None else reason,
    }
    _write_text(trail_path, yaml.safe_dump(trail, sort_keys=False, allow_unicode=True, width=100))
    out(f"The commit must end with the trailer: {pipeline_marker(date)}")
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

COMMANDS = ("link-apply", "record-map-review", "link-audit-plan", "record-link-audit", "link-publish")


def dispatch(args: Any, cfg: Config, fulltext: FullTextLoader | None, date: Any, out: Callable[[str], None]) -> int:
    """Run one of ``COMMANDS`` (called from ``me_atlas.pipeline``)."""
    from me_atlas import citations
    from me_atlas.pipeline import live_fulltext_loader

    if args.command == "link-apply":
        result = link_apply(cfg, args.slug, args.round)
        for line in result["ops_errors"]:
            out(f"operations error: {line}")
        for line in result["validator"]:
            out(f"validator: {line}")
        for row in result["citations"]:
            if (row["level"] == citations.ERROR or row["code"] == "C9") and not row["preexisting"]:
                out(f"citations: {row['study']}: {row['code']} {row['level']}: {row['message']}")
        out(f"checks: {cfg.checks_path(args.slug, None, args.round)}")
        if result["passed"]:
            out(f"PASSED; applied card: {result['applied']}")
            return 0
        out("FAILED")
        return 1
    if args.command == "record-map-review":
        review = record_map_review(cfg, args.slug, args.round)
        out(f"map review recorded: {review.verdict}, {len(review.findings)} finding(s)")
        return 0
    if args.command == "link-audit-plan":
        out(str(link_audit_plan(cfg, args.slug, fulltext or live_fulltext_loader(cfg.cache_dir))))
        return 0
    if args.command == "record-link-audit":
        record = record_link_audit(cfg, args.slug, second=args.second)
        out(f"audit recorded: {record.decision}, {len(record.parts)} part(s)")
        return 0
    assert args.command == "link-publish" and date is not None
    return link_publish(cfg, args.slug, date.isoformat(), dry_run=args.dry_run, out=out)
