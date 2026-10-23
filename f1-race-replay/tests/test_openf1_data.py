"""Tests for the OpenF1 replay backend's data derivation.

These cover the parts that interpret F1's message wording and stint bookkeeping,
where the API's shape is not self-evident; network calls are not exercised.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src import openf1_data

ORIGIN = datetime(2026, 3, 8, 4, 0, 0, tzinfo=timezone.utc)


def at(seconds):
    """An OpenF1-style ISO timestamp `seconds` after the test origin."""
    return (ORIGIN + timedelta(seconds=seconds)).isoformat()


def rc(seconds, category="Flag", message="", flag=None):
    return {"date": at(seconds), "category": category, "message": message, "flag": flag}


class TestDeriveTrackStatuses:
    def test_vsc_is_detected_from_the_abbreviation(self):
        """OpenF1 writes 'VSC DEPLOYED', not 'VIRTUAL SAFETY CAR'."""
        out = openf1_data._derive_track_statuses(
            [rc(10, "SafetyCar", "VSC DEPLOYED"),
             rc(60, "SafetyCar", "VSC ENDING")],
            ORIGIN,
        )
        assert [s["status"] for s in out] == ["6", "1"]
        assert [s["time_s"] for s in out] == [10.0, 60.0]

    def test_full_safety_car(self):
        out = openf1_data._derive_track_statuses(
            [rc(10, "SafetyCar", "SAFETY CAR DEPLOYED"),
             rc(90, "SafetyCar", "SAFETY CAR IN THIS LAP")],
            ORIGIN,
        )
        assert [s["status"] for s in out] == ["4", "1"]

    def test_sector_clear_does_not_cancel_a_vsc(self):
        out = openf1_data._derive_track_statuses(
            [rc(10, "SafetyCar", "VSC DEPLOYED"),
             rc(20, "Flag", "CLEAR IN TRACK SECTOR 13", "CLEAR"),
             rc(30, "SafetyCar", "VSC ENDING")],
            ORIGIN,
        )
        # still under VSC at t=20, only clearing when the VSC ends
        assert [s["status"] for s in out] == ["6", "1"]
        assert out[1]["time_s"] == 30.0

    def test_blue_flags_are_ignored(self):
        out = openf1_data._derive_track_statuses(
            [rc(10, "Flag", "WAVED BLUE FLAG FOR CAR 77 (BOT)", "BLUE"),
             rc(20, "Flag", "WAVED BLUE FLAG FOR CAR 18 (STR)", "BLUE")],
            ORIGIN,
        )
        assert out == []

    def test_red_flag_outranks_safety_car(self):
        out = openf1_data._derive_track_statuses(
            [rc(10, "SafetyCar", "SAFETY CAR DEPLOYED"),
             rc(20, "Flag", "RED FLAG", "RED")],
            ORIGIN,
        )
        assert [s["status"] for s in out] == ["4", "5"]

    def test_yellow_then_clear(self):
        out = openf1_data._derive_track_statuses(
            [rc(10, "Flag", "YELLOW IN TRACK SECTOR 7", "YELLOW"),
             rc(20, "Flag", "DOUBLE YELLOW IN TRACK SECTOR 7", "DOUBLE YELLOW"),
             rc(30, "Flag", "CLEAR IN TRACK SECTOR 7", "CLEAR")],
            ORIGIN,
        )
        # the second yellow is not a state change, so it is not re-emitted
        assert [s["status"] for s in out] == ["2", "1"]

    def test_collapses_repeated_states(self):
        out = openf1_data._derive_track_statuses(
            [rc(10, "Flag", "CLEAR", "CLEAR"),
             rc(20, "Flag", "CLEAR", "CLEAR"),
             rc(30, "Flag", "CLEAR", "CLEAR")],
            ORIGIN,
        )
        assert len(out) == 1

    def test_out_of_order_messages_are_sorted(self):
        out = openf1_data._derive_track_statuses(
            [rc(50, "SafetyCar", "VSC ENDING"),
             rc(10, "SafetyCar", "VSC DEPLOYED")],
            ORIGIN,
        )
        assert [s["status"] for s in out] == ["6", "1"]

    def test_messages_without_dates_are_skipped(self):
        out = openf1_data._derive_track_statuses(
            [{"date": None, "category": "Flag", "message": "x", "flag": "RED"}],
            ORIGIN,
        )
        assert out == []

    def test_empty_input(self):
        assert openf1_data._derive_track_statuses([], ORIGIN) == []


class TestStintLookup:
    def test_fresh_tyre_reads_one_on_its_first_lap(self):
        """FastF1's TyreLife counts the lap being driven."""
        lookup = openf1_data._stint_lookup(
            [{"lap_start": 28, "lap_end": 58, "compound": "HARD",
              "tyre_age_at_start": 0}]
        )
        compound, life = lookup(28)
        assert compound == 2          # HARD
        assert life == 1

    def test_life_accumulates_through_the_stint(self):
        lookup = openf1_data._stint_lookup(
            [{"lap_start": 1, "lap_end": 27, "compound": "MEDIUM",
              "tyre_age_at_start": 0}]
        )
        assert lookup(1)[1] == 1
        assert lookup(27)[1] == 27

    def test_used_set_starts_from_its_existing_age(self):
        lookup = openf1_data._stint_lookup(
            [{"lap_start": 10, "lap_end": 20, "compound": "SOFT",
              "tyre_age_at_start": 5}]
        )
        assert lookup(10)[1] == 6

    def test_unknown_compound_maps_to_minus_one(self):
        """OpenF1 reports compound: null for some stints."""
        lookup = openf1_data._stint_lookup(
            [{"lap_start": 1, "lap_end": 10, "compound": None,
              "tyre_age_at_start": 0}]
        )
        assert lookup(5)[0] == -1

    def test_lap_outside_every_stint(self):
        lookup = openf1_data._stint_lookup(
            [{"lap_start": 1, "lap_end": 10, "compound": "SOFT",
              "tyre_age_at_start": 0}]
        )
        assert lookup(50) == (-1, 0)

    def test_malformed_stints_are_skipped(self):
        lookup = openf1_data._stint_lookup(
            [{"compound": "SOFT"},                     # no lap bounds
             {"lap_start": None, "lap_end": 5, "compound": "SOFT"},
             {"lap_start": 1, "lap_end": 10, "compound": "HARD",
              "tyre_age_at_start": 0}]
        )
        assert lookup(5)[0] == 2


class TestBuildReferenceLapIgnoresFailures:
    def test_fetch_failure_markers_are_not_treated_as_drivers(self):
        """A failed fetch is recorded as a marker dict with no telemetry; it
        must not reach the outline selection as if it were a driver."""
        marker = {"code": "LAW", "fetch_failed": True}
        real = _driver_result("NOR", n=300, lap=1)
        ref = openf1_data.build_reference_lap([marker, real])
        assert len(ref) == 300


class TestLastLapEnd:
    def test_uses_the_final_lap_duration(self):
        laps = [{"_t": 0.0, "lap_duration": 85.0}, {"_t": 85.0, "lap_duration": 83.0}]
        assert openf1_data._last_lap_end(laps, np.array([0.0, 85.0])) == 168.0

    def test_falls_back_when_the_final_lap_has_no_duration(self):
        """A retirement lap has no duration; allow a lap's worth, not forever."""
        laps = [{"_t": 0.0, "lap_duration": 85.0}, {"_t": 85.0, "lap_duration": None}]
        assert openf1_data._last_lap_end(laps, np.array([0.0, 85.0])) == 85.0 + 150.0


class TestBuildReferenceLap:
    def test_picks_the_lap_with_most_samples(self):
        sparse = _driver_result("VER", n=120, lap=1)
        dense = _driver_result("NOR", n=300, lap=1)
        ref = openf1_data.build_reference_lap([sparse, dense])
        assert len(ref) == 300

    def test_rejects_a_parked_car(self):
        """A lap-1 retirement sits still, so its 'lap' measures ~0 m and must
        not be mistaken for the track outline even with the most samples."""
        parked = _driver_result("HUL", n=1900, lap=1)
        parked["data"]["x"] = np.full(1900, 1234.0)
        parked["data"]["y"] = np.full(1900, -567.0)
        real = _driver_result("NOR", n=300, lap=1)
        ref = openf1_data.build_reference_lap([parked, real])
        assert len(ref) == 300

    def test_rejects_a_lap_longer_than_any_circuit(self):
        # whole-session samples collapsed onto one lap number
        toolong = _driver_result("HUL", n=400, lap=1)
        toolong["data"]["x"] = np.linspace(0, 2_000_000, 400)
        toolong["data"]["y"] = np.zeros(400)
        real = _driver_result("NOR", n=300, lap=1)
        ref = openf1_data.build_reference_lap([toolong, real])
        assert len(ref) == 300

    def test_ignores_untimed_drivers(self):
        """A driver with no lap timing has every sample on lap 1, so its
        'lap' is the whole session and must not become the outline."""
        untimed = _driver_result("HUL", n=400, lap=1)
        untimed["untimed"] = True
        real = _driver_result("NOR", n=300, lap=1)
        ref = openf1_data.build_reference_lap([untimed, real])
        assert len(ref) == 300

    def test_returns_none_when_nothing_is_plausible(self):
        parked = _driver_result("HUL", n=100, lap=1)
        parked["data"]["x"] = np.zeros(100)
        parked["data"]["y"] = np.zeros(100)
        assert openf1_data.build_reference_lap([parked]) is None

    def test_distance_is_metres_not_a_fraction(self):
        # a straight 10,000-unit run is 1,000 m at 10 units/m
        result = _driver_result("VER", n=60, lap=1)
        # 50,000 feed units at 10 units/m = 5,000 m, a credible circuit length
        result["data"]["x"] = np.linspace(0.0, 50000.0, 60)
        result["data"]["y"] = np.zeros(60)
        ref = openf1_data.build_reference_lap([result])
        assert ref["Distance"].max() == pytest.approx(5000.0)

    def test_has_the_columns_the_safety_car_needs(self):
        ref = openf1_data.build_reference_lap([_driver_result("VER", n=120, lap=1)])
        assert {"X", "Y", "Distance"} <= set(ref.columns)

    def test_returns_none_without_data(self):
        assert openf1_data.build_reference_lap([None, None]) is None


def _driver_result(code, n, lap):
    return {
        "code": code,
        "data": {
            "t": np.arange(n, dtype=float),
            "x": np.linspace(0, 45000, n),
            "y": np.linspace(0, 20000, n),
            "lap": np.full(n, lap, dtype=float),
            "rel_dist": np.linspace(0, 1, n),
        },
        "t_min": 0.0,
        "t_max": float(n - 1),
        "max_lap": lap,
    }
