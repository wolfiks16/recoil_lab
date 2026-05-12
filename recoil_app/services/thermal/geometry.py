"""Построение тепловой сети из явной геометрии.

Backend ожидает все размеры в SI и не делает fallback'ов «если 0 — взять
из brake params». Эту логику выполняет UI-слой через кнопку «подставить»
и при необходимости валидацию формы. Так пользователь всегда видит, какие
числа попадают в расчёт.

Здесь три «автопостроителя сети»:
    build_nine_node_network(brakes, assembly)   — стандартная 9-узловая сеть
    build_single_node_network(brakes, assembly) — одна теплоёмкость на тормоз
    build_user_simple_network(brakes, assembly) — объединённый узел шина+магнитопровод
                                                  с двумя теплоотдачами в воздух
                                                  (используется в простой форме)
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


# --- User-simple network (ручной ввод параметров) -------------------------------------


@dataclass(slots=True)
class UserSimpleBrakeParams:
    """Параметры одного контура в упрощённой постановке (ручной ввод).

    Топология: ДВА узла на контур — шина и магнитопровод. Источник Q_in идёт
    только в шину (там наводятся вихревые токи). Магнитопровод плотно прижат
    к шине: связь G_pole. Воздух с внутренней стороны касается шины (G_air_in),
    с внешней — магнитопровода (G_air_out).

    ОДУ:
        m_ш·cp_ш·dT_ш/dt   = Q_in − G_air_in·(T_ш − T_air) − G_pole·(T_ш − T_маг)
        m_маг·cp_маг·dT_маг/dt =       G_pole·(T_ш − T_маг) − G_air_out·(T_маг − T_air)

    brake_index ОБЯЗАТЕЛЬНО соответствует колонке в forces.magnetic_each
    (0-based порядковый номер). Это column-index, а не значение поля
    MagneticBrakeConfig.index в БД.
    """

    brake_index: int           # 0-based column index в f_magnetic_each
    display_name: str = ""

    # Шина — здесь и происходит тепловыделение (источник Q подключается сюда).
    bus_mass_kg: float = 0.0
    bus_cp_j_per_kgk: float = 0.0

    # Магнитопровод — плотный контакт с шиной через G_pole.
    yoke_mass_kg: float = 0.0
    yoke_cp_j_per_kgk: float = 0.0

    # G шина↔магнитопровод (плотный контакт, обычно 1000…3000 Вт/К).
    g_pole_w_per_k: float = 2000.0

    # Теплопередача в воздух: внутрь — от шины, наружу — от магнитопровода.
    g_air_inner_w_per_k: float = 0.0
    g_air_outer_w_per_k: float = 0.0

    # Начальная температура контура (для обоих узлов одинаковая).
    temp0_c: float = 20.0


@dataclass(slots=True)
class UserSimpleAssemblyParams:
    """Общие параметры для упрощённой постановки."""

    T_ambient: float = 20.0


def build_user_simple_network(
    brakes: list[UserSimpleBrakeParams],
    assembly: UserSimpleAssemblyParams,
) -> ThermalNetwork:
    """Упрощённая сеть: 2 узла на контур (шина и магнитопровод) + связь G_pole.

    На контур:
        узел bus_<i>:  m_ш·cp_ш,  T0; стоки в воздух h_amb = G_air_in,  A=1
        узел yoke_<i>: m_маг·cp_маг, T0; стоки в воздух h_amb = G_air_out, A=1
        связь bus_<i> ↔ yoke_<i> через G_pole (плотный контакт)
        источник Q_in (вихревые токи) → ТОЛЬКО bus_<i> (heat_fraction=1)

    `brake_index` в источнике — это 0-based column-index в forces.magnetic_each.
    ThermalLink хранит связь как h·A, поэтому G_pole кодируется как h=G_pole, A=1.
    """
    if not brakes:
        raise ValueError("Нужен хотя бы один контур.")

    nodes: list[ThermalNode] = []
    links: list[ThermalLink] = []
    sources: list[ThermalSource] = []

    for brake in brakes:
        m_bus = max(brake.bus_mass_kg, 0.0)
        cp_bus = max(brake.bus_cp_j_per_kgk, 0.0)
        m_yoke = max(brake.yoke_mass_kg, 0.0)
        cp_yoke = max(brake.yoke_cp_j_per_kgk, 0.0)

        if m_bus <= 0.0 or cp_bus <= 0.0:
            raise ValueError(
                f"Контур #{brake.brake_index + 1}: масса и cp шины должны быть положительны."
            )
        if m_yoke <= 0.0 or cp_yoke <= 0.0:
            raise ValueError(
                f"Контур #{brake.brake_index + 1}: масса и cp магнитопровода должны быть положительны."
            )

        bus_name = f"bus_{brake.brake_index}"
        yoke_name = f"yoke_{brake.brake_index}"
        suffix = f"#{brake.brake_index + 1}"
        brake_label = (brake.display_name or "").strip()
        bus_display = f"Шина ({brake_label}) {suffix}" if brake_label else f"Шина {suffix}"
        yoke_display = f"Магнитопровод ({brake_label}) {suffix}" if brake_label else f"Магнитопровод {suffix}"

        # Узел «шина» — источник тепла. Стоки в воздух через G_air_in.
        g_in = max(brake.g_air_inner_w_per_k, 0.0)
        nodes.append(ThermalNode(
            name=bus_name,
            display_name=bus_display,
            mass_kg=m_bus,
            cp_j_per_kgk=cp_bus,
            temp0_c=brake.temp0_c,
            h_ambient_w_per_m2k=g_in,
            area_ambient_m2=1.0 if g_in > 0.0 else 0.0,
            ambient_c=assembly.T_ambient,
            emissivity=0.0,
            area_radiation_m2=0.0,
            material_key="user_simple_bus",
        ))

        # Узел «магнитопровод». Стоки в воздух через G_air_out.
        g_out = max(brake.g_air_outer_w_per_k, 0.0)
        nodes.append(ThermalNode(
            name=yoke_name,
            display_name=yoke_display,
            mass_kg=m_yoke,
            cp_j_per_kgk=cp_yoke,
            temp0_c=brake.temp0_c,
            h_ambient_w_per_m2k=g_out,
            area_ambient_m2=1.0 if g_out > 0.0 else 0.0,
            ambient_c=assembly.T_ambient,
            emissivity=0.0,
            area_radiation_m2=0.0,
            material_key="user_simple_yoke",
        ))

        # Связь шина ↔ магнитопровод (плотный контакт через G_pole).
        g_pole = max(brake.g_pole_w_per_k, 0.0)
        links.append(ThermalLink(
            node_a=bus_name,
            node_b=yoke_name,
            h_w_per_m2k=g_pole,
            area_m2=1.0 if g_pole > 0.0 else 0.0,
            description=f"Контакт шина↔магнитопровод {suffix}",
        ))

        # Источник: вихревые токи греют ТОЛЬКО шину.
        sources.append(ThermalSource(
            brake_index=brake.brake_index,   # column-index в f_magnetic_each
            node_name=bus_name,
            heat_fraction=1.0,
        ))

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
