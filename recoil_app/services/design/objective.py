"""Целевая функция и ограничения обратного проектирования (единый источник правды).

Новая постановка (лимиты, а не точные цели):
  минимизировать  x_max            (главное — самый компактный откат)
  при условии     x_max ≤ X_lim
                  T     ≤ T_lim     (просто под пределом — не давим, чтобы
                  v_end ≤ V_lim      осталась свобода → робастность)
                  ΣF_peak ≤ ΣF_max  (жёстко, проверяется отдельно)

Все три величины (`x_max`, `T`, `v_end`) в `DesignTargets` теперь трактуются как
ВЕРХНИЕ ПРЕДЕЛЫ. Быть под пределом — всегда допустимо; `rel_tol` — маленький
допуск на численное превышение предела.
"""

from __future__ import annotations

import numpy as np

# Веса невязок для least_squares: ограничения (жёсткие) ≫ цель (мягкая минимизация).
_W_OBJECTIVE = 1.0
_W_CONSTRAINT = 25.0
_NOT_COMPLETED = 6.0


def _over(value: float, limit: float) -> float:
    """Относительное превышение предела; 0, если под пределом."""
    return max(0.0, (value - limit) / max(abs(limit), 1e-9))


def constraint_overshoot(m, t) -> float:
    """Макс. относительное превышение любого из трёх пределов (0 = всё под пределами)."""
    if not m.completed:
        return float("inf")
    return max(_over(m.x_max, t.x_max), _over(m.T, t.T), _over(m.v_end, t.v_end))


def within_limits(m, t) -> bool:
    """Все три величины под пределами (с допуском rel_tol на численный шум)."""
    return bool(m.completed and constraint_overshoot(m, t) <= t.rel_tol)


def design_residuals(m, t, sigma_f_max: float | None = None) -> np.ndarray:
    """Невязки least_squares: минимизировать x_max + односторонние штрафы за
    превышение пределов x_max/T/v_end (и ΣF, если задан). Под пределом → штраф 0.

    ΣF-штраф ОБЯЗАТЕЛЕН для параметрических тормозов: их сила не ограничена
    структурно потолком, и без штрафа минимизация x_max загнала бы силу за ΣF_max.
    """
    if not m.completed:
        n = 5 if sigma_f_max is not None else 4
        return np.full(n, _NOT_COMPLETED)
    res = [
        _W_OBJECTIVE * (m.x_max / max(abs(t.x_max), 1e-9)),   # ↓ x_max — главная цель
        _W_CONSTRAINT * _over(m.x_max, t.x_max),              # x_max ≤ предел
        _W_CONSTRAINT * _over(m.T, t.T),                      # T ≤ предел
        _W_CONSTRAINT * _over(m.v_end, t.v_end),             # v_end ≤ предел
    ]
    if sigma_f_max is not None:
        res.append(_W_CONSTRAINT * _over(m.sigma_f_peak, sigma_f_max))  # ΣF ≤ потолок
    return np.array(res)
