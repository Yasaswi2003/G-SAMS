from django.urls import path,include
from . import views,admin,dashboard,auth,dashboard
from django.conf import settings
from .password_access import EmployeeLoginView, InitialPasswordChangeView

urlpatterns = [
    path('switch_role/<str:group_id>',views.switch_role,name="switch_role"),
    path('dashboard', dashboard.dashboard, name='dashboard'),
    path('not_found',views.not_found,name='not_found'),
    path('sign-in/',EmployeeLoginView.as_view(redirect_authenticated_user=True),name='employee_login'),
    path('ulogin/<str:emp_id>',EmployeeLoginView.as_view(),name='ulogin'),
    path('change-initial-password', InitialPasswordChangeView.as_view(), name='initial_password_change'),
    path('userlogout', views.userlogout, name='userlogout'),

    # Auth
    path('login_auth/', auth.login_auth, name='login_auth'),
    path('url_encode/<str:empid>', auth.url_encode, name='url_encode'),
    path('get_users_by_emp_id_search', admin.get_users_by_emp_id_search, name='get_users_by_emp_id_search'),
    # ADMIN
    path('staff', admin.staff, name='staff'),
    path('research_faculty', admin.research_faculty, name='research_faculty'),
    path('get_research_faculty', admin.get_research_faculty, name='get_research_faculty'),
    path('save_research_faculty', admin.save_research_faculty, name='save_research_faculty'),
    path('delete_research_faculty', admin.delete_research_faculty, name='delete_research_faculty'),
    path('get_faculty_login_history', admin.get_faculty_login_history, name='get_faculty_login_history'),
    path('session/<str:id>', admin.session, name="session"),
    path('add_user', admin.add_user, name='add_user'),
    path('get_users_by_emp_id', admin.get_users_by_emp_id, name='get_users_by_emp_id'),
    path('get_employee_data', admin.get_employee_data, name='get_employee_data'),
]
