"""Обобщение Stage 2 на N тормозов.

Динамика зависит только от суммарной силы ΣF(v), поэтому синтезированная Stage 1
кривая — это ТОТАЛ. Здесь:
  1. Раскладка: кривая-тотал делится по весам w_i (Σw=1) на доли w_i·F_total(v).
  2. Подгон: каждый тормоз подгоняется под свою долю (curve-fit из param_fit).
     Одинаковые веса → одинаковые доли → подгон переиспользуется (дедуп).
  3. Совместная доводка: ВСЕ непрерывные параметры N тормозов доводятся вместе
     под метрики цикла (least_squares по полной динамике) — только сумма N
     переходных сил обязана попасть в (x_max, T, v_end).
  4. Робастность: чувствительность метрик к индивидуальным допускам каждого
     параметра каждого тормоза; выделяется доминирующая пара (тормоз, параметр).

Потолок ΣF применяется к СУММЕ (sigma_f_peak прогона = max|ΣF(t)|).
Шина (если задана) — у КАЖДОГО тормоза своя той же длины: проверяется каждый тормоз.
Подбираются только размеры из `space.free_params`; в робастности — все размеры.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from ..magnetic import MagneticParams
from .forward import Metrics, evaluate_brakes
from .objective import bus_message, bus_report, design_residuals, within_limits
from .param_fit import (
    ParamTolerances,
    fit_parametric_to_curve,
    params_from_vec,
    quasistatic_curve,
    _with,
)
from .space import CONT_PARAMS, ParamSpace, bound_hits, bound_hits_message
from .targets import DesignConstraints, DesignTargets


@dataclass(slots=True)
class MultiBrakeResult:
    n_brakes: int
    weights: tuple
    brakes: list                     # list[MagneticParams] — N подобранных тормозов
    per_brake_curve_rmse: list       # качество curve-подгона каждой доли
    achieved: Metrics                # полная динамика со всеми N тормозами
    rel_error: dict
    within_tol: bool
    sigma_f_peak: float
    sigma_f_ok: bool
    robustness: dict
    messages: list = field(default_factory=list)
    bus: dict | None = None          # проверка шины (у каждого тормоза своя); None — не задана
    bus_ok: bool = True
    bound_hits: list = field(default_factory=list)  # по тормозам: параметры у края диапазона


def _normalize_weights(weights, n: int) -> tuple:
    if weights is None:
        return tuple(1.0 / n for _ in range(n))
    w = np.asarray(weights, dtype=float)
    if len(w) != n or np.any(w <= 0):
        raise ValueError(f"Веса: нужно {n} положительных значений.")
    return tuple(float(x) for x in (w / w.sum()))


def refine_multi_end_to_end(drive, base, brakes0: list, targets: DesignTargets,
                            space: ParamSpace, *, symmetric: bool = False,
                            sigma_f_max: float | None = None, bus_length: float | None = None,
                            max_nfev: int | None = None) -> list:
    """Совместная доводка подбираемых размеров тормозов под метрики цикла.

    symmetric=True (равные веса) → один общий набор подбираемых размеров, N
    одинаковых тормозов: well-posed и вдвое-втрое дешевле. Иначе — независимые
    наборы по тормозам (underdetermined, LM держится рядом с по-долевым приближением).
    n каждого тормоза фиксировано из curve-подгона.
    """
    free = space.free_params
    if not free:
        return list(brakes0)
    n = len(brakes0)
    nc = len(free)
    lo = np.array([space.cont_bounds[p][0] for p in free])
    hi = np.array([space.cont_bounds[p][1] for p in free])
    span = hi - lo
    ns = [int(b.n) for b in brakes0]

    def _u_of(b):
        x = np.array([getattr(b, p) for p in free])
        return np.clip((x - lo) / span, 0.0, 1.0)

    if symmetric:
        n_shared = ns[0]
        u0 = _u_of(brakes0[0])

        def _brakes(u):
            x = lo + np.clip(u, 0.0, 1.0) * span
            return [params_from_vec(x, n_shared, space)] * n
        dim = nc
    else:
        u0 = np.concatenate([_u_of(b) for b in brakes0])

        def _brakes(u):
            out = []
            for i in range(n):
                x = lo + np.clip(u[i * nc:(i + 1) * nc], 0.0, 1.0) * span
                out.append(params_from_vec(x, ns[i], space))
            return out
        dim = n * nc

    def _resid(u):
        brakes = _brakes(u)
        return design_residuals(evaluate_brakes(drive, base, brakes), targets, sigma_f_max,
                                brakes=brakes, bus_length=bus_length)

    if max_nfev is None:
        max_nfev = min(90, 12 * dim) if symmetric else min(150, 10 * dim)

    res = least_squares(_resid, u0, method="trf", bounds=(0.0, 1.0),
                        max_nfev=max_nfev, diff_step=0.03, xtol=1e-4, ftol=1e-4, gtol=1e-8)
    return _brakes(res.x)


def _multi_robustness(drive, base, brakes: list, targets: DesignTargets,
                      tol: ParamTolerances, sigma_f_max: float, sigma_f_peak_nom: float,
                      *, symmetric: bool = False) -> dict:
    """Чувствительность метрик к индивидуальным допускам каждого (тормоз, параметр).

    symmetric=True (одинаковые тормоза): возмущаем один тормоз, а σ по каждому
    параметру масштабируем на √N — N одинаковых тормозов дают N независимых
    (по производству) источников разброса, складывающихся в квадратуре.
    """
    n = len(brakes)
    contrib = {"x_max": [], "T": [], "v_end": []}
    contrib_sf = []
    per = []

    brake_indices = [0] if symmetric else range(n)
    scale = float(np.sqrt(n)) if symmetric else 1.0

    for bi in brake_indices:
        b = brakes[bi]
        for name in CONT_PARAMS:
            val = getattr(b, name)
            step = abs(val) * tol.rel.get(name, 0.0)
            if step == 0.0:
                continue
            plus = list(brakes);  plus[bi] = _with(b, name, val + step)
            minus = list(brakes); minus[bi] = _with(b, name, val - step)
            m_plus = evaluate_brakes(drive, base, plus)
            m_minus = evaluate_brakes(drive, base, minus)

            row = {"brake": ("×N" if symmetric else bi + 1), "param": name}
            if m_plus.completed and m_minus.completed:
                cx = scale * 0.5 * (m_plus.x_max - m_minus.x_max)
                cT = scale * 0.5 * (m_plus.T - m_minus.T)
                cv = scale * 0.5 * (m_plus.v_end - m_minus.v_end)
                csf = scale * 0.5 * (m_plus.sigma_f_peak - m_minus.sigma_f_peak)
                contrib["x_max"].append(cx); contrib["T"].append(cT); contrib["v_end"].append(cv)
                contrib_sf.append(csf)
                row.update(x_max=cx, T=cT, v_end=cv, sigma_f=csf)
            else:
                row.update(x_max=float("nan"), T=float("nan"), v_end=float("nan"),
                           sigma_f=float("nan"), fragile=True)
            per.append(row)

    def _rss(vals):
        arr = np.array([v for v in vals if np.isfinite(v)], dtype=float)
        return float(np.sqrt(np.sum(arr * arr))) if arr.size else float("nan")

    sigma_abs = {k: _rss(contrib[k]) for k in contrib}
    rel_sigma = {
        "x_max": sigma_abs["x_max"] / targets.x_max if targets.x_max else float("nan"),
        "T": sigma_abs["T"] / targets.T if targets.T else float("nan"),
        "v_end": sigma_abs["v_end"] / max(targets.v_end, 1e-9),
    }
    finite = [v for v in rel_sigma.values() if np.isfinite(v)]
    R = float(np.sqrt(np.sum(np.square(finite)))) if finite else float("nan")

    sf_sigma = _rss(contrib_sf)
    sf_margin = ((sigma_f_max - sigma_f_peak_nom) / sf_sigma) if (np.isfinite(sf_sigma) and sf_sigma > 0) else float("inf")

    return {"R": R, "rel_sigma": rel_sigma, "sigma_abs": sigma_abs,
            "per_param": per, "sigma_f_margin": sf_margin}


def run_multi_brake_stage(drive, base, v_nodes, f_nodes, targets: DesignTargets,
                          constraints: DesignConstraints, *, n_brakes: int, weights=None,
                          space: ParamSpace | None = None, param_tol: ParamTolerances | None = None,
                          seed: int = 0, stroke_hint: float | None = None) -> MultiBrakeResult:
    space = space or ParamSpace.default()
    param_tol = param_tol or ParamTolerances.uniform(0.02)
    weights = _normalize_weights(weights, n_brakes)
    symmetric = bool(np.allclose(weights, weights[0], atol=1e-9))
    bus_length = constraints.bus_length

    v_nodes = np.asarray(v_nodes, dtype=float)
    f_nodes = np.asarray(f_nodes, dtype=float)
    v_max = float(v_nodes[-1])
    v_grid = np.linspace(0.05 * v_max, v_max, 20)
    f_total = np.interp(v_grid, v_nodes, f_nodes)

    # Раскладка + подгон каждой доли (дедуп по одинаковым весам).
    fits: dict = {}
    brakes0, per_rmse = [], []
    for w in weights:
        key = round(w, 9)
        if key not in fits:
            fits[key] = fit_parametric_to_curve(v_grid, w * f_total, space, bus_length=bus_length,
                                                stroke=stroke_hint or 0.0, seed=seed)
        fit = fits[key]
        brakes0.append(fit.params)
        per_rmse.append(fit.curve_rmse)

    # Совместная доводка под метрики.
    brakes = refine_multi_end_to_end(drive, base, brakes0, targets, space, symmetric=symmetric,
                                     sigma_f_max=constraints.sigma_f_max, bus_length=bus_length)

    achieved = evaluate_brakes(drive, base, brakes)
    rel_error = _rel_error(achieved, targets)
    within_tol = within_limits(achieved, targets)
    sigma_f_peak = achieved.sigma_f_peak if np.isfinite(achieved.sigma_f_peak) else float("nan")
    # Малый допуск (как у пределов) на переходный заброс суммарной силы над потолком.
    sigma_f_ok = bool(np.isfinite(sigma_f_peak)
                      and sigma_f_peak <= constraints.sigma_f_max * (1.0 + targets.rel_tol))

    bus = bus_report(brakes, achieved.x_max if achieved.completed else None, bus_length)
    bus_ok = bus is None or bus["fits"]
    hits = [bound_hits(b, space) for b in brakes]
    # Одинаковые тормоза упираются одинаково — сообщаем один раз, без номеров.
    hits_message = bound_hits_message(hits[:1] if symmetric else hits)

    robustness = {}
    if achieved.completed:
        robustness = _multi_robustness(drive, base, brakes, targets, param_tol,
                                       constraints.sigma_f_max, sigma_f_peak, symmetric=symmetric)

    messages = _diagnose(achieved, within_tol, sigma_f_ok, sigma_f_peak, constraints, n_brakes,
                         bus=bus, hits_message=hits_message)

    return MultiBrakeResult(
        n_brakes=n_brakes, weights=weights, brakes=brakes, per_brake_curve_rmse=per_rmse,
        achieved=achieved, rel_error=rel_error, within_tol=within_tol,
        sigma_f_peak=sigma_f_peak, sigma_f_ok=sigma_f_ok, robustness=robustness,
        messages=messages, bus=bus, bus_ok=bus_ok, bound_hits=hits,
    )


def _rel_error(achieved: Metrics, targets: DesignTargets) -> dict:
    if not achieved.completed:
        return {"x_max": float("nan"), "T": float("nan"), "v_end": float("nan")}
    return {
        "x_max": (achieved.x_max - targets.x_max) / targets.x_max,
        "T": (achieved.T - targets.T) / targets.T,
        "v_end": (achieved.v_end - targets.v_end) / max(targets.v_end, 1e-9),
    }


def _diagnose(achieved, within_tol, sigma_f_ok, sigma_f_peak, constraints, n_brakes, *,
              bus=None, hits_message=None) -> list:
    msgs = []
    if not achieved.completed:
        msgs.append(f"С {n_brakes} подобранными тормозами цикл не завершается — параметры непригодны.")
        return msgs
    if not sigma_f_ok:
        msgs.append(
            f"Суммарный пик ΣF={sigma_f_peak:.0f} Н превышает потолок {constraints.sigma_f_max:.0f} Н."
        )
    bus_text = bus_message(bus)
    if bus_text:
        msgs.append(bus_text)
    if within_tol and sigma_f_ok and not bus_text:
        on_bus = ", каждый помещается на своей шине" if bus else ""
        msgs.append(f"{n_brakes} тормоза укладываются во все пределы (x_max/T/v_end ≤ лимитов, "
                    f"ΣF ≤ ΣF_max{on_bus}); x_max минимизирован.")
    elif not within_tol:
        msgs.append("Не удаётся уложиться во все пределы одновременно — ослабьте самый тесный.")
    if hits_message:
        msgs.append(hits_message)
    return msgs
