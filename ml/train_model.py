"""
F1 Winner Prediction — Training Pipeline
==========================================
Trains a RandomForestClassifier to predict top-3 finishes (podium) using:
  - Grid position
  - Qualifying time delta to pole
  - Rolling driver form (avg finish, last 5 races)
  - Rolling constructor form (avg finish, last 5 races)
  - Circuit-specific driver win rate
  - Starting tyre compound (soft/medium/hard)
  - Weather (dry/wet)

Usage:
    cd f1-predictor-project
    python ml/train_model.py [--years 2021 2022 2023 2024] [--verbose]

Outputs:
    ml/model.pkl         - Trained RandomForestClassifier (joblib)
    ml/features.json     - Feature names used for inference
    ml/historical_data.csv - Cached training dataset
"""

import argparse
import json
import os
import sys
import requests
import warnings
warnings.filterwarnings('ignore')

# Patch requests.Session to always use a 15-second timeout,
# because FastF1 doesn't set one by default and hangs on dropped connections.
old_request = requests.Session.request
def new_request(*args, **kwargs):
    if 'timeout' not in kwargs or kwargs['timeout'] is None:
        kwargs['timeout'] = 15
    return old_request(*args, **kwargs)
requests.Session.request = new_request

import fastf1
import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ─────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH  = os.path.join(SCRIPT_DIR, 'model.pkl')
FEATURES_PATH = os.path.join(SCRIPT_DIR, 'features.json')
DATA_PATH   = os.path.join(SCRIPT_DIR, 'historical_data.csv')
CACHE_DIR   = os.path.join(SCRIPT_DIR, 'fastf1_cache')

COMPOUND_MAP = {
    'SOFT': 1, 'MEDIUM': 2, 'HARD': 3,
    'INTERMEDIATE': 4, 'WET': 5,
    'UNKNOWN': 0, None: 0,
}

FEATURE_COLS = [
    'grid_position',
    'quali_delta_to_pole',
    'driver_rolling_avg_finish',
    'constructor_rolling_avg_finish',
    'driver_circuit_podium_rate',
    'starting_compound',
    'is_wet',
    'driver_number',  # encoded
    'team_encoded',
]

TARGET_COL = 'podium'  # 1 = finished in top 3, 0 = did not

# ─────────────────────────────────────────────────────────
#  FASTF1 SETUP
# ─────────────────────────────────────────────────────────
def setup_fastf1():
    os.makedirs(CACHE_DIR, exist_ok=True)
    fastf1.Cache.enable_cache(CACHE_DIR)


# ─────────────────────────────────────────────────────────
#  DATA COLLECTION
# ─────────────────────────────────────────────────────────
def fetch_race_data(year: int, round_number: int) -> pd.DataFrame | None:
    """
    Fetch results for one race weekend.
    Returns a DataFrame with one row per driver.
    """
    try:
        # Load race session
        race = fastf1.get_session(year, round_number, 'R')
        race.load(telemetry=False, weather=True, laps=True)

        results = race.results[['DriverNumber', 'Abbreviation', 'TeamName',
                                  'GridPosition', 'Position', 'Status']].copy()
        results.columns = ['driver_number', 'driver_code', 'team',
                           'grid_position', 'finish_position', 'status']

        results['year']         = year
        results['round']        = round_number
        results['circuit']      = race.event.get('Location', 'Unknown')
        results['event_name']   = race.event.get('EventName', '')

        # Finish position: DNF → 20 (penalize)
        results['finish_position'] = pd.to_numeric(results['finish_position'], errors='coerce')
        results['finish_position'] = results['finish_position'].fillna(20).clip(upper=20)
        results['grid_position']   = pd.to_numeric(results['grid_position'], errors='coerce').fillna(20)

        # Target: top-3 finish
        results['podium'] = (results['finish_position'] <= 3).astype(int)

        # Starting tyre compound
        laps = race.laps
        first_laps = laps[laps['LapNumber'] == 1][['DriverNumber', 'Compound']].drop_duplicates('DriverNumber')
        first_laps['driver_number'] = first_laps['DriverNumber'].astype(str)
        results['driver_number'] = results['driver_number'].astype(str)
        results = results.merge(first_laps[['driver_number', 'Compound']].rename(
            columns={'Compound': 'starting_compound_str'}),
            on='driver_number', how='left')
        results['starting_compound'] = results['starting_compound_str'].map(
            lambda x: COMPOUND_MAP.get(str(x).upper(), 0))

        # Weather: is wet?
        weather = race.weather_data
        if weather is not None and not weather.empty and 'Rainfall' in weather.columns:
            rain_vals = pd.to_numeric(weather['Rainfall'], errors='coerce').fillna(0)
            results['is_wet'] = int(rain_vals.mean() > 0.3)
        else:
            results['is_wet'] = 0

        # Qualifying time delta
        try:
            quali = fastf1.get_session(year, round_number, 'Q')
            quali.load(telemetry=False, weather=False, laps=True)
            q_results = quali.results[['DriverNumber', 'Q3', 'Q2', 'Q1']].copy()
            q_results['driver_number'] = q_results['DriverNumber'].astype(str)

            def best_q_time(row):
                for col in ['Q3', 'Q2', 'Q1']:
                    t = row.get(col)
                    if pd.notna(t):
                        return t.total_seconds() if hasattr(t, 'total_seconds') else float(t)
                return None

            q_results['q_time_s'] = q_results.apply(best_q_time, axis=1)
            pole_time = q_results['q_time_s'].min()
            q_results['quali_delta_to_pole'] = q_results['q_time_s'] - pole_time
            results = results.merge(
                q_results[['driver_number', 'quali_delta_to_pole']],
                on='driver_number', how='left')
        except Exception:
            results['quali_delta_to_pole'] = np.nan

        results['quali_delta_to_pole'] = results['quali_delta_to_pole'].fillna(
            results['quali_delta_to_pole'].median() if not results['quali_delta_to_pole'].isna().all() else 5.0
        )

        print(f"  ✓ {year} R{round_number:02d} {results['event_name'].iloc[0]} — {len(results)} drivers")
        return results

    except Exception as e:
        if "RateLimitExceededError" in str(type(e)):
            raise e
        print(f"  ✗ {year} R{round_number:02d} — {e}")
        return None


def collect_all_data(years: list[int], verbose: bool = False) -> pd.DataFrame:
    """
    Iterates over all rounds for the given years and collects race results.
    """
    all_dfs = []
    hit_rate_limit = False

    for year in years:
        if hit_rate_limit:
            break
            
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as e:
            print(f"\n[{year}] Failed to get schedule: {e}")
            print("Stopping data collection due to rate limit/error.")
            break
            
        race_rounds = schedule['RoundNumber'].tolist()
        print(f"\n[{year}] Found {len(race_rounds)} rounds")

        for rnd in race_rounds:
            try:
                df = fetch_race_data(year, rnd)
                if df is not None and not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                print(f"  ✗ {year} R{rnd:02d} — Stopped collection: {e}")
                hit_rate_limit = True
                break

    if not all_dfs:
        raise RuntimeError("No data collected — check FastF1 connectivity")

    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"\n📊 Total rows collected: {len(combined)}")
    return combined


# ─────────────────────────────────────────────────────────
#  FEATURE ENGINEERING
# ─────────────────────────────────────────────────────────
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add rolling statistics and circuit-specific features.
    Operates on data sorted chronologically (year, round).
    """
    df = df.sort_values(['year', 'round', 'driver_number']).copy()

    # ── 1. Encode categorical columns ──
    le_driver = LabelEncoder()
    le_team   = LabelEncoder()
    df['driver_encoded'] = le_driver.fit_transform(df['driver_code'].fillna('UNKNOWN'))
    df['team_encoded']   = le_team.fit_transform(df['team'].fillna('Unknown'))

    # ── 2. Rolling driver avg finish (last 5 races, per driver) ──
    df['driver_rolling_avg_finish'] = (
        df.groupby('driver_code')['finish_position']
        .transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        .fillna(10.0)
    )

    # ── 3. Rolling constructor avg finish (last 5 races, per team) ──
    df['constructor_rolling_avg_finish'] = (
        df.groupby('team')['finish_position']
        .transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        .fillna(10.0)
    )

    # ── 4. Circuit-specific driver podium rate (historical) ──
    circuit_podium = (
        df.groupby(['circuit', 'driver_code'])
        .apply(lambda g: g['podium'].shift(1).expanding().mean(), include_groups=False)
        .reset_index(level=[0, 1], drop=True)
    )
    df['driver_circuit_podium_rate'] = circuit_podium.fillna(0.15)

    return df


# ─────────────────────────────────────────────────────────
#  TRAIN MODEL
# ─────────────────────────────────────────────────────────
def train(df: pd.DataFrame) -> tuple:
    """Train and evaluate a RandomForestClassifier."""

    df = engineer_features(df)

    # Use only fully numeric features
    feature_cols = [
        'grid_position',
        'quali_delta_to_pole',
        'driver_rolling_avg_finish',
        'constructor_rolling_avg_finish',
        'driver_circuit_podium_rate',
        'starting_compound',
        'is_wet',
        'driver_encoded',
        'team_encoded',
    ]

    X = df[feature_cols].fillna(0).values
    y = df[TARGET_COL].values

    print(f"\n🏁 Training on {len(X)} samples | {y.sum()} podiums | {(y==0).sum()} non-podiums")
    print(f"   Class balance: {y.mean()*100:.1f}% podiums")

    # ── Model: RandomForest with class weighting ──
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=5,
        class_weight='balanced',
        random_state=42,
        n_jobs=-1,
    )

    # ── Cross-validation ──
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X, y, cv=cv, scoring='roc_auc', n_jobs=-1)
    print(f"\n📈 Cross-validation AUC: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # ── Final fit on all data ──
    model.fit(X, y)

    # ── Feature importances ──
    importances = sorted(zip(feature_cols, model.feature_importances_),
                         key=lambda x: x[1], reverse=True)
    print("\n🔍 Feature Importances:")
    for feat, imp in importances:
        bar = '█' * int(imp * 40)
        print(f"   {feat:<38} {imp:.4f}  {bar}")

    return model, feature_cols, df


# ─────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='Train F1 Winner Prediction Model',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--years', nargs='+', type=int,
                        default=[2021, 2022, 2023, 2024],
                        help='Season years to include in training data')
    parser.add_argument('--verbose', action='store_true',
                        help='Enable FastF1 verbose logging')
    args = parser.parse_args()

    if not args.verbose:
        import logging
        logging.getLogger('fastf1').setLevel(logging.ERROR)

    print("=" * 60)
    print("  F1 WINNER PREDICTION — TRAINING PIPELINE")
    print("=" * 60)
    print(f"  Years: {args.years}")
    print(f"  Output: {MODEL_PATH}")
    print("=" * 60)

    setup_fastf1()

    # ── Load or collect data ──
    if os.path.exists(DATA_PATH):
        print(f"\n📂 Loading cached data from {DATA_PATH}")
        df = pd.read_csv(DATA_PATH)
        print(f"   {len(df)} rows loaded")
    else:
        print("\n📡 Fetching data from FastF1…")
        df = collect_all_data(args.years)
        if df is None or df.empty:
            print("\n❌ No data collected. Cannot train model. (Did you hit the rate limit?)")
            return
            
        df.to_csv(DATA_PATH, index=False)
        print(f"\n💾 Data saved to {DATA_PATH}")

    # ── Train ──
    model, feature_cols, df_with_features = train(df)

    # ── Save model + feature list ──
    joblib.dump(model, MODEL_PATH)
    with open(FEATURES_PATH, 'w') as f:
        json.dump(feature_cols, f, indent=2)

    print(f"\n✅ Model saved → {MODEL_PATH}")
    print(f"✅ Features saved → {FEATURES_PATH}")
    print("\nRun predictions with:")
    print("  python ml/predict.py --year 2025 --round 18")


if __name__ == '__main__':
    main()
