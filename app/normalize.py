"""Upstream pageProps -> stable public JSON.

The upstream payload is deeply nullable (an undisclosed salary is nine separate
nulls, a missing seniority is ``None`` while a missing YOE flag may be
``None`` *or* ``False``). Every accessor here is defensive so a single null
never takes the response down.
"""

from __future__ import annotations

import html as _html
import math
from typing import Any

DEGREE_KEYS = (
    ("associates", "associates_degree_requirement"),
    ("bachelors", "bachelors_degree_requirement"),
    ("masters", "masters_degree_requirement"),
    ("doctorate", "doctorate_degree_requirement"),
)

BENEFIT_KEYS = (
    ("retirement_plan", "retirement_plan"),
    ("401k_matching", "401k_matching"),
    ("visa_sponsorship", "visa_sponsorship"),
    ("tuition_reimbursement", "tuition_reimbursement"),
    ("relocation_assistance", "relocation_assistance"),
    ("paid_time_off", "generous_paid_time_off"),
    ("parental_leave", "generous_parental_leave"),
    ("four_day_work_week", "four_day_work_week"),
    ("overtime_required", "overtime_required"),
)

# Listed amount fields per advertised pay period.
PERIOD_FIELDS = {
    "Yearly": ("yearly_min_compensation", "yearly_max_compensation"),
    "Hourly": ("hourly_min_compensation", "hourly_max_compensation"),
    "Monthly": ("monthly_min_compensation", "monthly_max_compensation"),
    "Weekly": ("weekly_min_compensation", "weekly_max_compensation"),
    "Bi-weekly": ("bi-weekly_min_compensation", "bi-weekly_max_compensation"),
    "Daily": ("daily_min_compensation", "daily_max_compensation"),
}


def _first(values: Any) -> Any:
    """First element of a list, or None for anything else."""
    if isinstance(values, (list, tuple)) and values:
        return values[0]
    return None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _text(value: Any) -> Any:
    """Upstream embeds HTML entities in plain fields.

    Measured on the real payload: `apply_url` for ADP/Workday boards is
    double-escaped (`...?cid=x&amp;ccId=y`), and industry strings contain
    `&amp;`. Passed through raw, the apply link is a broken URL.
    """
    return _html.unescape(value) if isinstance(value, str) else value


def _list(value: Any) -> list:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item) for item in value]


# Fields that would mark a paid/promoted placement. As of every captured payload
# no such field exists anywhere in the response -- see scripts/probe_sponsored.py,
# which scans both the SSR HTML and the JSON for sponsor/promote/featured
# vocabulary. In practice nothing is filtered today; these markers make the
# exclusion explicit and keep it working if upstream starts emitting a flag.
SPONSORED_MARKERS = (
    "is_sponsored",
    "sponsored",
    "is_promoted",
    "promoted",
    "is_featured",
)


def is_sponsored(hit: dict) -> bool:
    """True when a hit carries a sponsorship/promotion marker on either level."""
    for container in (hit, hit.get("job_information") or {}):
        if not isinstance(container, dict):
            continue
        for marker in SPONSORED_MARKERS:
            if container.get(marker):
                return True
    return False


def _posted_date(raw: Any) -> str | None:
    if isinstance(raw, str) and len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles."""
    radius = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def workplace_locations(data: dict, geolocs: Any) -> list[dict]:
    """Zip the parallel workplace lists into one entry per location.

    A posting like "Washington or New York City" carries two entries; keeping only
    the first is what makes a New York job look like a DC job.
    """
    cities = _list(data.get("workplace_cities"))
    states = _list(data.get("workplace_states"))
    counties = _list(data.get("workplace_counties"))
    countries = _list(data.get("workplace_countries"))
    geos = geolocs if isinstance(geolocs, list) else []

    locations = []
    for index in range(max(len(cities), len(states), len(countries), len(geos))):
        geo = geos[index] if index < len(geos) and isinstance(geos[index], dict) else {}
        locations.append(
            {
                "city": cities[index] if index < len(cities) else None,
                "county": counties[index] if index < len(counties) else None,
                "state": states[index] if index < len(states) else None,
                "country": countries[index] if index < len(countries) else None,
                "lat": _num(geo.get("lat")),
                "lon": _num(geo.get("lon")),
            }
        )
    return locations


def normalize_salary(job_data: dict) -> dict:
    period = job_data.get("listed_compensation_frequency")
    min_field, max_field = PERIOD_FIELDS.get(period, (None, None))

    if min_field:
        low = _num(job_data.get(min_field))
        high = _num(job_data.get(max_field))
    else:
        low = high = None
        for candidate_min, candidate_max in PERIOD_FIELDS.values():
            if _num(job_data.get(candidate_min)) is not None:
                min_field, max_field = candidate_min, candidate_max
                low = _num(job_data.get(candidate_min))
                high = _num(job_data.get(candidate_max))
                break

    return {
        "is_transparent": bool(job_data.get("is_compensation_transparent")),
        "currency": job_data.get("listed_compensation_currency"),
        "period": period,
        "min": low,
        "max": high,
        "annual_min": _num(job_data.get("yearly_min_compensation")),
        "annual_max": _num(job_data.get("yearly_max_compensation")),
        "hourly_min": _num(job_data.get("hourly_min_compensation")),
        "hourly_max": _num(job_data.get("hourly_max_compensation")),
    }


def normalize_job(
    hit: dict,
    *,
    center: dict | None = None,
    radius_miles: float | None = None,
) -> dict:
    job_info = hit.get("job_information") or {}
    data = hit.get("v5_processed_job_data") or {}
    geoloc = _first(hit.get("_geoloc")) or {}
    locations = workplace_locations(data, hit.get("_geoloc") or [])

    center_lat = _num((center or {}).get("lat"))
    center_lon = _num((center or {}).get("lon"))
    nearest: float | None = None
    if center_lat is not None and center_lon is not None:
        for entry in locations:
            if entry["lat"] is None or entry["lon"] is None:
                continue
            distance = haversine_miles(center_lat, center_lon, entry["lat"], entry["lon"])
            entry["distance_miles"] = round(distance, 1)
            if nearest is None or distance < nearest:
                nearest = distance

    if nearest is not None and radius_miles is not None:
        within_radius: bool | None = nearest <= radius_miles
    else:
        within_radius = None

    return {
        "id": hit.get("id"),
        "source": hit.get("source"),
        "source_and_board_token": hit.get("source_and_board_token"),
        "title": _text(job_info.get("title") or data.get("core_job_title")),
        "normalized_title": _text(data.get("core_job_title")),
        "company": _text(data.get("company_name")),
        "company_website": _text(data.get("company_website")),
        "company_industry": _text(data.get("company_sector_and_industry")),
        "apply_url": _text(hit.get("apply_url")),
        "location": {
            "formatted": _text(data.get("formatted_workplace_location")),
            "city": _text(_first(data.get("workplace_cities"))),
            "county": _text(_first(data.get("workplace_counties"))),
            "state": _text(_first(data.get("workplace_states"))),
            "country": _text(_first(data.get("workplace_countries"))),
            "lat": _num(geoloc.get("lat")),
            "lon": _num(geoloc.get("lon")),
        },
        # Every listed workplace, not just the first: "Washington or New York City"
        # is a local job whose primary entry points at DC.
        "locations": locations,
        "distance_miles": round(nearest, 1) if nearest is not None else None,
        "within_radius": within_radius,
        "workplace_type": data.get("workplace_type"),
        "seniority": data.get("seniority_level"),
        "job_category": data.get("job_category"),
        "employment_types": _list(data.get("commitment")),
        "years_experience": _int(data.get("min_industry_and_role_yoe")),
        "salary": normalize_salary(data),
        "posted_date": _posted_date(data.get("estimated_publish_date")),
        "posted_at": data.get("estimated_publish_date"),
        "posted_at_epoch_ms": _int(data.get("estimated_publish_date_millis")),
        "is_expired": bool(hit.get("is_expired")),
        "sponsored": is_sponsored(hit),
        "requirements_summary": _text(data.get("requirements_summary")),
        "technical_tools": _list(data.get("technical_tools")),
        "certifications": _list(data.get("licenses_or_certifications")),
        "education": {key: _text(data.get(field)) for key, field in DEGREE_KEYS},
        "benefits": {key: data.get(field) for key, field in BENEFIT_KEYS},
        "engagement": {
            "views": _int(job_info.get("num_views")) or 0,
            "applies": _int(job_info.get("num_applies")) or 0,
            "saves": _int(job_info.get("num_saves")) or 0,
        },
        "dedup_cluster_id": hit.get("strict_dedup_cluster_id"),
    }


def normalize_page(
    page_props: dict,
    *,
    query: str,
    location: dict,
    build_id: str,
    upstream_status: int,
    fetched_at: str,
    include_raw: bool = False,
    raw_payload: dict | None = None,
    cache_hit: bool = False,
    include_sponsored: bool = False,
    center: dict | None = None,
    radius: float | None = None,
    radius_unit: str | None = None,
    within_radius_only: bool = False,
) -> dict:
    hits = page_props.get("ssrHits") or []
    timings = page_props.get("ssrTimings") or {}

    if include_sponsored:
        kept, excluded = hits, 0
    else:
        kept = [hit for hit in hits if not is_sponsored(hit)]
        excluded = len(hits) - len(kept)

    if radius is None:
        radius_miles = None
    elif (radius_unit or "miles") == "miles":
        radius_miles = float(radius)
    else:
        radius_miles = float(radius) * 0.621371

    jobs = [normalize_job(hit, center=center, radius_miles=radius_miles) for hit in kept]

    out_of_radius = unknown_location = 0
    if within_radius_only:
        # A posting with no coordinates cannot be shown to be local, so it is not
        # treated as local -- but it is counted separately from a known-far job.
        local = [job for job in jobs if job["within_radius"] is True]
        out_of_radius = sum(1 for job in jobs if job["within_radius"] is False)
        unknown_location = sum(1 for job in jobs if job["within_radius"] is None)
        jobs = local

    response = {
        "meta": {
            "query": query,
            "location": location,
            "page": page_props.get("ssrPage", 0),
            "page_size": page_props.get("ssrPageSize"),
            # Upstream's own total; it does not know about our exclusions.
            "total_count": page_props.get("ssrTotalCount", len(hits)),
            # What this response actually carries.
            "returned_count": len(jobs),
            "excluded_sponsored": excluded,
            "excluded_out_of_radius": out_of_radius,
            "excluded_unknown_location": unknown_location,
            "search_center": center,
            "radius_miles": radius_miles,
            "company_count": page_props.get("ssrCompanyCount", 0),
            "is_last_page": bool(page_props.get("ssrIsLastPage")),
            "signed_in": bool(page_props.get("ssrSignedIn")),
            "es_latency_ms": timings.get("esLatencyMs"),
            "upstream_error": page_props.get("ssrError"),
            "build_id": build_id,
            "upstream_status": upstream_status,
            "fetched_at": fetched_at,
            "cache_hit": cache_hit,
        },
        "jobs": jobs,
    }

    if include_raw:
        response["raw"] = raw_payload if raw_payload is not None else {"pageProps": page_props}

    return response
