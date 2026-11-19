"""Temporary, owner-scoped revisions stored in the existing Django session."""
from datetime import date
from secrets import token_urlsafe
from time import time
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import ClassroomBooking

SESSION_KEY = 'classroom_booking_revisions'
TTL_SECONDS = 2 * 60 * 60
MAX_DRAFTS = 5
FORM_FIELDS = {'campus':100, 'building':250, 'room_key':250, 'booking_date':10,
               'from_time':5, 'to_time':5, 'duration_hours':2, 'purpose':5000,
               'details':5000, 'comment':5000, 'subject_code':50, 'subject_name':150}


class RevisionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

    def response(self):
        return JsonResponse({'error':str(self),'code':'revision_unavailable'},status=self.status)


def owned_booking(request, booking_id):
    from .booking_workflow import role
    if role(request.user) != 'TEACHER':
        raise RevisionError('Only the faculty owner can revise this request.',403)
    if not str(booking_id).isdigit():
        raise RevisionError('Booking not found.',404)
    booking = ClassroomBooking.objects.filter(pk=int(booking_id), booked_by=request.user,
        booking_source='teacher_request',is_active=True).prefetch_related('history__performed_by').first()
    if booking is None:
        raise RevisionError('Booking not found.',404)
    if booking.status != 'changes_requested':
        raise RevisionError('This request is no longer awaiting your response. Refresh the request list.',409)
    return booking


def load_draft(request, token, booking=None):
    from .booking_workflow import role
    if role(request.user) != 'TEACHER':
        raise RevisionError('Only the faculty owner can use this revision.',403)
    draft = request.session.get(SESSION_KEY, {}).get(token)
    if not draft or draft.get('user_id') != request.user.pk:
        raise RevisionError('Revision not found. Open Respond & Resubmit from your own request.',404)
    if time() - draft.get('created_at',0) > TTL_SECONDS:
        discard_draft(request,token)
        raise RevisionError('Your revision session expired. Reopen Respond & Resubmit; the original request is unchanged.',410)
    if booking is None:
        booking = owned_booking(request,draft['booking_id'])
    if booking.pk != draft['booking_id'] or booking.booked_by_id != request.user.pk or booking.status != 'changes_requested':
        raise RevisionError('This revision no longer belongs to an editable request.',409)
    if booking.modified_at.isoformat() != draft['revision']:
        raise RevisionError('This request changed while you were selecting a slot. Reopen Respond & Resubmit.',409)
    return draft,booking


def store_draft(request, token, draft):
    drafts = dict(request.session.get(SESSION_KEY, {}))
    drafts[token] = draft
    request.session[SESSION_KEY] = drafts


def discard_draft(request, token):
    drafts = dict(request.session.get(SESSION_KEY, {}))
    drafts.pop(token,None)
    request.session[SESSION_KEY] = drafts


def return_url(token):
    return reverse('classroom_requests') + '?' + urlencode({'revision':token,'status_group':'changes_requested'})


def latest_draft(request, booking):
    """Recover a valid draft when the owner reopens More after navigating away."""
    candidates = request.session.get(SESSION_KEY,{})
    for token in sorted(candidates, key=lambda key:candidates[key].get('created_at',0), reverse=True):
        candidate = candidates[token]
        if candidate.get('booking_id') != booking.pk or candidate.get('user_id') != request.user.pk:
            continue
        try:
            draft,_ = load_draft(request,token,booking)
            return token,draft
        except RevisionError:
            continue
    return None,None


@login_required
@require_POST
def start(request):
    from .booking_workflow import edit_payload
    try:
        booking = owned_booking(request,request.POST.get('booking_id',''))
        if request.POST.get('expected_revision') and request.POST['expected_revision'] != booking.modified_at.isoformat():
            raise RevisionError('The request has changed. Reopen Respond & Resubmit.',409)
        token = request.POST.get('revision_token')
        if token:
            draft,_ = load_draft(request,token,booking)
        else:
            drafts = {key:value for key,value in request.session.get(SESSION_KEY,{}).items()
                      if value.get('user_id') == request.user.pk and time()-value.get('created_at',0) <= TTL_SECONDS}
            if len(drafts) >= MAX_DRAFTS:
                oldest = min(drafts,key=lambda key:drafts[key]['created_at'])
                drafts.pop(oldest)
            request.session[SESSION_KEY] = drafts
            token = token_urlsafe(24)
            draft = {'user_id':request.user.pk,'booking_id':booking.pk,'revision':booking.modified_at.isoformat(),
                     'created_at':time(),'selection':None}
        payload = edit_payload(booking)
        fields = {**payload['initial'], 'subject_code':booking.subject_code,'subject_name':booking.subject_name}
        fields.update(draft.get('fields',{}))
        for field,limit in FORM_FIELDS.items():
            if field in request.POST:
                value = request.POST[field]
                if len(value)>limit:
                    raise RevisionError('A revision field is too long: '+field)
                fields[field] = value
        draft['fields'] = fields
        store_draft(request,token,draft)
        # Resolve filters using the catalog, not browser-provided campus/building.
        selected = next((room for room in payload['rooms'] if room['key']==fields.get('room_key')),None)
        selected = selected or next((room for room in payload['rooms'] if room['key']==payload['initial']['room_key']),None)
        try:
            selected_date = date.fromisoformat(fields.get('booking_date',''))
        except ValueError:
            selected_date = booking.booking_date
        params = {'revision':token,'date':selected_date.isoformat(),'include_after_hours':'0'}
        if selected:
            params.update(campus=selected['campus'],building=selected['building_key'],room=selected['key'])
        return JsonResponse({'token':token,'timetable_url':reverse('class_utilization')+'?'+urlencode(params),
                             'return_url':return_url(token)})
    except RevisionError as error:
        return error.response()
    except DatabaseError:
        return JsonResponse({'error':'Revision data is unavailable. Please retry.'},status=503)


@login_required
@require_GET
def state(request):
    from .booking_workflow import edit_payload
    try:
        token = request.GET.get('revision','')
        draft,booking = load_draft(request,token)
        payload = edit_payload(booking)
        payload.update(initial=draft['fields'],booking_id=booking.pk,revision_token=token,
                       selection=draft.get('selection'),return_url=return_url(token))
        response = JsonResponse(payload)
        response['Cache-Control'] = 'no-store'
        return response
    except RevisionError as error:
        return error.response()
    except DatabaseError:
        return JsonResponse({'error':'Revision data is unavailable. Please retry.'},status=503)


@login_required
@require_POST
def select_slot(request):
    from .booking_workflow import slot,faculty_conflict,BookingConflict
    try:
        token = request.POST.get('revision_token','')
        draft,booking = load_draft(request,token)
        room,day,start,end,_ = slot(request.POST,booking)
        faculty_conflict(request.user,(room,day,start,end,''),booking.pk)
        selection = {'campus':room['campus'],'building':room['building_key'],'room_key':room['key'],
                     'floor':room.get('floor_code', ''),
                     'room_name':room['room_name'],'booking_date':day.isoformat(),
                     'from_time':start.strftime('%H:%M'),'to_time':end.strftime('%H:%M'),
                     'duration_hours':int((end.hour*60+end.minute-start.hour*60-start.minute)/60)}
        draft['fields'] = {**draft['fields'],**{key:value for key,value in selection.items() if key in FORM_FIELDS}}
        draft['selection'] = selection
        store_draft(request,token,draft)
        return JsonResponse({'selection':selection,'return_url':return_url(token),
                             'message':'Slot selected for your revision. It is not reserved until you resubmit.'})
    except RevisionError as error:
        return error.response()
    except BookingConflict as error:
        return error.response()
    except (ValueError,TypeError) as error:
        return JsonResponse({'error':str(error)},status=400)
    except DatabaseError:
        return JsonResponse({'error':'Availability could not be verified. Please retry.'},status=503)
