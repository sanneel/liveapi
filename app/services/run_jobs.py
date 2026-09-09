"""Short-lived run codes: hand a generated console script to the browser.

Why this exists
---------------
96% of every emitted console script is embedded JSON payload — gow_combined is
651 KB of which 621 KB is the body. That is the whole reason pasting hurts. If
the operator instead runs a five-line loader that *fetches* the script, the paste
is one line and never changes, which makes a saved DevTools Snippet (or a
bookmarklet) enough. No extension, so no ExtensionInstallBlocklist to fight.

The flow:

    CRM page  --POST /admin/tools/script-runner/job-->  code (authenticated)
    backoffice console  --GET /run/<code>-->  the script text (public)

`GET /run/<code>` has to be public: it is fetched from a page on the backoffice
origin, which carries no CRM session (the cookie is SameSite=lax). The code is
the credential, so it is high-entropy, expires in minutes, and is good for only
a few reads.

In-memory on purpose. A run code is a rendered draft payload with a lifetime
measured in minutes; it belongs in RAM, not in the database or on disk. A
restart drops outstanding codes, which is correct — the operator mints another
with one click.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Optional

# Unambiguous alphabet: no O/0, no I/1/l. These get read off a screen and typed.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10  # 31^10 ≈ 8e14 — brute force is hopeless even before the TTL

TTL_SECONDS = 15 * 60
# More than one read so a failed run can be retried without re-minting, but few
# enough that a leaked code is not a standing grant.
MAX_READS = 3
# A cap so a runaway page cannot exhaust memory with 650 KB scripts.
MAX_JOBS = 64
MAX_SCRIPT_BYTES = 8 * 1024 * 1024


@dataclass
class Job:
    code: str
    name: str
    text: str
    created_at: float
    created_by: str
    reads: int = 0

    def expired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now - self.created_at > TTL_SECONDS or self.reads >= MAX_READS

    @property
    def expires_in(self) -> int:
        return max(0, int(TTL_SECONDS - (time.time() - self.created_at)))


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _purge(now: float) -> None:
    """Drop expired jobs. Called on every access; there are never many."""
    for code in [c for c, j in _jobs.items() if j.expired(now)]:
        _jobs.pop(code, None)


def create(name: str, text: str, created_by: str) -> Job:
    """Mint a code for this script. Raises ValueError on an unusable script."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty script")
    if len(text.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ValueError("script is too large to hand over")

    now = time.time()
    with _lock:
        _purge(now)
        if len(_jobs) >= MAX_JOBS:
            # Evict the oldest rather than refuse: the newest request is the one
            # an operator is waiting on.
            oldest = min(_jobs.values(), key=lambda j: j.created_at)
            _jobs.pop(oldest.code, None)

        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        job = Job(code=code, name=name[:200], text=text,
                  created_at=now, created_by=created_by)
        _jobs[code] = job
        return job


def claim(code: str) -> Optional[Job]:
    """Return the job for this code and count the read, or None.

    Case-insensitive, and tolerant of the spaces and dashes a person types.
    """
    if not code:
        return None
    normalised = "".join(ch for ch in code.upper() if ch in ALPHABET)
    now = time.time()
    with _lock:
        _purge(now)
        job = _jobs.get(normalised)
        if job is None:
            return None
        job.reads += 1
        if job.expired(now):
            # This read was the last one it had.
            _jobs.pop(normalised, None)
        return job


def stats() -> dict:
    with _lock:
        _purge(time.time())
        return {"outstanding": len(_jobs)}
