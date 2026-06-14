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
from core.grid import GridColumn, _csv_cell, grid_list_response
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

    def test_custody_list_feed_de_auditoria(self):
        # Parecer item 15: coluna ÚNICA de identificação (o código do evento já
        # contém item+movimento — a coluna «Item» repetia o prefixo), NUIPC e
        # Responsável com filtro, e cabeçalho honesto «Estado atual».
        content = self._get('/custodies/').content.decode('utf-8')
        self.assertNotIn('name="item"', content)
        self.assertIn('name="occ"', content)
        self.assertIn('name="agent"', content)
        self.assertIn('Estado atual', content)
        self.assertIn('Responsável', content)
        # O Evento fica visível na redução mobile (sem col-reduce-hide).
        self.assertIn('CC-1', content)   # NUIPC decorado (display_label)

    def test_custody_list_filtro_responsavel_e_nuipc(self):
        ok = self._get('/custodies/?agent=grid_cc').content.decode('utf-8')
        self.assertIn('-M01', ok)
        vazio = self._get('/custodies/?agent=outro_qualquer').content.decode('utf-8')
        self.assertNotIn('-M01', vazio)
        por_nuipc = self._get('/custodies/?occ=CC-1').content.decode('utf-8')
        self.assertIn('-M01', por_nuipc)


class ReportsListRenderTest(AuthenticatedFrontendTestCase):
    """Smoke da lista de Guias de transporte (remessas): grelha não-clicável + CSV."""

    def test_reports_list_renders_guias_grid(self):
        response = self.client.get('/reports/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('id="guias-grid"', content)
        self.assertIn('aria-label="Guias de transporte"', content)
        # Linhas NÃO clicáveis (cada guia descarrega o PDF pela ação).
        self.assertNotIn('grid--clickable', content)
        self.assertNotIn('?drawer=', content)

    def test_reports_csv_export(self):
        r = self.client.get('/reports/?export=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertIn('Guia', r.content.decode('utf-8'))  # cabeçalho da coluna 'Guia'

    def test_export_csv_so_nas_grelhas_opt_in(self):
        # /custodies/ exporta CSV; /occurrences/ ignora o parâmetro (sem opt-in).
        occ = _occ(self.test_user, 'RPT-CC')
        _event(_evidence(occ, self.test_user), self.test_user)
        cc = self.client.get('/custodies/?export=csv')
        self.assertIn('text/csv', cc['Content-Type'])
        occs = self.client.get('/occurrences/?export=csv')
        self.assertIn('text/html', occs['Content-Type'])


class AuditTrailGridTest(TestCase):
    """Trilho de /audit/ no gerador único (parecer item 16): filtros +
    paginação (matam o teto fixo de 30), carimbo da lente na régie, alvo
    numérico validado no filtro derivado, achados clicáveis e need-to-know do
    âmbito preservado; decisão 6 — feed do PAINEL por lente + rajadas ×N."""

    @classmethod
    def setUpTestData(cls):
        from core.models import AuditLog, EventType

        cls.nacional = _user('aud_nac', User.Profile.FORENSIC_EXPERT,
                             clearance=User.Clearance.NACIONAL)
        cls.agente = _user('aud_agente', User.Profile.FIRST_RESPONDER)
        # user_label = nome completo OU username: sem os nomes Faker da
        # factory, as linhas mostram o username (asserts determinísticos).
        User.objects.filter(pk__in=(cls.nacional.pk, cls.agente.pk)).update(
            first_name='', last_name=''
        )
        cls.occ = _occ(cls.agente, 'AUD-1')
        cls.ev = _evidence(cls.occ, cls.agente)
        _event(cls.ev, cls.agente)   # génese
        # Evento sem custódio → anomalia «custódio em falta» no universo do agente.
        _event(cls.ev, cls.agente, event_type=EventType.TRANSFERENCIA_CUSTODIA)
        # 35 leituras do perito NACIONAL sobre o item do agente: paginação a 30
        # no trilho; rajada colapsada no painel (mesmo autor+ação+recurso).
        for i in range(35):
            AuditLog.objects.create(
                user=cls.nacional, action=AuditLog.Action.VIEW,
                resource_type=AuditLog.ResourceType.EVIDENCE,
                resource_id=cls.ev.id, ip_address='127.0.0.1',
                correlation_id=f'aud-{i:04d}', details={},
            )
        # Ato do próprio agente (o ÚNICO que ele vê no trilho probatório).
        AuditLog.objects.create(
            user=cls.agente, action=AuditLog.Action.CREATE,
            resource_type=AuditLog.ResourceType.OCCURRENCE,
            resource_id=cls.occ.id, ip_address='127.0.0.1',
            correlation_id='aud-agente-1', details={},
        )

    def _get(self, user, url):
        auth_cookie(self.client, user)
        return self.client.get(url)

    def test_trilho_em_grelha_com_filtros_e_paginacao(self):
        body = self._get(self.nacional, '/audit/investigation/').content.decode()
        self.assertIn('id="aud-grid"', body)
        for param in ('name="action"', 'name="rtype"', 'name="alvo"',
                      'name="autor"'):
            self.assertIn(param, body)
        self.assertIn('Registo nacional', body)
        self.assertIn('page=2', body)            # 36 eventos > page_size 30

    def test_filtro_de_alvo_valida_inteiro(self):
        r = self._get(self.nacional, '/audit/investigation/?alvo=abc')
        self.assertEqual(r.status_code, 200)     # nunca 500 (lookup validado)
        self.assertIn('Nenhum resultado', r.content.decode())

    def test_trilho_apenas_proprios_sem_leitura_nacional(self):
        body = self._get(self.agente, '/audit/investigation/').content.decode()
        self.assertIn('Apenas as minhas ações', body)
        self.assertNotIn('aud_nac', body)        # atos de terceiros invisíveis

    def test_anomalia_clicavel_para_o_item(self):
        body = self._get(self.agente, '/audit/investigation/').content.decode()
        self.assertIn(f'href="/evidences/{self.ev.id}/"', body)

    def test_feed_do_painel_por_lente_com_rajada(self):
        # Decisão 6: sem leitura nacional, o painel mostra os eventos das
        # ocorrências da LENTE (o ato do perito sobre o caso do agente), com a
        # rajada colapsada (×N) — o trilho probatório continua 1 linha/facto.
        body = self._get(self.agente, '/dashboard/').content.decode()
        self.assertIn('aud_nac', body)
        self.assertIn('×19', body)               # 20 do feed = CREATE + 19 VIEW
        self.assertIn('As minhas ocorrências', body)


class CsvFormulaInjectionTest(SimpleTestCase):
    """Defesa OWASP contra injeção de fórmula no export CSV (item 18): uma
    célula de texto livre iniciada por = + - @ (ou TAB/CR) é prefixada com
    aspa simples para o Excel/LibreOffice não a executarem como fórmula."""

    def _cell(self, value):
        o = _Obj()
        o.number = value
        return _csv_cell(o, GridColumn('number', 'NUIPC'))

    def test_prefixos_perigosos_sao_neutralizados(self):
        for raw in ('=HYPERLINK("http://x")', '+1', '-2', '@cmd', '\tx', '\rx'):
            self.assertEqual(self._cell(raw), "'" + raw)

    def test_valor_benigno_fica_intacto(self):
        self.assertEqual(self._cell('NUIPC-2026-000123'), 'NUIPC-2026-000123')

    def test_celula_vazia_fica_vazia(self):
        self.assertEqual(self._cell(''), '')


class ReportsCsvInjectionTest(AuthenticatedFrontendTestCase):
    """Defesa OWASP contra injeção de fórmula no export CSV das guias: um valor
    iniciado por '=' (ex.: NUIPC do processo) sai prefixado com aspa simples."""

    def test_export_csv_neutraliza_injecao_de_formula(self):
        from core.models import (
            ChainOfCustody,
            EventType,
            GuiaTransporte,
            Institution,
            InstitutionType,
        )

        occ = OccurrenceFactory(agent=self.test_user, number='=2+5')
        ev = _evidence(occ, self.test_user)
        _event(ev, self.test_user)  # apreensão
        dest = Institution.objects.create(name='OPC Z', type=InstitutionType.OPC, sigla='OPC-Z')
        enc = ChainOfCustody.objects.create(
            evidence=ev,
            event_type=EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_institution=dest,
            custodian_type='OPC',
            agent=self.test_user,
            bearer_nome='Rui',
            bearer_apelido='Costa',
            bearer_matricula='M-1',
        )
        guia = GuiaTransporte.objects.create(occurrence=occ)
        guia.events.set([enc])
        body = self.client.get('/reports/?export=csv').content.decode('utf-8')
        self.assertIn("'=2+5", body)        # prefixado com aspa simples
