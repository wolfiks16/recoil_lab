from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from .io_utils import load_recoil_characteristics
from .magnetic import MagneticParams, magnetic_force_si


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
        raise ValueError(f"spring_force(abs(x)) вернула некорректное значение при x={x}: {force_abs}")

    if x > 0.0:
        return -force_abs
    if x < 0.0:
        return force_abs
    return 0.0


def magnetic_force_signed(v: float, force_abs: float) -> float:
    """
    Магнитный тормоз всегда направлен против скорости.
    """
    if v > 0.0:
        return -force_abs
    if v < 0.0:
        return force_abs
    return 0.0


def signed_forces(
    t: float,
    x: float,
    v: float,
    ext_force,
    spring_force,
    t_ext_max: float,
    mass: float,
    angle_deg: float,
    magnetic_list: Sequence[MagneticParams],
    wn_values: np.ndarray,
) -> tuple[float, float, float, np.ndarray, float, np.ndarray]:
    """
    Возвращает:
    Fext, Fa, Fspring, Fmag_each_signed, Ftotal, wn_next_each
    """
    if not np.isfinite(t):
        raise ValueError(f"t не является конечным числом: {t}")
    if not np.isfinite(x):
        raise ValueError(f"x не является конечным числом: {x}")
    if not np.isfinite(v):
        raise ValueError(f"v не является конечным числом: {v}")

    if len(magnetic_list) != len(wn_values):
        raise ValueError("Число тормозов и число состояний wn не совпадают.")

    Fext = ext_force(t) if t <= t_ext_max else 0.0
    Fa = angle_force_si(mass, angle_deg)
    Fspring = spring_force_signed(x, spring_force)

    n_brakes = len(magnetic_list)
    Fmag_each_signed = np.zeros(n_brakes, dtype=float)
    wn_next_each = np.zeros(n_brakes, dtype=float)

    for i, magnetic in enumerate(magnetic_list):
        force_abs, wn_next = magnetic_force_si(v, float(wn_values[i]), magnetic)
        Fmag_each_signed[i] = magnetic_force_signed(v, force_abs)
        wn_next_each[i] = wn_next

    Ftotal = Fext + Fa + Fspring + float(np.sum(Fmag_each_signed))
    return Fext, Fa, Fspring, Fmag_each_signed, Ftotal, wn_next_each


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
    magnetic_list: Sequence[MagneticParams],
    wn_values: np.ndarray,
) -> tuple[float, float]:
    def rhs(tt: float, xx: float, vv: float) -> tuple[float, float]:
        _, _, _, _, Ftotal, _ = signed_forces(
            tt,
            xx,
            vv,
            ext_force,
            spring_force,
            t_ext_max,
            mass,
            angle_deg,
            magnetic_list,
            wn_values,
        )
        return vv, Ftotal / mass

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
    magnetic_list: Sequence[MagneticParams],
) -> SimulationResult:
    if not magnetic_list:
        raise ValueError("Не задано ни одного магнитного тормоза.")

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

    n_brakes = len(magnetic_list)
    f_magnetic_each = np.zeros((len(t), n_brakes), dtype=float)
    wn_each = np.zeros((len(t), n_brakes), dtype=float)

    x[0] = recoil.x0
    v[0] = recoil.v0
    wn_each[0, :] = np.array([m.wn0 for m in magnetic_list], dtype=float)

    recoil_end_time = None
    recoil_end_index = None
    return_end_time = None
    return_end_index = None
    stop_index = None

    for i in range(len(t) - 1):
        if abs(x[i]) < x_min_tab or abs(x[i]) > x_max_tab:
            spring_out_of_range = True

        Fext, Fa, Fspring, Fmag_each, Ftotal, _ = signed_forces(
            t[i],
            x[i],
            v[i],
            ext_force,
            spring_force,
            t_ext_max,
            recoil.mass,
            recoil.angle_deg,
            magnetic_list,
            wn_each[i, :],
        )

        f_ext[i] = Fext
        f_angle[i] = Fa
        f_spring[i] = Fspring
        f_magnetic_each[i, :] = Fmag_each
        f_magnetic[i] = float(np.sum(Fmag_each))
        f_total[i] = Ftotal
        a[i] = Ftotal / recoil.mass

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
            magnetic_list,
            wn_each[i, :],
        )

        x[i + 1] = x_new
        v[i + 1] = v_new

        # Обновляем wn по новой скорости для всех тормозов
        wn_next_each = np.zeros(n_brakes, dtype=float)
        for j, magnetic in enumerate(magnetic_list):
            _, wn_next = magnetic_force_si(v_new, float(wn_each[i, j]), magnetic)
            wn_next_each[j] = wn_next
        wn_each[i + 1, :] = wn_next_each

        # Конец отката / начало наката
        if recoil_end_index is None and v[i] > 0.0 and v[i + 1] <= 0.0:
            alpha_v = v[i] / (v[i] - v[i + 1]) if v[i] != v[i + 1] else 0.0
            recoil_end_time = t[i] + alpha_v * recoil.dt
            recoil_end_index = i

        # После начала наката отслеживаем возврат в x = 0
        if recoil_end_index is not None and return_end_index is None:
            if x[i] > 0.0 and x[i + 1] <= 0.0:
                alpha_x = x[i] / (x[i] - x[i + 1]) if x[i] != x[i + 1] else 0.0

                t[i + 1] = t[i] + alpha_x * recoil.dt
                v[i + 1] = v[i] + alpha_x * (v[i + 1] - v[i])
                x[i + 1] = 0.0

                # Уточняем wn в конечной точке возврата
                wn_return_each = np.zeros(n_brakes, dtype=float)
                for j, magnetic in enumerate(magnetic_list):
                    _, wn_next = magnetic_force_si(v[i + 1], float(wn_each[i, j]), magnetic)
                    wn_return_each[j] = wn_next
                wn_each[i + 1, :] = wn_return_each

                Fext, Fa, Fspring, Fmag_each, Ftotal, _ = signed_forces(
                    t[i + 1],
                    x[i + 1],
                    v[i + 1],
                    ext_force,
                    spring_force,
                    t_ext_max,
                    recoil.mass,
                    recoil.angle_deg,
                    magnetic_list,
                    wn_each[i + 1, :],
                )

                f_ext[i + 1] = Fext
                f_angle[i + 1] = Fa
                f_spring[i + 1] = Fspring
                f_magnetic_each[i + 1, :] = Fmag_each
                f_magnetic[i + 1] = float(np.sum(Fmag_each))
                f_total[i + 1] = Ftotal
                a[i + 1] = Ftotal / recoil.mass

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
        Fext, Fa, Fspring, Fmag_each, Ftotal, _ = signed_forces(
            t[-1],
            x[-1],
            v[-1],
            ext_force,
            spring_force,
            t_ext_max,
            recoil.mass,
            recoil.angle_deg,
            magnetic_list,
            wn_each[-1, :],
        )

        f_ext[-1] = Fext
        f_angle[-1] = Fa
        f_spring[-1] = Fspring
        f_magnetic_each[-1, :] = Fmag_each
        f_magnetic[-1] = float(np.sum(Fmag_each))
        f_total[-1] = Ftotal
        a[-1] = Ftotal / recoil.mass

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
    
    return SimulationResult(
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