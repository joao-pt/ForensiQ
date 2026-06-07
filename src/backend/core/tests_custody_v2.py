"""
ForensiQ — Testes do modelo de custódia v2 (ADR-0016): portador na cadeia de
hash (hv2), gate de laboratório, handoff em dois tempos (encaminhar → receber),
estado ``em_transito`` e caixa "prova a chegar" (ProvaEmTransito).

Todos os eventos são criados append-only (.save()); nada de UPDATE no ledger
(os triggers de imutabilidade do PostgreSQL bloqueariam-no). O snapshot do
portador estabiliza no momento do evento — editar/desativar o Portador depois
nunca altera hashes já calculados.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from core import access
from core.models import (
    ChainOfCustody,
    CustodianType,
    EventType,
    Evidence,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Occurrence,
    Portador,
    ProvaEmTransito,
    User,
    derive_legal_state,
)
from core.tests_factories import CrimeTipoFactory


def _user(username, profile=User.Profile.FIRST_RESPONDER, clearance=None):
    kwargs = {'username': username, 'password': 'x12345678', 'profile': profile}
    if clearance is not None:
        kwargs['clearance'] = clearance
    return User.objects.create_user(**kwargs)


class CustodyV2Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = _user('cv2_agent')
        cls.expert = _user('cv2_expert', User.Profile.FORENSIC_EXPERT)
        cls.lab = Institution.objects.create(
            name='LPC v2',
            type=InstitutionType.LAB_PUBLICO,
            sigla='LPC-V2',
            gps_lat=Decimal('38.7256000'),
            gps_lng=Decimal('-9.1430000'),
        )
        cls.portador = Portador.objects.create(
            matricula='PSP-V2-001', nome='Rui', apelido='Marques', posto='Agente Principal'
        )

    def _occ(self, n):
        return Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number=f'NUIPC-CV2-{n}',
            description='Custódia v2.',
            agent=self.agent,
        )

    def _ev(self, occ, sn):
        return Evidence.objects.create(
            occurrence=occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item',
            serial_number=sn,
            agent=self.agent,
        )

    def _save(self, ev, event_type, **kwargs):
        rec = ChainOfCustody(evidence=ev, event_type=event_type, agent=self.agent, **kwargs)
        rec.save()
        return rec

    def _despachado(self, sn):
        """Evidência apreendida, validada e despachada (à guarda do OPC)."""
        occ = self._occ(sn)
        ev = self._ev(occ, sn)
        self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self._save(ev, EventType.VALIDACAO_APREENSAO, custodian_type=CustodianType.OPC)
        self._save(ev, EventType.DESPACHO_PERICIA, custodian_type=CustodianType.OPC)
        return ev


class LabGateTest(CustodyV2Base):
    """Gate (CPP Art. 154.º): laboratório não admite prova sem despacho prévio."""

    def test_encaminhar_para_lab_sem_despacho_falha(self):
        occ = self._occ('G1')
        ev = self._ev(occ, 'G1')
        self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self._save(ev, EventType.VALIDACAO_APREENSAO, custodian_type=CustodianType.OPC)
        with self.assertRaises(ValidationError):
            self._save(
                ev,
                EventType.ENCAMINHAMENTO_CUSTODIA,
                custodian_type=CustodianType.LAB_PUBLICO,
                custodian_institution=self.lab,
                bearer=self.portador,
            )

    def test_transferencia_legado_para_lab_sem_despacho_falha(self):
        occ = self._occ('G2')
        ev = self._ev(occ, 'G2')
        self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        with self.assertRaises(ValidationError):
            self._save(
                ev,
                EventType.TRANSFERENCIA_CUSTODIA,
                custodian_type=CustodianType.LAB_PUBLICO,
            )

    def test_encaminhar_para_lab_com_despacho_passa(self):
        ev = self._despachado('G3')
        rec = self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        self.assertEqual(rec.event_type, EventType.ENCAMINHAMENTO_CUSTODIA)

    def test_derivacao_no_lab_nao_e_bloqueada_pelo_gate(self):
        """Génese de sub-componente no laboratório herda a base legal do pai."""
        occ = self._occ('G4')
        raiz = self._ev(occ, 'G4')
        self._save(raiz, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        sub = Evidence.objects.create(
            occurrence=occ,
            type=Evidence.EvidenceType.SIM_CARD,
            description='Sub',
            serial_number='G4-SUB',
            parent_evidence=raiz,
            agent=self.agent,
        )
        # 1.º evento do sub = DERIVACAO_ITEM @ LAB, SEM despacho na cadeia do sub.
        rec = self._save(
            sub,
            EventType.DERIVACAO_ITEM,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
        )
        self.assertEqual(rec.event_type, EventType.DERIVACAO_ITEM)


class HandoffTwoPhaseTest(CustodyV2Base):
    """Encaminhar (em trânsito, sem GPS) → receber (ganha coordenadas)."""

    def test_encaminhamento_exige_portador(self):
        ev = self._despachado('H1')
        with self.assertRaises(ValidationError):
            self._save(
                ev,
                EventType.ENCAMINHAMENTO_CUSTODIA,
                custodian_type=CustodianType.LAB_PUBLICO,
                custodian_institution=self.lab,
            )

    def test_encaminhamento_exige_destino(self):
        ev = self._despachado('H2')
        with self.assertRaises(ValidationError):
            self._save(
                ev,
                EventType.ENCAMINHAMENTO_CUSTODIA,
                custodian_type=CustodianType.LAB_PUBLICO,
                bearer=self.portador,
            )

    def test_encaminhamento_rejeita_gps(self):
        ev = self._despachado('H3')
        with self.assertRaises(ValidationError):
            self._save(
                ev,
                EventType.ENCAMINHAMENTO_CUSTODIA,
                custodian_type=CustodianType.LAB_PUBLICO,
                custodian_institution=self.lab,
                bearer=self.portador,
                gps_lat=Decimal('38.7'),
                gps_lng=Decimal('-9.1'),
            )

    def test_estado_em_transito_apos_encaminhamento(self):
        ev = self._despachado('H4')
        self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        eventos = list(ev.custody_chain.order_by('sequence'))
        self.assertEqual(derive_legal_state(eventos), 'em_transito')

    def test_dois_encaminhamentos_seguidos_falha(self):
        ev = self._despachado('H5')
        self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        with self.assertRaises(ValidationError):
            self._save(
                ev,
                EventType.ENCAMINHAMENTO_CUSTODIA,
                custodian_type=CustodianType.LAB_PUBLICO,
                custodian_institution=self.lab,
                bearer=self.portador,
            )

    def test_recepcao_sem_transito_falha(self):
        ev = self._despachado('H6')
        with self.assertRaises(ValidationError):
            self._save(ev, EventType.RECEPCAO_CUSTODIA)

    def test_recepcao_herda_destino_e_coordenadas_da_instituicao(self):
        ev = self._despachado('H7')
        self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        # Receção sem GPS nem destino explícitos → herda do encaminhamento + registo.
        rec = self._save(ev, EventType.RECEPCAO_CUSTODIA)
        self.assertEqual(rec.custodian_institution_id, self.lab.id)
        self.assertEqual(rec.custodian_type, CustodianType.LAB_PUBLICO)
        self.assertEqual(rec.gps_lat, self.lab.gps_lat)
        self.assertEqual(rec.gps_lng, self.lab.gps_lng)
        eventos = list(ev.custody_chain.order_by('sequence'))
        self.assertEqual(derive_legal_state(eventos), 'encaminhada')


class BearerHashTest(CustodyV2Base):
    """Portador no hash (hv2): snapshot estável, versão por registo."""

    def test_registo_novo_e_hv2(self):
        occ = self._occ('B1')
        ev = self._ev(occ, 'B1')
        rec = self._save(ev, EventType.APREENSAO_OBJETO, custodian_type=CustodianType.OPC)
        self.assertEqual(rec.hash_version, 'hv2')

    def test_snapshot_do_portador_copiado(self):
        ev = self._despachado('B2')
        rec = self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        self.assertEqual(rec.bearer_matricula, self.portador.matricula)
        self.assertEqual(rec.bearer_nome, self.portador.nome)
        self.assertEqual(rec.bearer_apelido, self.portador.apelido)
        self.assertEqual(rec.bearer_posto, self.portador.posto)

    def test_editar_portador_nao_altera_hash_gravado(self):
        ev = self._despachado('B3')
        rec = self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        hash_original = rec.record_hash
        snapshot_original = rec.bearer_nome
        # Corrigir o registo do Portador (mutável) NÃO altera o snapshot do evento.
        self.portador.nome = 'NomeAlterado'
        self.portador.save()
        relido = ChainOfCustody.objects.get(pk=rec.pk)
        self.assertEqual(relido.bearer_nome, snapshot_original)
        self.assertEqual(relido.record_hash, hash_original)

    def test_recompute_bate_certo_com_versao_gravada(self):
        ev = self._despachado('B4')
        enc = self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        prev = (
            ev.custody_chain.filter(sequence=enc.sequence - 1).first().record_hash
        )
        relido = ChainOfCustody.objects.get(pk=enc.pk)
        self.assertEqual(relido.compute_record_hash(previous_hash=prev), relido.record_hash)

    def test_hv1_e_hv2_diferem_para_mesmos_campos(self):
        occ = self._occ('B5')
        ev = self._ev(occ, 'B5')
        comum = dict(
            evidence=ev,
            event_type=EventType.APREENSAO_OBJETO,
            custodian_type=CustodianType.OPC,
            agent=self.agent,
            sequence=1,
        )
        rec_hv1 = ChainOfCustody(hash_version='hv1', **comum)
        rec_hv2 = ChainOfCustody(hash_version='hv2', **comum)
        # timestamp determinístico igual nos dois (sem gravar — não corre save()).
        from django.utils import timezone

        ts = timezone.now()
        rec_hv1.timestamp = ts
        rec_hv2.timestamp = ts
        self.assertNotEqual(
            rec_hv1.compute_record_hash(previous_hash='0' * 64),
            rec_hv2.compute_record_hash(previous_hash='0' * 64),
        )


class ProvaEmTransitoTest(CustodyV2Base):
    """Caixa "prova a chegar": criada no encaminhamento, resolvida na receção."""

    def test_encaminhamento_cria_aviso(self):
        ev = self._despachado('P1')
        self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        aviso = ProvaEmTransito.objects.filter(evidence=ev).first()
        self.assertIsNotNone(aviso)
        self.assertEqual(aviso.destino_institution_id, self.lab.id)
        self.assertIsNone(aviso.acknowledged_at)

    def test_recepcao_resolve_aviso(self):
        ev = self._despachado('P2')
        self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        self._save(ev, EventType.RECEPCAO_CUSTODIA)
        aviso = ProvaEmTransito.objects.get(evidence=ev)
        self.assertIsNotNone(aviso.acknowledged_at)

    def test_scope_inbound_so_para_membro_do_destino(self):
        ev = self._despachado('P3')
        self._save(
            ev,
            EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO,
            custodian_institution=self.lab,
            bearer=self.portador,
        )
        membro = _user('cv2_membro', User.Profile.EVIDENCE_CUSTODIAN)
        InstitutionMembership.objects.create(user=membro, institution=self.lab)
        estranho = _user('cv2_estranho', User.Profile.EVIDENCE_CUSTODIAN)

        inbound_membro = access.scope_inbound_transit(membro)
        self.assertEqual(inbound_membro.count(), 1)
        self.assertEqual(inbound_membro.first().evidence_id, ev.id)
        # Sem pertença ao destino → caixa vazia (mesmo perito de leitura total).
        self.assertEqual(access.scope_inbound_transit(estranho).count(), 0)
        perito = _user('cv2_perito', User.Profile.FORENSIC_EXPERT, User.Clearance.NACIONAL)
        self.assertEqual(access.scope_inbound_transit(perito).count(), 0)


class SeedDemoHandoffSmokeTest(TestCase):
    """O seed completo corre e demonstra o handoff em dois tempos (ADR-0016 v2).

    Valida que ``seed_demo`` (modo completo) não rebenta com os novos eventos/
    guardas e que o resultado inclui ENCAMINHAMENTO + RECEPCAO + uma caixa
    "prova a chegar" pendente (Caso 4 fica em trânsito).
    """

    def test_seed_completo_cria_handoff_e_aviso_pendente(self):
        from io import StringIO

        from django.core.management import call_command

        call_command(
            'seed_demo',
            '--no-input',
            '--agent-username=seed-agent',
            '--agent-password=SeedAgent1!',
            '--expert-username=seed-expert',
            '--expert-password=SeedExpert1!',
            stdout=StringIO(),
            stderr=StringIO(),
        )
        self.assertTrue(
            ChainOfCustody.objects.filter(
                event_type=EventType.ENCAMINHAMENTO_CUSTODIA
            ).exists()
        )
        self.assertTrue(
            ChainOfCustody.objects.filter(event_type=EventType.RECEPCAO_CUSTODIA).exists()
        )
        # Caso 4 fica EM TRÂNSITO → pelo menos um aviso por reconhecer.
        self.assertTrue(
            ProvaEmTransito.objects.filter(acknowledged_at__isnull=True).exists()
        )
        # Portador entrou na cadeia com snapshot (hv2).
        enc = ChainOfCustody.objects.filter(
            event_type=EventType.ENCAMINHAMENTO_CUSTODIA
        ).first()
        self.assertEqual(enc.hash_version, 'hv2')
        self.assertTrue(enc.bearer_matricula)
