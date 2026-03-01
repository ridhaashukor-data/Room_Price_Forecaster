# Hotel Occupancy Forecasting API - Endpoints Documentation

## Starting the API Server

```bash
# Using venv
venv\Scripts\python.exe endpoint\endpoint.py

# Or using uvicorn directly
uvicorn endpoint.endpoint:app --reload --host 0.0.0.0 --port 8000
```

Server will run on: `http://localhost:8000`

Interactive API docs (Swagger UI): `http://localhost:8000/docs`

---

## API Endpoints

### 1. **Health Check**

**GET** `/`

Check if API is running.

**Response:**
```json
{
  "status": "success",
  "message": "Hotel Occupancy Forecasting API is running",
  "data": {
    "version": "1.0.0",
    "endpoints": [...]
  }
}
```

---

### 2. **Get Input Options**

**GET** `/options`

Get available options for event levels and sensitivity factors.

**Response:**
```json
{
  "status": "success",
  "data": {
    "event_levels": ["none", "minor", "major"],
    "sensitivity_factors": {
      "conservative": 0.3,
      "moderate": 0.5,
      "aggressive": 0.8
    },
    "default_price_cap": 12.0
  }
}
```

---

### 3. **Single-Day Forecast**

**POST** `/forecast`

Forecast occupancy and get pricing recommendations for a single date.

**Request Body:**
```json
{
  "stay_date": "150226",
  "today_date": "010226",
  "current_occupancy": 50.0,
  "current_adr": 280.0,
  "target_occupancy": 85.0,
  "sensitivity_factor": 0.5,
  "event_level": "none",
  "total_rooms_available": 100,
  "note": "Weekend city event expected"
}
```

**Response:**
```json
{
  "days_out": 14,
  "day_type": "weekend",
  "completion_ratio": 0.7523,
  "forecast_occupancy_pct": 66.5,
  "forecast_occupancy_rooms": 67,
  "confidence_level": "high",
  "sample_count": 245,
  "forecast_capped": false,
  "target_occupancy": 85.0,
  "current_adr": 280.0,
  "occupancy_gap": -18.5,
  "demand_signal": "Low Demand",
  "price_adjustment_pct": -9.25,
  "recommended_adr": 254.10,
  "price_change_amount": -25.90,
  "adjustment_capped": false,
  "price_cap_used": 12.0,
  "event_premium_applied": 0.0,
  "recommendation_text": "Decrease price by 9.25% to achieve target occupancy of 85.0%",
  "warnings": []
}
```

---

### 4. **Download Excel Template**

**GET** `/bulk/template`

Download the Excel template for bulk forecasting.

**Response:** Excel file download (`occupancy_template.xlsx`)

**Template Structure:**
- **Section 1**: Monthly Occupancy Targets (Jan-Dec)
- **Section 2**: Monthly ADR Budgets (Jan-Dec)
- **Section 3**: Total Rooms
- **Section 4**: Current Occupancy Grid (31 days x 12 months)

---

### 5. **Bulk Forecast Upload**

**POST** `/bulk/upload`

Upload filled Excel template and get forecast output.

**Request:**
- Form data with file upload
- Field name: `file`
- File type: `.xlsx` or `.xls`

**Response:** Excel file download with 2 sheets:
1. **Snapshot Sheet**: Current + Forecasted occupancy with conditional formatting
2. **Detailed Sheet**: All forecast fields for dates n=0 to n=30

**Processing:**
- Only forecasts dates from upload date to n=30
- Past dates ignored
- Zero occupancy dates skipped
- Fixed settings: k=0.5, event=none

---

### 6. **Health Check (Detailed)**

**GET** `/health`

Detailed health status.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-16T10:30:00",
  "completion_ratios_loaded": true,
  "mongodb_connected": true,
  "service": "Hotel Occupancy Forecasting API"
}
```

---

### 7. **Bulk Output History**

**GET** `/bulk/history?limit=20`

List previously generated bulk outputs stored in MongoDB.

**Retention policy:** bulk outputs are auto-pruned on every new upload to keep only the latest 5 records.

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "id": "67b70f8f7a8b0e5a1b2c3d4e",
      "created_at": "2026-02-20T10:24:11.123456",
      "input_filename": "occupancy_template_filled.xlsx",
      "output_filename": "forecast_output_20260220_102411.xlsx",
      "size_bytes": 84231
    }
  ]
}
```

---

### 7a. **Update Single-Day History Note**

**PATCH** `/single/history/{record_id}/note`

Update note text for one single-day history record.

**Request Body:**
```json
{
  "note": "Updated note text"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Single-day note updated",
  "data": {
    "updated_count": 1
  }
}
```

---

### 7b. **Delete Single-Day History Note**

**DELETE** `/single/history/{record_id}/note`

Clear note text for one single-day history record.

**Response:**
```json
{
  "status": "success",
  "message": "Single-day note deleted",
  "data": {
    "updated_count": 1
  }
}
```

---

### 8. **Download Past Bulk Output**

**GET** `/bulk/download/{record_id}`

Download one previously generated bulk output file by history record ID.

**Response:** Excel file download

---

### 9. **Delete One Bulk History Record**

**DELETE** `/bulk/history/{record_id}`

Delete a single stored bulk history item (including file bytes) by record ID.

**Response:**
```json
{
  "status": "success",
  "message": "Bulk history record deleted",
  "data": {
    "deleted_count": 1
  }
}
```

---

### 10. **Delete Old Bulk History Records**

**DELETE** `/bulk/history?older_than_days=30&limit=500`

Delete old bulk history records in batches to control storage growth.

- `older_than_days`: minimum age in days (default: `30`)
- `limit`: max records deleted in one call (default: `500`, max: `5000`)

**Response:**
```json
{
  "status": "success",
  "message": "Old bulk history records deleted",
  "data": {
    "deleted_count": 42,
    "older_than_days": 30,
    "applied_limit": 500
  }
}
```

---

### 11. **Run Backtesting**

**POST** `/backtest`

Run occupancy forecast backtesting using historical booking snapshots.

**Request Body:**
```json
{
  "total_rooms_available": 100,
  "start_date": "2024-01-01",
  "end_date": "2025-12-31",
  "day_type": "all",
  "days_out_min": 0,
  "days_out_max": 30,
  "include_details": true,
  "detail_limit": 500
}
```

**Response (example):**
```json
{
  "status": "success",
  "data": {
    "summary": {
      "count": 1000,
      "mae": 4.12,
      "rmse": 5.36,
      "mape": 6.04,
      "bias": -0.73,
      "within_3_pct": 41.2,
      "within_5_pct": 68.4,
      "within_10_pct": 93.1
    },
    "by_day_type": [],
    "by_days_out": [],
    "details": [],
    "input_filters": {},
    "dataset_stats": {}
  }
}
```

Notes:
- `day_type` supports: `all`, `weekday`, `weekend`
- `days_out_min/max` must stay in range `0-30`
- `start_date/end_date` format is `YYYY-MM-DD`

---

### 12. **Preview Uploaded Backtest File**

**POST** `/backtest/upload/preview`

Upload CSV/Excel and receive detected columns + sample rows to help with mapping.

**Request:**
- Form-data file field: `file`

**Response (example):**
```json
{
  "status": "success",
  "data": {
    "filename": "my_data.csv",
    "row_count": 3450,
    "column_count": 8,
    "columns": ["booking_id", "stay_date", "booking_date", "rooms_booked"],
    "sample_rows": []
  }
}
```

---

### 12a. **Download Upload Template**

**GET** `/backtest/upload/template`

Download a sample CSV template for custom backtesting uploads.

**Response:** CSV file download (`backtest_upload_template.csv`)

---

### 13. **Run Backtest With Uploaded Data**

**POST** `/backtest/upload/run`

Run backtest on uploaded **raw booking** CSV/Excel with explicit column mapping.

**Request:**
- Form-data file field: `file`
- Form-data text field: `mapping_json` (JSON string)
- Optional filters: `start_date`, `end_date`, `day_type`, `days_out_min`, `days_out_max`

**`mapping_json` example:**
```json
{
  "raw_data_mode": true,
  "stay_date_col": "stay_date",
  "booking_date_col": "booking_date",
  "rooms_per_row_col": "rooms_booked",
  "stay_date_format": "%Y-%m-%d",
  "booking_date_format": "%Y-%m-%d"
}
```

Notes:
- Only raw booking input is supported for uploaded backtesting
- `stay_date_col` and `booking_date_col` are required
- `rooms_per_row_col` is optional (if omitted, each row is treated as 1 room)
- System auto-aggregates raw rows into snapshot curves and computes final occupancy internally

---

## Testing with cURL

### Single-day forecast:
```bash
curl -X POST "http://localhost:8000/forecast" \
  -H "Content-Type: application/json" \
  -d '{
    "stay_date": "150226",
    "today_date": "010226",
    "current_occupancy": 50.0,
    "current_adr": 280.0,
    "target_occupancy": 85.0,
    "sensitivity_factor": 0.5,
    "event_level": "none",
    "total_rooms_available": 100
  }'
```

### Download template:
```bash
curl -O "http://localhost:8000/bulk/template"
```

### Upload for bulk forecast:
```bash
curl -X POST "http://localhost:8000/bulk/upload" \
  -F "file=@occupancy_template.xlsx" \
  --output forecast_output.xlsx
```

### Run backtest:
```bash
curl -X POST "http://localhost:8000/backtest" \
  -H "Content-Type: application/json" \
  -d '{
    "total_rooms_available": 100,
    "day_type": "all",
    "days_out_min": 0,
    "days_out_max": 30,
    "include_details": false,
    "detail_limit": 100
  }'
```

### Preview uploaded file for mapping:
```bash
curl -X POST "http://localhost:8000/backtest/upload/preview" \
  -F "file=@my_backtest_data.csv"
```

### Download upload template:
```bash
curl -O "http://localhost:8000/backtest/upload/template"
```

### Run uploaded backtest with mapping:
```bash
curl -X POST "http://localhost:8000/backtest/upload/run" \
  -F "file=@my_backtest_data.csv" \
  -F 'mapping_json={"raw_data_mode":true,"stay_date_col":"stay_date","booking_date_col":"booking_date","rooms_per_row_col":"rooms_booked","stay_date_format":"%Y-%m-%d","booking_date_format":"%Y-%m-%d"}'
```

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid date format: 1502. Expected format: DDMMYY (e.g., 150226)"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Error processing file: [error message]"
}
```

---

## Dependencies

- FastAPI
- Uvicorn
- Pydantic
- python-multipart (for file uploads)
- openpyxl (for Excel processing)
- pandas, numpy (for data processing)

Install all:
```bash
pip install -r requirements.txt
```
