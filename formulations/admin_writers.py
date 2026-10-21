"""Admin adapter for the bounded formula write protocol."""

from django.core.exceptions import ValidationError
from django.db import transaction

from formulations.writers import delete_instance, save_form, validate_final, write_gate


class FormulaWriterAdminMixin:
    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST':
            # Enclose delete_selected's collection, permission check, log and
            # deletion; locking only delete_queryset leaves its audit outside.
            with write_gate():
                return getattr(super(), 'changelist_view')(request, extra_context)
        return getattr(super(), 'changelist_view')(request, extra_context)

    def delete_view(self, request, object_id, extra_context=None):
        if request.method == 'POST':
            with write_gate():
                return getattr(super(), 'delete_view')(request, object_id, extra_context)
        return getattr(super(), 'delete_view')(request, object_id, extra_context)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        try:
            # Keep the gate acquisition at save_model (after validation). This
            # permits a stale validated form to be rebased, and holds it through
            # save_related and the final check inside the Admin transaction.
            with transaction.atomic():
                return getattr(super(), 'changeform_view')(
                    request, object_id, form_url, extra_context
                )
        except ValidationError as error:
            request._formula_writer_error = error
            # Rebuild a bound invalid form after rollback; never replay a save.
            return getattr(super(), 'changeform_view')(request, object_id, form_url, extra_context)

    def get_form(self, request, obj=None, **kwargs):
        base = getattr(super(), 'get_form')(request, obj, **kwargs)
        error = getattr(request, '_formula_writer_error', None)
        if error is None:
            return base

        messages = error.messages

        def clean(form):
            cleaned = base.clean(form)
            form.add_error(None, ValidationError(messages))
            return cleaned

        return type('RejectedWriteForm', (base,), {'clean': clean})

    def save_model(self, request, obj, form, change):
        current = save_form(form, final=False)
        # Admin and its inline formsets keep the originally constructed object.
        # Synchronize that object instead of returning an ignored replacement.
        obj.__dict__.update(current.__dict__)
        form.instance = obj

    def save_formset(self, request, form, formset, change):
        # ModelAdmin's audit message consumes the standard formset receipts.
        formset.new_objects, formset.changed_objects, formset.deleted_objects = [], [], []
        for child_form in formset.forms:
            if not child_form.has_changed():
                continue
            if child_form.cleaned_data.get('DELETE'):
                if child_form.instance.pk:
                    formset.deleted_objects.append(child_form.instance)
                    delete_instance(child_form.instance)
            else:
                is_new = not child_form.instance.pk
                current = save_form(child_form, final=False)
                if is_new:
                    formset.new_objects.append(current)
                else:
                    formset.changed_objects.append((current, child_form.changed_data))

    def save_related(self, request, form, formsets, change):
        getattr(super(), 'save_related')(request, form, formsets, change)
        validate_final(form.instance)

    def delete_model(self, request, obj):
        delete_instance(obj)

    def delete_queryset(self, request, queryset):
        with write_gate():
            for obj in queryset.order_by('pk'):
                delete_instance(obj)
