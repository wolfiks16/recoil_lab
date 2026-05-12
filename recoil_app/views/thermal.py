"""View'хи теплового модуля: список сценариев, создание, страница результата, удаление."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import (
    ThermalBrakeFormSet,
    ThermalRunForm,
    ThermalUserSimpleBrakeFormSet,
    ThermalUserSimpleRunForm,
)
from ..models import CalculationRun, CalculationSnapshot, ThermalRun
from ..services.permissions import can_delete_run, can_run_calc, can_view_run
from ..services.thermal import (
    AssemblyGeometry,
    BrakeGeometry,
    UserSimpleAssemblyParams,
    UserSimpleBrakeParams,
    build_config_snapshot,
    build_nine_node_network,
    build_result_snapshot,
    build_single_node_network,
    build_user_simple_network,
    derive_run_summary,
    simulate_repeated_cycles,
)
from ..services.thermal.charting import save_thermal_charts


# --- helpers --------------------------------------------------------------------------


def _read_chart_fragment(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _brake_meta_list(run: CalculationRun) -> list[dict]:
    """Метаданные тормозов для prefill-кнопок: индекс, имя, MagneticParams (если parametric)."""
    meta: list[dict] = []
    for brake in run.brakes.order_by("index"):
        is_parametric = brake.model_type == "parametric"
        params = None
        if is_parametric:
            params = {
                "xm": brake.xm, "ym": brake.ym,
                "dh1": brake.dh1, "dh2": brake.dh2,
                "dm": brake.dm, "n": brake.n,
                "delta": brake.delta, "lya": brake.lya,
            }
        meta.append({
            "index": int(brake.index),
            "display_name": brake.display_name,
            "model_type": brake.model_type,
            "is_parametric": is_parametric,
            "params": params,
        })
    return meta


def _read_kinematics_from_snapshot(run: CalculationRun) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Берёт t/v/F_magnetic_each из CalculationSnapshot. ValueError, если данных нет."""
    try:
        snapshot = run.snapshot
    except CalculationSnapshot.DoesNotExist as exc:
        raise ValueError(
            "Для этого расчёта нет CalculationSnapshot — пересоздайте расчёт, чтобы появились "
            "временные ряды для теплового анализа."
        ) from exc

    rs = snapshot.result_snapshot or {}
    timeline = rs.get("timeline") or {}
    forces = rs.get("forces") or {}

    t = timeline.get("t") or []
    v = timeline.get("v") or []
    f_each = forces.get("magnetic_each") or []

    if not t or not v:
        raise ValueError("В снапшоте расчёта нет временных рядов t/v.")
    if not f_each:
        raise ValueError("В снапшоте нет f_magnetic_each — тепловой расчёт невозможен.")

    t_arr = np.asarray(t, dtype=float)
    v_arr = np.asarray(v, dtype=float)
    f_arr = np.asarray(f_each, dtype=float)

    if f_arr.ndim != 2:
        raise ValueError("Некорректная форма массива f_magnetic_each в снапшоте.")
    if len(t_arr) != f_arr.shape[0]:
        raise ValueError(
            f"Размеры массивов не совпадают: len(t)={len(t_arr)}, f_each.shape={f_arr.shape}."
        )

    return t_arr, v_arr, f_arr


def _build_brake_geometries(brake_formset: ThermalBrakeFormSet, brake_indices: list[int]) -> list[BrakeGeometry]:
    """Из formset → list[BrakeGeometry]. brake_indices — реальные индексы тормозов из CalculationRun."""
    geos: list[BrakeGeometry] = []
    for i, form in enumerate(brake_formset.forms):
        cd = form.cleaned_data
        idx = brake_indices[i] if i < len(brake_indices) else i
        geos.append(BrakeGeometry(
            brake_index=idx,
            display_name=form._brake_meta.get("display_name", "") if hasattr(form, "_brake_meta") else "",
            bus_material=cd.get("bus_material") or "aluminum",
            D_bus_outer=float(cd.get("D_bus_outer") or 0.0),
            D_bus_inner=float(cd.get("D_bus_inner") or 0.0),
            L_active=float(cd.get("L_active") or 0.0),
            D_pole_outer=float(cd.get("D_pole_outer") or 0.0),
            D_pole_inner=float(cd.get("D_pole_inner") or 0.0),
            L_pole=float(cd.get("L_pole") or 0.0),
            D_magnet_outer=float(cd.get("D_magnet_outer") or 0.0),
            D_magnet_inner=float(cd.get("D_magnet_inner") or 0.0),
            L_magnet=float(cd.get("L_magnet") or 0.0),
            delta_gap_working=float(cd.get("delta_gap_working") or 1e-3),
            h_contact_pole_magnet=float(cd.get("h_contact_pole_magnet") or 1000.0),
        ))
    return geos


def _build_user_simple_brakes(
    brake_formset: ThermalUserSimpleBrakeFormSet,
    brake_indices: list[int],
    brake_meta: list[dict],
) -> list[UserSimpleBrakeParams]:
    """Из formset → list[UserSimpleBrakeParams].

    ВАЖНО: `brake_index` в `UserSimpleBrakeParams` — это 0-based column-index
    в forces.magnetic_each, а НЕ значение поля MagneticBrakeConfig.index в БД.
    Колонки f_each идут в порядке formset (== порядок brakes.order_by('index')),
    так что column-index = порядковый номер формы.
    """
    result: list[UserSimpleBrakeParams] = []
    for i, form in enumerate(brake_formset.forms):
        cd = form.cleaned_data
        db_idx = brake_indices[i] if i < len(brake_indices) else i + 1
        display = (
            brake_meta[i].get("display_name")
            if i < len(brake_meta)
            else f"Контур #{i + 1}"
        )
        result.append(UserSimpleBrakeParams(
            brake_index=i,                       # column-index, 0-based
            display_name=display or f"Контур #{i + 1} (БД idx={db_idx})",
            bus_mass_kg=float(cd.get("bus_mass_kg") or 0.0),
            bus_cp_j_per_kgk=float(cd.get("bus_cp") or 0.0),
            yoke_mass_kg=float(cd.get("yoke_mass_kg") or 0.0),
            yoke_cp_j_per_kgk=float(cd.get("yoke_cp") or 0.0),
            g_pole_w_per_k=float(cd.get("g_pole") or 0.0),
            g_air_inner_w_per_k=float(cd.get("g_air_inner") or 0.0),
            g_air_outer_w_per_k=float(cd.get("g_air_outer") or 0.0),
            temp0_c=float(cd.get("temp0_c") if cd.get("temp0_c") is not None else 20.0),
        ))
    return result


def _build_user_simple_assembly(run_form: ThermalUserSimpleRunForm) -> UserSimpleAssemblyParams:
    cd = run_form.cleaned_data
    return UserSimpleAssemblyParams(
        T_ambient=float(cd.get("T_ambient") if cd.get("T_ambient") is not None else 20.0),
    )


def _build_assembly(run_form: ThermalRunForm) -> AssemblyGeometry:
    cd = run_form.cleaned_data
    return AssemblyGeometry(
        D_casing_outer=float(cd.get("D_casing_outer") or 0.0),
        delta_casing=float(cd.get("delta_casing") or 0.0),
        L_casing=float(cd.get("L_casing") or 0.0),
        D_nonmag_outer=float(cd.get("D_nonmag_outer") or 0.0),
        D_nonmag_inner=float(cd.get("D_nonmag_inner") or 0.0),
        L_nonmag=float(cd.get("L_nonmag") or 0.0),
        nonmag_rod_material=cd.get("nonmag_rod_material") or "stainless",
        D_rod_steel_outer=float(cd.get("D_rod_steel_outer") or 0.0),
        D_rod_steel_inner=float(cd.get("D_rod_steel_inner") or 0.0),
        L_rod_steel=float(cd.get("L_rod_steel") or 0.0),
        delta_gap_casing_to_outer_bus=float(cd.get("delta_gap_casing_to_outer_bus") or 1e-3),
        delta_gap_inner_bus_to_rod=float(cd.get("delta_gap_inner_bus_to_rod") or 1e-3),
        h_contact_magnet_rod=float(cd.get("h_contact_magnet_rod") or 1000.0),
        h_ambient_outer=float(cd.get("h_ambient_outer") or 10.0),
        T_ambient_outer=float(cd.get("T_ambient_outer") if cd.get("T_ambient_outer") is not None else 20.0),
        h_ambient_rod_cavity=float(cd.get("h_ambient_rod_cavity") or 0.0),
        T_ambient_rod_cavity=float(cd.get("T_ambient_rod_cavity") if cd.get("T_ambient_rod_cavity") is not None else 25.0),
    )


# --- views ----------------------------------------------------------------------------


def _enforce_run_view_access(request, run):
    """Возвращает None, если можно смотреть; иначе HttpResponse (redirect/403)."""
    if can_view_run(request.user, run):
        return None
    if not request.user.is_authenticated:
        messages.warning(
            request,
            "Тепловые сценарии доступны только зарегистрированным пользователям.",
        )
        return redirect(f"/login/?next={request.path}")
    from django.http import HttpResponseForbidden
    return HttpResponseForbidden(
        "У вас нет прав на этот расчёт — тепловые сценарии тоже недоступны."
    )


def thermal_list_view(request, run_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
    forbid = _enforce_run_view_access(request, run)
    if forbid is not None:
        return forbid
    thermal_runs = list(run.thermal_runs.order_by("-created_at"))
    return render(request, "recoil_app/thermal_list.html", {
        "run": run,
        "thermal_runs": thermal_runs,
    })


def _save_and_redirect(
    *,
    request,
    run,
    name: str,
    preset: str,
    repetitions: int,
    pause_s: float,
    network,
    brake_params,
    assembly,
    combined,
) -> str:
    """Общая часть для всех preset'ов: сохранить ThermalRun, нарисовать графики, редиректить."""
    config_snap = build_config_snapshot(
        network=network,
        brake_geometries=brake_params,
        assembly=assembly,
        repetitions=repetitions,
        pause_s=pause_s,
        network_preset=preset,
    )
    result_snap = build_result_snapshot(network=network, combined=combined)
    summary = derive_run_summary(result_snap)

    thermal_run = ThermalRun.objects.create(
        run=run,
        name=name,
        network_preset=preset,
        repetitions=repetitions,
        pause_s=pause_s,
        config_snapshot=config_snap,
        result_snapshot=result_snap,
        warnings_text="\n".join(combined.warnings),
        max_temp_c=summary["max_temp_c"],
        max_temp_node_name=summary["max_temp_node_name"] or "",
        total_heat_j=summary["total_heat_j"],
    )

    folder = Path(settings.MEDIA_ROOT) / thermal_run.report_folder
    paths = save_thermal_charts(
        combined, network, folder, prefix=f"thermal_{thermal_run.id}",
    )
    rel_root = thermal_run.report_folder
    for chart_key, abs_path in paths.items():
        setattr(thermal_run, chart_key, f"{rel_root}/{Path(abs_path).name}")
    thermal_run.save(update_fields=[
        "chart_temperatures", "chart_power_brakes",
        "chart_heat_brakes", "chart_cycle_envelope",
    ])

    messages.success(request, "Тепловой сценарий рассчитан.")
    return thermal_run


def thermal_new_view(request, run_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
    forbid = _enforce_run_view_access(request, run)
    if forbid is not None:
        return forbid
    # Запуск нового теплового сценария — авторизация уже проверена через can_view_run,
    # но дополнительно убедимся: гость не должен сюда попадать через POST с form-данными.
    if not can_run_calc(request.user):
        messages.warning(request, "Для запуска расчёта войдите или зарегистрируйтесь.")
        return redirect(f"/login/?next={request.path}")
    brakes = list(run.brakes.order_by("index"))
    if not brakes:
        messages.error(request, "У расчёта нет тормозов — тепловой анализ невозможен.")
        return redirect("run_detail_v2", run_id=run.id)

    brake_meta = _brake_meta_list(run)

    # Preset выбирается верхним переключателем на форме. По умолчанию — упрощённая
    # ручная постановка: она проще и покрывает 95% случаев первичной оценки нагрева.
    valid_presets = {value for value, _ in ThermalRun.PRESET_CHOICES}
    if request.method == "POST":
        preset = request.POST.get("network_preset", ThermalRun.PRESET_USER_SIMPLE)
    else:
        preset = request.GET.get("preset", ThermalRun.PRESET_USER_SIMPLE)
    if preset not in valid_presets:
        preset = ThermalRun.PRESET_USER_SIMPLE

    # ===== Ветка PRESET_USER_SIMPLE — упрощённая постановка =====
    if preset == ThermalRun.PRESET_USER_SIMPLE:
        if request.method == "POST":
            run_form = ThermalUserSimpleRunForm(request.POST, run=run)
            brake_formset = ThermalUserSimpleBrakeFormSet(
                request.POST,
                prefix="thermal_brakes",
                brake_meta_list=brake_meta,
            )

            if run_form.is_valid() and brake_formset.is_valid():
                try:
                    with transaction.atomic():
                        t_arr, v_arr, f_arr = _read_kinematics_from_snapshot(run)
                        if f_arr.shape[1] != len(brakes):
                            raise ValueError(
                                f"Число столбцов f_magnetic_each ({f_arr.shape[1]}) "
                                f"не совпадает с числом тормозов расчёта ({len(brakes)})."
                            )

                        brake_params = _build_user_simple_brakes(
                            brake_formset,
                            brake_indices=[b.index for b in brakes],
                            brake_meta=brake_meta,
                        )
                        assembly = _build_user_simple_assembly(run_form)
                        network = build_user_simple_network(brake_params, assembly)

                        combined = simulate_repeated_cycles(
                            base_t=t_arr, base_v=v_arr, base_f_each=f_arr,
                            network=network,
                            repetitions=run_form.cleaned_data["repetitions"],
                            pause_s=run_form.cleaned_data["pause_s"],
                        )

                        thermal_run = _save_and_redirect(
                            request=request, run=run,
                            name=run_form.cleaned_data["name"],
                            preset=preset,
                            repetitions=run_form.cleaned_data["repetitions"],
                            pause_s=run_form.cleaned_data["pause_s"],
                            network=network,
                            brake_params=brake_params,
                            assembly=assembly,
                            combined=combined,
                        )
                    return redirect("thermal_detail", run_id=run.id, thermal_id=thermal_run.id)
                except ValueError as exc:
                    run_form.add_error(None, str(exc))
        else:
            run_form = ThermalUserSimpleRunForm(run=run)
            initial = [{} for _ in brakes]
            brake_formset = ThermalUserSimpleBrakeFormSet(
                initial=initial,
                prefix="thermal_brakes",
                brake_meta_list=brake_meta,
            )

        return render(request, "recoil_app/thermal_form.html", {
            "run": run,
            "brakes": brakes,
            "form": run_form,
            "brake_formset": brake_formset,
            "brake_meta": brake_meta,
            "preset": preset,
            "preset_choices": ThermalRun.PRESET_CHOICES,
            "is_user_simple": True,
        })

    # ===== Ветка PRESET_NINE_NODE / PRESET_SINGLE_NODE (старый код) =====
    if request.method == "POST":
        run_form = ThermalRunForm(request.POST, run=run)
        brake_formset = ThermalBrakeFormSet(
            request.POST,
            prefix="thermal_brakes",
            network_preset=preset,
            brake_meta_list=brake_meta,
        )

        if preset == ThermalRun.PRESET_NINE_NODE and len(brakes) != 2:
            run_form.add_error(
                "network_preset",
                f"9-узловая сеть требует ровно 2 тормоза, у расчёта их {len(brakes)}.",
            )

        if run_form.is_valid() and brake_formset.is_valid() and not run_form.errors:
            try:
                with transaction.atomic():
                    t_arr, v_arr, f_arr = _read_kinematics_from_snapshot(run)
                    if f_arr.shape[1] != len(brakes):
                        raise ValueError(
                            f"Число столбцов f_magnetic_each ({f_arr.shape[1]}) "
                            f"не совпадает с числом тормозов расчёта ({len(brakes)})."
                        )

                    brake_geos = _build_brake_geometries(
                        brake_formset, brake_indices=[b.index for b in brakes],
                    )
                    assembly = _build_assembly(run_form)

                    if preset == ThermalRun.PRESET_NINE_NODE:
                        network = build_nine_node_network(brake_geos, assembly)
                    else:
                        network = build_single_node_network(brake_geos, assembly)

                    combined = simulate_repeated_cycles(
                        base_t=t_arr, base_v=v_arr, base_f_each=f_arr,
                        network=network,
                        repetitions=run_form.cleaned_data["repetitions"],
                        pause_s=run_form.cleaned_data["pause_s"],
                    )

                    thermal_run = _save_and_redirect(
                        request=request, run=run,
                        name=run_form.cleaned_data["name"],
                        preset=preset,
                        repetitions=run_form.cleaned_data["repetitions"],
                        pause_s=run_form.cleaned_data["pause_s"],
                        network=network,
                        brake_params=brake_geos,
                        assembly=assembly,
                        combined=combined,
                    )
                return redirect("thermal_detail", run_id=run.id, thermal_id=thermal_run.id)

            except ValueError as exc:
                run_form.add_error(None, str(exc))
    else:
        run_form = ThermalRunForm(run=run)
        initial = [{} for _ in brakes]
        brake_formset = ThermalBrakeFormSet(
            initial=initial,
            prefix="thermal_brakes",
            network_preset=preset,
            brake_meta_list=brake_meta,
        )

    return render(request, "recoil_app/thermal_form.html", {
        "run": run,
        "brakes": brakes,
        "form": run_form,
        "brake_formset": brake_formset,
        "brake_meta": brake_meta,
        "preset": preset,
        "preset_choices": ThermalRun.PRESET_CHOICES,
        "is_user_simple": False,
    })


def thermal_detail_view(request, run_id: int, thermal_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
    forbid = _enforce_run_view_access(request, run)
    if forbid is not None:
        return forbid
    thermal_run = get_object_or_404(ThermalRun, pk=thermal_id, run=run)

    chart_fields = [
        "chart_temperatures", "chart_power_brakes",
        "chart_heat_brakes", "chart_cycle_envelope",
    ]
    chart_html: dict[str, str] = {}
    chart_errors: list[str] = []
    for fname in chart_fields:
        ff = getattr(thermal_run, fname, None)
        if ff and getattr(ff, "name", ""):
            try:
                chart_html[fname] = _read_chart_fragment(ff.path)
            except (FileNotFoundError, OSError) as exc:
                chart_errors.append(f"{fname}: {exc}")

    config = thermal_run.config_snapshot or {}
    result = thermal_run.result_snapshot or {}

    network_dict = (config.get("network") or {})
    nodes_table = network_dict.get("nodes") or []
    links_table = network_dict.get("links") or []

    # Для каждого узла добавим производную «G в воздух» = h_amb·A_amb,
    # чтобы шаблон не делал арифметику. Это особенно важно для user_simple,
    # где h_amb и A_amb — технические артефакты (h=G, A=1).
    for nd in nodes_table:
        h = float(nd.get("h_ambient_w_per_m2k") or 0.0)
        a = float(nd.get("area_ambient_m2") or 0.0)
        nd["g_to_air_w_per_k"] = h * a

    # Для preset=user_simple показываем переработанные таблицы:
    # — узлы: без A_amb/h_amb/A_rad (это технические артефакты кодирования G через h·A=G·1),
    #   вместо них G в воздух [Вт/К] = h·A;
    # — связи: только итоговое G [Вт/К] без h и A;
    # — отдельная секция «Контуры» с исходными параметрами пользователя (m, cp, G_pole, G_air_*).
    is_user_simple = thermal_run.network_preset == ThermalRun.PRESET_USER_SIMPLE

    user_simple_brakes: list[dict] = []
    if is_user_simple:
        for bg in (config.get("geometry") or {}).get("brakes") or []:
            user_simple_brakes.append({
                "brake_index": bg.get("brake_index"),
                "display_name": bg.get("display_name") or "",
                "bus_mass_kg": bg.get("bus_mass_kg"),
                "bus_cp_j_per_kgk": bg.get("bus_cp_j_per_kgk"),
                "yoke_mass_kg": bg.get("yoke_mass_kg"),
                "yoke_cp_j_per_kgk": bg.get("yoke_cp_j_per_kgk"),
                "g_pole_w_per_k": bg.get("g_pole_w_per_k"),
                "g_air_inner_w_per_k": bg.get("g_air_inner_w_per_k"),
                "g_air_outer_w_per_k": bg.get("g_air_outer_w_per_k"),
                "temp0_c": bg.get("temp0_c"),
            })

    return render(request, "recoil_app/thermal_detail.html", {
        "run": run,
        "thermal_run": thermal_run,
        "chart_html": chart_html,
        "chart_errors": chart_errors,
        "config": config,
        "result": result,
        "nodes_table": nodes_table,
        "links_table": links_table,
        "peaks": (result.get("peaks") or {}),
        "cycles": (result.get("cycles") or []),
        "is_user_simple": is_user_simple,
        "user_simple_brakes": user_simple_brakes,
        "T_ambient_user_simple": (config.get("geometry") or {}).get("assembly", {}).get("T_ambient"),
    })


@require_POST
def thermal_delete_view(request, run_id: int, thermal_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
    # Удалить тепловой сценарий может только тот, кто может удалить родительский расчёт.
    if not can_delete_run(request.user, run):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden(
            "Удалить тепловой сценарий может только владелец расчёта или администратор."
        )
    thermal_run = get_object_or_404(ThermalRun, pk=thermal_id, run=run)
    thermal_run.delete()
    messages.success(request, "Тепловой сценарий удалён.")
    return redirect("thermal_list", run_id=run.id)
