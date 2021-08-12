import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render


def index(request):
    return render(request, 'index.html')


def about(request):
    return render(request, 'about.html')


@login_required
def settings(request):
    return render(request, 'settings.html')


def save_push_subscription(request):
    print(json.loads(request.body))
    return HttpResponse()


def manifest(request):
    """Serve manifest.json"""
    return render(request, 'manifest.json', content_type='application/json')


def service_worker(request):
    """Serve serviceworker.js"""
    return render(request, 'serviceworker.js', content_type='application/javascript')
