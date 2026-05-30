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
  - target_state = TRANSFERENCIA (evento → LAB_PUBLICO, ADR-0015)

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

from core.models import ChainOfCustody, Evidence, Occurrence

User = get_user_model()


from core.tests_factories import CrimeTipoFactory


def _make_user(username, profile='AGENT', is_staff=False, is_superuser=False):
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
        cls.expert = _make_user('expert_intake', profile='EXPERT')
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
        cls.expert = _make_user('expert_render', profile='EXPERT')
        cls.occurrence = _make_occurrence(cls.agent)
        cls.ev_pending = _make_evidence(cls.occurrence, cls.agent, 'SN-PND-1')
        cls.ev_in_transit = _make_evidence(cls.occurrence, cls.agent, 'SN-TRA-1')
        cls.ev_received = _make_evidence(cls.occurrence, cls.agent, 'SN-RCV-1')
        # Ledger de eventos (ADR-0015):
        # - pending  → só APREENSAO          (estado derivado: a_guarda_opc)
        # - in_transit → APREENSAO+VALIDACAO (estado derivado: validada)
        # - received → APREENSAO+TRANSFERENCIA→LAB_PUBLICO (encaminhada =
        #   "já recebida" no intake).
        ChainOfCustody.objects.create(
            evidence=cls.ev_pending,
            event_type=ChainOfCustody.EventType.APREENSAO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=cls.agent,
        )
        for ev in (cls.ev_in_transit, cls.ev_received):
            ChainOfCustody.objects.create(
                evidence=ev,
                event_type=ChainOfCustody.EventType.APREENSAO,
                custodian_type=ChainOfCustody.CustodianType.OPC,
                agent=cls.agent,
            )
        ChainOfCustody.objects.create(
            evidence=cls.ev_in_transit,
            event_type=ChainOfCustody.EventType.VALIDACAO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=cls.agent,
        )
        ChainOfCustody.objects.create(
            evidence=cls.ev_received,
            event_type=ChainOfCustody.EventType.TRANSFERENCIA,
            custodian_type=ChainOfCustody.CustodianType.LAB_PUBLICO,
            agent=cls.agent,
        )

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=False)
        _login_cookie(self.client, self.expert)

    def test_template_inclui_codigo_ocorrencia(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        self.assertIn(self.occurrence.code.encode(), response.content)

    def test_template_inclui_contagem(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        self.assertIn(b'Itens esperados', response.content)
        # 3 evidências criadas no setup.
        self.assertIn(b'>3<', response.content)

    def test_template_marca_recebidas_como_disabled(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        # Tolerante a whitespace: procura por `disabled` perto do id do checkbox
        # da evidência já recebida.
        ev_id_str = f'id="ev-{self.ev_received.id}"'.encode()
        self.assertIn(ev_id_str, response.content)
        idx = response.content.find(ev_id_str)
        chunk = response.content[idx : idx + 200]
        self.assertIn(b'disabled', chunk)

    def test_template_pendentes_nao_estao_disabled(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        ev_id_str = f'id="ev-{self.ev_in_transit.id}"'.encode()
        idx = response.content.find(ev_id_str)
        chunk = response.content[idx : idx + 200]
        self.assertNotIn(b'disabled', chunk)

    def test_template_inclui_target_state(self):
        response = self.client.get(f'/occurrences/{self.occurrence.id}/intake/')
        # Intake regista um evento TRANSFERENCIA (→ LAB_PUBLICO) em lote.
        self.assertIn(b'TRANSFERENCIA', response.content)
