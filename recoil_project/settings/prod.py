"""
Production-настройки: для работы за gunicorn + nginx по http (без HTTPS).

Все секреты читаются из .env. На prod-сервере .env лежит в корне проекта
рядом с manage.py.
"""

from .base import *  # noqa: F401,F403
from .base import env


# SECRET_KEY обязателен — генерируется на сервере командой:
#   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY = env("DJANGO_SECRET_KEY")

DEBUG = False

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# Для AJAX-эндпоинтов (catalog_save_from_form). Без этого CSRF будет ругаться.
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")


# === HTTPS-related security warnings заглушены, т.к. деплой по HTTP ===
# При переходе на HTTPS убрать этот список и включить SECURE_SSL_REDIRECT,
# SECURE_HSTS_SECONDS, SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE.
SILENCED_SYSTEM_CHECKS = [
    "security.W004",  # SECURE_HSTS_SECONDS
    "security.W008",  # SECURE_SSL_REDIRECT
    "security.W012",  # SESSION_COOKIE_SECURE
    "security.W016",  # CSRF_COOKIE_SECURE
]


# === LOGGING ===
# В prod логи идут в stderr → systemd journal на сервере.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
