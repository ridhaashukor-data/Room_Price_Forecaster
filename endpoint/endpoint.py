"""
Hotel Occupancy Forecasting API

FastAPI endpoints for:
1. Single-day forecasting
2. Bulk Excel processing
3. Template generation
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Depends, Header
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any
from contextlib import asynccontextmanager
import os
import sys
from datetime import datetime, timedelta
import tempfile
from pathlib import Path
import json
import uuid
from threading import RLock

import pandas as pd

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
from backtester import (
    run_backtest,
    get_uploaded_preview,
    run_backtest_uploaded,
    generate_uploaded_backtest_template_csv,
    load_backtest_dataset,
    load_uploaded_dataframe,
    prepare_uploaded_backtest_dataset,
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
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_BULK_EXTENSIONS = {".xlsx", ".xls"}
ALLOWED_BACKTEST_UPLOAD_EXTENSIONS = {".csv", ".xlsx", ".xls"}
DEFAULT_COMPLETION_DATASET_ID = "default"
dataset_registry: dict[str, dict[str, Any]] = {}
active_completion_dataset_id: str = DEFAULT_COMPLETION_DATASET_ID
DATASET_STORE_DIR = Path(__file__).resolve().parents[1] / "backend" / "data" / "model_datasets"
DATASET_REGISTRY_FILE = DATASET_STORE_DIR / "dataset_registry.json"
ACTIVE_DATASET_FILE = DATASET_STORE_DIR / "active_dataset.json"
BULK_HISTORY_DIR = Path(__file__).resolve().parents[1] / "backend" / "data" / "bulk_history"
dataset_registry_lock = RLock()


def _is_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    """Protect sensitive endpoints with a static API key."""
    auth_enabled = _is_truthy(os.getenv("API_AUTH_ENABLED", "true"))
    if not auth_enabled:
        return

    expected_api_key = (os.getenv("API_KEY") or "").strip()
    if not expected_api_key:
        raise HTTPException(status_code=500, detail="API authentication is enabled but API_KEY is not configured")

    if not x_api_key or x_api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _raise_internal_error(client_message: str, exc: Exception) -> None:
    """Log internal exception details while returning a safe client message."""
    print(f"⚠️  {client_message}: {exc}")
    raise HTTPException(status_code=500, detail=client_message)


def _ensure_bulk_history_dir() -> None:
    BULK_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _bulk_history_file_path(stored_file_name: str) -> Path:
    return BULK_HISTORY_DIR / stored_file_name


def _delete_bulk_history_file(stored_file_name: Optional[str]) -> None:
    if not stored_file_name:
        return

    file_path = _bulk_history_file_path(str(stored_file_name))
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception:
            pass


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


def _persist_single_forecast(input_payload: dict, output_payload: dict, note: Optional[str] = None) -> None:
    """Persist single-day forecast request and response to MongoDB."""
    if not mongo_db:
        return

    document = {
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "source": "api_forecast",
        "input": _to_mongo_compatible(input_payload),
        "output": _to_mongo_compatible(output_payload),
        "note": (note or "").strip(),
    }
    mongo_db["single_day_forecasts"].insert_one(document)


def _persist_bulk_run(filename: str, output_filename: str, output_bytes: bytes) -> None:
    """Persist bulk forecast processing metadata to MongoDB."""
    if not mongo_db:
        return

    _ensure_bulk_history_dir()
    stored_file_name = f"{uuid.uuid4().hex}.xlsx"
    stored_path = _bulk_history_file_path(stored_file_name)
    stored_path.write_bytes(output_bytes)

    document = {
        "created_at": datetime.utcnow(),
        "source": "api_bulk_upload",
        "input_filename": filename,
        "output_filename": output_filename,
        "stored_file_name": stored_file_name,
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
        .find({}, {"_id": 1, "stored_file_name": 1})
        .sort("created_at", -1)
        .skip(max_records)
    )

    if not records_to_remove:
        return

    for record in records_to_remove:
        _delete_bulk_history_file(record.get("stored_file_name"))

    ids_to_remove = [record["_id"] for record in records_to_remove]
    mongo_db["bulk_forecasts"].delete_many({"_id": {"$in": ids_to_remove}})


def _validated_upload_filename(filename: Optional[str], allowed_extensions: set[str], field_name: str = "file") -> str:
    """Validate uploaded filename presence and extension."""
    cleaned_name = (filename or "").strip()
    if not cleaned_name:
        raise HTTPException(status_code=400, detail=f"Missing {field_name} filename")

    extension = os.path.splitext(cleaned_name)[1].lower()
    if extension not in allowed_extensions:
        expected = ", ".join(sorted(allowed_extensions))
        raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed extensions: {expected}")

    return cleaned_name


async def _read_upload_bytes_with_limit(upload_file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read uploaded file bytes and enforce a max-size limit."""
    file_bytes = await upload_file.read(max_bytes + 1)
    if len(file_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large. Max allowed size is {max_bytes // (1024 * 1024)} MB")
    return file_bytes


def _sanitize_dataset_label(label: Optional[str], fallback_label: str) -> str:
    text = (label or "").strip()
    if not text:
        return fallback_label
    return text[:120]


def _serialize_dataset_info(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "label": entry["label"],
        "source": entry["source"],
        "created_at": entry["created_at"],
        "training_stats": entry.get("training_stats") or {},
        "training_input_metadata": entry.get("training_input_metadata") or {},
    }


def _ensure_dataset_store_dir() -> None:
    DATASET_STORE_DIR.mkdir(parents=True, exist_ok=True)


def _dataset_csv_path(dataset_id: str) -> Path:
    return DATASET_STORE_DIR / f"{dataset_id}.csv"


def _persist_dataset_registry() -> None:
    with dataset_registry_lock:
        _ensure_dataset_store_dir()
        metadata_rows = []
        for entry in dataset_registry.values():
            csv_path = _dataset_csv_path(entry["id"])
            entry["ratios_df"].to_csv(csv_path, index=False)
            metadata_rows.append(
                {
                    "id": entry["id"],
                    "label": entry["label"],
                    "source": entry["source"],
                    "created_at": entry["created_at"],
                    "training_stats": entry.get("training_stats") or {},
                    "training_input_metadata": entry.get("training_input_metadata") or {},
                    "csv_file": csv_path.name,
                }
            )

        DATASET_REGISTRY_FILE.write_text(json.dumps(metadata_rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _persist_active_dataset_id(dataset_id: str) -> None:
    with dataset_registry_lock:
        _ensure_dataset_store_dir()
        ACTIVE_DATASET_FILE.write_text(
            json.dumps({"active_dataset_id": dataset_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _load_persisted_datasets() -> Optional[str]:
    if not DATASET_REGISTRY_FILE.exists():
        return None

    try:
        metadata_rows = json.loads(DATASET_REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(metadata_rows, list):
        return None

    with dataset_registry_lock:
        for item in metadata_rows:
            dataset_id = item.get("id")
            csv_file = item.get("csv_file")
            if not dataset_id or not csv_file:
                continue

            csv_path = DATASET_STORE_DIR / str(csv_file)
            if not csv_path.exists():
                continue

            try:
                ratios_df = pd.read_csv(csv_path)
            except Exception:
                continue

            _register_completion_dataset(
                dataset_id=str(dataset_id),
                label=str(item.get("label") or dataset_id),
                source=str(item.get("source") or "persisted"),
                ratios_df=ratios_df,
                training_stats=item.get("training_stats") or {},
                training_input_metadata=item.get("training_input_metadata") or {},
                activate=False,
                persist=False,
                created_at=item.get("created_at"),
            )

    if ACTIVE_DATASET_FILE.exists():
        try:
            active_payload = json.loads(ACTIVE_DATASET_FILE.read_text(encoding="utf-8"))
            active_id = (active_payload or {}).get("active_dataset_id")
            if isinstance(active_id, str) and active_id in dataset_registry:
                return active_id
        except Exception:
            return None

    return None


def _default_mapping_requirements() -> dict[str, Any]:
    return {
        "required_fields": [
            {
                "key": "booking_id_col",
                "label": "Booking ID",
                "required": False,
                "description": "Optional booking identifier column",
            },
            {
                "key": "stay_date_col",
                "label": "Stay Date",
                "required": True,
                "description": "Stay/check-in date column",
            },
            {
                "key": "booking_date_col",
                "label": "Booking Date",
                "required": True,
                "description": "Booking creation/snapshot date column",
            },
        ],
        "date_format_fields": ["stay_date_format", "booking_date_format"],
    }


def _register_completion_dataset(
    *,
    dataset_id: str,
    label: str,
    source: str,
    ratios_df: pd.DataFrame,
    training_stats: Optional[dict[str, Any]] = None,
    training_input_metadata: Optional[dict[str, Any]] = None,
    activate: bool = False,
    persist: bool = True,
    created_at: Optional[str] = None,
) -> dict[str, Any]:
    global completion_ratios_df, active_completion_dataset_id

    metadata = dict(training_input_metadata or {})
    if not metadata.get("training_input_type"):
        metadata["training_input_type"] = "raw-upload" if str(source).startswith("upload:") else "built-in"
    if metadata.get("training_input_type") == "raw-upload" and not metadata.get("raw_file_name"):
        source_text = str(source or "")
        metadata["raw_file_name"] = source_text.split("upload:", 1)[1] if source_text.startswith("upload:") else None
    if metadata.get("training_input_type") == "raw-upload" and not metadata.get("raw_uploaded_at"):
        metadata["raw_uploaded_at"] = created_at or datetime.utcnow().isoformat()

    metadata.setdefault("raw_file_name", None)
    metadata.setdefault("raw_uploaded_at", None)
    metadata.setdefault("raw_row_count", None)
    metadata.setdefault("raw_stay_date_min", None)
    metadata.setdefault("raw_stay_date_max", None)

    with dataset_registry_lock:
        dataset_registry[dataset_id] = {
            "id": dataset_id,
            "label": label,
            "source": source,
            "created_at": created_at or datetime.utcnow().isoformat(),
            "training_stats": training_stats or {},
            "training_input_metadata": metadata,
            "ratios_df": ratios_df.copy(),
        }

        if activate:
            active_completion_dataset_id = dataset_id
            completion_ratios_df = dataset_registry[dataset_id]["ratios_df"].copy()
            if persist:
                _persist_active_dataset_id(dataset_id)

        if persist:
            _persist_dataset_registry()

        return dataset_registry[dataset_id]


def _select_completion_dataset(dataset_id: str, persist: bool = True) -> dict[str, Any]:
    global completion_ratios_df, active_completion_dataset_id

    with dataset_registry_lock:
        entry = dataset_registry.get(dataset_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Dataset not found")

        active_completion_dataset_id = dataset_id
        completion_ratios_df = entry["ratios_df"].copy()
        if persist:
            _persist_active_dataset_id(dataset_id)
        return entry


def _delete_completion_dataset(dataset_id: str) -> dict[str, Any]:
    global completion_ratios_df, active_completion_dataset_id

    cleaned_id = (dataset_id or "").strip()
    if not cleaned_id:
        raise HTTPException(status_code=400, detail="Dataset id is required")

    if cleaned_id == DEFAULT_COMPLETION_DATASET_ID:
        raise HTTPException(status_code=400, detail="Default dataset cannot be deleted")

    with dataset_registry_lock:
        entry = dataset_registry.get(cleaned_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Dataset not found")

        csv_path = _dataset_csv_path(cleaned_id)
        dataset_registry.pop(cleaned_id, None)

        if cleaned_id == active_completion_dataset_id:
            next_dataset_id = DEFAULT_COMPLETION_DATASET_ID if DEFAULT_COMPLETION_DATASET_ID in dataset_registry else None
            if not next_dataset_id and dataset_registry:
                next_dataset_id = next(iter(dataset_registry.keys()))
            if not next_dataset_id:
                raise HTTPException(status_code=500, detail="No dataset available after deletion")

            active_completion_dataset_id = next_dataset_id
            completion_ratios_df = dataset_registry[next_dataset_id]["ratios_df"].copy()

        _persist_dataset_registry()
        _persist_active_dataset_id(active_completion_dataset_id)

    if csv_path.exists():
        try:
            csv_path.unlink()
        except Exception:
            pass

    return {
        "deleted_dataset_id": cleaned_id,
        "active_dataset_id": active_completion_dataset_id,
        "active_dataset": _serialize_dataset_info(dataset_registry[active_completion_dataset_id]),
    }


def _build_completion_ratios_from_training_df(
    training_df: pd.DataFrame,
    fallback_df: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    required_cols = {"day_type", "days_out", "current_occupancy", "final_occupancy"}
    missing = required_cols - set(training_df.columns)
    if missing:
        raise ValueError(f"Training data missing required columns: {sorted(missing)}")

    df = training_df.copy()
    df["day_type"] = df["day_type"].astype(str).str.lower().str.strip()
    df = df[df["day_type"].isin(["weekday", "weekend"])]
    df["days_out"] = pd.to_numeric(df["days_out"], errors="coerce")
    df["current_occupancy"] = pd.to_numeric(df["current_occupancy"], errors="coerce")
    df["final_occupancy"] = pd.to_numeric(df["final_occupancy"], errors="coerce")
    df = df.dropna(subset=["day_type", "days_out", "current_occupancy", "final_occupancy"])
    df = df[(df["days_out"] >= 0) & (df["days_out"] <= 30)]
    df = df[df["final_occupancy"] > 0]

    source_rows = int(len(training_df))
    clean_rows = int(len(df))
    if clean_rows == 0:
        raise ValueError("No valid rows left after cleaning for completion-ratio training")

    df["completion_ratio"] = df["current_occupancy"] / df["final_occupancy"]
    before_filter = len(df)
    df = df[(df["completion_ratio"] >= 0.0) & (df["completion_ratio"] <= 1.05)]
    ratio_rows = int(len(df))
    if ratio_rows == 0:
        raise ValueError("No valid completion-ratio rows after outlier filtering")

    grouped = (
        df.groupby(["day_type", "days_out"])["completion_ratio"]
        .agg(
            avg_completion_ratio="mean",
            sample_count="count",
            std_deviation="std",
        )
        .reset_index()
    )
    grouped["days_out"] = grouped["days_out"].astype(int)
    grouped["confidence"] = grouped["sample_count"].apply(lambda x: "high" if int(x) >= 100 else "low")

    full_grid = pd.MultiIndex.from_product(
        [["weekday", "weekend"], list(range(0, 31))],
        names=["day_type", "days_out"],
    ).to_frame(index=False)

    merged = full_grid.merge(grouped, on=["day_type", "days_out"], how="left")

    missing_groups = int(merged["avg_completion_ratio"].isna().sum())
    if missing_groups > 0 and fallback_df is not None and not fallback_df.empty:
        fallback_lookup = fallback_df[["day_type", "days_out", "avg_completion_ratio", "sample_count", "std_deviation", "confidence"]].copy()
        fallback_lookup["day_type"] = fallback_lookup["day_type"].astype(str).str.lower().str.strip()
        fallback_lookup["days_out"] = pd.to_numeric(fallback_lookup["days_out"], errors="coerce").astype("Int64")
        fallback_lookup = fallback_lookup.dropna(subset=["days_out"])
        fallback_lookup["days_out"] = fallback_lookup["days_out"].astype(int)
        merged = merged.merge(
            fallback_lookup,
            on=["day_type", "days_out"],
            how="left",
            suffixes=("", "_fallback"),
        )
        merged["avg_completion_ratio"] = merged["avg_completion_ratio"].fillna(merged["avg_completion_ratio_fallback"])
        merged["sample_count"] = merged["sample_count"].fillna(merged["sample_count_fallback"])
        merged["std_deviation"] = merged["std_deviation"].fillna(merged["std_deviation_fallback"])
        merged["confidence"] = merged["confidence"].fillna(merged["confidence_fallback"])
        merged = merged.drop(columns=[
            "avg_completion_ratio_fallback",
            "sample_count_fallback",
            "std_deviation_fallback",
            "confidence_fallback",
        ])

    if merged["avg_completion_ratio"].isna().any():
        raise ValueError("Could not build full completion-ratio matrix for all day_type/days_out combinations")

    merged["sample_count"] = pd.to_numeric(merged["sample_count"], errors="coerce").fillna(0).astype(int)
    merged["std_deviation"] = pd.to_numeric(merged["std_deviation"], errors="coerce").fillna(0.0)
    merged["confidence"] = merged["confidence"].fillna("low")
    merged["avg_completion_ratio"] = pd.to_numeric(merged["avg_completion_ratio"], errors="coerce").round(4)
    merged["std_deviation"] = merged["std_deviation"].round(4)

    model_df = merged[["day_type", "days_out", "avg_completion_ratio", "sample_count", "std_deviation", "confidence"]].sort_values(
        ["day_type", "days_out"],
        ascending=[True, False],
    ).reset_index(drop=True)

    stats = {
        "source_rows": source_rows,
        "clean_rows": clean_rows,
        "ratio_rows": ratio_rows,
        "outlier_filtered_rows": int(before_filter - ratio_rows),
        "missing_groups_filled": missing_groups,
    }
    return model_df, stats


def _build_training_df_from_backtest_df(source_df: pd.DataFrame) -> pd.DataFrame:
    candidate = source_df.copy()
    if "current_occupancy" not in candidate.columns:
        if "rooms_booked_cumulative" in candidate.columns:
            candidate["current_occupancy"] = pd.to_numeric(candidate["rooms_booked_cumulative"], errors="coerce")
        else:
            raise ValueError("Dataset missing current occupancy values")

    if "final_occupancy" not in candidate.columns:
        raise ValueError("Dataset missing final occupancy values")

    return candidate[["day_type", "days_out", "current_occupancy", "final_occupancy"]].copy()


def _build_raw_upload_metadata(uploaded_df: pd.DataFrame, mapping: dict[str, Any], filename: str) -> dict[str, Any]:
    stay_date_col = (mapping.get("stay_date_col") or "").strip() if isinstance(mapping.get("stay_date_col"), str) else mapping.get("stay_date_col")
    stay_date_format = (mapping.get("stay_date_format") or "").strip() or None

    raw_stay_date_min = None
    raw_stay_date_max = None
    if isinstance(stay_date_col, str) and stay_date_col and stay_date_col in uploaded_df.columns:
        series = uploaded_df[stay_date_col]
        if stay_date_format:
            parsed_stay_dates = pd.to_datetime(series.astype(str), format=stay_date_format, errors="coerce")
        else:
            parsed_stay_dates = pd.to_datetime(series, errors="coerce", dayfirst=True)

        parsed_stay_dates = parsed_stay_dates.dropna()
        if not parsed_stay_dates.empty:
            raw_stay_date_min = parsed_stay_dates.min().strftime("%Y-%m-%d")
            raw_stay_date_max = parsed_stay_dates.max().strftime("%Y-%m-%d")

    return {
        "training_input_type": "raw-upload",
        "raw_file_name": filename,
        "raw_uploaded_at": datetime.utcnow().isoformat(),
        "raw_row_count": int(len(uploaded_df)),
        "raw_stay_date_min": raw_stay_date_min,
        "raw_stay_date_max": raw_stay_date_max,
    }


def _build_uploaded_dataset_fallback_label(metadata: dict[str, Any]) -> str:
    """Readable default name for aggregated datasets trained from uploaded raw data."""
    uploaded_at_text = str(metadata.get("raw_uploaded_at") or "")
    try:
        uploaded_at = datetime.fromisoformat(uploaded_at_text.replace("Z", "+00:00")) if uploaded_at_text else None
        uploaded_at_fmt = uploaded_at.strftime("%Y-%m-%d %H:%M") if uploaded_at else "unknown-time"
    except Exception:
        uploaded_at_fmt = uploaded_at_text or "unknown-time"

    def _format_raw_range_date(raw_value: Any) -> str:
        if raw_value in (None, ""):
            return "N/A"
        raw_text = str(raw_value).strip()
        if not raw_text or raw_text.upper() == "N/A":
            return "N/A"
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw_text, fmt).strftime("%d/%m/%Y")
            except Exception:
                continue
        try:
            return datetime.fromisoformat(raw_text.replace("Z", "+00:00")).strftime("%d/%m/%Y")
        except Exception:
            return raw_text

    raw_date_min = _format_raw_range_date(metadata.get("raw_stay_date_min"))
    raw_date_max = _format_raw_range_date(metadata.get("raw_stay_date_max"))
    return f"Uploaded dataset | {uploaded_at_fmt} | {raw_date_min} to {raw_date_max}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load completion ratios on startup, cleanup on shutdown"""
    global completion_ratios_df, mongo_client, mongo_db, mongo_connected

    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(dotenv_path=env_path)

    if _is_truthy(os.getenv("API_AUTH_ENABLED", "true")) and not (os.getenv("API_KEY") or "").strip():
        raise RuntimeError("API authentication is enabled but API_KEY is not configured")

    try:
        completion_ratios_df = load_completion_ratios()
        _register_completion_dataset(
            dataset_id=DEFAULT_COMPLETION_DATASET_ID,
            label="Default completion ratios",
            source="built-in",
            ratios_df=completion_ratios_df,
            training_stats={"source_rows": None, "note": "Loaded from backend/data/completion_ratios.csv"},
            training_input_metadata={
                "training_input_type": "built-in",
                "raw_file_name": None,
                "raw_uploaded_at": None,
                "raw_row_count": None,
                "raw_stay_date_min": None,
                "raw_stay_date_max": None,
            },
            activate=True,
            persist=False,
        )

        persisted_active_dataset_id = _load_persisted_datasets()
        if persisted_active_dataset_id and persisted_active_dataset_id in dataset_registry:
            _select_completion_dataset(persisted_active_dataset_id, persist=False)
        else:
            _persist_dataset_registry()
            _persist_active_dataset_id(active_completion_dataset_id)

        print("✅ Completion ratios loaded successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not load completion ratios: {e}")

    try:
        mongodb_uri = _get_mongodb_uri()
        if mongodb_uri:
            mongo_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
            mongo_client.admin.command("ping")
            mongo_db = mongo_client["room_price_forecaster"]
            mongo_db["single_day_forecasts"].create_index("created_at")
            mongo_db["bulk_forecasts"].create_index("created_at")
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
                "total_rooms_available": 100,
                "note": "Weekend city event expected"
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
    note: Optional[str] = Field(default="", max_length=500, description="Optional note attached to this single-day forecast")


class SingleHistoryNoteUpdate(BaseModel):
    """Input model for updating single-day history note."""
    note: str = Field(..., min_length=1, max_length=500, description="Updated note text")


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


class BacktestInput(BaseModel):
    """Input model for occupancy forecast backtesting."""
    total_rooms_available: int = Field(default=100, gt=0, description="Total rooms available used to convert cumulative bookings into occupancy %")
    start_date: Optional[str] = Field(default=None, description="Optional stay-date filter start in YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="Optional stay-date filter end in YYYY-MM-DD")
    day_type: str = Field(default="all", description="Filter: all, weekday, or weekend")
    days_out_min: int = Field(default=0, ge=0, le=30, description="Minimum days_out filter (0-30)")
    days_out_max: int = Field(default=30, ge=0, le=30, description="Maximum days_out filter (0-30)")
    include_details: bool = Field(default=True, description="Include row-level prediction details in response")
    detail_limit: int = Field(default=500, ge=1, le=5000, description="Maximum detail rows returned when include_details=true")


class CompletionDatasetSelectInput(BaseModel):
    dataset_id: str = Field(..., min_length=1, description="Dataset id to activate")


class CompletionRetrainBuiltinInput(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120, description="Optional label for the retrained dataset")
    activate: bool = Field(default=True, description="Whether to activate this dataset immediately after retraining")


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
                "/options - Get input options",
                "/backtest - Historical occupancy backtesting",
                "/backtest/upload/template - Download sample upload file",
                "/backtest/upload/preview - Detect upload columns",
                "/backtest/upload/run - Run mapped upload backtest"
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
        _raise_internal_error("Failed to load options", e)


@app.post("/forecast", response_model=ForecastOutput)
async def single_day_forecast(input_data: SingleDayInput, _: None = Depends(_require_api_key)):
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
        note_text = (inputs.pop("note", "") or "").strip()
        
        # Run forecast
        result = forecast_and_price(inputs, completion_ratios_df)
        try:
            _persist_single_forecast(inputs, result, note=note_text)
        except Exception as db_error:
            print(f"⚠️  Warning: Could not persist single forecast: {db_error}")
        
        return ForecastOutput(**result)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _raise_internal_error("Internal forecast processing error", e)


@app.get("/bulk/template")
async def download_template(_: None = Depends(_require_api_key)):
    """
    Download Excel template for bulk forecasting
    
    Returns an Excel file with:
    - Monthly target inputs
    - Monthly ADR budget inputs
    - Current occupancy grid (31 days x 12 months)
    """
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = generate_template(output_dir=temp_dir)

            if not os.path.exists(template_path):
                raise HTTPException(status_code=500, detail="Template generation failed")

            template_bytes = Path(template_path).read_bytes()

        return Response(
            content=template_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=occupancy_template.xlsx"},
        )

    except Exception as e:
        _raise_internal_error("Error generating bulk template", e)


@app.post("/bulk/upload")
async def bulk_forecast_upload(file: UploadFile = File(...), _: None = Depends(_require_api_key)):
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
        filename = _validated_upload_filename(file.filename, ALLOWED_BULK_EXTENSIONS)
        file_bytes = await _read_upload_bytes_with_limit(file)

        with tempfile.TemporaryDirectory() as temp_dir:
            extension = os.path.splitext(filename)[1].lower()
            input_path = os.path.join(temp_dir, f"input{extension}")
            with open(input_path, "wb") as temp_input:
                temp_input.write(file_bytes)

            output_path = process_bulk_forecast(
                input_path,
                output_dir=temp_dir,
                completion_ratios_df=completion_ratios_df,
            )

            if not os.path.exists(output_path):
                raise HTTPException(status_code=500, detail="Forecast processing failed")

            output_filename = os.path.basename(output_path)
            output_bytes = Path(output_path).read_bytes()

        try:
            _persist_bulk_run(filename, output_filename, output_bytes)
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
        _raise_internal_error("Error processing bulk upload", e)


@app.post("/backtest")
async def run_backtest_endpoint(input_data: BacktestInput, _: None = Depends(_require_api_key)):
    """Run occupancy forecast backtesting against historical snapshots."""
    try:
        payload = input_data.model_dump()
        result = run_backtest(
            completion_ratios_df=completion_ratios_df,
            total_rooms_available=payload["total_rooms_available"],
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            day_type=payload.get("day_type", "all"),
            days_out_min=payload.get("days_out_min", 0),
            days_out_max=payload.get("days_out_max", 30),
            include_details=payload.get("include_details", True),
            detail_limit=payload.get("detail_limit", 500),
        )
        return JSONResponse(content={"status": "success", "data": result})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        _raise_internal_error("Backtest dataset file not found", e)
    except Exception as e:
        _raise_internal_error("Error running backtest", e)


@app.post("/backtest/upload/preview")
async def backtest_upload_preview(file: UploadFile = File(...), _: None = Depends(_require_api_key)):
    """Preview uploaded backtest file columns and sample rows for mapping."""
    try:
        filename = _validated_upload_filename(file.filename, ALLOWED_BACKTEST_UPLOAD_EXTENSIONS)
        file_bytes = await _read_upload_bytes_with_limit(file)
        preview = get_uploaded_preview(file_bytes=file_bytes, filename=filename)
        return JSONResponse(content={"status": "success", "data": preview})
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _raise_internal_error("Error generating upload preview", e)


@app.get("/backtest/upload/mapping/requirements")
async def get_backtest_mapping_requirements(_: None = Depends(_require_api_key)):
    """Return required/optional mapping fields used for uploaded dataset pairing."""
    return JSONResponse(content={"status": "success", "data": _default_mapping_requirements()})


@app.get("/backtest/upload/template")
async def download_backtest_upload_template(_: None = Depends(_require_api_key)):
    """Download sample CSV template for custom uploaded backtesting."""
    try:
        csv_bytes, filename, media_type = generate_uploaded_backtest_template_csv()
        return Response(
            content=csv_bytes,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            },
        )
    except Exception as e:
        _raise_internal_error("Error generating upload template", e)


@app.post("/backtest/upload/run")
async def run_backtest_uploaded_endpoint(
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    total_rooms_available: int = Form(100),
    start_date: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    day_type: str = Form("all"),
    days_out_min: int = Form(0),
    days_out_max: int = Form(30),
    include_details: bool = Form(True),
    detail_limit: int = Form(500),
    _: None = Depends(_require_api_key),
):
    """Run backtest using user-uploaded raw booking CSV/Excel with explicit column mapping."""
    try:
        try:
            mapping = json.loads(mapping_json)
        except Exception:
            raise HTTPException(status_code=400, detail="mapping_json must be valid JSON")

        filename = _validated_upload_filename(file.filename, ALLOWED_BACKTEST_UPLOAD_EXTENSIONS)
        file_bytes = await _read_upload_bytes_with_limit(file)
        result = run_backtest_uploaded(
            file_bytes=file_bytes,
            filename=filename,
            mapping=mapping,
            completion_ratios_df=completion_ratios_df,
            total_rooms_available=total_rooms_available,
            start_date=start_date,
            end_date=end_date,
            day_type=day_type,
            days_out_min=days_out_min,
            days_out_max=days_out_max,
            include_details=include_details,
            detail_limit=detail_limit,
        )
        return JSONResponse(content={"status": "success", "data": result})
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _raise_internal_error("Error running uploaded backtest", e)


@app.get("/model/datasets")
async def list_completion_datasets(_: None = Depends(_require_api_key)):
    """List all in-memory completion-ratio datasets and active selection."""
    with dataset_registry_lock:
        datasets = [_serialize_dataset_info(entry) for entry in dataset_registry.values()]
        datasets.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        active = dataset_registry.get(active_completion_dataset_id)

    return JSONResponse(
        content={
            "status": "success",
            "data": {
                "active_dataset_id": active_completion_dataset_id,
                "active_dataset": _serialize_dataset_info(active) if active else None,
                "datasets": datasets,
            },
        }
    )


@app.post("/model/datasets/select")
async def select_completion_dataset(payload: CompletionDatasetSelectInput, _: None = Depends(_require_api_key)):
    """Switch active completion-ratio dataset used by all forecast calculations."""
    selected = _select_completion_dataset(payload.dataset_id.strip())
    return JSONResponse(
        content={
            "status": "success",
            "message": "Active completion dataset updated",
            "data": {
                "active_dataset_id": selected["id"],
                "active_dataset": _serialize_dataset_info(selected),
            },
        }
    )


@app.delete("/model/datasets/{dataset_id}")
async def delete_completion_dataset(dataset_id: str, _: None = Depends(_require_api_key)):
    """Delete a completion-ratio dataset and keep an active fallback dataset selected."""
    deleted_data = _delete_completion_dataset(dataset_id)
    return JSONResponse(
        content={
            "status": "success",
            "message": "Completion dataset deleted",
            "data": deleted_data,
        }
    )


@app.post("/model/retrain/builtin")
async def retrain_completion_model_builtin(payload: CompletionRetrainBuiltinInput, _: None = Depends(_require_api_key)):
    """Retrain completion ratios using the built-in historical dataset and optionally activate it."""
    try:
        source_df = load_backtest_dataset()
        training_df = _build_training_df_from_backtest_df(source_df)
        fallback_df = dataset_registry.get(DEFAULT_COMPLETION_DATASET_ID, {}).get("ratios_df")
        trained_df, training_stats = _build_completion_ratios_from_training_df(training_df, fallback_df=fallback_df)

        dataset_id = f"builtin-{uuid.uuid4().hex[:8]}"
        label = _sanitize_dataset_label(payload.label, fallback_label="Built-in retrained dataset")
        entry = _register_completion_dataset(
            dataset_id=dataset_id,
            label=label,
            source="built-in-retrained",
            ratios_df=trained_df,
            training_stats=training_stats,
            training_input_metadata={
                "training_input_type": "built-in",
                "raw_file_name": None,
                "raw_uploaded_at": None,
                "raw_row_count": None,
                "raw_stay_date_min": None,
                "raw_stay_date_max": None,
            },
            activate=payload.activate,
        )

        return JSONResponse(
            content={
                "status": "success",
                "message": "Completion model retrained from built-in dataset",
                "data": {
                    "dataset": _serialize_dataset_info(entry),
                    "active_dataset_id": active_completion_dataset_id,
                },
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _raise_internal_error("Error retraining built-in dataset", e)


@app.post("/model/retrain/upload")
async def retrain_completion_model_upload(
    file: UploadFile = File(...),
    mapping_json: str = Form(...),
    total_rooms_available: int = Form(100),
    label: str = Form(""),
    activate: bool = Form(True),
    _: None = Depends(_require_api_key),
):
    """Retrain completion ratios from uploaded raw booking data and optionally activate it."""
    try:
        try:
            mapping = json.loads(mapping_json)
        except Exception:
            raise HTTPException(status_code=400, detail="mapping_json must be valid JSON")

        filename = _validated_upload_filename(file.filename, ALLOWED_BACKTEST_UPLOAD_EXTENSIONS)
        file_bytes = await _read_upload_bytes_with_limit(file)

        uploaded_df = load_uploaded_dataframe(file_bytes=file_bytes, filename=filename)
        raw_upload_metadata = _build_raw_upload_metadata(uploaded_df=uploaded_df, mapping=mapping, filename=filename)
        prepared_df = prepare_uploaded_backtest_dataset(
            source_df=uploaded_df,
            mapping=mapping,
            total_rooms_available=total_rooms_available,
        )
        training_df = prepared_df[["day_type", "days_out", "current_occupancy", "final_occupancy"]].copy()

        fallback_df = dataset_registry.get(DEFAULT_COMPLETION_DATASET_ID, {}).get("ratios_df")
        trained_df, training_stats = _build_completion_ratios_from_training_df(training_df, fallback_df=fallback_df)

        dataset_id = f"upload-{uuid.uuid4().hex[:8]}"
        dataset_label = _sanitize_dataset_label(
            label,
            fallback_label=_build_uploaded_dataset_fallback_label(raw_upload_metadata),
        )
        entry = _register_completion_dataset(
            dataset_id=dataset_id,
            label=dataset_label,
            source=f"upload:{filename}",
            ratios_df=trained_df,
            training_stats=training_stats,
            training_input_metadata=raw_upload_metadata,
            activate=bool(activate),
        )

        return JSONResponse(
            content={
                "status": "success",
                "message": "Completion model retrained from uploaded dataset",
                "data": {
                    "dataset": _serialize_dataset_info(entry),
                    "active_dataset_id": active_completion_dataset_id,
                },
            }
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _raise_internal_error("Error retraining uploaded dataset", e)


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
async def single_history(limit: int = 20, _: None = Depends(_require_api_key)):
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
                "updated_at": 1,
                "input": 1,
                "output": 1,
                "note": 1,
            },
        )
        .sort("created_at", -1)
        .limit(limit)
    )

    history_items = []
    for record in records:
        created_at = record.get("created_at")
        updated_at = record.get("updated_at")
        input_payload = record.get("input") or {}
        output_payload = record.get("output") or {}
        history_items.append(
            {
                "id": str(record.get("_id")),
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "stay_date": input_payload.get("stay_date"),
                "today_date": input_payload.get("today_date"),
                "event_level": input_payload.get("event_level"),
                "forecast_occupancy_pct": output_payload.get("forecast_occupancy_pct"),
                "recommended_adr": output_payload.get("recommended_adr"),
                "demand_signal": output_payload.get("demand_signal"),
                "note": record.get("note") or "",
            }
        )

    return JSONResponse(
        content={
            "status": "success",
            "data": history_items,
        }
    )


@app.get("/single/history/{record_id}")
async def single_history_detail(record_id: str, _: None = Depends(_require_api_key)):
    """Get one previously generated single-day forecast record by ID."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    try:
        object_id = ObjectId(record_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid record id")

    record = mongo_db["single_day_forecasts"].find_one(
        {"_id": object_id},
        {"created_at": 1, "updated_at": 1, "input": 1, "output": 1, "source": 1, "note": 1},
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    created_at = record.get("created_at")
    updated_at = record.get("updated_at")
    return JSONResponse(
        content={
            "status": "success",
            "data": {
                "id": str(record.get("_id")),
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "source": record.get("source"),
                "input": record.get("input") or {},
                "output": record.get("output") or {},
                "note": record.get("note") or "",
            },
        }
    )


@app.patch("/single/history/{record_id}/note")
async def update_single_history_note(record_id: str, payload: SingleHistoryNoteUpdate, _: None = Depends(_require_api_key)):
    """Update note text for one previously generated single-day forecast record."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    try:
        object_id = ObjectId(record_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid record id")

    note_text = payload.note.strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="Note must not be empty")

    update_result = mongo_db["single_day_forecasts"].update_one(
        {"_id": object_id},
        {
            "$set": {
                "note": note_text,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")

    return JSONResponse(
        content={
            "status": "success",
            "message": "Single-day note updated",
            "data": {"updated_count": update_result.modified_count},
        }
    )


@app.delete("/single/history/{record_id}/note")
async def delete_single_history_note(record_id: str, _: None = Depends(_require_api_key)):
    """Delete note text for one previously generated single-day forecast record."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    try:
        object_id = ObjectId(record_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid record id")

    update_result = mongo_db["single_day_forecasts"].update_one(
        {"_id": object_id},
        {
            "$set": {
                "note": "",
                "updated_at": datetime.utcnow(),
            }
        },
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")

    return JSONResponse(
        content={
            "status": "success",
            "message": "Single-day note deleted",
            "data": {"updated_count": update_result.modified_count},
        }
    )


@app.get("/bulk/history")
async def bulk_history(limit: int = 20, _: None = Depends(_require_api_key)):
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
async def download_past_bulk_output(record_id: str, _: None = Depends(_require_api_key)):
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

    output_bytes = None
    stored_file_name = record.get("stored_file_name")
    if stored_file_name:
        stored_path = _bulk_history_file_path(str(stored_file_name))
        if not stored_path.exists():
            raise HTTPException(status_code=404, detail="Stored file data not found for this record")
        output_bytes = stored_path.read_bytes()

    if output_bytes is None:
        legacy_output_bytes = record.get("output_file_bytes")
        if not legacy_output_bytes:
            raise HTTPException(status_code=404, detail="Stored file data not found for this record")
        output_bytes = bytes(legacy_output_bytes)

    output_filename = record.get("output_filename") or f"bulk_output_{record_id}.xlsx"
    content_type = record.get("content_type") or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return Response(
        content=output_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename={output_filename}"
        },
    )


@app.delete("/bulk/history/{record_id}")
async def delete_bulk_history_record(record_id: str, _: None = Depends(_require_api_key)):
    """Delete one bulk history record (including stored file bytes) by ID."""
    if not mongo_db:
        raise HTTPException(status_code=503, detail="MongoDB is not connected")

    try:
        object_id = ObjectId(record_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid record id")

    record = mongo_db["bulk_forecasts"].find_one({"_id": object_id}, {"stored_file_name": 1})
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    _delete_bulk_history_file(record.get("stored_file_name"))

    delete_result = mongo_db["bulk_forecasts"].delete_one({"_id": object_id})

    return JSONResponse(
        content={
            "status": "success",
            "message": "Bulk history record deleted",
            "data": {"deleted_count": delete_result.deleted_count},
        }
    )


@app.delete("/bulk/history")
async def delete_old_bulk_history(older_than_days: int = 30, limit: int = 500, _: None = Depends(_require_api_key)):
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
            {"_id": 1, "stored_file_name": 1},
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

    for record in old_records:
        _delete_bulk_history_file(record.get("stored_file_name"))

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
