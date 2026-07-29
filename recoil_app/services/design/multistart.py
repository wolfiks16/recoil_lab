"""Мультистарт + отбор по робастности.

Подбор параметров не единственен: разные наборы (для одного тормоза — разные `n`;
для N — разные раскладки ΣF) дают ту же цель. Здесь генерируем СЕМЕЙСТВО кандидатов,
и среди попавших в цель выбираем самый РОБАСТНЫЙ (min R) — робастность как отборщик
по многообразию решений (как и задумывалось: «раскладка ΣF — доп. степень свободы
робастности»).

Двухфидельно ради скорости:
  1. Скрининг ВСЕХ кандидатов на грубом dt (дёшево) → грубые R и допустимость.
  2. Точная доводка только победителя на рабочем dt.
Грубый dt смещает абсолютные метрики, но относительный порядок робастности держит.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..dynamics import RecoilParams
from .multi_brake import run_multi_brake_stage
from .param_fit import ParamSpace, ParamTolerances, run_parametric_stage


@dataclass(slots=True)
class Candidate:
    label: str
    config: dict
    result: object            # ParametricResult | MultiBrakeResult
    R: float
    feasible: bool
    max_abs_err: float
    fidelity: str             # 'coarse' | 'fine'


@dataclass(slots=True)
class MultistartResult:
    candidates: list          # ВСЕ (грубые) — для согласованного Парето-графика
    best: Candidate | None    # победитель, доведённый на рабочем (точном) dt
    best_coarse: Candidate | None  # его грубая запись в `candidates` (для отметки ★ на Парето)
    n_evaluated: int
    n_feasible: int
    coarse_dt: float


def _default_configs(n_brakes: int, space: ParamSpace) -> list:
    if n_brakes <= 1:
        ns = list(space.n_choices)
        pick = ns[::2][:4] if len(ns) > 4 else ns   # разброс по n
        return [{"n": int(n), "label": f"n={int(n)}"} for n in pick]

    if n_brakes == 2:
        raw = [(1, 1), (3, 2), (2, 1), (3, 1)]
    elif n_brakes == 3:
        raw = [(1, 1, 1), (2, 1, 1), (3, 2, 1)]
    else:
        raw = [tuple(1 for _ in range(n_brakes)), tuple([2] + [1] * (n_brakes - 1))]
    return [{"weights": [float(x) for x in w],
             "label": "веса " + "/".join(str(x) for x in w)} for w in raw]


def _evaluate_config(drive, base, v_nodes, f_nodes, targets, constraints,
                     n_brakes, cfg, space, param_tol, seed):
    if n_brakes <= 1:
        sp = ParamSpace(cont_bounds=space.cont_bounds, n_choices=(cfg["n"],), fixed=space.fixed)
        res = run_parametric_stage(drive, base, v_nodes, f_nodes, targets, constraints,
                                   space=sp, param_tol=param_tol, seed=seed)
    else:
        res = run_multi_brake_stage(drive, base, v_nodes, f_nodes, targets, constraints,
                                    n_brakes=n_brakes, weights=cfg["weights"],
                                    space=space, param_tol=param_tol, seed=seed)
    R = (res.robustness or {}).get("R", float("inf"))
    feasible = bool(res.within_tol and res.sigma_f_ok)
    errs = [abs(v) for v in res.rel_error.values() if v == v]
    max_err = max(errs) if errs else float("inf")
    return res, R, feasible, max_err


def run_multistart(drive, base_fine: RecoilParams, v_nodes, f_nodes, targets, constraints, *,
                   n_brakes: int, space: ParamSpace | None = None,
                   param_tol: ParamTolerances | None = None,
                   configs: list | None = None, seed: int = 0) -> MultistartResult:
    space = space or ParamSpace.default()
    param_tol = param_tol or ParamTolerances.uniform(0.02)
    configs = configs or _default_configs(n_brakes, space)

    coarse_dt = max(base_fine.dt, base_fine.t_max / 400.0)
    coarse = RecoilParams(mass=base_fine.mass, angle_deg=base_fine.angle_deg,
                          v0=base_fine.v0, x0=base_fine.x0, t_max=base_fine.t_max, dt=coarse_dt)

    # --- Скрининг всех кандидатов на грубом dt ---
    screened = []
    for cfg in configs:
        res, R, feasible, max_err = _evaluate_config(
            drive, coarse, v_nodes, f_nodes, targets, constraints,
            n_brakes, cfg, space, param_tol, seed)
        screened.append(Candidate(label=cfg["label"], config=cfg, result=res, R=R,
                                  feasible=feasible, max_abs_err=max_err, fidelity="coarse"))

    # Отбор кандидатов на доводку: грубый dt смещает метрики, поэтому берём не
    # строгий допуск, а расширенный (2×) — иначе почти-достижимые кандидаты
    # ложно отсеиваются. Истинную достижимость решит доводка победителя на точном dt.
    screen_tol = 2.0 * targets.rel_tol
    eligible = sorted([c for c in screened if np.isfinite(c.R) and c.max_abs_err <= screen_tol],
                      key=lambda c: c.R)
    rest = sorted([c for c in screened if c not in eligible], key=lambda c: c.max_abs_err)
    ranked = eligible + rest   # всё грубое — единая шкала для Парето

    # --- Точная доводка победителя (min R среди подходящих) на рабочем dt ---
    best = None
    best_coarse = None
    if eligible:
        best_coarse = eligible[0]           # грубая запись победителя (остаётся в `ranked`)
        win_cfg = best_coarse.config
        res, R, feasible, max_err = _evaluate_config(
            drive, base_fine, v_nodes, f_nodes, targets, constraints,
            n_brakes, win_cfg, space, param_tol, seed)
        best = Candidate(label=best_coarse.label, config=win_cfg, result=res, R=R,
                         feasible=feasible, max_abs_err=max_err, fidelity="fine")

    return MultistartResult(candidates=ranked, best=best, best_coarse=best_coarse,
                            n_evaluated=len(screened), n_feasible=len(eligible),
                            coarse_dt=coarse_dt)
