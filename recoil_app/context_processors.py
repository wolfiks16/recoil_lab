"""Контекст каркаса страницы (base_v2.html): навигация и фоновые задачи.

Раньше топбар и рейл собирал shell.js из data-атрибутов (мигание при загрузке,
иконки без подписей). Теперь боковая навигация рендерится сервером; активный
раздел определяется по имени URL — шаблонам не нужно ничего объявлять.
"""

from __future__ import annotations

from django.urls import reverse

from .services.background_tasks import running_tasks_for

# Разделы навигации: ключ → (подпись, имя URL корня раздела).
NAV_SECTIONS: dict[str, tuple[str, str]] = {
    "dashboard": ("Рабочий стол", "dashboard"),
    "new": ("Новый расчёт", "index"),
    "results": ("Все расчёты", "results"),
    "iterative": ("Пошаговые сессии", "iterative_list"),
    "compare": ("Сравнение", "compare"),
    "optimize": ("Подбор тормоза", "optimize_list"),
    "catalog": ("Каталог тормозов", "catalog_list"),
    "users": ("Пользователи", "users_list"),
    "profile": ("Профиль", "profile"),
}

# Имя URL → раздел навигации.
URL_SECTION: dict[str, str] = {
    "dashboard": "dashboard",
    "index": "new",
    "free_fall_new": "new",
    "iterative_new": "new",
    "results": "results",
    "run_detail_v2": "results",
    "delete_run": "results",
    "thermal_list": "results",
    "thermal_new": "results",
    "thermal_detail": "results",
    "iterative_list": "iterative",
    "iterative_detail": "iterative",
    "compare": "compare",
    "optimize_list": "optimize",
    "optimize_new": "optimize",
    "optimize_detail": "optimize",
    "catalog_list": "catalog",
    "catalog_new": "catalog",
    "catalog_detail": "catalog",
    "catalog_edit": "catalog",
    "users_list": "users",
    "profile": "profile",
}

# Группы бокового меню (ключи разделов). «Новый расчёт» — отдельная кнопка над группами.
NAV_GROUPS: list[tuple[str, list[str]]] = [
    ("Расчёты", ["dashboard", "results", "iterative"]),
    ("Анализ", ["compare", "optimize"]),
    ("Справочник", ["catalog"]),
]


def shell(request) -> dict:
    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match else None
    active = URL_SECTION.get(url_name or "", "")

    groups = []
    for title, keys in NAV_GROUPS:
        items = []
        for key in keys:
            label, url_name_root = NAV_SECTIONS[key]
            items.append({"key": key, "label": label, "url": reverse(url_name_root)})
        groups.append({"title": title, "items": items})

    section = None
    if active:
        label, url_name_root = NAV_SECTIONS[active]
        section = {
            "key": active,
            "label": label,
            "url": reverse(url_name_root),
            # На корневой странице раздела крошка — просто его название, без ссылки на себя.
            "is_root": url_name == url_name_root,
        }

    user = getattr(request, "user", None)
    tasks = running_tasks_for(user) if user is not None else []

    return {
        "nav_active": active,
        "nav_groups": groups,
        "nav_section": section,
        "background_tasks": tasks,
    }
