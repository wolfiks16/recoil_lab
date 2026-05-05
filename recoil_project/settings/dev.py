"""
Dev-настройки: для локальной разработки на Windows.

Используется по умолчанию через manage.py.
"""

from .base import *  # noqa: F401,F403
from .base import env


SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="django-insecure-(z5jqf$r++5(s^vhnc5^uv^x8n#l&@lf)0kbr%1mxb&j%+n&q%",
)

DEBUG = env.bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["127.0.0.1", "localhost"],
)
