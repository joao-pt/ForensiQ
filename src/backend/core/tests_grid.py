"""ForensiQ — Testes do gerador ÚNICO de grelhas (core.grid + cellattr).

Tranca o contrato transversal que TODAS as listas passam a partilhar: o filtro
``cellattr`` (atributo variável, caminho com ponto, sem invocar callables), a
guarda de largura obrigatória (table-layout:fixed) e a paridade do markup da
grelha — cabeçalho de 2 linhas, larguras por classe (CSP-safe), células com
``role=gridcell``, bolinha de urgência, hora restaurada, ícone GPS e vista
mobile reduzida.
"""
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.grid import GridColumn, grid_list_response
from core.templatetags.grid_extras import cellattr
from core.tests_base import auth_cookie
from core.tests_factories import (
    OccurrenceFactory,
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)
from core.tests_frontend import AuthenticatedFrontendTestCase

User = get_user_model()


class _Obj:
    """Objeto simples para exercitar o acesso por atributo."""


class CellAttrFilterTest(SimpleTestCase):
    """O filtro que resolve o valor da célula a partir do nome de coluna."""

    def test_simple_attr(self):
        o = _Obj()
        o.code = 'OC-1'
        self.assertEqual(cellattr(o, 'code'), 'OC-1')

    def test_dotted_path(self):
        parent, child = _Obj(), _Obj()
        child.code = 'EV-1'
        parent.evidence = child
        self.assertEqual(cellattr(parent, 'evidence.code'), 'EV-1')

    def test_missing_attr_returns_empty(self):
        self.assertEqual(cellattr(_Obj(), 'nope'), '')

    def test_missing_in_dotted_path_returns_empty(self):
        parent = _Obj()
        parent.evidence = None
        self.assertEqual(cellattr(parent, 'evidence.code'), '')

    def test_none_value_passthrough(self):
        o = _Obj()
        o.x = None
        self.assertIsNone(cellattr(o, 'x'))

    def test_numeric_zero_passthrough(self):
        # A célula 'num' usa |default_if_none → o 0 tem de passar (não virar '—').
        o = _Obj()
        o.n = 0
        self.assertEqual(cellattr(o, 'n'), 0)

    def test_mapping_key(self):
        self.assertEqual(cellattr({'a': 1}, 'a'), 1)

    def test_does_not_invoke_callable(self):
        o = _Obj()
        o.m = lambda: 'chamado'
        self.assertTrue(callable(cellattr(o, 'm')))

    def test_filter_in_template(self):
        o = _Obj()
        o.code = 'OC-9'
        tpl = Template("{% load grid_extras %}{{ row|cellattr:key|default:'—' }}")
        self.assertEqual(tpl.render(Context({'row': o, 'key': 'code'})), 'OC-9')


class GridWidthGuardTest(SimpleTestCase):
    """Sob table-layout:fixed, uma coluna sem largura colapsa silenciosamente."""

    def test_missing_width_raises(self):
        req = RequestFactory().get('/x/')
        with self.assertRaises(ValueError):
            grid_list_response(
                req, queryset=[], columns=[GridColumn('a', 'A')],  # width=0
                grid_key='x', endpoint='/x/', page_template='x.html',
                table_label='X', count_noun='x', sorts={'r': 'id'},
                default_sort='r')


class GridGeneratorRenderTest(AuthenticatedFrontendTestCase):
    """Paridade do markup gerado na página de ocorrências (a referência)."""

    def test_grid_markup_is_single_source(self):
        OccurrenceFactory(agent=self.test_user)
        content = self.client.get(reverse('occurrences')).content.decode('utf-8')
        # Tabela única: filterable + resizable + clickable + mobile-reduce + aria.
        self.assertIn('grid--filterable', content)
        self.assertIn('grid--resizable', content)
        self.assertIn('grid--clickable', content)
        self.assertIn('grid--mobile-reduce', content)
        self.assertIn('aria-label="Lista de ocorrências"', content)
        # Cabeçalho de 2 linhas + largura por classe utilitária (CSP-safe).
        self.assertIn('grid__head-row', content)
        self.assertIn('grid__filter-row', content)
        self.assertIn('grid__col--w13', content)        # Código
        # Células ARIA + bolinha de urgência (host = Código) + legenda.
        self.assertIn('role="gridcell"', content)
        self.assertIn('grid__dot-host', content)
        self.assertIn('urgency-dot', content)
        self.assertIn('urgency-legend', content)
        # Hora restaurada (desktop) e ícone GPS no Local.
        self.assertIn('grid__cell-time', content)
        self.assertIn('grid__geo', content)
        # Colunas não-essenciais escondem-se no telemóvel.
        self.assertIn('col-reduce-hide', content)

    def test_no_inline_width_style(self):
        # CSP estrito: nenhuma largura via style inline (tudo por classe).
        OccurrenceFactory(agent=self.test_user)
        content = self.client.get(reverse('occurrences')).content.decode('utf-8')
        self.assertNotIn('style="width', content)


class CustodyListRenderTest(TestCase):
    """Smoke real da LISTA de custódias (a timeline já tinha testes; a lista não).

    Tranca que o gerador renderiza com os filtros por coluna PRESERVADOS (incl.
    Instituição + Estado, que viviam numa gaveta à parte) e a bolinha por estado.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = _user('grid_cc', User.Profile.FIRST_RESPONDER)
        occ = _occ(cls.user, 'CC-1')
        ev = _evidence(occ, cls.user)
        _event(ev, cls.user)   # apreensão → item à guarda (estado derivado)

    def _get(self, url):
        auth_cookie(self.client, self.user)
        return self.client.get(url)

    def test_custody_list_renders_with_filters_and_dot(self):
        response = self._get('/custodies/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('id="cc-grid"', content)
        self.assertIn('grid--mobile-reduce', content)
        self.assertIn('aria-label="Eventos de custódia"', content)
        # Filtros por coluna preservados (igual às ocorrências), incl. os 2 que
        # antes viviam na gaveta: Instituição e Estado.
        self.assertIn('name="event"', content)
        self.assertIn('name="custodian"', content)
        self.assertIn('name="institution"', content)
        self.assertIn('name="state"', content)
        # Bolinha de estado (host = Código) + badge de estado na coluna própria.
        self.assertIn('urgency-dot', content)
        self.assertIn('state state--', content)


class ReportsListRenderTest(AuthenticatedFrontendTestCase):
    """Smoke da lista de Guias de transporte: linhas NÃO-clicáveis, ação PDF e
    ligação do Código ao detalhe (mesma grelha, dados diferentes)."""

    def test_reports_list_renders_non_clickable_with_pdf(self):
        OccurrenceFactory(agent=self.test_user)
        response = self.client.get('/reports/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('id="rpt-grid"', content)
        self.assertIn('aria-label="Guias de transporte"', content)
        self.assertIn('grid--mobile-reduce', content)
        # Linhas NÃO clicáveis (sem gaveta de detalhe).
        self.assertNotIn('grid--clickable', content)
        self.assertNotIn('?drawer=', content)
        # Ação PDF + Código ligado ao detalhe.
        self.assertIn('/api/occurrences/', content)
        self.assertIn('grid__link', content)
