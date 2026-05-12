# Migration: добавляет PRESET_USER_SIMPLE в choices ThermalRun.network_preset.
# Создана вручную, чтобы не тянуть AlterField на id всех моделей (W042 — отдельная задача).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recoil_app', '0020_thermalrun'),
    ]

    operations = [
        migrations.AlterField(
            model_name='thermalrun',
            name='network_preset',
            field=models.CharField(
                choices=[
                    ('user_simple', 'Упрощённая (шина+магнитопровод, ручной ввод)'),
                    ('nine_node', '9-узловая сеть'),
                    ('single_node', 'Упрощённая (1 узел/тормоз)'),
                ],
                default='nine_node',
                max_length=16,
            ),
        ),
    ]
