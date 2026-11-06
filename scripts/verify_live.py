"""Independent verification: live API output vs the captured upstream payload.

Deliberately re-derives every field from the raw fixture with its own logic
instead of calling app.normalize, so a bug in normalize.py cannot hide itself.

Usage: python scripts/verify_live.py [live_search.json]
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "live_search.json"
FIXTURE = ROOT / "tests" / "fixtures" / "classic_83702_data_analyst.json"

PERIOD = {
    "Yearly": ("yearly_min_compensation", "yearly_max_compensation"),
    "Hourly": ("hourly_min_compensation", "hourly_max_compensation"),
    "Monthly": ("monthly_min_compensation", "monthly_max_compensation"),
    "Weekly": ("weekly_min_compensation", "weekly_max_compensation"),
    "Bi-weekly": ("bi-weekly_min_compensation", "bi-weekly_max_compensation"),
    "Daily": ("daily_min_compensation", "daily_max_compensation"),
}


def expected_from_upstream(hit: dict) -> dict:
    v5 = hit.get("v5_processed_job_data") or {}
    ji = hit.get("job_information") or {}
    period = v5.get("listed_compensation_frequency")
    fmin, fmax = PERIOD.get(period, (None, None))
    return {
        "id": hit.get("id"),
        "title": ji.get("title") or v5.get("core_job_title"),
        "company": v5.get("company_name"),
        "workplace_type": v5.get("workplace_type"),
        "seniority": v5.get("seniority_level"),
        "posted_date": (v5.get("estimated_publish_date") or "")[:10] or None,
        "views": ji.get("num_views") or 0,
        "applies": ji.get("num_applies") or 0,
        "saves": ji.get("num_saves") or 0,
        "pay_min": v5.get(fmin) if fmin else None,
        "pay_max": v5.get(fmax) if fmax else None,
        "transparent": bool(v5.get("is_compensation_transparent")),
    }


def main() -> int:
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    upstream = json.loads(FIXTURE.read_text(encoding="utf-8"))["pageProps"]

    hits = upstream["ssrHits"]
    jobs = live["jobs"]
    meta = live["meta"]
    failures: list[str] = []

    def check(label: str, got, want) -> None:
        ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  !=  {want!r}"))
        if not ok:
            failures.append(label)

    print("== meta ==")
    check("total_count", meta["total_count"], upstream["ssrTotalCount"])
    check("company_count", meta["company_count"], upstream["ssrCompanyCount"])
    check("is_last_page", meta["is_last_page"], upstream["ssrIsLastPage"])
    check("page", meta["page"], upstream["ssrPage"])
    check("signed_in", meta["signed_in"], upstream["ssrSignedIn"])
    check("jobs returned", len(jobs), len(hits))
    check("build_id present", bool(meta["build_id"]), True)
    check("upstream_status", meta["upstream_status"], 200)

    print("\n== resolved location (byte-exact reproduction) ==")
    check("location == upstream initialSearchState", meta["location"], upstream["initialSearchState"]["locations"][0])

    print("\n== per-job field extraction ==")
    by_id = {job["id"]: job for job in jobs}
    check("id set matches", sorted(by_id), sorted(h.get("id") for h in hits))

    for hit in hits:
        want = expected_from_upstream(hit)
        job = by_id.get(want["id"])
        if job is None:
            failures.append(f"missing job {want['id']}")
            continue
        got = {
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "workplace_type": job["workplace_type"],
            "seniority": job["seniority"],
            "posted_date": job["posted_date"],
            "views": job["engagement"]["views"],
            "applies": job["engagement"]["applies"],
            "saves": job["engagement"]["saves"],
            "pay_min": job["salary"]["min"],
            "pay_max": job["salary"]["max"],
            "transparent": job["salary"]["is_transparent"],
        }
        diffs = {k: (got[k], want[k]) for k in want if got[k] != want[k]}
        if diffs:
            failures.append(f"{want['id']}: {diffs}")
            print(f"  FAIL  {want['title']!r} -> {diffs}")
        else:
            print(f"  PASS  {want['title']!r} @ {want['company']!r}")

    print("\n== summary ==")
    if failures:
        print(f"FAILED ({len(failures)} problems)")
        for f in failures:
            print(" -", f)
        return 1
    print(f"ALL CHECKS PASSED: {len(jobs)} jobs reproduced field-for-field from upstream")
    print(f"  build_id={meta['build_id']}  cache_hit={meta.get('cache_hit')}  es_latency_ms={meta['es_latency_ms']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
