from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = 'common'

    def ready(self):
        import common.file.signals  # noqa: F401
        import common.notification_signals  # noqa: F401
