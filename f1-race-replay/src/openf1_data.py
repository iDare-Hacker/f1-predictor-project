"""Replay data built from the OpenF1 API instead of FastF1.

FastF1 reads F1's timing archive, which has returned HTTP 401 since mid-October
2026, so uncached sessions cannot be loaded that way. OpenF1 republishes the
same live-timing feed and needs no credentials, covering 2023 onwards.

The output matches the FastF1 path exactly: per-driver channel arrays are handed
to :mod:`src.replay_frames`, which builds the frames both backends share.

Coordinates: OpenF1's x/y are the raw feed units (1/10 m), the same space
FastF1 exposes as X/Y, so track maps and distances line up without rescaling.
"""

import os
import pickle
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from src import openf1_client, replay_frames
from src.f1_data import _compute_safety_car_positions, get_tyre_compound_int
from src.lib.settings import get_settings

# Feed units per metre (see module docstring).
UNITS_PER_METRE = 10.0

# Drop location samples the feed emits with no fix.
MIN_VALID_COORD = 1

# Workers for the per-driver fetch. OpenF1 throttles (HTTP 429) well before
# this saturates a connection, and losing a driver to a 429 is worse than
# taking longer, so keep it low.
MAX_WORKERS = 2

# Replaying a race with cars silently missing is worse than failing, so refuse
# when too few drivers came back.
MIN_DRIVER_FRACTION = 0.8


class OpenF1DataUnavailable(RuntimeError):
    """OpenF1 has no usable data for the requested session."""


def _to_seconds(dates, origin):
    """Convert an array of ISO timestamps to seconds since `origin`."""
    return np.array([(d - origin).total_seconds() for d in dates], dtype=float)


def _build_lap_index(laps):
    """Return (lap_starts_s, lap_numbers) sorted by time, for lap attribution."""
    timed = [
        (lap["_t"], int(lap["lap_number"]))
        for lap in laps
        if lap.get("_t") is not None
    ]
    timed.sort()
    if not timed:
        return np.array([]), np.array([])
    return (
        np.array([t for t, _ in timed], dtype=float),
        np.array([n for _, n in timed], dtype=int),
    )


def _last_lap_end(laps, lap_starts):
    """When the driver's final timed lap finished, in seconds from the origin.

    Falls back to a generous margin past the last lap start when that lap has
    no recorded duration (the usual case for a retirement).
    """
    last_start = float(lap_starts[-1])
    duration = None
    for lap in laps:
        if lap.get("_t") is not None and float(lap["_t"]) == last_start:
            duration = lap.get("lap_duration")
            break
    if duration:
        return last_start + float(duration)
    # No duration: allow one typical lap's worth so the lap is not truncated.
    return last_start + 150.0


def _stint_lookup(stints):
    """Return a function mapping lap number -> (compound_int, tyre_life)."""
    spans = []
    for stint in stints:
        try:
            start = int(stint["lap_start"])
            end = int(stint["lap_end"])
        except (TypeError, ValueError, KeyError):
            continue
        compound = get_tyre_compound_int(str(stint.get("compound") or "UNKNOWN"))
        age_at_start = stint.get("tyre_age_at_start") or 0
        spans.append((start, end, compound, int(age_at_start)))

    def lookup(lap_number):
        for start, end, compound, age_at_start in spans:
            if start <= lap_number <= end:
                # Match FastF1's TyreLife: age when fitted, plus the laps run on
                # it this stint, counting the lap being driven.
                return compound, age_at_start + (lap_number - start) + 1
        return -1, 0

    return lookup


def _process_driver(args):
    """Fetch and shape one driver's telemetry into the shared per-driver form."""
    session_key, driver_number, code, laps, stints, origin, window = args
    print(f"Getting telemetry for driver: {code}")

    date_gt, date_lt = window
    try:
        location = openf1_client.get(
            "location", session_key=session_key, driver_number=driver_number,
            **{"date>": date_gt, "date<": date_lt},
        )
        car_data = openf1_client.get(
            "car_data", session_key=session_key, driver_number=driver_number,
            **{"date>": date_gt, "date<": date_lt},
        )
    except openf1_client.OpenF1Error as e:
        print(f"Warning: Could not fetch telemetry for {code}: {e}")
        # A failed request is not the same as a driver with no data: the grid
        # check below must only count genuine fetch failures.
        return {"code": code, "fetch_failed": True}

    # Keep only samples with a real position fix
    points = [
        r for r in location
        if abs(r.get("x") or 0) >= MIN_VALID_COORD
        or abs(r.get("y") or 0) >= MIN_VALID_COORD
    ]
    if not points:
        print(f"Warning: no position data for {code}")
        return None

    for r in points:
        r["_dt"] = openf1_client.parse_date(r["date"])
    points.sort(key=lambda r: r["_dt"])

    t = _to_seconds([r["_dt"] for r in points], origin)
    x = np.array([r["x"] for r in points], dtype=float)
    y = np.array([r["y"] for r in points], dtype=float)

    # Lap attribution: a sample belongs to the most recent lap that had started.
    lap_starts, lap_numbers = _build_lap_index(laps)
    if len(lap_starts) == 0:
        # A driver who retired before completing a timed lap still has position
        # data worth replaying; attribute all of it to lap 1.
        print(f"Note: {code} has no timed laps (early retirement) - using lap 1")
        lap = np.ones(len(t), dtype=float)
        untimed = True
    else:
        # Clip to the driver's running window. Without this, a car that retires
        # or finishes keeps emitting position data from the garage, and every
        # one of those samples attributes to its last lap - which pins a
        # stationary car on the track for the rest of the replay.
        last_lap_end = _last_lap_end(laps, lap_starts)
        idx = np.searchsorted(lap_starts, t, side="right") - 1
        valid = (idx >= 0) & (t <= last_lap_end)
        if not valid.any():
            print(f"Warning: no telemetry inside any lap for {code}")
            return None
        t, x, y, idx = t[valid], x[valid], y[valid], idx[valid]
        lap = lap_numbers[idx].astype(float)
        untimed = False

    # Distance travelled, from the chord lengths between position samples.
    step = np.hypot(np.diff(x), np.diff(y)) / UNITS_PER_METRE
    step = np.concatenate(([0.0], step))
    # A new lap restarts the within-lap distance; a jump in the feed should not
    # add a huge bogus step either.
    new_lap = np.concatenate(([False], np.diff(lap) != 0))
    step[new_lap] = 0.0

    race_dist = np.cumsum(step)

    # Within-lap distance and its fraction of that lap's length
    lap_dist = np.zeros_like(race_dist)
    rel_dist = np.zeros_like(race_dist)
    for lap_no in np.unique(lap):
        mask = lap == lap_no
        within = np.cumsum(step[mask])
        lap_dist[mask] = within
        total = within[-1]
        rel_dist[mask] = within / total if total > 0 else 0.0

    # Car channels, interpolated onto the position timestamps
    def car_channel(name, default=0.0, scale=1.0):
        if not car_samples:
            return np.full(len(t), default)
        values = np.array(
            [default if r.get(name) is None else float(r[name]) for r in car_samples],
            dtype=float,
        ) * scale
        return np.interp(t, car_t, values)

    car_samples = [r for r in car_data if r.get("date")]
    for r in car_samples:
        r["_dt"] = openf1_client.parse_date(r["date"])
    car_samples.sort(key=lambda r: r["_dt"])
    car_t = (
        _to_seconds([r["_dt"] for r in car_samples], origin)
        if car_samples else np.array([])
    )

    speed = car_channel("speed")
    throttle = car_channel("throttle")
    brake = car_channel("brake")
    gear = np.round(car_channel("n_gear"))
    drs = np.round(car_channel("drs"))

    # Tyre compound and life come from stints, which are per lap
    lookup = _stint_lookup(stints)
    compound_by_lap = {int(n): lookup(int(n)) for n in np.unique(lap)}
    tyre = np.array([compound_by_lap[int(n)][0] for n in lap], dtype=float)
    tyre_life = np.array([compound_by_lap[int(n)][1] for n in lap], dtype=float)

    print(f"Completed telemetry for driver: {code}")

    return {
        "code": code,
        "data": {
            "t": t,
            "x": x,
            "y": y,
            "dist": race_dist,
            "rel_dist": rel_dist,
            "lap": lap,
            "tyre": tyre,
            "tyre_life": tyre_life,
            "speed": speed,
            "gear": gear,
            "drs": drs,
            "throttle": throttle,
            "brake": brake,
        },
        "t_min": float(t.min()),
        "t_max": float(t.max()),
        "max_lap": int(lap.max()),
        # True when every sample was forced onto lap 1 for lack of lap timing,
        # which makes this driver's "lap" useless as a track outline.
        "untimed": untimed,
    }


def _derive_track_statuses(race_control, origin):
    """Approximate FastF1's track status codes from race control messages.

    OpenF1 has no track-status feed, so flags and safety-car messages stand in.
    Codes match FastF1's: 1 clear, 2 yellow, 4 safety car, 5 red, 6 VSC.

    Safety-car state and flag state are tracked separately and the more severe
    wins, so a "CLEAR IN TRACK SECTOR 13" during a VSC does not cancel it.
    Per-driver blue flags are ignored - they say nothing about the track.
    """
    events = []
    for msg in race_control:
        dt = openf1_client.parse_date(msg.get("date"))
        if dt is None:
            continue
        events.append((
            (dt - origin).total_seconds(),
            str(msg.get("category") or ""),
            str(msg.get("message") or "").upper(),
            str(msg.get("flag") or "").upper(),
        ))
    events.sort(key=lambda e: e[0])

    statuses = []
    sc_state = None       # '4' safety car, '6' VSC, or None
    flag_state = "1"      # '1' clear, '2' yellow, '5' red
    last_emitted = None

    for time_s, category, text, flag in events:
        if category == "SafetyCar" or "SAFETY CAR" in text or "VSC" in text:
            # OpenF1 abbreviates the virtual safety car as "VSC"
            if "VSC" in text or "VIRTUAL SAFETY CAR" in text:
                sc_state = None if "ENDING" in text else "6"
            elif "SAFETY CAR" in text:
                sc_state = None if ("IN THIS LAP" in text or "ENDING" in text) else "4"
        elif flag == "RED":
            flag_state = "5"
        elif flag in ("YELLOW", "DOUBLE YELLOW"):
            flag_state = "2"
        elif flag in ("GREEN", "CLEAR", "CHEQUERED"):
            flag_state = "1"
        else:
            # BLUE and anything unrecognised say nothing about track state
            continue

        # A red flag outranks a safety car; otherwise the SC wins over flags.
        if flag_state == "5":
            effective = "5"
        else:
            effective = sc_state or flag_state

        if effective != last_emitted:
            statuses.append({"status": effective, "time_s": time_s})
            last_emitted = effective

    return statuses


def get_circuit_rotation(year, round_number, session_type="R"):
    """Circuit rotation for the track map.

    OpenF1 has no rotation, but it does give the circuit_key, and FastF1's
    MultiViewer source (a different host, unaffected by the archive 401)
    is keyed on exactly that.
    """
    try:
        session = openf1_client.resolve_session(year, round_number, session_type)
        sessions = openf1_client.get("sessions", session_key=session["session_key"])
        circuit_key = sessions[0].get("circuit_key") if sessions else None
        if circuit_key is None:
            return 0.0

        import fastf1.mvapi

        info = fastf1.mvapi.get_circuit_info(year=year, circuit_key=int(circuit_key))
        return float(info.rotation) if info is not None else 0.0
    except Exception as e:
        print(f"Could not determine circuit rotation ({e}); using 0°.")
        return 0.0


def get_session_info(year, round_number, session_type="R"):
    """Metadata for the replay's session banner."""
    session = openf1_client.resolve_session(year, round_number, session_type)
    date = session["date_start"]
    return {
        "event_name": session["event_name"],
        "circuit_name": session["location"],
        "country": session["country"],
        "year": year,
        "round": round_number,
        "date": date.strftime("%B %d, %Y") if date else "",
    }


def get_race_telemetry(year, round_number, session_type="R", refresh=False):
    """Build the replay payload for a race/sprint session from OpenF1."""
    session = openf1_client.resolve_session(year, round_number, session_type)
    settings = get_settings()
    computed_dir = settings.computed_data_location

    label = (
        f"{year}_Round_{round_number}_{session['event_name'].replace(' ', '_')}"
        f"_openf1_{'sprint' if session_type == 'S' else 'race'}"
    )
    cache_file = os.path.join(computed_dir, f"{label}_telemetry.pkl")

    if not refresh and os.path.exists(cache_file):
        with open(cache_file, "rb") as f:
            print("Loaded precomputed telemetry data (OpenF1).")
            return pickle.load(f)

    session_key = session["session_key"]
    print(f"Fetching {session['event_name']} {session['session_name']} from OpenF1…")

    drivers = openf1_client.get("drivers", session_key=session_key)
    if not drivers:
        raise OpenF1DataUnavailable(
            f"OpenF1 has no driver list for {session['event_name']} "
            f"({year} round {round_number})."
        )

    all_laps = openf1_client.get("laps", session_key=session_key)
    if not all_laps:
        raise OpenF1DataUnavailable(
            f"OpenF1 has no lap data for {session['event_name']} "
            f"({year} round {round_number}). The session may not have run yet."
        )

    # The feed carries samples well outside the session; the first lap start is
    # the natural origin and keeps the timeline comparable to FastF1's.
    for lap in all_laps:
        dt = openf1_client.parse_date(lap.get("date_start"))
        lap["_t"] = dt
    timed = [lap["_t"] for lap in all_laps if lap["_t"] is not None]
    if not timed:
        raise OpenF1DataUnavailable(
            f"OpenF1 lap data for {session['event_name']} has no timestamps."
        )
    origin = min(timed)

    # Re-express lap starts as seconds from the origin for lap attribution
    for lap in all_laps:
        lap["_t"] = (lap["_t"] - origin).total_seconds() if lap["_t"] else None

    window_start = session["date_start"] or origin
    window_end = session["date_end"]
    fetch_window = (
        min(window_start, origin).isoformat(),
        (window_end.isoformat() if window_end else ""),
    )
    if not fetch_window[1]:
        # No end in the metadata: bound it by the last lap seen, plus a margin.
        last = max(lap["_t"] for lap in all_laps if lap["_t"] is not None)
        fetch_window = (
            fetch_window[0],
            (origin + pd.Timedelta(seconds=last + 600)).isoformat(),
        )

    all_stints = openf1_client.get("stints", session_key=session_key)
    race_control = openf1_client.get("race_control", session_key=session_key)
    weather_raw = openf1_client.get("weather", session_key=session_key)
    pit_raw = openf1_client.get("pit", session_key=session_key)

    laps_by_driver = {}
    for lap in all_laps:
        laps_by_driver.setdefault(lap["driver_number"], []).append(lap)
    stints_by_driver = {}
    for stint in all_stints:
        stints_by_driver.setdefault(stint["driver_number"], []).append(stint)

    codes = {}
    driver_colors = {}
    for d in drivers:
        number = d["driver_number"]
        code = d.get("name_acronym") or str(number)
        codes[number] = code
        colour = str(d.get("team_colour") or "").lstrip("#")
        if len(colour) == 6:
            driver_colors[code] = tuple(
                int(colour[i:i + 2], 16) for i in (0, 2, 4)
            )

    print(f"Processing {len(codes)} drivers' data")
    args = [
        (
            session_key, number, codes[number],
            laps_by_driver.get(number, []), stints_by_driver.get(number, []),
            origin, fetch_window,
        )
        for number in codes
    ]
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(args))) as executor:
        results = list(executor.map(_process_driver, args))

    failed = sorted(r["code"] for r in results if r is not None and r.get("fetch_failed"))
    recovered = [r for r in results if r is not None and not r.get("fetch_failed")]

    if not recovered:
        raise OpenF1DataUnavailable(
            f"OpenF1 returned no usable telemetry for {session['event_name']} "
            f"({year} round {round_number})."
        )

    # Only request failures justify refusing: a driver who crashed on lap 1
    # legitimately has no position data, and that is not a broken fetch.
    if failed and len(recovered) < MIN_DRIVER_FRACTION * len(results):
        raise OpenF1DataUnavailable(
            f"Only {len(recovered)} of {len(results)} drivers came back from "
            f"OpenF1 for {session['event_name']}; failed to fetch "
            f"{', '.join(failed)}.\n\nThis is usually rate limiting (HTTP 429). "
            "Wait a minute and run it again - partial results are not replayed."
        )
    if failed:
        print(f"Note: continuing without {', '.join(failed)} (fetch failed).")

    results = recovered

    # Session-level inputs, in the shared neutral form
    track_statuses = _derive_track_statuses(race_control, origin)

    rc_messages = []
    for msg in race_control:
        dt = openf1_client.parse_date(msg.get("date"))
        if dt is None:
            continue
        rc_messages.append({
            "time_s": (dt - origin).total_seconds(),
            "category": msg.get("category", ""),
            "message": msg.get("message", ""),
            "flag": msg.get("flag", ""),
            "scope": msg.get("scope", ""),
            "sector": msg.get("sector", ""),
            "racing_number": msg.get("driver_number", ""),
        })

    weather = None
    if weather_raw:
        rows = [w for w in weather_raw if w.get("date")]
        rows.sort(key=lambda w: w["date"])
        if rows:
            def column(name):
                return np.array(
                    [0.0 if r.get(name) is None else float(r[name]) for r in rows],
                    dtype=float,
                )
            weather = {
                "time_s": _to_seconds(
                    [openf1_client.parse_date(r["date"]) for r in rows], origin
                ),
                "track_temp": column("track_temperature"),
                "air_temp": column("air_temperature"),
                "humidity": column("humidity"),
                "wind_speed": column("wind_speed"),
                "wind_direction": column("wind_direction"),
                "rainfall": column("rainfall"),
            }

    # Pit windows: OpenF1 gives the moment of the stop and its duration
    pit_windows = {}
    for stop in pit_raw:
        code = codes.get(stop.get("driver_number"))
        dt = openf1_client.parse_date(stop.get("date"))
        if code is None or dt is None:
            continue
        start = (dt - origin).total_seconds()
        duration = stop.get("pit_duration")
        end = start + (float(duration) if duration else 40.0)
        pit_windows.setdefault(code, []).append((start, end))

    payload = replay_frames.assemble(
        results, track_statuses, rc_messages, weather, pit_windows
    )

    # Safety car needs a reference lap for the track shape; reuse the fastest
    # driver's first full lap of position data.
    reference_lap = build_reference_lap(results)
    _compute_safety_car_positions(
        payload["frames"], payload["track_statuses"], reference_lap
    )

    payload["driver_colors"] = driver_colors
    # Carried in the payload so the replay gets the track layout without refetching
    payload["reference_lap"] = reference_lap

    os.makedirs(computed_dir, exist_ok=True)
    with open(cache_file, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Saved telemetry cache: {cache_file}")

    return payload


# A single flying lap must measure somewhere in this range to be a credible
# track outline. It filters out parked cars (≈0 m) and any driver whose samples
# all landed on one lap number, such as a lap-1 retirement.
MIN_LAP_METRES = 2000.0
MAX_LAP_METRES = 10000.0


def _lap_metres(x, y):
    return float(np.sum(np.hypot(np.diff(x), np.diff(y))) / UNITS_PER_METRE)


def build_reference_lap(results):
    """Build a track-shape reference (X/Y/Distance) from processed telemetry.

    Picks the lap with the most position samples among those whose measured
    length is plausible for a circuit, so the polyline is as smooth as the feed
    allows without mistaking a stationary car for a lap.
    """
    best = None
    for result in results:
        if result is None or result.get("untimed") or "data" not in result:
            # Skip fetch-failure markers, and untimed drivers whose samples all
            # sit on lap 1 - their "lap" is the whole session, not a circuit lap.
            continue
        data = result["data"]
        lap = data["lap"]
        for lap_no in np.unique(lap):
            mask = lap == lap_no
            count = int(mask.sum())
            if not 50 <= count <= 2000:
                # A real lap at the feed's ~4 Hz is a few hundred samples.
                continue
            if best is not None and count <= best[0]:
                continue
            metres = _lap_metres(data["x"][mask], data["y"][mask])
            if not (MIN_LAP_METRES <= metres <= MAX_LAP_METRES):
                continue
            best = (count, data, mask)

    if best is None:
        print("Warning: no plausible reference lap found; track outline unavailable")
        return None

    _, data, mask = best
    x = data["x"][mask]
    y = data["y"][mask]
    # Distance along the lap in metres, from the chords between samples, so the
    # replay's circuit-length readout is real and not a normalised fraction.
    step = np.concatenate(([0.0], np.hypot(np.diff(x), np.diff(y)) / UNITS_PER_METRE))
    return pd.DataFrame({"X": x, "Y": y, "Distance": np.cumsum(step)})
