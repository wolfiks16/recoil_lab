"""Физика режимов итерационного расчёта — тонкие адаптеры над `dynamics.py`.

Адаптер отдаёт две операции над ОДНИМ узлом/шагом:
    forces(t, x, v, models, states) -> (F_вход, F_угол, F_пруж, F_маг по включённым, F_сумм)
    step(t, x, v, h, models, states) -> (x_new, v_new, n_подшагов)

Внутри — ровно те же функции и тот же порядок арифметики, что в
`simulate_recoil_core` / `simulate_free_fall`. Это и обеспечивает совпадение
пошагового прогона с обычным расчётом бит-в-бит. Формулы здесь не
дублировать — только вызывать `dynamics`.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from ..dynamics import (
    RecoilParams,
    _FREE_FALL_MAX_SUBSTEPS,
    _evaluate_brake_force_components,
    _free_fall_advance,
    angle_force_si,
    rk4_step_recoil_return,
    signed_forces,
)
from ..magnetic import BrakeModel

MODE_RECOIL = "recoil"
MODE_FREE_FALL = "free_fall"


class RecoilPhysics:
    """Откат/накат: выстрел F(t) + пружина F(x) + угол + тормоза, RK4 на шаге h."""

    has_return = True

    def __init__(self, recoil: RecoilParams, drive):
        if drive is None:
            raise ValueError("Для расчёта отката нужен входной привод (F(t), F(x)).")
        self.ext_force, self.spring_force, self.t_ext_max, self.x_range = drive
        self.mass = recoil.mass
        self.angle_deg = recoil.angle_deg

    def forces(self, t, x, v, models: Sequence[BrakeModel], states: np.ndarray):
        fext, fa, fspring, fmag_each, ftotal, _ = signed_forces(
            t, x, v, self.ext_force, self.spring_force, self.t_ext_max,
            self.mass, self.angle_deg, models, states,
        )
        return fext, fa, fspring, fmag_each, ftotal

    def step(self, t, x, v, h, models: Sequence[BrakeModel], states: np.ndarray):
        x_new, v_new = rk4_step_recoil_return(
            t, x, v, h, self.ext_force, self.spring_force, self.t_ext_max,
            self.mass, self.angle_deg, models, states,
        )
        return x_new, v_new, 1

    def spring_out_of_range(self, x: float) -> bool:
        x_min_tab, x_max_tab = self.x_range
        return abs(x) < x_min_tab or abs(x) > x_max_tab


class FreeFallPhysics:
    """Свободное падение: только угол (гравитация) + тормоза; шаг — адаптивное
    дробление при замороженном wn (см. `simulate_free_fall`)."""

    has_return = False
    max_substeps = _FREE_FALL_MAX_SUBSTEPS

    def __init__(self, recoil: RecoilParams):
        self.mass = recoil.mass
        self.fa_const = angle_force_si(recoil.mass, recoil.angle_deg)

    def forces(self, t, x, v, models: Sequence[BrakeModel], states: np.ndarray):
        fmag_each, _ = _evaluate_brake_force_components(v, models, states)
        ftotal = self.fa_const + float(np.sum(fmag_each))
        return 0.0, self.fa_const, 0.0, fmag_each, ftotal

    def step(self, t, x, v, h, models: Sequence[BrakeModel], states: np.ndarray):
        return _free_fall_advance(x, v, h, self.mass, self.fa_const, models, states)

    def spring_out_of_range(self, x: float) -> bool:
        return False


def make_physics(mode: str, recoil: RecoilParams, drive=None):
    if mode == MODE_RECOIL:
        return RecoilPhysics(recoil, drive)
    if mode == MODE_FREE_FALL:
        return FreeFallPhysics(recoil)
    raise ValueError(f"Неизвестный режим итерационного расчёта: {mode!r}")
