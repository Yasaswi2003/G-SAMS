from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET

from .booking_workflow import role


DATA_PATH = Path(__file__).with_name('data') / 'room_utilization.json'


@login_required
@require_GET
def dashboard(request):
    if role(request.user) != 'ADMIN':
        return HttpResponseForbidden('Only Admin can access room utilization analytics.')
    return redirect(reverse('booking_analytics') + '#ba-occupancy')


@login_required
@require_GET
def data(request):
    if role(request.user) != 'ADMIN':
        return JsonResponse({'error': 'Only Admin can access room utilization analytics.'}, status=403)
    try:
        response = FileResponse(DATA_PATH.open('rb'), content_type='application/json')
    except FileNotFoundError:
        return JsonResponse({'error': 'The room utilization data has not been imported yet.'}, status=503)
    response['Cache-Control'] = 'private, no-cache'
    return response
