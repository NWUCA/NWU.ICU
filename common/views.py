from django.shortcuts import render


def manifest(request):
    """Serve manifest.json"""
    return render(request, 'manifest.json', content_type='application/json')


def service_worker(request):
    """Serve manifest.json"""
    return render(request, 'serviceworker.js', content_type='application/javascript')
