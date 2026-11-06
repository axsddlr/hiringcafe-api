"""Normalization contract: upstream pageProps -> stable public JSON.

Assertions either pin values that the captured fixture actually contains, or use
predicates over the job list, so the suite does not silently encode one sample's
quirks (e.g. "there happens to be a Remote job at index 18").
"""

import json

import pytest

from app.normalize import normalize_job, normalize_page

FETCHED_AT = "2026-11-06T07:10:00+00:00"


def build(page_props, upstream_search_state, *, include_raw=False, raw_payload=None,
          include_sponsored=False):
    return normalize_page(
        page_props,
        query="data analyst",
        location=upstream_search_state["locations"][0],
        build_id="TESTBUILDID",
        upstream_status=200,
        fetched_at=FETCHED_AT,
        include_raw=include_raw,
        raw_payload=raw_payload,
        include_sponsored=include_sponsored,
    )


def with_sponsored(page_props, *, marker="is_sponsored", where="job_information"):
    """Deep-copy the payload and flag the first hit as a paid placement."""
    import copy

    page_props = copy.deepcopy(page_props)
    hit = page_props["ssrHits"][0]
    (hit["job_information"] if where == "job_information" else hit)[marker] = True
    return page_props


def find(jobs, predicate):
    for job in jobs:
        if predicate(job):
            return job
    raise AssertionError("no job matched the predicate")


def test_meta_counts(page_props, upstream_search_state):
    meta = build(page_props, upstream_search_state)["meta"]
    assert meta["query"] == "data analyst"
    assert meta["page"] == 0
    assert meta["page_size"] == 40
    assert meta["total_count"] == 38
    assert meta["company_count"] == 21
    assert meta["is_last_page"] is True
    assert meta["signed_in"] is False
    assert meta["es_latency_ms"] == 242
    assert meta["build_id"] == "TESTBUILDID"
    assert meta["upstream_status"] == 200
    assert meta["fetched_at"] == FETCHED_AT


def test_meta_echoes_resolved_location(page_props, upstream_search_state):
    out = build(page_props, upstream_search_state)
    assert out["meta"]["location"] == upstream_search_state["locations"][0]


def test_all_jobs_returned(page_props, upstream_search_state):
    out = build(page_props, upstream_search_state)
    assert len(out["jobs"]) == 38
    assert len({j["id"] for j in out["jobs"]}) == 38  # no duplicate ids


def test_first_job_exact_extraction(page_props, upstream_search_state):
    job = build(page_props, upstream_search_state)["jobs"][0]
    assert job["id"] == (
        "workday___clearwateranalytics-wd1-clearwater_analytics_careers___financial-data-analyst_r12478"
    )
    assert job["source"] == "workday"
    assert job["title"] == "Financial Data Analyst"
    assert job["company"] == "Clearwater Analytics"
    assert job["company_industry"] == "Information Technology"
    assert job["workplace_type"] == "Onsite"
    assert job["seniority"] == "Entry Level"
    assert job["job_category"] == "Data and Analytics"
    assert job["employment_types"] == ["Full Time"]
    assert job["years_experience"] is None
    assert job["location"]["formatted"] == "Boise, Idaho, United States"
    assert job["location"]["state"] == "Idaho, US"
    assert job["location"]["country"] == "US"
    assert job["location"]["lat"] == pytest.approx(43.615)
    assert job["location"]["lon"] == pytest.approx(-116.2023)
    assert job["posted_date"] == "2026-10-22"
    assert job["is_expired"] is False
    assert job["technical_tools"] == ["Microsoft Excel", "SQL", "Microsoft Office"]
    assert job["education"]["associates"] == "Not Mentioned"
    assert job["education"]["bachelors"] == "Required"
    assert job["engagement"] == {"views": 75, "applies": 19, "saves": 2}
    assert job["apply_url"].startswith("https://clearwateranalytics.wd1.myworkdayjobs.com/")


def test_undisclosed_salary_is_explicit(page_props, upstream_search_state):
    job = build(page_props, upstream_search_state)["jobs"][0]
    salary = job["salary"]
    assert salary["is_transparent"] is False
    assert salary["min"] is None
    assert salary["max"] is None
    assert salary["period"] == "Yearly"
    assert salary["currency"] == "USD"


def test_hourly_salary_is_preserved_and_annualized(page_props, upstream_search_state):
    jobs = build(page_props, upstream_search_state)["jobs"]
    job = find(jobs, lambda j: j["company"] == "Idaho Legislative Services Office")

    salary = job["salary"]
    assert salary["is_transparent"] is True
    assert salary["period"] == "Hourly"
    assert salary["min"] == pytest.approx(31.25)
    assert salary["max"] == pytest.approx(33.65)
    assert salary["annual_min"] == pytest.approx(65000)
    assert salary["annual_max"] == pytest.approx(69992)


def test_some_jobs_do_disclose_pay(page_props, upstream_search_state):
    jobs = build(page_props, upstream_search_state)["jobs"]
    disclosed = [j for j in jobs if j["salary"]["is_transparent"]]
    assert len(disclosed) == 15
    for job in disclosed:
        assert job["salary"]["min"] is not None


def test_non_standard_workplace_type_is_passed_through(page_props, upstream_search_state):
    """Upstream emits Onsite/Hybrid and occasionally 'Field'; unknown values must survive verbatim."""
    jobs = build(page_props, upstream_search_state)["jobs"]
    assert {j["workplace_type"] for j in jobs} == {"Onsite", "Hybrid", "Field"}
    field = find(jobs, lambda j: j["workplace_type"] == "Field")
    assert field["company"] == "Mass. Electric Construction Co."


def test_nullable_years_of_experience(page_props, upstream_search_state):
    jobs = build(page_props, upstream_search_state)["jobs"]
    assert sum(1 for j in jobs if j["years_experience"] is None) == 10
    assert any(isinstance(j["years_experience"], int) for j in jobs)


def test_missing_saves_counter_normalizes_to_zero(page_props, upstream_search_state):
    """Upstream omits num_saves on some hits; it must not surface as null."""
    jobs = build(page_props, upstream_search_state)["jobs"]
    job = find(jobs, lambda j: "sr-technical-data-analyst" in j["id"])
    assert job["engagement"]["saves"] == 0
    assert job["engagement"]["views"] == 9


def test_benefits_are_surfaced(page_props, upstream_search_state):
    job = build(page_props, upstream_search_state)["jobs"][0]
    benefits = job["benefits"]
    assert benefits["retirement_plan"] is False
    assert benefits["401k_matching"] is False
    assert benefits["visa_sponsorship"] is False
    assert set(benefits) == {
        "retirement_plan",
        "401k_matching",
        "visa_sponsorship",
        "tuition_reimbursement",
        "relocation_assistance",
        "paid_time_off",
        "parental_leave",
        "four_day_work_week",
        "overtime_required",
    }


def test_certifications_list(page_props, upstream_search_state):
    jobs = build(page_props, upstream_search_state)["jobs"]
    job = find(jobs, lambda j: j["title"] == "Quantitative Financial Analyst I")
    assert job["certifications"] == ["cfa", "frm", "cqf"]


def test_raw_payload_opted_out_by_default(page_props, upstream_search_state):
    assert "raw" not in build(page_props, upstream_search_state)


def test_raw_payload_opted_in(page_props, upstream_search_state):
    out = build(
        page_props,
        upstream_search_state,
        include_raw=True,
        raw_payload={"pageProps": page_props, "__N_SSP": True},
    )
    assert out["raw"]["__N_SSP"] is True
    assert len(out["raw"]["pageProps"]["ssrHits"]) == 38


def test_empty_result_set_is_handled(upstream_search_state):
    page_props = {
        "ssrHits": [],
        "ssrPage": 0,
        "ssrTotalCount": 0,
        "ssrCompanyCount": 0,
        "ssrPageSize": 40,
        "ssrIsLastPage": True,
        "ssrError": None,
        "ssrTimings": {"esLatencyMs": 12},
        "ssrSignedIn": False,
    }
    out = build(page_props, upstream_search_state)
    assert out["jobs"] == []
    assert out["meta"]["total_count"] == 0


def test_upstream_error_surfaces(page_props, upstream_search_state):
    page_props = dict(page_props, ssrError="upstream timeout")
    out = build(page_props, upstream_search_state)
    assert out["meta"]["upstream_error"] == "upstream timeout"


def test_every_job_carries_a_category(page_props, upstream_search_state):
    """job_category is upstream's own classification and is always populated here.

    Without it, keyword search returns business/sales noise: a "network specialist"
    query matches provider-network and media-relations roles.
    """
    jobs = build(page_props, upstream_search_state)["jobs"]
    assert all(job["job_category"] for job in jobs)
    assert {j["job_category"] for j in jobs} >= {"Data and Analytics", "Finance and Accounting"}


def test_no_html_entities_survive_anywhere(page_props, upstream_search_state):
    out = build(page_props, upstream_search_state)
    assert "&amp;" not in json.dumps(out)


def test_captured_search_contains_no_sponsored_posts(page_props, upstream_search_state):
    """Measured fact: the real payload carries no placement markers at all."""
    meta = build(page_props, upstream_search_state)["meta"]
    assert meta["excluded_sponsored"] == 0
    assert meta["returned_count"] == 38
    assert meta["total_count"] == 38


def test_sponsored_hits_are_excluded_by_default(page_props, upstream_search_state):
    out = build(with_sponsored(page_props), upstream_search_state)

    assert len(out["jobs"]) == 37
    assert out["meta"]["excluded_sponsored"] == 1
    assert out["meta"]["returned_count"] == 37
    # upstream's total is reported as-is, not rewritten to match our filter
    assert out["meta"]["total_count"] == 38
    assert all(job["sponsored"] is False for job in out["jobs"])


def test_sponsored_hits_can_be_included_explicitly(page_props, upstream_search_state):
    out = build(with_sponsored(page_props), upstream_search_state, include_sponsored=True)

    assert len(out["jobs"]) == 38
    assert out["meta"]["excluded_sponsored"] == 0
    assert out["jobs"][0]["sponsored"] is True


@pytest.mark.parametrize(
    "marker,where",
    [
        ("is_sponsored", "job_information"),
        ("sponsored", "job_information"),
        ("is_promoted", "top"),
        ("promoted", "top"),
        ("is_featured", "top"),
    ],
)
def test_every_known_marker_triggers_exclusion(page_props, upstream_search_state, marker, where):
    out = build(with_sponsored(page_props, marker=marker, where=where), upstream_search_state)
    assert out["meta"]["excluded_sponsored"] == 1


def test_falsey_marker_does_not_exclude(page_props, upstream_search_state):
    page_props = with_sponsored(page_props, marker="is_sponsored")
    page_props["ssrHits"][0]["job_information"]["is_sponsored"] = False
    out = build(page_props, upstream_search_state)
    assert out["meta"]["excluded_sponsored"] == 0
    assert len(out["jobs"]) == 38


def test_pay_falls_back_to_the_period_that_has_numbers():
    """Upstream sometimes omits listed_compensation_frequency but still sends amounts."""
    job = normalize_job(
        {
            "id": "synthetic",
            "v5_processed_job_data": {
                "monthly_min_compensation": 5000,
                "monthly_max_compensation": 6000,
            },
        }
    )
    assert job["salary"]["period"] is None
    assert job["salary"]["min"] == 5000.0
    assert job["salary"]["max"] == 6000.0


def test_non_numeric_compensation_is_treated_as_missing():
    job = normalize_job(
        {
            "id": "synthetic",
            "v5_processed_job_data": {
                "listed_compensation_frequency": "Yearly",
                "yearly_min_compensation": "n/a",
                "yearly_max_compensation": None,
                "is_compensation_transparent": True,
            },
        }
    )
    assert job["salary"]["min"] is None
    assert job["salary"]["max"] is None


def test_html_entities_are_unescaped_in_text_fields():
    """Synthetic: upstream really does double-escape some ATS links and industry strings."""
    job = normalize_job(
        {
            "id": "synthetic",
            "source": "adp",
            "apply_url": "https://example.test/job?cid=abc&amp;ccId=19000101&amp;jobId=9",
            "job_information": {"title": "R&amp;D Analyst", "num_views": 1},
            "v5_processed_job_data": {
                "company_name": "Smith &amp; Sons",
                "company_sector_and_industry": "Oil &amp; Gas",
                "requirements_summary": "SQL &amp; Excel",
                "technical_tools": ["C&amp;C"],
                "listed_compensation_frequency": "Yearly",
            },
        }
    )
    assert job["apply_url"] == "https://example.test/job?cid=abc&ccId=19000101&jobId=9"
    assert job["title"] == "R&D Analyst"
    assert job["company"] == "Smith & Sons"
    assert job["company_industry"] == "Oil & Gas"
    assert job["requirements_summary"] == "SQL & Excel"
    assert job["technical_tools"] == ["C&C"]
