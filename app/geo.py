"""Postal-code -> HiringCafe ``searchState.locations[]`` entry.

HiringCafe geocodes a US zip into this exact shape using GeoNames postal data,
so we rebuild it from the same source rather than inventing our own geometry.
The reproduction is verified field-for-field in tests/test_geo.py against a
captured upstream response.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT
from .errors import UnknownLocationError, ZipDatabaseMissingError

DEFAULT_ZIPDB = ROOT / "data" / "us_zips.db"

# GeoNames accuracy: 1=estimated, 4=geonameid, 6=centroid of addresses/shape.
# Highest accuracy wins; ties fall back to source file order (stable).
_SQL = """
SELECT postal_code, place_name, state_name, state_code, lat, lon
FROM zips
WHERE postal_code = ?
ORDER BY accuracy DESC, ordinal
LIMIT 1
"""


@dataclass(frozen=True, slots=True)
class Location:
    postal_code: str
    place_name: str
    state_name: str
    state_code: str
    lat: float
    lon: float
    radius: int = 50
    radius_unit: str = "miles"
    ignore_radius: bool = False
    country_code: str = "US"
    postal_code_source: str = "geonames"

    def to_search_state(self) -> dict:
        """Render the exact object HiringCafe puts in ``searchState.locations``."""
        return {
            "id": f"{self.country_code.lower()}-zip-{self.postal_code}",
            "postal_code": self.postal_code,
            "types": ["postal_code"],
            "formatted_address": f"{self.place_name}, {self.state_code}, {self.country_code}",
            "address_components": [
                {
                    "long_name": self.postal_code,
                    "short_name": self.postal_code,
                    "types": ["postal_code"],
                },
                {
                    "long_name": self.place_name,
                    "short_name": self.place_name,
                    "types": ["locality"],
                },
                {
                    "long_name": self.state_name,
                    "short_name": self.state_code,
                    "types": ["administrative_area_level_1"],
                },
                {"long_name": "United States", "short_name": "US", "types": ["country"]},
            ],
            "geometry": {"location": {"lat": self.lat, "lon": self.lon}},
            "postal_code_source": self.postal_code_source,
            "workplace_types": [],
            "options": {
                "radius": self.radius,
                "radius_unit": self.radius_unit,
                "ignore_radius": self.ignore_radius,
            },
        }


def resolve_us_zip(
    postal_code: str,
    *,
    radius: int = 50,
    radius_unit: str = "miles",
    ignore_radius: bool = False,
    zipdb_path: Path | str | None = None,
) -> Location:
    """Resolve a US postal code to a :class:`Location`, or raise 404.

    Two zips in the GeoNames dataset map to more than one place name; selection
    is deterministic (accuracy, then file order) but HiringCafe's tie-break for
    those two codes is unverified.
    """
    normalized = (postal_code or "").strip()
    path = Path(zipdb_path) if zipdb_path else DEFAULT_ZIPDB

    if not normalized:
        raise UnknownLocationError("postal_code must not be empty")
    if not path.is_file():
        raise ZipDatabaseMissingError(
            f"zip database not found at {path}; run: python scripts/build_zipdb.py"
        )

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute(_SQL, (normalized,)).fetchone()
    finally:
        conn.close()

    if row is None:
        raise UnknownLocationError(
            f"postal code {normalized!r} is not a known US postal code (GeoNames)",
            details={"postal_code": normalized},
        )

    code, place, state_name, state_code, lat, lon = row
    return Location(
        postal_code=code,
        place_name=place,
        state_name=state_name,
        state_code=state_code,
        lat=float(lat),
        lon=float(lon),
        radius=radius,
        radius_unit=radius_unit,
        ignore_radius=ignore_radius,
    )
