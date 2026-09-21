"""
F1 Winner Prediction — CLI Predictor
======================================
Loads the trained model and predicts podium probabilities for
a specific race using the current qualifying results.

Usage:
    cd f1-predictor-project
    python ml/predict.py --year 2025 --round 18
    python ml/predict.py --year 2024 --round 1 --session R
    python ml/predict.py --year 2025 --round 18 --top 5

Requirements:
    Run ml/train_model.py first to generate model.pkl and features.json
"""

import argparse
import json
import os
import sys
import warnings
warnings.filterwarnings('ignore')

import fastf1
import numpy as np
import pandas as pd
import joblib

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("[Note] Install 'rich' for better output: pip install rich")

# ─────────────────────────────────────────────────────────
#  PATHS
# ─────────────────────────────────────────────────────────
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH    = os.path.join(SCRIPT_DIR, 'model.pkl')
FEATURES_PATH = os.path.join(SCRIPT_DIR, 'features.json')
DATA_PATH     = os.path.join(SCRIPT_DIR, 'historical_data.csv')
CACHE_DIR     = os.path.join(SCRIPT_DIR, 'fastf1_cache')

COMPOUND_MAP = {
    'SOFT': 1, 'MEDIUM': 2, 'HARD': 3,
    'INTERMEDIATE': 4, 'WET': 5,
    'UNKNOWN': 0, None: 0,
}

# ─────────────────────────────────────────────────────────
#  TEAM COLORS (for rich output)
# ─────────────────────────────────────────────────────────
TEAM_COLORS = {
    'Red Bull Racing':   'bright_blue',
    'Ferrari':           'red',
    'Mercedes':          'cyan',
    'McLaren':           'bright_yellow',
    'Aston Martin':      'green',
    'Alpine':            'bright_blue',
    'Williams':          'blue',
    'RB':                'bright_blue',
    'Kick Sauber':       'green',
    'Haas F1 Team':      'white',
}

# ─────────────────────────────────────────────────────────
#  SETUP
# ─────────────────────────────────────────────────────────
def setup():
    os.makedirs(CACHE_DIR, exist_ok=True)
    fastf1.Cache.enable_cache(CACHE_DIR)

    if not os.path.exists(MODEL_PATH):
        print("❌ No trained model found!")
        print("   Run: python ml/train_model.py first")
        sys.exit(1)


# ─────────────────────────────────────────────────────────
#  BUILD FEATURES FOR ONE RACE
# ─────────────────────────────────────────────────────────
def build_features(year: int, round_number: int) -> pd.DataFrame:
    """
    Builds the feature vector for each driver in the upcoming/selected race.
    Uses qualifying results + historical rolling stats from historical_data.csv.
    """
    print(f"\n📡 Loading qualifying session: {year} Round {round_number}…")

    # Load qualifying
    try:
        quali = fastf1.get_session(year, round_number, 'Q')
        quali.load(telemetry=False, weather=True, laps=True)
    except Exception as e:
        print(f"❌ Could not load qualifying: {e}")
        sys.exit(1)

    results = quali.results[[
        'DriverNumber', 'Abbreviation', 'TeamName', 'GridPosition', 'Q1', 'Q2', 'Q3'
    ]].copy()
    results.columns = ['driver_number', 'driver_code', 'team', 'grid_position', 'Q1', 'Q2', 'Q3']
    results['driver_number'] = results['driver_number'].astype(str)
    results['grid_position'] = pd.to_numeric(results['grid_position'], errors='coerce').fillna(20)

    # Qualifying delta to pole
    def best_q_time(row):
        for col in ['Q3', 'Q2', 'Q1']:
            t = row.get(col)
            if pd.notna(t):
                return t.total_seconds() if hasattr(t, 'total_seconds') else float(t)
        return None

    results['q_time_s'] = results.apply(best_q_time, axis=1)
    pole_time = results['q_time_s'].min()
    results['quali_delta_to_pole'] = (results['q_time_s'] - pole_time).fillna(5.0)

    # Weather
    weather = quali.weather_data
    if weather is not None and not weather.empty and 'Rainfall' in weather.columns:
        rain_vals = pd.to_numeric(weather['Rainfall'], errors='coerce').fillna(0)
        is_wet = int(rain_vals.mean() > 0.3)
    else:
        is_wet = 0
    results['is_wet'] = is_wet

    # Starting compound (predict from softest available in quali)
    results['starting_compound'] = 1  # assume SOFT for sprint/race start

    # Load historical data for rolling stats
    hist_df = None
    if os.path.exists(DATA_PATH):
        hist_df = pd.read_csv(DATA_PATH)

    if hist_df is not None and not hist_df.empty:
        # Rolling driver form (last 5 races)
        driver_form = (
            hist_df.groupby('driver_code')['finish_position']
            .apply(lambda s: s.tail(5).mean())
            .fillna(10.0)
            .to_dict()
        )
        # Rolling constructor form
        constructor_form = (
            hist_df.groupby('team')['finish_position']
            .apply(lambda s: s.tail(5).mean())
            .fillna(10.0)
            .to_dict()
        )
        # Circuit podium rate
        circuit = quali.event.get('Location', 'Unknown')
        circ_data = hist_df[hist_df['circuit'] == circuit] if 'circuit' in hist_df.columns else pd.DataFrame()
        if not circ_data.empty:
            driver_circuit_pod = (
                circ_data.groupby('driver_code')['podium']
                .mean()
                .fillna(0.15)
                .to_dict()
            )
        else:
            driver_circuit_pod = {}
    else:
        driver_form       = {}
        constructor_form  = {}
        driver_circuit_pod = {}

    results['driver_rolling_avg_finish']       = results['driver_code'].map(driver_form).fillna(10.0)
    results['constructor_rolling_avg_finish']  = results['team'].map(constructor_form).fillna(10.0)
    results['driver_circuit_podium_rate']      = results['driver_code'].map(driver_circuit_pod).fillna(0.15)

    # Encode driver/team as integers (simple hash for inference)
    results['driver_encoded'] = results['driver_code'].apply(lambda x: abs(hash(x)) % 100)
    results['team_encoded']   = results['team'].apply(lambda x: abs(hash(x)) % 50)

    return results


# ─────────────────────────────────────────────────────────
#  PREDICT
# ─────────────────────────────────────────────────────────
def predict(year: int, round_number: int, top_n: int = 10) -> pd.DataFrame:
    """Run predictions and return results sorted by win probability."""

    with open(FEATURES_PATH) as f:
        feature_cols = json.load(f)

    model = joblib.load(MODEL_PATH)

    df = build_features(year, round_number)

    # Align to training features
    X = df[feature_cols].fillna(0).values

    proba = model.predict_proba(X)
    # Column 1 = probability of podium (class 1)
    podium_proba = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]

    df['podium_probability'] = podium_proba
    df['win_probability'] = podium_proba * (1.0 / (df['grid_position'].clip(lower=1) ** 0.3))
    # Normalize win probability to sum to 1
    total = df['win_probability'].sum()
    if total > 0:
        df['win_probability'] = df['win_probability'] / total

    df = df.sort_values('win_probability', ascending=False).reset_index(drop=True)
    return df.head(top_n)


# ─────────────────────────────────────────────────────────
#  OUTPUT
# ─────────────────────────────────────────────────────────
def print_rich_results(df: pd.DataFrame, year: int, round_number: int):
    """Pretty-print predictions with rich tables."""
    console = Console()

    console.print()
    console.print(Panel.fit(
        f"[bold red]F1 WINNER PREDICTION[/bold red]\n"
        f"[dim]{year} · Round {round_number}[/dim]",
        border_style="red",
        padding=(0, 4),
    ))
    console.print()

    table = Table(
        box=box.ROUNDED,
        border_style="dim",
        header_style="bold white",
        show_edge=True,
        padding=(0, 1),
    )

    table.add_column("🏆 Rank",       style="bold yellow", justify="center", width=7)
    table.add_column("Driver",         style="bold white",  justify="left",   width=8)
    table.add_column("Team",           style="dim",         justify="left",   width=22)
    table.add_column("Grid",           style="cyan",        justify="center", width=6)
    table.add_column("Win Prob %",     style="bold",        justify="right",  width=11)
    table.add_column("Podium Prob %",  style="green",       justify="right",  width=13)
    table.add_column("Form (5)",       style="yellow",      justify="right",  width=10)
    table.add_column("Δ Pole (s)",     style="dim",         justify="right",  width=10)

    MEDALS = ['🥇', '🥈', '🥉']
    BAR_CHARS = '█▉▊▋▌▍▎▏'

    for i, row in df.iterrows():
        rank   = i + 1
        medal  = MEDALS[i] if i < 3 else f" {rank}."
        code   = str(row.get('driver_code', '???'))
        team   = str(row.get('team', ''))
        grid   = str(int(row.get('grid_position', 0)))
        win_p  = row.get('win_probability', 0) * 100
        pod_p  = row.get('podium_probability', 0) * 100
        form   = row.get('driver_rolling_avg_finish', 10)
        delta  = row.get('quali_delta_to_pole', 0)

        # Win probability bar
        bar_len = int(win_p / 5)
        bar = '█' * min(bar_len, 20)

        team_color = TEAM_COLORS.get(team, 'white')
        win_style  = 'bold green' if win_p > 20 else ('green' if win_p > 10 else 'yellow')

        table.add_row(
            medal,
            f"[bold]{code}[/bold]",
            f"[{team_color}]{team}[/{team_color}]",
            f"P{grid}",
            f"[{win_style}]{win_p:.1f}%[/{win_style}]  {bar}",
            f"{pod_p:.1f}%",
            f"{form:.1f}",
            f"+{delta:.3f}",
        )

    console.print(table)
    console.print()
    console.print(
        "[dim]Model: RandomForestClassifier · Features: grid pos, quali delta, "
        "rolling form, circuit history, weather[/dim]"
    )
    console.print(
        "[dim]⚠ Predictions are probabilistic — F1 has infinite variables![/dim]\n"
    )


def print_plain_results(df: pd.DataFrame, year: int, round_number: int):
    """Fallback plain text output."""
    print(f"\n{'='*60}")
    print(f"  F1 WINNER PREDICTION — {year} Round {round_number}")
    print(f"{'='*60}")
    print(f"{'Rank':<5} {'Driver':<8} {'Team':<22} {'Grid':<6} {'WinProb':>9} {'PodiumProb':>11}")
    print("-" * 60)
    for i, row in df.iterrows():
        rank  = i + 1
        code  = str(row.get('driver_code', '???'))
        team  = str(row.get('team', ''))[:21]
        grid  = int(row.get('grid_position', 0))
        wp    = row.get('win_probability', 0) * 100
        pp    = row.get('podium_probability', 0) * 100
        print(f"{rank:<5} {code:<8} {team:<22} P{grid:<5} {wp:>8.1f}% {pp:>10.1f}%")
    print("=" * 60)


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='Predict F1 race winner probabilities',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--year',  type=int, required=True, help='Season year, e.g. 2025')
    parser.add_argument('--round', type=int, required=True, help='Race round number, e.g. 18')
    parser.add_argument('--top',   type=int, default=10,   help='Number of drivers to show')
    parser.add_argument('--verbose', action='store_true', help='Enable FastF1 logging')
    args = parser.parse_args()

    if not args.verbose:
        import logging
        logging.getLogger('fastf1').setLevel(logging.ERROR)

    setup()

    results = predict(args.year, args.round, args.top)

    if RICH_AVAILABLE:
        print_rich_results(results, args.year, args.round)
    else:
        print_plain_results(results, args.year, args.round)


if __name__ == '__main__':
    main()
