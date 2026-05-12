"""Сигналы приложения.

Задачи:
  1. После удаления `ThermalRun` — снести файлы и папку отчёта (Django каскад
     чистит запись в БД, но не FileField'ы).
  2. После создания `auth.User` — автоматически создать `UserProfile` с
     корректной ролью: суперпользователь → admin, остальные → engineer.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import ThermalRun, UserProfile


@receiver(post_delete, sender=ThermalRun)
def remove_thermal_run_artifacts(sender, instance: ThermalRun, **kwargs) -> None:
    file_fields = [
        "chart_temperatures",
        "chart_power_brakes",
        "chart_heat_brakes",
        "chart_cycle_envelope",
    ]
    for field_name in file_fields:
        field_file = getattr(instance, field_name, None)
        if field_file:
            try:
                field_file.delete(save=False)
            except (OSError, ValueError):
                pass

    folder = Path(settings.MEDIA_ROOT) / instance.report_folder
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


@receiver(post_save, sender=get_user_model())
def create_user_profile(sender, instance, created, **kwargs) -> None:
    """Создаёт `UserProfile` сразу после создания пользователя.

    Роль:
        is_superuser → admin (для первого админа через `createsuperuser`),
        иначе          → engineer (минимальные права).

    Идемпотентно: если профиль уже существует (например, переcоздан вручную или
    дёрнут через `get_or_create`), сигнал ничего не меняет — повышать роль может
    только админ через UI.
    """
    if not created:
        return
    role = UserProfile.ROLE_ADMIN if instance.is_superuser else UserProfile.ROLE_ENGINEER
    UserProfile.objects.get_or_create(user=instance, defaults={"role": role})
