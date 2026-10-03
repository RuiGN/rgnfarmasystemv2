import os
import ipaddress
import socket
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from base.normalized_locations import normalized_city_name, normalized_state_code
from files.models import ProtectedFile, ProtectedFileAccessRule, SecureFileLink
from fiscal.models import FiscalDocument, FiscalEmailDelivery, FiscalEmissionEvent
from integrations.fiscal_security import validate_fiscal_destination
from integrations.models import IntegrationConnector, IntegrationEvent, sanitize_safe_context


@dataclass(frozen=True)
class FiscalProviderResponse:
    class Status:
        AUTHORIZED = 'authorized'
        REJECTED = 'rejected'
        CANCELLED = 'cancelled'
        ERROR = 'error'
        PROCESSING = 'processing'

    status: str
    access_key: str = ''
    authorization_protocol: str = ''
    authorized_at: object = None
    cancel_protocol: str = ''
    cancelled_at: object = None
    rejection_code: str = ''
    rejection_reason: str = ''
    xml: str | bytes = ''
    danfe_pdf: bytes = b''
    message: str = ''
    raw: dict = field(default_factory=dict)


class _PinnedFiscalNetworkBackend:
    """Connect to the checked IP; httpcore keeps the original TLS/SNI hostname."""

    def __init__(self, backend, hostname, address):
        self.backend = backend
        self.hostname = hostname
        self.address = address

    def connect_tcp(self, host, port, **kwargs):
        if host != self.hostname or port != 443:
            raise ValidationError({'base_url': 'Conexão fiscal fora do destino autorizado.'})
        return self.backend.connect_tcp(self.address, port, **kwargs)

    def connect_unix_socket(self, *args, **kwargs):
        raise ValidationError({'base_url': 'Sockets locais não são destinos fiscais.'})

    def sleep(self, seconds):
        return self.backend.sleep(seconds)


def _fiscal_transport(base_url):
    hostname = urlsplit(base_url).hostname
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ValidationError(
            {'base_url': 'Não foi possível resolver o destino fiscal.'}
        ) from error
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global
        or ipaddress.ip_address(item[4][0]).is_multicast
        for item in addresses
    ):
        raise ValidationError({'base_url': 'Destino fiscal resolve para rede não pública.'})
    transport = httpx.HTTPTransport(trust_env=False, retries=0)
    # HTTPX exposes no public network_backend argument. Keep this narrow adapter
    # covered by a transport regression test when upgrading HTTPX/httpcore.
    transport._pool._network_backend = _PinnedFiscalNetworkBackend(
        transport._pool._network_backend, hostname, addresses[0][4][0]
    )
    return transport


class FiscalProviderClient:
    provider_name = 'generic'

    def issue(self, payload, connector=None):
        return self._post('/nfe/issue', payload, connector=connector)

    def check_status(self, payload, connector=None):
        return self._post('/nfe/status', payload, connector=connector)

    def cancel(self, payload, connector=None):
        return self._post('/nfe/cancel', payload, connector=connector)

    def _post(self, path, payload, connector=None):
        base_url = (connector.base_url if connector else '') or getattr(
            settings, 'FISCAL_PROVIDER_BASE_URL', ''
        )
        if not base_url:
            raise ValidationError(
                {'connector': 'Configure um conector fiscal ativo ou FISCAL_PROVIDER_BASE_URL.'}
            )
        reference = (connector.secret_reference if connector else '') or getattr(
            settings, 'FISCAL_PROVIDER_SECRET_REFERENCE', ''
        )
        base_url = validate_fiscal_destination(base_url, reference)
        transport = _fiscal_transport(base_url)
        secret = self._resolve_secret(connector)
        headers = {'Content-Type': 'application/json'}
        if secret:
            headers['Authorization'] = f'Bearer {secret}'
        timeout = getattr(settings, 'FISCAL_PROVIDER_TIMEOUT_SECONDS', 30)
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                f'{base_url.rstrip("/")}{path}', json=payload, headers=headers, timeout=timeout
            )
        response.raise_for_status()
        return self._parse_response(response.json())

    def _resolve_secret(self, connector=None):
        secret_reference = (connector.secret_reference if connector else '') or getattr(
            settings, 'FISCAL_PROVIDER_SECRET_REFERENCE', ''
        )
        base_url = (connector.base_url if connector else '') or getattr(
            settings, 'FISCAL_PROVIDER_BASE_URL', ''
        )
        validate_fiscal_destination(base_url, secret_reference)
        if not secret_reference:
            return ''
        return os.environ.get(secret_reference, '')

    def _parse_response(self, data):
        status_value = (
            data.get('status') or data.get('emission_status') or FiscalProviderResponse.Status.ERROR
        )
        authorized_at = data.get('authorized_at') or data.get('authorization_at')
        cancelled_at = data.get('cancelled_at')
        return FiscalProviderResponse(
            status=status_value,
            access_key=data.get('access_key') or data.get('chave_acesso') or '',
            authorization_protocol=data.get('authorization_protocol') or data.get('protocol') or '',
            authorized_at=parse_datetime(authorized_at)
            if isinstance(authorized_at, str)
            else authorized_at,
            cancel_protocol=data.get('cancel_protocol') or '',
            cancelled_at=parse_datetime(cancelled_at)
            if isinstance(cancelled_at, str)
            else cancelled_at,
            rejection_code=data.get('rejection_code') or data.get('code') or '',
            rejection_reason=data.get('rejection_reason') or data.get('reason') or '',
            xml=data.get('xml') or data.get('authorized_xml') or '',
            danfe_pdf=(data.get('danfe_pdf') or b''),
            message=data.get('message') or '',
            raw=sanitize_safe_context(data),
        )


class FiscalEmissionService:
    def __init__(self, provider_client=None):
        self.provider_client = provider_client or FiscalProviderClient()

    @transaction.atomic
    def issue(self, document, user=None, schedule_email=None):
        document = self._locked_document(document)
        self._validate_for_issue(document)
        connector = self._active_connector(document)
        document.emission_status = FiscalDocument.EmissionStatus.VALIDATING
        document.save(update_fields=['emission_status', 'updated_at'])
        payload = self._build_issue_payload(document)
        try:
            document.emission_status = FiscalDocument.EmissionStatus.SENT
            document.save(update_fields=['emission_status', 'updated_at'])
            response = self.provider_client.issue(payload, connector=connector)
        except Exception as exc:
            document.emission_status = FiscalDocument.EmissionStatus.ERROR
            document.rejection_reason = str(exc)[:4000]
            document.save(update_fields=['emission_status', 'rejection_reason', 'updated_at'])
            self._record_event(
                document,
                FiscalEmissionEvent.EventType.ERROR,
                user=user,
                message=str(exc),
                payload={'stage': 'issue'},
            )
            raise ValidationError(
                {'provider': f'Falha ao transmitir NF-e: {str(exc)[:1000]}'}
            ) from exc

        if response.status == FiscalProviderResponse.Status.AUTHORIZED:
            xml_file = self._store_artifact(
                document,
                response.xml,
                file_name=f'{document.number}-{document.series}.xml',
                mime_type='application/xml',
                title=f'XML NF-e {document.number}/{document.series}',
                user=user,
            )
            danfe_file = self._store_artifact(
                document,
                response.danfe_pdf,
                file_name=f'{document.number}-{document.series}-danfe.pdf',
                mime_type='application/pdf',
                title=f'DANFE NF-e {document.number}/{document.series}',
                user=user,
            )
            document.emission_status = FiscalDocument.EmissionStatus.AUTHORIZED
            document.access_key = response.access_key
            document.authorization_protocol = response.authorization_protocol
            document.authorization_at = response.authorized_at or timezone.now()
            document.rejection_code = ''
            document.rejection_reason = ''
            document.full_clean()
            document.save(
                update_fields=[
                    'emission_status',
                    'access_key',
                    'authorization_protocol',
                    'authorization_at',
                    'rejection_code',
                    'rejection_reason',
                    'updated_at',
                ]
            )
            self._record_event(
                document,
                FiscalEmissionEvent.EventType.AUTHORIZED,
                user=user,
                response=response,
                xml_file=xml_file,
                danfe_file=danfe_file,
            )
            should_schedule_email = (
                schedule_email
                if schedule_email is not None
                else getattr(settings, 'FISCAL_EMAIL_AUTO_SEND', True)
            )
            if should_schedule_email:
                self.schedule_email_delivery(
                    document, user=user, xml_file=xml_file, danfe_file=danfe_file
                )
            return document

        if response.status == FiscalProviderResponse.Status.REJECTED:
            document.emission_status = FiscalDocument.EmissionStatus.REJECTED
            document.rejection_code = response.rejection_code
            document.rejection_reason = response.rejection_reason or response.message
            document.save(
                update_fields=[
                    'emission_status',
                    'rejection_code',
                    'rejection_reason',
                    'updated_at',
                ]
            )
            self._record_event(
                document, FiscalEmissionEvent.EventType.REJECTED, user=user, response=response
            )
            return document

        document.emission_status = FiscalDocument.EmissionStatus.ERROR
        document.rejection_reason = response.message or 'Resposta fiscal não reconhecida.'
        document.save(update_fields=['emission_status', 'rejection_reason', 'updated_at'])
        self._record_event(
            document, FiscalEmissionEvent.EventType.ERROR, user=user, response=response
        )
        return document

    @transaction.atomic
    def check_status(self, document, user=None):
        document = self._locked_document(document)
        connector = self._active_connector(document)
        try:
            response = self.provider_client.check_status(
                {
                    'access_key': document.access_key,
                    'number': document.number,
                    'series': document.series,
                },
                connector=connector,
            )
        except Exception as exc:
            self._record_event(
                document,
                FiscalEmissionEvent.EventType.ERROR,
                user=user,
                message=str(exc),
                payload={'stage': 'check_status'},
            )
            raise ValidationError(
                {'provider': f'Falha ao consultar NF-e: {str(exc)[:1000]}'}
            ) from exc
        if response.status == FiscalProviderResponse.Status.AUTHORIZED:
            document.emission_status = FiscalDocument.EmissionStatus.AUTHORIZED
            document.access_key = response.access_key or document.access_key
            document.authorization_protocol = (
                response.authorization_protocol or document.authorization_protocol
            )
            document.authorization_at = (
                response.authorized_at or document.authorization_at or timezone.now()
            )
            document.save(
                update_fields=[
                    'emission_status',
                    'access_key',
                    'authorization_protocol',
                    'authorization_at',
                    'updated_at',
                ]
            )
        elif response.status == FiscalProviderResponse.Status.REJECTED:
            document.emission_status = FiscalDocument.EmissionStatus.REJECTED
            document.rejection_code = response.rejection_code
            document.rejection_reason = response.rejection_reason or response.message
            document.save(
                update_fields=[
                    'emission_status',
                    'rejection_code',
                    'rejection_reason',
                    'updated_at',
                ]
            )
        self._record_event(
            document, FiscalEmissionEvent.EventType.STATUS_CHECKED, user=user, response=response
        )
        return document

    @transaction.atomic
    def cancel(self, document, justification, user=None):
        document = self._locked_document(document)
        if document.emission_status != FiscalDocument.EmissionStatus.AUTHORIZED:
            raise ValidationError(
                {'emission_status': 'Somente NF-e autorizada pode ser cancelada.'}
            )
        if not str(justification or '').strip():
            raise ValidationError({'justification': 'Informe a justificativa de cancelamento.'})
        connector = self._active_connector(document)
        try:
            response = self.provider_client.cancel(
                {
                    'access_key': document.access_key,
                    'number': document.number,
                    'series': document.series,
                    'justification': str(justification).strip(),
                },
                connector=connector,
            )
        except Exception as exc:
            self._record_event(
                document,
                FiscalEmissionEvent.EventType.ERROR,
                user=user,
                message=str(exc),
                payload={'stage': 'cancel'},
            )
            raise ValidationError(
                {'provider': f'Falha ao cancelar NF-e: {str(exc)[:1000]}'}
            ) from exc
        if response.status != FiscalProviderResponse.Status.CANCELLED:
            raise ValidationError(
                {'cancel': response.message or 'Cancelamento não autorizado pelo provedor.'}
            )
        document.emission_status = FiscalDocument.EmissionStatus.CANCELLED
        document.status = FiscalDocument.Status.CANCELLED
        document.cancel_protocol = response.cancel_protocol
        document.cancelled_at = response.cancelled_at or timezone.now()
        document.full_clean()
        document.save(
            update_fields=[
                'emission_status',
                'status',
                'cancel_protocol',
                'cancelled_at',
                'updated_at',
            ]
        )
        self._record_event(
            document,
            FiscalEmissionEvent.EventType.CANCELLED,
            user=user,
            response=response,
            payload={'justification': justification},
        )
        return document

    def schedule_email_delivery(self, document, user=None, xml_file=None, danfe_file=None):
        document = FiscalDocument.objects.select_related('company', 'partner').get(pk=document.pk)
        if document.emission_status != FiscalDocument.EmissionStatus.AUTHORIZED:
            raise ValidationError(
                {'document': 'Somente NF-e autorizada pode ser enviada por e-mail.'}
            )
        recipient = document.partner.email
        if not recipient:
            raise ValidationError({'recipient_email': 'O parceiro não possui e-mail cadastrado.'})
        xml_file = xml_file or self._latest_artifact(document, '.xml')
        danfe_file = danfe_file or self._latest_artifact(document, '.pdf')
        if not xml_file or not danfe_file:
            raise ValidationError(
                {'attachments': 'XML e DANFE devem estar disponíveis para envio.'}
            )
        delay = int(getattr(settings, 'FISCAL_EMAIL_SEND_DELAY_SECONDS', 300))
        scheduled_at = timezone.now() + timedelta(seconds=max(delay, 0))
        delivery = FiscalEmailDelivery.objects.create(
            document=document,
            recipient_email=recipient,
            subject=f'NF-e {document.number}/{document.series} - {document.company.legal_name}',
            body=self._email_body(document),
            scheduled_at=scheduled_at,
            requested_by=user,
            xml_file=xml_file,
            danfe_file=danfe_file,
        )
        self._record_event(
            document,
            FiscalEmissionEvent.EventType.EMAIL_SCHEDULED,
            user=user,
            message=f'Envio agendado para {recipient}.',
            payload={'delivery_id': delivery.pk, 'recipient_email': recipient},
            xml_file=xml_file,
            danfe_file=danfe_file,
        )
        try:
            from fiscal.tasks import send_fiscal_document_email

            send_fiscal_document_email.apply_async(args=[delivery.pk], eta=scheduled_at)
        except Exception as exc:
            delivery.last_error = f'Falha ao enfileirar task: {str(exc)[:1000]}'
            delivery.save(update_fields=['last_error', 'updated_at'])
        return delivery

    def send_delivery_email(self, delivery):
        delivery = FiscalEmailDelivery.objects.select_related(
            'document', 'document__company', 'xml_file', 'danfe_file', 'requested_by'
        ).get(pk=delivery.pk)
        if delivery.status == FiscalEmailDelivery.Status.SENT:
            return delivery
        if delivery.status == FiscalEmailDelivery.Status.CANCELLED:
            return delivery
        if not delivery.requested_by:
            raise ValidationError(
                {'requested_by': 'Envio fiscal exige usuário solicitante para acesso aos arquivos.'}
            )
        delivery.mark_sending()
        try:
            message = EmailMessage(
                subject=delivery.subject,
                body=delivery.body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                to=[delivery.recipient_email],
            )
            attachments = self._delivery_attachments_or_links(delivery)
            for file_name, content, mime_type in attachments['attachments']:
                message.attach(file_name, content, mime_type)
            if attachments['links']:
                message.body = f'{message.body}\n\nLinks seguros:\n' + '\n'.join(
                    attachments['links']
                )
            message.send(fail_silently=False)
        except Exception as exc:
            delivery.mark_failed(exc)
            self._record_event(
                delivery.document,
                FiscalEmissionEvent.EventType.EMAIL_FAILED,
                user=delivery.requested_by,
                message=str(exc),
                payload={'delivery_id': delivery.pk},
                xml_file=delivery.xml_file,
                danfe_file=delivery.danfe_file,
            )
            raise
        delivery.mark_sent()
        self._record_event(
            delivery.document,
            FiscalEmissionEvent.EventType.EMAIL_SENT,
            user=delivery.requested_by,
            message=f'E-mail enviado para {delivery.recipient_email}.',
            payload={'delivery_id': delivery.pk},
            xml_file=delivery.xml_file,
            danfe_file=delivery.danfe_file,
        )
        return delivery

    def _locked_document(self, document):
        return (
            FiscalDocument.objects.select_for_update(of=('self',))
            .select_related(
                'company',
                'company__city_ref',
                'company__state_ref',
                'partner',
                'partner__city_ref',
                'partner__state_ref',
            )
            .get(pk=document.pk)
        )

    def _active_connector(self, document):
        return (
            IntegrationConnector.objects.filter(
                provider_type=IntegrationConnector.ProviderType.FISCAL_SYSTEM,
                status=IntegrationConnector.Status.ACTIVE,
                is_active=True,
            )
            .order_by('code')
            .first()
        )

    def _validate_for_issue(self, document):
        errors = {}
        if document.document_type != FiscalDocument.DocumentType.OUTBOUND:
            errors['document_type'] = 'A emissão inicial suporta somente NF-e de saída.'
        if document.emission_status in {
            FiscalDocument.EmissionStatus.AUTHORIZED,
            FiscalDocument.EmissionStatus.CANCELLED,
        }:
            errors['emission_status'] = (
                'NF-e autorizada ou cancelada não pode ser emitida novamente.'
            )
        if document.total_amount <= 0:
            errors['total_amount'] = 'A nota fiscal precisa ter valor total maior que zero.'
        if not document.items.exists():
            errors['items'] = 'Inclua ao menos um item fiscal.'
        if not document.taxes.exists():
            errors['taxes'] = 'Inclua os tributos da nota fiscal.'
        self._validate_party(errors, 'company', document.company)
        self._validate_party(errors, 'partner', document.partner)
        if errors:
            raise ValidationError(errors)

    def _validate_party(self, errors, prefix, party):
        if not getattr(party, 'document', ''):
            errors[f'{prefix}.document'] = 'Informe o documento fiscal.'
        if not getattr(party, 'city_ref_id', None):
            errors[f'{prefix}.city_ref'] = 'Informe o município normalizado.'
        if not getattr(party, 'state_ref_id', None):
            errors[f'{prefix}.state_ref'] = 'Informe a UF normalizada.'
        if (
            getattr(party, 'city_ref_id', None)
            and getattr(party, 'state_ref_id', None)
            and party.city_ref.state_id
            and party.city_ref.state_id != party.state_ref_id
        ):
            errors[f'{prefix}.city_ref'] = (
                'O município normalizado deve pertencer à UF normalizada.'
            )

    @staticmethod
    def _party_location_payload(party):
        return {
            'city': normalized_city_name(getattr(party, 'city_ref', None)),
            'state': normalized_state_code(getattr(party, 'state_ref', None)),
        }

    def _build_issue_payload(self, document):
        company_location = self._party_location_payload(document.company)
        partner_location = self._party_location_payload(document.partner)
        return {
            'model': document.electronic_model,
            'environment': document.environment,
            'document': {
                'id': document.pk,
                'number': document.number,
                'series': document.series,
                'issue_date': document.issue_date.isoformat(),
                'operation_date': document.operation_date.isoformat(),
                'operation_type': document.operation_type,
                'total_products': str(document.total_products),
                'total_taxes': str(document.total_taxes),
                'total_amount': str(document.total_amount),
            },
            'company': {
                'legal_name': document.company.legal_name,
                'document': document.company.document,
                'state_registration': document.company.state_registration,
                'tax_regime': document.company.tax_regime,
                **company_location,
            },
            'partner': {
                'legal_name': document.partner.legal_name,
                'document': document.partner.document,
                'email': document.partner.email,
                **partner_location,
            },
            'items': [
                {
                    'line_number': item.line_number,
                    'product_code': item.product.code,
                    'description': item.product.description,
                    'ncm': item.ncm.code,
                    'cfop': item.cfop.code,
                    'tax_situation': item.tax_situation.code,
                    'unit': item.fiscal_unit.code,
                    'quantity': str(item.quantity),
                    'unit_price': str(item.unit_price),
                    'line_total': str(item.line_total),
                }
                for item in document.items.select_related(
                    'product', 'fiscal_unit', 'ncm', 'cfop', 'tax_situation'
                )
            ],
            'taxes': [
                {
                    'tax_kind': tax.tax_kind,
                    'base_amount': str(tax.base_amount),
                    'rate_percent': str(tax.rate_percent),
                    'tax_amount': str(tax.tax_amount),
                    'is_retained': tax.is_retained,
                }
                for tax in document.taxes.all()
            ],
        }

    def _store_artifact(self, document, content, *, file_name, mime_type, title, user=None):
        if not content:
            raise ValidationError({'artifact': f'{title} não retornado pelo provedor fiscal.'})
        protected_file = ProtectedFile.objects.create(
            source_module=ProtectedFile.SourceModule.FISCAL,
            source_model='FiscalDocument',
            source_record_id=str(document.pk),
            fiscal_document=document,
            file_type=ProtectedFile.FileType.FISCAL_DOCUMENT,
            origin=ProtectedFile.Origin.INTEGRATION,
            criticality=ProtectedFile.Criticality.HIGH,
            confidentiality=ProtectedFile.Confidentiality.RESTRICTED,
            title=title,
            file_name=file_name,
            file_reference='pending',
            mime_type=mime_type,
            file_size=0,
            content_hash='sha256:pending',
            responsible=user,
            uploaded_by=user,
        )
        protected_file.store_encrypted_content(
            content, file_name=file_name, mime_type=mime_type, user=user
        )
        return protected_file

    def _latest_artifact(self, document, suffix):
        return (
            document.protected_files.filter(
                file_name__endswith=suffix, status=ProtectedFile.Status.ACTIVE
            )
            .order_by('-created_at')
            .first()
        )

    def _email_body(self, document):
        return (
            f'Prezado(a),\n\n'
            f'Segue a NF-e {document.number}/{document.series} emitida por {document.company.legal_name}.\n'
            f'Chave de acesso: {document.access_key}\n'
            f'Valor total: R$ {document.total_amount}\n\n'
            f'Esta mensagem foi gerada automaticamente pelo RGN Farma System.'
        )

    def _delivery_attachments_or_links(self, delivery):
        files = [delivery.xml_file, delivery.danfe_file]
        max_bytes = int(getattr(settings, 'FISCAL_EMAIL_MAX_ATTACHMENT_MB', 10)) * 1024 * 1024
        total_size = sum(file.file_size for file in files if file)
        if total_size <= max_bytes:
            return {
                'attachments': [
                    (
                        file.file_name,
                        file.read_encrypted_content(
                            delivery.requested_by,
                            permission=ProtectedFileAccessRule.Permission.DOWNLOAD,
                        ),
                        file.mime_type,
                    )
                    for file in files
                    if file
                ],
                'links': [],
            }
        if not getattr(settings, 'FISCAL_EMAIL_USE_SECURE_LINKS_WHEN_TOO_LARGE', True):
            raise ValidationError(
                {'attachments': 'Anexos excedem o limite configurado para envio.'}
            )
        links = []
        for file in files:
            if not file:
                continue
            link = file.generate_secure_link(
                delivery.requested_by,
                purpose=SecureFileLink.Purpose.DOWNLOAD,
                expires_in_minutes=1440,
            )
            links.append(f'{file.file_name}: {link.token}')
        return {'attachments': [], 'links': links}

    def _record_event(
        self,
        document,
        event_type,
        user=None,
        response=None,
        message='',
        payload=None,
        xml_file=None,
        danfe_file=None,
    ):
        safe_payload = sanitize_safe_context(payload or {})
        if response is not None:
            safe_payload.update(sanitize_safe_context(response.raw or {}))
        event = FiscalEmissionEvent.objects.create(
            document=document,
            event_type=event_type,
            provider=getattr(self.provider_client, 'provider_name', 'generic'),
            status=(response.status if response else ''),
            access_key=(response.access_key if response else document.access_key),
            protocol=(
                response.authorization_protocol or response.cancel_protocol if response else ''
            ),
            message=message or (response.message if response else ''),
            payload=safe_payload,
            actor=user,
            xml_file=xml_file,
            danfe_file=danfe_file,
        )
        connector = self._active_connector(document)
        if connector:
            connector.record_event(
                IntegrationEvent.EventType.CALL_LOGGED
                if event_type != FiscalEmissionEvent.EventType.ERROR
                else IntegrationEvent.EventType.ERROR,
                actor=user,
                message=event.message,
                safe_context={
                    'document': document.number,
                    'event': event_type,
                    'event_id': event.pk,
                },
            )
        FiscalAuditTrail = document._meta.apps.get_model('fiscal', 'FiscalAuditTrail')
        FiscalAuditTrail.record(
            user, 'FiscalDocument', document.pk, event_type, {'event_id': event.pk}
        )
        return event
