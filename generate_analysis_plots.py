import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Set style for better-looking plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 10)
plt.rcParams['font.size'] = 10

# Paths
BASE_PATH = Path(__file__).parent
MANIFEST_PATH = BASE_PATH / "inst" / "manifest.csv"
REPORT_PATH = BASE_PATH / "sol" / "solve_150_report.csv"
OUTPUT_PATH = BASE_PATH / "analysis_plots"

# Create output directory
OUTPUT_PATH.mkdir(exist_ok=True)

# Load data
print("Loading data...")
manifest = pd.read_csv(MANIFEST_PATH)
report = pd.read_csv(REPORT_PATH)

# Merge datasets
data = manifest.merge(report[['id', 'status', 'solver_status', 'objective']], on='id')

# Create status categories
def categorize_status(row):
    if row['status'] == 'UNSOLVED':
        return 'Unsolved'
    elif row['solver_status'] == 'OPTIMAL':
        return 'Optimal'
    else:
        return 'Solved (not optimal)'

data['status_category'] = data.apply(categorize_status, axis=1)

print(f"Total instances: {len(data)}")
print(f"Optimal solutions: {(data['status_category'] == 'Optimal').sum()}")
print(f"Solved (not optimal): {(data['status_category'] == 'Solved (not optimal)').sum()}")
print(f"Unsolved: {(data['status_category'] == 'Unsolved').sum()}")
print()

# =====================================================================
# PLOT 1: Overall Status Distribution (Pie Chart)
# =====================================================================
fig, ax = plt.subplots(figsize=(8, 8))
status_counts = data['status_category'].value_counts()
colors = ['#2ecc71', '#3498db', '#e74c3c']  # Green, Blue, Red
explode = (0.05, 0.05, 0.1)
ax.pie(status_counts.values, labels=status_counts.index, autopct='%1.1f%%',
       colors=colors, explode=explode, startangle=90, textprops={'fontsize': 12, 'weight': 'bold'})
ax.set_title('Solution Status Distribution (190s Time Limit)', fontsize=14, weight='bold', pad=20)
plt.tight_layout()
plt.savefig(OUTPUT_PATH / "01_status_distribution.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 01_status_distribution.png")
plt.close()

# =====================================================================
# PLOT 2: Instance Characteristics - Vehicles
# =====================================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Vehicles distribution
ax = axes[0, 0]
vehicles_counts = data['vehicles'].value_counts().sort_index()
ax.bar(vehicles_counts.index, vehicles_counts.values, color='steelblue', alpha=0.7, edgecolor='black')
ax.set_xlabel('Number of Vehicles', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Distribution of Vehicles per Instance', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

# Depots distribution
ax = axes[0, 1]
depots_counts = data['depots'].value_counts().sort_index()
ax.bar(depots_counts.index, depots_counts.values, color='coral', alpha=0.7, edgecolor='black')
ax.set_xlabel('Number of Depots', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Distribution of Depots per Instance', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

# Stations distribution
ax = axes[1, 0]
stations_counts = data['stations'].value_counts().sort_index()
ax.bar(stations_counts.index, stations_counts.values, color='lightgreen', alpha=0.7, edgecolor='black')
ax.set_xlabel('Number of Stations', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Distribution of Stations per Instance', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

# Products distribution
ax = axes[1, 1]
products_counts = data['products'].value_counts().sort_index()
ax.bar(products_counts.index, products_counts.values, color='mediumpurple', alpha=0.7, edgecolor='black')
ax.set_xlabel('Number of Products', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Distribution of Products per Instance', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "02_instance_characteristics.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 02_instance_characteristics.png")
plt.close()

# =====================================================================
# PLOT 3: Capacity and Demand Levels
# =====================================================================
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Capacity level
ax = axes[0]
capacity_counts = data['capacity_level'].value_counts()
capacity_order = ['low', 'mixed', 'large']
capacity_counts = capacity_counts.reindex([x for x in capacity_order if x in capacity_counts.index])
colors_cap = ['#3498db', '#f39c12', '#e74c3c']
ax.bar(range(len(capacity_counts)), capacity_counts.values, color=colors_cap[:len(capacity_counts)],
       alpha=0.7, edgecolor='black')
ax.set_xticks(range(len(capacity_counts)))
ax.set_xticklabels(capacity_counts.index, fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Capacity Level Distribution', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

# Demand level
ax = axes[1]
demand_counts = data['demand_level'].value_counts()
demand_order = ['low', 'medium', 'high']
demand_counts = demand_counts.reindex([x for x in demand_order if x in demand_counts.index])
colors_dem = ['#3498db', '#f39c12', '#e74c3c']
ax.bar(range(len(demand_counts)), demand_counts.values, color=colors_dem[:len(demand_counts)],
       alpha=0.7, edgecolor='black')
ax.set_xticks(range(len(demand_counts)))
ax.set_xticklabels(demand_counts.index, fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Demand Level Distribution', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "03_capacity_demand_levels.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 03_capacity_demand_levels.png")
plt.close()

# =====================================================================
# PLOT 4: Coordinate Strategy and Changeover Cost
# =====================================================================
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Coordinate strategy
ax = axes[0]
coord_counts = data['coordinate_strategy'].value_counts()
colors_coord = ['#2ecc71', '#3498db', '#f39c12']
ax.bar(range(len(coord_counts)), coord_counts.values, color=colors_coord[:len(coord_counts)],
       alpha=0.7, edgecolor='black')
ax.set_xticks(range(len(coord_counts)))
ax.set_xticklabels(coord_counts.index, fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Coordinate Strategy Distribution', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

# Changeover cost level
ax = axes[1]
changeover_counts = data['changeover_cost_level'].value_counts()
changeover_order = ['low', 'mixed', 'normal', 'high']
changeover_counts = changeover_counts.reindex([x for x in changeover_order if x in changeover_counts.index])
colors_change = ['#3498db', '#f39c12', '#95a5a6', '#e74c3c']
ax.bar(range(len(changeover_counts)), changeover_counts.values,
       color=colors_change[:len(changeover_counts)], alpha=0.7, edgecolor='black')
ax.set_xticks(range(len(changeover_counts)))
ax.set_xticklabels(changeover_counts.index, fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Changeover Cost Level Distribution', fontsize=12, weight='bold')
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "04_strategy_changeover.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 04_strategy_changeover.png")
plt.close()

# =====================================================================
# PLOT 5: Solvability by Problem Size
# =====================================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Solvability by vehicles
ax = axes[0, 0]
pivot_vehicles = pd.crosstab(data['vehicles'], data['status_category'])
pivot_vehicles.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Number of Vehicles', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Number of Vehicles', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

# Solvability by depots
ax = axes[0, 1]
pivot_depots = pd.crosstab(data['depots'], data['status_category'])
pivot_depots.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Number of Depots', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Number of Depots', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

# Solvability by stations
ax = axes[1, 0]
pivot_stations = pd.crosstab(data['stations'], data['status_category'])
pivot_stations.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Number of Stations', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Number of Stations', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

# Solvability by products
ax = axes[1, 1]
pivot_products = pd.crosstab(data['products'], data['status_category'])
pivot_products.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Number of Products', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Number of Products', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "05_solvability_by_size.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 05_solvability_by_size.png")
plt.close()

# =====================================================================
# PLOT 6: Solvability by Problem Characteristics
# =====================================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# By capacity level
ax = axes[0, 0]
pivot_capacity = pd.crosstab(data['capacity_level'], data['status_category'])
capacity_order = ['low', 'mixed', 'large']
pivot_capacity = pivot_capacity.reindex([x for x in capacity_order if x in pivot_capacity.index])
pivot_capacity.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Capacity Level', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Capacity Level', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=0)

# By demand level
ax = axes[0, 1]
pivot_demand = pd.crosstab(data['demand_level'], data['status_category'])
demand_order = ['low', 'medium', 'high']
pivot_demand = pivot_demand.reindex([x for x in demand_order if x in pivot_demand.index])
pivot_demand.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Demand Level', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Demand Level', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=0)

# By coordinate strategy
ax = axes[1, 0]
pivot_coord = pd.crosstab(data['coordinate_strategy'], data['status_category'])
pivot_coord.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Coordinate Strategy', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Coordinate Strategy', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

# By changeover cost level
ax = axes[1, 1]
pivot_changeover = pd.crosstab(data['changeover_cost_level'], data['status_category'])
changeover_order = ['low', 'mixed', 'normal', 'high']
pivot_changeover = pivot_changeover.reindex([x for x in changeover_order if x in pivot_changeover.index])
pivot_changeover.plot(kind='bar', ax=ax, color=['#2ecc71', '#3498db', '#e74c3c'], alpha=0.8, edgecolor='black')
ax.set_xlabel('Changeover Cost Level', fontsize=11, weight='bold')
ax.set_ylabel('Count', fontsize=11, weight='bold')
ax.set_title('Solution Status by Changeover Cost Level', fontsize=12, weight='bold')
ax.legend(title='Status', fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "06_solvability_by_characteristics.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 06_solvability_by_characteristics.png")
plt.close()

# =====================================================================
# PLOT 7: Objective Value Distribution
# =====================================================================
fig, ax = plt.subplots(figsize=(12, 6))

# Filter only solved instances
solved_data = data[data['status'] == 'SOLVED'].copy()

# Create scatter plot colored by status
optimal_data = solved_data[solved_data['solver_status'] == 'OPTIMAL']
timelimit_data = solved_data[solved_data['solver_status'] == 'TIME_LIMIT']

ax.scatter(range(len(optimal_data)), optimal_data['objective'].values,
          label='Optimal', color='#2ecc71', s=100, alpha=0.7, edgecolors='black', zorder=3)
ax.scatter(range(len(optimal_data), len(optimal_data) + len(timelimit_data)),
          timelimit_data['objective'].values, label='Time Limit', color='#3498db',
          s=100, alpha=0.7, edgecolors='black', zorder=3)

ax.set_xlabel('Instance (Sorted by Status)', fontsize=12, weight='bold')
ax.set_ylabel('Objective Value', fontsize=12, weight='bold')
ax.set_title('Objective Values for Solved Instances', fontsize=13, weight='bold')
ax.legend(fontsize=11)
ax.grid(True, alpha=0.3)
ax.set_yscale('log')

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "07_objective_values.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 07_objective_values.png")
plt.close()

# =====================================================================
# PLOT 8: Solvability Heatmap (Vehicles vs Stations)
# =====================================================================
fig, ax = plt.subplots(figsize=(12, 8))

# Create a pivot table for heatmap
heatmap_data = data.groupby(['vehicles', 'stations'])['status_category'].apply(
    lambda x: (x == 'Optimal').sum()
).unstack(fill_value=0)

sns.heatmap(heatmap_data, annot=True, fmt='d', cmap='RdYlGn', ax=ax, cbar_kws={'label': 'Optimal Solutions'})
ax.set_xlabel('Number of Stations', fontsize=12, weight='bold')
ax.set_ylabel('Number of Vehicles', fontsize=12, weight='bold')
ax.set_title('Optimal Solutions: Vehicles vs Stations', fontsize=13, weight='bold')

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "08_heatmap_vehicles_stations.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 08_heatmap_vehicles_stations.png")
plt.close()

# =====================================================================
# PLOT 9: Problem Difficulty Analysis
# =====================================================================
fig, ax = plt.subplots(figsize=(12, 6))

# Create a difficulty score based on parameters
data['total_customers'] = data['depots'] + data['stations']
data['total_products'] = data['products']
data['fleet_size'] = data['vehicles']
data['difficulty_index'] = data['total_customers'] * data['total_products'] / data['fleet_size']

# Compute average success rate by difficulty
difficulty_bins = pd.cut(data['difficulty_index'], bins=5)
difficulty_analysis = data.groupby(difficulty_bins, observed=True).agg({
    'status_category': lambda x: ((x == 'Optimal').sum() / len(x) * 100),
    'id': 'count'
})
difficulty_analysis = difficulty_analysis.reset_index()

x_labels = [f"{int(interval.left)}-{int(interval.right)}" for interval in difficulty_analysis['difficulty_index']]
ax.bar(range(len(difficulty_analysis)), difficulty_analysis['status_category'].values,
       color='steelblue', alpha=0.7, edgecolor='black')
ax.set_xticks(range(len(difficulty_analysis)))
ax.set_xticklabels(x_labels, rotation=45)
ax.set_ylabel('% Optimal Solutions', fontsize=12, weight='bold')
ax.set_xlabel('Problem Difficulty Index\n(Customers×Products / Vehicles)', fontsize=12, weight='bold')
ax.set_title('Optimal Solution Rate vs Problem Difficulty', fontsize=13, weight='bold')
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_PATH / "09_difficulty_analysis.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 09_difficulty_analysis.png")
plt.close()

# =====================================================================
# PLOT 10: Comprehensive Summary Statistics Table
# =====================================================================
fig, ax = plt.subplots(figsize=(12, 6))
ax.axis('off')

# Create summary statistics
summary_stats = {
    'Total Instances': len(data),
    'Optimal Solutions': (data['status_category'] == 'Optimal').sum(),
    'Solved (not optimal)': (data['status_category'] == 'Solved (not optimal)').sum(),
    'Unsolved': (data['status_category'] == 'Unsolved').sum(),
    'Optimal %': f"{(data['status_category'] == 'Optimal').sum() / len(data) * 100:.1f}%",
    'Solved %': f"{(data['status'] == 'SOLVED').sum() / len(data) * 100:.1f}%",
    'Avg Vehicles': f"{data['vehicles'].mean():.1f}",
    'Avg Depots': f"{data['depots'].mean():.1f}",
    'Avg Stations': f"{data['stations'].mean():.1f}",
    'Avg Products': f"{data['products'].mean():.1f}",
}

# Create table data
table_data = [[k, v] for k, v in summary_stats.items()]

table = ax.table(cellText=table_data, colLabels=['Metric', 'Value'],
                cellLoc='center', loc='center', colWidths=[0.5, 0.3])
table.auto_set_font_size(False)
table.set_fontsize(11)
table.scale(1, 2.5)

# Style header
for i in range(2):
    table[(0, i)].set_facecolor('#34495e')
    table[(0, i)].set_text_props(weight='bold', color='white')

# Alternate row colors
for i in range(1, len(table_data) + 1):
    for j in range(2):
        if i % 2 == 0:
            table[(i, j)].set_facecolor('#ecf0f1')
        else:
            table[(i, j)].set_facecolor('#ffffff')

ax.set_title('Summary Statistics', fontsize=14, weight='bold', pad=20)
plt.tight_layout()
plt.savefig(OUTPUT_PATH / "10_summary_statistics.png", dpi=300, bbox_inches='tight')
print("✓ Saved: 10_summary_statistics.png")
plt.close()
