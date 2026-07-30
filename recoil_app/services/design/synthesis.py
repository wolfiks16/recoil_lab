"""Stage 1 — синтез характеристики F(|v|) под конечные условия цикла.

Кривая параметризуется монотонно-возрастающей насыщающейся формой (физично для
вихретокового тормоза) через K свободных внутренних переменных u:

    d   = softplus(u)                        ≥ 0   (приращения)
    c   = cumsum(d)
    f_i = f_max · (1 − exp(−c_i))            ∈ [0, f_max)   — монотонно, с насыщением

Узел v=0 закреплён на F=0 (нет вихревых токов при нулевой скорости). Потолок ΣF
соблюдён структурно: f_i < f_max = ΣF_max.

Оптимизатор — Левенберг-Марквардт (`least_squares`, method='trf') по трём
нормированным невязкам (x_max, T, v_end). Он на порядок дешевле глобального DE
(десятки прогонов вместо тысяч); начальное приближение выбирается коротким
сканом по уровню торможения, чтобы стартовать в области, где цикл завершается.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from .forward import evaluate
from .objective import design_residuals
from .targets import DesignTargets

_U_BOUND = 8.0
_INIT_LEVELS = (-3.0, -1.5, 0.0, 1.5)   # равномерные уровни торможения для скана старта


def _softplus(u: np.ndarray) -> np.ndarray:
    """Численно устойчивый softplus."""
    u = np.asarray(u, dtype=float)
    return np.maximum(u, 0.0) + np.log1p(np.exp(-np.abs(u)))


def f_nodes_from_u(u, f_max: float) -> np.ndarray:
    """u (K свободных) → полный вектор узлов силы [0, f_1, …, f_K], монотонный."""
    d = _softplus(np.asarray(u, dtype=float))
    c = np.cumsum(d)
    f_free = f_max * (1.0 - np.exp(-c))
    return np.concatenate(([0.0], f_free))


def _residuals(u, drive, base, v_nodes, f_max, targets: DesignTargets) -> np.ndarray:
    f_nodes = f_nodes_from_u(u, f_max)
    m = evaluate(drive, base, v_nodes, f_nodes)
    return design_residuals(m, targets, f_max)


def synthesize_curve(drive, base, v_nodes, f_max: float, targets: DesignTargets,
                     *, max_nfev: int = 80):
    """Возвращает (f_nodes, sum_sq_residual). Прогоняется на переданном base.dt."""
    k = len(v_nodes) - 1
    args = (drive, base, v_nodes, f_max, targets)

    # --- скан старта: выбираем уровень торможения с наименьшей невязкой ---
    best_u, best_cost = None, np.inf
    for level in _INIT_LEVELS:
        u0 = np.full(k, level, dtype=float)
        r = _residuals(u0, *args)
        cost = float(np.sum(r * r))
        if cost < best_cost:
            best_cost, best_u = cost, u0

    # --- локальный LM от лучшего старта ---
    res = least_squares(
        _residuals, best_u, args=args, method="trf",
        bounds=(-_U_BOUND, _U_BOUND),
        max_nfev=max_nfev, diff_step=1e-2, xtol=1e-4, ftol=1e-4, gtol=1e-8,
    )

    f_nodes = f_nodes_from_u(res.x, f_max)
    return f_nodes, float(np.sum(res.fun ** 2))
