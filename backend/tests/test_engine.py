"""Run with:  python -m unittest discover -s tests   (or pytest)"""
import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import DataError, Timetable, rank, risk_notes, tags  # noqa: E402

D = date(2026, 10, 10)
ALL_DAYS = dict(mon=1, tue=1, wed=1, thu=1, fri=1, sat=1, sun=1)


def build(trains, stops, avail, stations=("A", "B", "C", "D")):
    st = pd.DataFrame(
        [dict(station_code=c, station_name=c, city=c, state="X", is_major_junction=1) for c in stations]
    )
    tr = pd.DataFrame([dict(train_id=t, train_number=t, train_name=t, **ALL_DAYS) for t in trains])
    sp = pd.DataFrame(
        [dict(train_id=t, station_code=s, sequence=q, arrival=a, departure=d, day_offset=o) for t, s, q, a, d, o in stops]
    )
    av = pd.DataFrame(
        [
            {"train_id": t, "journey_date": jd, "station_from": f, "station_to": to, "class": c,
             "available_seats": n, "status": "AVAILABLE", "fare": fare}
            for t, jd, f, to, c, n, fare in avail
        ]
    )
    return Timetable(st.astype(str), tr.astype(str), sp.astype(str), av.astype(str))


class SampleData(unittest.TestCase):
    def setUp(self):
        self.tt = Timetable.from_dir(Path(__file__).resolve().parents[1] / "data")

    def test_sample_data_is_clean(self):
        self.assertEqual(self.tt.warnings, [])
        self.assertEqual(len(self.tt.legs), 8)

    def test_vskp_pgt_uses_bengaluru_connection(self):
        js = self.tt.search("VSKP", "PGT", D, "3A", 1)
        self.assertEqual(len(js), 1)
        self.assertEqual(js[0].via, ["SBC"])
        self.assertEqual(js[0].layovers, [110])
        self.assertEqual(js[0].fare_pp, 1900)

    def test_no_day_long_wait_for_same_train(self):
        # T3 VSKP->MAS (10 Oct) + T3 MAS->PGT (next day's run) must not be offered.
        js = self.tt.search("VSKP", "PGT", D, "3A", 1, max_layover_hours=30, max_hours=72)
        self.assertTrue(all(j.via != ["MAS"] for j in js))

    def test_passenger_count_filters(self):
        self.assertEqual(self.tt.search("VSKP", "PGT", D, "3A", 16), [])  # SBC->PGT has 15

    def test_same_origin_destination(self):
        with self.assertRaises(ValueError):
            self.tt.search("VSKP", "VSKP", D, "3A")


class Routing(unittest.TestCase):
    def test_min_transfer_and_max_layover(self):
        tt = build(
            ["T1", "T2"],
            [("T1", "A", 1, "08:00", "08:00", 0), ("T1", "B", 2, "10:00", "10:10", 0),
             ("T2", "B", 1, "10:30", "10:40", 0), ("T2", "C", 2, "14:00", "14:00", 0)],
            [("T1", "2026-10-10", "A", "B", "3A", 5, 100), ("T2", "2026-10-10", "B", "C", "3A", 5, 100)],
        )
        self.assertEqual(tt.search("A", "C", D, "3A", min_transfer=15)[0].layovers, [40])
        self.assertEqual(tt.search("A", "C", D, "3A", min_transfer=60), [])
        self.assertEqual(tt.search("A", "C", D, "3A", min_transfer=15, max_layover_hours=0.5), [])

    def test_same_run_split_ticket_ignores_min_transfer(self):
        tt = build(
            ["T1"],
            [("T1", "A", 1, "08:00", "08:00", 0), ("T1", "B", 2, "10:00", "10:05", 0), ("T1", "C", 3, "12:00", "12:00", 0)],
            [("T1", "2026-10-10", "A", "B", "3A", 2, 100), ("T1", "2026-10-10", "B", "C", "3A", 2, 80)],
        )
        j = tt.search("A", "C", D, "3A", min_transfer=60)[0]
        self.assertEqual(j.stays_on_train, [True])
        self.assertTrue(any("same train" in n for n in risk_notes(j)))

    def test_two_changes_only_when_allowed(self):
        tt = build(
            ["T1", "T2", "T3"],
            [("T1", "A", 1, "06:00", "06:00", 0), ("T1", "B", 2, "08:00", "08:00", 0),
             ("T2", "B", 1, "09:30", "09:30", 0), ("T2", "C", 2, "11:00", "11:00", 0),
             ("T3", "C", 1, "12:30", "12:30", 0), ("T3", "D", 2, "15:00", "15:00", 0)],
            [("T1", "2026-10-10", "A", "B", "3A", 5, 50), ("T2", "2026-10-10", "B", "C", "3A", 5, 50),
             ("T3", "2026-10-10", "C", "D", "3A", 5, 50)],
        )
        self.assertEqual(tt.search("A", "D", D, "3A", max_legs=2), [])
        js = tt.search("A", "D", D, "3A", max_legs=3)
        self.assertEqual([j.via for j in js], [["B", "C"]])

    def test_boarding_after_midnight_run_date(self):
        # Run starts 9 Oct, reaches B on 10 Oct: searching 10 Oct must find it.
        tt = build(
            ["T1"],
            [("T1", "A", 1, "22:00", "22:00", 0), ("T1", "B", 2, "01:00", "01:10", 1), ("T1", "C", 3, "05:00", "05:00", 1)],
            [("T1", "2026-10-09", "B", "C", "3A", 4, 70)],
        )
        self.assertEqual(len(tt.search("B", "C", D, "3A")), 1)
        self.assertEqual(tt.search("B", "C", date(2026, 10, 9), "3A"), [])

    def test_ranking_and_tags(self):
        tt = build(
            ["T1", "T2"],
            [("T1", "A", 1, "06:00", "06:00", 0), ("T1", "B", 2, "12:00", "12:00", 0),
             ("T2", "A", 1, "07:00", "07:00", 0), ("T2", "B", 2, "10:00", "10:00", 0)],
            [("T1", "2026-10-10", "A", "B", "3A", 5, 100), ("T2", "2026-10-10", "A", "B", "3A", 5, 300)],
        )
        js = tt.search("A", "B", D, "3A")
        self.assertEqual(js[0].legs[0].train_id, "T2")  # fastest first
        self.assertEqual(rank(js, "cheapest")[0].legs[0].train_id, "T1")
        t = tags(js)
        self.assertIn("Fastest", t[js[0].key])
        self.assertIn("Cheapest", t[rank(js, "cheapest")[0].key])


class Validation(unittest.TestCase):
    def test_missing_column_raises(self):
        with self.assertRaises(DataError):
            Timetable(pd.DataFrame({"station_code": ["A"]}), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    def test_bad_rows_are_skipped_with_warnings(self):
        tt = build(
            ["T1"],
            [("T1", "A", 1, "08:00", "08:00", 0), ("T1", "B", 2, "10:00", "10:00", 0)],
            [("T1", "2026-10-10", "B", "A", "3A", 5, 100),      # wrong direction
             ("T1", "2026-10-10", "A", "B", "3A", -1, 100),     # negative seats
             ("T9", "2026-10-10", "A", "B", "3A", 5, 100),      # unknown train
             ("T1", "not-a-date", "A", "B", "3A", 5, 100)],
        )
        self.assertEqual(tt.legs, [])
        self.assertEqual(len(tt.warnings), 4)


if __name__ == "__main__":
    unittest.main()
