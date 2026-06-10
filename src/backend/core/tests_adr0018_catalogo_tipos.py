"""
ForensiQ — ADR-0018: prova de que mover o catálogo de tipos (enum → tabela
de referência editável) NÃO afeta a imutabilidade nem o hash dos registos
selados.

Estes testes são o ARTEFACTO DE DEFESA do ADR-0018. Demonstram, por
construção e com o código ATUAL (sem depender da tabela ``EvidenceTypeRef``
ainda por implementar), que o hash de integridade de uma evidência depende
apenas do *slug* gravado na própria linha imutável (ex.: ``"MOBILE_DEVICE"``)
e nunca do rótulo legível (``"Telemóvel / Smartphone / Tablet"``) que um
catálogo editável mostraria. Daqui decorre que:

  - editar o rótulo no catálogo é, por construção, incapaz de alterar o hash
    de qualquer registo já selado — o rótulo nem sequer é *input* do hash;
  - migrar o catálogo de enum-em-código para tabela-em-BD produz hashes
    byte-idênticos, desde que o *slug* (a string gravada) se mantenha;
  - o *slug*, uma vez selado num registo, fica congelado (a linha é imutável).

Ponto de prova no código de produção: ``Evidence.compute_integrity_hash``
serializa ``self.type`` cru em ``core/models.py:1230`` — o membro de
``TextChoices`` interpola para o slug, exatamente como uma string lida da BD.
"""

from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from core.models import Evidence
from core.tests_factories import VALID_IMEI, EvidenceMobileFactory

# Instante fixo: o hash inclui ``timestamp_seizure.isoformat()``; fixá-lo
# garante que duas instâncias só diferem no campo que queremos isolar.
_FIXED_DT = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)


def _evidence_in_memory(type_value):
    """Evidência em memória (não gravada), com campos fixos; só varia ``type``.

    ``compute_integrity_hash`` é função pura dos atributos da instância (sem
    fotografia → ``_compute_photo_hash`` devolve ''), pelo que não toca na BD.
    """
    return Evidence(
        occurrence_id=1,
        agent_id=1,
        type=type_value,
        parent_evidence=None,
        description='Telemóvel apreendido na busca',
        gps_lat=None,
        gps_lng=None,
        timestamp_seizure=_FIXED_DT,
        serial_number='SN-0001',
        type_specific_data={'imei': VALID_IMEI},
    )


class CatalogoTiposHashInvarianteTests(SimpleTestCase):
    """O hash compromete-se com o SLUG, não com o rótulo nem com a origem."""

    def test_membro_de_enum_e_string_da_bd_dao_hash_identico(self):
        """O cerne do ADR-0018.

        Hoje ``type`` vem de um membro ``TextChoices``; depois de enum→BD viria
        de uma string validada contra a tabela de referência. Para o hash são
        indistintos — logo a migração é byte-segura desde que o slug se mantenha.
        """
        h_enum = _evidence_in_memory(
            Evidence.EvidenceType.MOBILE_DEVICE
        ).compute_integrity_hash()
        h_str = _evidence_in_memory('MOBILE_DEVICE').compute_integrity_hash()
        self.assertEqual(h_enum, h_str)

    def test_o_token_hashado_e_o_slug_nao_o_rotulo(self):
        """O que entra no hash é o slug; o rótulo (o que o catálogo editaria) não."""
        member = Evidence.EvidenceType.MOBILE_DEVICE
        # A f-string (igual à de compute_integrity_hash) interpola o membro
        # para o slug cru — é exatamente o que entra no hash.
        self.assertEqual(f'{member}', 'MOBILE_DEVICE')
        # O rótulo legível é OUTRA coisa, e é o que um catálogo editável mudaria.
        self.assertEqual(member.label, 'Telemóvel / Smartphone / Tablet')
        self.assertNotEqual(f'{member}', member.label)

    def test_slug_diferente_muda_o_hash(self):
        """Prova complementar: o hash É sensível ao slug (não é constante)."""
        h_mobile = _evidence_in_memory('MOBILE_DEVICE').compute_integrity_hash()
        h_computer = _evidence_in_memory('COMPUTER').compute_integrity_hash()
        self.assertNotEqual(h_mobile, h_computer)


class RegistoSeladoCongeladoTests(SimpleTestCase):
    """O slug, uma vez selado num registo, não pode ser reescrito."""

    def test_alterar_tipo_de_registo_existente_e_recusado(self):
        ev = _evidence_in_memory('MOBILE_DEVICE')
        ev.pk = 1  # simula um registo já gravado/selado
        ev.type = 'COMPUTER'
        with self.assertRaises(ValidationError):
            ev.save()


class ReverificacaoPersistidaTests(TestCase):
    """Contra PostgreSQL real (triggers de imutabilidade ativos)."""

    def test_hash_persistido_reverifica(self):
        """Cria → sela → relê → recomputa: o hash gravado re-verifica."""
        ev = EvidenceMobileFactory()
        ev.refresh_from_db()
        self.assertEqual(ev.compute_integrity_hash(), ev.integrity_hash)
