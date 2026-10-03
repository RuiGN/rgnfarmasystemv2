from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import re
import secrets
from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError
from defusedxml.common import DefusedXmlException
from django.core.files.storage import default_storage
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from files.models import ProtectedFile
from governance.models import InstitutionSettings
from procurement.models import (
    PurchaseOrder,
    PurchaseReceipt,
    PurchaseReceiptItem,
    ZERO_QUANTITY,
)


MAX_NFE_XML_SIZE = 10 * 1024 * 1024
CENT = Decimal('0.01')


class NfeImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NfeItemData:
    product_code: str
    description: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal
    product_total: Decimal
    tax_amount: Decimal
    lot_number: str
    manufacturing_date: date | None
    expiry_date: date | None


@dataclass(frozen=True, slots=True)
class NfeData:
    access_key: str
    number: str
    series: str
    issue_date: date
    model: str
    authorization_status: str
    supplier_document: str
    supplier_name: str
    destination_document: str
    product_total: Decimal
    items: tuple[NfeItemData, ...]
    xml_sha256: str
    raw_xml: bytes


def _local_name(tag):
    return str(tag).rsplit('}', 1)[-1]


def _first(element, name):
    return next((child for child in element.iter() if _local_name(child.tag) == name), None)


def _all(element, name):
    return tuple(child for child in element.iter() if _local_name(child.tag) == name)


def _text(element, name, *, required=True):
    child = _first(element, name)
    value = (child.text or '').strip() if child is not None else ''
    if required and not value:
        raise NfeImportError(f'O XML da NF-e não informa {name}.')
    return value


def _decimal(element, name, *, positive=False, default=None):
    raw = _text(element, name, required=default is None)
    if not raw and default is not None:
        return default
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise NfeImportError(f'O campo {name} deve conter um número válido.') from error
    if not value.is_finite():
        raise NfeImportError(f'O campo {name} deve conter um número finito.')
    if value < 0 or (positive and value <= 0):
        comparison = 'maior que zero' if positive else 'não negativo'
        raise NfeImportError(f'O campo {name} deve ser {comparison}.')
    return value


def _date(element, name):
    raw = _text(element, name, required=False)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except (TypeError, ValueError) as error:
        raise NfeImportError(f'O campo {name} deve conter uma data ISO válida.') from error


def _document(element):
    value = _text(element, 'CNPJ', required=False) or _text(element, 'CPF', required=False)
    digits = re.sub(r'\D', '', value)
    if not digits:
        raise NfeImportError('O XML da NF-e não informa o documento da parte.')
    return digits


def _raw_xml(xml_content):
    if hasattr(xml_content, 'read'):
        xml_content = xml_content.read()
    if isinstance(xml_content, str):
        xml_content = xml_content.encode('utf-8')
    if not isinstance(xml_content, (bytes, bytearray, memoryview)):
        raise NfeImportError('Informe o conteúdo XML da NF-e em bytes.')
    raw_xml = bytes(xml_content)
    if not raw_xml:
        raise NfeImportError('O arquivo XML da NF-e está vazio.')
    if len(raw_xml) > MAX_NFE_XML_SIZE:
        raise NfeImportError('O XML da NF-e não pode exceder 10 MiB.')
    upper_xml = raw_xml.upper()
    if b'<!DOCTYPE' in upper_xml or b'<!ENTITY' in upper_xml:
        raise NfeImportError('O XML da NF-e não pode conter DOCTYPE ou ENTITY.')
    return raw_xml


def _parse_item(det):
    product = _first(det, 'prod')
    if product is None:
        raise NfeImportError('Um item da NF-e não contém o grupo prod.')
    tracking = _first(product, 'rastro')
    manufacturing_date = _date(tracking, 'dFab') if tracking is not None else None
    expiry_date = _date(tracking, 'dVal') if tracking is not None else None
    if manufacturing_date and expiry_date and manufacturing_date > expiry_date:
        raise NfeImportError('A fabricação do lote não pode ser posterior à validade.')
    tax_group = _first(det, 'imposto')
    tax_amount = (
        _decimal(tax_group, 'vTotTrib', default=Decimal('0.00'))
        if tax_group is not None
        else Decimal('0.00')
    )
    return NfeItemData(
        product_code=_text(product, 'cProd'),
        description=_text(product, 'xProd'),
        quantity=_decimal(product, 'qCom', positive=True),
        unit_code=_text(product, 'uCom'),
        unit_price=_decimal(product, 'vUnCom'),
        product_total=_decimal(product, 'vProd'),
        tax_amount=tax_amount,
        lot_number=_text(tracking, 'nLote', required=False) if tracking is not None else '',
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
    )


def parse_nfe_xml(xml_content):
    raw_xml = _raw_xml(xml_content)
    try:
        root = ElementTree.fromstring(raw_xml)
    except (DefusedXmlException, ParseError, ValueError) as error:
        raise NfeImportError('O arquivo informado não contém um XML NF-e válido.') from error
    if _local_name(root.tag) != 'nfeProc':
        raise NfeImportError('O XML deve usar a estrutura autorizada nfeProc.')

    inf_nfe = _first(root, 'infNFe')
    inf_prot = _first(root, 'infProt')
    if inf_nfe is None or inf_prot is None:
        raise NfeImportError('O XML não contém os grupos obrigatórios da NF-e autorizada.')

    model = _text(inf_nfe, 'mod')
    if model != '55':
        raise NfeImportError('A importação aceita somente NF-e modelo 55.')
    authorization_status = _text(inf_prot, 'cStat')
    if authorization_status != '100':
        raise NfeImportError('A NF-e precisa estar autorizada com cStat 100.')
    access_key = _text(inf_prot, 'chNFe')
    if re.fullmatch(r'\d{44}', access_key) is None:
        raise NfeImportError('A chave de acesso da NF-e deve conter exatamente 44 dígitos.')
    if inf_nfe.attrib.get('Id') != f'NFe{access_key}':
        raise NfeImportError('A chave autorizada diverge do identificador infNFe.')

    ide = _first(inf_nfe, 'ide')
    supplier = _first(inf_nfe, 'emit')
    destination = _first(inf_nfe, 'dest')
    total_group = _first(inf_nfe, 'ICMSTot')
    if None in (ide, supplier, destination, total_group):
        raise NfeImportError('O XML não contém cabeçalho, partes e total obrigatórios.')

    issue_date = _date(ide, 'dhEmi')
    if issue_date is None:
        raise NfeImportError('O XML da NF-e não informa a data de emissão.')
    items = tuple(_parse_item(det) for det in _all(inf_nfe, 'det'))
    if not items:
        raise NfeImportError('A NF-e precisa conter ao menos um item.')
    product_total = _decimal(total_group, 'vProd')
    items_total = sum((item.product_total for item in items), Decimal('0.00')).quantize(CENT)
    if items_total != product_total.quantize(CENT):
        raise NfeImportError('O total dos itens diverge do total de produtos da NF-e.')

    return NfeData(
        access_key=access_key,
        number=_text(ide, 'nNF'),
        series=_text(ide, 'serie'),
        issue_date=issue_date,
        model=model,
        authorization_status=authorization_status,
        supplier_document=_document(supplier),
        supplier_name=_text(supplier, 'xNome'),
        destination_document=_document(destination),
        product_total=product_total,
        items=items,
        xml_sha256=hashlib.sha256(raw_xml).hexdigest(),
        raw_xml=raw_xml,
    )


def _only_digits(value):
    return re.sub(r'\D', '', str(value or ''))


def _safe_file_name(file_name):
    normalized = str(file_name or 'nfe.xml').replace('\\', '/')
    return (normalized.rsplit('/', 1)[-1] or 'nfe.xml')[:180]


def _cleanup_reserved_reference(reserved_reference):
    if reserved_reference and default_storage.exists(reserved_reference):
        default_storage.delete(reserved_reference)


def _constraint_name(error):
    cause = getattr(error, '__cause__', None)
    diagnostic = getattr(cause, 'diag', None)
    return getattr(diagnostic, 'constraint_name', '')


def _locked_order(purchase_order):
    return (
        PurchaseOrder.objects.select_for_update()
        .select_related('supplier')
        .prefetch_related('items__product', 'items__unit')
        .get(pk=purchase_order.pk)
    )


def _validate_import_parties(nfe, order):
    institution = InstitutionSettings.objects.filter(is_active=True).order_by('pk').first()
    if institution is None:
        raise NfeImportError('Cadastre os dados ativos da instituição antes de importar NF-e.')
    if _only_digits(institution.document) != nfe.destination_document:
        raise NfeImportError('O destinatário da NF-e diverge da instituição ativa.')
    if _only_digits(order.supplier.document) != nfe.supplier_document:
        raise NfeImportError('O documento do fornecedor da NF-e diverge do pedido.')


def _matched_order_items(nfe, order):
    order_items_by_code = {}
    for order_item in order.items.all():
        code = order_item.product.code.strip()
        if code in order_items_by_code:
            raise NfeImportError(
                f'O pedido possui mais de um item para o produto {code}; consolide-o antes da importação.'
            )
        order_items_by_code[code] = order_item

    matches = []
    incoming_by_order_item = {}
    for nfe_item in nfe.items:
        order_item = order_items_by_code.get(nfe_item.product_code.strip())
        if order_item is None:
            raise NfeImportError(
                f'O produto {nfe_item.product_code} da NF-e não existe no pedido aprovado.'
            )
        accepted_units = {order_item.unit.code.casefold(), order_item.unit.symbol.casefold()}
        if nfe_item.unit_code.casefold() not in accepted_units:
            raise NfeImportError(
                f'A unidade {nfe_item.unit_code} da NF-e diverge da unidade do produto '
                f'{nfe_item.product_code} no pedido.'
            )
        incoming_by_order_item[order_item.pk] = (
            incoming_by_order_item.get(order_item.pk, ZERO_QUANTITY) + nfe_item.quantity
        )
        matches.append((nfe_item, order_item))

    for order_item in order_items_by_code.values():
        incoming = incoming_by_order_item.get(order_item.pk, ZERO_QUANTITY)
        if incoming == ZERO_QUANTITY:
            continue
        consumed = (
            PurchaseReceiptItem.objects.filter(order_item=order_item)
            .exclude(receipt__status=PurchaseReceipt.Status.CANCELLED)
            .aggregate(total=models.Sum('received_quantity'))['total']
            or ZERO_QUANTITY
        )
        remaining = order_item.quantity - consumed
        if incoming > remaining:
            raise NfeImportError(
                f'A quantidade da NF-e para {order_item.product.code} supera o saldo '
                f'do pedido ({remaining}).'
            )
    return tuple(matches)


def _create_protected_nfe_file(nfe, receipt, user, file_name, reserved_reference):
    protected_file = ProtectedFile.objects.create(
        source_module=ProtectedFile.SourceModule.FISCAL,
        source_model='PurchaseReceipt',
        source_record_id=str(receipt.pk),
        file_type=ProtectedFile.FileType.FISCAL_DOCUMENT,
        origin=ProtectedFile.Origin.UPLOAD,
        criticality=ProtectedFile.Criticality.HIGH,
        confidentiality=ProtectedFile.Confidentiality.INTERNAL,
        title=f'XML NF-e {nfe.number}',
        file_name=_safe_file_name(file_name),
        file_reference=reserved_reference,
        mime_type='application/xml',
        file_size=len(nfe.raw_xml),
        content_hash=f'sha256:{nfe.xml_sha256}',
        responsible=user,
        uploaded_by=user,
    )
    protected_file.store_encrypted_content(
        nfe.raw_xml,
        file_name=_safe_file_name(file_name),
        mime_type='application/xml',
        user=user,
        reserved_reference=reserved_reference,
    )
    return protected_file


def import_nfe_into_purchase_order(
    xml_content,
    *,
    purchase_order,
    user,
    file_name='nfe.xml',
):
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        raise NfeImportError('A importação exige um usuário autenticado e ativo.')
    nfe = parse_nfe_xml(xml_content)
    reserved_reference = ''
    try:
        with transaction.atomic():
            order = _locked_order(purchase_order)
            if order.status != PurchaseOrder.Status.APPROVED:
                raise NfeImportError('A NF-e só pode ser importada em um pedido aprovado.')
            _validate_import_parties(nfe, order)
            if PurchaseReceipt.objects.filter(nfe_access_key=nfe.access_key).exists():
                raise NfeImportError('A NF-e já foi importada no sistema.')
            matches = _matched_order_items(nfe, order)

            receipt = PurchaseReceipt.objects.create(
                order=order,
                status=PurchaseReceipt.Status.DRAFT,
                fiscal_document_number=nfe.number,
                fiscal_received_at=timezone.now(),
                quality_status=PurchaseReceipt.QualityStatus.PENDING,
                stock_entry_status=PurchaseReceipt.StockEntryStatus.PENDING,
                received_by=user,
                nfe_access_key=nfe.access_key,
                nfe_xml_sha256=nfe.xml_sha256,
            )
            for nfe_item, order_item in matches:
                receipt_item = PurchaseReceiptItem(
                    receipt=receipt,
                    order_item=order_item,
                    product=order_item.product,
                    received_quantity=nfe_item.quantity,
                    accepted_quantity=ZERO_QUANTITY,
                    rejected_quantity=ZERO_QUANTITY,
                    unit=order_item.unit,
                    lot_number=nfe_item.lot_number,
                    manufacturing_date=nfe_item.manufacturing_date,
                    expiry_date=nfe_item.expiry_date,
                )
                receipt_item.full_clean()
                receipt_item.save()

            token = secrets.token_urlsafe(18)
            reserved_reference = f'protected/nfe-{nfe.access_key}/{token}.enc'
            protected_file = _create_protected_nfe_file(
                nfe,
                receipt,
                user,
                file_name,
                reserved_reference,
            )
            receipt.nfe_xml_file = protected_file
            receipt.save(update_fields={'nfe_xml_file', 'updated_at'})
            return receipt
    except IntegrityError as error:
        _cleanup_reserved_reference(reserved_reference)
        if _constraint_name(error) == 'unique_purchase_receipt_nfe_access_key':
            raise NfeImportError('A NF-e já foi importada no sistema.') from error
        raise
    except Exception:
        _cleanup_reserved_reference(reserved_reference)
        raise
