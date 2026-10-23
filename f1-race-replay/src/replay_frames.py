"""Backend-neutral assembly of replay frames.

Both data sources (FastF1 and OpenF1) produce the same per-driver telemetry
arrays and session-level events; this module turns them into the frame list the
replay window consumes, so the timeline, leaderboard and pit/weather logic exist
in exactly one place.

All input times are *absolute session seconds*. The shift onto a zero-based
playback timeline happens here.
"""

import math

import numpy as np

FPS = 25
DT = 1 / FPS

# The per-driver channels carried through resampling onto the common timeline.
CHANNELS = (
    "x", "y", "dist", "rel_dist", "lap",
    "tyre", "tyre_life", "speed", "gear", "drs", "throttle", "brake",
)


def _safe_str(val, as_int=False):
    """Convert a value to string, returning '' for None/NaN."""
    if val is None:
        return ""
    try:
        if isinstance(val, float) and math.isnan(val):
            return ""
    except (TypeError, ValueError):
        pass
    if as_int:
        try:
            return str(int(float(val)))
        except (ValueError, TypeError):
            return str(val)
    return str(val)


def format_track_statuses(statuses, global_t_min):
    """Shift track statuses onto the playback timeline and close their windows.

    `statuses` is [{"status": str, "time_s": float}] in absolute session seconds.
    Each entry's end_time is the next entry's start; the last stays open (None).
    """
    formatted = []
    for status in sorted(statuses, key=lambda s: s["time_s"]):
        start_time = status["time_s"] - global_t_min
        if formatted:
            formatted[-1]["end_time"] = start_time
        formatted.append({
            "status": status["status"],
            "start_time": start_time,
            "end_time": None,
        })
    return formatted


def format_race_control_messages(messages, global_t_min):
    """Shift race control messages onto the playback timeline, dropping pre-start ones."""
    formatted = []
    for msg in messages:
        msg_time = msg["time_s"] - global_t_min
        if msg_time > 0.0:
            formatted.append({
                "time": round(msg_time, 3),
                "category": _safe_str(msg.get("category", "")),
                "message": _safe_str(msg.get("message", "")),
                "flag": _safe_str(msg.get("flag", "")),
                "scope": _safe_str(msg.get("scope", "")),
                "sector": _safe_str(msg.get("sector", ""), as_int=True),
                "racing_number": _safe_str(msg.get("racing_number", ""), as_int=True),
            })
    formatted.sort(key=lambda m: m["time"])
    return formatted


def _resample_weather(weather, timeline, global_t_min):
    """Interpolate weather channels onto the playback timeline."""
    if not weather:
        return None
    try:
        times = np.asarray(weather["time_s"], dtype=float) - global_t_min
        if len(times) == 0:
            return None
        order = np.argsort(times)
        times = times[order]

        def resample(name):
            series = weather.get(name)
            if series is None:
                return None
            return np.interp(timeline, times, np.asarray(series, dtype=float)[order])

        return {
            "track_temp": resample("track_temp"),
            "air_temp": resample("air_temp"),
            "humidity": resample("humidity"),
            "wind_speed": resample("wind_speed"),
            "wind_direction": resample("wind_direction"),
            "rainfall": resample("rainfall"),
        }
    except Exception as e:
        print(f"Weather data could not be processed: {e}")
        return None


def _weather_snapshot(weather_resampled, i):
    """Build one frame's weather dict, or {} if unavailable."""
    if not weather_resampled:
        return {}
    try:
        wt = weather_resampled
        rain_val = wt["rainfall"][i] if wt.get("rainfall") is not None else 0.0

        def at(name):
            return float(wt[name][i]) if wt.get(name) is not None else None

        return {
            "track_temp": at("track_temp"),
            "air_temp": at("air_temp"),
            "humidity": at("humidity"),
            "wind_speed": at("wind_speed"),
            "wind_direction": at("wind_direction"),
            "rain_state": "RAINING" if rain_val and rain_val >= 0.5 else "DRY",
        }
    except Exception as e:
        print(f"Failed to attach weather data to frame {i}: {e}")
        return {}


def resample_drivers(driver_data, global_t_min, global_t_max):
    """Resample every driver's channels onto one common timeline.

    Returns (timeline, {code: {channel: array}}, max_tyre_life_map).
    """
    timeline = np.arange(global_t_min, global_t_max, DT) - global_t_min

    resampled_data = {}
    max_tyre_life_map = {}

    for code, data in driver_data.items():
        t = np.asarray(data["t"], dtype=float) - global_t_min
        order = np.argsort(t)
        t_sorted = t[order]

        resampled = {
            name: np.interp(timeline, t_sorted, np.asarray(data[name], dtype=float)[order])
            for name in CHANNELS
        }
        resampled["t"] = timeline
        resampled_data[code] = resampled

        tyre = resampled["tyre"]
        tyre_life = resampled["tyre_life"]
        for t_int in np.unique(tyre):
            mask = tyre == t_int
            c_max = np.nanmax(tyre_life[mask])
            if not np.isnan(c_max):
                key = int(t_int)
                max_tyre_life_map[key] = max(max_tyre_life_map.get(key, 1), int(c_max))

    return timeline, resampled_data, max_tyre_life_map


def build_frames(timeline, resampled_data, pit_windows_shifted, weather_resampled):
    """Build the frame list, assigning running race positions from race distance."""
    frames = []
    driver_codes = list(resampled_data.keys())

    for i in range(len(timeline)):
        t = timeline[i]
        snapshot = []
        for code in driver_codes:
            d = resampled_data[code]
            snapshot.append({
                "code": code,
                "dist": float(d["dist"][i]),
                "x": float(d["x"][i]),
                "y": float(d["y"][i]),
                "lap": int(round(d["lap"][i])),
                "rel_dist": float(d["rel_dist"][i]),
                "tyre": float(d["tyre"][i]),
                "tyre_life": float(d["tyre_life"][i]),
                "speed": float(d["speed"][i]),
                "gear": int(d["gear"][i]),
                "drs": int(d["drs"][i]),
                "throttle": float(d["throttle"][i]),
                "brake": float(d["brake"][i]),
            })

        # If for some reason we have no drivers at this instant
        if not snapshot:
            continue

        # Sort by race distance to get POSITIONS (1-20); leader covered the most
        snapshot.sort(key=lambda r: (r.get("lap", 0), r["dist"]), reverse=True)

        leader_lap = snapshot[0]["lap"]

        frame_data = {}
        for idx, car in enumerate(snapshot):
            code = car["code"]

            in_pit = False
            for start, end in pit_windows_shifted.get(code, []):
                if start <= t <= end:
                    in_pit = True
                    break

            frame_data[code] = {
                "x": car["x"],
                "y": car["y"],
                "dist": car["dist"],
                "lap": car["lap"],
                "rel_dist": round(car["rel_dist"], 4),
                "tyre": car["tyre"],
                "tyre_life": car["tyre_life"],
                "position": idx + 1,
                "speed": car["speed"],
                "gear": car["gear"],
                "drs": car["drs"],
                "throttle": car["throttle"],
                "brake": car["brake"],
                "in_pit": in_pit,
            }

        frame_payload = {
            "t": round(t, 3),
            "lap": leader_lap,  # leader's lap at this time
            "drivers": frame_data,
        }
        weather_snapshot = _weather_snapshot(weather_resampled, i)
        if weather_snapshot:
            frame_payload["weather"] = weather_snapshot

        frames.append(frame_payload)

    return frames


def assemble(driver_results, track_statuses, rc_messages, weather, pit_windows):
    """Turn per-driver telemetry and session events into the replay payload.

    `driver_results` is the list of per-driver dicts (as produced by either
    backend): {"code", "data": {channel: array, "t": array}, "t_min", "t_max",
    "max_lap"}. Entries of None are skipped.

    Returns a dict with frames, track_statuses, race_control_messages,
    total_laps and max_tyre_life. Safety-car positions are *not* applied here;
    the caller does that, because it needs a reference lap.
    """
    driver_data = {}
    global_t_min = None
    global_t_max = None
    max_lap_number = 0

    for result in driver_results:
        if result is None:
            continue
        driver_data[result["code"]] = result["data"]
        max_lap_number = max(max_lap_number, result["max_lap"])
        t_min, t_max = result["t_min"], result["t_max"]
        global_t_min = t_min if global_t_min is None else min(global_t_min, t_min)
        global_t_max = t_max if global_t_max is None else max(global_t_max, t_max)

    if global_t_min is None or global_t_max is None:
        raise ValueError("No valid telemetry data found for any driver")

    timeline, resampled_data, max_tyre_life_map = resample_drivers(
        driver_data, global_t_min, global_t_max
    )

    formatted_track_statuses = format_track_statuses(track_statuses, global_t_min)
    formatted_rc_messages = format_race_control_messages(rc_messages, global_t_min)
    weather_resampled = _resample_weather(weather, timeline, global_t_min)

    pit_windows_shifted = {
        code: [(start - global_t_min, end - global_t_min) for start, end in windows]
        for code, windows in pit_windows.items()
    }

    frames = build_frames(
        timeline, resampled_data, pit_windows_shifted, weather_resampled
    )

    return {
        "frames": frames,
        "track_statuses": formatted_track_statuses,
        "race_control_messages": formatted_rc_messages,
        "total_laps": int(max_lap_number),
        "max_tyre_life": max_tyre_life_map,
    }
