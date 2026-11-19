from collections import defaultdict
from django.contrib import admin
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from usermanagement.encryption_util import *
from django.contrib import admin
from .models import *
from datetime import datetime
from .decorators import *
from workspace.helpers import *

def get_employee_workspace(emp_id):
    """
    Returns workspace details for the given employee ID.
    """
    seat = (
        Seat.objects.select_related(
            "room",
            "room__building",
            "room__floor",
            "room__block"
        )
        .filter(current_empid=emp_id)
        .first()
    )

    if not seat:
        return ""

    building_name = seat.room.building.name if seat.room and seat.room.building else ""
    building_prefix = seat.room.building.code if seat.room and seat.room.building else ""
    room_number = seat.room.room_number if seat.room else ""
    cabin_number = seat.room.block.name if seat.room and seat.room.block else ""
    current_seat_number = seat.seat_number or ""

    return (
        f"Building: {building_name} | "
        f"Prefix: {building_prefix} | "
        f"Room: {room_number} | "
        f"Cabin/Cubicle: {cabin_number} | "
        f"Seat: {current_seat_number}"
    )

@csrf_exempt
@login_required
def get_users_by_emp_id_search(request):
    term = request.POST.get('term', '').strip()
    user_id = request.user.id

    try:
        reach_queryset=None
        if EmployeeMaster.objects.using('GITAM').filter(Q(empid__icontains=term) |Q(emp_name__icontains=term) |Q(emailid__icontains=term)).exists():
            queryset = EmployeeMaster.objects.using('GITAM').filter(
                Q(empid__icontains=term) |
                Q(emp_name__icontains=term) |
                Q(emailid__icontains=term)
            ).values('empid', 'emp_name', 'campus', 'college_code', 'dept_code','job_description','dept_name')
        elif ResearchFaculty.objects.filter(Q(emp_id__icontains=term)|Q(name__icontains=term)|Q(email__icontains=term)|Q(faculty_type__icontains=term)).exists():
            reach_queryset=ResearchFaculty.objects.filter(Q(emp_id__icontains=term)|Q(name__icontains=term)|
            Q(email__icontains=term)|Q(faculty_type__icontains=term)).values('name','department','email','designation','dept_code','emp_id','faculty_type')
        else :
            queryset = GlearnGuestStaffMaster.objects.using('GITAM').filter(
                Q(empid__icontains=term) |
                Q(emp_name__icontains=term) |
                Q(emailid__icontains=term)
            ).values( 'empid', 'emp_name', 'campus', 'college_code', 'dept_code','dept_name')
        #======================Get Room Data===========
        message = get_employee_workspace(term)
        #====================End============
        if UserGroups.objects.filter(
            user_id=user_id,
            group__name__in=['RADMIN'],
            is_active=1
        ).exists():

            access_campuses = list(get_access_campus(user_id))

            campus_map = {
                1: 'VSP',
                2: 'HYD',
                3: 'BLR'
            }

            campus_codes = [
                campus_map.get(c) for c in access_campuses if c in campus_map
            ]

            if campus_codes:
                queryset = queryset.filter(campus__in=campus_codes)
            else:
                queryset = queryset.none()  # no access
        if reach_queryset:
            data=reach_queryset
        else:
            data = queryset.filter(emp_status='A')
        final_data=[]
        for item in data:
            final_data.append({
                "id": item.get("empid") or item.get("emp_id"),
                "empid": item.get("empid") or item.get("emp_id") or "",
                "emp_name": item.get("emp_name") or item.get("name") or "",
                "campus": item.get("campus") or "",
                "college_code": item.get("college_code") or "",
                "dept_code": item.get("dept_code") or "",
                "designation": item.get("job_description") or item.get("designation") or "Guest Faculty",
                "dept_name": item.get("dept_name") or item.get("department") or "",
                "faculty_type": item.get("faculty_type") or item.get("faculty_type") or "",
                "message": message
            })

        return JsonResponse({'status': 200, 'data': final_data})
    except Exception as e:
        print("ERROR:", e)
        return JsonResponse({'status': 500, 'error': str(e)})



@login_required
@group_required('ADMIN')
@csrf_exempt
def staff(request):
    title = "Users"
    if request.method == 'POST':
        user_details = User.objects.filter(is_active=1).values('username','email','first_name','last_name',
                                                               'designation_code','campus',
                                                               'college_code','id','last_login','phone',
                                                               'dept_code',

        ).exclude(id=request.user.id).order_by('-id')

        if UserGroups.objects.filter(user_id=request.user.id, group__name='HR', is_active=1).exists():
            user_details=user_details.filter(campus=request.user.campus)

        user_groups = UserGroups.objects.values('user_id', 'group__name', 'is_active', 'group_id', 'role')

        grouped_roles = defaultdict(list)
        role_status_map = {}

        for ug in user_groups:
            grouped_roles[ug['user_id']].append(ug['role'])
            if ug['is_active'] == 1:
                role_status_map[ug['user_id']] = ug['role']

        results = []
        s_no = 1
        for u in user_details:
            u['encrypt_id'] = encrypt(u['id'])
            u['roles'] = ','.join(grouped_roles.get(u['id'], []))
            u['role_status'] = role_status_map.get(u['id'], '')
            login_btn = f'<a href="/workspace/access_permission/{u["encrypt_id"]}" class="btn btn-primary btn-sm">View</a>'
            login_history = ''
            if u['last_login']:
                login_history = f'<span class="history" data-id="{u["id"]}" onclick="get_faculty_login_history(this)"><i class="fa fa-history"></i></span>'
            data = [
                s_no,
                u['username'],
                u['first_name'],
                u['email'],
                u['phone'],
                u['designation_code'],
                u['campus'],
                u['college_code'],
                u['dept_code'],
                f"{u['last_login']} {login_history}",
                login_btn
            ]
            results.append(data)
            s_no += 1
        return JsonResponse({'data': results})
    return render(request, 'sadmin/staff.html',context={'title': title})
@login_required
@group_required('ADMIN')
@csrf_exempt
def research_faculty(request):
    title = "Research Faculty"
    data=ResearchFaculty.objects.filter(is_active=1).values()
    return render(request, 'sadmin/research_faculty.html',context={'title': title,'data':data})
@login_required
@group_required('ADMIN')
@csrf_exempt
def save_research_faculty(request):

    if request.method != "POST":
        return JsonResponse({
            "status": 0,
            "message": "Invalid Request"
        })

    faculty_id = request.POST.get("faculty_id")
    data = {

        "name": request.POST.get("faculty_name"),
        "emp_id": request.POST.get("faculty_phone"),
        "designation": request.POST.get("faculty_designation"),
        "department": request.POST.get("faculty_department"),
        "faculty_type": request.POST.get("faculty_type"),
        "email": request.POST.get("faculty_email"),
        "phone": request.POST.get("faculty_phone"),
        "is_active": True,
    }
    # Duplicate Employee ID check
    duplicate = ResearchFaculty.objects.filter(emp_id=data["emp_id"])
    if faculty_id:
        duplicate = duplicate.exclude(id=faculty_id)
    if duplicate.exists():
        return JsonResponse({
            "status": 2,
            "message": "Employee ID already exists."
        })
    # Update
    if faculty_id:
        ResearchFaculty.objects.filter(id=faculty_id).update(**data)
        return JsonResponse({
            "status": 1,
            "message": "Research Faculty updated successfully."
        })

    # Create
    ResearchFaculty.objects.create(**data)

    return JsonResponse({
        "status": 1,
        "message": "Research Faculty created successfully."
    })
@login_required
@group_required('ADMIN')
@csrf_exempt
def get_research_faculty(request):

    if request.method != "POST":
        return JsonResponse({
            "status": 0,
            "message": "Invalid Request"
        })

    faculty_id = request.POST.get("faculty_id")

    try:
        faculty = ResearchFaculty.objects.get(id=faculty_id)

        return JsonResponse({
            "status": 1,
            "data": {
                "id": faculty.id,
                "name": faculty.name,
                "designation": faculty.designation,
                "department": faculty.department,
                "faculty_type": faculty.faculty_type,
                "email": faculty.email,
                "phone": faculty.phone,
            }
        })

    except ResearchFaculty.DoesNotExist:
        return JsonResponse({
            "status": 0,
            "message": "Research Faculty not found."
        })
#============Delete Research Faculty===========
@login_required
@group_required('ADMIN')
@csrf_exempt
def delete_research_faculty(request):
    if request.method != "POST":
        return JsonResponse({
            "status": 0,
            "message": "Invalid Request"
        })

    faculty_id = request.POST.get("faculty_id")

    try:
        faculty = ResearchFaculty.objects.get(id=faculty_id)
        faculty.is_active = False
        faculty.save(update_fields=["is_active"])
        return JsonResponse({
            "status": 1,
            "message": "Research Faculty deleted successfully."
        })
    except ResearchFaculty.DoesNotExist:
        return JsonResponse({
            "status": 0,
            "message": "Research Faculty not found."
        })
@csrf_exempt
@login_required
def get_faculty_login_history(request):
    if request.method == 'POST':
        user_id=request.POST.get('user_id')
        final_data=UserAuthLogs.objects.filter(user_id=user_id).values().order_by('-id')
        return JsonResponse({'status': 200, 'data': list(final_data)})
    else:
        return JsonResponse({'status': 500})

@login_required
@group_required('ADMIN')
def session(request,id):
    if request.user.is_superuser or request.user.is_staff:
        id=decrypt(id)
        if User.objects.filter(id=id).exists():
            user = User.objects.get(id=id)
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
            return redirect('/')
        else:
            return redirect('/')
    else:
        return redirect('/')


@login_required
@group_required('ADMIN')
@csrf_exempt
def add_user(request):
    if request.method == 'POST':
        try:
            emp_id = request.POST.get('emp_id')
            data = EmployeeMaster.objects.using('GITAM').filter(
                empid=emp_id
            ).values(
                'empid', 'emp_name', 'emailid',
                'doj', 'dob', 'job_description',
                'mobile', 'campus', 'college_code',
                'dept_code'
            ).last()

            if not data:
                messages.error(request, "Employee not found")
                return redirect('staff')

            # Create user
            user = User.objects.create_user(
                username=emp_id,
                password="SAS@gitam$",
                emp_id=emp_id,
                first_name=data['emp_name'],
                last_name="",
                email=data['emailid'],
                phone=data['mobile'] if data['mobile'] else 0,
                designation_code=data['job_description'],
                campus=data['campus'],
                college_code=data['college_code'],
                dept_code=data['dept_code'],
                doj=data['doj'],
            )
            UserGroups.objects.create(
                role='ADMIN',
                is_active=1,
                is_default=1,
                is_block=0,
                group_id=1,
                user_id=user.id
            )
            messages.success(request, 'Added Successfully')
            return redirect('staff')
        except Exception as e:
            ErrorLogs.objects.create(
                log=str(e),
                info=request.POST,
                user_id=request.user.id
            )
            messages.error(request, str(e))
            return redirect('staff')

    return render(
        request,
        'sadmin/add_user.html',
        {}
    )

    """
    Returns workspace details for the given employee ID.
    """

    seat = (
        Seat.objects.select_related(
            "room",
            "room__building",
            "room__floor",
            "room__block"
        )
        .filter(current_empid=emp_id)
        .first()
    )

    if not seat:
        return ""

    building_name = seat.room.building.name if seat.room and seat.room.building else ""
    building_prefix = seat.room.building.code if seat.room and seat.room.building else ""
    room_number = seat.room.room_number if seat.room else ""
    cabin_number = seat.room.block.name if seat.room and seat.room.block else ""
    current_seat_number = seat.seat_number or ""

    return (
        f"Building: {building_name} | "
        f"Prefix: {building_prefix} | "
        f"Room: {room_number} | "
        f"Cabin/Cubicle: {cabin_number} | "
        f"Seat: {current_seat_number}"
    )
@csrf_exempt
@login_required
def get_users_by_emp_id(request):
    term = request.POST.get('term', '').strip()
    user_id = request.user.id
    exists_emp_ids = list(
        User.objects.filter(is_active=1).values_list('username', flat=True)
    )
    # Campus access for RADMIN
    campus_codes = None
    if UserGroups.objects.filter(
        user_id=user_id,
        group__name='RADMIN',
        is_active=1
    ).exists():
        access_campuses = list(get_access_campus(user_id))
        campus_map = {1: "VSP", 2: "HYD", 3: "BLR"}
        campus_codes = [campus_map[c] for c in access_campuses if c in campus_map]

    search_q = (
        Q(empid__icontains=term) |
        Q(emp_name__icontains=term) |
        Q(emailid__icontains=term)
    )

    data = []

    # Employee Master
    if EmployeeMaster.objects.using("GITAM").filter(search_q).exists():
        qs = EmployeeMaster.objects.using("GITAM").filter(search_q)
        if campus_codes is not None:
            qs = qs.filter(campus__in=campus_codes) if campus_codes else qs.none()
        data = qs.values(
            "empid",
            "emp_name",
            "campus",
            "college_code",
            "dept_code",
            "job_description",
            "dept_name"
        )
    # Research Faculty
    elif ResearchFaculty.objects.filter(Q(emp_id__icontains=term) |Q(name__icontains=term) |Q(email__icontains=term) |Q(faculty_type__icontains=term)).exists():
        data = ResearchFaculty.objects.filter(
            Q(emp_id__icontains=term) |
            Q(name__icontains=term) |
            Q(email__icontains=term) |
            Q(faculty_type__icontains=term)
        ).values(
            "emp_id",
            "name",
            "designation",
            "department",
            "dept_code",
            "college_code",
            "faculty_type"
        )
    # Guest Staff
    else:
        qs = GlearnGuestStaffMaster.objects.using("GITAM").filter(
            search_q,
            emp_status="A"
        )
        if campus_codes is not None:
            qs = qs.filter(campus__in=campus_codes) if campus_codes else qs.none()

        data = qs.values(
            "empid",
            "emp_name",
            "campus",
            "college_code",
            "dept_code",
            "dept_name"
        )
    workspace = get_employee_workspace(term) or ""
    final_data = []
    for item in data:
        empid = item.get("empid") or item.get("emp_id")
        emp_name = item.get("emp_name") or item.get("name")
        final_data.append({
            "id": empid,
            "empid" : item.get("empid") or item.get("emp_id"),
            'emp_name' : item.get("emp_name") or item.get("name"),
            "campus": item.get("campus", ""),
            "college_code": item.get("college_code", ""),
            "dept_code": item.get("dept_code", ""),
            "dept_name": item.get("dept_name") or item.get("department", ""),
            "designation": item.get("job_description") or item.get("designation") or "Guest Faculty",
            "faculty_type": item.get("faculty_type", ""),
            "exists": str(empid) in exists_emp_ids,
            "message": workspace,
        })
    print("final_data",final_data)
    return JsonResponse({
        "status": 200,
        "data": final_data
    })

@login_required
@csrf_exempt
def get_employee_data(request):
    if request.method == 'POST':
        emp_id = request.POST.get('emp_id')
        data = EmployeeMaster.objects.using('GITAM').filter(empid=emp_id).values('empid','emp_name','emailid','doj','dob',
                                                                                 'job_description','mobile','campus','college_code','dept_code')
        final_data = []
        for item in data:
            item['id'] = item['empid']
            item['dob'] = item['dob'].strftime("%Y-%m-%d")
            item['doj'] = item['doj'].strftime("%Y-%m-%d")
            final_data.append(item)
        return JsonResponse({'status': 200, 'data': final_data})
    else:
        return JsonResponse({'status': 500})


