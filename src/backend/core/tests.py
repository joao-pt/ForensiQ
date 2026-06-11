"""
ForensiQ — Testes unitários para os modelos core.

Testa:
- Criação de utilizadores (AGENT e EXPERT)
- Criação de ocorrências e evidências
- Hash SHA-256 automático em evidências
- Ledger de eventos da cadeia de custódia (guardas mínimas + estado derivado)
- Imutabilidade da cadeia de custódia (append-only)

Nota de taxonomia (ver ADR-0010): os tipos de Evidence passaram de 5
genéricos para 18 digital-first. Tradução dos usos históricos:
DIGITAL_DEVICE → MOBILE_DEVICE / COMPUTER (dispositivos autónomos)
DOCUMENT       → OTHER_DIGITAL (fallback — papel deixou de existir)
PHOTO          → DIGITAL_FILE  (captura / fotografia digital)
"""

import hashlib
import unittest
from datetime import UTC, timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection
from django.test import TestCase
from django.utils import timezone

from core.tests_factories import LISBOA_GPS, RECEIVER_KWARGS, CrimeTipoFactory

from .models import (
    VALIDATION_DEADLINE,
    ChainOfCustody,
    CustodianType,
    EventType,
    Evidence,
    Occurrence,
    User,
    derive_legal_state,
    validation_status,
)


class UserModelTest(TestCase):
    """Testes para o modelo User personalizado."""

    def test_create_agent(self):
        user = User.objects.create_user(
            username='agente01',
            password='test12345',
            profile=User.Profile.FIRST_RESPONDER,
            badge_number='AGT-1234',
        )
        self.assertTrue(user.is_agent)
        self.assertFalse(user.is_expert)
        self.assertEqual(user.badge_number, 'AGT-1234')

    def test_create_expert(self):
        user = User.objects.create_user(
            username='perito01',
            password='test12345',
            profile=User.Profile.FORENSIC_EXPERT,
            clearance=User.Clearance.NACIONAL,
        )
        self.assertFalse(user.is_agent)
        self.assertTrue(user.is_expert)


class OccurrenceModelTest(TestCase):
    """Testes para o modelo Occurrence."""

    def setUp(self):
        self.agent = User.objects.create_user(
            username='agente01',
            password='test12345',
        )

    def test_create_occurrence(self):
        # Campo gps_* tem max_digits=10, decimal_places=7 — o total de
        # dígitos inteiros é 3 (90 ou -180) e fraccionários até 7.
        # "38.7223340" tem 9 dígitos = 2 inteiros + 7 decimais → ok.
        # "-9.1393366" tem 8 dígitos = 1 inteiro + 7 decimais → ok.
        occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-001',
            description='Furto de telemóvel na via pública.',
            agent=self.agent,
            gps_lat=LISBOA_GPS[0],
            gps_lng=LISBOA_GPS[1],
        )
        # __str__ combina NUIPC + código interno gerado (OCC-YYYY-NNNNN).
        self.assertTrue(str(occ).startswith('Ocorrência NUIPC-2026-001'))
        self.assertIn('OC-', str(occ))
        self.assertIsNotNone(occ.created_at)


class EvidenceModelTest(TestCase):
    """Testes para o modelo Evidence (inclui hash SHA-256)."""

    def setUp(self):
        self.agent = User.objects.create_user(
            username='agente01',
            password='test12345',
        )
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-001',
            description='Furto de telemóvel.',
            agent=self.agent,
        )

    def test_create_evidence_with_auto_hash(self):
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='iPhone 15 Pro encontrado no local.',
            agent=self.agent,
        )
        # Hash SHA-256 deve ser calculado automaticamente
        self.assertEqual(len(ev.integrity_hash), 64)
        self.assertNotEqual(ev.integrity_hash, '')

    def test_hash_is_deterministic(self):
        """O mesmo conjunto de metadados gera sempre o mesmo hash."""
        ts = timezone.now()
        ev = Evidence(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.OTHER_DIGITAL,
            description='Ficheiro recuperado.',
            timestamp_seizure=ts,
            agent=self.agent,
        )
        hash1 = ev.compute_integrity_hash()
        hash2 = ev.compute_integrity_hash()
        self.assertEqual(hash1, hash2)

    def test_update_blocked(self):
        """Atualizar uma evidência existente deve levantar ValidationError."""
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Smartphone original.',
            agent=self.agent,
        )
        ev.description = 'Tentativa de alteração.'
        with self.assertRaises(ValidationError):
            ev.save()

    def test_delete_blocked(self):
        """Eliminar uma evidência deve levantar ValidationError."""
        ev = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Smartphone.',
            agent=self.agent,
        )
        with self.assertRaises(ValidationError):
            ev.delete()


class ChainOfCustodyModelTest(TestCase):
    """Testes do ledger de eventos (guardas mínimas + imutabilidade), ADR-0015."""

    def setUp(self):
        self.agent = User.objects.create_user(
            username='agente01',
            password='test12345',
        )
        self.expert = User.objects.create_user(
            username='perito01',
            password='test12345',
            profile=User.Profile.FORENSIC_EXPERT,
            clearance=User.Clearance.NACIONAL,
        )
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-003',
            description='Apreensão.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Smartphone Samsung.',
            agent=self.agent,
        )

    def _evento(self, event_type, **kwargs):
        kwargs.setdefault('agent', self.agent)
        record = ChainOfCustody(evidence=self.evidence, event_type=event_type, **kwargs)
        record.save()
        return record

    # --- Primeiro evento de uma evidência ---

    def test_primeiro_evento_apreensao_passa(self):
        record = self._evento(EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self.assertEqual(len(record.record_hash), 64)
        self.assertEqual(record.sequence, 1)

    def test_primeiro_evento_diferente_de_apreensao_falha(self):
        with self.assertRaises(ValidationError):
            self._evento(EventType.VALIDACAO_APREENSAO)

    def test_apreensao_so_pode_ser_primeiro(self):
        self._evento(EventType.APREENSAO_OBJETO)
        with self.assertRaises(ValidationError):
            self._evento(EventType.APREENSAO_OBJETO)

    # --- Guarda da validação ---

    def test_validacao_requer_apreensao_previa(self):
        # Primeiro evento tem de ser APREENSAO_OBJETO; aqui forçamos uma evidência
        # nova cujo 1.º evento seria VALIDACAO_APREENSAO — bloqueado pela guarda do 1.º.
        with self.assertRaises(ValidationError):
            self._evento(EventType.VALIDACAO_APREENSAO)

    def test_validacao_so_uma_vez(self):
        self._evento(EventType.APREENSAO_OBJETO)
        self._evento(EventType.VALIDACAO_APREENSAO)
        with self.assertRaises(ValidationError):
            self._evento(EventType.VALIDACAO_APREENSAO)

    def test_validacao_fora_de_prazo_aceite_mas_assinalada(self):
        """VALIDACAO_APREENSAO >72h após apreensão é aceite, mas validation_overdue=True."""
        # A apreensão tem de ficar >72h no passado. O ledger é imutável (o
        # trigger PostgreSQL bloqueia qualquer UPDATE), por isso não se retrodata
        # com .update(); congela-se o relógio do servidor só durante a criação
        # da apreensão — o save() força timestamp = timezone.now().
        backdated = timezone.now() - timedelta(hours=80)
        with mock.patch('core.models.timezone.now', return_value=backdated):
            self._evento(EventType.APREENSAO_OBJETO)
        record = self._evento(EventType.VALIDACAO_APREENSAO)
        self.assertTrue(record.validation_overdue)

    def test_validacao_dentro_do_prazo_nao_assinalada(self):
        self._evento(EventType.APREENSAO_OBJETO)
        record = self._evento(EventType.VALIDACAO_APREENSAO)
        self.assertFalse(record.validation_overdue)

    # --- Guarda da perícia ---

    def test_inicio_pericia_sem_despacho_falha(self):
        self._evento(EventType.APREENSAO_OBJETO)
        with self.assertRaises(ValidationError):
            self._evento(EventType.INICIO_PERICIA)

    def test_inicio_pericia_com_despacho_passa(self):
        self._evento(EventType.APREENSAO_OBJETO)
        self._evento(EventType.VALIDACAO_APREENSAO)   # o despacho exige-a (178.º/5-6)
        self._evento(EventType.DESPACHO_PERICIA)
        record = self._evento(EventType.INICIO_PERICIA)
        self.assertEqual(record.event_type, EventType.INICIO_PERICIA)

    def test_despacho_sem_validacao_falha(self):
        """DESPACHO_PERICIA com apreensão por validar é recusado (CPP 178.º/5-6
        — a validação implícita da jurisprudência fica explícita no ledger)."""
        self._evento(EventType.APREENSAO_OBJETO)
        with self.assertRaises(ValidationError):
            self._evento(EventType.DESPACHO_PERICIA)

    # --- Terminais fecham o ledger ---

    def test_terminal_restituicao_fecha(self):
        self._evento(EventType.APREENSAO_OBJETO)
        self._evento(
            EventType.RESTITUICAO,
            custodian_type=CustodianType.PROPRIETARIO,
            **RECEIVER_KWARGS,
        )
        with self.assertRaises(ValidationError):
            self._evento(EventType.TRANSFERENCIA_CUSTODIA)

    def test_terminal_destruicao_fecha(self):
        self._evento(EventType.APREENSAO_OBJETO)
        self._evento(EventType.DESTRUICAO)
        with self.assertRaises(ValidationError):
            self._evento(EventType.TRANSFERENCIA_CUSTODIA)

    # --- Ordem livre e repetível ---

    def test_ordem_livre_transferencias_e_pericias_repetidas(self):
        self._evento(EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self._evento(EventType.VALIDACAO_APREENSAO, custodian_type=CustodianType.OPC)
        self._evento(EventType.DESPACHO_PERICIA, custodian_type=CustodianType.OPC)
        self._evento(EventType.TRANSFERENCIA_CUSTODIA, custodian_type=CustodianType.LAB_PUBLICO)
        self._evento(EventType.INICIO_PERICIA, custodian_type=CustodianType.LAB_PUBLICO)
        self._evento(EventType.CONCLUSAO_PERICIA, custodian_type=CustodianType.LAB_PUBLICO)
        # Nova perícia noutro laboratório (Art. 158.º) — encaminhamento de volta.
        self._evento(EventType.TRANSFERENCIA_CUSTODIA, custodian_type=CustodianType.OPC)
        self._evento(EventType.TRANSFERENCIA_CUSTODIA, custodian_type=CustodianType.LAB_PRIVADO)
        self._evento(EventType.INICIO_PERICIA, custodian_type=CustodianType.LAB_PRIVADO)
        self.assertEqual(self.evidence.custody_chain.count(), 9)

    # --- Imutabilidade (append-only) ---

    def test_update_blocked(self):
        """Atualizar um registo existente deve levantar ValidationError."""
        record = self._evento(EventType.APREENSAO_OBJETO)
        record.observations = 'Tentativa de alteração.'
        with self.assertRaises(ValidationError):
            record.save()

    def test_delete_blocked(self):
        """Eliminar um registo deve levantar ValidationError."""
        record = self._evento(EventType.APREENSAO_OBJETO)
        with self.assertRaises(ValidationError):
            record.delete()

    def test_hash_chain_integrity(self):
        """Hashes encadeiam-se (blockchain-like) e recomputam-se."""
        r1 = self._evento(EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        r2 = self._evento(EventType.VALIDACAO_APREENSAO, custodian_type=CustodianType.OPC)

        self.assertNotEqual(r1.record_hash, r2.record_hash)
        self.assertEqual(len(r1.record_hash), 64)
        self.assertEqual(len(r2.record_hash), 64)
        # r2 encadeia com r1: recomputar com previous_hash=r1.record_hash bate certo.
        self.assertEqual(
            r2.compute_record_hash(previous_hash=r1.record_hash),
            r2.record_hash,
        )


class DeriveLegalStateTest(TestCase):
    """Estado legal derivado (ADR-0015 §6) — função pura sobre a sequência."""

    def setUp(self):
        self.agent = User.objects.create_user(username='ag_dls', password='x12345678')
        self.occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-DLS-001',
            description='Estado derivado.',
            agent=self.agent,
        )

    def _evidence(self, sn):
        return Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item',
            serial_number=sn,
            agent=self.agent,
        )

    def _chain(self, ev, eventos):
        for event_type, custodian_type in eventos:
            # A RESTITUICAO exige a identidade do recetor (clean(), hv3) —
            # identidade canónica da fonte única de teste.
            extra = RECEIVER_KWARGS if event_type == EventType.RESTITUICAO else {}
            ChainOfCustody(
                evidence=ev,
                event_type=event_type,
                custodian_type=custodian_type,
                agent=self.agent,
                **extra,
            ).save()
        return list(ev.custody_chain.order_by('sequence'))

    def test_estado_vazio_fallback(self):
        self.assertEqual(derive_legal_state([]), 'a_guarda_opc')

    def test_a_guarda_opc(self):
        ev = self._evidence('DLS-1')
        eventos = self._chain(ev, [(EventType.APREENSAO_OBJETO, CustodianType.OPC)])
        self.assertEqual(derive_legal_state(eventos), 'a_guarda_opc')

    def test_validacao_nao_muda_o_estado_de_custodia(self):
        """A validação é ATO jurídico, não deslocação: o estado de custódia
        mantém-se a_guarda_opc; o estatuto deriva-se no eixo próprio."""
        ev = self._evidence('DLS-2')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'a_guarda_opc')
        self.assertEqual(validation_status(eventos, timezone.now()), 'validada')

    def test_encaminhada(self):
        ev = self._evidence('DLS-3')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                # Gate (ADR-0016 v2): o laboratório exige um despacho prévio.
                (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                # Movimentação LEGADO (um só tempo) — ainda deriva 'encaminhada'.
                (EventType.TRANSFERENCIA_CUSTODIA, CustodianType.LAB_PUBLICO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'encaminhada')

    def test_em_pericia(self):
        ev = self._evidence('DLS-4')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                (EventType.TRANSFERENCIA_CUSTODIA, CustodianType.LAB_PUBLICO),
                (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'em_pericia')

    def test_pericia_concluida(self):
        ev = self._evidence('DLS-5')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
                (EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'pericia_concluida')

    def test_segunda_pericia_volta_a_em_pericia(self):
        """Nova perícia (Art. 158.º) após conclusão → em_pericia outra vez."""
        ev = self._evidence('DLS-5b')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
                (EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO),
                (EventType.INICIO_PERICIA, CustodianType.LAB_PRIVADO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'em_pericia')

    def test_restituida_terminal(self):
        ev = self._evidence('DLS-6')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.RESTITUICAO, CustodianType.PROPRIETARIO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'restituida')

    def test_perdida_favor_estado(self):
        ev = self._evidence('DLS-7')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.PERDA_FAVOR_ESTADO, CustodianType.DEPOSITARIO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'perdida_favor_estado')

    def test_destruida_terminal(self):
        ev = self._evidence('DLS-8')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.DESTRUICAO, CustodianType.DEPOSITARIO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'destruida')

    def test_encaminhada_apos_pericia_concluida(self):
        """Transferência para outro lab APÓS uma perícia concluída → encaminhada.

        Regressão: o estado segue o ÚLTIMO acto (a transferência), não a perícia
        anterior — fluxo de 2.ª perícia noutro laboratório (CPP Art. 158.º).
        """
        ev = self._evidence('DLS-9')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
                (EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO),
                (EventType.TRANSFERENCIA_CUSTODIA, CustodianType.LAB_PRIVADO),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'encaminhada')

    def test_transferencia_para_tribunal_e_encaminhada(self):
        """Transferência para custódio não-laboratorial (tribunal) → encaminhada."""
        ev = self._evidence('DLS-10')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                (EventType.TRANSFERENCIA_CUSTODIA, CustodianType.TRIBUNAL),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'encaminhada')

    def test_transferencia_de_volta_ao_opc(self):
        """Transferência de regresso ao OPC → à guarda do OPC (não encaminhada)."""
        ev = self._evidence('DLS-11')
        eventos = self._chain(
            ev,
            [
                (EventType.APREENSAO_OBJETO, CustodianType.OPC),
                (EventType.VALIDACAO_APREENSAO, CustodianType.OPC),
                (EventType.DESPACHO_PERICIA, CustodianType.OPC),
                (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
                (EventType.CONCLUSAO_PERICIA, CustodianType.LAB_PUBLICO),
                (EventType.TRANSFERENCIA_CUSTODIA, CustodianType.OPC),
            ],
        )
        self.assertEqual(derive_legal_state(eventos), 'a_guarda_opc')


class _RegStub:
    """Registo mínimo para testar funções PURAS da policy (event_type+timestamp)."""

    def __init__(self, event_type, timestamp=None):
        self.event_type = event_type
        self.timestamp = timestamp


class ValidationStatusTest(TestCase):
    """Estatuto de validação da apreensão (CPP art. 178.º/6) — eixo ORTOGONAL ao
    estado de custódia: a validação é ato jurídico, não deslocação, e por isso
    nunca aparece em derive_legal_state nem desaparece quando o item viaja."""

    def setUp(self):
        self.now = timezone.now()

    def _seizure(self, age):
        return _RegStub(EventType.APREENSAO_OBJETO, self.now - age)

    def test_sem_apreensao_nao_aplicavel(self):
        # Item autonomizado no laboratório herda a base legal do pai.
        eventos = [_RegStub(EventType.DERIVACAO_ITEM, self.now)]
        self.assertIsNone(validation_status(eventos, self.now))
        self.assertIsNone(validation_status([], self.now))

    def test_apreensao_dentro_do_prazo_por_validar(self):
        eventos = [self._seizure(timedelta(hours=1))]
        self.assertEqual(validation_status(eventos, self.now), 'por_validar')

    def test_apreensao_fora_do_prazo_em_atraso(self):
        eventos = [self._seizure(VALIDATION_DEADLINE + timedelta(minutes=1))]
        self.assertEqual(validation_status(eventos, self.now), 'em_atraso')

    def test_validada_sobrevive_a_viagem(self):
        # O marco legal não se perde com encaminhamento+receção (a nota que
        # motivou a separação dos eixos).
        eventos = [
            self._seizure(timedelta(days=5)),
            _RegStub(EventType.VALIDACAO_APREENSAO, self.now - timedelta(days=4)),
            _RegStub(EventType.ENCAMINHAMENTO_CUSTODIA, self.now - timedelta(days=2)),
            _RegStub(EventType.RECEPCAO_CUSTODIA, self.now - timedelta(days=1)),
        ]
        self.assertEqual(validation_status(eventos, self.now), 'validada')

    def test_disposicao_final_extingue_exigencia(self):
        # Restituída sem validação: a apreensão cessou — nada resta para validar.
        eventos = [
            self._seizure(timedelta(days=5)),
            _RegStub(EventType.RESTITUICAO, self.now - timedelta(days=1)),
        ]
        self.assertIsNone(validation_status(eventos, self.now))

    def test_validada_e_depois_restituida_continua_validada(self):
        # A validação registada é facto histórico; a disposição não a apaga.
        eventos = [
            self._seizure(timedelta(days=5)),
            _RegStub(EventType.VALIDACAO_APREENSAO, self.now - timedelta(days=4)),
            _RegStub(EventType.RESTITUICAO, self.now - timedelta(days=1)),
        ]
        self.assertEqual(validation_status(eventos, self.now), 'validada')


class CustodyHashFormulaTest(TestCase):
    """Determinismo, vector de regressão, GPS, escaping e quantização (ADR-0013)."""

    def setUp(self):
        self.agent = User.objects.create_user(username='ag_hash', password='x12345678')
        self.occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-HASH-001',
            description='Hash.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item hash.',
            agent=self.agent,
        )

    def _build(self, **kwargs):
        """Constrói (sem gravar) um registo já com sequence/timestamp fixos."""
        defaults = dict(
            evidence=self.evidence,
            event_type=EventType.APREENSAO_OBJETO,
            custodian_type=CustodianType.OPC,
            agent=self.agent,
            sequence=1,
            timestamp=timezone.now(),
            observations='obs',
        )
        defaults.update(kwargs)
        return ChainOfCustody(**defaults)

    def test_hash_determinista(self):
        rec = self._build()
        self.assertEqual(
            rec.compute_record_hash(previous_hash='0' * 64),
            rec.compute_record_hash(previous_hash='0' * 64),
        )

    def test_hash_vector_de_regressao(self):
        """Congela a STRING DE DADOS exacta e o SHA-256 esperado (contrato)."""
        ts = timezone.datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
        rec = self._build(
            sequence=2,
            timestamp=ts,
            event_type=EventType.TRANSFERENCIA_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            location_name='Bomba BP, Av. da Liberdade | Lisboa',
            storage_location='Armário B-12, Sala 3',
            gps_lat=LISBOA_GPS[0],
            gps_lng=LISBOA_GPS[1],
            gps_accuracy_m=8,
            observations='obs reg',
        )
        prev = 'a' * 64
        # String de dados esperada (17 segmentos, ordem fixa — ADR-0013 + ADR-0016 §6).
        # event_type/custodian_type CRUS; texto livre escapado (| e , → \| \,);
        # gps_* já com 7 casas; observations + selo por-evento no fim.
        esperado = (
            f'{prev}|'
            'seq=2|'
            f'{self.evidence.id}|'
            'TRANSFERENCIA_CUSTODIA|'
            'LAB_PUBLICO|'
            f'{self.agent.id}|'
            '2026-05-30T12:00:00+00:00|'
            '38.7223340|'
            '-9.1393366|'
            '8|'
            r'Bomba BP\, Av. da Liberdade \| Lisboa|'
            r'Armário B-12\, Sala 3|'
            'obs reg'
            # Selo por-evento (ADR-0016 §6) — vazios/falsos neste vetor.
            '|sealed=0|sealcond=|newseal=|relinq='
        )
        esperado_hash = hashlib.sha256(esperado.encode('utf-8')).hexdigest()
        self.assertEqual(rec.compute_record_hash(previous_hash=prev), esperado_hash)

    def test_hash_difere_com_e_sem_gps(self):
        com = self._build(gps_lat=LISBOA_GPS[0], gps_lng=LISBOA_GPS[1])
        sem = self._build()
        self.assertNotEqual(
            com.compute_record_hash(previous_hash='0' * 64),
            sem.compute_record_hash(previous_hash='0' * 64),
        )

    def test_hash_gps_parcial_difere_de_sem_gps(self):
        """Só gps_accuracy_m preenchido (lat/lng nulos) difere de tudo nulo."""
        parcial = self._build(gps_accuracy_m=12)
        sem = self._build()
        self.assertNotEqual(
            parcial.compute_record_hash(previous_hash='0' * 64),
            sem.compute_record_hash(previous_hash='0' * 64),
        )

    def test_hash_ordem_lat_lng_nao_comutavel(self):
        a = self._build(gps_lat=LISBOA_GPS[0], gps_lng=LISBOA_GPS[1])
        b = self._build(gps_lat=LISBOA_GPS[1], gps_lng=LISBOA_GPS[0])
        self.assertNotEqual(
            a.compute_record_hash(previous_hash='0' * 64),
            b.compute_record_hash(previous_hash='0' * 64),
        )

    def test_hash_escaping_evita_colisao(self):
        """Sem escaping, estas duas location_name colidiriam na string de dados."""
        a = self._build(location_name='A,B', storage_location='')
        b = self._build(location_name='A', storage_location='B')
        self.assertNotEqual(
            a.compute_record_hash(previous_hash='0' * 64),
            b.compute_record_hash(previous_hash='0' * 64),
        )

    def test_quantizacao_no_clean_determinismo(self):
        """gps_lat com 5 casas é quantizado a 7 no clean(); o hash recomputado
        a partir do registo relido da BD bate certo com o gravado."""
        rec = ChainOfCustody(
            evidence=self.evidence,
            event_type=EventType.APREENSAO_OBJETO,
            custodian_type=CustodianType.OPC,
            agent=self.agent,
            gps_lat=Decimal('38.72234'),
            gps_lng=Decimal('-9.13934'),
        )
        rec.save()
        relido = ChainOfCustody.objects.get(pk=rec.pk)
        self.assertEqual(str(relido.gps_lat), '38.7223400')
        self.assertEqual(
            relido.compute_record_hash(previous_hash='0' * 64),
            relido.record_hash,
        )


_ONLY_PG = 'Os triggers de imutabilidade só existem em PostgreSQL.'


class ImmutabilityTriggerTest(TestCase):
    """3.ª camada de imutabilidade — triggers PostgreSQL (BEFORE UPDATE/DELETE).

    Exercita, via cursor **bruto** (bypass do ORM e dos ``save()``/``delete()``
    sobrepostos), as três tabelas protegidas — ``core_evidence`` e
    ``core_chainofcustody`` (migration ``0002``) e ``core_occurrence``
    (migration ``0013``) — provando que a recusa de UPDATE/DELETE vem da BD,
    não apenas da camada Python (ORM/admin/API).

    Só correm contra PostgreSQL (``skipUnless``): em SQLite (BD de teste por
    omissão) os triggers não existem, pelo que ficam *skipped*. Para os
    exercitar de facto, correr a suite contra Postgres (ver job dedicado no
    pipeline). Cada método faz **uma única** operação por transação porque um
    erro de BD a meio aborta a transação corrente.
    """

    def setUp(self):
        self.agent = User.objects.create_user(username='ag_trg', password='x12345678')
        self.occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-TRG-001',
            description='Trigger.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item trigger.',
            agent=self.agent,
        )
        self.record = ChainOfCustody(
            evidence=self.evidence,
            event_type=EventType.APREENSAO_OBJETO,
            custodian_type=CustodianType.OPC,
            agent=self.agent,
        )
        self.record.save()

    # -- ChainOfCustody (core_chainofcustody, trigger de 0002) ------------

    @unittest.skipUnless(connection.vendor == 'postgresql', _ONLY_PG)
    def test_update_directo_custody_bloqueado(self):
        """UPDATE directo numa coluna do ledger (event_type) é recusado pelo trigger."""
        with self.assertRaises(DatabaseError), connection.cursor() as cur:
            cur.execute(
                'UPDATE core_chainofcustody SET event_type = %s WHERE id = %s',
                [EventType.VALIDACAO_APREENSAO, self.record.pk],
            )

    @unittest.skipUnless(connection.vendor == 'postgresql', _ONLY_PG)
    def test_delete_directo_custody_bloqueado(self):
        """DELETE directo de um registo do ledger é recusado pelo trigger."""
        with self.assertRaises(DatabaseError), connection.cursor() as cur:
            cur.execute(
                'DELETE FROM core_chainofcustody WHERE id = %s',
                [self.record.pk],
            )

    # -- Evidence (core_evidence, trigger de 0002) ------------------------

    @unittest.skipUnless(connection.vendor == 'postgresql', _ONLY_PG)
    def test_update_directo_evidence_bloqueado(self):
        """UPDATE directo numa coluna da evidência é recusado pelo trigger."""
        with self.assertRaises(DatabaseError), connection.cursor() as cur:
            cur.execute(
                'UPDATE core_evidence SET description = %s WHERE id = %s',
                ['adulterado', self.evidence.pk],
            )

    @unittest.skipUnless(connection.vendor == 'postgresql', _ONLY_PG)
    def test_delete_directo_evidence_bloqueado(self):
        """DELETE directo de uma evidência é recusado pelo trigger.

        Usa uma evidência **sem** registos de custódia a referenciá-la, para
        isolar o trigger da restrição de chave estrangeira.
        """
        ev = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Sem custódia.',
            agent=self.agent,
        )
        with self.assertRaises(DatabaseError), connection.cursor() as cur:
            cur.execute('DELETE FROM core_evidence WHERE id = %s', [ev.pk])

    # -- Occurrence (core_occurrence, trigger de 0013) --------------------

    @unittest.skipUnless(connection.vendor == 'postgresql', _ONLY_PG)
    def test_update_directo_occurrence_bloqueado(self):
        """UPDATE directo numa coluna da ocorrência é recusado pelo trigger (0013)."""
        with self.assertRaises(DatabaseError), connection.cursor() as cur:
            cur.execute(
                'UPDATE core_occurrence SET description = %s WHERE id = %s',
                ['adulterado', self.occ.pk],
            )

    @unittest.skipUnless(connection.vendor == 'postgresql', _ONLY_PG)
    def test_delete_directo_occurrence_bloqueado(self):
        """DELETE directo de uma ocorrência é recusado pelo trigger (0013).

        Usa uma ocorrência **sem** evidências a referenciá-la, para isolar o
        trigger da restrição de chave estrangeira.
        """
        occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-TRG-002',
            description='Sem evidências.',
            agent=self.agent,
        )
        with self.assertRaises(DatabaseError), connection.cursor() as cur:
            cur.execute('DELETE FROM core_occurrence WHERE id = %s', [occ.pk])
