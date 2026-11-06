"""Tests for the causal map: link targets (M2), content files (M6), convergence counts and the report.

Fictional cards and content only; no network, no AI.
"""

import copy
from pathlib import Path

import pytest
import yaml

from me_atlas import cards as cardlib
from me_atlas import map as maplib

FIXTURE = Path(__file__).parent / "fixtures" / "cards" / "fictional-hypothesis.yaml"


def card_data(slug: str, name: str | None = None, layer: str | None = None, links=()) -> dict:
    data = copy.deepcopy(yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))
    data["slug"] = slug
    data["name"] = name or slug.replace("-", " ").title()
    if layer:
        data["layer"] = layer
    data["links"] = [dict(x) for x in links]
    return data


def lk(to: str, support: str = "proposed", sources=("pmid:00000001",), text: str = "A fictional link.") -> dict:
    return {"to": to, "support": support, "text": text, "sources": list(sources)}


def put(directory: Path, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{data['slug']}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def dump(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


SYMPTOMS = [{"id": "fatigue", "name": "Fictional fatigue", "sources": ["doi:10.0000/fictional.5"]}]
QUESTIONS = [
    {"id": "what-keeps-it-going", "layer": "mechanism", "text": "What keeps it going?", "editorial": True},
    {"id": "asked", "layer": "trigger", "text": "What starts it?", "asked_by": ["doi:10.0000/fictional.5"]},
]


@pytest.fixture
def content(tmp_path: Path) -> Path:
    folder = tmp_path / "content"
    dump(folder / "symptoms.yaml", SYMPTOMS)
    dump(folder / "open-questions.yaml", QUESTIONS)
    return folder


def validate(tmp_path: Path, content_dir: Path, *paths: Path):
    return cardlib.validate_paths(list(paths), content_dir=content_dir, cards_dir=tmp_path / "no-cards")


# --- M2: targets --------------------------------------------------------------


def test_links_that_resolve_pass(tmp_path, content):
    cards_dir = tmp_path / "cards"
    put(cards_dir, card_data("card-a", links=[lk("card-b"), lk("symptom:fatigue"), lk("question:asked")]))
    put(cards_dir, card_data("card-b"))
    _, issues = validate(tmp_path, content, cards_dir)
    assert issues == []


@pytest.mark.parametrize(
    ("to", "fragment"),
    [
        ("no-such-card", "no card 'no-such-card'"),
        ("symptom:nope", "'symptom:nope' is not an entry of content/symptoms.yaml"),
        ("question:nope", "'question:nope' is not an entry of content/open-questions.yaml"),
        ("foo:bar", "'foo:bar' is not a card slug"),
        ("Not A Slug", "'Not A Slug' is not a card slug"),
    ],
)
def test_m2_a_target_that_does_not_resolve_names_the_value(tmp_path, content, to, fragment):
    put(tmp_path / "cards", card_data("card-a", links=[lk(to)]))
    _, issues = validate(tmp_path, content, tmp_path / "cards")
    assert [i.rule for i in issues] == ["M2"]
    assert issues[0].path == "links[0].to" and fragment in issues[0].message


def test_m2_symptom_links_fail_when_the_symptom_file_is_absent(tmp_path):
    put(tmp_path / "cards", card_data("card-a", links=[lk("symptom:fatigue")]))
    _, issues = validate(tmp_path, tmp_path / "empty-content", tmp_path / "cards")
    assert [i.rule for i in issues] == ["M2"]


def test_m2_a_self_link_is_reported_once_by_m3_only(tmp_path, content):
    put(tmp_path / "cards", card_data("card-a", links=[lk("card-a")]))
    _, issues = validate(tmp_path, content, tmp_path / "cards")
    assert [i.rule for i in issues] == ["M3"]


def test_m2_a_link_to_an_entry_marked_todo_verify_fails(tmp_path):
    folder = tmp_path / "content"
    dump(folder / "symptoms.yaml", [{"id": "pending", "name": "Fictional pending", "todo": "verify"}])
    put(tmp_path / "cards", card_data("card-a", links=[lk("symptom:pending")]))
    _, issues = validate(tmp_path, folder, tmp_path / "cards")
    assert [i.rule for i in issues] == ["M2"] and "todo: verify" in issues[0].message


def test_a_draft_may_link_to_a_published_card_when_a_directory_is_validated(tmp_path, content):
    put(tmp_path / "cards", card_data("published-card"))
    put(tmp_path / "drafts", card_data("draft-card", links=[lk("published-card")]))
    args = {"content_dir": content, "cards_dir": tmp_path / "cards"}
    assert cardlib.validate_paths([tmp_path / "drafts"], **args)[1] == []
    # a single file given on its own is checked against the files given only
    one_file = cardlib.validate_paths([tmp_path / "drafts" / "draft-card.yaml"], **args)[1]
    assert [i.rule for i in one_file] == ["M2"]


def test_cards_validate_command_reports_m2_and_exits_1(tmp_path, content, capsys):
    put(tmp_path / "cards", card_data("card-a", links=[lk("no-such-card")]))
    argv = ["validate", str(tmp_path / "cards"), "--content", str(content), "--cards", str(tmp_path / "x")]
    assert cardlib.main(argv) == 1
    assert "[M2]" in capsys.readouterr().err


# --- M6: content files ----------------------------------------------------------


def load(tmp_path: Path, symptoms=None, questions=None):
    folder = tmp_path / "c"
    if symptoms is not None:
        dump(folder / "symptoms.yaml", symptoms)
    if questions is not None:
        dump(folder / "open-questions.yaml", questions)
    return maplib.load_content(folder)


def test_valid_content_loads(tmp_path):
    content, issues = load(tmp_path, SYMPTOMS, QUESTIONS)
    assert issues == [] and [s.id for s in content.symptoms] == ["fatigue"] and len(content.questions) == 2


def test_absent_content_files_are_fine(tmp_path):
    content, issues = maplib.load_content(tmp_path / "nothing")
    assert issues == [] and content.symptoms == () and content.questions == ()


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "x", "name": "Fictional x"},  # neither sources nor todo
        {"id": "x", "name": "Fictional x", "sources": []},
        {"id": "x", "name": "Fictional x", "sources": ["doi:10.0000/f"], "todo": "verify"},
        {"id": "x", "name": "Fictional x", "sources": ["not-an-id"]},
        {"id": "Bad Id", "name": "Fictional x", "sources": ["doi:10.0000/f"]},
        {"id": "x", "name": "Fictional x", "sources": ["doi:10.0000/f"], "extra": 1},
        {"id": "x", "name": "Fictional cure", "sources": ["doi:10.0000/f"]},
    ],
)
def test_m6_bad_symptom_entries(tmp_path, entry):
    _, issues = load(tmp_path, [entry])
    assert issues and {i.rule for i in issues} == {"M6"}


def test_m6_duplicate_symptom_ids(tmp_path):
    _, issues = load(tmp_path, [SYMPTOMS[0], dict(SYMPTOMS[0])])
    assert [i.rule for i in issues] == ["M6"] and "duplicate id 'fatigue'" in issues[0].message


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "q", "layer": "mechanism", "text": "Fictional?"},  # neither
        {"id": "q", "layer": "mechanism", "text": "Fictional?", "editorial": True, "asked_by": ["doi:10.0000/f"]},
        {"id": "q", "layer": "mechanism", "text": "Fictional?", "editorial": False, "asked_by": []},
        {"id": "q", "layer": "organ", "text": "Fictional?", "editorial": True},
        {"id": "q", "layer": "mechanism", "text": "Fictional?", "editorial": True, "extra": 1},
    ],
)
def test_m6_bad_question_entries(tmp_path, entry):
    _, issues = load(tmp_path, None, [entry])
    assert issues and {i.rule for i in issues} == {"M6"}


def test_m6_duplicate_question_ids(tmp_path):
    _, issues = load(tmp_path, None, [QUESTIONS[0], dict(QUESTIONS[0])])
    assert [i.rule for i in issues] == ["M6"]


def test_m6_unreadable_yaml_and_wrong_top_level(tmp_path):
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "symptoms.yaml").write_text("a: [unclosed\n", encoding="utf-8")
    (folder / "open-questions.yaml").write_text("id: x\n", encoding="utf-8")
    _, issues = maplib.load_content(folder)
    assert len(issues) == 2 and {i.rule for i in issues} == {"M6"}


def test_todo_verify_entries_are_valid_but_left_out_with_a_warning(tmp_path):
    content, issues = load(
        tmp_path,
        [*SYMPTOMS, {"id": "pending", "name": "Fictional pending", "todo": "verify"}],
        [{"id": "pq", "layer": "trigger", "text": "Fictional pending question?", "todo": "verify"}],
    )
    assert issues == []
    assert [s.id for s in content.symptoms] == ["fatigue"] and content.questions == ()
    warnings = maplib.content_warnings(content)
    assert any("symptom:pending" in w for w in warnings) and any("question:pq" in w for w in warnings)


def test_validate_paths_reports_content_errors_with_the_cards(tmp_path):
    put(tmp_path / "cards", card_data("card-a"))
    folder = tmp_path / "content"
    dump(folder / "symptoms.yaml", [{"id": "x", "name": "Fictional x"}])
    count, issues = validate(tmp_path, folder, tmp_path / "cards")
    assert [i.rule for i in issues] == ["M6"] and count == 2


def test_local_texts_are_checked_against_the_english_ids(tmp_path, content):
    english, _ = maplib.load_content(content)
    dump(content / "symptoms.nb.yaml", [{"id": "fatigue", "name": "Fiktiv utmattelse"}])
    dump(content / "open-questions.nb.yaml", [{"id": "ghost", "text": "Hva?"}])
    names, texts, problems = maplib.load_local_texts(content, "nb", english)
    assert names == {"symptom:fatigue": "Fiktiv utmattelse"} and texts == {}
    assert len(problems) == 1 and "'ghost' is not an id of the English file" in problems[0]


# --- the graph and the counts -----------------------------------------------------


def build(tmp_path: Path, content_dir: Path, *datas: dict):
    for d in datas:
        put(tmp_path / "cards", d)
    paths = sorted((tmp_path / "cards").glob("*.yaml"))
    content, _ = maplib.load_content(content_dir)
    return maplib.build_graph([cardlib.load_card(p) for p in paths], content)


def test_two_incoming_links_from_different_cards_make_a_candidate_common_mechanism(tmp_path, content):
    g = build(
        tmp_path,
        content,
        card_data("card-a", "Card A", "predisposition", [lk("card-c")]),
        card_data("card-b", "Card B", "trigger", [lk("card-c")]),
        card_data("card-c", "Card C", "mechanism"),
    )
    assert [(n.key, count) for n, count in maplib.common_mechanisms(g)] == [("card-c", 2)]
    assert maplib.candidate_roots(g) == []  # one link out each


def test_two_links_out_make_a_candidate_root_and_one_does_not(tmp_path, content):
    g = build(
        tmp_path,
        content,
        card_data("card-a", "Card A", "predisposition", [lk("card-b"), lk("symptom:fatigue")]),
        card_data("card-b", "Card B", "mechanism", [lk("symptom:fatigue")]),
    )
    assert [(n.key, c) for n, c in maplib.candidate_roots(g)] == [("card-a", 2)]
    assert [(n.key, c) for n, c in maplib.common_mechanisms(g)] == [("symptom:fatigue", 2)]


def test_one_incoming_link_is_not_convergence(tmp_path, content):
    g = build(tmp_path, content, card_data("card-a", links=[lk("card-b")]), card_data("card-b"))
    assert maplib.common_mechanisms(g) == [] and maplib.candidate_roots(g) == []


def test_cards_without_a_layer_are_not_yet_placed(tmp_path, content):
    g = build(tmp_path, content, card_data("card-a"), card_data("card-b", layer="trigger"))
    assert [n.key for n in g.in_layer(maplib.UNPLACED, "card")] == ["card-a"]
    assert [n.key for n in g.in_layer("trigger", "card")] == ["card-b"]


# --- the report ---------------------------------------------------------------------


def test_report_prints_layers_links_and_both_lists(tmp_path, content, capsys):
    put(tmp_path / "cards", card_data("card-a", "Card A", "predisposition", [lk("card-c"), lk("symptom:fatigue")]))
    put(tmp_path / "cards", card_data("card-b", "Card B", "trigger", [lk("card-c", "associated")]))
    put(tmp_path / "cards", card_data("card-c", "Card C", "mechanism"))
    put(tmp_path / "cards", card_data("card-d", "Card D"))
    code = maplib.main(["report", "--cards", str(tmp_path / "cards"), "--content", str(content)])
    out = capsys.readouterr().out
    assert code == 0
    assert out.index("Predisposition (1)") < out.index("Trigger (1)") < out.index("Perpetuating mechanism (1)")
    assert out.index("Perpetuating mechanism (1)") < out.index("Not yet placed (1)")
    assert "  Card A (card-a)\n    -> Card C [proposed] (pmid:00000001)\n" in out
    assert "    -> Fictional fatigue [proposed] (pmid:00000001)" in out
    assert "    -> Card C [associated] (pmid:00000001)" in out
    assert "Symptoms (1)\n  Fictional fatigue (symptom:fatigue)" in out
    assert "Open questions (2)" in out
    assert "Candidate common mechanisms (1)\n  Card C (card-c): 2 incoming links from different cards" in out
    assert "Candidate roots (1)\n  Card A (card-a): 2 links out" in out


def test_report_with_no_convergence_prints_empty_lists(tmp_path, content, capsys):
    put(tmp_path / "cards", card_data("card-a"))
    assert maplib.main(["report", "--cards", str(tmp_path / "cards"), "--content", str(content)]) == 0
    out = capsys.readouterr().out
    assert "Not yet placed (1)" in out
    assert "Candidate common mechanisms (0)\n  none" in out and "Candidate roots (0)\n  none" in out


def test_report_exits_1_with_the_errors_when_an_input_is_invalid(tmp_path, content, capsys):
    put(tmp_path / "cards", card_data("card-a", links=[lk("no-such-card")]))
    assert maplib.main(["report", "--cards", str(tmp_path / "cards"), "--content", str(content)]) == 1
    captured = capsys.readouterr()
    assert "[M2]" in captured.err and captured.out == ""


def test_report_with_drafts_lets_a_draft_replace_the_card(tmp_path, content, capsys, monkeypatch):
    put(tmp_path / "cards", card_data("card-a", "Published A"))
    put(tmp_path / "drafts", card_data("card-a", "Draft A", "trigger"))
    monkeypatch.chdir(tmp_path)
    assert maplib.main(["report", "--drafts", "--cards", "cards", "--content", str(content)]) == 0
    out = capsys.readouterr().out
    assert "Draft A (card-a)" in out and "Published A" not in out
    assert maplib.main(["report", "--cards", "cards", "--content", str(content)]) == 0
    assert "Published A (card-a)" in capsys.readouterr().out


def test_report_prints_a_warning_for_todo_entries(tmp_path, capsys):
    folder = tmp_path / "content"
    dump(folder / "symptoms.yaml", [{"id": "pending", "name": "Fictional pending", "todo": "verify"}])
    put(tmp_path / "cards", card_data("card-a"))
    assert maplib.main(["report", "--cards", str(tmp_path / "cards"), "--content", str(folder)]) == 0
    captured = capsys.readouterr()
    assert "warning:" in captured.err and "Fictional pending" not in captured.out


# --- the agents (C7): the files describe the shapes the code knows ---------------

REPO = Path(__file__).resolve().parents[1]


def agent_text(name: str) -> str:
    return (REPO / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")


def json_blocks(markdown: str) -> list[dict]:
    import json
    import re

    return [json.loads(b.replace("<slug>", "example-card")) for b in re.findall(r"```json\n(.*?)```", markdown, re.S)]


def test_the_link_drafter_is_a_sonnet_agent_that_may_only_read_and_write():
    text = agent_text("link-drafter")
    meta = yaml.safe_load(text.split("---")[1])
    assert meta["name"] == "link-drafter" and meta["model"] == "sonnet"
    assert [t.strip() for t in meta["tools"].split(",")] == ["Read", "Write"]
    for needle in ("Never from memory", "Do not write to `cards/` or `drafts/`", "data/pipeline/", "1 Proposed"):
        assert needle in text
    assert "2 Associated" in text and "3 Direction supported" in text


def test_the_link_drafter_example_is_a_proposal_whose_links_the_card_model_accepts():
    (proposal,) = json_blocks(agent_text("link-drafter"))
    assert set(proposal) == {"slug", "layer", "links"} and proposal["layer"] in cardlib.LAYERS
    for item in proposal["links"]:
        assert set(item) == {"to", "support", "text", "sources", "why"}
        cardlib.Link.model_validate({k: v for k, v in item.items() if k != "why"})


def test_the_reviewer_map_mode_shows_the_verdict_and_findings_shape_of_translation_mode():
    from me_atlas import translations as tr

    section = agent_text("card-reviewer").split("## Map mode")[1].split("\n## ")[0]
    (review,) = json_blocks(section)
    assert set(review) == {"slug", "verdict", "findings"}
    assert review["findings"][0]["item"] == "links[0]"
    # the findings parse as translation findings (same keys), and the verdict rule is the same
    for finding in review["findings"]:
        tr.TranslationFinding.model_validate(finding)
    with pytest.raises(ValueError, match="must_fix"):
        tr.TranslationReview.model_validate({**review, "lang": "nb"})
    for needle in ("both ends measured in the same patients", "temporal order", "intervention", "mediation"):
        assert needle in section
