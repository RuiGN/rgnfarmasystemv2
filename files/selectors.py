"""Object authorization shared by the API, HTML UI and related choices."""

from django.db.models import Q

from files.models import ProtectedFile, ProtectedFileAccessRule


def accessible_protected_files(user, permission='view'):
    queryset = ProtectedFile.objects.exclude(
        report_executions__status__in=('pending', 'running', 'failed', 'cancelled')
    )
    if not user or not user.is_authenticated or not user.is_active:
        return queryset.none()
    if user.is_superuser:
        return queryset
    rules = ProtectedFileAccessRule.objects.filter(
        is_active=True, permission__in=(permission, 'manage')
    )
    grants = Q(rule_type='user', user=user)
    for role in user.groups.values_list('name', flat=True):
        grants |= Q(rule_type='role', role__iexact=role)
    granted_ids = rules.filter(grants).values('protected_file_id')
    return queryset.filter(
        Q(responsible=user) | Q(uploaded_by=user) | Q(pk__in=granted_ids)
    ).distinct()
