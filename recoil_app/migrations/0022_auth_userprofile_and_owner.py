# Auth-миграция: добавляет UserProfile (роль) и owner для CalculationRun/BrakeCatalog.
# Также назначает существующим записям владельца — первого суперпользователя.
# Если суперпользователя в системе нет (свежий стенд) — owner остаётся NULL,
# первый createsuperuser затем не подцепит легаси-данные; для прода реко-
# мендуется создавать суперпользователя ДО применения этой миграции.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_legacy_owner(apps, schema_editor):
    """Назначает owner = первый суперпользователь для всех существующих
    CalculationRun и BrakeCatalog. Идемпотентно: трогает только записи с owner=None."""
    User = apps.get_model(settings.AUTH_USER_MODEL.split(".")[0],
                         settings.AUTH_USER_MODEL.split(".")[1])
    superuser = User.objects.filter(is_superuser=True).order_by("id").first()
    if superuser is None:
        # Нет суперпользователя — оставляем owner=None. На проде это означает,
        # что данные останутся «бесхозными» до создания первого админа; admin
        # потом сможет их назначить вручную либо через django-shell.
        return
    CalculationRun = apps.get_model("recoil_app", "CalculationRun")
    BrakeCatalog = apps.get_model("recoil_app", "BrakeCatalog")
    CalculationRun.objects.filter(owner__isnull=True).update(owner=superuser)
    BrakeCatalog.objects.filter(owner__isnull=True).update(owner=superuser)


def noop_reverse(apps, schema_editor):
    # При откате назад owner становится NULL — данные не теряем, но связь стирается.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('recoil_app', '0021_thermalrun_user_simple_preset'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- UserProfile ---
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(
                    choices=[
                        ('admin', 'Администратор'),
                        ('analyst', 'Инженер-аналитик'),
                        ('engineer', 'Инженер'),
                    ],
                    default='engineer',
                    max_length=16,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='profile',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Профиль пользователя',
                'verbose_name_plural': 'Профили пользователей',
            },
        ),
        # --- CalculationRun.owner ---
        migrations.AddField(
            model_name='calculationrun',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='calculation_runs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # --- BrakeCatalog.owner ---
        migrations.AddField(
            model_name='brakecatalog',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='brake_catalog_entries',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # --- Data migration: назначить legacy-записи первому суперпользователю ---
        migrations.RunPython(assign_legacy_owner, reverse_code=noop_reverse),
    ]
