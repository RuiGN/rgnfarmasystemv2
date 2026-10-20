from dataclasses import dataclass
from functools import lru_cache

from django.db.models import Model
from django.urls import URLPattern, URLResolver, get_resolver


@dataclass(frozen=True, slots=True)
class DiscoveredAction:
    app_label: str
    model: type[Model]
    action_name: str
    route_name: str
    detail: bool
    permissions: tuple[str, ...]
    viewset: type

    @property
    def key(self) -> tuple[str, str, bool]:
        return self.model._meta.label_lower, self.action_name, self.detail


@lru_cache(maxsize=1)
def discover_post_actions() -> tuple[DiscoveredAction, ...]:
    api_resolver = next(
        pattern
        for pattern in get_resolver().url_patterns
        if isinstance(pattern, URLResolver) and str(pattern.pattern) == 'api/v1/'
    )
    discovered = []
    for pattern, namespaces in _walk_patterns(api_resolver.url_patterns):
        callback = pattern.callback
        actions = getattr(callback, 'actions', {}) or {}
        initkwargs = getattr(callback, 'initkwargs', {}) or {}
        if 'post' not in actions or 'name' not in initkwargs:
            continue
        if '(?P<format>' in str(pattern.pattern):
            continue

        viewset = callback.cls
        if getattr(viewset, 'exclude_from_action_registry', False):
            continue
        action_name = actions['post']
        model = viewset.queryset.model
        detail = bool(initkwargs['detail'])
        custom_permissions = getattr(viewset, 'action_permission_map', {}).get(action_name)
        permissions = tuple(custom_permissions or (_default_permission(model),))
        route_name = ':'.join((*namespaces, pattern.name))
        discovered.append(
            DiscoveredAction(
                app_label=model._meta.app_label,
                model=model,
                action_name=action_name,
                route_name=route_name,
                detail=detail,
                permissions=permissions,
                viewset=viewset,
            )
        )
    return tuple(discovered)


def _walk_patterns(patterns, namespaces=()):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            nested_namespaces = namespaces
            if pattern.namespace:
                nested_namespaces = (*namespaces, pattern.namespace)
            yield from _walk_patterns(pattern.url_patterns, nested_namespaces)
        elif isinstance(pattern, URLPattern):
            yield pattern, namespaces


def _default_permission(model: type[Model]) -> str:
    return f'{model._meta.app_label}.change_{model._meta.model_name}'
