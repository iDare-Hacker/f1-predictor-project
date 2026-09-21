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

### (Optional) Re-train the model on fresh data
> ⚠️ This takes ~30 mins due to API rate limits (500 calls/hour on the free tier).

```bash
rm ml/historical_data.csv   # Clear old cached data first
python ml/train_model.py
```

**Training data:** 2021–2024 seasons (~1679 race entries)  
**Model AUC:** 0.935 ± 0.016 (cross-validated)

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
