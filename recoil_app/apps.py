from django.apps import AppConfig


class RecoilAppConfig(AppConfig):
    name = 'recoil_app'

    def ready(self) -> None:
        from . import signals  # noqa: F401
