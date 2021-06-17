from django.shortcuts import render


def index(request):
    return render(request, 'index.html')


def about(request):
    return render(request, 'about.html')


def manifest(request):
    """Serve manifest.json"""
    return render(request, 'manifest.json', content_type='application/json')


def service_worker(request):
    """Serve serviceworker.js"""
    return render(request, 'serviceworker.js', content_type='application/javascript')
