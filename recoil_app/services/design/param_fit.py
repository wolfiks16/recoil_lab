"""Stage 2 — подбор физических параметров тормоза под синтезированную кривую F(v).

Параметрическая модель `magnetic_force_si` история-зависима (переходник wn), но
её «статическая» форма — квазистатическая сила `magnetic_force_quasistatic`
(закрытая форма wn*). Её и подгоняем под целевую кривую Stage 1.

Свободные параметры (design): delta, xm, ym, dh1, dh2, dm, bz + целое n.
Фиксированные (материал/стандарт): gamma (проводник), mu, lya, wn0 —
wn0 в квазистатику не входит вовсе (сходится из любого начального).

Подгон — differential_evolution по относительной RMSE (без симуляции в цикле:
только алгебра силы → тысячи прогонов дёшевы), с внешним перебором целого n.
Затем — верификация полной переходной динамикой и оценка робастности метрик к
индивидуальным допускам параметров.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import differential_evolution, least_squares

from ..magnetic import MagneticParams, magnetic_force_quasistatic
from .forward import Metrics, evaluate_parametric
from .targets import DesignConstraints, DesignTargets

# Порядок свободных непрерывных параметров.
CONT_PARAMS = ("delta", "xm", "ym", "dh1", "dh2", "dm", "bz")


@dataclass(slots=True)
class ParamSpace:
    """Границы конструкции: диапазоны непрерывных параметров, набор целых n,
    фиксированные материал/стандарт."""

    cont_bounds: dict
    n_choices: tuple
    fixed: dict

    @classmethod
    def default(cls) -> "ParamSpace":
        return cls(
            cont_bounds={
                "delta": (0.001, 0.008),
                "xm": (0.012, 0.035),
                "ym": (0.10, 0.75),
                "dh1": (0.008, 0.040),
                "dh2": (0.008, 0.040),
                "dm": (0.006, 0.030),
                "bz": (0.40, 2.00),
            },
            n_choices=(8, 10, 12, 14, 16, 18, 20, 24),
            fixed={"gamma": 1.77e7, "mu": 1.0, "lya": 2.5, "wn0": 1.0},
        )


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


def params_from_vec(x, n: int, space: ParamSpace) -> MagneticParams:
    d = {k: float(v) for k, v in zip(CONT_PARAMS, x)}
    return MagneticParams(n=int(n), **d, **space.fixed)


def quasistatic_curve(v_grid, params: MagneticParams) -> np.ndarray:
    return np.array([magnetic_force_quasistatic(float(v), params) for v in v_grid], dtype=float)


def _rmse(x, n, space, v_grid, f_target, f_scale) -> float:
    try:
        fq = quasistatic_curve(v_grid, params_from_vec(x, n, space))
    except (ValueError, OverflowError, ZeroDivisionError, FloatingPointError):
        return 1.0e6
    if not np.all(np.isfinite(fq)):
        return 1.0e6
    r = (fq - f_target) / f_scale
    return float(np.sqrt(np.mean(r * r)))


def fit_parametric_to_curve(v_grid, f_target, space: ParamSpace | None = None,
                            *, seed: int = 0, maxiter: int = 40, popsize: int = 12) -> ParametricFit:
    """Подгоняет 7 непрерывных параметров + целое n под кривую F(v) (квазистатика)."""
    space = space or ParamSpace.default()
    v_grid = np.asarray(v_grid, dtype=float)
    f_target = np.asarray(f_target, dtype=float)
    f_scale = max(float(np.max(np.abs(f_target))), 1e-9)
    bounds = [space.cont_bounds[k] for k in CONT_PARAMS]

    best = None  # (rmse, n, x)
    for n in space.n_choices:
        res = differential_evolution(
            _rmse, bounds, args=(n, space, v_grid, f_target, f_scale),
            seed=seed, maxiter=maxiter, popsize=popsize, tol=1e-4,
            mutation=(0.5, 1.0), recombination=0.7, polish=True, init="latinhypercube",
        )
        if best is None or res.fun < best[0]:
            best = (res.fun, n, res.x)

    rmse, n, x = best
    params = params_from_vec(x, n, space)
    fq = quasistatic_curve(v_grid, params)
    max_rel = float(np.max(np.abs((fq - f_target) / f_scale)))
    return ParametricFit(params=params, n=n, curve_rmse=rmse,
                         curve_max_rel_err=max_rel, fit_ok=(rmse < 0.05))


def refine_parametric_end_to_end(drive, base, params0: MagneticParams, targets: DesignTargets,
                                 space: ParamSpace, *, max_nfev: int = 60) -> MagneticParams:
    """Доводит непрерывные параметры (от curve-подгона) под МЕТРИКИ цикла.

    Кривая-подгон даёт хорошее нач. приближение, но переходник wn уводит метрики
    от статической кривой. Здесь `least_squares` минимизирует невязки (x_max, T,
    v_end) уже по полной симуляции. Оптимизируем в нормированных координатах
    u∈[0,1] (параметры разного масштаба). n — целое, фиксировано от curve-подгона.
    """
    lo = np.array([space.cont_bounds[p][0] for p in CONT_PARAMS])
    hi = np.array([space.cont_bounds[p][1] for p in CONT_PARAMS])
    span = hi - lo

    x0 = np.array([getattr(params0, p) for p in CONT_PARAMS])
    u0 = np.clip((x0 - lo) / span, 0.0, 1.0)

    def _params_from_u(u):
        x = lo + np.clip(u, 0.0, 1.0) * span
        return params_from_vec(x, params0.n, space)

    def _resid(u):
        m = evaluate_parametric(drive, base, _params_from_u(u))
        if not m.completed:
            if np.isfinite(m.x_max) and targets.x_max > 0:
                dx = np.clip((m.x_max - targets.x_max) / targets.x_max, -3.0, 3.0)
                return np.array([5.0 + dx, 5.0, 5.0])
            return np.array([8.0, 8.0, 8.0])
        return np.array([
            (m.x_max - targets.x_max) / targets.x_max,
            (m.T - targets.T) / targets.T,
            (m.v_end - targets.v_end) / max(targets.v_end, 1e-9),
        ])

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
                         param_tol: ParamTolerances | None = None, seed: int = 0) -> ParametricResult:
    """Полный Stage 2: подгон под кривую → верификация полной динамикой → робастность."""
    space = space or ParamSpace.default()
    param_tol = param_tol or ParamTolerances.uniform(0.02)

    # Целевая кривая, сэмплированная на рабочей сетке (пропускаем окрестность v=0).
    v_nodes = np.asarray(v_nodes, dtype=float)
    f_nodes = np.asarray(f_nodes, dtype=float)
    v_max = float(v_nodes[-1])
    v_grid = np.linspace(0.05 * v_max, v_max, 20)
    f_target = np.interp(v_grid, v_nodes, f_nodes)

    # Stage 2a — подгон под характеристику (даёт нач. приближение и выбор n).
    fit = fit_parametric_to_curve(v_grid, f_target, space, seed=seed)

    # Stage 2b — доводка под метрики полной динамикой (закрывает переходный зазор wn).
    params_final = refine_parametric_end_to_end(drive, base, fit.params, targets, space)

    # RMSE итоговых параметров к кривой (мог вырасти — метрики важнее формы).
    fq_final = quasistatic_curve(v_grid, params_final)
    f_scale = max(float(np.max(np.abs(f_target))), 1e-9)
    curve_rmse_final = float(np.sqrt(np.mean(((fq_final - f_target) / f_scale) ** 2)))

    # Верификация полной переходной симуляцией (итоговые параметры).
    achieved = evaluate_parametric(drive, base, params_final)
    rel_error = _rel_error(achieved, targets)
    within_tol = achieved.completed and all(
        abs(rel_error[k]) <= targets.rel_tol for k in ("x_max", "T", "v_end")
    )
    sigma_f_peak = achieved.sigma_f_peak if np.isfinite(achieved.sigma_f_peak) else float("nan")
    sigma_f_ok = bool(np.isfinite(sigma_f_peak) and sigma_f_peak <= constraints.sigma_f_max)

    robustness = {}
    if achieved.completed:
        robustness = _param_robustness(drive, base, params_final, targets, param_tol,
                                       constraints.sigma_f_max, sigma_f_peak)

    messages = _diagnose(fit, achieved, within_tol, sigma_f_ok, sigma_f_peak, constraints)

    return ParametricResult(
        fit=fit, params_final=params_final, curve_rmse_final=curve_rmse_final,
        achieved=achieved, rel_error=rel_error, within_tol=within_tol,
        sigma_f_peak=sigma_f_peak, sigma_f_ok=sigma_f_ok, robustness=robustness,
        messages=messages,
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
              sigma_f_peak, constraints) -> list:
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
    if within_tol and sigma_f_ok:
        msgs.append("Параметры обеспечивают цели и не превышают ΣF_max (в пределах допуска).")
    return msgs
