import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from inventory.models import StockQualityStatus
from masters.models import BusinessPartner, Product
from tests.test_qa import (
    create_approved_release_evidence,
    create_qa_item,
    create_quality_document,
)


pytestmark = pytest.mark.django_db
User = get_user_model()


def make_user(name):
    return User.objects.create_user(
        username=f'{name}@example.com', email=f'{name}@example.com', password='S3curePass!123'
    )


def make_release(suffix='FIX', with_review=True, with_document=True):
    from qa.models import LotRelease

    unit, product, lot = create_qa_item(suffix=suffix)
    review, document = create_approved_release_evidence(
        product, lot, unit, suffix, make_user(f'aprov-{suffix.lower()}')
    )
    release = LotRelease.objects.create(
        product=product,
        stock_lot=lot,
        qa_review=review if with_review else None,
        quality_document=document if with_document else None,
    )
    return release, review, document, lot, unit


# --- Fix 1: mandatory release evidence ---------------------------------------


def test_release_requires_qa_review():
    release, *_ = make_release('NOREV', with_review=False)
    with pytest.raises(ValidationError) as error:
        release.approve(user=make_user('lib1'), decision='ok')
    assert 'qa_review' in error.value.message_dict


def test_release_requires_issued_quality_document():
    release, review, *_ = make_release('NODOC', with_document=False)
    type(review).objects.filter(pk=review.pk).update(quality_document=None)
    with pytest.raises(ValidationError) as error:
        release.approve(user=make_user('lib2'), decision='ok')
    assert 'quality_document' in error.value.message_dict


def test_release_rejects_unapproved_review_and_unissued_document():
    from qa.models import QAReview
    from quality.models import QualityDocument

    release, review, document, _lot, _unit = make_release('BAD')
    QAReview.objects.filter(pk=review.pk).update(status=QAReview.Status.DRAFT)
    with pytest.raises(ValidationError) as error:
        release.approve(user=make_user('lib3'), decision='ok')
    assert 'qa_review' in error.value.message_dict
    QAReview.objects.filter(pk=review.pk).update(status=QAReview.Status.APPROVED)
    QualityDocument.objects.filter(pk=document.pk).update(status=QualityDocument.Status.DRAFT)
    with pytest.raises(ValidationError) as error:
        release.approve(user=make_user('lib4'), decision='ok')
    assert 'quality_document' in error.value.message_dict


def test_release_rejects_document_from_other_lot():
    release, _review, _document, _lot, _unit = make_release('OWN')
    other_unit, other_product, other_lot = create_qa_item(suffix='OWN2')
    other_document = create_quality_document(other_product, other_lot, other_unit, suffix='OWN2')
    type(release).objects.filter(pk=release.pk).update(quality_document=other_document)
    release.refresh_from_db()
    with pytest.raises(ValidationError):
        release.approve(user=make_user('lib5'), decision='ok')


def test_release_blocked_by_open_investigation_then_allowed_after_conclusion():
    from quality.models import LaboratoryInvestigation

    release, _review, document, lot, _unit = make_release('INV')
    investigation = LaboratoryInvestigation.objects.create(
        sample=document.sample,
        investigation_type=LaboratoryInvestigation.InvestigationType.LABORATORY,
        justification='Resultado limítrofe.',
    )
    actor = make_user('lib6')
    with pytest.raises(ValidationError) as error:
        release.approve(user=actor, decision='ok')
    assert 'release_status' in error.value.message_dict

    investigation.conclude('Erro de diluição', 'Sem impacto no lote.', user=actor)
    release.approve(user=actor, decision='Liberado.')
    lot.refresh_from_db()
    assert release.release_status == type(release).ReleaseStatus.RELEASED
    assert lot.quality_status == StockQualityStatus.APPROVED


def test_release_happy_path_with_full_evidence():
    release, _review, _document, lot, _unit = make_release('OK')
    release.approve(user=make_user('lib7'), decision='Liberado.')
    lot.refresh_from_db()
    assert lot.quality_status == StockQualityStatus.APPROVED


# --- Fix 2: QualityBlock.unblock ----------------------------------------------


def make_block(lot=None, product=None, supplier=None, user=None):
    from qa.models import QualityBlock

    block = QualityBlock.objects.create(
        target_type=QualityBlock.TargetType.LOT,
        product=product,
        stock_lot=lot,
        supplier=supplier,
        reason='Falha crítica.',
        blocked_by=user,
    )
    block.apply()
    return block


def test_unblock_only_from_active():
    from qa.models import QualityBlock

    _unit, _product, lot = create_qa_item('BLK1')
    blocker, other = make_user('blk-a'), make_user('blk-b')
    block = make_block(lot=lot, user=blocker)
    block.unblock('Avaliado.', user=other)
    assert block.status == QualityBlock.Status.UNBLOCKED
    with pytest.raises(ValidationError) as error:
        block.unblock('Repetido.', user=other)
    assert 'status' in error.value.message_dict


def test_unblock_keeps_lot_blocked_while_another_active_block_targets_it():
    _unit, _product, lot = create_qa_item('BLK2')
    blocker, other = make_user('blk-c'), make_user('blk-d')
    first = make_block(lot=lot, user=blocker)
    make_block(lot=lot, user=blocker)
    first.unblock('Avaliado.', user=other)
    lot.refresh_from_db()
    assert lot.quality_status == StockQualityStatus.BLOCKED


def test_unblock_keeps_product_and_supplier_blocked_by_other_active_blocks():
    _unit, product, _lot = create_qa_item('BLK3')
    supplier = BusinessPartner.objects.create(
        code='FOR-BLK3',
        legal_name='Fornecedor BLK3',
        partner_type=BusinessPartner.PartnerType.SUPPLIER,
    )
    blocker, other = make_user('blk-e'), make_user('blk-f')
    first = make_block(product=product, supplier=supplier, user=blocker)
    make_block(product=product, supplier=supplier, user=blocker)
    first.unblock('Avaliado.', user=other)
    product.refresh_from_db()
    supplier.refresh_from_db()
    assert product.status == Product.Status.BLOCKED
    assert supplier.is_blocked is True


def test_unblock_never_moves_rejected_lot_back_to_quarantine():
    from qa.models import QualityBlock

    _unit, _product, lot = create_qa_item('BLK4')
    blocker, other = make_user('blk-g'), make_user('blk-h')
    block = make_block(lot=lot, user=blocker)
    lot.quality_status = StockQualityStatus.REJECTED
    lot.save(update_fields=['quality_status', 'updated_at'])
    block.unblock('Avaliado.', user=other)
    lot.refresh_from_db()
    assert block.status == QualityBlock.Status.UNBLOCKED
    assert lot.quality_status == StockQualityStatus.REJECTED


def test_unblock_records_audit_log_and_restores_when_alone():
    from governance.models import GovernanceAuditLog

    _unit, _product, lot = create_qa_item('BLK5')
    blocker, other = make_user('blk-i'), make_user('blk-j')
    block = make_block(lot=lot, user=blocker)
    block.unblock('Avaliado.', user=other)
    lot.refresh_from_db()
    assert lot.quality_status == StockQualityStatus.QUARANTINE
    assert GovernanceAuditLog.objects.filter(
        action='qa.quality_block.unblocked', target_record_id=str(block.pk)
    ).exists()


# --- Fix 3: status guards -----------------------------------------------------


def test_sample_cancel_blocked_from_approved_and_allowed_when_requested():
    from quality.models import QualitySample

    unit, product, lot = create_qa_item('SMP2')
    approved_doc = create_quality_document(product, lot, unit, suffix='SMP2')
    approved_sample = approved_doc.sample
    assert approved_sample.status == QualitySample.Status.APPROVED
    with pytest.raises(ValidationError) as error:
        approved_sample.cancel('Tentativa')
    assert 'status' in error.value.message_dict

    open_sample = QualitySample.objects.create(
        sample_type=QualitySample.SampleType.PRODUCTION,
        product=product,
        stock_lot=lot,
        quantity=1,
        unit=unit,
    )
    open_sample.cancel('Amostra inválida.')
    assert open_sample.status == QualitySample.Status.CANCELLED
    with pytest.raises(ValidationError):
        open_sample.cancel('De novo')


def test_analysis_reject_blocked_from_approved_and_ok_otherwise():
    from quality.models import QualityAnalysis

    unit, product, lot = create_qa_item('ANR')
    document = create_quality_document(product, lot, unit, suffix='ANR')
    approved = document.sample.analyses.get()
    assert approved.status == QualityAnalysis.Status.APPROVED
    with pytest.raises(ValidationError) as error:
        approved.reject('Tarde demais', user=make_user('rej1'))
    assert 'status' in error.value.message_dict

    pending = QualityAnalysis.objects.create(sample=document.sample)
    pending.reject('Falha de sistema', user=make_user('rej2'))
    assert pending.status == QualityAnalysis.Status.REJECTED


def test_specification_approve_and_obsolete_guards():
    from quality.models import AnalyticalSpecification

    unit, product, lot = create_qa_item('SPC')
    document = create_quality_document(product, lot, unit, suffix='SPC')
    spec = document.sample.specification
    assert spec.status == AnalyticalSpecification.Status.DRAFT
    with pytest.raises(ValidationError):
        spec.obsolete()
    spec.approve(user=make_user('spc1'))
    spec.obsolete()
    assert spec.status == AnalyticalSpecification.Status.OBSOLETE
    with pytest.raises(ValidationError):
        spec.approve(user=make_user('spc2'))
    with pytest.raises(ValidationError):
        spec.obsolete()


def test_investigation_conclude_only_from_open_states():
    from quality.models import LaboratoryInvestigation

    unit, product, lot = create_qa_item('INC')
    document = create_quality_document(product, lot, unit, suffix='INC')
    investigation = LaboratoryInvestigation.objects.create(
        sample=document.sample,
        investigation_type=LaboratoryInvestigation.InvestigationType.RETEST,
        justification='Reteste.',
    )
    investigation.conclude('Causa', 'Conclusão', user=make_user('inc1'))
    assert investigation.status == LaboratoryInvestigation.Status.CONCLUDED
    with pytest.raises(ValidationError) as error:
        investigation.conclude('Outra', 'Outra', user=make_user('inc2'))
    assert 'status' in error.value.message_dict


# --- Fix 4: segregation of duties ---------------------------------------------


def test_qa_review_cannot_be_approved_by_submitter():
    from qa.models import QAReview

    _unit, _product, lot = create_qa_item('SOD1')
    review = QAReview.objects.create(
        review_type=QAReview.ReviewType.LOT_RELEASE, title='Revisão', stock_lot=lot
    )
    author, approver = make_user('sod-a'), make_user('sod-b')
    review.submit(user=author)
    with pytest.raises(ValidationError) as error:
        review.approve(user=author)
    assert 'approved_by' in error.value.message_dict
    review.approve(user=approver)
    assert review.status == QAReview.Status.APPROVED


def test_analysis_review_and_approve_reject_the_analyst():
    from quality.models import QualityAnalysis

    unit, product, lot = create_qa_item('SOD2')
    document = create_quality_document(product, lot, unit, suffix='SOD2')
    analysis = QualityAnalysis.objects.create(sample=document.sample)
    analyst, reviewer = make_user('sod-c'), make_user('sod-d')
    analysis.start(user=analyst)
    analysis.complete()
    with pytest.raises(ValidationError) as error:
        analysis.review(user=analyst)
    assert 'reviewer' in error.value.message_dict
    analysis.review(user=reviewer)
    with pytest.raises(ValidationError) as error:
        analysis.approve(user=analyst)
    assert 'approver' in error.value.message_dict
    analysis.approve(user=reviewer)
    assert analysis.status == QualityAnalysis.Status.APPROVED


def test_block_cannot_be_unblocked_by_its_author():
    _unit, _product, lot = create_qa_item('SOD3')
    author = make_user('sod-e')
    block = make_block(lot=lot, user=author)
    with pytest.raises(ValidationError) as error:
        block.unblock('Eu mesmo.', user=author)
    assert 'unblocked_by' in error.value.message_dict
    block.refresh_from_db()
    assert block.status == type(block).Status.ACTIVE
