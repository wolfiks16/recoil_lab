"""Фоновое исполнение исследования дизайна.

Расчёт идёт 50–170 с — слишком долго для HTTP-запроса, поэтому запускается в
демон-потоке. Статус и результат пишутся в `DesignStudy`; страница опрашивает их
AJAX-ом. Поток закрывает свою DB-connection в finally (SQLite, per-thread).
"""

from __future__ import annotations

import threading
import traceback

from .persist import serialize_design, study_summary
from .space import ParamSpace
from .study import run_design_study
from .targets import DesignConstraints, DesignTargets, ToleranceModel


def start_study(study_id: int) -> None:
    """Запускает исследование в фоновом потоке (не блокирует запрос)."""
    thread = threading.Thread(target=_run, args=(study_id,), daemon=True)
    thread.start()


def study_inputs(study) -> dict:
    """Вход `run_design_study` из `DesignStudy` (кроме донора/привода).

    Старые исследования без `param_space` считаются с границами по умолчанию.
    """
    return {
        "targets": DesignTargets(T=study.target_T, x_max=study.target_x_max,
                                 v_end=study.target_v_end, rel_tol=study.rel_tol),
        "constraints": DesignConstraints(sigma_f_max=study.sigma_f_max, n_free_nodes=study.n_nodes,
                                         bus_length=study.bus_length),
        "tol": ToleranceModel.from_fraction(study.n_nodes, study.sigma_f_max, 0.02),
        "space": ParamSpace.from_dict(study.param_space),
        "fit_parametric": study.do_parametric,
        "param_tol_rel": study.param_tol_rel,
        "n_brakes": study.n_brakes,
        "multistart": study.multistart,
    }


def _run(study_id: int) -> None:
    from django.db import connection

    from ...models import DesignStudy

    try:
        study = DesignStudy.objects.get(pk=study_id)
        study.status = DesignStudy.STATUS_RUNNING
        study.save(update_fields=["status"])

        donor = study.source_run
        if donor is None or not donor.input_file:
            raise ValueError("Донор-расчёт удалён или без входного файла.")

        result = run_design_study(
            input_file_path=donor.input_file.path,
            mass=donor.mass, angle_deg=donor.angle_deg, v0=donor.v0, x0=donor.x0,
            base_dt=donor.dt,
            **study_inputs(study),
        )

        snapshot = serialize_design(result)
        study.result_snapshot = snapshot
        study.feasible, study.best_R = study_summary(snapshot)
        study.status = DesignStudy.STATUS_DONE
        study.save()

    except Exception as exc:  # noqa: BLE001
        try:
            study = DesignStudy.objects.get(pk=study_id)
            study.status = DesignStudy.STATUS_ERROR
            study.error_text = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[:2000]}"
            study.save(update_fields=["status", "error_text"])
        except Exception:  # noqa: BLE001
            pass
    finally:
        connection.close()
