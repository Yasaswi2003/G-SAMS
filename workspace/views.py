from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from .models import *
from usermanagement.decorators import *

@login_required
@group_required('ADMIN')
def access_permission(request, id):
    user_id = decrypt(id)

    if request.method == 'POST':
        campus_id   = request.POST.get('campus')   or None
        building_id = request.POST.get('building') or None
        block_id    = request.POST.get('block')    or None
        floor_id    = request.POST.get('floor')    or None
        room_ids    = request.POST.getlist('room')

        if not room_ids:
            return JsonResponse({'status': 300, 'message': 'Please select at least one room.'})

        skipped = 0
        created = 0

        for room_id in room_ids:
            already = EmployeeAccessPermission.objects.filter(
                user_id     = user_id,
                campus_id   = campus_id,
                building_id = building_id,
                block_id    = block_id,
                floor_id    = floor_id,
                room_id     = room_id,
                is_active   = True,
            ).exists()

            if already:
                skipped += 1
                continue

            EmployeeAccessPermission.objects.create(
                user_id     = user_id,
                campus_id   = campus_id,
                building_id = building_id,
                block_id    = block_id,
                floor_id    = floor_id,
                room_id     = room_id,
                createdby   = request.user,
            )
            created += 1

        if created == 0:
            return JsonResponse({'status': 300, 'message': 'All selected rooms already have permission assigned.'})

        msg = f'{created} room permission(s) saved successfully.'
        if skipped:
            msg += f' {skipped} skipped (already exist).'
        return JsonResponse({'status': 200, 'message': msg})

    # ── GET ──
    permissions = EmployeeAccessPermission.objects.filter(
        user_id   = user_id,
        is_active = True
    ).select_related(
        'campus', 'building', 'block', 'floor', 'room', 'createdby'
    ).order_by('-created_at')

    campuses = Campus.objects.filter(is_active=True)
    user     = User.objects.get(id=user_id)

    context = {
        'permissions' : permissions,
        'campuses'    : campuses,
        'user_id'     : user_id,
        'user'        : user,
    }
    return render(request, 'workspace/access_permission.html', context)

