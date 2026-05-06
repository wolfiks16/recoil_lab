"""Dataclass'ы тепловой сети.

Модель повторяет логику `teplo/standalone_brake_thermal_v3.py`, но без I/O,
без print, в стиле проекта. Узлы и связи задаются по именам (для удобства
ссылок из конфига); индексация для интегратора собирается в `ThermalNetwork.__post_init__`.

Уравнение узла k:
    C_k · dT_k/dt = Q_in_k(t) + Σ_j G_{kj} (T_j − T_k) − G_amb_k (T_k − T_amb_k) − Q_rad_k

где:
    C_k    = m_k · cp_k                            — теплоёмкость узла, Дж/К
    G_{kj} = h_{kj} · A_{kj}                       — проводимость связи, Вт/К
    G_amb  = h_amb · A_amb                         — конвективная связь с воздухом, Вт/К
    Q_rad  = ε · σ · A_rad · (T⁴ − T_amb⁴)         — излучение в окружающую среду, Вт
    Q_in   = heat_fraction · |F_brake(v) · v|      — мощность от тормоза-источника, Вт

Источник `ThermalSource` — отдельная сущность, чтобы можно было прицепить
один тормоз к нескольким узлам с разными долями heat_fraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .materials import STEFAN_BOLTZMANN


@dataclass(slots=True)
class ThermalNode:
    """Один узел тепловой сети."""

    name: str                                        # ASCII-ключ для ссылок
    display_name: str = ""                           # имя для UI/графиков
    mass_kg: float = 0.0
    cp_j_per_kgk: float = 0.0
    temp0_c: float = 20.0

    # Конвекция в воздух (если узел граничит с воздухом).
    h_ambient_w_per_m2k: float = 0.0
    area_ambient_m2: float = 0.0
    ambient_c: float = 20.0

    # Излучение в окружающую среду (тот же воздух, обычно та же T_ambient).
    # Степень черноты не показывается пользователю — выставляется по материалу.
    emissivity: float = 0.0
    area_radiation_m2: float = 0.0

    material_key: str = ""                           # информационно (для UI)

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name
        if self.mass_kg < 0 or self.cp_j_per_kgk < 0:
            raise ValueError(
                f"Узел '{self.name}': масса и cp должны быть неотрицательными."
            )
        if not self.name:
            raise ValueError("У узла должно быть непустое имя.")

    @property
    def capacitance_j_per_k(self) -> float:
        return self.mass_kg * self.cp_j_per_kgk


@dataclass(slots=True)
class ThermalLink:
    """Связь между двумя узлами через G = h·A."""

    node_a: str
    node_b: str
    h_w_per_m2k: float
    area_m2: float
    description: str = ""

    def __post_init__(self) -> None:
        if self.node_a == self.node_b:
            raise ValueError(
                f"Связь не может соединять узел '{self.node_a}' сам с собой."
            )
        if self.h_w_per_m2k < 0 or self.area_m2 < 0:
            raise ValueError(
                f"Связь {self.node_a}↔{self.node_b}: h и A должны быть неотрицательными."
            )

    @property
    def conductance_w_per_k(self) -> float:
        return self.h_w_per_m2k * self.area_m2


@dataclass(slots=True)
class ThermalSource:
    """Привязка тормоза к узлу-приёмнику тепла.

    Один тормоз может питать несколько узлов с разными долями (например,
    99% в шину, 1% в магниты). Σ heat_fraction по всем приёмникам одного
    тормоза должна равняться 1.0 — это проверяется в ThermalNetwork.
    """

    brake_index: int                                 # ссылка на MagneticBrakeConfig.index
    node_name: str                                   # имя узла-приёмника
    heat_fraction: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.heat_fraction <= 1.0):
            raise ValueError(
                f"heat_fraction для тормоза #{self.brake_index} → '{self.node_name}' "
                f"должна быть в [0, 1], получено {self.heat_fraction}."
            )


@dataclass(slots=True)
class ThermalNetwork:
    """Полная тепловая сеть: узлы + связи + источники."""

    nodes: list[ThermalNode]
    links: list[ThermalLink]
    sources: list[ThermalSource]

    # Заполняется в __post_init__.
    node_index_by_name: dict[str, int] = field(default_factory=dict)
    sources_by_brake: dict[int, list[ThermalSource]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("Тепловая сеть должна содержать хотя бы один узел.")

        seen_names: set[str] = set()
        self.node_index_by_name = {}
        for idx, node in enumerate(self.nodes):
            if node.name in seen_names:
                raise ValueError(f"Имя узла '{node.name}' встречается дважды.")
            seen_names.add(node.name)
            self.node_index_by_name[node.name] = idx

        for link in self.links:
            if link.node_a not in self.node_index_by_name:
                raise ValueError(
                    f"Связь ссылается на неизвестный узел '{link.node_a}'."
                )
            if link.node_b not in self.node_index_by_name:
                raise ValueError(
                    f"Связь ссылается на неизвестный узел '{link.node_b}'."
                )

        self.sources_by_brake = {}
        for source in self.sources:
            if source.node_name not in self.node_index_by_name:
                raise ValueError(
                    f"Источник для тормоза #{source.brake_index} ссылается "
                    f"на неизвестный узел '{source.node_name}'."
                )
            self.sources_by_brake.setdefault(source.brake_index, []).append(source)

        self.warnings = []
        for brake_index, srcs in self.sources_by_brake.items():
            total = sum(s.heat_fraction for s in srcs)
            if abs(total - 1.0) > 1e-6:
                self.warnings.append(
                    f"Сумма heat_fraction для тормоза #{brake_index} = {total:.4f} "
                    f"(ожидается 1.0). Часть мощности будет потеряна или дублирована."
                )

        for node in self.nodes:
            if node.capacitance_j_per_k <= 0:
                raise ValueError(
                    f"Узел '{node.name}' имеет неположительную теплоёмкость "
                    f"(масса·cp = {node.capacitance_j_per_k}). Задайте mass_kg и cp_j_per_kgk."
                )

    # --- Удобные индекс-доступы для интегратора ---

    def node_index(self, name: str) -> int:
        return self.node_index_by_name[name]

    def n_nodes(self) -> int:
        return len(self.nodes)

    def link_indices(self) -> list[tuple[int, int, float]]:
        """Список (i, j, G) — связь i↔j с проводимостью G = h·A."""
        return [
            (
                self.node_index_by_name[link.node_a],
                self.node_index_by_name[link.node_b],
                link.conductance_w_per_k,
            )
            for link in self.links
        ]

    def source_assignments(self) -> dict[int, list[tuple[int, float]]]:
        """Для каждого индекса тормоза — список (node_index, fraction)."""
        result: dict[int, list[tuple[int, float]]] = {}
        for brake_index, srcs in self.sources_by_brake.items():
            result[brake_index] = [
                (self.node_index_by_name[s.node_name], s.heat_fraction) for s in srcs
            ]
        return result


def linearized_radiation_h(
    temp_c: float,
    ambient_c: float,
    emissivity: float,
) -> float:
    """Линеаризованный коэффициент радиационной теплоотдачи, Вт/(м²·К).

    Для неявного шага удобно линеаризовать:
        Q_rad ≈ h_rad · A · (T − T_amb),
        h_rad = ε · σ · (T² + T_amb²) · (T + T_amb),
    где T в Кельвинах. Пересчитывается каждый шаг по текущей T узла.
    """
    if emissivity <= 0.0:
        return 0.0
    t_k = temp_c + 273.15
    t_amb_k = ambient_c + 273.15
    return emissivity * STEFAN_BOLTZMANN * (t_k * t_k + t_amb_k * t_amb_k) * (t_k + t_amb_k)
