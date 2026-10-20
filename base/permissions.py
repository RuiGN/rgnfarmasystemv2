from rest_framework.permissions import DjangoModelPermissions

from base.retention import requires_gxp_retention


class SingleInstanceDjangoModelPermissions(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'OPTIONS': ['%(app_label)s.view_%(model_name)s'],
        'HEAD': ['%(app_label)s.view_%(model_name)s'],
    }

    def has_permission(self, request, view):
        if request.method == 'DELETE':
            queryset = self._queryset(view)
            if requires_gxp_retention(queryset.model):
                return False

        action = getattr(view, 'action', None)
        configured_permissions = getattr(view, 'action_permission_map', {}).get(action)
        if configured_permissions is not None:
            if getattr(view, '_ignore_model_permissions', False):
                return True
            if not request.user or (
                not request.user.is_authenticated and self.authenticated_users_only
            ):
                return False
            return request.user.has_perms(configured_permissions)

        if request.method != 'POST' or not action or action == 'create':
            return super().has_permission(request, view)

        if getattr(view, '_ignore_model_permissions', False):
            return True
        if not request.user or (
            not request.user.is_authenticated and self.authenticated_users_only
        ):
            return False

        queryset = self._queryset(view)
        # Additional POST actions mutate by default, even on a collection.
        # Creation-only actions must declare their add permission explicitly.
        required_permissions = self.get_required_permissions('PUT', queryset.model)
        return request.user.has_perms(required_permissions)
