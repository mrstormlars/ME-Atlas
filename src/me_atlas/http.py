"""HTTP helpers shared by the PubMed and Europe PMC clients: rate limiter, retries and ``.env`` reading.

Behaviour is exactly what ``pubmed.py`` had before the move (see ``tests/test_pubmed.py``): requests are
spaced by a sliding-window rate limiter, and 429, 5xx and transport errors are retried with exponential
backoff (honouring a numeric ``Retry-After`` header, capped at 60 seconds).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx


class RateLimiter:
    """Allows at most ``max_per_second`` request starts in any ``window`` seconds.

    ``clock`` and ``sleep`` are injectable so tests run without real waiting.
    """

    def __init__(
        self,
        max_per_second: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        window: float = 1.0,
    ):
        self._max = max_per_second
        self._clock = clock
        self._sleep = sleep
        self._window = window
        self._starts: deque[float] = deque(maxlen=max_per_second)

    def wait(self) -> None:
        """Block until a request may start, then record its start."""
        while True:
            now = self._clock()
            if len(self._starts) < self._max or now - self._starts[0] >= self._window:
                break
            self._sleep(self._starts[0] + self._window - now)
        self._starts.append(now)


def get_with_retries(
    http: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str | int] | None,
    limiter: RateLimiter,
    sleep: Callable[[float], None],
    max_retries: int,
    backoff: float,
    label: str,
    error: type[Exception],
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """GET with rate limiting; retries 429, 5xx and transport errors with exponential backoff.

    Other 4xx responses are not retried. Failures raise ``error`` with a message that starts with ``label``.
    """
    attempts = max_retries + 1
    last = "no attempt made"
    for attempt in range(attempts):
        limiter.wait()
        retry_after = 0.0
        try:
            response = http.get(url, params=params, headers=headers)
        except httpx.TransportError as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 429 or response.status_code >= 500:
                last = f"HTTP {response.status_code}"
                header = response.headers.get("Retry-After", "")
                retry_after = min(float(header), 60.0) if header.isdigit() else 0.0
            elif response.status_code >= 400:
                raise error(f"{label} failed: HTTP {response.status_code} (not retried)")
            else:
                return response
        if attempt < attempts - 1:
            sleep(max(backoff * 2**attempt, retry_after))
    raise error(f"{label} failed after {attempts} attempts; last error: {last}")


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    """Read simple KEY=VALUE lines from a .env file (no dependency on python-dotenv)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values
