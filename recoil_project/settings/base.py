"""
Базовые настройки RecoilLab — общие для dev и prod.

Конкретные значения SECRET_KEY, DEBUG, ALLOWED_HOSTS и других
секретов читаются из окружения в dev.py / prod.py.
"""

from pathlib import Path

import environ


# settings/__init__.py живёт в recoil_project/settings/, поэтому
# поднимаемся на 2 уровня, чтобы получить корень проекта (где manage.py).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# === ENVIRONMENT ===
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")


# === APPLICATIONS ===
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "recoil_app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "recoil_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "recoil_project.wsgi.application"


# === DATABASE ===
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# === PASSWORD VALIDATION ===
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# === I18N ===
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True


# === STATIC / MEDIA ===
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# === Auth ===
# Django auth по умолчанию редиректит на /accounts/login/. У нас свой URL.
LOGIN_URL = "login"                  # имя URL (resolves via reverse)
LOGIN_REDIRECT_URL = "dashboard"     # куда отправлять после успешного логина
LOGOUT_REDIRECT_URL = "dashboard"    # куда после выхода
