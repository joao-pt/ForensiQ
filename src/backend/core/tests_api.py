"""
ForensiQ — Testes da API REST.

Testa:
- Autenticação JWT em cookies HttpOnly (login, refresh) — ADR-0009
- CRUD de ocorrências (permissões por perfil)
- CRUD de evidências (hash automático, permissões)
- CRUD de dispositivos digitais
- Cadeia de custódia (append-only via API, timeline)
- Permissões: AGENT vs EXPERT vs não autenticado

Nota de taxonomia (ADR-0010): DIGITAL_DEVICE → MOBILE_DEVICE;
DOCUMENT → OTHER_DIGITAL; PHOTO → DIGITAL_FILE.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

# BaseAPITestCase vive em core.tests_base (auditoria D112) — re-importada aqui
# para as suites (e tests_new_features/tests_dashboard) continuarem a funcionar.
from core.tests_base import BaseAPITestCase as BaseAPITestCase, make_image_bytes
from core.tests_factories import LISBOA_GPS, LISBOA_GPS_STR, TEST_PASSWORD, CrimeTipoFactory

from .auth import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from .models import (
    ChainOfCustody,
    Evidence,
    Occurrence,
    User,
)

# ---------------------------------------------------------------------------
# Testes de Autenticação JWT
# ---------------------------------------------------------------------------


class JWTAuthTest(BaseAPITestCase):
    """Testes de autenticação JWT via cookies HttpOnly (ADR-0009)."""

    def test_login_success(self):
        """Login válido devolve 200 e semeia os cookies fq_access / fq_refresh."""
        response = self.get_jwt_token('agente_api', TEST_PASSWORD)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Os tokens não são devolvidos no body — ficam em cookies HttpOnly.
        self.assertIn(ACCESS_COOKIE_NAME, response.cookies)
        self.assertIn(REFRESH_COOKIE_NAME, response.cookies)
        self.assertTrue(response.cookies[ACCESS_COOKIE_NAME]['httponly'])
        self.assertTrue(response.cookies[REFRESH_COOKIE_NAME]['httponly'])
        # O body inclui informação do utilizador autenticado.
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['username'], 'agente_api')

    def test_login_invalid_credentials(self):
        """Login com credenciais inválidas recusa autenticação.

        Aceitamos 401 *ou* 403: com ``authentication_classes=[]`` em
        ``CookieLoginView`` (ADR-0009), a DRF rebaixa
        ``AuthenticationFailed`` para 403 porque não há classe
        autenticadora para emitir ``WWW-Authenticate``. O contrato
        comportamental relevante é que *nenhum cookie de sessão seja
        emitido* e que a resposta seja 4xx de recusa.
        """
        response = self.get_jwt_token('agente_api', 'wrongpassword')
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        # Nenhum token deve ter sido emitido.
        self.assertNotIn(ACCESS_COOKIE_NAME, response.cookies)
        self.assertNotIn(REFRESH_COOKIE_NAME, response.cookies)

    def test_token_refresh(self):
        """Refresh lê o cookie fq_refresh e rotaciona os tokens."""
        login = self.get_jwt_token('agente_api', TEST_PASSWORD)
        self.assertEqual(login.status_code, status.HTTP_200_OK)

        # O APIClient mantém cookies em `self.client.cookies` — o endpoint
        # de refresh lê o `fq_refresh` do cookie automaticamente.
        url = reverse('auth_refresh')
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(ACCESS_COOKIE_NAME, response.cookies)

    def test_unauthenticated_access_denied(self):
        """Acesso sem token retorna 401."""
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Testes de User
# ---------------------------------------------------------------------------


class UserAPITest(BaseAPITestCase):
    """Testes para o endpoint /api/users/."""

    def test_list_users_authenticated(self):
        """Utilizador autenticado pode listar utilizadores."""
        self.authenticate_as(self.agent)
        url = reverse('core:user-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_me_endpoint(self):
        """Endpoint /api/users/me/ retorna perfil do utilizador autenticado."""
        self.authenticate_as(self.agent)
        url = reverse('core:user-me')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'agente_api')
        self.assertEqual(response.data['profile'], 'FIRST_RESPONDER')

    def test_create_user_requires_admin(self):
        """Apenas administradores podem criar utilizadores."""
        self.authenticate_as(self.agent)
        url = reverse('core:user-list')
        response = self.client.post(
            url,
            {
                'username': 'novo_agente',
                'password': 'NovoPass123!',
                'profile': 'FIRST_RESPONDER',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_user(self):
        """Administrador pode criar utilizadores."""
        self.authenticate_as(self.admin)
        url = reverse('core:user-list')
        response = self.client.post(
            url,
            {
                'username': 'novo_agente',
                'password': 'NovoPass123!',
                'profile': 'FIRST_RESPONDER',
                'badge_number': 'AGT-NEW-01',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['username'], 'novo_agente')


# ---------------------------------------------------------------------------
# Testes de Occurrence
# ---------------------------------------------------------------------------


class OccurrenceAPITest(BaseAPITestCase):
    """Testes para o endpoint /api/occurrences/."""

    def test_agent_creates_occurrence(self):
        """AGENT pode criar ocorrências."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-API-001',
                'description': 'Teste de ocorrência via API.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['number'], 'NUIPC-2026-API-001')
        # Agent preenchido automaticamente
        self.assertEqual(response.data['agent'], self.agent.id)

    def test_expert_cannot_create_occurrence(self):
        """EXPERT não pode criar ocorrências."""
        self.authenticate_as(self.expert)
        url = reverse('core:occurrence-list')
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-API-002',
                'description': 'Tentativa de perito.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_expert_can_list_occurrences(self):
        """EXPERT pode consultar ocorrências."""
        self.authenticate_as(self.expert)
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_occurrence_detail(self):
        """Detalhe de uma ocorrência específica."""
        self.authenticate_as(self.agent)
        occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-DET',
            description='Ocorrência para detalhe.',
            agent=self.agent,
        )
        url = reverse('core:occurrence-detail', kwargs={'pk': occ.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['number'], 'NUIPC-2026-DET')


# ---------------------------------------------------------------------------
# Testes de Evidence
# ---------------------------------------------------------------------------


class EvidenceAPITest(BaseAPITestCase):
    """Testes para o endpoint /api/evidences/."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-EV',
            description='Ocorrência para evidências.',
            agent=self.agent,
        )

    def test_agent_creates_evidence(self):
        """AGENT pode criar evidências com hash automático."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')
        response = self.client.post(
            url,
            {
                'occurrence': self.occurrence.pk,
                'type': 'MOBILE_DEVICE',
                'description': 'Smartphone encontrado no local.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Hash SHA-256 calculado automaticamente
        self.assertEqual(len(response.data['integrity_hash']), 64)

    def test_filter_by_occurrence(self):
        """Filtrar evidências por ocorrência."""
        Evidence.objects.create(
            occurrence=self.occurrence,
            type='OTHER_DIGITAL',
            description='Documento de teste.',
            agent=self.agent,
        )
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')
        response = self.client.get(url, {'occurrence': self.occurrence.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)


# ---------------------------------------------------------------------------
# Testes de ChainOfCustody
# ---------------------------------------------------------------------------


class ChainOfCustodyAPITest(BaseAPITestCase):
    """Testes para o endpoint /api/custody/."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-COC',
            description='Ocorrência para custódia.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Smartphone para custódia.',
            agent=self.agent,
        )

    def test_agent_creates_first_custody_record(self):
        """AGENT pode criar o primeiro evento (APREENSAO_OBJETO)."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-list')
        response = self.client.post(
            url,
            {
                'evidence': self.evidence.pk,
                'event_type': 'APREENSAO_OBJETO',
                'custodian_type': 'OPC',
                'observations': 'Apreensão no local do crime.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['record_hash']), 64)
        self.assertEqual(response.data['legal_state'], 'a_guarda_opc')

    def test_expert_can_advance_custody(self):
        """EXPERT pode registar eventos seguintes (ex.: início de perícia)."""
        # Sequência prévia pelo agente.
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.DESPACHO_PERICIA,
            agent=self.agent,
        ).save()

        # Perito inicia a perícia no laboratório.
        self.authenticate_as(self.expert)
        url = reverse('core:custody-list')
        response = self.client.post(
            url,
            {
                'evidence': self.evidence.pk,
                'event_type': 'INICIO_PERICIA',
                'custodian_type': 'LAB_PUBLICO',
                'observations': 'Início da perícia forense.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_put_not_allowed(self):
        """PUT não é permitido (append-only)."""
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
            agent=self.agent,
        ).save()

        record = ChainOfCustody.objects.first()
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': record.pk})
        response = self.client.put(
            url,
            {
                'evidence': self.evidence.pk,
                'event_type': 'APREENSAO_OBJETO',
                'observations': 'Alteração bloqueada.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed(self):
        """DELETE não é permitido (append-only)."""
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
            agent=self.agent,
        ).save()

        record = ChainOfCustody.objects.first()
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': record.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_invalid_first_event_returns_400(self):
        """Primeiro evento ≠ APREENSAO_OBJETO é rejeitado pela guarda do ledger (400)."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-list')
        response = self.client.post(
            url,
            {
                'evidence': self.evidence.pk,
                'event_type': 'VALIDACAO_APREENSAO',  # Inválido — 1.º evento tem de ser APREENSAO_OBJETO
                'observations': 'Evento inválido.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validacao_sem_identificacao_da_autoridade_e_rejeitada(self):
        """VALIDACAO_APREENSAO 'nua' (sem observations) → 400: o ato exige a
        identificação de quem validou — o caminho único vale também na API
        (a UI constrói o texto certificado a partir dos campos do modal)."""
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()
        self.authenticate_as(self.agent)
        response = self.client.post(
            reverse('core:custody-list'),
            {'evidence': self.evidence.pk, 'event_type': 'VALIDACAO_APREENSAO'},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('observations', response.data)

    def test_validation_status_exposto_na_api_de_evidencias(self):
        """O eixo de validação é visível aos consumidores da API (PWA):
        campo read-only derivado, nunca gravado."""
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-detail', kwargs={'pk': self.evidence.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['validation_status'], 'por_validar')

    def test_timeline_endpoint(self):
        """Endpoint timeline retorna histórico ordenado."""
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.APREENSAO_OBJETO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()
        ChainOfCustody(
            evidence=self.evidence,
            event_type=ChainOfCustody.EventType.VALIDACAO_APREENSAO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()

        self.authenticate_as(self.agent)
        url = reverse('core:custody-timeline', kwargs={'evidence_id': self.evidence.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        # Ordenação canónica por sequence.
        self.assertEqual(response.data[0]['event_type'], 'APREENSAO_OBJETO')
        self.assertEqual(response.data[1]['event_type'], 'VALIDACAO_APREENSAO')


# ---------------------------------------------------------------------------
# Testes de Autorização — IDOR (Insecure Direct Object Reference)
# ---------------------------------------------------------------------------


class AuthorizationIDORTest(BaseAPITestCase):
    """
    Testa isolamento de dados entre agentes.
    Verifica que Agent A não consegue aceder a ocorrências/evidências de Agent B.
    """

    def setUp(self):
        super().setUp()
        # Criar um segundo agente
        self.agent_b = User.objects.create_user(
            username='agente_b_api',
            password=TEST_PASSWORD,
            profile=User.Profile.FIRST_RESPONDER,
            badge_number='AGT-API-02',
            first_name='Bruno',
            last_name='Santos',
        )

        # Ocorrência e evidência do Agent A
        self.occurrence_a = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-IDOR-A',
            description='Ocorrência do Agent A.',
            agent=self.agent,
        )
        self.evidence_a = Evidence.objects.create(
            occurrence=self.occurrence_a,
            type='MOBILE_DEVICE',
            description='Evidência do Agent A.',
            agent=self.agent,
        )

        # Ocorrência e evidência do Agent B
        self.occurrence_b = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-IDOR-B',
            description='Ocorrência do Agent B.',
            agent=self.agent_b,
        )
        self.evidence_b = Evidence.objects.create(
            occurrence=self.occurrence_b,
            type='MOBILE_DEVICE',
            description='Evidência do Agent B.',
            agent=self.agent_b,
        )

    def test_agent_a_cannot_see_agent_b_occurrences(self):
        """Agent A não consegue ver ocorrências de Agent B na listagem."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verificar que Agent A só vê as suas próprias ocorrências
        occurrence_ids = [occ['id'] for occ in response.data.get('results', [])]
        self.assertIn(self.occurrence_a.id, occurrence_ids)
        self.assertNotIn(self.occurrence_b.id, occurrence_ids)

    def test_agent_a_cannot_access_agent_b_occurrence_detail(self):
        """Agent A não consegue aceder ao detalhe de ocorrência de Agent B."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-detail', kwargs={'pk': self.occurrence_b.pk})
        response = self.client.get(url)
        # Deve retornar 404 (não encontrado) ou 403 (proibido)
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

    def test_agent_a_cannot_see_agent_b_evidences(self):
        """Agent A não consegue ver evidências de Agent B na listagem."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verificar que Agent A só vê as suas próprias evidências
        evidence_ids = [ev['id'] for ev in response.data.get('results', [])]
        self.assertIn(self.evidence_a.id, evidence_ids)
        self.assertNotIn(self.evidence_b.id, evidence_ids)

    def test_agent_a_cannot_access_agent_b_evidence_detail(self):
        """Agent A não consegue aceder ao detalhe de evidência de Agent B."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-detail', kwargs={'pk': self.evidence_b.pk})
        response = self.client.get(url)
        # Deve retornar 404 ou 403
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

    def test_agent_a_cannot_filter_agent_b_evidence_by_occurrence(self):
        """Agent A não consegue filtrar evidências de ocorrência de Agent B."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')
        response = self.client.get(url, {'occurrence': self.occurrence_b.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Não deve retornar evidências da ocorrência de Agent B
        results = response.data.get('results', [])
        self.assertEqual(len(results), 0)

    def test_expert_can_see_all_occurrences(self):
        """EXPERT consegue ver ocorrências de todos os agentes."""
        self.authenticate_as(self.expert)
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Expert deve ver ambas as ocorrências
        occurrence_ids = [occ['id'] for occ in response.data.get('results', [])]
        self.assertIn(self.occurrence_a.id, occurrence_ids)
        self.assertIn(self.occurrence_b.id, occurrence_ids)

    def test_expert_can_see_all_evidences(self):
        """EXPERT consegue ver evidências de todos os agentes."""
        self.authenticate_as(self.expert)
        url = reverse('core:evidence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Expert deve ver ambas as evidências
        evidence_ids = [ev['id'] for ev in response.data.get('results', [])]
        self.assertIn(self.evidence_a.id, evidence_ids)
        self.assertIn(self.evidence_b.id, evidence_ids)


# ---------------------------------------------------------------------------
# Testes de Imutabilidade — Evidence (API)
# ---------------------------------------------------------------------------


class EvidenceImmutabilityAPITest(BaseAPITestCase):
    """
    Testa que evidências são imutáveis via API.
    PUT, PATCH e DELETE devem retornar 405 Method Not Allowed.
    """

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-IMMUT-EV',
            description='Ocorrência para teste de imutabilidade.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Evidência original.',
            agent=self.agent,
        )

    def test_evidence_put_returns_405(self):
        """PUT na evidência retorna 405 Method Not Allowed."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-detail', kwargs={'pk': self.evidence.pk})
        response = self.client.put(
            url,
            {
                'occurrence': self.occurrence.pk,
                'type': 'OTHER_DIGITAL',
                'description': 'Descrição alterada.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_evidence_patch_returns_405(self):
        """PATCH na evidência retorna 405 Method Not Allowed."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-detail', kwargs={'pk': self.evidence.pk})
        response = self.client.patch(
            url,
            {
                'description': 'Descrição alterada.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_evidence_delete_returns_405(self):
        """DELETE na evidência retorna 405 Method Not Allowed."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-detail', kwargs={'pk': self.evidence.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_evidence_data_unchanged_after_attempted_put(self):
        """Dados da evidência permanecem inalterados após tentativa de PUT."""
        original_description = self.evidence.description
        original_type = self.evidence.type

        self.authenticate_as(self.agent)
        url = reverse('core:evidence-detail', kwargs={'pk': self.evidence.pk})
        self.client.put(
            url,
            {
                'occurrence': self.occurrence.pk,
                'type': 'OTHER_DIGITAL',
                'description': 'Nova descrição.',
            },
        )

        # Recarregar evidência da BD
        self.evidence.refresh_from_db()
        self.assertEqual(self.evidence.description, original_description)
        self.assertEqual(self.evidence.type, original_type)

    def test_evidence_cannot_be_deleted_by_admin(self):
        """Mesmo administrador não consegue deletar evidência."""
        self.authenticate_as(self.admin)
        url = reverse('core:evidence-detail', kwargs={'pk': self.evidence.pk})
        response = self.client.delete(url)
        # Deve retornar 405 (imutável via API)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Verificar que evidência ainda existe na BD
        self.assertTrue(Evidence.objects.filter(pk=self.evidence.pk).exists())


# ---------------------------------------------------------------------------
# Testes End-to-End
# ---------------------------------------------------------------------------


class EndToEndFlowTest(BaseAPITestCase):
    """
    Teste end-to-end: fluxo completo desde a criação de ocorrência
    até à exportação do relatório PDF.
    Simula o ciclo operacional real de um first responder.
    """

    def test_full_operational_flow(self):
        """
        Fluxo completo operacional (ledger de eventos, ADR-0015):
        1. Autenticação como agente
        2. Criar ocorrência com coordenadas GPS
        3. Criar evidência ligada à ocorrência
        4. Registar evento APREENSAO_OBJETO (agente)
        5. Registar evento VALIDACAO_APREENSAO (agente)
        6. Trocar para utilizador perito
        7. Registar evento DESPACHO_PERICIA → INICIO_PERICIA (perito)
        8. Exportar PDF da evidência
        9. Verificar resposta PDF (status 200, tipo, header %PDF)
        10. Consultar timeline de custódia (4 registos em ordem)
        11. Verificar integridade: todos os hashes são 64 caracteres hex
        """
        # --- STEP 1: Autenticação como agente ---
        self.authenticate_as(self.agent)

        # --- STEP 2: Criar ocorrência com GPS ---
        occurrence_url = reverse('core:occurrence-list')
        occurrence_response = self.client.post(
            occurrence_url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-E2E-001',
                'description': 'Ocorrência end-to-end: roubo com dispositivo digital.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(occurrence_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(occurrence_response.data['number'], 'NUIPC-2026-E2E-001')
        occurrence_id = occurrence_response.data['id']

        # --- STEP 3: Criar evidência ---
        evidence_url = reverse('core:evidence-list')
        evidence_response = self.client.post(
            evidence_url,
            {
                'occurrence': occurrence_id,
                'type': 'MOBILE_DEVICE',
                'description': 'iPhone 13 Pro encontrado no local do crime.',
            },
        )
        self.assertEqual(evidence_response.status_code, status.HTTP_201_CREATED)
        evidence_id = evidence_response.data['id']
        # Verificar hash de integridade
        self.assertEqual(len(evidence_response.data['integrity_hash']), 64)
        self.assertRegex(evidence_response.data['integrity_hash'], r'^[a-f0-9]{64}$')

        # --- STEP 4: Registar evento APREENSAO_OBJETO ---
        custody_url = reverse('core:custody-list')
        custody_response_1 = self.client.post(
            custody_url,
            {
                'evidence': evidence_id,
                'event_type': 'APREENSAO_OBJETO',
                'custodian_type': 'OPC',
                'observations': 'Apreensão no local do crime. Dispositivo selado.',
            },
        )
        self.assertEqual(custody_response_1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(custody_response_1.data['event_type'], 'APREENSAO_OBJETO')
        # Verificar hash do registo
        self.assertEqual(len(custody_response_1.data['record_hash']), 64)
        self.assertRegex(custody_response_1.data['record_hash'], r'^[a-f0-9]{64}$')

        # --- STEP 5: Registar evento VALIDACAO_APREENSAO ---
        custody_response_2 = self.client.post(
            custody_url,
            {
                'evidence': evidence_id,
                'event_type': 'VALIDACAO_APREENSAO',
                'custodian_type': 'OPC',
                'observations': 'Apreensão validada pela autoridade judiciária.',
            },
        )
        self.assertEqual(custody_response_2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(custody_response_2.data['event_type'], 'VALIDACAO_APREENSAO')
        self.assertEqual(len(custody_response_2.data['record_hash']), 64)

        # --- STEP 6: Trocar para utilizador perito ---
        self.authenticate_as(self.expert)

        # --- STEP 7a: Despacho para perícia (pré-requisito de INICIO_PERICIA) ---
        custody_response_3a = self.client.post(
            custody_url,
            {
                'evidence': evidence_id,
                'event_type': 'DESPACHO_PERICIA',
                'observations': 'Despacho que ordena a perícia (Art. 154.º).',
            },
        )
        self.assertEqual(custody_response_3a.status_code, status.HTTP_201_CREATED)

        # --- STEP 7b: Início da perícia no laboratório ---
        custody_response_3 = self.client.post(
            custody_url,
            {
                'evidence': evidence_id,
                'event_type': 'INICIO_PERICIA',
                'custodian_type': 'LAB_PUBLICO',
                'observations': 'Início da análise forense.',
            },
        )
        self.assertEqual(custody_response_3.status_code, status.HTTP_201_CREATED)
        self.assertEqual(custody_response_3.data['event_type'], 'INICIO_PERICIA')
        self.assertEqual(custody_response_3.data['legal_state'], 'em_pericia')
        self.assertEqual(len(custody_response_3.data['record_hash']), 64)

        # --- STEP 8-9: Exportar PDF da evidência e verificar ---
        pdf_url = reverse('core:evidence-export-pdf', kwargs={'pk': evidence_id})
        pdf_response = self.client.get(pdf_url)
        self.assertEqual(pdf_response.status_code, status.HTTP_200_OK)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        # PDF deve começar com %PDF
        self.assertTrue(pdf_response.content.startswith(b'%PDF'))

        # --- STEP 10: Consultar timeline de custódia ---
        timeline_url = reverse('core:custody-list') + f'?evidence={evidence_id}'
        timeline_response = self.client.get(timeline_url)
        self.assertEqual(timeline_response.status_code, status.HTTP_200_OK)
        # Deve haver 4 registos
        self.assertEqual(len(timeline_response.data['results']), 4)
        # Verificar ordem: APREENSAO_OBJETO, VALIDACAO_APREENSAO, DESPACHO_PERICIA, INICIO_PERICIA
        self.assertEqual(timeline_response.data['results'][0]['event_type'], 'APREENSAO_OBJETO')
        self.assertEqual(timeline_response.data['results'][1]['event_type'], 'VALIDACAO_APREENSAO')
        self.assertEqual(timeline_response.data['results'][2]['event_type'], 'DESPACHO_PERICIA')
        self.assertEqual(timeline_response.data['results'][3]['event_type'], 'INICIO_PERICIA')

        # --- STEP 11: Verificar integridade de todos os hashes ---
        for record in timeline_response.data['results']:
            # Todos os hashes devem ser 64 caracteres hexadecimais
            self.assertEqual(len(record['record_hash']), 64)
            self.assertRegex(record['record_hash'], r'^[a-f0-9]{64}$')


# ---------------------------------------------------------------------------
# Testes de Validação de Entrada (Input Validation)
# ---------------------------------------------------------------------------


class InputValidationTest(BaseAPITestCase):
    """
    Testa validação de entrada para campos GPS, números duplicados,
    strings muito longas, Unicode e injeção HTML.
    """

    def test_gps_latitude_above_90_rejected(self):
        """GPS latitude acima de 90 deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LAT-HIGH',
                'description': 'Teste de latitude inválida.',
                'gps_lat': '200.0000000',  # Fora do intervalo [-90, 90]
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_gps_latitude_below_minus_90_rejected(self):
        """GPS latitude abaixo de -90 deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LAT-LOW',
                'description': 'Teste de latitude inválida.',
                'gps_lat': '-150.0000000',  # Fora do intervalo [-90, 90]
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_gps_longitude_above_180_rejected(self):
        """GPS longitude acima de 180 deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LON-HIGH',
                'description': 'Teste de longitude inválida.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': '200.0000000',  # Fora do intervalo [-180, 180]
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_gps_longitude_below_minus_180_rejected(self):
        """GPS longitude abaixo de -180 deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LON-LOW',
                'description': 'Teste de longitude inválida.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': '-200.0000000',  # Fora do intervalo [-180, 180]
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_gps_valid_boundaries_accepted(self):
        """GPS nos limites válidos (90, -90, 180, -180) deve ser aceito."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        # Teste com latitudes nos limites
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LIMIT-1',
                'description': 'Latitude em +90.',
                'gps_lat': '90.0000000',
                'gps_lng': '0.0000000',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LIMIT-2',
                'description': 'Latitude em -90.',
                'gps_lat': '-90.0000000',
                'gps_lng': '0.0000000',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LIMIT-3',
                'description': 'Longitude em +180.',
                'gps_lat': '0.0000000',
                'gps_lng': '180.0000000',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-LIMIT-4',
                'description': 'Longitude em -180.',
                'gps_lat': '0.0000000',
                'gps_lng': '-180.0000000',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_duplicate_occurrence_number_rejected(self):
        """Número de ocorrência duplicado deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        # Criar primeira ocorrência
        response1 = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-DUP-001',
                'description': 'Primeira ocorrência.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        # Tentar criar segunda com mesmo número
        response2 = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-DUP-001',  # Número duplicado
                'description': 'Segunda ocorrência com número duplicado.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_very_long_description_accepted(self):
        """Descrição com 100.000 caracteres deve ser aceita."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        # Criar string com 100.000 caracteres
        long_description = 'A' * 100000

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-LONG-DESC',
                'description': long_description,
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verificar que a descrição foi armazenada corretamente
        occ = Occurrence.objects.get(number='NUIPC-2026-LONG-DESC')
        self.assertEqual(len(occ.description), 100000)

    def test_unicode_description_accepted(self):
        """Descrição com caracteres Unicode deve ser aceita."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        unicode_description = (
            'Ocorrência com caracteres especiais: '
            'português (ç, ã, õ), '
            'grego (α, β, γ), '
            'árabe (العربية), '
            'chinês (中文), '
            'emoji (😀🎉🚀)'
        )

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-UNICODE',
                'description': unicode_description,
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verificar que a descrição foi armazenada corretamente
        occ = Occurrence.objects.get(number='NUIPC-2026-UNICODE')
        self.assertIn('português', occ.description)
        self.assertIn('العربية', occ.description)
        self.assertIn('中文', occ.description)

    def test_html_injection_in_description_stored_safely(self):
        """HTML/script injection em descrição deve ser armazenado de forma segura."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        injection_payload = (
            '<script>alert("XSS")</script>'
            '<img src=x onerror="alert(\'XSS\')">'
            '<svg onload="alert(\'XSS\')">'
            '<?php echo "dangerous"; ?>'
        )

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-XSS-TEST',
                'description': injection_payload,
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        # Deve ser aceito (não rejeitar injeção, apenas escapar na saída)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verificar que foi armazenado
        occ = Occurrence.objects.get(number='NUIPC-2026-XSS-TEST')
        self.assertEqual(occ.description, injection_payload)

    def test_null_byte_in_description(self):
        """Strings com null bytes devem ser rejeitadas ou tratadas com segurança."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        # Null byte pode causar problemas de segurança
        description_with_null = 'Normal description\x00dangerous data'

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-NULL-BYTE',
                'description': description_with_null,
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        # Deve ser rejeitado ou o null byte deve ser removido
        # Se aceito, verificar que foi tratado corretamente
        if response.status_code == status.HTTP_201_CREATED:
            occ = Occurrence.objects.get(number='NUIPC-2026-NULL-BYTE')
            # Null byte não deve estar presente
            self.assertNotIn('\x00', occ.description)

    def test_very_long_occurrence_number_rejected(self):
        """Número de ocorrência que excede max_length deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        # Campo number tem max_length=50
        long_number = 'NUIPC-' + 'A' * 100

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': long_number,
                'description': 'Ocorrência com número muito longo.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_number_field_rejected(self):
        """Campo number vazio deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': '',
                'description': 'Ocorrência sem número.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_required_field_rejected(self):
        """Campo obrigatório ausente deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        # number é obrigatório
        response = self.client.post(
            url,
            {
                'description': 'Ocorrência sem número.',
                'gps_lat': LISBOA_GPS_STR[0],
                'gps_lng': LISBOA_GPS_STR[1],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_partial_gps_coordinates_rejected(self):
        """GPS parcial é rejeitado — latitude e longitude têm de ser
        ambas preenchidas ou ambas vazias (ver ``Occurrence.clean()``).
        Uma coordenada sozinha é inútil em campo e sinaliza dados corrompidos.
        """
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')

        # Apenas latitude (longitude omissa) → ValidationError no clean()
        response = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-PARTIAL-1',
                'description': 'Ocorrência com apenas latitude.',
                'gps_lat': LISBOA_GPS_STR[0],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Ambos omissos → aceite (GPS é opcional)
        response_both = self.client.post(
            url,
            {
                'crime_type': CrimeTipoFactory().id,
                'number': 'NUIPC-2026-GPS-NONE-1',
                'description': 'Ocorrência sem GPS.',
            },
        )
        self.assertEqual(response_both.status_code, status.HTTP_201_CREATED)


class ImageUploadValidationTest(BaseAPITestCase):
    """
    Testa validação de uploads de imagens (tamanho máximo, tipo de ficheiro).
    """

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-IMG',
            description='Ocorrência para testes de imagem.',
            agent=self.agent,
        )

    def _make_valid_jpeg(self, size_bytes):
        """JPEG mínimo padded — gerador único (tests_base.make_image_bytes, D113)."""
        return make_image_bytes(size=(1, 1), pad_to=size_bytes)

    def test_image_upload_valid_size(self):
        """Upload de imagem com tamanho válido (< 25MB) deve ser aceito.

        Regressão corrigida na Wave 4b: ``Evidence._compute_photo_hash()``
        deixa de fechar o stream antes do ``ImageField.pre_save`` chamar
        ``seek(0)``; o hash é computado via ``chunks()`` e o cursor é
        reposto. Garante que o upload de fotografia não rebenta com
        ``ValueError: I/O operation on closed file``.
        """
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')

        image_content = self._make_valid_jpeg(1024)  # 1KB JPEG válido
        image_file = SimpleUploadedFile(
            name='test_image_valid.jpg', content=image_content, content_type='image/jpeg'
        )

        response = self.client.post(
            url,
            {
                'occurrence': self.occurrence.pk,
                'type': 'MOBILE_DEVICE',
                'description': 'Evidência com imagem.',
                'photo': image_file,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_image_upload_too_large_rejected(self):
        """Upload de imagem > 25MB deve ser rejeitado pelo validador."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')

        image_content = self._make_valid_jpeg(26 * 1024 * 1024)  # 26MB
        image_file = SimpleUploadedFile(
            name='test_image_large.jpg', content=image_content, content_type='image/jpeg'
        )

        response = self.client.post(
            url,
            {
                'occurrence': self.occurrence.pk,
                'type': 'MOBILE_DEVICE',
                'description': 'Evidência com imagem muito grande.',
                'photo': image_file,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_image_limit_read_from_settings(self):
        """O limite vem de ``settings.MAX_IMAGE_UPLOAD_BYTES`` (não hard-coded):
        baixando-o, um ficheiro normalmente aceite passa a ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')

        image_content = self._make_valid_jpeg(4 * 1024)  # 4 KB — OK no default 25 MB
        image_file = SimpleUploadedFile(
            name='test_image_over_override.jpg', content=image_content, content_type='image/jpeg'
        )
        with self.settings(MAX_IMAGE_UPLOAD_BYTES=2 * 1024):  # 2 KB
            response = self.client.post(
                url,
                {
                    'occurrence': self.occurrence.pk,
                    'type': 'MOBILE_DEVICE',
                    'description': 'Evidência acima do limite reduzido.',
                    'photo': image_file,
                },
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_file_type_rejected(self):
        """Upload de ficheiro não-imagem deve ser rejeitado pelo ImageField."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')

        invalid_file = SimpleUploadedFile(
            name='not_an_image.txt',
            content=b'This is plain text, not an image.',
            content_type='text/plain',
        )

        response = self.client.post(
            url,
            {
                'occurrence': self.occurrence.pk,
                'type': 'MOBILE_DEVICE',
                'description': 'Evidência com ficheiro de texto.',
                'photo': invalid_file,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_file_upload_rejected(self):
        """Upload de ficheiro vazio deve ser rejeitado."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')

        empty_file = SimpleUploadedFile(
            name='empty_file.jpg', content=b'', content_type='image/jpeg'
        )

        response = self.client.post(
            url,
            {
                'occurrence': self.occurrence.pk,
                'type': 'MOBILE_DEVICE',
                'description': 'Evidência com ficheiro vazio.',
                'photo': empty_file,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Testes de Segurança — Token JWT tampered/expirado
# ---------------------------------------------------------------------------


class JWTSecurityTest(BaseAPITestCase):
    """
    Testa que tokens JWT tampered ou inválidos são rejeitados.

    Conformidade: OWASP — validação de integridade de tokens.
    """

    def test_tampered_token_rejected(self):
        """Token JWT alterado em cookie deve ser rejeitado com 401.

        Com ADR-0009 o access token vive num cookie HttpOnly. Simulamos
        tampering injectando um cookie inválido directamente no cliente
        — `JWTCookieAuthentication.authenticate()` rejeita com 401.
        """
        # Obter token válido via login (devolvido em cookie).
        login_url = reverse('auth_login')
        login_response = self.client.post(
            login_url,
            {
                'username': 'agente_api',
                'password': TEST_PASSWORD,
            },
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        valid_token = login_response.cookies[ACCESS_COOKIE_NAME].value
        # Corromper um carácter NÃO-terminal do payload (header.payload.signature).
        # Alterar só o último carácter da assinatura é não-fiável: os bits de
        # padding base64url do carácter terminal podem alias para os mesmos bytes
        # de assinatura, deixando o token válido (falso 200). Mutar um carácter
        # interior do payload altera sempre os bytes descodificados → a assinatura
        # deixa de bater certo → 401 determinístico.
        head, payload, sig = valid_token.split('.')
        i = 5  # posição interior, fora dos bits de padding
        payload = payload[:i] + ('A' if payload[i] != 'A' else 'B') + payload[i + 1 :]
        tampered = '.'.join([head, payload, sig])
        # Substituir o cookie mantido pelo APIClient
        self.client.cookies[ACCESS_COOKIE_NAME] = tampered

        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_token_rejected(self):
        """Token vazio deve ser rejeitado com 401."""
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ')
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_malformed_authorization_header_rejected(self):
        """Header de autorização mal formado deve ser rejeitado."""
        self.client.credentials(HTTP_AUTHORIZATION='InvalidScheme abc123')
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_random_string_token_rejected(self):
        """String aleatória como token deve ser rejeitada."""
        self.client.credentials(HTTP_AUTHORIZATION='Bearer eyJhbGciOiJIUzI1NiJ9.fake.payload')
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Testes de Segurança — CSP Header
# ---------------------------------------------------------------------------


class CSPHeaderTest(BaseAPITestCase):
    """
    Testa que o middleware CSP adiciona o header Content-Security-Policy.

    Conformidade: OWASP — mitigação de XSS via CSP.
    """

    def test_csp_header_present_on_api_response(self):
        """Respostas da API devem incluir CSP header."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        # Em test (DEBUG=True), deve ser Report-Only
        has_csp = (
            'Content-Security-Policy' in response
            or 'Content-Security-Policy-Report-Only' in response
        )
        self.assertTrue(has_csp, 'Response deve incluir CSP header')

    def test_csp_header_contains_default_src(self):
        """CSP header deve conter directiva default-src."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        csp = response.get('Content-Security-Policy-Report-Only', '') or response.get(
            'Content-Security-Policy', ''
        )
        self.assertIn("default-src 'self'", csp)

    def test_csp_header_contains_frame_ancestors(self):
        """CSP header deve conter frame-ancestors 'none' (anti-clickjacking)."""
        self.authenticate_as(self.agent)
        url = reverse('core:occurrence-list')
        response = self.client.get(url)
        csp = response.get('Content-Security-Policy-Report-Only', '') or response.get(
            'Content-Security-Policy', ''
        )
        self.assertIn("frame-ancestors 'none'", csp)


# ---------------------------------------------------------------------------
# Testes de Segurança — Rate Limiting nos endpoints de auth
# ---------------------------------------------------------------------------


class AuthRateLimitingTest(TestCase):
    """
    Testa que os endpoints de autenticação JWT têm rate limiting aplicado.

    Verifica a configuração estrutural (classe de throttle aplicada).
    Após ADR-0009 os endpoints ``token_obtain_pair`` / ``token_refresh``
    foram substituídos por ``CookieLoginView`` / ``CookieRefreshView`` em
    ``core.auth_views``. O rate limit mantém-se via ``AuthRateThrottle``.
    """

    def test_auth_login_view_has_throttle_class(self):
        """Verifica que a CookieLoginView usa AuthRateThrottle."""
        from core.auth_views import CookieLoginView
        from core.throttles import AuthRateThrottle

        view = CookieLoginView()
        throttle_classes = [type(t) for t in view.get_throttles()]
        self.assertIn(AuthRateThrottle, throttle_classes)

    def test_auth_refresh_view_has_throttle_class(self):
        """Verifica que a CookieRefreshView usa AuthRateThrottle."""
        from core.auth_views import CookieRefreshView
        from core.throttles import AuthRateThrottle

        view = CookieRefreshView()
        throttle_classes = [type(t) for t in view.get_throttles()]
        self.assertIn(AuthRateThrottle, throttle_classes)


# ---------------------------------------------------------------------------
# Testes de Imutabilidade — ChainOfCustody via API
# ---------------------------------------------------------------------------


class CustodyImmutabilityAPITest(BaseAPITestCase):
    """
    Testa que registos de cadeia de custódia são imutáveis via API.
    PUT, PATCH e DELETE devem retornar 405 Method Not Allowed.
    """

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-2026-IMMUT-COC',
            description='Ocorrência para teste de imutabilidade CoC.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Evidência para teste de imutabilidade CoC.',
            agent=self.agent,
        )
        # Criar primeiro evento do ledger
        self.custody = ChainOfCustody.objects.create(
            evidence=self.evidence,
            event_type='APREENSAO_OBJETO',
            custodian_type='OPC',
            agent=self.agent,
        )

    def test_custody_put_returns_405(self):
        """PUT num registo de custódia deve retornar 405."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': self.custody.pk})
        response = self.client.put(
            url,
            {
                'evidence': self.evidence.pk,
                'event_type': 'VALIDACAO_APREENSAO',
                'observations': 'Tentativa de PUT.',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_custody_patch_returns_405(self):
        """PATCH num registo de custódia deve retornar 405."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': self.custody.pk})
        response = self.client.patch(url, {'observations': 'Alteração.'})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_custody_delete_returns_405(self):
        """DELETE num registo de custódia deve retornar 405."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': self.custody.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_custody_data_unchanged_after_put_attempt(self):
        """Dados de custódia permanecem inalterados após tentativa de PUT."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': self.custody.pk})
        self.client.put(
            url,
            {
                'evidence': self.evidence.pk,
                'event_type': 'VALIDACAO_APREENSAO',
                'observations': 'Adulteração.',
            },
        )
        self.custody.refresh_from_db()
        self.assertEqual(self.custody.event_type, 'APREENSAO_OBJETO')
        self.assertNotEqual(self.custody.observations, 'Adulteração.')

    def test_custody_hash_integrity_preserved(self):
        """Hash do registo de custódia não pode ser alterado via API."""
        self.authenticate_as(self.agent)
        original_hash = self.custody.record_hash
        url = reverse('core:custody-detail', kwargs={'pk': self.custody.pk})
        self.client.patch(url, {'record_hash': 'a' * 64})
        self.custody.refresh_from_db()
        self.assertEqual(self.custody.record_hash, original_hash)


# ---------------------------------------------------------------------------
# Fluxo CSRF por cookie (ADR-0009)
# ---------------------------------------------------------------------------


class CsrfCookieFlowTest(TestCase):
    """Prova a fronteira CSRF da autenticação por cookie (``enforce_csrf``).

    A esmagadora maioria dos testes de escrita usa ``force_authenticate``,
    que faz *bypass* de ``JWTCookieAuthentication`` e, com ele, do
    ``enforce_csrf()``. Mesmo os testes que fazem login real por cookie usam
    o ``APIClient`` por omissão (``enforce_csrf_checks=False``), que marca
    ``request._dont_enforce_csrf_checks = True`` — tornando o ``enforce_csrf()``
    um *no-op*. Esta classe usa explicitamente
    ``APIClient(enforce_csrf_checks=True)`` para exercitar o gate a sério: um
    POST autenticado por cookie **sem** token CSRF tem de ser recusado (403),
    e **com** token tem de passar o gate (nunca 403 por CSRF).
    """

    def setUp(self):
        # Cliente que FAZ enforce de CSRF — oposto do APIClient por omissão.
        self.client = APIClient(enforce_csrf_checks=True)
        self.agent = User.objects.create_user(
            username='ag_csrf',
            password=TEST_PASSWORD,
            profile=User.Profile.FIRST_RESPONDER,
            badge_number='AGT-CSRF-01',
        )
        self.occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='NUIPC-CSRF-001',
            description='Ocorrência para teste CSRF.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='Item para teste CSRF.',
            agent=self.agent,
        )

    def _login(self):
        """Login real por cookie: semeia fq_access/fq_refresh + csrftoken.

        Devolve o valor do cookie ``csrftoken`` (a enviar no header
        ``X-CSRFToken``). ``CookieLoginView`` é uma view DRF (csrf_exempt ao
        nível do middleware do Django) decorada com ``ensure_csrf_cookie``,
        pelo que o próprio login passa sem token e devolve o cookie CSRF.
        """
        resp = self.client.post(
            reverse('auth_login'),
            {'username': 'ag_csrf', 'password': TEST_PASSWORD},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('csrftoken', self.client.cookies)
        return self.client.cookies['csrftoken'].value

    def _custody_payload(self):
        return {
            'evidence': self.evidence.pk,
            'event_type': 'APREENSAO_OBJETO',
            'custodian_type': 'OPC',
            'observations': 'Apreensão no local (teste CSRF).',
        }

    def test_write_sem_csrf_token_recusado_403(self):
        """POST autenticado por cookie SEM header X-CSRFToken → 403 CSRF."""
        self._login()
        resp = self.client.post(reverse('core:custody-list'), self._custody_payload())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('CSRF', str(resp.data))

    def test_write_com_csrf_token_passa_o_gate(self):
        """POST autenticado por cookie COM X-CSRFToken válido → 201 (nunca 403)."""
        token = self._login()
        resp = self.client.post(
            reverse('core:custody-list'),
            self._custody_payload(),
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_metodo_safe_get_nao_exige_csrf(self):
        """GET (método safe) não aciona o gate CSRF, mesmo autenticado por cookie."""
        self._login()
        resp = self.client.get(reverse('core:occurrence-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
