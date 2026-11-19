import json
import re
from datetime import date, timedelta, time
from unittest.mock import patch
from django.db import connection
from django.test import TestCase, Client
from django.urls import reverse
from usermanagement.models import User, UserGroups
from .models import ClassroomBooking as Booking, ClassroomBookingHistory, ClassroomBookingLock, ClassroomBookingChangeRequest, ClassroomBookingNotification
from .class_utilization import _build_room_catalog, get_current_semester


class BookingWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        # The existing project adds Group.priority at runtime but has no auth migration for it.
        # Insert only standard columns so tests also work on a freshly migrated database.
        for name in ('TEACHER', 'HOD', 'HOI', 'ADMIN'):
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO auth_group (name) VALUES (%s)', [name])
                group_id = cursor.lastrowid
            user = User.objects.create_user(username=name.lower(), first_name=name.title(), dept_code='CSE', campus='VSP', email=name.lower()+'@example.com')
            UserGroups.objects.create(user=user, group_id=group_id, role=name, is_active=True)
            cls.users[name] = user
        cls.other = User.objects.create_user(username='other', campus='VSP', dept_code='ECE')
        group_id = UserGroups.objects.get(user=cls.users['TEACHER']).group_id
        UserGroups.objects.create(user=cls.other, group_id=group_id, role='TEACHER', is_active=True)

    def setUp(self):
        self.catalog = _build_room_catalog([{'campus_code':'VSP', 'building_code':'ICT', 'building_name':'ICT Block', 'room_code':'101', 'room_number':'101', 'room_name':'ICT 101', 'capacity':40}])
        self.day = date.today() + timedelta(days=1)
        self.payload = {'room_key':'VSP|ICT|101','booking_date':self.day.isoformat(),'from_time':'12:00','to_time':'13:00','purpose':'Extra teaching session'}
        self.patches = [patch('workspace.class_utilization._load_room_catalog', return_value=self.catalog), patch('workspace.class_utilization._load_semester_choices', return_value=[get_current_semester(self.day)]), patch('workspace.class_utilization._load_timetable', return_value=[])]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        ClassroomBookingLock.objects.get_or_create(pk=1)

    def login(self, r):
        self.client.force_login(self.users[r])

    def submit(self, r='TEACHER', **overrides):
        self.login(r)
        return self.client.post(reverse('book_classroom'), {**self.payload, **overrides})

    def booking(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.content)
        return Booking.objects.get(pk=response.json()['booking_id'])

    def act(self, r, booking, action, **extra):
        self.login(r)
        return self.client.post(reverse('review_classroom_booking'), {'booking_id':booking.pk,'action':action,**extra})

    def test_local_direct_access_signs_in_designated_account_and_preserves_sessions(self):
        from django.test import override_settings
        with override_settings(DEBUG=True,LOCAL_DIRECT_ACCESS=True,LOCAL_DIRECT_ACCESS_USERNAME=self.users['ADMIN'].username):
            response=self.client.get(reverse('class_utilization'),HTTP_HOST='127.0.0.1:8001')
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.client.session['_auth_user_id'],str(self.users['ADMIN'].pk))
            self.login('TEACHER')
            self.client.get(reverse('class_utilization'),HTTP_HOST='localhost:8001')
            self.assertEqual(self.client.session['_auth_user_id'],str(self.users['TEACHER'].pk))

    def test_local_direct_access_does_not_apply_outside_loopback_or_production(self):
        from django.test import override_settings
        scenarios=[({'DEBUG':False},{'HTTP_HOST':'localhost:8001'}),
                   ({'DEBUG':True},{'HTTP_HOST':'localhost:8001','REMOTE_ADDR':'192.168.1.2','HTTP_X_FORWARDED_FOR':'127.0.0.1'}),
                   ({'DEBUG':True},{'HTTP_HOST':'external.example'}),
                   ({'DEBUG':True,'LOCAL_DIRECT_ACCESS':False},{'HTTP_HOST':'localhost:8001'})]
        for config,headers in scenarios:
            with override_settings(**{'LOCAL_DIRECT_ACCESS':True,'LOCAL_DIRECT_ACCESS_USERNAME':self.users['ADMIN'].username,**config}):
                client=Client()
                response=client.get(reverse('class_utilization'),**headers)
                self.assertEqual(response.status_code,302)
                self.assertNotIn('_auth_user_id',client.session)

    def test_local_employee_link_signs_in_requested_user_and_switches_existing_session(self):
        from django.test import override_settings
        with override_settings(DEBUG=True,LOCAL_DIRECT_ACCESS=True,LOCAL_DIRECT_ACCESS_USERNAME=self.users['ADMIN'].username):
            self.login('ADMIN')
            response=self.client.get(reverse('ulogin',args=[self.users['TEACHER'].username]),HTTP_HOST='127.0.0.1:8001')
            self.assertRedirects(response,reverse('dashboard'),fetch_redirect_response=False)
            self.assertEqual(self.client.session['_auth_user_id'],str(self.users['TEACHER'].pk))
            fresh=Client()
            response=fresh.get('/user/ulogin/'+self.users['HOD'].username,HTTP_HOST='localhost:8001')
            self.assertEqual(response.status_code,302)
            self.assertEqual(fresh.session['_auth_user_id'],str(self.users['HOD'].pk))
            missing=Client()
            self.assertEqual(missing.get('/ulogin/unknown-employee',HTTP_HOST='localhost:8001').status_code,404)
            self.assertNotIn('_auth_user_id',missing.session)

    def test_local_direct_access_never_falls_back_to_another_account(self):
        from django.test import override_settings
        with override_settings(DEBUG=True,LOCAL_DIRECT_ACCESS=True,LOCAL_DIRECT_ACCESS_USERNAME='missing-account'):
            response=self.client.get(reverse('class_utilization'),HTTP_HOST='localhost:8001')
            self.assertEqual(response.status_code,503)
            self.assertNotIn('_auth_user_id',self.client.session)

    def test_archived_booking_hidden_and_action_returns_json(self):
        b = self.booking()
        b.is_active = False
        b.save(update_fields=['is_active'])
        from .booking_workflow import visible
        for role in ('TEACHER', 'HOD', 'HOI', 'ADMIN'):
            self.assertFalse(visible(self.users[role]).filter(pk=b.pk).exists())
        response = self.act('ADMIN', b, 'request_changes', comment='Update purpose')
        self.assertEqual(response.status_code, 404)
        self.assertIn('Refresh', response.json()['error'])
        self.assertEqual(b.history.count(), 1)

    def test_teacher_hod_admin_workflow_and_history(self):
        b=self.booking()
        self.assertEqual(self.act('HOD',b,'approve').status_code,200)
        b.refresh_from_db()
        self.assertEqual(b.status,'confirmed')
        self.assertEqual(b.confirmed_by,self.users['HOD'])
        self.assertIsNotNone(b.confirmed_at)
        self.assertEqual(self.act('ADMIN',b,'confirm').status_code,400)
        self.assertEqual(self.act('ADMIN',b,'reject',comment='Too late').status_code,400)
        self.assertEqual(list(b.history.values_list('action',flat=True)),['Submitted','Approved'])

    def test_rejection_reason_mandatory_and_visible_to_teacher(self):
        b=self.booking()
        self.assertEqual(self.act('HOD',b,'reject',comment='  ').status_code,400)
        self.assertEqual(self.act('HOD',b,'reject',comment='Department examination').status_code,200)
        self.login('TEACHER')
        response=self.client.get(reverse('classroom_requests'))
        self.assertContains(response,'Department examination')
        b.refresh_from_db();self.assertEqual(b.status,'hod_rejected')

    def test_teacher_cannot_review_and_cannot_impersonate(self):
        response=self.submit(teacher_id='someone_else',teacher_name='Impersonation')
        b=Booking.objects.get(pk=response.json()['booking_id'])
        self.assertEqual(b.teacher_id,'teacher')
        self.assertEqual(self.act('TEACHER',b,'approve').status_code,403)
        self.assertEqual(self.act('TEACHER',b,'confirm').status_code,403)

    def test_hod_scope_and_self_approval(self):
        b=self.booking();b.requester_department='ECE';b.save()
        self.assertEqual(self.act('HOD',b,'approve').status_code,404)
        b.requester_department='CSE';b.booked_by=self.users['HOD'];b.save()
        self.assertEqual(self.act('HOD',b,'approve').status_code,403)
        b.booked_by=self.users['TEACHER'];b.requester_campus='HYD';b.save()
        self.assertEqual(self.act('HOD',b,'approve').status_code,404)

    def test_hoi_read_only_and_campus_scope(self):
        b=self.booking()
        self.login('HOI');response=self.client.get(reverse('classroom_requests'));self.assertContains(response,'Extra teaching session')
        for action in ('approve','reject','confirm','cancel','modify'):
            self.assertEqual(self.act('HOI',b,action,comment='No').status_code,403)
        self.assertEqual(self.submit('HOI').status_code,403)
        b.requester_campus='HYD';b.save()
        self.login('HOI');self.assertNotContains(self.client.get(reverse('classroom_requests')),'Extra teaching session')

    def test_teacher_only_sees_own_requests(self):
        b=self.booking();self.client.force_login(self.other)
        response=self.client.get(reverse('classroom_requests'))
        self.assertNotContains(response,'Extra teaching session')

    def test_admin_can_complete_pending_decision_without_hod(self):
        b=self.booking();self.login('ADMIN')
        response=self.client.get(reverse('classroom_requests'))
        self.assertNotContains(response,'data-action="modify"')
        self.assertNotContains(response,'data-action="withdraw"')
        self.assertContains(response,'Request Changes')
        self.assertEqual(self.act('ADMIN',b,'confirm').status_code,200)
        self.assertEqual(self.act('HOD',b,'approve').status_code,400)
        b.refresh_from_db();self.assertEqual(b.status,'confirmed')
        self.assertEqual(b.confirmed_by,self.users['ADMIN'])
        self.assertEqual(b.history.last().action,'Confirmed')

    def test_booking_details_hide_history_and_timetable_link(self):
        b=self.booking();self.login('TEACHER')
        response=self.client.get(reverse('classroom_requests'))
        self.assertNotContains(response,'Complete booking history')
        self.assertNotContains(response,'id="bw-view-timetable"')
        self.assertNotContains(response,reverse('class_utilization')+'?booking_id='+str(b.pk))
        self.assertEqual(b.history.count(),1)

    def test_booking_timetable_applies_record_scope_date_and_highlights_full_duration(self):
        b=self.booking()
        booking_day=self.day+timedelta(days=9)
        if booking_day.weekday()>=5:
            booking_day+=timedelta(days=7-booking_day.weekday())
        b.booking_date=booking_day;b.from_time=time(10);b.to_time=time(13);b.save()
        weekday=b.booking_date.strftime('%A')
        def event(start,end,code):
            return {'campus':'VSP','campus_key':'VSP','building':'ICT Block','building_key':'VSP|ICT','room_key':'VSP|ICT|101','room_code':'101','room_name':'ICT 101','room_master_match':True,'weekday':weekday,'start_minutes':start*60,'end_minutes':end*60,'duration_minutes':(end-start)*60,'subject_code':code,'subject_name':code,'instructor_id':'faculty'}
        with patch('workspace.class_utilization._load_timetable',return_value=[event(8,9,'BEFORE'),event(11,12,'DURING'),event(14,15,'AFTER')]):
            self.login('TEACHER')
            response=self.client.get(reverse('class_utilization'),{'booking_id':b.pk,'campus':'BLR','building':'stale','room':'stale','date':'2030-01-01','q':'stale'})
        self.assertEqual(response.status_code,200)
        context=response.context
        self.assertEqual(context['selected_campus'],'VSP')
        self.assertEqual(context['selected_building'],'VSP|ICT')
        self.assertEqual(context['selected_room_key'],'VSP|ICT|101')
        self.assertEqual(context['selected_date'],b.booking_date.isoformat())
        self.assertEqual(next(header for header in context['day_headers'] if header['day']==weekday)['iso_date'],b.booking_date.isoformat())
        self.assertEqual(context['visible_days'],('Monday','Tuesday','Wednesday','Thursday','Friday'))
        self.assertEqual(len(context['grid_rows']),8)
        self.assertEqual(sum(cell['highlighted'] for row in context['grid_rows'] for cell in row['cells']),3)
        self.assertEqual({row['subject_code'] for row in context['classes']},{'BEFORE','DURING','AFTER'})
        self.assertContains(response,'cu-selected-booking-period')

    def test_booking_timetable_switching_rooms_has_no_stale_filters(self):
        b=self.booking()
        second=Booking.objects.create(booked_by=self.users['TEACHER'],campus_code='VSP',building_name='GSB',room_code='0.5',room_key='VSP|GSB|0.5',semester_flag=get_current_semester(self.day),booking_date=self.day,from_time=time(10),to_time=time(13),purpose='Another classroom',title='Another classroom',requester_campus='VSP',requester_department='CSE')
        catalog=_build_room_catalog([{'campus_code':'VSP','building_code':'ICT','building_name':'ICT Block','room_code':'101','room_name':'ICT 101'}, {'campus_code':'VSP','building_code':'GSB','building_name':'GSB','room_code':'0.5','room_name':'GSB 0.5'}])
        self.login('TEACHER')
        with patch('workspace.class_utilization._load_room_catalog',return_value=catalog):
            first=self.client.get(reverse('class_utilization'),{'booking_id':b.pk})
            response=self.client.get(reverse('class_utilization'),{'booking_id':second.pk})
        self.assertEqual(first.context['selected_room_key'],'VSP|ICT|101')
        self.assertEqual(response.context['selected_room_key'],'VSP|GSB|0.5')
        self.assertEqual(response.context['selected_building'],'VSP|GSB')
        self.assertEqual(response.context['room_count'],1)
        direct=self.client.get(reverse('class_utilization'))
        self.assertIsNone(direct.context['selected_booking'])
        self.assertEqual(direct.context['selected_date'],date.today().isoformat())
        self.assertEqual(len(direct.context['visible_days']),5)

    def test_booking_timetable_rejects_unauthorized_ids_and_invalid_dates(self):
        b=self.booking();self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('class_utilization'),{'booking_id':b.pk}).status_code,404)
        self.assertEqual(self.client.get(reverse('class_utilization'),{'booking_id':'not-a-number'}).status_code,404)
        self.assertEqual(self.client.get(reverse('class_utilization'),{'date':'invalid'}).status_code,400)

    def test_admin_direct_conflict_and_adjacent_slot(self):
        response=self.submit('ADMIN');self.assertEqual(response.status_code,201)
        b=Booking.objects.get(pk=response.json()['booking_id']);self.assertEqual(b.status,'confirmed');self.assertEqual(b.booking_source,'admin_direct')
        self.assertEqual(self.submit().status_code,400)
        self.assertEqual(self.submit(from_time='13:00',to_time='14:00').status_code,201)

    def test_pending_requests_hold_room_and_prevent_duplicates(self):
        first=self.booking()
        response=self.submit()
        self.assertEqual(response.status_code,400)
        self.assertIn('12:00 PM',response.json()['error'])
        self.assertEqual(self.act('HOD',first,'approve').status_code,200)
        self.assertEqual(self.submit().status_code,400)
        self.assertEqual(self.act('ADMIN',first,'confirm').status_code,400)
        self.assertEqual(self.submit().status_code,400)

    def test_pending_conflict_returns_hold_metadata_for_other_faculty(self):
        self.booking()
        self.client.force_login(self.other)
        overlap = {**self.payload, 'from_time': '12:30', 'to_time': '13:30'}
        for response in [self.client.get(reverse('classroom_availability'), overlap),
                         self.client.post(reverse('book_classroom'), overlap)]:
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['code'], 'booking_conflict')
            self.assertEqual(response.json()['conflict']['availability'], 'hold')
            self.assertEqual(response.json()['conflict']['status'], 'pending')
            self.assertNotIn('teacher_id', response.json()['conflict'])
        self.assertEqual(Booking.objects.count(), 1)

    def test_hod_approved_and_confirmed_conflicts_are_booked(self):
        booking=self.booking()
        for status in ['hod_approved','confirmed']:
            # Legacy approval rows and final confirmations both reserve the room.
            booking.status=status;booking.save(update_fields=['status'])
            self.client.force_login(self.other)
            response=self.client.post(reverse('book_classroom'),self.payload)
            self.assertEqual(response.status_code,400)
            self.assertEqual(response.json()['conflict']['availability'],'booked')
            self.assertEqual(response.json()['conflict']['status'],status)
        self.assertEqual(Booking.objects.count(),1)

    def test_rejected_and_withdrawn_requests_release_the_slot(self):
        for action_role, action, expected in [('HOD', 'reject', 'hod_rejected'),
                                              ('TEACHER', 'withdraw', 'withdrawn'),
                                              ('ADMIN', 'reject', 'admin_rejected')]:
            with self.subTest(status=expected):
                Booking.objects.all().delete()
                booking = self.booking()
                self.assertEqual(self.act(action_role, booking, action, comment='Release this slot').status_code, 200)
                booking.refresh_from_db()
                self.assertEqual(booking.status, expected)
                self.client.force_login(self.other)
                self.assertTrue(self.client.get(reverse('classroom_availability'), self.payload).json()['available'])
                self.assertEqual(self.client.post(reverse('book_classroom'), self.payload).status_code, 201)

    def test_hold_allows_adjacent_slots_other_days_and_other_rooms(self):
        self.booking()
        self.client.force_login(self.other)
        for changes in [{'from_time': '13:00', 'to_time': '14:00'},
                        {'from_time': '11:00', 'to_time': '12:00'},
                        {'booking_date': (self.day + timedelta(days=1)).isoformat()}]:
            response = self.client.get(reverse('classroom_availability'), {**self.payload, **changes})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['available'])
        catalog = _build_room_catalog([
            {'campus_code': 'VSP', 'building_code': 'ICT', 'building_name': 'ICT Block', 'room_code': '101'},
            {'campus_code': 'VSP', 'building_code': 'ICT', 'building_name': 'ICT Block', 'room_code': '102'}])
        with patch('workspace.class_utilization._load_room_catalog', return_value=catalog):
            response = self.client.post(reverse('book_classroom'), {**self.payload, 'room_key': 'VSP|ICT|102'})
        self.assertEqual(response.status_code, 201)

    def test_hold_preflight_edit_excludes_only_the_owners_request(self):
        booking = self.booking()
        response = self.client.get(reverse('classroom_availability'), {**self.payload, 'booking_id': booking.pk})
        self.assertEqual(response.status_code, 200)
        self.client.force_login(self.other)
        response = self.client.get(reverse('classroom_availability'), {**self.payload, 'booking_id': booking.pk})
        self.assertEqual(response.status_code, 403)
        invalid = self.client.get(reverse('classroom_availability'), {**self.payload, 'booking_date': 'invalid'})
        self.assertEqual(invalid.status_code, 400)
        self.assertNotIn('code', invalid.json())

    def test_private_pending_hold_is_visible_without_other_faculty_details(self):
        booking = self.booking()
        self.client.force_login(self.other)
        response = self.client.get(reverse('class_utilization'), {
            'booking_id': '', 'room':self.payload['room_key'], 'date': self.day.isoformat(), 'campus': 'VSP', 'building': 'VSP|ICT', 'include_weekends': '1'})
        self.assertContains(response, 'On hold &mdash; Pending HOD approval')
        self.assertNotContains(response, 'data-booking-id="' + str(booking.pk) + '"')
        self.assertTrue(any(cell['has_pending_holds'] for row in response.context['grid_rows'] for cell in row['cells']))

    def test_timetable_collision_at_submission_and_confirmation(self):
        b=self.booking();self.act('HOD',b,'approve')
        row={'room_key':'VSP|ICT|101','weekday':self.day.strftime('%A'),'start_minutes':720,'end_minutes':780}
        with patch('workspace.class_utilization._load_timetable',return_value=[row]):
            self.assertEqual(self.submit().status_code,400)
            self.assertEqual(self.act('ADMIN',b,'confirm').status_code,400)
            self.login('TEACHER');response=self.client.get(reverse('classroom_availability'),self.payload);self.assertEqual(response.status_code,400)

    def test_admin_rejection_cancel_and_modification_are_audited(self):
        b=self.booking()
        self.assertEqual(self.act('ADMIN',b,'reject').status_code,400)
        self.assertEqual(self.act('ADMIN',b,'reject',comment='Building closed').status_code,200)
        self.login('TEACHER');self.assertContains(self.client.get(reverse('classroom_requests')),'Building closed')
        b=self.booking();self.confirm(b)
        self.assertEqual(self.act('ADMIN',b,'modify',from_time='14:00',to_time='15:00',comment='Rescheduled').status_code,403)
        self.assertEqual(self.act('ADMIN',b,'cancel',comment='Event cancelled').status_code,403)
        b.refresh_from_db();self.assertEqual(b.status,'confirmed');self.assertEqual(b.history.last().action,'Confirmed')

    def test_invalid_input_master_outage_and_blocked_role(self):
        self.assertEqual(self.submit(to_time='11:00').status_code,400)
        self.assertEqual(self.submit(room_key='invalid').status_code,400)
        self.assertEqual(self.submit(campus='HYD').status_code,400)
        self.assertEqual(self.submit(purpose='').status_code,400)
        with patch('workspace.class_utilization._load_semester_choices',return_value=[]):
            self.assertEqual(self.submit().status_code,400)
        UserGroups.objects.filter(user=self.users['TEACHER']).update(is_block=True)
        self.assertEqual(self.submit().status_code,403)

    def test_csrf_protects_mutations(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.users['TEACHER'])
        self.assertEqual(client.post(reverse('book_classroom'),self.payload).status_code,403)

    def test_role_dashboards_render_and_teacher_has_booking_controls(self):
        self.booking()
        for r in ('TEACHER','HOD','HOI','ADMIN'):
            self.login(r);response=self.client.get(reverse('classroom_requests'))
            self.assertEqual(response.status_code,200)
            self.assertNotContains(response,'id="bw-admin-direct"')
            self.assertNotContains(response,'Analytics Dashboard')
            self.assertNotContains(response,'View classroom timetable')

    def test_staff_uses_teacher_workflow_and_scopes_fail_closed(self):
        from .booking_workflow import role, visible
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO auth_group (name) VALUES (%s)', ['STAFF'])
            group_id=cursor.lastrowid
        user=self.users['TEACHER']
        UserGroups.objects.filter(user=user).update(is_active=False)
        UserGroups.objects.create(user=user, group_id=group_id, role='STAFF', is_active=True)
        self.assertEqual(role(user),'TEACHER')
        self.assertEqual(self.submit().status_code,201)
        hod=self.users['HOD'];hod.dept_code='';hod.save()
        self.assertFalse(visible(hod).exists())
        hoi=self.users['HOI'];hoi.campus='';hoi.save()
        self.assertFalse(visible(hoi).exists())

    def test_timetable_occupancy_excludes_unconfirmed_requests(self):
        b=self.booking();b.booking_date=date.today();b.save()
        self.login('ADMIN')
        for status in ('pending','hod_approved','hod_rejected','admin_rejected','cancelled','confirmed'):
            b.status=status;b.save()
            response=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'VSP|ICT','room':self.payload['room_key'],'include_weekends':'1'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.context['booking_events']),1)
            self.assertEqual(response.context['scheduled_hours'],1.0 if status=='confirmed' else 0)

    def test_hod_and_hoi_home_open_their_scoped_dashboards(self):
        for r in ('TEACHER','HOD','HOI'):
            self.login(r)
            self.assertRedirects(self.client.get('/dashboard'), reverse('classroom_requests'), fetch_redirect_response=False)

    def test_faculty_subject_defaults_render_and_save_on_booking(self):
        teacher=self.users['TEACHER']
        teacher.teaching_subject_code='CSEN8052'
        teacher.teaching_subject_name='Advance Computer Networks'
        teacher.save()
        self.login('TEACHER')
        response=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'VSP|ICT'})
        self.assertContains(response,"subjectCode:'CSEN8052'")
        self.assertContains(response,"subjectName:'Advance Computer Networks'")
        response=self.submit(subject_code=teacher.teaching_subject_code,subject_name=teacher.teaching_subject_name)
        self.assertEqual(response.status_code,201)
        booking=Booking.objects.get(pk=response.json()['booking_id'])
        self.assertEqual(booking.subject_code,'CSEN8052')
        self.assertEqual(booking.subject_name,'Advance Computer Networks')

    def test_rejected_decision_is_closed_and_requires_new_request(self):
        b=self.booking()
        self.assertEqual(self.act('HOD',b,'reject',comment='Initial reason').status_code,200)
        for active,action in [('HOD','approve'),('ADMIN','confirm'),('TEACHER','edit'),('TEACHER','withdraw')]:
            self.assertEqual(self.act(active,b,action,comment='Cannot reopen',**self.payload).status_code,400)
        self.login('TEACHER')
        self.assertEqual(self.client.get(reverse('booking_edit_data'),{'booking_id':b.pk}).status_code,403)
        new=self.booking();self.assertNotEqual(new.pk,b.pk)
        self.assertEqual(self.act('HOD',new,'approve').status_code,200)
        b.refresh_from_db();self.assertEqual(b.status,'hod_rejected')
        self.assertEqual(b.history.count(),2)

    def test_resubmitted_approval_rechecks_timetable_and_is_final(self):
        b=self.booking();self.act('HOD',b,'request_changes',comment='Review later')
        self.assertEqual(self.act('TEACHER',b,'edit',**self.payload).status_code,200)
        row={'room_key':'VSP|ICT|101','weekday':self.day.strftime('%A'),'start_minutes':750,'end_minutes':810}
        with patch('workspace.class_utilization._load_timetable',return_value=[row]):
            response=self.act('HOD',b,'approve',comment='Reconsider')
            self.assertEqual(response.status_code,400)
            self.assertIn('12:30 PM',response.json()['error'])
        self.assertEqual(self.act('HOD',b,'approve',comment='Available now').status_code,200)
        self.assertEqual(self.act('ADMIN',b,'reject',comment='Too late').status_code,400)

    def test_working_hours_and_full_duration_validation(self):
        for fields in ({'from_time':'07:00','to_time':'08:00'},{'from_time':'15:00','to_time':'17:00'},{'from_time':'08:00','to_time':'10:00','duration_hours':'3'},{'from_time':'08:00','duration_hours':'0'}):
            self.assertEqual(self.submit(**fields).status_code,400)
        row={'room_key':'VSP|ICT|101','weekday':self.day.strftime('%A'),'start_minutes':600,'end_minutes':660}
        with patch('workspace.class_utilization._load_timetable',return_value=[row]):
            response=self.submit(from_time='08:00',to_time='12:00',duration_hours='4')
            self.assertEqual(response.status_code,400)
            self.assertIn('10:00 AM to 11:00 AM',response.json()['error'])
        self.assertEqual(Booking.objects.count(),0)
        self.assertEqual(self.submit(from_time='08:00',to_time='10:00',duration_hours='2').status_code,201)

    def test_faculty_cannot_hold_two_rooms_for_the_same_time(self):
        self.booking()
        catalog=_build_room_catalog([
            {'campus_code':'VSP','building_code':'ICT','building_name':'ICT Block','room_code':'101','room_name':'ICT 101'},
            {'campus_code':'VSP','building_code':'ICT','building_name':'ICT Block','room_code':'102','room_name':'ICT 102'},
        ])
        with patch('workspace.class_utilization._load_room_catalog',return_value=catalog):
            response=self.submit(room_key='VSP|ICT|102')
        self.assertEqual(response.status_code,400)
        self.assertIn('already have an overlapping',response.json()['error'])

    def test_admin_rejection_comments_are_directly_visible_to_all_roles(self):
        b=self.booking()
        self.assertEqual(self.act('ADMIN',b,'reject',comment='Campus closure').status_code,200)
        b.refresh_from_db();self.assertEqual(b.admin_comment,'Campus closure');self.assertEqual(b.admin_decided_by,self.users['ADMIN'])
        for r in self.users:
            self.login(r);response=self.client.get(reverse('classroom_requests'))
            self.assertContains(response,'Campus closure')

    def test_admin_direct_booking_visible_in_faculty_and_monitoring_scope(self):
        response=self.submit('ADMIN');self.assertEqual(response.status_code,201)
        self.login('TEACHER');self.assertContains(self.client.get(reverse('classroom_requests')),'Admin Direct Booking')
        self.client.force_login(self.other);self.assertContains(self.client.get(reverse('classroom_requests')),'Admin Direct Booking')

    def test_analytics_pages_and_api_are_admin_only(self):
        for r in ('TEACHER','HOD','HOI'):
            self.login(r)
            self.assertEqual(self.client.get(reverse('booking_analytics')).status_code,403)
            self.assertEqual(self.client.get(reverse('booking_analytics_data')).status_code,403)
        self.login('ADMIN');self.assertEqual(self.client.get(reverse('booking_analytics')).status_code,200)

    def test_analytics_counts_and_utilization_use_actual_records(self):
        b=self.booking();self.act('HOD',b,'approve');self.act('ADMIN',b,'confirm')
        self.login('ADMIN')
        response=self.client.get(reverse('booking_analytics_data'),{'start':self.day.isoformat(),'end':self.day.isoformat()})
        self.assertEqual(response.status_code,200,response.content)
        data=response.json();cards={c['label']:c['value'] for c in data['cards']}
        self.assertEqual(cards['Total Booking Requests'],1);self.assertEqual(cards['Confirmed by Admin'],1)
        self.assertEqual(data['occupied_hours'],1.0 if self.day.weekday()<5 else 0)
        self.assertEqual(len(data['charts']),11)
        self.assertEqual(self.client.get(reverse('booking_analytics_data'),{'start':'invalid'}).status_code,400)

    def test_dashboard_comparison_uses_prior_dates_and_current_scope(self):
        from .booking_analytics import build_analytics
        previous = self.booking()
        previous.booking_date = self.day - timedelta(days=1)
        previous.save(update_fields=['booking_date'])
        current = self.booking()
        self.confirm(current)
        params = {'start': self.day.isoformat(), 'end': self.day.isoformat()}
        dashboard = build_analytics(params)['dashboard']
        self.assertEqual(dashboard['trend'][0]['value'], 1)
        self.assertEqual(dashboard['trend'][0]['previous'], 1)
        self.assertEqual([card['label'] for card in dashboard['cards']],
                         ['Total Bookings', 'Approval Rate', 'Avg Lead Time', 'Peak Hour'])
        self.assertEqual(dashboard['cards'][0]['delta'], 0)
        self.assertEqual(dashboard['cards'][0]['numeric_value'], 1)
        self.assertEqual(dashboard['cards'][0]['previous_value'], 1)
        self.assertEqual(dashboard['cards'][3]['value'], '12 PM')
        self.assertEqual([stage['value'] for stage in dashboard['funnel']], [1, 1, 1, 0])
        self.assertEqual(sum(sum(row['values']) for row in dashboard['weekday']), 1)
        previous.requester_department = 'ECE'
        previous.save(update_fields=['requester_department'])
        filtered = build_analytics({**params, 'department': 'CSE'})['dashboard']
        self.assertEqual(filtered['trend'][0]['previous'], 0)
        self.assertIsNone(filtered['cards'][0]['delta'])

    def test_dashboard_empty_range_has_no_fabricated_metrics(self):
        from .booking_analytics import build_analytics
        dashboard = build_analytics({'start': self.day.isoformat(), 'end': self.day.isoformat()})['dashboard']
        self.assertEqual(dashboard['cards'][0]['value'], 0)
        self.assertEqual(dashboard['cards'][1]['value'], '\u2014')
        self.assertEqual(dashboard['cards'][3]['value'], '\u2014')
        self.assertEqual(dashboard['top_rooms'], [])
        self.assertTrue(all(stage['value'] == 0 for stage in dashboard['funnel']))

    def test_analytics_raw_payload_retains_rows_for_cross_filters(self):
        booking = self.booking()
        self.login('ADMIN')
        response = self.client.get(reverse('booking_analytics'), {
            'start': self.day.isoformat(), 'end': self.day.isoformat(),
            'department': 'NO_MATCH', 'room': 'NO_MATCH'})
        self.assertEqual(response.status_code, 200)
        rows = response.context['bookings']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], booking.pk)
        required = {'id', 'date', 'weekday', 'hour', 'department', 'room_name',
                    'campus', 'building', 'room_key', 'room_code', 'room_type',
                    'status', 'source', 'faculty_name', 'created_at'}
        self.assertTrue(required.issubset(rows[0]))
        self.assertEqual(rows[0]['date'], self.day.isoformat())
        self.assertEqual(rows[0]['hour'], 12)
        self.assertEqual(rows[0]['status'], 'pending')
        self.assertEqual(rows[0]['source'], 'teacher_request')
        self.assertEqual(rows[0]['room_key'], self.payload['room_key'])
        self.assertTrue(rows[0]['ends_at'].endswith('+05:30'))
        self.assertContains(response, 'id="bookings-data"')
        self.assertContains(response, 'type="date" name="start"')
        self.assertContains(response, 'id="ba-status-chart"')
        self.assertContains(response, 'Booking Source by Weekday')
        self.assertContains(response, 'chart.js@4.')
        self.assertNotContains(response, 'booking_dashboard.js')
        outside = self.client.get(reverse('booking_analytics'), {
            'start': (self.day + timedelta(days=1)).isoformat(),
            'end': (self.day + timedelta(days=1)).isoformat()})
        self.assertEqual(outside.context['bookings'], [])

    def test_analytics_raw_payload_is_html_safe_and_archive_aware(self):
        booking = self.booking()
        booking.teacher_name = '</script><script>alert(1)</script>'
        booking.save(update_fields=['teacher_name'])
        self.login('ADMIN')
        params = {'start': self.day.isoformat(), 'end': self.day.isoformat()}
        response = self.client.get(reverse('booking_analytics'), params)
        self.assertNotContains(response, booking.teacher_name)
        self.assertEqual(response.context['bookings'][0]['faculty_name'], booking.teacher_name)
        booking.is_active = False
        booking.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(reverse('booking_analytics'), params).context['bookings'], [])

    def test_analytics_raw_date_range_validation_and_room_fallback(self):
        self.booking()
        self.login('ADMIN')
        for params in [{'start': 'bad'}, {'start': '2026-11-20', 'end': '2026-11-01'},
                       {'start': '2025-01-01', 'end': '2026-11-01'}]:
            self.assertEqual(self.client.get(reverse('booking_analytics'), params).status_code, 400)
        from django.db import DatabaseError
        with patch('workspace.class_utilization._load_room_catalog', side_effect=DatabaseError('offline')):
            response = self.client.get(reverse('booking_analytics'), {
                'start': self.day.isoformat(), 'end': self.day.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['bookings'][0]['room_type'], 'Unclassified')

    def test_management_tabs_counts_scope_and_search_are_real(self):
        first=self.booking()
        for status in ('pending','changes_requested','confirmed','hod_rejected','withdrawn'):
            Booking.objects.create(booked_by=self.users['TEACHER'],campus_code='VSP',building_name='ICT Block',
                room_code='102',room_key='VSP|ICT|102',booking_date=self.day,from_time=time(9),to_time=time(10),
                title='Count test',purpose='Count test',teacher_name='Teacher',teacher_id='teacher',
                requester_department='CSE',requester_campus='VSP',status=status)
        self.login('ADMIN')
        response=self.client.get(reverse('classroom_requests'),{'q':'ICT','campus':'VSP'})
        tabs={item['key']:item for item in response.context['request_summary']}
        self.assertEqual([item['label'] for item in response.context['request_summary']],
            ['All Requests','Pending Approval','Changes Requested','Approved','Rejected','Withdrawn'])
        self.assertEqual(tabs['all']['count'],6)
        self.assertEqual(tabs['pending']['count'],2)
        self.assertEqual(tabs['changes_requested']['count'],1)
        self.assertEqual(tabs['approved']['count'],1)
        self.assertIn('q=ICT',tabs['approved']['url']);self.assertIn('campus=VSP',tabs['approved']['url'])
        filtered=self.client.get(reverse('classroom_requests'),{'q':'ICT','status_group':'changes_requested'})
        self.assertEqual([b.status for b in filtered.context['bookings']],['changes_requested'])
        self.assertNotContains(response,'Approval Progress');self.assertNotContains(response,'Request Status')
        self.assertNotContains(response,'ref-donut');self.assertNotContains(response,'data-summary-count')
        self.assertContains(response,'VSP &middot; ICT Block &middot; 101')
        self.assertIn('Approval Timeline',response.content.decode())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('classroom_requests')).context['request_total'],0)

    def test_management_actions_order_and_final_decision_visibility(self):
        booking=self.booking()
        for active in ('HOD','ADMIN'):
            self.login(active)
            html=self.client.get(reverse('classroom_requests')).content.decode()
            approve='approve' if active=='HOD' else 'confirm'
            self.assertLess(html.index('data-view='),html.index('data-action="'+approve+'"'))
            self.assertLess(html.index('data-action="'+approve+'"'),html.index('data-action="request_changes"'))
            self.assertLess(html.index('data-action="request_changes"'),html.index('data-action="reject"'))
        self.act('HOD',booking,'approve')
        for active in ('HOD','ADMIN','HOI'):
            self.login(active)
            html=self.client.get(reverse('classroom_requests')).content.decode()
            for action in ('approve','confirm','request_changes','reject','edit','withdraw'):
                self.assertNotIn('data-action="'+action+'"',html)

    def test_stale_reviewer_revision_is_rejected_after_resubmission(self):
        booking=self.booking();original=booking.modified_at.isoformat()
        self.assertEqual(self.act('HOD',booking,'request_changes',comment='Please revise',expected_revision=original).status_code,200)
        self.assertEqual(self.act('TEACHER',booking,'edit',**self.payload).status_code,200)
        self.assertEqual(self.act('ADMIN',booking,'confirm',expected_revision=original).status_code,409)
        booking.refresh_from_db();self.assertEqual(booking.status,'pending')
        self.assertEqual(self.act('ADMIN',booking,'confirm',expected_revision=booking.modified_at.isoformat()).status_code,200)
        self.assertEqual(booking.history.filter(action='Resubmitted').count(),1)
        self.assertEqual(booking.history.filter(action='Changes Requested').count(),1)

    def test_live_updates_are_scoped_and_change_after_decision(self):
        b=self.booking();self.login('TEACHER')
        first=self.client.get(reverse('booking_updates')).json()['version']
        self.act('HOD',b,'approve');self.login('TEACHER')
        second=self.client.get(reverse('booking_updates')).json()['version']
        self.assertNotEqual(first,second)
        self.client.force_login(self.other)
        response=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'VSP|ICT'})
        self.assertEqual(response.context['booking_events'],[])

    def test_hoi_timetable_has_no_booking_controls(self):
        self.booking();self.login('HOI')
        response=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'VSP|ICT','room':self.payload['room_key'],'include_weekends':'1'})
        self.assertNotContains(response,'class="cu-slot-available"')
        self.assertContains(response,'data-status="Pending HOD Approval"')
        self.assertContains(response,'class="cu-slot-faculty"')

    def test_employee_login_requires_password_and_first_change_is_enforced(self):
        user=self.users['HOI'];user.set_password('Test-Temporary-981!');user.must_change_password=True;user.save()
        self.client.logout()
        response=self.client.get(reverse('ulogin',args=[user.username]))
        self.assertEqual(response.status_code,200);self.assertNotIn('_auth_user_id',self.client.session)
        response=self.client.post(reverse('ulogin',args=[user.username]),{'username':user.username,'password':'Test-Temporary-981!'})
        self.assertRedirects(response,'/user/change-initial-password',fetch_redirect_response=False)
        self.assertEqual(self.client.post(reverse('review_classroom_booking'),{}).status_code,403)
        self.assertRedirects(self.client.get(reverse('classroom_requests')),reverse('initial_password_change'),fetch_redirect_response=False)
        response=self.client.post(reverse('initial_password_change'),{'old_password':'Test-Temporary-981!','new_password1':'New-Private-Password-619!','new_password2':'New-Private-Password-619!'})
        self.assertEqual(response.status_code,302)
        user.refresh_from_db();self.assertFalse(user.must_change_password)
        self.assertTrue(user.check_password('New-Private-Password-619!'))

    def confirm(self,b):
        self.assertEqual(self.act('ADMIN',b,'confirm').status_code,200)
        b.refresh_from_db()

    def test_faculty_edit_pending_prepopulates_and_preserves_before_after(self):
        b=self.booking();self.login('TEACHER')
        response=self.client.get(reverse('booking_edit_data'),{'booking_id':b.pk})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['initial']['from_time'],'12:00')
        self.assertEqual(response.json()['initial']['room_key'],self.payload['room_key'])
        response=self.act('TEACHER',b,'edit',**{**self.payload,'from_time':'14:00','to_time':'16:00','duration_hours':'2','purpose':'Updated purpose'})
        self.assertEqual(response.status_code,200,response.content)
        b.refresh_from_db();self.assertEqual(b.status,'pending');self.assertEqual(b.from_time,time(14));self.assertEqual(b.to_time,time(16))
        event=b.history.last();self.assertEqual(event.action,'Edited');self.assertIn('before',event.comments);self.assertIn('after',event.comments)

    def test_faculty_responds_to_changes_and_approved_request_is_read_only(self):
        b=self.booking();b.status='hod_approved';b.save(update_fields=['status'])
        self.assertEqual(self.act('TEACHER',b,'edit',**self.payload).status_code,400)
        self.assertEqual(self.act('TEACHER',b,'withdraw',comment='Not eligible').status_code,400)
        b.status='pending';b.save(update_fields=['status'])
        self.assertEqual(self.act('HOD',b,'request_changes',comment='Please select another time').status_code,200)
        self.assertEqual(self.act('TEACHER',b,'edit',**self.payload).status_code,200)
        b.refresh_from_db();self.assertEqual(b.status,'pending');self.assertIsNone(b.reviewed_by)
        self.assertIn('Please select another time',b.history.get(action='Changes Requested').comments)
        self.assertEqual(b.history.filter(action='Resubmitted').count(),1)

    def test_rejected_requests_cannot_be_edited_or_withdrawn(self):
        for reviewer in ('HOD','ADMIN'):
            b=self.booking();self.act(reviewer,b,'reject',comment='Closed decision')
            self.assertEqual(self.act('TEACHER',b,'edit',**self.payload).status_code,400)
            self.assertEqual(self.act('TEACHER',b,'withdraw',comment='Not eligible').status_code,400)
            self.login('TEACHER')
            self.assertEqual(self.client.get(reverse('booking_edit_data'),{'booking_id':b.pk}).status_code,403)
            html=self.client.get(reverse('classroom_requests')).content.decode()
            self.assertNotIn('data-booking-menu=',html)
            self.assertNotIn('class="bw-row-menu"',html)
            self.assertIn('Closed decision',b.history.get(action='Rejected').comments)

    def test_only_own_faculty_requests_can_be_edited_or_withdrawn(self):
        b=self.booking()
        for reviewer in ('HOD','ADMIN','HOI'):
            self.assertEqual(self.act(reviewer,b,'edit',**self.payload).status_code,403)
            self.assertEqual(self.act(reviewer,b,'withdraw',comment='Not permitted').status_code,403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('review_classroom_booking'),{'booking_id':b.pk,'action':'edit',**self.payload}).status_code,404)
        self.assertEqual(self.client.get(reverse('booking_edit_data'),{'booking_id':b.pk}).status_code,404)

    def test_withdrawal_requires_reason_releases_room_and_is_terminal(self):
        b=self.booking()
        self.assertEqual(self.act('TEACHER',b,'withdraw',comment='  ').status_code,400)
        self.assertEqual(self.act('TEACHER',b,'withdraw',comment='Class moved online').status_code,200)
        b.refresh_from_db();self.assertEqual(b.status,'withdrawn');self.assertEqual(b.withdrawal_reason,'Class moved online');self.assertEqual(b.withdrawn_by,self.users['TEACHER'])
        self.assertTrue(Booking.objects.filter(pk=b.pk).exists())
        self.assertEqual(self.act('TEACHER',b,'edit',**self.payload).status_code,400)
        self.assertEqual(self.act('HOD',b,'approve').status_code,400)
        self.login('TEACHER');report=self.client.get(reverse('class_utilization'),{'date':self.day.isoformat(),'campus':'VSP','building':'VSP|ICT'})
        self.assertFalse(any(event['id']==b.pk for event in report.context['booking_events']))
        self.assertEqual(self.submit().status_code,201)

    def test_edit_and_resubmission_check_timetable_and_other_reservations(self):
        b=self.booking();self.act('HOD',b,'reject',comment='Choose a new time')
        self.assertEqual(self.submit('ADMIN',from_time='14:00',to_time='15:00').status_code,201)
        response=self.act('TEACHER',b,'edit',**{**self.payload,'from_time':'14:00','to_time':'15:00'})
        self.assertEqual(response.status_code,400)
        b.refresh_from_db();self.assertEqual(b.status,'hod_rejected');self.assertEqual(b.from_time,time(12))
        row={'room_key':self.payload['room_key'],'weekday':self.day.strftime('%A'),'start_minutes':720,'end_minutes':780}
        with patch('workspace.class_utilization._load_timetable',return_value=[row]):self.assertEqual(self.act('TEACHER',b,'edit',**self.payload).status_code,400)

    def test_request_changes_permissions_and_mandatory_comments(self):
        b=self.booking()
        for reviewer in ('TEACHER','HOI'):
            self.assertEqual(self.act(reviewer,b,'request_changes',comment='No authority').status_code,403)
        self.assertEqual(self.act('HOD',b,'request_changes',comment='  ').status_code,400)
        self.assertEqual(self.act('HOD',b,'request_changes',comment='Add a clear purpose').status_code,200)
        b.refresh_from_db();self.assertEqual(b.status,'changes_requested');self.assertEqual(b.review_comment,'Add a clear purpose')
        self.assertEqual(self.act('HOD',b,'approve').status_code,400)
        self.assertEqual(self.act('ADMIN',b,'request_changes',comment='Stale decision').status_code,400)
        self.assertEqual(self.act('TEACHER',b,'edit',**self.payload).status_code,200)
        self.assertEqual(self.act('ADMIN',b,'request_changes',comment='Select another classroom').status_code,200)
        b.refresh_from_db();self.assertEqual(b.admin_comment,'Select another classroom')
        self.login('TEACHER');response=self.client.get(reverse('classroom_requests'));self.assertContains(response,'Select another classroom');self.assertContains(response,'Add a clear purpose')

    def test_confirmed_booking_only_accepts_amendment_and_cancellation_requests(self):
        b=self.booking();self.confirm(b)
        for r in ('TEACHER','HOD','ADMIN','HOI'):
            self.assertIn(self.act(r,b,'edit',**self.payload).status_code,(400,403))
            self.assertIn(self.act(r,b,'withdraw',comment='No direct withdrawal').status_code,(400,403))
        self.assertEqual(self.act('HOD',b,'request_changes',comment='Not allowed').status_code,400)
        self.assertEqual(self.act('ADMIN',b,'request_changes',comment='Not allowed').status_code,400)

    def test_amendment_keeps_original_active_until_admin_accepts(self):
        b=self.booking();self.confirm(b)
        response=self.act('TEACHER',b,'request_amendment',**{**self.payload,'from_time':'14:00','to_time':'16:00','duration_hours':'2','purpose':'Amended class','comment':'Faculty availability changed'})
        self.assertEqual(response.status_code,200,response.content)
        b.refresh_from_db();self.assertEqual(b.status,'confirmed');self.assertEqual(b.from_time,time(12))
        change=b.change_requests.get(status='pending')
        self.assertEqual(self.act('HOD',b,'approve_change',change_request_id=change.pk).status_code,403)
        response=self.act('ADMIN',b,'approve_change',change_request_id=change.pk)
        self.assertEqual(response.status_code,200,response.content)
        b.refresh_from_db();change.refresh_from_db();self.assertEqual(b.from_time,time(14));self.assertEqual(b.status,'confirmed');self.assertEqual(change.status,'approved')
        self.assertIn('before',b.history.last().comments)

    def test_amendment_conflict_and_stale_revision_never_change_original(self):
        b=self.booking();self.confirm(b)
        self.assertEqual(self.act('TEACHER',b,'request_amendment',**{**self.payload,'from_time':'14:00','to_time':'15:00','comment':'Reschedule'}).status_code,200)
        change=b.change_requests.get(status='pending')
        self.assertEqual(self.act('TEACHER',b,'request_cancellation',comment='Duplicate pending proposal').status_code,400)
        self.assertEqual(self.submit('ADMIN',from_time='14:00',to_time='15:00').status_code,201)
        self.assertEqual(self.act('ADMIN',b,'approve_change',change_request_id=change.pk).status_code,400)
        b.refresh_from_db();self.assertEqual(b.from_time,time(12));self.assertEqual(b.status,'confirmed')
        self.assertEqual(self.act('ADMIN',b,'reject_change',change_request_id=change.pk,comment='Room unavailable').status_code,200)
        self.assertEqual(self.act('TEACHER',b,'request_cancellation',comment='Cancel instead').status_code,200)
        change=b.change_requests.get(status='pending');b.purpose='External correction';b.save()
        self.assertEqual(self.act('ADMIN',b,'approve_change',change_request_id=change.pk).status_code,400)
        b.refresh_from_db();self.assertEqual(b.status,'confirmed')

    def test_cancellation_is_a_request_until_admin_accepts(self):
        b=self.booking();self.confirm(b)
        self.assertEqual(self.act('TEACHER',b,'request_cancellation',comment='Event no longer required').status_code,200)
        b.refresh_from_db();self.assertEqual(b.status,'confirmed')
        change=b.change_requests.get(status='pending')
        self.assertEqual(self.act('ADMIN',b,'approve_change',change_request_id=change.pk).status_code,200)
        b.refresh_from_db();self.assertEqual(b.status,'cancelled');self.assertTrue(Booking.objects.filter(pk=b.pk).exists())
        self.assertEqual(self.submit().status_code,201)

    def test_admin_confirmation_does_not_accept_direct_booking_edits(self):
        b=self.booking()
        response=self.act('ADMIN',b,'confirm',from_time='14:00',to_time='15:00',purpose='Admin must not replace purpose',room_key='invalid')
        self.assertEqual(response.status_code,200)
        b.refresh_from_db();self.assertEqual(b.from_time,time(12));self.assertEqual(b.purpose,'Extra teaching session')

    def test_change_request_and_review_csrf_protection(self):
        b=self.booking()
        client=Client(enforce_csrf_checks=True);client.force_login(self.users['TEACHER'])
        self.assertEqual(client.post(reverse('review_classroom_booking'),{'booking_id':b.pk,'action':'withdraw','comment':'Need a reason'}).status_code,403)
        self.assertEqual(client.post(reverse('booking_notification_read'),{'notification_id':1}).status_code,403)

    def test_notifications_follow_roles_and_are_private_and_markable(self):
        b=self.booking()
        self.assertTrue(ClassroomBookingNotification.objects.filter(recipient=self.users['HOD'],history__booking=b,history__action='Submitted').exists())
        self.act('HOD',b,'request_changes',comment='Please clarify the purpose')
        self.login('TEACHER');response=self.client.get(reverse('booking_notifications'))
        notice=next(row for row in response.json()['notifications'] if row['action']=='Changes Requested')
        self.assertIn('Please clarify',notice['comment']);self.assertIn('booking_id='+str(b.pk),notice['url'])
        self.assertEqual(self.client.post(reverse('booking_notification_read'),{'notification_id':notice['id']}).status_code,200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('booking_notification_read'),{'notification_id':notice['id']}).status_code,404)
        self.assertEqual(self.client.get(reverse('booking_notifications')).json()['notifications'],[])

    def test_final_confirmation_notifies_faculty_hod_and_hoi(self):
        b=self.booking();self.confirm(b)
        recipients=set(ClassroomBookingNotification.objects.filter(history__booking=b,history__action='Confirmed').values_list('recipient_id',flat=True))
        self.assertEqual(recipients,{self.users[r].pk for r in ('TEACHER','HOD','HOI')})

    def test_actions_render_strictly_for_each_role(self):
        b=self.booking()
        self.login('TEACHER');response=self.client.get(reverse('classroom_requests'))
        html=response.content.decode()
        self.assertLess(html.index('id="bw-csrf"'),re.search(r'const csrf\s*=',html).start())
        self.assertContains(response,'data-action="edit"');self.assertContains(response,'data-action="withdraw"');self.assertNotContains(response,'data-action="request_changes"')
        for r in ('HOD','ADMIN','HOI'):
            self.login(r);response=self.client.get(reverse('classroom_requests'))
            self.assertNotContains(response,'data-action="edit"');self.assertNotContains(response,'data-action="withdraw"');self.assertNotContains(response,'data-action="modify"')
            if r=='HOI':
                self.assertFalse(re.search(r'<button[^>]+data-action=',response.content.decode()))
                self.assertContains(response,'Approval Timeline');self.assertNotContains(response,'data-booking-menu=')
            else:self.assertContains(response,'data-action="request_changes"')

    def test_compact_row_menu_actions_and_details_for_each_role(self):
        booking=self.booking()
        for active,required in [('TEACHER',('edit','withdraw')),('HOD',('approve','request_changes','reject')),
                                ('ADMIN',('confirm','request_changes','reject'))]:
            self.login(active)
            html=self.client.get(reverse('classroom_requests')).content.decode()
            match=re.search(r'<dialog class="bw-row-menu".*?>(.*?)</dialog>',html,re.S)
            self.assertIsNotNone(match)
            for action in required:self.assertIn('data-action="'+action+'"',match.group(1))
            visible=re.sub(r'<template.*?</template>|<dialog.*?</dialog>','',html,flags=re.S)
            actions=re.search(r'<td data-label="Actions".*?</td>',visible,re.S).group(0)
            self.assertEqual(len(re.findall(r'<button',actions)),2)
            self.assertIn('>View</button>',actions)
            self.assertIn('data-booking-menu=',actions)
        self.login('HOI')
        html=self.client.get(reverse('classroom_requests')).content.decode()
        self.assertNotIn('class="bw-row-menu"',html)
        self.assertNotIn('data-booking-menu=',html)
        for label in ['Registration number','Building','Start time','End time','HOD review status',
                      'Admin review status','HOD comments','Admin comments','Approval Timeline']:
            self.assertIn(label,html)
        self.act('HOD',booking,'request_changes',comment='Move to a different room')
        self.login('TEACHER')
        html=self.client.get(reverse('classroom_requests')).content.decode()
        menu=re.search(r'<dialog class="bw-row-menu".*?>(.*?)</dialog>',html,re.S).group(1)
        for label in ['Respond &amp; Resubmit','Withdraw Request']:
            self.assertIn(label,menu)
        self.assertIn('Move to a different room',html)
        self.act('TEACHER',booking,'edit',**self.payload)
        self.act('HOD',booking,'approve')
        for active in ('TEACHER','HOD','ADMIN'):
            self.login(active)
            html=self.client.get(reverse('classroom_requests')).content.decode()
            self.assertNotIn('data-booking-menu=',html)
            self.assertNotIn('class="bw-row-menu"',html)

    def _revision_draft(self, booking, **values):
        self.client.force_login(booking.booked_by)
        response=self.client.post(reverse('booking_revision_start'),{
            'booking_id':booking.pk,'purpose':booking.purpose,'expected_revision':booking.modified_at.isoformat(),**values})
        self.assertEqual(response.status_code,200,response.content)
        return response.json()

    def test_timetable_revision_nithin_morning_to_evening_same_request(self):
        teacher=self.users['TEACHER'];teacher.username='503823';teacher.first_name='Nithin';teacher.save()
        catalog=_build_room_catalog([
            {'campus_code':'VSP','building_code':'ChB','building_name':'ChB','room_code':'132','room_name':'ChB 132','capacity':60,'floor_code':'1'},
            {'campus_code':'VSP','building_code':'ChB','building_name':'ChB','room_code':'135','room_name':'ChB 135','capacity':60,'floor_code':'2'}])
        with patch('workspace.class_utilization._load_room_catalog',return_value=catalog):
            original={**self.payload,'room_key':'VSP|CHB|132','from_time':'08:00','to_time':'10:00','purpose':'test','subject_code':'CSEN8052','subject_name':'Advanced Computer Networks'}
            self.login('TEACHER');created=self.client.post(reverse('book_classroom'),original)
            self.assertEqual(created.status_code,201,created.content)
            booking=Booking.objects.get(pk=created.json()['booking_id']);request_id=booking.pk
            reason='Please change your 2-hour booking to an evening slot.'
            self.assertEqual(self.act('ADMIN',booking,'request_changes',comment=reason).status_code,200)
            booking.refresh_from_db();self.assertEqual(booking.status,'changes_requested')
            draft=self._revision_draft(booking,duration_hours='2')
            self.assertIn('revision=',draft['timetable_url'])
            timetable=self.client.get(draft['timetable_url'])
            self.assertEqual(timetable.status_code,200)
            self.assertEqual(timetable.context['revision_context']['booking_id'],request_id)
            self.assertNotContains(timetable,'cu-revision-slot')
            self.assertNotContains(timetable,'id="cu-revision-back" href="'+draft['return_url']+'">')
            popup=self.client.get(draft['timetable_url']+'&revision_popup=1')
            self.assertEqual(popup.headers['X-Frame-Options'],'SAMEORIGIN')
            for markup in ('Classroom Utilization','id="cuCampus"','id="cuBuilding"','id="cuDate"',
                           'name="revision_popup"','data-revision-back>Back to Form','Weekly Timetable','Schedule legend'):
                self.assertContains(popup,markup)
            self.assertNotContains(popup,'aria-label="Class utilization summary"')
            floor=self.client.get(reverse('class_utilization'),{
                'revision':draft['token'],'revision_popup':'1','campus':'VSP','building':'VSP|CHB','floor':'2','room':''})
            self.assertContains(floor,'Choose a classroom')
            self.assertNotContains(floor,'id="cuTimetableModal"')
            selection={'revision_token':draft['token'],'room_key':'VSP|CHB|135','booking_date':str(self.day),
                       'from_time':'16:00','to_time':'18:00','duration_hours':'2'}
            selected=self.client.post(reverse('booking_revision_select'),selection)
            self.assertEqual(selected.status_code,200,selected.content)
            self.assertEqual(selected.json()['selection']['floor'],'2')
            booking.refresh_from_db();self.assertEqual(booking.room_code,'132')
            self.assertEqual(booking.status,'changes_requested');self.assertEqual(Booking.objects.count(),1)
            self.assertEqual(booking.history.count(),2)
            refreshed=self.client.get(draft['timetable_url'])
            self.assertEqual(refreshed.context['revision_context']['selection']['to_time'],'18:00')
            updated=self.client.get(draft['timetable_url']+'&room=VSP%7CCHB%7C135&floor=2')
            self.assertNotContains(updated,'Updated slot')
            self.assertEqual(updated.context['revision_context']['selection']['room_key'],'VSP|CHB|135')
            returned=self.client.get(selected.json()['return_url'])
            self.assertEqual(returned.status_code,200)
            state=self.client.get(reverse('booking_revision_state'),{'revision':draft['token']}).json()
            self.assertEqual(state['initial']['purpose'],'test')
            self.assertEqual(state['initial']['room_key'],'VSP|CHB|135')
            self.assertEqual(state['initial']['duration_hours'],2)
            self.assertEqual(state['original']['room_key'],'VSP|CHB|132')
            self.assertEqual(state['original']['floor'],'1')
            self.assertEqual(state['original']['from_time'],'08:00')
            self.assertEqual(state['subject_code'],'CSEN8052')
            self.assertIn(reason,state['review_comments'][0]['comment'])
            self.assertEqual(state['review_comments'][0]['reviewer'],'Admin')
            submitted=self.client.post(reverse('review_classroom_booking'),{
                **state['initial'],'action':'edit','booking_id':request_id,'revision_token':draft['token'],
                'expected_revision':state['revision']})
            self.assertEqual(submitted.status_code,200,submitted.content)
            booking.refresh_from_db();self.assertEqual(booking.pk,request_id)
            self.assertEqual(booking.room_code,'135');self.assertEqual(booking.from_time,time(16));self.assertEqual(booking.to_time,time(18))
            self.assertEqual(booking.status,'pending');self.assertEqual(booking.purpose,'test')
            held=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'ChB','room':'VSP|CHB|135','date':str(self.day),'include_after_hours':'1'})
            self.assertContains(held,'Pending ? On hold')
            self.assertNotContains(held,'Updated slot')
            for row in held.context['grid_rows']:
                if row['start_time'] in ('16:00','17:00'):
                    for cell in row['cells']:
                        if cell['booking_date']==str(self.day):self.assertEqual(cell['free_rooms'],[])
            self.assertEqual(list(booking.history.values_list('action',flat=True)),['Submitted','Changes Requested','Resubmitted'])
            self.assertIn('132',booking.history.last().comments);self.assertIn('135',booking.history.last().comments)
            self.assertNotIn(draft['token'],self.client.session.get('classroom_booking_revisions',{}))
            for active in ('HOD','ADMIN'):
                self.login(active)
                self.assertIn(request_id,[b.pk for b in self.client.get(reverse('classroom_requests')).context['bookings']])
            self.assertEqual(self.act('HOD',booking,'approve').status_code,200)
            self.assertEqual(self.act('ADMIN',booking,'reject',comment='Too late').status_code,400)

    def test_revision_ownership_status_csrf_and_normal_timetable(self):
        booking=self.booking()
        self.assertEqual(self.client.post(reverse('booking_revision_start'),{'booking_id':booking.pk}).status_code,409)
        self.act('ADMIN',booking,'request_changes',comment='Use timetable');booking.refresh_from_db()
        draft=self._revision_draft(booking)
        normal=self.client.get(reverse('class_utilization'))
        self.assertNotContains(normal,'id="cu-revision-back"')
        self.assertIsNone(normal.context['revision_context'])
        for active in ('HOD','ADMIN','HOI'):
            self.login(active)
            self.assertEqual(self.client.get(draft['timetable_url']).status_code,403)
            self.assertEqual(self.client.get(reverse('booking_revision_state'),{'revision':draft['token']}).status_code,403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('booking_revision_start'),{'booking_id':booking.pk}).status_code,404)
        self.assertEqual(self.client.get(reverse('booking_revision_state'),{'revision':draft['token']}).status_code,404)
        guarded=Client(enforce_csrf_checks=True);guarded.force_login(self.users['TEACHER'])
        self.assertEqual(guarded.post(reverse('booking_revision_start'),{'booking_id':booking.pk}).status_code,403)
        self.assertEqual(guarded.post(reverse('booking_revision_select'),{'revision_token':draft['token']}).status_code,403)

    def test_expired_and_stale_revision_sessions_never_change_booking(self):
        from .booking_revisions import TTL_SECONDS
        booking=self.booking();self.act('HOD',booking,'request_changes',comment='Revise slot');booking.refresh_from_db()
        draft=self._revision_draft(booking,purpose='Preserve this purpose')
        saved=self.client.session['classroom_booking_revisions'][draft['token']]
        with patch('workspace.booking_revisions.time',return_value=saved['created_at']+TTL_SECONDS+1):
            response=self.client.get(reverse('booking_revision_state'),{'revision':draft['token']})
        self.assertEqual(response.status_code,410)
        self.assertNotIn(draft['token'],self.client.session.get('classroom_booking_revisions',{}))
        booking.refresh_from_db();self.assertEqual(booking.purpose,'Extra teaching session')
        draft=self._revision_draft(booking)
        booking.purpose='Changed elsewhere';booking.save()
        response=self.client.get(reverse('booking_revision_state'),{'revision':draft['token']})
        self.assertEqual(response.status_code,409)
        self.assertEqual(booking.history.count(),2)

    def test_revision_draft_preserves_unsubmitted_values_across_refresh(self):
        booking=self.booking();self.act('ADMIN',booking,'request_changes',comment='Move it');booking.refresh_from_db()
        draft=self._revision_draft(booking,purpose='Unsaved faculty text',comment='Evening slot selected as requested',details='Keep my notes',duration_hours='2',from_time='10:00',to_time='12:00')
        for unused in range(2):
            self.assertEqual(self.client.get(draft['timetable_url']).status_code,200)
            state=self.client.get(reverse('booking_revision_state'),{'revision':draft['token']}).json()
            self.assertEqual(state['initial']['purpose'],'Unsaved faculty text')
            self.assertEqual(state['initial']['details'],'Keep my notes')
            self.assertEqual(state['initial']['comment'],'Evening slot selected as requested')
        reopened=self.client.get(reverse('booking_edit_data'),{'booking_id':booking.pk}).json()
        self.assertEqual(reopened['revision_token'],draft['token'])
        self.assertEqual(reopened['initial']['purpose'],'Unsaved faculty text')
        booking.refresh_from_db();self.assertEqual(booking.purpose,'Extra teaching session')
        self.assertEqual(Booking.objects.count(),1)
        invalid=self.client.post(reverse('booking_revision_select'),{**self.payload,'revision_token':draft['token'],'room_key':'INVALID'})
        self.assertEqual(invalid.status_code,400)
        response=self.client.post(reverse('review_classroom_booking'),{**state['initial'],'action':'edit',
            'booking_id':booking.pk,'revision_token':draft['token'],'expected_revision':state['revision']})
        self.assertEqual(response.status_code,200,response.content)
        self.assertIn('Evening slot selected as requested',booking.history.get(action='Resubmitted').comments)

    def test_revision_selection_and_final_submit_recheck_conflicts(self):
        booking=self.booking();self.act('HOD',booking,'request_changes',comment='Choose a slot');booking.refresh_from_db()
        draft=self._revision_draft(booking,purpose='Keep draft')
        selection={**self.payload,'from_time':'14:00','to_time':'16:00','duration_hours':'2','revision_token':draft['token']}
        selected=self.client.post(reverse('booking_revision_select'),selection)
        self.assertEqual(selected.status_code,200,selected.content)
        Booking.objects.create(booked_by=self.other,campus_code='VSP',building_name='ICT Block',room_code='101',
            room_key=self.payload['room_key'],booking_date=self.day,from_time=time(14),to_time=time(16),status='confirmed')
        state=self.client.get(reverse('booking_revision_state'),{'revision':draft['token']}).json()
        response=self.client.post(reverse('review_classroom_booking'),{**state['initial'],'action':'edit',
            'booking_id':booking.pk,'revision_token':draft['token'],'expected_revision':state['revision']})
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json()['code'],'booking_conflict')
        booking.refresh_from_db();self.assertEqual(booking.status,'changes_requested');self.assertEqual(booking.from_time,time(12))
        self.assertEqual(booking.history.count(),2)
        self.assertEqual(self.client.get(reverse('booking_revision_state'),{'revision':draft['token']}).json()['initial']['purpose'],'Keep draft')

    def test_assigned_hod_is_distinct_from_actual_reviewer_and_timeline_collapses(self):
        booking=self.booking();self.login('ADMIN')
        response=self.client.get(reverse('classroom_requests'))
        displayed=list(response.context['bookings'])[0]
        self.assertEqual(displayed.assigned_hod_names,'Hod')
        self.assertIsNone(displayed.reviewed_by_id)
        self.assertContains(response,'Assigned HOD: Hod')
        self.assertContains(response,'class="bw-timeline-toggle" aria-expanded="false"')
        self.assertContains(response,'class="bw-timeline-collapse"')
        self.assertEqual(self.act('HOD',booking,'approve').status_code,200)
        self.login('ADMIN');response=self.client.get(reverse('classroom_requests'))
        self.assertEqual(list(response.context['bookings'])[0].reviewed_by_id,self.users['HOD'].pk)
        UserGroups.objects.filter(user=self.users['HOD']).update(is_block=True)
        response=self.client.get(reverse('classroom_requests'))
        self.assertEqual(list(response.context['bookings'])[0].assigned_hod_names,'Not Assigned')
        self.assertEqual(list(response.context['bookings'])[0].reviewed_by_id,self.users['HOD'].pk)

    def test_semester_automatically_tracks_date_and_ignores_stale_url_term(self):
        from .class_utilization import _filters
        from django.test import RequestFactory
        semesters=['2026-2027#ODD','2026-2027#EVEN','2027-2028#ODD']
        request=RequestFactory().get('/workspace/class_utilization',{'semester':'2026-2027#ODD'})
        for day,expected in [(date(2026,12,31),'2026-2027#ODD'),(date(2027,1,1),'2026-2027#EVEN'),
                             (date(2027,6,30),'2026-2027#EVEN'),(date(2027,7,1),'2027-2028#ODD')]:
            result=_filters(request,self.catalog[0],[],semesters,reference_date=day)
            self.assertEqual(result['selected_semester'],expected)
        missing=_filters(request,self.catalog[0],[],['2026-2027#ODD'],reference_date=date(2027,1,1))
        self.assertEqual(missing['current_semester'],'2026-2027#EVEN')
        self.assertEqual(missing['selected_semester'],'')
        self.login('ADMIN')
        response=self.client.get(reverse('class_utilization'))
        self.assertContains(response,'id="cuSemester"')
        self.assertNotContains(response,'<select name="semester"')

    def test_week_navigation_defaults_current_week_and_preserves_filters(self):
        from urllib.parse import urlsplit,parse_qs
        from django.utils import timezone
        today=timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
        self.login('ADMIN')
        params={'campus':'VSP','building':'VSP|ICT','room':'VSP|ICT|101','semester':get_current_semester(today)}
        response=self.client.get(reverse('class_utilization'),params)
        monday=today-timedelta(days=today.weekday())
        self.assertEqual(response.context['week_start'],monday)
        self.assertEqual(response.context['week_work_end'],monday+timedelta(days=4))
        next_params=parse_qs(urlsplit(response.context['next_week_url']).query)
        for key,value in params.items():self.assertEqual(next_params[key],[value])
        self.assertEqual(next_params['date'],[(monday+timedelta(days=7)).isoformat()])
        future=self.client.get(reverse('class_utilization'),{key:values[0] for key,values in next_params.items()})
        self.assertEqual(future.context['week_start'],monday+timedelta(days=7))
        self.assertNotContains(response,'Search Timetable')
        self.assertNotContains(response,'Semester and Schedule Synchronization')
        self.assertNotContains(response,'Booking Dashboard')
        self.assertContains(response,'cu-live-dot')
        self.assertContains(response,'classroom_weekly.css')

    def test_official_closure_blocks_booking_and_is_highlighted(self):
        from .holidays import validate_calendar
        calendar=validate_calendar({'years':{str(self.day.year):{'source':'Test fixture only',
            'holidays':[{'name':'Fixture campus closure','date':self.day.isoformat(),'category':'campus','campuses':['VSP']}]}}})
        self.login('TEACHER')
        with patch('workspace.holidays.calendar_data',return_value=calendar):
            unavailable=self.client.get(reverse('classroom_availability'),self.payload)
            self.assertEqual(unavailable.status_code,400)
            self.assertIn('Fixture campus closure',unavailable.json()['error'])
            self.assertEqual(self.client.post(reverse('book_classroom'),self.payload).status_code,400)
            report=self.client.get(reverse('class_utilization'),{'date':self.day.isoformat(),'campus':'VSP','building':'VSP|ICT','room':self.payload['room_key'],'include_weekends':'1'})
            self.assertContains(report,'FIXTURE CAMPUS CLOSURE')
            day=self.day.strftime('%A')
            self.assertTrue(next(header for header in report.context['day_headers'] if header['day']==day)['is_holiday'])
            self.assertTrue(all(not cell['free_rooms'] for row in report.context['grid_rows'] for cell in row['cells'] if cell['day']==day))

    def test_progressive_campus_building_floor_classroom_and_back_navigation(self):
        catalog=_build_room_catalog([
            {'campus_code':'VSP','building_code':'ChB','building_name':'ChB','room_code':'132','floor_code':'3','capacity':60},
            {'campus_code':'VSP','building_code':'ChB','building_name':'ChB','room_code':'133','floor_code':'4'},
            {'campus_code':'VSP','building_code':'MVB','building_name':'MVB','room_code':'201','floor_code':'2'},
            {'campus_code':'HYD','building_code':'HY1','building_name':'HY1','room_code':'101','floor_code':'1'}])
        self.login('TEACHER')
        with patch('workspace.class_utilization._load_room_catalog',return_value=catalog):
            page=self.client.get(reverse('class_utilization'))
            self.assertFalse(page.context['show_schedule']);self.assertEqual(page.context['selection_step'],1)
            self.assertNotContains(page,'Explore campus')
            self.assertContains(page,'Total Classrooms')
            self.assertEqual(len(page.context['campus_cards']),2)
            self.assertNotContains(page,'Choose from the filters above')
            self.assertNotContains(page,'aria-current="step"')
            self.assertNotContains(page,'class="cu-grid"')
            campus=self.client.get(reverse('class_utilization'),{'campus':'VSP'})
            self.assertEqual(campus.context['selection_step'],2)
            self.assertEqual({b['key'] for b in campus.context['buildings']},{'VSP|CHB','VSP|MVB'})
            building=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'VSP|CHB'})
            self.assertEqual(building.context['selection_step'],3)
            self.assertEqual({f['key'] for f in building.context['floor_choices']},{'3','4'})
            self.assertContains(building,'cu-floor-card',count=2)
            self.assertNotContains(building,'<select id="cuFloor"')
            floor_page=self.client.get(reverse('class_utilization')+building.context['floor_cards'][0]['url'])
            self.assertEqual(floor_page.context['selection_step'],4)
            params={'campus':'VSP','building':'VSP|CHB','floor':'3','date':str(self.day)}
            cards=self.client.get(reverse('class_utilization'),params)
            self.assertEqual(cards.context['selection_step'],4)
            self.assertEqual([r['room_code'] for r in cards.context['classroom_cards']],['132'])
            timetable=self.client.get(reverse('class_utilization')+cards.context['classroom_cards'][0]['url'])
            self.assertTrue(timetable.context['show_schedule'])
            self.assertEqual(timetable.context['selected_room_key'],'VSP|CHB|132')
            next_week=self.client.get(reverse('class_utilization')+timetable.context['next_week_url'])
            self.assertEqual(next_week.context['selected_floor'],'3')
            self.assertEqual(next_week.context['selected_room_key'],'VSP|CHB|132')
            back=self.client.get(reverse('class_utilization')+timetable.context['back_to_classrooms_url'])
            self.assertFalse(back.context['show_schedule']);self.assertEqual(back.context['selected_floor'],'3')
            self.assertEqual([r['room_code'] for r in back.context['classroom_cards']],['132'])
            invalid=self.client.get(reverse('class_utilization'),{**params,'room':'VSP|CHB|133'})
            self.assertFalse(invalid.context['show_schedule'])

    def test_classroom_card_statuses_are_time_dependent_and_maintenance_blocks_booking(self):
        from .classroom_selection import selection_context
        from django.test import RequestFactory
        from django.utils import timezone
        now=timezone.localtime() if timezone.is_aware(timezone.now()) else timezone.now()
        room=self.catalog[0][0]
        filters={'selected_campus':'VSP','selected_building':'VSP|ICT','selected_floor':'__unrecorded__','selected_room_key':'','floor_choices':[],'campuses':[],'buildings':[]}
        request=RequestFactory().get('/workspace/class_utilization')
        minute=now.hour*60+now.minute
        schedule={'room_key':room['key'],'weekday':now.strftime('%A'),'start_minutes':minute,'end_minutes':minute+10}
        with patch('workspace.classroom_selection.closures_on',return_value=[]):
            occupied=selection_context(request,[room],[schedule],filters,now.date())
            self.assertEqual(occupied['classroom_cards'][0]['state'],'occupied')
            free=selection_context(request,[room],[],filters,now.date())
            self.assertEqual(free['classroom_cards'][0]['state'],'available')
            pending=Booking.objects.create(booked_by=self.users['TEACHER'],booking_date=now.date(),from_time=time(0),to_time=time(23,59),
                room_key=room['key'],campus_code='VSP',building_name='ICT Block',room_code='101',status='pending')
            reserved=selection_context(request,[room],[],filters,now.date())
            self.assertEqual(reserved['classroom_cards'][0]['state'],'reserved')
            pending.status='withdrawn';pending.save()
            self.assertEqual(selection_context(request,[room],[],filters,now.date())['classroom_cards'][0]['state'],'available')
        maintenance=_build_room_catalog([{'campus_code':'VSP','building_code':'ICT','room_code':'101','current_status':'M'}])
        with patch('workspace.class_utilization._load_room_catalog',return_value=maintenance):
            response=self.submit()
            self.assertEqual(response.status_code,400);self.assertIn('maintenance',response.json()['error'])

    def test_classroom_card_shows_partial_booking_for_a_mixed_week(self):
        booking=self.booking()
        self.assertEqual(self.act('HOD',booking,'approve').status_code,200)
        self.login('TEACHER')
        params={'campus':'VSP','building':'VSP|ICT','floor':'__unrecorded__',
                'date':self.day.isoformat(),'include_weekends':'1'}
        mixed=self.client.get(reverse('class_utilization'),params)
        self.assertEqual(mixed.context['classroom_cards'][0]['state'],'partial')
        self.assertContains(mixed,'cu-classroom-card cu-room-partial')
        params['date']=(self.day+timedelta(days=7)).isoformat()
        open_week=self.client.get(reverse('class_utilization'),params)
        self.assertEqual(open_week.context['classroom_cards'][0]['state'],'available')

    def test_maintenance_review_blocks_only_affected_slots_and_cancellation_preserves_bookings(self):
        from .models import ClassroomMaintenance
        booking=self.booking()
        self.assertEqual(self.act('HOD',booking,'approve').status_code,200)
        schedule=reverse('schedule_classroom_maintenance')
        payload={'scope':'room','campus':'VSP','building':'VSP|ICT','room':self.payload['room_key'],
                 'selections':[{'date':self.day.isoformat(),'start':'11:00','end':'14:00'}],
                 'duration':'short','reasons':['Electrical Issue'],'action':'preview'}
        for role_name in ('TEACHER','HOD','HOI'):
            self.login(role_name)
            self.assertEqual(self.client.post(schedule,payload,content_type='application/json').status_code,403)
            self.assertEqual(self.client.get(reverse('classroom_maintenance')).status_code,403)
        self.login('ADMIN')
        preview=self.client.post(schedule,payload,content_type='application/json')
        self.assertEqual(preview.status_code,200,preview.content)
        self.assertEqual([item['reference'] for item in preview.json()['affected']],[booking.pk])
        self.assertTrue(preview.json()['blocking'])
        self.assertEqual(self.client.post(schedule,{**payload,'action':'save','token':preview.json()['token']},
                                          content_type='application/json').status_code,400)
        payload['selections']=[{'date':self.day.isoformat(),'start':'13:00','end':'15:00'}]
        preview=self.client.post(schedule,payload,content_type='application/json')
        self.assertFalse(preview.json()['blocking'])
        confirmed={**payload,'action':'save','token':preview.json()['token']}
        tampered=self.client.post(schedule,{**confirmed,'duration':'long'},content_type='application/json')
        self.assertEqual(tampered.status_code,400)
        response=self.client.post(schedule,confirmed,content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        schedule_id=response.json()['id']
        self.assertEqual(self.client.post(schedule,payload,content_type='application/json').status_code,400)
        panel=self.client.get(reverse('class_utilization'),{'room':self.payload['room_key'],'timetable_popup':'1','date':self.day.isoformat(),'include_weekends':'1'})
        self.assertEqual(panel.headers['X-Frame-Options'],'SAMEORIGIN')
        self.assertContains(panel,'data-cm-mode="timetable"')
        self.assertContains(panel,'data-cm-day=')
        self.assertContains(panel,'data-cm-slot')
        self.assertContains(self.client.get(reverse('classroom_maintenance')),'Electrical Issue')
        self.login('TEACHER')
        blocked={**self.payload,'from_time':'13:00','to_time':'14:00'}
        availability=reverse('classroom_availability')
        result=self.client.get(availability,blocked)
        self.assertEqual(result.status_code,400,result.content)
        self.assertIn('maintenance',result.json()['error'])
        self.assertEqual(self.client.get(availability,{**blocked,'from_time':'15:00','to_time':'16:00'}).status_code,200)
        timetable=self.client.get(reverse('class_utilization'),{'room':self.payload['room_key'],'date':self.day.isoformat(),'include_weekends':'1'})
        self.assertContains(timetable,'Classroom maintenance windows')
        self.assertContains(timetable,'Electrical Issue')
        self.assertNotContains(timetable,'data-cm-start')
        finish=reverse('finish_classroom_maintenance',args=[schedule_id])
        self.assertEqual(self.client.post(finish,{'action':'cancel'},content_type='application/json').status_code,403)
        self.login('ADMIN')
        self.assertEqual(self.client.post(finish,{'action':'cancel','reason':'Repair rescheduled'},content_type='application/json').status_code,200)
        booking.refresh_from_db()
        self.assertEqual(booking.status,'confirmed')
        record=ClassroomMaintenance.objects.get(pk=schedule_id)
        self.assertEqual(record.history[-1]['reason'],'Repair rescheduled')
        self.assertEqual(record.windows.count(),1)
        self.login('TEACHER')
        self.assertEqual(self.client.get(availability,blocked).status_code,200)

    def test_maintenance_recurrence_uses_each_weekday_time_and_floor_scope(self):
        from .classroom_maintenance import maintenance_blocks
        from .models import ClassroomMaintenance
        catalog=_build_room_catalog([
            {'campus_code':'VSP','building_code':'ICT','room_code':'101','floor_code':'1'},
            {'campus_code':'VSP','building_code':'ICT','room_code':'102','floor_code':'1'},
            {'campus_code':'VSP','building_code':'ICT','room_code':'201','floor_code':'2'}])
        first=self.day;second=first+timedelta(days=1)
        payload={'scope':'floor','campus':'VSP','building':'VSP|ICT','floor':'1','recurrence':True,
                 'start_date':first.isoformat(),'end_date':(second+timedelta(days=7)).isoformat(),
                 'selections':[{'date':first.isoformat(),'start':'09:00','end':'12:00'},
                               {'date':second.isoformat(),'start':'13:00','end':'15:00'}],
                 'duration':'long','reasons':['Cleaning / Housekeeping'],'action':'preview'}
        self.login('ADMIN')
        url=reverse('schedule_classroom_maintenance')
        with patch('workspace.class_utilization._load_room_catalog',return_value=catalog):
            preview=self.client.post(url,payload,content_type='application/json')
            self.assertEqual(preview.status_code,200,preview.content)
            self.assertEqual(preview.json()['window_count'],4)
            result=self.client.post(url,{**payload,'action':'save','token':preview.json()['token']},content_type='application/json')
            self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(ClassroomMaintenance.objects.get().rooms.count(),2)
        self.assertTrue(maintenance_blocks('VSP|ICT|102',first,time(10),time(11)))
        self.assertFalse(maintenance_blocks('VSP|ICT|201',first,time(10),time(11)))
        self.assertFalse(maintenance_blocks('VSP|ICT|102',second,time(10),time(11)))
        self.assertTrue(maintenance_blocks('VSP|ICT|102',second+timedelta(days=7),time(13),time(14)))

    def test_maintenance_edit_custom_reason_and_explicit_completion(self):
        from datetime import datetime
        from django.utils import timezone
        from .classroom_maintenance import maintenance_blocks
        from .models import ClassroomMaintenance, ClassroomMaintenanceReason
        reason_url=reverse('classroom_maintenance_reason')
        self.login('HOI')
        self.assertEqual(self.client.post(reason_url,{'name':'Safety inspection'},content_type='application/json').status_code,403)
        self.login('ADMIN')
        self.assertEqual(self.client.post(reason_url,{'name':'Safety inspection'},content_type='application/json').status_code,200)
        self.client.post(reason_url,{'name':'safety inspection'},content_type='application/json')
        self.assertEqual(ClassroomMaintenanceReason.objects.count(),1)
        url=reverse('schedule_classroom_maintenance')
        payload={'scope':'building','campus':'VSP','building':'VSP|ICT','duration':'short','action':'preview',
                 'expected_completion':self.day.isoformat()+'T10:30',
                 'selections':[{'date':self.day.isoformat(),'start':'10:00','end':'13:00'}],'reasons':['Safety inspection']}
        def save(data):
            preview=self.client.post(url,data,content_type='application/json')
            self.assertEqual(preview.status_code,200,preview.content)
            result=self.client.post(url,{**data,'action':'save','token':preview.json()['token']},content_type='application/json')
            self.assertEqual(result.status_code,200,result.content)
            return result.json()['id']
        record_id=save(payload)
        active = self.client.get(reverse('classroom_maintenance'), {'status': 'active'})
        self.assertEqual(active.context['records'][record_id]['status'], 'Active')
        self.assertContains(active, '<th>Rq ID</th>')
        self.assertContains(active, 'data-cm-finish="complete"')
        self.assertNotContains(active, 'data-cm-finish="cancel"')
        updated={**payload,'id':record_id,'selections':[{'date':self.day.isoformat(),'start':'11:00','end':'13:00'}]}
        self.assertEqual(save(updated),record_id)
        self.assertFalse(maintenance_blocks(self.payload['room_key'],self.day,time(10),time(11)))
        current=timezone.make_aware(datetime.combine(self.day,time(12)))
        with patch('workspace.classroom_maintenance.local_now',return_value=current):
            self.assertTrue(maintenance_blocks(self.payload['room_key'],self.day,time(12),time(13)))
            active = self.client.get(reverse('classroom_maintenance'), {'status': 'active'})
            self.assertEqual(active.context['records'][record_id]['status'], 'Active')
        before_start = timezone.make_aware(datetime.combine(self.day,time(9)))
        with patch('workspace.classroom_maintenance.local_now',return_value=before_start):
            finish=reverse('finish_classroom_maintenance',args=[record_id])
            self.assertEqual(self.client.post(finish,{'action':'complete','reason':'Room checked'},content_type='application/json').status_code,200)
        record=ClassroomMaintenance.objects.get(pk=record_id)
        self.assertEqual([item['action'] for item in record.history],['Scheduled','Edited','Completed'])
        self.assertEqual(record.history[1]['previous']['selections'][0]['start'],'10:00')
        self.assertFalse(maintenance_blocks(self.payload['room_key'],self.day,time(12),time(13)))

    def test_maintenance_multi_select_scopes_and_disjoint_time_slots(self):
        from .classroom_maintenance import maintenance_blocks
        catalog=_build_room_catalog([
            {'campus_code':'VSP','building_code':'ICT','room_code':'101','floor_code':'1'},
            {'campus_code':'VSP','building_code':'ICT','room_code':'102','floor_code':'1'},
            {'campus_code':'VSP','building_code':'ICT','room_code':'201','floor_code':'2'},
            {'campus_code':'VSP','building_code':'ICT','room_code':'301','floor_code':'3'},
            {'campus_code':'VSP','building_code':'GIFT','room_code':'401','floor_code':'1'},
        ])
        payload={'scope':'floor','campus':'VSP','building':'VSP|ICT','targets':['1','2'],
                 'selections':[{'date':self.day.isoformat(),'start':start,'end':end}
                               for start,end in [('08:00','09:00'),('09:00','10:00'),('13:00','14:00')]],
                 'duration':'short','reasons':['Electrical Issue'],'action':'preview'}
        self.login('ADMIN')
        url=reverse('schedule_classroom_maintenance')
        with patch('workspace.class_utilization._load_room_catalog',return_value=catalog):
            invalid=self.client.post(url,{**payload,'scope':'room','floor':'1',
                'targets':['VSP|ICT|101','VSP|GIFT|401']},content_type='application/json')
            self.assertEqual(invalid.status_code,400)
            preview=self.client.post(url,payload,content_type='application/json')
            self.assertEqual(preview.status_code,200,preview.content)
            self.assertEqual(preview.json()['window_count'],2)
            self.assertEqual(set(preview.json()['room_codes']),{'101','102','201'})
            saved=self.client.post(url,{**payload,'action':'save','token':preview.json()['token']},content_type='application/json')
            self.assertEqual(saved.status_code,200,saved.content)
            picker=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'VSP|ICT','date':self.day.isoformat()})
            self.assertContains(picker,'data-cm-mode="floor"')
            self.assertContains(picker,'data-cm-card="2"')
            rooms=self.client.get(reverse('class_utilization'),{'campus':'VSP','building':'VSP|ICT','floor':'1','date':self.day.isoformat()})
            self.assertContains(rooms,'data-cm-mode="room"')
            self.assertContains(rooms,'data-cm-card="VSP|ICT|102"')
            room_payload = {
                **payload, 'scope': 'room', 'targets': ['VSP|ICT|101'],
                'selections': [{'date': self.day.isoformat(), 'start': '15:00', 'end': '16:00'}],
            }
            preview = self.client.post(url, room_payload, content_type='application/json')
            self.assertEqual(preview.status_code, 200, preview.content)
            created = self.client.post(url, {**room_payload, 'action': 'save', 'token': preview.json()['token']},
                                       content_type='application/json')
            self.assertEqual(created.status_code, 200, created.content)
            record_id = created.json()['id']
            edited = {**room_payload, 'id': record_id, 'targets': ['VSP|ICT|102']}
            preview = self.client.post(url, edited, content_type='application/json')
            self.assertEqual(preview.status_code, 200, preview.content)
            result = self.client.post(url, {**edited, 'action': 'save', 'token': preview.json()['token']},
                                      content_type='application/json')
            self.assertEqual(result.status_code, 200, result.content)
            records = self.client.get(reverse('classroom_maintenance')).context['records']
            self.assertEqual(records[record_id]['history'][-1]['previous']['room_codes'], ['101'])
            self.assertEqual(records[record_id]['room_codes'], ['102'])
            self.assertFalse(maintenance_blocks('VSP|ICT|101', self.day, time(15), time(16)))
            self.assertTrue(maintenance_blocks('VSP|ICT|102', self.day, time(15), time(16)))
        self.assertTrue(maintenance_blocks('VSP|ICT|201',self.day,time(9),time(10)))
        self.assertTrue(maintenance_blocks('VSP|ICT|101',self.day,time(13),time(14)))
        self.assertFalse(maintenance_blocks('VSP|ICT|101',self.day,time(10),time(13)))
        self.assertFalse(maintenance_blocks('VSP|ICT|301',self.day,time(8),time(10)))

    def test_timetable_maintenance_accepts_available_slots_and_validates_dates(self):
        from .models import ClassroomMaintenanceWindow
        booking=self.booking()
        self.assertEqual(self.act('HOD',booking,'approve').status_code,200)
        self.login('ADMIN')
        day=self.day.isoformat()
        next_week=(self.day+timedelta(days=7)).isoformat()
        payload={'scope':'room','campus':'VSP','building':'VSP|ICT','room':self.payload['room_key'],
                 'timetable_selection':True,
                 'selections':[{'date':day,'start':'13:00','end':'14:00'},
                               {'date':day,'start':'14:00','end':'15:00'},
                               {'date':next_week,'start':'09:00','end':'10:00'}],
                 'starts_at':day+'T13:00','expected_completion':next_week+'T10:00',
                 'reasons':['Electrical Issue'],'action':'preview'}
        url=reverse('schedule_classroom_maintenance')
        invalid=self.client.post(url,{**payload,'expected_completion':day+'T11:00'},content_type='application/json')
        self.assertEqual(invalid.status_code,400)
        booked=self.client.post(url,{**payload,'booking_ids':[booking.pk]},content_type='application/json')
        self.assertEqual(booked.status_code,400)
        preview=self.client.post(url,payload,content_type='application/json')
        self.assertEqual(preview.status_code,200,preview.content)
        self.assertFalse(preview.json()['blocking'])
        saved=self.client.post(url,{**payload,'action':'save','token':preview.json()['token']},content_type='application/json')
        self.assertEqual(saved.status_code,200,saved.content)
        self.assertEqual(list(ClassroomMaintenanceWindow.objects.filter(maintenance_id=saved.json()['id'])
                              .values_list('date','start','end')),[
            (self.day,time(13),time(14)),(self.day,time(14),time(15)),
            (date.fromisoformat(next_week),time(9),time(10)),
        ])
        booking.refresh_from_db()
        self.assertEqual(booking.status,'confirmed')

    def test_room_and_floor_maintenance_require_acknowledgement_of_approved_booking(self):
        from .classroom_maintenance import maintenance_blocks
        booking=self.booking()
        self.assertEqual(self.act('HOD',booking,'approve').status_code,200)
        self.login('ADMIN')
        payload={'scope':'floor','campus':'VSP','building':'VSP|ICT','floor':'__unrecorded__',
                 'selections':[{'date':self.day.isoformat(),'start':'08:00','end':'16:00'}],
                 'reasons':['Electrical Issue'],'action':'preview'}
        url=reverse('schedule_classroom_maintenance')
        for scope in ('floor','room'):
            with self.subTest(scope=scope):
                request_data={**payload,'scope':scope,'room':self.payload['room_key']}
                preview=self.client.post(url,request_data,content_type='application/json')
                self.assertEqual(preview.status_code,200,preview.content)
                self.assertTrue(preview.json()['blocking'])
                save={**request_data,'action':'save','token':preview.json()['token']}
                self.assertEqual(self.client.post(url,save,content_type='application/json').status_code,400)
                accepted=self.client.post(url,{**save,'acknowledge_overlaps':True},content_type='application/json')
                self.assertEqual(accepted.status_code,200,accepted.content)
                self.assertTrue(maintenance_blocks(self.payload['room_key'],self.day,time(12),time(13)))
                booking.refresh_from_db()
                self.assertEqual(booking.status,'confirmed')
                finish=reverse('finish_classroom_maintenance',args=[accepted.json()['id']])
                self.assertEqual(self.client.post(finish,{'action':'cancel'},content_type='application/json').status_code,200)

    def test_maintenance_day_controls_require_an_eligible_booking(self):
        from datetime import datetime
        thursday=date(2026,11,19)
        for day,start,end,status in [
            (date(2026,11,18),8,9,'confirmed'),
            (thursday,8,9,'confirmed'),
            (thursday,9,11,'confirmed'),
            (date(2026,11,20),9,10,'pending'),
            (date(2026,11,21),9,10,'confirmed'),
        ]:
            Booking.objects.create(booked_by=self.users['TEACHER'],booking_date=day,from_time=time(start),to_time=time(end),
                status=status,campus_code='VSP',building_name='ICT Block',room_code='101',room_key=self.payload['room_key'])
        self.login('ADMIN')
        with patch('workspace.class_utilization.timezone.now',return_value=datetime.combine(thursday,time(10,30))), patch(
                'workspace.class_utilization._load_semester_choices',return_value=['2026-2027#ODD']):
            response=self.client.get(reverse('class_utilization'),{'room':self.payload['room_key'],
                'date':thursday.isoformat(),'include_weekends':'1','timetable_popup':'1'})
        self.assertContains(response,'data-cm-day="2026-11-19"',count=1)
        self.assertContains(response,'data-cm-day="2026-11-21"',count=1)
        self.assertNotContains(response,'data-cm-day="2026-11-18"')
        self.assertContains(response,'data-cm-day="2026-11-20"',count=1)
        self.assertContains(response,'data-id="open:2026-11-20:08:00"')
        self.assertNotContains(response,'data-id="open:2026-11-20:09:00"')
        self.assertNotContains(response,'data-id="open:2026-11-19:10:00"')
        self.assertNotContains(response,'data-id="open:2026-11-18:')
        self.assertNotContains(response,'cm-booking-choice')

    def test_timetable_shows_passed_for_empty_hours_earlier_today(self):
        from datetime import datetime
        today=date(2026,11,19)
        self.login('TEACHER')
        with patch('workspace.class_utilization.timezone.now',return_value=datetime.combine(today,time(12))), patch(
                'workspace.class_utilization._load_semester_choices',return_value=['2026-2027#ODD']):
            response=self.client.get(reverse('class_utilization'),{'room':self.payload['room_key'],'date':today.isoformat()})
        html=response.content.decode()
        self.assertNotRegex(html, r'data-date="2026-11-19"\s+data-start="(?:08|09|10|11):00"')
        self.assertRegex(html, r'data-date="2026-11-19"\s+data-start="12:00"')
        thursday_cells = re.findall(r'<td data-day="Thursday"[^>]*>(.*?)</td>', html, re.S)
        self.assertGreaterEqual(len(thursday_cells), 5)
        for cell in thursday_cells[:4]:
            self.assertIn('<span class="cu-no-availability">Passed</span>', cell)

    def test_common_holidays_database_records_and_scope(self):
        from .models import PublicHoliday
        from .holidays import _database_calendar, closures_on
        _database_calendar.cache_clear()
        self.assertEqual(PublicHoliday.objects.filter(year=2026).count(),13)
        for campus in ('VSP','HYD','BLR'):
            self.assertEqual([h['name'] for h in closures_on(date(2026,12,25),campus)],['Christmas'])
            self.assertEqual(closures_on(date(2026,12,24),campus),[])
        self.assertEqual([h['name'] for h in closures_on(date(2026,1,26),'VSP')],['Republic Day'])
        self.assertEqual(list(PublicHoliday.objects.filter(date__gt=date(2026,11,17)).values_list('name',flat=True)),['Christmas'])

    def test_christmas_full_column_all_campuses_and_week_navigation(self):
        from .holidays import _database_calendar
        _database_calendar.cache_clear()
        self.login('ADMIN')
        catalog=_build_room_catalog([{'campus_code':campus,'building_code':'ICT','building_name':'ICT Block',
            'room_code':'101','room_name':'ICT 101','capacity':40} for campus in ('VSP','HYD','BLR')])
        with patch('workspace.class_utilization._load_room_catalog',return_value=catalog):
            for campus in ('VSP','HYD','BLR'):
                report=self.client.get(reverse('class_utilization'),{'date':'2026-12-25','campus':campus,'room':campus+'|ICT|101'})
                self.assertEqual(report.status_code,200)
                friday=next(h for h in report.context['day_headers'] if h['day']=='Friday')
                self.assertTrue(friday['is_holiday'])
                self.assertContains(report,'PUBLIC HOLIDAY')
                self.assertContains(report,'CHRISTMAS')
                self.assertContains(report,'25 December 2026')
                self.assertContains(report,'class="cu-holiday-message"',count=1)
                self.assertNotContains(report,'class="cu-holiday-cell"')
                self.assertContains(report,'Public Holiday &ndash; No classroom bookings available')
                for row in report.context['grid_rows']:
                    for cell in row['cells']:
                        if cell['booking_date']=='2026-12-25':
                            self.assertTrue(cell['is_holiday']);self.assertEqual(cell['free_rooms'],[])
                        if cell['booking_date']=='2026-12-24':self.assertFalse(cell['is_holiday'])
                previous=self.client.get(reverse('class_utilization')+report.context['previous_week_url'])
                self.assertNotContains(previous,'CHRISTMAS')
                self.assertNotContains(report,'Optional holiday (information only)')

    def test_christmas_blocks_new_and_revised_bookings_preserves_original(self):
        from .holidays import _database_calendar
        _database_calendar.cache_clear()
        self.assertEqual(self.submit(booking_date='2026-12-25').status_code,400)
        booking=self.booking()
        self.assertEqual(self.act('ADMIN',booking,'request_changes',comment='Select another day').status_code,200)
        booking.refresh_from_db()
        draft=self._revision_draft(booking)
        selected=self.client.post(reverse('booking_revision_select'),{**self.payload,'booking_date':'2026-12-25','revision_token':draft['token']})
        self.assertEqual(selected.status_code,400)
        self.assertIn('Christmas',selected.json()['error'])
        response=self.client.post(reverse('review_classroom_booking'),{**self.payload,'booking_date':'2026-12-25',
            'action':'edit','booking_id':booking.pk,'revision_token':draft['token'],'expected_revision':booking.modified_at.isoformat()})
        self.assertEqual(response.status_code,400)
        booking.refresh_from_db();self.assertEqual(booking.booking_date,self.day)
        self.assertEqual(booking.status,'changes_requested')

    def test_optional_holiday_remains_informational_and_available(self):
        from .holidays import validate_calendar
        calendar=validate_calendar({'years':{str(self.day.year):{'source':'Test fixture only',
            'holidays':[{'name':'Fixture optional date','date':self.day.isoformat(),'category':'optional','campuses':[]}]}}})
        self.login('TEACHER')
        with patch('workspace.holidays.calendar_data',return_value=calendar):
            self.assertEqual(self.client.get(reverse('classroom_availability'),self.payload).status_code,200)
            report=self.client.get(reverse('class_utilization'),{'date':self.day.isoformat(),'campus':'VSP','building':'VSP|ICT','room':self.payload['room_key'],'include_weekends':'1'})
            header=next(header for header in report.context['day_headers'] if header['day']==self.day.strftime('%A'))
            self.assertTrue(header['has_optional']);self.assertFalse(header['is_holiday'])
            self.assertEqual(self.client.post(reverse('book_classroom'),self.payload).status_code,201)

    def test_all_closed_status_rows_are_view_only_for_all_roles(self):
        booking=self.booking()
        for status in ('hod_rejected','admin_rejected','hod_approved','confirmed','withdrawn','cancelled'):
            booking.status=status;booking.save(update_fields=['status'])
            for active in ('TEACHER','HOD','ADMIN','HOI'):
                with self.subTest(status=status,role=active):
                    self.login(active)
                    html=self.client.get(reverse('classroom_requests')).content.decode()
                    self.assertIn('data-view="'+str(booking.pk)+'"',html)
                    self.assertNotIn('data-booking-menu=',html)
                    self.assertNotIn('class="bw-row-menu"',html)

    def test_response_form_contains_reviewer_comments_and_keeps_revision(self):
        b=self.booking();self.act('ADMIN',b,'request_changes',comment='Please use classroom 102')
        self.login('TEACHER')
        response=self.client.get(reverse('booking_edit_data'),{'booking_id':b.pk})
        data=response.json();self.assertEqual(data['status'],'changes_requested')
        self.assertEqual(data['review_comments'][0]['role'],'ADMIN')
        self.assertIn('Please use classroom 102',data['review_comments'][0]['comment'])
        self.assertEqual(self.act('TEACHER',b,'edit',expected_revision=data['revision'],**self.payload).status_code,200)
        b.refresh_from_db();self.assertEqual(b.status,'pending')
        self.assertEqual(b.history.filter(action='Resubmitted').count(),1)

    def test_admin_booking_navigation_groups_existing_pages_only_for_admin(self):
        for active in ('ADMIN','HOD','HOI','TEACHER'):
            self.login(active)
            response=self.client.get(reverse('class_utilization'))
            self.assertEqual(response.status_code,200)
            if active=='ADMIN':
                self.assertContains(response,'aria-label="Booking Analytics pages"')
                html=response.content.decode()
                group=html.split('aria-label="Booking Analytics pages"',1)[1].split('</ul>',1)[0]
                self.assertIn(reverse('class_utilization'),group)
                self.assertIn(reverse('classroom_requests'),group)
            else:self.assertNotContains(response,'aria-label="Booking Analytics pages"')

    def test_utilization_charts_move_to_analytics_and_keep_summary_cards(self):
        self.login('ADMIN')
        timetable=self.client.get(reverse('class_utilization'),{'room':self.payload['room_key']})
        self.assertNotContains(timetable,'Classroom Utilization Heatmap')
        self.assertNotContains(timetable,'Utilization by Building')
        self.assertContains(timetable,'Total Classrooms')
        analytics=self.client.get(reverse('booking_analytics'),{'start':self.day.isoformat(),'end':self.day.isoformat()})
        self.assertContains(analytics,'Classroom Utilization Heatmap')
        self.assertContains(analytics,'Utilization by Building')
        room_analytics=self.client.get(reverse('booking_analytics'),{
            'start':self.day.isoformat(),'end':self.day.isoformat(),'util_room':self.payload['room_key']})
        self.assertContains(room_analytics,'Classroom Occupancy by Hour')
        self.assertContains(room_analytics,'id="ba-room-usage-chart"')
        self.assertContains(room_analytics,'id="ba-room-window-chart"')
        self.assertNotContains(room_analytics,'Utilization by Building')
        self.assertContains(room_analytics,'id="ba-no-bookings"')
        self.assertContains(analytics,'id="ba-trend-style"')
        self.assertContains(analytics,'id="ba-demand-chart"')
        self.assertContains(analytics,'id="ba-duration-chart"')
        self.assertContains(analytics,'<select name="util_campus"')
        self.assertContains(analytics,'<select name="util_building"')
        self.assertContains(analytics,'<select name="util_room"')
        self.assertNotContains(analytics,'<select name="util_department"')
        self.assertNotContains(analytics,'<input name="util_campus"')
        self.assertNotContains(analytics,'Click any bar, slice or row to filter')
        self.assertNotContains(analytics,'id="ba-dates"')
        self.assertLess(analytics.content.index(b'id="ba-cards"'),analytics.content.index(b'Classroom Utilization Heatmap'))
        self.assertLess(analytics.content.index(b'id="ba-utilization-filters"'),analytics.content.index(b'id="ba-cards"'))
        self.assertEqual(analytics.context['util_options']['campuses'],['VSP'])
        filtered=self.client.get(reverse('booking_analytics'),{'start':self.day.isoformat(),'end':self.day.isoformat(),'util_room':self.payload['room_key']})
        self.assertEqual(filtered.context['design_summary']['rooms'],1)
        self.assertEqual(len(analytics.context['design_summary']['heatmap']),5)
        self.assertEqual(len(analytics.context['design_summary']['hours']),8)
        empty=self.client.get(reverse('booking_analytics'),{'start':self.day.isoformat(),'end':self.day.isoformat(),'util_campus':'NO_MATCH'})
        self.assertEqual(empty.context['design_summary']['rooms'],0)

    def test_compact_table_and_feedback_modal(self):
        b=self.booking()
        self.act('HOD',b,'request_changes',comment='Please use the larger classroom')
        self.login('TEACHER')
        response=self.client.get(reverse('classroom_requests'))
        html=response.content.decode()
        self.assertEqual(len(re.findall(r'<th>', html)), 6)
        self.assertNotContains(response, 'Approval Progress')
        self.assertContains(response, 'Approval Timeline')
        self.assertContains(response, 'Comments and Feedback')
        self.assertContains(response, 'Please use the larger classroom')
        self.assertNotContains(response, 'bookingNotificationBell')
        table=re.search(r'<tbody>(.*?)</tbody>', html, re.S).group(1)
        table=re.sub(r'<template.*?</template>', '', table, flags=re.S)
        self.assertNotIn('Please use the larger classroom', table)

    def test_withdrawn_approval_stages_are_not_awaiting(self):
        b=self.booking()
        self.act('TEACHER',b,'withdraw',comment='No longer needed')
        b.refresh_from_db()
        self.assertEqual(b.hod_progress_label,'Not Required')
        self.assertEqual(b.admin_progress_label,'Not Required')

    def test_activity_page_is_scoped_and_paginated(self):
        b=self.booking()
        self.login('HOD')
        response=self.client.get(reverse('booking_activity'))
        self.assertContains(response,'Notifications &amp; Activity')
        self.assertContains(response,'View booking')
        self.assertContains(response,'Unread')
        self.assertNotContains(response,'bookingNotificationBell')
        self.login('HOI')
        response=self.client.get(reverse('booking_activity'))
        self.assertNotContains(response,'data-notice-id=')
        self.assertEqual(self.client.get(reverse('booking_activity')+'?page=invalid').status_code,200)

    def test_failed_history_or_notification_rolls_back_booking_edit(self):
        b=self.booking()
        from django.db import DatabaseError
        with patch('workspace.booking_notifications.notify_event',side_effect=DatabaseError('Notification storage unavailable')):
            response=self.act('TEACHER',b,'edit',**{**self.payload,'purpose':'Must roll back'})
        self.assertEqual(response.status_code,503)
        b.refresh_from_db();self.assertEqual(b.purpose,'Extra teaching session');self.assertEqual(b.history.count(),1)


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.test import TransactionTestCase
from .booking_workflow import lock_bookings as original_lock


class ConcurrentBookingTests(TransactionTestCase):
    def setUp(self):
        BookingWorkflowTests.setUpTestData.__func__(type(self))
        BookingWorkflowTests.setUp(self)

    def test_simultaneous_admin_confirmations_create_one_reservation(self):
        barrier = Barrier(2)
        def locked():
            barrier.wait(timeout=10)
            original_lock()
        def submit():
            close_old_connections()
            try:
                from django.test import RequestFactory
                from .booking_workflow import book_classroom
                request = RequestFactory().post('/workspace/book_classroom', self.payload)
                request.user = self.users['ADMIN']
                return book_classroom(request).status_code
            finally:
                close_old_connections()
        with patch('workspace.booking_workflow.lock_bookings', side_effect=locked):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(results.count(201),1,results)
        self.assertTrue(all(code in (201,400,503) for code in results),results)
        self.assertEqual(Booking.objects.filter(status='confirmed').count(),1)

    def test_simultaneous_faculty_requests_create_one_pending_hold(self):
        barrier = Barrier(2)
        def locked():
            barrier.wait(timeout=10)
            original_lock()
        def submit(user):
            close_old_connections()
            try:
                from django.test import RequestFactory
                from .booking_workflow import book_classroom
                request = RequestFactory().post('/workspace/book_classroom', self.payload)
                request.user = user
                response = book_classroom(request)
                return response.status_code, json.loads(response.content)
            finally:
                close_old_connections()
        with patch('workspace.booking_workflow.lock_bookings', side_effect=locked):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, [self.users['TEACHER'], self.other]))
        self.assertEqual(sum(code == 201 for code, body in results), 1, results)
        self.assertTrue(all(code in (201, 400, 503) for code, body in results), results)
        self.assertEqual(Booking.objects.filter(status='pending').count(), 1)
        self.assertEqual(ClassroomBookingHistory.objects.filter(action='Submitted').count(), 1)

    def test_hod_and_admin_simultaneous_decisions_only_one_is_applied(self):
        from django.test import RequestFactory
        from .booking_workflow import book_classroom, review_classroom_booking
        create=RequestFactory().post('/workspace/book_classroom',self.payload)
        create.user=self.users['TEACHER']
        self.assertEqual(book_classroom(create).status_code,201)
        booking=Booking.objects.get();revision=booking.modified_at.isoformat()
        barrier=Barrier(2)
        def locked():
            barrier.wait(timeout=10)
            original_lock()
        def decide(values):
            active,action=values
            close_old_connections()
            try:
                request=RequestFactory().post('/workspace/review_classroom_booking',{
                    'booking_id':booking.pk,'action':action,'comment':'Concurrent decision','expected_revision':revision})
                request.user=self.users[active]
                return review_classroom_booking(request).status_code
            finally:
                close_old_connections()
        with patch('workspace.booking_workflow.lock_bookings',side_effect=locked):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(decide,[('HOD','approve'),('ADMIN','reject')]))
        self.assertEqual(results.count(200),1,results)
        self.assertTrue(all(code in (200,409,503) for code in results),results)
        booking.refresh_from_db()
        self.assertIn(booking.status,('confirmed','admin_rejected'))
        self.assertEqual(booking.history.exclude(action='Submitted').count(),1)

    def test_revision_resubmission_and_competing_booking_cannot_both_hold_same_slot(self):
        from django.test import RequestFactory
        from .booking_workflow import book_classroom,review_classroom_booking
        from .booking_revisions import SESSION_KEY
        request=RequestFactory().post('/workspace/book_classroom',self.payload)
        request.user=self.users['TEACHER'];self.assertEqual(book_classroom(request).status_code,201)
        booking=Booking.objects.get()
        request=RequestFactory().post('/workspace/review_classroom_booking',{
            'booking_id':booking.pk,'action':'request_changes','comment':'Choose another time'})
        request.user=self.users['ADMIN'];self.assertEqual(review_classroom_booking(request).status_code,200)
        booking.refresh_from_db()
        client=Client();client.force_login(self.users['TEACHER'])
        draft=client.post(reverse('booking_revision_start'),{'booking_id':booking.pk,'purpose':'Revision purpose'}).json()
        selected=client.post(reverse('booking_revision_select'),{**self.payload,'from_time':'14:00','to_time':'16:00','duration_hours':'2','revision_token':draft['token']})
        self.assertEqual(selected.status_code,200)
        saved=client.get(reverse('booking_revision_state'),{'revision':draft['token']}).json()
        session_data={SESSION_KEY:dict(client.session[SESSION_KEY])}
        barrier=Barrier(2)
        def locked():
            barrier.wait(timeout=10);original_lock()
        def submit(revising):
            close_old_connections()
            try:
                if revising:
                    request=RequestFactory().post('/workspace/review_classroom_booking',{
                        **saved['initial'],'booking_id':booking.pk,'action':'edit','revision_token':draft['token'],
                        'expected_revision':saved['revision']})
                    request.user=self.users['TEACHER'];request.session=dict(session_data)
                    response=review_classroom_booking(request)
                else:
                    request=RequestFactory().post('/workspace/book_classroom',{
                        **self.payload,'from_time':'14:00','to_time':'16:00','duration_hours':'2'})
                    request.user=self.other;response=book_classroom(request)
                return response.status_code
            finally:
                close_old_connections()
        with patch('workspace.booking_workflow.lock_bookings',side_effect=locked):
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,[True,False]))
        self.assertEqual(sum(code in (200,201) for code in results),1,results)
        self.assertTrue(all(code in (200,201,400,503) for code in results),results)
        self.assertEqual(Booking.objects.filter(status='pending',from_time=time(14),to_time=time(16)).count(),1)
