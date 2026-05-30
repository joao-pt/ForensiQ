"""
ForensiQ — Testes do feed de actividade (T06) e do enriquecimento do
dashboard (T07).

T06 — GET /api/activity-feed/:
- feed read-only ordenado por -timestamp;
- ``is_priority_alert`` True para criação de ocorrência prioritária e False
  para ocorrência normal;
- âmbito: AGENT só vê os SEUS eventos, EXPERT/staff vêem todos;
- métodos de escrita devolvem 405; não-autenticado devolve 401.

T07 — GET /api/stats/dashboard/ (chaves aditivas):
- ``deltas_24h`` com a aritmética last/prev/delta correcta;
- ``total_active`` exclui evidências em estado terminal;
- ``occurrences_series_7d`` com 7 entradas e contagens certas.

Nota: ``created_at`` (``auto_now_add``) e ``ChainOfCustody.timestamp`` (forçado
ao relógio do servidor no ``save()``) não são definíveis na criação; para
posicionar registos em janelas temporais específicas usamos ``.update()``, que
escreve directamente na BD (em SQLite de teste não há triggers de
imutabilidade — ver CLAUDE.md). Isto NÃO é caminho de produção: é apenas
instrumentação de teste para datar registos.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import AuditLog, ChainOfCustody, Evidence, Occurrence, User
from .tests_factories import (
    CrimeTipoFactory,
    EvidenceMobileFactory,
    OccurrenceFactory,
)


class DashboardBaseTestCase(TestCase):
    """Setup comum: agente, perito e admin (mesma convenção de tests_api)."""

    def setUp(self):
        self.client = APIClient()
        self.agent = User.objects.create_user(
            username='agente_dash',
            password='TestPass123!',
            profile=User.Profile.AGENT,
            first_name='Ana',
            last_name='Silva',
        )
        self.other_agent = User.objects.create_user(
            username='agente_dash_2',
            password='TestPass123!',
            profile=User.Profile.AGENT,
            first_name='Bruno',
            last_name='Mendes',
        )
        self.expert = User.objects.create_user(
            username='perito_dash',
            password='TestPass123!',
            profile=User.Profile.EXPERT,
            first_name='Carlos',
            last_name='Costa',
        )
        self.admin = User.objects.create_superuser(
            username='admin_dash',
            password='AdminPass123!',
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    # -- helpers de domínio --

    def _make_priority_crime_type(self):
        """Tipo de crime marcado como prioritário via Política Criminal activa."""
        from .models import PoliticaCriminalPrioridade, PrioridadeCrimeTipo

        crime = CrimeTipoFactory(codigo=1)
        politica = PoliticaCriminalPrioridade.objects.create(
            lei='Lei 51/2023',
            biennium='2023-2025',
            vigente_desde=timezone.localdate(),
            is_active=True,
        )
        PrioridadeCrimeTipo.objects.create(
            politica=politica,
            crime_tipo=crime,
            eixo=PrioridadeCrimeTipo.Eixo.INVESTIGACAO,
        )
        return crime


# ---------------------------------------------------------------------------
# T06 — Activity Feed
# ---------------------------------------------------------------------------


class ActivityFeedTest(DashboardBaseTestCase):
    """Testes do endpoint read-only GET /api/activity-feed/ (T06)."""

    def _log(self, user, action, resource_type, resource_id):
        return AuditLog.objects.create(
            user=user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address='127.0.0.1',
        )

    def test_requires_authentication(self):
        """Não-autenticado → 401."""
        url = reverse('core:activity-feed')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_read_only_methods_rejected(self):
        """POST/PUT/DELETE → 405 (feed é só leitura)."""
        self.authenticate_as(self.expert)
        url = reverse('core:activity-feed')
        self.assertEqual(self.client.post(url, {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.put(url, {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_ordered_by_timestamp_desc(self):
        """Eventos vêm ordenados do mais recente para o mais antigo."""
        a = self._log(self.expert, AuditLog.Action.CREATE, AuditLog.ResourceType.OCCURRENCE, 1)
        b = self._log(self.expert, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 2)
        c = self._log(self.expert, AuditLog.Action.EXPORT_PDF, AuditLog.ResourceType.EVIDENCE, 3)
        # Forçar timestamps distintos e crescentes.
        now = timezone.now()
        AuditLog.objects.filter(pk=a.pk).update(timestamp=now - timedelta(minutes=30))
        AuditLog.objects.filter(pk=b.pk).update(timestamp=now - timedelta(minutes=20))
        AuditLog.objects.filter(pk=c.pk).update(timestamp=now - timedelta(minutes=10))

        self.authenticate_as(self.expert)
        url = reverse('core:activity-feed')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data['results']]
        self.assertEqual(ids, [c.pk, b.pk, a.pk])

    def test_priority_alert_true_for_priority_occurrence(self):
        """is_priority_alert=True para CREATE de ocorrência PRIORITÁRIA."""
        crime = self._make_priority_crime_type()
        occ = OccurrenceFactory(agent=self.agent, crime_type=crime)
        self.assertEqual(occ.priority, Occurrence.Priority.PRIORITARIA)
        log = self._log(
            self.agent, AuditLog.Action.CREATE, AuditLog.ResourceType.OCCURRENCE, occ.pk
        )

        self.authenticate_as(self.expert)
        url = reverse('core:activity-feed')
        response = self.client.get(url)
        item = next(i for i in response.data['results'] if i['id'] == log.pk)
        self.assertTrue(item['is_priority_alert'])

    def test_priority_alert_false_for_normal_occurrence(self):
        """is_priority_alert=False para CREATE de ocorrência NORMAL."""
        occ = OccurrenceFactory(agent=self.agent, crime_type=CrimeTipoFactory(codigo=99))
        self.assertEqual(occ.priority, Occurrence.Priority.NORMAL)
        log = self._log(
            self.agent, AuditLog.Action.CREATE, AuditLog.ResourceType.OCCURRENCE, occ.pk
        )

        self.authenticate_as(self.expert)
        response = self.client.get(reverse('core:activity-feed'))
        item = next(i for i in response.data['results'] if i['id'] == log.pk)
        self.assertFalse(item['is_priority_alert'])

    def test_priority_alert_false_for_non_occurrence_create(self):
        """CREATE de evidência nunca é alerta de prioridade."""
        log = self._log(self.agent, AuditLog.Action.CREATE, AuditLog.ResourceType.EVIDENCE, 7)
        self.authenticate_as(self.expert)
        response = self.client.get(reverse('core:activity-feed'))
        item = next(i for i in response.data['results'] if i['id'] == log.pk)
        self.assertFalse(item['is_priority_alert'])

    def test_priority_alert_false_when_occurrence_deleted(self):
        """Ocorrência inexistente (resource_id órfão) → is_priority_alert=False."""
        log = self._log(
            self.agent, AuditLog.Action.CREATE, AuditLog.ResourceType.OCCURRENCE, 999999
        )
        self.authenticate_as(self.expert)
        response = self.client.get(reverse('core:activity-feed'))
        item = next(i for i in response.data['results'] if i['id'] == log.pk)
        self.assertFalse(item['is_priority_alert'])

    def test_scope_agent_sees_only_own_events(self):
        """AGENT vê apenas os eventos que ELE praticou."""
        own = self._log(self.agent, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 1)
        alheio = self._log(
            self.other_agent, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 2
        )
        do_perito = self._log(self.expert, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 3)

        self.authenticate_as(self.agent)
        response = self.client.get(reverse('core:activity-feed'))
        ids = {item['id'] for item in response.data['results']}
        self.assertIn(own.pk, ids)
        self.assertNotIn(alheio.pk, ids)
        self.assertNotIn(do_perito.pk, ids)

    def test_scope_expert_sees_all_events(self):
        """EXPERT vê os eventos de todos os utilizadores."""
        a = self._log(self.agent, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 1)
        b = self._log(self.other_agent, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 2)

        self.authenticate_as(self.expert)
        response = self.client.get(reverse('core:activity-feed'))
        ids = {item['id'] for item in response.data['results']}
        self.assertIn(a.pk, ids)
        self.assertIn(b.pk, ids)

    def test_scope_staff_sees_all_events(self):
        """Staff (superuser) vê os eventos de todos os utilizadores."""
        a = self._log(self.agent, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 1)
        b = self._log(self.other_agent, AuditLog.Action.VIEW, AuditLog.ResourceType.EVIDENCE, 2)

        self.authenticate_as(self.admin)
        response = self.client.get(reverse('core:activity-feed'))
        ids = {item['id'] for item in response.data['results']}
        self.assertIn(a.pk, ids)
        self.assertIn(b.pk, ids)

    def test_item_shape_and_labels(self):
        """Cada item expõe rótulos legíveis e o autor (user_name)."""
        log = self._log(self.agent, AuditLog.Action.CREATE, AuditLog.ResourceType.OCCURRENCE, 42)
        self.authenticate_as(self.agent)
        response = self.client.get(reverse('core:activity-feed'))
        item = next(i for i in response.data['results'] if i['id'] == log.pk)
        self.assertEqual(item['action'], 'CREATE')
        self.assertEqual(item['action_display'], 'Criação')
        self.assertEqual(item['resource_type'], 'OCCURRENCE')
        self.assertEqual(item['resource_type_display'], 'Ocorrência')
        self.assertEqual(item['resource_id'], 42)
        self.assertEqual(item['user'], 'agente_dash')
        self.assertEqual(item['user_name'], 'Ana Silva')
        self.assertEqual(item['label'], 'Ana Silva criou OCORRÊNCIA #42')

    def test_system_event_has_null_user_and_label_sistema(self):
        """Evento sem utilizador → user=None, user_name='sistema'."""
        log = self._log(None, AuditLog.Action.SYSTEM_ALERT, AuditLog.ResourceType.SYSTEM, 0)
        self.authenticate_as(self.expert)
        response = self.client.get(reverse('core:activity-feed'))
        item = next(i for i in response.data['results'] if i['id'] == log.pk)
        self.assertIsNone(item['user'])
        self.assertEqual(item['user_name'], 'sistema')


# ---------------------------------------------------------------------------
# T07 — Enriquecimento do dashboard
# ---------------------------------------------------------------------------


class DashboardEnrichmentTest(DashboardBaseTestCase):
    """Testes das chaves aditivas de /api/stats/dashboard/ (T07)."""

    def _dashboard(self, user):
        self.authenticate_as(user)
        response = self.client.get(reverse('core:stats-dashboard'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def test_existing_keys_preserved(self):
        """As chaves originais continuam presentes (aditivo, não destrutivo)."""
        data = self._dashboard(self.expert)
        for chave in (
            'total_occurrences',
            'open_occurrences',
            'total_evidences',
            'evidences_by_type',
            'evidences_by_current_state',
            'custodies_in_transit',
            'evidences_in_analysis',
            'deltas_24h',
            'total_active',
            'occurrences_series_7d',
        ):
            self.assertIn(chave, data)

    def test_deltas_24h_arithmetic(self):
        """last_24h, prev_24h e delta correctos para as três métricas."""
        now = timezone.now()
        within = now - timedelta(hours=6)  # janela [agora-24h, agora]
        prev = now - timedelta(hours=30)  # janela [agora-48h, agora-24h]
        old = now - timedelta(hours=60)  # fora de ambas as janelas

        # Ocorrência-âncora ANTIGA: serve de container às evidências sem
        # contaminar as janelas de ocorrências (as evidências partilham-na em
        # vez de cada uma criar a sua via SubFactory).
        ancora = OccurrenceFactory(agent=self.agent, crime_type=CrimeTipoFactory())
        Occurrence.objects.filter(pk=ancora.pk).update(created_at=old)

        # Ocorrências contadas: 2 nas últimas 24h, 1 nas 24h anteriores.
        # (A âncora antiga acima também conta, mas está fora das duas janelas.)
        for created in (within, within, prev):
            occ = OccurrenceFactory(agent=self.agent, crime_type=CrimeTipoFactory())
            Occurrence.objects.filter(pk=occ.pk).update(created_at=created)

        # Evidências: 1 nas últimas 24h, 2 nas 24h anteriores — todas na âncora.
        for created in (within, prev, prev):
            ev = EvidenceMobileFactory(agent=self.agent, occurrence=ancora)
            Evidence.objects.filter(pk=ev.pk).update(created_at=created)

        # Eventos de custódia: 3 nas últimas 24h, 0 nas anteriores.
        ev = EvidenceMobileFactory(agent=self.agent, occurrence=ancora)
        Evidence.objects.filter(pk=ev.pk).update(created_at=old)
        # APREENSAO + DESPACHO_PERICIA + INICIO_PERICIA (sequência válida).
        ChainOfCustody(
            evidence=ev,
            event_type=ChainOfCustody.EventType.APREENSAO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()
        ChainOfCustody(
            evidence=ev,
            event_type=ChainOfCustody.EventType.DESPACHO_PERICIA,
            agent=self.agent,
        ).save()
        ChainOfCustody(
            evidence=ev,
            event_type=ChainOfCustody.EventType.INICIO_PERICIA,
            custodian_type=ChainOfCustody.CustodianType.LAB_PUBLICO,
            agent=self.agent,
        ).save()
        ChainOfCustody.objects.filter(evidence=ev).update(timestamp=within)

        data = self._dashboard(self.expert)
        d = data['deltas_24h']

        self.assertEqual(d['occurrences']['last_24h'], 2)
        self.assertEqual(d['occurrences']['prev_24h'], 1)
        self.assertEqual(d['occurrences']['delta'], 1)

        self.assertEqual(d['evidences']['last_24h'], 1)
        self.assertEqual(d['evidences']['prev_24h'], 2)
        self.assertEqual(d['evidences']['delta'], -1)

        self.assertEqual(d['custody_events']['last_24h'], 3)
        self.assertEqual(d['custody_events']['prev_24h'], 0)
        self.assertEqual(d['custody_events']['delta'], 3)

    def test_total_active_excludes_terminal(self):
        """total_active conta activas (incl. sem custódia) e exclui terminais."""
        # ev_sem_custodia: activa (sem qualquer registo de custódia).
        EvidenceMobileFactory(agent=self.agent)

        # ev_activa: APREENSAO (não terminal) → activa.
        ev_activa = EvidenceMobileFactory(agent=self.agent)
        ChainOfCustody(
            evidence=ev_activa,
            event_type=ChainOfCustody.EventType.APREENSAO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()

        # ev_terminal: APREENSAO → RESTITUICAO (terminal) → NÃO activa.
        ev_terminal = EvidenceMobileFactory(agent=self.agent)
        ChainOfCustody(
            evidence=ev_terminal,
            event_type=ChainOfCustody.EventType.APREENSAO,
            custodian_type=ChainOfCustody.CustodianType.OPC,
            agent=self.agent,
        ).save()
        ChainOfCustody(
            evidence=ev_terminal,
            event_type=ChainOfCustody.EventType.RESTITUICAO,
            custodian_type=ChainOfCustody.CustodianType.PROPRIETARIO,
            agent=self.agent,
        ).save()

        data = self._dashboard(self.expert)
        # 3 evidências no total, 1 terminal → 2 activas.
        self.assertEqual(data['total_evidences'], 3)
        self.assertEqual(data['total_active'], 2)

    def test_occurrences_series_7d_shape_and_counts(self):
        """7 entradas (dia mais antigo→hoje) com contagens diárias certas."""
        hoje = timezone.localdate()
        # 2 ocorrências hoje, 1 há 3 dias, 1 há 6 dias, 1 há 10 dias (fora).
        offsets = [0, 0, 3, 6, 10]
        for offset in offsets:
            occ = OccurrenceFactory(agent=self.agent, crime_type=CrimeTipoFactory())
            dia = hoje - timedelta(days=offset)
            # Datar a meio do dia local evita ambiguidades de fronteira.
            momento = timezone.make_aware(
                timezone.datetime.combine(dia, timezone.datetime.min.time())
            ) + timedelta(hours=12)
            Occurrence.objects.filter(pk=occ.pk).update(created_at=momento)

        data = self._dashboard(self.expert)
        serie = data['occurrences_series_7d']

        self.assertEqual(len(serie), 7)
        # Ordem ascendente: primeiro é há 6 dias, último é hoje.
        self.assertEqual(serie[0]['date'], (hoje - timedelta(days=6)).isoformat())
        self.assertEqual(serie[-1]['date'], hoje.isoformat())

        por_data = {entry['date']: entry['count'] for entry in serie}
        self.assertEqual(por_data[hoje.isoformat()], 2)
        self.assertEqual(por_data[(hoje - timedelta(days=3)).isoformat()], 1)
        self.assertEqual(por_data[(hoje - timedelta(days=6)).isoformat()], 1)
        # A ocorrência de há 10 dias está fora da janela → não soma.
        total_na_serie = sum(por_data.values())
        self.assertEqual(total_na_serie, 4)

    def test_agent_scope_isolated(self):
        """AGENT só vê o seu scope nas novas métricas."""
        # Ocorrência + evidência do outro agente — não devem contar.
        OccurrenceFactory(agent=self.other_agent, crime_type=CrimeTipoFactory())
        EvidenceMobileFactory(agent=self.other_agent)
        # Uma do próprio agente, hoje.
        occ = OccurrenceFactory(agent=self.agent, crime_type=CrimeTipoFactory())
        Occurrence.objects.filter(pk=occ.pk).update(created_at=timezone.now())

        data = self._dashboard(self.agent)
        self.assertEqual(data['total_occurrences'], 1)
        # total_active conta só evidências do próprio (0 aqui).
        self.assertEqual(data['total_active'], 0)
        self.assertEqual(sum(e['count'] for e in data['occurrences_series_7d']), 1)
