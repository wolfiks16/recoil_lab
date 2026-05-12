# Добавляет в UserProfile поля кастомизации:
#   - avatar_key   — ключ мультяшного аватара (эмодзи мордочка животного);
#   - birth_date   — дата рождения, опциональное.
# Никаких бэкфиллов: дефолт "fox" применится автоматически для всех существующих
# профилей (Django заполнит default'ом при ALTER TABLE).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recoil_app', '0023_backfill_user_profiles'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='avatar_key',
            field=models.CharField(
                choices=[
                    ('fox',     '🦊 Лиса'),
                    ('cat',     '🐱 Кот'),
                    ('bear',    '🐻 Медведь'),
                    ('rabbit',  '🐰 Кролик'),
                    ('dog',     '🐶 Собака'),
                    ('panda',   '🐼 Панда'),
                    ('raccoon', '🦝 Енот'),
                    ('wolf',    '🐺 Волк'),
                    ('tiger',   '🐯 Тигр'),
                    ('lion',    '🦁 Лев'),
                    ('mouse',   '🐭 Мышь'),
                    ('frog',    '🐸 Лягушка'),
                ],
                default='fox',
                help_text='Мультяшный аватар пользователя (мордочка животного).',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='birth_date',
            field=models.DateField(
                blank=True,
                help_text='Дата рождения. Опциональное поле.',
                null=True,
            ),
        ),
    ]
