"""ForensiQ — Testes de view da CONSOLA (duas zonas) + Arquivo.

A consola (substitui a antiga lente de 3 eixos por papel) tem duas zonas: "as
minhas" (âmbito de caso pessoal) e "Instituição" (processo inteiro da instituição,
só para membros). Exercita: a renderização condicional do seletor (≥2 zonas), a
mudança de cor (``data-console-mode``), o fallback silencioso das zonas antigas,
o acesso institucional ao processo inteiro e a separação ativo/arquivo.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.models import (
    EventType,
    Institution,
    InstitutionMembership,
    InstitutionType,
)
from core.tests_base import auth_cookie
from core.tests_factories import (
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)

User = get_user_model()


class ConsoleFrontendTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lab = Institution.objects.create(
            name='Lab C', type=InstitutionType.LAB_PUBLICO, sigla='LAB-C'
        )
        cls.opc = Institution.objects.create(
            name='PSP C', type=InstitutionType.OPC, sigla='PSP-C'
        )
        # Titular (sem pertença) e membro do lab (custódio, sem titularidade).
        cls.responder = cls._u('cf_responder', User.Profile.FIRST_RESPONDER)
        cls.member = cls._u('cf_member', User.Profile.EVIDENCE_CUSTODIAN)
        InstitutionMembership.objects.create(user=cls.member, institution=cls.lab)

        # Processo ATIVO: item à guarda do lab (génese pelo titular + movimentação
        # registada com o lab como custodian_institution) — não terminal.
        cls.occ_active = _occ(cls.responder, 'C-ATIVO')
        cls.ev_a = _evidence(cls.occ_active, cls.responder)
        _event(cls.ev_a, cls.responder, inst=cls.opc)  # APREENSAO_OBJETO
        _event(cls.ev_a, cls.responder, event_type=EventType.TRANSFERENCIA_CUSTODIA, inst=cls.lab)
        # Item-IRMÃO no mesmo processo que o lab NUNCA custodiou (só @opc): o membro
        # deve poder abri-lo (processo inteiro), embora fora do seu need-to-know item.
        cls.ev_b = _evidence(cls.occ_active, cls.responder)
        _event(cls.ev_b, cls.responder, inst=cls.opc)  # APREENSAO_OBJETO @opc

        # Processo ARQUIVADO: único item em estado terminal (restituído).
        cls.occ_arch = _occ(cls.responder, 'C-ARQUIVO')
        ev_x = _evidence(cls.occ_arch, cls.responder)
        _event(ev_x, cls.responder, inst=cls.opc)  # APREENSAO_OBJETO
        _event(ev_x, cls.responder, event_type=EventType.RESTITUICAO, inst=cls.opc)

    @classmethod
    def _u(cls, username, profile):
        return _user(username, profile)

    def _get(self, user, url):
        auth_cookie(self.client, user)
        return self.client.get(url)

    # -- Seletor de consola -------------------------------------------------

    def test_membro_tem_consola_duas_zonas(self):
        body = self._get(self.member, '/occurrences/').content.decode()
        self.assertIn('class="lens-bar"', body)
        self.assertIn('href="?lens=mine"', body)
        self.assertIn('href="?lens=institution"', body)
        self.assertIn('Instituição', body)

    def test_nao_membro_sem_seletor(self):
        # Sem pertença → só a zona "as minhas" → seletor escondido (<2 zonas).
        body = self._get(self.responder, '/occurrences/').content.decode()
        self.assertNotIn('class="lens-bar"', body)

    def test_zona_antiga_cai_em_mine_sem_500(self):
        # Os valores antigos ('all'/'custody') já não existem → fallback em mine.
        for old in ('all', 'custody', 'bogus'):
            r = self._get(self.member, f'/occurrences/?lens={old}')
            self.assertEqual(r.status_code, 200, old)
            self.assertIn('data-console-mode="mine"', r.content.decode())

    # -- Mudança de cor (modo Instituição) ----------------------------------

    def test_modo_instituicao_muda_cor(self):
        body = self._get(self.member, '/occurrences/?lens=institution').content.decode()
        self.assertIn('data-console-mode="institution"', body)

    def test_modo_mine_por_omissao(self):
        body = self._get(self.member, '/occurrences/').content.decode()
        self.assertIn('data-console-mode="mine"', body)

    # -- Zona Instituição = processo inteiro --------------------------------

    def test_instituicao_ve_processo_sem_ser_titular(self):
        # O membro não é titular; em "as minhas" não vê o processo, mas na zona
        # Instituição vê-o (a instituição é dona do processo).
        mine = self._get(self.member, '/occurrences/?lens=mine').content.decode()
        inst = self._get(self.member, '/occurrences/?lens=institution').content.decode()
        self.assertNotIn(f'data-id="{self.occ_active.id}"', mine)
        self.assertIn(f'data-id="{self.occ_active.id}"', inst)

    def test_membro_abre_detalhe_por_pertenca(self):
        # Clicar numa linha da zona Instituição abre o processo (não 404).
        r = self._get(self.member, f'/occurrences/{self.occ_active.id}/')
        self.assertEqual(r.status_code, 200)

    def test_membro_abre_item_irmao_que_a_instituicao_nunca_teve(self):
        # ev_b é item-irmão que o lab nunca custodiou. Como o membro lê o PROCESSO
        # inteiro (a instituição é dona), o detalhe/timeline de ev_b abrem
        # (sem o clicável-para-404 que existiria com gate só item-level).
        self.assertEqual(self._get(self.member, f'/evidences/{self.ev_b.id}/').status_code, 200)
        self.assertEqual(
            self._get(self.member, f'/evidences/{self.ev_b.id}/custody/').status_code, 200
        )

    def test_link_antigo_de_drawer_redireciona_para_o_detalhe(self):
        # Cortesia de migração: o painel lateral foi removido; um link antigo
        # ?drawer=<id> cai na página de detalhe equivalente.
        r = self._get(self.member, f'/evidences/?drawer={self.ev_b.id}')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'/evidences/{self.ev_b.id}/')

    def test_estranho_nao_abre_item(self):
        # Deny-side intacto: um custódio sem pertença nem titularidade → 404.
        estranho = self._u('cf_estranho', User.Profile.EVIDENCE_CUSTODIAN)
        self.assertEqual(self._get(estranho, f'/evidences/{self.ev_b.id}/').status_code, 404)

    # -- Arquivo ------------------------------------------------------------

    def test_lista_ativa_exclui_arquivados(self):
        body = self._get(self.responder, '/occurrences/').content.decode()
        self.assertIn(f'data-id="{self.occ_active.id}"', body)
        self.assertNotIn(f'data-id="{self.occ_arch.id}"', body)

    def test_arquivo_mostra_so_concluidos(self):
        body = self._get(self.responder, '/arquivo/').content.decode()
        self.assertIn(f'data-id="{self.occ_arch.id}"', body)
        self.assertNotIn(f'data-id="{self.occ_active.id}"', body)
