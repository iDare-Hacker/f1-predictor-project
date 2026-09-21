# F1 Winner Prediction — ML Module

Predicts Formula 1 race winner probabilities using a **RandomForestClassifier** trained on 4 seasons of historical FastF1 data.

---

## Features Used

| Feature | Description |
|---|---|
| `grid_position` | Starting grid position from qualifying |
| `quali_delta_to_pole` | Gap to pole position in seconds |
| `driver_rolling_avg_finish` | Driver's average finish in last 5 races |
| `constructor_rolling_avg_finish` | Team's average finish in last 5 races |
| `driver_circuit_podium_rate` | Driver's historical podium rate at this circuit |
| `starting_compound` | Tyre compound at race start (1=Soft … 5=Wet) |
| `is_wet` | 1 if qualifying was in wet conditions |
| `driver_encoded` | Integer-encoded driver identifier |
| `team_encoded` | Integer-encoded constructor |

**Target:** `podium` — binary, 1 if driver finished in top 3.

---

## Setup

```bash
cd f1-predictor-project
pip install -r ml/requirements.txt
```

---

## Step 1 — Train the Model

Fetches 2021–2024 race data from FastF1 (downloads ~1–2 GB on first run).

```bash
python ml/train_model.py
# Or for specific years:
python ml/train_model.py --years 2022 2023 2024
```

**Outputs:**
- `ml/model.pkl` — serialized RandomForestClassifier
- `ml/features.json` — feature column order
- `ml/historical_data.csv` — cached training data (speeds up re-trains)

---

## Step 2 — Predict a Race

```bash
# Predict winners for 2025 Round 18 (Singapore GP)
python ml/predict.py --year 2025 --round 18

# Show top 5 only
python ml/predict.py --year 2025 --round 18 --top 5

# Backtest: predict a historical race
python ml/predict.py --year 2024 --round 1
```

**Example Output:**
```
╭──────────────────────────────────────────────────────╮
│      F1 WINNER PREDICTION · 2025 · Round 18          │
╰──────────────────────────────────────────────────────╯

 Rank  Driver  Team                    Grid   Win Prob%  Podium%
 🥇    VER     Red Bull Racing         P1       24.3%    68.1%
 🥈    NOR     McLaren                 P2       19.7%    59.2%
 🥉    LEC     Ferrari                 P4       14.1%    48.3%
 4.    HAM     Ferrari                 P3       12.8%    41.9%
 5.    RUS     Mercedes                P5        8.2%    32.0%
```

---

## Model Details

- **Algorithm:** `RandomForestClassifier` (300 trees, `max_depth=8`, `class_weight='balanced'`)
- **Validation:** 5-fold stratified cross-validation
- **Metric:** ROC-AUC (typical: 0.78–0.85)

---

## Disclaimer

> ⚠️ This is a probabilistic model — F1 racing is inherently unpredictable.
> Predictions are for analytical/educational purposes only.
