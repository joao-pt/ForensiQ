"""
ForensiQ — Testes da página de intake no laboratório (ADR-0012 Vaga 2).

Cobertura da view `/occurrences/<id>/intake/`:

- Sem JWT cookie → redirect para /login/ com next=...
- JWT inválido/expirado → redirect.
- JWT válido + AGENT → 403 (template `403_intake.html`).
- JWT válido + EXPERT → 200 (template `occurrence_intake.html`).
- JWT válido + staff/superuser → 200.
- Ocorrência inexistente → 404.
- Template inclui:
  - código da ocorrência
  - contagem de evidências esperadas
  - 1 checkbox por evidência (com `disabled` se já recebida)
  - target_state = TRANSFERENCIA_CUSTODIA (evento → LAB_PUBLICO, ADR-0015)

A submissão real (POST a `/api/custody/cascade/`) é coberta pelos
testes existentes do cascade endpoint — este ficheiro só valida a
camada de render + auth.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import (
    ChainOfCustody,
    Evidence,
    Institution,
    InstitutionType,
    Occurrence,
    Portador,
)

User = get_user_model()


from core.tests_factories import CrimeTipoFactory


def _make_user(username, profile='FIRST_RESPONDER', is_staff=False, is_superuser=False):
    user = User.objects.create_user(
        username=username,
        password='TestPass123!',
        profile=profile,
    )
    if is_staff:
        user.is_staff = True
    if is_superuser:
        user.is_superuser = True
        user.is_staff = True
    user.save()
    return user


def _login_cookie(client, user):
    refresh = RefreshToken.for_user(user)
    access = str(refresh.access_token)
    client.cookies['fq_access'] = access


def _make_occurrence(agent):
    return Occurrence.objects.create(
        crime_type=CrimeTipoFactory(),
        number='OCC-INTAKE-001',
        description='Intake test',
        date_time=timezone.now(),
        gps_lat=Decimal('38.7'),
        gps_lng=Decimal('-9.1'),
        address='Lab Test',
        agent=agent,
    )


def _make_evidence(occurrence, agent, serial):
    return Evidence.objects.create(
        occurrence=occurrence,
        type=Evidence.EvidenceType.MOBILE_DEVICE,
        description='Item para intake',
        serial_number=serial,
        agent=agent,
    )


class OccurrenceIntakeAuthTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = _make_user('agent_intake')
        cls.expert = _make_user('expert_intake', profile='FORENSIC_EXPERT')
        cls.staff = _make_user('staff_intake', is_staff=True)
        cls.occurrence = _make_occurrence(cls.agent)
        cls.evidence = _make_evidence(cls.occurrence, cls.agent, 'SN-IN-001')

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=False)

    def _url(self, occ_id=None):
        oid = occ_id or self.occurrence.id
        return f'/occurrences/{oid}/intake/'

    def test_sem_cookie_redirect_login(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_cookie_invalido_redirect_login(self):
        self.client.cookies['fq_access'] = 'invalid-token'
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_agent_logado_devolve_403(self):
        _login_cookie(self.client, self.agent)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Sem permiss', response.content)

    def test_expert_logado_devolve_200(self):
        _login_cookie(self.client, self.expert)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.occurrence.code.encode(), response.content)

    def test_staff_logado_devolve_200(self):
        _login_cookie(self.client, self.staff)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

    def test_occurrence_inexistente_404(self):
        _login_cookie(self.client, self.expert)
        response = self.client.get(self._url(99999))
        self.assertEqual(response.status_code, 404)


class OccurrenceIntakeRenderTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = _make_user('agent_render')
        cls.expert = _make_user('expert_render', profile='FORENSIC_EXPERT')
        cls.occurrence = _make_occurrence(cls.agent)
        cls.ev_pending = _make_evidence(cls.occurrence, cls.agent, 'SN-PND-1')
        cls.ev_in_transit = _make_evidence(cls.occurrence, cls.agent, 'SN-TRA-1')
        cls.ev_received = _make_evidence(cls.occurrence, cls.agent, 'SN-RCV-1')
        # Destino do encaminhamento + portador (ADR-0016 v2 — handoff em 2 tempos).
        cls.lab = Institution.objects.create(
            name='Lab Intake', type=InstitutionType.LAB_PUBLICO, sigla='LAB-INT'
        )
        cls.portador = Portador.objects.create(
            matricula='INT-0001', nome='Ana', apelido='Costa', posto='Agente'
        )
        # Ledger de eventos (ADR-0015 / ADR-0016 v2):
        # - pending    → só APREENSAO_OBJETO (a_guarda_opc; nem em trânsito nem recebida).
        # - in_transit → …+DESPACHO+ENCAMINHAMENTO (em_transito = recebível no intake).
        # - received   → …+ENCAMINHAMENTO+RECEPCAO  (encaminhada = "já recebida").
        ChainOfCustody.objects.create(
            evidence=cls.ev_pending,
            event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=cls.agent,
        )
        for ev in (cls.ev_in_transit, cls.ev_received):
            for et in (
                ChainOfCustody.EventType.APREENSAO_OBJETO,
                ChainOfCustody.EventType.VALIDACAO_APREENSAO,
                ChainOfCustody.EventType.DESPACHO_PERICIA,
            ):
                ChainOfCustody.objects.create(
                    evidence=ev,
                    event_type=et,
                    custodian_type=ChainOfCustody.CustodianType.OPC,
                    agent=cls.agent,
                )
            ChainOfCustody.objects.create(
                evidence=ev,
                event_type=ChainOfCustody.EventType.ENCAMINHAMENTO_CUSTODIA,
                custodian_type=ChainOfCustody.CustodianType.LAB_PUBLICO,
                custodian_institution=cls.lab,
                bearer=cls.portador,
                agent=cls.agent,
            )
        # ev_received fecha o trânsito com a receção no laboratório (perito).
        ChainOfCustody.objects.create(
            evidence=cls.ev_received,
            event_type=ChainOfCustody.EventType.RECEPCAO_CUSTODIA,
            custodian_type=ChainOfCustody.CustodianType.LAB_PUBLICO,
            custodian_institution=cls.lab,
            agent=cls.expert,
        )

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=False)
        _login_cookie(self.client, self.expert)

    def test_template_inclui_codigo_ocorrencia(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        self.assertIn(self.occurrence.code.encode(), response.content)

    def test_template_inclui_contagem(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        # O cabeçalho da receção mostra a contagem em texto livre
        # (`{{ evidence_count }} ite{{ ...|pluralize }}`). 3 evidências no setup.
        self.assertIn(b'3 itens', response.content)

    def test_template_recebidas_nao_tem_checkbox(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        # A evidência já recebida não é selecionável: a sua linha mostra o
        # estado "Já recebida" (em vez de um checkbox `evidence_ids`).
        self.assertNotIn(
            f'name="evidence_ids" value="{self.ev_received.id}"'.encode(),
            response.content,
        )
        self.assertIn(b'>J\xc3\xa1 recebida<', response.content)

    def test_template_pendentes_tem_checkbox_selecionavel(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        # As evidências ainda não recebidas têm um checkbox `evidence_ids`
        # pré-marcado para a receção em lote.
        chk = f'name="evidence_ids" value="{self.ev_in_transit.id}" checked'.encode()
        self.assertIn(chk, response.content)

    def test_template_indica_recepcao_de_prova_encaminhada(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        # Intake = fase 2 do handoff (ADR-0016 v2): regista a RECEÇÃO da prova
        # encaminhada. O DOM não expõe o enum cru; comunica-o no cabeçalho.
        self.assertIn(
            'Receção de prova encaminhada'.encode(),
            response.content,
        )
