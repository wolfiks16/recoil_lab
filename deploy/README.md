# RecoilLab — деплой на Linux-сервер

Конфигурация: gunicorn (Unix socket) + nginx (proxy + static + media), без HTTPS.

Целевой сервер: `185.250.47.144`. Адаптируй пути и IP под свою установку.

---

## 1. Подготовка сервера (от root)

```bash
# Обновление и базовые пакеты (Ubuntu/Debian)
apt-get update && apt-get upgrade -y
apt-get install -y python3 python3-venv python3-pip nginx sqlite3 git

# Выделенный пользователь без shell
adduser --system --group --no-create-home --shell /usr/sbin/nologin recoil

# Каталог проекта
mkdir -p /srv/recoil
chown recoil:www-data /srv/recoil
```

## 2. Загрузка кода

Один из вариантов:

```bash
# Через git, если выложил на GitHub/GitLab
cd /srv/recoil
git clone <url> recoil_web

# Или через rsync с локальной машины (с Windows через WSL/Git Bash):
# rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='media' --exclude='db.sqlite3' \
#       ./ user@185.250.47.144:/srv/recoil/recoil_web/

# Или через scp + tar
```

## 3. Виртуальное окружение и зависимости

```bash
cd /srv/recoil/recoil_web
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 4. .env для production

```bash
# Сгенерировать SECRET_KEY:
.venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Создать .env из шаблона
cp .env.example .env
nano .env  # вписать SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS
```

Минимальное содержимое `.env` для prod:

```ini
DJANGO_SECRET_KEY=<сгенерированный_ключ>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=185.250.47.144
DJANGO_CSRF_TRUSTED_ORIGINS=http://185.250.47.144
```

## 5. БД и статика

```bash
export DJANGO_SETTINGS_MODULE=recoil_project.settings.prod

.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser  # опционально, для admin

# Проверка — должно не быть ошибок (warnings про SECRET_KEY/HTTPS — ОК).
.venv/bin/python manage.py check --deploy
```

## 6. Права

```bash
# Весь проект — recoil:www-data, чтобы nginx мог читать static/media.
chown -R recoil:www-data /srv/recoil/recoil_web
chmod -R g+rX /srv/recoil/recoil_web

# media/ должна быть писабельна gunicorn (создание расчётов).
chmod -R g+rwX /srv/recoil/recoil_web/media

# db.sqlite3 — то же.
chmod g+rw /srv/recoil/recoil_web/db.sqlite3
```

## 7. systemd unit для gunicorn

```bash
cp deploy/gunicorn.service /etc/systemd/system/recoil-gunicorn.service
systemctl daemon-reload
systemctl enable recoil-gunicorn
systemctl start recoil-gunicorn

# Проверка
systemctl status recoil-gunicorn
journalctl -u recoil-gunicorn -f
ls -la /run/recoil.sock   # должен существовать, group=www-data
```

## 8. nginx

```bash
cp deploy/nginx.conf /etc/nginx/sites-available/recoil
ln -sf /etc/nginx/sites-available/recoil /etc/nginx/sites-enabled/recoil

# Опционально — убрать дефолтный сайт
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx
```

## 9. Файрвол (если используется)

```bash
ufw allow 80/tcp
ufw status
```

## 10. Проверка

Открыть в браузере: `http://185.250.47.144/`

Должен открыться дашборд RecoilLab.

---

## Обновление кода после деплоя

```bash
cd /srv/recoil/recoil_web

# Обновить код
git pull   # или rsync с локальной машины

# Зависимости (если менялись)
.venv/bin/pip install -r requirements.txt

# Миграции (если есть новые)
export DJANGO_SETTINGS_MODULE=recoil_project.settings.prod
.venv/bin/python manage.py migrate

# Статика (если менялась)
.venv/bin/python manage.py collectstatic --noinput

# Перезапуск gunicorn
systemctl restart recoil-gunicorn
```

## Просмотр логов

```bash
# Логи gunicorn (Django request errors, traceback'и)
journalctl -u recoil-gunicorn -f

# Последние 200 строк
journalctl -u recoil-gunicorn -n 200

# Логи nginx
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## Откат

```bash
# Если что-то сломалось — остановить gunicorn:
systemctl stop recoil-gunicorn

# Восстановить предыдущую версию кода (git checkout / rsync)
# Применить нужные миграции назад при необходимости (manage.py migrate <app> <prev_migration>)

# Запуск
systemctl start recoil-gunicorn
```
