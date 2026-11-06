"""Redact user-identifying arrays from the captured upstream fixture.

Upstream `job_information` ships `viewedByUsers`, `appliedFromUsers`,
`savedFromUsers` and `hiddenFromUsers`: arrays of real Firebase UIDs belonging to
real people. The fixture is a genuine captured response and is valuable as test
ground truth, but it should not republish personal identifiers, so those four
keys are removed before the fixture is committed.

Nothing else changes: every field the tests assert on (titles, companies,
compensation, engagement *counts*, technical tools, education, benefits) is
preserved, which is why the measured behaviour is identical after redaction.

Run: python scripts/redact_fixture.py [fixture.json]
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "tests" / "fixtures" / "classic_83702_data_analyst.json"

PII_KEYS = ("viewedByUsers", "appliedFromUsers", "savedFromUsers", "hiddenFromUsers")


def redact(node: object, removed: dict[str, int]) -> None:
    """Walk the structure in place, deleting any PII array and counting the loss."""
    if isinstance(node, dict):
        for key in PII_KEYS:
            if key in node:
                value = node.pop(key)
                removed[key] = removed.get(key, 0) + (len(value) if isinstance(value, list) else 1)
        for value in node.values():
            redact(value, removed)
    elif isinstance(node, list):
        for item in node:
            redact(item, removed)


def main() -> int:
    path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    payload = json.loads(path.read_text(encoding="utf-8"))

    removed: dict[str, int] = {}
    redact(payload, removed)

    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    hits = len(payload.get("pageProps", {}).get("ssrHits") or [])
    print(f"redacted {path.name}: {hits} hits preserved")
    for key, count in sorted(removed.items()):
        print(f"  removed {count:>6} identifiers from {key}")
    print(f"  total identifiers removed: {sum(removed.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
