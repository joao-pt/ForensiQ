"""
ForensiQ — Testes da API REST.

Testa:
- Autenticação JWT (login, token refresh)
- CRUD de ocorrências (permissões por perfil)
- CRUD de evidências (hash automático, permissões)
- CRUD de dispositivos digitais
- Cadeia de custódia (append-only via API, timeline)
- Permissões: AGENT vs EXPERT vs não autenticado
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
    User,
)


class BaseAPITestCase(TestCase):
    """Classe base com setup comum para testes da API."""

    def setUp(self):
        self.client = APIClient()

        # Criar utilizadores de teste
        self.agent = User.objects.create_user(
            username='agente_api',
            password='TestPass123!',
            profile=User.Profile.AGENT,
            badge_number='PSP-API-01',
            first_name='Ana',
            last_name='Silva',
        )
        self.expert = User.objects.create_user(
            username='perito_api',
            password='TestPass123!',
            profile=User.Profile.EXPERT,
            first_name='Carlos',
            last_name='Costa',
        )
        self.admin = User.objects.create_superuser(
            username='admin_api',
            password='AdminPass123!',
        )

    def authenticate_as(self, user):
        """Autentica o cliente via JWT."""
        self.client.force_authenticate(user=user)

    def get_jwt_token(self, username, password):
        """Obtém token JWT via endpoint de login."""
        url = reverse('token_obtain_pair')
        response = self.client.post(url, {
            'username': username,
            'password': password,
        })
        return response


# ---------------------------------------------------------------------------
# Testes de Autenticação JWT
# ---------------------------------------------------------------------------

class JWTAuthTest(BaseAPITestCase):
    """Testes de autenticação JWT."""

    def test_login_success(self):
        """Login com credenciais válidas retorna tokens."""
        response = self.get_jwt_token('agente_api', 'TestPass123!')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_invalid_credentials(self):
        """Login com credenciais inválidas retorna 401."""
        response = self.get_jwt_token('agente_api', 'wrongpassword')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_refresh(self):
        """Refresh token gera novo access token."""
        login = self.get_jwt_token('agente_api', 'TestPass123!')
        refresh_token = login.data['refresh']

        url = reverse('token_refresh')
        response = self.client.post(url, {'refresh': refresh_token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

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
        self.assertEqual(response.data['profile'], 'AGENT')

    def test_create_user_requires_admin(self):
        """Apenas administradores podem criar utilizadores."""
        self.authenticate_as(self.agent)
        url = reverse('core:user-list')
        response = self.client.post(url, {
            'username': 'novo_agente',
            'password': 'NovoPass123!',
            'profile': 'AGENT',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_user(self):
        """Administrador pode criar utilizadores."""
        self.authenticate_as(self.admin)
        url = reverse('core:user-list')
        response = self.client.post(url, {
            'username': 'novo_agente',
            'password': 'NovoPass123!',
            'profile': 'AGENT',
            'badge_number': 'PSP-NEW-01',
        })
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
        response = self.client.post(url, {
            'number': 'NUIPC-2026-API-001',
            'description': 'Teste de ocorrência via API.',
            'gps_lat': '38.7223340',
            'gps_lon': '-9.1393366',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['number'], 'NUIPC-2026-API-001')
        # Agent preenchido automaticamente
        self.assertEqual(response.data['agent'], self.agent.id)

    def test_expert_cannot_create_occurrence(self):
        """EXPERT não pode criar ocorrências."""
        self.authenticate_as(self.expert)
        url = reverse('core:occurrence-list')
        response = self.client.post(url, {
            'number': 'NUIPC-2026-API-002',
            'description': 'Tentativa de perito.',
        })
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
            number='NUIPC-2026-EV',
            description='Ocorrência para evidências.',
            agent=self.agent,
        )

    def test_agent_creates_evidence(self):
        """AGENT pode criar evidências com hash automático."""
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')
        response = self.client.post(url, {
            'occurrence': self.occurrence.pk,
            'type': 'DIGITAL_DEVICE',
            'description': 'Smartphone encontrado no local.',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Hash SHA-256 calculado automaticamente
        self.assertEqual(len(response.data['integrity_hash']), 64)

    def test_filter_by_occurrence(self):
        """Filtrar evidências por ocorrência."""
        Evidence.objects.create(
            occurrence=self.occurrence,
            type='DOCUMENT',
            description='Documento de teste.',
            agent=self.agent,
        )
        self.authenticate_as(self.agent)
        url = reverse('core:evidence-list')
        response = self.client.get(url, {'occurrence': self.occurrence.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)


# ---------------------------------------------------------------------------
# Testes de DigitalDevice
# ---------------------------------------------------------------------------

class DigitalDeviceAPITest(BaseAPITestCase):
    """Testes para o endpoint /api/devices/."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            number='NUIPC-2026-DEV',
            description='Ocorrência para dispositivos.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='DIGITAL_DEVICE',
            description='Portátil.',
            agent=self.agent,
        )

    def test_agent_creates_device(self):
        """AGENT pode registar um dispositivo digital."""
        self.authenticate_as(self.agent)
        url = reverse('core:device-list')
        response = self.client.post(url, {
            'evidence': self.evidence.pk,
            'type': 'LAPTOP',
            'brand': 'Lenovo',
            'model': 'ThinkPad X1',
            'condition': 'FUNCTIONAL',
            'serial_number': 'SN-TEST-001',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['brand'], 'Lenovo')


# ---------------------------------------------------------------------------
# Testes de ChainOfCustody
# ---------------------------------------------------------------------------

class ChainOfCustodyAPITest(BaseAPITestCase):
    """Testes para o endpoint /api/custody/."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            number='NUIPC-2026-COC',
            description='Ocorrência para custódia.',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='DIGITAL_DEVICE',
            description='Smartphone para custódia.',
            agent=self.agent,
        )

    def test_agent_creates_first_custody_record(self):
        """AGENT pode criar primeiro registo de custódia."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-list')
        response = self.client.post(url, {
            'evidence': self.evidence.pk,
            'previous_state': '',
            'new_state': 'APREENDIDA',
            'observations': 'Apreensão no local do crime.',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['record_hash']), 64)

    def test_expert_can_advance_custody(self):
        """EXPERT pode avançar a custódia."""
        # Primeiro registo pelo agente
        ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        ).save()
        ChainOfCustody(
            evidence=self.evidence,
            previous_state=ChainOfCustody.CustodyState.APREENDIDA,
            new_state=ChainOfCustody.CustodyState.EM_TRANSPORTE,
            agent=self.agent,
        ).save()

        # Perito recebe no laboratório
        self.authenticate_as(self.expert)
        url = reverse('core:custody-list')
        response = self.client.post(url, {
            'evidence': self.evidence.pk,
            'previous_state': 'EM_TRANSPORTE',
            'new_state': 'RECEBIDA_LABORATORIO',
            'observations': 'Recebido no laboratório forense.',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_put_not_allowed(self):
        """PUT não é permitido (append-only)."""
        ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        ).save()

        record = ChainOfCustody.objects.first()
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': record.pk})
        response = self.client.put(url, {
            'evidence': self.evidence.pk,
            'previous_state': '',
            'new_state': 'APREENDIDA',
            'observations': 'Alteração bloqueada.',
        })
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed(self):
        """DELETE não é permitido (append-only)."""
        ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        ).save()

        record = ChainOfCustody.objects.first()
        self.authenticate_as(self.agent)
        url = reverse('core:custody-detail', kwargs={'pk': record.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_invalid_transition_returns_400(self):
        """Transição inválida retorna 400."""
        self.authenticate_as(self.agent)
        url = reverse('core:custody-list')
        response = self.client.post(url, {
            'evidence': self.evidence.pk,
            'previous_state': '',
            'new_state': 'EM_PERICIA',  # Inválido — deve ser APREENDIDA primeiro
            'observations': 'Transição inválida.',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_timeline_endpoint(self):
        """Endpoint timeline retorna histórico ordenado."""
        ChainOfCustody(
            evidence=self.evidence,
            previous_state='',
            new_state=ChainOfCustody.CustodyState.APREENDIDA,
            agent=self.agent,
        ).save()
        ChainOfCustody(
            evidence=self.evidence,
            previous_state=ChainOfCustody.CustodyState.APREENDIDA,
            new_state=ChainOfCustody.CustodyState.EM_TRANSPORTE,
            agent=self.agent,
        ).save()

        self.authenticate_as(self.agent)
        url = reverse('core:custody-timeline', kwargs={'evidence_id': self.evidence.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        # Ordenação cronológica
        self.assertEqual(response.data[0]['new_state'], 'APREENDIDA')
        self.assertEqual(response.data[1]['new_state'], 'EM_TRANSPORTE')
