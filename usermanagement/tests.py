from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from .views import switch_role


class SwitchRoleTests(SimpleTestCase):
    def switch(self, decoded, selected, next_url='/workspace/class_utilization?campus=VSP'):
        request = RequestFactory().get('/user/switch_role/token', {'next': next_url})
        request.user = SimpleNamespace(id=1, is_authenticated=True)
        roles = Mock()
        roles.filter.return_value.first.return_value = selected
        with patch('usermanagement.views.decrypt', return_value=decoded), \
             patch('usermanagement.views.transaction.atomic', return_value=nullcontext()), \
             patch('usermanagement.views.UserGroups.objects') as manager, \
             patch('usermanagement.views.messages.error'):
            manager.select_for_update.return_value.filter.return_value = roles
            response = switch_role(request, 'token')
        return response, roles

    def test_switch_preserves_current_page_and_activates_assigned_role(self):
        response, roles = self.switch('2', SimpleNamespace(pk=7))
        self.assertEqual(response.url, '/workspace/class_utilization?campus=VSP')
        roles.filter.assert_any_call(group_id=2, is_block=False)
        roles.update.assert_called_once_with(is_active=False)
        roles.filter.assert_any_call(pk=7)
        roles.filter.return_value.update.assert_called_once_with(is_active=True)

    def test_unassigned_or_blocked_role_keeps_current_role(self):
        _, roles = self.switch('2', None)
        roles.update.assert_not_called()
        roles.filter.return_value.update.assert_not_called()

    def test_invalid_token_keeps_current_role(self):
        _, roles = self.switch(None, None)
        roles.update.assert_not_called()

    def test_external_redirect_is_rejected(self):
        response, _ = self.switch('2', None, 'https://example.com/')
        self.assertEqual(response.url, '/dashboard')
