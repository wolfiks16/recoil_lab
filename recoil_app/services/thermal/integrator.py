"""Неявный Эйлер для линейной тепловой сети с линеаризованным излучением.

На шаге решаем систему:

    A · T_new = rhs

где для узла k:

    A[k, k]  = C_k/dt + Σ_j G_kj + G_amb_eff_k(T_n)
    A[k, j]  = -G_kj          (для каждой связи k↔j)
    rhs[k]   = (C_k/dt) T_old_k + Q_in_k(t_i) + G_amb_eff_k(T_n) · T_amb_k

`G_amb_eff = (h_conv + h_rad(T_n)) · A_amb_or_rad`.

Излучение линеаризуется вокруг T_n текущего шага через `linearized_radiation_h`.
Это не итерация Ньютона, а одношаговая линеаризация — для гладких процессов
с шагом dt ≪ τ работает точно. При больших dt и высоких T возникает
небольшая систематика; на охлаждении она проявляется как пере- или
недоохлаждение в первой паре шагов и быстро исчезает.

Сетевой Якобиан собирается плотно (numpy 2D). Для нашей задачи
≤ 9 узлов и ≤ 8 связей — это банально и достаточно. Если когда-нибудь
сеть дорастёт до десятков узлов, замена на scipy.sparse — точечная.

Конвенция: power_brakes[i, b] = |F_mag_b(t_i) · v(t_i)|. Источник для узла k
суммируется по всем тормозам с их heat_fraction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .network import ThermalNetwork, linearized_radiation_h


@dataclass(slots=True)
class ActivePhaseThermalResult:
    """Температуры и мощности на сетке активной фазы (одного цикла)."""

    t: np.ndarray                                    # (n_steps,)
    temp_nodes: np.ndarray                           # (n_steps, n_nodes), °C
    power_nodes: np.ndarray                          # (n_steps, n_nodes), Вт
    power_brakes: np.ndarray                         # (n_steps, n_brakes), Вт
    heat_brakes: np.ndarray                          # (n_steps, n_brakes), Дж — накопленная


@dataclass(slots=True)
class CoolingThermalResult:
    """Температуры на сетке паузы (без источников)."""

    t: np.ndarray                                    # (n_steps,) — относительное время от 0
    temp_nodes: np.ndarray                           # (n_steps, n_nodes), °C


# --- Сборка статических векторов сети ------------------------------------------------


def _build_static(network: ThermalNetwork) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[tuple[int, int, float]]]:
    """Возвращает (C, G_amb_conv, area_rad, eps, T_amb, link_indices)."""
    n = network.n_nodes()
    capacitance = np.array([nd.capacitance_j_per_k for nd in network.nodes], dtype=float)
    conv_g = np.array(
        [nd.h_ambient_w_per_m2k * nd.area_ambient_m2 for nd in network.nodes],
        dtype=float,
    )
    area_rad = np.array([nd.area_radiation_m2 for nd in network.nodes], dtype=float)
    emissivity = np.array([nd.emissivity for nd in network.nodes], dtype=float)
    t_amb = np.array([nd.ambient_c for nd in network.nodes], dtype=float)
    link_idx = network.link_indices()
    return capacitance, conv_g, area_rad, emissivity, t_amb, np.zeros(n), link_idx


def _ambient_effective_g(
    temp_now: np.ndarray,
    conv_g: np.ndarray,
    area_rad: np.ndarray,
    emissivity: np.ndarray,
    t_amb_c: np.ndarray,
) -> np.ndarray:
    """G_amb_eff[k] = G_conv[k] + h_rad(T_now[k], T_amb[k], ε[k]) · A_rad[k]."""
    g_eff = conv_g.copy()
    for k in range(len(temp_now)):
        if emissivity[k] > 0.0 and area_rad[k] > 0.0:
            h_rad = linearized_radiation_h(
                temp_c=float(temp_now[k]),
                ambient_c=float(t_amb_c[k]),
                emissivity=float(emissivity[k]),
            )
            g_eff[k] += h_rad * area_rad[k]
    return g_eff


def _assemble_step(
    capacitance: np.ndarray,
    g_amb_eff: np.ndarray,
    t_amb_c: np.ndarray,
    link_idx: list[tuple[int, int, float]],
    dt: float,
    temp_old: np.ndarray,
    q_in: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Собирает (A, rhs) для одного шага неявного Эйлера."""
    n = len(temp_old)
    a = np.zeros((n, n), dtype=float)
    rhs = np.zeros(n, dtype=float)

    # Диагональ: C/dt + G_amb_eff
    diag = capacitance / dt + g_amb_eff
    np.fill_diagonal(a, diag)

    # Связи
    for i, j, g in link_idx:
        a[i, i] += g
        a[j, j] += g
        a[i, j] -= g
        a[j, i] -= g

    # rhs
    rhs[:] = (capacitance / dt) * temp_old + q_in + g_amb_eff * t_amb_c
    return a, rhs


# --- Активная фаза --------------------------------------------------------------------


def solve_active_phase(
    t_array: np.ndarray,
    v_array: np.ndarray,
    f_magnetic_each: np.ndarray,                     # (n_steps, n_brakes), знак неважен — берём |F·v|
    network: ThermalNetwork,
    temp_start_c: np.ndarray,
) -> ActivePhaseThermalResult:
    """Интегрирует сеть на готовой сетке активной фазы.

    Кинематика берётся снаружи (из готового SimulationResult / снапшота).
    Шаг dt берётся из `t_array` (потенциально неравномерный — корректно).
    """
    t = np.asarray(t_array, dtype=float)
    v = np.asarray(v_array, dtype=float)
    f_each = np.asarray(f_magnetic_each, dtype=float)

    n_steps = len(t)
    n_nodes = network.n_nodes()
    n_brakes = f_each.shape[1] if f_each.ndim == 2 else 0

    if n_steps < 2:
        # Особый случай: сетка из одной точки — никакого интегрирования не нужно.
        return ActivePhaseThermalResult(
            t=t.copy(),
            temp_nodes=np.tile(temp_start_c, (max(n_steps, 1), 1)),
            power_nodes=np.zeros((max(n_steps, 1), n_nodes)),
            power_brakes=np.zeros((max(n_steps, 1), n_brakes)),
            heat_brakes=np.zeros((max(n_steps, 1), n_brakes)),
        )

    if temp_start_c.shape != (n_nodes,):
        raise ValueError(
            f"temp_start_c shape {temp_start_c.shape} не соответствует n_nodes={n_nodes}."
        )

    capacitance, conv_g, area_rad, emissivity, t_amb_c, _, link_idx = _build_static(network)
    source_assignments = network.source_assignments()

    # Мощности тормозов и накопленное тепло.
    power_brakes = np.abs(f_each * v[:, None]) if n_brakes > 0 else np.zeros((n_steps, 0))
    power_nodes = np.zeros((n_steps, n_nodes), dtype=float)
    for brake_idx, assignments in source_assignments.items():
        if brake_idx < 0 or brake_idx >= n_brakes:
            continue
        for node_idx, fraction in assignments:
            power_nodes[:, node_idx] += fraction * power_brakes[:, brake_idx]

    # Накопленное тепло по тормозам (трапеция).
    heat_brakes = np.zeros((n_steps, n_brakes), dtype=float)
    if n_brakes > 0:
        dt_arr = np.diff(t)
        increments = 0.5 * (power_brakes[:-1, :] + power_brakes[1:, :]) * dt_arr[:, None]
        heat_brakes[1:, :] = np.cumsum(increments, axis=0)

    # Температурный массив.
    temp = np.zeros((n_steps, n_nodes), dtype=float)
    temp[0, :] = temp_start_c

    for i in range(n_steps - 1):
        dt = t[i + 1] - t[i]
        if dt <= 0:
            # Дубль точек (например, на стыках сегментов) — копируем без изменения.
            temp[i + 1, :] = temp[i, :]
            continue

        g_amb_eff = _ambient_effective_g(temp[i, :], conv_g, area_rad, emissivity, t_amb_c)
        # Источник берём в начале интервала (явно для Q, неявно для T — IMEX-подход).
        q_in = power_nodes[i, :]

        a, rhs = _assemble_step(capacitance, g_amb_eff, t_amb_c, link_idx, dt, temp[i, :], q_in)
        temp[i + 1, :] = np.linalg.solve(a, rhs)

    return ActivePhaseThermalResult(
        t=t,
        temp_nodes=temp,
        power_nodes=power_nodes,
        power_brakes=power_brakes,
        heat_brakes=heat_brakes,
    )


# --- Охлаждение (пауза между циклами) -------------------------------------------------


def _adaptive_pause_dt(
    network: ThermalNetwork,
    capacitance: np.ndarray,
    conv_g: np.ndarray,
    area_rad: np.ndarray,
    emissivity: np.ndarray,
    t_amb_c: np.ndarray,
    link_idx: list[tuple[int, int, float]],
) -> float:
    """Шаг паузы dt = clamp(0.1·τ_min, 1e-3, 0.5).

    τ_k = C_k / G_total_k, где G_total_k — суммарная проводимость связей узла k
    плюс конвекция плюс линеаризованное излучение вокруг T_amb.
    """
    n = len(capacitance)
    g_total = conv_g.copy()
    # Линеаризация излучения вокруг T_amb (T = T_amb → разностей нет, берём верхний предел
    # как для разогретого узла на 50 К: даёт нижнюю оценку τ).
    for k in range(n):
        if emissivity[k] > 0.0 and area_rad[k] > 0.0:
            h_rad = linearized_radiation_h(
                temp_c=float(t_amb_c[k]) + 50.0,
                ambient_c=float(t_amb_c[k]),
                emissivity=float(emissivity[k]),
            )
            g_total[k] += h_rad * area_rad[k]
    for i, j, g in link_idx:
        g_total[i] += g
        g_total[j] += g

    tau = np.full(n, np.inf, dtype=float)
    for k in range(n):
        if g_total[k] > 0:
            tau[k] = capacitance[k] / g_total[k]
    tau_min = float(np.min(tau))
    if not math.isfinite(tau_min):
        return 0.5
    return max(1e-3, min(0.5, 0.1 * tau_min))


def solve_cooling(
    network: ThermalNetwork,
    temp_start_c: np.ndarray,
    duration_s: float,
    dt_hint: float | None = None,
) -> CoolingThermalResult:
    """Интегрирует сеть на интервале [0, duration_s] без источников.

    Шаг dt — адаптивный, по характерному времени. Можно переопределить hint'ом.
    """
    n_nodes = network.n_nodes()
    if duration_s <= 0:
        return CoolingThermalResult(
            t=np.array([0.0]),
            temp_nodes=temp_start_c.reshape(1, -1).copy(),
        )

    capacitance, conv_g, area_rad, emissivity, t_amb_c, _, link_idx = _build_static(network)

    dt = dt_hint if dt_hint is not None else _adaptive_pause_dt(
        network, capacitance, conv_g, area_rad, emissivity, t_amb_c, link_idx,
    )

    n_steps = max(2, int(math.ceil(duration_s / dt)) + 1)
    t = np.linspace(0.0, duration_s, n_steps)
    temp = np.zeros((n_steps, n_nodes), dtype=float)
    temp[0, :] = temp_start_c
    q_zero = np.zeros(n_nodes, dtype=float)

    for i in range(n_steps - 1):
        local_dt = t[i + 1] - t[i]
        if local_dt <= 0:
            temp[i + 1, :] = temp[i, :]
            continue
        g_amb_eff = _ambient_effective_g(temp[i, :], conv_g, area_rad, emissivity, t_amb_c)
        a, rhs = _assemble_step(capacitance, g_amb_eff, t_amb_c, link_idx, local_dt, temp[i, :], q_zero)
        temp[i + 1, :] = np.linalg.solve(a, rhs)

    return CoolingThermalResult(t=t, temp_nodes=temp)
