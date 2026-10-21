"""Central retention policy for regulated GxP records."""

GXP_RETENTION_APP_LABELS = frozenset(
    {
        'audits',
        'capa',
        'changes',
        'deviations',
        'documents',
        'files',
        'production',
        'qa',
        'quality',
        'recalls',
        'risks',
        'training',
    }
)


GXP_RETENTION_MODEL_LABELS = frozenset({'inventory.stockbalance'})


def requires_gxp_retention(model) -> bool:
    """Return whether generic physical deletion is forbidden for this model."""

    return (
        model._meta.app_label in GXP_RETENTION_APP_LABELS
        or model._meta.label_lower in GXP_RETENTION_MODEL_LABELS
    )
