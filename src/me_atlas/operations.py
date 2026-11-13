"""Operations on an evidence card: what the drafting agent may propose, and how code applies it.

The drafting agent never writes a whole card. It writes a list of operations as JSON (``OpsFile``); this
module validates them against a schema and applies them to the card's YAML text.

Operations:

* ``add_study``         append one study (all Study fields) to ``studies``
* ``add_paragraph``     append a sourced paragraph to a sourced-text field
* ``replace_paragraph`` replace paragraph ``index`` of such a field
* ``propose``           set the level, the contested mark or a badge (tier 2: the founder decides)

Sourced-text fields: ``level_reason``, ``contested.reason``, ``badges.diagnostic_marker.reason``,
``badges.explains_pem.reason`` (one sourced text or a list of paragraphs), and ``subgroups`` and
``early_signals`` (lists of sourced texts, one per item).

**Approach: text splices.** A YAML library cannot keep this repository's comments and folded text, so the
card is edited as lines. Only the lines of the named field are replaced or inserted; every other line stays
byte-identical. After each operation the edited text is parsed again and compared with the same change made
on the parsed data; any difference is an error, so a splice cannot silently produce a different card. What
splicing cannot do (a field written in flow style on one line, CRLF line endings) is refused with a message.
Comments inside a field that is rewritten (the whole reason of a ``propose``, one replaced paragraph) are
lost; comments elsewhere are kept.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from me_atlas.cards import (
    RECOGNISED_CASE_DEFINITIONS,
    Card,
    NonEmptyStr,
    Slug,
    Study,
    StudyId,
    _schema_issues,
    check_card,
)

PARAGRAPH_FIELDS = (
    "level_reason",
    "contested.reason",
    "badges.diagnostic_marker.reason",
    "badges.explains_pem.reason",
    "subgroups",
    "early_signals",
)
ParagraphField = Literal[
    "level_reason",
    "contested.reason",
    "badges.diagnostic_marker.reason",
    "badges.explains_pem.reason",
    "subgroups",
    "early_signals",
]
FOLD_WIDTH = 96


class OperationError(Exception):
    """An operation is invalid or cannot be applied. The card text is never changed when this is raised."""


# ---------------------------------------------------------------------------
# Schema of the operations file
# ---------------------------------------------------------------------------


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _collapse(text: str) -> str:
    return " ".join(text.split())


class _TextOp(_Op):
    text: NonEmptyStr
    sources: Annotated[list[StudyId], Field(min_length=1)]

    @field_validator("text")
    @classmethod
    def _one_line(cls, value: str) -> str:
        return _collapse(value)


class Paragraph(_TextOp):
    """One sourced paragraph, as used inside ``propose``."""


class AddStudy(_Op):
    op: Literal["add_study"]
    study: Study

    @model_validator(mode="after")
    def _provenance(self) -> AddStudy:
        s = self.study
        if s.case_definition == "unverified":
            if s.case_definition_source is not None or s.case_definition_quote is not None:
                raise ValueError("an 'unverified' case definition must have null source and null quote")
        elif s.case_definition_source is None:
            raise ValueError(
                f"case_definition '{s.case_definition}' needs case_definition_source (abstract or fulltext)"
            )
        if s.case_definition in RECOGNISED_CASE_DEFINITIONS and s.case_definition_quote is None:
            raise ValueError(
                f"case_definition '{s.case_definition}' needs case_definition_quote, "
                "the verbatim sentence from the source that states it"
            )
        return self


class AddParagraph(_TextOp):
    op: Literal["add_paragraph"]
    field: ParagraphField


class ReplaceParagraph(_TextOp):
    op: Literal["replace_paragraph"]
    field: ParagraphField
    index: Annotated[int, Field(strict=True, ge=0)]


class Propose(_Op):
    """Set the level, the contested mark or a badge. Always tier 2.

    ``target`` ``level``: ``value`` is the new level (0-5) and ``reason`` the new ``level_reason`` paragraphs.
    ``target`` ``contested``: ``value`` is the list of contested rungs, or ``null`` to remove the mark;
    ``reason`` the new ``contested.reason`` paragraphs (required when ``value`` is a list).
    ``target`` ``diagnostic_marker`` or ``explains_pem``: ``value`` is true or false; ``reason`` the new badge
    reason paragraphs (required when true, optional when false).
    """

    op: Literal["propose"]
    target: Literal["level", "contested", "diagnostic_marker", "explains_pem"]
    value: Any
    reason: Annotated[list[Paragraph], Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def _combination(self) -> Propose:
        v, t = self.value, self.target
        if t == "level":
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 5:
                raise ValueError("for target 'level', value must be a whole number from 0 to 5")
            if self.reason is None:
                raise ValueError("a level proposal needs reason: the new level_reason paragraphs")
        elif t == "contested":
            if v is None:
                if self.reason is not None:
                    raise ValueError("removing the contested mark (value null) takes no reason")
            elif isinstance(v, list) and v and all(isinstance(x, int) and not isinstance(x, bool) for x in v):
                if self.reason is None:
                    raise ValueError("a contested proposal needs reason: the new contested.reason paragraphs")
            else:
                raise ValueError("for target 'contested', value must be a non-empty list of rungs, or null to remove")
        else:
            if not isinstance(v, bool):
                raise ValueError(f"for target '{t}', value must be true or false")
            if v and self.reason is None:
                raise ValueError(f"'{t}': true needs reason: the badge reason paragraphs")
        return self


Operation = Annotated[AddStudy | AddParagraph | ReplaceParagraph | Propose, Field(discriminator="op")]


class OpsFile(_Op):
    """What the drafting agent writes for one card and one paper. No free text apart from card content."""

    card: Slug
    paper: StudyId
    operations: list[Operation]

    @model_validator(mode="after")
    def _studies_are_the_paper(self) -> OpsFile:
        for i, op in enumerate(self.operations):
            if isinstance(op, AddStudy) and op.study.id != self.paper:
                raise ValueError(
                    f"operations[{i}]: add_study may only add the paper '{self.paper}', not '{op.study.id}'"
                )
        return self


def preprint_ids(ops: OpsFile | Sequence[Operation], card_data: Mapping[str, Any] | None = None) -> frozenset[str]:
    """Ids of the studies marked ``preprint: true`` on the card (its parsed YAML) or added by these operations."""
    found: set[str] = set()
    studies = (card_data or {}).get("studies")
    for s in studies if isinstance(studies, list) else []:
        if isinstance(s, dict) and s.get("preprint") is True and isinstance(s.get("id"), str):
            found.add(s["id"])
    for op in ops.operations if isinstance(ops, OpsFile) else ops:
        if isinstance(op, AddStudy) and op.study.preprint:
            found.add(op.study.id)
    return frozenset(found)


def tier(op: Operation, preprints: Collection[str] = frozenset()) -> int:
    """Tier of one operation (functional spec section 6): propose is tier 2, everything else tier 1.

    An operation that adds a study with ``preprint: true``, or cites a preprint study (one of ``preprints``:
    see ``preprint_ids``) in its sources, is also tier 2: preprint changes are decided by the founder.
    """
    if isinstance(op, Propose):
        return 2
    if isinstance(op, AddStudy):
        return 2 if op.study.preprint or op.study.id in preprints else 1
    return 2 if any(src in preprints for src in op.sources) else 1


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return "\n".join(lines)


def parse_ops(data: object) -> OpsFile:
    """Validate parsed JSON as an operations file. Raises OperationError listing every problem."""
    try:
        return OpsFile.model_validate(data)
    except ValidationError as exc:
        raise OperationError(_format_errors(exc)) from exc


# ---------------------------------------------------------------------------
# Rendering YAML lines
# ---------------------------------------------------------------------------


def _scalar(value: object) -> str:
    out = yaml.safe_dump(value, width=10**9, allow_unicode=True, default_flow_style=True).rstrip()
    return out.removesuffix("\n...").rstrip()


def _flow_list(values: list[Any]) -> str:
    return _scalar(list(values))


def _folded(text: str, indent: int) -> list[str]:
    width = max(FOLD_WIDTH - indent, 30)
    return [" " * indent + line for line in textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)]


def _render_text(text: str, sources: list[str], ci: int, first_prefix: str) -> list[str]:
    """A sourced text as lines. ``ci`` is the column of its keys; ``first_prefix`` is '' or '- '."""
    pad = " " * ci
    key_pad = pad + " " * len(first_prefix)
    head = pad + first_prefix if first_prefix else pad
    return [
        f"{head}text: >-",
        *_folded(text, len(key_pad) + 2),
        f"{key_pad}sources: {_flow_list(sources)}",
    ]


def _render_item(text: str, sources: list[str], ci: int) -> list[str]:
    return _render_text(text, sources, ci, "- ")


def _render_items(paras: list[dict[str, Any]], ci: int) -> list[str]:
    return [line for p in paras for line in _render_item(p["text"], p["sources"], ci)]


_FOLD_STUDY_FIELDS = ("finding",)


def render_study(study: Study, ci: int) -> list[str]:
    """A study as the lines of a list item whose ``-`` is at column ``ci``."""
    data = study.model_dump(mode="python")
    if data["group"] is None:
        del data["group"]
    if not data["preprint"]:
        del data["preprint"]
    lines: list[str] = []
    for n, (name, value) in enumerate(data.items()):
        head = " " * ci + "- " if n == 0 else " " * (ci + 2)
        if name in _FOLD_STUDY_FIELDS and isinstance(value, str) and value == _collapse(value) and len(value) > 60:
            lines.append(f"{head}{name}: >-")
            lines += _folded(value, ci + 4)
        else:
            lines.append(f"{head}{name}: {_scalar(value)}")
    return lines


# ---------------------------------------------------------------------------
# Finding a field in the text
# ---------------------------------------------------------------------------


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith("#")


@dataclass(frozen=True)
class _Loc:
    key_line: int
    end: int  # exclusive; lines[key_line + 1:end] belong to the key
    indent: int
    key: str


def _find_key(lines: list[str], key: str, start: int, end: int, indent: int) -> int | None:
    pattern = re.compile(rf"^{' ' * indent}{re.escape(key)}:(?:\s|$)")
    for i in range(start, end):
        if pattern.match(lines[i]):
            return i
    return None


def _block_end(lines: list[str], i: int, indent: int, limit: int) -> int:
    j = i + 1
    while j < limit:
        line = lines[j]
        if not line.strip():
            j += 1
            continue
        ind = _indent(line)
        if ind > indent or (ind == indent and line.lstrip().startswith("- ")):
            j += 1
            continue
        break
    while j - 1 > i and not lines[j - 1].strip():
        j -= 1
    return j


def _first_content(lines: list[str], loc: _Loc) -> int | None:
    for k in range(loc.key_line + 1, loc.end):
        if _is_content(lines[k]):
            return k
    return None


def _locate(lines: list[str], path: list[str]) -> _Loc:
    start, end, indent = 0, len(lines), 0
    loc: _Loc | None = None
    for depth, key in enumerate(path):
        i = _find_key(lines, key, start, end, indent)
        shown = ".".join(path[: depth + 1])
        if i is None:
            raise OperationError(f"cannot find '{shown}' in the card text")
        loc = _Loc(i, _block_end(lines, i, indent, end), indent, key)
        if depth < len(path) - 1:
            first = _first_content(lines, loc)
            if first is None:
                raise OperationError(f"'{shown}' is written on one line (flow style) and cannot be edited by splice")
            start, end, indent = i + 1, loc.end, _indent(lines[first])
    assert loc is not None
    return loc


def _inline_value(lines: list[str], loc: _Loc) -> str:
    rest = lines[loc.key_line][loc.indent + len(loc.key) + 1 :]
    return re.sub(r"\s+#.*$", "", rest).strip()


def _replace_lines(lines: list[str], loc: _Loc, new: list[str]) -> list[str]:
    return lines[: loc.key_line] + new + lines[loc.end :]


# ---------------------------------------------------------------------------
# Data-side effect of each operation (the meaning), mirrored by a text splice
# ---------------------------------------------------------------------------


def _as_list(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    return list(value)  # type: ignore[call-overload]


def _get(data: dict[str, Any], field: str) -> tuple[dict[str, Any], str]:
    """The mapping that holds ``field`` and the last key. Raises if the path does not exist on this card."""
    parts = field.split(".")
    node: Any = data
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            raise OperationError(f"the card has no '{part}' to edit; use a propose operation to set it first")
    return node, parts[-1]


def _splice_paragraph(lines: list[str], op: AddParagraph | ReplaceParagraph) -> list[str]:
    path = op.field.split(".")
    loc = _locate(lines, path)
    inline = _inline_value(lines, loc)
    new = {"text": op.text, "sources": list(op.sources)}
    if inline in ("null", "~", "[]"):
        if isinstance(op, ReplaceParagraph):
            raise OperationError(f"paragraph index {op.index} is out of range for {op.field} (it has 0 paragraphs)")
        head = " " * loc.indent + f"{loc.key}:"
        return _replace_lines(lines, loc, [head, *_render_items([new], loc.indent + 2)])
    if inline:
        raise OperationError(
            f"{op.field} is written on one line (flow style); rewrite it as a block in the card before editing it"
        )
    first = _first_content(lines, loc)
    if first is None:
        raise OperationError(f"{op.field} has no content to edit")
    ci = _indent(lines[first])
    if lines[first].lstrip().startswith("- "):
        starts = [k for k in range(first, loc.end) if _indent(lines[k]) == ci and lines[k].lstrip().startswith("- ")]
        if isinstance(op, AddParagraph):
            return lines[: loc.end] + _render_items([new], ci) + lines[loc.end :]
        a = starts[op.index]
        b = starts[op.index + 1] if op.index + 1 < len(starts) else loc.end
        # blank lines and comments at the item's own column before the next item belong to the next item
        while b - 1 > a and (
            not lines[b - 1].strip() or (_indent(lines[b - 1]) <= ci and lines[b - 1].lstrip().startswith("#"))
        ):
            b -= 1
        return lines[:a] + _render_item(op.text, list(op.sources), ci) + lines[b:]
    # one sourced text written as a mapping
    if isinstance(op, ReplaceParagraph):
        body = _render_text(op.text, list(op.sources), ci, "")
        return lines[: loc.key_line + 1] + body + lines[loc.end :]
    converted = []
    for k in range(loc.key_line + 1, loc.end):
        line = lines[k]
        if not line.strip():
            converted.append(line)
        elif k == first:
            converted.append(line[:ci] + "- " + line[ci:])
        else:
            converted.append("  " + line)
    return lines[: loc.key_line + 1] + converted + _render_items([new], ci) + lines[loc.end :]


def _apply_paragraph(lines: list[str], data: dict[str, Any], op: AddParagraph | ReplaceParagraph) -> list[str]:
    parent, key = _get(data, op.field)
    current = parent.get(key)
    paras = _as_list(current)
    new = {"text": op.text, "sources": list(op.sources)}
    if isinstance(op, ReplaceParagraph):
        if op.index >= len(paras):
            raise OperationError(
                f"paragraph index {op.index} is out of range for {op.field} "
                f"({len(paras)} paragraph{'s' if len(paras) != 1 else ''}; indexes start at 0)"
            )
        parent[key] = new if isinstance(current, dict) else [*paras[: op.index], new, *paras[op.index + 1 :]]
    else:
        parent[key] = [*paras, new]
    return _splice_paragraph(lines, op)


def _apply_study(lines: list[str], data: dict[str, Any], op: AddStudy) -> list[str]:
    studies = data.get("studies")
    if not isinstance(studies, list):
        raise OperationError("the card has no studies list")
    if any(isinstance(s, dict) and s.get("id") == op.study.id for s in studies):
        raise OperationError(f"study id '{op.study.id}' is already on this card")
    entry = op.study.model_dump(mode="python")
    if entry["group"] is None:
        del entry["group"]
    if not entry["preprint"]:
        del entry["preprint"]
    studies.append(entry)
    loc = _locate(lines, ["studies"])
    inline = _inline_value(lines, loc)
    if inline == "[]":
        return _replace_lines(lines, loc, [f"{loc.key}:", *render_study(op.study, 2)])
    if inline:
        raise OperationError("studies is written on one line (flow style) and cannot be edited by splice")
    first = _first_content(lines, loc)
    ci = _indent(lines[first]) if first is not None else 2
    return lines[: loc.end] + render_study(op.study, ci) + lines[loc.end :]


def _paragraph_dicts(paras: list[Paragraph]) -> list[dict[str, Any]]:
    return [{"text": p.text, "sources": list(p.sources)} for p in paras]


def _set_reason(lines: list[str], path: list[str], paras: list[dict[str, Any]] | None) -> list[str]:
    loc = _locate(lines, path)
    if paras is None:
        return _replace_lines(lines, loc, [" " * loc.indent + f"{loc.key}: null"])
    return _replace_lines(lines, loc, [" " * loc.indent + f"{loc.key}:", *_render_items(paras, loc.indent + 2)])


def _apply_propose(lines: list[str], data: dict[str, Any], op: Propose) -> list[str]:
    paras = _paragraph_dicts(op.reason) if op.reason else None
    if op.target == "level":
        assert paras is not None
        data["level"] = op.value
        data["level_reason"] = paras
        loc = _locate(lines, ["level"])
        lines = lines[: loc.key_line] + [f"level: {op.value}"] + lines[loc.end :]
        return _set_reason(lines, ["level_reason"], paras)
    if op.target == "contested":
        loc = _locate(lines, ["contested"])
        if op.value is None:
            if data.get("contested") is None:
                raise OperationError("the card has no contested mark to remove")
            data["contested"] = None
            return _replace_lines(lines, loc, ["contested: null"])
        assert paras is not None and isinstance(op.value, list)
        data["contested"] = {"rungs": list(op.value), "reason": paras}
        block = ["contested:", f"  rungs: {_flow_list(op.value)}", "  reason:", *_render_items(paras, 4)]
        return _replace_lines(lines, loc, block)
    badge = data["badges"][op.target]
    badge["value"] = op.value
    badge["reason"] = paras
    base = ["badges", op.target]
    loc = _locate(lines, base)
    first = _first_content(lines, loc)
    if first is None:
        raise OperationError(f"badges.{op.target} is written on one line (flow style) and cannot be edited by splice")
    child = _indent(lines[first])
    vi = _find_key(lines, "value", loc.key_line + 1, loc.end, child)
    if vi is None:
        raise OperationError(f"cannot find 'badges.{op.target}.value' in the card text")
    lines = [*lines[:vi], f"{' ' * child}value: {_scalar(op.value)}", *lines[vi + 1 :]]
    return _set_reason(lines, [*base, "reason"], paras)


def _validation_problems(data: dict[str, Any]) -> list[str]:
    try:
        card = Card.model_validate(data)
    except ValidationError as exc:
        return [f"{i.path}: {i.message}" for i in _schema_issues(exc, "")]
    return [f"[{rule}] {path}: {message}" for rule, path, message in check_card(card, str(data.get("slug", "")))]


def apply_operations(text: str, operations: list[Operation] | OpsFile, *, validate: bool = True) -> str:
    """Apply operations in order to card YAML text and return the new text.

    Pure: the input is never changed, and on any error (``OperationError``) nothing is returned. Lines not
    named by an operation are byte-identical. With ``validate`` (default) the result must also pass the card
    validator and the card must have passed it before; the pipeline passes ``validate=False`` and runs the
    validator itself so it can report validator failures apart from bad operations.
    """
    ops = operations.operations if isinstance(operations, OpsFile) else list(operations)
    if "\r" in text:
        raise OperationError("the card file uses CRLF line endings; convert it to LF first")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise OperationError(f"the card does not parse as YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise OperationError("the card's top level must be a mapping")
    if validate and (problems := _validation_problems(data)):
        raise OperationError("the card does not validate before the operations:\n" + "\n".join(problems))

    lines = text.split("\n")
    for n, op in enumerate(ops):
        try:
            if isinstance(op, AddStudy):
                lines = _apply_study(lines, data, op)
            elif isinstance(op, (AddParagraph, ReplaceParagraph)):
                lines = _apply_paragraph(lines, data, op)
            else:
                lines = _apply_propose(lines, data, op)
        except OperationError as exc:
            raise OperationError(f"operations[{n}] ({op.op}): {exc}") from exc
        try:
            reparsed = yaml.safe_load("\n".join(lines))
        except yaml.YAMLError as exc:
            raise OperationError(f"operations[{n}] ({op.op}): the edited text does not parse: {exc}") from exc
        if reparsed != data:
            raise OperationError(
                f"operations[{n}] ({op.op}): the edited text does not match the intended change; nothing applied"
            )
    if validate and (problems := _validation_problems(data)):
        raise OperationError("the card does not validate after the operations:\n" + "\n".join(problems))
    return "\n".join(lines)
