"""Thin client for the public OpenF1 API (https://openf1.org).

Used as a replay data source when FastF1 cannot reach F1's timing archive.
Covers 2023 onwards; earlier seasons are only available through FastF1's cache.
"""

import time
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.openf1.org/v1"

# OpenF1 is a free public service, so be a polite client: a short timeout, a
# couple of retries on transient failures, and no parallel hammering beyond the
# small worker pool the caller uses.
TIMEOUT_S = 60
MAX_RETRIES = 5
RETRY_BACKOFF_S = 3.0
# A 429 means we are being throttled, so back off much harder than for a 5xx.
RATE_LIMIT_BACKOFF_S = 15.0

# OpenF1 only has data from 2023 onwards.
EARLIEST_YEAR = 2023

# Session names as OpenF1 spells them, keyed by the app's FastF1-style codes.
SESSION_NAMES = {
    "R": ("Race",),
    "S": ("Sprint",),
    "Q": ("Qualifying",),
    "SQ": ("Sprint Qualifying", "Sprint Shootout"),
}


class OpenF1Error(RuntimeError):
    """An OpenF1 request failed, or returned nothing usable."""


def get(endpoint, **params):
    """GET one OpenF1 endpoint and return the decoded JSON list."""
    url = f"{BASE_URL}/{endpoint}"
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            last_error = e
        else:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError as e:
                    raise OpenF1Error(f"{endpoint}: malformed JSON ({e})") from e
                if isinstance(data, dict) and "detail" in data:
                    raise OpenF1Error(f"{endpoint}: {data['detail']}")
                return data
            # 429/5xx are worth retrying; a 4xx is not going to improve.
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code < 500 and resp.status_code != 429:
                raise OpenF1Error(f"{endpoint}: {last_error} for {params}")

            if resp.status_code == 429:
                # Prefer the server's own guidance when it sends Retry-After.
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else None
                except ValueError:
                    delay = None
                wait = delay if delay else RATE_LIMIT_BACKOFF_S * (attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    print(f"  OpenF1 rate limited; waiting {wait:.0f}s…")
                    time.sleep(wait)
                continue

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))

    raise OpenF1Error(f"{endpoint}: giving up after {MAX_RETRIES} attempts ({last_error})")


def parse_date(value):
    """Parse an OpenF1 ISO-8601 timestamp into an aware UTC datetime."""
    if not value:
        return None
    # Python's fromisoformat handles the "+00:00" offset OpenF1 emits.
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def list_rounds(year):
    """Return [{round_number, meeting_key, name, date}] for a season, in order.

    OpenF1 has no round number, so it is derived from the chronological order of
    the season's race weekends. Testing meetings are excluded, because FastF1
    and the F1 calendar do not count them as rounds.
    """
    meetings = get("meetings", year=year)
    if not meetings:
        raise OpenF1Error(
            f"OpenF1 has no meetings for {year}. It only covers "
            f"{EARLIEST_YEAR} onwards."
        )

    races = [
        m for m in meetings
        if "testing" not in str(m.get("meeting_name", "")).lower()
    ]
    races.sort(key=lambda m: str(m.get("date_start", "")))

    return [
        {
            "round_number": i + 1,
            "meeting_key": m["meeting_key"],
            "name": m.get("meeting_name", ""),
            "date": str(m.get("date_start", ""))[:10],
            "location": m.get("location", ""),
            "country": m.get("country_name", ""),
            "circuit": m.get("circuit_short_name", ""),
        }
        for i, m in enumerate(races)
    ]


def resolve_session(year, round_number, session_type="R"):
    """Find the OpenF1 session for a season/round/session-type.

    Returns a dict with session_key, meeting metadata and the session window.
    """
    if year < EARLIEST_YEAR:
        raise OpenF1Error(
            f"OpenF1 has no data for {year} (it starts at {EARLIEST_YEAR}).\n"
            "For earlier seasons the FastF1 cache is the only source."
        )

    rounds = list_rounds(year)
    meeting = next((r for r in rounds if r["round_number"] == round_number), None)
    if meeting is None:
        raise OpenF1Error(
            f"{year} has no round {round_number} on OpenF1 "
            f"(found {len(rounds)} rounds)."
        )

    wanted = SESSION_NAMES.get(session_type, (session_type,))
    sessions = get("sessions", meeting_key=meeting["meeting_key"])
    match = next(
        (s for s in sessions if s.get("session_name") in wanted),
        None,
    )
    if match is None:
        available = sorted({str(s.get("session_name")) for s in sessions})
        raise OpenF1Error(
            f"{meeting['name']} ({year} round {round_number}) has no "
            f"{'/'.join(wanted)} session on OpenF1. Available: {', '.join(available)}"
        )

    return {
        "session_key": match["session_key"],
        "session_name": match.get("session_name", ""),
        "meeting_key": meeting["meeting_key"],
        "event_name": meeting["name"],
        "location": meeting["location"],
        "country": meeting["country"],
        "circuit": meeting["circuit"],
        "round_number": round_number,
        "year": year,
        "date_start": parse_date(match.get("date_start")),
        "date_end": parse_date(match.get("date_end")),
    }
