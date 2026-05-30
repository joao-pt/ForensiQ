"""
ForensiQ — Testes das novas funcionalidades (revisão UX 2026-05-02).

Cobre:
- D (backend): validação EVIDENCE_LEAF_TYPES em ``Evidence.clean()``.
- G (backend): manager ``with_current_state()`` + filtros ``?state=`` em
  ``EvidenceViewSet`` e ``OccurrenceViewSet``.
- E (backend): endpoint ``POST /api/custody/cascade/`` (atómico).
- J (backend): ``MediaServeView`` com ownership + auditoria + anti
  path-traversal.
"""

import io
from unittest import mock

import httpx
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    AuditLog,
    ChainOfCustody,
    CustodianType,
    EventType,
    Evidence,
    Occurrence,
)
from .tests_api import BaseAPITestCase

User = get_user_model()


from core.tests_factories import CrimeTipoFactory


def _png_upload(name='photo.png', size=(2, 2)):
    """Devolve um SimpleUploadedFile com PNG válido (Pillow.verify passa)."""
    buf = io.BytesIO()
    Image.new('RGB', size, color=(255, 0, 0)).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


# ---------------------------------------------------------------------------
# D — EVIDENCE_LEAF_TYPES rejeita filhos
# ---------------------------------------------------------------------------


class LeafTypeValidationTest(BaseAPITestCase):
    """Tipos terminais (SIM, MEMORY, RFID, DIGITAL_FILE) não aceitam filhos."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='LEAF-2026-001',
            description='Caso para teste de tipos LEAF',
            agent=self.agent,
        )

    def _create(self, type_, parent=None):
        return Evidence.objects.create(
            occurrence=self.occurrence,
            type=type_,
            description=f'Teste {type_}',
            parent_evidence=parent,
            agent=self.agent,
        )

    def test_sim_card_as_root_is_allowed(self):
        """SIM como raiz é permitido — só não pode ser PAI."""
        ev = self._create('SIM_CARD')
        self.assertIsNotNone(ev.pk)

    def test_sim_card_rejects_child(self):
        """Tentar criar filho de um SIM_CARD levanta ValidationError."""
        sim = self._create('SIM_CARD')
        with self.assertRaises(ValidationError) as ctx:
            self._create('MEMORY_CARD', parent=sim)
        self.assertIn('parent_evidence', ctx.exception.message_dict)

    def test_memory_card_rejects_child(self):
        mem = self._create('MEMORY_CARD')
        with self.assertRaises(ValidationError):
            self._create('OTHER_DIGITAL', parent=mem)

    def test_rfid_card_rejects_child(self):
        rfid = self._create('RFID_NFC_CARD')
        with self.assertRaises(ValidationError):
            self._create('SIM_CARD', parent=rfid)

    def test_digital_file_rejects_child(self):
        df = self._create('DIGITAL_FILE')
        with self.assertRaises(ValidationError):
            self._create('OTHER_DIGITAL', parent=df)

    def test_mobile_device_accepts_sim_child(self):
        """Tipo não-LEAF (MOBILE_DEVICE) continua a aceitar filhos."""
        phone = self._create('MOBILE_DEVICE')
        sim = self._create('SIM_CARD', parent=phone)
        self.assertEqual(sim.parent_evidence_id, phone.id)


# ---------------------------------------------------------------------------
# G — Manager with_current_state + filtro ?state=
# ---------------------------------------------------------------------------


class CurrentStateAndFilterTest(BaseAPITestCase):
    """Manager anota o estado actual e os ViewSets respeitam ?state=."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='STATE-2026-001',
            description='Caso filtro state',
            agent=self.agent,
        )
        self.ev_in_analysis = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Em perícia',
            agent=self.agent,
        )
        self.ev_apreendida = Evidence.objects.create(
            occurrence=self.occurrence,
            type='COMPUTER',
            description='Apenas apreendido',
            agent=self.agent,
        )
        # Avança ev_in_analysis até estar em perícia (estado derivado em_pericia).
        for event_type, custodian_type in [
            (EventType.APREENSAO, CustodianType.OPC),
            (EventType.DESPACHO_PERICIA, CustodianType.OPC),
            (EventType.TRANSFERENCIA, CustodianType.LAB_PUBLICO),
            (EventType.INICIO_PERICIA, CustodianType.LAB_PUBLICO),
        ]:
            ChainOfCustody.objects.create(
                evidence=self.ev_in_analysis,
                event_type=event_type,
                custodian_type=custodian_type,
                agent=self.agent,
            )
        ChainOfCustody.objects.create(
            evidence=self.ev_apreendida,
            event_type=EventType.APREENSAO,
            custodian_type=CustodianType.OPC,
            agent=self.agent,
        )

    def test_manager_annotates_current_event_type(self):
        qs = Evidence.objects.with_current_state().filter(occurrence=self.occurrence)
        events = {e.id: e.current_event_type for e in qs}
        self.assertEqual(events[self.ev_in_analysis.id], 'INICIO_PERICIA')
        self.assertEqual(events[self.ev_apreendida.id], 'APREENSAO')

    def test_evidences_filter_by_state(self):
        self.client.force_authenticate(self.agent)
        url = '/api/evidences/?state=em_pericia'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        ids = [e['id'] for e in resp.json()['results']]
        self.assertIn(self.ev_in_analysis.id, ids)
        self.assertNotIn(self.ev_apreendida.id, ids)

    def test_evidences_filter_invalid_state_returns_400(self):
        self.client.force_authenticate(self.agent)
        resp = self.client.get('/api/evidences/?state=INVALID_STATE')
        self.assertEqual(resp.status_code, 400)

    def test_occurrences_filter_by_state(self):
        # Outra ocorrência sem evidências em perícia
        other_occ = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='STATE-2026-002',
            description='Outra ocorrência',
            agent=self.agent,
        )
        Evidence.objects.create(
            occurrence=other_occ,
            type='COMPUTER',
            description='Outro item',
            agent=self.agent,
        )
        self.client.force_authenticate(self.agent)
        resp = self.client.get('/api/occurrences/?state=em_pericia')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.json()['results']]
        self.assertIn(self.occurrence.id, ids)
        self.assertNotIn(other_occ.id, ids)


# ---------------------------------------------------------------------------
# E — Endpoint POST /api/custody/cascade/
# ---------------------------------------------------------------------------


class CascadeCustodyTest(BaseAPITestCase):
    """Cascade aplica a transição a múltiplas evidências em transação atómica."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='CASCADE-2026-001',
            description='Caso cascade',
            agent=self.agent,
        )
        self.parent = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Telemóvel',
            agent=self.agent,
        )
        self.sim = Evidence.objects.create(
            occurrence=self.occurrence,
            type='SIM_CARD',
            description='SIM',
            parent_evidence=self.parent,
            agent=self.agent,
        )
        self.sd = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MEMORY_CARD',
            description='SD',
            parent_evidence=self.parent,
            agent=self.agent,
        )
        # Evento inicial APREENSAO para todos.
        for ev in [self.parent, self.sim, self.sd]:
            ChainOfCustody.objects.create(
                evidence=ev,
                event_type=EventType.APREENSAO,
                custodian_type=CustodianType.OPC,
                agent=self.agent,
            )

    def test_cascade_creates_chain_for_all_evidences(self):
        self.client.force_authenticate(self.agent)
        resp = self.client.post(
            '/api/custody/cascade/',
            {
                'evidence_ids': [self.parent.id, self.sim.id, self.sd.id],
                'event_type': 'VALIDACAO',
                'custodian_type': 'OPC',
                'observations': 'Validação em conjunto',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        # 3 novos eventos (em adição às 3 APREENSAO)
        for ev in [self.parent, self.sim, self.sd]:
            last = ev.custody_chain.order_by('-sequence').first()
            self.assertEqual(last.event_type, 'VALIDACAO')

    def test_cascade_partial_subset(self):
        """Pode-se passar só um subconjunto — restantes ficam no evento anterior."""
        self.client.force_authenticate(self.agent)
        resp = self.client.post(
            '/api/custody/cascade/',
            {
                'evidence_ids': [self.parent.id, self.sim.id],
                'event_type': 'VALIDACAO',
                'custodian_type': 'OPC',
                'observations': 'Sem o SD',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            self.parent.custody_chain.order_by('-sequence').first().event_type,
            'VALIDACAO',
        )
        # SD não avançou — continua no evento de apreensão.
        self.assertEqual(
            self.sd.custody_chain.order_by('-sequence').first().event_type,
            'APREENSAO',
        )

    def test_cascade_rolls_back_on_invalid_event(self):
        """Se o evento é inválido para uma evidência, todas revertem."""
        # Fecha o SIM com um evento terminal (RESTITUICAO): qualquer evento
        # seguinte (incl. VALIDACAO) é rejeitado pela guarda dos terminais.
        ChainOfCustody.objects.create(
            evidence=self.sim,
            event_type=EventType.RESTITUICAO,
            custodian_type=CustodianType.PROPRIETARIO,
            agent=self.agent,
        )
        sequences_before = {
            ev.id: ev.custody_chain.count() for ev in [self.parent, self.sim, self.sd]
        }

        self.client.force_authenticate(self.agent)
        resp = self.client.post(
            '/api/custody/cascade/',
            {
                'evidence_ids': [self.parent.id, self.sim.id, self.sd.id],
                'event_type': 'VALIDACAO',
                'custodian_type': 'OPC',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

        # Nenhuma das 3 ganhou registos
        for ev in [self.parent, self.sim, self.sd]:
            self.assertEqual(ev.custody_chain.count(), sequences_before[ev.id])

    def test_cascade_idor_blocks_other_agent(self):
        """Outro AGENT não pode fazer cascade sobre evidências do agent."""
        other = User.objects.create_user(
            username='outro_agent',
            password='X12345678!',
            profile=User.Profile.AGENT,
            badge_number='AGT-OUTRO-99',
        )
        self.client.force_authenticate(other)
        resp = self.client.post(
            '/api/custody/cascade/',
            {
                'evidence_ids': [self.parent.id],
                'event_type': 'VALIDACAO',
                'custodian_type': 'OPC',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cascade_invalid_payload(self):
        self.client.force_authenticate(self.agent)
        resp = self.client.post(
            '/api/custody/cascade/',
            {'evidence_ids': [], 'event_type': 'VALIDACAO'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# J — MediaServeView
# ---------------------------------------------------------------------------


class MediaServeTest(BaseAPITestCase):
    """Foto de evidência só servida com auth + ownership; audita acesso."""

    def setUp(self):
        super().setUp()
        self.occurrence = Occurrence.objects.create(
            crime_type=CrimeTipoFactory(),
            number='MEDIA-2026-001',
            description='Caso media',
            agent=self.agent,
        )
        self.evidence = Evidence.objects.create(
            occurrence=self.occurrence,
            type='MOBILE_DEVICE',
            description='Item com foto',
            photo=_png_upload('test.png'),
            agent=self.agent,
        )

    def _media_url(self):
        # Path relativo guardado no FileField; URL servida = MEDIA_URL + path
        return '/media/' + str(self.evidence.photo.name)

    def test_anonymous_blocked(self):
        client = APIClient()
        resp = client.get(self._media_url())
        self.assertIn(resp.status_code, (401, 403))

    def test_owner_gets_file(self):
        self.client.force_authenticate(self.agent)
        resp = self.client.get(self._media_url())
        self.assertEqual(resp.status_code, 200)
        self.assertIn('image/', resp.headers.get('Content-Type', ''))
        self.assertIn('private', resp.headers.get('Cache-Control', ''))

    def test_other_agent_blocked(self):
        other = User.objects.create_user(
            username='outro_media',
            password='X12345678!',
            profile=User.Profile.AGENT,
            badge_number='AGT-MEDIA-99',
        )
        self.client.force_authenticate(other)
        resp = self.client.get(self._media_url())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_expert_can_access(self):
        self.client.force_authenticate(self.expert)
        resp = self.client.get(self._media_url())
        self.assertEqual(resp.status_code, 200)

    def test_path_traversal_blocked(self):
        self.client.force_authenticate(self.agent)
        resp = self.client.get('/media/../etc/passwd')
        self.assertIn(resp.status_code, (404, 403))

    def test_creates_audit_log(self):
        AuditLog.objects.filter(
            user=self.agent,
            resource_type=AuditLog.ResourceType.EVIDENCE,
        ).delete()
        self.client.force_authenticate(self.agent)
        self.client.get(self._media_url())
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.agent,
                resource_type=AuditLog.ResourceType.EVIDENCE,
                details__media_path__isnull=False,
            ).exists()
        )

    def test_unknown_path_outside_evidencias_blocked(self):
        self.client.force_authenticate(self.agent)
        resp = self.client.get('/media/random/file.jpg')
        self.assertIn(resp.status_code, (403, 404))


# ---------------------------------------------------------------------------
# POIs próximos — proxy Overpass server-side (ADR-0015)
# ---------------------------------------------------------------------------


class NearbyPOIsViewTest(BaseAPITestCase):
    """Proxy server-side de POIs OSM: validação, filtragem, 502 e throttle."""

    URL = '/api/nearby-pois/'

    def test_requires_lat_lon(self):
        self.authenticate_as(self.agent)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lat_out_of_range(self):
        self.authenticate_as(self.agent)
        resp = self.client.get(self.URL, {'lat': '200', 'lon': '-9.1'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_numeric_params(self):
        self.authenticate_as(self.agent)
        resp = self.client.get(self.URL, {'lat': 'abc', 'lon': 'def'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_success_filters_and_minimal_payload(self):
        """Resposta do Overpass é filtrada a amenities úteis e payload minimal."""

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'elements': [
                        {
                            'type': 'node',
                            'lat': 38.7230,
                            'lon': -9.1400,
                            'tags': {'amenity': 'police', 'name': 'PSP Lisboa'},
                        },
                        {
                            'type': 'way',
                            'center': {'lat': 38.7250, 'lon': -9.1420},
                            'tags': {'amenity': 'courthouse', 'name': 'Tribunal'},
                        },
                        # Amenity irrelevante — deve ser filtrado fora.
                        {
                            'type': 'node',
                            'lat': 38.7231,
                            'lon': -9.1401,
                            'tags': {'amenity': 'cafe', 'name': 'Café'},
                        },
                    ]
                }

        self.authenticate_as(self.agent)
        with mock.patch('core.views.httpx.post', return_value=_Resp()):
            resp = self.client.get(self.URL, {'lat': '38.7223', 'lon': '-9.1393'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        tipos = {p['tipo'] for p in data}
        self.assertEqual(tipos, {'police', 'courthouse'})
        # Payload minimal: só nome/tipo/lat/lon/dist_m.
        self.assertEqual(set(data[0].keys()), {'nome', 'tipo', 'lat', 'lon', 'dist_m'})
        # Ordenado por distância crescente.
        self.assertLessEqual(data[0]['dist_m'], data[1]['dist_m'])

    def test_overpass_unavailable_returns_502(self):
        """Indisponibilidade do Overpass degrada graciosamente (502)."""
        self.authenticate_as(self.agent)
        with mock.patch('core.views.httpx.post', side_effect=httpx.ConnectError('down')):
            resp = self.client.get(self.URL, {'lat': '38.7223', 'lon': '-9.1393'})
        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_throttle_scope_is_reverse_geocode(self):
        """O endpoint reusa o scope de throttle 'reverse_geocode' (ADR-0015)."""
        from core.views import NearbyPOIsView

        self.assertEqual(NearbyPOIsView.throttle_scope, 'reverse_geocode')

    def test_throttle_dispara_apos_limite(self):
        """Ao atingir o limite do scope reverse_geocode devolve 429.

        Nota (igual ao ImeiLookupThrottleTest): override_settings reseta
        api_settings mas NÃO ``SimpleRateThrottle.THROTTLE_RATES`` (capturado
        no import). Patcheamos directamente o atributo de classe.
        """
        from django.core.cache import cache
        from rest_framework.throttling import SimpleRateThrottle

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {'elements': []}

        cache.clear()
        self.authenticate_as(self.agent)
        rates = {'reverse_geocode': '1/minute'}
        with (
            mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', rates),
            mock.patch('core.views.httpx.post', return_value=_Resp()),
        ):
            first = self.client.get(self.URL, {'lat': '38.7', 'lon': '-9.1'})
            second = self.client.get(self.URL, {'lat': '38.7', 'lon': '-9.1'})
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
