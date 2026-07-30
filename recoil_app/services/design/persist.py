"""Сериализация результата обратного проектирования в JSON-снапшот и сборка
тормозов дизайна для «отпочкования» в обычный CalculationRun.

serialize_design(DesignResult) → чистый dict (для хранения в DesignStudy и рендера).
create_brakes_from_design(run, design) → создаёт MagneticBrakeConfig(и) + runtime-модели.
"""

from __future__ import annotations

import math

_PARAM_FIELDS = ("gamma", "delta", "xm", "ym", "dh1", "dh2", "dm", "n", "mu", "bz", "lya", "wn0")


def _f(x):
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if math.isfinite(xf) else None


def _metrics(m) -> dict | None:
    if m is None:
        return None
    return {"x_max": _f(m.x_max), "T": _f(m.T), "v_end": _f(m.v_end),
            "sigma_f_peak": _f(m.sigma_f_peak), "completed": bool(m.completed)}


def _params(p) -> dict:
    out = {}
    for k in _PARAM_FIELDS:
        v = getattr(p, k)
        out[k] = int(v) if k == "n" else _f(v)
    return out


def _dominant(per_param) -> str | None:
    finite = [x for x in (per_param or []) if x.get("T") == x.get("T")]
    if not finite:
        return None
    d = max(finite, key=lambda x: abs(x["T"]))
    return f"тормоз {d['brake']} · {d['param']}" if "brake" in d else d["param"]


def _robustness_dict(rob) -> dict | None:
    """Из dict-робастности (param_fit/multi_brake)."""
    if not rob:
        return None
    return {
        "R": _f(rob.get("R")),
        "rel_sigma": {k: _f(v) for k, v in (rob.get("rel_sigma") or {}).items()},
        "sigma_f_margin": _f(rob.get("sigma_f_margin")),
        "dominant": _dominant(rob.get("per_param")),
    }


def _robustness_report(rr) -> dict | None:
    """Из RobustnessReport (Stage 1)."""
    if rr is None:
        return None
    return {"R": _f(rr.R), "rel_sigma": {k: _f(v) for k, v in rr.rel_sigma.items()},
            "sigma_f_margin": _f(rr.sigma_f_margin), "dominant": None}


def _stage2_common(r) -> dict:
    return {
        "achieved": _metrics(r.achieved),
        "rel_error": {k: _f(v) for k, v in r.rel_error.items()},
        "within_tol": bool(r.within_tol),
        "sigma_f_peak": _f(r.sigma_f_peak),
        "sigma_f_ok": bool(r.sigma_f_ok),
        "robustness": _robustness_dict(r.robustness),
        "messages": list(r.messages),
    }


def _stage2_single(pr) -> dict:
    d = _stage2_common(pr)
    d.update(kind="single", n_brakes=1, params=[_params(pr.params_final)],
             curve_rmse=_f(pr.fit.curve_rmse), curve_rmse_final=_f(pr.curve_rmse_final),
             n=int(pr.fit.n), weights=[1.0])
    return d


def _stage2_multi(mr) -> dict:
    d = _stage2_common(mr)
    d.update(kind="multi", n_brakes=int(mr.n_brakes),
             weights=[_f(w) for w in mr.weights],
             params=[_params(b) for b in mr.brakes],
             per_brake_curve_rmse=[_f(x) for x in mr.per_brake_curve_rmse])
    return d


def _cand_dict(c, ms) -> dict:
    rob = getattr(c.result, "robustness", None) or {}
    ach = getattr(c.result, "achieved", None)
    is_best = bool(getattr(ms, "best_coarse", None) is not None and c is ms.best_coarse)
    # Позиция (x_max, R) — грубая (единая шкала Парето), но достижимость победителя
    # берём точную (он доведён и проверен на рабочем dt), иначе таблица/цвет врут.
    feasible = bool(ms.best.feasible) if (is_best and ms.best is not None) else bool(c.feasible)
    return {
        "label": c.label, "feasible": feasible,
        "R": _f(c.R), "overshoot": _f(c.max_abs_err), "fidelity": c.fidelity,
        "x_max": _f(ach.x_max) if ach is not None else None,   # цель — минимизируем
        "sigma_f_margin": _f(rob.get("sigma_f_margin")),
        "is_best": is_best,
    }


def _stage2_of(result) -> dict | None:
    ms = result.multistart_result
    if ms and ms.best is not None:
        best = ms.best.result
        s2 = _stage2_multi(best) if hasattr(best, "brakes") else _stage2_single(best)
        s2["multistart"] = {
            "best_label": ms.best.label,
            "n_evaluated": ms.n_evaluated,
            "n_feasible": ms.n_feasible,
            "candidates": [_cand_dict(c, ms) for c in ms.candidates],
        }
        return s2
    if ms and ms.best is None:
        # мультистарт был, но ни один кандидат не попал в цель
        return {"kind": "multistart_failed",
                "candidates": [_cand_dict(c, ms) for c in ms.candidates],
                "params": None, "within_tol": False, "sigma_f_ok": False,
                "robustness": None, "achieved": None, "rel_error": {}, "messages": []}
    if result.multi:
        return _stage2_multi(result.multi)
    if result.parametric:
        return _stage2_single(result.parametric)
    return None


def serialize_design(result) -> dict:
    stage1 = {
        "feasible": bool(result.feasible),
        "achieved": _metrics(result.achieved),
        "rel_error": {k: _f(v) for k, v in result.rel_error.items()},
        "curve": {"v_nodes": [_f(v) for v in result.v_nodes],
                  "f_nodes": [_f(v) for v in result.f_nodes]},
        "envelope": {kk: _metrics(vv) for kk, vv in result.envelope.items()},
        "messages": list(result.messages),
        "synth_loss": _f(result.synth_loss),
        "sim": {k: _f(v) for k, v in result.sim.items()},
        "robustness": _robustness_report(result.robustness),
    }
    s2 = _stage2_of(result)

    # Реализуемый (buildable) дизайн: параметрические тормоза, иначе — синтез-кривая.
    if s2 and s2.get("params"):
        design = {"type": "parametric", "brakes": s2["params"]}
    else:
        design = {"type": "curve", "curve": stage1["curve"]}

    return {"stage1": stage1, "stage2": s2, "design": design}


def create_brakes_from_design(run, design: dict):
    """Создаёт MagneticBrakeConfig(и) дизайна для отпочкованного расчёта.

    Возвращает (brake_objects, runtime_brakes) как в run_pipeline.
    """
    from ...models import BrakeForcePoint, MagneticBrakeConfig
    from ..magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams

    brake_objects, runtime = [], []

    if design.get("type") == "parametric":
        for i, pd in enumerate(design["brakes"], start=1):
            obj = MagneticBrakeConfig.objects.create(
                run=run, index=i, model_type=MagneticBrakeConfig.MODEL_TYPE_PARAMETRIC,
                name=f"design-{i}", **pd,
            )
            brake_objects.append(obj)
            runtime.append(MagneticParams(**pd))
    else:
        v_nodes = design["curve"]["v_nodes"]
        f_nodes = design["curve"]["f_nodes"]
        obj = MagneticBrakeConfig.objects.create(
            run=run, index=1, model_type=MagneticBrakeConfig.MODEL_TYPE_CURVE, name="design-curve",
        )
        BrakeForcePoint.objects.bulk_create([
            BrakeForcePoint(brake=obj, order=j + 1, velocity=float(v), force=max(0.0, float(f)))
            for j, (v, f) in enumerate(zip(v_nodes, f_nodes))
        ])
        brake_objects.append(obj)
        runtime.append(CurveBrakeParams(points=tuple(
            ForceCurvePoint(velocity=float(v), force=max(0.0, float(f)))
            for v, f in zip(v_nodes, f_nodes)
        )))

    return brake_objects, runtime
