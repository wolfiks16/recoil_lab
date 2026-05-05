from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from .io_utils import load_recoil_characteristics
from .magnetic import (
    BrakeModel,
    CurveRangeError,
    evaluate_brake_force_si,
    initial_brake_state,
)


G = 9.81
DEFAULT_V_EPS = 1e-6


@dataclass(slots=True)
class RecoilParams:
    mass: float
    angle_deg: float = 70.0
    v0: float = 0.0
    x0: float = 0.0
    t_max: float = 0.15
    dt: float = 1e-4
    v_eps: float = DEFAULT_V_EPS


@dataclass(slots=True)
class SimulationResult:
    t: np.ndarray
    x: np.ndarray
    v: np.ndarray
    a: np.ndarray
    f_total: np.ndarray
    f_ext: np.ndarray
    f_spring: np.ndarray
    f_magnetic: np.ndarray
    f_angle: np.ndarray
    f_magnetic_each: np.ndarray
    wn_each: np.ndarray

    recoil_end_time: float | None
    recoil_end_index: int | None
    return_end_time: float | None
    return_end_index: int | None

    termination_reason: str
    spring_out_of_range: bool
    warnings: list[str]

    # --- Энергобаланс (вычисляется в compute_energy_balance) ---
    energy_kinetic: np.ndarray | None = None      # m * v^2 / 2,  [Дж]
    energy_spring: np.ndarray | None = None       # ∫ F_spring(x) dx от 0 до x(t),  [Дж]
    energy_brake_cum: np.ndarray | None = None    # накопленное рассеяние тормозами: -∫ F_mag * v dt,  [Дж]
    energy_input_cum: np.ndarray | None = None    # накопленная работа выстрела + гравитации: ∫ (F_ext + F_angle) * v dt
    energy_total: np.ndarray | None = None        # E_kin + E_spring + E_brake_cum,  [Дж]
    energy_residual_pct: float | None = None      # макс относительная невязка баланса в % к энергии-входу


def angle_force_si(mass: float, angle_deg: float) -> float:
    return mass * G * math.sin(math.radians(angle_deg))


def spring_force_signed(x: float, spring_force) -> float:
    """
    Пружина всегда направлена к x = 0.
    """
    if not np.isfinite(x):
        raise ValueError(f"В spring_force_signed пришёл некорректный x: {x}")

    force_abs = spring_force(abs(x))
    if not np.isfinite(force_abs):
        raise ValueError(
            f"spring_force(abs(x)) вернула некорректное значение при x={x}: {force_abs}"
        )

    if x > 0.0:
        return -force_abs
    if x < 0.0:
        return force_abs
    return 0.0


def magnetic_force_signed(v: float, force_abs: float) -> float:
    """
    Тормоз всегда направлен против скорости.
    """
    if v > 0.0:
        return -force_abs
    if v < 0.0:
        return force_abs
    return 0.0


def _evaluate_brake_force_components(
    v: float,
    brake_list: Sequence[BrakeModel],
    brake_states: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    n_brakes = len(brake_list)
    fmag_each_signed = np.zeros(n_brakes, dtype=float)
    brake_state_next_each = np.zeros(n_brakes, dtype=float)

    for i, brake in enumerate(brake_list):
        try:
            force_abs, state_next = evaluate_brake_force_si(v, float(brake_states[i]), brake)
        except CurveRangeError as exc:
            raise ValueError(f"Тормоз {i + 1}: {exc}") from exc

        fmag_each_signed[i] = magnetic_force_signed(v, force_abs)
        brake_state_next_each[i] = state_next

    return fmag_each_signed, brake_state_next_each


def _advance_brake_states(
    v: float,
    brake_list: Sequence[BrakeModel],
    brake_states: np.ndarray,
) -> np.ndarray:
    n_brakes = len(brake_list)
    next_states = np.zeros(n_brakes, dtype=float)

    for i, brake in enumerate(brake_list):
        try:
            _, state_next = evaluate_brake_force_si(v, float(brake_states[i]), brake)
        except CurveRangeError as exc:
            raise ValueError(f"Тормоз {i + 1}: {exc}") from exc
        next_states[i] = state_next

    return next_states


def signed_forces(
    t: float,
    x: float,
    v: float,
    ext_force,
    spring_force,
    t_ext_max: float,
    mass: float,
    angle_deg: float,
    brake_list: Sequence[BrakeModel],
    brake_states: np.ndarray,
) -> tuple[float, float, float, np.ndarray, float, np.ndarray]:
    """
    Возвращает:
    Fext, Fa, Fspring, Fmag_each_signed, Ftotal, brake_state_next_each
    """
    if not np.isfinite(t):
        raise ValueError(f"t не является конечным числом: {t}")
    if not np.isfinite(x):
        raise ValueError(f"x не является конечным числом: {x}")
    if not np.isfinite(v):
        raise ValueError(f"v не является конечным числом: {v}")

    if len(brake_list) != len(brake_states):
        raise ValueError("Число тормозов и число состояний тормозов не совпадают.")

    fext = ext_force(t) if t <= t_ext_max else 0.0
    fa = angle_force_si(mass, angle_deg)
    fspring = spring_force_signed(x, spring_force)

    fmag_each_signed, brake_state_next_each = _evaluate_brake_force_components(
        v,
        brake_list,
        brake_states,
    )

    ftotal = fext + fa + fspring + float(np.sum(fmag_each_signed))
    return fext, fa, fspring, fmag_each_signed, ftotal, brake_state_next_each


def rk4_step_recoil_return(
    t: float,
    x: float,
    v: float,
    dt: float,
    ext_force,
    spring_force,
    t_ext_max: float,
    mass: float,
    angle_deg: float,
    brake_list: Sequence[BrakeModel],
    brake_states: np.ndarray,
) -> tuple[float, float]:
    def rhs(tt: float, xx: float, vv: float) -> tuple[float, float]:
        _, _, _, _, ftotal, _ = signed_forces(
            tt,
            xx,
            vv,
            ext_force,
            spring_force,
            t_ext_max,
            mass,
            angle_deg,
            brake_list,
            brake_states,
        )
        return vv, ftotal / mass

    k1_x, k1_v = rhs(t, x, v)
    k2_x, k2_v = rhs(t + dt / 2, x + dt * k1_x / 2, v + dt * k1_v / 2)
    k3_x, k3_v = rhs(t + dt / 2, x + dt * k2_x / 2, v + dt * k2_v / 2)
    k4_x, k4_v = rhs(t + dt, x + dt * k3_x, v + dt * k3_v)

    x_new = x + dt * (k1_x + 2 * k2_x + 2 * k3_x + k4_x) / 6
    v_new = v + dt * (k1_v + 2 * k2_v + 2 * k3_v + k4_v) / 6
    return x_new, v_new


def simulate_recoil(
    xlsx_path: str | Path,
    recoil: RecoilParams,
    brake_list: Sequence[BrakeModel],
) -> SimulationResult:
    if not brake_list:
        raise ValueError("Не задано ни одного тормоза.")

    ext_force, spring_force, t_ext_max, x_range = load_recoil_characteristics(xlsx_path)

    x_min_tab, x_max_tab = x_range
    spring_out_of_range = False

    t = np.arange(0.0, recoil.t_max + recoil.dt, recoil.dt)
    x = np.zeros_like(t)
    v = np.zeros_like(t)
    a = np.zeros_like(t)

    f_total = np.zeros_like(t)
    f_ext = np.zeros_like(t)
    f_spring = np.zeros_like(t)
    f_magnetic = np.zeros_like(t)
    f_angle = np.full_like(t, angle_force_si(recoil.mass, recoil.angle_deg))

    n_brakes = len(brake_list)
    f_magnetic_each = np.zeros((len(t), n_brakes), dtype=float)
    wn_each = np.zeros((len(t), n_brakes), dtype=float)

    x[0] = recoil.x0
    v[0] = recoil.v0
    wn_each[0, :] = np.array([initial_brake_state(brake) for brake in brake_list], dtype=float)

    recoil_end_time = None
    recoil_end_index = None
    return_end_time = None
    return_end_index = None
    stop_index = None

    for i in range(len(t) - 1):
        if abs(x[i]) < x_min_tab or abs(x[i]) > x_max_tab:
            spring_out_of_range = True

        fext, fa, fspring, fmag_each, ftotal, _ = signed_forces(
            t[i],
            x[i],
            v[i],
            ext_force,
            spring_force,
            t_ext_max,
            recoil.mass,
            recoil.angle_deg,
            brake_list,
            wn_each[i, :],
        )

        f_ext[i] = fext
        f_angle[i] = fa
        f_spring[i] = fspring
        f_magnetic_each[i, :] = fmag_each
        f_magnetic[i] = float(np.sum(fmag_each))
        f_total[i] = ftotal
        a[i] = ftotal / recoil.mass

        x_new, v_new = rk4_step_recoil_return(
            t[i],
            x[i],
            v[i],
            recoil.dt,
            ext_force,
            spring_force,
            t_ext_max,
            recoil.mass,
            recoil.angle_deg,
            brake_list,
            wn_each[i, :],
        )

        x[i + 1] = x_new
        v[i + 1] = v_new
        wn_each[i + 1, :] = _advance_brake_states(v_new, brake_list, wn_each[i, :])

        if recoil_end_index is None and v[i] > 0.0 and v[i + 1] <= 0.0:
            alpha_v = v[i] / (v[i] - v[i + 1]) if v[i] != v[i + 1] else 0.0
            recoil_end_time = t[i] + alpha_v * recoil.dt
            recoil_end_index = i

        if recoil_end_index is not None and return_end_index is None:
            if x[i] > 0.0 and x[i + 1] <= 0.0:
                alpha_x = x[i] / (x[i] - x[i + 1]) if x[i] != x[i + 1] else 0.0

                t[i + 1] = t[i] + alpha_x * recoil.dt
                v[i + 1] = v[i] + alpha_x * (v[i + 1] - v[i])
                x[i + 1] = 0.0

                wn_each[i + 1, :] = _advance_brake_states(v[i + 1], brake_list, wn_each[i, :])

                fext, fa, fspring, fmag_each, ftotal, _ = signed_forces(
                    t[i + 1],
                    x[i + 1],
                    v[i + 1],
                    ext_force,
                    spring_force,
                    t_ext_max,
                    recoil.mass,
                    recoil.angle_deg,
                    brake_list,
                    wn_each[i + 1, :],
                )

                f_ext[i + 1] = fext
                f_angle[i + 1] = fa
                f_spring[i + 1] = fspring
                f_magnetic_each[i + 1, :] = fmag_each
                f_magnetic[i + 1] = float(np.sum(fmag_each))
                f_total[i + 1] = ftotal
                a[i + 1] = ftotal / recoil.mass

                return_end_time = t[i + 1]
                return_end_index = i + 1
                stop_index = i + 2
                break

    if stop_index is not None:
        t = t[:stop_index]
        x = x[:stop_index]
        v = v[:stop_index]
        a = a[:stop_index]
        f_total = f_total[:stop_index]
        f_ext = f_ext[:stop_index]
        f_spring = f_spring[:stop_index]
        f_magnetic = f_magnetic[:stop_index]
        f_angle = f_angle[:stop_index]
        f_magnetic_each = f_magnetic_each[:stop_index, :]
        wn_each = wn_each[:stop_index, :]
    else:
        fext, fa, fspring, fmag_each, ftotal, _ = signed_forces(
            t[-1],
            x[-1],
            v[-1],
            ext_force,
            spring_force,
            t_ext_max,
            recoil.mass,
            recoil.angle_deg,
            brake_list,
            wn_each[-1, :],
        )

        f_ext[-1] = fext
        f_angle[-1] = fa
        f_spring[-1] = fspring
        f_magnetic_each[-1, :] = fmag_each
        f_magnetic[-1] = float(np.sum(fmag_each))
        f_total[-1] = ftotal
        a[-1] = ftotal / recoil.mass

    if return_end_time is not None:
        termination_reason = "returned_to_zero"
    elif np.isclose(t[-1], recoil.t_max) or t[-1] >= recoil.t_max:
        termination_reason = "time_limit"
    else:
        termination_reason = "not_finished"

    warnings = []

    if spring_out_of_range:
        warnings.append(
            f"В ходе расчёта перемещение вышло за диапазон табличной характеристики пружины: "
            f"[{x_min_tab:.6f}, {x_max_tab:.6f}] м."
        )

    sim_result = SimulationResult(
        t=t,
        x=x,
        v=v,
        a=a,
        f_total=f_total,
        f_ext=f_ext,
        f_spring=f_spring,
        f_magnetic=f_magnetic,
        f_angle=f_angle,
        f_magnetic_each=f_magnetic_each,
        wn_each=wn_each,
        recoil_end_time=recoil_end_time,
        recoil_end_index=recoil_end_index,
        return_end_time=return_end_time,
        return_end_index=return_end_index,
        termination_reason=termination_reason,
        spring_out_of_range=spring_out_of_range,
        warnings=warnings,
    )

    compute_energy_balance(sim_result, mass=recoil.mass)

    return sim_result


def compute_energy_balance(result: SimulationResult, mass: float) -> None:
    """
    Заполняет поля энергобаланса прямо в SimulationResult.

    Уравнение баланса:
        E_kin(t) + E_spring(t) + E_brake_cum(t) - E_input_cum(t) = const

    где
        E_kin(t)        = m * v(t)^2 / 2
        E_spring(t)     = ∫_0^x(t) |F_spring(s)| ds — потенциальная энергия пружины
        E_brake_cum(t)  = ∫_0^t (-F_mag(τ)) * v(τ) dτ  — рассеяно тормозами
                          (тормоз противодействует движению; -F_mag*v ≥ 0)
        E_input_cum(t)  = ∫_0^t (F_ext(τ) + F_angle(τ)) * v(τ) dτ — внешняя подведённая энергия

    Невязка баланса отнесена к максимуму подведённой энергии (или к сумме E_kin+E_brake,
    если входная мала — например, при свободных колебаниях).
    """
    t = np.asarray(result.t, dtype=float)
    x = np.asarray(result.x, dtype=float)
    v = np.asarray(result.v, dtype=float)
    f_ext = np.asarray(result.f_ext, dtype=float)
    f_angle = np.asarray(result.f_angle, dtype=float)
    f_spring = np.asarray(result.f_spring, dtype=float)
    f_magnetic = np.asarray(result.f_magnetic, dtype=float)

    n = len(t)
    if n < 2:
        result.energy_kinetic = np.zeros(n)
        result.energy_spring = np.zeros(n)
        result.energy_brake_cum = np.zeros(n)
        result.energy_input_cum = np.zeros(n)
        result.energy_total = np.zeros(n)
        result.energy_residual_pct = 0.0
        return

    # Кинетическая энергия
    e_kin = 0.5 * mass * v * v

    # Потенциальная энергия пружины: ∫_0^x |F_spring(s)| ds
    # f_spring уже sign-corrected (направлена к 0). Возвращающая работа = ∫ F_spring(x) dx по знаку x.
    # Чтобы получить положительную потенциальную энергию, интегрируем |F_spring(x)| по dx по модулю смещения.
    # Простой способ: e_spring(t) = cumulative_trapezoid(|f_spring|, |x|), но x монотонно растёт-падает.
    # Корректнее: dE_spring = - F_spring_signed * dx  (т.к. F_spring = -dU/dx)
    dx = np.diff(x)
    # f_spring уже знаковая: на x>0 она отрицательная (тянет к 0). dU = -F·dx = |F|·dx при dx>0, x>0
    de_spring = -0.5 * (f_spring[:-1] + f_spring[1:]) * dx  # средняя сила × dx
    e_spring = np.concatenate(([0.0], np.cumsum(de_spring)))
    # На случай численных дрейфов в отрицательную область
    e_spring = np.maximum(e_spring, 0.0)

    # Накопленная мощность тормоза: P_brake = -F_mag * v ≥ 0 (тормоз противодействует движению)
    p_brake = -f_magnetic * v
    dt_arr = np.diff(t)
    de_brake = 0.5 * (p_brake[:-1] + p_brake[1:]) * dt_arr
    e_brake_cum = np.concatenate(([0.0], np.cumsum(de_brake)))

    # Накопленная подведённая энергия: ∫ (F_ext + F_angle) v dt
    p_input = (f_ext + f_angle) * v
    de_input = 0.5 * (p_input[:-1] + p_input[1:]) * dt_arr
    e_input_cum = np.concatenate(([0.0], np.cumsum(de_input)))

    # Полная "сохраняемая" сумма
    e_total = e_kin + e_spring + e_brake_cum

    # Невязка: E_kin + E_spring + E_brake = E_input + E_kin(0) + E_spring(0)
    # Начальные условия: E_kin(0) = m*v0²/2, E_spring(0) = 0
    e_kin_0 = e_kin[0]
    e_spring_0 = 0.0
    residual = e_total - e_input_cum - e_kin_0 - e_spring_0

    # Относим невязку к характерной энергии цикла
    e_scale = float(max(np.max(np.abs(e_input_cum)), np.max(e_kin), np.max(e_brake_cum), 1e-9))
    residual_pct = float(np.max(np.abs(residual)) / e_scale * 100.0)

    result.energy_kinetic = e_kin
    result.energy_spring = e_spring
    result.energy_brake_cum = e_brake_cum
    result.energy_input_cum = e_input_cum
    result.energy_total = e_total
    result.energy_residual_pct = residual_pct