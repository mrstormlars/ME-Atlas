"""Tests for the static site generator. Cards are fictional; the build runs in tmp_path. No network, no LLM."""

from __future__ import annotations

import copy
import datetime as dt
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

from me_atlas import cards as cardlib
from me_atlas import i18n, site
from me_atlas.glossary import Glossary, GlossaryEntry

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CARD = Path(__file__).parent / "fixtures" / "cards" / "fictional-hypothesis.yaml"
FIXTURE_CHANGELOG = Path(__file__).parent / "fixtures" / "cards" / "changelog.yaml"
REAL_GLOSSARY = REPO_ROOT / "content" / "glossary.yaml"
I18N_DIR = REPO_ROOT / "content" / "i18n"
EN = i18n.load_strings(I18N_DIR / "en.yaml")
RUNG_NAMES = tuple(EN[f"rung.{i}.name"] for i in range(6))
RUNG_MEANINGS = tuple(EN[f"rung.{i}.meaning"] for i in range(6))
CSS = REPO_ROOT / "src" / "me_atlas" / "static" / "site.css"
TODAY = dt.date(2026, 11, 1)

# --- a very small HTML tree so tests assert on structure, not on strings -----

VOID = {"meta", "link", "br", "hr", "img", "input", "source", "area", "base", "col", "wbr"}


class Node:
    def __init__(self, tag: str, attrs: dict[str, str | None], parent: Node | None = None):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node | str] = []

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def get(self, name: str) -> str | None:
        return self.attrs.get(name)

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find_all(self, tag: str | None = None, cls: str | None = None) -> list[Node]:
        return [n for n in self.walk() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes)]

    def find(self, tag: str | None = None, cls: str | None = None, id: str | None = None) -> Node | None:
        for n in self.walk():
            if (
                (tag is None or n.tag == tag)
                and (cls is None or cls in n.classes)
                and (id is None or n.get("id") == id)
            ):
                return n
        return None

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def text(self, skip_classes: frozenset[str] = frozenset()) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif not (child.classes & skip_classes):
                parts.append(child.text(skip_classes))
        return "".join(parts)


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    return builder.root


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page(out: Path, name: str) -> Node:
    return parse((out / name).read_text(encoding="utf-8"))


def html_files(out: Path) -> list[Path]:
    """The English pages. The Norwegian tree (build/nb/) has its own tests."""
    return sorted(p for p in out.rglob("*.html") if p.relative_to(out).parts[0] != "nb")


# --- fictional input -----


def base() -> dict:
    return copy.deepcopy(yaml.safe_load(FIXTURE_CARD.read_text(encoding="utf-8")))


def make_card(slug: str, name: str, level: int = 2, *, contested_rungs: list[int] | None = None, **over) -> dict:
    """A valid fictional card at the given level. Contested only when rungs are given."""
    data = base()
    data["slug"], data["name"], data["level"] = slug, name, level
    data["contested"] = (
        {"rungs": contested_rungs, "reason": data["contested"]["reason"]} if contested_rungs is not None else None
    )
    data.update(over)
    return data


def drop_long_covid(data: dict) -> dict:
    """Remove the long COVID study (and the early signal citing it)."""
    data["studies"] = [s for s in data["studies"] if s["cohort"] != "long_covid"]
    data["early_signals"] = []
    return data


def add_study(data: dict, study_id: str, case_definition: str, **over) -> dict:
    study = {
        "id": study_id,
        "title": f"Fictional study {study_id} with case definition {case_definition}",
        "year": 2006,
        "cohort": "me_cfs",
        "case_definition": case_definition,
        "case_definition_source": None if case_definition == "unverified" else "abstract",
        "case_definition_quote": (
            f"Fictional participants met the {case_definition} criteria."
            if case_definition in cardlib.RECOGNISED_CASE_DEFINITIONS
            else None
        ),
        "design": "other",
        "n_patients": 10,
        "n_controls": None,
        "measures_pem": False,
        "preregistered": None,
        "role": "context",
        "direction": "not_applicable",
        "finding": "A fictional background study.",
    }
    study.update(over)
    data["studies"].append(study)
    return study


def write_yaml(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def write_card(directory: Path, data: dict) -> Path:
    return write_yaml(directory / f"{data['slug']}.yaml", data)


def make_glossary(tmp_path: Path, extra: list[dict] | None = None) -> Path:
    """The real glossary (the templates need its terms) plus fictional extras."""
    entries = yaml.safe_load(REAL_GLOSSARY.read_text(encoding="utf-8")) + (extra or [])
    return write_yaml(tmp_path / "glossary.yaml", entries)


class Site:
    """A fictional project layout in tmp_path and a way to build it."""

    def __init__(self, tmp_path: Path, extra_terms: list[dict] | None = None):
        self.root = tmp_path
        self.cards = tmp_path / "cards"
        self.drafts = tmp_path / "drafts"
        self.cards.mkdir()
        self.drafts.mkdir()
        self.glossary = make_glossary(tmp_path, extra_terms)
        # Never the repo's real content folder: only its fixed texts, no symptoms or open questions.
        self.content = tmp_path / "site-content"
        self.content.mkdir()
        for part in ("i18n", "methods"):
            shutil.copytree(REPO_ROOT / "content" / part, self.content / part)
        self.out = tmp_path / "build"

    def build(self, *, drafts: bool = False, **options) -> site.BuildResult:
        options.setdefault("content_dir", self.content)
        return site.build(
            self.cards, self.out, self.glossary, drafts_dir=self.drafts if drafts else None, today=TODAY, **options
        )

    def run(self, *, drafts: bool = False, extra: list[str] | None = None) -> int:
        args = [
            "build",
            "--cards-dir",
            str(self.cards),
            "--drafts-dir",
            str(self.drafts),
            "--glossary",
            str(self.glossary),
            "--out",
            str(self.out),
            "--content-dir",
            str(self.content),
        ]
        return site.main(args + (extra or []) + (["--drafts"] if drafts else []))


@pytest.fixture
def proj(tmp_path) -> Site:
    return Site(tmp_path)


def built(proj: Site, *cards: dict, drafts: bool = False) -> Path:
    for c in cards:
        write_card(proj.cards, c)
    result = proj.build(drafts=drafts)
    assert result.errors == []
    return proj.out


# --- front page: sorting -----


def row_order(out: Path) -> list[str]:
    return [n.get("id").removeprefix("row-") for n in page(out, "index.html").find_all("section", "row")]


def test_front_page_sorts_by_level_then_name_and_breaks_ties_alphabetically(proj):
    # File order (slug) is the opposite of name order for the two level-3 cards, so a sort on slug would fail.
    out = built(
        proj,
        make_card("aaa-first-file", "Zeta fictional idea", 3),
        make_card("zzz-last-file", "Alpha fictional idea", 3),
        make_card("mmm-highest", "Middle fictional idea", 4),
        make_card("bbb-lowest", "Aardvark fictional idea", 1),
    )
    assert row_order(out) == ["mmm-highest", "zzz-last-file", "aaa-first-file", "bbb-lowest"]


def test_tie_break_ignores_letter_case(proj):
    out = built(proj, make_card("one", "beta lower case", 2), make_card("two", "Alpha capital", 2))
    assert row_order(out) == ["two", "one"]


def test_summary_table_follows_the_same_order_and_gives_level_and_rung_name(proj):
    out = built(proj, make_card("low", "Fictional low", 1), make_card("high", "Fictional high", 3))
    rows = page(out, "index.html").find("table", "summary").find_all("tr")[1:]
    cells = [[norm(c.text()) for c in r.find_all() if c.tag in ("th", "td")] for r in rows]
    assert [c[0] for c in cells] == ["Fictional high", "Fictional low"]
    assert cells[0][1] == "3: Repeated by others"
    assert cells[1][1] == "1: First signs"


def test_each_name_on_the_front_page_links_to_its_card_page(proj):
    out = built(proj, make_card("fictional-one", "Fictional one", 2))
    hrefs = [a.get("href") for a in page(out, "index.html").find_all("a")]
    assert hrefs.count("hypotheses/fictional-one.html") == 2  # chart row and table
    assert (out / "hypotheses" / "fictional-one.html").is_file()


# --- contested -----


def test_contested_card_has_hatched_rungs_on_the_front_page_and_a_reason_on_its_page(proj):
    out = built(proj, make_card("contested-one", "Fictional contested", 3, contested_rungs=[3]))
    row = page(out, "index.html").find("section", id="row-contested-one")
    segments = row.find_all("i", "seg")
    assert [("contested" in s.classes, "on" in s.classes) for s in segments] == [
        (False, True),
        (False, True),
        (False, True),
        (True, False),
        (False, False),
        (False, False),
    ]
    assert "contested at rung 3" in norm(row.text())
    assert "Solid up to rung 2" in norm(row.text())
    card_page = page(out, "hypotheses/contested-one.html")
    assert norm(card_page.find("h2", id="contested").text()) == "Contested at rung 3"
    assert "A fictional larger controlled study did not find the same pattern." in norm(card_page.text())


def test_two_contested_rungs_are_both_hatched(proj):
    out = built(proj, make_card("two-rungs", "Fictional two rungs", 3, contested_rungs=[2, 3]))
    row = page(out, "index.html").find("section", id="row-two-rungs")
    assert len([s for s in row.find_all("i", "seg") if "contested" in s.classes]) == 2
    assert "rungs 2, 3" in norm(row.text())


def test_card_without_contested_has_no_hatching_and_no_reason(proj):
    out = built(proj, make_card("plain-one", "Fictional plain", 3))
    row = page(out, "index.html").find("section", id="row-plain-one")
    assert not [s for s in row.find_all("i", "seg") if "contested" in s.classes]
    assert "contested" not in norm(row.text()).lower()
    card_page = page(out, "hypotheses/plain-one.html")
    assert norm(card_page.find("h2", id="contested").text()) == "Not contested"
    assert "Contested at" not in norm(card_page.text())
    assert "A fictional larger controlled study did not find the same pattern." not in norm(card_page.text())
    assert not [s for s in card_page.find_all("i", "seg") if "contested" in s.classes]


# --- long COVID label -----


def test_long_covid_label_only_when_a_study_has_a_long_covid_cohort(proj):
    out = built(
        proj,
        make_card("with-lc", "Fictional with long covid", 2),
        drop_long_covid(make_card("without-lc", "Fictional without long covid", 2)),
    )
    front = page(out, "index.html")
    assert front.find("section", id="row-with-lc").find_all(cls="lc-label")
    assert not front.find("section", id="row-without-lc").find_all(cls="lc-label")
    assert norm(page(out, "hypotheses/with-lc.html").find(cls="lc-label").text()) == "Also studied in long COVID"
    assert page(out, "hypotheses/without-lc.html").find(cls="lc-label") is None


def test_table_says_yes_or_no_for_long_covid_and_badges(proj):
    out = built(proj, make_card("yes-one", "Fictional yes", 2), drop_long_covid(make_card("no-one", "Fictional no", 2)))
    rows = {norm(r.find("th").text()): r for r in page(out, "index.html").find("table", "summary").find_all("tr")[1:]}
    yes_cells = [norm(c.text()) for c in rows["Fictional yes"].find_all("td")]
    no_cells = [norm(c.text()) for c in rows["Fictional no"].find_all("td")]
    assert yes_cells[-1] == "Yes" and no_cells[-1] == "No"
    assert yes_cells[2:4] == ["Yes", "Yes"]  # the fixture card has both badges


def test_badge_marks_on_the_front_page_only_when_yes(proj):
    no_badges = make_card("no-badges", "Fictional no badges", 2)
    no_badges["badges"] = {
        "diagnostic_marker": {"value": False, "reason": None},
        "explains_pem": {"value": False, "reason": None},
    }
    out = built(proj, make_card("badges", "Fictional badges", 2), no_badges)
    front = page(out, "index.html")
    assert len(front.find("section", id="row-badges").find_all(cls="badge")) == 2
    assert not front.find("section", id="row-no-badges").find_all(cls="badge")
    card_page = page(out, "hypotheses/no-badges.html")
    text = norm(card_page.text())
    assert "Marker validated in an independent cohort: no" in text
    assert "Explains PEM: no" in text


# --- references -----


def test_every_reference_links_to_a_study_that_exists_on_the_page(proj):
    out = built(proj, make_card("refs", "Fictional refs", 4, contested_rungs=[4]))
    doc = page(out, "hypotheses/refs.html")
    study_ids = {a.get("id") for a in doc.find_all("article", "study")}
    refs = doc.find_all("a", "ref")
    assert refs
    for ref in refs:
        target = ref.get("href")
        assert target.startswith("#study-")
        assert target[1:] in study_ids
    cited = {r.get("href")[len("#study-") :] for r in refs}
    card = cardlib.load_card(proj.cards / "refs.yaml")
    for text in site.sourced_texts_in_page_order(card):
        assert set(text.sources) <= cited
    assert {s.id for s in card.studies} >= cited


def test_reference_numbers_follow_the_order_of_first_citation_and_are_stable(proj):
    out = built(proj, make_card("numbers", "Fictional numbers", 4, contested_rungs=[4]))
    doc = page(out, "hypotheses/numbers.html")
    shown = [norm(r.text()) for r in doc.find_all("a", "ref")]
    first_seen: list[int] = []
    for label in shown:
        n = int(label.strip("[]"))
        if n not in first_seen:
            first_seen.append(n)
    assert first_seen == list(range(1, len(first_seen) + 1))
    # The same study always gets the same number.
    by_target: dict[str, set[str]] = {}
    for r in doc.find_all("a", "ref"):
        by_target.setdefault(r.get("href"), set()).add(norm(r.text()))
    assert all(len(v) == 1 for v in by_target.values())
    # Each cited study says which number it carries.
    entry = doc.find("article", id="study-pmid:00000001")
    assert f"cited as {by_target['#study-pmid:00000001'].copy().pop()}" in norm(entry.text())


def test_references_are_numbered_per_page(proj):
    other = make_card("other", "Fictional other", 2)
    other["core_claim"]["sources"] = ["pmid:00000003", "pmid:00000001"]
    out = built(proj, make_card("first", "Fictional first", 2), other)
    first = page(out, "hypotheses/first.html").find("a", "ref")
    assert (first.get("href"), norm(first.text())) == ("#study-pmid:00000001", "[1]")
    refs = page(out, "hypotheses/other.html").find_all("a", "ref")[:2]
    # On this page study 3 is cited first, so it is [1] here although it is not [1] on the other page.
    assert [(r.get("href"), norm(r.text())) for r in refs] == [
        ("#study-pmid:00000003", "[1]"),
        ("#study-pmid:00000001", "[2]"),
    ]


def test_study_links_use_pubmed_for_pmid_and_doi_org_for_doi():
    assert site.study_url("pmid:00000001") == "https://pubmed.ncbi.nlm.nih.gov/00000001/"
    assert site.study_url("doi:10.0000/fictional.5") == "https://doi.org/10.0000/fictional.5"


def test_study_entries_link_out(proj):
    out = built(proj, make_card("links", "Fictional links", 2))
    doc = page(out, "hypotheses/links.html")
    hrefs = {a.get("id"): a.find("h4").find("a").get("href") for a in doc.find_all("article", "study")}
    assert hrefs["study-pmid:00000001"] == "https://pubmed.ncbi.nlm.nih.gov/00000001/"
    assert hrefs["study-doi:10.0000/fictional.5"] == "https://doi.org/10.0000/fictional.5"


# --- studies -----


def test_studies_are_grouped_by_role(proj):
    out = built(proj, make_card("groups", "Fictional groups", 2))
    doc = page(out, "hypotheses/groups.html")
    headings = [norm(h.text()) for h in doc.find_all("h3")]
    assert headings == ["Studies that support it", "Studies that contradict it", "Other studies"]

    def ids_after(heading: str) -> list[str]:
        out_ids: list[str] = []
        collecting = False
        for n in doc.find("main").walk():  # the studies of a group sit in a panel after its heading
            if n.tag == "h3":
                collecting = norm(n.text()) == heading
            elif n.tag == "h2":
                collecting = False
            elif collecting and n.tag == "article":
                out_ids.append(n.get("id"))
        return out_ids

    assert ids_after("Studies that support it") == ["study-pmid:00000001", "study-pmid:00000002"]
    assert ids_after("Studies that contradict it") == ["study-pmid:00000003"]
    assert ids_after("Other studies") == ["study-pmid:00000004", "study-doi:10.0000/fictional.5"]


def test_empty_study_group_says_so(proj):
    data = make_card("no-contradiction", "Fictional no contradiction", 2)
    data["studies"] = [s for s in data["studies"] if s["role"] != "contradicts"]
    out = built(proj, data)
    text = norm(page(out, "hypotheses/no-contradiction.html").text())
    assert "No study on this card is listed as contradicting it." in text
    assert "No study on this card is listed as supporting it." not in text


def facts(entry: Node) -> dict[str, str]:
    """The sample sizes in a study's metadata line (they were a definition list before the layout revision)."""
    return {
        "Patients": norm(entry.find(cls="n-patients").text()),
        "Controls": norm(entry.find(cls="n-controls").text()),
    }


def test_missing_sample_sizes_show_not_stated(proj):
    out = built(proj, make_card("sizes", "Fictional sizes", 2))
    doc = page(out, "hypotheses/sizes.html")
    uncontrolled = facts(doc.find("article", id="study-pmid:00000004"))
    assert (uncontrolled["Patients"], uncontrolled["Controls"]) == (
        "12 patients",
        "controls: none (uncontrolled study)",
    )
    background = facts(doc.find("article", id="study-doi:10.0000/fictional.5"))
    assert (background["Patients"], background["Controls"]) == ("patients: not stated", "controls: not stated")
    controlled = facts(doc.find("article", id="study-pmid:00000001"))
    assert (controlled["Patients"], controlled["Controls"]) == ("40 patients", "40 controls")


def test_controls_row_depends_on_design_and_whether_the_number_is_given(proj):
    data = make_card("controls", "Fictional controls", 2)
    add_study(data, "pmid:00000301", "Fukuda", design="uncontrolled", n_patients=5, n_controls=None)
    add_study(data, "pmid:00000302", "Fukuda", design="uncontrolled", n_patients=5, n_controls=3)
    add_study(data, "pmid:00000303", "Fukuda", design="controlled", n_patients=5, n_controls=None)
    add_study(data, "pmid:00000304", "Fukuda", design="intervention_controlled", n_patients=5, n_controls=None)
    doc = page(built(proj, data), "hypotheses/controls.html")

    def controls(study_id: str) -> str:
        return facts(doc.find("article", id=f"study-{study_id}"))["Controls"]

    assert controls("pmid:00000301") == "controls: none (uncontrolled study)"
    assert controls("pmid:00000302") == "3 controls"  # a stated number always wins
    assert (
        controls("pmid:00000303") == "controls: not stated"
    )  # a controlled study without a number is unknown, not zero
    assert controls("pmid:00000304") == "controls: not stated"
    assert controls("doi:10.0000/fictional.5") == "controls: not stated"  # design "other"


def test_study_shows_year_design_and_direction(proj):
    out = built(proj, make_card("facts", "Fictional facts", 2))
    entry = page(out, "hypotheses/facts.html").find("article", id="study-pmid:00000001")
    text = norm(entry.text())
    assert "2001" in text and "Controlled" in text and "Lower in patients" in text
    assert "A study of n=40 patients and 40 controls found a fictional difference" in text


@pytest.mark.parametrize(
    ("case_definition", "label", "flag"),
    [
        ("Fukuda", "Fukuda criteria", "does not require PEM"),
        ("Holmes1988", "Holmes 1988 criteria", "does not require PEM"),
        ("CDC_unspecified", "CDC criteria (version not stated)", "does not require PEM"),
        ("Oxford", "Oxford criteria", "broad"),
        ("unverified", "case definition not yet checked", None),
        ("none", "no case definition stated", None),
        ("other", "other definition", None),
        ("CCC", "Canadian Consensus Criteria (CCC)", None),
        ("ICC", "International Consensus Criteria (ICC)", None),
        ("IOM2015", "IOM 2015 criteria", None),
    ],
)
def test_case_definition_label_and_flag(proj, case_definition, label, flag):
    data = make_card("casedef", "Fictional case definitions", 2)
    add_study(data, "pmid:00000100", case_definition)
    out = built(proj, data)
    entry = page(out, "hypotheses/casedef.html").find("article", id="study-pmid:00000100")
    assert norm(entry.find(cls="casedef").text()) == label
    flags = entry.find_all(cls="flag")
    if flag is None:
        assert flags == []  # no flag: a CCC study is not "broad" and an unchecked one is not "no PEM"
    else:
        assert [norm(f.text()) for f in flags] == [flag]


def test_every_case_definition_label_is_covered():
    assert set(site.CASE_DEFINITION_META) == set(cardlib.CASE_DEFINITION_RANK)


def test_last_checked_names_who_checked(proj):
    founder = make_card("founder", "Fictional founder", 2)
    founder["last_checked"] = {"date": dt.date(2026, 10, 2), "by": "founder"}
    out = built(proj, make_card("audit", "Fictional audit", 2), founder)
    assert "Last checked 2026-10-01 by the AI auditor." in norm(page(out, "hypotheses/audit.html").text())
    assert "Last checked 2026-10-02 by the founder." in norm(page(out, "hypotheses/founder.html").text())


def test_working_on_it_links_out_and_empty_says_none(proj):
    nobody = make_card("nobody", "Fictional nobody", 2, working_on_it=[], subgroups=[])
    out = built(proj, make_card("somebody", "Fictional somebody", 2), nobody)
    links = [
        a
        for a in page(out, "hypotheses/somebody.html").find_all("a")
        if (a.get("href") or "").startswith("https://example.org")
    ]
    assert [norm(a.text()) for a in links] == ["Fictional Research Group"]
    text = norm(page(out, "hypotheses/nobody.html").text())
    assert "Who is working on it None listed." in text
    assert "Subgroups it may apply to None listed." in text


def test_badge_without_a_reason_says_the_reason_is_not_yet_written(proj):
    bare = make_card("bare", "Fictional bare", 2)
    bare["badges"] = {
        "diagnostic_marker": {"value": False, "reason": None},
        "explains_pem": {"value": False, "reason": None},
    }
    half = make_card("half", "Fictional half", 2)
    half["badges"]["explains_pem"] = {"value": False, "reason": None}
    out = built(proj, bare, half, make_card("reasoned", "Fictional reasoned", 2))
    assert norm(page(out, "hypotheses/bare.html").text()).count("Reason not yet written.") == 2
    assert norm(page(out, "hypotheses/half.html").text()).count("Reason not yet written.") == 1
    assert "Reason not yet written." not in norm(page(out, "hypotheses/reasoned.html").text())


def test_other_studies_carry_a_fixed_context_line_only_when_there_are_other_studies(proj):
    note = "Shown for context. These studies do not count for or against the level"
    only_supporting = make_card("only-supporting", "Fictional only supporting", 2)
    only_supporting["studies"] = [s for s in only_supporting["studies"] if s["role"] in ("supports", "contradicts")]
    only_supporting["early_signals"] = []
    only_supporting["subgroups"] = []
    out = built(proj, make_card("with-others", "Fictional with others", 2), only_supporting)
    assert note in norm(page(out, "hypotheses/with-others.html").text())
    empty_text = norm(page(out, "hypotheses/only-supporting.html").text())
    assert note not in empty_text and "No other studies are listed." in empty_text


# --- early signals -----

EARLY = "Early signals: not yet repeated"


def test_early_signals_heading_present_when_there_are_early_signals(proj):
    out = built(proj, make_card("signals", "Fictional signals", 2))
    doc = page(out, "hypotheses/signals.html")
    assert [norm(h.text()) for h in doc.find_all("h2") if norm(h.text()) == EARLY] == [EARLY]
    assert "A fictional small uncontrolled study reported a related fictional change, not yet replicated." in norm(
        doc.text()
    )


def test_early_signals_section_absent_when_empty(proj):
    out = built(proj, make_card("quiet", "Fictional quiet", 2, early_signals=[]))
    assert EARLY not in norm(page(out, "hypotheses/quiet.html").text())
    assert EARLY not in norm(page(out, "index.html").text())


def test_early_signals_never_appear_on_the_front_page(proj):
    out = built(proj, make_card("signals", "Fictional signals", 2))
    assert EARLY not in norm(page(out, "index.html").text())
    assert "A fictional small uncontrolled study reported" not in norm(page(out, "index.html").text())


# --- banned words -----


def visible_text_without_titles(doc: Node) -> str:
    return doc.find("body").text(frozenset({"study-title", "sr"}))


def banned_outside_titles(html: str) -> list[str]:
    return [m.group(0) for m in cardlib._BANNED_RE.finditer(visible_text_without_titles(parse(html)))]


def test_no_banned_word_on_any_page_outside_study_titles(proj):
    titled = make_card("titled", "Fictional titled", 2)
    titled["studies"][0]["title"] = "Fictional study of a cure for widget signalling"
    out = built(proj, make_card("plain", "Fictional plain", 4, contested_rungs=[4]), titled)
    write_yaml(proj.cards / "changelog.yaml", yaml.safe_load(FIXTURE_CHANGELOG.read_text(encoding="utf-8")))
    proj.build()
    pages = html_files(out)
    assert len(pages) >= 6
    for path in pages:
        assert banned_outside_titles(path.read_text(encoding="utf-8")) == [], path.name
    # The word is really on the page, inside the quoted title, so the check above is not vacuous.
    assert "cure" in (out / "hypotheses" / "titled.html").read_text(encoding="utf-8")


def test_banned_word_check_catches_a_word_outside_a_title():
    html = (
        '<html><body><main><p>This is a promising result.</p><h4 class="study-title">A cure</h4></main></body></html>'
    )
    assert banned_outside_titles(html) == ["promising"]


def test_banned_word_in_a_finding_is_visible_to_the_check(proj):
    # The card validator (V10) only scans the core claim and early signals; the page check covers findings too.
    data = make_card("finding", "Fictional finding", 2)
    data["studies"][0]["finding"] = "A study of n=40 patients found a hopeful fictional difference."
    out = built(proj, data)
    assert banned_outside_titles((out / "hypotheses" / "finding.html").read_text(encoding="utf-8")) == ["hopeful"]


# --- empty, invalid, drafts -----


def test_empty_cards_build_a_front_page_that_says_nothing_is_published(proj, capsys):
    assert proj.run() == 0
    front = page(proj.out, "index.html")
    assert "no hypotheses published yet" in norm(front.text()).lower()
    assert front.find("section", "row") is None
    assert front.find("table", "summary") is None
    assert (proj.out / "methods.html").is_file() and (proj.out / "changes.html").is_file()
    assert not (proj.out / "hypotheses").exists()
    assert "No changes have been published yet." in norm(page(proj.out, "changes.html").text())
    assert "OK:" in capsys.readouterr().out


def test_invalid_card_exits_non_zero_and_writes_no_pages(proj, capsys):
    good = make_card("good", "Fictional good", 2)
    bad = make_card("bad", "Fictional bad", 2)
    bad["core_claim"]["sources"] = ["pmid:99999999"]  # not in the card's studies (V3)
    write_card(proj.cards, good)
    write_card(proj.cards, bad)
    assert proj.run() == 1
    assert not proj.out.exists()
    err = capsys.readouterr().err
    assert "V3" in err and "bad.yaml" in err and "nothing was built" in err


def test_invalid_card_leaves_a_previous_build_untouched(proj):
    write_card(proj.cards, make_card("good", "Fictional good", 2))
    assert proj.run() == 0
    before = (proj.out / "index.html").read_text(encoding="utf-8")
    bad = make_card("bad", "Fictional bad", 2)
    bad["level"] = 9
    write_card(proj.cards, bad)
    assert proj.run() == 1
    assert (proj.out / "index.html").read_text(encoding="utf-8") == before


def test_invalid_changelog_stops_the_build(proj):
    write_card(proj.cards, make_card("good", "Fictional good", 2))
    entry = yaml.safe_load(FIXTURE_CHANGELOG.read_text(encoding="utf-8"))[0]
    write_yaml(proj.cards / "changelog.yaml", [{**entry, "card": "no-such-card"}])
    assert proj.run() == 1
    assert not proj.out.exists()


def test_invalid_glossary_stops_the_build(proj, capsys):
    write_card(proj.cards, make_card("good", "Fictional good", 2))
    write_yaml(proj.glossary, [{"term": "widget", "explanation": "x" * 300}])
    assert proj.run() == 1
    assert not proj.out.exists()
    assert "300 characters" in capsys.readouterr().err


def test_missing_cards_directory_stops_the_build(proj):
    proj.cards.rmdir()
    assert proj.run() == 1
    assert not proj.out.exists()


def test_a_term_used_by_a_template_but_missing_from_the_glossary_stops_the_build(proj, capsys):
    write_card(proj.cards, make_card("good", "Fictional good", 2))
    write_yaml(proj.glossary, [{"term": "widget", "explanation": "A fictional thing."}])
    assert proj.run() == 1
    assert not proj.out.exists()
    assert "not in the glossary" in capsys.readouterr().err


def test_without_drafts_no_draft_appears_and_no_banner(proj):
    write_card(proj.cards, make_card("published", "Fictional published", 2))
    write_card(proj.drafts, make_card("only-draft", "Fictional only draft", 2))
    assert proj.build().errors == []
    assert not (proj.out / "hypotheses" / "only-draft.html").exists()
    for path in html_files(proj.out):
        html = path.read_text(encoding="utf-8")
        assert "Fictional only draft" not in html
        assert "Draft preview" not in html
        assert "noindex" not in html


def test_without_drafts_an_invalid_draft_is_not_read(proj):
    write_card(proj.cards, make_card("published", "Fictional published", 2))
    bad = make_card("only-draft", "Fictional only draft", 2)
    bad["level"] = 9
    write_card(proj.drafts, bad)
    assert proj.run() == 0
    assert proj.run(drafts=True) == 1


def test_with_drafts_the_draft_appears_and_every_page_has_banner_and_noindex(proj):
    write_card(proj.cards, make_card("published", "Fictional published", 2))
    write_card(proj.drafts, make_card("only-draft", "Fictional only draft", 3))
    assert proj.build(drafts=True).errors == []
    assert (proj.out / "hypotheses" / "only-draft.html").is_file()
    assert "Fictional only draft" in (proj.out / "index.html").read_text(encoding="utf-8")
    pages = html_files(proj.out)
    assert {p.name for p in pages} >= {"index.html", "methods.html", "glossary.html", "changes.html", "only-draft.html"}
    for path in pages:
        doc = page(proj.out, path.relative_to(proj.out).as_posix())
        banner = doc.find("div", "banner")
        assert banner is not None and norm(banner.text()) == "Draft preview — not published", path.name
        robots = [m for m in doc.find_all("meta") if m.get("name") == "robots"]
        assert [m.get("content") for m in robots] == ["noindex"], path.name


def test_a_draft_replaces_the_card_with_the_same_slug(proj):
    write_card(proj.cards, make_card("same", "Fictional approved name", 2))
    write_card(proj.drafts, make_card("same", "Fictional draft name", 3))
    proj.build(drafts=True)
    assert row_order(proj.out) == ["same"]
    assert "Fictional draft name" in (proj.out / "index.html").read_text(encoding="utf-8")
    assert "Fictional approved name" not in (proj.out / "index.html").read_text(encoding="utf-8")
    proj.build(drafts=False)
    assert "Fictional approved name" in (proj.out / "index.html").read_text(encoding="utf-8")


def test_drafts_directory_missing_with_drafts_flag_is_an_error(proj):
    proj.drafts.rmdir()
    assert proj.run(drafts=True) == 1
    assert proj.run() == 0


# --- what changed -----


def changelog_entries() -> list[dict]:
    return yaml.safe_load(FIXTURE_CHANGELOG.read_text(encoding="utf-8"))


def test_changes_page_lists_entries_newest_first_with_card_link_reason_sources_and_tier(proj):
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional hypothesis", 4))
    write_yaml(proj.cards / "changelog.yaml", changelog_entries())
    assert proj.build().errors == []
    doc = page(proj.out, "changes.html")
    entries = doc.find_all("article", "change")
    assert [norm(e.find("time").text()) for e in entries] == ["2026-10-08", "2026-10-01"]
    first = norm(entries[0].text())
    assert "Marked rung 4 as contested." in first
    assert "A fictional larger study found no difference." in first
    assert "pmid:00000003" in first and "Tier 2" in first
    assert entries[0].find("h2").find("a").get("href") == "hypotheses/fictional-hypothesis.html"
    assert "Fictional hypothesis" in first


def test_changes_page_uses_the_published_card_name_when_a_draft_replaces_the_slug(proj):
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional published name", 4))
    write_card(proj.drafts, make_card("fictional-hypothesis", "Fictional draft name", 4))
    write_yaml(proj.cards / "changelog.yaml", changelog_entries())
    assert proj.build(drafts=True).errors == []
    changes = norm(page(proj.out, "changes.html").text())
    assert "Fictional published name" in changes
    assert "Fictional draft name" not in changes
    assert "Fictional draft name" in (proj.out / "index.html").read_text(encoding="utf-8")  # the card page does


def test_changes_page_never_contains_draft_entries(proj):
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional hypothesis", 4))
    write_card(proj.drafts, make_card("fictional-hypothesis", "Fictional draft hypothesis", 4))
    write_card(proj.drafts, make_card("new-draft", "Fictional new draft", 2))
    write_yaml(proj.cards / "changelog.yaml", changelog_entries())
    draft_entry = {**changelog_entries()[0], "change": "FICTIONAL DRAFT-ONLY CHANGE", "card": "new-draft"}
    write_yaml(proj.drafts / "changelog.yaml", [draft_entry])
    for drafts in (False, True):
        assert proj.build(drafts=drafts).errors == []
        text = norm(page(proj.out, "changes.html").text())
        assert "DRAFT-ONLY" not in text
        assert "Fictional new draft" not in text
        assert len(page(proj.out, "changes.html").find_all("article", "change")) == 2


# --- glossary marking -----


def make_marker(*entries: tuple[str, list[str]]) -> site.Marker:
    return site.Marker(
        Glossary(
            tuple(GlossaryEntry(term=t, aliases=a, explanation=f"Fictional explanation of {t}.") for t, a in entries)
        )
    )


def marked_words(html) -> list[str]:
    return [norm(b.text()) for b in parse(str(html)).find_all("button", "term")]


def new_page(marker: site.Marker) -> site.Page:
    return site.Page(marker, "index.html", "Test")


def test_marking_marks_only_the_first_occurrence_on_the_page():
    pg = new_page(make_marker(("widget", [])))
    first = pg.mark("A widget and another widget.")
    second = pg.mark("Yet another widget.")
    assert marked_words(first) == ["widget"]
    assert str(first).endswith(" and another widget.")  # the second occurrence in the same text stays plain
    assert marked_words(second) == []
    assert "Yet another widget." in str(second)
    assert [e.term for e in pg.used] == ["widget"]


def test_marking_is_whole_word_only():
    pg = new_page(make_marker(("cell", [])))
    assert marked_words(pg.mark("cellular cells subcell cell-like")) == ["cell"]
    pg = new_page(make_marker(("cell", [])))
    assert marked_words(pg.mark("cellular cells subcell")) == []


def test_marking_is_case_sensitive():
    pg = new_page(make_marker(("widget", [])))
    assert marked_words(pg.mark("Widget WIDGET")) == []
    assert marked_words(pg.mark("a widget")) == ["widget"]


def test_alias_marks_the_same_entry_and_counts_as_the_same_term():
    pg = new_page(make_marker(("widget", ["gizmo"])))
    assert marked_words(pg.mark("A gizmo, then a widget.")) == ["gizmo"]
    assert [e.term for e in pg.used] == ["widget"]


def test_longest_match_wins_when_terms_overlap():
    marker = make_marker(("widget signalling", []), ("widget signalling pathway", []))
    pg = new_page(marker)
    assert marked_words(pg.mark("The widget signalling pathway.")) == ["widget signalling pathway"]
    assert [e.term for e in pg.used] == ["widget signalling pathway"]


def test_longest_match_wins_over_an_earlier_shorter_partial_overlap():
    marker = make_marker(("alpha beta", []), ("beta gamma delta", []))
    pg = new_page(marker)
    assert marked_words(pg.mark("alpha beta gamma delta")) == ["beta gamma delta"]


def test_marking_escapes_the_text_after_the_last_marked_term():
    pg = new_page(make_marker(("widget", [])))
    out = str(pg.mark("a widget <script>alert(1)</script> & more"))
    assert "<script>" not in out and "</script>" not in out
    assert out.endswith("&lt;script&gt;alert(1)&lt;/script&gt; &amp; more")
    # Text with no term at all is only a tail.
    assert str(new_page(make_marker(("widget", []))).mark("<i>x</i>")) == "&lt;i&gt;x&lt;/i&gt;"


def test_marking_escapes_text():
    pg = new_page(make_marker(("widget", [])))
    out = str(pg.mark("1 < 2 & a <b>widget</b>"))
    assert "&lt;b&gt;" in out and "<b>" not in out and "&amp;" in out


def test_explicit_template_marking_shares_the_first_occurrence_rule():
    pg = new_page(make_marker(("widget", [])))
    assert marked_words(pg.term("widget")) == ["widget"]
    assert marked_words(pg.term("widget")) == []
    assert marked_words(pg.mark("a widget")) == []


def test_explicit_marking_of_an_unknown_term_is_an_error():
    pg = new_page(make_marker(("widget", [])))
    with pytest.raises(site.SiteError):
        pg.term("gadget")


GLOSS_FIXTURE = [
    {"term": "widget signalling", "aliases": ["signalling"], "explanation": "FICTIONAL: how widgets pass messages."},
    {"term": "unused fictional term", "explanation": "FICTIONAL: appears on no page."},
    {"term": "Fictional background paper", "explanation": "FICTIONAL: a term that also sits inside a title."},
]


def glossed(tmp_path) -> Site:
    return Site(tmp_path, GLOSS_FIXTURE)


def test_marking_on_a_built_card_page_skips_study_titles_headings_and_links(tmp_path):
    proj = glossed(tmp_path)
    data = make_card("marked", "Fictional marked widget signalling", 2)
    data["studies"][0]["title"] = "Fictional study of widget signalling in a controlled cohort"
    out = built(proj, data)
    doc = page(out, "hypotheses/marked.html")
    buttons = [b for b in doc.find_all("button", "term") if b.get("id") == "use-widget-signalling"]
    assert len(buttons) == 1  # first occurrence only, although the term is in the claim, a title and a finding
    for b in doc.find_all("button", "term"):
        assert not any(a.tag in ("a", "h1", "h2", "h3", "h4") for a in b.ancestors()), b.text()
    for title in doc.find_all("h4", "study-title"):
        assert title.find("button") is None
    assert "widget signalling" in norm(doc.find("h4", "study-title").text())


def test_a_term_found_only_in_a_title_is_not_marked(tmp_path):
    proj = glossed(tmp_path)
    out = built(proj, make_card("titles", "Fictional titles", 2))
    doc = page(out, "hypotheses/titles.html")
    assert "Fictional background paper" in norm(doc.text())  # the title of doi:10.0000/fictional.5
    assert not [b for b in doc.find_all("button", "term") if b.get("id") == "use-fictional-background-paper"]


def test_every_marked_term_is_a_focusable_control_described_by_its_explanation(tmp_path):
    proj = glossed(tmp_path)
    out = built(proj, make_card("described", "Fictional described", 4, contested_rungs=[4]))
    entries = {e["term"]: e["explanation"] for e in yaml.safe_load(proj.glossary.read_text(encoding="utf-8"))}
    checked = 0
    for path in html_files(out):
        doc = parse(path.read_text(encoding="utf-8"))
        ids = {n.get("id"): n for n in doc.walk() if n.get("id")}
        for btn in doc.find_all(cls="term"):
            assert btn.tag == "button" and btn.get("type") == "button"  # focusable without tabindex tricks
            assert btn.get("tabindex") != "-1"
            tip = ids[btn.get("aria-describedby")]
            assert tip.get("role") == "tooltip"
            assert norm(tip.text()) in entries.values()
            checked += 1
    assert checked > 5


def test_each_marked_term_has_exactly_one_explanation_element_per_page(tmp_path):
    proj = glossed(tmp_path)
    out = built(proj, make_card("single", "Fictional single", 2))
    for path in html_files(out):
        doc = parse(path.read_text(encoding="utf-8"))
        buttons = doc.find_all("button", "term")
        tips = doc.find_all("div", "tip")
        assert len(tips) == len(buttons) == len({b.get("aria-describedby") for b in buttons})
        assert len({n.get("id") for n in doc.walk() if n.get("id")}) == len([n for n in doc.walk() if n.get("id")])


def test_glossary_page_lists_only_used_terms_alphabetically_with_back_links(tmp_path):
    proj = glossed(tmp_path)
    out = built(proj, make_card("used", "Fictional used", 2))
    doc = page(out, "glossary.html")
    entries = doc.find_all("div", "entry")
    terms = [norm(e.find("dt").text()) for e in entries]
    assert "widget signalling" in terms
    assert "unused fictional term" not in terms
    assert terms == sorted(terms, key=str.casefold)
    widget = next(e for e in entries if norm(e.find("dt").text()) == "widget signalling")
    assert "FICTIONAL: how widgets pass messages." in norm(widget.text())
    links = [a.get("href") for a in widget.find_all("a")]
    assert links == ["hypotheses/used.html#use-widget-signalling"]
    target = page(out, "hypotheses/used.html")
    assert target.find("button", id="use-widget-signalling") is not None


def test_glossary_page_back_links_name_every_page_that_uses_the_term(tmp_path):
    proj = glossed(tmp_path)
    out = built(proj, make_card("one", "Fictional one", 2), make_card("two", "Fictional two", 2))
    doc = page(out, "glossary.html")
    widget = next(e for e in doc.find_all("div", "entry") if norm(e.find("dt").text()) == "widget signalling")
    assert sorted(a.get("href") for a in widget.find_all("a")) == [
        "hypotheses/one.html#use-widget-signalling",
        "hypotheses/two.html#use-widget-signalling",
    ]
    # Every glossary term shown has at least one working back-link target.
    for entry in doc.find_all("div", "entry"):
        for a in entry.find_all("a"):
            path, _, fragment = a.get("href").partition("#")
            target = page(out, path)
            assert target.find(id=fragment) is not None, a.get("href")


def test_glossary_explanations_match_the_in_page_text(tmp_path):
    proj = glossed(tmp_path)
    out = built(proj, make_card("same", "Fictional same", 2))
    entries = {e["term"]: e["explanation"] for e in yaml.safe_load(proj.glossary.read_text(encoding="utf-8"))}
    in_page = {
        norm(t.text())
        for name in ("hypotheses/same.html", "index.html", "methods.html")
        for t in page(out, name).find_all("div", "tip")
    }
    on_glossary_page = {
        norm(e.find("dd").find("p").text()) for e in page(out, "glossary.html").find_all("div", "entry")
    }
    assert in_page <= on_glossary_page
    assert on_glossary_page <= set(entries.values())


def test_unused_term_is_reported_as_a_warning(tmp_path, capsys):
    proj = glossed(tmp_path)
    write_card(proj.cards, make_card("warn", "Fictional warn", 2))
    result = proj.build()
    assert "unused fictional term" in result.unused_terms
    assert "widget signalling" not in result.unused_terms
    assert "glossary term 'unused fictional term' is not used on any page" in result.warnings
    assert proj.run() == 0  # a warning does not fail the build
    assert "warning: glossary term 'unused fictional term' is not used on any page" in capsys.readouterr().err


def test_a_used_term_is_not_reported_as_unused(tmp_path):
    proj = glossed(tmp_path)
    write_card(proj.cards, make_card("fine", "Fictional fine", 2))
    result = proj.build()
    assert "widget signalling" not in [w.split("'")[1] for w in result.warnings]


def test_a_card_with_every_case_definition_builds_with_the_real_glossary(tmp_path):
    """Every term the templates mark must exist in the real glossary (a missing one stops the build)."""
    proj = Site(tmp_path)
    data = make_card("everything", "Fictional everything", 4, contested_rungs=[4])
    for i, cd in enumerate(sorted(cardlib.CASE_DEFINITION_RANK)):
        add_study(data, f"pmid:0000020{i}", cd)
    out = built(proj, data)
    assert (out / "methods.html").is_file()


# --- the methods page -----


def test_methods_page_states_plainly_that_no_expert_has_reviewed_the_content(proj):
    out = built(proj)
    text = norm(page(out, "methods.html").text())
    assert "No medical or research expert has reviewed this content." in text
    assert "no medical or research expert has reviewed the content" in text
    assert "including every evidence level, is drafted, checked and decided by AI tools" in text
    assert "Draft — pending expert review" in text


def test_methods_page_follows_the_spec_tables(proj):
    out = built(proj)
    doc = page(out, "methods.html")
    ladder = doc.find_all("table", "plain")[0]
    names = [norm(r.find("th").text()) for r in ladder.find_all("tr")[1:]]
    assert names == list(RUNG_NAMES)
    text = norm(doc.text())
    assert 'flagged on the card as "does not require PEM"' in text
    assert "No person decides the content of a card." in text
    assert "cannot raise a hypothesis above level 1" in text
    assert "Applied when the mechanical checks pass and the drafting and review agents agree" in text
    assert "The AI auditor, accept or reject, after the checks and the review" in text
    assert "any change that adds or cites a preprint" in text
    assert "Consistency check." in text and "one in five of the other audited changes" in text
    assert "It writes no card text." in text and "a quote that code checks against the cached record" in text
    assert "it does not share a blind spot" not in text  # the page says the opposite, plainly
    assert "may share the blind spots of the agents whose work it audits" in text


def test_methods_page_ladder_and_case_definition_rows_match_the_spec(proj):
    doc = page(built(proj), "methods.html")
    ladder, cases = doc.find_all("table", "plain")[0], doc.find_all("table", "plain")[2]
    meanings = [norm(r.find_all("td")[-1].text()) for r in ladder.find_all("tr")[1:]]
    assert tuple(meanings) == RUNG_MEANINGS
    spec_text = SPEC.read_text(encoding="utf-8")
    spec_row = re.search(r"(?m)^\| (CDC criteria, version not stated) \| ([^|]+?) \|$", spec_text)
    assert spec_row is not None
    rows = {norm(r.find("th").text()): norm(r.find("td").text()) for r in cases.find_all("tr")[1:]}
    assert rows["CDC criteria, version not stated"] == spec_row.group(2)


# --- every page -----


def test_every_page_has_navigation_footer_statement_and_build_date(proj):
    out = built(proj, make_card("nav", "Fictional nav", 2))
    for path in html_files(out):
        rel = path.relative_to(out).as_posix()
        doc = page(out, rel)
        nav = doc.find("nav")
        labels = [norm(a.text()) for a in nav.find_all("a")]
        assert labels == ["Front page", "What changed", "Causal map", "What is missing", "Methods", "Glossary"], rel
        footer = norm(doc.find("footer").text())
        assert "No medical or research expert has reviewed it." in footer, rel
        assert "Built 2026-11-01" in footer, rel
        assert doc.find("html").get("lang") == "en"
        assert doc.find("main") is not None and doc.find("h1") is not None


def test_only_the_current_page_is_marked_in_the_navigation(proj):
    out = built(proj)
    current = [a for a in page(out, "methods.html").find("nav").find_all("a") if a.get("aria-current")]
    assert [norm(a.text()) for a in current] == ["Methods"]


def test_internal_links_and_anchors_all_resolve(proj):
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional hypothesis", 4, contested_rungs=[4]))
    write_yaml(proj.cards / "changelog.yaml", changelog_entries())
    assert proj.build().errors == []
    checked = 0
    for path in html_files(proj.out):
        doc = parse(path.read_text(encoding="utf-8"))
        for el in doc.find_all():
            for attr in ("href", "src"):
                value = el.get(attr)
                if not value or re.match(r"^[a-z]+:", value):
                    continue
                target, _, fragment = value.partition("#")
                target_path = path if target == "" else (path.parent / target).resolve()
                assert target_path.is_file(), (path.name, value)
                if fragment:
                    other = doc if target == "" else parse(target_path.read_text(encoding="utf-8"))
                    assert other.find(id=fragment) is not None, (path.name, value)
                checked += 1
    assert checked > 30


# --- no external resources -----


def external_resource_refs(html: str) -> list[str]:
    """URLs of things a page would load: anything but an anchor that points to another host."""
    found = []
    for el in parse(html).find_all():
        for attr in ("src", "srcset", "data", "poster", "action", "formaction"):
            if el.get(attr):
                found.append(el.get(attr))
        if el.tag in ("link", "image", "use") and el.get("href"):
            found.append(el.get("href"))
        if el.tag == "meta" and "url=" in (el.get("content") or "").lower():
            found.append(el.get("content"))
    return [u for u in found if re.match(r"^(https?:)?//", u.strip(), re.IGNORECASE)]


def external_hrefs(html: str) -> list[str]:
    return [a.get("href") for a in parse(html).find_all("a") if re.match(r"^(https?:)?//", a.get("href") or "")]


def test_resource_check_flags_external_scripts_styles_images_and_frames():
    bad = (
        '<html><head><link rel="stylesheet" href="https://cdn.example/x.css">'
        '<script src="//cdn.example/x.js"></script></head>'
        '<body><img src="http://example.org/a.png"><iframe src="https://example.org/"></iframe></body></html>'
    )
    assert external_resource_refs(bad) == [
        "https://cdn.example/x.css",
        "//cdn.example/x.js",
        "http://example.org/a.png",
        "https://example.org/",
    ]
    assert external_resource_refs('<a href="https://example.org/">x</a><link href="static/site.css">') == []


def test_no_page_loads_anything_from_another_host(proj):
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional hypothesis", 4, contested_rungs=[4]))
    write_yaml(proj.cards / "changelog.yaml", changelog_entries())
    assert proj.build().errors == []
    card = cardlib.load_card(proj.cards / "fictional-hypothesis.yaml")
    allowed = {site.study_url(s.id) for s in card.studies} | {w.url for w in card.working_on_it}
    allowed |= {site.study_url(s) for e in changelog_entries() for s in e["sources"]}
    allowed |= {site.REPO_URL, site.REPO_ISSUES_URL}  # the footer's error-report line
    seen: set[str] = set()
    for path in html_files(proj.out):
        html = path.read_text(encoding="utf-8")
        assert external_resource_refs(html) == [], path.name
        for href in external_hrefs(html):
            assert href in allowed, (path.name, href)
            seen.add(href)
    assert seen  # study links and the working-on-it link really are there
    css = CSS.read_text(encoding="utf-8")
    assert not re.search(r"@import|url\(\s*['\"]?(https?:)?//", css)
    js = (proj.out / "static" / "site.js").read_text(encoding="utf-8")
    assert not re.search(r"https?://|fetch\(|XMLHttpRequest|import\(", js)


def test_external_study_links_do_not_leak_a_referrer_opener(proj):
    out = built(proj, make_card("rel", "Fictional rel", 2))
    for path in html_files(out):
        for a in parse(path.read_text(encoding="utf-8")).find_all("a"):
            if (a.get("href") or "").startswith("http"):
                assert "noopener" in (a.get("rel") or ""), (path.name, a.get("href"))


# --- output directory -----


def test_a_rebuild_removes_stale_files_from_the_previous_build(proj):
    write_card(proj.cards, make_card("first", "Fictional first", 2))
    write_card(proj.cards, make_card("second", "Fictional second", 2))
    assert proj.build().errors == []
    assert (proj.out / "hypotheses" / "second.html").is_file()
    (proj.cards / "second.yaml").unlink()
    assert proj.build().errors == []
    assert not (proj.out / "hypotheses" / "second.html").exists()


def test_the_build_refuses_to_delete_a_directory_that_is_not_a_previous_build(proj):
    write_card(proj.cards, make_card("first", "Fictional first", 2))
    proj.out.mkdir()
    precious = proj.out / "notes.txt"
    precious.write_text("keep me", encoding="utf-8")
    result = proj.build()
    assert result.errors and "not deleting" in result.errors[0]
    assert precious.read_text(encoding="utf-8") == "keep me"
    assert proj.run() == 1


def test_the_build_writes_into_an_existing_empty_directory(proj):
    write_card(proj.cards, make_card("first", "Fictional first", 2))
    proj.out.mkdir()
    assert proj.build().errors == []
    assert (proj.out / "index.html").is_file()


def test_written_files_use_unix_line_endings_and_utf8(proj):
    out = built(proj, make_card("lf", "Fictional lf", 2))
    for path in html_files(out) + list((out / "static").iterdir()):
        data = path.read_bytes()
        assert b"\r" not in data, path.name
        data.decode("utf-8")


def test_build_result_lists_every_written_file(proj):
    write_card(proj.cards, make_card("listed", "Fictional listed", 2))
    result = proj.build()
    on_disk = {p for p in proj.out.rglob("*") if p.is_file() and p.name != site.BUILD_MARKER}
    assert set(result.written) == on_disk
    assert {p.name for p in on_disk} == {
        "index.html",
        "listed.html",
        "changes.html",
        "map.html",
        "gaps.html",
        "methods.html",
        "glossary.html",
        "site.css",
        "site.js",
    }


# --- contrast of the colour tokens -----


def css_tokens() -> dict[str, str]:
    root = re.search(r":root\s*\{(.*?)\}", CSS.read_text(encoding="utf-8"), re.DOTALL).group(1)
    return dict(re.findall(r"--([a-z-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", root))


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Body text (4.5:1): text colour, background it sits on.
TEXT_PAIRS = [
    ("ink", "bg"),  # page text
    ("ink", "card"),  # text in rows, studies, tables
    ("ink", "empty"),  # table header cells
    ("muted", "bg"),  # footer, last checked
    ("muted", "card"),  # tags, axis numbers, study meta
    ("muted", "empty"),  # (kept honest: muted text on the pale fill)
    ("link", "bg"),
    ("link", "card"),
    ("warn", "warnbg"),  # draft banner, draft notice
    ("warn", "bg"),  # "Draft - pending expert review" in the intro
    ("tip-ink", "tip-bg"),  # glossary explanation
]
# Chart marks, borders that carry meaning, focus outline and large text (3:1).
GRAPHIC_PAIRS = [
    ("fill", "card"),  # reached segment on a row
    ("fill", "bg"),
    ("fill", "empty"),  # reached versus empty segment
    ("focus", "bg"),  # keyboard focus outline
    ("focus", "card"),
    ("ink", "card"),  # badge border
]


def test_the_contrast_function_rejects_low_contrast():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#888888") < 3
    assert contrast("#767676", "#ffffff") > 4.5  # the well-known smallest grey that passes on white
    assert contrast("#777777", "#ffffff") < 4.5


@pytest.mark.parametrize(("fg", "bg"), TEXT_PAIRS)
def test_body_text_colours_meet_4_5_to_1(fg, bg):
    tokens = css_tokens()
    assert contrast(tokens[fg], tokens[bg]) >= 4.5, (fg, bg, contrast(tokens[fg], tokens[bg]))


@pytest.mark.parametrize(("fg", "bg"), GRAPHIC_PAIRS)
def test_chart_marks_and_focus_meet_3_to_1(fg, bg):
    tokens = css_tokens()
    assert contrast(tokens[fg], tokens[bg]) >= 3, (fg, bg, contrast(tokens[fg], tokens[bg]))


def test_every_colour_used_in_the_stylesheet_is_a_token_or_white():
    css = CSS.read_text(encoding="utf-8")
    body = css.split("}", 1)[1]  # everything after :root
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
    assert not re.findall(r"rgba?\((?!0, 0, 0)", body)  # the shadow is the only literal colour
    used = set(re.findall(r"var\(--([a-z-]+)\)", css))
    assert used <= set(css_tokens())


def test_marked_terms_and_references_get_their_tap_area_without_changing_line_height():
    css = CSS.read_text(encoding="utf-8")
    for selector in (".term", "a.ref"):
        rule = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{(.*?)\}", css, re.DOTALL).group(1)
        assert "min-height" not in rule and "min-width" not in rule, selector
    hit_area = re.search(r"\.term::before,\s*a\.ref::before\s*\{(.*?)\}", css, re.DOTALL).group(1)
    assert "position: absolute" in hit_area and "height: 44px" in hit_area and "max(100%, 44px)" in hit_area


def test_the_stylesheet_meets_the_basic_accessibility_rules():
    css = CSS.read_text(encoding="utf-8")
    assert "font-size: 112.5%" in css  # 18 px base
    assert "prefers-reduced-motion: reduce" in css
    assert ":focus-visible" in css and "outline:" in css
    assert "min-height: 44px" in css
    # nothing scrolls sideways except the map figure, which scrolls inside itself (docs/map.md, "The drawing")
    assert "overflow-x" not in re.sub(r"(?m)^\.map-figure \{[^}]*\}", "", css)


# --- layout revision: ladder key, table behind a disclosure, one h1, minimum text size -----

SPEC = REPO_ROOT / "docs" / "ME-Atlas-functional-spec.md"
MIN_SECONDARY_PX = 16  # spec section 5: secondary text at least 16 px; the base is 18 px (html is 112.5%)
BASE_PX = 18


def spec_rungs() -> list[tuple[int, str, str]]:
    rows = re.findall(r"(?m)^\| ([0-5]) \| ([^|]+?) \| ([^|]+?) \|$", SPEC.read_text(encoding="utf-8"))
    return [(int(n), name, meaning) for n, name, meaning in rows]


def font_sizes_below_minimum(css: str) -> list[str]:
    """Rules with a font-size under 16 px, except the hidden .sr rule. Units other than rem, px and % also fail."""
    offenders = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        names = [n.strip() for n in selectors.split(",")]
        if names == [".sr"]:
            continue
        for value in re.findall(r"(?<![\w-])font-size\s*:\s*([^;}]+)", body):
            value = value.strip()
            m = re.fullmatch(r"([\d.]+)(rem|px|%)", value)
            px = None
            if m:
                number = float(m.group(1))
                px = {"rem": number * BASE_PX, "px": number, "%": number / 100 * BASE_PX}[m.group(2)]
            if px is None or px < MIN_SECONDARY_PX:
                offenders.append(f"{selectors.strip()}: {value}")
    return offenders


def test_the_spec_table_has_six_rungs():
    assert [n for n, _, _ in spec_rungs()] == [0, 1, 2, 3, 4, 5]


def test_front_page_ladder_key_comes_after_the_chart(proj):
    out = built(proj, make_card("one", "Fictional one", 2), make_card("two", "Fictional two", 3))
    order = list(page(out, "index.html").walk())
    last_row = max(i for i, n in enumerate(order) if n.tag == "section" and "row" in n.classes)
    key = next(i for i, n in enumerate(order) if n.tag == "section" and "key" in n.classes)
    legend = next(i for i, n in enumerate(order) if "legend" in n.classes)
    assert last_row < legend < key


def test_ladder_key_has_all_six_rung_names_and_meanings_from_the_spec(proj):
    out = built(proj, make_card("one", "Fictional one", 2))
    key = page(out, "index.html").find("section", "key")
    items = [norm(li.text()) for li in key.find("ol").find_all("li")]
    spec = spec_rungs()
    assert len(items) == 6
    for item, (number, name, meaning) in zip(items, spec, strict=True):
        assert item == f"{number} {name} {meaning}"
    assert tuple(name for _, name, _ in spec) == RUNG_NAMES
    assert tuple(meaning for _, _, meaning in spec) == RUNG_MEANINGS


def test_ladder_key_carries_the_draft_notice_and_the_two_standing_sentences(proj):
    out = built(proj, make_card("one", "Fictional one", 2))
    text = norm(page(out, "index.html").find("section", "key").text())
    assert "The ladder is a draft, pending expert review." in text
    assert "Hypotheses are not mutually exclusive." in text
    assert "furthest along, not by an editorial opinion" in text


def test_ladder_key_is_there_even_when_no_hypothesis_is_published(proj):
    out = built(proj)
    assert page(out, "index.html").find("section", "key") is not None
    assert page(out, "index.html").find("details") is None  # nothing to show as a table


def test_the_table_is_closed_by_default_inside_a_details_element_with_a_summary(proj):
    out = built(proj, make_card("one", "Fictional one", 2))
    doc = page(out, "index.html")
    details = doc.find_all("details")
    assert len(details) == 1
    assert "open" not in details[0].attrs  # an `open` attribute would show the table at first glance
    summary = details[0].find("summary")
    assert norm(summary.text()) == "Show the chart as a table"
    tables = doc.find_all("table")
    assert len(tables) == 1
    assert details[0] in tables[0].ancestors()
    assert list(details[0].children).index(summary) < list(details[0].children).index(tables[0])


def test_every_page_has_exactly_one_h1(proj):
    data = make_card("one", "Fictional one", 3, contested_rungs=[3])
    out = built(proj, data, make_card("two", "Fictional two", 2))
    pages = html_files(out)
    assert len(pages) >= 6  # front page, two cards, changes, methods, glossary
    for path in pages:
        assert len(page(out, path.relative_to(out).as_posix()).find_all("h1")) == 1, path.name
    (proj.root / "empty").mkdir()
    empty = Site(proj.root / "empty")  # a site with no cards has the same rule
    empty.build()
    for path in html_files(empty.out):
        assert len(page(empty.out, path.relative_to(empty.out).as_posix()).find_all("h1")) == 1, path.name


def test_no_font_size_in_the_stylesheet_is_below_16_px_except_the_hidden_sr_rule():
    css = CSS.read_text(encoding="utf-8")
    assert font_sizes_below_minimum(css) == []
    assert re.search(r"\.sr\s*\{", css)  # the exception exists and is the only one


def test_the_font_size_check_flags_small_sizes_and_unknown_units():
    assert font_sizes_below_minimum("p { font-size: .85rem; }") == ["p: .85rem"]
    assert font_sizes_below_minimum(".tag { font-size: 15px; }") == [".tag: 15px"]
    assert font_sizes_below_minimum("@media (max-width: 40em) { .a, .b { font-size: 0.8rem } }") == [".a, .b: 0.8rem"]
    assert font_sizes_below_minimum("h1 { font-size: smaller; }") == ["h1: smaller"]  # cannot be checked, so it fails
    assert font_sizes_below_minimum(".sr { font-size: 0; }") == []
    assert font_sizes_below_minimum("p { font-size: .889rem; } html { font-size: 112.5%; }") == []


# --- paragraphs in level_reason, contested.reason and badges.*.reason -----


def section_paragraphs(doc: Node, heading: str) -> list[Node]:
    """The <p> elements between the h2 whose text starts with ``heading`` and the next h2."""
    main = doc.find("main")
    siblings = main.children
    start = next(
        i
        for i, n in enumerate(siblings)
        if isinstance(n, Node) and n.tag == "h2" and norm(n.text()).startswith(heading)
    )
    out = []
    for n in siblings[start + 1 :]:
        if isinstance(n, Node):
            if n.tag == "h2":
                break
            if n.tag == "p":
                out.append(n)
    return out


def ref_labels(p: Node) -> list[str]:
    return [norm(a.text()) for a in p.find_all("a", "ref")]


def test_paragraphs_render_as_separate_p_elements_with_their_own_references(proj):
    data = make_card("paras", "Fictional paras", 2)
    data["core_claim"]["sources"] = ["pmid:00000001"]
    data["level_reason"] = [
        {"text": "First fictional paragraph.", "sources": ["pmid:00000002"]},
        {"text": "Second fictional paragraph.", "sources": ["pmid:00000003", "pmid:00000001"]},
    ]
    doc = page(built(proj, data), "hypotheses/paras.html")
    ps = section_paragraphs(doc, "Why this level")
    assert [norm(p.text(frozenset({"refs"}))) for p in ps] == [
        "First fictional paragraph.",
        "Second fictional paragraph.",
    ]
    # Numbering follows page order: core claim cites 00000001 -> [1], then 00000002 -> [2], 00000003 -> [3].
    assert ref_labels(ps[0]) == ["[2]"]
    assert ref_labels(ps[1]) == ["[1]", "[3]"]
    hrefs = [a.get("href") for a in ps[1].find_all("a", "ref")]
    assert hrefs == ["#study-pmid:00000001", "#study-pmid:00000003"]


def test_paragraphs_in_contested_and_badge_reasons_render_one_p_each(proj):
    data = make_card("paras2", "Fictional paras two", 4, contested_rungs=[4])
    data["contested"]["reason"] = [
        {"text": "Dispute one.", "sources": ["pmid:00000001"]},
        {"text": "Dispute two.", "sources": ["pmid:00000003"]},
    ]
    data["badges"]["explains_pem"]["reason"] = [
        {"text": "Pem one.", "sources": ["pmid:00000002"]},
        {"text": "Pem two.", "sources": ["pmid:00000002"]},
    ]
    doc = page(built(proj, data), "hypotheses/paras2.html")
    assert [norm(p.text(frozenset({"refs"}))) for p in section_paragraphs(doc, "Contested at")] == [
        "Dispute one.",
        "Dispute two.",
    ]
    badges = doc.find("ul", "badges").find_all("li")[1]
    assert [norm(p.text(frozenset({"refs"}))) for p in badges.find_all("p")[1:]] == ["Pem one.", "Pem two."]


def test_single_object_reason_still_renders_one_p_with_its_references(proj):
    doc = page(built(proj, make_card("single", "Fictional single", 2)), "hypotheses/single.html")
    ps = section_paragraphs(doc, "Why this level")
    assert len(ps) == 1
    assert ref_labels(ps[0]) == ["[1]", "[2]"]  # level_reason cites 00000001 and 00000002


def test_sourced_texts_in_page_order_flattens_paragraphs():
    data = base()
    data["level_reason"] = [
        {"text": "One.", "sources": ["pmid:00000001"]},
        {"text": "Two.", "sources": ["pmid:00000002"]},
    ]
    card = cardlib.Card.model_validate(data)
    texts = site.sourced_texts_in_page_order(card)
    assert [t.text for t in texts[1:3]] == ["One.", "Two."]


# --- the English tree is unchanged by the translation work -----

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "site_en_golden"


def golden_scenario(proj: Site) -> None:
    """Fictional inputs whose English build was recorded (tests/fixtures/site_en_golden) before the language work."""
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional hypothesis", 4, contested_rungs=[4]))
    second = drop_long_covid(make_card("second-idea", "Second fictional idea", 1))
    second["badges"]["explains_pem"] = {"value": False, "reason": None}
    write_card(proj.cards, second)
    every = make_card("every-definition", "Fictional every definition", 3)
    for i, cd in enumerate(sorted(cardlib.CASE_DEFINITION_RANK)):
        add_study(every, f"pmid:0000030{i}", cd)
    write_card(proj.cards, every)
    write_yaml(proj.cards / "changelog.yaml", changelog_entries())
    write_card(proj.drafts, make_card("draft-only", "Fictional draft only idea", 0, contested_rungs=None))


def test_the_english_tree_is_unchanged_apart_from_the_selector_hreflang_tags_and_the_script(tmp_path):
    """The English pages of a fictional project, built by the code of before the language work, are recorded in
    tests/fixtures/site_en_golden. Today's English pages must match them once the added lines are taken out."""

    def without_additions(text: str) -> str:
        added = (
            '<link rel="alternate" hreflang=',
            "<script>(function(){",
            '<div class="lang-switch"',
            '<li><a href="map.html"',  # the navigation entry of the causal map page
            '<li><a href="../map.html"',
            '<li><a href="gaps.html"',
            '<li><a href="../gaps.html"',
            "<p>Found an error on a card",  # the footer's error-report line
        )
        return "".join(line for line in text.splitlines(keepends=True) if not line.lstrip().startswith(added))

    proj = Site(tmp_path)
    golden_scenario(proj)
    checked = 0
    for name, drafts in (("plain", False), ("drafts", True)):
        assert proj.build(drafts=drafts).errors == []
        for recorded in sorted((GOLDEN_DIR / name).rglob("*.html")):
            rel = recorded.relative_to(GOLDEN_DIR / name)
            now = (proj.out / rel).read_text(encoding="utf-8")
            assert without_additions(now) == recorded.read_text(encoding="utf-8"), f"{name}/{rel.as_posix()}"
            checked += 1
    assert checked == 9  # seven pages of the plain build; front page and draft card of the draft build


# --- who decides: the footer and the pages say AI decides and no expert has reviewed -----

FORBIDDEN_PHRASES = (
    "checked by AI tools and by the founder",
    "by the founder and by AI",
    "the founder approves",
    "the founder decides",
    "the founder checks",
    "approved by the founder",
    "decided by the founder",
    "Solve ME",
    "grunnleggeren godkjenner",
    "grunnleggeren avgjør",
    "grunnleggeren kontrollerer",
    "av grunnleggeren",
)


def test_the_footer_says_ai_decides_every_level_and_no_expert_has_reviewed_it_in_both_languages(proj):
    out = built(proj, make_card("fictional-hypothesis", "Fictional hypothesis", 2))
    en = norm(page(out, "index.html").find("footer").text())
    assert "The content, including every evidence level, is drafted, checked and decided by AI tools." in en
    assert "No medical or research expert has reviewed it." in en
    assert "checked by AI tools and by the founder" not in en
    nb = norm(page(out, "nb/index.html").find("footer").text())
    assert "Innholdet, også hvert evidensnivå, utarbeides, kontrolleres og avgjøres av KI-verktøy." in nb
    assert "Ingen medisinsk eller forskningsfaglig ekspert har gjennomgått det." in nb


def test_no_built_page_says_the_founder_checks_approves_or_decides_content_and_none_has_a_contact_line(proj):
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional hypothesis", 2))
    write_yaml(proj.cards / "changelog.yaml", changelog_entries())
    assert proj.build().errors == []
    pages = sorted(proj.out.rglob("*.html"))
    assert any(p.name == "methods.html" and p.parent.name == "nb" for p in pages)
    for path in pages:
        text = norm(page(proj.out, path.relative_to(proj.out).as_posix()).text())
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text, f"{path.relative_to(proj.out)}: {phrase}"
        assert "@" not in text.replace("@media", ""), path.name  # no contact address
