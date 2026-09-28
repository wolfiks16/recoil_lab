"""Страницы обратного проектирования (rail «Оптимизация»).

Список исследований, форма запуска (в фоновом потоке), страница результата с
опросом статуса, отпочкование победителя в обычный CalculationRun, удаление.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import DesignStudyForm
from ..models import CalculationRun, DesignStudy
from ..services.design.persist import create_brakes_from_design
from ..services.design.runner import start_study
from ..services.dynamics import RecoilParams, simulate_recoil
from ..services.permissions import can_run_calc
from ..services.run_pipeline import persist_result_and_snapshot


def _can_view_study(user, study: DesignStudy) -> bool:
    if not user.is_authenticated:
        return False
    profile = getattr(user, "profile", None)
    if profile and (profile.is_admin or profile.is_analyst):
        return True
    return study.owner_id == user.id


def _visible_studies(user):
    if not user.is_authenticated:
        return DesignStudy.objects.none()
    qs = DesignStudy.objects.select_related("source_run", "spawned_run", "owner")
    profile = getattr(user, "profile", None)
    if profile and (profile.is_admin or profile.is_analyst):
        return qs
    return qs.filter(owner=user)


def optimize_list_view(request):
    studies = list(_visible_studies(request.user).order_by("-created_at")[:100])
    return render(request, "recoil_app/optimize_list.html", {
        "studies": studies,
        "can_create": can_run_calc(request.user),
    })


def optimize_new_view(request):
    if not can_run_calc(request.user):
        messages.warning(request, "Для запуска исследования войдите или зарегистрируйтесь.")
        return redirect(f"/login/?next={request.path}")

    if request.method == "POST":
        form = DesignStudyForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            study = DesignStudy.objects.create(
                name=cd["name"],
                source_run=cd["source_run"],
                owner=request.user,
                target_T=cd["target_T"],
                target_x_max=cd["target_x_max"],
                target_v_end=cd["target_v_end"],
                rel_tol=cd["rel_tol"],
                sigma_f_max=cd["sigma_f_max"],
                n_brakes=cd["n_brakes"],
                do_parametric=cd["do_parametric"],
                multistart=cd["multistart"],
                status=DesignStudy.STATUS_PENDING,
            )
            start_study(study.id)
            messages.success(request, "Исследование запущено — идёт подбор.")
            return redirect("optimize_detail", study_id=study.id)
    else:
        form = DesignStudyForm()

    return render(request, "recoil_app/optimize_form.html", {"form": form})


def optimize_detail_view(request, study_id):
    study = get_object_or_404(DesignStudy, pk=study_id)
    if not _can_view_study(request.user, study):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        return HttpResponseForbidden("Нет доступа к этому исследованию.")

    snap = study.result_snapshot or {}
    curve_html = ""
    pareto_html = ""
    if study.status == DesignStudy.STATUS_DONE:
        curve = (snap.get("stage1") or {}).get("curve") or {}
        vs, fs = curve.get("v_nodes") or [], curve.get("f_nodes") or []
        design = snap.get("design") or {}
        if vs and fs:
            from ..services.charting import make_brake_curve_fragment, make_design_fv_fragment
            if design.get("type") == "parametric" and design.get("brakes"):
                # Реальная F(v) подобранного тормоза (сумма квазистатики по N) — что
                # тормоз ДЕЙСТВИТЕЛЬНО делает, поверх идеала (цели синтеза).
                import numpy as np
                from ..services.magnetic import MagneticParams, magnetic_force_quasistatic
                v_max = float(vs[-1]) if vs else 18.0
                v_grid = list(np.linspace(0.0, v_max, 60))
                f_actual = [0.0] * len(v_grid)
                for pd in design["brakes"]:
                    try:
                        p = MagneticParams(**pd)
                        for i, v in enumerate(v_grid):
                            f_actual[i] += magnetic_force_quasistatic(float(v), p)
                    except Exception:  # noqa: BLE001
                        pass
                curve_html = make_design_fv_fragment(
                    ideal_v=vs, ideal_f=fs, actual_v=v_grid, actual_f=f_actual,
                    sigma_f_max=study.sigma_f_max,
                    title="Характеристика F(v): цель синтеза и реальный тормоз",
                )
            else:
                points = [{"velocity": v, "force": f} for v, f in zip(vs, fs)]
                curve_html = make_brake_curve_fragment(
                    points, title="Синтезированная F(v) — табличный тормоз (реализуема как есть)")

        # Парето-плоскость кандидатов мультистарта (если он был).
        s2 = snap.get("stage2") or {}
        cands = (s2.get("multistart") or {}).get("candidates") or s2.get("candidates") or []
        if len(cands) >= 2:
            from ..services.charting import make_pareto_fragment
            pareto_html = make_pareto_fragment(cands)

    return render(request, "recoil_app/optimize_detail.html", {
        "study": study,
        "snap": snap,
        "stage1": snap.get("stage1"),
        "stage2": snap.get("stage2"),
        "curve_html": curve_html,
        "pareto_html": pareto_html,
        "design_type": (snap.get("design") or {}).get("type"),
        "can_spawn": (study.status == DesignStudy.STATUS_DONE
                      and study.source_run_id is not None
                      and snap.get("design") is not None),
        "perm_can_delete": _can_view_study(request.user, study),
    })


def optimize_status_view(request, study_id):
    study = get_object_or_404(DesignStudy, pk=study_id)
    if not _can_view_study(request.user, study):
        return JsonResponse({"error": "forbidden"}, status=403)
    return JsonResponse({
        "status": study.status,
        "feasible": study.feasible,
        "best_R": study.best_R,
    })


@require_POST
def optimize_spawn_view(request, study_id):
    study = get_object_or_404(DesignStudy, pk=study_id)
    if not _can_view_study(request.user, study):
        return HttpResponseForbidden("Нет доступа.")

    if study.status != DesignStudy.STATUS_DONE:
        messages.error(request, "Исследование ещё не готово.")
        return redirect("optimize_detail", study_id=study.id)
    if study.spawned_run_id:
        messages.info(request, "Расчёт из этого дизайна уже создан.")
        return redirect("run_detail_v2", run_id=study.spawned_run_id)

    donor = study.source_run
    if donor is None or not donor.input_file:
        messages.error(request, "Донор удалён — нельзя воспроизвести привод.")
        return redirect("optimize_detail", study_id=study.id)
    design = (study.result_snapshot or {}).get("design")
    if not design:
        messages.error(request, "В результате нет реализуемого дизайна.")
        return redirect("optimize_detail", study_id=study.id)

    run_name = _unique_run_name(f"{study.name}-design")
    try:
        with transaction.atomic():
            run = CalculationRun.objects.create(
                name=run_name, mode=CalculationRun.MODE_RECOIL,
                mass=donor.mass, angle_deg=donor.angle_deg, v0=donor.v0, x0=donor.x0,
                t_max=donor.t_max, dt=donor.dt, owner=request.user,
            )
            donor.input_file.open("rb")
            try:
                content = donor.input_file.read()
            finally:
                donor.input_file.close()
            run.input_file.save(Path(donor.input_file.name).name, ContentFile(content), save=True)

            brake_objects, runtime = create_brakes_from_design(run, design)
            recoil = RecoilParams(mass=run.mass, angle_deg=run.angle_deg, v0=run.v0,
                                  x0=run.x0, t_max=run.t_max, dt=run.dt)
            result = simulate_recoil(run.input_file.path, recoil, runtime)
            persist_result_and_snapshot(run, brake_objects, result)

            study.spawned_run = run
            study.save(update_fields=["spawned_run"])
        messages.success(request, "Расчёт из дизайна создан.")
        return redirect("run_detail_v2", run_id=run.id)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Не удалось создать расчёт: {exc}")
        return redirect("optimize_detail", study_id=study.id)


@require_POST
def optimize_delete_view(request, study_id):
    study = get_object_or_404(DesignStudy, pk=study_id)
    if not _can_view_study(request.user, study):
        return HttpResponseForbidden("Нет доступа.")
    study.delete()
    messages.success(request, "Исследование удалено.")
    return redirect("optimize_list")


def _unique_run_name(base: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]", "-", base) or "design"
    name, i = base, 2
    while CalculationRun.objects.filter(name=name).exists():
        name = f"{base}-{i}"
        i += 1
    return name
