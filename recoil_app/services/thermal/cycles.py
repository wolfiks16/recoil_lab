"""Оркестратор повторяющихся циклов: активная фаза → пауза → активная → ...

Берёт готовый timeline (t, v, f_magnetic_each) от одного выстрела и
реплицирует его N раз. Между циклами — пауза без источников. Температура
переходит из конца предыдущего сегмента в начало следующего.

Кинематика **не пересчитывается** — она везде одинакова, потому что в
текущей физической модели тепловое состояние не влияет на силы тормоза.
Если в будущем появится зависимость F_brake от T (для curve через α(T)
или для параметрической через γ(T)), потребуется передавать обновлённый
timeline на каждом цикле.

Возвращает `CombinedCycleResult` с конкатенированными рядами по всему
интервалу [0, T_total] и сводкой по каждому циклу.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .integrator import (
    ActivePhaseThermalResult,
    CoolingThermalResult,
    solve_active_phase,
    solve_cooling,
)
from .network import ThermalNetwork


SEGMENT_BRAKING = "braking"
SEGMENT_PAUSE = "pause"


@dataclass(slots=True)
class CycleSummary:
    """Сводка по одному циклу — что важно показать в таблице."""

    cycle_number: int
    start_temp_c: dict[str, float]                   # name → T в начале активной фазы
    end_temp_after_braking_c: dict[str, float]
    max_temp_in_cycle_c: dict[str, float]
    end_temp_after_pause_c: dict[str, float]
    added_heat_by_brake_j: dict[int, float]          # brake_index → накопленное за цикл


@dataclass(slots=True)
class CombinedCycleResult:
    """Объединённый результат: глобальные ряды + сводка по циклам."""

    t: np.ndarray                                    # глобальное время [0, T_total]
    temp_nodes: np.ndarray                           # (n_total, n_nodes), °C
    power_nodes: np.ndarray                          # (n_total, n_nodes), Вт
    power_brakes: np.ndarray                         # (n_total, n_brakes), Вт
    heat_brakes: np.ndarray                          # (n_total, n_brakes), Дж — глобально накопленные
    cycle_index: np.ndarray                          # (n_total,) int — номер цикла, начиная с 1
    segment: np.ndarray                              # (n_total,) object — "braking"/"pause"
    summaries: list[CycleSummary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def simulate_repeated_cycles(
    base_t: np.ndarray,
    base_v: np.ndarray,
    base_f_each: np.ndarray,                         # (n_steps, n_brakes)
    network: ThermalNetwork,
    repetitions: int,
    pause_s: float,
    pause_dt_hint: float | None = None,
) -> CombinedCycleResult:
    """Реплицирует один выстрел `repetitions` раз с паузами `pause_s` между ними.

    Перед первым циклом T = node.temp0_c. После последнего цикла остывание
    добавляется только если pause_s > 0 (поведение совпадает с teplo v3).
    """
    if repetitions < 1:
        raise ValueError("repetitions должно быть ≥ 1.")
    if pause_s < 0:
        raise ValueError("pause_s должно быть ≥ 0.")

    n_nodes = network.n_nodes()
    n_brakes = base_f_each.shape[1] if base_f_each.ndim == 2 else 0

    # Стартовая температура — из начальных условий узлов.
    temp_now = np.array([nd.temp0_c for nd in network.nodes], dtype=float)

    t_chunks: list[np.ndarray] = []
    temp_chunks: list[np.ndarray] = []
    power_node_chunks: list[np.ndarray] = []
    power_brake_chunks: list[np.ndarray] = []
    heat_brake_chunks: list[np.ndarray] = []
    cycle_idx_chunks: list[np.ndarray] = []
    segment_chunks: list[np.ndarray] = []

    cumulative_heat = np.zeros(n_brakes, dtype=float)
    time_offset = 0.0
    summaries: list[CycleSummary] = []

    def append_segment(
        t_local: np.ndarray,
        temp: np.ndarray,
        power_node: np.ndarray,
        power_brake: np.ndarray,
        heat_local: np.ndarray,
        cycle_no: int,
        segment_name: str,
    ) -> None:
        nonlocal time_offset, cumulative_heat
        if len(t_local) == 0:
            return

        # Если уже что-то накоплено, отрезаем дубликат-стык по первой точке.
        if t_chunks:
            t_local = t_local[1:]
            temp = temp[1:, :]
            power_node = power_node[1:, :]
            power_brake = power_brake[1:, :]
            heat_local = heat_local[1:, :]
            if len(t_local) == 0:
                return

        t_global = t_local + time_offset
        heat_global = heat_local + cumulative_heat[None, :]

        t_chunks.append(t_global)
        temp_chunks.append(temp)
        power_node_chunks.append(power_node)
        power_brake_chunks.append(power_brake)
        heat_brake_chunks.append(heat_global)
        cycle_idx_chunks.append(np.full(len(t_local), cycle_no, dtype=int))
        segment_chunks.append(np.array([segment_name] * len(t_local), dtype=object))

        time_offset = float(t_global[-1])
        if n_brakes > 0:
            cumulative_heat = heat_global[-1, :].copy()

    node_names = [nd.display_name for nd in network.nodes]

    for cycle_no in range(1, repetitions + 1):
        cycle_start_temp = temp_now.copy()

        active_result: ActivePhaseThermalResult = solve_active_phase(
            t_array=base_t,
            v_array=base_v,
            f_magnetic_each=base_f_each,
            network=network,
            temp_start_c=cycle_start_temp,
        )

        max_in_cycle = active_result.temp_nodes.max(axis=0)
        end_after_braking = active_result.temp_nodes[-1, :].copy()

        append_segment(
            t_local=active_result.t,
            temp=active_result.temp_nodes,
            power_node=active_result.power_nodes,
            power_brake=active_result.power_brakes,
            heat_local=active_result.heat_brakes,
            cycle_no=cycle_no,
            segment_name=SEGMENT_BRAKING,
        )

        added_per_brake: dict[int, float] = {}
        if n_brakes > 0:
            for b in range(n_brakes):
                added_per_brake[b] = float(active_result.heat_brakes[-1, b])

        temp_now = end_after_braking

        # Пауза — кроме случая, когда pause_s == 0 или это последний цикл (тогда тоже опускаем,
        # как в teplo v3, чтобы не приклеивать охлаждение хвостом).
        end_after_pause = end_after_braking.copy()
        if pause_s > 0 and cycle_no < repetitions:
            cooling: CoolingThermalResult = solve_cooling(
                network=network,
                temp_start_c=temp_now,
                duration_s=pause_s,
                dt_hint=pause_dt_hint,
            )
            end_after_pause = cooling.temp_nodes[-1, :].copy()

            n_cool = len(cooling.t)
            zero_node = np.zeros((n_cool, n_nodes))
            zero_brake = np.zeros((n_cool, n_brakes))
            append_segment(
                t_local=cooling.t,
                temp=cooling.temp_nodes,
                power_node=zero_node,
                power_brake=zero_brake,
                heat_local=zero_brake,                # heat не накапливается на паузе
                cycle_no=cycle_no,
                segment_name=SEGMENT_PAUSE,
            )
            temp_now = end_after_pause

        summaries.append(CycleSummary(
            cycle_number=cycle_no,
            start_temp_c={node_names[i]: float(cycle_start_temp[i]) for i in range(n_nodes)},
            end_temp_after_braking_c={node_names[i]: float(end_after_braking[i]) for i in range(n_nodes)},
            max_temp_in_cycle_c={node_names[i]: float(max_in_cycle[i]) for i in range(n_nodes)},
            end_temp_after_pause_c={node_names[i]: float(end_after_pause[i]) for i in range(n_nodes)},
            added_heat_by_brake_j=added_per_brake,
        ))

    # Конкатенация. Если ни одного сегмента не приклеилось (вырожденный случай) — пустые массивы.
    def _stack(chunks: Sequence[np.ndarray], default_shape: tuple[int, ...]) -> np.ndarray:
        if chunks:
            return np.concatenate(chunks, axis=0)
        return np.zeros(default_shape, dtype=float)

    t_total = _stack(t_chunks, (0,))
    temp_total = _stack(temp_chunks, (0, n_nodes))
    power_node_total = _stack(power_node_chunks, (0, n_nodes))
    power_brake_total = _stack(power_brake_chunks, (0, n_brakes))
    heat_brake_total = _stack(heat_brake_chunks, (0, n_brakes))
    cycle_idx_total = (
        np.concatenate(cycle_idx_chunks) if cycle_idx_chunks else np.zeros(0, dtype=int)
    )
    segment_total = (
        np.concatenate(segment_chunks) if segment_chunks else np.array([], dtype=object)
    )

    return CombinedCycleResult(
        t=t_total,
        temp_nodes=temp_total,
        power_nodes=power_node_total,
        power_brakes=power_brake_total,
        heat_brakes=heat_brake_total,
        cycle_index=cycle_idx_total,
        segment=segment_total,
        summaries=summaries,
        warnings=list(network.warnings),
    )
