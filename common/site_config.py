"""Public, explicitly allowlisted site settings shared with the browser."""
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.html import json_script
from django.views.decorators.http import require_GET, require_safe


def public_site_config():
    return {
        'site_name': settings.WEBSITE_NAME,
        'site_origin': settings.SITE_ORIGIN,
        'university_name': settings.UNIVERSITY_CHINESE_NAME,
        'university_short_name': settings.UNIVERSITY_SHORT_NAME,
        'college_email_domains': list(
            dict.fromkeys(
                [
                    settings.UNIVERSITY_TEACHER_MAIL_SUFFIX.lower(),
                    settings.UNIVERSITY_STUDENT_MAIL_SUFFIX.lower(),
                ]
            )
        ),
        'registration_blocked_email_domains': [settings.UNIVERSITY_MAIL_SUFFIX.lower()],
        'navigation_links': settings.SITE_NAVIGATION_LINKS,
        'analytics': {
            'website_id': settings.ANALYTICS_WEBSITE_ID,
            'domains': settings.ANALYTICS_DOMAINS,
        },
        'sentry_dsn': settings.SENTRY_DSN,
        'footer_start_year': settings.SITE_START_YEAR,
        'frontend_repository_url': settings.FRONTEND_GITHUB_URL,
        'backend_repository_url': settings.BACKEND_GITHUB_URL,
    }


@require_GET
def site_config(request):
    response = JsonResponse(public_site_config())
    response['Cache-Control'] = 'no-store'
    return response


@require_safe
def site_config_bootstrap(request):
    response = HttpResponse(json_script(public_site_config(), 'site-config-bootstrap'))
    response['Cache-Control'] = 'no-store'
    return response
