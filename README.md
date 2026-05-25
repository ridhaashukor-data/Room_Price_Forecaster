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
- Input <img width="1531" height="929" alt="Single day input whole" src="https://github.com/user-attachments/assets/6147532d-b87d-43ae-b15e-287301a21643" />
- Output <img width="1183" height="925" alt="image" src="https://github.com/user-attachments/assets/091ebf33-2c2f-49eb-9549-9ad04e2a4ee1" />


### 2) Bulk Forecast (Excel)
You can:
- Download a template
- Fill occupancy values
- Upload it for forecasting
- Download output with current + forecast occupancy grid and conditional formatting
- Input <img width="665" height="775" alt="Bulk forecast input eg" src="https://github.com/user-attachments/assets/e8a4547b-ff87-4977-88b2-b07583a0d35a" />
- Output <img width="528" height="790" alt="Bulk forecast output eg" src="https://github.com/user-attachments/assets/c2954bcb-b925-429b-9384-8b438575e4ab" />


### 3) History (MongoDB)
If MongoDB is connected, the system stores:
- Single-day forecast history
- Bulk output files (latest records retained)
- If MongoDB is not configured, forecasting still works; history endpoints return unavailable/offline messages.
- <img width="1183" height="925" alt="Single history" src="https://github.com/user-attachments/assets/b63a8705-d292-4421-8683-1ebae1a36bb9" />


### 4) Backtesting (MVP)
Run historical forecast evaluation and review:
- Overall metrics (MAE, RMSE, MAPE, bias)
- Accuracy bands (within ±3, ±5, ±10 occupancy points)
- Breakdown by day type and days-out
- Optional detailed row-level actual vs predicted output
- Support for user-uploaded raw booking CSV/XLSX data with manual column mapping
- Downloadable sample upload template (booking_id, stay_date, booking_date)
- Retrain completion-ratio datasets from built-in or uploaded data and set active dataset
- MAE (Mean Absolute Error) is the average size of forecasting error. It means the prediction is off by an average of X.XX percentage points. Lower is better.
- RMSE (Root Mean Squared Error) also measure error size, but it penalize large error heavily. Lower is better.
- MAPE (Mean Absolute Percentage Error) measure the deviation from true OCC. Lower is better.
- Backtest result for built-in data <img width="1353" height="173" alt="Backtest result for built in data" src="https://github.com/user-attachments/assets/8629cd48-45e4-4b37-a82e-ad82dc103a6f" />


### 5) Active Forecast Dataset Selection
- You can switch which completion-ratio dataset is active from the Backtesting tab.
- The active dataset is used by **Single-Day Forecast**, **Bulk Forecast**, and **Backtesting** calculations until changed again.
- The last active dataset is persisted and restored on API restart.

### 6) Uploaded Dataset Pairing (Backtesting Upload)
- Upload your own raw booking dataset.
- Follow the download template format before upload.
- Map stay_date and booking_date fields before running.
- Dataset used can be changed to user data, which will affect calculation in the whole app.
- Data required for training <img width="259" height="102" alt="Data required for training" src="https://github.com/user-attachments/assets/5b2e35f4-5628-46fd-86c0-7ba6f1111be9" />


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
