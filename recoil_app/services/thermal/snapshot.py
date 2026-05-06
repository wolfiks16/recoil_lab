"""Упаковка config / result теплового сценария в JSON-сериализуемый вид.

Используется для записи в `ThermalRun.config_snapshot` и `ThermalRun.result_snapshot`.

Гранулярность:
    config_snapshot:
        cycle:    repetitions, pause_s
        network:  узлы, связи, источники (полная сеть с массами/площадями)
        geometry: исходные геометрические inputs (BrakeGeometry/AssemblyGeometry)
                  — нужны, чтобы потом можно было пересоздать сеть и проверить.
        materials: ключи материалов узлов

    result_snapshot:
        timeline: t, temp_nodes (decimated), cycle_index, segment
        powers:   power_nodes (decimated), power_brakes (decimated)
        heats:    heat_brakes — суммарно накопленное по тормозам в финале
        peaks:    pin'ы пиковых T и времена их достижения
        cycles:   таблица сводок CycleSummary
        warnings: список предупреждений
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np

from .cycles import CombinedCycleResult, CycleSummary
from .decimation import (
    DEFAULT_TARGET_HZ,
    decimate_per_segment,
    merge_indices,
    pick_peak_indices,
)
from .geometry import AssemblyGeometry, BrakeGeometry
from .network import ThermalNetwork


# --- config snapshot -------------------------------------------------------------------


def network_to_dict(network: ThermalNetwork) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "name": nd.name,
                "display_name": nd.display_name,
                "mass_kg": float(nd.mass_kg),
                "cp_j_per_kgk": float(nd.cp_j_per_kgk),
                "capacitance_j_per_k": float(nd.capacitance_j_per_k),
                "temp0_c": float(nd.temp0_c),
                "h_ambient_w_per_m2k": float(nd.h_ambient_w_per_m2k),
                "area_ambient_m2": float(nd.area_ambient_m2),
                "ambient_c": float(nd.ambient_c),
                "emissivity": float(nd.emissivity),
                "area_radiation_m2": float(nd.area_radiation_m2),
                "material_key": nd.material_key,
            }
            for nd in network.nodes
        ],
        "links": [
            {
                "node_a": lk.node_a,
                "node_b": lk.node_b,
                "h_w_per_m2k": float(lk.h_w_per_m2k),
                "area_m2": float(lk.area_m2),
                "conductance_w_per_k": float(lk.conductance_w_per_k),
                "description": lk.description,
            }
            for lk in network.links
        ],
        "sources": [
            {
                "brake_index": int(s.brake_index),
                "node_name": s.node_name,
                "heat_fraction": float(s.heat_fraction),
            }
            for s in network.sources
        ],
        "warnings": list(network.warnings),
    }


def build_config_snapshot(
    *,
    network: ThermalNetwork,
    brake_geometries: list[BrakeGeometry],
    assembly: AssemblyGeometry,
    repetitions: int,
    pause_s: float,
    network_preset: str,
) -> dict[str, Any]:
    return {
        "preset": network_preset,
        "cycle": {
            "repetitions": int(repetitions),
            "pause_s": float(pause_s),
        },
        "geometry": {
            "brakes": [asdict(bg) for bg in brake_geometries],
            "assembly": asdict(assembly),
        },
        "network": network_to_dict(network),
    }


# --- result snapshot -------------------------------------------------------------------


def _summary_to_dict(s: CycleSummary) -> dict[str, Any]:
    return {
        "cycle_number": s.cycle_number,
        "start_temp_c": dict(s.start_temp_c),
        "end_temp_after_braking_c": dict(s.end_temp_after_braking_c),
        "max_temp_in_cycle_c": dict(s.max_temp_in_cycle_c),
        "end_temp_after_pause_c": dict(s.end_temp_after_pause_c),
        "added_heat_by_brake_j": {str(k): float(v) for k, v in s.added_heat_by_brake_j.items()},
    }


def _peaks_block(network: ThermalNetwork, combined: CombinedCycleResult) -> dict[str, Any]:
    peaks: dict[str, dict[str, float]] = {}
    n_nodes = network.n_nodes()
    for k in range(n_nodes):
        i_peak = int(np.argmax(combined.temp_nodes[:, k]))
        peaks[network.nodes[k].name] = {
            "display_name": network.nodes[k].display_name,
            "t_peak_s": float(combined.t[i_peak]),
            "temp_peak_c": float(combined.temp_nodes[i_peak, k]),
            "cycle_at_peak": int(combined.cycle_index[i_peak]),
            "segment_at_peak": str(combined.segment[i_peak]),
        }
    return peaks


def build_result_snapshot(
    *,
    network: ThermalNetwork,
    combined: CombinedCycleResult,
    target_hz: float = DEFAULT_TARGET_HZ,
) -> dict[str, Any]:
    """Превращает результат расчёта в JSON-сериализуемый dict."""
    n = len(combined.t)
    if n == 0:
        return {
            "timeline": {"t": [], "temp_nodes": [], "power_nodes": [],
                         "power_brakes": [], "cycle_index": [], "segment": []},
            "node_names": [nd.name for nd in network.nodes],
            "node_display_names": [nd.display_name for nd in network.nodes],
            "heats_total_j": [],
            "peaks": {},
            "cycles": [],
            "warnings": list(combined.warnings),
        }

    # Decimation: per segment + сохраняем все пики температур.
    seg_idx = decimate_per_segment(
        t=combined.t,
        segment=combined.segment,
        cycle_index=combined.cycle_index,
        target_hz=target_hz,
    )
    peak_idx = pick_peak_indices(combined.temp_nodes)
    keep = merge_indices(seg_idx, peak_idx)

    return {
        "timeline": {
            "t":             combined.t[keep].tolist(),
            "temp_nodes":    combined.temp_nodes[keep, :].tolist(),
            "power_nodes":   combined.power_nodes[keep, :].tolist(),
            "power_brakes":  combined.power_brakes[keep, :].tolist(),
            "cycle_index":   combined.cycle_index[keep].tolist(),
            "segment":       [str(s) for s in combined.segment[keep]],
            "n_full":        int(n),
            "n_decimated":   int(len(keep)),
            "target_hz":     float(target_hz),
        },
        "node_names":         [nd.name for nd in network.nodes],
        "node_display_names": [nd.display_name for nd in network.nodes],
        "heats_total_j": [
            float(combined.heat_brakes[-1, b]) if combined.heat_brakes.shape[1] > b else 0.0
            for b in range(combined.heat_brakes.shape[1])
        ],
        "peaks": _peaks_block(network, combined),
        "cycles": [_summary_to_dict(s) for s in combined.summaries],
        "warnings": list(combined.warnings),
    }


def derive_run_summary(result_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Денормализованные поля для ThermalRun.{max_temp_c, max_temp_node_name, total_heat_j}."""
    peaks = result_snapshot.get("peaks") or {}
    if peaks:
        worst_key, worst_data = max(peaks.items(), key=lambda kv: kv[1]["temp_peak_c"])
        max_t = float(worst_data["temp_peak_c"])
        max_t_name = str(worst_data.get("display_name") or worst_key)
    else:
        max_t = None
        max_t_name = ""
    total_heat = sum(result_snapshot.get("heats_total_j") or [])
    return {
        "max_temp_c": max_t,
        "max_temp_node_name": max_t_name,
        "total_heat_j": float(total_heat) if peaks else None,
    }
