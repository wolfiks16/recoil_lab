"""Тепловой модуль: расчёт температур узлов поверх готового CalculationRun.

Слои:
    materials.py   — справочник плотностей/теплоёмкостей/степеней черноты
    network.py     — dataclass'ы ThermalNode / ThermalLink / ThermalNetwork
    geometry.py    — построение сети из параметров тормозов и геометрии сборки
    integrator.py  — неявный Эйлер с линеаризованным излучением
    cycles.py      — оркестратор: реплицирует базовую фазу, добавляет паузы
    decimation.py  — урезание временных рядов перед сериализацией в JSON
    snapshot.py    — упаковка config / result в JSON для ThermalRun
    charting.py    — Plotly-фрагменты в стиле проекта
"""

from .materials import MATERIALS, get_material  # noqa: F401
from .network import (  # noqa: F401
    ThermalNode,
    ThermalLink,
    ThermalNetwork,
    ThermalSource,
)
from .geometry import (  # noqa: F401
    BrakeGeometry,
    AssemblyGeometry,
    UserSimpleBrakeParams,
    UserSimpleAssemblyParams,
    build_nine_node_network,
    build_single_node_network,
    build_user_simple_network,
)
from .cycles import (  # noqa: F401
    simulate_repeated_cycles,
    CombinedCycleResult,
    CycleSummary,
)
from .snapshot import (  # noqa: F401
    build_config_snapshot,
    build_result_snapshot,
    derive_run_summary,
)
