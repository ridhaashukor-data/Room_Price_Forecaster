# 🏨 Room Price Forecaster

Hotel occupancy forecasting system with:
- FastAPI backend (`endpoint/endpoint.py`)
- Streamlit frontend (`frontend/frontend.py`)
- Single-day forecast + bulk Excel forecast
- Historical occupancy backtesting
- Optional MongoDB-backed history

---

## ✅ What this project does

### 1) Single-Day Forecast
Given current occupancy for a stay date (up to 30 days out), the system returns:
- Forecasted final occupancy
- Occupancy confidence metadata
- ADR recommendation and adjustment details
- Demand signal + warnings


### 2) Bulk Forecast (Excel)
You can:
- Download a template
- Fill occupancy values
- Upload it for forecasting
- Download output with current + forecast occupancy grid and conditional formatting


### 3) History (Optional, requires MongoDB)
If MongoDB is connected, the system stores:
- Single-day forecast history
- Bulk output files (latest records retained)

If MongoDB is not configured, forecasting still works; history endpoints return unavailable/offline messages.

### 4) Backtesting (MVP)
Run historical forecast evaluation and review:
- Overall metrics (MAE, RMSE, MAPE, bias)
- Accuracy bands (within ±3, ±5, ±10 occupancy points)
- Breakdown by day type and days-out
- Optional detailed row-level actual vs predicted output
- Support for user-uploaded raw booking CSV/XLSX data with manual column mapping
- Downloadable sample upload template (booking_id, stay_date, booking_date)
- Retrain completion-ratio datasets from built-in or uploaded data and set active dataset

### 5) Active Forecast Dataset Selection
- You can switch which completion-ratio dataset is active from the Backtesting tab.
- The active dataset is used by **Single-Day Forecast**, **Bulk Forecast**, and **Backtesting** calculations until changed again.
- The last active dataset is persisted and restored on API restart.

### 6) Uploaded Dataset Pairing (Backtesting Upload)
- Upload your own raw booking dataset.
- Follow the download template format before upload.
- Map stay_date and booking_date fields before running.
- booking_id is optional and used only for reference.

---

## 🧱 Tech Stack

- Python 3.10+
- FastAPI + Uvicorn
- Streamlit
- Pandas + OpenPyXL
- MongoDB (optional)

---

## 📁 Project Structure

```text
Room price forecaster/
├── backend/
│   ├── forecaster.py
│   ├── bulk_processor.py
│   ├── completion_model.py
│   ├── data/
│   │   └── completion_ratios.csv
│   └── data_generation/
│       ├── aggregated_data.py
│       ├── plot_booking_curve.py
│       ├── simulator.py
│       └── generated_data/
│           ├── aggregated_bookings.csv
│           └── simulated_raw_data.csv
├── endpoint/
│   ├── endpoint.py
│   └── API_DOCUMENTATION.md
├── frontend/
│   └── frontend.py
├── requirements.txt
├── .env
└── README.md
```

---

## ⚙️ Local Setup

1. Create/activate virtual environment.
2. Install dependencies:

```bash
venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 🔐 Environment Variables

Create/update `.env` in project root.

### Required for frontend/backend connection

```env
API_BASE_URL=http://localhost:8000
API_REQUEST_TIMEOUT=180
```

### Optional for history persistence

```env
MONGODB_ATLAS_CLUSTER_URI=your_mongodb_connection_string
```

Notes:
- `API_BASE_URL` is used by Streamlit to call FastAPI.
- If MongoDB URI is not set (or invalid), API still runs but history features are disabled.

---

## ▶️ Run the Project

Open **two terminals** from project root.

### Terminal 1: Start API

```bash
venv\Scripts\python.exe endpoint\endpoint.py
```

API URLs:
- Health: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`

### Terminal 2: Start Streamlit

```bash
venv\Scripts\streamlit run frontend\frontend.py
```

Frontend URL:
- `http://localhost:8501`

---

## 🌐 API Endpoints (Current)

Core:
- `GET /`
- `GET /health`
- `GET /options`
- `POST /forecast`
- `POST /backtest`
- `POST /backtest/upload/preview`
- `POST /backtest/upload/run`
- `GET /bulk/template`
- `POST /bulk/upload`

Single forecast history:
- `GET /single/history`
- `GET /single/history/{record_id}`
- `PATCH /single/history/{record_id}/note`
- `DELETE /single/history/{record_id}/note`

Bulk history:
- `GET /bulk/history`
- `GET /bulk/download/{record_id}`
- `DELETE /bulk/history/{record_id}`
- `DELETE /bulk/history?older_than_days=30&limit=500`

---

## 📤 Upload Limits & File Types

- Max upload size: **50 MB** per request
- `POST /bulk/upload`: `.xlsx`, `.xls`
- `POST /backtest/upload/preview`: `.csv`, `.xlsx`, `.xls`
- `POST /backtest/upload/run`: `.csv`, `.xlsx`, `.xls`
- Invalid file type returns `400`; oversized uploads return `413`

---

## 🧪 Quick Check

1. Run API and verify:
```bash
curl http://localhost:8000/health
```

2. Open Streamlit at `http://localhost:8501`.

3. Test:
- Single-day forecast tab
- Bulk template download/upload
- History sections (if MongoDB connected)

---

## 🛠️ Data Utilities (Optional)

Generate or rebuild completion ratios if needed:

```bash
venv\Scripts\python.exe backend\completion_model.py
```

Sample data generation scripts are in:
- `backend/data_generation/`

---

## 🐛 Troubleshooting

### API fails to start
- Ensure dependencies are installed.
- Ensure `backend/data/completion_ratios.csv` exists.
- If missing, run `backend/completion_model.py`.

### Frontend shows API connection error
- Confirm API is running on port 8000.
- Confirm `.env` has correct `API_BASE_URL`.

### History not available
- Check MongoDB URI in `.env`.
- API remains usable without MongoDB; only history is affected.

---

## 📌 Notes

- Forecast window is limited to 0–30 days out.
- Bulk processing forecasts occupancy only (not ADR pricing per row).
- Streamlit/Frontend and API must run simultaneously for full UI flow.
