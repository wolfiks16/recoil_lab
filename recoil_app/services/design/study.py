"""Оркестрация обратного проектирования: Stage 1 (синтез) → верификация → робастность.

Многофидельность: синтез гоняется на грубом dt (быстро), финальные метрики и
робастность — на точном dt (base_dt).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..dynamics import RecoilParams, simulate_recoil_core
from ..io_utils import load_recoil_characteristics
from .forward import Metrics, build_curve, evaluate
from .objective import within_limits
from .param_fit import ParamTolerances, ParametricResult, run_parametric_stage
from .multi_brake import MultiBrakeResult, run_multi_brake_stage
from .multistart import MultistartResult, run_multistart
from .robustness import RobustnessReport, score_robustness
from .synthesis import synthesize_curve
from .targets import DesignConstraints, DesignTargets, ToleranceModel


@dataclass(slots=True)
class DesignResult:
    feasible: bool
    v_nodes: list
    f_nodes: list
    achieved: Metrics
    targets: DesignTargets
    rel_error: dict
    robustness: RobustnessReport | None
    envelope: dict
    synth_loss: float
    sim: dict
    messages: list = field(default_factory=list)
    parametric: ParametricResult | None = None   # Stage 2, один тормоз
    multi: MultiBrakeResult | None = None         # Stage 2, N тормозов
    multistart_result: MultistartResult | None = None  # мультистарт + отбор по робастности


def _estimate_v_peak(drive, base) -> float:
    """max|v| при нулевом торможении — верхняя граница скорости для сетки узлов."""
    ext_force, spring_force, t_ext_max, x_range = drive
    brake = build_curve([0.0, 1.0e6], [0.0, 0.0])
    res = simulate_recoil_core(ext_force, spring_force, t_ext_max, x_range, base, [brake])
    return float(np.max(np.abs(res.v))) if len(res.v) else 0.0


def _rel_error(achieved: Metrics, targets: DesignTargets) -> dict:
    if not achieved.completed:
        return {"x_max": float("nan"), "T": float("nan"), "v_end": float("nan")}
    return {
        "x_max": (achieved.x_max - targets.x_max) / targets.x_max,
        "T": (achieved.T - targets.T) / targets.T,
        "v_end": (achieved.v_end - targets.v_end) / max(targets.v_end, 1e-9),
    }


def run_design_study(
    *,
    input_file_path: str,
    mass: float,
    angle_deg: float,
    v0: float,
    x0: float,
    base_dt: float,
    targets: DesignTargets,
    constraints: DesignConstraints,
    tol: ToleranceModel,
    seed: int = 0,
    fit_parametric: bool = False,
    param_tol_rel: float = 0.02,
    n_brakes: int = 1,
    weights=None,
    multistart: bool = False,
) -> DesignResult:
    drive = load_recoil_characteristics(input_file_path)
    t_ext_max = drive[2]

    f_max = constraints.sigma_f_max
    n_free = constraints.n_free_nodes

    # Горизонт: чуть больше целевого цикла (завершающийся прогон всё равно
    # обрывается на возврате x=0, длинный t_sim бьёт только по незавершающимся).
    t_sim = max(1.6 * targets.T, 1.3 * float(t_ext_max), 20.0 * base_dt)
    # Рабочий шаг: RK4 4-го порядка, ~1200 шагов на горизонт достаточно для
    # проектной точности (rel_tol ~5%); не мельче донорского. Синтез, верификация
    # и робастность — на нём. (2× быстрее прежних 2500 шагов при том же качестве.)
    work_dt = max(base_dt, t_sim / 1200.0)

    base = RecoilParams(mass=mass, angle_deg=angle_deg, v0=v0, x0=x0,
                        t_max=t_sim, dt=work_dt)

    # Сетка скоростей: 0 … 1.2·v_peak (оценка без торможения).
    v_peak = _estimate_v_peak(drive, base)
    v_max_node = 1.2 * max(v_peak, 1e-3)
    v_nodes = list(np.linspace(0.0, v_max_node, n_free + 1))

    # --- Stage 1: синтез ---
    f_nodes, synth_loss = synthesize_curve(drive, base, v_nodes, f_max, targets)

    # --- Верификация ---
    achieved = evaluate(drive, base, v_nodes, f_nodes)
    rel_error = _rel_error(achieved, targets)
    within_tol = within_limits(achieved, targets)

    # --- Envelope (диагностика достижимости): без торможения / макс. торможение ---
    envelope = {
        "no_brake": evaluate(drive, base, v_nodes, [0.0] * (n_free + 1)),
        "full_brake": evaluate(drive, base, v_nodes, [0.0] + [f_max] * n_free),
    }

    # --- Робастность (только если решение состоялось) ---
    robustness = None
    if achieved.completed:
        robustness = score_robustness(
            drive, base, v_nodes, f_nodes, tol, targets,
            sigma_f_max=f_max, sigma_f_peak_nominal=achieved.sigma_f_peak,
        )

    messages = _diagnose(within_tol, achieved, targets, rel_error, envelope)
    if robustness is not None:
        messages.extend(robustness.warnings)

    # --- Stage 2: подбор физических параметров под синтезированную кривую ---
    parametric = None
    multi = None
    multistart_result = None
    if fit_parametric and achieved.completed:
        p_tol = ParamTolerances.uniform(param_tol_rel)
        if multistart:
            multistart_result = run_multistart(
                drive, base, v_nodes, f_nodes, targets, constraints,
                n_brakes=n_brakes, param_tol=p_tol, seed=seed,
            )
        elif n_brakes <= 1:
            parametric = run_parametric_stage(
                drive, base, v_nodes, f_nodes, targets, constraints, param_tol=p_tol, seed=seed,
            )
        else:
            multi = run_multi_brake_stage(
                drive, base, v_nodes, f_nodes, targets, constraints,
                n_brakes=n_brakes, weights=weights, param_tol=p_tol, seed=seed,
            )

    return DesignResult(
        feasible=within_tol,
        v_nodes=list(v_nodes),
        f_nodes=list(f_nodes),
        achieved=achieved,
        targets=targets,
        rel_error=rel_error,
        robustness=robustness,
        envelope=envelope,
        synth_loss=synth_loss,
        sim={
            "t_sim": t_sim, "work_dt": work_dt,
            "v_peak": v_peak, "v_max_node": v_max_node, "sigma_f_max": f_max,
        },
        messages=messages,
        parametric=parametric,
        multi=multi,
        multistart_result=multistart_result,
    )


def _diagnose(within_tol, achieved: Metrics, targets: DesignTargets,
              rel_error: dict, envelope: dict) -> list:
    msgs: list[str] = []

    if not achieved.completed:
        msgs.append(
            "Синтез не нашёл характеристику, при которой накат доходит до x=0 за t_sim. "
            "Ослабьте пределы (T/v_end) или потолок ΣF."
        )
        return msgs

    if within_tol:
        msgs.append(
            f"Все пределы соблюдены; откат сведён к x_max = {achieved.x_max:.4g} м "
            f"(предел {targets.x_max:.4g} м). T={achieved.T:.4g} с и v_end={achieved.v_end:.4g} м/с "
            f"оставлены под пределами — это сохраняет робастность."
        )
        return msgs

    # Что превышает свой предел (положительный rel_error = сверх лимита).
    overs = {k: rel_error[k] for k in ("x_max", "T", "v_end")
             if rel_error.get(k) is not None and rel_error[k] > targets.rel_tol}
    if overs:
        worst = max(overs, key=overs.get)
        names = {"x_max": "откат x_max", "T": "время T", "v_end": "скорость наката v_end"}
        msgs.append(
            f"Предел «{names[worst]}» превышен на {overs[worst] * 100:+.1f}% — из-за конфликта "
            f"(меньше откат/скорость требуют больше торможения, а оно растит T). "
            f"Ослабьте самый тесный предел или ΣF_max."
        )

    fb = envelope["full_brake"]
    if fb.completed and targets.x_max < fb.x_max:
        msgs.append(
            f"Предел отката x_max={targets.x_max:.4g} м недостижим: даже при максимальном "
            f"торможении откат больше ({fb.x_max:.4g} м). Поднимите предел x_max или ΣF_max."
        )

    return msgs
