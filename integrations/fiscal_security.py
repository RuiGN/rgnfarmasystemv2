"""Deployment-owned fiscal destinations and per-destination credential references."""

import ipaddress
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError


def validate_fiscal_destination(base_url, secret_reference=None):
    try:
        parsed = urlsplit(base_url)
        invalid = (
            parsed.scheme != 'https'
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in base_url)
            or '\\' in base_url
            or '%' in parsed.netloc
        )
        try:
            address = ipaddress.ip_address(parsed.hostname or '')
        except ValueError:
            address = None
        if address is not None and (not address.is_global or address.is_multicast):
            invalid = True
    except ValueError, TypeError:
        invalid = True
    if invalid:
        raise ValidationError(
            {
                'base_url': 'Destino fiscal deve ser HTTPS público, sem credenciais, query ou fragmento (porta 443).'
            }
        )
    destinations = getattr(settings, 'FISCAL_PROVIDER_ALLOWED_DESTINATIONS', {})
    destination = base_url.rstrip('/')
    if not isinstance(destinations, dict) or destination not in destinations:
        raise ValidationError(
            {'base_url': 'Destino fiscal não autorizado pela configuração do deployment.'}
        )
    references = destinations[destination]
    if not isinstance(references, (list, tuple)) or any(
        not isinstance(ref, str) for ref in references
    ):
        # This is a validation message; the field stores an environment name, not a token.
        message = 'Allowlist fiscal inválida.'
        raise ValidationError({'secret_reference': message})
    if secret_reference and (
        re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', secret_reference) is None
        or secret_reference not in references
    ):
        message = 'Referência de segredo não autorizada para este destino fiscal.'
        raise ValidationError({'secret_reference': message})
    return destination
