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
import requests
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=Path(PROJECT_ROOT) / ".env")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = int(os.getenv("API_REQUEST_TIMEOUT", "180"))

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

def run_backend(endpoint, method="GET", data=None, files=None):
    """Call FastAPI backend over HTTP."""
    url = f"{API_BASE_URL}{endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
        elif method == "POST":
            response = requests.post(url, json=data, files=files, timeout=REQUEST_TIMEOUT)
        elif method == "PATCH":
            response = requests.patch(url, json=data, timeout=REQUEST_TIMEOUT)
        elif method == "DELETE":
            response = requests.delete(url, timeout=REQUEST_TIMEOUT)
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
tab1, tab2 = st.tabs(["📊 Single-Day Forecast", "📁 Bulk Forecast"])

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
