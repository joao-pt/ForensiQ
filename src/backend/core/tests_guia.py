"""ForensiQ — Testes: guia de transporte de uma REMESSA (GuiaTransporte).

O encaminhamento em LOTE cria uma GuiaTransporte que agrupa os eventos da remessa;
o PDF é re-gerado a partir do ledger e servido em ``/guias/<code>/pdf/`` a quem pode
ver a ocorrência.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.documents import generate_guia_transporte
from core.models import (
    GuiaTransporte,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Portador,
)
from core.tests_base import auth_cookie
from core.tests_factories import (
    make_event as _event,
    make_evidence as _evidence,
    make_occ as _occ,
    make_user as _user,
)

User = get_user_model()


class GuiaTransporteTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.opc = Institution.objects.create(name='PSP G', type=InstitutionType.OPC, sigla='PSP-G')
        cls.dest = Institution.objects.create(name='PJ G', type=InstitutionType.OPC, sigla='PJ-G')
        cls.agent = _user('guia_agent', User.Profile.FIRST_RESPONDER)
        InstitutionMembership.objects.create(user=cls.agent, institution=cls.opc)
        cls.portador = Portador.objects.create(
            matricula='GUIA-P-1', nome='Rui', apelido='Costa', posto='Agente'
        )
        cls.occ = _occ(cls.agent, 'GUIA-1')
        cls.ev1 = _evidence(cls.occ, cls.agent)
        _event(cls.ev1, cls.agent, inst=cls.opc)  # APREENSAO @opc
        cls.ev2 = _evidence(cls.occ, cls.agent)
        _event(cls.ev2, cls.agent, inst=cls.opc)

    def _encaminhar(self):
        auth_cookie(self.client, self.agent)
        return self.client.post(
            f'/occurrences/{self.occ.id}/encaminhar/',
            {
                'modal': '1',
                'evidence_ids': [self.ev1.id, self.ev2.id],
                'bearer': self.portador.id,
                'custodian_institution': self.dest.id,
            },
        )

    def test_handoff_cria_guia_com_os_eventos_do_lote(self):
        """O encaminhamento em lote cria UMA GuiaTransporte que liga os N eventos."""
        resp = self._encaminhar()
        self.assertEqual(resp.status_code, 204)
        guia = GuiaTransporte.objects.get(occurrence=self.occ)
        self.assertTrue(guia.code.startswith('GT-'))
        self.assertEqual(guia.events.count(), 2)
        self.assertEqual(
            set(guia.events.values_list('evidence_id', flat=True)),
            {self.ev1.id, self.ev2.id},
        )

    def test_render_devolve_pdf(self):
        self._encaminhar()
        guia = GuiaTransporte.objects.get(occurrence=self.occ)
        pdf = generate_guia_transporte(guia)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 3_000)

    def test_endpoint_dono_descarrega_pdf(self):
        self._encaminhar()
        guia = GuiaTransporte.objects.get(occurrence=self.occ)
        auth_cookie(self.client, self.agent)
        resp = self.client.get(f'/guias/{guia.code}/pdf/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('attachment', resp.get('Content-Disposition', ''))
        self.assertIn(guia.code, resp.get('Content-Disposition', ''))
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_endpoint_inexistente_404(self):
        auth_cookie(self.client, self.agent)
        self.assertEqual(self.client.get('/guias/GT-2099-9999/pdf/').status_code, 404)

    def test_endpoint_sem_acesso_404(self):
        """Indistinto: quem não pode ver a ocorrência recebe 404, não 403."""
        self._encaminhar()
        guia = GuiaTransporte.objects.get(occurrence=self.occ)
        outro = _user('guia_outro', User.Profile.FIRST_RESPONDER)
        auth_cookie(self.client, outro)
        self.assertEqual(self.client.get(f'/guias/{guia.code}/pdf/').status_code, 404)

    # -- QR / verificação pública da remessa -----------------------------

    def test_qr_resolve_roundtrip(self):
        from core.qr_verify import resolve_guia, short_hash_for_guia

        self._encaminhar()
        guia = GuiaTransporte.objects.get(occurrence=self.occ)
        self.assertEqual(resolve_guia(short_hash_for_guia(guia.id)).id, guia.id)
        self.assertIsNone(resolve_guia('0' * 12))

    def test_verificacao_publica_da_remessa_anon(self):
        from django.test import Client

        from core.qr_verify import short_hash_for_guia

        self._encaminhar()
        guia = GuiaTransporte.objects.get(occurrence=self.occ)
        resp = Client().get(f'/v/g/{short_hash_for_guia(guia.id)}/')  # sem auth
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(guia.code, body)
        self.assertIn(self.ev1.code, body)  # item da remessa listado

    def test_verificacao_publica_hash_invalido_404(self):
        from django.test import Client

        self.assertEqual(Client().get('/v/g/zzzzzzzzzzzz/').status_code, 404)

    # -- conteúdo do PDF -------------------------------------------------

    def test_pdf_mostra_identificadores_e_destino(self):
        from io import BytesIO

        from pypdf import PdfReader

        from core.models import Evidence

        ev = Evidence.objects.create(
            occurrence=self.occ,
            type=Evidence.EvidenceType.MOBILE_DEVICE,
            description='telemóvel',
            agent=self.agent,
            type_specific_data={'marca': 'Samsung', 'modelo': 'Galaxy S24'},
        )
        _event(ev, self.agent, inst=self.opc)
        auth_cookie(self.client, self.agent)
        self.client.post(
            f'/occurrences/{self.occ.id}/encaminhar/',
            {
                'modal': '1',
                'evidence_ids': [ev.id],
                'bearer': self.portador.id,
                'custodian_institution': self.dest.id,
            },
        )
        guia = GuiaTransporte.objects.filter(occurrence=self.occ).latest('created_at')
        text = '\n'.join(
            p.extract_text() or '' for p in PdfReader(BytesIO(generate_guia_transporte(guia))).pages
        )
        self.assertIn('Samsung', text)  # marca = identificador
        self.assertIn(self.dest.short_label, text)  # destino da remessa

    def test_builder_fecha_buffer_em_erro_de_build(self):
        """Invariante do DocumentBuilder: o BytesIO fecha mesmo se ``build`` levantar."""
        from unittest.mock import MagicMock, patch

        from core.documents.builder import DocumentBuilder

        buf = MagicMock()
        doc_mock = MagicMock()
        doc_mock.build.side_effect = RuntimeError('boom')
        with (
            patch('core.documents.builder.BytesIO', return_value=buf),
            patch('core.documents.builder.SimpleDocTemplate', return_value=doc_mock),
            self.assertRaises(RuntimeError),
        ):
            DocumentBuilder(title='t', doc_subject='s', footer_ref='r').render()
        buf.close.assert_called_once()
