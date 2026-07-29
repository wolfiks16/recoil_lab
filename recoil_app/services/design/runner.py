"""Фоновое исполнение исследования дизайна.

Расчёт идёт 50–170 с — слишком долго для HTTP-запроса, поэтому запускается в
демон-потоке. Статус и результат пишутся в `DesignStudy`; страница опрашивает их
AJAX-ом. Поток закрывает свою DB-connection в finally (SQLite, per-thread).
"""

from __future__ import annotations

import threading
import traceback

from .persist import serialize_design
from .study import run_design_study
from .targets import DesignConstraints, DesignTargets, ToleranceModel


def start_study(study_id: int) -> None:
    """Запускает исследование в фоновом потоке (не блокирует запрос)."""
    thread = threading.Thread(target=_run, args=(study_id,), daemon=True)
    thread.start()


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

        targets = DesignTargets(T=study.target_T, x_max=study.target_x_max,
                                v_end=study.target_v_end, rel_tol=study.rel_tol)
        constraints = DesignConstraints(sigma_f_max=study.sigma_f_max, n_free_nodes=study.n_nodes)
        tol = ToleranceModel.from_fraction(study.n_nodes, study.sigma_f_max, 0.02)

        result = run_design_study(
            input_file_path=donor.input_file.path,
            mass=donor.mass, angle_deg=donor.angle_deg, v0=donor.v0, x0=donor.x0,
            base_dt=donor.dt,
            targets=targets, constraints=constraints, tol=tol,
            fit_parametric=study.do_parametric, param_tol_rel=study.param_tol_rel,
            n_brakes=study.n_brakes, multistart=study.multistart,
        )

        snapshot = serialize_design(result)
        study.result_snapshot = snapshot

        s2 = snapshot.get("stage2")
        s1 = snapshot["stage1"]
        if s2 and s2.get("kind") != "multistart_failed":
            study.feasible = bool(s2.get("within_tol") and s2.get("sigma_f_ok"))
            study.best_R = (s2.get("robustness") or {}).get("R")
        else:
            study.feasible = bool(s1["feasible"])
            study.best_R = (s1.get("robustness") or {}).get("R")

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
