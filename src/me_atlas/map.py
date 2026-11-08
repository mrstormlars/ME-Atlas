"""Causal map: the layers, the links between hypotheses, and the counts that find common mechanisms.

A card may carry a ``layer`` and a list of ``links`` (see ``docs/card-format.md``). This module

- loads and validates the two content files, ``content/symptoms.yaml`` and ``content/open-questions.yaml`` (rule M6),
- checks that every link target exists (rule M2; M1 and M3-M5 are in ``me_atlas.cards``),
- builds the graph and counts convergence, and
- prints a report::

    uv run python -m me_atlas.map report [--drafts] [--cards DIR] [--content DIR]

Nothing here calls the network or an AI. Convergence is counted, never judged: the report prints "candidate" lists.
See ``docs/map.md``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from me_atlas import cards as cardlib
from me_atlas.cards import _BANNED_NB_RE, _BANNED_RE, Card, Issue, NonEmptyStr, Slug, StudyId

SYMPTOMS_FILE = "symptoms.yaml"
QUESTIONS_FILE = "open-questions.yaml"
# Plan order, root to experience. The first four hold hypothesis cards; "symptom" holds the symptom list.
LAYER_ORDER = (*cardlib.LAYERS, "symptom")
LayerKey = Literal["predisposition", "trigger", "mechanism", "dysfunction", "symptom"]
UNPLACED = "unplaced"
SYMPTOM_PREFIX = "symptom:"
QUESTION_PREFIX = "question:"
_TARGET_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# Content files (rule M6)
# ---------------------------------------------------------------------------


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Symptom(_M):
    id: Slug
    name: NonEmptyStr
    sources: list[StudyId] = []
    todo: Literal["verify"] | None = None

    @model_validator(mode="after")
    def _sourced(self) -> Symptom:
        if self.todo is None and not self.sources:
            raise ValueError("needs at least one source (the case-definition document), or 'todo: verify'")
        if self.todo is not None and self.sources:
            raise ValueError("'todo: verify' stands instead of sources; give one or the other")
        return self


class Question(_M):
    id: Slug
    layer: LayerKey
    text: NonEmptyStr
    asked_by: list[StudyId] = []
    editorial: bool = False
    todo: Literal["verify"] | None = None

    @model_validator(mode="after")
    def _origin(self) -> Question:
        if self.todo is not None:
            if self.asked_by:
                raise ValueError("'todo: verify' stands instead of asked_by; give one or the other")
            return self
        if bool(self.asked_by) == self.editorial:
            raise ValueError("needs exactly one of a non-empty 'asked_by' or 'editorial: true'")
        return self


class LocalSymptom(_M):
    id: Slug
    name: NonEmptyStr


class LocalQuestion(_M):
    id: Slug
    text: NonEmptyStr


@dataclass(frozen=True)
class MapContent:
    """The built entries; ``excluded`` holds the keys (``symptom:x``) of valid entries marked ``todo: verify``."""

    symptoms: tuple[Symptom, ...] = ()
    questions: tuple[Question, ...] = ()
    excluded: frozenset[str] = frozenset()


def _load_list(path: Path, model: type[_M]) -> tuple[list, list[Issue]]:
    """Entries that pass the schema, and the problems. A file that does not exist is not a problem (no entries)."""
    if not path.is_file():
        return [], []
    data, issues = cardlib._read_yaml(path)
    if issues:
        return [], [Issue("M6", i.file, i.path, i.message) for i in issues]
    file = str(path)
    if data is None:
        return [], []
    if not isinstance(data, list):
        return [], [Issue("M6", file, "", "top level must be a list of entries")]
    entries: list = []
    for i, raw in enumerate(data):
        try:
            entries.append(model.model_validate(raw))
        except ValidationError as exc:
            issues += [
                Issue("M6", file, f"[{i}]" + (f".{e.path}" if e.path else ""), e.message)
                for e in cardlib._schema_issues(exc, file)
            ]
    return entries, issues


def _banned(file: str, entries: Sequence, field_name: str) -> list[Issue]:
    out: list[Issue] = []
    for i, e in enumerate(entries):
        for pattern in (_BANNED_RE, _BANNED_NB_RE):
            out += [
                Issue("M6", file, f"[{i}].{field_name}", f"banned word '{m.group(0)}'")
                for m in pattern.finditer(getattr(e, field_name))
            ]
    return out


def _duplicates(file: str, entries: Sequence) -> list[Issue]:
    seen: set[str] = set()
    out: list[Issue] = []
    for i, e in enumerate(entries):
        if e.id in seen:
            out.append(Issue("M6", file, f"[{i}].id", f"duplicate id '{e.id}'"))
        seen.add(e.id)
    return out


def load_content(content_dir: Path) -> tuple[MapContent, list[Issue]]:
    """Read and validate ``symptoms.yaml`` and ``open-questions.yaml`` in ``content_dir`` (both optional)."""
    content_dir = Path(content_dir)
    sym_path, q_path = content_dir / SYMPTOMS_FILE, content_dir / QUESTIONS_FILE
    symptoms, issues = _load_list(sym_path, Symptom)
    questions, q_issues = _load_list(q_path, Question)
    issues += q_issues
    issues += _duplicates(str(sym_path), symptoms) + _duplicates(str(q_path), questions)
    issues += _banned(str(sym_path), symptoms, "name") + _banned(str(q_path), questions, "text")
    excluded = frozenset(
        [SYMPTOM_PREFIX + s.id for s in symptoms if s.todo] + [QUESTION_PREFIX + q.id for q in questions if q.todo]
    )
    content = MapContent(tuple(s for s in symptoms if not s.todo), tuple(q for q in questions if not q.todo), excluded)
    return content, issues


def content_warnings(content: MapContent) -> list[str]:
    return [
        f"'{key}' is marked 'todo: verify' and is left out of the build and the report"
        for key in sorted(content.excluded)
    ]


def load_local_texts(
    content_dir: Path, lang: str, content: MapContent
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Translated symptom names and question texts (``symptoms.<lang>.yaml``, ``open-questions.<lang>.yaml``) by
    key (``symptom:x``). Every id must exist in the English file and appear once. Returns (names, texts, problems)."""
    content_dir = Path(content_dir)
    problems: list[str] = []
    result: list[dict[str, str]] = []
    for filename, model, prefix, known, attr in (
        (f"symptoms.{lang}.yaml", LocalSymptom, SYMPTOM_PREFIX, {s.id for s in content.symptoms}, "name"),
        (f"open-questions.{lang}.yaml", LocalQuestion, QUESTION_PREFIX, {q.id for q in content.questions}, "text"),
    ):
        path = content_dir / filename
        entries, issues = _load_list(path, model)
        problems += [str(i) for i in issues]
        problems += [str(i) for i in _duplicates(str(path), entries)]
        problems += [str(i) for i in _banned(str(path), entries, attr)]
        out: dict[str, str] = {}
        for i, e in enumerate(entries):
            if e.id not in known:
                problems.append(f"{path}: [{i}].id: '{e.id}' is not an id of the English file")
            else:
                out[prefix + e.id] = getattr(e, attr)
        result.append(out)
    return result[0], result[1], problems


# ---------------------------------------------------------------------------
# Rule M2: link targets
# ---------------------------------------------------------------------------


def check_targets(card_files: Sequence[tuple[str, Card]], known_slugs: set[str], content: MapContent) -> list[Issue]:
    """M2 for every link of every given card. ``known_slugs`` is the resolution set (see docs/map.md)."""
    out: list[Issue] = []
    symptom_keys = {SYMPTOM_PREFIX + s.id for s in content.symptoms}
    question_keys = {QUESTION_PREFIX + q.id for q in content.questions}
    for file, card in card_files:
        for i, link in enumerate(card.links):
            to = link.to
            path = f"links[{i}].to"
            if to.startswith(SYMPTOM_PREFIX):
                if to in content.excluded:
                    out.append(Issue("M2", file, path, f"'{to}' is marked 'todo: verify' and is not built"))
                elif to not in symptom_keys:
                    out.append(Issue("M2", file, path, f"'{to}' is not an entry of content/{SYMPTOMS_FILE}"))
            elif to.startswith(QUESTION_PREFIX):
                if to in content.excluded:
                    out.append(Issue("M2", file, path, f"'{to}' is marked 'todo: verify' and is not built"))
                elif to not in question_keys:
                    out.append(Issue("M2", file, path, f"'{to}' is not an entry of content/{QUESTIONS_FILE}"))
            elif not _TARGET_SLUG.match(to):
                out.append(Issue("M2", file, path, f"'{to}' is not a card slug, 'symptom:<id>' or 'question:<id>'"))
            elif to != card.slug and to not in known_slugs:  # a self-link is reported by M3
                out.append(Issue("M2", file, path, f"no card '{to}' to link to"))
    return out


# ---------------------------------------------------------------------------
# The graph and its counts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    key: str  # a card slug, "symptom:<id>" or "question:<id>"
    kind: Literal["card", "symptom", "question"]
    name: str
    layer: str  # one of LAYER_ORDER, or UNPLACED for a card with no layer


@dataclass(frozen=True)
class Edge:
    source: str  # card slug
    index: int  # position in the card's links
    target: str  # node key
    support: str
    sources: tuple[str, ...]
    text: str


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    out: dict[str, list[Edge]] = field(default_factory=dict)
    incoming: dict[str, list[Edge]] = field(default_factory=dict)

    def in_layer(self, layer: str, kind: str | None = None) -> list[Node]:
        return [n for n in self.nodes.values() if n.layer == layer and (kind is None or n.kind == kind)]


def build_graph(cards: Sequence[Card], content: MapContent) -> Graph:
    """Nodes: every card, symptom and question, in the order given. A link whose target is not a node is skipped
    (validation reports it)."""
    g = Graph()
    for c in cards:
        g.nodes[c.slug] = Node(c.slug, "card", c.name, c.layer or UNPLACED)
    for s in content.symptoms:
        g.nodes[SYMPTOM_PREFIX + s.id] = Node(SYMPTOM_PREFIX + s.id, "symptom", s.name, "symptom")
    for q in content.questions:
        g.nodes[QUESTION_PREFIX + q.id] = Node(QUESTION_PREFIX + q.id, "question", q.text, q.layer)
    for c in cards:
        for i, link in enumerate(c.links):
            if link.to not in g.nodes:
                continue
            edge = Edge(c.slug, i, link.to, link.support, tuple(link.sources), link.text)
            g.out.setdefault(c.slug, []).append(edge)
            g.incoming.setdefault(link.to, []).append(edge)
    return g


def common_mechanisms(g: Graph) -> list[tuple[Node, int]]:
    """Nodes with two or more incoming links from different cards, with that number of cards. Most first."""
    found = [
        (g.nodes[key], len({e.source for e in edges}))
        for key, edges in g.incoming.items()
        if len({e.source for e in edges}) >= 2
    ]
    return sorted(found, key=lambda nc: (-nc[1], nc[0].name.casefold(), nc[0].key))


def candidate_roots(g: Graph) -> list[tuple[Node, int]]:
    """Cards with two or more links out, with the number of links. Most first."""
    found = [(g.nodes[key], len(edges)) for key, edges in g.out.items() if len(edges) >= 2]
    return sorted(found, key=lambda nc: (-nc[1], nc[0].name.casefold(), nc[0].key))


def unlinked_symptoms(g: Graph) -> list[Node]:
    """Symptom nodes with no incoming link, in node order."""
    return [n for n in g.nodes.values() if n.kind == "symptom" and not g.incoming.get(n.key)]


def proposed_only_symptoms(g: Graph) -> list[tuple[Node, tuple[str, ...]]]:
    """Symptom nodes with at least one incoming link, all of them ``proposed``, with the distinct source cards
    (slugs, in card order). Node order."""
    found: list[tuple[Node, tuple[str, ...]]] = []
    for n in g.nodes.values():
        edges = g.incoming.get(n.key, [])
        if n.kind == "symptom" and edges and all(e.support == "proposed" for e in edges):
            found.append((n, tuple(dict.fromkeys(e.source for e in edges))))
    return found


def proposed_links(g: Graph) -> list[tuple[Node, list[Edge]]]:
    """Every link at step ``proposed``, grouped by target node. Groups in node order, edges in card order."""
    found: list[tuple[Node, list[Edge]]] = []
    for n in g.nodes.values():
        edges = [e for e in g.incoming.get(n.key, []) if e.support == "proposed"]
        if edges:
            found.append((n, edges))
    return found


def unlinked_cards(g: Graph) -> list[Node]:
    """Card nodes with no link in and none out, in node order."""
    return [n for n in g.nodes.values() if n.kind == "card" and not g.incoming.get(n.key) and not g.out.get(n.key)]


def cards_by_level(cards: Sequence[Card]) -> list[tuple[int, list[Card]]]:
    """Cards grouped by level, 5 down to 0, alphabetical by name within a level (the front page's order). Only
    levels that have a card."""
    groups: dict[int, list[Card]] = {}
    for c in cards:
        groups.setdefault(c.level, []).append(c)
    return [
        (level, sorted(groups[level], key=lambda c: (c.name.casefold(), c.slug)))
        for level in sorted(groups, reverse=True)
    ]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

# The plain-language names of the rungs of the evidence ladder (docs/ME-Atlas-functional-spec.md section 3).
RUNG_NAMES = (
    "Proposed",
    "First signs",
    "Backed in a defined group",
    "Repeated by others",
    "Tested by intervention",
    "Causal case built",
)

LAYER_TITLES = {
    "predisposition": "Predisposition",
    "trigger": "Trigger",
    "mechanism": "Perpetuating mechanism",
    "dysfunction": "Measurable dysfunction",
    "symptom": "Symptom",
    UNPLACED: "Not yet placed",
}


def render_report(g: Graph, cards: Sequence[Card] = ()) -> str:
    lines: list[str] = []
    for layer in (*cardlib.LAYERS, UNPLACED):
        members = g.in_layer(layer, "card")
        lines.append(f"{LAYER_TITLES[layer]} ({len(members)})")
        for node in members:
            lines.append(f"  {node.name} ({node.key})")
            for e in g.out.get(node.key, []):
                lines.append(f"    -> {g.nodes[e.target].name} [{e.support}] ({', '.join(e.sources)})")
        lines.append("")
    symptoms = [n for n in g.nodes.values() if n.kind == "symptom"]
    questions = [n for n in g.nodes.values() if n.kind == "question"]
    lines.append(f"Symptoms ({len(symptoms)})")
    lines += [f"  {n.name} ({n.key})" for n in symptoms]
    lines.append("")
    lines.append(f"Open questions ({len(questions)})")
    lines += [f"  [{n.layer}] {n.name} ({n.key})" for n in questions]
    lines.append("")
    for title, found, unit in (
        ("Candidate common mechanisms", common_mechanisms(g), "incoming links from different cards"),
        ("Candidate roots", candidate_roots(g), "links out"),
    ):
        lines.append(f"{title} ({len(found)})")
        lines += [f"  {n.name} ({n.key}): {count} {unit}" for n, count in found]
        if not found:
            lines.append("  none")
        lines.append("")
    lines += _gap_lines(g, cards)
    return "\n".join(lines).rstrip() + "\n"


def _gap_lines(g: Graph, cards: Sequence[Card]) -> list[str]:
    """The gap lists: counted and listed, never judged."""
    lines: list[str] = []
    unlinked = unlinked_symptoms(g)
    lines.append(f"Symptoms with no link ({len(unlinked)})")
    lines += [f"  {n.name} ({n.key})" for n in unlinked]
    if not unlinked:
        lines.append("  none")
    lines.append("")
    step1 = proposed_only_symptoms(g)
    lines.append(f"Symptoms linked only at step 1 ({len(step1)})")
    for n, sources in step1:
        word = "hypothesis" if len(sources) == 1 else "hypotheses"
        lines.append(f"  {n.name} ({n.key}): {len(sources)} {word}, none above step 1")
        lines += [f"    <- {g.nodes[s].name} ({s})" for s in sources]
    if not step1:
        lines.append("  none")
    lines.append("")
    groups = proposed_links(g)
    lines.append(f"Links not yet tested in patients ({sum(len(es) for _, es in groups)})")
    for n, edges in groups:
        lines.append(f"  -> {n.name} ({n.key})")
        lines += [f"    <- {g.nodes[e.source].name} [{e.support}] ({', '.join(e.sources)})" for e in edges]
    if not groups:
        lines.append("  none")
    lines.append("")
    lines.append("What the next rung requires")
    levels = cards_by_level(cards)
    for level, members in levels:
        lines.append(f"  Level {level}: {RUNG_NAMES[level]}")
        for c in members:
            line = f"    {c.name} ({c.slug})"
            if c.contested:
                line += f" — contested at rung(s) {', '.join(str(r) for r in sorted(c.contested.rungs))}"
            lines.append(line)
        if level < 5:
            lines.append(f"    next: {RUNG_NAMES[level + 1]}")
    if not levels:
        lines.append("  none")
    lines.append("")
    loose = unlinked_cards(g)
    lines.append(f"Hypotheses with no links yet ({len(loose)})")
    lines += [f"  {n.name} ({n.key})" for n in loose]
    if not loose:
        lines.append("  none")
    lines.append("")
    return lines


def _card_paths(cards_dir: Path, drafts_dir: Path | None) -> list[Path]:
    """Cards, then drafts; a draft replaces the card with the same slug (as in the site build)."""
    by_slug: dict[str, Path] = {}
    for directory in (cards_dir, drafts_dir):
        if directory is not None and directory.is_dir():
            for p in sorted(directory.glob("*.yaml")):
                if p.name != cardlib.CHANGELOG_NAME:
                    by_slug[p.stem] = p
    return sorted(by_slug.values(), key=lambda p: p.stem)


def run_report(cards_dir: Path, drafts_dir: Path | None, content_dir: Path) -> int:
    paths = _card_paths(cards_dir, drafts_dir)
    _, issues = cardlib.validate_paths(paths, content_dir=content_dir, cards_dir=cards_dir)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        print(f"FAILED: {len(issues)} error(s); no report", file=sys.stderr)
        return 1
    content, _ = load_content(content_dir)
    for w in content_warnings(content):
        print(f"warning: {w}", file=sys.stderr)
    cards = sorted((cardlib.load_card(p) for p in paths), key=lambda c: (c.name.casefold(), c.slug))
    sys.stdout.write(render_report(build_graph(cards, content), cards))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m me_atlas.map", description="Causal map tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="print the layers, the links and the convergence lists")
    rep.add_argument("--drafts", action="store_true", help="also read the cards in drafts/ (they replace the cards)")
    rep.add_argument("--cards", type=Path, default=Path("cards"), help="default: %(default)s")
    rep.add_argument("--drafts-dir", type=Path, default=Path("drafts"), help=argparse.SUPPRESS)
    rep.add_argument("--content", type=Path, default=Path("content"), help="default: %(default)s")
    args = parser.parse_args(argv)
    return run_report(args.cards, args.drafts_dir if args.drafts else None, args.content)


if __name__ == "__main__":
    raise SystemExit(main())
