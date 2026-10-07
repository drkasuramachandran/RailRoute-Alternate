from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from engine import SORTS, DataError, Timetable, fmt_minutes, rank, risk_notes, tags

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

app = FastAPI(title="RailRoute Alternate API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    timetable = Timetable.from_dir(DATA_DIR)
except (DataError, FileNotFoundError) as exc:
    raise RuntimeError(f"Could not load railway data: {exc}") from exc


def leg_dict(leg) -> dict[str, Any]:
    return {
        "trainId": leg.train_id,
        "trainNumber": leg.train_number,
        "trainName": leg.train_name,
        "fromCode": leg.from_code,
        "fromName": timetable.name(leg.from_code),
        "toCode": leg.to_code,
        "toName": timetable.name(leg.to_code),
        "runDate": leg.run_date.isoformat(),
        "departure": leg.departure.isoformat(),
        "arrival": leg.arrival.isoformat(),
        "class": leg.cls,
        "seats": leg.seats,
        "status": leg.status,
        "fare": leg.fare,
    }


def journey_dict(j, pax: int, badge_list: list[str]) -> dict[str, Any]:
    return {
        "key": str(j.key),
        "route": " → ".join([timetable.name(j.legs[0].from_code), *map(timetable.name, j.via), timetable.name(j.legs[-1].to_code)]),
        "departure": j.departure.isoformat(),
        "arrival": j.arrival.isoformat(),
        "durationMinutes": j.duration_min,
        "duration": fmt_minutes(j.duration_min),
        "transfers": j.transfers,
        "farePerPerson": j.fare_pp,
        "totalFare": j.fare_pp * pax,
        "seats": j.seats,
        "via": [{"code": code, "name": timetable.name(code)} for code in j.via],
        "legs": [leg_dict(leg) for leg in j.legs],
        "layovers": j.layovers,
        "staysOnTrain": j.stays_on_train,
        "badges": badge_list,
        "riskNotes": risk_notes(j),
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "railroute-api"}


@app.get("/api/meta")
def meta():
    dr = timetable.date_range
    return {
        "stations": [
            {
                "code": row.station_code,
                "name": row.station_name,
                "city": row.city,
                "state": row.state,
                "majorJunction": str(row.is_major_junction) == "1",
            }
            for row in timetable.stations.itertuples(index=False)
        ],
        "classes": timetable.classes,
        "dateRange": {"from": dr[0].isoformat(), "to": dr[1].isoformat()} if dr else None,
        "warnings": timetable.warnings,
        "sorts": list(SORTS.keys()),
    }


@app.get("/api/search")
def search(
    src: str,
    dst: str,
    day: date,
    cls: str = Query("3A"),
    passengers: int = Query(1, ge=1, le=6),
    connections: int = Query(2, ge=1, le=3),
    min_transfer: int = Query(60, ge=15, le=180),
    max_layover_hours: float = Query(12, ge=1, le=48),
    max_hours: float = Query(36, ge=6, le=72),
    sort_by: str = Query("fastest"),
    always_alt: bool = False,
):
    if src == dst:
        raise HTTPException(400, "Origin and destination must be different.")
    if sort_by not in SORTS:
        raise HTTPException(400, f"Unknown sort option: {sort_by}")
    if src not in set(timetable.stations.station_code) or dst not in set(timetable.stations.station_code):
        raise HTTPException(400, "Unknown station code.")

    found = timetable.search(
        src, dst, day, cls, passengers,
        min_transfer=min_transfer,
        max_layover_hours=max_layover_hours,
        max_hours=max_hours,
        max_legs=connections,
    )
    direct = rank([j for j in found if j.transfers == 0], sort_by)
    alts = rank([j for j in found if j.transfers > 0], sort_by)
    badge_map = tags(found)
    show_alts = (not direct) or always_alt

    return {
        "query": {
            "src": src, "dst": dst, "day": day.isoformat(), "class": cls,
            "passengers": passengers, "connections": connections,
            "minTransfer": min_transfer, "maxLayoverHours": max_layover_hours,
            "maxHours": max_hours, "sortBy": sort_by, "alwaysAlt": always_alt,
        },
        "origin": timetable.label(src),
        "destination": timetable.label(dst),
        "direct": [journey_dict(j, passengers, badge_map[j.key]) for j in direct],
        "alternatives": [journey_dict(j, passengers, badge_map[j.key]) for j in alts] if show_alts and connections > 1 else [],
        "foundCount": len(found),
        "dateInRange": not timetable.date_range or timetable.date_range[0] <= day <= timetable.date_range[1],
        "dateRange": {"from": timetable.date_range[0].isoformat(), "to": timetable.date_range[1].isoformat()} if timetable.date_range else None,
    }


@app.get("/api/export.csv")
def export_csv(
    src: str, dst: str, day: date, cls: str = "3A", passengers: int = 1,
    connections: int = 2, min_transfer: int = 60, max_layover_hours: float = 12,
    max_hours: float = 36, sort_by: str = "fastest",
):
    if sort_by not in SORTS:
        raise HTTPException(400, "Unknown sort option.")
    found = timetable.search(src, dst, day, cls, passengers, min_transfer=min_transfer,
                             max_layover_hours=max_layover_hours, max_hours=max_hours,
                             max_legs=connections)
    import pandas as pd
    rows = []
    for j in rank(found, sort_by):
        rows.append({
            "route": " → ".join([timetable.name(j.legs[0].from_code), *map(timetable.name, j.via), timetable.name(j.legs[-1].to_code)]),
            "trains": " + ".join(l.train_number for l in j.legs),
            "departure": j.departure.strftime("%d %b %H:%M"),
            "arrival": j.arrival.strftime("%d %b %H:%M"),
            "duration": fmt_minutes(j.duration_min),
            "changes": j.transfers,
            "fare_per_person": j.fare_pp,
            f"total_fare_{passengers}_pax": j.fare_pp * passengers,
            "min_seats": j.seats,
        })
    csv = pd.DataFrame(rows).to_csv(index=False)
    filename = f"railroute_{src}_{dst}_{day.isoformat()}.csv"
    return Response(content=csv, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
