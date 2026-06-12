"""
ForensiQ — Testes da árvore de sub-componentes (roadmap §6, Lote 1): guardas de
profundidade/ciclo do modelo (sem cobertura até aqui) e ordem de ÁRVORE das
listas por ocorrência (regressão: ``parent_evidence_id`` ASC punha as raízes
NULL em último no PostgreSQL; ordenação lexicográfica punha .10 antes de .2).
"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.frontend_views import _intake_world, _occurrence_items, _tree_sort_key
from core.models import Evidence, Occurrence
from core.tests_factories import CrimeTipoFactory, UserFactory


def _occ(agent, n):
    return Occurrence.objects.create(
        number=f'NUIPC-SUB-{n}',
        crime_type=CrimeTipoFactory(),
        description='caso de teste de sub-componentes',
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


class TreeDepthGuardTest(TestCase):
    """Guardas de profundidade e ciclo de ``Evidence.clean()`` — MAX_TREE_DEPTH."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()
        cls.occ = _occ(cls.agent, 'D1')

    def test_tres_niveis_sao_permitidos(self):
        raiz = _ev(self.occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(
            self.occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=raiz
        )
        neto = _ev(
            self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=filho
        )
        self.assertEqual(neto.code, f'{raiz.code}.1.1')
        self.assertEqual(neto.get_depth(), Evidence.MAX_TREE_DEPTH)

    def test_quarto_nivel_e_recusado(self):
        raiz = _ev(self.occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(
            self.occ,
            self.agent,
            Evidence.EvidenceType.VEHICLE_COMPONENT,
            parent=raiz,
        )
        neto = _ev(
            self.occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=filho
        )
        with self.assertRaises(ValidationError) as ctx:
            _ev(self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=neto)
        self.assertIn('parent_evidence', ctx.exception.message_dict)
        self.assertIn(
            'Profundidade', str(ctx.exception.message_dict['parent_evidence'])
        )

    def test_ciclo_e_recusado(self):
        raiz = _ev(self.occ, self.agent)
        filho = _ev(
            self.occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz
        )
        # A imutabilidade impede gravar um ciclo; a guarda defende contra dados
        # corrompidos — verifica-se em memória, sem persistir.
        raiz.parent_evidence = filho
        self.assertTrue(raiz._parent_contains_self())
        with self.assertRaises(ValidationError) as ctx:
            raiz.clean()
        self.assertIn('Ciclo', str(ctx.exception.message_dict['parent_evidence']))


class TreeOrderTest(TestCase):
    """Ordem de árvore das listas por ocorrência (raiz antes dos filhos; irmãos
    por índice numérico) e anotação ``tree_depth``."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = UserFactory()

    def test_raiz_antes_dos_filhos_e_filhos_adjacentes(self):
        occ = _occ(self.agent, 'O1')
        raiz1 = _ev(occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=raiz1)
        neto = _ev(occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=filho)
        raiz2 = _ev(occ, self.agent)
        itens = _occurrence_items(occ)
        self.assertEqual(
            [e.code for e in itens],
            [raiz1.code, filho.code, neto.code, raiz2.code],
        )
        self.assertEqual([e.tree_depth for e in itens], [1, 2, 3, 1])

    def test_irmaos_ordenam_numericamente_nao_lexicograficamente(self):
        occ = _occ(self.agent, 'O2')
        raiz = _ev(occ, self.agent)
        filhos = [
            _ev(occ, self.agent, Evidence.EvidenceType.SIM_CARD, parent=raiz)
            for _ in range(10)
        ]
        itens = _occurrence_items(occ)
        # .10 vem depois de .9 (lexicograficamente viria logo a seguir a .1).
        self.assertEqual(
            [e.code for e in itens],
            [raiz.code] + [f.code for f in filhos],
        )
        self.assertEqual(itens[-1].code, f'{raiz.code}.10')

    def test_chave_tolerante_a_codigo_fora_do_padrao(self):
        occ = _occ(self.agent, 'O3')
        raiz = _ev(occ, self.agent)
        raiz.code = 'LIXO-SEM-PADRAO.x'
        self.assertEqual(_tree_sort_key(raiz), (float('inf'),))

    def test_intake_usa_a_mesma_ordem_de_arvore(self):
        occ = _occ(self.agent, 'O4')
        raiz1 = _ev(occ, self.agent, Evidence.EvidenceType.VEHICLE)
        filho = _ev(occ, self.agent, Evidence.EvidenceType.GPS_TRACKER, parent=raiz1)
        raiz2 = _ev(occ, self.agent)
        evidences, _states, _eventos = _intake_world(occ)
        self.assertEqual(
            [e.code for e in evidences], [raiz1.code, filho.code, raiz2.code]
        )
