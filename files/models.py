import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import IdentifierSpec, sequence_code
from base.roles import OperationalRole, user_has_operational_role
from core.crypto import AES256GCMCipher


PROTECTED_STORAGE_REFERENCE_PATTERN = re.compile(
    r'\Aprotected/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.enc\Z'
)
REPLACEMENT_HASH_PATTERN = re.compile(r'\A[0-9a-f]{64}\Z')


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


class ProtectedFile(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('file_number', 'ARQ'),)

    class SourceModule(models.TextChoices):
        OPERATIONAL = 'operational', 'Operacional'
        FINANCIAL = 'financial', 'Financeiro'
        FISCAL = 'fiscal', 'Fiscal'
        QUALITY = 'quality', 'Qualidade'
        REGULATORY = 'regulatory', 'Regulatório'
        ADMINISTRATIVE = 'administrative', 'Administrativo'

    class FileType(models.TextChoices):
        DOCUMENT = 'document', 'Documento'
        FISCAL_DOCUMENT = 'fiscal_document', 'Documento fiscal'
        CERTIFICATE = 'certificate', 'Certificado'
        REPORT = 'report', 'Relatório'
        EVIDENCE = 'evidence', 'Evidência'
        IMAGE = 'image', 'Imagem'
        CONTRACT = 'contract', 'Contrato'
        OTHER = 'other', 'Outro'

    class Origin(models.TextChoices):
        UPLOAD = 'upload', 'Upload'
        SYSTEM = 'system', 'Sistema'
        INTEGRATION = 'integration', 'Integração'
        EMAIL = 'email', 'Email'
        SCANNER = 'scanner', 'Scanner'

    class Criticality(models.TextChoices):
        LOW = 'low', 'Baixa'
        MEDIUM = 'medium', 'Média'
        HIGH = 'high', 'Alta'
        CRITICAL = 'critical', 'Crítica'

    class Confidentiality(models.TextChoices):
        PUBLIC_INTERNAL = 'public_internal', 'Público interno'
        INTERNAL = 'internal', 'Interno'
        RESTRICTED = 'restricted', 'Restrito'
        CONFIDENTIAL = 'confidential', 'Confidencial'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativo'
        SUPERSEDED = 'superseded', 'Substituído'
        EXPIRED = 'expired', 'Expirado'
        DELETED = 'deleted', 'Excluído'

    class EncryptionAlgorithm(models.TextChoices):
        NONE = 'none', 'Sem criptografia'
        AES_256_GCM = 'aes-256-gcm', 'AES-256-GCM'

    file_number = models.CharField('número do arquivo', max_length=80, blank=True)
    source_module = models.CharField(
        'módulo de origem', max_length=32, choices=SourceModule.choices
    )
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='módulo de origem normalizado',
    )
    source_model = models.CharField('modelo de origem', max_length=120)
    source_model_ref = models.ForeignKey(
        'auxiliary.SystemModel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='model de origem normalizado',
    )
    source_record_id = models.CharField('registro de origem', max_length=80)
    controlled_document = models.ForeignKey(
        'documents.ControlledDocument',
        on_delete=models.PROTECT,
        related_name='protected_files',
        null=True,
        blank=True,
        verbose_name='documento controlado',
    )
    fiscal_document = models.ForeignKey(
        'fiscal.FiscalDocument',
        on_delete=models.PROTECT,
        related_name='protected_files',
        null=True,
        blank=True,
        verbose_name='documento fiscal',
    )
    quality_document = models.ForeignKey(
        'quality.QualityDocument',
        on_delete=models.PROTECT,
        related_name='protected_files',
        null=True,
        blank=True,
        verbose_name='documento de qualidade',
    )
    financial_title = models.ForeignKey(
        'finance.FinancialTitle',
        on_delete=models.PROTECT,
        related_name='protected_files',
        null=True,
        blank=True,
        verbose_name='título financeiro',
    )
    file_type = models.CharField('tipo de arquivo', max_length=32, choices=FileType.choices)
    origin = models.CharField('origem', max_length=32, choices=Origin.choices)
    criticality = models.CharField(
        'criticidade', max_length=24, choices=Criticality.choices, default=Criticality.MEDIUM
    )
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    confidentiality = models.CharField(
        'sigilo', max_length=32, choices=Confidentiality.choices, default=Confidentiality.INTERNAL
    )
    title = models.CharField('título', max_length=180)
    description = models.TextField('descrição', blank=True)
    file_name = models.CharField('nome do arquivo', max_length=180)
    file_reference = models.CharField('referência protegida', max_length=255)
    mime_type = models.CharField('MIME type', max_length=120, blank=True)
    file_size = models.PositiveBigIntegerField('tamanho em bytes', default=0)
    content_hash = models.CharField('hash do conteúdo', max_length=128)
    encryption_algorithm = models.CharField(
        'algoritmo de criptografia',
        max_length=32,
        choices=EncryptionAlgorithm.choices,
        default=EncryptionAlgorithm.NONE,
    )
    encryption_key_id = models.CharField('id da chave de criptografia', max_length=80, blank=True)
    encrypted_at = models.DateTimeField('criptografado em', null=True, blank=True)
    encrypted_size = models.PositiveBigIntegerField('tamanho criptografado em bytes', default=0)
    valid_until = models.DateField('validade', null=True, blank=True)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='responsible_protected_files',
        null=True,
        blank=True,
        verbose_name='responsável',
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='uploaded_protected_files',
        null=True,
        blank=True,
        verbose_name='enviado por',
    )
    uploaded_at = models.DateTimeField('enviado em', default=timezone.now)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.ACTIVE
    )
    supersedes = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='revisions',
        null=True,
        blank=True,
        verbose_name='substitui',
    )
    replaced_by = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='replaced_files',
        null=True,
        blank=True,
        verbose_name='substituído por',
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='deleted_protected_files',
        null=True,
        blank=True,
        verbose_name='excluído por',
    )
    deleted_at = models.DateTimeField('excluído em', null=True, blank=True)
    deletion_reason = models.TextField('motivo da exclusão', blank=True)

    class Meta:
        ordering = ['-created_at', 'file_number']
        constraints = [
            models.UniqueConstraint(fields=['file_number'], name='unique_protected_file_number'),
            models.UniqueConstraint(
                fields=['content_hash', 'file_reference'],
                name='unique_protected_file_hash_reference',
            ),
        ]
        indexes = [
            models.Index(fields=['source_module', 'source_model', 'source_record_id']),
            models.Index(fields=['file_type', 'status']),
            models.Index(fields=['criticality', 'confidentiality']),
            models.Index(fields=['valid_until']),
            models.Index(fields=['uploaded_by']),
            models.Index(fields=['content_hash']),
        ]
        verbose_name = 'arquivo protegido'
        verbose_name_plural = 'arquivos protegidos'

    @property
    def is_current(self):
        if self.status != self.Status.ACTIVE:
            return False
        return self.valid_until is None or self.valid_until >= timezone.localdate()

    @property
    def is_encrypted(self):
        return self.encryption_algorithm == self.EncryptionAlgorithm.AES_256_GCM

    def save(self, *args, **kwargs):
        if not self.file_number:
            self.file_number = _sequence_code(ProtectedFile, 'file_number', 'ARQ')
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def user_can_access(
        self, user, permission='view', source_module='', source_model='', source_record_id=''
    ):
        if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
            return False
        if user.is_superuser:
            return True
        if user.pk in {self.responsible_id, self.uploaded_by_id}:
            return True
        return any(
            rule.matches(
                user,
                permission,
                source_module=source_module,
                source_model=source_model,
                source_record_id=source_record_id,
            )
            for rule in self.access_rules.filter(is_active=True)
        )

    def _assert_file_available(self):
        if self.pk and self.report_executions.exclude(status='completed').exists():
            raise ValidationError({'status': 'Arquivo de relatório ainda não foi concluído.'})
        if self.status != self.Status.ACTIVE:
            raise ValidationError({'status': 'Arquivo indisponível para acesso.'})
        if self.valid_until and self.valid_until < timezone.localdate():
            raise ValidationError({'valid_until': 'Arquivo com validade expirada.'})

    def _permission_for_purpose(self, purpose):
        if purpose == SecureFileLink.Purpose.DOWNLOAD:
            return ProtectedFileAccessRule.Permission.DOWNLOAD
        return ProtectedFileAccessRule.Permission.VIEW

    def _encryption_associated_data(self):
        if not self.pk:
            raise ValidationError({'id': 'Arquivo precisa estar salvo antes da criptografia.'})
        return f'ProtectedFile:{self.pk}:{self.file_number}'

    def _encrypted_storage_path(self):
        file_number = self.file_number or f'file-{self.pk}'
        token = secrets.token_urlsafe(18)
        return f'protected/{file_number}/{token}.enc'

    @transaction.atomic
    def store_encrypted_content(
        self,
        content,
        *,
        file_name='',
        mime_type='',
        user=None,
        reserved_reference='',
    ):
        if hasattr(content, 'read'):
            content = content.read()
        if isinstance(content, str):
            content = content.encode('utf-8')
        if content is None:
            raise ValidationError({'content': 'Informe o conteúdo do arquivo.'})
        content = bytes(content)
        cipher = AES256GCMCipher()
        encrypted_payload = cipher.encrypt_bytes(
            content, associated_data=self._encryption_associated_data()
        ).encode('ascii')
        if reserved_reference and (
            type(reserved_reference) is not str
            or PROTECTED_STORAGE_REFERENCE_PATTERN.fullmatch(reserved_reference) is None
        ):
            raise ValidationError({'file_reference': 'A referência reservada não é canônica.'})
        target_reference = reserved_reference or self._encrypted_storage_path()
        if reserved_reference and default_storage.exists(reserved_reference):
            raise ValidationError({'file_reference': 'A referência reservada já está ocupada.'})
        reference = default_storage.save(target_reference, ContentFile(encrypted_payload))
        if reserved_reference and reference != reserved_reference:
            if type(reference) is not str:
                raise ValidationError(
                    {'file_reference': ('O storage retornou uma referência fora da reserva.')}
                )
            reserved_directory = reserved_reference.rpartition('/')[0]
            returned_directory = reference.rpartition('/')[0]
            if (
                PROTECTED_STORAGE_REFERENCE_PATTERN.fullmatch(reference) is None
                or returned_directory != reserved_directory
            ):
                raise ValidationError(
                    {'file_reference': ('O storage retornou uma referência fora da reserva.')}
                )
            try:
                default_storage.delete(reference)
            except Exception as error:
                raise OSError(
                    'O storage alterou a referência e o cleanup imediato falhou.'
                ) from error
            raise OSError('O storage alterou a referência reservada.')
        self.file_reference = reference
        if file_name:
            self.file_name = file_name
        if mime_type:
            self.mime_type = mime_type
        self.file_size = len(content)
        self.encrypted_size = len(encrypted_payload)
        self.content_hash = f'sha256:{hashlib.sha256(content).hexdigest()}'
        self.encryption_algorithm = self.EncryptionAlgorithm.AES_256_GCM
        self.encryption_key_id = cipher.active_key_id
        self.encrypted_at = timezone.now()
        self.save(
            update_fields=[
                'file_reference',
                'file_name',
                'mime_type',
                'file_size',
                'encrypted_size',
                'content_hash',
                'encryption_algorithm',
                'encryption_key_id',
                'encrypted_at',
                'updated_at',
            ]
        )
        self.record_audit(
            ProtectedFileAuditTrail.Action.UPLOAD,
            user=user,
            details={
                'encrypted': True,
                'algorithm': self.encryption_algorithm,
                'key_id': self.encryption_key_id,
            },
        )
        return reference

    def read_encrypted_content(
        self,
        user,
        permission=None,
        *,
        ip_address='',
        user_agent='',
    ):
        permission = permission or ProtectedFileAccessRule.Permission.DOWNLOAD
        try:
            self._assert_file_available()
            if not self.is_encrypted:
                raise ValidationError(
                    {'encryption_algorithm': 'Arquivo não está criptografado com AES-256-GCM.'}
                )
            if not self.user_can_access(user, permission=permission):
                raise ValidationError(
                    {'permission': 'Usuário sem permissão para descriptografar este arquivo.'}
                )
        except ValidationError:
            self.record_audit(
                ProtectedFileAuditTrail.Action.ACCESS_DENIED,
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise
        with default_storage.open(self.file_reference, 'rb') as encrypted_file:
            encrypted_payload = encrypted_file.read()
        return AES256GCMCipher().decrypt_bytes(
            encrypted_payload, associated_data=self._encryption_associated_data()
        )

    def generate_secure_link(
        self, user, purpose='download', expires_in_minutes=15, ip_address='', user_agent=''
    ):
        if purpose not in SecureFileLink.Purpose.values:
            raise ValidationError({'purpose': 'Finalidade de link inválida.'})
        try:
            expires_in_minutes = int(expires_in_minutes)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {'expires_in_minutes': 'Informe um prazo válido em minutos.'}
            ) from exc
        if expires_in_minutes <= 0 or expires_in_minutes > 1440:
            raise ValidationError(
                {'expires_in_minutes': 'O prazo deve ficar entre 1 e 1440 minutos.'}
            )
        permission = self._permission_for_purpose(purpose)
        try:
            self._assert_file_available()
        except ValidationError as error:
            self.record_audit(
                ProtectedFileAuditTrail.Action.ACCESS_DENIED,
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise error
        if not self.user_can_access(user, permission=permission):
            self.record_audit(
                ProtectedFileAuditTrail.Action.ACCESS_DENIED,
                user=user,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise ValidationError(
                {'permission': 'Usuário sem permissão para gerar link seguro deste arquivo.'}
            )
        link = SecureFileLink.objects.create(
            protected_file=self,
            purpose=purpose,
            requested_by=user,
            expires_at=timezone.now() + timedelta(minutes=expires_in_minutes),
        )
        self.record_audit(
            ProtectedFileAuditTrail.Action.LINK_GENERATED,
            user=user,
            secure_link=link,
            ip_address=ip_address,
            user_agent=user_agent,
            details={'purpose': purpose, 'expires_in_minutes': expires_in_minutes},
        )
        return link

    def record_access(
        self, user, action, secure_link=None, ip_address='', user_agent='', details=None
    ):
        if action not in {
            ProtectedFileAuditTrail.Action.DOWNLOAD,
            ProtectedFileAuditTrail.Action.VIEW,
        }:
            raise ValidationError({'action': 'Acesso deve ser download ou visualização.'})
        return self.record_audit(
            action,
            user=user,
            secure_link=secure_link,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
        )

    def record_audit(
        self, action, user=None, secure_link=None, ip_address='', user_agent='', details=None
    ):
        return ProtectedFileAuditTrail.objects.create(
            protected_file=self,
            secure_link=secure_link,
            action=action,
            actor=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
        )

    def _replacement_instance(self, **overrides):
        values = {
            'source_module': self.source_module,
            'source_model': self.source_model,
            'source_record_id': self.source_record_id,
            'controlled_document': self.controlled_document,
            'fiscal_document': self.fiscal_document,
            'quality_document': self.quality_document,
            'financial_title': self.financial_title,
            'file_type': self.file_type,
            'origin': self.Origin.UPLOAD,
            'criticality': self.criticality,
            'confidentiality': self.confidentiality,
            'title': self.title,
            'description': self.description,
            'valid_until': self.valid_until,
            'responsible': self.responsible,
            'supersedes': self,
        }
        values.update(overrides)
        return ProtectedFile.objects.create(**values)

    def _replace_with_content(self, content, file_name, content_hash, file_size, mime_type, user):
        if hasattr(content, 'read'):
            content = content.read()
        if isinstance(content, str):
            content = content.encode('utf-8')
        content = bytes(content)
        computed_hash = f'sha256:{hashlib.sha256(content).hexdigest()}'
        if content_hash and self._normalize_hash(content_hash) != self._normalize_hash(
            computed_hash
        ):
            raise ValidationError(
                {'content_hash': 'O hash informado não confere com o conteúdo enviado.'}
            )
        declared_size = self._validated_file_size(file_size)
        if declared_size is not None and declared_size != len(content):
            raise ValidationError(
                {'file_size': 'O tamanho informado não confere com o conteúdo enviado.'}
            )
        replacement = self._replacement_instance(
            file_name=file_name,
            file_reference=f'pending/{secrets.token_urlsafe(12)}',
            mime_type=mime_type or self.mime_type,
            file_size=len(content),
            content_hash=computed_hash,
            uploaded_by=user,
        )
        replacement.store_encrypted_content(
            content, file_name=file_name, mime_type=mime_type, user=user
        )
        return replacement

    def _replace_with_reference(
        self, file_reference, file_name, content_hash, file_size, mime_type, user
    ):
        declared_size = self._validated_file_size(file_size)
        if not content_hash:
            raise ValidationError(
                {'content_hash': 'Substituição exige hash para integridade ALCOA+.'}
            )
        if (
            type(file_reference) is not str
            or PROTECTED_STORAGE_REFERENCE_PATTERN.fullmatch(file_reference) is None
        ):
            raise ValidationError(
                {'new_file_reference': 'Informe uma referência protegida canônica.'}
            )
        if not default_storage.exists(file_reference):
            raise ValidationError(
                {'new_file_reference': 'A referência protegida informada não existe no storage.'}
            )
        if REPLACEMENT_HASH_PATTERN.fullmatch(self._normalize_hash(content_hash)) is None:
            raise ValidationError({'content_hash': 'Informe um hash SHA-256 hexadecimal válido.'})
        cipher = AES256GCMCipher()
        replacement = self._replacement_instance(
            file_name=file_name,
            file_reference=file_reference,
            mime_type=mime_type or self.mime_type,
            file_size=0,
            content_hash=content_hash,
            encryption_algorithm=self.EncryptionAlgorithm.AES_256_GCM,
            encryption_key_id=cipher.active_key_id,
            encrypted_at=timezone.now(),
            uploaded_by=user,
        )
        with default_storage.open(file_reference, 'rb') as stored:
            payload = stored.read()
        try:
            plain = cipher.decrypt_bytes(
                payload, associated_data=replacement._encryption_associated_data()
            )
        except Exception as error:
            raise ValidationError(
                {'new_file_reference': 'O conteúdo armazenado não pôde ser verificado.'}
            ) from error
        computed_hash = hashlib.sha256(plain).hexdigest()
        if self._normalize_hash(content_hash) != computed_hash:
            raise ValidationError(
                {'content_hash': 'O hash informado não confere com o conteúdo armazenado.'}
            )
        if declared_size is not None and declared_size != len(plain):
            raise ValidationError(
                {'file_size': 'O tamanho informado não confere com o conteúdo armazenado.'}
            )
        replacement.content_hash = f'sha256:{computed_hash}'
        replacement.file_size = len(plain)
        replacement.encrypted_size = len(payload)
        replacement.save(
            update_fields=['content_hash', 'file_size', 'encrypted_size', 'updated_at']
        )
        return replacement

    @staticmethod
    def _validated_file_size(file_size):
        if file_size in (None, ''):
            return None
        if isinstance(file_size, bool):
            raise ValidationError({'file_size': 'Informe um tamanho de arquivo válido.'})
        try:
            size = int(file_size)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValidationError({'file_size': 'Informe um tamanho de arquivo válido.'}) from error
        if size < 0:
            raise ValidationError({'file_size': 'O tamanho do arquivo não pode ser negativo.'})
        return size

    @staticmethod
    def _normalize_hash(value):
        value = str(value or '').strip().lower()
        return value.removeprefix('sha256:')

    @transaction.atomic
    def replace(
        self,
        new_file_reference,
        new_file_name,
        content_hash,
        user=None,
        reason='',
        file_size=None,
        mime_type='',
        content=None,
    ):
        if not new_file_name:
            raise ValidationError({'new_file_name': 'Informe o nome do novo arquivo.'})
        persisted = type(self).objects.select_for_update().get(pk=self.pk)
        if persisted.status != self.Status.ACTIVE or persisted.replaced_by_id:
            raise ValidationError(
                {'status': 'Somente arquivo ativo e vigente pode ser substituído.'}
            )
        try:
            with transaction.atomic():
                if content is not None:
                    replacement = self._replace_with_content(
                        content, new_file_name, content_hash, file_size, mime_type, user
                    )
                else:
                    replacement = self._replace_with_reference(
                        new_file_reference,
                        new_file_name,
                        content_hash,
                        file_size,
                        mime_type,
                        user,
                    )
        except IntegrityError as error:
            raise ValidationError(
                {'new_file_reference': 'A substituição conflita com um registro existente.'}
            ) from error
        self.status = self.Status.SUPERSEDED
        self.replaced_by = replacement
        self.save(update_fields=['status', 'replaced_by', 'updated_at'])
        self.record_audit(
            ProtectedFileAuditTrail.Action.REPLACE,
            user=user,
            details={'replacement': replacement.pk, 'reason': reason},
        )
        replacement.record_audit(
            ProtectedFileAuditTrail.Action.UPLOAD,
            user=user,
            details={
                'reason': 'Arquivo criado por substituição controlada.',
                'supersedes': self.pk,
            },
        )
        return replacement

    def delete_secure(self, reason, user=None):
        if not reason:
            raise ValidationError({'reason': 'Informe a justificativa para exclusão protegida.'})
        if self.status == self.Status.DELETED:
            raise ValidationError({'status': 'Arquivo já está excluído.'})
        self.status = self.Status.DELETED
        self.deleted_by = user
        self.deleted_at = timezone.now()
        self.deletion_reason = reason
        self.save(
            update_fields=['status', 'deleted_by', 'deleted_at', 'deletion_reason', 'updated_at']
        )
        self.record_audit(
            ProtectedFileAuditTrail.Action.DELETE, user=user, details={'reason': reason}
        )

    def expire(self, user=None):
        if self.status == self.Status.DELETED:
            raise ValidationError({'status': 'Arquivo excluído não pode expirar novamente.'})
        self.status = self.Status.EXPIRED
        self.save(update_fields=['status', 'updated_at'])
        self.record_audit(ProtectedFileAuditTrail.Action.EXPIRE, user=user)

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            'controlled_document',
            'fiscal_document',
            'quality_document',
            'financial_title',
            'supersedes',
            'replaced_by',
        ):
            pass
        for field in ('responsible', 'uploaded_by', 'deleted_by'):
            pass
        if not self.source_model:
            errors['source_model'] = 'Informe o modelo do registro de origem.'
        if not self.source_record_id:
            errors['source_record_id'] = 'Informe o identificador do registro de origem.'
        if not self.content_hash:
            errors['content_hash'] = 'Arquivo protegido exige hash para integridade ALCOA+.'
        if (
            self.valid_until
            and self.valid_until < timezone.localdate()
            and self.status == self.Status.ACTIVE
        ):
            errors['valid_until'] = 'Arquivo ativo não pode ter validade expirada.'
        if self.status == self.Status.DELETED:
            if not self.deleted_by:
                errors['deleted_by'] = 'Arquivo excluído exige usuário responsável pela exclusão.'
            if not self.deleted_at:
                errors['deleted_at'] = 'Arquivo excluído exige data da exclusão.'
            if not self.deletion_reason:
                errors['deletion_reason'] = 'Arquivo excluído exige justificativa.'
        if self.replaced_by and self.replaced_by_id == self.pk:
            errors['replaced_by'] = 'Arquivo não pode substituir a si próprio.'
        if self.supersedes and self.supersedes_id == self.pk:
            errors['supersedes'] = 'Arquivo não pode substituir a si próprio.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.file_number} - {self.title}'


class ProtectedFileAccessRule(SingleInstanceModel):
    class RuleType(models.TextChoices):
        USER = 'user', 'Usuário'
        ROLE = 'role', 'Papel'
        MODULE = 'module', 'Módulo'
        RECORD = 'record', 'Registro'

    class Permission(models.TextChoices):
        VIEW = 'view', 'Visualizar'
        DOWNLOAD = 'download', 'Baixar'
        MANAGE = 'manage', 'Gerenciar'

    protected_file = models.ForeignKey(
        ProtectedFile,
        on_delete=models.CASCADE,
        related_name='access_rules',
        verbose_name='arquivo protegido',
    )
    rule_type = models.CharField('tipo de regra', max_length=24, choices=RuleType.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='protected_file_access_rules',
        null=True,
        blank=True,
        verbose_name='usuário',
    )
    role = models.CharField('papel', max_length=32, choices=OperationalRole.choices, blank=True)
    source_module = models.CharField(
        'módulo', max_length=32, choices=ProtectedFile.SourceModule.choices, blank=True
    )
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='módulo normalizado',
    )
    source_model = models.CharField('modelo de origem', max_length=120, blank=True)
    source_model_ref = models.ForeignKey(
        'auxiliary.SystemModel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='model de origem normalizado',
    )
    source_record_id = models.CharField('registro de origem', max_length=80, blank=True)
    permission = models.CharField('permissão', max_length=24, choices=Permission.choices)
    is_active = models.BooleanField('ativa', default=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['protected_file', 'rule_type', 'permission']
        indexes = [
            models.Index(fields=['protected_file', 'is_active']),
            models.Index(fields=['rule_type', 'permission']),
            models.Index(fields=['user']),
            models.Index(fields=['role']),
            models.Index(fields=['source_module', 'source_model', 'source_record_id']),
        ]
        verbose_name = 'regra de acesso a arquivo'
        verbose_name_plural = 'regras de acesso a arquivos'

    def _permission_matches(self, requested_permission):
        return self.permission == self.Permission.MANAGE or self.permission == requested_permission

    def matches(
        self, user, requested_permission, source_module='', source_model='', source_record_id=''
    ):
        if not self.is_active or not self._permission_matches(requested_permission):
            return False
        if self.rule_type == self.RuleType.USER:
            return self.user_id == user.pk
        if self.rule_type == self.RuleType.ROLE:
            return user_has_operational_role(user, self.role)
        if self.rule_type == self.RuleType.MODULE:
            if not source_module:
                return False
            if self.source_module and self.source_module != source_module:
                return False
            if self.source_model and self.source_model != source_model:
                return False
            return True
        if self.rule_type == self.RuleType.RECORD:
            return (
                self.source_module == source_module
                and self.source_model == source_model
                and self.source_record_id == str(source_record_id)
            )
        return False

    def clean(self):
        super().clean()
        errors = {}
        if self.rule_type == self.RuleType.USER and not self.user:
            errors['user'] = 'Regra por usuário exige usuário.'
        if self.rule_type == self.RuleType.ROLE and not self.role:
            errors['role'] = 'Regra por papel exige papel.'
        if self.rule_type == self.RuleType.MODULE and not self.source_module:
            errors['source_module'] = 'Regra por módulo exige módulo.'
        if self.rule_type == self.RuleType.RECORD:
            if not self.source_module:
                errors['source_module'] = 'Regra por registro exige módulo.'
            if not self.source_model:
                errors['source_model'] = 'Regra por registro exige modelo.'
            if not self.source_record_id:
                errors['source_record_id'] = 'Regra por registro exige identificador.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.protected_file} - {self.get_rule_type_display()} - {self.get_permission_display()}'


class SecureFileLink(SingleInstanceModel):
    class Purpose(models.TextChoices):
        DOWNLOAD = 'download', 'Download'
        VIEW = 'view', 'Visualização'

    protected_file = models.ForeignKey(
        ProtectedFile,
        on_delete=models.CASCADE,
        related_name='secure_links',
        verbose_name='arquivo protegido',
    )
    token = models.CharField('token', max_length=128, unique=True, blank=True)
    purpose = models.CharField('finalidade', max_length=24, choices=Purpose.choices)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_secure_file_links',
        verbose_name='solicitado por',
    )
    expires_at = models.DateTimeField('expira em')
    max_uses = models.PositiveIntegerField('usos máximos', default=1)
    use_count = models.PositiveIntegerField('usos realizados', default=0)
    used_at = models.DateTimeField('usado em', null=True, blank=True)
    is_revoked = models.BooleanField('revogado', default=False)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='revoked_secure_file_links',
        null=True,
        blank=True,
        verbose_name='revogado por',
    )
    revoked_at = models.DateTimeField('revogado em', null=True, blank=True)
    revocation_reason = models.TextField('motivo da revogação', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['protected_file', 'purpose']),
            models.Index(fields=['requested_by']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['token']),
        ]
        verbose_name = 'link seguro de arquivo'
        verbose_name_plural = 'links seguros de arquivos'

    @property
    def is_valid(self):
        return (
            not self.is_revoked
            and self.expires_at >= timezone.now()
            and self.use_count < self.max_uses
        )

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = self._generate_token()
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def _generate_token(self):
        token = secrets.token_urlsafe(32)
        while SecureFileLink.objects.filter(token=token).exists():
            token = secrets.token_urlsafe(32)
        return token

    def use(self, user, ip_address='', user_agent=''):
        denial = None
        try:
            with transaction.atomic():
                link = (
                    SecureFileLink.objects.select_for_update()
                    .select_related('protected_file')
                    .get(pk=self.pk)
                )
                denial = self._denial_for_use(link, user)
                if denial is None:
                    return self._consume(link, user, ip_address, user_agent)
        except SecureFileLink.DoesNotExist:
            raise ValidationError({'token': 'Link inexistente.'}) from None
        # A negativa é registrada fora do bloco atômico para não sofrer rollback.
        field, message, details = denial
        link.protected_file.record_audit(
            ProtectedFileAuditTrail.Action.ACCESS_DENIED,
            user=user,
            secure_link=link,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
        )
        raise ValidationError({field: message})

    def _denial_for_use(self, link, user):
        permission = (
            ProtectedFileAccessRule.Permission.DOWNLOAD
            if link.purpose == link.Purpose.DOWNLOAD
            else ProtectedFileAccessRule.Permission.VIEW
        )
        if not link.is_valid:
            message = 'Link expirado, revogado ou sem usos disponíveis.'
            return 'token', message, {'reason': message}
        try:
            link.protected_file._assert_file_available()
        except ValidationError as error:
            field, messages = next(iter(error.message_dict.items()))
            return field, messages[0], {}
        if not link.protected_file.user_can_access(user, permission=permission):
            return 'permission', 'Usuário sem permissão para usar este link.', {}
        return None

    def _consume(self, link, user, ip_address, user_agent):
        link.use_count += 1
        link.used_at = timezone.now()
        link.save(update_fields=['use_count', 'used_at', 'updated_at'])
        action = (
            ProtectedFileAuditTrail.Action.DOWNLOAD
            if link.purpose == link.Purpose.DOWNLOAD
            else ProtectedFileAuditTrail.Action.VIEW
        )
        link.protected_file.record_access(
            user=user,
            action=action,
            secure_link=link,
            ip_address=ip_address,
            user_agent=user_agent,
            details={'token': link.token[-8:]},
        )
        self.use_count = link.use_count
        self.used_at = link.used_at
        return link.protected_file.file_reference

    def revoke(self, reason, user=None):
        if not reason:
            raise ValidationError({'reason': 'Informe o motivo da revogação.'})
        if self.is_revoked:
            raise ValidationError({'status': 'Link já está revogado.'})
        self.is_revoked = True
        self.revoked_by = user
        self.revoked_at = timezone.now()
        self.revocation_reason = reason
        self.save(
            update_fields=[
                'is_revoked',
                'revoked_by',
                'revoked_at',
                'revocation_reason',
                'updated_at',
            ]
        )
        self.protected_file.record_audit(
            ProtectedFileAuditTrail.Action.LINK_REVOKED,
            user=user,
            secure_link=self,
            details={'reason': reason},
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('requested_by', 'revoked_by'):
            pass
        if self.max_uses <= 0:
            errors['max_uses'] = 'O número máximo de usos deve ser maior que zero.'
        if self.expires_at and self.expires_at <= timezone.now() and not self.used_at:
            errors['expires_at'] = 'O link deve expirar no futuro.'
        if self.is_revoked:
            if not self.revoked_by:
                errors['revoked_by'] = 'Link revogado exige usuário responsável.'
            if not self.revoked_at:
                errors['revoked_at'] = 'Link revogado exige data da revogação.'
            if not self.revocation_reason:
                errors['revocation_reason'] = 'Link revogado exige justificativa.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.protected_file.file_number} - {self.get_purpose_display()}'


class ProtectedFileAuditTrail(SingleInstanceModel):
    class Action(models.TextChoices):
        UPLOAD = 'upload', 'Upload'
        DOWNLOAD = 'download', 'Download'
        VIEW = 'view', 'Visualização'
        REPLACE = 'replace', 'Substituição'
        DELETE = 'delete', 'Exclusão'
        EXPIRE = 'expire', 'Expiração'
        LINK_GENERATED = 'link_generated', 'Link gerado'
        LINK_REVOKED = 'link_revoked', 'Link revogado'
        ACCESS_DENIED = 'access_denied', 'Acesso negado'

    protected_file = models.ForeignKey(
        ProtectedFile,
        on_delete=models.CASCADE,
        related_name='audit_trail',
        verbose_name='arquivo protegido',
    )
    secure_link = models.ForeignKey(
        SecureFileLink,
        on_delete=models.SET_NULL,
        related_name='audit_trail',
        null=True,
        blank=True,
        verbose_name='link seguro',
    )
    action = models.CharField('ação', max_length=32, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='protected_file_audit_events',
        null=True,
        blank=True,
        verbose_name='usuário',
    )
    occurred_at = models.DateTimeField('ocorrido em', default=timezone.now)
    ip_address = models.GenericIPAddressField('IP', null=True, blank=True)
    user_agent = models.CharField('user agent', max_length=255, blank=True)
    details = models.JSONField('detalhes', default=dict, blank=True)

    class Meta:
        ordering = ['-occurred_at', '-created_at']
        indexes = [
            models.Index(fields=['protected_file', 'action']),
            models.Index(fields=['actor']),
            models.Index(fields=['occurred_at']),
            models.Index(fields=['action']),
        ]
        verbose_name = 'auditoria de arquivo protegido'
        verbose_name_plural = 'auditorias de arquivos protegidos'

    def clean(self):
        super().clean()
        errors = {}
        if self.secure_link and self.secure_link.protected_file_id != self.protected_file_id:
            errors['secure_link'] = 'O link seguro deve pertencer ao mesmo arquivo.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.protected_file.file_number} - {self.get_action_display()}'
