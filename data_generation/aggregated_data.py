"""
Aggregate raw booking data for completion ratio analysis.
Converts individual booking records into cumulative booking snapshots.
"""

import pandas as pd
from datetime import datetime, timedelta
import os

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_date(date_str):
    """Convert date string/int to datetime object. Handles DDMMYYYY format with missing leading zeros."""
    date_str = str(date_str).strip()
    
    # Pad to 8 digits if leading zero was lost (e.g., 1012024 -> 01012024)
    if len(date_str) < 8:
        date_str = date_str.zfill(8)
    
    # Parse as DDMMYYYY
    return datetime.strptime(date_str, '%d%m%Y')

def format_date(date_obj):
    """Convert datetime object to DDMMYYYY string."""
    return date_obj.strftime('%d%m%Y')

def get_day_type(date_str):
    """Determine if date is weekday (Mon-Thu) or weekend (Fri-Sun)."""
    date_obj = parse_date(date_str)
    weekday = date_obj.weekday()  # 0=Monday, 6=Sunday
    if weekday <= 3:  # Mon-Thu
        return 'weekday'
    else:  # Fri-Sun
        return 'weekend'

def calculate_days_out(stay_date_str, booking_date_str):
    """Calculate number of days between booking_date and stay_date."""
    stay_date = parse_date(stay_date_str)
    booking_date = parse_date(booking_date_str)
    return (stay_date - booking_date).days

# ============================================================================
# AGGREGATION FUNCTIONS
# ============================================================================

def aggregate_bookings(df):
    """
    Aggregate raw booking data into cumulative bookings by days_out.
    
    Input: DataFrame with [booking_id, stay_date, booking_date]
    Output: DataFrame with [stay_date, days_out, rooms_booked_cumulative, day_type, final_occupancy]
    """
    print("🔄 Starting data aggregation...")
    print(f"📊 Raw bookings: {len(df):,}")
    
    # Calculate days_out for each booking
    print("📅 Calculating days_out...")
    df['days_out'] = df.apply(
        lambda row: calculate_days_out(row['stay_date'], row['booking_date']), 
        axis=1
    )
    
    # Count bookings by stay_date and booking_date
    print("🔢 Counting bookings by stay_date and booking_date...")
    booking_counts = df.groupby(['stay_date', 'booking_date', 'days_out']).size().reset_index(name='new_bookings')
    
    # Sort by stay_date and days_out (descending, so 30 days out comes first)
    booking_counts = booking_counts.sort_values(['stay_date', 'days_out'], ascending=[True, False])
    
    # Calculate cumulative bookings for each stay_date
    print("📈 Calculating cumulative bookings...")
    booking_counts['rooms_booked_cumulative'] = booking_counts.groupby('stay_date')['new_bookings'].cumsum()
    
    # Add day_type
    print("🏷️ Adding day type...")
    booking_counts['day_type'] = booking_counts['stay_date'].apply(get_day_type)
    
    # Calculate final occupancy for each stay_date
    print("🎯 Calculating final occupancy...")
    final_occ = df.groupby('stay_date').size().reset_index(name='final_occupancy')
    booking_counts = booking_counts.merge(final_occ, on='stay_date', how='left')
    
    # Select and reorder columns
    result = booking_counts[['stay_date', 'days_out', 'rooms_booked_cumulative', 'day_type', 'final_occupancy']]
    
    # Format data for display and export
    result['stay_date'] = result['stay_date'].astype(str).str.zfill(8)
    result['rooms_booked_cumulative'] = result['rooms_booked_cumulative'].astype(int)
    
    print(f"✅ Aggregation complete!")
    print(f"   Unique stay dates: {result['stay_date'].nunique()}")
    print(f"   Total snapshots: {len(result):,}")
    
    return result

def fill_missing_days_out(df):
    """
    Ensure each stay_date has all days_out from 30 to 0.
    Fill missing days with forward-fill logic (carry previous booking count).
    """
    print("\n🔍 Checking for missing days_out...")
    
    all_records = []
    
    for stay_date in df['stay_date'].unique():
        stay_data = df[df['stay_date'] == stay_date].copy()
        day_type = stay_data['day_type'].iloc[0]
        final_occ = stay_data['final_occupancy'].iloc[0]
        
        # Create complete range 30 to 0
        complete_days = pd.DataFrame({
            'stay_date': stay_date,
            'days_out': range(30, -1, -1)
        })
        
        # Merge with actual data
        merged = complete_days.merge(
            stay_data[['days_out', 'rooms_booked_cumulative']], 
            on='days_out', 
            how='left'
        )
        
        # Forward fill (if days_out=25 is missing, use value from days_out=26)
        merged['rooms_booked_cumulative'] = merged['rooms_booked_cumulative'].bfill().fillna(0)
        
        # Add metadata
        merged['day_type'] = day_type
        merged['final_occupancy'] = final_occ
        
        all_records.append(merged)
    
    result = pd.concat(all_records, ignore_index=True)
    result = result.sort_values(['stay_date', 'days_out'], ascending=[True, False])
    
    # Format data for display and export
    result['stay_date'] = result['stay_date'].astype(str).str.zfill(8)
    result['rooms_booked_cumulative'] = result['rooms_booked_cumulative'].astype(int)
    
    print(f"✅ Missing days filled. Total records: {len(result):,}")
    
    return result

# ============================================================================
# SAVE & DISPLAY
# ============================================================================

def save_aggregated_data(df, output_dir='generated_data', filename='aggregated_bookings.csv'):
    """Save aggregated DataFrame to CSV."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    
    print(f"\n💾 Aggregated data saved to: {filepath}")
    print(f"   File size: {os.path.getsize(filepath) / 1024:.2f} KB")
    
    return filepath

def display_sample(df, stay_date=None, n=31):
    """Display sample of aggregated data for one stay_date."""
    if stay_date is None:
        stay_date = df['stay_date'].iloc[0]
    
    sample = df[df['stay_date'] == stay_date].head(n)
    
    print(f"\n📋 Sample Data for stay_date: {stay_date}")
    print(sample.to_string(index=False))

def display_summary_stats(df):
    """Display summary statistics of aggregated data."""
    print("\n📊 Aggregated Data Summary:")
    print(f"   Total records: {len(df):,}")
    print(f"   Unique stay dates: {df['stay_date'].nunique()}")
    print(f"   Date range: {df['stay_date'].min()} to {df['stay_date'].max()}")
    print(f"\n   Day Type Distribution:")
    print(df.groupby('day_type')['stay_date'].nunique())
    print(f"\n   Sample Final Occupancy Stats:")
    print(df.groupby('stay_date')['final_occupancy'].first().describe())

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    # Load raw data
    input_file = 'generated_data/historical_bookings.csv'
    
    if not os.path.exists(input_file):
        print(f"❌ Error: {input_file} not found!")
        print("   Please run simulator.py first to generate the data.")
        return
    
    print(f"📂 Loading raw data from: {input_file}")
    df_raw = pd.read_csv(input_file)
    print(f"✅ Loaded {len(df_raw):,} booking records")
    
    # Aggregate
    df_agg = aggregate_bookings(df_raw)
    
    # Fill missing days
    df_complete = fill_missing_days_out(df_agg)
    
    # Display sample
    display_sample(df_complete)
    
    # Display stats
    display_summary_stats(df_complete)
    
    # Save
    save_aggregated_data(df_complete)
    
    print("\n✅ Aggregation complete! Ready for completion model.")

if __name__ == "__main__":
    main()