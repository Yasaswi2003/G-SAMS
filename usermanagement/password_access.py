from django.contrib.auth.views import LoginView, PasswordChangeView
from django.shortcuts import redirect
from django.urls import reverse_lazy


class EmployeeLoginView(LoginView):
    template_name = 'usermanagement/password_login.html'
    redirect_authenticated_user = False

    def get_initial(self):
        return {**super().get_initial(), 'username': self.kwargs.get('emp_id', '')}

    def get_success_url(self):
        return '/user/change-initial-password' if self.request.user.must_change_password else '/dashboard'


class InitialPasswordChangeView(PasswordChangeView):
    template_name = 'usermanagement/password_change.html'
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=['must_change_password'])
        return response


class RequireInitialPasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and getattr(request.user, 'must_change_password', False):
            allowed = ('/user/change-initial-password', '/change-initial-password', '/user/userlogout', '/userlogout')
            if request.path not in allowed:
                if request.path.startswith('/workspace/') and request.method != 'GET':
                    from django.http import JsonResponse
                    return JsonResponse({'error': 'Change your temporary password before continuing.'}, status=403)
                return redirect('initial_password_change')
        return self.get_response(request)
