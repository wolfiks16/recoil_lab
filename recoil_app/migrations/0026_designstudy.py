import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0025_calculationrun_free_fall_mode"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DesignStudy",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("target_T", models.FloatField(help_text="Целевое время цикла, с")),
                ("target_x_max", models.FloatField(help_text="Целевой откат, м")),
                ("target_v_end", models.FloatField(help_text="Целевая |скорость| при x=0, м/с")),
                ("rel_tol", models.FloatField(default=0.05)),
                ("sigma_f_max", models.FloatField(help_text="Потолок суммарного усилия, Н")),
                ("n_nodes", models.PositiveIntegerField(default=4)),
                ("n_brakes", models.PositiveIntegerField(default=1)),
                ("param_tol_rel", models.FloatField(default=0.02)),
                ("do_parametric", models.BooleanField(default=True, help_text="Подбирать физ. параметры (Stage 2)")),
                ("multistart", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("pending", "В очереди"), ("running", "Считается"), ("done", "Готово"), ("error", "Ошибка")], default="pending", max_length=16)),
                ("error_text", models.TextField(blank=True, default="")),
                ("result_snapshot", models.JSONField(blank=True, default=dict)),
                ("feasible", models.BooleanField(blank=True, null=True)),
                ("best_R", models.FloatField(blank=True, null=True)),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="design_studies", to=settings.AUTH_USER_MODEL)),
                ("source_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="design_studies", to="recoil_app.calculationrun")),
                ("spawned_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="recoil_app.calculationrun")),
            ],
            options={
                "verbose_name": "Исследование дизайна",
                "verbose_name_plural": "Исследования дизайна",
                "ordering": ["-created_at"],
            },
        ),
    ]
