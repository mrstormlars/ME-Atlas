"""The card page labels a preprint study and the early-signal paragraphs that cite one. Fictional cards; no network."""

from __future__ import annotations

import pytest
from test_site import Site, built, make_card, norm, page, write_card
from test_site_languages import write_sidecar

SLUG = "fictional-preprint-card"
PREPRINT_ID = "doi:10.99999/fictional.pre"
LABEL_EN = "Preprint: not peer reviewed."
LABEL_NB = "Preprint: ikke fagfellevurdert."
PREPRINT_SIGNAL = "A fictional preprint reported a related change, not yet replicated and not peer reviewed by anyone."


def preprint_card() -> dict:
    card = make_card(SLUG, "Fictional hypothesis with a preprint", 4, contested_rungs=[4])
    card["studies"].append(
        {
            "id": PREPRINT_ID,
            "title": "Fictional preprint of widget signalling",
            "year": 2026,
            "cohort": "me_cfs",
            "case_definition": "other",
            "case_definition_source": "abstract",
            "case_definition_quote": None,
            "design": "uncontrolled",
            "n_patients": 12,
            "n_controls": None,
            "measures_pem": False,
            "preregistered": None,
            "role": "early_signal",
            "direction": "mixed",
            "finding": "A preprint of n=12 patients reported a fictional change.",
            "preprint": True,
        }
    )
    card["early_signals"].append({"text": PREPRINT_SIGNAL, "sources": [PREPRINT_ID]})
    return card


@pytest.fixture
def proj(tmp_path) -> Site:
    return Site(tmp_path)


def label_places(doc, label: str) -> list[str]:
    """Where the label stands: the study entry of the preprint, or an early-signal paragraph."""
    places = []
    for article in doc.find_all("article", "study"):
        if label in norm(article.text()):
            places.append("study:" + article.get("id"))
    for p in doc.find_all("p"):
        text = norm(p.text())
        if label in text and PREPRINT_SIGNAL in text:
            places.append("early_signal")
    return places


def test_the_english_card_page_labels_the_preprint_study_and_the_early_signal_that_cites_it(proj):
    out = built(proj, preprint_card())
    html = (out / "hypotheses" / f"{SLUG}.html").read_text(encoding="utf-8")
    assert html.count(LABEL_EN) == 2
    assert label_places(page(out, f"hypotheses/{SLUG}.html"), LABEL_EN) == [
        f"study:study-{PREPRINT_ID}",
        "early_signal",
    ]


def test_the_norwegian_card_page_has_the_norwegian_label_and_not_the_english_one(proj):
    card = preprint_card()
    write_card(proj.cards, card)
    write_sidecar(proj, card)
    assert proj.build().errors == []
    html = (proj.out / "nb" / "hypotheses" / f"{SLUG}.html").read_text(encoding="utf-8")
    assert html.count(LABEL_NB) == 2
    assert LABEL_EN not in html
    assert label_places(page(proj.out, f"nb/hypotheses/{SLUG}.html"), LABEL_NB) == [
        f"study:study-{PREPRINT_ID}",
        "early_signal",
    ]


def test_a_card_without_preprints_shows_no_label_in_either_language(proj):
    card = make_card("fictional-plain-card", "Fictional plain hypothesis", 4, contested_rungs=[4])
    write_card(proj.cards, card)
    write_sidecar(proj, card)
    assert proj.build().errors == []
    for name in ("hypotheses/fictional-plain-card.html", "nb/hypotheses/fictional-plain-card.html"):
        html = (proj.out / name).read_text(encoding="utf-8")
        assert LABEL_EN not in html and LABEL_NB not in html


def test_the_other_pages_do_not_carry_the_label(proj):
    out = built(proj, preprint_card())
    for name in ("index.html", "map.html", "gaps.html", "methods.html", "changes.html"):
        assert LABEL_EN not in (out / name).read_text(encoding="utf-8"), name
