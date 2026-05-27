"""
ForensiQ — Testes da vista pública de verificação por QR (ADR-0012 P1).

Cobertura:
- `short_hash_for` é determinístico para o mesmo (id, secret).
- `short_hash_for` muda quando o secret muda.
- Hash desconhecido → 404 com template `public_verify_notfound.html`.
- Hash válido + sem login → 200 com template `public_verify.html`
  contendo dados mínimos não-sensíveis.
- Hash válido + EXPERT logado → 302 para `/occurrences/<id>/`.
- Hash válido + AGENT-dono → 302.
- Hash válido + AGENT-não-dono → 200 vista pública (não vaza).
- Vista pública não contém descrição, GPS, ou nome de agente.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Evidence, Occurrence
from core.qr_verify import short_hash_for

User = get_user_model()


def _make_user(username, profile='AGENT', password='TestPass123!'):
    return User.objects.create_user(
        username=username,
        password=password,
        profile=profile,
        badge_number=f'BADGE-{username}',
    )


def _make_occurrence(agent, number='OCC-PV-001'):
    return Occurrence.objects.create(
        number=number,
        description='Cena de crime sensível — não deve aparecer na vista pública',
        date_time=timezone.now(),
        gps_lat=Decimal('38.7'),
        gps_lon=Decimal('-9.1'),
        address='Rua Sensível 42, Lisboa',
        agent=agent,
    )


def _make_evidence(occurrence, agent, *, serial='SN-PV-001'):
    return Evidence.objects.create(
        occurrence=occurrence,
        type=Evidence.EvidenceType.MOBILE_DEVICE,
        description='Descrição confidencial do item',
        serial_number=serial,
        agent=agent,
    )


def _login_cookie(client, user):
    """Coloca um JWT access cookie no APIClient (simula login)."""
    refresh = RefreshToken.for_user(user)
    access = str(refresh.access_token)
    client.cookies['fq_access'] = access


class ShortHashTest(TestCase):
    def test_determinístico_para_mesmo_secret(self):
        with override_settings(QR_VERIFY_SECRET='secret-A'):
            h1 = short_hash_for(42)
            h2 = short_hash_for(42)
        self.assertEqual(h1, h2)

    def test_muda_quando_secret_muda(self):
        with override_settings(QR_VERIFY_SECRET='secret-A'):
            h1 = short_hash_for(42)
        with override_settings(QR_VERIFY_SECRET='secret-B'):
            h2 = short_hash_for(42)
        self.assertNotEqual(h1, h2)

    def test_diferente_por_occurrence(self):
        h1 = short_hash_for(1)
        h2 = short_hash_for(2)
        self.assertNotEqual(h1, h2)

    def test_comprimento_default_12(self):
        self.assertEqual(len(short_hash_for(1)), 12)


class PublicVerifyEndpointTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent_owner = _make_user('agent_owner_pv')
        cls.agent_other = _make_user('agent_other_pv')
        cls.expert = _make_user('expert_pv', profile='EXPERT')
        cls.occurrence = _make_occurrence(cls.agent_owner)
        cls.evidence = _make_evidence(cls.occurrence, cls.agent_owner)
        cls.short_hash = short_hash_for(cls.occurrence.id)

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=False)

    def test_hash_desconhecido_devolve_404(self):
        response = self.client.get('/v/000000000000/')
        self.assertEqual(response.status_code, 404)
        # Mensagem em PT-PT do template not-found.
        self.assertIn(b'Tal\xc3\xa3o n\xc3\xa3o reconhecido', response.content)

    def test_hash_curto_invalido_devolve_404(self):
        # Hash com tamanho diferente de QR_VERIFY_HASH_LEN.
        response = self.client.get('/v/abc/')
        self.assertEqual(response.status_code, 404)

    def test_sem_login_renderiza_vista_publica(self):
        response = self.client.get(f'/v/{self.short_hash}/')
        self.assertEqual(response.status_code, 200)
        # Mostra código da ocorrência e contagem.
        self.assertIn(self.occurrence.code.encode(), response.content)
        self.assertIn(b'Itens esperados', response.content)
        # Mostra integrity_hash (defesa em profundidade).
        self.assertIn(self.evidence.integrity_hash.encode(), response.content)

    def test_vista_publica_nao_vaza_descricao(self):
        response = self.client.get(f'/v/{self.short_hash}/')
        self.assertEqual(response.status_code, 200)
        # Descrição confidencial NÃO deve aparecer.
        self.assertNotIn(b'confidencial', response.content.lower())
        self.assertNotIn(b'sensivel', response.content.lower())
        self.assertNotIn(b'sens\xc3\xadvel', response.content.lower())
        # Nome de agente NÃO deve aparecer.
        self.assertNotIn(b'agent_owner_pv', response.content)

    def test_expert_logado_redirect_para_detalhe(self):
        _login_cookie(self.client, self.expert)
        response = self.client.get(f'/v/{self.short_hash}/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f'/occurrences/{self.occurrence.id}/')

    def test_agent_dono_redirect_para_detalhe(self):
        _login_cookie(self.client, self.agent_owner)
        response = self.client.get(f'/v/{self.short_hash}/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f'/occurrences/{self.occurrence.id}/')

    def test_agent_nao_dono_ve_vista_publica(self):
        """AGENT que não é dono cai na vista pública (read-only)."""
        _login_cookie(self.client, self.agent_other)
        response = self.client.get(f'/v/{self.short_hash}/')
        self.assertEqual(response.status_code, 200)
        # Não redirecciona para detalhe (IDOR-safe).
        self.assertIn(b'Aceder com login', response.content)
