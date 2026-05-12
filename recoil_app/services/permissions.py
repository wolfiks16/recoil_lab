"""Хелперы прав доступа.

Единая точка правды для решений «может ли пользователь X сделать Y».
Используется во views (для разрешений и фильтрации queryset) и в шаблонах
(через template-теги для условного показа кнопок).

Роли (определены в `UserProfile`):
    admin     — полный доступ ко всему, раздаёт роли.
    analyst   — видит все расчёты, удаляет только свои, копирует чужие;
                полный CRUD по каталогу.
    engineer  — видит и удаляет только свои расчёты; в каталоге может
                использовать любые, но создавать/редактировать только свои.

Гость (AnonymousUser) — может смотреть дашборд, каталог, форму создания
(там его перенаправят на login), но НЕ может видеть результат расчёта.
"""

from __future__ import annotations

from typing import Optional

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db.models import QuerySet

from ..models import BrakeCatalog, CalculationRun, UserProfile

UserOrAnon = AbstractBaseUser | AnonymousUser


# --- Чтение роли ----------------------------------------------------------------------


def user_role(user: UserOrAnon) -> Optional[str]:
    """Возвращает строку роли или None (гость / нет профиля)."""
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        profile: UserProfile = user.profile
    except UserProfile.DoesNotExist:
        return None
    return profile.role


def is_admin(user: UserOrAnon) -> bool:
    return user_role(user) == UserProfile.ROLE_ADMIN


def is_analyst(user: UserOrAnon) -> bool:
    return user_role(user) == UserProfile.ROLE_ANALYST


def is_engineer(user: UserOrAnon) -> bool:
    return user_role(user) == UserProfile.ROLE_ENGINEER


def is_admin_or_analyst(user: UserOrAnon) -> bool:
    return user_role(user) in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_ANALYST)


# --- CalculationRun -------------------------------------------------------------------


def can_run_calc(user: UserOrAnon) -> bool:
    """Может ли пользователь запустить новый расчёт (POST на /new/, AJAX и т.п.)."""
    return user_role(user) is not None


def can_view_run(user: UserOrAnon, run: CalculationRun) -> bool:
    """Может ли пользователь открыть страницу результата конкретного расчёта."""
    role = user_role(user)
    if role is None:
        return False                                        # гостя не пускаем
    if role in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_ANALYST):
        return True
    # engineer — только свой
    return run.owner_id is not None and run.owner_id == user.id


def can_delete_run(user: UserOrAnon, run: CalculationRun) -> bool:
    """Может ли удалить расчёт. Admin — любой, остальные — только свой."""
    role = user_role(user)
    if role is None:
        return False
    if role == UserProfile.ROLE_ADMIN:
        return True
    return run.owner_id is not None and run.owner_id == user.id


def can_duplicate_run(user: UserOrAnon, run: CalculationRun) -> bool:
    """Кнопка «Дублировать»: создаёт копию с собой как owner.
    Доступна всем, кому разрешено смотреть расчёт.
    """
    return can_view_run(user, run)


def runs_visible_to(user: UserOrAnon) -> QuerySet[CalculationRun]:
    """Queryset расчётов, видимых пользователю.

    admin/analyst    → все расчёты
    engineer         → только свои
    гость            → пустой queryset (но дашборд гость всё равно может открыть,
                       вызывающий код может смягчить: «гостям показывать nothing,
                       но не падать 403»).
    """
    role = user_role(user)
    base = CalculationRun.objects.all()
    if role in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_ANALYST):
        return base
    if role == UserProfile.ROLE_ENGINEER:
        return base.filter(owner_id=user.id)
    return base.none()


# --- BrakeCatalog ---------------------------------------------------------------------


def can_create_catalog(user: UserOrAnon) -> bool:
    """Создание записи каталога — доступно всем авторизованным."""
    return user_role(user) is not None


def can_edit_catalog(user: UserOrAnon, entry: BrakeCatalog) -> bool:
    """Редактирование записи каталога.
    admin/analyst — любую; engineer — только свою.
    """
    role = user_role(user)
    if role is None:
        return False
    if role in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_ANALYST):
        return True
    return entry.owner_id is not None and entry.owner_id == user.id


def can_delete_catalog(user: UserOrAnon, entry: BrakeCatalog) -> bool:
    """Удаление записи каталога — те же правила, что и редактирование."""
    return can_edit_catalog(user, entry)


def can_use_catalog(user: UserOrAnon, entry: BrakeCatalog) -> bool:  # noqa: ARG001
    """Использовать запись каталога в новом расчёте — все авторизованные."""
    return user_role(user) is not None


# --- Users management (только admin) --------------------------------------------------


def can_manage_users(user: UserOrAnon) -> bool:
    """Только admin может раздавать роли."""
    return is_admin(user)
