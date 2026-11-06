"""Build data/us_zips.db from the GeoNames US postal-code dump.

GeoNames data is CC-BY 4.0 -- see data/geonames/readme.txt.
Source: https://download.geonames.org/export/zip/US.zip

Usage:
    python scripts/build_zipdb.py [--src data/geonames/US.txt] [--out data/us_zips.db]
"""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "data" / "geonames" / "US.txt"
DEFAULT_OUT = ROOT / "data" / "us_zips.db"

SCHEMA = """
DROP TABLE IF EXISTS zips;
CREATE TABLE zips (
    postal_code TEXT NOT NULL,
    place_name  TEXT,
    state_name  TEXT,
    state_code  TEXT,
    county      TEXT,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    accuracy    INTEGER,
    ordinal     INTEGER NOT NULL
);
CREATE INDEX idx_zips_postal_code ON zips(postal_code);
"""

# GeoNames accuracy: 1=estimated, 4=geonameid, 6=centroid of addresses/shape.
# Higher is more precise, so selection orders by accuracy DESC then file order.


def parse_row(line: str) -> tuple | None:
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 12:
        return None
    _country, postal, place, admin1, code1, admin2 = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
    lat_s, lon_s, acc_s = parts[9], parts[10], parts[11]
    if not postal or not lat_s or not lon_s:
        return None
    try:
        lat, lon = float(lat_s), float(lon_s)
    except ValueError:
        return None
    try:
        accuracy = int(acc_s) if acc_s else None
    except ValueError:
        accuracy = None
    return (postal, place, admin1, code1, admin2, lat, lon, accuracy)


def build(src: pathlib.Path, out: pathlib.Path) -> tuple[int, int]:
    if not src.is_file():
        raise SystemExit(f"source dump not found: {src}\nDownload US.zip from "
                         f"https://download.geonames.org/export/zip/ and extract US.txt into data/geonames/")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    total = inserted = 0
    conn = sqlite3.connect(out)
    try:
        conn.executescript(SCHEMA)
        with src.open("r", encoding="utf-8", newline="") as fh:
            for ordinal, line in enumerate(fh):
                total += 1
                row = parse_row(line)
                if row is None:
                    continue
                conn.execute(
                    "INSERT INTO zips (postal_code, place_name, state_name, state_code,"
                    " county, lat, lon, accuracy, ordinal) VALUES (?,?,?,?,?,?,?,?,?)",
                    (*row, ordinal),
                )
                inserted += 1
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return total, inserted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=pathlib.Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    total, inserted = build(args.src, args.out)
    size_mb = args.out.stat().st_size / (1024 * 1024)
    print(f"read {total} lines, inserted {inserted} rows -> {args.out} ({size_mb:.2f} MB)")

    conn = sqlite3.connect(args.out)
    try:
        row = conn.execute(
            "SELECT postal_code, place_name, state_code, lat, lon, accuracy FROM zips"
            " WHERE postal_code = '83702' ORDER BY accuracy DESC, ordinal LIMIT 1"
        ).fetchone()
        print("sanity check 83702:", row)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
