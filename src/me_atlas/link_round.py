"""A link round on one published card: add the links a ``link-drafter`` proposed, with an audit trail.

The weekly path works per (card, paper) and has no operation that adds a link; a card in ``cards/`` changes only
through the pipeline. A link round is that path for links (``docs/pipeline.md``, "Adding links to a published card").
Everything lives in one run folder ``DIR`` (normally ``data/pipeline/links/<date>-<slug>/``)::

    map/<slug>-r<N>.json          the link-drafter's proposal (round N = 1 or 2)
    ops/<slug>-r<N>.json          the proposal as ``add_link`` operations         (``link-apply``)
    applied/<slug>-r<N>/          the card with the links added, and changes.diff (``link-apply``)
    checks/<slug>-r<N>.json       the card validator and the citations check      (``link-apply``)
    map-review/<slug>-r<N>.json   the card-reviewer's map-mode review             (``record-map-review``)
    link-stage/<slug>-links[-second]/<slug>.yaml  the text an audit reads: the card plus the links in play
    audit-context/<slug>-links[-second].md  the change audit's context            (``link-audit-plan [--second]``)
    audit/<slug>-links[-second].yaml  the two sequential audits                   (``record-link-audit``)
    valve/<slug>-links-<stage>.json, valve/<slug>-links-<stage>/<slug>.yaml, ...-check.json,
    valve-check-context/<slug>-links-<stage>.md   the wording valve               (``link-valve-*``)
    link-report.md                the outcome                                     (``link-publish``)

Each link is decided on its own (``docs/pipeline.md``): the map review and the audits drop a link on a decisive
finding, a wording-only finding goes to the valve (``set_link_text``), and ``link-publish`` publishes the links that
passed every stage. It reuses the helpers of ``me_atlas.pipeline`` (the checks, the audit context and its record
validation, the valve's fix-check model, the change log) and changes no rule of the weekly path. ``cards/`` is written
by ``link-publish`` only.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from me_atlas import citations
from me_atlas.cards import NonEmptyStr, Slug, StudyId
from me_atlas.operations import (
    AddLink,
    OperationError,
    OpsFile,
    SetLinkText,
    apply_operations,
    parse_ops,
    tiers,
)
from me_atlas.pipeline import (
    _M,
    FIRST_INVALID_TWICE,
    AuditPart,
    AuditRecord,
    Config,
    FullTextLoader,
    PipelineError,
    ValveCheck,
    _cached_study_files,
    _check_applied,
    _check_error_lines,
    _Classified,
    _finish_checks,
    _missing_record_note,
    _new_errors,
    _pending_retry,
    _published_card_problems,
    _pydantic_lines,
    _read_json,
    _read_valve_check,
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
    validate_audit_record,
)

ROUNDS = (1, 2)
MAX_TRIES = 3  # failed tries of one round (as the correction rounds' check retries)
LINKS = "links"  # the audit's round tag: audit/<slug>-links.yaml, audit-context/<slug>-links.md
LINKS_SECOND = "links-second"  # the second audit's context: audit-context/<slug>-links-second.md
STAGES = ("map-review", "audit")  # the stages that can open the wording valve
SEQUENTIAL_REJECT = (
    "the first audit rejected every link on a decisive part; no second audit was run (sequential audits)"
)
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


class MapFinding(_Classified):
    """One finding of the map review. A ``must_fix`` carries ``class``: ``decisive``, or ``wording`` with ``target`` the
    same ``links[i]`` as ``item``. A finding on the proposal as a whole (``item`` null or ``layer``) is ``decisive``."""

    item: str | None
    severity: Literal["must_fix", "advisory"]
    problem: NonEmptyStr
    fix: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _classed(self) -> MapFinding:
        if self.klass == "none":
            raise ValueError("a finding is `decisive` or `wording`; `none` is for an audit part that supports the card")
        if self.severity != "must_fix":
            return self
        if self.klass is None:
            raise ValueError("a must_fix finding needs `class`: `decisive` or `wording`")
        if self.klass == "wording":
            if self.item is None or self.item == "layer":
                raise ValueError(
                    "a must_fix on the proposal as a whole (item null or layer) is `decisive`, not `wording`"
                )
            if self.target != self.item:
                raise ValueError(f"a wording finding's `target` is its `item` ({self.item!r}); got {self.target!r}")
        return self


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


def _has_decisive(review: MapReview) -> bool:
    return any(f.severity == "must_fix" and f.klass == "decisive" for f in review.findings)


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
    ``reject`` with a decisive finding (a wording-only reject goes to the valve instead), a round that already has a
    map review or passed its checks, a round that failed three times, a round after the audits began."""
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
        if not _has_decisive(review):
            raise PipelineError(
                "round 2 is not applied: the map review of round 1 has no decisive finding, so its wording "
                "findings go to the valve (`link-valve-apply --stage map-review`)"
            )
    if cfg.audit_context_path(slug, None, LINKS).exists():
        raise PipelineError(
            f"the audits of this round began ({cfg.audit_context_path(slug, None, LINKS).name}); "
            "no further round is applied"
        )
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
# The text of a stage, and what the audits and the valve say about each link
# ---------------------------------------------------------------------------


def _stage_text(base_text: str, proposal: Proposal, tos: Sequence[str], texts: Mapping[str, str]) -> str:
    """The card text with the links ``tos`` of the proposal added, in proposal order, each with ``texts[to]`` (else the
    proposed text). Every stage text of a round (the map review's, the audits', the valve's, the published card) is
    made by this one function, so a stored stage text can be compared with a re-derived one."""
    wanted = set(tos)
    ops = [
        AddLink(op="add_link", to=x.to, support=x.support, text=texts.get(x.to, x.text), sources=list(x.sources))
        for x in proposal.links
        if x.to in wanted
    ]
    try:
        return apply_operations(base_text, ops, validate=False)
    except OperationError as exc:
        raise PipelineError(f"the links cannot be added to the card: {exc}") from exc


def stage_path(cfg: Config, slug: str, second: bool) -> Path:
    """``link-stage/<slug>-links[-second]/<slug>.yaml``: the text an audit read (named for the card as the validator
    wants)."""
    return cfg.f("link-stage", f"{slug}-{LINKS_SECOND if second else LINKS}", f"{slug}.yaml")


def context_path(cfg: Config, slug: str, second: bool) -> Path:
    return cfg.audit_context_path(slug, None, LINKS_SECOND if second else LINKS)


def _applied_round(cfg: Config, slug: str) -> int:
    """The last applied round, when its checks passed."""
    n = last_round(cfg, slug)
    if n is None:
        raise PipelineError("no round applied; run `link-apply` first")
    checks = _round_checks(cfg, slug, n)
    if checks is None or not checks.get("passed"):
        raise PipelineError(f"the checks of round {n} did not pass")
    return n


def _stage_mapping(cfg: Config, slug: str, second: bool) -> dict[int, str] | None:
    """``links[n]`` (the numbering of the stage text an audit read) to the ``to`` of each link of the round in it."""
    try:
        data = yaml.safe_load(stage_path(cfg, slug, second).read_text(encoding="utf-8"))
        n = last_round(cfg, slug)
        proposed = {x.to for x in load_proposal(cfg, slug, n).links} if n is not None else set()
    except (OSError, yaml.YAMLError, PipelineError):
        return None
    links = data.get("links") if isinstance(data, dict) else None
    return {i: x["to"] for i, x in enumerate(links or []) if isinstance(x, dict) and x.get("to") in proposed}


def _audit_problems(cfg: Config, slug: str, second: bool) -> Callable[[AuditRecord], list[str]]:
    """The checks of the audit record of a link round beyond a weekly record: ``link_decisions`` (one per link of the
    stage text the audit read), the decision that follows from them, no ``accept_lower``, and each objecting part naming
    its link with ``target: links[n]`` (every rejected link has one, no accepted link has one)."""

    def check(record: AuditRecord) -> list[str]:
        mapping = _stage_mapping(cfg, slug, second)
        if mapping is None:
            return [f"no stage text {stage_path(cfg, slug, second)}; run `link-audit-plan` first"]
        found: list[str] = []
        if record.decision == "accept_lower":
            found.append("accept_lower is not available in a link round: it changes no level")
        decisions = record.link_decisions
        expected = list(mapping.values())
        if decisions is None:
            return [*found, "link_decisions is missing: one {to, decision} entry for each of " + ", ".join(expected)]
        given = [d.to for d in decisions]
        found += [f"link_decisions has no entry for `{to}`" for to in expected if to not in given]
        found += [
            f"link_decisions has an entry for `{to}`, which this audit does not decide"
            for to in dict.fromkeys(given)
            if to not in expected
        ]
        found += [f"link_decisions has `{to}` twice" for to in dict.fromkeys(given) if given.count(to) > 1]
        if record.decision != "accept_lower":
            want = "accept" if all(d.decision == "accept" for d in decisions) else "reject"
            if record.decision != want:
                found.append(
                    f"decision is {record.decision}, but the link_decisions give {want}: the decision is `accept` "
                    "only when every link is accepted"
                )
        named: dict[str, list[int]] = {}
        for i, part in enumerate(record.parts):
            if part.klass not in ("decisive", "wording"):
                continue
            m = _ITEM.match(part.target or "")
            if m is None:
                found.append(f"parts[{i}] objects but its target {part.target!r} is not `links[n]`")
            elif (to := mapping.get(int(m.group(1)))) is None:
                found.append(f"parts[{i}].target {part.target} is not a link of this round (they are {mapping})")
            else:
                named.setdefault(to, []).append(i)
        for d in decisions:
            if d.decision == "reject" and d.to in expected and d.to not in named:
                found.append(f"the link `{d.to}` is rejected but no objecting part names it (`target: links[n]`)")
            if d.decision == "accept" and d.to in named:
                found.append(f"the link `{d.to}` is accepted but parts[{named[d.to][0]}] objects to it")
        return found

    return check


def _load_link_audit(cfg: Config, slug: str, second: bool) -> tuple[AuditRecord | None, Path, str | None]:
    """The valid audit record of a link round, or (None, path, why it is missing or invalid)."""
    path = cfg.audit_path(slug, None, second, LINKS)
    if not path.is_file():
        return None, path, _missing_record_note(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        record = validate_audit_record(
            cfg,
            raw,
            slug=slug,
            key=None,
            source=path,
            context_path=context_path(cfg, slug, second),
            redraft=LINKS,
            require_class=True,
            extra_check=_audit_problems(cfg, slug, second),
        )
    except yaml.YAMLError as exc:
        return None, path, f"{path.name} is not valid YAML: {str(exc).splitlines()[0]}"
    except (OSError, PipelineError) as exc:
        return None, path, str(exc).replace("\n", "; ")
    return record, path, None


@dataclass(frozen=True)
class Verdict:
    """One audit's decision on one link: ``accept``, ``wording`` (rejected, and every objecting part naming it is
    wording) or ``decisive`` (rejected, with a decisive part); and the objecting parts naming it."""

    kind: Literal["accept", "wording", "decisive"]
    parts: tuple[tuple[int, AuditPart], ...] = ()

    def decisive_part(self) -> str:
        return next((p.decision_part for _i, p in self.parts if p.klass == "decisive"), "")


def _verdicts(record: AuditRecord, mapping: Mapping[int, str]) -> dict[str, Verdict]:
    named: dict[str, list[tuple[int, AuditPart]]] = {}
    for i, part in enumerate(record.parts):
        m = _ITEM.match(part.target or "")
        if part.klass in ("decisive", "wording") and m and (to := mapping.get(int(m.group(1)))):
            named.setdefault(to, []).append((i, part))
    out: dict[str, Verdict] = {}
    for d in record.link_decisions or []:
        parts = tuple(named.get(d.to, ()))
        if d.decision == "accept":
            out[d.to] = Verdict("accept", parts)
        else:
            out[d.to] = Verdict("decisive" if any(p.klass == "decisive" for _i, p in parts) else "wording", parts)
    return out


@dataclass(frozen=True)
class LinkFinding:
    """One wording finding (a ``must_fix`` of the map review) or objecting wording part (of an audit) the valve
    answers."""

    id: str
    to: str
    problem: str
    fix: str | None = None


def valve_key(stage: str) -> str:
    if stage not in STAGES:
        raise PipelineError(f"--stage is one of {', '.join(STAGES)}")
    return f"links-{stage}"


def _read_link_valve(cfg: Config, slug: str, key: str) -> OpsFile:
    path = cfg.valve_path(slug, key)
    try:
        ops = parse_ops(_read_json(path))
    except OperationError as exc:
        raise PipelineError(f"{path} is not a valid operations file: {exc}") from exc
    if ops.card != slug:
        raise PipelineError(f"{path} is for card '{ops.card}', not '{slug}'")
    return ops


def _same_words(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def apply_link_valve(stage_text: str, ops: OpsFile, allowed: set[str]) -> tuple[str | None, list[str]]:
    """The guard of the link valve: apply a valve file (``set_link_text`` only) to ``stage_text`` with the ordinary
    operation code; (the new text, []) or (None, what is wrong). Refused: any other operation, a link not in the stage
    text, a link no wording finding of the stage names (``allowed``), an empty or unchanged text, a link twice, and a
    result that differs from the stage text in anything but the text of the named links (``to``, ``support``,
    ``sources``, order and every other line are compared)."""
    try:
        old = yaml.safe_load(stage_text)
    except yaml.YAMLError as exc:
        return None, [f"the text the fix is applied to does not parse: {exc}"]
    present = {x["to"]: x for x in old.get("links") or [] if isinstance(x, dict) and "to" in x}
    found: list[str] = []
    if ops.paper is not None:
        found.append(f"a link valve fix names no paper, this file names {ops.paper!r}")
    if not ops.operations:
        found.append("a link valve fix needs at least one operation")
    seen: set[str] = set()
    for i, op in enumerate(ops.operations):
        if not isinstance(op, SetLinkText):
            found.append(f"operations[{i}] is {op.op}: a link valve fix holds set_link_text only")
            continue
        if op.to not in present:
            found.append(f"operations[{i}]: `{op.to}` is not a link in play at this stage")
        elif op.to not in allowed:
            found.append(f"operations[{i}] changes `{op.to}`, which no wording finding of this stage names")
        elif op.to in seen:
            found.append(f"operations[{i}]: the text of `{op.to}` is set twice")
        elif _same_words(op.text, str(present[op.to].get("text"))):
            found.append(f"operations[{i}]: the new text of `{op.to}` equals the old one")
        seen.add(op.to)
    if found:
        return None, found
    try:
        new_text = apply_operations(stage_text, ops, validate=False)
    except OperationError as exc:
        return None, [str(exc)]

    def neutral(data: dict[str, Any]) -> dict[str, Any]:
        d = json.loads(json.dumps(data, default=str))
        for x in d.get("links") or []:
            if x.get("to") in seen:
                x["text"] = None
        return d

    if neutral(old) != neutral(yaml.safe_load(new_text)):
        return None, ["the fix changes more than the text of the named link(s); nothing applied"]
    matcher = difflib.SequenceMatcher(None, stage_text.split("\n"), new_text.split("\n"), autojunk=False)
    if len([o for o in matcher.get_opcodes() if o[0] != "equal"]) > len(seen):
        return None, ["the fix changes lines outside the text of the named link(s); nothing applied"]
    return new_text, []


def _unfinished(what: str, slug: str, stage: str) -> str:
    return (
        f"{what}: the {stage} opened the valve; run `link-valve-apply {slug} --stage {stage} --run-dir DIR`, then "
        "`link-valve-check-plan`, the card-reviewer and `record-link-valve-check`; the round stays open"
    )


def _valve_progress(
    cfg: Config, slug: str, stage: str, findings: Sequence[LinkFinding]
) -> tuple[str | None, dict[str, str], dict[str, str]]:
    """(what the operator has not finished or None, the links whose fix failed its check with why, the text each
    ``set_link_text`` gives). The valve is finished when its fix is applied and its check recorded."""
    key = valve_key(stage)
    if not cfg.valve_text_path(slug, key).is_file():
        return _unfinished("valve fix not applied", slug, stage), {}, {}
    check = _read_valve_check(cfg, slug, key)
    answered = [x.finding for x in check.fixes] if check else []
    if check is None or sorted(answered) != sorted(f.id for f in findings):
        return _unfinished("valve check missing", slug, stage), {}, {}
    ops = _read_link_valve(cfg, slug, key)
    texts = {op.to: op.text for op in ops.operations if isinstance(op, SetLinkText)}
    by_id = {x.finding: x for x in check.fixes}
    failures: dict[str, str] = {}
    for f in findings:
        answer = by_id[f.id]
        if f.to in failures:
            continue
        if not answer.resolves:
            failures[f.to] = f"{f.id} does not resolve the finding ({answer.reason})"
        elif answer.new_claim:
            failures[f.to] = f"{f.id} adds a claim ({answer.reason})"
        elif f.to not in texts:
            failures[f.to] = f"{f.id}: no fix was written for the link"
    return None, failures, texts


# ---------------------------------------------------------------------------
# The stages of a round, link by link
# ---------------------------------------------------------------------------


class _Flow:
    """What the files of a link round say about each link, stage by stage: the map review, its valve, the first and
    the second audit, the audit valve. ``out[to]`` is None while the link is in play, else why it is out. A stage that
    cannot go on for the whole round sets ``hold`` (the card is held back); a valve the operator has not finished sets
    ``unfinished`` (a refusal). Nothing is written."""

    def __init__(self, cfg: Config, slug: str):
        self.cfg, self.slug = cfg, slug
        card_path, _draft = _card_paths(cfg, slug)
        n = last_round(cfg, slug)
        if n is None:
            raise PipelineError("no round applied; run `link-apply` first")
        self.n = n
        self.proposal = load_proposal(cfg, slug, n)
        self.base_text = card_path.read_text(encoding="utf-8")
        self.tos = [x.to for x in self.proposal.links]
        self.out: dict[str, str | None] = dict.fromkeys(self.tos)
        self.texts = {x.to: x.text for x in self.proposal.links}
        self.fixed: set[str] = set()
        self.hold: str | None = None
        self.unfinished: str | None = None
        self.review: MapReview | None = None
        self.map_findings: list[LinkFinding] = []
        self.audit_findings: list[LinkFinding] = []
        self.first: AuditRecord | None = None
        self.first_why: str | None = None
        self.second: AuditRecord | None = None
        self.verdicts: dict[str, dict[str, Verdict]] = {}

    def live(self) -> list[str]:
        return [to for to in self.tos if self.out[to] is None]

    def stop(self, reason: str) -> None:
        """The whole round is held back for ``reason``; the links still in play are out with it."""
        self.hold = self.hold or reason
        for to in self.tos:
            if self.out[to] is None:
                self.out[to] = f"held back: {reason}"

    @property
    def blocked(self) -> bool:
        return self.hold is not None or self.unfinished is not None

    def run(self) -> None:
        self.begin()
        self.map_review()
        self.map_valve()
        self.first_audit()
        self.second_audit()
        self.audit_valve()

    def begin(self) -> None:
        checks = _round_checks(self.cfg, self.slug, self.n)
        if checks is None or not checks.get("passed"):
            return self.stop("checks failed")
        self.review, why = load_map_review(self.cfg, self.slug, self.n)
        if self.review is None:
            return self.stop(f"no valid map review: {why}")
        applied = self.cfg.applied_dir(self.slug, None, self.n) / f"{self.slug}.yaml"
        try:
            stored: str | None = applied.read_text(encoding="utf-8")
            rederived = _stage_text(self.base_text, self.proposal, self.tos, {})
        except (OSError, PipelineError):
            stored, rederived = None, ""
        if stored is None or rederived != stored:
            return self.stop("the card changed since the round was applied")

    def map_review(self) -> None:
        """P1: a link is out when the last round's map review has a decisive ``must_fix`` on it, or on the proposal as a
        whole; a wording-only ``must_fix`` on a link in play is a valve finding."""
        if self.blocked or self.review is None:
            return
        must = [(i, f) for i, f in enumerate(self.review.findings) if f.severity == "must_fix"]
        whole = next((f for _i, f in must if f.item is None or f.item == "layer"), None)
        for idx, link in enumerate(self.proposal.links):
            hit = whole or next((f for _i, f in must if f.item == f"links[{idx}]" and f.klass == "decisive"), None)
            if hit is not None:
                self.out[link.to] = f"dropped at map review: {hit.problem}"
        for i, f in must:
            m = _ITEM.match(f.item or "")
            if f.klass == "wording" and m is not None:
                link = self.proposal.links[int(m.group(1))]
                if self.out[link.to] is None:
                    self.map_findings.append(LinkFinding(f"findings[{i}]", link.to, f.problem, f.fix))
        if not self.live():
            tail = "" if self.n == 2 else "; no second round was applied"
            self.stop(f"map review rejected in round {self.n}{tail}")

    def _valve(self, stage: str, findings: list[LinkFinding]) -> None:
        links = self.live()
        note, failures, op_texts = _valve_progress(self.cfg, self.slug, stage, findings)
        if note is not None:
            self.unfinished = note
            return
        derived = _stage_text(self.base_text, self.proposal, links, self.texts | op_texts)
        try:
            stored = self.cfg.valve_text_path(self.slug, valve_key(stage)).read_text(encoding="utf-8")
        except OSError:
            stored = None
        if stored != derived:
            return self.stop(
                f"the stored text of the {stage} wording fix differs from the one re-derived from the round's files"
            )
        for to, why in failures.items():
            self.out[to] = f"wording fix did not pass its check: {why}"
        for to, text in op_texts.items():
            if to in links and to not in failures:
                self.texts[to] = text
                self.fixed.add(to)
        if not self.live():
            self.stop(f"no link passed the wording fix check of the {stage}")

    def map_valve(self) -> None:
        if not self.blocked and self.map_findings:
            self._valve("map-review", self.map_findings)

    def _check_stage(self, second: bool, links: list[str]) -> bool:
        derived = _stage_text(self.base_text, self.proposal, links, self.texts)
        try:
            stored = stage_path(self.cfg, self.slug, second).read_text(encoding="utf-8")
        except OSError:
            stored = None
        if stored != derived:
            which = "second" if second else "first"
            self.stop(f"the text the {which} audit read differs from the one re-derived from the round's files")
            return False
        return True

    def _drop_decisive(self, label: str, second: bool) -> None:
        mapping = _stage_mapping(self.cfg, self.slug, second) or {}
        record = self.second if second else self.first
        assert record is not None
        verdicts = self.verdicts[label] = _verdicts(record, mapping)
        for to in self.live():
            if verdicts[to].kind == "decisive":
                self.out[to] = f"rejected in audit (decisive): {verdicts[to].decisive_part()}"

    def first_audit(self) -> None:
        if self.blocked:
            return
        self.first, path, self.first_why = _load_link_audit(self.cfg, self.slug, False)
        if self.first is None:
            second_started = _record_started(self.cfg.audit_path(self.slug, None, True, LINKS))
            if not second_started and _sibling(path, ".invalid-2.yaml").is_file():
                return self.stop(FIRST_INVALID_TWICE)
            return self.stop(f"no valid first audit: {self.first_why}")
        if not self._check_stage(False, self.live()):
            return
        self._drop_decisive("first", False)
        if not self.live():
            self.stop(SEQUENTIAL_REJECT)

    def second_audit(self) -> None:
        if self.blocked:
            return
        links = self.live()
        self.second, path, why = _load_link_audit(self.cfg, self.slug, True)
        if self.second is None:
            if not _record_started(path):
                raise PipelineError(
                    f"a second audit is needed for {', '.join(links)} and there is none: run `link-audit-plan "
                    f"{self.slug} --second`, the auditor and `record-link-audit {self.slug} --second`"
                )
            for to in links:
                self.out[to] = "not audited a second time"
            return self.stop(f"no valid second audit: {why}")
        if not self._check_stage(True, links):
            return
        self._drop_decisive("second", True)
        if not self.live():
            self.stop("no link passed both audits")

    def audit_findings_of_survivors(self) -> None:
        """The objecting wording parts of the audits that name a link both audits accepted, or rejected on wording
        only."""
        self.audit_findings = [
            LinkFinding(f"{label}.parts[{i}]", to, part.decision_part)
            for label in ("first", "second")
            for to in self.live()
            for i, part in self.verdicts.get(label, {}).get(to, Verdict("accept")).parts
            if part.klass == "wording"
        ]

    def audit_valve(self) -> None:
        if self.blocked:
            return
        self.audit_findings_of_survivors()
        if self.audit_findings:
            self._valve("audit", self.audit_findings)


# ---------------------------------------------------------------------------
# link-audit-plan, record-link-audit
# ---------------------------------------------------------------------------


def link_audit_plan(cfg: Config, slug: str, loader: FullTextLoader, *, second: bool = False) -> Path:
    """Write ``audit-context/<slug>-links.md``: the change audit of the links in play after the map review (with its
    valve fix applied), built by the code that builds a weekly change audit; with ``second``
    ``audit-context/<slug>-links-second.md`` for the links the first audit did not reject on a decisive part. The text
    the audit reads is kept as ``link-stage/<slug>-links[-second]/<slug>.yaml``. It holds nothing from the proposal's
    ``why``, the map review, its valve or an earlier audit."""
    _card_paths(cfg, slug)
    _applied_round(cfg, slug)
    flow = _Flow(cfg, slug)
    flow.begin()
    flow.map_review()
    flow.map_valve()
    if flow.hold:
        raise PipelineError(flow.hold)
    if flow.unfinished:
        raise PipelineError(flow.unfinished)
    if second:
        flow.first_audit()
        if flow.first is None:
            raise PipelineError(f"a second audit needs a valid first audit record: {flow.first_why}")
        if flow.hold:
            raise PipelineError(f"no link is left for a second audit: {flow.hold}")
    links = flow.live()
    _write_text(stage_path(cfg, slug, second), _stage_text(flow.base_text, flow.proposal, links, flow.texts))
    context = build_audit_context(
        cfg,
        slug,
        None,
        loader,
        applied_round=flow.n,
        applied_file=stage_path(cfg, slug, second),
        round_links=links,
        second=second,
    )
    path = context_path(cfg, slug, second)
    _write_text(path, context)
    return path


def record_link_audit(cfg: Config, slug: str, *, second: bool = False) -> AuditRecord:
    """Validate ``audit/<slug>-links.yaml`` (``-second``) against its context, with the one format retry of the weekly
    path and the link-round checks (``_audit_problems``). A second audit needs a valid first one that left a link."""
    if second:
        first, _path, why = _load_link_audit(cfg, slug, False)
        if first is None:
            raise PipelineError(f"a second audit needs a valid first audit record: {why}")
        verdicts = _verdicts(first, _stage_mapping(cfg, slug, False) or {})
        if all(v.kind == "decisive" for v in verdicts.values()):
            raise PipelineError(f"no link is left for a second audit: {SEQUENTIAL_REJECT}")
    ctx = context_path(cfg, slug, second)
    if not ctx.is_file():
        raise PipelineError(f"no audit context {ctx}; run `link-audit-plan{' --second' if second else ''}` first")
    return record_audit(
        cfg,
        slug,
        None,
        second=second,
        file=cfg.audit_path(slug, None, second, LINKS),
        redraft=LINKS,
        context_file=ctx,
        extra_check=_audit_problems(cfg, slug, second),
    )


# ---------------------------------------------------------------------------
# link-valve-apply, link-valve-check-plan, record-link-valve-check
# ---------------------------------------------------------------------------


def _valve_stage(cfg: Config, slug: str, stage: str) -> tuple[_Flow, list[LinkFinding], list[str]]:
    """(the flow, the findings the valve of ``stage`` answers, the links in the stage's text). Refused (nothing
    written) when the valve is not open for the stage: for the map review, a wording ``must_fix`` of the last round's
    review on a link in play; for the audit, both audits valid and a link accepted by them only through wording
    parts."""
    valve_key(stage)
    flow = _Flow(cfg, slug)
    flow.begin()
    flow.map_review()
    if stage == "audit":
        flow.map_valve()
        flow.first_audit()
        flow.second_audit()
        if not flow.blocked:
            flow.audit_findings_of_survivors()
    if flow.unfinished:
        raise PipelineError(flow.unfinished)
    if flow.hold:
        raise PipelineError(f"the valve is not open for the {stage}: {flow.hold}")
    findings = flow.map_findings if stage == "map-review" else flow.audit_findings
    if not findings:
        raise PipelineError(f"the valve is not open for the {stage}: no wording finding names a link still in play")
    return flow, findings, flow.live()


def link_valve_apply(cfg: Config, slug: str, stage: str) -> Path:
    """`link-valve-apply`: apply ``valve/<slug>-links-<stage>.json``, the orchestrator's wording fix of link texts
    (``set_link_text`` only), to the stage's text with the guard (``apply_link_valve``), run the card validator and the
    citations check, and write ``valve/<slug>-links-<stage>/<slug>.yaml``. One valve per stage; refused when it is not
    open, or when the guard or a new check error fails."""
    flow, findings, links = _valve_stage(cfg, slug, stage)
    key = valve_key(stage)
    text_path = cfg.valve_text_path(slug, key)
    if text_path.exists():
        raise PipelineError(f"{text_path} exists: one valve per stage")
    ops = _read_link_valve(cfg, slug, key)
    stage_text = _stage_text(flow.base_text, flow.proposal, links, flow.texts)
    new_text, problems = apply_link_valve(stage_text, ops, {f.to for f in findings})
    if new_text is None:
        raise PipelineError("the wording fix is refused:\n" + "\n".join(problems))
    result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        _check_applied(cfg, slug, cfg.cards_dir / f"{slug}.yaml", stage_text, new_text, Path(tmp), result)
    errors = [
        *result["validator"],
        *(f"citations: {r['study']}: {r['code']}: {r['message']}" for r in _new_errors(result)),
    ]
    if errors:
        raise PipelineError("the wording fix fails the checks:\n" + "\n".join(errors))
    _write_text(text_path, new_text)
    return text_path


def link_valve_check_plan(cfg: Config, slug: str, stage: str) -> Path:
    """`link-valve-check-plan`: write ``valve-check-context/<slug>-links-<stage>.md`` for the card-reviewer's fix check:
    each wording finding or part (id, link, problem, fix), the link text before and after the fix and the cached
    records of the link's sources (named by path, not embedded). Nothing else."""
    flow, findings, _links = _valve_stage(cfg, slug, stage)
    key = valve_key(stage)
    if not cfg.valve_text_path(slug, key).is_file():
        raise PipelineError(f"no applied wording fix for {key}: run `link-valve-apply {slug} --stage {stage}` first")
    ops = _read_link_valve(cfg, slug, key)
    after = {op.to: op.text for op in ops.operations if isinstance(op, SetLinkText)}
    reader = citations.CacheReader(cfg.cache_dir)
    parts = [
        f"# Fix check ({stage}, link round): `{slug}`",
        "",
        "A wording fix answers each finding below. For each finding say, from this file and the cached records it "
        "names, whether the fix **resolves** it and whether it **adds a claim** the records do not state. Read only "
        "this file and those cached files; fetch nothing. Write "
        f"`{cfg.valve_path(slug, key, '-check.json')}`: "
        '`{"card": "<slug>", "fixes": [{"finding": "<id>", "resolves": true|false, "new_claim": true|false, '
        '"reason": "one line"}]}`, one entry per finding.',
        "",
    ]
    for f in findings:
        link = next(x for x in flow.proposal.links if x.to == f.to)
        parts += [
            f"## Finding {f.id}",
            "",
            f"- link: `{f.to}`",
            f"- problem: {f.problem}",
            *([f"- fix: {f.fix}"] if f.fix else []),
            f"- before: {flow.texts[f.to]}",
            f"- after: {after.get(f.to, '(no operation touches this link)')}",
            "- cited records:",
        ]
        for study_id in dict.fromkeys(link.sources):
            parts += [f"  - {study_id}", *(f"    {line}" for line in _cached_study_files(cfg, study_id, reader))]
        parts.append("")
    path = cfg.valve_context_path(slug, key)
    _write_text(path, "\n".join(parts))
    return path


def record_link_valve_check(cfg: Config, slug: str, stage: str) -> ValveCheck:
    """`record-link-valve-check`: validate ``valve/<slug>-links-<stage>-check.json``: one answer for each finding of the
    stage, no other. Passed means every fix resolves its finding and adds no claim."""
    _flow, findings, _links = _valve_stage(cfg, slug, stage)
    key = valve_key(stage)
    if not cfg.valve_text_path(slug, key).is_file():
        raise PipelineError(f"no applied wording fix for {key}: run `link-valve-apply {slug} --stage {stage}` first")
    path = cfg.valve_path(slug, key, "-check.json")
    try:
        check = ValveCheck.model_validate(_read_json(path))
    except ValidationError as exc:
        raise PipelineError(f"{path} is malformed:\n" + "\n".join(_pydantic_lines(exc))) from exc
    answered = [x.finding for x in check.fixes]
    problems = [f"card is '{check.card}', expected '{slug}'"] if check.card != slug else []
    problems += [f"no answer for the finding {f.id}" for f in findings if f.id not in answered]
    problems += [
        f"an answer for '{a}', which is no finding of this stage" for a in answered if a not in {f.id for f in findings}
    ]
    problems += [f"the finding {a} is answered twice" for a in dict.fromkeys(answered) if answered.count(a) > 1]
    if problems:
        raise PipelineError(f"{path} is not valid:\n" + "\n".join(problems))
    return check


# ---------------------------------------------------------------------------
# link-publish
# ---------------------------------------------------------------------------


def _finding_dicts(findings: list[MapFinding]) -> list[dict[str, Any]]:
    return [f.model_dump(mode="json", exclude_none=True, by_alias=True) for f in findings]


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


def _attempt_suffix(cfg: Config, slug: str, date: str) -> str:
    """``""`` for the first link-round trail of a card and date in ``audits/``; ``-2``, ``-3``, ... when one exists, so
    that a later round on the same card and date never meets the names of an earlier one."""
    if not (cfg.audits_dir / f"{date}-{slug}-{LINKS}-trail.yaml").exists():
        return ""
    k = 2
    while (cfg.audits_dir / f"{date}-{slug}-{LINKS}-{k}-trail.yaml").exists():
        k += 1
    return f"-{k}"


def _valve_record(cfg: Config, slug: str, stage: str, findings: list[LinkFinding]) -> dict[str, Any]:
    key = valve_key(stage)
    check = _read_valve_check(cfg, slug, key)
    try:
        operations = _read_json(cfg.valve_path(slug, key)).get("operations")
    except (PipelineError, AttributeError):
        operations = None
    return {
        "card": slug,
        "stage": stage,
        "classification": [
            {
                "finding": f.id,
                "link": f.to,
                "class": "wording",
                "problem": f.problem,
                **({"fix": f.fix} if f.fix else {}),
            }
            for f in findings
        ],
        "operations": operations,
        "check": None
        if check is None
        else {"passed": check.passed, "fixes": [x.model_dump(mode="json") for x in check.fixes]},
    }


def _report(
    slug: str,
    reason: str | None,
    proposal: Proposal,
    outcomes: dict[str, str],
    published: list[str],
    records: dict[str, AuditRecord],
) -> str:
    lines = [f"# Link round: {slug}", "", f"Outcome: {'published' if published else 'held back'}"]
    if reason is not None:
        lines.append(f"Held back: {reason}")
    by_to = {x.to: x for x in proposal.links}

    def row(x: ProposedLink) -> str:
        return f"- {x.to} ({x.support}); sources {', '.join(x.sources)}"

    lines += ["", "## Links " + ("added" if published else "proposed (not added)"), ""]
    lines += [row(by_to[to]) for to in published] or [row(x) for x in proposal.links]
    if published and (rest := [x for x in proposal.links if x.to not in published]):
        lines += ["", "## Links not added", "", *(f"{row(x)}: {outcomes[x.to]}" for x in rest)]
    lines += ["", "## The audits", ""]
    for label, record in records.items():
        lines += [f"- {label}: {record.decision}", f"  reasons_summary: {record.reasons_summary}"]
    if not records:
        lines.append("- no valid audit record")
    return "\n".join(lines) + "\n"


def link_publish(cfg: Config, slug: str, date: str, *, dry_run: bool, out: Callable[[str], None] = print) -> int:
    """Publish the links of the last round that passed every stage into ``cards/<slug>.yaml``, else hold the card back
    (both cards files byte-identical). Exit 0 for a decision, PipelineError (exit 1) for a refusal."""
    card_path, _draft = _card_paths(cfg, slug)
    n = last_round(cfg, slug)
    if n is None:
        raise PipelineError("no round applied; run `link-apply` first")
    first, first_path, _first_why = _load_link_audit(cfg, slug, False)
    second, second_path, _second_why = _load_link_audit(cfg, slug, True)
    if first is None and (pending := _pending_retry(first_path)) is not None:
        raise PipelineError(pending.replace("record-audit --card ... --retry", "record-link-audit"))
    invalid = _sibling(first_path, ".invalid-2.yaml")
    invalid_copy = invalid if first is None and not _record_started(second_path) and invalid.is_file() else None
    records: dict[str, tuple[Path, AuditRecord]] = {}
    if first is not None:
        records[""] = (first_path, first)
    if second is not None:
        records["-second"] = (second_path, second)
    stem = f"{date}-{slug}-{LINKS}{_attempt_suffix(cfg, slug, date)}"
    copies = [(src, cfg.audits_dir / f"{stem}{suffix}.yaml") for suffix, (src, _r) in records.items()]
    invalid_copies = [] if invalid_copy is None else [(invalid_copy, cfg.audits_dir / f"{stem}-invalid.yaml")]
    valve_stages = [st for st in STAGES if cfg.valve_path(slug, valve_key(st)).is_file()]
    valve_dests = [cfg.audits_dir / f"{stem}-valve-{st}.yaml" for st in valve_stages]
    trail_path = cfg.audits_dir / f"{stem}-trail.yaml"
    if not dry_run:
        for dest in [*(d for _s, d in (*copies, *invalid_copies)), *valve_dests, trail_path]:
            if dest.exists():
                raise PipelineError(f"{dest} already exists; an audit record is never overwritten")

    card_bytes = card_path.read_bytes()
    flow = _Flow(cfg, slug)
    flow.run()
    if flow.unfinished:
        raise PipelineError(flow.unfinished)
    published = flow.live()
    new_text: str | None = None
    if published:
        stage = _stage_text(flow.base_text, flow.proposal, published, flow.texts)
        text = _set_last_checked(stage, date, "ai_audit")
        if issues := _published_card_problems(cfg, slug, text):
            published = []
            flow.stop("the card to publish does not validate: " + "; ".join(issues))
        else:
            new_text = text
    elif flow.hold is None:
        flow.stop("no link passed every stage")
    reason = flow.hold
    assert (new_text is None) == (reason is not None)
    fixed_published = [to for to in published if to in flow.fixed]
    outcomes: dict[str, str] = {}
    for to in flow.tos:
        if to in published:
            outcomes[to] = "published after a wording fix" if to in fixed_published else "published"
        else:
            outcomes[to] = str(flow.out[to])
    changelog = None
    if new_text is not None:
        assert first is not None
        entry = {
            "date": dt.date.fromisoformat(date),
            "card": slug,
            "change": "Links added: " + ", ".join(published) + (" after a wording fix" if fixed_published else ""),
            "reason": first.reasons_summary,
            "sources": list(dict.fromkeys(s for x in flow.proposal.links if x.to in published for s in x.sources)),
            "tier": 2,
            "decided_by": "ai_audit",
        }
        changelog = append_changelog_entry(cfg, entry, date)

    labels = {f"{'second' if k else 'first'} audit": r for k, (_p, r) in records.items()}
    report = _report(slug, reason, flow.proposal, outcomes, published, labels)
    _write_text(cfg.f(REPORT), report)
    out(report.rstrip("\n"))
    if dry_run:
        out(f"Dry run: only {cfg.f(REPORT)} was written.")
        return 0
    if new_text is not None:
        assert changelog is not None
        _write_text(card_path, new_text)
        _write_text(changelog[0], changelog[1])
    for src, dest in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    for src, dest in invalid_copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_invalid_copy(src, dest, slug)
    for st, dest in zip(valve_stages, valve_dests, strict=True):
        findings = flow.map_findings if st == "map-review" else flow.audit_findings
        record = _valve_record(cfg, slug, st, findings)
        _write_text(dest, yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100))
    audits_run = [dest.name for _s, dest in (*copies, *invalid_copies)]
    trail = {
        "card": slug,
        "card_sha256": _sha256(card_bytes),
        "rounds": [_round_trail(cfg, slug, r) for r in ROUNDS if cfg.checks_path(slug, None, r).is_file()],
        "links": [{"to": to, "outcome": outcomes[to]} for to in flow.tos],
        "audits_run": audits_run,
        "outcome": "published" if reason is None else reason,
    }
    _write_text(trail_path, yaml.safe_dump(trail, sort_keys=False, allow_unicode=True, width=100))
    out(f"The commit must end with the trailer: {pipeline_marker(date)}")
    return 0


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

COMMANDS = (
    "link-apply",
    "record-map-review",
    "link-audit-plan",
    "record-link-audit",
    "link-valve-apply",
    "link-valve-check-plan",
    "record-link-valve-check",
    "link-publish",
)


def dispatch(args: Any, cfg: Config, fulltext: FullTextLoader | None, date: Any, out: Callable[[str], None]) -> int:
    """Run one of ``COMMANDS`` (called from ``me_atlas.pipeline``)."""
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
        loader = fulltext or live_fulltext_loader(cfg.cache_dir)
        out(str(link_audit_plan(cfg, args.slug, loader, second=args.second)))
        return 0
    if args.command == "record-link-audit":
        record = record_link_audit(cfg, args.slug, second=args.second)
        out(f"audit recorded: {record.decision}, {len(record.parts)} part(s)")
        return 0
    if args.command == "link-valve-apply":
        out(f"wording fix applied: {link_valve_apply(cfg, args.slug, args.stage)}")
        return 0
    if args.command == "link-valve-check-plan":
        out(str(link_valve_check_plan(cfg, args.slug, args.stage)))
        return 0
    if args.command == "record-link-valve-check":
        check = record_link_valve_check(cfg, args.slug, args.stage)
        out(f"fix check recorded: {'PASSED' if check.passed else 'FAILED'}, {len(check.fixes)} fix(es)")
        return 0
    assert args.command == "link-publish" and date is not None
    return link_publish(cfg, args.slug, date.isoformat(), dry_run=args.dry_run, out=out)
