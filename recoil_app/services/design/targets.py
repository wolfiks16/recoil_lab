"""Целевые условия, ограничения и модель допусков для обратного проектирования."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DesignTargets:
    """Конечные условия цикла, которые характеристика тормоза должна обеспечить.

    T       — время цикла (откат + накат), с.
    x_max   — максимальный откат, м.
    v_end   — |скорость| в момент возврата x=0 (конец наката), м/с.
    """

    T: float
    x_max: float
    v_end: float

    # Допуск попадания в цель (относительный). Внутри него цель считается достигнутой.
    rel_tol: float = 0.02


@dataclass(slots=True)
class DesignConstraints:
    """Жёсткие ограничения конструкции."""

    # Потолок суммарного усилия тормозов: max_t |ΣF(t)| ≤ sigma_f_max, Н.
    sigma_f_max: float

    # Число свободных узлов кривой F(v) (не считая закреплённого узла v=0, F=0).
    n_free_nodes: int = 4


@dataclass(slots=True)
class ToleranceModel:
    """Индивидуальные допуски на каждый параметр для оценки робастности.

    В MVP параметры — это значения силы в свободных узлах кривой F(v).
    node_tol[i] — абсолютный допуск (±, Н) на силу i-го свободного узла.
    Длина должна совпадать с числом свободных узлов (DesignConstraints.n_free_nodes).
    """

    node_tol: tuple[float, ...]

    @classmethod
    def uniform(cls, n_free_nodes: int, tol_abs: float) -> "ToleranceModel":
        return cls(node_tol=tuple(float(tol_abs) for _ in range(n_free_nodes)))

    @classmethod
    def from_fraction(cls, n_free_nodes: int, sigma_f_max: float, fraction: float) -> "ToleranceModel":
        """Допуск = fraction · sigma_f_max, одинаковый по узлам (дефолт-заготовка)."""
        return cls.uniform(n_free_nodes, float(sigma_f_max) * float(fraction))
