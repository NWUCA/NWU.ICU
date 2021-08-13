import json

from django.conf import settings as dj_settings
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import render
from pywebpush import webpush

from .models import WebPushSubscription


def index(request):
    return render(request, 'index.html')


def about(request):
    return render(request, 'about.html')


@login_required
def settings(request):
    context = {"VAPID_PUBLIC_KEY": dj_settings.WEBPUSH_SETTINGS["VAPID_PUBLIC_KEY"]}
    return render(request, 'settings.html', context=context)


@login_required
def save_push_subscription(request):
    data = json.loads(request.body)
    WebPushSubscription.objects.update_or_create(
        user=request.user, defaults={'subscription': data}
    )
    return HttpResponse()


@permission_required('dumb_perm')  # superuser has all the permissions
def send_test_notification(request):
    try:
        msg = request.GET['msg']
        for s in WebPushSubscription.objects.all():
            webpush(
                s.subscription,
                msg,
                vapid_private_key=dj_settings.WEBPUSH_SETTINGS['VAPID_PRIVATE_KEY'],
                vapid_claims={
                    "sub": f"mailto:{dj_settings.WEBPUSH_SETTINGS['VAPID_ADMIN_EMAIL']}"
                },
            )
        return HttpResponse('OK')
    except KeyError:
        return HttpResponse(status=400)


def manifest(request):
    """Serve manifest.json"""
    return render(request, 'manifest.json', content_type='application/json')


def service_worker(request):
    """Serve serviceworker.js"""
    return render(request, 'serviceworker.js', content_type='application/javascript')
