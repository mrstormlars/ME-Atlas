"""``content/last-run.yaml``: when the weekly pipeline last searched for new research, and what it found.

The file is written by ``pipeline pr`` from the run's own files (``prepare.json`` and the number of card texts), never
from an agent's output, and read by the site build. One loader, ``load``, serves both; it returns the record or a list
of problems. A record is a mapping with exactly the keys in ``KEYS``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "content" / "last-run.yaml"
FILE_NAME = "last-run.yaml"
MODES = ("weekly", "since", "ids")
COUNT_KEYS = ("papers_in_window", "papers_selected", "cards_changed")
KEYS = ("date", "mode", *COUNT_KEYS)


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and len(value) == 10:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def validate(raw: Any, today: dt.date) -> tuple[dict[str, Any] | None, list[str]]:
    """The record (the date as an ISO string) and no problems, or None and the problems."""
    if not isinstance(raw, dict):
        return None, ["the file is not a mapping"]
    problems = [f"missing key '{k}'" for k in KEYS if k not in raw]
    problems += [f"unexpected key '{k}'" for k in raw if k not in KEYS]
    if "date" in raw:
        day = _date(raw["date"])
        if day is None:
            problems.append(f"date {raw['date']!r} is not an ISO date (YYYY-MM-DD)")
        elif day > today:
            problems.append(f"date {day.isoformat()} is later than today ({today.isoformat()})")
    if "mode" in raw and raw["mode"] not in MODES:
        problems.append(f"mode {raw['mode']!r} is not one of {', '.join(MODES)}")
    for key in COUNT_KEYS:
        if key in raw:
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(f"{key} {value!r} is not an integer")
            elif value < 0:
                problems.append(f"{key} {value} is negative")
    if problems:
        return None, problems
    record = {k: raw[k] for k in KEYS}
    record["date"] = _date(raw["date"]).isoformat()  # type: ignore[union-attr]
    return record, []


def load(path: Path, today: dt.date | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Read and check the file. Problems are printable lines; none means the record is valid."""
    today = today or dt.date.today()
    path = Path(path)
    if not path.is_file():
        return None, [f"{path} is missing"]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        return None, [f"{path} is not valid YAML: {exc}"]
    record, problems = validate(raw, today)
    return record, [f"{path}: {p}" for p in problems]


def make_record(prepare: dict[str, Any], cards_changed: int) -> dict[str, Any]:
    """The record of a run, from its ``prepare.json`` and the number of card texts the ``pr`` step writes."""
    return {
        "date": str(prepare["date"]),
        "mode": prepare["mode"],
        "papers_in_window": prepare["in_window"],
        "papers_selected": prepare["selected"],
        "cards_changed": cards_changed,
    }


def dump(record: dict[str, Any]) -> str:
    """The file text. The date is quoted so that it stays a string for every YAML reader."""
    lines = [f"date: '{record['date']}'"]
    lines += [f"{k}: {record[k]}" for k in KEYS[1:]]
    return "# Written by `pipeline pr` from the run's own files; do not edit by hand.\n" + "\n".join(lines) + "\n"
