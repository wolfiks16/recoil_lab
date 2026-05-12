# Backfill UserProfile для уже существующих пользователей.
# Сигнал post_save на User создаёт профиль только для НОВЫХ пользователей;
# те, кто был зарегистрирован ДО введения auth-системы, остались без профиля.
# Эта миграция создаёт для них профиль: superuser → admin, остальные → engineer.

from django.conf import settings
from django.db import migrations


def backfill_profiles(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    UserProfile = apps.get_model("recoil_app", "UserProfile")
    created = 0
    for user in User.objects.all():
        if UserProfile.objects.filter(user=user).exists():
            continue
        role = "admin" if user.is_superuser else "engineer"
        UserProfile.objects.create(user=user, role=role)
        created += 1
    if created:
        print(f"  [auth] backfilled {created} UserProfile(s)")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('recoil_app', '0022_auth_userprofile_and_owner'),
    ]

    operations = [
        migrations.RunPython(backfill_profiles, reverse_code=noop_reverse),
    ]
