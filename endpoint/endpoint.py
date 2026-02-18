"""
Hotel Occupancy Forecasting API

FastAPI endpoints for:
1. Single-day forecasting
2. Bulk Excel processing
3. Template generation
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from contextlib import asynccontextmanager
import os
import sys
from datetime import datetime
import tempfile

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load completion ratios on startup, cleanup on shutdown"""
    global completion_ratios_df
    try:
        completion_ratios_df = load_completion_ratios()
        print("✅ Completion ratios loaded successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not load completion ratios: {e}")
    
    yield
    
    # Cleanup (if needed)
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
        
        # Return output file
        return FileResponse(
            path=output_path,
            filename=os.path.basename(output_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={os.path.basename(output_path)}"
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
        "service": "Hotel Occupancy Forecasting API"
    })


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
