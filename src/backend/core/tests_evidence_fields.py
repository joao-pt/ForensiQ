"""
ForensiQ — Testes da configuração de campos por tipo de evidência (#59).

A config passou a viver na BD (``EvidenceFieldDef`` + ``FieldOption``, semeada
pela migração ``0027_seed_evidence_fields``), editável no admin. ``core.evidence_field_config``
é a API de leitura; ``Evidence._validate_type_specific_data`` deriva dela. Por
isso os testes de forma passaram a ``TestCase`` (precisam da BD semeada).
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from core import evidence_field_config
from core.models import Evidence


class EvidenceFieldConfigShapeTest(TestCase):
    """A config (agora na BD) tem a forma esperada."""

    def test_transversais(self):
        keys = {f['key'] for f in evidence_field_config.transversal_fields()}
        self.assertEqual(keys, {'marca', 'modelo', 'estado_energia'})

    def test_estado_energia_e_select_com_estados_volateis(self):
        campo = next(
            f for f in evidence_field_config.transversal_fields() if f['key'] == 'estado_energia'
        )
        self.assertEqual(campo['input'], 'select')
        for estado in ('Ligado', 'Desligado', 'Modo de avião'):
            self.assertIn(estado, campo['options'])
        # tem de estar em all_keys() para a view o recolher do POST
        self.assertIn('estado_energia', evidence_field_config.all_keys())

    def test_all_keys_inclui_transversais_e_identificadores(self):
        keys = evidence_field_config.all_keys()
        for k in ('marca', 'modelo', 'imei', 'imsi', 'iccid', 'vin', 'mac'):
            self.assertIn(k, keys)

    def test_sensitive_keys_marcados(self):
        self.assertIn('passcode', evidence_field_config.sensitive_keys())
        self.assertIn('pin_code', evidence_field_config.sensitive_keys())

    def test_fields_for_tipo_desconhecido_vazio(self):
        self.assertEqual(evidence_field_config.fields_for('TIPO_INEXISTENTE'), [])

    def test_type_fields_flat_marca_o_tipo(self):
        # Cada campo por-tipo vem marcado com 'type' (o JS mostra/esconde por tipo).
        flat = evidence_field_config.type_fields_flat()
        imei = next(f for f in flat if f['key'] == 'imei' and f['type'] == 'MOBILE_DEVICE')
        self.assertEqual(imei['validator'], 'imei')


class EvidenceTypeValidationTest(TestCase):
    """A validação por tipo corre a partir da config (BD)."""

    def _ev(self, etype, tsd):
        return Evidence(type=etype, type_specific_data=tsd)

    def test_marca_modelo_passam_sem_validador(self):
        ev = self._ev(Evidence.EvidenceType.MOBILE_DEVICE, {'marca': 'Apple', 'modelo': 'iPhone 14'})
        ev._validate_type_specific_data()  # não deve levantar

    def test_imei_invalido_rejeitado(self):
        ev = self._ev(Evidence.EvidenceType.MOBILE_DEVICE, {'imei': '123'})
        with self.assertRaises(ValidationError):
            ev._validate_type_specific_data()

    def test_iot_mac_passa_a_ser_validado(self):
        # Cobertura nova face ao hardcoded antigo (só NETWORK_DEVICE validava MAC).
        ev = self._ev(Evidence.EvidenceType.IOT_DEVICE, {'mac': 'isto-nao-e-mac'})
        with self.assertRaises(ValidationError):
            ev._validate_type_specific_data()

    def test_vin_invalido_rejeitado(self):
        ev = self._ev(Evidence.EvidenceType.VEHICLE, {'vin': 'curto'})
        with self.assertRaises(ValidationError):
            ev._validate_type_specific_data()

    def test_estado_energia_aceite_em_qualquer_tipo(self):
        # Transversal, sem validador de formato — deve passar mesmo num tipo
        # sem campos específicos (não é "não aplicável" que bloqueia o registo).
        ev = self._ev(Evidence.EvidenceType.DIGITAL_FILE, {'estado_energia': 'Desligado'})
        ev._validate_type_specific_data()  # não deve levantar
