"""Справочник материалов: плотность ρ, удельная теплоёмкость cp, степень черноты ε.

Используется при автопостроении тепловой сети — масса узла = ρ·V, теплоёмкость
C = m·cp, излучение Q_rad = ε·σ·A·(T⁴ − T_amb⁴). Степень черноты пользователю
не показывается — проект использует разумные дефолты по материалу. Если в будущем
понадобится дать тонкую настройку — переопределяем через отдельное поле формы.

Все значения SI: ρ [кг/м³], cp [Дж/(кг·К)], ε [безразм. 0–1].
Источники: справочники по материалам, типовые величины для индустриального применения
(окисленная/слегка корродированная поверхность, не свежеотполированная).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Material:
    key: str
    label: str
    rho: float          # плотность, кг/м³
    cp: float           # удельная теплоёмкость, Дж/(кг·К)
    eps: float          # степень черноты, безразм.


MATERIALS: dict[str, Material] = {
    # Обечайка, полюсники, внутренний шток — типовая углеродистая сталь.
    "steel_10": Material(
        key="steel_10",
        label="Сталь 10",
        rho=7850.0,
        cp=460.0,
        eps=0.85,           # окисленная поверхность
    ),
    # Шины — алюминий или медь. Пользователь выбирает per-brake.
    "aluminum": Material(
        key="aluminum",
        label="Алюминий",
        rho=2700.0,
        cp=900.0,
        eps=0.20,           # окисленный/анодированный (полированный 0.05)
    ),
    "copper": Material(
        key="copper",
        label="Медь",
        rho=8960.0,
        cp=385.0,
        eps=0.30,           # окисленная (полированная 0.05)
    ),
    # Магниты NdFeB.
    "ndfeb": Material(
        key="ndfeb",
        label="Магниты NdFeB",
        rho=7500.0,
        cp=440.0,
        eps=0.85,           # обычно покрыты Ni — поверхность темная, но мы консервативно
    ),
    # Немагнитный шток — выбор материала.
    "stainless": Material(
        key="stainless",
        label="Нержавейка 12Х18Н10Т",
        rho=7900.0,
        cp=500.0,
        eps=0.40,
    ),
    "duralumin": Material(
        key="duralumin",
        label="Сплав Д16",
        rho=2780.0,
        cp=880.0,
        eps=0.20,
    ),
    "brass": Material(
        key="brass",
        label="Латунь",
        rho=8500.0,
        cp=380.0,
        eps=0.30,
    ),
}


# Постоянная Стефана-Больцмана, Вт/(м²·К⁴).
STEFAN_BOLTZMANN = 5.670374419e-8

# Теплопроводность воздуха при ~20 °C, Вт/(м·К). Используется для перевода
# толщины воздушного зазора в коэффициент теплопередачи: h = λ_air / δ.
AIR_THERMAL_CONDUCTIVITY = 0.026


# Для удобства — выбор материала по типу узла.
BUS_MATERIAL_CHOICES = ("aluminum", "copper")
NONMAG_ROD_MATERIAL_CHOICES = ("stainless", "duralumin", "brass")


def get_material(key: str) -> Material:
    if key not in MATERIALS:
        known = ", ".join(sorted(MATERIALS.keys()))
        raise KeyError(f"Неизвестный материал '{key}'. Доступны: {known}.")
    return MATERIALS[key]


def material_choices_for_form(keys: tuple[str, ...]) -> list[tuple[str, str]]:
    """Готовые choices для Django ChoiceField: [(key, label), ...]."""
    return [(k, MATERIALS[k].label) for k in keys]
