"""ForensiQ — Testes: validar a apreensão em LOTE a partir da ocorrência.

Modelo de domínio (CPP art. 178.º/6): a validação é um ATO JURÍDICO, não uma
deslocação — regista QUEM validou, QUANDO (data do despacho, declarada) e a
justificação, sem GPS nem mudança de custódio (herdado do último evento). O
``timestamp`` do evento é sempre o do servidor; a data do despacho entra no
texto de ``observations``, que faz parte da fórmula do hash. O estado de
custódia não muda (eixo ortogonal — ``validation_status``).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

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
from core.utils import legal_state_of, sort_custody_chain, validation_status_of

User = get_user_model()


def _dtl(dt):
    """Valor de um input ``datetime-local`` (YYYY-MM-DDTHH:MM) em hora local."""
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


class ValidarLoteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP Val', type=InstitutionType.OPC, sigla='PSP-VL')
        cls.agent = _user('val_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.occ = _occ(cls.agent, 'VAL-1')
        # Dois itens com génese de apreensão (validáveis).
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO_OBJETO @opc
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)

    def _post(self, data):
        auth_cookie(self.client, self.agent)
        return self.client.post(f'/occurrences/{self.occ.id}/validar/', data)

    def _get(self, suffix=''):
        auth_cookie(self.client, self.agent)
        return self.client.get(f'/occurrences/{self.occ.id}/validar/{suffix}')

    def _last(self, ev):
        return sort_custody_chain(ev.custody_chain.all())[-1]

    def _payload(self, ids, **extra):
        data = {
            'modal': '1',
            'evidence_ids': ids,
            'validated_by': 'Procuradora Maria Costa',
            'validated_at': _dtl(timezone.now()),
        }
        data.update(extra)
        return data

    # -- Modal / listagem ------------------------------------------------

    def test_modal_lista_itens_por_validar(self):
        body = self._get('?modal=1').content.decode()
        self.assertIn('data-modal-title', body)
        self.assertNotIn('<html', body)  # fragmento
        self.assertIn(f'value="{self.ev1.id}"', body)
        self.assertIn(f'value="{self.ev2.id}"', body)
        self.assertIn('name="validated_by"', body)
        self.assertIn('name="validated_at"', body)
        self.assertIn('name="justification"', body)
        # Ato jurídico: o modal não pede GPS nem local.
        self.assertNotIn('name="gps_lat"', body)
        self.assertNotIn('name="location_name"', body)

    # -- Validação OK ------------------------------------------------------

    def test_valida_em_lote_sem_mudar_o_estado(self):
        r = self._post(self._payload(
            [self.ev1.id, self.ev2.id], justification='Despacho 123/26.',
        ))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Redirect'], f'/occurrences/{self.occ.id}/')
        for ev in (self.ev1, self.ev2):
            ult = self._last(ev)
            self.assertEqual(ult.event_type, EventType.VALIDACAO_APREENSAO)
            # Quem validou + data do despacho + justificação: texto CERTIFICADO
            # (observations entra na fórmula do hash).
            self.assertIn('Procuradora Maria Costa', ult.observations)
            self.assertIn('Despacho 123/26.', ult.observations)
            # Ato sem deslocação: sem GPS; custódio herdado do último evento.
            self.assertIsNone(ult.gps_lat)
            self.assertEqual(ult.custodian_institution_id, self.opc.id)
            # Eixos separados: o estado de custódia NÃO muda; o estatuto sim.
            self.assertEqual(legal_state_of(ev), 'a_guarda_opc')
            self.assertEqual(validation_status_of(ev), 'validada')

    def test_validacao_parcial_so_dos_selecionados(self):
        r = self._post(self._payload([self.ev1.id]))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self._last(self.ev1).event_type, EventType.VALIDACAO_APREENSAO)
        self.assertEqual(self._last(self.ev2).event_type, EventType.APREENSAO_OBJETO)
        self.assertEqual(validation_status_of(self.ev2), 'por_validar')

    def test_item_validado_sai_da_lista(self):
        self._post(self._payload([self.ev1.id, self.ev2.id]))
        body = self._get('?modal=1').content.decode()
        self.assertIn('Sem apreensões por validar', body)

    # -- Validação de entrada --------------------------------------------

    def test_sem_selecao_devolve_erro(self):
        r = self._post(self._payload([]))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Selecione pelo menos um item', r.content.decode())

    def test_sem_autoridade_devolve_erro(self):
        r = self._post(self._payload([self.ev1.id], validated_by=''))
        self.assertEqual(r.status_code, 400)
        self.assertIn('quem validou', r.content.decode())

    def test_data_no_futuro_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], validated_at=_dtl(timezone.now() + timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('futuro', r.content.decode())

    def test_data_anterior_a_apreensao_devolve_erro(self):
        r = self._post(self._payload(
            [self.ev1.id], validated_at=_dtl(timezone.now() - timedelta(days=1)),
        ))
        self.assertEqual(r.status_code, 400)
        self.assertIn('anteceder', r.content.decode())
        self.assertEqual(self._last(self.ev1).event_type, EventType.APREENSAO_OBJETO)
