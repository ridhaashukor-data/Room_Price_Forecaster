"""
Hotel Occupancy Forecasting - Streamlit Frontend

Interactive UI for:
1. Single-day forecasting
2. Bulk Excel upload/download
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=Path(PROJECT_ROOT) / ".env")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = int(os.getenv("API_REQUEST_TIMEOUT", "180"))
API_KEY = (os.getenv("API_KEY") or "").strip()

# ============================================================================
# CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="Hotel Occupancy Forecaster",
    page_icon="🏨",
    layout="wide"
)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_date_to_ddmmyy(date_obj):
    """Convert datetime to DDMMYY format"""
    return date_obj.strftime('%d%m%y')

def format_history_timestamp(timestamp_str):
    """Convert ISO timestamp string to readable date-time label."""
    if not timestamp_str:
        return "Unknown date/time"
    try:
        timestamp_text = str(timestamp_str).replace("Z", "+00:00")
        parsed_dt = datetime.fromisoformat(timestamp_text)
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        local_dt = parsed_dt.astimezone()
        return local_dt.strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        return str(timestamp_str)


def format_raw_range_date(raw_date_value):
    """Normalize raw date range values to DD/MM/YYYY for labels."""
    if raw_date_value in (None, ""):
        return "N/A"

    text = str(raw_date_value).strip()
    if not text or text.upper() == "N/A":
        return "N/A"

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except Exception:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except Exception:
        return text

def format_dataset_used(active_model):
    """Return readable active dataset details for display."""
    model = active_model or {}
    source = str(model.get("source") or "").strip().lower()
    metadata = model.get("training_input_metadata") or {}

    if metadata.get("training_input_type") == "raw-upload" or source.startswith("upload"):
        file_name = metadata.get("raw_file_name") or str(model.get("source") or "").split("upload:", 1)[-1] or "Unknown file"
        uploaded_at = format_history_timestamp(metadata.get("raw_uploaded_at"))
        raw_date_min = format_raw_range_date(metadata.get("raw_stay_date_min"))
        raw_date_max = format_raw_range_date(metadata.get("raw_stay_date_max"))
        return (
            f"Dataset used: {file_name} | uploaded: {uploaded_at} | "
            f"raw date range: {raw_date_min} to {raw_date_max}"
        )

    if source.startswith("built-in"):
        return "Dataset used: completion_ratios.csv (built-in)"

    return f"Dataset used: {source or 'unknown'}"


def format_date_only(timestamp_str):
    """Convert ISO timestamp into compact date text for labels."""
    if not timestamp_str:
        return "N/A"
    try:
        timestamp_text = str(timestamp_str).replace("Z", "+00:00")
        parsed_dt = datetime.fromisoformat(timestamp_text)
        return parsed_dt.strftime("%Y-%m-%d")
    except Exception:
        return str(timestamp_str)


def format_uploaded_dataset_name(metadata):
    """Standard uploaded-model naming format for aggregated datasets."""
    file_name = metadata.get("raw_file_name") or "Unknown file"
    uploaded_at = format_history_timestamp(metadata.get("raw_uploaded_at"))
    raw_date_min = format_raw_range_date(metadata.get("raw_stay_date_min"))
    raw_date_max = format_raw_range_date(metadata.get("raw_stay_date_max"))
    return (
        "Uploaded dataset"
        f" | uploaded: {uploaded_at}"
        f" | raw range: {raw_date_min} to {raw_date_max}"
        f" | file: {file_name}"
    )

def run_backend(endpoint, method="GET", data=None, files=None):
    """Call FastAPI backend over HTTP."""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {"X-API-Key": API_KEY} if API_KEY else None

    try:
        if method == "GET":
            response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
        elif method == "POST":
            if files:
                response = requests.post(url, data=data, files=files, timeout=REQUEST_TIMEOUT, headers=headers)
            else:
                response = requests.post(url, json=data, timeout=REQUEST_TIMEOUT, headers=headers)
        elif method == "PATCH":
            response = requests.patch(url, json=data, timeout=REQUEST_TIMEOUT, headers=headers)
        elif method == "DELETE":
            response = requests.delete(url, timeout=REQUEST_TIMEOUT, headers=headers)
        else:
            st.error(f"❌ Unsupported operation: {method} {endpoint}")
            return None

        if response.status_code >= 400:
            error_message = "Unknown API error"
            try:
                payload = response.json()
                error_message = payload.get("detail") or payload.get("message") or str(payload)
            except Exception:
                error_message = response.text
            st.error(f"❌ API Error ({response.status_code}): {error_message}")
            if response.status_code == 401 and not API_KEY:
                st.caption("Set API_KEY in your .env so Streamlit can authenticate with the API.")
            return None

        return response

    except ValueError as e:
        st.error(f"❌ Validation Error: {e}")
        return None
    except requests.RequestException as e:
        st.error(f"❌ Cannot reach API at {API_BASE_URL}. Details: {e}")
        st.caption("Start the API first: venv\\Scripts\\python.exe endpoint\\endpoint.py")
        return None
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return None

# ============================================================================
# MAIN APP
# ============================================================================

st.title("🏨 Hotel Occupancy Forecasting System")
st.markdown("---")

# Create tabs
tab1, tab2, tab3 = st.tabs(["📊 Single-Day Forecast", "📁 Bulk Forecast", "🧪 Backtesting"])

if "single_last_result" not in st.session_state:
    st.session_state["single_last_result"] = None
if "single_last_current_occupancy" not in st.session_state:
    st.session_state["single_last_current_occupancy"] = None
if "single_last_current_adr" not in st.session_state:
    st.session_state["single_last_current_adr"] = None
if "single_last_total_rooms" not in st.session_state:
    st.session_state["single_last_total_rooms"] = None
if "single_last_record_id" not in st.session_state:
    st.session_state["single_last_record_id"] = None
if "single_last_note" not in st.session_state:
    st.session_state["single_last_note"] = ""
if "single_generated_note_editor" not in st.session_state:
    st.session_state["single_generated_note_editor"] = ""
if "single_generated_note_reset" not in st.session_state:
    st.session_state["single_generated_note_reset"] = False
if "single_history_note_refresh_id" not in st.session_state:
    st.session_state["single_history_note_refresh_id"] = None

# ============================================================================
# TAB 1: SINGLE-DAY FORECAST
# ============================================================================

with tab1:
    st.header("Single-Day Occupancy Forecast")
    st.write("Get forecast and pricing recommendations for a specific date")

    single_tab_model_status = run_backend("/model/datasets")
    if single_tab_model_status and single_tab_model_status.status_code == 200:
        active_model = single_tab_model_status.json().get("data", {}).get("active_dataset") or {}
        if active_model:
            st.caption(format_dataset_used(active_model))
    
    # Get input options from backend
    options_response = run_backend("/options")
    
    if options_response and options_response.status_code == 200:
        options = options_response.json()['data']
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📅 Date Information")
            
            # Today's date (default to current date)
            today_date = st.date_input(
                "Today's Date",
                value=datetime.now(),
                help="The date you're making this forecast"
            )
            
            # Stay date
            stay_date = st.date_input(
                "Stay Date (Check-in)",
                value=datetime.now() + timedelta(days=14),
                min_value=today_date,
                max_value=today_date + timedelta(days=30),
                help="The date you want to forecast (up to 30 days from today)"
            )
            
            # Calculate days out automatically
            days_out = (stay_date - today_date).days
            st.info(f"📊 Days Out: **{days_out}**")
            
        with col2:
            st.subheader("🏨 Property Information")
            
            total_rooms = st.number_input(
                "Total Rooms Available",
                min_value=1,
                value=100,
                help="Total number of rooms in your property"
            )
            
            current_occupancy = st.number_input(
                "Current Occupancy (%)",
                min_value=0.0,
                max_value=100.0,
                value=50.0,
                step=1.0,
                help="Current booked occupancy percentage"
            )
        
        st.markdown("---")
        
        col3, col4 = st.columns(2)
        
        with col3:
            st.subheader("💰 Pricing Information")
            
            current_adr = st.number_input(
                "Current ADR (RM)",
                min_value=0.0,
                value=280.0,
                step=10.0,
                help="Current Average Daily Rate"
            )
            
            target_occupancy = st.number_input(
                "Target Occupancy (%)",
                min_value=0.0,
                max_value=100.0,
                value=85.0,
                step=1.0,
                help="Your target occupancy goal"
            )
        
        with col4:
            st.subheader("⚙️ Settings")
            
            sensitivity = st.selectbox(
                "Pricing Sensitivity",
                options=['conservative', 'moderate', 'aggressive'],
                index=1,
                help="How aggressively to adjust prices"
            )
            sensitivity_factor = options['sensitivity_factors'][sensitivity]
            st.caption(f"Factor: {sensitivity_factor}")
            
            event_level = st.selectbox(
                "Event Level",
                options=options['event_levels'],
                index=0,
                help="Is there a special event on this date?"
            )

            note_text = st.text_area(
                "Note (Optional)",
                value="",
                max_chars=500,
                help="Add a note for this forecast record"
            )
        
        st.markdown("---")
        
        # Forecast button
        if st.button("🔮 Generate Forecast", type="primary", use_container_width=True):
            # Prepare input data
            input_data = {
                "stay_date": format_date_to_ddmmyy(stay_date),
                "today_date": format_date_to_ddmmyy(today_date),
                "current_occupancy": current_occupancy,
                "current_adr": current_adr,
                "target_occupancy": target_occupancy,
                "sensitivity_factor": sensitivity_factor,
                "event_level": event_level,
                "total_rooms_available": total_rooms,
                "note": note_text.strip(),
            }
            
            # Run backend
            with st.spinner("Generating forecast..."):
                response = run_backend("/forecast", method="POST", data=input_data)
            
            if response and response.status_code == 200:
                result = response.json()
                st.session_state["single_last_result"] = result
                st.session_state["single_last_current_occupancy"] = current_occupancy
                st.session_state["single_last_current_adr"] = current_adr
                st.session_state["single_last_total_rooms"] = total_rooms

                latest_single_history_response = run_backend("/single/history?limit=1")
                latest_single_history_items = []
                if latest_single_history_response and latest_single_history_response.status_code == 200:
                    latest_single_history_items = latest_single_history_response.json().get("data", [])

                if latest_single_history_items:
                    latest_single_item = latest_single_history_items[0]
                    st.session_state["single_last_record_id"] = latest_single_item.get("id")
                    st.session_state["single_last_note"] = latest_single_item.get("note") or ""
                else:
                    st.session_state["single_last_record_id"] = None
                    st.session_state["single_last_note"] = note_text.strip()

                st.session_state["single_generated_note_editor"] = st.session_state["single_last_note"]
                
                st.success("✅ Forecast generated successfully!")

        result = st.session_state.get("single_last_result")
        if result:
            current_occupancy_display = st.session_state.get("single_last_current_occupancy") or 0.0
            current_adr_display = st.session_state.get("single_last_current_adr") or 0.0
            total_rooms_display = st.session_state.get("single_last_total_rooms") or 0

            st.markdown("---")
            st.header("📊 Forecast Results")

            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

            with metric_col1:
                st.metric(
                    "Current Occupancy",
                    f"{current_occupancy_display:.1f}%",
                    help="Today's occupancy"
                )

            with metric_col2:
                occupancy_gap = result['occupancy_gap']
                sign = "+" if occupancy_gap >= 0 else "-"
                st.metric(
                    "Forecast Occupancy",
                    f"{result['forecast_occupancy_pct']:.1f}%",
                    delta=f"{sign} {abs(occupancy_gap):.1f}% vs target",
                    delta_color="normal",
                    help="Predicted final occupancy"
                )

            with metric_col3:
                st.metric(
                    "Current ADR",
                    f"RM {current_adr_display:.2f}",
                    help="Current price"
                )

            with metric_col4:
                price_change = result['price_change_amount']
                sign = "+" if price_change >= 0 else "-"
                st.metric(
                    "Recommended ADR",
                    f"RM {result['recommended_adr']:.2f}",
                    delta=f"{sign} RM{abs(price_change):.2f} vs current",
                    delta_color="normal",
                    help="Recommended price"
                )

            st.markdown("---")

            detail_col1, detail_col2 = st.columns(2)

            with detail_col1:
                st.subheader("📈 Forecast Details")

                st.write(f"**Day Type:** {result['day_type'].title()}")
                st.write(f"**Completion Ratio:** {result['completion_ratio']:.4f}")
                st.write(f"**Forecast Rooms:** {result['forecast_occupancy_rooms']} / {total_rooms_display}")
                st.write(f"**Confidence:** {result['confidence_level'].title()} ({result['sample_count']} samples)")

                if result['forecast_capped']:
                    st.warning("⚠️ Forecast exceeds 100% - very high demand!")

            with detail_col2:
                st.subheader("💰 Pricing Details")

                demand_color = {
                    'High Demand': '🔴',
                    'On Target': '🟢',
                    'Low Demand': '🔵'
                }

                st.write(f"**Demand Signal:** {demand_color.get(result['demand_signal'], '⚪')} {result['demand_signal']}")
                st.write(f"**Price Adjustment:** {result['price_adjustment_pct']:+.2f}%")
                st.write(f"**Price Cap Used:** ±{result['price_cap_used']:.0f}%")

                if result['adjustment_capped']:
                    st.warning("⚠️ Price adjustment was capped")

                if result['event_premium_applied'] > 0:
                    st.info(f"ℹ️ Event premium: +{result['event_premium_applied']:.0f}%")

            st.markdown("---")
            st.subheader("💡 Recommendation")
            st.info(result['recommendation_text'])

            if result['warnings']:
                st.markdown("---")
                st.subheader("⚠️ Warnings")
                for warning in result['warnings']:
                    st.warning(warning)

            st.markdown("---")
            st.subheader("📝 Note")

            if st.session_state.get("single_generated_note_reset"):
                st.session_state["single_generated_note_editor"] = st.session_state.get("single_last_note") or ""
                st.session_state["single_generated_note_reset"] = False

            st.text_area(
                "Note",
                key="single_generated_note_editor",
                max_chars=500,
                height=100,
                label_visibility="collapsed"
            )

            generated_record_id = st.session_state.get("single_last_record_id")
            generated_note_col1, generated_note_col2, _ = st.columns([1, 1, 4])

            with generated_note_col1:
                if st.button("💾 Update Note", type="secondary", key="single_generated_update_note"):
                    edited_generated_note = (st.session_state.get("single_generated_note_editor") or "").strip()
                    if not generated_record_id:
                        st.warning("⚠️ Note update requires MongoDB history to be available.")
                    elif not edited_generated_note:
                        st.warning("⚠️ Note is empty. Use Delete Note to clear it.")
                    else:
                        generated_update_response = run_backend(
                            f"/single/history/{generated_record_id}/note",
                            method="PATCH",
                            data={"note": edited_generated_note}
                        )
                        if generated_update_response and generated_update_response.status_code == 200:
                            st.session_state["single_last_note"] = edited_generated_note
                            st.session_state["single_generated_note_reset"] = True
                            st.success("✅ Note updated successfully.")
                            st.rerun()

            with generated_note_col2:
                if st.button("🗑️ Delete Note", type="secondary", key="single_generated_delete_note"):
                    if not generated_record_id:
                        st.warning("⚠️ Note delete requires MongoDB history to be available.")
                    else:
                        generated_delete_response = run_backend(
                            f"/single/history/{generated_record_id}/note",
                            method="DELETE"
                        )
                        if generated_delete_response and generated_delete_response.status_code == 200:
                            st.session_state["single_last_note"] = ""
                            st.session_state["single_generated_note_reset"] = True
                            st.success("✅ Note deleted successfully.")
                            st.rerun()

        st.markdown("---")
        st.subheader("🕘 Single-Day History")

        single_history_response = run_backend("/single/history")
        if single_history_response and single_history_response.status_code == 200:
            single_history_payload = single_history_response.json()
            single_history_items = single_history_payload.get("data", [])
            single_history_message = (single_history_payload.get("message") or "").strip()

            if "mongodb is not connected" in single_history_message.lower():
                st.warning("🟡 Single-day history unavailable: MongoDB is offline.")

            if single_history_items:
                def _format_single_history_item(item):
                    return format_history_timestamp(item.get("created_at"))

                selected_single_index = st.selectbox(
                    "Select a previous single-day forecast",
                    options=list(range(len(single_history_items))),
                    format_func=lambda idx: _format_single_history_item(single_history_items[idx]),
                    index=0,
                    key="single_history_select"
                )

                selected_single_item = single_history_items[selected_single_index]
                selected_single_id = selected_single_item.get("id")

                if st.button("👁️ View Selected Single-Day Record", type="secondary", key="single_history_view_button"):
                    st.session_state["single_history_view_id"] = selected_single_id

                if st.session_state.get("single_history_view_id") == selected_single_id:
                    single_detail_response = run_backend(f"/single/history/{selected_single_id}")
                    if single_detail_response and single_detail_response.status_code == 200:
                        single_detail = single_detail_response.json().get("data", {})
                        single_input = single_detail.get("input") or {}
                        single_output = single_detail.get("output") or {}
                        single_note = single_detail.get("note") or ""
                        note_key = f"single_history_note_editor_{selected_single_id}"
                        should_refresh_history_note = st.session_state.get("single_history_note_refresh_id") == selected_single_id

                        st.caption(f"Saved at: {format_history_timestamp(single_detail.get('created_at'))}")
                        st.caption(f"Last updated: {format_history_timestamp(single_detail.get('updated_at'))}")

                        if note_key not in st.session_state or should_refresh_history_note:
                            st.session_state[note_key] = single_note
                            if should_refresh_history_note:
                                st.session_state["single_history_note_refresh_id"] = None

                        st.markdown("**Saved Input (Table View)**")
                        input_table_df = pd.DataFrame(
                            [{"Field": key, "Value": value} for key, value in single_input.items()]
                        )
                        st.dataframe(input_table_df, use_container_width=True)

                        st.markdown("**Saved Output (Table View)**")
                        output_table_df = pd.DataFrame(
                            [{"Field": key, "Value": value} for key, value in single_output.items()]
                        )
                        st.dataframe(output_table_df, use_container_width=True)

                        st.markdown("**Note**")
                        st.text_area(
                            "Edit note",
                            key=note_key,
                            max_chars=500,
                            height=100,
                            label_visibility="collapsed"
                        )

                        note_action_col1, note_action_col2, _ = st.columns([1, 1, 4])
                        with note_action_col1:
                            if st.button("💾 Update Note", type="secondary", key=f"single_history_update_note_{selected_single_id}"):
                                edited_note = (st.session_state.get(note_key) or "").strip()
                                if not edited_note:
                                    st.warning("⚠️ Note is empty. Use Delete Note to clear it.")
                                else:
                                    update_response = run_backend(
                                        f"/single/history/{selected_single_id}/note",
                                        method="PATCH",
                                        data={"note": edited_note}
                                    )
                                    if update_response and update_response.status_code == 200:
                                        st.session_state["single_history_note_refresh_id"] = selected_single_id
                                        st.success("✅ Note updated successfully.")
                                        st.rerun()

                        with note_action_col2:
                            if st.button("🗑️ Delete Note", type="secondary", key=f"single_history_delete_note_{selected_single_id}"):
                                delete_response = run_backend(
                                    f"/single/history/{selected_single_id}/note",
                                    method="DELETE"
                                )
                                if delete_response and delete_response.status_code == 200:
                                    st.session_state["single_history_note_refresh_id"] = selected_single_id
                                    st.success("✅ Note deleted successfully.")
                                    st.rerun()
            else:
                st.info("No single-day history records found yet.")
        else:
            st.caption("Single-day history is unavailable right now. Check API and MongoDB connection.")

# ============================================================================
# TAB 2: BULK FORECAST
# ============================================================================

with tab2:
    st.header("Bulk Occupancy Forecast")
    st.write("Upload Excel with current occupancy - get side-by-side forecast output with color-coded trends")

    bulk_tab_model_status = run_backend("/model/datasets")
    if bulk_tab_model_status and bulk_tab_model_status.status_code == 200:
        active_model = bulk_tab_model_status.json().get("data", {}).get("active_dataset") or {}
        if active_model:
            st.caption(format_dataset_used(active_model))
    
    # Step 1: Download template
    st.subheader("📥 Step 1: Download Template")
    st.write("Download the template with current + forecast columns. Fill only the current occupancy columns.")
    
    if st.button("⬇️ Download Template", type="secondary"):
        response = run_backend("/bulk/template")
        
        if response and response.status_code == 200:
            st.download_button(
                label="💾 Save Template",
                data=response.content,
                file_name="occupancy_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            st.success("✅ Template ready! Click 'Save Template' to download.")
    
    st.markdown("---")
    
    # Step 2: Upload filled template
    st.subheader("📤 Step 2: Upload Filled Template")
    
    uploaded_file = st.file_uploader(
        "Choose your filled Excel file",
        type=['xlsx', 'xls'],
        help="Upload the template after filling in your occupancy data"
    )
    
    if uploaded_file is not None:
        st.info(f"📄 File uploaded: {uploaded_file.name}")
        
        if st.button("🔮 Generate Bulk Forecast", type="primary"):
            with st.spinner("Processing bulk forecast... This may take a moment."):
                # Prepare file for upload
                files = {
                    'file': (uploaded_file.name, uploaded_file.getvalue(), 
                            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                }
                
                response = run_backend("/bulk/upload", method="POST", files=files)
            
            if response and response.status_code == 200:
                st.success("✅ Bulk forecast generated successfully!")
                
                # Provide download button
                st.download_button(
                    label="⬇️ Download Forecast Output",
                    data=response.content,
                    file_name=f"forecast_output_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )
                
                st.info("""
                📊 **Output contains:**
                - Side-by-side view: each month's current & forecast occupancy
                - Borders grouping month pairs (right borders) and marking last valid day (bottom borders)
                - Color gradient: Green (50%) → Yellow (75%) → Red (100%+)
                - Can reuse this file as template for next forecast
                """)

    st.markdown("---")
    st.subheader("🕘 Step 3: Download Past Outputs")

    history_response = run_backend("/bulk/history")
    if history_response and history_response.status_code == 200:
        history_payload = history_response.json()
        history_items = history_payload.get("data", [])
        history_message = (history_payload.get("message") or "").strip()

        if "mongodb is not connected" in history_message.lower():
            st.warning("🟡 History unavailable: MongoDB is offline.")

        if history_items:
            def _format_history_item(item):
                return format_history_timestamp(item.get("created_at"))

            selected_index = st.selectbox(
                "Select a previous output",
                options=list(range(len(history_items))),
                format_func=lambda idx: _format_history_item(history_items[idx]),
                index=0
            )

            selected_item = history_items[selected_index]
            selected_id = selected_item.get("id")

            if st.button("⬇️ Download Selected Past Output", type="secondary"):
                download_response = run_backend(f"/bulk/download/{selected_id}")
                if download_response and download_response.status_code == 200:
                    output_name = selected_item.get("output_filename") or f"bulk_output_{selected_id}.xlsx"
                    st.download_button(
                        label="💾 Save Selected Output",
                        data=download_response.content,
                        file_name=output_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    st.success("✅ Past output is ready. Click 'Save Selected Output'.")
        else:
            st.info("No past bulk outputs found in history yet.")
    else:
        st.caption("Past output history is unavailable right now. Check API and MongoDB connection.")
    
    # Instructions
    st.markdown("---")
    st.subheader("📝 Instructions")
    
    with st.expander("How to use bulk forecast"):
        st.markdown("""
        1. **Download Template**: Click the button above to get the Excel template
        
        2. **Fill in Data**:
           - Upload Date: Current date (DD/MM/YY format)
           - Current Occupancy: Fill ONLY the month columns (Jan, Feb, etc.)
           - Leave forecast columns empty - they will be filled automatically
        
        3. **Upload**: Upload the filled template
        
        4. **Download Results**: Get output Excel with:
           - Current occupancy for each date (from your input)
           - Forecast occupancy for each date (calculated, up to 30 days)
           - Color gradient: Green (50%) → Yellow (75%) → Red (100%+)
        
        **Notes:**
        - Only forecasts up to 30 days from upload date
        - Past dates are ignored
        - Color gradient: Green (50%) → Yellow (75%) → Red (100%+)
        """)

# ============================================================================
# TAB 3: BACKTESTING
# ============================================================================

with tab3:
    st.header("Backtesting")
    st.write("Evaluate occupancy forecast accuracy using historical booking snapshots.")

    def interpret_bias(value):
        if value is None:
            return "Unknown"
        if value > 0.5:
            return "Over-forecasting"
        if value < -0.5:
            return "Under-forecasting"
        return "Near neutral"

    def interpret_precision(within_3_pct):
        if within_3_pct is None:
            return "Unknown"
        if within_3_pct >= 70:
            return "High precision"
        if within_3_pct >= 55:
            return "Moderate precision"
        return "Lower precision"

    def render_backtest_result(backtest_result):
        summary = backtest_result.get("summary", {})
        dataset_stats = backtest_result.get("dataset_stats", {})

        st.success("✅ Backtest completed")

        metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)
        metric_col1.metric("Rows Evaluated", f"{summary.get('count', 0)}")
        metric_col2.metric("MAE", f"{summary.get('mae', 'N/A')}")
        metric_col3.metric("RMSE", f"{summary.get('rmse', 'N/A')}")
        metric_col4.metric("MAPE (%)", f"{summary.get('mape', 'N/A')}")
        metric_col5.metric("Within ±5%", f"{summary.get('within_5_pct', 'N/A')}%")

        st.caption(
            f"Bias interpretation: {interpret_bias(summary.get('bias'))} | "
            f"Precision interpretation: {interpret_precision(summary.get('within_3_pct'))}"
        )

        st.caption(
            f"Source rows: {dataset_stats.get('source_rows', 0)} | "
            f"Candidate rows: {dataset_stats.get('candidate_rows', 0)} | "
            f"Skipped rows: {dataset_stats.get('skipped_rows', 0)}"
        )

        by_day_type = backtest_result.get("by_day_type", [])
        if by_day_type:
            st.markdown("### By Day Type")
            by_day_type_df = pd.DataFrame(by_day_type)
            by_day_type_df["bias_read"] = by_day_type_df["bias"].apply(interpret_bias)
            by_day_type_df["within_3_read"] = by_day_type_df["within_3_pct"].apply(interpret_precision)
            st.dataframe(by_day_type_df, use_container_width=True)

        by_days_out = backtest_result.get("by_days_out", [])
        if by_days_out:
            st.markdown("### By Days Out")
            by_days_out_df = pd.DataFrame(by_days_out)
            by_days_out_df["bias_read"] = by_days_out_df["bias"].apply(interpret_bias)
            by_days_out_df["within_3_read"] = by_days_out_df["within_3_pct"].apply(interpret_precision)
            st.dataframe(by_days_out_df, use_container_width=True)

        details = backtest_result.get("details", [])
        if details:
            st.markdown("### Detailed Rows")
            st.dataframe(pd.DataFrame(details), use_container_width=True)

    st.markdown("### Aggregated Forecast Datasets")
    st.caption("These are aggregated completion-ratio models used by single-day forecast, bulk forecast, and backtesting.")

    model_status_response = run_backend("/model/datasets")
    model_data = {}
    if model_status_response and model_status_response.status_code == 200:
        model_data = model_status_response.json().get("data", {})

    active_model = model_data.get("active_dataset") or {}
    active_model_id = model_data.get("active_dataset_id")
    model_options = model_data.get("datasets", [])

    if active_model:
        st.info(format_dataset_used(active_model))

    if model_options:
        option_ids = [item.get("id") for item in model_options if item.get("id")]

        def _model_option_label(dataset_id):
            for item in model_options:
                if item.get("id") == dataset_id:
                    metadata = item.get("training_input_metadata") or {}
                    input_type = metadata.get("training_input_type")
                    if input_type == "raw-upload":
                        preferred_name = item.get("label") or format_uploaded_dataset_name(metadata)
                        raw_file_name = metadata.get("raw_file_name") or "Unknown file"
                        raw_uploaded_at = format_history_timestamp(metadata.get("raw_uploaded_at"))
                        raw_date_min = format_raw_range_date(metadata.get("raw_stay_date_min"))
                        raw_date_max = format_raw_range_date(metadata.get("raw_stay_date_max"))
                        return (
                            f"{preferred_name} | file: {raw_file_name} | "
                            f"uploaded: {raw_uploaded_at} | range: {raw_date_min} to {raw_date_max}"
                        )
                    return f"{item.get('label', dataset_id)} | built-in | uploaded: N/A | range: N/A"
            return dataset_id

        default_model_index = option_ids.index(active_model_id) if active_model_id in option_ids else 0
        selected_model_id = st.selectbox(
            "Select active forecast dataset",
            options=option_ids,
            index=default_model_index,
            format_func=_model_option_label,
            key="backtest_model_dataset_selector",
        )

        selected_dataset = next((item for item in model_options if item.get("id") == selected_model_id), None)
        selected_metadata = (selected_dataset or {}).get("training_input_metadata") or {}
        if selected_dataset:
            if selected_metadata.get("training_input_type") == "raw-upload":
                st.caption(
                    "Selected aggregated model source -> "
                    f"upload: {selected_metadata.get('raw_file_name') or 'Unknown file'} | "
                    f"uploaded: {format_history_timestamp(selected_metadata.get('raw_uploaded_at'))} | "
                    f"raw date range: {format_raw_range_date(selected_metadata.get('raw_stay_date_min'))} to {format_raw_range_date(selected_metadata.get('raw_stay_date_max'))}"
                )
            else:
                st.caption("Selected aggregated model source -> built-in data")

        dataset_action_col1, dataset_action_col2 = st.columns(2)
        with dataset_action_col1:
            if st.button("✅ Use Selected Dataset", type="secondary", key="backtest_apply_selected_dataset"):
                select_response = run_backend(
                    "/model/datasets/select",
                    method="POST",
                    data={"dataset_id": selected_model_id},
                )
                if select_response and select_response.status_code == 200:
                    st.success("✅ Active forecast dataset updated.")
                    st.rerun()

        with dataset_action_col2:
            delete_disabled = selected_model_id == "default"
            if st.button("🗑️ Delete Selected Dataset", type="secondary", key="backtest_delete_selected_dataset", disabled=delete_disabled):
                delete_response = run_backend(f"/model/datasets/{selected_model_id}", method="DELETE")
                if delete_response and delete_response.status_code == 200:
                    st.success("✅ Selected dataset deleted.")
                    st.rerun()

            if delete_disabled:
                st.caption("Default dataset cannot be deleted.")

    st.markdown("### Data Source")
    backtest_data_source = st.radio(
        "Choose dataset",
        options=["Built-in dataset", "Upload my own data"],
        horizontal=True,
        label_visibility="collapsed",
    )

    base_payload = {
        "total_rooms_available": 100,
        "start_date": None,
        "end_date": None,
        "day_type": "all",
        "days_out_min": 0,
        "days_out_max": 30,
        "include_details": True,
        "detail_limit": 500,
    }

    if backtest_data_source == "Built-in dataset":
        if st.button("🚀 Run Backtest", type="primary", use_container_width=True):
            with st.spinner("Running backtest..."):
                backtest_response = run_backend("/backtest", method="POST", data=base_payload)

            if backtest_response and backtest_response.status_code == 200:
                render_backtest_result(backtest_response.json().get("data", {}))
    else:
        st.markdown("### Raw Upload (Training Input)")
        if st.button("⬇️ Download Sample Upload Template", type="secondary", key="download_backtest_upload_template"):
            template_response = run_backend("/backtest/upload/template")
            if template_response and template_response.status_code == 200:
                st.download_button(
                    label="💾 Save Backtest Upload Template",
                    data=template_response.content,
                    file_name="backtest_upload_template.csv",
                    mime="text/csv",
                    key="save_backtest_upload_template",
                )
                st.success("✅ Template ready. Click 'Save Backtest Upload Template'.")

        uploaded_backtest_file = st.file_uploader(
            "Upload CSV or Excel",
            type=["csv", "xlsx", "xls"],
            help="Upload raw booking rows following the template (booking_id, stay_date, booking_date).",
            key="backtest_custom_upload_file",
        )

        st.caption("Use the upload template format with raw booking rows: booking_id, stay_date, booking_date.")

        mapping_requirements_response = run_backend("/backtest/upload/mapping/requirements")
        mapping_requirements = {}
        if mapping_requirements_response and mapping_requirements_response.status_code == 200:
            mapping_requirements = mapping_requirements_response.json().get("data", {})

        if uploaded_backtest_file is not None:
            uploaded_bytes = uploaded_backtest_file.getvalue()

            analyze_clicked = st.button("🔍 Analyze File Columns", type="secondary", key="backtest_analyze_upload")

            preview_files = {
                "file": (
                    uploaded_backtest_file.name,
                    uploaded_bytes,
                    "application/octet-stream",
                )
            }

            if analyze_clicked:
                preview_response = run_backend("/backtest/upload/preview", method="POST", files=preview_files)
                if preview_response and preview_response.status_code == 200:
                    st.session_state["backtest_upload_preview"] = preview_response.json().get("data", {})
                    st.session_state["backtest_upload_preview_filename"] = uploaded_backtest_file.name

            preview_payload = st.session_state.get("backtest_upload_preview", {})
            preview_filename = st.session_state.get("backtest_upload_preview_filename")

            if preview_payload and preview_filename == uploaded_backtest_file.name:
                st.caption(
                    f"Detected columns: {preview_payload.get('column_count', 0)} | "
                    f"Rows: {preview_payload.get('row_count', 0)}"
                )

                preview_rows = preview_payload.get("sample_rows", [])
                if preview_rows:
                    st.markdown("### File Sample")
                    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

                columns = preview_payload.get("columns", [])
                select_options = ["<None>"] + columns
                suggested_mapping = {}

                def default_index_for(candidates):
                    for candidate in candidates:
                        for idx, column in enumerate(columns):
                            if candidate in str(column).lower():
                                return idx + 1
                    return 0

                def suggested_or_heuristic(field_key, fallback_candidates):
                    suggested = suggested_mapping.get(field_key)
                    if isinstance(suggested, str) and suggested in columns:
                        return select_options.index(suggested)
                    return default_index_for(fallback_candidates)

                st.markdown("### Required Field Pairing")

                required_field_rows = mapping_requirements.get("required_fields", [])
                if required_field_rows:
                    status_rows = []
                    for item in required_field_rows:
                        status_rows.append(
                            {
                                "field": item.get("label", item.get("key")),
                                "required": bool(item.get("required", False)),
                                "description": item.get("description", ""),
                            }
                        )
                    st.dataframe(pd.DataFrame(status_rows), use_container_width=True)

                map_col1, map_col2 = st.columns(2)

                with map_col1:
                    stay_date_col = st.selectbox(
                        "Stay Date (required)",
                        options=select_options,
                        index=suggested_or_heuristic("stay_date_col", ["stay_date", "stay date", "checkin", "arrival"]),
                    )
                    booking_date_col = st.selectbox(
                        "Booking Date (required)",
                        options=select_options,
                        index=suggested_or_heuristic("booking_date_col", ["booking_date", "booked", "snapshot"]),
                    )

                with map_col2:
                    booking_id_col = st.selectbox(
                        "Booking ID (optional)",
                        options=select_options,
                        index=suggested_or_heuristic("booking_id_col", ["booking_id", "reservation", "confirmation", "ref"]),
                    )

                format_col1, format_col2 = st.columns(2)
                with format_col1:
                    stay_date_format = st.text_input(
                        "Stay Date Format (optional)",
                        value="",
                        placeholder="e.g., %d%m%Y or %Y-%m-%d",
                    )
                with format_col2:
                    booking_date_format = st.text_input(
                        "Booking Date Format (optional)",
                        value="",
                        placeholder="e.g., %d/%m/%Y",
                    )

                mapping = {
                    "booking_id_col": None if booking_id_col == "<None>" else booking_id_col,
                    "stay_date_col": None if stay_date_col == "<None>" else stay_date_col,
                    "booking_date_col": None if booking_date_col == "<None>" else booking_date_col,
                    "stay_date_format": stay_date_format.strip() or None,
                    "booking_date_format": booking_date_format.strip() or None,
                }

                uploaded_retrain_label = st.text_input(
                    "Uploaded retrain label (optional)",
                    value="",
                    placeholder="e.g., My property dataset Mar 2026",
                    key="uploaded_retrain_label",
                )

                retrain_col1, retrain_col2 = st.columns(2)

                with retrain_col1:
                    if st.button("🧠 Retrain & Activate From Upload", type="secondary", use_container_width=True):
                        retrain_payload = {
                            "mapping_json": json.dumps(mapping),
                            "total_rooms_available": str(base_payload["total_rooms_available"]),
                            "label": uploaded_retrain_label.strip(),
                            "activate": "true",
                        }
                        retrain_files = {
                            "file": (
                                uploaded_backtest_file.name,
                                uploaded_bytes,
                                "application/octet-stream",
                            )
                        }

                        with st.spinner("Retraining completion ratios from uploaded data..."):
                            retrain_upload_response = run_backend(
                                "/model/retrain/upload",
                                method="POST",
                                data=retrain_payload,
                                files=retrain_files,
                            )

                        if retrain_upload_response and retrain_upload_response.status_code == 200:
                            st.success("✅ Uploaded dataset retrained and activated for all forecasts.")
                            st.rerun()

                with retrain_col2:
                    run_uploaded_backtest = st.button("🚀 Run Uploaded Backtest", type="primary", use_container_width=True)

                if run_uploaded_backtest:
                    upload_run_payload = {
                        "mapping_json": json.dumps(mapping),
                        "total_rooms_available": str(base_payload["total_rooms_available"]),
                        "start_date": base_payload["start_date"] or "",
                        "end_date": base_payload["end_date"] or "",
                        "day_type": base_payload["day_type"],
                        "days_out_min": str(base_payload["days_out_min"]),
                        "days_out_max": str(base_payload["days_out_max"]),
                        "include_details": str(base_payload["include_details"]),
                        "detail_limit": str(base_payload["detail_limit"]),
                    }
                    upload_files = {
                        "file": (
                            uploaded_backtest_file.name,
                            uploaded_bytes,
                            "application/octet-stream",
                        )
                    }

                    with st.spinner("Running uploaded backtest..."):
                        upload_run_response = run_backend(
                            "/backtest/upload/run",
                            method="POST",
                            data=upload_run_payload,
                            files=upload_files,
                        )

                    if upload_run_response and upload_run_response.status_code == 200:
                        render_backtest_result(upload_run_response.json().get("data", {}))

    with st.expander("📘 How to read these metrics", expanded=False):
        st.markdown(
            """
            - **Rows Evaluated**: Number of historical prediction points tested.
            - **MAE**: Average absolute error in occupancy points. Lower is better.
            - **RMSE**: Penalizes large misses more than MAE. If RMSE is much higher than MAE, there are outliers.
            - **MAPE (%)**: Average percentage error relative to actual occupancy. Lower is better.
            - **Within ±5%**: Share of predictions with absolute error ≤ 5 occupancy points. Higher is better.
            - **Bias**: Average signed error (`predicted - actual`). Positive means over-forecasting; negative means under-forecasting.
            """
        )

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.header("ℹ️ About")
    st.write("""
    This system provides occupancy forecasting and pricing recommendations 
    for hotel revenue management.
    
    **Features:**
    - Single-day forecasts
    - Bulk processing
    - Pricing recommendations
    - Historical data analysis
    """)
    
    st.markdown("---")
    
    # Backend Status check
    st.subheader("🔌 Backend Status")
    health_response = run_backend("/health")
    
    if health_response and health_response.status_code == 200:
        health_data = health_response.json()
        st.success("✅ Backend Ready")
        st.caption(f"Last checked: {datetime.now().strftime('%H:%M:%S')}")
        
        if health_data.get('completion_ratios_loaded'):
            st.info("📊 Completion ratios loaded")
    else:
        st.error("❌ Backend Not Ready")
        st.caption("Backend modules failed to load")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    st.write("")
