"""
ForensiQ — Testes de carga com Locust.

Cenário simulado: operação forense completa (first responder + perito).
- Autenticação JWT
- Criar ocorrências
- Criar evidências
- Criar dispositivos digitais
- Registar transições de custódia
- Exportar relatórios PDF

Uso básico:
    locust -f tests/locustfile.py --host=https://forensiq.pt

Uso local (desenvolvimento):
    locust -f tests/locustfile.py --host=http://localhost:8000

Opções:
    -u 100              — 100 utilizadores simultâneos
    -r 10               — taxa de spawn: 10 novos utilizadores por segundo
    -t 1m               — duração: 1 minuto
    --headless          — modo sem interface (CI/CD)
    -f tests/locustfile.py

Referência: https://docs.locust.io/
"""

import json
import re
from datetime import datetime
from locust import HttpUser, task, between, events
from locust.contrib.fasthttp import FastHttpUser


class ForensiQUser(FastHttpUser):
    """
    Utilizador ForensiQ: simula fluxo operacional de first responder/perito.

    Pesos de tarefas:
    - Listar ocorrências (3): frequência alta (monitorização)
    - Criar ocorrência + evidência (2): frequência média
    - Exportar PDF (1): frequência baixa (operação pesada)

    Wait time: 1-3 segundos entre tarefas (simula interação real).
    """

    wait_time = between(1, 3)

    def on_start(self):
        """
        Executado quando o utilizador inicia.
        Autentica via JWT e armazena o token.
        """
        self.token = None
        self.occurrence_ids = []
        self.evidence_ids = []

        # Simular primeiro responder (AGENT) ou perito (EXPERT)
        self.is_agent = True  # Começa como agente

        self._authenticate()

    def _authenticate(self):
        """
        POST /api/token/ — obtém token JWT.
        Credenciais pré-existentes no banco de testes.
        """
        username = 'agente_api' if self.is_agent else 'perito_api'
        password = 'TestPass123!'

        response = self.client.post(
            '/api/token/',
            json={'username': username, 'password': password},
            name='/api/token/ (login JWT)'
        )

        if response.status_code == 200:
            self.token = response.json().get('access')
            self._update_headers()
        else:
            self.environment.stats.events.request.fire(
                request_type='POST',
                name='/api/token/',
                response_time=response.elapsed.total_seconds() * 1000,
                response_length=len(response.text),
                response=response,
                context={},
                exception=Exception(f'Autenticação falhou: {response.status_code}')
            )

    def _update_headers(self):
        """Atualiza headers com token JWT."""
        if self.token:
            self.client.headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json',
            }

    def _create_occurrence(self):
        """
        POST /api/occurrences/ — cria ocorrência com GPS.
        Retorna ID da ocorrência criada.
        """
        timestamp = datetime.now().isoformat()
        occurrence_data = {
            'number': f'NUIPC-2026-LOAD-{timestamp[:10]}-{int(datetime.now().timestamp()) % 10000}',
            'description': f'Ocorrência de teste Locust - {timestamp}',
            'gps_lat': '38.7223340',
            'gps_lon': '-9.1393366',
        }

        response = self.client.post(
            '/api/occurrences/',
            json=occurrence_data,
            name='/api/occurrences/ (POST)'
        )

        if response.status_code == 201:
            data = response.json()
            occurrence_id = data.get('id')
            self.occurrence_ids.append(occurrence_id)
            return occurrence_id

        return None

    def _create_evidence(self, occurrence_id):
        """
        POST /api/evidences/ — cria evidência ligada a ocorrência.
        Retorna ID da evidência criada.
        """
        evidence_types = ['DIGITAL_DEVICE', 'DOCUMENT', 'PHYSICAL', 'BIOLOGICAL']
        import random

        evidence_data = {
            'occurrence': occurrence_id,
            'type': random.choice(evidence_types),
            'description': f'Evidência de teste Locust - {datetime.now().isoformat()}',
        }

        response = self.client.post(
            '/api/evidences/',
            json=evidence_data,
            name='/api/evidences/ (POST)'
        )

        if response.status_code == 201:
            data = response.json()
            evidence_id = data.get('id')
            self.evidence_ids.append(evidence_id)
            return evidence_id

        return None

    def _create_digital_device(self, evidence_id):
        """
        POST /api/devices/ — cria dispositivo digital.
        """
        device_data = {
            'evidence': evidence_id,
            'type': 'SMARTPHONE',
            'model': f'Test Device {int(datetime.now().timestamp()) % 1000}',
            'serial_number': f'SN-{int(datetime.now().timestamp()) % 100000}',
            'imei': '358623072123456',
        }

        response = self.client.post(
            '/api/devices/',
            json=device_data,
            name='/api/devices/ (POST)'
        )

        return response.status_code == 201

    def _create_custody_record(self, evidence_id, previous_state, new_state):
        """
        POST /api/custody/ — registar transição de custódia.
        """
        custody_data = {
            'evidence': evidence_id,
            'previous_state': previous_state,
            'new_state': new_state,
            'observations': f'Transição registada {datetime.now().isoformat()}',
        }

        response = self.client.post(
            '/api/custody/',
            json=custody_data,
            name='/api/custody/ (POST)'
        )

        return response.status_code == 201

    @task(3)
    def list_occurrences(self):
        """
        GET /api/occurrences/ — listar ocorrências.
        Tarefa frequente (monitorização).
        """
        self.client.get(
            '/api/occurrences/',
            name='/api/occurrences/ (GET)'
        )

    @task(2)
    def create_occurrence_and_evidence(self):
        """
        Workflow: criar ocorrência + evidência + dispositivo + custódia.
        Simula operação completa de first responder.
        """
        # 1. Criar ocorrência
        occurrence_id = self._create_occurrence()
        if not occurrence_id:
            return

        # 2. Criar evidência
        evidence_id = self._create_evidence(occurrence_id)
        if not evidence_id:
            return

        # 3. Criar dispositivo digital (se evidência é DIGITAL_DEVICE)
        self._create_digital_device(evidence_id)

        # 4. Registar primeiro estado de custódia
        self._create_custody_record(evidence_id, '', 'APREENDIDA')

    @task(1)
    def export_evidence_pdf(self):
        """
        GET /api/evidences/{id}/pdf/ — exportar relatório PDF.
        Tarefa pouco frequente (operação pesada).
        """
        if not self.evidence_ids:
            # Se não tem evidências, criar uma antes
            occ_id = self._create_occurrence()
            if occ_id:
                ev_id = self._create_evidence(occ_id)
                if ev_id:
                    self.evidence_ids.append(ev_id)

        if self.evidence_ids:
            import random
            evidence_id = random.choice(self.evidence_ids)

            response = self.client.get(
                f'/api/evidences/{evidence_id}/pdf/',
                name='/api/evidences/{id}/pdf/ (GET)'
            )

            # Verificar que é PDF válido
            if response.status_code == 200:
                if not response.content.startswith(b'%PDF'):
                    self.environment.stats.events.request_failure.fire(
                        request_type='GET',
                        name='/api/evidences/{id}/pdf/',
                        response_time=response.elapsed.total_seconds() * 1000,
                        response_length=len(response.content),
                        response=response,
                        context={},
                        exception=Exception('Resposta não é PDF válido')
                    )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Hook: executado no início dos testes de carga."""
    print("""
    ╔════════════════════════════════════════════════════════════════╗
    ║ ForensiQ — Teste de Carga (Locust)                            ║
    ║════════════════════════════════════════════════════════════════║
    ║ Cenário: Operação forense completa (first responder + perito)  ║
    ║ - Autenticação JWT                                             ║
    ║ - Criação de ocorrências (GPS, descrição)                      ║
    ║ - Criação de evidências (tipo, hash automático)                ║
    ║ - Criação de dispositivos digitais                             ║
    ║ - Transições de custódia (append-only, validação de estados)   ║
    ║ - Exportação de relatórios PDF                                 ║
    ║════════════════════════════════════════════════════════════════║
    """)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Hook: executado no final dos testes de carga."""
    print("""
    ║════════════════════════════════════════════════════════════════║
    ║ Teste concluído. Relatório disponível em /stats                ║
    ║════════════════════════════════════════════════════════════════╝
    """)


if __name__ == '__main__':
    # Permitir execução direta: python locustfile.py
    print(__doc__)
