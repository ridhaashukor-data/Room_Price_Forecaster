import os
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from forecaster import forecast_occupancy, load_completion_ratios


DEFAULT_BACKTEST_DATA_PATH = os.path.join(
    os.path.dirname(__file__),
    "data_generation",
    "generated_data",
    "aggregated_bookings.csv",
)

SUPPORTED_UPLOAD_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def _to_ddmmyy(value: datetime) -> str:
    return value.strftime("%d%m%y")


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return np.nan


def _parse_datetime_series(series: pd.Series, date_format: Optional[str] = None) -> pd.Series:
    if date_format:
        return pd.to_datetime(series.astype(str), format=date_format, errors="coerce")

    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return parsed


def _normalize_day_type(value: object, stay_date_dt: datetime) -> str:
    raw = str(value).strip().lower() if value is not None else ""
    if raw in {"weekday", "weekend"}:
        return raw
    if raw in {"weekdays", "week day", "wd"}:
        return "weekday"
    if raw in {"weekends", "week end", "we"}:
        return "weekend"
    return "weekday" if stay_date_dt.weekday() <= 3 else "weekend"


def _build_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "count": 0,
            "mae": None,
            "rmse": None,
            "mape": None,
            "bias": None,
            "within_3_pct": None,
            "within_5_pct": None,
            "within_10_pct": None,
        }

    mae = float(df["abs_error"].mean())
    rmse = float(np.sqrt(df["squared_error"].mean()))
    bias = float(df["error"].mean())

    nonzero_actual = df[df["actual_final_occupancy_pct"] > 0]
    mape = float(nonzero_actual["ape"].mean() * 100.0) if not nonzero_actual.empty else None

    within_3 = float((df["abs_error"] <= 3.0).mean() * 100.0)
    within_5 = float((df["abs_error"] <= 5.0).mean() * 100.0)
    within_10 = float((df["abs_error"] <= 10.0).mean() * 100.0)

    return {
        "count": int(len(df)),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "mape": round(mape, 4) if mape is not None else None,
        "bias": round(bias, 4),
        "within_3_pct": round(within_3, 4),
        "within_5_pct": round(within_5, 4),
        "within_10_pct": round(within_10, 4),
    }


def _build_breakdown(df: pd.DataFrame, group_column: str) -> list[dict]:
    if df.empty:
        return []

    rows = []
    for group_value, group_df in df.groupby(group_column):
        metrics = _build_metrics(group_df)
        rows.append({group_column: group_value, **metrics})

    if group_column == "days_out":
        rows.sort(key=lambda item: item["days_out"])
    else:
        rows.sort(key=lambda item: str(item[group_column]))

    return rows


def load_uploaded_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise ValueError("Unsupported file type. Please upload CSV or Excel (.xlsx/.xls)")

    buffer = BytesIO(file_bytes)
    if extension == ".csv":
        return pd.read_csv(buffer)
    return pd.read_excel(buffer)


def get_uploaded_preview(file_bytes: bytes, filename: str, sample_rows: int = 5) -> dict:
    df = load_uploaded_dataframe(file_bytes=file_bytes, filename=filename)
    columns = [str(column) for column in df.columns]
    rows_preview = df.head(max(1, sample_rows)).replace({np.nan: None}).to_dict(orient="records")

    return {
        "filename": filename,
        "row_count": int(len(df)),
        "column_count": int(len(columns)),
        "columns": columns,
        "sample_rows": rows_preview,
    }


def generate_uploaded_backtest_template_csv() -> tuple[bytes, str, str]:
    template_df = pd.DataFrame(
        [
            {
                "booking_id": 1,
                "stay_date": "2026-03-20",
                "booking_date": "2026-02-25",
                "rooms_booked": 1,
            },
            {
                "booking_id": 2,
                "stay_date": "2026-03-20",
                "booking_date": "2026-03-01",
                "rooms_booked": 2,
            },
            {
                "booking_id": 3,
                "stay_date": "2026-03-21",
                "booking_date": "2026-02-28",
                "rooms_booked": 1,
            },
        ]
    )

    csv_bytes = template_df.to_csv(index=False).encode("utf-8")
    return csv_bytes, "backtest_upload_template.csv", "text/csv"


def prepare_uploaded_backtest_dataset(
    source_df: pd.DataFrame,
    mapping: dict,
    total_rooms_available: int,
) -> pd.DataFrame:
    raw_data_mode = bool(mapping.get("raw_data_mode", False))

    if not raw_data_mode:
        raise ValueError(
            "Only raw booking data is supported for uploaded backtesting. "
            "Please provide stay_date + booking_date (and optional rooms_per_row_col)."
        )

    if raw_data_mode:
        stay_date_col = mapping.get("stay_date_col")
        booking_date_col = mapping.get("booking_date_col")
        rooms_per_row_col = mapping.get("rooms_per_row_col")
        stay_date_format = (mapping.get("stay_date_format") or "").strip() or None
        booking_date_format = (mapping.get("booking_date_format") or "").strip() or None

        if not stay_date_col:
            raise ValueError("stay_date_col mapping is required in raw data mode")
        if not booking_date_col:
            raise ValueError("booking_date_col mapping is required in raw data mode")
        if stay_date_col not in source_df.columns:
            raise ValueError(f"Mapped stay_date_col not found: {stay_date_col}")
        if booking_date_col not in source_df.columns:
            raise ValueError(f"Mapped booking_date_col not found: {booking_date_col}")
        if rooms_per_row_col and rooms_per_row_col not in source_df.columns:
            raise ValueError(f"Mapped rooms_per_row_col not found: {rooms_per_row_col}")

        if total_rooms_available <= 0:
            raise ValueError("total_rooms_available must be greater than 0 in raw data mode")

        df = source_df.copy()
        df["stay_date_dt"] = _parse_datetime_series(df[stay_date_col], stay_date_format)
        df["booking_date_dt"] = _parse_datetime_series(df[booking_date_col], booking_date_format)

        if rooms_per_row_col:
            df["rooms_units"] = pd.to_numeric(df[rooms_per_row_col], errors="coerce")
        else:
            df["rooms_units"] = 1.0

        df = df.dropna(subset=["stay_date_dt", "booking_date_dt", "rooms_units"])
        df = df[df["rooms_units"] > 0]
        df = df[df["booking_date_dt"] <= df["stay_date_dt"]]

        if df.empty:
            raise ValueError("No valid rows found after raw data cleaning")

        aggregated_rows: list[dict] = []
        for stay_date_dt, stay_group in df.groupby("stay_date_dt"):
            final_rooms = float(stay_group["rooms_units"].sum())
            final_occupancy = final_rooms / float(total_rooms_available) * 100.0

            bookings_by_date = (
                stay_group.groupby("booking_date_dt", as_index=False)["rooms_units"]
                .sum()
                .sort_values("booking_date_dt")
            )
            bookings_by_date["cum_rooms"] = bookings_by_date["rooms_units"].cumsum()

            for entry in bookings_by_date.itertuples(index=False):
                snapshot_dt = getattr(entry, "booking_date_dt")
                days_out = int((stay_date_dt - snapshot_dt).days)
                if days_out < 0 or days_out > 30:
                    continue

                current_rooms = float(getattr(entry, "cum_rooms"))
                current_occupancy = current_rooms / float(total_rooms_available) * 100.0

                aggregated_rows.append(
                    {
                        "stay_date_dt": stay_date_dt,
                        "days_out": days_out,
                        "current_occupancy": current_occupancy,
                        "final_occupancy": final_occupancy,
                        "day_type": "weekday" if stay_date_dt.weekday() <= 3 else "weekend",
                    }
                )

        aggregated_df = pd.DataFrame(aggregated_rows)
        if aggregated_df.empty:
            raise ValueError("No usable snapshot rows were generated from raw data (days_out must be 0-30)")

        aggregated_df["days_out"] = pd.to_numeric(aggregated_df["days_out"], errors="coerce").astype("Int64")
        aggregated_df = aggregated_df.dropna(subset=["stay_date_dt", "days_out", "current_occupancy", "final_occupancy"])
        aggregated_df = aggregated_df[(aggregated_df["current_occupancy"] >= 0) & (aggregated_df["current_occupancy"] <= 100)]
        aggregated_df = aggregated_df[(aggregated_df["final_occupancy"] >= 0) & (aggregated_df["final_occupancy"] <= 100)]

        return aggregated_df[["stay_date_dt", "days_out", "current_occupancy", "final_occupancy", "day_type"]]

    raise ValueError("Invalid mapping configuration for uploaded data")


def load_backtest_dataset(csv_path: Optional[str] = None) -> pd.DataFrame:
    path = csv_path or DEFAULT_BACKTEST_DATA_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Backtest dataset not found: {path}")

    df = pd.read_csv(path)
    required_cols = {"stay_date", "days_out", "final_occupancy", "day_type"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns for backtesting: {sorted(missing)}")

    if "current_occupancy" not in df.columns:
        if "rooms_booked_cumulative" in df.columns:
            df["current_occupancy"] = pd.to_numeric(df["rooms_booked_cumulative"], errors="coerce")
        else:
            raise ValueError(
                "Backtest dataset must contain either 'current_occupancy' or 'rooms_booked_cumulative'"
            )

    df["stay_date_dt"] = pd.to_datetime(
        df["stay_date"].astype(str),
        format="%d%m%Y",
        errors="coerce",
    )
    df["days_out"] = pd.to_numeric(df["days_out"], errors="coerce").astype("Int64")
    df["current_occupancy"] = pd.to_numeric(df["current_occupancy"], errors="coerce")
    df["final_occupancy"] = pd.to_numeric(df["final_occupancy"], errors="coerce")
    df["day_type"] = df["day_type"].astype(str).str.lower().str.strip()

    df = df.dropna(subset=["stay_date_dt", "days_out", "current_occupancy", "final_occupancy"])
    df = df[(df["days_out"] >= 0) & (df["days_out"] <= 30)]

    return df


def _run_backtest_on_prepared_df(
    source_df: pd.DataFrame,
    completion_ratios_df: Optional[pd.DataFrame] = None,
    dataset_path_label: str = DEFAULT_BACKTEST_DATA_PATH,
    total_rooms_available: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    day_type: str = "all",
    days_out_min: int = 0,
    days_out_max: int = 30,
    include_details: bool = True,
    detail_limit: int = 500,
) -> dict:
    if total_rooms_available <= 0:
        raise ValueError("total_rooms_available must be greater than 0")

    if days_out_min < 0 or days_out_max > 30 or days_out_min > days_out_max:
        raise ValueError("days_out range must be within 0-30 and min <= max")

    if day_type not in {"all", "weekday", "weekend"}:
        raise ValueError("day_type must be one of: all, weekday, weekend")

    parsed_start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    parsed_end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None
    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise ValueError("start_date cannot be after end_date")

    filtered_df = source_df.copy()
    filtered_df = filtered_df[(filtered_df["days_out"] >= days_out_min) & (filtered_df["days_out"] <= days_out_max)]

    if day_type != "all":
        filtered_df = filtered_df[filtered_df["day_type"] == day_type]

    if parsed_start is not None:
        filtered_df = filtered_df[filtered_df["stay_date_dt"] >= parsed_start]

    if parsed_end is not None:
        filtered_df = filtered_df[filtered_df["stay_date_dt"] <= parsed_end]

    if filtered_df.empty:
        return {
            "summary": _build_metrics(pd.DataFrame()),
            "by_day_type": [],
            "by_days_out": [],
            "details": [],
            "input_filters": {
                "total_rooms_available": total_rooms_available,
                "start_date": start_date,
                "end_date": end_date,
                "day_type": day_type,
                "days_out_min": days_out_min,
                "days_out_max": days_out_max,
                "dataset_path": dataset_path_label,
            },
            "dataset_stats": {
                "source_rows": int(len(source_df)),
                "evaluated_rows": 0,
            },
        }

    ratios_df = completion_ratios_df if completion_ratios_df is not None else load_completion_ratios()

    detail_rows: list[dict] = []
    skipped_rows = 0

    for row in filtered_df.itertuples(index=False):
        stay_date_dt = getattr(row, "stay_date_dt")
        days_out_value = int(getattr(row, "days_out"))
        current_occ = _safe_float(getattr(row, "current_occupancy"))
        actual_final_occ = _safe_float(getattr(row, "final_occupancy"))
        row_day_type = str(getattr(row, "day_type")).lower().strip()

        today_date_dt = stay_date_dt - timedelta(days=days_out_value)

        model_input = {
            "stay_date": _to_ddmmyy(stay_date_dt),
            "today_date": _to_ddmmyy(today_date_dt),
            "current_occupancy": float(current_occ),
            "total_rooms_available": int(total_rooms_available),
            "event_level": "none",
        }

        try:
            forecast_result = forecast_occupancy(model_input, ratios_df)
            predicted_occ = float(forecast_result["forecast_occupancy_pct"])
        except Exception:
            skipped_rows += 1
            continue

        error = predicted_occ - actual_final_occ
        abs_error = abs(error)
        squared_error = error ** 2
        ape = (abs_error / actual_final_occ) if actual_final_occ > 0 else np.nan

        detail_rows.append(
            {
                "stay_date": stay_date_dt.strftime("%Y-%m-%d"),
                "day_type": row_day_type,
                "days_out": days_out_value,
                "current_occupancy_pct": round(float(current_occ), 4),
                "actual_final_occupancy_pct": round(float(actual_final_occ), 4),
                "predicted_final_occupancy_pct": round(float(predicted_occ), 4),
                "error": round(float(error), 4),
                "abs_error": round(float(abs_error), 4),
                "squared_error": round(float(squared_error), 4),
                "ape": float(ape) if pd.notna(ape) else np.nan,
            }
        )

    details_df = pd.DataFrame(detail_rows)

    summary = _build_metrics(details_df)
    by_day_type = _build_breakdown(details_df, "day_type")
    by_days_out = _build_breakdown(details_df, "days_out")

    details_payload = []
    if include_details and not details_df.empty:
        details_copy = details_df.copy()
        details_copy["ape_pct"] = np.where(
            details_copy["ape"].notna(),
            np.round(details_copy["ape"] * 100.0, 4),
            np.nan,
        )
        details_copy = details_copy.drop(columns=["ape"])
        details_payload = details_copy.head(max(1, detail_limit)).replace({np.nan: None}).to_dict(orient="records")

    return {
        "summary": summary,
        "by_day_type": by_day_type,
        "by_days_out": by_days_out,
        "details": details_payload,
        "input_filters": {
            "total_rooms_available": total_rooms_available,
            "start_date": start_date,
            "end_date": end_date,
            "day_type": day_type,
            "days_out_min": days_out_min,
            "days_out_max": days_out_max,
            "dataset_path": dataset_path_label,
        },
        "dataset_stats": {
            "source_rows": int(len(source_df)),
            "candidate_rows": int(len(filtered_df)),
            "evaluated_rows": int(len(details_df)),
            "skipped_rows": int(skipped_rows),
            "min_stay_date": filtered_df["stay_date_dt"].min().strftime("%Y-%m-%d") if not filtered_df.empty else None,
            "max_stay_date": filtered_df["stay_date_dt"].max().strftime("%Y-%m-%d") if not filtered_df.empty else None,
        },
    }


def run_backtest(
    completion_ratios_df: Optional[pd.DataFrame] = None,
    csv_path: Optional[str] = None,
    total_rooms_available: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    day_type: str = "all",
    days_out_min: int = 0,
    days_out_max: int = 30,
    include_details: bool = True,
    detail_limit: int = 500,
) -> dict:
    source_df = load_backtest_dataset(csv_path=csv_path)
    return _run_backtest_on_prepared_df(
        source_df=source_df,
        completion_ratios_df=completion_ratios_df,
        dataset_path_label=csv_path or DEFAULT_BACKTEST_DATA_PATH,
        total_rooms_available=total_rooms_available,
        start_date=start_date,
        end_date=end_date,
        day_type=day_type,
        days_out_min=days_out_min,
        days_out_max=days_out_max,
        include_details=include_details,
        detail_limit=detail_limit,
    )


def run_backtest_uploaded(
    file_bytes: bytes,
    filename: str,
    mapping: dict,
    completion_ratios_df: Optional[pd.DataFrame] = None,
    total_rooms_available: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    day_type: str = "all",
    days_out_min: int = 0,
    days_out_max: int = 30,
    include_details: bool = True,
    detail_limit: int = 500,
) -> dict:
    uploaded_df = load_uploaded_dataframe(file_bytes=file_bytes, filename=filename)
    mapping_payload = {**mapping, "raw_data_mode": True}
    prepared_df = prepare_uploaded_backtest_dataset(
        source_df=uploaded_df,
        mapping=mapping_payload,
        total_rooms_available=total_rooms_available,
    )

    return _run_backtest_on_prepared_df(
        source_df=prepared_df,
        completion_ratios_df=completion_ratios_df,
        dataset_path_label=f"uploaded:{filename}",
        total_rooms_available=total_rooms_available,
        start_date=start_date,
        end_date=end_date,
        day_type=day_type,
        days_out_min=days_out_min,
        days_out_max=days_out_max,
        include_details=include_details,
        detail_limit=detail_limit,
    )
