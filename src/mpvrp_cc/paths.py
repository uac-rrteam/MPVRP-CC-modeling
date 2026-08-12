from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
INSTANCES_DIR = DATA_DIR / "instances"
WITH_CHANGEOVER_INSTANCES_DIR = INSTANCES_DIR / "with_changeover_costs"
WITHOUT_CHANGEOVER_INSTANCES_DIR = INSTANCES_DIR / "without_changeover_costs"
GENERATED_INSTANCES_DIR = INSTANCES_DIR / "generated"
SOLUTIONS_DIR = DATA_DIR / "solutions"
WITH_CHANGEOVER_SOLUTIONS_DIR = SOLUTIONS_DIR / "with_changeover_costs"
WITHOUT_CHANGEOVER_SOLUTIONS_DIR = SOLUTIONS_DIR / "without_changeover_costs"
RESULTS_DIR = PROJECT_ROOT / "results"
