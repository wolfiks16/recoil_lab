"""Stage 3-скоринг — робастность решения к индивидуальным допускам узлов F(v).

Чувствительность метрик (x_max, T, v_end) к каждому свободному узлу считается
центральной разностью с шагом = допуск этого узла. Вклад узла i в разброс метрики
m равен половине разности m(f+tol) − m(f−tol); суммарный σ_m — RSS вкладов.
Робастность R — нормированная на цели свёртка σ по трём метрикам (меньше = лучше).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .forward import evaluate
from .targets import DesignTargets, ToleranceModel


@dataclass(slots=True)
class RobustnessReport:
    R: float                                   # свёртка (меньше = робастнее)
    rel_sigma: dict                            # {'x_max','T','v_end'} → отн. σ метрики
    sigma_abs: dict                            # то же в абсолютных единицах
    sigma_f_margin: float                      # запас до ΣF_max в «сигмах» разброса ΣF
    node_contrib: list = field(default_factory=list)  # [{node, x_max, T, v_end, sigma_f}] — вклады узлов
    warnings: list = field(default_factory=list)


def score_robustness(drive, base, v_nodes, f_nodes, tol: ToleranceModel,
                     targets: DesignTargets, sigma_f_max: float,
                     sigma_f_peak_nominal: float) -> RobustnessReport:
    f_nodes = np.asarray(f_nodes, dtype=float)
    node_tol = np.asarray(tol.node_tol, dtype=float)
    k = len(f_nodes) - 1  # свободные узлы (индексы 1..k)

    if len(node_tol) != k:
        raise ValueError(
            f"Число допусков ({len(node_tol)}) не совпадает с числом свободных узлов ({k})."
        )

    contrib_x, contrib_T, contrib_v, contrib_sf = [], [], [], []
    node_contrib = []
    warnings: list[str] = []

    for i in range(k):
        step = node_tol[i]
        node_idx = i + 1

        f_plus = f_nodes.copy();  f_plus[node_idx] += step
        f_minus = f_nodes.copy(); f_minus[node_idx] = max(0.0, f_minus[node_idx] - step)

        m_plus = evaluate(drive, base, v_nodes, f_plus)
        m_minus = evaluate(drive, base, v_nodes, f_minus)

        # x_max определён всегда (даже без завершения цикла)
        cx = 0.5 * (m_plus.x_max - m_minus.x_max) if (
            np.isfinite(m_plus.x_max) and np.isfinite(m_minus.x_max)) else float("nan")
        csf = 0.5 * (m_plus.sigma_f_peak - m_minus.sigma_f_peak) if (
            np.isfinite(m_plus.sigma_f_peak) and np.isfinite(m_minus.sigma_f_peak)) else float("nan")

        if m_plus.completed and m_minus.completed:
            cT = 0.5 * (m_plus.T - m_minus.T)
            cv = 0.5 * (m_plus.v_end - m_minus.v_end)
        else:
            cT = float("nan")
            cv = float("nan")
            warnings.append(
                f"Узел {node_idx}: при возмущении на ±допуск цикл не завершается — "
                f"чувствительность T/v_end по нему не учтена (решение хрупкое у этого узла)."
            )

        contrib_x.append(cx); contrib_T.append(cT); contrib_v.append(cv); contrib_sf.append(csf)
        node_contrib.append({
            "node": node_idx, "x_max": cx, "T": cT, "v_end": cv, "sigma_f": csf,
        })

    def _rss(vals) -> float:
        arr = np.array([v for v in vals if np.isfinite(v)], dtype=float)
        return float(np.sqrt(np.sum(arr * arr))) if arr.size else float("nan")

    sigma_abs = {"x_max": _rss(contrib_x), "T": _rss(contrib_T), "v_end": _rss(contrib_v)}
    rel_sigma = {
        "x_max": sigma_abs["x_max"] / targets.x_max if targets.x_max else float("nan"),
        "T": sigma_abs["T"] / targets.T if targets.T else float("nan"),
        "v_end": sigma_abs["v_end"] / max(targets.v_end, 1e-9),
    }

    finite_rel = [v for v in rel_sigma.values() if np.isfinite(v)]
    R = float(np.sqrt(np.sum(np.square(finite_rel)))) if finite_rel else float("nan")

    sigma_f = _rss(contrib_sf)
    if np.isfinite(sigma_f) and sigma_f > 0:
        sigma_f_margin = (sigma_f_max - sigma_f_peak_nominal) / sigma_f
    else:
        sigma_f_margin = float("inf")

    return RobustnessReport(
        R=R,
        rel_sigma=rel_sigma,
        sigma_abs=sigma_abs,
        sigma_f_margin=sigma_f_margin,
        node_contrib=node_contrib,
        warnings=warnings,
    )
