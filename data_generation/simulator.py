"""
Hotel Booking Data Simulator
Generates realistic historical booking transaction data for revenue management forecasting.
"""

import pandas as pd
from datetime import datetime, timedelta
import random
import os

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    'total_rooms': 100,
    'start_date': '01012024',  # DDMMYYYY
    'years_of_history': 2,
    
    # Final occupancy ranges (number of rooms)
    'final_occupancy_range': {
        'weekday': (65, 80),  # Mon-Thu
        'weekend': (80, 90)   # Fri-Sun
    },
    
    # Booking curves - baseline % of final occupancy achieved at each days_out
    # Weekday: Gradual, early booking pattern (business travelers)
    'weekday_curve': {
        30: 0.40, 29: 0.42, 28: 0.44, 27: 0.46, 26: 0.48,
        25: 0.50, 24: 0.52, 23: 0.54, 22: 0.56, 21: 0.58,
        20: 0.60, 19: 0.62, 18: 0.64, 17: 0.66, 16: 0.68,
        15: 0.70, 14: 0.72, 13: 0.74, 12: 0.76, 11: 0.78,
        10: 0.80, 9: 0.82, 8: 0.84, 7: 0.86, 6: 0.88,
        5: 0.90, 4: 0.92, 3: 0.94, 2: 0.96, 1: 0.98, 0: 1.00
    },
    
    # Weekend: Steep, last-minute booking pattern (leisure travelers)
    'weekend_curve': {
        30: 0.25, 29: 0.26, 28: 0.27, 27: 0.28, 26: 0.29,
        25: 0.30, 24: 0.31, 23: 0.32, 22: 0.33, 21: 0.34,
        20: 0.35, 19: 0.37, 18: 0.39, 17: 0.41, 16: 0.43,
        15: 0.45, 14: 0.48, 13: 0.51, 12: 0.54, 11: 0.57,
        10: 0.60, 9: 0.63, 8: 0.66, 7: 0.69, 6: 0.72,
        5: 0.76, 4: 0.80, 3: 0.85, 2: 0.90, 1: 0.95, 0: 1.00
    },
    
    # Random variation range (±10%)
    'variation': 0.10
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_date(date_str):
    """Convert DDMMYYYY string to datetime object."""
    return datetime.strptime(date_str, '%d%m%Y')

def format_date(date_obj):
    """Convert datetime object to DDMMYYYY string."""
    return date_obj.strftime('%d%m%Y')

def get_day_type(date_obj):
    """Determine if date is weekday (Mon-Thu) or weekend (Fri-Sun)."""
    weekday = date_obj.weekday()  # 0=Monday, 6=Sunday
    if weekday <= 3:  # Mon-Thu
        return 'weekday'
    else:  # Fri-Sun
        return 'weekend'

def apply_variation(value, variation_range):
    """Apply random variation to a value within ±variation_range."""
    variation = random.uniform(-variation_range, variation_range)
    result = value * (1 + variation)
    return max(0, result)  # Ensure non-negative

# ============================================================================
# CORE SIMULATION LOGIC
# ============================================================================

def generate_booking_records_for_stay_date(stay_date, config):
    """
    Generate all booking records for a single stay date.
    
    Returns: List of tuples (booking_id_placeholder, stay_date_str, booking_date_str)
    Note: booking_id will be assigned globally later
    """
    stay_date_obj = parse_date(stay_date)
    day_type = get_day_type(stay_date_obj)
    
    # Step 1: Determine final occupancy
    occ_range = config['final_occupancy_range'][day_type]
    final_occupancy = random.randint(occ_range[0], occ_range[1])
    
    # Step 2: Select booking curve
    curve = config[f'{day_type}_curve']
    
    # Step 3: Generate bookings following the curve
    bookings = []
    previous_rooms_booked = 0
    
    for days_out in range(30, -1, -1):  # 30 down to 0
        # Get baseline percentage from curve
        baseline_pct = curve[days_out]
        
        # Apply random variation
        varied_pct = apply_variation(baseline_pct, config['variation'])
        
        # Ensure percentage doesn't exceed 100% or go below previous
        varied_pct = min(varied_pct, 1.0)
        
        # Calculate cumulative rooms booked at this point
        rooms_booked_at_this_point = int(final_occupancy * varied_pct)
        
        # Ensure monotonic increase (can't have fewer bookings than before)
        rooms_booked_at_this_point = max(rooms_booked_at_this_point, previous_rooms_booked)
        
        # Ensure we don't exceed final occupancy until days_out = 0
        if days_out > 0:
            rooms_booked_at_this_point = min(rooms_booked_at_this_point, final_occupancy - 1)
        else:  # days_out = 0, arrival day
            rooms_booked_at_this_point = final_occupancy
        
        # Calculate new bookings made on this booking_date
        new_bookings = rooms_booked_at_this_point - previous_rooms_booked
        
        # Calculate booking_date
        booking_date_obj = stay_date_obj - timedelta(days=days_out)
        booking_date_str = format_date(booking_date_obj)
        stay_date_str = format_date(stay_date_obj)
        
        # Create booking records
        for _ in range(new_bookings):
            bookings.append((None, stay_date_str, booking_date_str))  # booking_id assigned later
        
        previous_rooms_booked = rooms_booked_at_this_point
    
    return bookings

def generate_all_stay_dates(config):
    """Generate list of all stay dates for the simulation period."""
    start_date = parse_date(config['start_date'])
    num_days = config['years_of_history'] * 365
    
    stay_dates = []
    for i in range(num_days):
        stay_date = start_date + timedelta(days=i)
        stay_dates.append(format_date(stay_date))
    
    return stay_dates

def simulate_historical_data(config):
    """
    Main simulation function.
    Generates all booking records for all stay dates.
    
    Returns: pandas DataFrame with columns [booking_id, stay_date, booking_date]
    """
    print("🚀 Starting Hotel Booking Data Simulation...")
    print(f"📅 Period: {config['years_of_history']} years from {config['start_date']}")
    print(f"🏨 Total Rooms: {config['total_rooms']}")
    print()
    
    # Generate all stay dates
    stay_dates = generate_all_stay_dates(config)
    print(f"📊 Generating data for {len(stay_dates)} stay dates...")
    
    # Collect all bookings
    all_bookings = []
    
    for idx, stay_date in enumerate(stay_dates):
        bookings = generate_booking_records_for_stay_date(stay_date, config)
        all_bookings.extend(bookings)
        
        # Progress indicator
        if (idx + 1) % 100 == 0:
            print(f"   Processed {idx + 1}/{len(stay_dates)} stay dates...")
    
    print(f"\n✅ Generated {len(all_bookings)} total booking records")
    
    # Assign sequential booking IDs
    print("🔢 Assigning booking IDs...")
    bookings_with_ids = []
    for idx, (_, stay_date, booking_date) in enumerate(all_bookings, start=1):
        bookings_with_ids.append((idx, stay_date, booking_date))
    
    # Create DataFrame
    df = pd.DataFrame(bookings_with_ids, columns=['booking_id', 'stay_date', 'booking_date'])
    
    print(f"✅ Simulation complete!")
    print(f"\n📈 Summary Statistics:")
    print(f"   Total bookings: {len(df):,}")
    print(f"   Date range: {df['stay_date'].min()} to {df['stay_date'].max()}")
    print(f"   Unique stay dates: {df['stay_date'].nunique()}")
    
    return df

# ============================================================================
# SAVE & EXPORT
# ============================================================================

def save_to_csv(df, output_dir='generated_data', filename='historical_bookings.csv'):
    """Save DataFrame to CSV file."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    
    print(f"\n💾 Data saved to: {filepath}")
    print(f"   File size: {os.path.getsize(filepath) / 1024:.2f} KB")
    
    return filepath

def display_sample(df, n=20):
    """Display sample of generated data."""
    print(f"\n📋 Sample Data (first {n} rows):")
    print(df.head(n).to_string(index=False))

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    # Set random seed for reproducibility (optional - comment out for true randomness)
    random.seed(42)
    
    # Run simulation
    df = simulate_historical_data(CONFIG)
    
    # Display sample
    display_sample(df, n=20)
    
    # Save to CSV
    save_to_csv(df)
    
    print("\n✅ All done! Your historical booking data is ready.")