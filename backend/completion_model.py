"""
Completion Ratio Model
Calculates average completion ratios from historical booking data for occupancy forecasting.
"""

import pandas as pd
import os

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    'min_sample_size': 100,  # Minimum samples required for reliable ratio
    'outlier_filter': True,  # Filter out ratios < 0 or > 1.05
    'outlier_min': 0.0,
    'outlier_max': 1.05
}

# ============================================================================
# CORE CALCULATION FUNCTIONS
# ============================================================================

def calculate_individual_ratios(df):
    """
    Calculate completion ratio for each row.
    
    completion_ratio = rooms_booked_cumulative / final_occupancy
    
    Input: DataFrame with [stay_date, days_out, rooms_booked_cumulative, day_type, final_occupancy]
    Output: Same DataFrame with additional 'completion_ratio' column
    """
    print("🧮 Calculating individual completion ratios...")
    
    df['completion_ratio'] = df['rooms_booked_cumulative'] / df['final_occupancy']
    
    # Handle edge cases
    df['completion_ratio'] = df['completion_ratio'].fillna(0)  # If final_occupancy = 0 (shouldn't happen)
    
    print(f"✅ Calculated ratios for {len(df):,} records")
    
    return df

def filter_outliers(df, config):
    """
    Remove outlier completion ratios (< 0 or > 1.05).
    
    Ratios > 1.0 can occur due to:
    - Data entry errors
    - Overbooking
    - Simulation artifacts
    
    We allow slight overshoot (1.05) but cap extreme values.
    """
    if not config['outlier_filter']:
        print("⏭️  Outlier filtering disabled")
        return df
    
    print("🔍 Filtering outliers...")
    
    initial_count = len(df)
    
    df_filtered = df[
        (df['completion_ratio'] >= config['outlier_min']) & 
        (df['completion_ratio'] <= config['outlier_max'])
    ].copy()
    
    removed_count = initial_count - len(df_filtered)
    
    if removed_count > 0:
        print(f"   Removed {removed_count:,} outlier records ({removed_count/initial_count*100:.2f}%)")
    else:
        print(f"   No outliers detected")
    
    return df_filtered

def aggregate_completion_ratios(df, config):
    """
    Group by day_type and days_out, then calculate average completion ratio.
    
    Output: DataFrame with [day_type, days_out, avg_completion_ratio, sample_count]
    """
    print("\n📊 Aggregating completion ratios by day_type and days_out...")
    
    # Group and calculate statistics
    grouped = df.groupby(['day_type', 'days_out'])['completion_ratio'].agg([
        ('avg_completion_ratio', 'mean'),
        ('sample_count', 'count'),
        ('std_deviation', 'std'),
        ('min_ratio', 'min'),
        ('max_ratio', 'max')
    ]).reset_index()
    
    # Round for readability
    grouped['avg_completion_ratio'] = grouped['avg_completion_ratio'].round(4)
    grouped['std_deviation'] = grouped['std_deviation'].round(4)
    grouped['min_ratio'] = grouped['min_ratio'].round(4)
    grouped['max_ratio'] = grouped['max_ratio'].round(4)
    
    # Sort by day_type and days_out (descending)
    grouped = grouped.sort_values(['day_type', 'days_out'], ascending=[True, False])
    
    print(f"✅ Calculated {len(grouped)} completion ratio groups")
    
    return grouped

def validate_sample_sizes(df, config):
    """
    Check if each group has sufficient samples for reliable ratios.
    Add 'confidence' flag.
    """
    print("\n✅ Validating sample sizes...")
    
    min_samples = config['min_sample_size']
    
    df['confidence'] = df['sample_count'].apply(
        lambda x: 'high' if x >= min_samples else 'low'
    )
    
    # Summary
    high_conf = len(df[df['confidence'] == 'high'])
    low_conf = len(df[df['confidence'] == 'low'])
    
    print(f"   High confidence groups: {high_conf}")
    print(f"   Low confidence groups: {low_conf}")
    
    if low_conf > 0:
        print(f"\n⚠️  Warning: {low_conf} groups have < {min_samples} samples")
        print("   These ratios may be less reliable.")
        
        # Show which groups are low confidence
        low_conf_groups = df[df['confidence'] == 'low'][['day_type', 'days_out', 'sample_count']]
        print("\n   Low confidence groups:")
        print(low_conf_groups.to_string(index=False))
    
    return df

# ============================================================================
# DISPLAY & SUMMARY
# ============================================================================

def display_summary_stats(df):
    """Display summary statistics of completion ratios."""
    print("\n📈 Completion Ratio Summary:")
    print(f"   Total groups: {len(df)}")
    print(f"   Day types: {df['day_type'].unique().tolist()}")
    print(f"   Days out range: {df['days_out'].min()} to {df['days_out'].max()}")
    
    print("\n   Sample Statistics by Day Type:")
    for day_type in df['day_type'].unique():
        subset = df[df['day_type'] == day_type]
        print(f"\n   {day_type.upper()}:")
        print(f"      Groups: {len(subset)}")
        print(f"      Avg samples per group: {subset['sample_count'].mean():.0f}")
        print(f"      Min samples: {subset['sample_count'].min()}")
        print(f"      Max samples: {subset['sample_count'].max()}")

def display_sample_ratios(df, day_type='weekend', days_list=[30, 14, 7, 1, 0]):
    """Display sample completion ratios for key days_out."""
    print(f"\n📋 Sample Completion Ratios - {day_type.upper()}:")
    
    sample = df[
        (df['day_type'] == day_type) & 
        (df['days_out'].isin(days_list))
    ][['days_out', 'avg_completion_ratio', 'sample_count', 'confidence']]
    
    print(sample.to_string(index=False))

def display_comparison_table(df):
    """Display side-by-side comparison of weekday vs weekend ratios."""
    print("\n📊 Weekday vs Weekend Comparison (Key Checkpoints):")
    
    key_days = [30, 20, 14, 7, 3, 1, 0]
    
    comparison = df[df['days_out'].isin(key_days)].pivot(
        index='days_out',
        columns='day_type',
        values='avg_completion_ratio'
    ).reset_index()
    
    comparison = comparison.sort_values('days_out', ascending=False)
    
    print(comparison.to_string(index=False))

# ============================================================================
# SAVE & EXPORT
# ============================================================================

def save_completion_ratios(df, output_dir='../data', filename='completion_ratios.csv'):
    """Save completion ratios to CSV."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    
    # Select columns to save
    output_df = df[[
        'day_type', 
        'days_out', 
        'avg_completion_ratio', 
        'sample_count', 
        'std_deviation',
        'confidence'
    ]]
    
    output_df.to_csv(filepath, index=False)
    
    print(f"\n💾 Completion ratios saved to: {filepath}")
    print(f"   File size: {os.path.getsize(filepath) / 1024:.2f} KB")
    
    return filepath

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def build_completion_model(input_file='../data_generation/generated_data/aggregated_bookings.csv', 
                          config=CONFIG):
    """
    Main function to build completion ratio model from aggregated booking data.
    
    Process:
    1. Load aggregated booking data
    2. Calculate individual completion ratios
    3. Filter outliers
    4. Aggregate by day_type and days_out
    5. Validate sample sizes
    6. Save results
    
    Returns: DataFrame with completion ratios
    """
    print("=" * 70)
    print("🏨 COMPLETION RATIO MODEL BUILDER")
    print("=" * 70)
    
    # Load data
    if not os.path.exists(input_file):
        print(f"\n❌ Error: {input_file} not found!")
        print("   Please run data aggregation first.")
        return None
    
    print(f"\n📂 Loading aggregated data from: {input_file}")
    df = pd.read_csv(input_file)
    print(f"✅ Loaded {len(df):,} aggregated records")
    print(f"   Unique stay dates: {df['stay_date'].nunique()}")
    
    # Calculate individual ratios
    df = calculate_individual_ratios(df)
    
    # Filter outliers
    df = filter_outliers(df, config)
    
    # Aggregate
    completion_ratios = aggregate_completion_ratios(df, config)
    
    # Validate
    completion_ratios = validate_sample_sizes(completion_ratios, config)
    
    # Display summaries
    display_summary_stats(completion_ratios)
    display_comparison_table(completion_ratios)
    display_sample_ratios(completion_ratios, 'weekday', [30, 14, 7, 1, 0])
    display_sample_ratios(completion_ratios, 'weekend', [30, 14, 7, 1, 0])
    
    # Save
    save_completion_ratios(completion_ratios)
    
    print("\n" + "=" * 70)
    print("✅ COMPLETION MODEL BUILD COMPLETE!")
    print("=" * 70)
    
    return completion_ratios

# ============================================================================
# HELPER FUNCTION FOR FORECASTING (to be used later)
# ============================================================================

def get_completion_ratio(day_type, days_out, completion_ratios_df):
    """
    Retrieve completion ratio for a given day_type and days_out.
    
    To be used by forecasting engine.
    
    Args:
        day_type: 'weekday' or 'weekend'
        days_out: integer 0-30
        completion_ratios_df: DataFrame with completion ratios
    
    Returns:
        float: completion ratio, or None if not found
    """
    result = completion_ratios_df[
        (completion_ratios_df['day_type'] == day_type) & 
        (completion_ratios_df['days_out'] == days_out)
    ]
    
    if len(result) == 0:
        return None
    
    return result['avg_completion_ratio'].iloc[0]

# ============================================================================
# RUN AS STANDALONE SCRIPT
# ============================================================================

if __name__ == "__main__":
    # Build the model
    completion_ratios = build_completion_model()
    
    print("\n📌 Next Steps:")
    print("   1. Review completion_ratios.csv in the data/ folder")
    print("   2. Use these ratios in the forecasting engine")
    print("   3. Build the pricing recommendation logic")