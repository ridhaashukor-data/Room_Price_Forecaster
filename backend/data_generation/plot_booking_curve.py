"""
Plot booking curve for a specific stay_date
"""
import pandas as pd
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv('generated_data/aggregated_bookings.csv')

# Filter for specific stay_date (as integer)
stay_date = 1012024  # 01/01/2024
stay_date_display = str(stay_date).zfill(8)  # For display: 01012024
data = df[df['stay_date'] == stay_date].sort_values('days_out', ascending=False)

# Create the plot
plt.figure(figsize=(12, 6))
plt.plot(data['days_out'], data['rooms_booked_cumulative'], 
         marker='o', linewidth=2, markersize=4, color='#2E86AB')

# Formatting
plt.xlabel('Days Out', fontsize=12, fontweight='bold')
plt.ylabel('Rooms Booked (Cumulative)', fontsize=12, fontweight='bold')
plt.title(f'Booking Curve for Stay Date: {stay_date_display}', fontsize=14, fontweight='bold')
plt.grid(True, alpha=0.3, linestyle='--')
plt.xticks(range(0, 31, 2))  # Show every 2 days
plt.xlim(30, 0)  # Reverse x-axis (30 to 0)

# Add final occupancy line
final_occ = data['final_occupancy'].iloc[0]
plt.axhline(y=final_occ, color='red', linestyle='--', alpha=0.5, label=f'Final Occupancy: {final_occ}')

# Add day type
day_type = data['day_type'].iloc[0]
plt.text(0.02, 0.98, f'Day Type: {day_type.capitalize()}', 
         transform=plt.gca().transAxes, 
         fontsize=10, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

plt.legend()
plt.tight_layout()

# Save
plt.savefig('generated_data/booking_curve_01012024.png', dpi=300, bbox_inches='tight')
print(f"✅ Booking curve saved to: generated_data/booking_curve_01012024.png")

# Show
plt.show()
