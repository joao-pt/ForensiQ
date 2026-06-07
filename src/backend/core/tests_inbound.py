"""ForensiQ — Testes: caixa "prova a chegar" (inbound, 2.ª metade do handoff v2).

Modelo de domínio: depois de encaminhada (em lote, a um portador, com destino), a prova
fica EM TRÂNSITO e gera um aviso ``ProvaEmTransito`` dirigido à instituição de destino.
A caixa "/inbound/" mostra esses avisos por receber e liga ao intake da ocorrência
(onde se regista a RECEÇÃO). É institucional: chaveia no DESTINO, não no detentor.

Os avisos são criados pelo fluxo HTTP REAL de encaminhamento (não fabricados), para
exercer o caminho ponta-a-ponta encaminhar→chegar.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from core.auth import ACCESS_COOKIE_NAME
from core.context_processors import inbound_nav
from core.models import (
    Institution,
    InstitutionMembership,
    InstitutionType,
    Portador,
    ProvaEmTransito,
)
from core.tests_access import _event, _evidence, _occ, _user

User = get_user_model()


class InboundCaixaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP In', type=InstitutionType.OPC, sigla='PSP-IN')
        cls.opc2 = Institution.objects.create(name='PJ In', type=InstitutionType.OPC, sigla='PJ-IN')
        cls.opc3 = Institution.objects.create(name='GNR In', type=InstitutionType.OPC, sigla='GNR-IN')
        # Agente que apreende e encaminha (membro do OPC de origem).
        cls.agent = _user('in_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        # Recetor: membro da instituição de DESTINO — é quem vê a caixa.
        cls.receiver = _user('in_receiver', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.receiver, institution=cls.opc2)
        cls.portador = Portador.objects.create(
            matricula='ENC-P-001', nome='Ana', apelido='Silva', posto='Agente principal'
        )
        cls.occ = _occ(cls.agent, 'IN-1')
        # Dois itens à guarda do OPC (génese feita) → encamináveis.
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)

    def _auth(self, user):
        self.client.cookies[ACCESS_COOKIE_NAME] = str(AccessToken.for_user(user))

    def _seed_notices(self):
        """Encaminha ev1+ev2 para opc2 pelo fluxo HTTP real → 2 avisos a chegar."""
        self._auth(self.agent)
        r = self.client.post(
            f'/occurrences/{self.occ.id}/encaminhar/',
            {
                'modal': '1',
                'evidence_ids': [self.ev1.id, self.ev2.id],
                'bearer': self.portador.id,
                'custodian_institution': self.opc2.id,
            },
        )
        self.assertEqual(r.status_code, 204)
        self.assertEqual(
            ProvaEmTransito.objects.filter(
                destino_institution=self.opc2, acknowledged_at__isnull=True
            ).count(),
            2,
        )

    # -- Listagem -------------------------------------------------------------

    def test_inbox_lista_avisos_para_membro_do_destino(self):
        self._seed_notices()
        self._auth(self.receiver)
        body = self.client.get('/inbound/').content.decode()
        self.assertIn(self.ev1.code, body)
        self.assertIn(self.ev2.code, body)
        # Liga ao intake (receber) da ocorrência — fecha o ciclo.
        self.assertIn(f'/occurrences/{self.occ.id}/intake/', body)
        # Portador vem do snapshot gravado na cadeia (nome + matrícula).
        self.assertIn('Ana Silva', body)
        self.assertIn('ENC-P-001', body)

    # -- Receber: o ciclo fecha de facto --------------------------------------

    def test_receiver_opc_abre_intake_e_fecha_o_ciclo(self):
        """O membro do destino (OPC, FIRST_RESPONDER — não perito) ABRE o intake
        (200, não 403) e a receção em lote limpa a caixa "prova a chegar". É a prova
        de que encaminhar→chegar→receber fecha para o público-alvo da caixa."""
        self._seed_notices()
        self._auth(self.receiver)
        # Abrir o formulário de receção — antes do fix dava 403 a um FIRST_RESPONDER.
        r = self.client.get(f'/occurrences/{self.occ.id}/intake/')
        self.assertEqual(r.status_code, 200)
        # Receber os dois itens em trânsito (lote atómico).
        r2 = self.client.post(
            f'/occurrences/{self.occ.id}/intake/',
            {'evidence_ids': [self.ev1.id, self.ev2.id], 'location_name': 'Receção PJ'},
        )
        self.assertEqual(r2.status_code, 302)
        # Avisos reconhecidos pela receção → caixa vazia.
        self.assertFalse(
            ProvaEmTransito.objects.filter(
                destino_institution=self.opc2, acknowledged_at__isnull=True
            ).exists()
        )
        body = self.client.get('/inbound/').content.decode()
        self.assertIn('Nada a chegar', body)

    def test_intake_403_para_membro_de_outra_instituicao(self):
        """A porta alargada NÃO é livre: um FIRST_RESPONDER de outra instituição (sem
        prova a chegar nesta ocorrência) continua a receber 403 no intake."""
        self._seed_notices()  # destino = opc2
        other = _user('in_intake_other', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=other, institution=self.opc3)
        self._auth(other)
        r = self.client.get(f'/occurrences/{self.occ.id}/intake/')
        self.assertEqual(r.status_code, 403)

    # -- Scope institucional --------------------------------------------------

    def test_inbox_nao_mostra_destino_de_outra_instituicao(self):
        self._seed_notices()  # tudo para opc2
        other = _user('in_other', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=other, institution=self.opc3)
        self._auth(other)
        body = self.client.get('/inbound/').content.decode()
        self.assertNotIn(self.ev1.code, body)
        self.assertIn('Nada a chegar', body)

    def test_inbox_vazio_para_nao_membro(self):
        self._seed_notices()
        loner = _user('in_loner', User.Profile.FORENSIC_EXPERT)  # leitura total, sem pertença
        self._auth(loner)
        body = self.client.get('/inbound/').content.decode()
        self.assertNotIn(self.ev1.code, body)
        self.assertIn('Nada a chegar', body)

    # -- Resolução (receção/ack) ----------------------------------------------

    def test_inbox_exclui_avisos_reconhecidos(self):
        self._seed_notices()
        # ProvaEmTransito é MUTÁVEL (sem trigger de imutabilidade) — receber/ack
        # carimba acknowledged_at e o aviso sai da caixa.
        ProvaEmTransito.objects.filter(destino_institution=self.opc2).update(
            acknowledged_at=timezone.now()
        )
        self._auth(self.receiver)
        body = self.client.get('/inbound/').content.decode()
        self.assertNotIn(self.ev1.code, body)
        self.assertIn('Nada a chegar', body)

    # -- Context processor (badge da casca) -----------------------------------

    def test_context_processor_conta_para_membro(self):
        self._seed_notices()
        req = RequestFactory().get('/dashboard/')
        req.user = self.receiver
        ctx = inbound_nav(req)
        self.assertTrue(ctx.get('inbound_member'))
        self.assertEqual(ctx.get('inbound_count'), 2)

    def test_context_processor_vazio_para_nao_membro_e_anonimo(self):
        self._seed_notices()
        rf = RequestFactory()
        loner = _user('in_cp_loner', User.Profile.FORENSIC_EXPERT)
        req = rf.get('/dashboard/')
        req.user = loner
        self.assertEqual(inbound_nav(req), {})
        anon_req = rf.get('/dashboard/')
        anon_req.user = AnonymousUser()
        self.assertEqual(inbound_nav(anon_req), {})

    # -- Integração casca (sidebar) ------------------------------------------

    def test_sidebar_mostra_link_e_badge_para_membro(self):
        self._seed_notices()
        self._auth(self.receiver)
        body = self.client.get('/dashboard/').content.decode()
        self.assertIn('/inbound/', body)
        self.assertIn('Prova a chegar', body)
        self.assertIn('app-sidebar__badge', body)

    def test_sidebar_esconde_link_para_nao_membro(self):
        loner = _user('in_sb_loner', User.Profile.FORENSIC_EXPERT)
        self._auth(loner)
        body = self.client.get('/dashboard/').content.decode()
        self.assertNotIn('Prova a chegar', body)
