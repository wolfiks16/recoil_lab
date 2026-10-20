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

Связанное ограничение конструкции — длина шины (если задана): у каждого тормоза
своя шина длины L_шины, магнитная система всё время хода остаётся над ней:
    N·x_m + (N−1)·d_m + x_max ≤ L_шины
Используется в подгоне под кривую (штраф к RMSE), в доводке под метрики
(доп. невязка) и в итоговой проверке достижимости.
"""

from __future__ import annotations

import numpy as np

# Веса невязок для least_squares: ограничения (жёсткие) ≫ цель (мягкая минимизация).
_W_OBJECTIVE = 1.0
_W_CONSTRAINT = 25.0
_NOT_COMPLETED = 6.0
# Шина — геометрия, допуска «на шум» как у пределов цикла у неё нет: вес выше,
# чтобы штрафной метод не оставлял заметного (миллиметры) превышения длины.
_W_BUS = 100.0
# Штраф к относительной RMSE подгона под кривую (DE) за 100 % превышения длины шины.
_W_BUS_FIT = 10.0
# Допуск на численное превышение длины шины (доля L_шины): ход x_max — из численной динамики.
BUS_REL_TOL = 1e-3


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


def design_residuals(m, t, sigma_f_max: float | None = None, *,
                     brakes=None, bus_length: float | None = None) -> np.ndarray:
    """Невязки least_squares: минимизировать x_max + односторонние штрафы за
    превышение пределов x_max/T/v_end (и ΣF, если задан). Под пределом → штраф 0.

    ΣF-штраф ОБЯЗАТЕЛЕН для параметрических тормозов: их сила не ограничена
    структурно потолком, и без штрафа минимизация x_max загнала бы силу за ΣF_max.
    Если задана шина (`bus_length` + параметрические `brakes`) — ещё невязка за
    «не помещается на шине» с фактическим ходом x_max этого прогона.
    """
    use_bus = bus_length is not None and brakes is not None
    if not m.completed:
        n = 4 + (sigma_f_max is not None) + use_bus
        return np.full(n, _NOT_COMPLETED)
    res = [
        _W_OBJECTIVE * (m.x_max / max(abs(t.x_max), 1e-9)),   # ↓ x_max — главная цель
        _W_CONSTRAINT * _over(m.x_max, t.x_max),              # x_max ≤ предел
        _W_CONSTRAINT * _over(m.T, t.T),                      # T ≤ предел
        _W_CONSTRAINT * _over(m.v_end, t.v_end),             # v_end ≤ предел
    ]
    if sigma_f_max is not None:
        res.append(_W_CONSTRAINT * _over(m.sigma_f_peak, sigma_f_max))  # ΣF ≤ потолок
    if use_bus:
        res.append(_W_BUS * bus_overshoot(brakes, m.x_max, bus_length))  # помещается на шине
    return np.array(res)


# --- Шина -------------------------------------------------------------------------------


def system_length(n, xm, dm) -> float:
    """Длина магнитной системы одного тормоза вдоль шины: N·x_m + (N−1)·d_m."""
    n = int(n)
    return n * float(xm) + max(n - 1, 0) * float(dm)


def bus_overshoot(brakes, stroke, bus_length: float | None) -> float:
    """Относительное превышение длины шины худшим тормозом (0 = помещается / шина не задана).

    У каждого тормоза своя шина длины `bus_length`; система должна оставаться над
    ней на всём ходе: L_i + ход ≤ L_шины. Ход — откат x_max: за цикл система
    проходит относительно шины [0, x_max] (накат кончается в x=0). Неизвестный ход
    (None/nan) считается нулевым.
    """
    if bus_length is None:
        return 0.0
    stroke = float(stroke) if stroke is not None and np.isfinite(stroke) else 0.0
    return max(_over(system_length(b.n, b.xm, b.dm) + max(stroke, 0.0), bus_length)
               for b in brakes)


def curve_fit_penalty(params, stroke, bus_length: float | None) -> float:
    """Штраф к RMSE подгона одного тормоза под кривую (там динамики нет — ход оценочный)."""
    return _W_BUS_FIT * bus_overshoot([params], stroke, bus_length)


def bus_report(brakes, stroke, bus_length: float | None) -> dict | None:
    """Итог проверки шины для снапшота/сообщений; None, если шина не задана."""
    if bus_length is None:
        return None
    lengths = [system_length(b.n, b.xm, b.dm) for b in brakes]
    known = stroke is not None and np.isfinite(stroke)
    overshoot = bus_overshoot(brakes, stroke, bus_length)
    required = max(lengths) + max(float(stroke), 0.0) if known else None
    return {
        "bus_length": float(bus_length),
        "stroke": float(stroke) if known else None,
        "system_lengths": lengths,
        "required": required,
        "margin": (float(bus_length) - required) if required is not None else None,
        "overshoot": overshoot,
        "fits": bool(known and overshoot <= BUS_REL_TOL),
    }


def bus_message(bus: dict | None) -> str | None:
    """Сообщение «не помещается на шине» (или None, если помещается / шина не задана)."""
    if not bus or bus["fits"]:
        return None
    if bus["required"] is None:
        return "Длину на шине проверить нельзя: цикл не завершился."
    return (f"Магнитная система не помещается на шине: N·x_m + (N−1)·d_m + ход = "
            f"{bus['required']:.4g} м > L шины = {bus['bus_length']:.4g} м. "
            f"Сузьте диапазоны N, x_m, d_m или удлините шину.")
