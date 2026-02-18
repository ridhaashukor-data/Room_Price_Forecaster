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
  "total_rooms_available": 100
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
  "service": "Hotel Occupancy Forecasting API"
}
```

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
