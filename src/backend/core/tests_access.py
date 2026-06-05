"""
ForensiQ — Testes do controlo de acesso *need-to-know* (ADR-0017).

Cobre as famílias 6–8 da estratégia de testes do modelo v2:
6. Acesso item-level (titular / teve-custódia / membro-instituição / NACIONAL).
7. Escrita por custódio (detém / claim institucional / perito override / despacho).
8. Credencial vs função (FORENSIC_EXPERT NORMAL não vê tudo; NACIONAL vê tudo).

Testa diretamente as funções de :mod:`core.access` (mais rápido e legível que
via HTTP); o gating HTTP é exercitado em tests_api.
"""

from django.test import TestCase
from django.utils import timezone

from core import access
from core.models import (
    ChainOfCustody,
    EventType,
    Evidence,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Occurrence,
    User,
)
from core.tests_factories import CrimeTipoFactory


def _user(username, profile, clearance=User.Clearance.NORMAL):
    return User.objects.create_user(
        username=username,
        password='TestPass123!',
        profile=profile,
        clearance=clearance,
    )


def _occ(agent, n):
    return Occurrence.objects.create(
        number=f'NUIPC-ACC-{n}',
        crime_type=CrimeTipoFactory(),
        description='caso de teste de acesso',
        date_time=timezone.now(),
        agent=agent,
    )


def _evidence(occ, agent, etype=Evidence.EvidenceType.MOBILE_DEVICE, parent=None):
    return Evidence.objects.create(
        occurrence=occ,
        type=etype,
        description='item de teste',
        timestamp_seizure=timezone.now(),
        agent=agent,
        parent_evidence=parent,
    )


def _event(ev, agent, *, event_type=EventType.APREENSAO_OBJETO, inst=None, holder=None):
    return ChainOfCustody.objects.create(
        evidence=ev,
        event_type=event_type,
        agent=agent,
        custodian_institution=inst,
        custodian_user=holder,
    )


class AccessReadItemLevelTest(TestCase):
    """Família 6 — leitura item-level (ADR-0017 §5)."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP X', type=InstitutionType.OPC, sigla='PSP-X')
        cls.lab = Institution.objects.create(
            name='Lab Y', type=InstitutionType.LAB_PUBLICO, sigla='LAB-Y'
        )
        cls.titular = _user('acc_titular', User.Profile.FIRST_RESPONDER)
        cls.perito_nac = _user('acc_perito_nac', User.Profile.FORENSIC_EXPERT, User.Clearance.NACIONAL)
        cls.perito_norm = _user('acc_perito_norm', User.Profile.FORENSIC_EXPERT)
        cls.lab_membro = _user('acc_labmembro', User.Profile.EVIDENCE_CUSTODIAN)
        cls.estranho = _user('acc_estranho', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.lab_membro, institution=cls.lab)

        cls.occ = _occ(cls.titular, '6')
        cls.ev = _evidence(cls.occ, cls.titular)
        # Génese pelo titular, à guarda do OPC.
        _event(cls.ev, cls.titular, inst=cls.opc)
        # Transferência registada pelo lab (a instituição lab toca no item).
        _event(
            cls.ev,
            cls.perito_nac,
            event_type=EventType.TRANSFERENCIA_CUSTODIA,
            inst=cls.lab,
        )

    def test_titular_ve_o_item(self):
        self.assertTrue(access.can_view_evidence(self.titular, self.ev))
        self.assertIn(self.ev, access.scope_evidences(self.titular))

    def test_nacional_ve_tudo(self):
        self.assertTrue(access.can_view_evidence(self.perito_nac, self.ev))
        self.assertIn(self.ev, access.scope_evidences(self.perito_nac))

    def test_membro_instituicao_custodia_ve_o_item(self):
        # O lab foi custodian_institution num evento → membro do lab vê o item.
        self.assertTrue(access.can_view_evidence(self.lab_membro, self.ev))
        self.assertIn(self.ev, access.scope_evidences(self.lab_membro))

    def test_estranho_nao_ve(self):
        self.assertFalse(access.can_view_evidence(self.estranho, self.ev))
        self.assertNotIn(self.ev, access.scope_evidences(self.estranho))

    def test_perito_normal_ve_tudo_por_funcao(self):
        # DECISÃO do dono (2026-06-05): o PERITO FORENSE tem leitura total por
        # FUNÇÃO (pode ser questionado sobre processos de outras áreas/divisões),
        # independentemente da credencial. Exceção explícita ao princípio geral
        # «a credencial governa a leitura» — ver access.has_full_read.
        self.assertTrue(access.can_view_evidence(self.perito_norm, self.ev))
        self.assertIn(self.ev, access.scope_evidences(self.perito_norm))

    def test_ex_custodio_ve_item_mas_nao_a_ocorrencia(self):
        # O membro do lab vê o ITEM mas NÃO a ocorrência inteira (least privilege).
        self.assertTrue(access.can_view_evidence(self.lab_membro, self.ev))
        self.assertNotIn(self.occ, access.scope_occurrences(self.lab_membro))


class AccessWriteTest(TestCase):
    """Família 7 — escrita por custódio (ADR-0017 §5)."""

    @classmethod
    def setUpTestData(cls):
        cls.lab = Institution.objects.create(
            name='Lab W', type=InstitutionType.LAB_PUBLICO, sigla='LAB-W'
        )
        cls.titular = _user('w_titular', User.Profile.FIRST_RESPONDER)
        cls.detentor = _user('w_detentor', User.Profile.EVIDENCE_CUSTODIAN)
        cls.lab_membro = _user('w_labmembro', User.Profile.EVIDENCE_CUSTODIAN)
        cls.perito = _user('w_perito', User.Profile.FORENSIC_EXPERT, User.Clearance.NACIONAL)
        cls.chefe = _user('w_chefe', User.Profile.CHEFE_SERVICO, User.Clearance.NACIONAL)
        cls.auditor = _user('w_auditor', User.Profile.AUDITOR, User.Clearance.NACIONAL)
        InstitutionMembership.objects.create(user=cls.lab_membro, institution=cls.lab)
        InstitutionMembership.objects.create(user=cls.detentor, institution=cls.lab)

        cls.occ = _occ(cls.titular, '7')
        cls.ev = _evidence(cls.occ, cls.titular)

    def test_titular_abre_a_cadeia(self):
        # Sem eventos ainda: o titular abre a génese.
        self.assertTrue(access.can_append_custody(self.titular, self.ev))

    def test_detentor_pessoal_pode_escrever(self):
        _event(self.ev, self.titular, holder=self.detentor, inst=self.lab)
        self.assertTrue(access.can_append_custody(self.detentor, self.ev))

    def test_membro_assume_custodia_institucional(self):
        # Item em armazenamento institucional (holder None, instituição = lab).
        _event(self.ev, self.titular, inst=self.lab)
        self.assertTrue(
            access.can_append_custody(self.lab_membro, self.ev, EventType.ASSUNCAO_CUSTODIA)
        )

    def test_perito_override(self):
        _event(self.ev, self.titular, inst=self.lab)
        self.assertTrue(access.can_append_custody(self.perito, self.ev))

    def test_chefe_e_auditor_nunca_escrevem(self):
        _event(self.ev, self.titular, inst=self.lab)
        self.assertFalse(access.can_append_custody(self.chefe, self.ev))
        self.assertFalse(access.can_append_custody(self.auditor, self.ev))

    def test_readonly_com_is_staff_continua_sem_escrever(self):
        # REGRESSÃO: o bypass de is_staff NÃO se pode sobrepor ao perfil só-leitura.
        # profile e is_staff são ortogonais; um CHEFE/AUDITOR a quem se dê acesso
        # de staff no admin continua impedido de escrever (READ_ONLY corre primeiro).
        _event(self.ev, self.titular, inst=self.lab)
        chefe_staff = _user('w_chefe_staff', User.Profile.CHEFE_SERVICO, User.Clearance.NACIONAL)
        chefe_staff.is_staff = True
        chefe_staff.save(update_fields=['is_staff'])
        auditor_staff = _user('w_auditor_staff', User.Profile.AUDITOR)
        auditor_staff.is_staff = True
        auditor_staff.save(update_fields=['is_staff'])
        self.assertFalse(access.can_append_custody(chefe_staff, self.ev))
        self.assertFalse(access.can_append_custody(auditor_staff, self.ev))


class AccessCredentialVsFunctionTest(TestCase):
    """Família 8 — credencial governa a leitura; função governa a escrita.

    EXCEÇÃO (decisão do dono, 2026-06-05): a função PERITO FORENSE é, ela própria,
    habilitante para leitura total (ver :func:`core.access.has_full_read`).
    """

    @classmethod
    def setUpTestData(cls):
        cls.titular = _user('c_titular', User.Profile.FIRST_RESPONDER)
        cls.perito_norm = _user('c_perito_norm', User.Profile.FORENSIC_EXPERT)
        cls.chefe_nac = _user('c_chefe_nac', User.Profile.CHEFE_SERVICO, User.Clearance.NACIONAL)
        cls.occ = _occ(cls.titular, '8')
        cls.ev = _evidence(cls.occ, cls.titular)
        _event(cls.ev, cls.titular)

    def test_perito_normal_ve_tudo_por_funcao(self):
        # Perito forense (mesmo NORMAL) tem leitura total por função — decisão do
        # dono (2026-06-05). A credencial governa a leitura dos RESTANTES perfis.
        self.assertTrue(access.can_view_evidence(self.perito_norm, self.ev))

    def test_chefe_nacional_ve_tudo_mas_nao_escreve(self):
        self.assertTrue(access.can_view_evidence(self.chefe_nac, self.ev))
        self.assertFalse(access.can_append_custody(self.chefe_nac, self.ev))


class AccessLensTest(TestCase):
    """Lentes de acesso (consolas por papel) — eixos de leitura expostos na UI.

    Cobre o ramo custodial (subconjunto estrito de :func:`scope_evidences`, sem
    curto-circuito de leitura total) e a matriz lente×papel×credencial.
    """

    @classmethod
    def setUpTestData(cls):
        cls.lab = Institution.objects.create(
            name='Lab L', type=InstitutionType.LAB_PUBLICO, sigla='LAB-L'
        )
        cls.opc = Institution.objects.create(
            name='PSP L', type=InstitutionType.OPC, sigla='PSP-L'
        )

        # Um utilizador por papel × credencial (12 combinações).
        cls.responder = _user('lns_responder', User.Profile.FIRST_RESPONDER)
        cls.responder_nac = _user(
            'lns_responder_nac', User.Profile.FIRST_RESPONDER, User.Clearance.NACIONAL
        )
        cls.custodian = _user('lns_custodian', User.Profile.EVIDENCE_CUSTODIAN)
        cls.custodian_nac = _user(
            'lns_custodian_nac', User.Profile.EVIDENCE_CUSTODIAN, User.Clearance.NACIONAL
        )
        cls.perito_norm = _user('lns_perito_norm', User.Profile.FORENSIC_EXPERT)
        cls.perito_nac = _user(
            'lns_perito_nac', User.Profile.FORENSIC_EXPERT, User.Clearance.NACIONAL
        )
        cls.mp = _user('lns_mp', User.Profile.CASE_AUTHORITY)
        cls.mp_nac = _user('lns_mp_nac', User.Profile.CASE_AUTHORITY, User.Clearance.NACIONAL)
        cls.chefe_norm = _user('lns_chefe_norm', User.Profile.CHEFE_SERVICO)
        cls.chefe_nac = _user('lns_chefe_nac', User.Profile.CHEFE_SERVICO, User.Clearance.NACIONAL)
        cls.auditor_norm = _user('lns_auditor_norm', User.Profile.AUDITOR)
        cls.auditor_nac = _user('lns_auditor_nac', User.Profile.AUDITOR, User.Clearance.NACIONAL)
        InstitutionMembership.objects.create(user=cls.custodian, institution=cls.lab)

        cls.all_users = [
            cls.responder, cls.responder_nac, cls.custodian, cls.custodian_nac,
            cls.perito_norm, cls.perito_nac, cls.mp, cls.mp_nac,
            cls.chefe_norm, cls.chefe_nac, cls.auditor_norm, cls.auditor_nac,
        ]

        cls.occ = _occ(cls.responder, 'L1')
        # Item à GUARDA do lab: génese pelo titular + transferência registada pelo
        # custódio (o lab é custodian_institution) → ramo custodial.
        cls.ev_held = _evidence(cls.occ, cls.responder)
        _event(cls.ev_held, cls.responder, inst=cls.opc)
        _event(
            cls.ev_held,
            cls.custodian,
            event_type=EventType.TRANSFERENCIA_CUSTODIA,
            inst=cls.lab,
        )
        # Item SÓ por titularidade (sem eventos) — visível por scope_evidences
        # (titular) mas FORA do ramo custodial. Testemunha do subconjunto estrito.
        cls.ev_owned_only = _evidence(cls.occ, cls.responder)

    # -- Ramo custodial -----------------------------------------------------

    def test_custodial_e_subconjunto_estrito(self):
        # Para o titular, o item só-por-titularidade está em scope_evidences mas
        # NÃO no ramo custodial → custodial ⊊ scope_evidences.
        self.assertIn(self.ev_owned_only, access.scope_evidences(self.responder))
        self.assertNotIn(self.ev_owned_only, access.scope_evidences_custodial(self.responder))
        for u in (self.responder, self.custodian):
            full = set(access.scope_evidences(u))
            custodial = set(access.scope_evidences_custodial(u))
            self.assertTrue(custodial.issubset(full))

    def test_custodial_inclui_item_a_guarda(self):
        # O custódio (membro do lab que tocou no item) vê o item no ramo custodial.
        self.assertIn(self.ev_held, access.scope_evidences_custodial(self.custodian))

    def test_custodial_nao_curtocircuita_full_read(self):
        # Perito (leitura total) que não detém nada nem pertence a instituição
        # custodial vê o ramo custodial VAZIO — apesar de scope_evidences ser tudo.
        for perito in (self.perito_norm, self.perito_nac):
            self.assertIn(self.ev_held, access.scope_evidences(perito))
            self.assertEqual(list(access.scope_evidences_custodial(perito)), [])

    def test_custodial_anonimo_vazio(self):
        from django.contrib.auth.models import AnonymousUser

        anon = AnonymousUser()
        self.assertEqual(list(access.scope_evidences_custodial(anon)), [])
        self.assertEqual(list(access.scope_custody_custodial(anon)), [])

    def test_custody_custodial_subconjunto(self):
        full = set(access.scope_custody(self.custodian))
        custodial = set(access.scope_custody_custodial(self.custodian))
        self.assertTrue(custodial.issubset(full))
        self.assertTrue(len(custodial) >= 1)

    # -- Matriz de lentes ---------------------------------------------------

    def test_available_lenses_nunca_vazio(self):
        for u in self.all_users:
            self.assertTrue(access.available_lenses(u), f'{u.username} sem lentes')

    def test_default_lens_in_available(self):
        for u in self.all_users:
            self.assertIn(
                access.default_lens(u),
                access.available_lenses(u),
                f'default fora de available para {u.username}',
            )

    def test_default_lens_por_papel(self):
        casos = {
            self.responder: access.Lens.MINE,
            self.responder_nac: access.Lens.MINE,
            self.custodian: access.Lens.CUSTODY,
            self.custodian_nac: access.Lens.CUSTODY,
            self.perito_norm: access.Lens.ALL,
            self.perito_nac: access.Lens.ALL,
            self.mp: access.Lens.MINE,
            self.mp_nac: access.Lens.MINE,
            self.chefe_norm: access.Lens.CUSTODY,
            self.chefe_nac: access.Lens.ALL,
            self.auditor_norm: access.Lens.CUSTODY,
            self.auditor_nac: access.Lens.ALL,
        }
        for u, esperado in casos.items():
            self.assertEqual(access.default_lens(u), esperado, u.username)

    def test_can_use_lens_all_iff_full_read(self):
        for u in self.all_users:
            self.assertEqual(
                access.can_use_lens(u, access.Lens.ALL),
                access.has_full_read(u),
                u.username,
            )

    def test_can_use_lens_mine_nega_readonly(self):
        for u in (self.chefe_norm, self.chefe_nac, self.auditor_norm, self.auditor_nac):
            self.assertFalse(access.can_use_lens(u, access.Lens.MINE), u.username)

    def test_resolve_lens_fallback(self):
        # Lente proibida / inválida / ausente → default; permitida → respeitada.
        self.assertEqual(access.resolve_lens(self.responder, 'all'), access.Lens.MINE)
        self.assertEqual(access.resolve_lens(self.responder, 'bogus'), access.Lens.MINE)
        self.assertEqual(access.resolve_lens(self.responder, None), access.Lens.MINE)
        self.assertEqual(access.resolve_lens(self.responder, 'custody'), access.Lens.CUSTODY)
        self.assertEqual(access.resolve_lens(self.perito_norm, 'all'), access.Lens.ALL)
