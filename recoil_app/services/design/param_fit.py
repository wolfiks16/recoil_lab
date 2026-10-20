"""Stage 2 — подбор физических параметров тормоза под синтезированную кривую F(v).

Параметрическая модель `magnetic_force_si` история-зависима (переходник wn), но
её «статическая» форма — квазистатическая сила `magnetic_force_quasistatic`
(закрытая форма wn*). Её и подгоняем под целевую кривую Stage 1.

Что подбирается, а что зафиксировано, задаёт `ParamSpace` (space.py): размеры
delta, xm, ym, dh1, dh2, dm, bz — каждый в своём диапазоне или зафиксирован,
целое n — набор вариантов; gamma (проводник), mu, lya, wn0 — фиксированы
(wn0 в квазистатику не входит вовсе — сходится из любого начального).

Подгон — differential_evolution по относительной RMSE (без симуляции в цикле:
только алгебра силы → тысячи прогонов дёшевы), с внешним перебором целого n.
Затем — верификация полной переходной динамикой и оценка робастности метрик к
индивидуальным допускам параметров (всех размеров, в т.ч. зафиксированных).
Если задана длина шины — система обязана на ней помещаться (objective.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import differential_evolution, least_squares

from ..magnetic import MagneticParams, magnetic_force_quasistatic
from .forward import Metrics, evaluate_parametric
from .objective import (
    bus_message,
    bus_report,
    curve_fit_penalty,
    design_residuals,
    within_limits,
)
from .space import CONT_PARAMS, ParamSpace, bound_hits, bound_hits_message  # noqa: F401
from .targets import DesignConstraints, DesignTargets


@dataclass(slots=True)
class ParamTolerances:
    """Индивидуальные относительные допуски на параметры (для робастности)."""

    rel: dict  # {param_name: относительный допуск}

    @classmethod
    def uniform(cls, value: float = 0.02) -> "ParamTolerances":
        return cls(rel={p: value for p in CONT_PARAMS})


@dataclass(slots=True)
class ParametricFit:
    params: MagneticParams
    n: int
    curve_rmse: float          # относительная RMSE к пику целевой кривой
    curve_max_rel_err: float
    fit_ok: bool


@dataclass(slots=True)
class ParametricResult:
    fit: ParametricFit         # стадия подгона под кривую (характеристика)
    params_final: MagneticParams  # после end-to-end доводки под метрики — итоговый дизайн
    curve_rmse_final: float    # RMSE итоговых параметров к целевой кривой (мог вырасти — норм)
    achieved: Metrics          # полная переходная симуляция с итоговыми параметрами
    rel_error: dict            # метрики vs цели
    within_tol: bool
    sigma_f_peak: float
    sigma_f_ok: bool           # пик ΣF ≤ потолок
    robustness: dict           # {'R', 'rel_sigma', 'per_param', 'sigma_f_margin'}
    messages: list = field(default_factory=list)
    bus: dict | None = None    # проверка длины шины (objective.bus_report); None — шина не задана
    bus_ok: bool = True        # помещается на шине (или шина не задана)
    bound_hits: list = field(default_factory=list)  # параметры у края диапазона (space.bound_hits)


def params_from_vec(x, n: int, space: ParamSpace) -> MagneticParams:
    """Тормоз из вектора ПОДБИРАЕМЫХ размеров (порядок space.free_params) + фиксированных."""
    d = dict(space.fixed)
    d.update({k: float(v) for k, v in zip(space.free_params, x)})
    return MagneticParams(n=int(n), **d)


def quasistatic_curve(v_grid, params: MagneticParams) -> np.ndarray:
    return np.array([magnetic_force_quasistatic(float(v), params) for v in v_grid], dtype=float)


def _curve_rmse(params: MagneticParams, v_grid, f_target, f_scale) -> float:
    try:
        fq = quasistatic_curve(v_grid, params)
    except (ValueError, OverflowError, ZeroDivisionError, FloatingPointError):
        return 1.0e6
    if not np.all(np.isfinite(fq)):
        return 1.0e6
    r = (fq - f_target) / f_scale
    return float(np.sqrt(np.mean(r * r)))


def _fit_cost(x, n, space, v_grid, f_target, f_scale, bus_length, stroke) -> float:
    """RMSE к кривой + штраф за непомещение на шине (ход — оценка, динамики тут нет)."""
    params = params_from_vec(x, n, space)
    return _curve_rmse(params, v_grid, f_target, f_scale) + curve_fit_penalty(params, stroke, bus_length)


def fit_parametric_to_curve(v_grid, f_target, space: ParamSpace | None = None,
                            *, bus_length: float | None = None, stroke: float = 0.0,
                            seed: int = 0, maxiter: int = 40, popsize: int = 12) -> ParametricFit:
    """Подгоняет подбираемые размеры + целое n под кривую F(v) (квазистатика).

    `stroke` — оценка хода для ограничения шины: x_max синтезированной кривой
    (нижняя оценка реального отката — годные варианты не отсекает); точную
    проверку с фактическим x_max делает доводка под метрики.
    """
    space = space or ParamSpace.default()
    v_grid = np.asarray(v_grid, dtype=float)
    f_target = np.asarray(f_target, dtype=float)
    f_scale = max(float(np.max(np.abs(f_target))), 1e-9)
    bounds = [space.cont_bounds[k] for k in space.free_params]
    args_tail = (v_grid, f_target, f_scale, bus_length, stroke)

    best = None  # (cost, n, x)
    for n in space.n_choices:
        if bounds:
            res = differential_evolution(
                _fit_cost, bounds, args=(n, space, *args_tail),
                seed=seed, maxiter=maxiter, popsize=popsize, tol=1e-4,
                mutation=(0.5, 1.0), recombination=0.7, polish=True, init="latinhypercube",
            )
            cost, x = float(res.fun), res.x
        else:  # все размеры зафиксированы — перебирается только n
            x = np.empty(0)
            cost = _fit_cost(x, n, space, *args_tail)
        if best is None or cost < best[0]:
            best = (cost, n, x)

    _cost, n, x = best
    params = params_from_vec(x, n, space)
    rmse = _curve_rmse(params, v_grid, f_target, f_scale)
    fq = quasistatic_curve(v_grid, params)
    max_rel = float(np.max(np.abs((fq - f_target) / f_scale)))
    return ParametricFit(params=params, n=n, curve_rmse=rmse,
                         curve_max_rel_err=max_rel, fit_ok=(rmse < 0.05))


def refine_parametric_end_to_end(drive, base, params0: MagneticParams, targets: DesignTargets,
                                 space: ParamSpace, *, sigma_f_max: float | None = None,
                                 bus_length: float | None = None,
                                 max_nfev: int = 60) -> MagneticParams:
    """Доводит подбираемые размеры (от curve-подгона) под МЕТРИКИ цикла.

    Кривая-подгон даёт хорошее нач. приближение, но переходник wn уводит метрики
    от статической кривой. Здесь `least_squares` минимизирует невязки (x_max, T,
    v_end, ΣF, шина) уже по полной симуляции. Оптимизируем в нормированных
    координатах u∈[0,1] (параметры разного масштаба). n — целое, фиксировано от
    curve-подгона; зафиксированные размеры не трогаются.
    """
    free = space.free_params
    if not free:
        return params0
    lo = np.array([space.cont_bounds[p][0] for p in free])
    hi = np.array([space.cont_bounds[p][1] for p in free])
    span = hi - lo

    x0 = np.array([getattr(params0, p) for p in free])
    u0 = np.clip((x0 - lo) / span, 0.0, 1.0)

    def _params_from_u(u):
        x = lo + np.clip(u, 0.0, 1.0) * span
        return params_from_vec(x, params0.n, space)

    def _resid(u):
        p = _params_from_u(u)
        return design_residuals(evaluate_parametric(drive, base, p), targets, sigma_f_max,
                                brakes=[p], bus_length=bus_length)

    res = least_squares(_resid, u0, method="trf", bounds=(0.0, 1.0),
                        max_nfev=max_nfev, diff_step=0.03, xtol=1e-4, ftol=1e-4, gtol=1e-8)
    return _params_from_u(res.x)


def _param_robustness(drive, base, params: MagneticParams, targets: DesignTargets,
                      tol: ParamTolerances, sigma_f_max: float, sigma_f_peak_nom: float) -> dict:
    """Чувствительность метрик (x_max, T, v_end) и пика ΣF к индивидуальным
    относительным допускам параметров — центральной разностью через полную симуляцию."""
    per_param = []
    contrib = {"x_max": [], "T": [], "v_end": []}
    contrib_sf = []

    for name in CONT_PARAMS:
        val = getattr(params, name)
        step = abs(val) * tol.rel.get(name, 0.0)
        if step == 0.0:
            continue

        p_plus = _with(params, name, val + step)
        p_minus = _with(params, name, val - step)
        m_plus = evaluate_parametric(drive, base, p_plus)
        m_minus = evaluate_parametric(drive, base, p_minus)

        row = {"param": name, "step": step}
        if m_plus.completed and m_minus.completed:
            cx = 0.5 * (m_plus.x_max - m_minus.x_max)
            cT = 0.5 * (m_plus.T - m_minus.T)
            cv = 0.5 * (m_plus.v_end - m_minus.v_end)
            csf = 0.5 * (m_plus.sigma_f_peak - m_minus.sigma_f_peak)
            contrib["x_max"].append(cx); contrib["T"].append(cT); contrib["v_end"].append(cv)
            contrib_sf.append(csf)
            row.update(x_max=cx, T=cT, v_end=cv, sigma_f=csf)
        else:
            row.update(x_max=float("nan"), T=float("nan"), v_end=float("nan"),
                       sigma_f=float("nan"), fragile=True)
        per_param.append(row)

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
            "per_param": per_param, "sigma_f_margin": sf_margin}


def _with(params: MagneticParams, name: str, value: float) -> MagneticParams:
    d = {f: getattr(params, f) for f in
         ("gamma", "delta", "xm", "ym", "dh1", "dh2", "dm", "n", "mu", "bz", "lya", "wn0")}
    d[name] = value
    return MagneticParams(**d)


def run_parametric_stage(drive, base, v_nodes, f_nodes, targets: DesignTargets,
                         constraints: DesignConstraints, *, space: ParamSpace | None = None,
                         param_tol: ParamTolerances | None = None, seed: int = 0,
                         stroke_hint: float | None = None) -> ParametricResult:
    """Полный Stage 2: подгон под кривую → верификация полной динамикой → робастность.

    `stroke_hint` — x_max синтезированной кривой (оценка хода для шины в подгоне).
    """
    space = space or ParamSpace.default()
    param_tol = param_tol or ParamTolerances.uniform(0.02)
    bus_length = constraints.bus_length

    # Целевая кривая, сэмплированная на рабочей сетке (пропускаем окрестность v=0).
    v_nodes = np.asarray(v_nodes, dtype=float)
    f_nodes = np.asarray(f_nodes, dtype=float)
    v_max = float(v_nodes[-1])
    v_grid = np.linspace(0.05 * v_max, v_max, 20)
    f_target = np.interp(v_grid, v_nodes, f_nodes)

    # Stage 2a — подгон под характеристику (даёт нач. приближение и выбор n).
    fit = fit_parametric_to_curve(v_grid, f_target, space, bus_length=bus_length,
                                  stroke=stroke_hint or 0.0, seed=seed)

    # Stage 2b — доводка под метрики полной динамикой (закрывает переходный зазор wn).
    params_final = refine_parametric_end_to_end(
        drive, base, fit.params, targets, space, sigma_f_max=constraints.sigma_f_max,
        bus_length=bus_length)

    # RMSE итоговых параметров к кривой (мог вырасти — метрики важнее формы).
    fq_final = quasistatic_curve(v_grid, params_final)
    f_scale = max(float(np.max(np.abs(f_target))), 1e-9)
    curve_rmse_final = float(np.sqrt(np.mean(((fq_final - f_target) / f_scale) ** 2)))

    # Верификация полной переходной симуляцией (итоговые параметры).
    achieved = evaluate_parametric(drive, base, params_final)
    rel_error = _rel_error(achieved, targets)
    within_tol = within_limits(achieved, targets)
    sigma_f_peak = achieved.sigma_f_peak if np.isfinite(achieved.sigma_f_peak) else float("nan")
    # Малый допуск (как у пределов) на переходный заброс силы над потолком.
    sigma_f_ok = bool(np.isfinite(sigma_f_peak)
                      and sigma_f_peak <= constraints.sigma_f_max * (1.0 + targets.rel_tol))

    bus = bus_report([params_final], achieved.x_max if achieved.completed else None, bus_length)
    bus_ok = bus is None or bus["fits"]
    hits = bound_hits(params_final, space)

    robustness = {}
    if achieved.completed:
        robustness = _param_robustness(drive, base, params_final, targets, param_tol,
                                       constraints.sigma_f_max, sigma_f_peak)

    messages = _diagnose(fit, achieved, within_tol, sigma_f_ok, sigma_f_peak, constraints,
                         bus=bus, hits_message=bound_hits_message([hits]))

    return ParametricResult(
        fit=fit, params_final=params_final, curve_rmse_final=curve_rmse_final,
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


def _diagnose(fit: ParametricFit, achieved: Metrics, within_tol, sigma_f_ok,
              sigma_f_peak, constraints, *, bus=None, hits_message=None) -> list:
    msgs = []
    if not fit.fit_ok:
        msgs.append(
            f"Параметрика приблизила кривую грубо (RMSE {fit.curve_rmse*100:.1f}%): "
            f"форма F(v) плохо ложится на параметрическую модель в заданных границах. "
            f"Расширьте границы или используйте curve-тормоз."
        )
    if not achieved.completed:
        msgs.append("С подобранными параметрами цикл не завершается — параметры непригодны.")
        return msgs
    if not sigma_f_ok:
        msgs.append(
            f"Пик ΣF={sigma_f_peak:.0f} Н превышает потолок {constraints.sigma_f_max:.0f} Н "
            f"(переходный заброс силы). Ужесточите целевую кривую или потолок."
        )
    bus_text = bus_message(bus)
    if bus_text:
        msgs.append(bus_text)
    if within_tol and sigma_f_ok and not bus_text:
        on_bus = ", помещается на шине" if bus else ""
        msgs.append("Параметры укладываются во все пределы (x_max/T/v_end ≤ лимитов, ΣF ≤ ΣF_max"
                    f"{on_bus}); x_max минимизирован.")
    elif not within_tol:
        msgs.append("Не удаётся уложиться во все пределы одновременно — какой-то из T/v_end/x_max "
                    "превышен. Ослабьте самый тесный предел или ΣF_max.")
    if hits_message:
        msgs.append(hits_message)
    return msgs
