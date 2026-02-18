"""
Occupancy Forecasting and Pricing Recommendation Engine

Combines:
1. Forecasting: Predicts final occupancy based on booking pace
2. Pricing: Recommends ADR adjustments to achieve target occupancy
"""

import pandas as pd
from datetime import datetime
import os

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    # Default price cap (recommended: ±12%)
    # This prevents extreme price swings that could harm brand positioning
    'default_price_cap': 12.0,  # percentage
    
    # Event pricing adjustments
    'event_premiums': {
        'none': 0.0,
        'minor': 10.0,   # Minor events: +10% additional adjustment
        'major': 20.0    # Major events: +20% additional adjustment
    },
    
    # Demand signal thresholds
    'demand_threshold': 2.0,  # ±2% occupancy gap threshold
    
    # Sensitivity factor options
    'sensitivity_options': {
        'conservative': 0.3,
        'moderate': 0.5,
        'aggressive': 0.8
    },
    
    # Forecast warning threshold
    'high_occupancy_threshold': 95.0,  # Flag forecasts >= 95%
    
    # Zero occupancy error threshold
    'zero_occ_days_threshold': 20  # Error if 0% at 20+ days out
}

# ============================================================================
# INPUT VALIDATION & HELPERS
# ============================================================================

def parse_date(date_str):
    """
    Convert DDMMYY string to datetime object.
    
    Input format: 'DDMMYY' (e.g., '150226' for 15 Feb 2026)
    """
    try:
        return datetime.strptime(date_str, '%d%m%y')
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Expected format: DDMMYY (e.g., 150226)")

def get_day_type(date_str):
    """
    Determine if date is weekday (Mon-Thu) or weekend (Fri-Sun).
    
    Input: date_str in DDMMYY format
    Output: 'weekday' or 'weekend'
    """
    date_obj = parse_date(date_str)
    weekday = date_obj.weekday()  # 0=Monday, 6=Sunday
    return 'weekday' if weekday <= 3 else 'weekend'

def calculate_days_out(stay_date_str, today_date_str):
    """
    Calculate days between today and stay_date.
    
    Input: Both dates in DDMMYY format
    Output: integer (days)
    """
    stay_date = parse_date(stay_date_str)
    today_date = parse_date(today_date_str)
    days = (stay_date - today_date).days
    
    if days < 0:
        raise ValueError(f"Stay date ({stay_date_str}) cannot be in the past")
    if days > 30:
        raise ValueError(f"Stay date is {days} days out. System only supports forecasts up to 30 days out")
    
    return days

def validate_inputs(inputs):
    """
    Validate all user inputs.
    
    Expected input format:
    {
        'stay_date': 'DDMMYY',             # e.g., '150226'
        'today_date': 'DDMMYY',            # e.g., '010226'
        'current_occupancy': 50.0,         # Percentage (0-100)
        'current_adr': 280.00,             # Currency amount (e.g., RM 280.00)
        'target_occupancy': 90.0,          # Percentage (0-100)
        'sensitivity_factor': 0.5,         # 0.3, 0.5, or 0.8
        'event_level': 'none',             # 'none', 'minor', or 'major'
        'total_rooms_available': 100       # Integer
    }
    """
    errors = []
    
    # Date validations
    if 'stay_date' not in inputs:
        errors.append("stay_date is required (format: DDMMYY)")
    if 'today_date' not in inputs:
        errors.append("today_date is required (format: DDMMYY)")
    
    # Numeric validations
    if inputs.get('current_occupancy', -1) < 0 or inputs.get('current_occupancy', 101) > 100:
        errors.append("current_occupancy must be between 0 and 100 (percentage)")
    
    if inputs.get('target_occupancy', -1) < 0 or inputs.get('target_occupancy', 101) > 100:
        errors.append("target_occupancy must be between 0 and 100 (percentage)")
    
    if inputs.get('current_adr', 0) <= 0:
        errors.append("current_adr must be greater than 0")
    
    if inputs.get('total_rooms_available', 0) <= 0:
        errors.append("total_rooms_available must be greater than 0")
    
    # Categorical validations
    valid_events = ['none', 'minor', 'major']
    if inputs.get('event_level') not in valid_events:
        errors.append(f"event_level must be one of: {valid_events}")
    
    valid_k = list(CONFIG['sensitivity_options'].values())
    if inputs.get('sensitivity_factor') not in valid_k:
        errors.append(f"sensitivity_factor must be one of: {valid_k}")
    
    if errors:
        raise ValueError("Input validation errors:\n" + "\n".join(f"  - {e}" for e in errors))
    
    return True

# ============================================================================
# COMPLETION RATIO LOOKUP
# ============================================================================

def load_completion_ratios(filepath=None):
    """Load pre-calculated completion ratios."""
    if filepath is None:
        # Use path relative to this file's location
        filepath = os.path.join(os.path.dirname(__file__), 'data', 'completion_ratios.csv')
    
    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"Completion ratios file not found: {filepath}\n"
            "Please run completion_model.py first to generate this file."
        )
    
    return pd.read_csv(filepath)

def get_completion_ratio(day_type, days_out, completion_ratios_df):
    """
    Retrieve completion ratio for given day_type and days_out.
    
    Args:
        day_type: 'weekday', 'weekend', or 'event'
        days_out: 0-30
        completion_ratios_df: DataFrame with completion ratios
    
    Returns:
        dict with 'ratio', 'confidence', 'sample_count'
    """
    # For events, use weekend completion ratios
    lookup_day_type = 'weekend' if day_type == 'event' else day_type
    
    result = completion_ratios_df[
        (completion_ratios_df['day_type'] == lookup_day_type) & 
        (completion_ratios_df['days_out'] == days_out)
    ]
    
    if len(result) == 0:
        raise ValueError(
            f"No completion ratio found for day_type={lookup_day_type}, days_out={days_out}"
        )
    
    row = result.iloc[0]
    
    return {
        'ratio': row['avg_completion_ratio'],
        'confidence': row['confidence'],
        'sample_count': int(row['sample_count'])
    }

# ============================================================================
# FORECASTING ENGINE
# ============================================================================

def forecast_occupancy(inputs, completion_ratios_df, config=CONFIG):
    """
    Forecast final occupancy based on current booking pace.
    
    Formula: forecast_occupancy = current_occupancy / completion_ratio
    
    Returns: dict with forecast results
    """
    # Calculate days out
    days_out = calculate_days_out(inputs['stay_date'], inputs['today_date'])
    
    # Determine day type
    base_day_type = get_day_type(inputs['stay_date'])
    
    # If event flagged, override day_type for display purposes
    if inputs['event_level'] != 'none':
        day_type = 'event'
    else:
        day_type = base_day_type
    
    # Get current occupancy
    current_occ_pct = inputs['current_occupancy']
    
    # ✅ ERROR: Zero occupancy too far out
    if current_occ_pct == 0 and days_out >= config['zero_occ_days_threshold']:
        raise ValueError(
            f"Insufficient booking data: 0% occupancy at {days_out} days out. "
            "Cannot generate reliable forecast. Check back when bookings begin."
        )
    
    # Get completion ratio (uses weekend ratio for events)
    ratio_info = get_completion_ratio(day_type, days_out, completion_ratios_df)
    completion_ratio = ratio_info['ratio']
    
    # Calculate forecast
    if completion_ratio == 0:
        raise ValueError("Completion ratio is 0 - cannot forecast")
    
    forecast_occ_pct = current_occ_pct / completion_ratio
    
    # Track if forecast exceeds 100% (overbooking scenario)
    forecast_capped = forecast_occ_pct > 100
    
    # Calculate rooms based on actual forecast (can exceed total rooms)
    forecast_rooms = int(round(forecast_occ_pct * inputs['total_rooms_available'] / 100))
    
    return {
        'days_out': days_out,
        'day_type': day_type,
        'completion_ratio': completion_ratio,
        'forecast_occupancy_pct': round(forecast_occ_pct, 2),
        'forecast_occupancy_rooms': forecast_rooms,
        'confidence_level': ratio_info['confidence'],
        'sample_count': ratio_info['sample_count'],
        'forecast_capped': forecast_capped
    }

# ============================================================================
# PRICING RECOMMENDATION ENGINE
# ============================================================================

def get_monthly_target(stay_date_str, monthly_targets):
    """
    Get target occupancy or ADR for a specific date based on its month.
    
    Args:
        stay_date_str: Date in DDMMYY format (e.g., '150226')
        monthly_targets: Dict with month names as keys (e.g., {'jan': 75.0, 'feb': 80.0, ...})
    
    Returns:
        Target value for that month
    """
    date_obj = parse_date(stay_date_str)
    month_names = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 
                   'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    month_key = month_names[date_obj.month - 1]
    
    return monthly_targets[month_key]

def calculate_price_adjustment(inputs, forecast_results, config=CONFIG):
    """
    Calculate recommended price adjustment based on occupancy gap.
    
    Formula:
    - No event: price_adj = k × (forecast - target)
    - Event: price_adj = k × (forecast - target) + event_premium
    
    Event adjustments bypass standard cap (events get higher allowable cap)
    
    Args:
        inputs: Can contain either:
            - 'target_occupancy': single value (for single-day mode)
            - 'monthly_targets': dict (for bulk mode, will lookup based on stay_date)
    
    Returns: dict with pricing recommendations
    """
    # Calculate occupancy gap
    forecast_occ = forecast_results['forecast_occupancy_pct']
    
    # Get target occupancy (support both single value and monthly lookup)
    if 'monthly_targets' in inputs:
        target_occ = get_monthly_target(inputs['stay_date'], inputs['monthly_targets'])
    else:
        target_occ = inputs['target_occupancy']
    
    occupancy_gap = forecast_occ - target_occ
    
    # Determine demand signal
    threshold = config['demand_threshold']
    if occupancy_gap > threshold:
        demand_signal = 'High Demand'
    elif occupancy_gap < -threshold:
        demand_signal = 'Low Demand'
    else:
        demand_signal = 'On Target'
    
    # Base price adjustment
    k = inputs['sensitivity_factor']
    base_adjustment = k * occupancy_gap
    
    # Add event premium if applicable
    event_premium = config['event_premiums'][inputs['event_level']]
    
    # For events, add premium only if demand is high/on-target
    # If demand is low even for an event, we might still need to decrease price
    if inputs['event_level'] != 'none' and occupancy_gap >= 0:
        price_adjustment_pct = base_adjustment + event_premium
    else:
        price_adjustment_pct = base_adjustment
    
    # ✅ UPDATED: Apply price cap (events get higher cap)
    base_price_cap = config['default_price_cap']
    
    # For events, increase the allowable cap
    if inputs['event_level'] != 'none':
        price_cap = base_price_cap + config['event_premiums'][inputs['event_level']]
    else:
        price_cap = base_price_cap
    
    adjustment_capped = False
    
    if price_adjustment_pct > price_cap:
        price_adjustment_pct = price_cap
        adjustment_capped = True
    elif price_adjustment_pct < -price_cap:
        price_adjustment_pct = -price_cap
        adjustment_capped = True
    
    # Calculate recommended ADR (support both single value and monthly lookup)
    if 'monthly_adr_budgets' in inputs:
        current_adr = get_monthly_target(inputs['stay_date'], inputs['monthly_adr_budgets'])
    else:
        current_adr = inputs['current_adr']
    
    recommended_adr = current_adr * (1 + price_adjustment_pct / 100)
    price_change_amount = recommended_adr - current_adr
    
    # Generate recommendation text
    if abs(occupancy_gap) <= threshold:
        recommendation_text = f"Maintain current price. Forecast is on target ({forecast_occ:.1f}% vs {target_occ:.1f}% target)."
    elif occupancy_gap > 0:
        recommendation_text = f"Increase price by {price_adjustment_pct:.2f}% to achieve target occupancy of {target_occ:.1f}%"
    else:
        recommendation_text = f"Decrease price by {abs(price_adjustment_pct):.2f}% to achieve target occupancy of {target_occ:.1f}%"
    
    if adjustment_capped:
        recommendation_text += f" (capped at ±{price_cap:.0f}%)"
    
    return {
        'target_occupancy': target_occ,
        'current_adr': current_adr,
        'occupancy_gap': round(occupancy_gap, 2),
        'demand_signal': demand_signal,
        'price_adjustment_pct': round(price_adjustment_pct, 2),
        'recommended_adr': round(recommended_adr, 2),
        'price_change_amount': round(price_change_amount, 2),
        'adjustment_capped': adjustment_capped,
        'price_cap_used': price_cap,
        'event_premium_applied': event_premium if inputs['event_level'] != 'none' else 0,
        'recommendation_text': recommendation_text
    }

# ============================================================================
# WARNINGS & VALIDATION
# ============================================================================

def generate_warnings(inputs, forecast_results, pricing_results, config=CONFIG):
    """Generate warnings and alerts based on results."""
    warnings = []
    
    # Low confidence warning
    if forecast_results['confidence_level'] == 'low':
        warnings.append(
            f"⚠️ Low confidence: Only {forecast_results['sample_count']} historical samples available"
        )
    
    # Forecast exceeds 100% warning
    if forecast_results.get('forecast_capped'):
        warnings.append(
            f"⚠️ Forecast exceeds 100% ({forecast_results['forecast_occupancy_pct']:.1f}%) - very high demand expected"
        )
    # High occupancy forecast warning (95-100% only, to avoid duplicate with >100% warning)
    elif forecast_results['forecast_occupancy_pct'] >= config['high_occupancy_threshold']:
        warnings.append(
            f"🔴 Very high demand forecast: {forecast_results['forecast_occupancy_pct']:.1f}% - consider aggressive pricing"
        )
    
    # Price adjustment capped warning
    if pricing_results['adjustment_capped']:
        warnings.append(
            f"⚠️ Price adjustment capped at ±{pricing_results['price_cap_used']:.0f}%"
        )
    
    # Event flagged notice
    if inputs['event_level'] != 'none':
        warnings.append(
            f"ℹ️ Event flagged ({inputs['event_level']}): Using weekend completion ratios with +{pricing_results['event_premium_applied']:.0f}% premium"
        )
    
    # Very low current occupancy warning
    days_out = forecast_results['days_out']
    if days_out <= 7 and inputs['current_occupancy'] < 30:
        warnings.append(
            "⚠️ Current occupancy very low with only 1 week remaining - forecast may be unreliable"
        )
    
    return warnings

# ============================================================================
# MAIN FORECASTING & PRICING FUNCTION
# ============================================================================

def forecast_and_price(inputs, completion_ratios_df=None):
    """
    Main function: Forecast occupancy and recommend pricing.
    
    Input format (dict):
    {
        'stay_date': str,              # DDMMYY format (e.g., '150226')
        'today_date': str,             # DDMMYY format (e.g., '010226')
        'current_occupancy': float,    # Percentage 0-100 (e.g., 50.0)
        'current_adr': float,          # Currency amount (e.g., 280.00)
        'target_occupancy': float,     # Percentage 0-100 (e.g., 90.0)
        'sensitivity_factor': float,   # 0.3, 0.5, or 0.8
        'event_level': str,            # 'none', 'minor', or 'major'
        'total_rooms_available': int   # e.g., 100
    }
    
    Output format (dict): Combined forecast and pricing results with warnings
    """
    # Validate inputs
    validate_inputs(inputs)
    
    # Load completion ratios if not provided
    if completion_ratios_df is None:
        completion_ratios_df = load_completion_ratios()
    
    # Run forecast
    forecast_results = forecast_occupancy(inputs, completion_ratios_df)
    
    # Calculate pricing
    pricing_results = calculate_price_adjustment(inputs, forecast_results)
    
    # Generate warnings
    warnings = generate_warnings(inputs, forecast_results, pricing_results)
    
    # Combine results
    output = {
        **forecast_results,
        **pricing_results,
        'warnings': warnings
    }
    
    return output

# ============================================================================
# HELPER FOR UI - GET OPTIONS
# ============================================================================

def get_input_options():
    """
    Return available options for dropdown/select inputs in UI.
    
    Use this in Streamlit to populate selectboxes.
    """
    return {
        'event_levels': ['none', 'minor', 'major'],
        'sensitivity_factors': CONFIG['sensitivity_options'],
        'default_price_cap': CONFIG['default_price_cap']
    }

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    from datetime import datetime
    
    print("=" * 70)
    print("🏨 HOTEL PRICING & FORECASTING ENGINE")
    print("=" * 70)
    
    # Get today's date automatically
    today_date = datetime.now().strftime('%d%m%y')
    print(f"\n📅 Today's Date: {today_date}")
    
    # ========================================================================
    # PART 1: GET BASIC INPUTS FOR FORECASTING
    # ========================================================================
    print("\n" + "=" * 70)
    print("📊 PART 1: OCCUPANCY FORECAST")
    print("=" * 70)
    print("\n📝 Enter basic information:\n")
    
    try:
        stay_date = input("Stay Date (DDMMYY, e.g., 150326): ").strip()
        current_occupancy = float(input("Current Occupancy (%, e.g., 50): "))
        total_rooms = int(input("Total Rooms Available (default=100): ").strip() or "100")
        
        # Build minimal input for forecast
        forecast_input = {
            'stay_date': stay_date,
            'today_date': today_date,
            'current_occupancy': current_occupancy,
            'total_rooms_available': total_rooms,
            'current_adr': 0,  # Not needed for forecast
            'target_occupancy': 0,  # Not needed yet
            'sensitivity_factor': 0.5,  # Not needed yet
            'event_level': 'none'  # Not needed yet
        }
        
        # Load completion ratios and run forecast
        print("\n🔄 Calculating forecast...")
        completion_ratios_df = load_completion_ratios()
        forecast_results = forecast_occupancy(forecast_input, completion_ratios_df)
        
        # Display forecast results
        print("\n" + "=" * 70)
        print("📊 FORECAST RESULTS")
        print("=" * 70)
        print(f"\n   Days out: {forecast_results['days_out']}")
        print(f"   Day type: {forecast_results['day_type']}")
        print(f"   Completion ratio: {forecast_results['completion_ratio']:.2%}")
        print(f"   Current occupancy: {current_occupancy:.1f}%")
        print(f"   Forecast occupancy: {forecast_results['forecast_occupancy_pct']:.1f}% ({forecast_results['forecast_occupancy_rooms']} rooms)")
        print(f"   Confidence: {forecast_results['confidence_level']} ({forecast_results['sample_count']} samples)")
        
        # Show overbooking warning if forecast > 100%
        if forecast_results['forecast_occupancy_pct'] > 100:
            print(f"\n   ⚠️  OVERBOOKING ALERT: Forecast exceeds 100% capacity!")
            print(f"   Projected: {forecast_results['forecast_occupancy_pct']:.1f}% ({forecast_results['forecast_occupancy_rooms']} rooms)")
            print(f"   Overbooked by: {forecast_results['forecast_occupancy_rooms'] - total_rooms} rooms")
        
        # ========================================================================
        # PART 2: GET PRICING INPUTS AND RECOMMENDATIONS
        # ========================================================================
        print("\n" + "=" * 70)
        print("💰 PART 2: PRICING RECOMMENDATIONS")
        print("=" * 70)
        print("\n📝 Enter pricing parameters:\n")
        
        current_adr = float(input("Current ADR (RM, e.g., 280): "))
        target_occupancy = float(input(f"Target Occupancy (%, e.g., 85): "))
        
        print("\nSensitivity Options:")
        print("  1. Conservative (0.3) - Gentle price adjustments")
        print("  2. Moderate (0.5) - Balanced approach")
        print("  3. Aggressive (0.8) - Strong price movements")
        sensitivity_choice = input("Choose sensitivity (1/2/3, default=2): ").strip() or "2"
        sensitivity_map = {"1": 0.3, "2": 0.5, "3": 0.8}
        sensitivity_factor = sensitivity_map.get(sensitivity_choice, 0.5)
        
        print("\nEvent Level:")
        print("  1. None - Regular day")
        print("  2. Minor - Small event/holiday")
        print("  3. Major - Major event/peak season")
        event_choice = input("Choose event level (1/2/3, default=1): ").strip() or "1"
        event_map = {"1": "none", "2": "minor", "3": "major"}
        event_level = event_map.get(event_choice, "none")
        
        # Build complete input
        complete_input = {
            'stay_date': stay_date,
            'today_date': today_date,
            'current_occupancy': current_occupancy,
            'current_adr': current_adr,
            'target_occupancy': target_occupancy,
            'sensitivity_factor': sensitivity_factor,
            'event_level': event_level,
            'total_rooms_available': total_rooms
        }
        
        print("\n🔄 Calculating pricing recommendations...")
        
        # Calculate pricing
        pricing_results = calculate_price_adjustment(complete_input, forecast_results)
        warnings = generate_warnings(complete_input, forecast_results, pricing_results)
        
        # Display pricing results
        print("\n" + "=" * 70)
        print("💰 PRICING RECOMMENDATIONS")
        print("=" * 70)
        print(f"\n   Occupancy gap: {pricing_results['occupancy_gap']:+.1f}%")
        print(f"   Demand signal: {pricing_results['demand_signal']}")
        print(f"   Price adjustment: {pricing_results['price_adjustment_pct']:+.2f}%")
        print(f"   Price cap used: ±{pricing_results['price_cap_used']:.0f}%")
        print(f"   Current ADR: RM {current_adr:.2f}")
        print(f"   Recommended ADR: RM {pricing_results['recommended_adr']:.2f}")
        print(f"   Change: RM {pricing_results['price_change_amount']:+.2f}")
        
        print(f"\n📝 RECOMMENDATION:")
        print(f"   {pricing_results['recommendation_text']}")
        
        if warnings:
            print(f"\n⚠️  WARNINGS:")
            for warning in warnings:
                print(f"   {warning}")
        
        print("\n" + "=" * 70)
        print("✅ ANALYSIS COMPLETE")
        print("=" * 70)
        
    except KeyboardInterrupt:
        print("\n\n❌ Operation cancelled by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")