# MPVRP-CC Python Workspace

Python tools and models for the **Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Cost (MPVRP-CC)**.

## About MPVRP-CC

A complex logistics optimization challenge for distributing multiple petroleum product types from depots to service stations. A heterogeneous fleet of tanker trucks is used, where each vehicle can carry only **one product type at a time**. During a route, vehicles can change the product they transport at a depot, but this incurs a **tank cleaning (changeover) cost**. The goal is to route the fleet minimizing total transportation distance and changeover costs.

## Getting Started

### Clone the Repository
```bash
git clone https://github.com/your-org/MPVRP-CC.git
cd python
```

### Install Dependencies
```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

## Project Structure

```
.
├── src/
│   ├── benchmarking/
│   │   ├── generate_150_instances.py    # Build benchmark set & manifest.csv
│   │   └── solve_150_instances.py       # Solve all instances, write solutions & report
│   ├── models/
│   │   └── lp.py                        # MILP model & solver (Gurobi)
│   ├── tools/
│   │   ├── generator.py                 # Instance generator CLI
│   │   ├── verificator.py               # Instance validator
│   │   ├── instance_schema.py           # Schema definition
│   │   ├── instance_io.py               # I/O logic
│   │   └── instance_validation.py       # Validation logic
│   └── utils/
│       └── parser.py                    # Instance parser & solution formatter
├── docs/
│   ├── problem.md                       # Problem description
│   ├── instance_format.md               # Input format specification
│   ├── solution_format.md               # Output format specification
│   └── lp_model.tex                     # Mathematical formulation
├── inst/                                # Instance files (150 benchmark instances)
│   └── manifest.csv                     # Benchmark metadata
├── sol/                                 # Solution files
├── pyproject.toml
└── README.md
```

## Requirements

- Python `>=3.12`
- Dependencies: `numpy`, `scipy`, `ortools`, `gurobipy`

## Quick Start

```bash
# Generate a single instance
python -m tools.generator -v 5 -d 2 -g 2 -s 12 -p 3 --id S_001

# Validate an instance file
python -m tools.verificator inst/MPVRP_003_s3_d7_p5.dat

# Generate the 150-instance benchmark
python -m benchmarking.generate_150_instances --count 150

# Solve the benchmark (190s time limit per instance)
python -m benchmarking.solve_150_instances --time-limit 190
```

## Documentation

See `docs/` for detailed documentation:
- **problem.md**: Problem definition and constraints
- **instance_format.md**: Input `.dat` file format
- **solution_format.md**: Output solution format
- **lp_model.tex**: Mathematical LP formulation

