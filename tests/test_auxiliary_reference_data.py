from io import StringIO
from unittest.mock import Mock, patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase

from auxiliary.models import City, Country, Currency, StateProvince
from auxiliary.reference_snapshots import OfficialReferenceSnapshot
from reference_data.manifest import build_manifest


COUNTRIES = [
    {
        'id': {'M49': 76, 'ISO-ALPHA-2': 'BR', 'ISO-ALPHA-3': 'BRA'},
        'nome': 'Brasil',
    }
]

STATES = [
    {
        'id': 26,
        'sigla': 'PE',
        'nome': 'Pernambuco',
        'regiao': {'id': 2, 'sigla': 'NE', 'nome': 'Nordeste'},
    }
]

CITIES = [
    {
        'id': 2611606,
        'nome': 'Recife',
        'regiao-imediata': {'regiao-intermediaria': {'UF': {'id': 26, 'sigla': 'PE'}}},
    },
    {
        'id': 2609600,
        'nome': 'Olinda',
        'microrregiao': {'mesorregiao': {'UF': {'id': 26, 'sigla': 'PE'}}},
    },
]

CURRENCIES_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ISO_4217 Pblshd="2026-01-01">
  <CcyTbl>
    <CcyNtry>
      <CtryNm>BRAZIL</CtryNm><CcyNm>Brazilian Real</CcyNm>
      <Ccy>BRL</Ccy><CcyNbr>986</CcyNbr><CcyMnrUnts>2</CcyMnrUnts>
    </CcyNtry>
    <CcyNtry>
      <CtryNm>UNITED STATES OF AMERICA</CtryNm><CcyNm>US Dollar</CcyNm>
      <Ccy>USD</Ccy><CcyNbr>840</CcyNbr><CcyMnrUnts>2</CcyMnrUnts>
    </CcyNtry>
    <CcyNtry>
      <CtryNm>PUERTO RICO</CtryNm><CcyNm>US Dollar</CcyNm>
      <Ccy>USD</Ccy><CcyNbr>840</CcyNbr><CcyMnrUnts>2</CcyMnrUnts>
    </CcyNtry>
  </CcyTbl>
</ISO_4217>
"""


class OfficialReferenceDataCommandTests(TestCase):
    def run_command(self, *, cities=CITIES):
        def city_state_abbreviation(item):
            immediate = item.get('regiao-imediata') or {}
            intermediate = immediate.get('regiao-intermediaria') or {}
            state = intermediate.get('UF') or {}
            if state.get('sigla'):
                return state['sigla']
            microregion = item.get('microrregiao') or {}
            mesoregion = microregion.get('mesorregiao') or {}
            return (mesoregion.get('UF') or {}).get('sigla', '')

        payload = {
            'countries': [
                {
                    'name': 'Brasil',
                    'iso_alpha2': 'BR',
                    'iso_alpha3': 'BRA',
                    'numeric_code': '076',
                }
            ],
            'states': [
                {
                    'name': 'Pernambuco',
                    'abbreviation': 'PE',
                    'ibge_code': '26',
                    'country_iso_alpha2': 'BR',
                }
            ],
            'cities': [
                {
                    'name': city['nome'],
                    'ibge_code': str(city['id']),
                    'state_ibge_code': (
                        str(
                            (city.get('regiao-imediata') or {})
                            .get('regiao-intermediaria', {})
                            .get('UF', {})
                            .get('id')
                            or ''
                        )
                        or str(
                            (city.get('microrregiao') or {})
                            .get('mesorregiao', {})
                            .get('UF', {})
                            .get('id')
                            or ''
                        )
                        or ({'PE': '26'}.get(city_state_abbreviation(city), ''))
                    ),
                }
                for city in cities
            ],
            'currencies': [
                {
                    'code': 'BRL',
                    'name': 'Real brasileiro',
                    'numeric_code': '986',
                    'decimal_places': 2,
                    'minor_unit_applicable': True,
                    'symbol': 'R$',
                    'description': (
                        'Nome oficial SIX: Brazilian Real. Entidades usuárias: BRAZIL. '
                        'Fonte: ISO 4217/SIX (lista vigente em 2026-01-01).'
                    ),
                },
                {
                    'code': 'USD',
                    'name': 'Dólar americano',
                    'numeric_code': '840',
                    'decimal_places': 2,
                    'minor_unit_applicable': True,
                    'symbol': 'US$',
                    'description': (
                        'Nome oficial SIX: US Dollar. '
                        'Entidades usuárias: PUERTO RICO; UNITED STATES OF AMERICA. '
                        'Fonte: ISO 4217/SIX (lista vigente em 2026-01-01).'
                    ),
                },
            ],
        }
        manifest = build_manifest(
            identifier='official-references-br',
            version='test',
            source_date='2026-08-31',
            source_urls=('https://example.test',),
            namespaces=('ISO-3166', 'IBGE-LOCALIDADES', 'ISO-4217'),
            provenance=('Fonte oficial de referência.',),
            license_name='Dados oficiais de acesso público',
            license_url='https://example.test/license',
            payload=payload,
        )
        stdout = StringIO()
        with (
            patch(
                'auxiliary.management.commands.load_official_reference_data.load_official_snapshot',
                return_value=OfficialReferenceSnapshot(manifest=manifest, payload=payload),
            ),
            patch.object(requests, 'get', Mock(side_effect=AssertionError('rede proibida'))),
        ):
            call_command('load_official_reference_data', stdout=stdout)
        return stdout.getvalue()

    def test_loads_official_catalogs_and_is_idempotent(self):
        output = self.run_command()

        brazil = Country.objects.get(name='Brasil')
        pernambuco = StateProvince.objects.get(name='Pernambuco')
        recife = City.objects.get(name='Recife')
        brl = Currency.objects.get(code='BRL')

        assert brazil.name == 'Brasil'
        assert brazil.iso_alpha2 == 'BR'
        assert brazil.iso_alpha3 == 'BRA'
        assert brazil.numeric_code == '076'
        assert pernambuco.abbreviation == 'PE'
        assert pernambuco.ibge_code == '26'
        assert recife.ibge_code == '2611606'

        assert recife.state == pernambuco
        assert brl.name == 'Real brasileiro'
        assert brl.numeric_code == '986'
        assert brl.minor_unit_applicable is True
        assert brl.symbol == 'R$'
        assert Currency.objects.get(code='USD').name == 'Dólar americano'
        assert Currency.objects.get(code='USD').description == (
            'Nome oficial SIX: US Dollar. '
            'Entidades usuárias: PUERTO RICO; UNITED STATES OF AMERICA. '
            'Fonte: ISO 4217/SIX (lista vigente em 2026-01-01).'
        )
        assert 'countries=1, states=1, cities=2, currencies=2' in output

        self.run_command()

        assert Country.objects.count() == 1
        assert StateProvince.objects.count() == 1
        assert City.objects.count() == 2
        assert Currency.objects.count() == 2

    def test_reuses_existing_normalized_location_records(self):
        brazil = Country.objects.create(name='Brasil')
        pernambuco = StateProvince.objects.create(name='Pernambuco', country=brazil)
        existing_city = City.objects.create(name='Recife', state=pernambuco)

        self.run_command()

        existing_city.refresh_from_db()
        pernambuco.refresh_from_db()

        assert City.objects.get(name='Recife').pk == existing_city.pk
        assert City.objects.filter(name='Recife').count() == 1
        brazil.refresh_from_db()
        pernambuco.refresh_from_db()

        assert brazil.name == 'Brasil'
        assert brazil.iso_alpha2 == 'BR'
        assert brazil.iso_alpha3 == 'BRA'
        assert brazil.numeric_code == '076'
        assert pernambuco.name == 'Pernambuco'
        assert pernambuco.country == brazil
        assert pernambuco.abbreviation == 'PE'
        assert pernambuco.ibge_code == '26'
        assert existing_city.ibge_code == '2611606'

    def test_leaves_nonmatching_legacy_locations_intact(self):
        legacy_state = StateProvince.objects.create(name='Pernambuco')
        legacy_city = City.objects.create(name='Recife', state=legacy_state)

        self.run_command()

        legacy_state.refresh_from_db()
        legacy_city.refresh_from_db()

        assert legacy_state.country is None
        assert legacy_state.abbreviation == ''
        assert legacy_state.ibge_code == ''
        assert legacy_city.state == legacy_state
        assert legacy_city.ibge_code == ''
        assert StateProvince.objects.count() == 2
        assert City.objects.count() == 3

    def test_rejects_divergent_country_code_without_overwriting_or_partial_writes(self):
        brazil = Country.objects.create(name='Brasil', iso_alpha2='XX')

        with pytest.raises(
            CommandError, match='Código oficial divergente no fallback legado de país Brasil'
        ):
            self.run_command()

        brazil.refresh_from_db()
        assert brazil.iso_alpha2 == 'XX'
        assert StateProvince.objects.count() == 0
        assert City.objects.count() == 0
        assert Currency.objects.count() == 0

    def test_rejects_divergent_state_code_without_overwriting_or_partial_writes(self):
        brazil = Country.objects.create(
            name='Brasil', iso_alpha2='BR', iso_alpha3='BRA', numeric_code='076'
        )
        pernambuco = StateProvince.objects.create(
            name='Pernambuco', country=brazil, abbreviation='PE', ibge_code='99'
        )

        with pytest.raises(CommandError, match='Código oficial divergente para UF PE'):
            self.run_command()

        pernambuco.refresh_from_db()
        assert pernambuco.ibge_code == '99'
        assert City.objects.count() == 0
        assert Currency.objects.count() == 0

    def test_rejects_divergent_city_code_without_overwriting_or_partial_writes(self):
        brazil = Country.objects.create(
            name='Brasil', iso_alpha2='BR', iso_alpha3='BRA', numeric_code='076'
        )
        pernambuco = StateProvince.objects.create(
            name='Pernambuco', country=brazil, abbreviation='PE', ibge_code='26'
        )
        recife = City.objects.create(name='Recife', state=pernambuco, ibge_code='9999999')

        with pytest.raises(
            CommandError, match='Código oficial divergente no fallback legado de município 2611606'
        ):
            self.run_command()

        recife.refresh_from_db()
        assert recife.ibge_code == '9999999'
        assert Currency.objects.count() == 0

    def test_rejects_ambiguous_legacy_state_match_without_partial_writes(self):
        brazil = Country.objects.create(
            name='Brasil', iso_alpha2='BR', iso_alpha3='BRA', numeric_code='076'
        )
        StateProvince.objects.create(name='Pernambuco', country=brazil)
        StateProvince.objects.create(name='Pernambuco', country=brazil)

        with pytest.raises(CommandError, match='Mais de um cadastro local corresponde a UF PE'):
            self.run_command()

        assert City.objects.count() == 0
        assert Currency.objects.count() == 0

    def test_runs_complete_location_validation_before_persisting(self):
        original_country_clean = Country.full_clean
        original_state_clean = StateProvince.full_clean
        original_city_clean = City.full_clean
        original_currency_clean = Currency.full_clean

        def full_clean(instance, *args, **kwargs):
            assert not args
            assert not kwargs
            return originals[type(instance)](instance, *args, **kwargs)

        originals = {
            Country: original_country_clean,
            StateProvince: original_state_clean,
            City: original_city_clean,
            Currency: original_currency_clean,
        }
        with (
            patch.object(Country, 'full_clean', autospec=True, side_effect=full_clean),
            patch.object(StateProvince, 'full_clean', autospec=True, side_effect=full_clean),
            patch.object(City, 'full_clean', autospec=True, side_effect=full_clean),
            patch.object(Currency, 'full_clean', autospec=True, side_effect=full_clean),
        ):
            self.run_command()

    def test_rejects_city_with_unknown_state_without_partial_writes(self):
        invalid_cities = [
            {
                'id': 9999999,
                'nome': 'Município inválido',
                'regiao-imediata': {'regiao-intermediaria': {'UF': {'id': 99, 'sigla': 'XX'}}},
            }
        ]

        with pytest.raises(CommandError, match='UF 99 não encontrada'):
            self.run_command(cities=invalid_cities)

        assert Country.objects.count() == 0
        assert StateProvince.objects.count() == 0
        assert City.objects.count() == 0
        assert Currency.objects.count() == 0


@pytest.mark.django_db
def test_official_location_codes_are_unique_when_present():
    Country.objects.create(name='Brasil', iso_alpha2='BR', iso_alpha3='BRA', numeric_code='076')

    with pytest.raises(IntegrityError):
        Country.objects.create(name='Brasil duplicado', iso_alpha2='BR')
