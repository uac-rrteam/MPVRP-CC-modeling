import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# DEFAULT_INSTANCE_PATH = PROJECT_ROOT / "inst" / "large" / "MPVRP_L_012_s176_d7_p11.dat"
DEFAULT_INSTANCE_PATH = PROJECT_ROOT / "inst" / "one.dat"


@dataclass(frozen=True)
class MPVRPNode:
    id: int
    global_id: int
    x: float
    y: float

    def distance(self, other: 'MPVRPNode') -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    @property
    def type(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class StationNode(MPVRPNode):
    demand: List[float]

    @property
    def type(self) -> int: return 0


@dataclass(frozen=True)
class GarageNode(MPVRPNode):
    @property
    def type(self) -> int: return 1


@dataclass(frozen=True)
class DepotNode(MPVRPNode):
    stocks: List[float]

    @property
    def type(self) -> int: return 2


@dataclass(frozen=True)
class Vehicule:
    id: int
    capacity: float
    start_g: Optional[GarageNode]
    init_prod: int


class MPVRPInstance:
    def __init__(self):
        self.uuid: str = ""
        self.n_prods: int = 0
        self.n_depots: int = 0
        self.n_garages: int = 0
        self.n_stations: int = 0
        self.n_vehicules: int = 0
        self.changeover_cost: List[List[float]] = []
        self.vehicules: List[Vehicule] = []
        self.stations: List[StationNode] = []
        self.depots: List[DepotNode] = []
        self.garages: List[GarageNode] = []
        self.dist_matrix: List[List[float]] = []

    @staticmethod
    def read(filename: str | Path) -> 'MPVRPInstance':
        inst = MPVRPInstance()
        filepath = Path(filename)

        def token_generator():
            with filepath.open('r') as f:
                for line in f:
                    for word in line.split():
                        yield word

        tokens = token_generator()

        def next_token():
            return next(tokens)

        # Lecture des entêtes
        next_token()  # Skip the first string (uuid prefix/hash)
        inst.uuid = next_token()
        inst.n_prods = int(next_token())
        inst.n_depots = int(next_token())
        inst.n_garages = int(next_token())
        inst.n_stations = int(next_token())
        inst.n_vehicules = int(next_token())

        # Matrice de changement (changeoverCost)
        inst.changeover_cost = [[float(next_token()) for _ in range(inst.n_prods)] for _ in range(inst.n_prods)]

        # Flotte de véhicules
        home_garage_ids = []
        for _ in range(inst.n_vehicules):
            v_id = int(next_token())
            capacity = float(next_token())
            home_garage_ids.append(int(next_token()))
            init_prod = int(next_token())
            inst.vehicules.append(Vehicule(v_id, capacity, None, init_prod))

        current_global_id = 0

        # Dépôts
        for _ in range(inst.n_depots):
            d_id = int(next_token())
            x = float(next_token())
            y = float(next_token())
            stocks = [float(next_token()) for _ in range(inst.n_prods)]
            inst.depots.append(DepotNode(d_id, current_global_id, x, y, stocks))
            current_global_id += 1

        # Garages
        for _ in range(inst.n_garages):
            g_id = int(next_token())
            x = float(next_token())
            y = float(next_token())
            inst.garages.append(GarageNode(g_id, current_global_id, x, y))
            current_global_id += 1

        # Stations
        for _ in range(inst.n_stations):
            s_id = int(next_token())
            x = float(next_token())
            y = float(next_token())
            demand = [float(next_token()) for _ in range(inst.n_prods)]
            inst.stations.append(StationNode(s_id, current_global_id, x, y, demand))
            current_global_id += 1

        # Post-traitement
        inst._link_vehicles(home_garage_ids)
        inst._build_distance_matrix()

        return inst

    def _link_vehicles(self, garage_ids: List[int]):
        for i in range(self.n_vehicules):
            target_id = garage_ids[i]
            # Recherche du garage correspondant
            garage = next((g for g in self.garages if g.id == target_id), None)
            v = self.vehicules[i]
            # Les dataclasses étant frozen, on recrée l'objet
            self.vehicules[i] = Vehicule(v.id, v.capacity, garage, v.init_prod)

    def _build_distance_matrix(self):
        all_nodes = self.depots + self.garages + self.stations
        size = len(all_nodes)
        self.dist_matrix = [[0.0 for _ in range(size)] for _ in range(size)]

        for i in range(size):
            for j in range(size):
                self.dist_matrix[i][j] = all_nodes[i].distance(all_nodes[j])

    def display(self):
        print(f"UUID: {self.uuid}")
        print(f"Prods:{self.n_prods} Depots:{self.n_depots} Garages:{self.n_garages} "
              f"Stations:{self.n_stations} Vehicules:{self.n_vehicules}")

        for row in self.changeover_cost:
            print("\t".join(map(str, row)))

        for v in self.vehicules:
            g_id = v.start_g.id if v.start_g else -1
            print(f"ID:{v.id} | Cap:{v.capacity} | GarageID:{g_id} | InitProd:{v.init_prod}")

        for d in self.depots:
            stocks_str = " ".join(map(str, d.stocks))
            print(f"ID:{d.id} | X:{d.x:.1f} Y:{d.y:.1f} | Stocks: {stocks_str}")

        for g in self.garages:
            print(f"ID:{g.id} | X:{g.x:.1f} Y:{g.y:.1f}")

        for s in self.stations:
            demand_str = " ".join(map(str, s.demand))
            print(f"ID:{s.id} | X:{s.x:.1f} Y:{s.y:.1f} | Requests: {demand_str}")


if __name__ == "__main__":
    try:
        instance = MPVRPInstance.read(DEFAULT_INSTANCE_PATH)
        instance.display()
    except Exception as e:
        import traceback

        traceback.print_exc()
