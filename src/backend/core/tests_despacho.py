"""ForensiQ — Testes: despacho para perícia em LOTE a partir da ocorrência.

Modelo de domínio (CPP art. 154.º): o despacho é um ATO de autoridade, não uma
deslocação — regista a AUTORIDADE que ordenou a perícia (nome/cargo), a data
declarada do despacho e o PRAZO fixado para a perícia (dias) em campos
ESTRUTURADOS (hv4, entram na fórmula do hash), sem GPS nem mudança de custódio
(herdado do último evento). O ``timestamp`` do evento é sempre o do servidor;
``observations`` leva só a referência/justificação livre. A maquinaria é a
MESMA da validação (modal único dos atos certificados, ``_CERTIFIED_ACT_SPECS``);
o despacho é repetível (2.ª perícia — Art. 158.º).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from core.models import (
    ChainOfCustody,
    CustodianType,
    EventType,
    Institution,
    InstitutionMembership,
    InstitutionType,
)
from core.tests_base import BaseAPITestCase, auth_cookie
from core.tests_factories import (
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)
from core.utils import legal_state_of, sort_custody_chain

User = get_user_model()


def _dtl(dt):
    """Valor de um input ``datetime-local`` (YYYY-MM-DDTHH:MM) em hora local."""
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


class DespacharLoteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Dsp', type=InstitutionType.OPC, sigla='PSP-DS')
        cls.agent = _user('dsp_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'DSP-1')
        # Dois itens despacháveis JÁ (apreensão validada — CPP 178.º/5-6).
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        _event(cls.ev1, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)
        _event(cls.ev2, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)
        # Item com apreensão POR VALIDAR: só despachável incluindo a validação.
        cls.ev_pend = _evidence(cls.occ, cls.agent)
        _event(cls.ev_pend, cls.agent, inst=cls.opc)
        # Item EM TRÂNSITO: não despachável (a receção tem de fechar primeiro).
        cls.ev_transit = _evidence(cls.occ, cls.agent)
        _event(cls.ev_transit, cls.agent, inst=cls.opc)
        _event(
            cls.ev_transit, cls.agent,
            event_type=EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.OPC, inst=cls.opc,
            bearer_nome='Rui', bearer_apelido='Faria', bearer_matricula='PSP-78',
        )

    def _post(self, data):
        auth_cookie(self.client, self.agent)
        return self.client.post(f'/occurrences/{self.occ.id}/despachar/', data)

    def _get(self, suffix=''):
        auth_cookie(self.client, self.agent)
        return self.client.get(f'/occurrences/{self.occ.id}/despachar/{suffix}')

    def _last(self, ev):
        return sort_custody_chain(ev.custody_chain.all())[-1]

    def _payload(self, ids, **extra):
        data = {
            'modal': '1',
            'evidence_ids': ids,
            'authority_nome': 'João Macedo',
            'authority_cargo': 'Procurador da República',
            'act_declared_at': _dtl(timezone.now()),
            'act_deadline_days': '30',
        }
        data.update(extra)
        return data

    # -- Modal / listagem ------------------------------------------------

    def test_modal_lista_so_itens_despachaveis(self):
        body = self._get('?modal=1').content.decode()
        self.assertIn('data-modal-title', body)
        self.assertNotIn('<html', body)  # fragmento
        self.assertIn(f'value="{self.ev1.id}"', body)
        self.assertIn(f'value="{self.ev2.id}"', body)
        # Pendente de validação TAMBÉM aparece (despachável incluindo-a),
        # com o alerta e a opção expressa de incluir a validação.
        self.assertIn(f'value="{self.ev_pend.id}"', body)
        self.assertIn('name="include_validation"', body)
        self.assertIn('POR VALIDAR', body)
        self.assertNotIn(f'value="{self.ev_transit.id}"', body)  # em trânsito
        self.assertIn('name="authority_nome"', body)
        self.assertIn('name="authority_cargo"', body)
        self.assertIn('name="act_declared_at"', body)
        self.assertIn('name="act_deadline_days"', body)
        self.assertIn('name="justification"', body)
        self.assertIn('Quem ordenou a perícia', body)
        # Ato jurídico: o modal não pede GPS nem local.
        self.assertNotIn('name="gps_lat"', body)
        self.assertNotIn('name="location_name"', body)

    # -- Despacho OK -------------------------------------------------------

    def test_despacha_em_lote_sem_mudar_o_estado(self):
        r = self._post(self._payload(
            [self.ev1.id, self.ev2.id], justification='Despacho 77/26 — exame pericial.',
        ))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], f'/occurrences/{self.occ.id}/')
        for ev in (self.ev1, self.ev2):
            ult = self._last(ev)
            self.assertEqual(ult.event_type, EventType.DESPACHO_PERICIA)
            # Autoridade + data declarada + PRAZO da perícia ESTRUTURADOS (hv4
            # — entram na fórmula do hash); observations leva só a referência.
            self.assertEqual(ult.authority_nome, 'João Macedo')
            self.assertEqual(ult.authority_cargo, 'Procurador da República')
            self.assertIsNotNone(ult.act_declared_at)
            self.assertEqual(ult.act_deadline_days, 30)
            self.assertEqual(ult.observations, 'Despacho 77/26 — exame pericial.')
            self.assertEqual(ult.hash_version, 'hv4')
            # Ato sem deslocação: sem GPS; custódio herdado do último evento.
            self.assertIsNone(ult.gps_lat)
            self.assertEqual(ult.custodian_institution_id, self.opc.id)
            # O estado de custódia NÃO muda (o despacho não desloca a prova).
            self.assertEqual(legal_state_of(ev), 'a_guarda_opc')

    def test_despacho_abre_o_gate_de_pericia(self):
        """Com o despacho registado, INICIO_PERICIA passa a ser aceite."""
        self._post(self._payload([self.ev1.id]))
        rec = _event(
            self.ev1, self.agent, event_type=EventType.INICIO_PERICIA,
            custodian_type=CustodianType.LAB_PUBLICO,
        )
        self.assertEqual(rec.event_type, EventType.INICIO_PERICIA)
        self.assertEqual(legal_state_of(self.ev1), 'em_pericia')

    def test_despacho_e_repetivel(self):
        """2.ª perícia (Art. 158.º): um novo despacho é aceite no mesmo item."""
        self._post(self._payload([self.ev1.id]))
        r = self._post(self._payload([self.ev1.id], justification='Nova perícia.'))
        self.assertEqual(r.status_code, 204)
        tipos = [x.event_type for x in sort_custody_chain(self.ev1.custody_chain.all())]
        self.assertEqual(tipos.count(EventType.DESPACHO_PERICIA), 2)

    def test_despacho_parcial_so_dos_selecionados(self):
        r = self._post(self._payload([self.ev1.id]))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self._last(self.ev1).event_type, EventType.DESPACHO_PERICIA)
        self.assertEqual(self._last(self.ev2).event_type, EventType.VALIDACAO_APREENSAO)

    # -- Apreensão por validar (CPP 178.º/5-6): despacho inclui a validação --

    def test_pendente_sem_checkbox_devolve_erro(self):
        """Item por validar selecionado sem a opção expressa → recusado, e
        nada entra no ledger (nem validação, nem despacho)."""
        r = self._post(self._payload([self.ev1.id, self.ev_pend.id]))
        self.assertEqual(r.status_code, 400)
        body = r.content.decode()
        self.assertIn('por validar', body)
        self.assertIn(self.ev_pend.code, body)
        self.assertEqual(self._last(self.ev1).event_type, EventType.VALIDACAO_APREENSAO)
        self.assertEqual(self._last(self.ev_pend).event_type, EventType.APREENSAO_OBJETO)

    def test_pendente_com_checkbox_regista_validacao_e_despacho(self):
        """Com «o despacho inclui a validação»: VALIDACAO_APREENSAO entra
        imediatamente antes do DESPACHO, pela mesma autoridade — a validação
        implícita da jurisprudência fica explícita no ledger."""
        r = self._post(self._payload(
            [self.ev1.id, self.ev_pend.id], include_validation='1',
            justification='Despacho 90/26.',
        ))
        self.assertEqual(r.status_code, 204)
        tipos = [x.event_type for x in sort_custody_chain(self.ev_pend.custody_chain.all())]
        self.assertEqual(
            tipos,
            [EventType.APREENSAO_OBJETO, EventType.VALIDACAO_APREENSAO,
             EventType.DESPACHO_PERICIA],
        )
        eventos = sort_custody_chain(self.ev_pend.custody_chain.all())
        # A validação incluída leva a MESMA autoridade estruturada E a MESMA
        # data declarada do despacho (sem prazo — o prazo é próprio do despacho).
        self.assertEqual(eventos[1].authority_nome, 'João Macedo')
        self.assertEqual(eventos[1].authority_cargo, 'Procurador da República')
        self.assertIn('Validação incluída no despacho', eventos[1].observations)
        self.assertIsNone(eventos[1].act_deadline_days)
        self.assertEqual(eventos[1].act_declared_at, eventos[2].act_declared_at)
        self.assertEqual(eventos[2].authority_nome, 'João Macedo')
        self.assertEqual(eventos[2].act_deadline_days, 30)
        # O item já validado leva SÓ o despacho (não revalida).
        tipos_ev1 = [x.event_type for x in sort_custody_chain(self.ev1.custody_chain.all())]
        self.assertEqual(tipos_ev1.count(EventType.VALIDACAO_APREENSAO), 1)
        self.assertEqual(tipos_ev1[-1], EventType.DESPACHO_PERICIA)

    # -- Validação de entrada --------------------------------------------

    def test_sem_selecao_devolve_erro(self):
        r = self._post(self._payload([]))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Selecione pelo menos um item', r.content.decode())

    def test_sem_autoridade_devolve_erro(self):
        r = self._post(self._payload([self.ev1.id], authority_nome=''))
        self.assertEqual(r.status_code, 400)
        self.assertIn('nome da autoridade', r.content.decode())

    def test_sem_prazo_devolve_erro(self):
        """O despacho FIXA o prazo da perícia: sem dias (ou com 0) é recusado."""
        for invalido in ('', '0', 'abc'):
            r = self._post(self._payload([self.ev1.id], act_deadline_days=invalido))
            self.assertEqual(r.status_code, 400)
            self.assertIn('prazo da perícia', r.content.decode())
        self.assertEqual(self._last(self.ev1).event_type, EventType.VALIDACAO_APREENSAO)

    def test_data_no_futuro_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], act_declared_at=_dtl(timezone.now() + timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('futuro', r.content.decode())

    def test_data_anterior_a_genese_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], act_declared_at=_dtl(timezone.now() - timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anteceder', r.content.decode())
        self.assertEqual(self._last(self.ev1).event_type, EventType.VALIDACAO_APREENSAO)


class DespachoCaminhoUnicoTest(TestCase):
    """O despacho tem UM caminho de registo (o modal certificado, que pede
    quem/quando/referência): o formulário genérico da timeline deixa de
    oferecer DESPACHO_PERICIA e as páginas do item ligam ao modal da
    ocorrência. As guardas do MODELO não mudam — é só o ecrã que fecha o
    segundo caminho sem certificação (a API recusa o evento "nu" na fronteira)."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP DUn', type=InstitutionType.OPC, sigla='PSP-DU')
        cls.agent = _user('dun_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'DUN-1')
        cls.ev = _evidence(cls.occ, cls.agent)
        _event(cls.ev, cls.agent, inst=cls.opc)

    def _get(self, url):
        auth_cookie(self.client, self.agent)
        return self.client.get(url)

    def test_timeline_nao_oferece_despacho_no_select_generico(self):
        body = self._get(f'/evidences/{self.ev.id}/custody/').content.decode()
        self.assertNotIn('<option value="DESPACHO_PERICIA"', body)
        # O caminho certo está lá: botão dedicado para o modal da ocorrência.
        self.assertIn(f'/occurrences/{self.occ.id}/despachar/', body)

    def test_detalhe_do_item_liga_ao_modal(self):
        body = self._get(f'/evidences/{self.ev.id}/').content.decode()
        self.assertIn(f'/occurrences/{self.occ.id}/despachar/', body)

    def test_detalhe_da_ocorrencia_tem_botao(self):
        body = self._get(f'/occurrences/{self.occ.id}/').content.decode()
        self.assertIn(f'/occurrences/{self.occ.id}/despachar/', body)


class DespachoBadgeTest(TestCase):
    """Visibilidade GUI do despacho: badge «Com despacho judicial» DERIVADO do
    ledger (``core.utils.has_despacho``) nas páginas de detalhe do item, da
    ocorrência (tabela de itens) e da timeline, e no modal do despacho (item já
    despachado fica marcado — selecioná-lo regista a 2.ª perícia, Art. 158.º).
    A par, a tabela de itens passou a mostrar também «Validada»: os atos
    certificados têm visibilidade POSITIVA, não só as pendências."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Bdg', type=InstitutionType.OPC, sigla='PSP-BG')
        cls.agent = _user('bdg_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'BDG-1')
        # Item validado COM despacho registado.
        cls.ev_desp = _evidence(cls.occ, cls.agent)
        _event(cls.ev_desp, cls.agent, inst=cls.opc)
        _event(cls.ev_desp, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)
        _event(cls.ev_desp, cls.agent, event_type=EventType.DESPACHO_PERICIA, inst=cls.opc)
        # Item validado SEM despacho (controlo negativo).
        cls.ev_val = _evidence(cls.occ, cls.agent)
        _event(cls.ev_val, cls.agent, inst=cls.opc)
        _event(cls.ev_val, cls.agent, event_type=EventType.VALIDACAO_APREENSAO, inst=cls.opc)

    def _get(self, url):
        auth_cookie(self.client, self.agent)
        return self.client.get(url)

    def test_detalhe_do_item_mostra_o_badge(self):
        body = self._get(f'/evidences/{self.ev_desp.id}/').content.decode()
        self.assertIn('Com despacho judicial', body)

    def test_item_sem_despacho_nao_mostra_o_badge(self):
        body = self._get(f'/evidences/{self.ev_val.id}/').content.decode()
        self.assertNotIn('Com despacho judicial', body)

    def test_timeline_mostra_o_badge(self):
        body = self._get(f'/evidences/{self.ev_desp.id}/custody/').content.decode()
        self.assertIn('Com despacho judicial', body)

    def test_tabela_de_itens_mostra_despacho_e_validada(self):
        """Detalhe da ocorrência: a linha de cada item mostra os atos — a
        «Validada» deixou de ser suprimida (mostrava-se só a pendência)."""
        body = self._get(f'/occurrences/{self.occ.id}/').content.decode()
        self.assertIn('Com despacho judicial', body)
        self.assertIn('>Validada<', body)

    def test_modal_despachar_marca_item_ja_despachado(self):
        body = self._get(f'/occurrences/{self.occ.id}/despachar/?modal=1').content.decode()
        self.assertIn('Com despacho judicial', body)

    def test_modal_despachar_nao_preseleciona_item_ja_despachado(self):
        """O item já despachado é elegível (2.ª perícia — Art. 158.º) mas entra
        DESMARCADO (precheck do spec): o 2.º despacho marca-se de propósito,
        nunca por omissão. Os restantes mantêm a pré-seleção."""
        body = self._get(f'/occurrences/{self.occ.id}/despachar/?modal=1').content.decode()
        self.assertIn(f'value="{self.ev_desp.id}" >', body)
        self.assertIn(f'value="{self.ev_val.id}" checked>', body)


class DespachoAPITest(BaseAPITestCase):
    """A fronteira de escrita externa é a MESMA da validação: o ``clean()`` do
    modelo recusa o despacho "nu" (sem a autoridade estruturada — hv4) e o
    handler global traduz em 400; o evento certificado é aceite."""

    def setUp(self):
        super().setUp()
        self.occ = _occ(self.agent, 'DAPI-1')
        self.ev = _evidence(self.occ, self.agent)
        _event(self.ev, self.agent)
        _event(self.ev, self.agent, event_type=EventType.VALIDACAO_APREENSAO)

    def _despacho_payload(self, ev, **extra):
        data = {
            'evidence': ev.pk,
            'event_type': 'DESPACHO_PERICIA',
            'custodian_type': 'OPC',
            'authority_nome': 'João Macedo',
            'authority_cargo': 'Procurador da República',
            'act_declared_at': timezone.now().isoformat(),
            'act_deadline_days': 30,
        }
        data.update(extra)
        return data

    def test_api_recusa_despacho_sem_identificacao(self):
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), {
            'evidence': self.ev.pk,
            'event_type': 'DESPACHO_PERICIA',
            'custodian_type': 'OPC',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('identificação', str(r.data))
        self.assertEqual(self.ev.custody_chain.count(), 2)

    def test_api_recusa_despacho_sem_prazo(self):
        self.authenticate_as(self.agent)
        r = self.client.post(
            reverse('core:custody-list'),
            self._despacho_payload(self.ev, act_deadline_days=''),
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('prazo', str(r.data))
        self.assertEqual(self.ev.custody_chain.count(), 2)

    def test_api_recusa_despacho_com_apreensao_por_validar(self):
        """A guarda do MODELO vale também na API: apreensão por validar →
        o despacho é recusado (CPP 178.º/5-6)."""
        ev2 = _evidence(self.occ, self.agent)
        _event(ev2, self.agent)   # apreensão SEM validação
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), self._despacho_payload(ev2))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('VALIDADA', str(r.data))
        self.assertEqual(ev2.custody_chain.count(), 1)

    def test_api_aceita_despacho_certificado(self):
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), self._despacho_payload(self.ev))
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['event_type'], 'DESPACHO_PERICIA')
        self.assertEqual(r.data['authority_nome'], 'João Macedo')
        self.assertEqual(r.data['act_deadline_days'], 30)
        self.assertEqual(r.data['hash_version'], 'hv4')


class AutoridadeHv4Test(BaseAPITestCase):
    """Guardas hv4 do MODELO: autoridade órfã recusada fora dos atos
    certificados; prazo só no despacho; data declarada nunca futura; fórmula
    hv4 aditiva e re-verificável a partir do registo relido."""

    def setUp(self):
        super().setUp()
        self.occ = _occ(self.agent, 'HV4-1')
        self.ev = _evidence(self.occ, self.agent)
        _event(self.ev, self.agent)

    def test_autoridade_orfa_e_recusada(self):
        """Identidade de autoridade fora de um ato certificado não entra
        (ex.: numa apreensão — a génese não é um ato de autoridade)."""
        ev2 = _evidence(self.occ, self.agent)
        with self.assertRaisesMessage(DjangoValidationError, 'atos certificados'):
            _event(
                ev2, self.agent,
                authority_nome='João Macedo', authority_cargo='Procurador',
                act_declared_at=timezone.now(),
            )

    def test_prazo_fora_do_despacho_e_recusado(self):
        with self.assertRaisesMessage(DjangoValidationError, 'prazo da perícia'):
            _event(
                self.ev, self.agent,
                event_type=EventType.VALIDACAO_APREENSAO,
                act_deadline_days=30,
            )

    def test_data_declarada_futura_e_recusada(self):
        with self.assertRaisesMessage(DjangoValidationError, 'futuro'):
            _event(
                self.ev, self.agent,
                event_type=EventType.VALIDACAO_APREENSAO,
                act_declared_at=timezone.now() + timedelta(days=1),
            )

    def test_data_declarada_anterior_a_apreensao_recusada_no_modelo(self):
        """A guarda de antecedência é invariante do LEDGER (clean()), não só
        pré-validação do formulário — vale também na API."""
        with self.assertRaisesMessage(DjangoValidationError, 'anteceder'):
            _event(
                self.ev, self.agent,
                event_type=EventType.VALIDACAO_APREENSAO,
                act_declared_at=timezone.now() - timedelta(days=1),
            )

    def test_ato_certificado_sem_autoridade_e_recusado(self):
        with self.assertRaisesMessage(DjangoValidationError, 'identificação da autoridade'):
            _event(
                self.ev, self.agent,
                event_type=EventType.VALIDACAO_APREENSAO,
                authority_nome='', authority_cargo='',
                act_declared_at=timezone.now(),
            )

    def test_hv3_e_hv4_diferem_para_mesmos_campos(self):
        """A versão é parte do contrato: o mesmo registo em hv3 e hv4 produz
        hashes distintos (prefixo + segmentos da autoridade no fim)."""
        comum = dict(
            evidence=self.ev, event_type=EventType.VALIDACAO_APREENSAO,
            agent=self.agent, sequence=2, observations='',
            authority_nome='João Macedo', authority_cargo='Procurador da República',
            act_declared_at=timezone.now(),
        )
        rec_hv3 = ChainOfCustody(hash_version='hv3', **comum)
        rec_hv4 = ChainOfCustody(hash_version='hv4', **comum)
        ts = timezone.now()
        rec_hv3.timestamp = ts
        rec_hv4.timestamp = ts
        self.assertNotEqual(
            rec_hv3.compute_record_hash(previous_hash='0' * 64),
            rec_hv4.compute_record_hash(previous_hash='0' * 64),
        )

    def test_registo_certificado_e_hv4_e_reverifica(self):
        """O perito re-lê o registo da BD e recalcula o hash com a fórmula
        hv4 — bate certo com o gravado (incl. a data declarada normalizada
        a UTC no clean(), análogo da quantização GPS)."""
        # Data declarada no FUSO LOCAL (não-UTC) — exercita a normalização;
        # posterior à apreensão do setUp (a guarda de antecedência vale aqui).
        rec = _event(
            self.ev, self.agent, event_type=EventType.VALIDACAO_APREENSAO,
            act_declared_at=timezone.localtime(timezone.now()),
        )
        self.assertEqual(rec.hash_version, 'hv4')
        relido = ChainOfCustody.objects.get(pk=rec.pk)
        anterior = ChainOfCustody.objects.get(
            evidence=self.ev, sequence=relido.sequence - 1
        ).record_hash
        self.assertEqual(
            relido.compute_record_hash(previous_hash=anterior), relido.record_hash
        )

    def test_registo_de_despacho_reverifica_com_prazo(self):
        """Round-trip BD→fórmula do segmento ``aprazo`` (inteiro de dias) —
        só o DESPACHO o preenche; o reverify da validação deixa-o vazio."""
        _event(self.ev, self.agent, event_type=EventType.VALIDACAO_APREENSAO)
        rec = _event(
            self.ev, self.agent, event_type=EventType.DESPACHO_PERICIA,
            act_deadline_days=45,
        )
        self.assertEqual(rec.hash_version, 'hv4')
        relido = ChainOfCustody.objects.get(pk=rec.pk)
        self.assertEqual(relido.act_deadline_days, 45)
        anterior = ChainOfCustody.objects.get(
            evidence=self.ev, sequence=relido.sequence - 1
        ).record_hash
        self.assertEqual(
            relido.compute_record_hash(previous_hash=anterior), relido.record_hash
        )
