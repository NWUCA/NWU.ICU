from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'course_assessment'

    def ready(self):
        import course_assessment.signals
