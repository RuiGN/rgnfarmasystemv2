from datetime import date, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from base.ui.actions.registry import action_registry
from base.ui.actions.types import FieldKind, SubmissionFormat
from files.models import ProtectedFile, ProtectedFileAuditTrail
from governance.models import InstitutionSettings
from inventory.models import StockBalance, StockLot, StockMovement
from masters.models import BusinessPartner, Product, UnitOfMeasure
from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)


User = get_user_model()


NFE_KEY = '2' * 44
NFE_NAMESPACE = 'http://www.portalfiscal.inf.br/nfe'


def nfe_parser_contract():
    try:
        from procurement.nfe_xml_import import (
            MAX_NFE_XML_SIZE,
            NfeImportError,
            parse_nfe_xml,
        )
    except ModuleNotFoundError:
        pytest.fail('O parser de NF-e ainda não foi implementado.')
    return MAX_NFE_XML_SIZE, NfeImportError, parse_nfe_xml


def authorized_nfe_xml(
    *,
    key=NFE_KEY,
    inf_key=None,
    model='55',
    status='100',
    quantity='2.5000',
    unit_price='10.0000',
    item_total='25.00',
    product_total='25.00',
    product_code='PROD-NFE-001',
    unit_code='KG',
    supplier_document='11222333000181',
    destination_document='99888777000166',
    include_item=True,
):
    inf_key = key if inf_key is None else inf_key
    item = ''
    if include_item:
        item = f"""
        <det nItem="1">
          <prod>
            <cProd>{product_code}</cProd>
            <xProd>Glicerina vegetal</xProd>
            <qCom>{quantity}</qCom>
            <uCom>{unit_code}</uCom>
            <vUnCom>{unit_price}</vUnCom>
            <vProd>{item_total}</vProd>
            <rastro>
              <nLote>LOTE-GLI-001</nLote>
              <qLote>{quantity}</qLote>
              <dFab>2026-08-01</dFab>
              <dVal>2027-08-01</dVal>
            </rastro>
          </prod>
          <imposto><vTotTrib>1.25</vTotTrib></imposto>
        </det>"""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
    <nfeProc xmlns="{NFE_NAMESPACE}" versao="4.00">
      <NFe>
        <infNFe Id="NFe{inf_key}" versao="4.00">
          <ide>
            <mod>{model}</mod>
            <serie>1</serie>
            <nNF>12345</nNF>
            <dhEmi>2026-09-01T10:15:00-03:00</dhEmi>
          </ide>
          <emit>
            <CNPJ>{supplier_document}</CNPJ>
            <xNome>Fornecedor Cosmético Ltda</xNome>
          </emit>
          <dest><CNPJ>{destination_document}</CNPJ></dest>
          {item}
          <total><ICMSTot><vProd>{product_total}</vProd></ICMSTot></total>
        </infNFe>
      </NFe>
      <protNFe>
        <infProt>
          <chNFe>{key}</chNFe>
          <cStat>{status}</cStat>
        </infProt>
      </protNFe>
    </nfeProc>'''.encode()


def test_parse_authorized_model_55_nfe_with_namespaces_and_lot_data():
    _max_size, _error, parse_nfe_xml = nfe_parser_contract()
    xml = authorized_nfe_xml()

    parsed = parse_nfe_xml(xml)

    assert parsed.access_key == NFE_KEY
    assert parsed.number == '12345'
    assert parsed.series == '1'
    assert parsed.issue_date == date(2026, 9, 1)
    assert parsed.model == '55'
    assert parsed.authorization_status == '100'
    assert parsed.supplier_document == '11222333000181'
    assert parsed.supplier_name == 'Fornecedor Cosmético Ltda'
    assert parsed.destination_document == '99888777000166'
    assert parsed.product_total == Decimal('25.00')
    assert parsed.xml_sha256 == hashlib.sha256(xml).hexdigest()
    assert parsed.raw_xml == xml
    assert len(parsed.items) == 1
    item = parsed.items[0]
    assert item.product_code == 'PROD-NFE-001'
    assert item.description == 'Glicerina vegetal'
    assert item.quantity == Decimal('2.5000')
    assert item.unit_code == 'KG'
    assert item.unit_price == Decimal('10.0000')
    assert item.product_total == Decimal('25.00')
    assert item.tax_amount == Decimal('1.25')
    assert item.lot_number == 'LOTE-GLI-001'
    assert item.manufacturing_date == date(2026, 8, 1)
    assert item.expiry_date == date(2027, 8, 1)


@pytest.mark.parametrize(
    ('overrides', 'expected_fragment'),
    (
        ({'model': '65'}, 'modelo 55'),
        ({'status': '110'}, 'autorizada'),
        ({'key': '123'}, '44 dígitos'),
        ({'inf_key': '3' * 44}, 'diverge'),
        ({'include_item': False, 'product_total': '0.00'}, 'item'),
    ),
)
def test_parse_rejects_invalid_nfe_identity_or_authorization(overrides, expected_fragment):
    _max_size, error_class, parse_nfe_xml = nfe_parser_contract()

    with pytest.raises(error_class) as error:
        parse_nfe_xml(authorized_nfe_xml(**overrides))

    assert expected_fragment.casefold() in str(error.value).casefold()


@pytest.mark.parametrize(
    'overrides',
    (
        {'quantity': '-1.0000', 'item_total': '-10.00', 'product_total': '-10.00'},
        {'quantity': 'NaN'},
        {'unit_price': 'Infinity'},
        {'item_total': 'NaN', 'product_total': 'NaN'},
    ),
)
def test_parse_rejects_negative_or_non_finite_numbers(overrides):
    _max_size, error_class, parse_nfe_xml = nfe_parser_contract()

    with pytest.raises(error_class):
        parse_nfe_xml(authorized_nfe_xml(**overrides))


def test_parse_rejects_malformed_and_mismatched_totals():
    _max_size, error_class, parse_nfe_xml = nfe_parser_contract()

    with pytest.raises(error_class):
        parse_nfe_xml(b'<nfeProc>')
    with pytest.raises(error_class) as mismatch:
        parse_nfe_xml(authorized_nfe_xml(product_total='24.99'))

    assert 'total' in str(mismatch.value).casefold()


def test_malicious_doctype_and_entity_are_rejected_before_xml_parsing():
    _max_size, error_class, parse_nfe_xml = nfe_parser_contract()
    malicious = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>' + authorized_nfe_xml()

    with pytest.raises(error_class) as error:
        parse_nfe_xml(malicious)

    assert 'doctype' in str(error.value).casefold() or 'entity' in str(error.value).casefold()


def test_size_limit_accepts_exactly_ten_mib_and_rejects_one_extra_byte():
    max_size, error_class, parse_nfe_xml = nfe_parser_contract()
    xml = authorized_nfe_xml()
    closing_tag = b'</nfeProc>'
    closing_index = xml.rfind(closing_tag)
    comment_overhead = len(b'<!---->')
    padding_size = max_size - len(xml) - comment_overhead
    exact_xml = xml[:closing_index] + b'<!--' + (b'x' * padding_size) + b'-->' + xml[closing_index:]

    assert len(exact_xml) == max_size
    assert parse_nfe_xml(exact_xml).access_key == NFE_KEY

    with pytest.raises(error_class) as error:
        parse_nfe_xml(exact_xml + b' ')

    assert '10 MiB' in str(error.value)


def nfe_import_contract():
    from procurement import nfe_xml_import

    importer = getattr(nfe_xml_import, 'import_nfe_into_purchase_order', None)
    if importer is None:
        pytest.fail('O serviço transacional de importação NF-e ainda não foi implementado.')
    return nfe_xml_import.NfeImportError, importer


class NfeImportServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='nfe.import@example.com',
            email='nfe.import@example.com',
            password='S3curePass!123',
        )
        InstitutionSettings.objects.create(
            legal_name='Indústria Cosmética Importadora Ltda',
            trade_name='Cosmética Importadora',
            document='99.888.777/0001-66',
            is_active=True,
        )
        self.unit = UnitOfMeasure.objects.create(
            code='KG',
            name='Quilograma',
            symbol='kg',
        )
        self.product = Product.objects.create(
            code='PROD-NFE-001',
            description='Glicerina vegetal',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=self.unit,
            status=Product.Status.APPROVED,
            requires_approved_supplier=False,
        )
        self.supplier = BusinessPartner.objects.create(
            code='FOR-NFE-001',
            legal_name='Fornecedor Cosmético Ltda',
            document='11.222.333/0001-81',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
        )
        self.order = PurchaseOrder.objects.create(
            order_number='PC-NFE-001',
            supplier=self.supplier,
            status=PurchaseOrder.Status.APPROVED,
            issue_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=5),
        )
        self.order_item = PurchaseOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=Decimal('10.0000'),
            unit=self.unit,
            unit_price=Decimal('10.0000'),
        )

    def _import(self, xml=None, **kwargs):
        _error_class, importer = nfe_import_contract()
        return importer(
            xml or authorized_nfe_xml(),
            purchase_order=self.order,
            user=self.user,
            file_name=kwargs.pop('file_name', 'nota-12345.xml'),
            **kwargs,
        )

    def test_import_creates_draft_receipt_items_and_encrypted_audit_without_stock(self):
        xml = authorized_nfe_xml()
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                receipt = self._import(xml)
                receipt.refresh_from_db()
                protected_file = receipt.nfe_xml_file
                encrypted_payload = Path(media_root, protected_file.file_reference).read_bytes()

                assert receipt.status == PurchaseReceipt.Status.DRAFT
                assert receipt.quality_status == PurchaseReceipt.QualityStatus.PENDING
                assert receipt.stock_entry_status == PurchaseReceipt.StockEntryStatus.PENDING
                assert receipt.fiscal_document_number == '12345'
                assert receipt.nfe_access_key == NFE_KEY
                assert receipt.nfe_xml_sha256 == hashlib.sha256(xml).hexdigest()
                assert receipt.received_by == self.user
                assert receipt.physical_received_at is None
                assert receipt.items.count() == 1
                item = receipt.items.get()
                assert item.order_item == self.order_item
                assert item.product == self.product
                assert item.received_quantity == Decimal('2.5000')
                assert item.accepted_quantity == Decimal('0.0000')
                assert item.rejected_quantity == Decimal('0.0000')
                assert item.unit == self.unit
                assert item.lot_number == 'LOTE-GLI-001'
                assert item.manufacturing_date == date(2026, 8, 1)
                assert item.expiry_date == date(2027, 8, 1)
                assert protected_file.is_encrypted is True
                assert protected_file.content_hash == f'sha256:{receipt.nfe_xml_sha256}'
                assert protected_file.read_encrypted_content(self.user) == xml
                assert xml not in encrypted_payload
                assert protected_file.audit_trail.filter(
                    action=ProtectedFileAuditTrail.Action.UPLOAD,
                    actor=self.user,
                ).exists()

        assert StockLot.objects.count() == 0
        assert StockBalance.objects.count() == 0
        assert StockMovement.objects.count() == 0

    def test_import_rejects_order_that_is_not_approved(self):
        error_class, _importer = nfe_import_contract()
        self.order.status = PurchaseOrder.Status.DRAFT
        self.order.save(update_fields=['status', 'updated_at'])

        with pytest.raises(error_class) as error:
            self._import()

        assert 'aprovado' in str(error.value).casefold()
        assert not PurchaseReceipt.objects.exists()

    def test_import_rejects_destination_and_supplier_document_mismatches(self):
        error_class, _importer = nfe_import_contract()

        for xml, fragment in (
            (authorized_nfe_xml(destination_document='11111111000111'), 'destinatário'),
            (authorized_nfe_xml(supplier_document='22222222000122'), 'fornecedor'),
        ):
            with pytest.raises(error_class) as error:
                self._import(xml)
            assert fragment in str(error.value).casefold()

        assert not PurchaseReceipt.objects.exists()

    def test_import_rejects_unknown_product_or_incompatible_unit(self):
        error_class, _importer = nfe_import_contract()

        for xml, fragment in (
            (authorized_nfe_xml(product_code='DESCONHECIDO'), 'produto'),
            (authorized_nfe_xml(unit_code='L'), 'unidade'),
        ):
            with pytest.raises(error_class) as error:
                self._import(xml)
            assert fragment in str(error.value).casefold()

        assert not PurchaseReceipt.objects.exists()

    def test_import_rejects_quantity_above_remaining_order_balance(self):
        error_class, _importer = nfe_import_contract()
        previous_receipt = PurchaseReceipt.objects.create(order=self.order)
        PurchaseReceiptItem.objects.create(
            receipt=previous_receipt,
            order_item=self.order_item,
            product=self.product,
            received_quantity=Decimal('8.0000'),
            unit=self.unit,
        )

        with pytest.raises(error_class) as error:
            self._import()

        assert 'saldo' in str(error.value).casefold()
        assert PurchaseReceipt.objects.count() == 1

    def test_import_rejects_duplicate_access_key(self):
        error_class, _importer = nfe_import_contract()
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                first = self._import()
                with pytest.raises(error_class) as error:
                    self._import()

                assert 'já foi importada' in str(error.value)
                assert PurchaseReceipt.objects.filter(nfe_access_key=NFE_KEY).count() == 1
                assert ProtectedFile.objects.count() == 1
                assert first.nfe_xml_file.read_encrypted_content(self.user) == authorized_nfe_xml()

    def test_import_cleans_reserved_encrypted_file_when_link_save_fails(self):
        original_save = PurchaseReceipt.save

        def fail_when_linking(receipt, *args, **kwargs):
            if 'nfe_xml_file' in set(kwargs.get('update_fields') or ()):
                raise RuntimeError('falha simulada ao vincular XML')
            return original_save(receipt, *args, **kwargs)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with patch.object(PurchaseReceipt, 'save', new=fail_when_linking):
                    with pytest.raises(RuntimeError, match='falha simulada'):
                        self._import()

                assert list(Path(media_root).rglob('*.enc')) == []
                assert not PurchaseReceipt.objects.exists()
                assert not ProtectedFile.objects.exists()


class NfeImportEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='nfe.endpoint@example.com',
            email='nfe.endpoint@example.com',
            password='S3curePass!123',
        )
        InstitutionSettings.objects.create(
            legal_name='Indústria Cosmética Endpoint Ltda',
            document='99.888.777/0001-66',
            is_active=True,
        )
        self.unit = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        self.product = Product.objects.create(
            code='PROD-NFE-001',
            description='Glicerina vegetal',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=self.unit,
            status=Product.Status.APPROVED,
            requires_approved_supplier=False,
        )
        supplier = BusinessPartner.objects.create(
            code='FOR-NFE-ENDPOINT',
            legal_name='Fornecedor Cosmético Endpoint Ltda',
            document='11.222.333/0001-81',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
        )
        self.order = PurchaseOrder.objects.create(
            order_number='PC-NFE-ENDPOINT',
            supplier=supplier,
            status=PurchaseOrder.Status.APPROVED,
            issue_date=timezone.localdate(),
        )
        self.order_item = PurchaseOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=Decimal('10.0000'),
            unit=self.unit,
            unit_price=Decimal('10.0000'),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.endpoint = '/api/v1/procurement/receipts/import_xml/'

    def _grant(self, action):
        permission = Permission.objects.get(
            content_type__app_label='procurement',
            content_type__model='purchasereceipt',
            codename=f'{action}_purchasereceipt',
        )
        self.user.user_permissions.add(permission)
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

    def _grant_html_views(self):
        permissions = Permission.objects.filter(
            content_type__app_label='procurement',
            codename__in=('view_purchaseorder', 'view_purchasereceipt'),
        )
        self.user.user_permissions.add(*permissions)
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

    def _upload(self, xml=None):
        return SimpleUploadedFile(
            'nota-12345.xml',
            xml or authorized_nfe_xml(),
            content_type='application/xml',
        )

    def _html_endpoint(self):
        return reverse(
            'app:collection_action',
            args=('procurement', 'receipts', 'import_xml'),
        )

    def test_html_catalog_exposes_secure_multipart_import_contract(self):
        config = action_registry.get('procurement', 'receipts', 'import_xml')

        assert config.route_name == 'v1_procurement:receipt-import-xml'
        assert config.permissions == ('procurement.add_purchasereceipt',)
        assert config.detail is False
        assert config.submission_format == SubmissionFormat.MULTIPART
        assert config.icon == 'feather-upload'
        assert tuple((field.name, field.kind) for field in config.fields) == (
            ('order_id', FieldKind.RELATION),
            ('xml', FieldKind.FILE),
        )

    def test_html_form_lists_only_approved_purchase_orders(self):
        self._grant('add')
        self._grant_html_views()
        draft_order = PurchaseOrder.objects.create(
            order_number='PC-NFE-DRAFT',
            supplier=self.order.supplier,
            status=PurchaseOrder.Status.DRAFT,
            issue_date=timezone.localdate(),
        )
        self.client.force_login(self.user)

        response = self.client.get(self._html_endpoint())

        assert response.status_code == 200
        queryset = response.context['form'].fields['order_id'].queryset
        assert self.order in queryset
        assert draft_order not in queryset
        assert response.context['form'].is_multipart()

    def test_html_form_imports_xml_and_redirects_to_receipt_list(self):
        self._grant('add')
        self._grant_html_views()
        self.client.force_login(self.user)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    self._html_endpoint(),
                    {'order_id': self.order.pk, 'xml': self._upload()},
                )

        assert response.status_code == 302
        assert response.url == reverse(
            'app:resource_list',
            args=('procurement', 'receipts'),
        )
        assert PurchaseReceipt.objects.filter(
            order=self.order,
            nfe_access_key=NFE_KEY,
        ).exists()

    def test_endpoint_imports_multipart_xml_and_returns_nested_items(self):
        self._grant('add')
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    self.endpoint,
                    {'order_id': self.order.pk, 'xml': self._upload()},
                    format='multipart',
                )

        assert response.status_code == 201
        payload = response.json()
        assert payload['nfe_access_key'] == NFE_KEY
        assert len(payload['nfe_xml_sha256']) == 64
        assert payload['nfe_xml_file'] is not None
        assert len(payload['items']) == 1
        assert payload['items'][0]['product'] == self.product.pk
        assert payload['items'][0]['manufacturing_date'] == '2026-08-01'

    def test_endpoint_rejects_missing_fields_and_domain_errors(self):
        self._grant('add')

        missing = self.client.post(self.endpoint, {'order_id': self.order.pk}, format='multipart')
        self.order.status = PurchaseOrder.Status.DRAFT
        self.order.save(update_fields=['status', 'updated_at'])
        invalid = self.client.post(
            self.endpoint,
            {'order_id': self.order.pk, 'xml': self._upload()},
            format='multipart',
        )

        assert missing.status_code == 400
        assert 'arquivo XML' in missing.json()['detail']
        assert invalid.status_code == 400
        assert 'aprovado' in invalid.json()['detail'].casefold()

    def test_endpoint_requires_add_purchase_receipt_permission(self):
        response = self.client.post(
            self.endpoint,
            {'order_id': self.order.pk, 'xml': self._upload()},
            format='multipart',
        )

        assert response.status_code == 403
        assert not PurchaseReceipt.objects.exists()

    def test_endpoint_ordinary_crud_ignores_read_only_nfe_metadata(self):
        self._grant('add')

        response = self.client.post(
            '/api/v1/procurement/receipts/',
            {
                'order': self.order.pk,
                'fiscal_document_number': 'MANUAL-001',
                'nfe_access_key': '9' * 44,
                'nfe_xml_sha256': 'f' * 64,
                'nfe_xml_file': 999999,
            },
            format='json',
        )

        assert response.status_code == 201
        receipt = PurchaseReceipt.objects.get(pk=response.json()['id'])
        assert receipt.nfe_access_key == ''
        assert receipt.nfe_xml_sha256 == ''
        assert receipt.nfe_xml_file is None


class NfeImportSchemaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='nfe.schema@example.com',
            email='nfe.schema@example.com',
            password='S3curePass!123',
        )
        self.unit = UnitOfMeasure.objects.create(
            code='UN-NFE-SCHEMA',
            name='Unidade NF-e',
            symbol='UN',
        )
        self.product = Product.objects.create(
            code='PROD-NFE-SCHEMA',
            description='Produto para recebimento NF-e',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=self.unit,
            status=Product.Status.APPROVED,
            requires_approved_supplier=False,
        )
        self.supplier = BusinessPartner.objects.create(
            code='FOR-NFE-SCHEMA',
            legal_name='Fornecedor NF-e Schema Ltda',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
        )
        self.order = PurchaseOrder.objects.create(
            order_number='PC-NFE-SCHEMA',
            supplier=self.supplier,
            issue_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=5),
        )
        self.order_item = PurchaseOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=Decimal('10.0000'),
            unit=self.unit,
            unit_price=Decimal('5.0000'),
        )

    def _receipt(self, **overrides):
        payload = {'order': self.order, **overrides}
        return PurchaseReceipt.objects.create(**payload)

    def _protected_file(self):
        return ProtectedFile.objects.create(
            source_module=ProtectedFile.SourceModule.FISCAL,
            source_model='PurchaseReceipt',
            source_record_id='pending',
            file_type=ProtectedFile.FileType.FISCAL_DOCUMENT,
            origin=ProtectedFile.Origin.UPLOAD,
            criticality=ProtectedFile.Criticality.HIGH,
            confidentiality=ProtectedFile.Confidentiality.INTERNAL,
            title='XML NF-e protegido',
            file_name='nfe.xml',
            file_reference='pending',
            mime_type='application/xml',
            file_size=0,
            content_hash='sha256:pending',
            responsible=self.user,
            uploaded_by=self.user,
        )

    def test_schema_purchase_receipt_exposes_nfe_metadata(self):
        field_names = {field.name for field in PurchaseReceipt._meta.fields}

        assert {'nfe_access_key', 'nfe_xml_sha256', 'nfe_xml_file'} <= field_names
        assert PurchaseReceipt._meta.get_field('nfe_access_key').max_length == 44
        assert PurchaseReceipt._meta.get_field('nfe_xml_sha256').max_length == 64

    def test_schema_nfe_access_key_is_conditionally_unique(self):
        assert any(field.name == 'nfe_access_key' for field in PurchaseReceipt._meta.fields)
        key = '1' * 44
        self._receipt(nfe_access_key=key)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                self._receipt(nfe_access_key=key)

        self._receipt(nfe_access_key='')
        self._receipt(nfe_access_key='')

    def test_schema_nfe_xml_file_is_protected_from_deletion(self):
        assert any(field.name == 'nfe_xml_file' for field in PurchaseReceipt._meta.fields)
        protected_file = self._protected_file()
        self._receipt(nfe_xml_file=protected_file)

        with pytest.raises(ProtectedError):
            protected_file.delete()

    def test_schema_manufacturing_date_persists_and_precedes_expiry(self):
        assert any(field.name == 'manufacturing_date' for field in PurchaseReceiptItem._meta.fields)
        receipt = self._receipt()
        item = PurchaseReceiptItem.objects.create(
            receipt=receipt,
            order_item=self.order_item,
            product=self.product,
            received_quantity=Decimal('2.0000'),
            unit=self.unit,
            manufacturing_date=date(2026, 8, 1),
            expiry_date=date(2027, 8, 1),
        )

        item.refresh_from_db()
        assert item.manufacturing_date == date(2026, 8, 1)

        item.manufacturing_date = date(2028, 1, 1)
        with pytest.raises(ValidationError) as error:
            item.full_clean()

        assert 'manufacturing_date' in error.value.message_dict
