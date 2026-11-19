"""Tests for the GitHub Pages workflow and the error-report line in the footer. No network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from test_site import Site, built, make_card, norm, page, write_card

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pages.yml"
REPO = "https://github.com/mrstormlars/ME-Atlas"
ISSUES = REPO + "/issues/new/choose"


@pytest.fixture
def proj(tmp_path) -> Site:
    return Site(tmp_path)


def load(text: str | None = None) -> dict:
    data = yaml.safe_load(text if text is not None else WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads the key `on` as the boolean True.
    data["on"] = data.pop(True) if True in data else data["on"]
    return data


def run_commands(workflow: dict) -> list[str]:
    return [s["run"] for job in workflow["jobs"].values() for s in job["steps"] if "run" in s]


def problems(text: str) -> list[str]:
    """Every way the workflow text breaks the rules; empty when it keeps them."""
    wf = load(text)
    found = []
    if set(wf["on"]) != {"push", "workflow_dispatch"} or wf["on"]["push"] != {"branches": ["main"]}:
        found.append("trigger")
    if wf["permissions"] != {"contents": "read", "pages": "write", "id-token": "write"}:
        found.append("permissions")
    if wf["concurrency"].get("cancel-in-progress") is not False or not wf["concurrency"].get("group"):
        found.append("concurrency")
    builds = [c for c in run_commands(wf) if "me_atlas.site" in c]
    if builds != ["uv run python -m me_atlas.site build --goatcounter me-atlas"]:
        found.append("build command")
    uses = re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*(\S+)", text)
    if not uses or not all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses):
        found.append("unpinned action")
    if "secrets." in text or "data/" in text:
        found.append("secret or data path")
    return found


def test_the_workflow_keeps_the_rules():
    assert problems(WORKFLOW.read_text(encoding="utf-8")) == []


def test_the_workflow_has_a_build_job_and_a_deploy_job_that_needs_it():
    wf = load()
    assert wf["jobs"]["deploy"]["needs"] == "build"
    assert wf["jobs"]["deploy"]["environment"]["name"] == "github-pages"
    upload = [s for s in wf["jobs"]["build"]["steps"] if s.get("uses", "").startswith("actions/upload-pages-artifact")]
    assert upload[0]["with"] == {"path": "build"}


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("site build --goatcounter me-atlas\n", "site build --goatcounter me-atlas --drafts\n", "build command"),
        ("site build --goatcounter me-atlas\n", "site build --goatcounter me-atlas --out public\n", "build command"),
        ("site build --goatcounter me-atlas\n", "site build\n", "build command"),
        ("branches: [main]", "branches: [main, dev]", "trigger"),
        ("  id-token: write", "  id-token: write\n  issues: write", "permissions"),
        ("cancel-in-progress: false", "cancel-in-progress: true", "concurrency"),
        ("@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3", "@v10", "unpinned action"),
        ("run: uv sync --locked", "run: uv sync --locked ${{ secrets.TOKEN }}", "secret or data path"),
        ("run: uv sync --locked", "run: cp -r data/cache x", "secret or data path"),
    ],
)
def test_a_broken_workflow_is_caught(old, new, expected):
    text = WORKFLOW.read_text(encoding="utf-8")
    assert old in text
    assert expected in problems(text.replace(old, new, 1))


# --- the error-report line -----


def test_every_built_page_in_both_languages_has_the_error_report_line_with_both_links(proj: Site):
    out = built(proj, make_card("fictional-hypothesis", "Fictional hypothesis", 2))
    pages = sorted(out.rglob("*.html"))
    assert any(p.parent.name == "nb" for p in pages) and any(p.parent == out for p in pages)
    for path in pages:
        rel = path.relative_to(out).as_posix()
        footer = page(out, rel).find("footer")
        hrefs = {a.get("href"): a for a in footer.find_all("a")}
        assert ISSUES in hrefs and REPO in hrefs, rel
        assert hrefs[ISSUES].get("target") is None and hrefs[REPO].get("target") is None, rel
        text = norm(footer.text())
        expected = "Found an error on a card or on the site?" if "nb/" not in rel else "Funnet en feil på et kort"
        assert expected in text, rel


def test_the_report_line_is_missing_when_the_key_is_removed_from_the_norwegian_file(proj: Site):
    nb = proj.content / "i18n" / "nb.yaml"
    lines = nb.read_text(encoding="utf-8").splitlines(keepends=True)
    nb.write_text("".join(ln for ln in lines if not ln.startswith("footer.report:")), encoding="utf-8")
    write_card(proj.cards, make_card("fictional-hypothesis", "Fictional hypothesis", 2))
    result = proj.build()
    assert any("missing key 'footer.report'" in e for e in result.errors)
