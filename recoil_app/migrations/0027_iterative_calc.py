import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import recoil_app.models


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0026_designstudy"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="calculationrun",
            name="is_iterative",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="IterativeCalc",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mode", models.CharField(choices=[("recoil", "Откат"), ("free_fall", "Свободное падение")], default="recoil", max_length=16)),
                ("input_file", models.FileField(blank=True, null=True, upload_to=recoil_app.models.iterative_upload_to)),
                ("mass", models.FloatField()),
                ("angle_deg", models.FloatField(default=70.0)),
                ("v0", models.FloatField(default=0.0)),
                ("x0", models.FloatField(default=0.0)),
                ("t_max", models.FloatField(default=0.15)),
                ("dt", models.FloatField(default=0.0001)),
                ("status", models.CharField(choices=[("active", "Идёт"), ("finished", "Завершён")], default="active", max_length=16)),
                ("version", models.PositiveIntegerField(default=0)),
                ("state", models.JSONField(blank=True, default=dict)),
                ("history_file", models.FileField(blank=True, null=True, upload_to=recoil_app.models.iterative_upload_to)),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="iterative_calcs", to=settings.AUTH_USER_MODEL)),
                ("source_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="recoil_app.calculationrun")),
                ("result_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="recoil_app.calculationrun")),
            ],
            options={
                "verbose_name": "Итерационный расчёт",
                "verbose_name_plural": "Итерационные расчёты",
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="BrakeStage",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stage", models.PositiveIntegerField()),
                ("config", models.JSONField(blank=True, default=list)),
                ("x_switch", models.FloatField(blank=True, null=True)),
                ("t_forward", models.FloatField(blank=True, null=True)),
                ("v_forward", models.FloatField(blank=True, null=True)),
                ("t_return", models.FloatField(blank=True, null=True)),
                ("v_return", models.FloatField(blank=True, null=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="brake_stages", to="recoil_app.calculationrun")),
            ],
            options={
                "verbose_name": "Этап тормозов",
                "verbose_name_plural": "Этапы тормозов",
                "ordering": ["run", "stage"],
                "unique_together": {("run", "stage")},
            },
        ),
    ]
