"""Documented response shapes.

These are TypedDicts, not pydantic response models, on purpose: the public
contract deliberately preserves ``null`` (e.g. an undisclosed salary) and omits
``raw`` entirely unless the caller asks for it, which a serialization model
would smooth over.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Salary(TypedDict):
    is_transparent: bool
    currency: str | None
    period: str | None
    min: float | None
    max: float | None
    annual_min: float | None
    annual_max: float | None
    hourly_min: float | None
    hourly_max: float | None


class JobLocation(TypedDict):
    formatted: str | None
    city: str | None
    county: str | None
    state: str | None
    country: str | None
    lat: float | None
    lon: float | None


class WorkplaceLocation(TypedDict, total=False):
    city: str | None
    county: str | None
    state: str | None
    country: str | None
    lat: float | None
    lon: float | None
    distance_miles: float


class Education(TypedDict):
    associates: str | None
    bachelors: str | None
    masters: str | None
    doctorate: str | None


# Functional syntax because "401k_matching" is not a valid Python identifier.
Benefits = TypedDict(
    "Benefits",
    {
        "retirement_plan": bool | None,
        "401k_matching": bool | None,
        "visa_sponsorship": bool | None,
        "tuition_reimbursement": bool | None,
        "relocation_assistance": bool | None,
        "paid_time_off": bool | None,
        "parental_leave": bool | None,
        "four_day_work_week": bool | None,
        "overtime_required": bool | None,
    },
)


class Engagement(TypedDict):
    views: int
    applies: int
    saves: int


class Job(TypedDict):
    id: str
    source: str | None
    source_and_board_token: str | None
    title: str | None
    normalized_title: str | None
    company: str | None
    company_website: str | None
    company_industry: str | None
    apply_url: str | None
    location: JobLocation
    locations: list[WorkplaceLocation]
    distance_miles: float | None
    within_radius: bool | None
    workplace_type: str | None
    seniority: str | None
    job_category: str | None
    employment_types: list[str]
    years_experience: int | None
    salary: Salary
    posted_date: str | None
    posted_at: str | None
    posted_at_epoch_ms: int | None
    is_expired: bool
    sponsored: bool
    requirements_summary: str | None
    technical_tools: list[str]
    certifications: list[str]
    education: Education
    benefits: Benefits
    engagement: Engagement
    dedup_cluster_id: str | None


class Meta(TypedDict):
    query: str
    location: dict
    page: int
    page_size: int | None
    total_count: int
    returned_count: int
    excluded_sponsored: int
    excluded_out_of_radius: int
    excluded_unknown_location: int
    search_center: dict | None
    radius_miles: float | None
    company_count: int
    is_last_page: bool
    signed_in: bool
    es_latency_ms: int | None
    upstream_error: str | None
    build_id: str
    upstream_status: int
    fetched_at: str
    cache_hit: bool


class SearchResponse(TypedDict, total=False):
    meta: Meta
    jobs: list[Job]
    raw: dict[str, Any]
