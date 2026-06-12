"""ForensiQ — Testes: consulta read-only dos atos de autoridade (badge → modal).

Os badges «Validada»/«Com despacho judicial»/«Perícia até …» dizem só O QUE
existe; a vista ``/evidences/<id>/atos/`` mostra o resto que está selado no
ledger (hv4): quem proferiu cada ato (nome/cargo), a data declarada, o prazo e
a data-limite derivada, a justificação e o registo. Mesmo contrato
modal/página dos atos certificados (fragmento para o <dialog>; página completa
no fallback sem-JS); porta de leitura igual à do detalhe (need-to-know).
"""

from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.labels import (
    DESPACHO_SUBSTITUIDO_LABEL,
    PRAZO_RESOLVIDO_LABELS,
    VALIDATION_LATE_LABEL,
)
from core.models import (
    CERTIFIED_ACT_EVENTS,
    AuditLog,
    ChainOfCustody,
    CustodianType,
    EventType,
    Institution,
    InstitutionMembership,
    InstitutionType,
)
from core.policy.event_states import validation_due_at
from core.tests_base import auth_cookie
from core.tests_factories import (
    AUTHORITY_KWARGS,
    AUTHORITY_PRAZO_DIAS,
    make_chain,
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)

User = get_user_model()


class AtosConsultaTest(TestCase):
    """Vista de consulta dos atos: conteúdo, contrato modal/página e acesso."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Atos', type=InstitutionType.OPC, sigla='PSP-AT'
        )
        cls.agent = _user('atos_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'ATOS-1')
        # Item com os DOIS atos certificados (autoridade canónica das factories).
        cls.ev = _evidence(cls.occ, cls.agent)
        make_chain(
            cls.ev,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': cls.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
        )

    def _get(self, ev, suffix=''):
        auth_cookie(self.client, self.agent)
        return self.client.get(
            reverse('evidence_atos', args=[ev.id]) + suffix
        )

    # -- Conteúdo ----------------------------------------------------------

    def test_modal_mostra_autoridade_data_e_prazo(self):
        body = self._get(self.ev, '?modal=1').content.decode()
        self.assertIn('data-modal-title', body)
        self.assertNotIn('<html', body)  # fragmento, não página
        # Quem proferiu (nome + cargo estruturados, hv4) — nos DOIS atos.
        self.assertEqual(body.count(AUTHORITY_KWARGS['authority_nome']), 2)
        self.assertIn(AUTHORITY_KWARGS['authority_cargo'], body)
        # O prazo do despacho e a data-limite derivada (policy pericia_due_date).
        self.assertIn(f'{AUTHORITY_PRAZO_DIAS} dias', body)
        despacho = self.ev.custody_chain.get(
            event_type=EventType.DESPACHO_PERICIA
        )
        due = (
            timezone.localtime(despacho.act_declared_at).date()
            + timedelta(days=AUTHORITY_PRAZO_DIAS)
        )
        self.assertIn(due.isoformat(), body)
        # Estatuto vigente do prazo junto ao despacho (badge da derivação).
        self.assertIn('Perícia até', body)
        # Rasto do registo: quem registou e o hash encadeado (prefixo).
        self.assertIn(despacho.record_hash[:16], body)

    def test_pagina_completa_no_fallback_sem_js(self):
        body = self._get(self.ev).content.decode()
        self.assertIn('<html', body)
        self.assertIn('Atos de autoridade', body)
        self.assertIn(AUTHORITY_KWARGS['authority_nome'], body)

    def test_validacao_pendente_mostra_base_e_limite_legal(self):
        ev = _evidence(self.occ, self.agent)
        seizure = _event(ev, self.agent, inst=self.opc)  # APREENSAO_OBJETO
        body = self._get(ev, '?modal=1').content.decode()
        self.assertIn('Por validar', body)
        # A base do estatuto: a apreensão e o limite legal — fórmula e prazo
        # da fonte única (validation_due_at / settings), nunca literais.
        self.assertIn(
            f'{settings.VALIDATION_DEADLINE_HOURS}h após a apreensão', body
        )
        limite = timezone.localtime(validation_due_at(seizure.timestamp))
        self.assertIn(limite.strftime('%Y-%m-%d %H:%M'), body)

    def test_validacao_fora_do_prazo_assinalada(self):
        ev = _evidence(self.occ, self.agent)
        # Ledger imutável (trigger PG): retrodatar = congelar o relógio na
        # criação (o save() força timestamp = timezone.now()).
        backdated = timezone.now() - timedelta(hours=80)
        with mock.patch('core.models.timezone.now', return_value=backdated):
            _event(ev, self.agent, inst=self.opc)
        _event(ev, self.agent, event_type=EventType.VALIDACAO_APREENSAO)
        body = self._get(ev, '?modal=1').content.decode()
        self.assertIn(VALIDATION_LATE_LABEL, body)

    def test_pericia_concluida_explica_prazo_cumprido(self):
        ev = _evidence(self.occ, self.agent)
        make_chain(
            ev,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': self.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
            EventType.INICIO_PERICIA,
            EventType.CONCLUSAO_PERICIA,
        )
        body = self._get(ev, '?modal=1').content.decode()
        self.assertIn('Perícia concluída a', body)
        # Prazo cumprido ⇒ sem badge de estatuto vigente.
        self.assertNotIn('Perícia até', body)

    def test_prazo_extinto_pela_disposicao_explicado(self):
        # A PERDA não fecha o ledger mas extingue o prazo do despacho anterior
        # (regra posicional da policy) — a razão tem de ficar visível.
        ev = _evidence(self.occ, self.agent)
        make_chain(
            ev,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': self.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
            EventType.PERDA_FAVOR_ESTADO,
        )
        body = self._get(ev, '?modal=1').content.decode()
        self.assertIn('extinto pela disposição final', body)
        self.assertNotIn('Perícia até', body)

    def test_item_sem_atos_mostra_vazio(self):
        ev = _evidence(self.occ, self.agent)  # sem eventos no ledger
        body = self._get(ev, '?modal=1').content.decode()
        self.assertIn('Sem atos de autoridade', body)

    # -- Acesso (need-to-know, mesma porta do detalhe) -----------------------

    def test_utilizador_sem_acesso_404(self):
        outra = Institution.objects.create(
            name='GNR Fora', type=InstitutionType.OPC, sigla='GNR-FX'
        )
        estranho = _user('atos_estranho', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=estranho, institution=outra)
        auth_cookie(self.client, estranho)
        r = self.client.get(reverse('evidence_atos', args=[self.ev.id]))
        self.assertEqual(r.status_code, 404)


class AtosBadgesClicaveisTest(TestCase):
    """As superfícies dos badges apontam para a consulta (âncora data-modal-open)."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Badges', type=InstitutionType.OPC, sigla='PSP-BD'
        )
        cls.agent = _user('atos_badges', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'ATOS-2')
        cls.ev = _evidence(cls.occ, cls.agent)
        make_chain(
            cls.ev,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': cls.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
        )
        cls.atos_url = reverse('evidence_atos', args=[cls.ev.id])

    def _get(self, url):
        auth_cookie(self.client, self.agent)
        return self.client.get(url).content.decode()

    def _assert_act_link(self, body):
        self.assertIn(f'href="{self.atos_url}"', body)
        self.assertIn('data-modal-open', body)

    def test_tabela_de_itens_da_ocorrencia(self):
        self._assert_act_link(self._get(f'/occurrences/{self.occ.id}/'))

    def test_ficha_do_item(self):
        body = self._get(f'/evidences/{self.ev.id}/')
        self._assert_act_link(body)
        # Linhas separadas da ficha: validação E despacho apontam ambos.
        self.assertEqual(body.count(f'href="{self.atos_url}"'), 2)

    def test_subtitulo_da_cadeia(self):
        self._assert_act_link(self._get(f'/evidences/{self.ev.id}/custody/'))

    def test_fila_prova_a_chegar(self):
        # O encaminhamento para o laboratório cria o aviso «prova a chegar»
        # (ProvaEmTransito nasce no save do evento); a fila ordena pelo prazo
        # da perícia — o badge tem de abrir a mesma consulta (only_pericia).
        lab = Institution.objects.create(
            name='Lab Badges', type=InstitutionType.LAB_PUBLICO, sigla='LAB-BD'
        )
        perito = _user('atos_perito', User.Profile.FORENSIC_EXPERT)
        InstitutionMembership.objects.create(user=perito, institution=lab)
        _event(
            self.ev, self.agent,
            event_type=EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.LAB_PUBLICO, inst=lab,
            bearer_nome='Rui', bearer_apelido='Faria', bearer_matricula='PSP-77',
        )
        auth_cookie(self.client, perito)
        body = self.client.get('/inbound/').content.decode()
        self._assert_act_link(body)


class AtosGlobaisGridTest(TestCase):
    """Página /atos/ — consulta GLOBAL dos atos certificados (grupo Análise).

    Grelha do gerador único sobre o ledger visível filtrado a
    ``CERTIFIED_ACT_EVENTS``: só validações/despachos, com a autoridade
    estruturada (hv4), o estatuto do prazo derivado por linha (despacho
    vigente/substituído/cumprido/extinto; validação fora do prazo) e a ação
    «Consultar» a abrir o modal único ``/evidences/<id>/atos/``. Mesma porta
    need-to-know das custódias (``_lens_custody``)."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(
            name='PSP Atos Globais', type=InstitutionType.OPC, sigla='PSP-AG'
        )
        cls.agent = _user('atos_grid', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'ATOS-3')
        cls.ev = _evidence(cls.occ, cls.agent)
        make_chain(
            cls.ev,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': cls.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
        )

    def _rows(self, suffix='', user=None):
        auth_cookie(self.client, user or self.agent)
        r = self.client.get('/atos/' + suffix)
        self.assertEqual(r.status_code, 200)
        return r, list(r.context['page_obj'].object_list)

    # -- Âmbito e conteúdo ---------------------------------------------------

    def test_lista_so_atos_certificados(self):
        # A APREENSAO (génese) fica de fora — a grelha é dos ATOS, não do
        # ledger inteiro; os dois atos do item aparecem.
        _, rows = self._rows()
        tipos = [r.event_type for r in rows]
        self.assertEqual(len(rows), 2)
        self.assertTrue(set(tipos) <= set(CERTIFIED_ACT_EVENTS))
        self.assertIn(EventType.VALIDACAO_APREENSAO, tipos)
        self.assertIn(EventType.DESPACHO_PERICIA, tipos)

    def test_linha_decorada_com_autoridade_navegacao_e_prazo(self):
        _, rows = self._rows()
        despacho = next(r for r in rows if r.event_type == EventType.DESPACHO_PERICIA)
        # Autoridade estruturada (hv4): nome (cargo) — fonte única _decorate_events.
        self.assertIn(AUTHORITY_KWARGS['authority_nome'], despacho.authority_label)
        self.assertIn(AUTHORITY_KWARGS['authority_cargo'], despacho.authority_label)
        # Navegações: item → ficha; «Consultar» → modal read-only já existente.
        self.assertEqual(despacho.item_url, f'/evidences/{self.ev.id}/')
        self.assertEqual(despacho.consultar['href'], f'/evidences/{self.ev.id}/atos/')
        self.assertIn(self.ev.code, despacho.consultar['modal_title'])
        # Despacho vigente com o prazo vivo: badge do estatuto (em prazo).
        self.assertIn('Perícia até', despacho.prazo_badge['label'])
        # Validação dentro do prazo: sem estatuto a acrescentar ('—' na célula).
        validacao = next(
            r for r in rows if r.event_type == EventType.VALIDACAO_APREENSAO
        )
        self.assertIsNone(validacao.prazo_badge)

    def test_acao_consultar_abre_modal(self):
        r, _ = self._rows()
        body = r.content.decode()
        # Âncora COMPLETA da ação (atributos adjacentes da célula 'action' do
        # gerador): um assert solto de 'data-modal-open' era vácuo — a string
        # existe num comentário HTML do base.html em qualquer página.
        self.assertIn(
            f'href="/evidences/{self.ev.id}/atos/" '
            f'aria-label="Consultar os atos de {self.ev.code}" '
            f'data-modal-open data-modal-title="Atos de autoridade · {self.ev.code}"',
            body,
        )

    def test_despacho_anterior_fica_substituido(self):
        # Art. 158.º: vale o ÚLTIMO despacho (2.ª perícia) — o anterior deixa
        # de ter prazo a correr e a grelha di-lo, em vez de dois «Perícia até».
        ev = _evidence(self.occ, self.agent)
        d1, d2 = make_chain(
            ev,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': self.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
            EventType.DESPACHO_PERICIA,
        )[2:]
        _, rows = self._rows()
        by_pk = {r.pk: r for r in rows}
        self.assertEqual(by_pk[d1.pk].prazo_badge['label'], DESPACHO_SUBSTITUIDO_LABEL)
        self.assertIn('Perícia até', by_pk[d2.pk].prazo_badge['label'])

    def test_prazo_cumprido_e_extinto(self):
        cumprida = _evidence(self.occ, self.agent)
        make_chain(
            cumprida,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': self.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
            EventType.INICIO_PERICIA,
            EventType.CONCLUSAO_PERICIA,
        )
        extinta = _evidence(self.occ, self.agent)
        make_chain(
            extinta,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': self.opc}),
            EventType.VALIDACAO_APREENSAO,
            EventType.DESPACHO_PERICIA,
            EventType.PERDA_FAVOR_ESTADO,
        )
        _, rows = self._rows()
        labels = {
            r.evidence_id: r.prazo_badge['label']
            for r in rows if r.event_type == EventType.DESPACHO_PERICIA
        }
        self.assertEqual(labels[cumprida.id], PRAZO_RESOLVIDO_LABELS['cumprido'])
        self.assertEqual(labels[extinta.id], PRAZO_RESOLVIDO_LABELS['extinto'])

    def test_validacao_fora_do_prazo_assinalada(self):
        ev = _evidence(self.occ, self.agent)
        # Retrodatar = congelar o relógio na criação (ledger imutável, trigger PG).
        backdated = timezone.now() - timedelta(hours=80)
        with mock.patch('core.models.timezone.now', return_value=backdated):
            _event(ev, self.agent, inst=self.opc)
        tarde = _event(ev, self.agent, event_type=EventType.VALIDACAO_APREENSAO)
        _, rows = self._rows()
        linha = next(r for r in rows if r.pk == tarde.pk)
        self.assertEqual(linha.prazo_badge['label'], VALIDATION_LATE_LABEL)

    # -- Filtros e export ------------------------------------------------------

    def test_filtro_por_ato(self):
        _, rows = self._rows('?ato=DESPACHO_PERICIA')
        self.assertTrue(rows)
        self.assertTrue(
            all(r.event_type == EventType.DESPACHO_PERICIA for r in rows)
        )

    def test_filtro_autoridade_discrimina_por_nome_ou_cargo(self):
        # 2.ª autoridade noutro ato — o filtro tem de DISCRIMINAR (excluir as
        # linhas não-correspondentes), e os ramos NOME e CARGO do OR
        # multi-campo exercem-se em separado (a busca global idem).
        ev = _evidence(self.occ, self.agent)
        make_chain(
            ev,
            (EventType.APREENSAO_OBJETO, {'custodian_institution': self.opc}),
            (EventType.VALIDACAO_APREENSAO,
             {'authority_nome': 'Rui Pires Andrade',
              'authority_cargo': 'Juiz de Instrução Criminal'}),
        )
        # Ramo do NOME: só os 2 atos da autoridade canónica correspondem.
        _, rows = self._rows('?autoridade=Helena')
        self.assertEqual(
            [r.authority_nome for r in rows],
            [AUTHORITY_KWARGS['authority_nome']] * 2,
        )
        # Ramo do CARGO: só o ato da 2.ª autoridade corresponde.
        _, rows = self._rows('?autoridade=Juiz')
        self.assertEqual([r.authority_nome for r in rows], ['Rui Pires Andrade'])
        # Busca global ?q= cobre o MESMO par nome/cargo do filtro de coluna.
        _, rows = self._rows('?q=Sousa Martins')
        self.assertEqual(len(rows), 2)
        _, rows = self._rows('?q=Juiz de Instrução')
        self.assertEqual([r.authority_nome for r in rows], ['Rui Pires Andrade'])
        _, rows = self._rows('?autoridade=ninguém-com-este-nome')
        self.assertEqual(rows, [])

    def test_csv_export_auditado(self):
        auth_cookie(self.client, self.agent)
        r = self.client.get('/atos/?export=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        body = r.content.decode()
        self.assertIn('Autoridade', body)
        self.assertIn(AUTHORITY_KWARGS['authority_nome'], body)
        # Extração massiva fica no trilho (EXPORT_CSV com o âmbito da grelha).
        log = AuditLog.objects.filter(action=AuditLog.Action.EXPORT_CSV).latest('id')
        self.assertEqual(log.details.get('grid'), 'atos')

    # -- Acesso (need-to-know, mesma porta das custódias) ----------------------

    def test_utilizador_sem_ambito_nao_ve_atos(self):
        outra = Institution.objects.create(
            name='GNR Fora Globais', type=InstitutionType.OPC, sigla='GNR-FG'
        )
        estranho = _user('atos_grid_estranho', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=estranho, institution=outra)
        _, rows = self._rows(user=estranho)
        self.assertEqual(rows, [])

    def test_lente_institucional_da_acesso_ao_colega(self):
        # Colega da MESMA instituição (não titular): a zona pessoal não mostra
        # nada; a zona Instituição mostra os atos do processo em que a PSP-AG
        # teve custódia. Exercita as DUAS lentes — ancora a escolha da lente
        # na view (um âmbito fixo em qualquer das direções rebenta aqui).
        colega = _user('atos_grid_colega', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=colega, institution=self.opc)
        _, rows = self._rows(user=colega)
        self.assertEqual(rows, [])
        _, rows = self._rows('?lens=institution', user=colega)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.evidence_id for r in rows}, {self.ev.id})

    def test_entrada_na_sidebar(self):
        auth_cookie(self.client, self.agent)
        body = self.client.get('/dashboard/').content.decode()
        self.assertIn('href="/atos/', body)
        self.assertIn('Atos de autoridade', body)
