"""RailRoute routing engine — pure Python/pandas, no Streamlit.

Data model
----------
* ``journey_date`` in availability.csv is the date the *train run starts at its
  origin station* (the usual railway convention), not the date you board.
* A row in availability.csv is a bookable leg: one train, one run, one
  ``station_from -> station_to`` pair, one class.  ``fare`` is **per passenger**.
* ``day_offset`` in train_stops.csv is how many days after the run's start date the
  train reaches that stop.

The engine turns those rows into dated legs, then searches 1..N-leg journeys
(direct, same-train split tickets, and connections via any station).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_TIME = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

REQUIRED = {
    "stations": ["station_code", "station_name", "city", "state", "is_major_junction"],
    "trains": ["train_id", "train_number", "train_name", *DAYS],
    "stops": ["train_id", "station_code", "sequence", "arrival", "departure", "day_offset"],
    "availability": [
        "train_id", "journey_date", "station_from", "station_to",
        "class", "available_seats", "status", "fare",
    ],
}


class DataError(ValueError):
    """Raised when a CSV is missing required columns (cannot continue)."""


@dataclass(frozen=True)
class Leg:
    train_id: str
    train_number: str
    train_name: str
    from_code: str
    to_code: str
    run_date: date          # date the train run starts at its origin
    departure: datetime
    arrival: datetime
    cls: str
    seats: int
    status: str
    fare: float             # per passenger

    @property
    def duration_min(self) -> int:
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def run_key(self) -> tuple[str, date]:
        return (self.train_id, self.run_date)


@dataclass(frozen=True)
class Journey:
    legs: tuple[Leg, ...]

    @property
    def departure(self) -> datetime:
        return self.legs[0].departure

    @property
    def arrival(self) -> datetime:
        return self.legs[-1].arrival

    @property
    def duration_min(self) -> int:
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def transfers(self) -> int:
        return len(self.legs) - 1

    @property
    def fare_pp(self) -> float:
        return sum(l.fare for l in self.legs)

    @property
    def seats(self) -> int:
        return min(l.seats for l in self.legs)

    @property
    def layovers(self) -> list[int]:
        return [
            int((b.departure - a.arrival).total_seconds() // 60)
            for a, b in zip(self.legs, self.legs[1:])
        ]

    @property
    def stays_on_train(self) -> list[bool]:
        return [a.run_key == b.run_key for a, b in zip(self.legs, self.legs[1:])]

    @property
    def via(self) -> list[str]:
        return [l.to_code for l in self.legs[:-1]]

    @property
    def key(self) -> tuple:
        return tuple((l.train_id, l.run_date, l.from_code, l.to_code) for l in self.legs)


def fmt_minutes(m: int) -> str:
    return f"{m // 60}h {m % 60:02d}m"


def _to_dt(d: date, hhmm: str, offset: int) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m) + timedelta(days=int(offset))


class Timetable:
    """Validated timetable + availability, indexed for fast searching."""

    def __init__(self, stations, trains, stops, availability):
        self.warnings: list[str] = []
        self.stations = self._check(stations, "stations")
        self.trains = self._check(trains, "trains")
        self.stops = self._check(stops, "stops")
        self.availability = self._check(availability, "availability")
        self._station_names = dict(zip(self.stations.station_code, self.stations.station_name))
        self.legs: list[Leg] = self._build_legs()
        self.legs_from: dict[str, list[Leg]] = {}
        for leg in sorted(self.legs, key=lambda l: l.departure):
            self.legs_from.setdefault(leg.from_code, []).append(leg)

    # ------------------------------------------------------------------ io
    @classmethod
    def from_dir(cls, path) -> "Timetable":
        from pathlib import Path

        p = Path(path)
        read = lambda name: pd.read_csv(p / name, dtype=str, keep_default_na=False)
        return cls(read("stations.csv"), read("trains.csv"), read("train_stops.csv"), read("availability.csv"))

    # ---------------------------------------------------------- validation
    def _check(self, df: pd.DataFrame, name: str) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        missing = [c for c in REQUIRED[name] if c not in df.columns]
        if missing:
            raise DataError(f"{name} data is missing column(s): {', '.join(missing)}")
        for c in df.columns:
            df[c] = df[c].astype(str).str.strip()
        if name == "availability":  # 'class' is a Python keyword; use 'cls' internally
            df = df.rename(columns={"class": "cls"})
        return df

    def _warn(self, msg: str) -> None:
        if len(self.warnings) < 50:
            self.warnings.append(msg)

    def _build_legs(self) -> list[Leg]:
        known_st = set(self.stations.station_code)
        trains = {r.train_id: r for r in self.trains.itertuples(index=False)}
        if len(trains) != len(self.trains):
            self._warn("trains.csv has duplicate train_id values; the last one wins.")

        # ---- stops per train (validated, ordered)
        stops: dict[str, dict[str, dict]] = {}
        for tid, g in self.stops.groupby("train_id"):
            if tid not in trains:
                self._warn(f"train_stops.csv references unknown train {tid}; ignored.")
                continue
            rows = []
            for r in g.itertuples(index=False):
                if r.station_code not in known_st:
                    self._warn(f"{tid}: stop at unknown station {r.station_code}; ignored.")
                    continue
                if not (_TIME.match(r.arrival) and _TIME.match(r.departure)):
                    self._warn(f"{tid}@{r.station_code}: bad time format; stop ignored.")
                    continue
                try:
                    rows.append((int(r.sequence), r.station_code, r.arrival, r.departure, int(r.day_offset)))
                except ValueError:
                    self._warn(f"{tid}@{r.station_code}: sequence/day_offset must be integers; stop ignored.")
            rows.sort()
            seqs = [r[0] for r in rows]
            if len(set(seqs)) != len(seqs):
                self._warn(f"{tid}: duplicate stop sequence numbers; train ignored.")
                continue
            stops[tid] = {code: dict(seq=seq, arr=arr, dep=dep, off=off) for seq, code, arr, dep, off in rows}

        legs: list[Leg] = []
        seen: set[tuple] = set()
        for r in self.availability.itertuples(index=False):
            tag = f"availability {r.train_id} {r.station_from}->{r.station_to} {r.journey_date}"
            try:
                run = date.fromisoformat(r.journey_date)
                seats, fare = int(r.available_seats), float(r.fare)
            except ValueError:
                self._warn(f"{tag}: bad date/seats/fare; row ignored.")
                continue
            if seats < 0 or fare < 0:
                self._warn(f"{tag}: negative seats or fare; row ignored.")
                continue
            if r.train_id not in trains or r.train_id not in stops:
                self._warn(f"{tag}: unknown train; row ignored.")
                continue
            st = stops[r.train_id]
            a, b = st.get(r.station_from), st.get(r.station_to)
            if a is None or b is None or a["seq"] >= b["seq"]:
                self._warn(f"{tag}: stations are not in running order on this train; row ignored.")
                continue
            if getattr(trains[r.train_id], DAYS[run.weekday()]) != "1":
                self._warn(f"{tag}: train does not run on {DAYS[run.weekday()].title()}; row ignored.")
                continue
            dep = _to_dt(run, a["dep"], a["off"])
            arr = _to_dt(run, b["arr"], b["off"])
            if arr <= dep:  # e.g. arrival 00:10 recorded with the previous day's offset
                arr += timedelta(days=1)
                if arr <= dep:
                    self._warn(f"{tag}: arrival is not after departure; row ignored.")
                    continue
            leg = Leg(
                train_id=r.train_id,
                train_number=trains[r.train_id].train_number,
                train_name=trains[r.train_id].train_name,
                from_code=r.station_from,
                to_code=r.station_to,
                run_date=run,
                departure=dep,
                arrival=arr,
                cls=r.cls,
                seats=seats,
                status=r.status,
                fare=fare,
            )
            ident = (leg.train_id, leg.run_date, leg.from_code, leg.to_code, leg.cls)
            if ident in seen:
                self._warn(f"{tag}: duplicate availability row; first one kept.")
                continue
            seen.add(ident)
            legs.append(leg)
        return legs

    # ----------------------------------------------------------- helpers
    def name(self, code: str) -> str:
        return self._station_names.get(code, code)

    def label(self, code: str) -> str:
        return f"{self.name(code)} ({code})" if code in self._station_names else code

    @property
    def classes(self) -> list[str]:
        order = ["SL", "3E", "3A", "2A", "1A", "CC", "EC", "2S"]
        found = sorted({l.cls for l in self.legs}, key=lambda c: order.index(c) if c in order else 99)
        return found or ["3A"]

    @property
    def date_range(self) -> tuple[date, date] | None:
        if not self.legs:
            return None
        ds = [l.departure.date() for l in self.legs]
        return min(ds), max(ds)

    # ------------------------------------------------------------- search
    def search(
        self,
        src: str,
        dst: str,
        day: date,
        cls: str,
        passengers: int = 1,
        *,
        min_transfer: int = 60,
        max_layover_hours: float = 12,
        max_hours: float = 36,
        max_legs: int = 2,
        limit: int = 40,
        budget: int = 200_000,
    ) -> list[Journey]:
        """All feasible journeys departing ``src`` on ``day`` (calendar date).

        * ``min_transfer``: minutes needed to change trains (not enforced when you
          stay on the same train run, i.e. a split ticket).
        * ``max_layover_hours``: longest acceptable wait at an intermediate station.
        * ``max_legs``: 1 = direct only, 2 = one change, 3 = two changes.
        """
        if src == dst:
            raise ValueError("Origin and destination must be different.")
        max_legs = max(1, min(int(max_legs), 3))
        out: dict[tuple, Journey] = {}
        spent = 0

        def dfs(station: str, path: list[Leg], visited: set[str]) -> None:
            nonlocal spent
            for leg in self.legs_from.get(station, ()):
                spent += 1
                if spent > budget or len(out) >= limit * 5:
                    return
                if leg.cls != cls or leg.seats < passengers:
                    continue
                if not path:
                    if leg.departure.date() != day:
                        continue
                else:
                    prev = path[-1]
                    gap = int((leg.departure - prev.arrival).total_seconds() // 60)
                    if gap < 0:
                        continue
                    if gap > max_layover_hours * 60:
                        break  # legs_from is sorted by departure: nothing later fits either
                    same_run = leg.run_key == prev.run_key
                    if leg.train_id == prev.train_id and not same_run:
                        continue  # never "change" onto another run of the same train
                    if not same_run and gap < min_transfer:
                        continue
                if leg.to_code in visited:
                    continue
                first_dep = path[0].departure if path else leg.departure
                if (leg.arrival - first_dep).total_seconds() > max_hours * 3600:
                    continue
                new_path = path + [leg]
                if leg.to_code == dst:
                    j = Journey(tuple(new_path))
                    out[j.key] = j
                elif len(new_path) < max_legs:
                    dfs(leg.to_code, new_path, visited | {leg.to_code})

        dfs(src, [], {src})
        return rank(list(out.values()), "fastest")[:limit]


# ------------------------------------------------------------------ ranking
SORTS = {
    "fastest": lambda j: (j.duration_min, j.fare_pp, -j.seats),
    "cheapest": lambda j: (j.fare_pp, j.duration_min, -j.seats),
    "fewest changes": lambda j: (j.transfers, j.duration_min, j.fare_pp),
    "earliest arrival": lambda j: (j.arrival, j.duration_min, j.fare_pp),
    "most seats": lambda j: (-j.seats, j.duration_min, j.fare_pp),
}


def rank(journeys: Iterable[Journey], by: str = "fastest") -> list[Journey]:
    return sorted(journeys, key=SORTS[by])


def tags(journeys: list[Journey]) -> dict[tuple, list[str]]:
    """Badges like 'Fastest' / 'Cheapest' keyed by Journey.key."""
    result: dict[tuple, list[str]] = {j.key: [] for j in journeys}
    if len(journeys) < 2:
        return result
    for badge, fn in (("Fastest", SORTS["fastest"]), ("Cheapest", SORTS["cheapest"])):
        result[min(journeys, key=fn).key].append(badge)
    return result


def risk_notes(j: Journey, tight: int = 90) -> list[str]:
    """Human-readable cautions for a journey."""
    notes = []
    for i, (gap, same) in enumerate(zip(j.layovers, j.stays_on_train), 1):
        at = j.legs[i - 1].to_code
        if same:
            notes.append(f"Split ticket on the same train at {at}: your berth/seat may change.")
        elif gap < tight:
            notes.append(f"Tight {gap}-minute change at {at}: a delay can mean a missed connection.")
        elif gap >= 8 * 60:
            notes.append(f"Long {fmt_minutes(gap)} wait at {at}.")
    if j.seats <= 3:
        notes.append(f"Only {j.seats} seat(s) left on the scarcest leg.")
    if j.transfers and not all(j.stays_on_train):
        notes.append("Separate tickets are not protected if a delay causes a missed connection.")
    return notes
