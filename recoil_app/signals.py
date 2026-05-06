"""Сигналы приложения.

Сейчас единственная задача — удалять файлы и папку теплового сценария
после удаления `ThermalRun` (Django каскад чистит запись в БД, но не FileField'ы).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ThermalRun


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
