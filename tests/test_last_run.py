"""Tests for content/last-run.yaml: the loader and the real seeded file. Offline."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from me_atlas import last_run

TODAY = dt.date(2026, 11, 18)
GOOD = "date: '2026-11-17'\nmode: weekly\npapers_in_window: 16\npapers_selected: 5\ncards_changed: 3\n"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "last-run.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_valid_file_loads_with_the_date_as_text(tmp_path):
    record, problems = last_run.load(write(tmp_path, GOOD), TODAY)
    assert problems == []
    assert record == {
        "date": "2026-11-17",
        "mode": "weekly",
        "papers_in_window": 16,
        "papers_selected": 5,
        "cards_changed": 3,
    }


def test_an_unquoted_yaml_date_is_accepted_and_today_is_not_in_the_future(tmp_path):
    text = GOOD.replace("'2026-11-17'", "2026-11-18")
    record, problems = last_run.load(write(tmp_path, text), TODAY)
    assert problems == [] and record["date"] == "2026-11-18"


def test_dump_and_load_round_trip(tmp_path):
    record = {"date": "2026-11-17", "mode": "since", "papers_in_window": 0, "papers_selected": 0, "cards_changed": 0}
    assert last_run.load(write(tmp_path, last_run.dump(record)), TODAY) == (record, [])


def test_the_seeded_file_is_valid():
    record, problems = last_run.load(last_run.DEFAULT_PATH, dt.date.today())
    assert problems == [] and record is not None


def test_a_missing_file_is_a_problem(tmp_path):
    record, problems = last_run.load(tmp_path / "nope.yaml", TODAY)
    assert record is None and "missing" in problems[0]


def test_invalid_yaml_is_a_problem(tmp_path):
    record, problems = last_run.load(write(tmp_path, "date: [unclosed\n"), TODAY)
    assert record is None and "not valid YAML" in problems[0]


@pytest.mark.parametrize("text", ["- a\n- b\n", "just text\n", "", "42\n"])
def test_a_file_that_is_not_a_mapping_is_a_problem(tmp_path, text):
    record, problems = last_run.load(write(tmp_path, text), TODAY)
    assert record is None and "not a mapping" in problems[0]


def test_a_missing_key_is_a_problem(tmp_path):
    record, problems = last_run.load(write(tmp_path, GOOD.replace("cards_changed: 3\n", "")), TODAY)
    assert record is None and "missing key 'cards_changed'" in problems[0]


def test_an_extra_key_is_a_problem(tmp_path):
    record, problems = last_run.load(write(tmp_path, GOOD + "note: x\n"), TODAY)
    assert record is None and "unexpected key 'note'" in problems[0]


@pytest.mark.parametrize("value", ["'17 November 2026'", "'2026-13-01'", "'2026-11-1'", "20261117", "null", "[1]"])
def test_a_date_that_is_not_an_iso_date_is_a_problem(tmp_path, value):
    record, problems = last_run.load(write(tmp_path, GOOD.replace("'2026-11-17'", value)), TODAY)
    assert record is None and "not an ISO date" in problems[0]


def test_a_date_after_today_is_a_problem(tmp_path):
    record, problems = last_run.load(write(tmp_path, GOOD.replace("2026-11-17", "2026-11-19")), TODAY)
    assert record is None and "later than today" in problems[0]


@pytest.mark.parametrize("key", ["papers_in_window", "papers_selected", "cards_changed"])
@pytest.mark.parametrize("value", ["-1", "'3'", "2.5", "true", "null"])
def test_a_count_that_is_negative_or_not_an_integer_is_a_problem(tmp_path, key, value):
    text = "\n".join(f"{key}: {value}" if line.startswith(key) else line for line in GOOD.splitlines()) + "\n"
    record, problems = last_run.load(write(tmp_path, text), TODAY)
    assert record is None and key in problems[0]


@pytest.mark.parametrize("mode", ["daily", "ids"])
def test_a_mode_other_than_weekly_or_since_is_a_problem_and_ids_is_one_too(tmp_path, mode):
    record, problems = last_run.load(write(tmp_path, GOOD.replace("weekly", mode)), TODAY)
    assert record is None and "mode" in problems[0]
