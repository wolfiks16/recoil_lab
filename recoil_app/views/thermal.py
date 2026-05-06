"""View'хи теплового модуля: список сценариев, создание, страница результата, удаление."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ThermalBrakeFormSet, ThermalRunForm
from ..models import CalculationRun, CalculationSnapshot, ThermalRun
from ..services.thermal import (
    AssemblyGeometry,
    BrakeGeometry,
    build_config_snapshot,
    build_nine_node_network,
    build_result_snapshot,
    build_single_node_network,
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


def thermal_list_view(request, run_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
    thermal_runs = list(run.thermal_runs.order_by("-created_at"))
    return render(request, "recoil_app/thermal_list.html", {
        "run": run,
        "thermal_runs": thermal_runs,
    })


def thermal_new_view(request, run_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
    brakes = list(run.brakes.order_by("index"))
    if not brakes:
        messages.error(request, "У расчёта нет тормозов — тепловой анализ невозможен.")
        return redirect("run_detail_v2", run_id=run.id)

    brake_meta = _brake_meta_list(run)

    if request.method == "POST":
        run_form = ThermalRunForm(request.POST, run=run)
        # Сначала прочитаем preset, чтобы передать в formset
        preset = request.POST.get("network_preset", ThermalRun.PRESET_NINE_NODE)
        brake_formset = ThermalBrakeFormSet(
            request.POST,
            prefix="thermal_brakes",
            network_preset=preset,
            brake_meta_list=brake_meta,
        )

        # Дополнительная проверка: для nine_node ровно 2 тормоза.
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

                    config_snap = build_config_snapshot(
                        network=network,
                        brake_geometries=brake_geos,
                        assembly=assembly,
                        repetitions=run_form.cleaned_data["repetitions"],
                        pause_s=run_form.cleaned_data["pause_s"],
                        network_preset=preset,
                    )
                    result_snap = build_result_snapshot(network=network, combined=combined)
                    summary = derive_run_summary(result_snap)

                    thermal_run = ThermalRun.objects.create(
                        run=run,
                        name=run_form.cleaned_data["name"],
                        network_preset=preset,
                        repetitions=run_form.cleaned_data["repetitions"],
                        pause_s=run_form.cleaned_data["pause_s"],
                        config_snapshot=config_snap,
                        result_snapshot=result_snap,
                        warnings_text="\n".join(combined.warnings),
                        max_temp_c=summary["max_temp_c"],
                        max_temp_node_name=summary["max_temp_node_name"] or "",
                        total_heat_j=summary["total_heat_j"],
                    )

                    # Графики
                    folder = Path(settings.MEDIA_ROOT) / thermal_run.report_folder
                    paths = save_thermal_charts(
                        combined, network, folder,
                        prefix=f"thermal_{thermal_run.id}",
                    )
                    rel_root = thermal_run.report_folder
                    for chart_key, abs_path in paths.items():
                        setattr(
                            thermal_run, chart_key,
                            f"{rel_root}/{Path(abs_path).name}",
                        )
                    thermal_run.save(update_fields=[
                        "chart_temperatures", "chart_power_brakes",
                        "chart_heat_brakes", "chart_cycle_envelope",
                    ])

                messages.success(request, "Тепловой сценарий рассчитан.")
                return redirect("thermal_detail", run_id=run.id, thermal_id=thermal_run.id)

            except ValueError as exc:
                run_form.add_error(None, str(exc))
    else:
        run_form = ThermalRunForm(run=run)
        # Стартовая раскладка formset: по одной форме на каждый тормоз расчёта.
        initial = [{} for _ in brakes]
        brake_formset = ThermalBrakeFormSet(
            initial=initial,
            prefix="thermal_brakes",
            network_preset=ThermalRun.PRESET_NINE_NODE,
            brake_meta_list=brake_meta,
        )

    return render(request, "recoil_app/thermal_form.html", {
        "run": run,
        "brakes": brakes,
        "form": run_form,
        "brake_formset": brake_formset,
        "brake_meta": brake_meta,
    })


def thermal_detail_view(request, run_id: int, thermal_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
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
    })


@require_POST
def thermal_delete_view(request, run_id: int, thermal_id: int):
    run = get_object_or_404(CalculationRun, pk=run_id)
    thermal_run = get_object_or_404(ThermalRun, pk=thermal_id, run=run)
    thermal_run.delete()  # post_delete сигнал чистит файлы и папку
    messages.success(request, "Тепловой сценарий удалён.")
    return redirect("thermal_list", run_id=run.id)
