"""
Hotel Occupancy Forecasting API

FastAPI endpoints for:
1. Single-day forecasting
2. Bulk Excel processing
3. Template generation
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any
from contextlib import asynccontextmanager
import os
import sys
from datetime import datetime, timedelta
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from forecaster import (
    forecast_and_price,
    load_completion_ratios,
    get_input_options
)
from bulk_processor import (
    generate_template,
    process_bulk_forecast
)

# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================

# Global completion ratios
completion_ratios_df = None
mongo_client = None
mongo_db = None
mongo_connected = False
MAX_BULK_HISTORY_RECORDS = 5


def _get_mongodb_uri() -> Optional[str]:
    """Read MongoDB connection URI from environment variables."""
    uri = os.getenv("MONGODB_ATLAS_CLUSTER_URI") or os.getenv("MONGODB_URI")
    if not uri:
        return None
    if "<" in uri and ">" in uri:
        return None
    return uri


def _to_mongo_compatible(value: Any) -> Any:
    """Convert nested values to MongoDB-compatible Python primitives."""
    if isinstance(value, dict):
        return {k: _to_mongo_compatible(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_to_mongo_compatible(item) for item in value]

    if value is None or isinstance(value, (str, int, float, bool, bytes, datetime, ObjectId)):
        return value

    if hasattr(value, "item"):
        try:
            return _to_mongo_compatible(value.item())
        except Exception:
            pass

    return str(value)


def _persist_single_forecast(input_payload: dict, output_payload: dict) -> None:
    """Persist single-day forecast request and response to MongoDB."""
    if not mongo_db:
        return

    document = {
        "created_at": datetime.utcnow(),
        "source": "api_forecast",
        "input": _to_mongo_compatible(input_payload),
        "output": _to_mongo_compatible(output_payload),
    }
    mongo_db["single_day_forecasts"].insert_one(document)


def _persist_bulk_run(filename: str, output_filename: str, output_bytes: bytes) -> None:
    """Persist bulk forecast processing metadata to MongoDB."""
    if not mongo_db:
        return

    document = {
        "created_at": datetime.utcnow(),
        "source": "api_bulk_upload",
        "input_filename": filename,
        "output_filename": output_filename,
        "output_file_bytes": output_bytes,
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "size_bytes": len(output_bytes),
    }
    mongo_db["bulk_forecasts"].insert_one(document)


def _enforce_bulk_history_retention(max_records: int = MAX_BULK_HISTORY_RECORDS) -> None:
    """Keep only the most recent bulk history records in MongoDB."""
    if not mongo_db:
        return

    records_to_remove = list(
        mongo_db["bulk_forecasts"]
        .find({}, {"_id": 1})
        .sort("created_at", -1)
        .skip(max_records)
    )

    if not records_to_remove:
        return

    ids_to_remove = [record["_id"] for record in records_to_remove]
    mongo_db["bulk_forecasts"].delete_many({"_id": {"$in": ids_to_remove}})

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load completion ratios on startup, cleanup on shutdown"""
    global completion_ratios_df, mongo_client, mongo_db, mongo_connected

    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(dotenv_path=env_path)

    try:
        completion_ratios_df = load_completion_ratios()
        print("✅ Completion ratios loaded successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not load completion ratios: {e}")

    try:
        mongodb_uri = _get_mongodb_uri()
        if mongodb_uri:
            mongo_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
            mongo_client.admin.command("ping")
            mongo_db = mongo_client["room_price_forecaster"]
            mongo_connected = True
            print("✅ MongoDB connected successfully")
        else:
            mongo_connected = False
            print("⚠️  Warning: MongoDB URI missing or still uses placeholder format")
    except Exception as e:
        mongo_connected = False
        mongo_client = None
        mongo_db = None
        print(f"⚠️  Warning: MongoDB connection failed: {e}")
    
    yield
    
    # Cleanup (if needed)
    if mongo_client:
        mongo_client.close()
    print("🔄 Shutting down...")

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class SingleDayInput(BaseModel):
    """Input model for single-day forecasting"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "stay_date": "150226",
                "today_date": "010226",
                "current_occupancy": 50.0,
                "current_adr": 280.0,
                "target_occupancy": 85.0,
                "sensitivity_factor": 0.5,
                "event_level": "none",
                "total_rooms_available": 100
            }
        }
    )
    
    stay_date: str = Field(..., description="Stay date in DDMMYY format (e.g., '150226')")
    today_date: str = Field(..., description="Today's date in DDMMYY format (e.g., '010226')")
    current_occupancy: float = Field(..., ge=0, le=100, description="Current occupancy percentage (0-100)")
    current_adr: float = Field(..., gt=0, description="Current ADR in RM")
    target_occupancy: float = Field(..., ge=0, le=100, description="Target occupancy percentage (0-100)")
    sensitivity_factor: float = Field(..., description="Sensitivity factor (0.3, 0.5, or 0.8)")
    event_level: str = Field(..., description="Event level: 'none', 'minor', or 'major'")
    total_rooms_available: int = Field(..., gt=0, description="Total rooms available")


class ForecastOutput(BaseModel):
    """Output model for single-day forecast"""
    days_out: int
    day_type: str
    completion_ratio: float
    forecast_occupancy_pct: float
    forecast_occupancy_rooms: int
    confidence_level: str
    sample_count: int
    forecast_capped: bool
    target_occupancy: float
    current_adr: float
    occupancy_gap: float
    demand_signal: str
    price_adjustment_pct: float
    recommended_adr: float
    price_change_amount: float
    adjustment_capped: bool
    price_cap_used: float
    event_premium_applied: float
    recommendation_text: str
    warnings: List[str]


class StatusResponse(BaseModel):
    """Generic status response"""
    status: str
    message: str
    data: Optional[dict] = None


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Hotel Occupancy Forecasting API",
    description="API for forecasting hotel occupancy and pricing recommendations",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/", response_model=StatusResponse)
async def root():
    """API health check"""
    return StatusResponse(
        status="success",
        message="Hotel Occupancy Forecasting API is running",
        data={
            "version": "1.0.0",
            "endpoints": [
                "/forecast - Single-day forecast",
                "/bulk/upload - Bulk Excel processing",
                "/bulk/template - Download template",
                "/options - Get input options"
            ]
        }
    )


@app.get("/options")
async def get_options():
    """Get available input options (event levels, sensitivity factors)"""
    try:
        options = get_input_options()
        return JSONResponse(content={
            "status": "success",
            "data": options
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/forecast", response_model=ForecastOutput)
async def single_day_forecast(input_data: SingleDayInput):
    """
    Single-day occupancy forecast and pricing recommendation
    
    Takes current occupancy data and returns:
    - Forecasted final occupancy
    - Recommended pricing adjustments
    - Warnings and alerts
    """
    try:
        # Convert Pydantic model to dict
        inputs = input_data.model_dump()
        
        # Run forecast
        result = forecast_and_price(inputs, completion_ratios_df)
        try:
            _persist_single_forecast(inputs, result)
        except Exception as db_error:
            print(f"⚠️  Warning: Could not persist single forecast: {db_error}")
        
        return ForecastOutput(**result)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/bulk/template")
async def download_template():
    """
    Download Excel template for bulk forecasting
    
    Returns an Excel file with:
    - Monthly target inputs
    - Monthly ADR budget inputs
    - Current occupancy grid (31 days x 12 months)
    """
    try:
        # Generate template in temp directory
        temp_dir = tempfile.gettempdir()
        template_path = generate_template(output_dir=temp_dir)
        
        if not os.path.exists(template_path):
            raise HTTPException(status_code=500, detail="Template generation failed")
        
        return FileResponse(
            path=template_path,
            filename="occupancy_template.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating template: {str(e)}")


@app.post("/bulk/upload")
async def bulk_forecast_upload(file: UploadFile = File(...)):
    """
    Upload Excel file for bulk forecasting
    
    Accepts filled template and returns:
    - Excel file with 2 sheets (Snapshot + Detailed forecast)
    
    Process:
    1. Parse uploaded Excel
    2. Run forecasts for n=0 to n=30 from upload date
    3. Generate output Excel with conditional formatting
    """
    try:
        # Validate file type
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(
                status_code=400, 
                detail="Invalid file type. Please upload an Excel file (.xlsx or .xls)"
            )
        
        # Save uploaded file to temp location
        temp_dir = tempfile.gettempdir()
        input_path = os.path.join(temp_dir, f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        
        with open(input_path, 'wb') as f:
            f.write(await file.read())
        
        # Process bulk forecast using same ratios object as single-day endpoint
        output_path = process_bulk_forecast(
            input_path,
            output_dir=temp_dir,
            completion_ratios_df=completion_ratios_df
        )
        
        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="Forecast processing failed")

        output_filename = os.path.basename(output_path)
        with open(output_path, "rb") as f:
            output_bytes = f.read()

        try:
            _persist_bulk_run(file.filename, output_filename, output_bytes)
            _enforce_bulk_history_retention()
        except Exception as db_error:
            print(f"⚠️  Warning: Could not persist bulk forecast metadata: {db_error}")
        
        # Return output file
        return Response(
            content=output_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={output_filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.get("/health")
async def health_check():
    """Detailed health check with system status"""
    return JSONResponse(content={
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "completion_ratios_loaded": completion_ratios_df is not None,
        "mongodb_connected": mongo_connected,
        "service": "Hotel Occupancy Forecasting API"
    })


@app.get("/single/history")
async def single_history(limit: int = 20):
    """List previously generated single-day forecast records saved in MongoDB."""
    if not mongo_db:
        return JSONResponse(
            content={
                "status": "success",
                "message": "MongoDB is not connected; single-day history is unavailable.",
                "data": [],
            }
        )

    limit = max(1, min(limit, 200))
    records = list(
        mongo_db["single_day_forecasts"]
        .find(
            {},
            {
                "created_at": 1,
                "input": 1,
                "output": 1,
            },
        )
        .sort("created_at", -1)
        .limit(limit)
    )

    history_items = []
    for record in records:
        created_at = record.get("created_at")
        input_payload = record.get("input") or {}
        output_payload = record.get("output") or {}
        history_items.append(
            {
                "id": str(record.get("_id")),
                "created_at": created_at.isoformat() if created_at else None,
                "stay_date": input_payload.get("stay_date"),
                "today_date": input_payload.get("today_date"),
                "event_level": input_payload.get("event_level"),
                "forecast_occupancy_pct": output_payload.get("forecast_occupancy_pct"),
                "recommended_adr": output_payload.get("recommended_adr"),
                "demand_signal": output_payload.get("demand_signal"),
            }
        )

    return JSONResponse(
        content={
            "status": "success",
            "data": history_items,
        }
    )


@app.get("/single/history/{record_id}")
async def single_history_detail(record_id: str):
    """Get one previously generated single-day forecast record by ID."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    try:
        object_id = ObjectId(record_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid record id")

    record = mongo_db["single_day_forecasts"].find_one(
        {"_id": object_id},
        {"created_at": 1, "input": 1, "output": 1, "source": 1},
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    created_at = record.get("created_at")
    return JSONResponse(
        content={
            "status": "success",
            "data": {
                "id": str(record.get("_id")),
                "created_at": created_at.isoformat() if created_at else None,
                "source": record.get("source"),
                "input": record.get("input") or {},
                "output": record.get("output") or {},
            },
        }
    )


@app.get("/bulk/history")
async def bulk_history(limit: int = 20):
    """List previously generated bulk forecast outputs saved in MongoDB."""
    if not mongo_db:
        return JSONResponse(
            content={
                "status": "success",
                "message": "MongoDB is not connected; bulk history is unavailable.",
                "data": [],
            }
        )

    limit = max(1, min(limit, 200))
    records = list(
        mongo_db["bulk_forecasts"]
        .find(
            {},
            {
                "input_filename": 1,
                "output_filename": 1,
                "created_at": 1,
                "size_bytes": 1,
            },
        )
        .sort("created_at", -1)
        .limit(limit)
    )

    history_items = []
    for record in records:
        created_at = record.get("created_at")
        history_items.append(
            {
                "id": str(record.get("_id")),
                "created_at": created_at.isoformat() if created_at else None,
                "input_filename": record.get("input_filename"),
                "output_filename": record.get("output_filename"),
                "size_bytes": record.get("size_bytes"),
            }
        )

    return JSONResponse(
        content={
            "status": "success",
            "data": history_items,
        }
    )


@app.get("/bulk/download/{record_id}")
async def download_past_bulk_output(record_id: str):
    """Download a previously generated bulk forecast output by history record ID."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    try:
        object_id = ObjectId(record_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid record id")

    record = mongo_db["bulk_forecasts"].find_one({"_id": object_id})
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    output_bytes = record.get("output_file_bytes")
    if not output_bytes:
        raise HTTPException(status_code=404, detail="Stored file data not found for this record")

    output_filename = record.get("output_filename") or f"bulk_output_{record_id}.xlsx"
    content_type = record.get("content_type") or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return Response(
        content=bytes(output_bytes),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename={output_filename}"
        },
    )


@app.delete("/bulk/history/{record_id}")
async def delete_bulk_history_record(record_id: str):
    """Delete one bulk history record (including stored file bytes) by ID."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    try:
        object_id = ObjectId(record_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid record id")

    delete_result = mongo_db["bulk_forecasts"].delete_one({"_id": object_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")

    return JSONResponse(
        content={
            "status": "success",
            "message": "Bulk history record deleted",
            "data": {"deleted_count": delete_result.deleted_count},
        }
    )


@app.delete("/bulk/history")
async def delete_old_bulk_history(older_than_days: int = 30, limit: int = 500):
    """Delete old bulk history records to control MongoDB storage growth."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    if older_than_days < 1:
        raise HTTPException(status_code=400, detail="older_than_days must be at least 1")

    limit = max(1, min(limit, 5000))
    cutoff_datetime = datetime.utcnow() - timedelta(days=older_than_days)

    old_records = list(
        mongo_db["bulk_forecasts"]
        .find(
            {"created_at": {"$lt": cutoff_datetime}},
            {"_id": 1},
        )
        .sort("created_at", 1)
        .limit(limit)
    )

    if not old_records:
        return JSONResponse(
            content={
                "status": "success",
                "message": "No old bulk history records found",
                "data": {"deleted_count": 0},
            }
        )

    ids_to_delete = [record["_id"] for record in old_records]
    delete_result = mongo_db["bulk_forecasts"].delete_many({"_id": {"$in": ids_to_delete}})

    return JSONResponse(
        content={
            "status": "success",
            "message": "Old bulk history records deleted",
            "data": {
                "deleted_count": delete_result.deleted_count,
                "older_than_days": older_than_days,
                "applied_limit": limit,
            },
        }
    )


# ============================================================================
# MAIN (for uvicorn)
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "endpoint:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
