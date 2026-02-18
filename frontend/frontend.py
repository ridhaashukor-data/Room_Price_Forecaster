"""
Hotel Occupancy Forecasting - Streamlit Frontend

Interactive UI for:
1. Single-day forecasting
2. Bulk Excel upload/download
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import os
import sys
import tempfile
import importlib

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

for path in (PROJECT_ROOT, BACKEND_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from backend.forecaster import (
        forecast_and_price,
        load_completion_ratios,
        get_input_options
    )
    from backend.bulk_processor import (
        generate_template,
        process_bulk_forecast
    )
except ModuleNotFoundError:
    forecaster_module = importlib.import_module("forecaster")
    bulk_processor_module = importlib.import_module("bulk_processor")

    forecast_and_price = forecaster_module.forecast_and_price
    load_completion_ratios = forecaster_module.load_completion_ratios
    get_input_options = forecaster_module.get_input_options
    generate_template = bulk_processor_module.generate_template
    process_bulk_forecast = bulk_processor_module.process_bulk_forecast

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

@st.cache_resource
def get_completion_ratios_df():
    """Load completion ratios once per Streamlit session."""
    return load_completion_ratios()


class LocalResponse:
    """Minimal response object to keep existing UI logic unchanged."""
    def __init__(self, status_code=200, data=None, content=b""):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.content = content

    def json(self):
        return self._data


def run_backend(endpoint, method="GET", data=None, files=None):
    """Run backend operations directly (no separate HTTP server required)."""
    try:
        completion_ratios_df = get_completion_ratios_df()

        if endpoint == "/options" and method == "GET":
            return LocalResponse(
                status_code=200,
                data={
                    "status": "success",
                    "data": get_input_options()
                }
            )

        if endpoint == "/forecast" and method == "POST":
            result = forecast_and_price(data, completion_ratios_df)
            return LocalResponse(status_code=200, data=result)

        if endpoint == "/bulk/template" and method == "GET":
            temp_dir = tempfile.gettempdir()
            template_path = generate_template(output_dir=temp_dir)
            with open(template_path, "rb") as f:
                template_bytes = f.read()
            return LocalResponse(status_code=200, content=template_bytes)

        if endpoint == "/bulk/upload" and method == "POST":
            if not files or 'file' not in files:
                st.error("❌ No file received.")
                return None

            filename, file_bytes, _ = files['file']
            if not filename.lower().endswith(('.xlsx', '.xls')):
                st.error("❌ Invalid file type. Please upload an Excel file (.xlsx or .xls)")
                return None

            temp_dir = tempfile.gettempdir()
            input_path = os.path.join(temp_dir, f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

            with open(input_path, 'wb') as f:
                f.write(file_bytes)

            output_path = process_bulk_forecast(
                input_path,
                output_dir=temp_dir,
                completion_ratios_df=completion_ratios_df
            )

            with open(output_path, "rb") as f:
                output_bytes = f.read()

            return LocalResponse(status_code=200, content=output_bytes)

        if endpoint == "/health" and method == "GET":
            return LocalResponse(
                status_code=200,
                data={
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "completion_ratios_loaded": completion_ratios_df is not None,
                    "service": "Hotel Occupancy Forecasting (Local Mode)"
                }
            )

        st.error(f"❌ Unsupported operation: {method} {endpoint}")
        return None

    except ValueError as e:
        st.error(f"❌ Validation Error: {e}")
        return None
    except FileNotFoundError as e:
        st.error(f"❌ Missing file: {e}")
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
                "total_rooms_available": total_rooms
            }
            
            # Run backend
            with st.spinner("Generating forecast..."):
                response = run_backend("/forecast", method="POST", data=input_data)
            
            if response and response.status_code == 200:
                result = response.json()
                
                st.success("✅ Forecast generated successfully!")
                
                # Display results
                st.markdown("---")
                st.header("📊 Forecast Results")
                
                # Key metrics in columns
                metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
                
                with metric_col1:
                    st.metric(
                        "Current Occupancy",
                        f"{current_occupancy:.1f}%",
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
                        f"RM {current_adr:.2f}",
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
                
                # Detailed results
                st.markdown("---")
                
                detail_col1, detail_col2 = st.columns(2)
                
                with detail_col1:
                    st.subheader("📈 Forecast Details")
                    
                    st.write(f"**Day Type:** {result['day_type'].title()}")
                    st.write(f"**Completion Ratio:** {result['completion_ratio']:.4f}")
                    st.write(f"**Forecast Rooms:** {result['forecast_occupancy_rooms']} / {total_rooms}")
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
                
                # Recommendation
                st.markdown("---")
                st.subheader("💡 Recommendation")
                st.info(result['recommendation_text'])
                
                # Warnings
                if result['warnings']:
                    st.markdown("---")
                    st.subheader("⚠️ Warnings")
                    for warning in result['warnings']:
                        st.warning(warning)

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
           - Bottom borders mark last valid day of each month (e.g., Feb ends at day 28)
        
        3. **Upload**: Upload the filled template
        
        4. **Download Results**: Get output Excel with:
           - Current occupancy for each date (from your input)
           - Forecast occupancy for each date (calculated, up to 30 days)
           - Color gradient: Green (50%) → Yellow (75%) → Red (100%+)
           - Month columns grouped with borders for easy tracking
        
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
