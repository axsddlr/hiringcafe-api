# Third-party data attribution

## GeoNames

`data/us_zips.db` is derived from the GeoNames postal-code dataset
(<https://download.geonames.org/export/zip/US.zip>, file `US.txt`), retrieved on
2026-11-06 and rebuilt by `scripts/build_zipdb.py`.

That dataset is licensed **Creative Commons Attribution 4.0 (CC BY 4.0)** —
<https://creativecommons.org/licenses/by/4.0/>. See
<https://www.geonames.org/> for the project.

Only the columns needed to rebuild HiringCafe's `searchState.locations[]` object
were retained: postal code, place name, state name/code, county, latitude,
longitude, and accuracy, plus the original row order. No GeoNames content is
modified; rows are copied and re-keyed into SQLite.

`data/geonames/US.txt` is deliberately **not** committed (2.6 MB raw dump) —
`scripts/build_zipdb.py` fetches and rebuilds it on demand.

## Job data

Everything under `tests/fixtures/` and `verification/` is a captured response
from hiringcafe.com, used as test ground truth and evidence. It is included for
reproducibility, not as a dataset you may redistribute. User-identifying arrays
(`viewedByUsers`, `appliedFromUsers`, `savedFromUsers`, `hiddenFromUsers`) were
stripped from the fixture by `scripts/redact_fixture.py`.
