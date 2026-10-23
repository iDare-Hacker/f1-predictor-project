# 🏎️ F1 Predictor Project

A live F1 race visualizer with a machine learning podium prediction model, built on the [OpenF1 API](https://openf1.org) and [FastF1](https://docs.fastf1.dev).

---

## 📁 Project Structure

```
f1-predictor-project/
├── live_visualizer/      # Live race dashboard (browser-based)
│   ├── index.html
│   ├── app.js
│   └── style.css
├── ml/                   # ML training & prediction pipeline
│   ├── train_model.py    # Train on 2021-2024 historical data
│   ├── predict.py        # Run predictions for any round
│   ├── model.pkl         # Pre-trained RandomForest model
│   └── features.json     # Feature list used by the model
├── f1-race-replay/       # Race replay GUI (desktop app)
│   ├── main.py
│   └── requirements.txt
└── requirements.txt      # Root-level Python dependencies
```

---

## ⚠️ Known issue: F1's timing archive requires auth (since ~14 Oct 2026)

`livetiming.formula1.com/static/...` now answers **HTTP 401** (a CloudFront edge rule).
That archive is FastF1's only source for historical timing data, and FastF1's own
mirror has no 2025/2026 files, so **any session not already in the local cache
cannot be loaded.** This is upstream — no change in this repo can restore the data.

| Component | Status |
|---|---|
| `live_visualizer/` | ✅ Unaffected — uses the public OpenF1 API |
| `ml/predict.py` | ⚠️ Works only for sessions in `ml/fastf1_cache/` |
| `ml/train_model.py` | ⚠️ Cannot fetch new seasons; existing `historical_data.csv` still trains |
| `f1-race-replay/` | ✅ Races/sprints 2023+ via OpenF1; other sessions need the cache |

**Workaround: the race replay can read from OpenF1 instead.** `api.openf1.org`
republishes the same live-timing feed, needs no credentials, and is unaffected.
The replay falls back to it automatically when FastF1 comes up empty:

```bash
python main.py --viewer --year 2026 --round 1              # auto: FastF1, then OpenF1
python main.py --viewer --year 2026 --round 1 --source openf1   # force OpenF1
python main.py --viewer --year 2026 --round 1 --source fastf1   # cache only
```

Limits of the OpenF1 path: **2023 onwards only**, race and sprint sessions only
(qualifying still needs FastF1's cache), and no per-lap DRS channel — the replay
uses its speed-based DRS detection instead. Track status is derived from race
control messages rather than a dedicated feed. A full race takes ~90 s to fetch
and is then cached in `computed_data/`.

Track upstream progress at
[Fast-F1#978](https://github.com/theOehrly/Fast-F1/issues/978) and
[f1-race-replay#354](https://github.com/IAmTomShaw/f1-race-replay/issues/354).

> **Do not delete `.fastf1-cache/` or `ml/fastf1_cache/`.** While the archive is
> gated, those directories hold the only replayable sessions. Cache clearing in the
> replay app is now opt-in via `--clear-cache` for this reason.

---

## ⚙️ Setup (for new contributors)

### 1. Clone the repo
```bash
git clone <repo-url>
cd f1-predictor-project
```

### 2. Create a Python virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate      # On Windows: .venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

To run the test suite, also install the dev dependencies:
```bash
pip install -r f1-race-replay/requirements-dev.txt
cd f1-race-replay && python -m pytest
```

---

## 🌐 Live Visualizer

Runs entirely in the browser — no backend needed.

```bash
cd live_visualizer
python3 -m http.server 8000
```

Then open **http://localhost:8000** in your browser.

> The visualizer connects to the public OpenF1 API and shows live driver positions, telemetry, race control messages, and pit stops during an active F1 session.

---

## 🤖 ML Model — Podium Prediction

The pre-trained model (`ml/model.pkl`) is already included. Just run predictions directly.

### Run a prediction
```bash
python ml/predict.py --year 2025 --round 18
```

### (Optional) Re-train the model
> ⚠️ **Do not delete `ml/historical_data.csv`.** While F1's archive returns 401 (see
> above) it cannot be re-downloaded, and it is gitignored — so there is no copy to
> restore from. Re-training on the existing CSV reproduces AUC 0.935 ± 0.016 in seconds.

```bash
python ml/train_model.py            # retrain on the existing CSV
python ml/train_model.py --years 2021 2022 2023 2024   # refetch (needs the archive)
```

**Training data:** 2021–2024 seasons (~1679 race entries)  
**Model AUC:** 0.935 ± 0.016 (cross-validated)

`ml/encoders.json` holds the driver/team → integer mapping the model was trained on.
`predict.py` needs it to encode categoricals the same way training did; without it,
predictions silently drift. `train_model.py` rewrites it on every run.

**Key features used:**
| Feature | Importance |
|---|---|
| Grid position | 36% |
| Quali delta to pole | 24% |
| Constructor rolling avg finish | 16% |
| Driver rolling avg finish | 12% |
| Team & driver encoding | 7% |

---

## 🎮 Race Replay (Desktop GUI)

A standalone desktop app to replay historical F1 sessions with telemetry overlays.

```bash
cd f1-race-replay
pip install -r requirements.txt
python main.py
```

> Requires a desktop environment (uses Tkinter GUI).

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `fastf1` | Historical race data & telemetry |
| `scikit-learn` | ML model training |
| `pandas` | Data processing |
| `requests` / `requests-cache` | API calls with caching |
| `tkinter` | Race replay GUI (included with Python) |
