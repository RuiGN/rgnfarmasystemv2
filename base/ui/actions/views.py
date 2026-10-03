import json
import logging
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import resolve, reverse
from django.utils.datastructures import MultiValueDict
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect

from base.ui.actions.discovery import discover_post_actions
from base.ui.actions.forms import build_action_form
from base.ui.actions.registry import action_registry
from base.ui.actions.types import SubmissionFormat, SuccessBehavior
from base.ui.views import ResourceContextMixin, _annotate_form_accessibility


logger = logging.getLogger(__name__)


@method_decorator(csrf_protect, name='dispatch')
class ResourceActionView(LoginRequiredMixin, ResourceContextMixin, View):
    detail = True
    template_name = 'app/resource_action_form.html'

    def get_config(self):
        return action_registry.get(
            self.kwargs['module_slug'],
            self.kwargs['resource_slug'],
            self.kwargs['action_name'],
        )

    def get_action_object(self):
        return self.get_object() if self.detail else None

    def get_form_class(self):
        return build_action_form(self.get_config(), self.request, self.get_action_object())

    def get_context(self, form):
        config = self.get_config()
        obj = self.get_action_object()
        return {
            'module': self.get_module(),
            'resource': self.get_resource(),
            'object': obj,
            'action': config,
            'form': form,
            'cancel_url': self._success_url(),
        }

    def get(self, request, *args, **kwargs):
        unavailable = self._unavailable_response()
        if unavailable:
            return unavailable
        form = self.get_form_class()()
        return render(request, self.template_name, self.get_context(form))

    def post(self, request, *args, **kwargs):
        unavailable = self._unavailable_response()
        if unavailable:
            return unavailable

        form_class = self.get_form_class()
        form = form_class(request.POST, request.FILES)
        if not form.is_valid():
            _annotate_form_accessibility(form)
            return render(request, self.template_name, self.get_context(form))

        config = self.get_config()
        match = resolve(config.api_url(pk=self.kwargs.get('pk')))
        self._validate_callback(match)
        self._replace_request_payload(form.cleaned_payload())
        try:
            response = match.func(request, **match.kwargs)
            response.render()
        except Exception:
            request_id = request.META.get('HTTP_X_REQUEST_ID', '')
            logger.exception('Falha inesperada ao executar ação HTML. request_id=%s', request_id)
            return HttpResponse(
                f'Não foi possível executar a ação. Identificador: {request_id or "indisponível"}.',
                status=500,
            )

        if 200 <= response.status_code < 300:
            messages.success(request, config.success_message)
            if config.success_behavior == SuccessBehavior.DOWNLOAD:
                return response
            if config.success_behavior == SuccessBehavior.REDIRECT and config.redirect_route:
                return redirect(reverse(config.redirect_route))
            return redirect(self._success_url())
        if response.status_code == 400:
            self._apply_api_errors(form, response.data)
            _annotate_form_accessibility(form)
            return render(request, self.template_name, self.get_context(form))
        if response.status_code in {403, 409}:
            return HttpResponse(
                'A ação não pôde ser executada por permissão ou alteração de estado.',
                status=response.status_code,
            )

        request_id = request.META.get('HTTP_X_REQUEST_ID', '')
        logger.error(
            'Ação DRF retornou erro inesperado status=%s request_id=%s',
            response.status_code,
            request_id,
        )
        return HttpResponse(
            f'Não foi possível executar a ação. Identificador: {request_id or "indisponível"}.',
            status=500,
        )

    def _unavailable_response(self):
        config = self.get_config()
        obj = self.get_action_object()
        if not self.request.user.has_perms(config.permissions):
            raise PermissionDenied('Usuário sem permissão para executar esta ação.')
        if config.allowed_states and not config.is_available(self.request.user, obj):
            return HttpResponse(
                'O registro foi alterado e a ação não está disponível no estado atual.',
                status=409,
            )
        return None

    def _validate_callback(self, match):
        config = self.get_config()
        discovered = next(
            (
                action
                for action in discover_post_actions()
                if action.model is config.model
                and action.action_name == config.action_name
                and action.detail is config.detail
            ),
            None,
        )
        callback_actions = getattr(match.func, 'actions', {}) or {}
        if (
            discovered is None
            or getattr(match.func, 'cls', None) is not discovered.viewset
            or callback_actions.get('post') != config.action_name
        ):
            raise PermissionDenied('Callback de ação não autorizado.')

    def _replace_request_payload(self, payload):
        config = self.get_config()
        if config.submission_format == SubmissionFormat.JSON:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.request._body = body
            self.request._stream = BytesIO(body)
            self.request._read_started = False
            self.request.META['CONTENT_TYPE'] = 'application/json'
            self.request.META['CONTENT_LENGTH'] = str(len(body))
            self.request._post = QueryDict('', mutable=False)
            self.request._files = MultiValueDict()
            return

        post = QueryDict('', mutable=True)
        files = MultiValueDict()
        for key, value in payload.items():
            if hasattr(value, 'read'):
                files.setlist(key, [value])
            else:
                post[key] = value
        csrf_token = self.request.POST.get('csrfmiddlewaretoken')
        if csrf_token:
            post['csrfmiddlewaretoken'] = csrf_token
        post._mutable = False
        self.request._post = post
        self.request._files = files
        self.request._read_started = True
        if hasattr(self.request, '_body'):
            del self.request._body

    def _apply_api_errors(self, form, data):
        if not isinstance(data, dict):
            form.add_error(None, 'A API rejeitou os dados enviados.')
            return
        for field_name, errors in data.items():
            target = field_name if field_name in form.fields else None
            if isinstance(errors, (list, tuple)):
                for error in errors:
                    form.add_error(target, str(error))
            else:
                form.add_error(target, str(errors))

    def _success_url(self):
        route_name = 'app:resource_detail' if self.detail else 'app:resource_list'
        kwargs = {
            'module_slug': self.kwargs['module_slug'],
            'resource_slug': self.kwargs['resource_slug'],
        }
        if self.detail:
            kwargs['pk'] = self.kwargs['pk']
        return reverse(route_name, kwargs=kwargs)


class CollectionResourceActionView(ResourceActionView):
    detail = False

    def _success_url(self):
        config = self.get_config()
        if config.key == ('inventory', 'movements', 'issue') and not self.get_resource().can_view(
            self.request.user
        ):
            return reverse(
                'app:collection_action',
                kwargs={
                    'module_slug': config.module_slug,
                    'resource_slug': config.resource_slug,
                    'action_name': config.action_name,
                },
            )
        return super()._success_url()

    @method_decorator(csrf_protect)
    def dispatch(self, request, *args, **kwargs):
        # An authorized stock operator can issue without being granted generic
        # ledger viewing/editing rights. Other actions retain their resource gate.
        if (kwargs.get('module_slug'), kwargs.get('resource_slug'), kwargs.get('action_name')) == (
            'inventory',
            'movements',
            'issue',
        ):
            if not request.user.is_authenticated:
                return self.handle_no_permission()
            self.get_module()
            self.get_resource()
            if not request.user.has_perms(self.get_config().permissions):
                raise PermissionDenied('Usuário sem permissão para executar esta ação.')
            return View.dispatch(self, request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)
