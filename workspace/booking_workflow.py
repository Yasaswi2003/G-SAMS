"""Scoped classroom requests and audited, serialized booking transitions."""
import json
from datetime import date, datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from usermanagement.models import UserGroups
from .models import ClassroomBooking as Booking, ClassroomBookingHistory as History, ClassroomBookingLock, ClassroomBookingChangeRequest as ChangeRequest


class BookingConflict(ValueError):
    """A real room/time clash, distinct from invalid form or permission errors."""
    def __init__(self, booking):
        self.status = booking.status
        self.availability = 'hold' if booking.status == 'pending' else 'booked'
        self.day = booking.booking_date.isoformat()
        self.start = booking.from_time.strftime('%H:%M')
        self.end = booking.to_time.strftime('%H:%M')
        super().__init__(
            'Classroom unavailable! An existing ' + booking.get_status_display() +
            ' request overlaps from ' + booking.from_time.strftime('%I:%M %p') +
            ' to ' + booking.to_time.strftime('%I:%M %p') +
            '. Please select another time slot or classroom.')

    def response(self):
        # Do not disclose the other faculty member's identity or booking details.
        return JsonResponse({'error': str(self), 'code': 'booking_conflict',
                             'conflict': {'status': self.status, 'availability': self.availability,
                                          'date': self.day, 'start': self.start, 'end': self.end},
                             'available': False}, status=400)


def role(user):
    if not user.is_authenticated or not user.is_active:
        return ''
    names = set(UserGroups.objects.filter(user=user, is_active=True, is_block=False).values_list('group__name', flat=True))
    # Exactly one active role is expected; fail closed on ambiguous assignments.
    selected = next(iter(names)) if len(names) == 1 else ''
    return 'TEACHER' if selected == 'STAFF' else selected


def visible(user, active_role=None):
    r = active_role or role(user)
    qs = Booking.objects.filter(is_active=True).select_related('booked_by', 'reviewed_by', 'confirmed_by', 'admin_decided_by').prefetch_related('history__performed_by','change_requests__reviewed_by')
    if r == 'ADMIN':
        return qs
    if r == 'HOD' and user.dept_code and user.campus:
        return qs.filter(Q(requester_department__iexact=user.dept_code.strip(), requester_campus__iexact=user.campus.strip()) | Q(booking_source='admin_direct', campus_code__iexact=user.campus.strip()))
    if r == 'HOI' and user.campus:
        return qs.filter(requester_campus__iexact=user.campus.strip())
    if r == 'TEACHER':
        return qs.filter(Q(booked_by=user) | Q(booking_source='admin_direct', campus_code__iexact=user.campus or '__unassigned__'))
    return qs.none()


def audit(booking, user, r, action, previous='', comments=''):
    snapshot = {'campus': booking.campus_code, 'building': booking.building_name, 'room': booking.room_key or booking.room_code, 'date': str(booking.booking_date), 'start': str(booking.from_time), 'end': str(booking.to_time), 'purpose': booking.purpose}
    comments = comments + '\n' + json.dumps({'booking': snapshot})
    entry = History.objects.create(booking=booking, performed_by=user, user_role=r, action=action,
                           previous_status=previous, new_status=booking.status, comments=comments)
    from .booking_notifications import notify_event
    notify_event(entry)
    return entry


def lock_bookings():
    # UPDATE is intentionally the first DB statement inside the transaction.
    # SQLite serializes writers; a second writer waits or fails without committing.
    if ClassroomBookingLock.objects.filter(pk=1).update(version=F('version') + 1) != 1:
        raise DatabaseError('Booking mutex missing; run migrations.')


def slot(data, existing=None, reserve_pending=True):
    from . import class_utilization as cu
    rooms, by_key, aliases = cu._load_room_catalog()
    key = data.get('room_key') or (existing.room_key if existing else '')
    room = by_key.get(key)
    if room is None and existing and not data.get('room_key'):
        matches = [r for r in rooms if cu._normalise(r['campus']) == cu._normalise(existing.campus_code)
                   and cu._normalise(r['room_code']) == cu._normalise(existing.room_code)
                   and cu._normalise(existing.building_name) in {cu._normalise(r['building']), cu._normalise(r['building_code'])}]
        room = matches[0] if len(matches) == 1 else None
    if room is None:
        raise ValueError('Select a valid active classroom.')
    for field, expected in [('campus', room['campus']), ('building', room['building_key'])]:
        if data.get(field) and cu._normalise(data[field]) != cu._normalise(expected):
            raise ValueError('Campus, building and room must match.')
    if room.get('maintenance'):
        raise ValueError('This classroom is under maintenance. Select another classroom.')
    day = date.fromisoformat(data.get('booking_date') or (existing.booking_date.isoformat() if existing else ''))
    start = datetime.strptime(data.get('from_time') or (existing.from_time.strftime('%H:%M') if existing else ''), '%H:%M').time()
    if data.get('to_time'):
        end = datetime.strptime(data['to_time'], '%H:%M').time()
    elif data.get('duration_hours'):
        end_dt = datetime.combine(day, start) + timedelta(hours=int(data['duration_hours']))
        if end_dt.date() != day:
            raise ValueError('Bookings must end on the same day.')
        end = end_dt.time()
    elif existing:
        end = existing.to_time
    else:
        raise ValueError('Select an end time.')
    if day < date.today() or start >= end:
        raise ValueError('Choose a future date and an end time after the start time.')
    from .holidays import closures_on
    holidays = closures_on(day, room['campus'])
    if holidays:
        raise ValueError('This campus is closed for ' + ', '.join(item['name'] for item in holidays) + '. Choose a working date.')
    from .classroom_maintenance import maintenance_blocks
    if maintenance_blocks(room['key'], day, start, end):
        raise ValueError('Classroom unavailable! This classroom is under maintenance during the selected time.')
    closing_hour = 22 if existing and (existing.status == 'changes_requested' or existing.to_time > datetime.strptime('16:00','%H:%M').time()) else 16
    if start.hour < 8 or end.hour > closing_hour or (end.hour == closing_hour and (end.minute or end.second)):
        raise ValueError('Bookings must be within 08:00 and '+str(closing_hour)+':00.')
    minutes = cu._minutes(end) - cu._minutes(start)
    if minutes > 8 * 60:
        raise ValueError('Choose a booking duration of 1 to 8 hours.')
    if (existing is None or data.get('from_time') or data.get('to_time') or data.get('duration_hours')) and minutes % 60:
        raise ValueError('Choose a booking duration in whole hours.')
    if data.get('duration_hours'):
        duration = int(data['duration_hours'])
        if not 1 <= duration <= 8 or cu._minutes(end) - cu._minutes(start) != duration * 60:
            raise ValueError('Duration and ending time do not match. Choose 1 to 8 hours.')
    semester = cu.get_current_semester(day)
    # Do not silently fall back to a different term when checking availability.
    if semester not in cu._load_semester_choices():
        raise ValueError('Timetable data for this academic term is unavailable.')
    schedules = cu._load_timetable(semester, by_key, aliases)
    for row in schedules:
        matching = row['room_key'] == room['key']
        # Unresolved master rows are conservatively treated as occupied if their room alias matches.
        if not row['room_key']:
            matching = cu._normalise(row['campus']) == cu._normalise(room['campus']) and cu._normalise(row['room_code']) in {
                alias[1] for alias, keys in aliases.items() if room['key'] in keys}
        if matching and row['weekday'] == cu.DAYS[day.weekday()] and row['start_minutes'] < cu._minutes(end) and row['end_minutes'] > cu._minutes(start):
            raise ValueError('Classroom unavailable! A scheduled class occupies ' + _clock(row['start_minutes']) + ' to ' + _clock(row['end_minutes']) + '. Please select another time slot or classroom.')
    conflicts = Booking.objects.filter(is_active=True, status__in=['pending', 'hod_approved', 'confirmed'] if reserve_pending else ['confirmed'], booking_date=day,
        campus_code__iexact=room['campus'], room_code__iexact=room['room_code'],
        from_time__lt=end, to_time__gt=start).filter(Q(room_key=room['key']) | Q(building_name__iexact=room['building']) | Q(building_name__iexact=room['building_code']))
    if existing:
        conflicts = conflicts.exclude(pk=existing.pk)
    conflict = conflicts.order_by('from_time').first()
    if conflict:
        raise BookingConflict(conflict)
    return room, day, start, end, semester


def _clock(minutes):
    return datetime.strptime(f'{minutes // 60:02d}:{minutes % 60:02d}', '%H:%M').strftime('%I:%M %p')


def apply_slot(booking, values):
    room, day, start, end, semester = values
    booking.room_key = room['key']
    booking.campus_code = room['campus']
    booking.building_name = room['building']
    booking.room_code = room['room_code']
    booking.booking_date, booking.from_time, booking.to_time = day, start, end
    booking.semester_flag = semester
    booking.duration_hours = max(1, int((datetime.combine(day, end) - datetime.combine(day, start)).total_seconds() / 3600))


@login_required
@require_POST
def book_classroom(request):
    r = role(request.user)
    if r not in ('TEACHER', 'ADMIN'):
        return JsonResponse({'error': 'Only Teachers and Admin can create bookings.'}, status=403)
    purpose = request.POST.get('purpose', '').strip()
    if not purpose:
        return JsonResponse({'error': 'Booking purpose is required.'}, status=400)
    if r == 'TEACHER' and (not request.user.dept_code or not request.user.campus):
        return JsonResponse({'error': 'Your department and campus must be assigned before requesting a room.'}, status=400)
    try:
        with transaction.atomic():
            lock_bookings()
            values = slot(request.POST)
            if r == 'TEACHER' and Booking.objects.filter(booked_by=request.user, booking_date=values[1], from_time__lt=values[3], to_time__gt=values[2], status__in=['pending','hod_approved','confirmed'], is_active=True).exists():
                raise ValueError('You already have an overlapping classroom request or booking at this time.')
            booking = Booking(booked_by=request.user, purpose=purpose,
                title=request.POST.get('subject_name', '').strip()[:150] or purpose[:150],
                subject_code=request.POST.get('subject_code', '').strip()[:50],
                subject_name=request.POST.get('subject_name', '').strip()[:150],
                details=request.POST.get('details', '').strip(),
                teacher_name=request.user.get_full_name() or request.user.username,
                teacher_id=request.user.username, teacher_email=request.user.email,
                requester_department=request.user.dept_code or '', requester_campus=request.user.campus or values[0]['campus'],
                status='confirmed' if r == 'ADMIN' else 'pending',
                booking_source='admin_direct' if r == 'ADMIN' else 'teacher_request')
            apply_slot(booking, values)
            if r == 'ADMIN':
                booking.confirmed_by, booking.confirmed_at = request.user, timezone.now()
                booking.admin_decided_by, booking.admin_decided_at = request.user, timezone.now()
            booking.save()
            audit(booking, request.user, r, 'Confirmed' if r == 'ADMIN' else 'Submitted', comments=purpose)
    except BookingConflict as exc:
        return exc.response()
    except (ValueError, TypeError) as exc:
        return JsonResponse({'error': str(exc), **({'code':'slot_unavailable'} if str(exc).startswith(('Classroom unavailable!','This campus is closed for ','You already have an overlapping classroom')) else {})}, status=400)
    except DatabaseError:
        return JsonResponse({'error': 'Booking data could not be verified or is busy. Please retry.'}, status=503)
    return JsonResponse({'message': booking.get_status_display(), 'booking_id': booking.pk, 'status': booking.status}, status=201)


@login_required
@require_GET
def availability(request):
    if role(request.user) not in ('TEACHER', 'ADMIN'):
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    try:
        existing = None
        if request.GET.get('booking_id'):
            booking_id = request.GET['booking_id']
            existing = visible(request.user).filter(pk=int(booking_id)).first() if booking_id.isdigit() else None
            if existing is None or existing.booked_by_id != request.user.pk or existing.booking_source != 'teacher_request':
                return JsonResponse({'error': 'You can only check edits to your own faculty request.'}, status=403)
        room, day, start, end, _ = slot(request.GET, existing)
        return JsonResponse({'available': True, 'capacity': room['capacity'], 'message': 'Available. Availability is checked again on submission and confirmation.'})
    except BookingConflict as exc:
        return exc.response()
    except (ValueError, TypeError) as exc:
        return JsonResponse({'available': False, 'error': str(exc), **({'code':'slot_unavailable'} if str(exc).startswith(('Classroom unavailable!','This campus is closed for ','You already have an overlapping classroom')) else {})}, status=400)
    except DatabaseError:
        return JsonResponse({'error': 'Master data unavailable. Please retry.'}, status=503)


def booking_snapshot(booking):
    return {'campus':booking.campus_code,'building':booking.building_name,'room':booking.room_key or booking.room_code,'date':str(booking.booking_date),'start':str(booking.from_time),'end':str(booking.to_time),'purpose':booking.purpose}


def faculty_conflict(user,values,exclude=None):
    qs=Booking.objects.filter(booked_by=user,booking_date=values[1],from_time__lt=values[3],to_time__gt=values[2],status__in=['pending','hod_approved','confirmed'],is_active=True)
    if exclude:qs=qs.exclude(pk=exclude)
    conflict=qs.order_by('from_time','pk').first()
    if conflict:
        raise ValueError('You already have an overlapping classroom request or booking: Request #'+str(conflict.pk)+
            ' ('+conflict.get_status_display()+'), '+conflict.building_name+' / '+conflict.room_code+
            ' on '+conflict.booking_date.strftime('%d %b %Y')+', '+conflict.from_time.strftime('%H:%M')+
            ' - '+conflict.to_time.strftime('%H:%M')+'. This room may be free, but your requests cannot overlap. Choose another time or withdraw your other eligible request.')


def reset_reviews(booking):
    booking.reviewed_by=None;booking.reviewed_at=None;booking.review_comment=''
    booking.admin_decided_by=None;booking.admin_decided_at=None;booking.admin_comment=''
    booking.confirmed_by=None;booking.confirmed_at=None


@login_required
@require_POST
def review_classroom_booking(request):
    r=role(request.user)
    if r not in ('TEACHER','HOD','ADMIN'):
        return JsonResponse({'error':'Your role cannot modify booking requests.'},status=403)
    action=request.POST.get('action','')
    faculty_actions={'edit','withdraw','request_amendment','request_cancellation'}
    allowed=faculty_actions if r=='TEACHER' else ({'approve','reject','request_changes'} if r=='HOD' else {'approve','confirm','reject','request_changes','approve_change','reject_change'})
    if action not in allowed:
        return JsonResponse({'error':'This action is not permitted for your active role.'},status=403)
    comment=request.POST.get('comment','').strip()
    if action in {'withdraw','request_amendment','request_cancellation','reject','request_changes','reject_change'} and not comment:
        return JsonResponse({'error':'A reason or comment is required.'},status=400)
    try:
        with transaction.atomic():
            lock_bookings()
            booking_id=request.POST.get('booking_id','')
            if not str(booking_id).isdigit():
                return JsonResponse({'error':'Booking not found.'},status=404)
            booking=visible(request.user,r).filter(pk=int(booking_id)).first()
            if booking is None:
                return JsonResponse({'error':'This booking is no longer available within your access. Refresh the requests list.'},status=404)
            if request.POST.get('expected_revision') and request.POST['expected_revision'] != booking.modified_at.isoformat():
                return JsonResponse({'error':'This request changed after you opened it. Refresh the list before reviewing.'},status=409)
            if r=='HOD' and booking.booked_by_id==request.user.pk:
                return JsonResponse({'error':'You cannot review your own request.'},status=403)
            revision_token=request.POST.get('revision_token')
            if revision_token:
                from .booking_revisions import load_draft, RevisionError
                try:
                    draft,_=load_draft(request,revision_token,booking=booking)
                except RevisionError as error:
                    return error.response()
                if action!='edit':
                    return JsonResponse({'error':'This revision can only resubmit the original request.'},status=400)
            previous=booking.status
            before=booking_snapshot(booking)
            if r=='TEACHER':
                if booking.booked_by_id!=request.user.pk or booking.booking_source!='teacher_request':
                    return JsonResponse({'error':'You can only manage your own faculty booking requests.'},status=403)
                if action in ('edit','withdraw'):
                    if booking.status in ('hod_rejected','admin_rejected'):
                        raise ValueError('Rejected requests are closed. Create a new booking request if you still need a classroom.')
                    if not booking.faculty_can_edit:raise ValueError('This request cannot be edited or withdrawn directly. Confirmed bookings require an amendment or cancellation request.')
                    if action=='withdraw':
                        booking.status='withdrawn';booking.withdrawal_reason=comment
                        booking.withdrawn_by=request.user;booking.withdrawn_at=timezone.now()
                        event='Withdrawn'
                    else:
                        purpose=request.POST.get('purpose','').strip()
                        if not purpose:raise ValueError('Booking purpose is required.')
                        values=slot(request.POST,booking)
                        faculty_conflict(request.user,values,booking.pk)
                        apply_slot(booking,values);booking.purpose=purpose
                        booking.details=request.POST.get('details',booking.details).strip()
                        booking.status='pending';reset_reviews(booking)
                        event='Edited' if previous=='pending' else 'Resubmitted'
                        comment=(comment+'\n' if comment else '')+json.dumps({'before':before,'after':booking_snapshot(booking)})
                    booking.save()
                    audit(booking,request.user,r,event,previous,comment)
                else:
                    if previous!='confirmed':raise ValueError('Only confirmed bookings can request an amendment or cancellation.')
                    if booking.change_requests.filter(status='pending').exists():raise ValueError('A change request is already awaiting Admin review.')
                    proposal={}
                    if action=='request_amendment':
                        purpose=request.POST.get('purpose','').strip()
                        if not purpose:raise ValueError('Booking purpose is required.')
                        values=slot(request.POST,booking)
                        faculty_conflict(request.user,values,booking.pk)
                        room,day,start,end,semester=values
                        proposal={'room_key':room['key'],'campus':room['campus'],'building':room['building_key'],'building_name':room['building'],'room_name':room['room_name'],'booking_date':str(day),'from_time':start.strftime('%H:%M'),'to_time':end.strftime('%H:%M'),'duration_hours':(end.hour*60+end.minute-start.hour*60-start.minute)//60,'purpose':purpose}
                    change=ChangeRequest.objects.create(booking=booking,kind='amendment' if action=='request_amendment' else 'cancellation',proposed_values=proposal,original_values=before,booking_revision=booking.modified_at.isoformat(),reason=comment,requested_by=request.user)
                    details=comment
                    if proposal:details+='\n'+json.dumps({'proposal':proposal})
                    audit(booking,request.user,r,'Amendment Requested' if change.kind=='amendment' else 'Cancellation Requested',previous,details)
            elif action in ('approve_change','reject_change'):
                change=get_object_or_404(booking.change_requests,pk=request.POST.get('change_request_id'),status='pending')
                if previous!='confirmed':raise ValueError('The original confirmed booking is no longer eligible.')
                if action=='approve_change':
                    if change.booking_revision!=booking.modified_at.isoformat():raise ValueError('The original booking has changed. Reject this stale request and ask the faculty to submit a new proposal.')
                    if change.kind=='amendment':
                        values=slot(change.proposed_values,booking)
                        faculty_conflict(booking.booked_by,values,booking.pk)
                        apply_slot(booking,values);booking.purpose=change.proposed_values['purpose']
                        booking.confirmed_by=request.user;booking.confirmed_at=timezone.now()
                    else:booking.status='cancelled'
                    change.status='approved'
                    booking.admin_comment=comment;booking.admin_decided_by=request.user;booking.admin_decided_at=timezone.now()
                    booking.save()
                else:
                    change.status='rejected'
                    booking.admin_comment=comment;booking.admin_decided_by=request.user;booking.admin_decided_at=timezone.now()
                    booking.save(update_fields=['admin_comment','admin_decided_by','admin_decided_at','modified_at'])
                change.reviewed_by=request.user;change.reviewed_at=timezone.now();change.review_comment=comment;change.save()
                event=change.kind.title()+(' Approved' if action=='approve_change' else ' Rejected')
                audit(booking,request.user,r,event,previous,comment+'\n'+json.dumps({'before':before,'after':booking_snapshot(booking)}))
            elif action=='request_changes':
                if not booking.can_request_changes:raise ValueError('Changes can only be requested before final confirmation of a faculty request.')
                booking.status='changes_requested'
                if r=='HOD':booking.review_comment=comment;booking.reviewed_by=request.user;booking.reviewed_at=timezone.now()
                else:booking.admin_comment=comment;booking.admin_decided_by=request.user;booking.admin_decided_at=timezone.now()
                booking.save();audit(booking,request.user,r,'Changes Requested',previous,comment)
            else:
                # Either authorized reviewer can finish a pending decision. The
                # write mutex above makes a second conflicting decision fail.
                legacy_confirmation = r=='ADMIN' and action=='confirm' and previous=='hod_approved'
                if previous!='pending' and not legacy_confirmation:
                    raise ValueError('This request already has a decision. Refresh the list; faculty must resubmit returned requests before another review.')
                approving = action in ('approve','confirm')
                if approving:
                    apply_slot(booking,slot({},booking))
                    booking.status='confirmed';booking.confirmed_by=request.user;booking.confirmed_at=timezone.now()
                else:booking.status='hod_rejected' if r=='HOD' else 'admin_rejected'
                if r=='HOD':
                    booking.reviewed_by=request.user;booking.reviewed_at=timezone.now();booking.review_comment=comment
                else:
                    booking.admin_comment=comment;booking.admin_decided_by=request.user;booking.admin_decided_at=timezone.now()
                booking.save();audit(booking,request.user,r,('Approved' if r=='HOD' or action=='approve' else 'Confirmed') if approving else 'Rejected',previous,comment)
    except BookingConflict as error:
        return error.response()
    except (ValueError,TypeError) as error:
        return JsonResponse({'error':str(error), **({'code':'slot_unavailable'} if str(error).startswith(('Classroom unavailable!','This campus is closed for ','You already have an overlapping classroom')) else {})},status=400)
    except DatabaseError:
        return JsonResponse({'error':'Booking data is busy or unavailable. Please retry.'},status=503)
    if request.POST.get('revision_token') and action=='edit':
        from .booking_revisions import discard_draft
        discard_draft(request,request.POST['revision_token'])
    message='Your request has been sent to Admin; the original confirmed booking remains active.' if action in ('request_amendment','request_cancellation') else booking.get_status_display()
    if r=='HOD' and action=='approve':
        message='Approved by HOD. The booking is confirmed.'
    return JsonResponse({'message':message,'status':booking.status,'booking_id':booking.pk})


@login_required
@require_GET
def classroom_requests(request):
    from .class_utilization import _load_room_catalog
    r = role(request.user)
    revision_token = request.GET.get('revision')
    if revision_token:
        from .booking_revisions import load_draft, RevisionError
        try:
            load_draft(request,revision_token)
        except RevisionError as error:
            return error.response()
    qs = visible(request.user, r).order_by('-created_at')
    if request.GET.get('booking_id'):
        qs=qs.filter(pk=request.GET['booking_id']) if request.GET['booking_id'].isdigit() else qs.none()
    for field, lookup in [('campus','campus_code__iexact'), ('building','building_name__icontains'), ('room','room_code__icontains'), ('department','requester_department__iexact'), ('teacher','teacher_name__icontains')]:
        if request.GET.get(field):
            qs = qs.filter(**{lookup: request.GET[field]})
    if request.GET.get('date'):
        try:
            qs = qs.filter(booking_date=date.fromisoformat(request.GET['date']))
        except ValueError:
            qs = qs.none()
    if request.GET.get('q'):
        query = request.GET['q']
        qs = qs.filter(Q(teacher_name__icontains=query) | Q(purpose__icontains=query) | Q(teacher_id__icontains=query) | Q(room_code__icontains=query) | Q(building_name__icontains=query))
    from django.db.models import Count
    counts = dict(qs.order_by().values('status').annotate(total=Count('pk')).values_list('status', 'total'))
    groups = [('all', 'All Requests', tuple(value for value, label in Booking.STATUS_CHOICES)),
              ('pending', 'Pending Approval', ('pending',)),
              ('changes_requested', 'Changes Requested', ('changes_requested',)),
              ('approved', 'Approved', ('hod_approved', 'confirmed')),
              ('rejected', 'Rejected', ('hod_rejected', 'admin_rejected')),
              ('withdrawn', 'Withdrawn', ('withdrawn',))]
    summary = []
    total = sum(counts.values())
    for key, label, values in groups:
        count = sum(counts.get(value, 0) for value in values)
        params = request.GET.copy()
        params.pop('status', None)
        params.pop('status_group', None)
        if key != 'all':
            params['status_group'] = key
        summary.append({'key': key, 'label': label, 'count': count,
                        'url': '?' + params.urlencode(),
                        'active': request.GET.get('status_group', 'all') == key and not request.GET.get('status')})
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    selected_group = request.GET.get('status_group')
    if selected_group == 'closed':  # Preserve old bookmarked filter URLs.
        qs = qs.filter(status__in=('withdrawn','cancelled'))
    elif selected_group and selected_group != 'all':
        qs = qs.filter(status__in=next((values for key, label, values in groups if key == selected_group), ()))
    rooms, error = [], ''
    if r in ('TEACHER', 'ADMIN'):
        try:
            rooms = _load_room_catalog()[0]
        except DatabaseError:
            error = 'Room master is unavailable.'
    assigned_hods = {}
    assignments = UserGroups.objects.filter(group__name='HOD', is_block=False,
                                           user__is_active=True).select_related('user')
    for assignment in assignments:
        hod = assignment.user
        scope = ((hod.campus or '').strip().casefold(), (hod.dept_code or '').strip().casefold())
        if all(scope):
            assigned_hods.setdefault(scope, set()).add(hod.get_full_name() or hod.username)
    for booking in qs:
        scope = (booking.requester_campus.strip().casefold(), booking.requester_department.strip().casefold())
        booking.assigned_hod_names = ', '.join(sorted(assigned_hods.get(scope, ()))) or 'Not Assigned'
    return render(request, 'workspace/classroom_requests.html', {'bookings': qs, 'revision_token':revision_token, 'request_summary': summary, 'request_total': total, 'booking_role': r, 'rooms': rooms, 'room_error': error, 'statuses': Booking.STATUS_CHOICES, 'filters': request.GET})


@login_required
@require_GET
def booking_updates(request):
    """Scoped DB version for lightweight polling; never includes unrelated request data."""
    from django.db.models import Max, Count
    summary = visible(request.user).aggregate(count=Count('id'), modified=Max('modified_at'), history=Max('history__id'))
    held = Booking.objects.filter(campus_code__iexact=request.user.campus or '', status__in=['pending','hod_approved','confirmed'], is_active=True).aggregate(modified=Max('modified_at'), count=Count('id'))
    from .models import ClassroomMaintenance
    maintenance = ClassroomMaintenance.objects.aggregate(modified=Max('updated_at'), count=Count('id'))
    return JsonResponse({'version': str(summary) + str(held) + str(maintenance)})


@login_required
@require_GET
def faculty_edit_data(request):
    if role(request.user)!='TEACHER':return JsonResponse({'error':'Only faculty can edit their own requests.'},status=403)
    booking_id=request.GET.get('booking_id','')
    if not booking_id.isdigit():return JsonResponse({'error':'Booking not found.'},status=404)
    booking=get_object_or_404(Booking.objects.prefetch_related('history__performed_by'),pk=int(booking_id),booked_by=request.user,booking_source='teacher_request',is_active=True)
    if not booking.faculty_can_edit and booking.status!='confirmed':return JsonResponse({'error':'This booking is view only.'},status=403)
    try:
        payload=edit_payload(booking)
        if booking.status=='changes_requested':
            from .booking_revisions import latest_draft
            token,draft=latest_draft(request,booking)
            if draft:
                payload.update(initial=draft['fields'],revision_token=token,selection=draft.get('selection'))
        response=JsonResponse(payload)
        response['Cache-Control']='no-store'
        return response
    except DatabaseError:
        return JsonResponse({'error':'Room master is unavailable.'},status=503)


def edit_payload(booking):
    from .class_utilization import _load_room_catalog,_resolve_room
    rooms,by_key,aliases=_load_room_catalog()
    room=by_key.get(booking.room_key) or _resolve_room({'campus_code':booking.campus_code,'building_name':booking.building_name,'room_number':booking.room_code},by_key,aliases)
    initial={'room_key':room['key'] if room else '', 'booking_date':str(booking.booking_date),'from_time':booking.from_time.strftime('%H:%M'),'to_time':booking.to_time.strftime('%H:%M'),'duration_hours':booking.duration_hours,'purpose':booking.purpose,'details':booking.details}
    comments = [{'role': entry.user_role, 'comment': entry.display_details['comments'],
                 'reviewer': (entry.performed_by.get_full_name() or entry.performed_by.username) if entry.performed_by else '',
                 'at': entry.created_at.isoformat()}
                for entry in booking.history.all() if entry.action=='Changes Requested']
    original = {**initial, 'campus': room['campus'] if room else booking.campus_code,
                'building': room['building'] if room else booking.building_name,
                'room_name': room['room_name'] if room else booking.room_code,
                'floor': room.get('floor_code', '') if room else ''}
    return {'initial':initial,'original':original,'rooms':rooms,'subject_code':booking.subject_code,
                         'subject_name':booking.subject_name,'review_comments':comments,
                         'status':booking.status,'revision':booking.modified_at.isoformat()}
