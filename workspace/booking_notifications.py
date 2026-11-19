"""In-app booking notifications, backed by the existing chronological history."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from usermanagement.models import UserGroups
from .models import ClassroomBookingNotification


def notify_event(entry):
    booking=entry.booking
    faculty={'Submitted':False,'Edited':False,'Resubmitted':False,'Withdrawn':False,'Amendment Requested':False,'Cancellation Requested':False}.get(entry.action,True)
    roles={
        'Submitted':('HOD',), 'Edited':('HOD','ADMIN'), 'Resubmitted':('HOD','ADMIN'),
        'Withdrawn':('HOD','ADMIN'), 'Approved':('ADMIN','HOI'),
        'Amendment Requested':('ADMIN',), 'Cancellation Requested':('ADMIN',),
    }.get(entry.action,())
    if entry.action=='Changes Requested': roles=('HOD',) if entry.user_role=='ADMIN' else ()
    if entry.action=='Confirmed' or (entry.action=='Rejected' and entry.user_role=='ADMIN') or entry.action in ('Amendment Approved','Amendment Rejected','Cancellation Approved','Cancellation Rejected'):
        roles=('HOD','HOI')
    recipients={booking.booked_by_id} if faculty else set()
    for name in roles:
        assignments=UserGroups.objects.filter(group__name=name,is_block=False,user__is_active=True)
        if name=='HOD':
            assignments=assignments.filter(user__campus__iexact=booking.requester_campus,user__dept_code__iexact=booking.requester_department)
            if not booking.requester_campus or not booking.requester_department:continue
        elif name=='HOI':
            assignments=assignments.filter(user__campus__iexact=booking.requester_campus)
            if not booking.requester_campus:continue
        recipients.update(assignments.values_list('user_id',flat=True))
    recipients.discard(entry.performed_by_id)
    ClassroomBookingNotification.objects.bulk_create([ClassroomBookingNotification(recipient_id=user_id,history=entry) for user_id in recipients])


def notification_scope(user):
    from .booking_workflow import visible
    return ClassroomBookingNotification.objects.filter(recipient=user,history__booking__in=visible(user).values('pk')).select_related('history__performed_by','history__booking')


@login_required
@require_GET
def notifications(request):
    qs=notification_scope(request.user)
    rows=[]
    for notice in qs[:30]:
        event=notice.history
        rows.append({'id':notice.pk,'booking_id':event.booking_id,'action':event.action,'actor':event.performed_by.get_full_name() or event.performed_by.username if event.performed_by else 'Former user','created_at':event.created_at.strftime('%d %b %Y %H:%M'),'comment':event.display_details['comments'],'read':notice.read_at is not None,'url':reverse('classroom_requests')+'?booking_id='+str(event.booking_id)})
    return JsonResponse({'unread':qs.filter(read_at__isnull=True).count(),'notifications':rows})


@login_required
@require_POST
def mark_read(request):
    notice_id=request.POST.get('notification_id','')
    if not notice_id.isdigit():return JsonResponse({'error':'Notification not found.'},status=404)
    notice=get_object_or_404(notification_scope(request.user),pk=int(notice_id))
    if notice.read_at is None:
        notice.read_at=timezone.now();notice.save(update_fields=['read_at'])
    return JsonResponse({'message':'Notification marked as read.'})


@login_required
@require_GET
def activity_page(request):
    page = Paginator(notification_scope(request.user).order_by('-created_at', '-pk'), 15).get_page(request.GET.get('page'))
    return render(request, 'workspace/booking_activity.html', {'activity_page': page})
