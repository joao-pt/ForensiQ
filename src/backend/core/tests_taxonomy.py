"""Testes da taxonomia de crimes + prioridade por Política Criminal (ADR-0014, T19).

Cobre: seed idempotente (Tabela 1.7 + Lei 51/2023), integridade hierárquica,
derivação de prioridade (eixo INVESTIGACAO operativo), override manual, constraint
de versão única activa, e a OccurrenceViewSet POST-only.
"""

from datetime import date

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CrimeCategoria,
    CrimeSubcategoria,
    CrimeTipo,
    Occurrence,
    PoliticaCriminalPrioridade,
    PrioridadeCrimeTipo,
)
from core.tests_factories import UserFactory

# Contagens canónicas da Tabela de Crimes Registados 1.7 (2024) e do mapa.
N_CATEGORIAS = 7
N_SUBCATEGORIAS = 50
N_TIPOS = 219
N_INVESTIGACAO = 46
N_PREVENCAO = 51

# Códigos N3 de referência (verificados no mapa_politica_criminal.json):
COD_HOMICIDIO = 1  # INVESTIGACAO (Art.5 a) — prioritário
COD_OUTROS_VIDA = 5  # não mapeado — normal
COD_REGRAS_SEG = 13  # só PREVENCAO (Art.4 a) — normal (eixo operativo é investigação)


class SeedCrimeTaxonomyTest(TestCase):
    """Seed da taxonomia + política criminal a partir de core/data/*.json."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_crime_taxonomy')

    def test_contagens_da_tabela_1_7(self):
        self.assertEqual(CrimeCategoria.objects.count(), N_CATEGORIAS)
        self.assertEqual(CrimeSubcategoria.objects.count(), N_SUBCATEGORIAS)
        self.assertEqual(CrimeTipo.objects.count(), N_TIPOS)

    def test_categorias_incluem_codigo_10(self):
        """A 7.ª categoria (animais de companhia) — códigos N1 não contíguos."""
        codigos = set(CrimeCategoria.objects.values_list('codigo', flat=True))
        self.assertEqual(codigos, {1, 2, 3, 4, 5, 6, 10})

    def test_integridade_hierarquica(self):
        """Cada tipo tem subcategoria e categoria válidas."""
        for tipo in CrimeTipo.objects.select_related('subcategoria__categoria'):
            self.assertIsNotNone(tipo.subcategoria_id)
            self.assertIsNotNone(tipo.subcategoria.categoria_id)

    def test_codigos_2024_existem_e_descritivos(self):
        """Os exemplos do ADR (códigos 2024) existem com o descritivo certo."""
        self.assertEqual(CrimeTipo.objects.get(codigo=57).descritivo[:18], 'Abuso de cartão de')
        self.assertTrue(CrimeTipo.objects.filter(codigo__in=[241, 242, 243, 244]).count() == 4)
        # 53 (burla informática de 2008) já não existe na 1.7
        self.assertFalse(CrimeTipo.objects.filter(codigo=53).exists())

    def test_politica_criminal_seeded(self):
        politica = PoliticaCriminalPrioridade.objects.vigente()
        self.assertIsNotNone(politica)
        self.assertTrue(politica.is_active)
        self.assertEqual(
            politica.associacoes.filter(eixo=PrioridadeCrimeTipo.Eixo.INVESTIGACAO).count(),
            N_INVESTIGACAO,
        )
        self.assertEqual(
            politica.associacoes.filter(eixo=PrioridadeCrimeTipo.Eixo.PREVENCAO).count(),
            N_PREVENCAO,
        )

    def test_seed_idempotente(self):
        """Re-correr o seed não duplica registos."""
        call_command('seed_crime_taxonomy')
        self.assertEqual(CrimeTipo.objects.count(), N_TIPOS)
        self.assertEqual(PrioridadeCrimeTipo.objects.count(), N_INVESTIGACAO + N_PREVENCAO)

    def test_uma_so_politica_activa(self):
        """Constraint: não pode haver duas versões activas em simultâneo."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            PoliticaCriminalPrioridade.objects.create(
                lei='Lei 2025/2027 (futura)',
                biennium='2025-2027',
                vigente_desde=date(2025, 9, 1),
                is_active=True,
            )


class PriorityDerivationTest(TestCase):
    """Derivação de Occurrence.priority a partir do crime_type (ADR-0014)."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_crime_taxonomy')
        cls.agent = UserFactory()

    def _criar(self, codigo, **extra):
        return Occurrence.objects.create(
            number=f'NUIPC-PRI-{codigo}',
            description='Teste de derivação de prioridade.',
            agent=self.agent,
            crime_type=CrimeTipo.objects.get(codigo=codigo),
            **extra,
        )

    def test_crime_de_investigacao_prioritaria(self):
        occ = self._criar(COD_HOMICIDIO)
        self.assertEqual(occ.priority, Occurrence.Priority.PRIORITARIA)
        self.assertEqual(occ.priority_source, Occurrence.PrioritySource.LEI)

    def test_crime_nao_listado_normal(self):
        occ = self._criar(COD_OUTROS_VIDA)
        self.assertEqual(occ.priority, Occurrence.Priority.NORMAL)
        self.assertEqual(occ.priority_source, Occurrence.PrioritySource.LEI)

    def test_apenas_prevencao_nao_e_prioritaria(self):
        """Eixo operativo é INVESTIGACAO: um crime só de prevenção é normal."""
        occ = self._criar(COD_REGRAS_SEG)
        self.assertEqual(occ.priority, Occurrence.Priority.NORMAL)

    def test_override_manual_eleva(self):
        occ = self._criar(COD_OUTROS_VIDA, priority_source=Occurrence.PrioritySource.MANUAL)
        self.assertEqual(occ.priority, Occurrence.Priority.PRIORITARIA)
        self.assertEqual(occ.priority_source, Occurrence.PrioritySource.MANUAL)

    def test_lei_prevalece_sobre_override(self):
        """Override num crime que a lei já prioriza → fonte continua LEI."""
        occ = self._criar(COD_HOMICIDIO, priority_source=Occurrence.PrioritySource.MANUAL)
        self.assertEqual(occ.priority, Occurrence.Priority.PRIORITARIA)
        self.assertEqual(occ.priority_source, Occurrence.PrioritySource.LEI)


class OccurrencePostOnlyAPITest(TestCase):
    """OccurrenceViewSet é POST-only (ADR-0014) e crime_type é obrigatório."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_crime_taxonomy')
        cls.agent = UserFactory()

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.agent)

    def _payload(self, **extra):
        data = {
            'number': 'NUIPC-API-PRI-001',
            'description': 'Ocorrência via API.',
            'crime_type': CrimeTipo.objects.get(codigo=COD_HOMICIDIO).id,
        }
        data.update(extra)
        return data

    def test_post_com_crime_type_prioritario(self):
        resp = self.client.post('/api/occurrences/', self._payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['priority'], Occurrence.Priority.PRIORITARIA)
        self.assertEqual(resp.data['priority_source'], Occurrence.PrioritySource.LEI)

    def test_post_sem_crime_type_rejeitado(self):
        data = {'number': 'NUIPC-API-NO-CT', 'description': 'Sem tipo.'}
        resp = self.client.post('/api/occurrences/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('crime_type', resp.data)

    def test_post_override_manual(self):
        data = self._payload(
            number='NUIPC-API-OVR',
            crime_type=CrimeTipo.objects.get(codigo=COD_OUTROS_VIDA).id,
            elevar_prioridade=True,
        )
        resp = self.client.post('/api/occurrences/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['priority'], Occurrence.Priority.PRIORITARIA)
        self.assertEqual(resp.data['priority_source'], Occurrence.PrioritySource.MANUAL)

    def test_put_patch_delete_nao_permitidos(self):
        occ = self.client.post('/api/occurrences/', self._payload(), format='json')
        detail = f'/api/occurrences/{occ.data["id"]}/'
        self.assertEqual(
            self.client.put(detail, self._payload(), format='json').status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(detail, {'description': 'x'}, format='json').status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(detail).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
