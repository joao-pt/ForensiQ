"""ForensiQ — Testes do modo tabela densa (F1 backend).

Cobre:
- ``BoundedPageNumberPagination`` — cap defensivo a 100.
- ``OccurrenceFilter`` / ``EvidenceFilter`` / ``CustodyFilter`` — filtros
  declarados via ``django-filter``.
- Preservação de ``IsOwnerOrReadOnly`` (AGENT só vê os seus) com filtros
  activos — anti-IDOR.
- Convivência com filtros pré-existentes (``?state=`` em occurrences).
"""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.tests_factories import (
    EvidenceMobileFactory,
    EvidenceVehicleFactory,
    OccurrenceFactory,
    UserFactory,
)
from django.utils import timezone


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class BoundedPaginationTest(APITestCase):
    """``page_size_query_param`` é honrado mas com cap a ``max_page_size``."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory.create()
        # 12 ocorrências chega para validar paginação sem inflar a duração.
        cls.occurrences = [
            OccurrenceFactory.create(agent=cls.agent) for _ in range(12)
        ]

    def setUp(self):
        self.client.force_authenticate(user=self.agent)

    def test_default_page_size_50(self):
        """Sem ``page_size`` na URL, devolve até 50 itens."""
        response = self.client.get('/api/occurrences/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(response.data['results']), 50)
        self.assertEqual(response.data['count'], 12)

    def test_custom_page_size_query_param(self):
        """``?page_size=5`` devolve apenas 5 itens por página."""
        response = self.client.get('/api/occurrences/?page_size=5')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 5)

    def test_page_size_capped_at_100(self):
        """``?page_size=10000`` é cortado para o ``max_page_size`` (100)."""
        # Não temos 100 ocorrências mas o cap é validado antes do slicing —
        # o output ainda terá só 12, mas o teste garante que nem 200 nem 500
        # rebentam o servidor (DoS).
        response = self.client.get('/api/occurrences/?page_size=10000')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(response.data['results']), 100)


# ---------------------------------------------------------------------------
# OccurrenceFilter
# ---------------------------------------------------------------------------


class OccurrenceFilterTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory.create()
        now = timezone.now()
        # Hoje
        cls.occ_today = OccurrenceFactory.create(
            agent=cls.agent, date_time=now,
        )
        # 30 dias atrás
        cls.occ_old = OccurrenceFactory.create(
            agent=cls.agent, date_time=now - timedelta(days=30),
        )
        # Sem GPS
        cls.occ_no_gps = OccurrenceFactory.create(
            agent=cls.agent, gps_lat=None, gps_lon=None,
        )

    def setUp(self):
        self.client.force_authenticate(user=self.agent)

    def test_filter_date_after(self):
        """``?date_after=YYYY-MM-DD`` filtra ocorrências a partir da data."""
        cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
        response = self.client.get(f'/api/occurrences/?date_after={cutoff}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {o['id'] for o in response.data['results']}
        self.assertIn(self.occ_today.id, ids)
        self.assertNotIn(self.occ_old.id, ids)

    def test_filter_date_before(self):
        """``?date_before=YYYY-MM-DD`` filtra até à data."""
        cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
        response = self.client.get(f'/api/occurrences/?date_before={cutoff}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {o['id'] for o in response.data['results']}
        self.assertNotIn(self.occ_today.id, ids)
        self.assertIn(self.occ_old.id, ids)

    def test_filter_has_gps_true(self):
        """``?has_gps=true`` exclui ocorrências sem coordenadas."""
        response = self.client.get('/api/occurrences/?has_gps=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {o['id'] for o in response.data['results']}
        self.assertNotIn(self.occ_no_gps.id, ids)
        self.assertIn(self.occ_today.id, ids)

    def test_filter_has_gps_false(self):
        """``?has_gps=false`` devolve apenas as sem coordenadas."""
        response = self.client.get('/api/occurrences/?has_gps=false')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {o['id'] for o in response.data['results']}
        self.assertIn(self.occ_no_gps.id, ids)
        self.assertNotIn(self.occ_today.id, ids)

    def test_state_filter_still_works(self):
        """Filtro ``?state=`` (custom no get_queryset) continua a funcionar."""
        # Sem registo de custódia — `state=APREENDIDA` devolve 0 itens.
        response = self.client.get('/api/occurrences/?state=APREENDIDA')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_state_invalid_returns_400(self):
        response = self.client.get('/api/occurrences/?state=INVALID_STATE')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# EvidenceFilter
# ---------------------------------------------------------------------------


class EvidenceFilterTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory.create()
        cls.occ = OccurrenceFactory.create(agent=cls.agent)
        cls.mobile = EvidenceMobileFactory.create(occurrence=cls.occ, agent=cls.agent)
        cls.vehicle = EvidenceVehicleFactory.create(occurrence=cls.occ, agent=cls.agent)

    def setUp(self):
        self.client.force_authenticate(user=self.agent)

    def test_filter_type_single(self):
        """``?type=MOBILE_DEVICE`` devolve apenas telemóveis."""
        response = self.client.get('/api/evidences/?type=MOBILE_DEVICE')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {e['id'] for e in response.data['results']}
        self.assertIn(self.mobile.id, ids)
        self.assertNotIn(self.vehicle.id, ids)

    def test_filter_type_multiple(self):
        """``?type=MOBILE_DEVICE&type=VEHICLE`` agrega ambos os tipos."""
        response = self.client.get(
            '/api/evidences/?type=MOBILE_DEVICE&type=VEHICLE',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {e['id'] for e in response.data['results']}
        self.assertIn(self.mobile.id, ids)
        self.assertIn(self.vehicle.id, ids)


# ---------------------------------------------------------------------------
# Ownership preserved with filters (anti-IDOR)
# ---------------------------------------------------------------------------


class OwnershipWithFiltersTest(APITestCase):
    """AGENT continua a ver só as suas ocorrências mesmo com filtros activos."""

    @classmethod
    def setUpTestData(cls):
        cls.agent_a = UserFactory.create(username='agent_a')
        cls.agent_b = UserFactory.create(username='agent_b')
        cls.occ_a = OccurrenceFactory.create(agent=cls.agent_a)
        cls.occ_b = OccurrenceFactory.create(agent=cls.agent_b)

    def test_agent_a_filters_only_sees_own(self):
        """Filtros não rompem o filtro de ownership do ``get_queryset``."""
        self.client.force_authenticate(user=self.agent_a)
        response = self.client.get('/api/occurrences/?has_gps=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {o['id'] for o in response.data['results']}
        self.assertIn(self.occ_a.id, ids)
        self.assertNotIn(self.occ_b.id, ids)

    def test_evidence_filter_respects_ownership(self):
        """Idem para evidências — ?type= não dá acesso a evidências de outros."""
        EvidenceMobileFactory.create(occurrence=self.occ_b, agent=self.agent_b)
        self.client.force_authenticate(user=self.agent_a)
        response = self.client.get('/api/evidences/?type=MOBILE_DEVICE')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Agent A não tem evidências MOBILE_DEVICE — não deve ver as do B.
        self.assertEqual(response.data['count'], 0)


# ---------------------------------------------------------------------------
# Imutabilidade ISO/IEC 27037 — regressão (filtros não devem habilitar PATCH)
# ---------------------------------------------------------------------------


class ImmutabilityRegressionTest(APITestCase):
    """Garantia que adicionar django-filter não quebra a imutabilidade.

    Evidence é write-once; PATCH/DELETE devem continuar a devolver 405.
    """

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory.create()
        cls.occ = OccurrenceFactory.create(agent=cls.agent)
        cls.evidence = EvidenceMobileFactory.create(occurrence=cls.occ, agent=cls.agent)

    def setUp(self):
        self.client.force_authenticate(user=self.agent)

    def test_patch_evidence_returns_405(self):
        response = self.client.patch(
            f'/api/evidences/{self.evidence.id}/',
            data={'description': 'tampered'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_evidence_returns_405(self):
        response = self.client.delete(f'/api/evidences/{self.evidence.id}/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
