from django.conf import settings
from django.db import models
from usermanagement.models import *
# ==========================
# CAMPUS
# ==========================
class Campus(models.Model):
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'workspace_campus'

    def __str__(self):
        return self.name


# ==========================
# BUILDING
# ==========================
class BuildingStatus(models.Model):
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'workspace_building_status'

    def __str__(self):
        return self.name


class Building(models.Model):
    campus = models.ForeignKey(
        Campus,
        on_delete=models.CASCADE,
        related_name="Building_campus"
    )
    building_status = models.ForeignKey(
        BuildingStatus,
        on_delete=models.CASCADE,
        related_name="Building_building_status",null=True
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20)
    total_floors = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    createdby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="Building_created_by",null=True,blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'workspace_building'
    def __str__(self):
        return f"{self.name} ({self.campus})"


# ==========================
# BLOCK (OPTIONAL)
# ==========================
class BlockType(models.Model):
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'workspace_block_type'

    def __str__(self):
        return self.name

class Block(models.Model):
    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="Block_building",null=True,blank=True
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.CASCADE,
        related_name="Block_campus",null=True,blank=True
    )
    block_type = models.ForeignKey(
        BlockType,
        on_delete=models.CASCADE,
        related_name="Block_block_type",null=True,blank=True
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    createdby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="Block_created_by",null=True,blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'workspace_block'

    def __str__(self):
        return f"{self.name} - {self.building}"


# ==========================
# FLOOR
# ==========================
class Floor(models.Model):
    campus = models.ForeignKey(
        Campus,
        on_delete=models.CASCADE,
        related_name="Floor_campus",
        null=True, blank=True
    )

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="Floor_building"
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="Floor_block"
    )
    floor_number = models.IntegerField()
    floor_label  = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    createdby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="Floor_created_by",null=True,blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'workspace_floor'

    def __str__(self):
        return f"{self.name}"


# ==========================
# ROOM
# ==========================
class RoomType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'workspace_room_type'

    def __str__(self):
        return self.name

class Room(models.Model):
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.PROTECT,
        related_name="Room_room_type"
    )
    room_number = models.CharField(max_length=50)
    room_name = models.CharField(max_length=150, blank=True, null=True)
    floor = models.ForeignKey(
        Floor,
        on_delete=models.CASCADE,
        related_name="Room_floor",null=True,blank=True
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.CASCADE,
        related_name="Room_campus",
        null=True, blank=True
    )

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="Room_building",
         null = True, blank = True
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="Room_block"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    createdby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="Room_created_by",null=True,blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'workspace_room'

    def __str__(self):
        return self.room_number


# ==========================
# SEAT
# ==========================
class SeatType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    icon = models.CharField(max_length=60, default="bx bx-chair",null=True)
    color = models.CharField(max_length=10, default="#9CA3AF",null=True)
    class Meta:
        db_table = 'workspace_seat_type'

    def __str__(self):
        return self.name

class SeatStatus(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'workspace_seat_status'

    def __str__(self):
        return self.name

class Seat(models.Model):
    seat_type = models.ForeignKey(
        SeatType,
        on_delete=models.CASCADE,
        related_name="seats"
    )
    seat_status = models.ForeignKey(
        SeatStatus,
        on_delete=models.CASCADE,
        related_name="seats"
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="Seat_room"
    )
    current_empid = models.CharField(max_length=50, null=True, blank=True)
    seat_number = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    createdby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="Seat_created_by",null=True,blank=True
    )
    updatedby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="Seat_updatedby", null=True, blank=True
    )

    class Meta:
        db_table = 'workspace_seat'

    def __str__(self):
        return self.seat_number

class SeatHistory(models.Model):
    seat = models.ForeignKey(
        Seat,
        on_delete=models.CASCADE,
        related_name="SeatHistory_seat"
    )
    previous_seat_number = models.CharField(max_length=50)
    current_seat_number = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    createdby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="SeatHistory_created_by",null=True,blank=True
    )
    class Meta:
        db_table = 'workspace_seat_history'
# ==========================
# SEAT ALLOCATION
# ==========================
class SeatAllocationHistory(models.Model):
    empid = models.CharField(max_length=50,null=True,blank=True)
    campus = models.CharField(max_length=100, null=True)
    college_code = models.CharField(max_length=100, null=True)
    dept_code = models.CharField(max_length=100, null=True)
    designation = models.CharField(max_length=100, null=True)
    seat = models.ForeignKey(
        Seat,
        on_delete=models.CASCADE,
        related_name="SeatAllocation_seat"
    )
    allocated_date = models.DateTimeField(auto_now_add=True)
    released_date = models.DateTimeField(null=True, blank=True)

    seat_status = models.ForeignKey(
        SeatStatus,null=True,blank=True,
        on_delete=models.CASCADE,
        related_name="SeatAllocation_seat_status"
    )

    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    createdby = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="SeatAllocation_created_by",null=True,blank=True
    )
    class Meta:
        db_table = 'workspace_seat_allocation_history'

    def __str__(self):
        return f"{self.empid} -> {self.seat}"


class EmployeeAccessPermission(models.Model):
    user   = models.ForeignKey(User,   on_delete=models.CASCADE, null=True, blank=True, related_name='AccessPermission_user')

    campus   = models.ForeignKey(Campus,   on_delete=models.CASCADE, null=True, blank=True, related_name='AccessPermission_campus')
    building = models.ForeignKey(Building, on_delete=models.CASCADE, null=True, blank=True, related_name='AccessPermission_building')
    block    = models.ForeignKey(Block,    on_delete=models.CASCADE, null=True, blank=True, related_name='AccessPermission_block')
    floor    = models.ForeignKey(Floor,    on_delete=models.CASCADE, null=True, blank=True, related_name='AccessPermission_floor')
    room     = models.ForeignKey(Room,     on_delete=models.CASCADE, null=True, blank=True, related_name='AccessPermission_room')

    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    createdby  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='AccessPermission_created_by')

    class Meta:
        db_table = 'workspace_employee_access_permission'

    def __str__(self):
        return f"{self.user}"


class ClassroomBooking(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending HOD Approval'),
        ('hod_approved', 'Approved by HOD'),
        ('hod_rejected', 'Rejected by HOD'),
        ('confirmed', 'Confirmed by Admin'),
        ('admin_rejected', 'Rejected by Admin'),
        ('cancelled', 'Cancelled'),
        ('changes_requested', 'Changes Requested'),
        ('withdrawn', 'Withdrawn by Faculty'),
    )

    campus_code = models.CharField(max_length=20)
    building_name = models.CharField(max_length=150)
    room_code = models.CharField(max_length=50)
    semester_flag = models.CharField(max_length=30)
    booking_date = models.DateField()
    from_time = models.TimeField()
    to_time = models.TimeField()
    duration_hours = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=150)
    purpose = models.TextField()
    details = models.TextField(blank=True)
    teacher_name = models.CharField(max_length=150, blank=True)
    teacher_id = models.CharField(max_length=50, blank=True)
    teacher_email = models.EmailField(blank=True)
    subject_code = models.CharField(max_length=50, blank=True)
    subject_name = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    booking_source = models.CharField(max_length=30, default='teacher_request')
    room_key = models.CharField(max_length=250, blank=True)
    modified_at = models.DateTimeField(auto_now=True)
    confirmed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='confirmed_classroom_bookings')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    admin_comment = models.TextField(blank=True)
    admin_decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='admin_decided_bookings')
    admin_decided_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='withdrawn_classroom_bookings')
    review_comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_classroom_bookings',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requester_department = models.CharField(max_length=100, blank=True)
    requester_campus = models.CharField(max_length=50, blank=True)
    booked_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='classroom_bookings',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    @property
    def hod_decision_label(self):
        if self.status in ('withdrawn', 'cancelled'):
            return 'Not required'
        if self.status == 'pending':
            return 'Awaiting HOD'
        for entry in reversed(list(self.history.all())):
            if entry.user_role == 'HOD' and entry.action in ('Approved', 'Rejected', 'Changes Requested'):
                return {'Approved':'Approved by HOD','Rejected':'Rejected by HOD','Changes Requested':'Changes Requested'}.get(entry.action)
        if self.booking_source == 'admin_direct' or (self.status == 'confirmed' and self.confirmed_by_id):
            return 'Not required'
        return 'Awaiting HOD'

    @property
    def admin_decision_label(self):
        if self.status in ('withdrawn', 'cancelled', 'hod_rejected'):
            return 'Not required'
        if self.status == 'pending':
            return 'Awaiting Admin'
        if self.status == 'confirmed' and self.confirmed_by_id == self.reviewed_by_id:
            return 'Not required'
        for entry in reversed(list(self.history.all())):
            if entry.user_role == 'ADMIN':
                return {'Confirmed':'Confirmed by Admin', 'Rejected':'Rejected by Admin', 'Cancelled':'Cancelled by Admin', 'Modified':'Modified by Admin','Changes Requested':'Changes Requested'}.get(entry.action, entry.action)
        return 'Awaiting Admin'

    @property
    def hod_progress_label(self):
        return {'Approved by HOD':'Approved', 'Rejected by HOD':'Rejected', 'Not required':'Not Required'}.get(self.hod_decision_label, self.hod_decision_label)

    @property
    def admin_progress_label(self):
        if self.status == 'confirmed':
            return 'Confirmed'
        return {'Confirmed by Admin':'Confirmed', 'Rejected by Admin':'Rejected', 'Not required':'Not Required'}.get(self.admin_decision_label, self.admin_decision_label)

    @property
    def feedback_groups(self):
        groups = {}
        for event in self.history.all():
            detail = event.display_details
            snapshots = [item for item in detail['snapshots'] if item['title'] != 'Booking details']
            if not detail['comments'] and not snapshots:
                continue
            actor = event.performed_by
            key = event.performed_by_id
            group = groups.setdefault(key, {'person': (actor.get_full_name() or actor.username) if actor else 'Former user', 'items': []})
            group['items'].append({'action':event.action, 'role':event.user_role, 'date':event.created_at, 'comments':detail['comments'], 'snapshots':snapshots})
        return list(groups.values())

    @property
    def management_status_label(self):
        if self.status == 'pending':
            events = list(self.history.all())
            return 'Resubmitted / Pending Approval' if events and events[-1].action == 'Resubmitted' else 'Pending Approval'
        return {'hod_approved':'Approved', 'confirmed':'Confirmed', 'hod_rejected':'Rejected',
                'admin_rejected':'Rejected', 'changes_requested':'Changes Requested',
                'withdrawn':'Withdrawn', 'cancelled':'Cancelled'}.get(self.status, self.get_status_display())

    @property
    def faculty_can_edit(self):
        return self.booking_source == 'teacher_request' and self.status in ('pending','changes_requested')

    @property
    def can_request_changes(self):
        return self.booking_source == 'teacher_request' and self.status == 'pending'

    @property
    def pending_change(self):
        return next((item for item in self.change_requests.all() if item.status == 'pending'), None)

    class Meta:
        db_table = 'workspace_classroom_booking'
        ordering = ('booking_date', 'from_time')
        indexes = [
            models.Index(
                fields=('campus_code', 'room_code', 'booking_date', 'is_active'),
                name='classbook_camp_room_date',
            ),
        ]

    def __str__(self):
        return f"{self.room_code} {self.booking_date} {self.from_time}-{self.to_time}"


class ClassUtilizationDemoClass(models.Model):
    ROOM_TYPES = (
        ("classroom", "Classroom"),
        ("lab", "Laboratory"),
        ("seminar", "Seminar hall"),
    )
    WEEKDAYS = (
        ("Monday", "Monday"),
        ("Tuesday", "Tuesday"),
        ("Wednesday", "Wednesday"),
        ("Thursday", "Thursday"),
        ("Friday", "Friday"),
        ("Saturday", "Saturday"),
        ("Sunday", "Sunday"),
    )

    campus = models.CharField(max_length=100)
    building = models.CharField(max_length=150)
    room_code = models.CharField(max_length=50)
    room_name = models.CharField(max_length=150)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES)
    weekday = models.CharField(max_length=12, choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    course_code = models.CharField(max_length=50)
    course_name = models.CharField(max_length=200)
    instructor_name = models.CharField(max_length=150)
    instructor_id = models.CharField(max_length=50, blank=True)
    instructor_email = models.EmailField(blank=True)
    section = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspace_class_utilization_demo_class"
        ordering = ("weekday", "start_time", "room_name")
        indexes = [
            models.Index(
                fields=("campus", "building", "room_code", "weekday", "is_active"),
                name="cu_demo_room_day_active",
            ),
        ]

    def __str__(self):
        return f"{self.course_code} - {self.room_name} {self.weekday} {self.start_time}-{self.end_time}"


class RoomMaster(models.Model):
    id = models.IntegerField(primary_key=True, db_column="ID")
    room_code = models.CharField(max_length=50, db_column="ROOM_CODE", null=True)
    room_name = models.CharField(max_length=200, db_column="ROOM_NAME", null=True)
    building_code = models.CharField(max_length=50, db_column="BUILDING_CODE", null=True)
    building_name = models.CharField(max_length=200, db_column="BUILDING_NAME", null=True)
    campus_code = models.CharField(max_length=50, db_column="CAMPUS_CODE", null=True)
    capacity = models.IntegerField(db_column="CAPACITY", null=True)
    room_status = models.CharField(max_length=1, db_column="ROOM_STATUS", null=True)
    current_status = models.CharField(max_length=1, db_column="CURRENT_STATUS", null=True)
    room_type = models.CharField(max_length=50, db_column="ROOM_TYPE", null=True)
    room_category = models.CharField(max_length=50, db_column="ROOM_CATEGORY", null=True)
    theory_lab = models.CharField(max_length=50, db_column="THEORY_LAB", null=True)
    room_number = models.CharField(max_length=50, db_column="room_no", null=True)
    floor_code = models.CharField(max_length=50, db_column="FLOOR_CODE", null=True)
    is_active = models.BooleanField(db_column="is_active")

    class Meta:
        managed = False
        db_table = "ROOM_MASTER"


class TimeTableMaster(models.Model):
    id = models.IntegerField(primary_key=True, db_column="ID")
    subject_code = models.CharField(max_length=50, null=True)
    subject_name = models.CharField(max_length=150, null=True)
    weekday = models.CharField(max_length=50, null=True)
    from_time = models.TimeField(db_column="FROMTIME", null=True)
    to_time = models.TimeField(db_column="TOTIME", null=True)
    section = models.CharField(max_length=10, null=True)
    semester = models.IntegerField(null=True)
    batch = models.CharField(max_length=50, null=True)
    branch_code = models.CharField(max_length=50, null=True)
    course_code = models.CharField(max_length=50, null=True)
    degree_code = models.CharField(max_length=50, null=True)
    dept_code = models.CharField(max_length=50, null=True)
    college_code = models.CharField(max_length=50, null=True)
    campus_code = models.CharField(max_length=50, null=True)
    empid = models.CharField(max_length=50, null=True)
    empname = models.CharField(max_length=150, null=True)
    room_number = models.CharField(max_length=150, db_column="room_no", null=True)
    sem_flag = models.CharField(max_length=50, db_column="Sem_flag", null=True)
    status_flag = models.CharField(max_length=50, null=True)
    building_name = models.CharField(max_length=100, db_column="buildingname", null=True)

    class Meta:
        managed = False
        db_table = "TIME_TABLE_MASTER"



class ClassroomBookingHistory(models.Model):
    booking = models.ForeignKey(ClassroomBooking, on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=30)
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)
    performed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    user_role = models.CharField(max_length=30)
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_details(self):
        from .booking_presentation import history_details
        return history_details(self.comments)

    @property
    def previous_status_label(self):
        return {'confirmed':'Confirmed', 'pending':'Pending Approval'}.get(self.previous_status,
            dict(ClassroomBooking.STATUS_CHOICES).get(self.previous_status, self.previous_status or 'New request'))

    @property
    def new_status_label(self):
        return {'confirmed':'Confirmed', 'pending':'Pending Approval'}.get(self.new_status,
            dict(ClassroomBooking.STATUS_CHOICES).get(self.new_status, self.new_status))

    class Meta:
        db_table = 'workspace_classroom_booking_history'
        ordering = ('created_at', 'id')


class ClassroomBookingLock(models.Model):
    """A write mutex acquired before availability reads, including on SQLite."""
    version = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = 'workspace_classroom_booking_lock'


class ClassroomBookingChangeRequest(models.Model):
    booking = models.ForeignKey(ClassroomBooking, on_delete=models.CASCADE, related_name='change_requests')
    kind = models.CharField(max_length=20, choices=(('amendment','Amendment'),('cancellation','Cancellation')))
    proposed_values = models.JSONField(default=dict, blank=True)
    original_values = models.JSONField(default=dict)
    booking_revision = models.CharField(max_length=64)
    reason = models.TextField()
    status = models.CharField(max_length=12, choices=(('pending','Pending'),('approved','Approved'),('rejected','Rejected')), default='pending')
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='classroom_change_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_classroom_changes')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)

    class Meta:
        db_table = 'workspace_classroom_booking_change_request'
        ordering = ('-created_at','-id')
        constraints = [models.UniqueConstraint(fields=['booking'], condition=models.Q(status='pending'), name='one_pending_classroom_change')]


class ClassroomBookingNotification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='booking_notifications')
    history = models.ForeignKey(ClassroomBookingHistory, on_delete=models.CASCADE, related_name='notifications')
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workspace_classroom_booking_notification'
        ordering = ('-created_at','-id')
        constraints = [models.UniqueConstraint(fields=['recipient','history'], name='unique_classroom_notification')]


class PublicHoliday(models.Model):
    """Common holidays shared by every campus, sourced from an annual circular."""
    name = models.CharField(max_length=150)
    date = models.DateField(unique=True)
    year = models.PositiveSmallIntegerField(db_index=True)
    holiday_type = models.CharField(max_length=16, default='common', choices=[('common', 'Common public holiday')])
    source = models.CharField(max_length=250)

    class Meta:
        db_table = 'workspace_public_holiday'
        ordering = ['date']

    def __str__(self):
        return f'{self.date}: {self.name}'
class ClassroomMaintenanceReason(models.Model):
    name = models.CharField(max_length=120, unique=True)

    def __str__(self):
        return self.name


class ClassroomMaintenance(models.Model):
    scope = models.CharField(max_length=10, choices=[('room', 'Classroom'), ('floor', 'Entire floor'), ('building', 'Entire building')])
    campus = models.CharField(max_length=100)
    building_key = models.CharField(max_length=250)
    building_name = models.CharField(max_length=250)
    floor = models.CharField(max_length=100, blank=True)
    room_key = models.CharField(max_length=250, blank=True)
    room_codes = models.JSONField(default=list)
    scope_targets = models.JSONField(default=list, blank=True)
    recurrence = models.BooleanField(default=False)
    start_date = models.DateField()
    end_date = models.DateField()
    selections = models.JSONField(default=list)
    reasons = models.JSONField(default=list)
    description = models.TextField(blank=True)
    duration = models.CharField(max_length=10, choices=[('short', 'Short Duration'), ('medium', 'Medium Duration'), ('long', 'Long Duration')])
    expected_completion = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=[('open', 'Open'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='open', db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = models.JSONField(default=list)

    class Meta:
        ordering = ('-created_at', '-pk')


class ClassroomMaintenanceRoom(models.Model):
    maintenance = models.ForeignKey(ClassroomMaintenance, on_delete=models.CASCADE, related_name='rooms')
    room_key = models.CharField(max_length=250, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('maintenance', 'room_key'), name='unique_maintenance_room')]


class ClassroomMaintenanceWindow(models.Model):
    maintenance = models.ForeignKey(ClassroomMaintenance, on_delete=models.CASCADE, related_name='windows')
    date = models.DateField(db_index=True)
    start = models.TimeField()
    end = models.TimeField()

    class Meta:
        ordering = ('date', 'start')
        constraints = [models.CheckConstraint(condition=models.Q(end__gt=models.F('start')), name='maintenance_window_end_after_start')]
