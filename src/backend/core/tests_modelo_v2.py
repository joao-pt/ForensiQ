"""
ForensiQ — Testes do modelo v2 (ADR-0016): génese, IDs hierárquicos, bifurcação,
hash-chain com selo. Famílias 1–5 da estratégia de testes (as 6–8, de acesso,
estão em tests_access).
"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    ChainOfCustody,
    EventType,
    Evidence,
    Occurrence,
)
from core.tests_factories import RECEIVER_KWARGS, CrimeTipoFactory, UserFactory


def _occ(agent, n):
    return Occurrence.objects.create(
        number=f'NUIPC-V2-{n}',
        crime_type=CrimeTipoFactory(),
        description='caso de teste do modelo v2',
        date_time=timezone.now(),
        agent=agent,
    )


def _ev(occ, agent, etype=Evidence.EvidenceType.MOBILE_DEVICE, parent=None):
    return Evidence.objects.create(
        occurrence=occ,
        type=etype,
        description='item',
        timestamp_seizure=timezone.now(),
        agent=agent,
        parent_evidence=parent,
    )


class HierarchicalIdTest(TestCase):
    """Família 5 — geração de IDs hierárquicos (ADR-0016 §1)."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()
        cls.occ = _occ(cls.agent, '5')

    def test_codigo_ocorrencia_ano_de_registo(self):
        ano = timezone.now().year
        self.assertTrue(self.occ.code.startswith(f'OC-{ano}-'))

    def test_indice_local_raiz_por_ocorrencia(self):
        e1 = _ev(self.occ, self.agent)
        e2 = _ev(self.occ, self.agent)
        self.assertEqual(e1.code, f'{self.occ.code}.1')
        self.assertEqual(e2.code, f'{self.occ.code}.2')

    def test_subitem_indice_por_pai_nao_consome_o_da_ocorrencia(self):
        e1 = _ev(self.occ, self.agent)
        s1 = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=e1)
        s2 = _ev(self.occ, self.agent, Evidence.EvidenceType.MEMORY_CARD, parent=e1)
        # Os sub-itens contam por pai (1, 2) e o código deriva do pai.
        self.assertEqual(s1.code, f'{e1.code}.1')
        self.assertEqual(s2.code, f'{e1.code}.2')
        # Um novo item-raiz é o .2 da ocorrência (os sub-itens não consumiram o contador).
        e2 = _ev(self.occ, self.agent)
        self.assertEqual(e2.code, f'{self.occ.code}.2')

    def test_codigo_movimento_e_o_do_item_mais_M(self):
        e1 = _ev(self.occ, self.agent)
        r1 = ChainOfCustody.objects.create(
            evidence=e1, event_type=EventType.APREENSAO_OBJETO, agent=self.agent
        )
        r2 = ChainOfCustody.objects.create(
            evidence=e1, event_type=EventType.VALIDACAO_APREENSAO, agent=self.agent
        )
        self.assertEqual(r1.code, f'{e1.code}-M01')
        self.assertEqual(r2.code, f'{e1.code}-M02')
        self.assertEqual(r2.sequence, 2)


class GenesisGuardTest(TestCase):
    """Família 4 — guardas de génese/sequência (ADR-0016 §2)."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()
        cls.occ = _occ(cls.agent, '4')

    def _genesis(self, ev, event_type):
        rec = ChainOfCustody(evidence=ev, event_type=event_type, agent=self.agent)
        rec.save()
        return rec

    def test_primeiro_evento_tem_de_ser_genese(self):
        ev = _ev(self.occ, self.agent)
        with self.assertRaises(ValidationError):
            self._genesis(ev, EventType.VALIDACAO_APREENSAO)

    def test_apreensao_dados_so_para_digital_file(self):
        ev = _ev(self.occ, self.agent, Evidence.EvidenceType.MOBILE_DEVICE)
        with self.assertRaises(ValidationError):
            self._genesis(ev, EventType.APREENSAO_DADOS)
        dig = _ev(self.occ, self.agent, Evidence.EvidenceType.DIGITAL_FILE)
        self._genesis(dig, EventType.APREENSAO_DADOS)  # válido

    def test_derivacao_item_exige_pai(self):
        raiz = _ev(self.occ, self.agent)
        with self.assertRaises(ValidationError):
            self._genesis(raiz, EventType.DERIVACAO_ITEM)
        self._genesis(raiz, EventType.APREENSAO_OBJETO)
        sub = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
        self._genesis(sub, EventType.DERIVACAO_ITEM)  # válido

    def test_apreensao_objeto_nao_em_subcomponente(self):
        raiz = _ev(self.occ, self.agent)
        self._genesis(raiz, EventType.APREENSAO_OBJETO)
        sub = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
        with self.assertRaises(ValidationError):
            self._genesis(sub, EventType.APREENSAO_OBJETO)

    def test_apreensao_objeto_nao_em_digital_file_raiz(self):
        # Drift fechado (auditoria D31): a cópia de dados entra por
        # APREENSAO_DADOS; o clean() aceitava o que o ecrã nunca oferecia.
        dig = _ev(self.occ, self.agent, Evidence.EvidenceType.DIGITAL_FILE)
        with self.assertRaises(ValidationError):
            self._genesis(dig, EventType.APREENSAO_OBJETO)

    def test_apreensao_dados_nao_em_subcomponente(self):
        # Idem: um DIGITAL_FILE com evidência-pai autonomiza-se por derivação.
        raiz = _ev(self.occ, self.agent)
        self._genesis(raiz, EventType.APREENSAO_OBJETO)
        sub = _ev(self.occ, self.agent, Evidence.EvidenceType.DIGITAL_FILE, parent=raiz)
        with self.assertRaises(ValidationError):
            self._genesis(sub, EventType.APREENSAO_DADOS)

    def test_validacao_exige_apreensao_previa(self):
        # Numa cadeia que começa por DERIVACAO_ITEM não há apreensão a validar.
        raiz = _ev(self.occ, self.agent)
        self._genesis(raiz, EventType.APREENSAO_OBJETO)
        sub = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
        self._genesis(sub, EventType.DERIVACAO_ITEM)
        rec = ChainOfCustody(
            evidence=sub, event_type=EventType.VALIDACAO_APREENSAO, agent=self.agent
        )
        with self.assertRaises(ValidationError):
            rec.save()

    def test_terminal_fecha_o_ledger(self):
        ev = _ev(self.occ, self.agent)
        self._genesis(ev, EventType.APREENSAO_OBJETO)
        ChainOfCustody.objects.create(
            evidence=ev, event_type=EventType.RESTITUICAO, agent=self.agent,
            **RECEIVER_KWARGS,
        )
        rec = ChainOfCustody(
            evidence=ev, event_type=EventType.TRANSFERENCIA_CUSTODIA, agent=self.agent
        )
        with self.assertRaises(ValidationError):
            rec.save()

    def test_derivacao_de_pai_fechado_proibida(self):
        raiz = _ev(self.occ, self.agent)
        self._genesis(raiz, EventType.APREENSAO_OBJETO)
        ChainOfCustody.objects.create(
            evidence=raiz, event_type=EventType.DESTRUICAO, agent=self.agent
        )
        sub = _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
        rec = ChainOfCustody(evidence=sub, event_type=EventType.DERIVACAO_ITEM, agent=self.agent)
        with self.assertRaises(ValidationError):
            rec.save()


class BifurcationTest(TestCase):
    """Família 3 — continuidade per-item / bifurcação (ADR-0016)."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()
        cls.occ = _occ(cls.agent, '3')
        cls.raiz = _ev(cls.occ, cls.agent)
        cls.sub = _ev(cls.occ, cls.agent, Evidence.EvidenceType.SIM_CARD, parent=cls.raiz)
        ChainOfCustody.objects.create(
            evidence=cls.raiz, event_type=EventType.APREENSAO_OBJETO, agent=cls.agent
        )
        ChainOfCustody.objects.create(
            evidence=cls.raiz, event_type=EventType.VALIDACAO_APREENSAO, agent=cls.agent
        )
        ChainOfCustody.objects.create(
            evidence=cls.sub, event_type=EventType.DERIVACAO_ITEM, agent=cls.agent
        )

    def test_cadeias_independentes(self):
        self.assertEqual(self.raiz.custody_chain.count(), 2)
        self.assertEqual(self.sub.custody_chain.count(), 1)

    def test_sequence_reinicia_por_evidencia(self):
        seqs_raiz = list(self.raiz.custody_chain.order_by('sequence').values_list('sequence', flat=True))
        seqs_sub = list(self.sub.custody_chain.values_list('sequence', flat=True))
        self.assertEqual(seqs_raiz, [1, 2])
        self.assertEqual(seqs_sub, [1])


class HashChainSealTest(TestCase):
    """Família 2 — hash-chain com selo por-evento (ADR-0016 §6)."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()
        cls.occ = _occ(cls.agent, '2')
        cls.ev = _ev(cls.occ, cls.agent)

    def test_record_hash_inclui_campos_de_selo(self):
        # Dois eventos idênticos exceto no selo → hashes diferentes.
        r1 = ChainOfCustody(
            evidence=self.ev, event_type=EventType.APREENSAO_OBJETO, agent=self.agent
        )
        h_sem_selo = r1.compute_record_hash(previous_hash='0' * 64)
        r1.sealed = True
        r1.new_seal_number = 'SEL-2026-0001'
        h_com_selo = r1.compute_record_hash(previous_hash='0' * 64)
        self.assertNotEqual(h_sem_selo, h_com_selo)

    def test_cadeia_encadeada_deteta_adulteracao(self):
        r1 = ChainOfCustody.objects.create(
            evidence=self.ev, event_type=EventType.APREENSAO_OBJETO, agent=self.agent
        )
        r2 = ChainOfCustody.objects.create(
            evidence=self.ev, event_type=EventType.VALIDACAO_APREENSAO, agent=self.agent
        )
        # Recalcular r2 encadeado a partir do r1 reproduz o hash gravado.
        self.assertEqual(r2.compute_record_hash(previous_hash=r1.record_hash), r2.record_hash)
        # Adulterar um campo muda o hash recalculado.
        r2.observations = 'adulterado'
        self.assertNotEqual(
            r2.compute_record_hash(previous_hash=r1.record_hash), r2.record_hash
        )


class IntegrityHashAcquisitionTest(TestCase):
    """Família 2b — integrity_hash inclui aquisição + selo inicial (ADR-0016 §6)."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()
        cls.occ = _occ(cls.agent, '2b')

    def test_acquisition_hash_entra_no_integrity_hash(self):
        ev = Evidence(
            occurrence=self.occ,
            type=Evidence.EvidenceType.DIGITAL_FILE,
            description='cópia de dados',
            timestamp_seizure=timezone.now(),
            agent=self.agent,
        )
        h_sem = ev.compute_integrity_hash()
        ev.acquisition_hash = 'a' * 64
        ev.acquisition_hash_algo = 'SHA-256'
        h_com = ev.compute_integrity_hash()
        self.assertNotEqual(h_sem, h_com)

    def test_selo_inicial_entra_no_integrity_hash(self):
        ev = Evidence(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='item',
            timestamp_seizure=timezone.now(),
            agent=self.agent,
        )
        h_sem = ev.compute_integrity_hash()
        ev.initial_seal_number = 'SEL-INI-0001'
        ev.bag_number = 'BAG-001'
        h_com = ev.compute_integrity_hash()
        self.assertNotEqual(h_sem, h_com)
