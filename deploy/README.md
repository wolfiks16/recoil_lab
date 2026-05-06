# RecoilLab — деплой на Linux-сервер

Конфигурация: gunicorn (Unix socket) + nginx (proxy + static + media), без HTTPS.

Текущий prod: `185.250.47.144`, корень установки — `/srv/recoil_lab`, сервис
`recoillab.service`. Адаптируй пути и IP под свою установку.

---

## 1. Подготовка сервера (от root)

```bash
# Обновление и базовые пакеты (Ubuntu/Debian)
apt-get update && apt-get upgrade -y
apt-get install -y python3 python3-venv python3-pip nginx sqlite3 git

# Каталог проекта
mkdir -p /srv/recoil_lab
```

> На текущем prod gunicorn работает от `root` (Group=www-data, чтобы сокет был
> доступен nginx). Если хочешь изолировать процесс, создай выделенного
> пользователя и поменяй `User=` в `deploy/gunicorn.service`:
>
> ```bash
> adduser --system --group --no-create-home --shell /usr/sbin/nologin recoil
> chown recoil:www-data /srv/recoil_lab
> ```

## 2. Загрузка кода

```bash
cd /srv/recoil_lab
git clone <url> .

# Или через rsync с локальной машины (с Windows через WSL/Git Bash):
# rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='media' --exclude='db.sqlite3' \
#       ./ user@185.250.47.144:/srv/recoil_lab/
```

## 3. Виртуальное окружение и зависимости

```bash
cd /srv/recoil_lab
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

Без `.env` процесс не стартует — `settings.prod` обязательно требует
`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.

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
# media/ должна быть писабельна процессу gunicorn (создание расчётов).
chmod -R u+rwX,g+rwX /srv/recoil_lab/media
chmod u+rw,g+rw /srv/recoil_lab/db.sqlite3

# .env содержит SECRET_KEY — пожать права.
chmod 640 /srv/recoil_lab/.env

# Если завёл выделенного пользователя:
# chown -R recoil:www-data /srv/recoil_lab
# chmod -R g+rX /srv/recoil_lab
```

## 7. systemd unit для gunicorn

```bash
cp deploy/gunicorn.service /etc/systemd/system/recoillab.service
systemctl daemon-reload
systemctl enable recoillab
systemctl start recoillab

# Проверка
systemctl status recoillab
journalctl -u recoillab -f
ls -la /run/recoil.sock   # должен существовать, group=www-data
```

> ⚠️ `ExecStart` в `gunicorn.service` строго одной строкой. Многострочный
> вариант с `\` в systemd хрупкий: если потеряется перенос или пробелы между
> аргументами съедятся, gunicorn получит на вход бессмыслицу вроде
> `error-logfile` как имя WSGI-модуля и упадёт с `ModuleNotFoundError`.

## 8. nginx

```bash
cp deploy/nginx.conf /etc/nginx/sites-available/recoillab
ln -sf /etc/nginx/sites-available/recoillab /etc/nginx/sites-enabled/recoillab

# Опционально — убрать дефолтный сайт
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx
```

> ⚠️ Путь сокета в `proxy_pass http://unix:/run/recoil.sock;` должен **точно**
> совпадать с `--bind` в `gunicorn.service`. Опечатка (`reciol.sock` вместо
> `recoil.sock`) приводит к 502 с `connect() to unix:... failed
> (No such file or directory)` в `/var/log/nginx/error.log`.

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
cd /srv/recoil_lab

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
systemctl restart recoillab
```

## Просмотр логов

```bash
# Логи gunicorn (Django request errors, traceback'и)
journalctl -u recoillab -f

# Последние 200 строк
journalctl -u recoillab -n 200

# Логи nginx
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## Откат

```bash
# Если что-то сломалось — остановить gunicorn:
systemctl stop recoillab

# Восстановить предыдущую версию кода (git checkout / rsync)
# Применить нужные миграции назад при необходимости (manage.py migrate <app> <prev_migration>)

# Запуск
systemctl start recoillab
```

---

## Миграция со старого однофайлового settings.py

Если у тебя на сервере ещё лежит старый `recoil_project/settings.py` (вручную
правленый под prod) и ты накатываешь обновление с новой структурой
`recoil_project/settings/{base,dev,prod}.py`:

1. **Перед `git pull`** выпиши из старого `settings.py` значения `SECRET_KEY`,
   `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` — они переедут в `.env`.
2. Сделай бэкап: `cp db.sqlite3 ~/db.sqlite3.bak && tar czf ~/media.tar.gz media/`.
3. Если старый `settings.py` у тебя tracked в git — `git stash` или
   `git checkout -- recoil_project/settings.py` перед pull.
4. После `git pull` создай `.env` (см. шаг 4 выше) и подставь сохранённый
   `SECRET_KEY` — иначе все активные сессии разлогинятся.
5. Доустанови зависимости — в новой версии появились `django-environ` и
   `gunicorn` (если их не было): `.venv/bin/pip install -r requirements.txt`.
6. Поправь `Environment="DJANGO_SETTINGS_MODULE=..."` в systemd unit:
   старое значение `recoil_project.settings` → новое `recoil_project.settings.prod`.
   `systemctl daemon-reload` после правки.
7. Прогон: `migrate` → `collectstatic --noinput` → `systemctl restart recoillab`.

## Типичные грабли

- **502 Bad Gateway**: смотри `/var/log/nginx/error.log`. Чаще всего —
  опечатка в пути сокета (`proxy_pass`) или сокет не создан, потому что
  gunicorn не стартовал. `ls -la /run/recoil.sock` + `systemctl status recoillab`.
- **`ModuleNotFoundError: No module named 'error-logfile'`** или похожее:
  поломан `ExecStart` в юните, `--` отвалился у одного из флагов. Сделай
  `ExecStart` одной строкой.
- **`ImproperlyConfigured: ... DJANGO_SECRET_KEY`** при старте: `.env` не
  создан или не доступен gunicorn'у. Проверь, что файл лежит в
  `/srv/recoil_lab/.env` и читаем процессом.
- **Permission denied при загрузке файлов / сохранении расчёта**: `media/`
  или `db.sqlite3` не писабельны процессу gunicorn. См. шаг 6.
