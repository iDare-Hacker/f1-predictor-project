"""Tests for the backend-neutral frame assembly shared by both data sources."""

import numpy as np
import pytest

from src import replay_frames


def make_driver(code, t, lap=1, dist=None, **overrides):
    """Build a per-driver result in the shape both backends emit."""
    t = np.asarray(t, dtype=float)
    n = len(t)
    data = {
        "t": t,
        "x": np.linspace(0, 100, n),
        "y": np.linspace(0, 50, n),
        "dist": np.linspace(0, 1000, n) if dist is None else np.asarray(dist, float),
        "rel_dist": np.linspace(0, 1, n),
        "lap": np.full(n, lap, dtype=float),
        "tyre": np.full(n, 1.0),
        "tyre_life": np.linspace(1, n, n),
        "speed": np.full(n, 200.0),
        "gear": np.full(n, 7.0),
        "drs": np.zeros(n),
        "throttle": np.full(n, 100.0),
        "brake": np.zeros(n),
    }
    data.update(overrides)
    return {
        "code": code,
        "data": data,
        "t_min": float(t.min()),
        "t_max": float(t.max()),
        "max_lap": lap,
    }


class TestTrackStatuses:
    def test_shifts_to_timeline_and_closes_windows(self):
        out = replay_frames.format_track_statuses(
            [{"status": "1", "time_s": 100.0},
             {"status": "4", "time_s": 160.0},
             {"status": "1", "time_s": 220.0}],
            global_t_min=100.0,
        )
        assert [s["start_time"] for s in out] == [0.0, 60.0, 120.0]
        # each window ends where the next begins; the last stays open
        assert [s["end_time"] for s in out] == [60.0, 120.0, None]
        assert [s["status"] for s in out] == ["1", "4", "1"]

    def test_sorts_out_of_order_input(self):
        out = replay_frames.format_track_statuses(
            [{"status": "4", "time_s": 50.0}, {"status": "1", "time_s": 10.0}],
            global_t_min=0.0,
        )
        assert [s["status"] for s in out] == ["1", "4"]

    def test_empty(self):
        assert replay_frames.format_track_statuses([], 0.0) == []


class TestRaceControlMessages:
    def test_drops_messages_before_green(self):
        out = replay_frames.format_race_control_messages(
            [{"time_s": 50.0, "message": "before"},
             {"time_s": 150.0, "message": "after"}],
            global_t_min=100.0,
        )
        assert [m["message"] for m in out] == ["after"]
        assert out[0]["time"] == 50.0

    def test_normalises_missing_and_nan_fields(self):
        out = replay_frames.format_race_control_messages(
            [{"time_s": 10.0, "message": "x", "flag": None,
              "sector": float("nan"), "racing_number": 44.0}],
            global_t_min=0.0,
        )
        msg = out[0]
        assert msg["flag"] == ""
        assert msg["sector"] == ""
        # numeric driver numbers must not render as "44.0"
        assert msg["racing_number"] == "44"
        assert msg["category"] == ""

    def test_sorted_by_time(self):
        out = replay_frames.format_race_control_messages(
            [{"time_s": 30.0, "message": "b"}, {"time_s": 20.0, "message": "a"}],
            global_t_min=0.0,
        )
        assert [m["message"] for m in out] == ["a", "b"]


class TestResampleDrivers:
    def test_timeline_is_zero_based_at_fps(self):
        timeline, _, _ = replay_frames.resample_drivers(
            {"VER": make_driver("VER", [10.0, 11.0])["data"]},
            global_t_min=10.0, global_t_max=11.0,
        )
        assert timeline[0] == 0.0
        assert np.isclose(timeline[1] - timeline[0], replay_frames.DT)
        assert timeline[-1] < 1.0

    def test_max_tyre_life_tracked_per_compound(self):
        d = make_driver("VER", [0.0, 1.0, 2.0])
        d["data"]["tyre"] = np.full(3, 1.0)
        d["data"]["tyre_life"] = np.array([5.0, 9.0, 12.0])
        _, _, max_life = replay_frames.resample_drivers(
            {"VER": d["data"]}, 0.0, 2.0
        )
        # the timeline stops just short of t_max, so the final sample is excluded
        assert max_life[1] == 11

    def test_compound_changes_interpolate_across_the_boundary(self):
        """Documents existing behaviour: tyre is a categorical channel but is
        linearly interpolated, so a stint change passes through values that are
        not real compounds. Kept as-is; the replay tolerates it."""
        d = make_driver("VER", [0.0, 2.0])
        d["data"]["tyre"] = np.array([1.0, 2.0])
        _, resampled, _ = replay_frames.resample_drivers({"VER": d["data"]}, 0.0, 2.0)
        tyres = resampled["VER"]["tyre"]
        assert np.any((tyres > 1.0) & (tyres < 2.0))


class TestAssemble:
    def test_positions_ranked_by_lap_then_distance(self):
        # NOR is further along the same lap than VER, so NOR leads
        out = replay_frames.assemble(
            [make_driver("VER", [0.0, 4.0], dist=[0.0, 500.0]),
             make_driver("NOR", [0.0, 4.0], dist=[0.0, 900.0])],
            track_statuses=[], rc_messages=[], weather=None, pit_windows={},
        )
        last = out["frames"][-1]["drivers"]
        assert last["NOR"]["position"] == 1
        assert last["VER"]["position"] == 2

    def test_a_lap_ahead_outranks_greater_distance(self):
        behind = make_driver("VER", [0.0, 4.0], lap=2, dist=[0.0, 100.0])
        ahead = make_driver("NOR", [0.0, 4.0], lap=1, dist=[0.0, 5000.0])
        out = replay_frames.assemble(
            [behind, ahead],
            track_statuses=[], rc_messages=[], weather=None, pit_windows={},
        )
        last = out["frames"][-1]["drivers"]
        assert last["VER"]["position"] == 1

    def test_skips_none_results(self):
        out = replay_frames.assemble(
            [None, make_driver("VER", [0.0, 2.0]), None],
            track_statuses=[], rc_messages=[], weather=None, pit_windows={},
        )
        assert set(out["frames"][0]["drivers"]) == {"VER"}

    def test_raises_when_no_driver_has_data(self):
        with pytest.raises(ValueError, match="No valid telemetry"):
            replay_frames.assemble(
                [None, None], track_statuses=[], rc_messages=[],
                weather=None, pit_windows={},
            )

    def test_total_laps_is_the_max_across_drivers(self):
        out = replay_frames.assemble(
            [make_driver("VER", [0.0, 2.0], lap=57),
             make_driver("NOR", [0.0, 2.0], lap=58)],
            track_statuses=[], rc_messages=[], weather=None, pit_windows={},
        )
        assert out["total_laps"] == 58

    def test_pit_windows_shift_onto_timeline(self):
        # absolute window 101-103s, session starting at t=100 -> 1-3s on timeline
        out = replay_frames.assemble(
            [make_driver("VER", [100.0, 110.0])],
            track_statuses=[], rc_messages=[], weather=None,
            pit_windows={"VER": [(101.0, 103.0)]},
        )
        in_pit_at = [f["t"] for f in out["frames"] if f["drivers"]["VER"]["in_pit"]]
        assert min(in_pit_at) == pytest.approx(1.0, abs=0.05)
        assert max(in_pit_at) == pytest.approx(3.0, abs=0.05)

    def test_frame_payload_shape(self):
        out = replay_frames.assemble(
            [make_driver("VER", [0.0, 2.0])],
            track_statuses=[], rc_messages=[], weather=None, pit_windows={},
        )
        frame = out["frames"][0]
        assert set(frame) == {"t", "lap", "drivers"}
        car = frame["drivers"]["VER"]
        assert set(car) == {
            "x", "y", "dist", "lap", "rel_dist", "tyre", "tyre_life",
            "position", "speed", "gear", "drs", "throttle", "brake", "in_pit",
        }
        assert isinstance(car["gear"], int)
        assert isinstance(car["lap"], int)

    def test_weather_attached_and_rain_state_derived(self):
        out = replay_frames.assemble(
            [make_driver("VER", [0.0, 4.0])],
            track_statuses=[], rc_messages=[],
            weather={
                "time_s": np.array([0.0, 4.0]),
                "track_temp": np.array([30.0, 32.0]),
                "air_temp": np.array([20.0, 21.0]),
                "humidity": np.array([50.0, 55.0]),
                "wind_speed": np.array([1.0, 2.0]),
                "wind_direction": np.array([180.0, 190.0]),
                "rainfall": np.array([0.0, 1.0]),
            },
            pit_windows={},
        )
        assert out["frames"][0]["weather"]["rain_state"] == "DRY"
        assert out["frames"][-1]["weather"]["rain_state"] == "RAINING"
        assert out["frames"][0]["weather"]["track_temp"] == pytest.approx(30.0)

    def test_no_weather_key_when_absent(self):
        out = replay_frames.assemble(
            [make_driver("VER", [0.0, 2.0])],
            track_statuses=[], rc_messages=[], weather=None, pit_windows={},
        )
        assert "weather" not in out["frames"][0]
