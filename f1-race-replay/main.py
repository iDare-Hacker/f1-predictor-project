from src.f1_data import get_race_telemetry, enable_cache, get_circuit_rotation, load_session, get_quali_telemetry, list_rounds, list_sprints, SessionDataUnavailable
from src import openf1_data
from src.openf1_client import OpenF1Error
from src.run_session import run_arcade_replay, launch_insights_menu
from src.interfaces.qualifying import run_qualifying_replay
import sys
from src.cli.race_selection import cli_load
from src.gui.race_selection import RaceSelectionWindow
from PySide6.QtWidgets import QApplication
from src.lib.season import get_season
from src.lib.f1_theme import apply_f1_theme
import logging

def run_race_openf1(year, round_number, playback_speed, session_type, visible_hud, ready_file):
  """Replay a race/sprint using OpenF1 as the data source."""
  race_telemetry = openf1_data.get_race_telemetry(
    year, round_number, session_type, refresh="--refresh-data" in sys.argv
  )

  # OpenF1 has no per-lap DRS channel, so the replay falls back to its
  # speed-based DRS detection; the track layout comes from the reference lap.
  example_lap = race_telemetry.get("reference_lap")

  session_info = openf1_data.get_session_info(year, round_number, session_type)
  session_info["total_laps"] = race_telemetry["total_laps"]
  session_info["circuit_length_m"] = (
    float(example_lap["Distance"].max())
    if example_lap is not None and "Distance" in example_lap
    else None
  )

  launch_insights_menu()
  print("Launching insights menu...")

  run_arcade_replay(
    frames=race_telemetry['frames'],
    track_statuses=race_telemetry['track_statuses'],
    example_lap=example_lap,
    drivers=list(race_telemetry['driver_colors'].keys()),
    playback_speed=playback_speed,
    driver_colors=race_telemetry['driver_colors'],
    title=f"{session_info['event_name']} - {'Sprint' if session_type == 'S' else 'Race'} (OpenF1)",
    total_laps=race_telemetry['total_laps'],
    circuit_rotation=openf1_data.get_circuit_rotation(year, round_number, session_type),
    visible_hud=visible_hud,
    ready_file=ready_file,
    session_info=session_info,
    session=None,
    enable_telemetry=True,
    race_control_messages=race_telemetry.get('race_control_messages', [])
  )


def main(year=None, round_number=None, playback_speed=1, session_type='R', visible_hud=True, ready_file=None, show_telemetry_viewer=True, clear_cache=False, source='auto'):
  print(f"Loading F1 {year} Round {round_number} Session '{session_type}'")

  # Clearing is opt-in (--clear-cache). F1's archive returns 401 since mid-October
  # 2026, so a cached session that gets wiped cannot be downloaded again.
  enable_cache(clear=clear_cache)

  if source == 'openf1':
    if session_type in ('Q', 'SQ'):
      raise OpenF1Error(
        "The OpenF1 backend covers race and sprint replays only; qualifying "
        "still needs FastF1's cache."
      )
    run_race_openf1(year, round_number, playback_speed, session_type, visible_hud, ready_file)
    return

  try:
    session = load_session(year, round_number, session_type)
  except SessionDataUnavailable:
    # 'auto': FastF1's archive is gated, so try OpenF1 before giving up.
    if source == 'auto' and session_type not in ('Q', 'SQ'):
      print("\nFastF1 has no data for this session - trying OpenF1 instead…\n")
      run_race_openf1(year, round_number, playback_speed, session_type, visible_hud, ready_file)
      return
    raise

  print(f"Loaded session: {session.event['EventName']} - {session.event['RoundNumber']} - {session_type}")

  if session_type == 'Q' or session_type == 'SQ':

    # Get the drivers who participated and their lap times

    qualifying_session_data = get_quali_telemetry(session, session_type=session_type)

    # Run the arcade screen showing qualifying results

    title = f"{session.event['EventName']} - {'Sprint Qualifying' if session_type == 'SQ' else 'Qualifying Results'}"
    
    run_qualifying_replay(
      session=session,
      data=qualifying_session_data,
      title=title,
      ready_file=ready_file,
    )

  else:

    # Get the drivers who participated in the race

    try:
      race_telemetry = get_race_telemetry(session, session_type=session_type)
    except (SessionDataUnavailable, ValueError) as e:
      # Laps existed but the telemetry channels did not. OpenF1 may still have it.
      if source != 'auto':
        raise
      print(f"\nFastF1 telemetry unusable ({e}) - trying OpenF1 instead…\n")
      run_race_openf1(year, round_number, playback_speed, session_type, visible_hud, ready_file)
      return

    # Get example lap for track layout
    # Qualifying lap preferred for DRS zones (fallback to fastest race lap (no DRS data))
    example_lap = None
    
    try:
        print("Attempting to load qualifying session for track layout...")
        quali_session = load_session(year, round_number, 'Q')
        if quali_session is not None and len(quali_session.laps) > 0:
            fastest_quali = quali_session.laps.pick_fastest()
            if fastest_quali is not None:
                quali_telemetry = fastest_quali.get_telemetry()
                if 'DRS' in quali_telemetry.columns:
                    example_lap = quali_telemetry
                    print(f"Using qualifying lap from driver {fastest_quali['Driver']} for DRS Zones")
    except Exception as e:
        print(f"Could not load qualifying session: {e}")

    # fallback: Use fastest race lap
    if example_lap is None:
        try:
            fastest_lap = session.laps.pick_fastest() if session.laps is not None and not session.laps.empty else None
            if fastest_lap is not None:
                example_lap = fastest_lap.get_telemetry()
                print("Using fastest race lap (DRS detection may use speed-based fallback)")
            else:
                print("Error: No valid laps found in session")
                return
        except Exception as e:
            print(f"Error accessing race laps: {e}")
            return

    drivers = session.drivers

    # Get circuit rotation

    circuit_rotation = get_circuit_rotation(session)
    
    # Prepare session info for display banner
    session_info = {
        'event_name': session.event.get('EventName', ''),
        'circuit_name': session.event.get('Location', ''),  # Circuit location/name
        'country': session.event.get('Country', ''),
        'year': year,
        'round': round_number,
        'date': session.event.get('EventDate', '').strftime('%B %d, %Y') if session.event.get('EventDate') else '',
        'total_laps': race_telemetry['total_laps'],
        'circuit_length_m': float(example_lap["Distance"].max()) if example_lap is not None and "Distance" in example_lap else None,
    }

    # Launch insights menu (always shown with replay)
    launch_insights_menu()
    print("Launching insights menu...")

    # Run the arcade replay

    run_arcade_replay(
      frames=race_telemetry['frames'],
      track_statuses=race_telemetry['track_statuses'],
      example_lap=example_lap,
      drivers=drivers,
      playback_speed=playback_speed,
      driver_colors=race_telemetry['driver_colors'],
      title=f"{session.event['EventName']} - {'Sprint' if session_type == 'S' else 'Race'}",
      total_laps=race_telemetry['total_laps'],
      circuit_rotation=circuit_rotation,
      visible_hud=visible_hud,
      ready_file=ready_file,
      session_info=session_info,
      session=session,
      enable_telemetry=True,
      race_control_messages=race_telemetry.get('race_control_messages', [])
    )

if __name__ == "__main__":

  if "--verbose" not in sys.argv:# fastf1 logging is disabled by default
    logging.getLogger("fastf1").setLevel(logging.CRITICAL)

  if "--cli" in sys.argv:
    # Run the CLI
    cli_load()
    sys.exit(0)

  if "--year" in sys.argv:
    year_index = sys.argv.index("--year") + 1
    year = int(sys.argv[year_index])
  else:
    year = get_season()  # Default year

  if "--round" in sys.argv:
    round_index = sys.argv.index("--round") + 1
    round_number = int(sys.argv[round_index])
  else:
    round_number = 12  # Default round number

  if "--list-rounds" in sys.argv:
    list_rounds(year)
    sys.exit(0)

  if "--list-sprints" in sys.argv:
    list_sprints(year)
    sys.exit(0)

  playback_speed = 1

  if "--viewer" in sys.argv:
  
    visible_hud = True
    if "--no-hud" in sys.argv:
      visible_hud = False

    # Session type selection
    session_type = 'SQ' if "--sprint-qualifying" in sys.argv else ('S' if "--sprint" in sys.argv else ('Q' if "--qualifying" in sys.argv else 'R'))

    # Optional ready-file path used when spawned from the GUI to signal ready state
    ready_file = None
    if "--ready-file" in sys.argv:
      idx = sys.argv.index("--ready-file") + 1
      if idx < len(sys.argv):
        ready_file = sys.argv[idx]

    # Data source: 'auto' (FastF1, falling back to OpenF1), or force one.
    source = 'auto'
    if "--source" in sys.argv:
      idx = sys.argv.index("--source") + 1
      if idx < len(sys.argv):
        source = sys.argv[idx].lower()
      if source not in ('auto', 'fastf1', 'openf1'):
        print(f"Unknown --source '{source}'. Use auto, fastf1 or openf1.", file=sys.stderr)
        sys.exit(2)

    try:
      main(year, round_number, playback_speed, session_type=session_type, visible_hud=visible_hud, ready_file=ready_file,
           clear_cache="--clear-cache" in sys.argv, source=source)
    except (SessionDataUnavailable, OpenF1Error, openf1_data.OpenF1DataUnavailable) as e:
      print(f"\n{e}\n", file=sys.stderr)
      sys.exit(1)
    sys.exit(0)

  # Run the GUI

  app = QApplication(sys.argv)
  apply_f1_theme(app)          # Apply official F1 brand design system
  app.setApplicationName("F1 Race Replay")
  app.setApplicationVersion("1.0")
  win = RaceSelectionWindow()
  win.show()
  sys.exit(app.exec())