"""ForensiQ — Testes: restituição com identidade do RECETOR (hv3).

Modelo de domínio (CPP art. 186.º — termo de entrega): a restituição EXTINGUE a
cadeia, pelo que o ato exige identificar QUEM recebeu — nome completo + tipo e
n.º de documento, campos ESTRUTURADOS no evento (pesquisáveis), que entram na
fórmula de hash hv3 (aditiva sobre hv2: prefixo de versão + segmentos do
recetor no fim; o verificador escolhe pela ``hash_version`` gravada). O
``timestamp`` é sempre o do servidor; o custódio passa a PROPRIETARIO; sem GPS
(a entrega formaliza-se no posto). Os mesmos campos ficam disponíveis na
entrega a DEPOSITARIO particular; fora desses atos o ledger recusa identidade
órfã.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from core import integrity
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
    RECEIVER_KWARGS,
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)
from core.utils import legal_state_of, sort_custody_chain

User = get_user_model()


class RestituirLoteTest(TestCase):
    """Modal de restituição em lote a partir da ocorrência (padrão validar)."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Rst', type=InstitutionType.OPC, sigla='PSP-RS')
        cls.agent = _user('rst_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'RST-1')
        # Dois itens restituíveis (génese feita, ledger aberto).
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)
        # Item EM TRÂNSITO: não restituível (a receção tem de fechar primeiro).
        cls.ev_transit = _evidence(cls.occ, cls.agent)
        _event(cls.ev_transit, cls.agent, inst=cls.opc)
        _event(
            cls.ev_transit, cls.agent,
            event_type=EventType.ENCAMINHAMENTO_CUSTODIA,
            custodian_type=CustodianType.OPC, inst=cls.opc,
            bearer_nome='Rui', bearer_apelido='Faria', bearer_matricula='PSP-77',
        )

    def _post(self, data):
        auth_cookie(self.client, self.agent)
        return self.client.post(f'/occurrences/{self.occ.id}/restituir/', data)

    def _get(self, suffix=''):
        auth_cookie(self.client, self.agent)
        return self.client.get(f'/occurrences/{self.occ.id}/restituir/{suffix}')

    def _last(self, ev):
        return sort_custody_chain(ev.custody_chain.all())[-1]

    def _payload(self, ids, **extra):
        data = {
            'modal': '1',
            'evidence_ids': ids,
            'receiver_nome': 'Manuel Augusto Pinto',
            'receiver_doc_tipo': 'CC',
            'receiver_doc_numero': '11223344 5 ZB7',
        }
        data.update(extra)
        return data

    # -- Modal / listagem --------------------------------------------------

    def test_modal_lista_so_itens_restituiveis(self):
        body = self._get('?modal=1').content.decode()
        self.assertIn('data-modal-title', body)
        self.assertNotIn('<html', body)  # fragmento
        self.assertIn(f'value="{self.ev1.id}"', body)
        self.assertIn(f'value="{self.ev2.id}"', body)
        self.assertNotIn(f'value="{self.ev_transit.id}"', body)  # em trânsito
        self.assertIn('name="receiver_nome"', body)
        self.assertIn('name="receiver_doc_tipo"', body)
        self.assertIn('name="receiver_doc_numero"', body)
        # A entrega formaliza-se no posto: o modal não pede GPS nem local.
        self.assertNotIn('name="gps_lat"', body)
        self.assertNotIn('name="location_name"', body)

    # -- Restituição OK ----------------------------------------------------

    def test_restitui_em_lote_com_identidade_estruturada(self):
        r = self._post(self._payload(
            [self.ev1.id, self.ev2.id], justification='Despacho 45/26 do MP.',
        ))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], f'/occurrences/{self.occ.id}/')
        for ev in (self.ev1, self.ev2):
            ult = self._last(ev)
            self.assertEqual(ult.event_type, EventType.RESTITUICAO)
            # Identidade ESTRUTURADA (não em observations) — pesquisável e no hash.
            self.assertEqual(ult.receiver_nome, 'Manuel Augusto Pinto')
            self.assertEqual(ult.receiver_doc_tipo, 'CC')
            self.assertEqual(ult.receiver_doc_numero, '11223344 5 ZB7')
            self.assertEqual(ult.observations, 'Despacho 45/26 do MP.')
            # Terminal: custódio = proprietário; sem GPS; cadeia extinta.
            self.assertEqual(ult.custodian_type, CustodianType.PROPRIETARIO)
            self.assertIsNone(ult.gps_lat)
            self.assertEqual(legal_state_of(ev), 'restituida')

    def test_restituicao_parcial_so_dos_selecionados(self):
        r = self._post(self._payload([self.ev1.id]))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self._last(self.ev1).event_type, EventType.RESTITUICAO)
        self.assertEqual(self._last(self.ev2).event_type, EventType.APREENSAO_OBJETO)

    def test_item_restituido_sai_da_lista(self):
        self._post(self._payload([self.ev1.id, self.ev2.id]))
        body = self._get('?modal=1').content.decode()
        self.assertNotIn(f'value="{self.ev1.id}"', body)
        self.assertNotIn(f'value="{self.ev2.id}"', body)

    # -- Validação de entrada ----------------------------------------------

    def test_sem_selecao_devolve_erro(self):
        r = self._post(self._payload([]))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Selecione pelo menos um item', r.content.decode())

    def test_recetor_incompleto_devolve_erro(self):
        r = self._post(self._payload([self.ev1.id], receiver_doc_numero=''))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Identifique quem recebeu', r.content.decode())
        self.assertEqual(self._last(self.ev1).event_type, EventType.APREENSAO_OBJETO)

    def test_tipo_de_documento_invalido_devolve_erro(self):
        r = self._post(self._payload([self.ev1.id], receiver_doc_tipo='BI'))
        self.assertEqual(r.status_code, 400)
        self.assertIn('inválido', r.content.decode())


class RestituicaoCaminhoUnicoTest(TestCase):
    """O ato de restituição tem UM caminho de registo (o modal do termo de
    entrega, que pede a identidade do recetor): o formulário genérico da
    timeline deixa de oferecer RESTITUICAO e as páginas do item ligam ao modal
    da ocorrência enquanto o item é restituível. As guardas do MODELO não mudam
    — é só o ecrã que fecha o segundo caminho sem identificação."""

    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP RUn', type=InstitutionType.OPC, sigla='PSP-RU')
        cls.agent = _user('run_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'RUN-1')
        cls.ev_aberto = _evidence(cls.occ, cls.agent)
        _event(cls.ev_aberto, cls.agent, inst=cls.opc)
        cls.ev_fechado = _evidence(cls.occ, cls.agent)
        _event(cls.ev_fechado, cls.agent, inst=cls.opc)
        _event(
            cls.ev_fechado, cls.agent, event_type=EventType.RESTITUICAO,
            custodian_type=CustodianType.PROPRIETARIO,
        )

    def _get(self, url):
        auth_cookie(self.client, self.agent)
        return self.client.get(url)

    def test_timeline_nao_oferece_restituicao_no_select_generico(self):
        body = self._get(f'/evidences/{self.ev_aberto.id}/custody/').content.decode()
        self.assertNotIn('<option value="RESTITUICAO"', body)
        # O caminho certo está lá: botão dedicado para o modal da ocorrência.
        self.assertIn(f'/occurrences/{self.occ.id}/restituir/', body)

    def test_timeline_de_item_fechado_nao_mostra_botao(self):
        body = self._get(f'/evidences/{self.ev_fechado.id}/custody/').content.decode()
        self.assertNotIn(f'/occurrences/{self.occ.id}/restituir/', body)

    def test_timeline_mostra_recetor_do_termo_de_entrega(self):
        body = self._get(f'/evidences/{self.ev_fechado.id}/custody/').content.decode()
        self.assertIn('Recebido por', body)
        self.assertIn(RECEIVER_KWARGS['receiver_nome'], body)
        self.assertIn(RECEIVER_KWARGS['receiver_doc_numero'], body)

    def test_detalhe_do_item_liga_ao_modal_quando_restituivel(self):
        body = self._get(f'/evidences/{self.ev_aberto.id}/').content.decode()
        self.assertIn(f'/occurrences/{self.occ.id}/restituir/', body)


class ReceiverGuardTest(TestCase):
    """Guardas do clean(): a RESTITUICAO exige o recetor completo; identidade
    parcial é recusada; fora da restituição/depositário é identidade órfã."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = _user('rgd_agent', User.Profile.FIRST_RESPONDER)
        cls.occ = _occ(cls.agent, 'RGD-1')

    def _ev_com_genese(self):
        ev = _evidence(self.occ, self.agent)
        _event(ev, self.agent)  # APREENSAO_OBJETO
        return ev

    def test_restituicao_sem_recetor_falha(self):
        ev = self._ev_com_genese()
        with self.assertRaises(ValidationError) as ctx:
            ChainOfCustody(
                evidence=ev, event_type=EventType.RESTITUICAO,
                custodian_type=CustodianType.PROPRIETARIO, agent=self.agent,
            ).save()
        self.assertIn('receiver_nome', ctx.exception.message_dict)

    def test_recetor_parcial_falha(self):
        ev = self._ev_com_genese()
        with self.assertRaises(ValidationError):
            ChainOfCustody(
                evidence=ev, event_type=EventType.RESTITUICAO,
                custodian_type=CustodianType.PROPRIETARIO, agent=self.agent,
                receiver_nome='Só o Nome',
            ).save()

    def test_recetor_fora_da_restituicao_ou_depositario_falha(self):
        ev = self._ev_com_genese()
        with self.assertRaises(ValidationError):
            ChainOfCustody(
                evidence=ev, event_type=EventType.DESPACHO_PERICIA,
                custodian_type=CustodianType.OPC, agent=self.agent,
                **RECEIVER_KWARGS,
            ).save()

    def test_recetor_disponivel_na_entrega_a_depositario(self):
        ev = self._ev_com_genese()
        rec = ChainOfCustody(
            evidence=ev, event_type=EventType.TRANSFERENCIA_CUSTODIA,
            custodian_type=CustodianType.DEPOSITARIO, agent=self.agent,
            **RECEIVER_KWARGS,
        )
        rec.save()
        self.assertEqual(rec.receiver_nome, RECEIVER_KWARGS['receiver_nome'])


class ReceiverHashTest(TestCase):
    """Fórmula hv3: aditiva sobre hv2, recetor no fim; re-verificável pela
    ``hash_version`` gravada — registos antigos nunca se recalculam."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = _user('rh3_agent', User.Profile.FIRST_RESPONDER)
        cls.occ = _occ(cls.agent, 'RH3-1')

    def _restituida(self):
        ev = _evidence(self.occ, self.agent)
        _event(ev, self.agent)
        return ev, _event(
            ev, self.agent, event_type=EventType.RESTITUICAO,
            custodian_type=CustodianType.PROPRIETARIO,
        )

    def test_registo_de_restituicao_e_hv3_e_reverifica(self):
        ev, rec = self._restituida()
        self.assertEqual(rec.hash_version, 'hv3')
        prev = sort_custody_chain(ev.custody_chain.all())[-2].record_hash
        relido = ChainOfCustody.objects.get(pk=rec.pk)
        self.assertEqual(relido.compute_record_hash(previous_hash=prev), relido.record_hash)

    def test_recetor_entra_na_formula(self):
        """Mudar um dígito do documento muda o hash — a identidade está selada."""
        ev = _evidence(self.occ, self.agent)
        comum = dict(
            evidence=ev, event_type=EventType.RESTITUICAO,
            custodian_type=CustodianType.PROPRIETARIO, agent=self.agent,
            hash_version='hv3', sequence=2, timestamp=timezone.now(),
            **RECEIVER_KWARGS,
        )
        rec_a = ChainOfCustody(**comum)
        rec_b = ChainOfCustody(**dict(comum, receiver_doc_numero='99999999 9 XX9'))
        self.assertNotEqual(
            rec_a.compute_record_hash(previous_hash='0' * 64),
            rec_b.compute_record_hash(previous_hash='0' * 64),
        )

    def test_hv2_e_hv3_diferem_para_mesmos_campos(self):
        ev = _evidence(self.occ, self.agent)
        comum = dict(
            evidence=ev, event_type=EventType.APREENSAO_OBJETO,
            custodian_type=CustodianType.OPC, agent=self.agent,
            sequence=1, timestamp=timezone.now(),
        )
        rec_hv2 = ChainOfCustody(hash_version='hv2', **comum)
        rec_hv3 = ChainOfCustody(hash_version='hv3', **comum)
        self.assertNotEqual(
            rec_hv2.compute_record_hash(previous_hash='0' * 64),
            rec_hv3.compute_record_hash(previous_hash='0' * 64),
        )

    def test_cadeia_com_restituicao_verifica_integra(self):
        ev, _ = self._restituida()
        result = integrity.verify_chains([ev.id])
        self.assertTrue(result['intact'])


class RestituicaoAPITest(BaseAPITestCase):
    """A API partilha as guardas do modelo: aceita a identidade estruturada e
    recusa a restituição sem ela (não há caminho sem termo de entrega)."""

    def setUp(self):
        super().setUp()
        self.occ = _occ(self.agent, 'RAPI-1')
        self.ev = _evidence(self.occ, self.agent)
        _event(self.ev, self.agent)

    def test_api_restitui_com_recetor(self):
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), {
            'evidence': self.ev.pk,
            'event_type': 'RESTITUICAO',
            'custodian_type': 'PROPRIETARIO',
            **RECEIVER_KWARGS,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['receiver_nome'], RECEIVER_KWARGS['receiver_nome'])
        self.assertEqual(r.data['hash_version'], 'hv3')
        self.assertEqual(r.data['legal_state'], 'restituida')

    def test_api_recusa_restituicao_sem_recetor(self):
        self.authenticate_as(self.agent)
        r = self.client.post(reverse('core:custody-list'), {
            'evidence': self.ev.pk,
            'event_type': 'RESTITUICAO',
            'custodian_type': 'PROPRIETARIO',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.ev.custody_chain.count(), 1)
