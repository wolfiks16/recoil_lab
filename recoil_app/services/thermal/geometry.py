"""Построение тепловой сети из явной геометрии.

Backend ожидает все размеры в SI и не делает fallback'ов «если 0 — взять
из brake params». Эту логику выполняет UI-слой через кнопку «подставить»
и при необходимости валидацию формы. Так пользователь всегда видит, какие
числа попадают в расчёт.

Здесь только два «автопостроителя сети»:
    build_nine_node_network(brakes, assembly) — стандартная 9-узловая сеть
    build_single_node_network(brakes, assembly) — одна теплоёмкость на тормоз
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .materials import (
    AIR_THERMAL_CONDUCTIVITY,
    MATERIALS,
    get_material,
)
from .network import (
    ThermalLink,
    ThermalNetwork,
    ThermalNode,
    ThermalSource,
)


# --- Geometry input dataclasses --------------------------------------------------------


@dataclass(slots=True)
class BrakeGeometry:
    """Геометрия одного тормоза. Все размеры — м, материалы — ключи MATERIALS."""

    brake_index: int
    display_name: str = ""
    bus_material: str = "aluminum"

    # Bus shell (тормозная шина)
    D_bus_outer: float = 0.0
    D_bus_inner: float = 0.0
    L_active: float = 0.0

    # Pole shoe (полюсный наконечник, сталь)
    D_pole_outer: float = 0.0
    D_pole_inner: float = 0.0
    L_pole: float = 0.0

    # Magnet block (NdFeB)
    D_magnet_outer: float = 0.0
    D_magnet_inner: float = 0.0
    L_magnet: float = 0.0

    # Толщина рабочего магнитного зазора (между шиной и полюсником)
    delta_gap_working: float = 1e-3

    # Контактный коэффициент полюсник↔магнит, Вт/(м²·К). По умолчанию 1000.
    h_contact_pole_magnet: float = 1000.0


@dataclass(slots=True)
class AssemblyGeometry:
    """Общая геометрия сборки и параметры окружения."""

    # Casing — обечайка (сталь)
    D_casing_outer: float = 0.0
    delta_casing: float = 0.0
    L_casing: float = 0.0

    # Non-magnetic rod — немагнитный шток
    D_nonmag_outer: float = 0.0
    D_nonmag_inner: float = 0.0
    L_nonmag: float = 0.0
    nonmag_rod_material: str = "stainless"

    # Inner steel rod — внутренний стальной шток
    D_rod_steel_outer: float = 0.0
    D_rod_steel_inner: float = 0.0
    L_rod_steel: float = 0.0

    # Сборочные воздушные зазоры
    delta_gap_casing_to_outer_bus: float = 1e-3
    delta_gap_inner_bus_to_rod: float = 1e-3

    # Контакт магнит↔шток
    h_contact_magnet_rod: float = 1000.0

    # Окружение
    h_ambient_outer: float = 10.0
    T_ambient_outer: float = 20.0
    h_ambient_rod_cavity: float = 4.0
    T_ambient_rod_cavity: float = 25.0


# --- Geometry helpers ------------------------------------------------------------------


def cylindrical_shell_volume(D_outer: float, D_inner: float, L: float) -> float:
    if D_outer <= D_inner or L <= 0:
        return 0.0
    return math.pi / 4.0 * (D_outer * D_outer - D_inner * D_inner) * L


def cylindrical_lateral_area(D: float, L: float) -> float:
    if D <= 0 or L <= 0:
        return 0.0
    return math.pi * D * L


def disc_area(D_outer: float, D_inner: float = 0.0) -> float:
    if D_outer <= 0:
        return 0.0
    return math.pi / 4.0 * (D_outer * D_outer - D_inner * D_inner)


def air_gap_h(delta_m: float) -> float:
    """h = λ_воздуха / δ для тонкого зазора."""
    if delta_m <= 0:
        return 0.0
    return AIR_THERMAL_CONDUCTIVITY / delta_m


# --- 9-node network --------------------------------------------------------------------


def build_nine_node_network(
    brakes: list[BrakeGeometry],
    assembly: AssemblyGeometry,
) -> ThermalNetwork:
    """Стандартная 9-узловая сеть для коаксиального двухтормозного узла.

    Топология: обечайка ↔ шина_внеш ↔ полюсник_внеш ↔ магниты_внеш ↔ шток_немагн
    ↔ магниты_внутр ↔ полюсник_внутр ↔ шина_внутр ↔ шток_сталь
    """
    if len(brakes) != 2:
        raise ValueError(
            f"9-узловая сеть требует ровно 2 тормоза (внешний и внутренний), "
            f"получено {len(brakes)}."
        )

    outer = brakes[0]
    inner = brakes[1]

    steel = MATERIALS["steel_10"]
    bus_outer_mat = get_material(outer.bus_material)
    bus_inner_mat = get_material(inner.bus_material)
    ndfeb = MATERIALS["ndfeb"]
    nonmag_mat = get_material(assembly.nonmag_rod_material)

    # --- массы узлов (SI) ---
    D_casing_inner = max(0.0, assembly.D_casing_outer - 2.0 * assembly.delta_casing)
    m_casing = cylindrical_shell_volume(
        assembly.D_casing_outer, D_casing_inner, assembly.L_casing
    ) * steel.rho

    m_bus_outer = cylindrical_shell_volume(
        outer.D_bus_outer, outer.D_bus_inner, outer.L_active
    ) * bus_outer_mat.rho

    m_pole_outer = cylindrical_shell_volume(
        outer.D_pole_outer, outer.D_pole_inner, outer.L_pole
    ) * steel.rho

    m_magnets_outer = cylindrical_shell_volume(
        outer.D_magnet_outer, outer.D_magnet_inner, outer.L_magnet
    ) * ndfeb.rho

    m_rod_nonmag = cylindrical_shell_volume(
        assembly.D_nonmag_outer, assembly.D_nonmag_inner, assembly.L_nonmag
    ) * nonmag_mat.rho

    m_magnets_inner = cylindrical_shell_volume(
        inner.D_magnet_outer, inner.D_magnet_inner, inner.L_magnet
    ) * ndfeb.rho

    m_pole_inner = cylindrical_shell_volume(
        inner.D_pole_outer, inner.D_pole_inner, inner.L_pole
    ) * steel.rho

    m_bus_inner = cylindrical_shell_volume(
        inner.D_bus_outer, inner.D_bus_inner, inner.L_active
    ) * bus_inner_mat.rho

    m_rod_steel = cylindrical_shell_volume(
        assembly.D_rod_steel_outer, assembly.D_rod_steel_inner, assembly.L_rod_steel
    ) * steel.rho

    # --- площади ---
    A_amb_casing = (
        cylindrical_lateral_area(assembly.D_casing_outer, assembly.L_casing)
        + 2.0 * disc_area(assembly.D_casing_outer)
    )
    A_amb_rod_inner = cylindrical_lateral_area(assembly.D_rod_steel_inner, assembly.L_rod_steel)

    # связи (площади контакта на меньшем диаметре или по зазору)
    A_casing_to_bus_outer = cylindrical_lateral_area(outer.D_bus_outer, outer.L_active)
    A_bus_outer_to_pole_outer = cylindrical_lateral_area(outer.D_bus_inner, outer.L_active)
    A_pole_outer_to_magnets_outer = cylindrical_lateral_area(outer.D_pole_inner, outer.L_pole)
    A_magnets_outer_to_rod_nonmag = cylindrical_lateral_area(outer.D_magnet_inner, outer.L_magnet)
    A_rod_nonmag_to_magnets_inner = cylindrical_lateral_area(inner.D_magnet_outer, inner.L_magnet)
    A_magnets_inner_to_pole_inner = cylindrical_lateral_area(inner.D_pole_outer, inner.L_pole)
    A_pole_inner_to_bus_inner = cylindrical_lateral_area(inner.D_pole_outer, inner.L_pole)
    A_bus_inner_to_rod_steel = cylindrical_lateral_area(inner.D_bus_inner, inner.L_active)

    # --- коэффициенты теплопередачи воздушных зазоров ---
    h_air_working_outer = air_gap_h(outer.delta_gap_working)
    h_air_working_inner = air_gap_h(inner.delta_gap_working)
    h_air_casing_bus = air_gap_h(assembly.delta_gap_casing_to_outer_bus)
    h_air_inner_bus_rod = air_gap_h(assembly.delta_gap_inner_bus_to_rod)

    T0 = assembly.T_ambient_outer

    nodes = [
        ThermalNode(
            name="casing",
            display_name="Обечайка",
            mass_kg=m_casing,
            cp_j_per_kgk=steel.cp,
            temp0_c=T0,
            h_ambient_w_per_m2k=assembly.h_ambient_outer,
            area_ambient_m2=A_amb_casing,
            ambient_c=assembly.T_ambient_outer,
            emissivity=steel.eps,
            area_radiation_m2=A_amb_casing,
            material_key=steel.key,
        ),
        ThermalNode(
            name="bus_outer",
            display_name=outer.display_name or "Шина внешняя",
            mass_kg=m_bus_outer,
            cp_j_per_kgk=bus_outer_mat.cp,
            temp0_c=T0,
            ambient_c=assembly.T_ambient_outer,
            material_key=bus_outer_mat.key,
        ),
        ThermalNode(
            name="pole_outer",
            display_name="Полюсник внешний",
            mass_kg=m_pole_outer,
            cp_j_per_kgk=steel.cp,
            temp0_c=T0,
            ambient_c=assembly.T_ambient_outer,
            material_key=steel.key,
        ),
        ThermalNode(
            name="magnets_outer",
            display_name="Магниты внешние",
            mass_kg=m_magnets_outer,
            cp_j_per_kgk=ndfeb.cp,
            temp0_c=T0,
            ambient_c=assembly.T_ambient_outer,
            material_key=ndfeb.key,
        ),
        ThermalNode(
            name="rod_nonmag",
            display_name="Шток немагнитный",
            mass_kg=m_rod_nonmag,
            cp_j_per_kgk=nonmag_mat.cp,
            temp0_c=T0,
            ambient_c=assembly.T_ambient_outer,
            material_key=nonmag_mat.key,
        ),
        ThermalNode(
            name="magnets_inner",
            display_name="Магниты внутренние",
            mass_kg=m_magnets_inner,
            cp_j_per_kgk=ndfeb.cp,
            temp0_c=T0,
            ambient_c=assembly.T_ambient_outer,
            material_key=ndfeb.key,
        ),
        ThermalNode(
            name="pole_inner",
            display_name="Полюсник внутренний",
            mass_kg=m_pole_inner,
            cp_j_per_kgk=steel.cp,
            temp0_c=T0,
            ambient_c=assembly.T_ambient_outer,
            material_key=steel.key,
        ),
        ThermalNode(
            name="bus_inner",
            display_name=inner.display_name or "Шина внутренняя",
            mass_kg=m_bus_inner,
            cp_j_per_kgk=bus_inner_mat.cp,
            temp0_c=T0,
            ambient_c=assembly.T_ambient_outer,
            material_key=bus_inner_mat.key,
        ),
        ThermalNode(
            name="rod_steel",
            display_name="Шток внутренний (сталь)",
            mass_kg=m_rod_steel,
            cp_j_per_kgk=steel.cp,
            temp0_c=T0,
            h_ambient_w_per_m2k=(
                assembly.h_ambient_rod_cavity if A_amb_rod_inner > 0 else 0.0
            ),
            area_ambient_m2=A_amb_rod_inner,
            ambient_c=assembly.T_ambient_rod_cavity,
            material_key=steel.key,
        ),
    ]

    links = [
        ThermalLink(
            node_a="casing", node_b="bus_outer",
            h_w_per_m2k=h_air_casing_bus, area_m2=A_casing_to_bus_outer,
            description="Сборочный зазор обечайка↔шина внеш.",
        ),
        ThermalLink(
            node_a="bus_outer", node_b="pole_outer",
            h_w_per_m2k=h_air_working_outer, area_m2=A_bus_outer_to_pole_outer,
            description="Рабочий магнитный зазор внеш.",
        ),
        ThermalLink(
            node_a="pole_outer", node_b="magnets_outer",
            h_w_per_m2k=outer.h_contact_pole_magnet, area_m2=A_pole_outer_to_magnets_outer,
            description="Контакт полюсник↔магниты внеш.",
        ),
        ThermalLink(
            node_a="magnets_outer", node_b="rod_nonmag",
            h_w_per_m2k=assembly.h_contact_magnet_rod, area_m2=A_magnets_outer_to_rod_nonmag,
            description="Контакт магниты внеш.↔шток немагн.",
        ),
        ThermalLink(
            node_a="rod_nonmag", node_b="magnets_inner",
            h_w_per_m2k=assembly.h_contact_magnet_rod, area_m2=A_rod_nonmag_to_magnets_inner,
            description="Контакт шток немагн.↔магниты внутр.",
        ),
        ThermalLink(
            node_a="magnets_inner", node_b="pole_inner",
            h_w_per_m2k=inner.h_contact_pole_magnet, area_m2=A_magnets_inner_to_pole_inner,
            description="Контакт магниты↔полюсник внутр.",
        ),
        ThermalLink(
            node_a="pole_inner", node_b="bus_inner",
            h_w_per_m2k=h_air_working_inner, area_m2=A_pole_inner_to_bus_inner,
            description="Рабочий магнитный зазор внутр.",
        ),
        ThermalLink(
            node_a="bus_inner", node_b="rod_steel",
            h_w_per_m2k=h_air_inner_bus_rod, area_m2=A_bus_inner_to_rod_steel,
            description="Сборочный зазор шина внутр.↔шток сталь",
        ),
    ]

    sources = [
        ThermalSource(brake_index=outer.brake_index, node_name="bus_outer", heat_fraction=1.0),
        ThermalSource(brake_index=inner.brake_index, node_name="bus_inner", heat_fraction=1.0),
    ]

    return ThermalNetwork(nodes=nodes, links=links, sources=sources)


# --- Single-node network ---------------------------------------------------------------


def build_single_node_network(
    brakes: list[BrakeGeometry],
    assembly: AssemblyGeometry,
) -> ThermalNetwork:
    """Упрощённая сеть: один узел-шина на каждый тормоз с конвекцией в воздух.

    Подходит для быстрых прикидок «на сколько шина нагреется». Связей нет —
    тепло аккумулируется в шине и уходит только в воздух.
    """
    if not brakes:
        raise ValueError("Нужен хотя бы один тормоз.")

    nodes: list[ThermalNode] = []
    sources: list[ThermalSource] = []

    for i, brake in enumerate(brakes):
        bus_mat = get_material(brake.bus_material)
        m = cylindrical_shell_volume(
            brake.D_bus_outer, brake.D_bus_inner, brake.L_active,
        ) * bus_mat.rho

        # Контакт с воздухом — лат. наружная поверхность + торцы.
        a_amb = (
            cylindrical_lateral_area(brake.D_bus_outer, brake.L_active)
            + 2.0 * disc_area(brake.D_bus_outer, brake.D_bus_inner)
        )

        node_name = f"bus_{brake.brake_index}"
        nodes.append(ThermalNode(
            name=node_name,
            display_name=brake.display_name or f"Шина тормоза #{brake.brake_index + 1}",
            mass_kg=m,
            cp_j_per_kgk=bus_mat.cp,
            temp0_c=assembly.T_ambient_outer,
            h_ambient_w_per_m2k=assembly.h_ambient_outer,
            area_ambient_m2=a_amb,
            ambient_c=assembly.T_ambient_outer,
            emissivity=bus_mat.eps,
            area_radiation_m2=a_amb,
            material_key=bus_mat.key,
        ))
        sources.append(ThermalSource(
            brake_index=brake.brake_index,
            node_name=node_name,
            heat_fraction=1.0,
        ))

    return ThermalNetwork(nodes=nodes, links=[], sources=sources)
