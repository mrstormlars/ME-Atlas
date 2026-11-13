"""Tests for `pipeline content-paths`: protected content paths change only by commits carrying the pipeline marker.

The repositories are built in a temporary folder with the local git; no network, no model. The user name and email are
set in the temporary repository only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from me_atlas import pipeline

MARKED = "ME-Atlas-Pipeline: weekly-run 2026-11-13"


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True
    )
    return done.stdout


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-b", "main")
    git(r, "config", "user.name", "Test Author")
    git(r, "config", "user.email", "test@example.invalid")
    git(r, "config", "core.autocrlf", "false")
    commit(r, {"README.md": "x\n", "cards/a.yaml": "a: 1\n"}, "base")
    git(r, "switch", "-c", "feature")
    return r


def run(repo: Path, capsys) -> tuple[int, str]:
    code = pipeline.main(["content-paths", "--repo", str(repo), "--base", "main", "--head", "HEAD"])
    return code, capsys.readouterr().out


def marked(subject: str) -> str:
    return f"{subject}\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n{MARKED}"


def test_a_branch_that_changes_only_code_and_docs_passes(repo, capsys):
    commit(repo, {"src/x.py": "1\n", "docs/y.md": "y\n"}, "code and docs")
    code, out = run(repo, capsys)
    assert code == 0
    assert "PASS: no protected content path is changed." in out
    assert "2 file(s) changed" in out


@pytest.mark.parametrize(
    "path",
    ["cards/x.yaml", "cards/changelog.yaml", "drafts/x.yaml", "translations/nb/x.yaml", "audits/2026-11-13-x.yaml"],
)
def test_an_unmarked_commit_that_changes_a_protected_path_fails_and_is_named(repo, capsys, path):
    sha = commit(repo, {path: "z: 1\n", "src/x.py": "1\n"}, "edit content by hand")
    code, out = run(repo, capsys)
    assert code == 1
    assert "FAIL" in out and path in out and sha[:10] in out and "edit content by hand" in out
    assert "src/x.py" not in out.split("FAIL")[1]  # only the offending file is listed


def test_an_unmarked_commit_that_deletes_a_protected_file_fails(repo, capsys):
    git(repo, "rm", "-q", "cards/a.yaml")
    git(repo, "commit", "-m", "delete a card")
    code, out = run(repo, capsys)
    assert code == 1 and "cards/a.yaml" in out


def test_a_branch_whose_only_protected_change_is_in_a_marked_commit_passes(repo, capsys):
    commit(repo, {"drafts/x.yaml": "x: 1\n", "cards/a.yaml": "a: 2\n"}, marked("Weekly pipeline"))
    commit(repo, {"src/x.py": "1\n"}, "a code change")
    code, out = run(repo, capsys)
    assert code == 0
    assert "PASS: every protected path is changed only by commits marked" in out
    assert "2 protected" in out


def test_a_marked_commit_followed_by_an_unmarked_one_on_the_same_file_fails(repo, capsys):
    commit(repo, {"cards/a.yaml": "a: 2\n"}, marked("Weekly pipeline"))
    late = commit(repo, {"cards/a.yaml": "a: 3\n"}, "a hand edit afterwards")
    code, out = run(repo, capsys)
    assert code == 1
    assert "cards/a.yaml" in out and late[:10] in out


@pytest.mark.parametrize(
    "trailer",
    [
        "ME-Atlas-Pipeline: weekly-run 2026-13-45",  # not a date
        "ME-Atlas-Pipeline: weekly-run tomorrow",
        "ME-Atlas-Pipeline: weekly-run",  # no date
        "ME-Atlas-Pipelines: weekly-run 2026-11-13",  # wrong key
        "me-atlas-pipeline: weekly-run 2026-11-13",  # wrong case
        "ME-Atlas-Pipeline: manual-run 2026-11-13",  # wrong value
        "ME-Atlas-Pipeline: weekly-run 2026-11-13 extra",
    ],
)
def test_a_malformed_marker_does_not_count(repo, capsys, trailer):
    commit(
        repo,
        {"cards/a.yaml": "a: 2\n"},
        f"Weekly pipeline\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n{trailer}",
    )
    code, out = run(repo, capsys)
    assert code == 1 and "cards/a.yaml" in out


def test_a_marker_that_is_not_in_the_last_paragraph_or_is_the_only_paragraph_does_not_count(repo, capsys):
    commit(repo, {"cards/a.yaml": "a: 2\n"}, f"{MARKED}\n\nthen a closing paragraph")
    assert run(repo, capsys)[0] == 1
    commit(repo, {"cards/a.yaml": "a: 3\n"}, MARKED)  # a subject line alone is not a trailer block
    assert run(repo, capsys)[0] == 1


def test_a_merge_commit_that_changes_a_protected_path_on_its_own_fails(repo, capsys):
    commit(repo, {"cards/a.yaml": "a: 1\nfeature: 1\n"}, marked("Weekly pipeline"))
    git(repo, "switch", "main")
    commit(repo, {"cards/a.yaml": "a: 1\nmain: 1\n"}, "a change on main")
    git(repo, "switch", "feature")
    done = subprocess.run(["git", "-C", str(repo), "merge", "--no-commit", "--no-ff", "main"], capture_output=True)
    assert done.returncode != 0  # a conflict in cards/a.yaml
    (repo / "cards" / "a.yaml").write_text("a: 1\nresolved by hand: 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "Merge main")
    code, out = run(repo, capsys)
    assert code == 1
    assert "cards/a.yaml" in out and "Merge main" in out


def test_a_clean_merge_of_main_into_the_branch_passes(repo, capsys):
    commit(repo, {"src/x.py": "1\n"}, "a code change")
    git(repo, "switch", "main")
    commit(repo, {"cards/b.yaml": "b: 1\n"}, "a card published on main")
    git(repo, "switch", "feature")
    git(repo, "merge", "--no-ff", "-m", "Merge main", "main")
    code, out = run(repo, capsys)
    assert code == 0, out


def test_commit_is_marked_reads_the_exact_trailer_only():
    assert pipeline.commit_is_marked(marked("Subject"))
    assert pipeline.commit_is_marked(marked("Subject") + "\n")
    assert pipeline.commit_is_marked(f"Subject\n\nbody\n\n{MARKED}")
    assert not pipeline.commit_is_marked("Subject\n\nbody")
    assert not pipeline.commit_is_marked("Subject\n\nME-Atlas-Pipeline: weekly-run 2026-02-30")


def test_an_unknown_base_is_an_error_not_a_pass(repo, capsys):
    assert pipeline.main(["content-paths", "--repo", str(repo), "--base", "no-such-branch"]) == 1
    assert "error:" in capsys.readouterr().err
