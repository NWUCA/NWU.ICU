"""Directory restrictions apply to browsing, searching and direct downloads."""
from django.http import Http404
from rest_framework.exceptions import NotAuthenticated
from common.models import ResourceAccessRule
from .resource_directories import normalize_directory_path


class ResourceAccess:
    def __init__(self, user=None):
        self.rules = []
        invalid_rule = False
        for rule in ResourceAccessRule.objects.values('path', 'mode'):
            try:
                self.rules.append({**rule, 'path': normalize_directory_path(rule['path']).casefold()})
            except ValueError:
                invalid_rule = True
        if invalid_rule:
            # A malformed stored ACL must fail closed rather than silently expose data.
            self.rules.append({'path': '/', 'mode': 'admin'})
        self.logged_in = bool(user and user.is_authenticated and user.is_active)
        self.admin = bool(self.logged_in and user.is_staff and user.has_perm('common.manage_resource_files'))

    def mode(self, path):
        path = normalize_directory_path(path).casefold()
        modes = [rule['mode'] for rule in self.rules if rule['path'] == '/'
                 or path == rule['path'] or path.startswith(rule['path'] + '/')]
        return 'admin' if 'admin' in modes else 'login' if 'login' in modes else 'public'

    def allowed(self, path):
        mode = self.mode(path)
        return mode == 'public' or (mode == 'login' and self.logged_in) or (mode == 'admin' and self.admin)

    def require(self, path):
        if self.allowed(path):
            return
        if self.mode(path) == 'login' and not self.logged_in:
            raise NotAuthenticated('此目录需要登录后访问。')
        raise Http404
