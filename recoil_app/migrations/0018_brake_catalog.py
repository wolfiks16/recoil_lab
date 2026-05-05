# Generated for slice 3a — Brake Catalog (CRUD foundation)
from django.db import migrations, models

import recoil_app.models


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0017_v2_energy_and_charts"),
    ]

    operations = [
        migrations.CreateModel(
            name="BrakeCatalog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "model_type",
                    models.CharField(
                        choices=[
                            ("parametric", "Параметрический"),
                            ("curve", "По графику F(v)"),
                        ],
                        default="parametric",
                        max_length=16,
                    ),
                ),
                ("gamma", models.FloatField(blank=True, help_text="Линейный коэффициент γ", null=True)),
                ("delta", models.FloatField(blank=True, help_text="Квадратичный коэффициент δ", null=True)),
                ("n", models.IntegerField(blank=True, help_text="Число секций", null=True)),
                (
                    "curve_file",
                    models.FileField(
                        blank=True,
                        help_text="CSV/XLSX с двумя колонками: v, F",
                        null=True,
                        upload_to=recoil_app.models.catalog_curve_upload_to,
                    ),
                ),
                ("xm", models.FloatField(blank=True, null=True)),
                ("ym", models.FloatField(blank=True, null=True)),
                ("dh1", models.FloatField(blank=True, null=True)),
                ("dh2", models.FloatField(blank=True, null=True)),
                ("dm", models.FloatField(blank=True, null=True)),
                ("mu", models.FloatField(blank=True, null=True)),
                ("bz", models.FloatField(blank=True, null=True)),
                ("lya", models.FloatField(blank=True, default=2.5, null=True)),
                ("wn0", models.FloatField(blank=True, default=1.0, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Тормоз в каталоге",
                "verbose_name_plural": "Каталог тормозов",
                "ordering": ["name"],
            },
        ),
    ]
