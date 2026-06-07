# ADR-0006: Extensibilidade e Arquitectura Modular

## Status
Accepted

## Data
2026-04-12

## Context

O ForensiQ é uma plataforma modular de gestão de prova digital com ambição de suportar múltiplos contextos forenses (digital, biológico, químico) e diversos tipos de utilizadores. A arquitectura deve permitir:

1. **Novos tipos de prova** — DNA, fibras, tóxicos, sem recompilar o núcleo
2. **Novos módulos forenses** — Apps Django especializadas (ex: `forensics_bio`, `forensics_chem`) que partilham a infraestrutura base
3. **Novos perfis de utilizador** — Perito biólogo, químico, gestor de laboratório, com permissões apropriadas
4. **Novos estados de custódia** — Contextos específicos (ex: armazenamento criogénico, replicação) que expandem a máquina de estados
5. **Novos formatos de exportação** — Relatórios em Word, Excel, XML, sem modificar a API existente
6. **Módulos transversais** — Auditoria, logs de atividade, compliance (ISO/IEC 27037, ISO/IEC 27001)

Sem arquitectura modular, cada novo requisito forçaria mudanças centralizadas nos modelos de `core`, risco crescente de regressões, e dificuldade em manter múltiplas variantes do produto.

## Decision

A arquitectura assenta em cinco pilares:

### 1. Django Apps Reutilizáveis

> **Estado atual:** o backend é uma **única** app Django (`core`); o resto de
> `src/backend/` são `forensiq_project/` (projeto), `tests/` e `e2e/`. As apps
> `forensics_bio`/`forensics_chem` e a estrutura multi-app abaixo são roadmap de
> extensibilidade, ainda não implementado. Prevê-se que módulos futuros sejam
> Django apps independentes que reutilizam `core` por FK (não por herança de modelo).

Estrutura base em `src/backend/core/` com modelos agnósticos:
- `User` — utilizador genérico com campo `profile`. Os valores atuais (ADR-0017) são `FIRST_RESPONDER`, `FORENSIC_EXPERT`, `EVIDENCE_CUSTODIAN`, `CASE_AUTHORITY`, `CHEFE_SERVICO`, `AUDITOR`. Perfis de domínio biológico/químico (ex: `BIOLOGIST`, `CHEMIST`, `LAB_MANAGER`) são exemplos hipotéticos de extensão futura, ainda não implementados.
- `Occurrence` — caso genérico (local, data, descrição)
- `Evidence` — prova genérica (FK para Occurrence, type, description, integrity_hash SHA-256)
- `ChainOfCustody` — cadeia append-only encadeada, agnóstica ao tipo de prova
- `AuditLog` — auditoria transversal (user, action, resource_type, timestamp, correlation_id)

Novos módulos (ex: `forensics_bio`) criar-se-ão como Django apps independentes:
```
src/backend/
├── core/                    # Base (User, Occurrence, Evidence, ChainOfCustody)
├── forensics_bio/           # Novo módulo biológico
│   ├── models.py           # DNAProfile, BiologicalMarker, etc.
│   ├── views.py            # Viewsets especializados
│   ├── serializers.py
│   └── tests.py
└── forensics_chem/          # Novo módulo químico (futuro)
```

### 2. Services Layer para Lógica Reutilizável

> **Estado atual:** `core/services/` contém apenas `imei_lookup.py` e
> `vin_lookup.py` (mais `__init__.py`). A exportação PDF vive em `core/pdf_export.py`,
> como módulo direto, não atrás de uma interface. A abstração `ExportService` e um
> `hash_service.py` dedicado ainda **não** estão implementados — o que se segue é a
> proposta de design para quando a variedade de exportadores/serviços o justificar.

Operações comuns (hashing, encadeamento, exportação, auditoria) passariam a viver
em módulos de serviço com interface estável:

```python
# core/services/hash_service.py  (proposto)
def compute_evidence_hash(evidence: Evidence) -> str:
    """Calcula SHA-256 de um Evidence, independente do tipo."""

# core/services/export_service.py  (proposto)
class ExportService(ABC):
    @abstractmethod
    def export(self, evidence: Evidence) -> bytes:
        """Interface para exportadores."""

class PDFExporter(ExportService):
    def export(self, evidence: Evidence) -> bytes: ...

class ExcelExporter(ExportService):
    def export(self, evidence: Evidence) -> bytes: ...
```

### 3. Signals para Desacoplamento

Novo tipo de prova → novo handler, sem modificar `core`:

```python
# forensics_bio/apps.py — configuração de app
class BiologyConfig(AppConfig):
    def ready(self):
        from . import signals  # Registar handlers

# forensics_bio/signals.py
@receiver(post_save, sender=Evidence)
def on_evidence_created(sender, instance, created, **kwargs):
    if instance.type == 'DNA':
        # Lógica específica de DNA (enviar para análise, etc.)
        send_to_lab.delay(instance.id)
```

### 4. Choices Enum para Extensão Segura

Em vez de strings hardcoded, usar enums Django com Choices:

```python
# core/models.py
class EvidenceType(models.TextChoices):
    DIGITAL_DEVICE = 'DIGITAL_DEVICE', 'Dispositivo Digital'
    DNA = 'DNA', 'Perfil DNA'
    FIBER = 'FIBER', 'Fibra'
    TOXICOLOGY = 'TOXICOLOGY', 'Análise Toxicológica'

class Evidence(models.Model):
    type = models.CharField(max_length=20, choices=EvidenceType.choices)

# forensics_bio/models.py — estender sem herança
class DNAProfile(models.Model):
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT)
    markers = models.JSONField()  # STR markers em JSON
```

### 5. Permissões Granulares via Permission Classes

Novos perfis → novas permission classes:

```python
# core/permissions.py
class IsExpert(BasePermission):
    def has_permission(self, request, view):
        return request.user.profile == 'EXPERT'

class IsBiologist(BasePermission):
    def has_permission(self, request, view):
        return request.user.profile == 'BIOLOGIST'

# forensics_bio/views.py
class DNAProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsBiologist]
```

## Pontos de Extensão Concretos

> **Nota de estado:** os pontos A, B e C descrevem o caminho previsto para
> domínios forenses adicionais (toxicologia, biologia, química) em apps próprias
> com FK para `core`. Nenhum desses módulos existe hoje — o backend tem apenas a
> app `core`. São apresentados como roadmap, não como código existente.

### A. Novos Tipos de Prova

**Processo:**
1. Adicionar choice ao `EvidenceType` enum em `core/models.py`
2. Criar nova app especializada (ex: `forensics_toxicology`)
3. Implementar modelo associado (ex: `ToxicologySample`) com FK para `Evidence`
4. Registar viewset e serializer em `forensics_toxicology/views.py`
5. Incluir URLs em `forensics_project/urls.py`

**Exemplo:** Adicionar "Toxicologia"
```python
# core/models.py
class EvidenceType(models.TextChoices):
    TOXICOLOGY = 'TOXICOLOGY', 'Análise Toxicológica'

# forensics_toxicology/models.py
class ToxicologySample(models.Model):
    evidence = models.OneToOneField(Evidence, on_delete=models.PROTECT, primary_key=True)
    substance = models.CharField(max_length=100)
    concentration_mg_l = models.FloatField()
    test_method = models.CharField(max_length=50)  # GC-MS, HPLC, etc.
```

### B. Novos Módulos Forenses

**Processo:**
1. Criar app `forensics_<domain>/` com estrutura padrão (models, views, serializers, tests, permissions)
2. Herdar de `core` (User, Occurrence, Evidence, ChainOfCustody) via FK, não herança de modelo
3. Registar signals em `ready()` do AppConfig se houver lógica transversal
4. Incluir em `INSTALLED_APPS` de `settings.py`
5. Executar `makemigrations` e `migrate`

**Exemplo:** App de análise biológica
```python
# forensics_bio/apps.py
class BioConfig(AppConfig):
    name = 'forensics_bio'
    def ready(self):
        from . import signals

# forensics_bio/models.py
class BiologicalMarker(models.Model):
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT)
    marker_name = models.CharField(max_length=50)  # STR D8S1179, etc.
    allele_1 = models.IntegerField()
    allele_2 = models.IntegerField()

# forensics_bio/permissions.py
class IsBiologist(BasePermission):
    def has_permission(self, request, view):
        return request.user.profile == 'BIOLOGIST'

# forensics_bio/views.py
class BiologicalMarkerViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsBiologist]
    serializer_class = BiologicalMarkerSerializer
    queryset = BiologicalMarker.objects.all()
```

### C. Novos Perfis de Utilizador

**Processo:**
1. Adicionar choice ao `Profile` enum em `core/models.py`
2. Criar nova permission class (ex: `IsBiologist`)
3. Associar a viewsets específicos da app correspondente
4. Atualizar Django Admin se necessário

> **Estado atual (ADR-0017):** o enum `Profile` real em `core/models.py` tem seis
> valores — `FIRST_RESPONDER`, `FORENSIC_EXPERT`, `EVIDENCE_CUSTODIAN`,
> `CASE_AUTHORITY`, `CHEFE_SERVICO`, `AUDITOR`. O exemplo abaixo (`CHEMIST` e
> companhia) é hipotético e ilustra como acrescentar um perfil de domínio futuro;
> não existe hoje.

**Exemplo (hipotético):** Novo perfil "Perito Químico"
```python
# core/models.py — exemplo de extensão futura, não o enum atual
class Profile(models.TextChoices):
    FIRST_RESPONDER = 'FIRST_RESPONDER', 'Agente / Primeiro interveniente'
    FORENSIC_EXPERT = 'FORENSIC_EXPERT', 'Perito forense digital'
    # ... restantes valores atuais (ADR-0017) ...
    CHEMIST = 'CHEMIST', 'Perito Químico'  # novo, a acrescentar

# forensics_chem/permissions.py
class IsChemist(BasePermission):
    def has_permission(self, request, view):
        return request.user.profile == 'CHEMIST'

# forensics_chem/views.py
class ChemicalAnalysisViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsChemist]
```

### D. Novos Actos de Custódia

> **Estado atual (ADR-0015):** a custódia **não** é uma máquina de estados. Foi
> substituída por um ledger de eventos append-only: cada evento tem um `EventType`
> (acto processual) e um `CustodianType` (quem detém a prova após o evento), ambos
> `TextChoices` em `core/models.py`. Não existe `STATUS_CHOICES` nem
> `VALID_TRANSITIONS` — o estado legal é **derivado** da sequência de eventos, e as
> regras de aceitação são guardas mínimas (génese única, eventos terminais que
> fecham o ledger, etc.), não uma tabela de transições.

**Processo:**
1. Acrescentar o valor a `EventType` (e/ou `CustodianType`) — `TextChoices` em `core/models.py`
2. Se o novo acto encerrar a cadeia, adicioná-lo a `TERMINAL_EVENTS`; se for génese, a `GENESIS_EVENTS`
3. Acrescentar as guardas mínimas necessárias na validação do evento, sem reintroduzir uma tabela de transições
4. Testar a derivação do estado legal e as guardas com novos casos

**Exemplo:** Acrescentar acto "Armazenamento criogénico"
```python
# core/models.py
class CustodianType(models.TextChoices):
    # ... valores atuais ...
    LAB_PUBLICO = 'LAB_PUBLICO', 'Laboratório público'
    CRIO = 'CRIO', 'Armazenamento criogénico'  # novo custódio

class EventType(models.TextChoices):
    # ... actos atuais ...
    ENTRADA_CRIO = 'ENTRADA_CRIO', 'Entrada em armazenamento criogénico'  # novo acto
# Sem VALID_TRANSITIONS: o estado legal continua a derivar-se do ledger.
```

### E. Novos Formatos de Exportação

> **Estado atual:** só existe exportação PDF, em `core/pdf_export.py` (módulo
> direto). A interface `ExportService` em `core/services/export_service.py` ainda
> não existe — o processo abaixo é o desenho previsto para o dia em que se
> acrescentar um segundo formato (Excel, Word, XML) e fizer sentido fatorizar a
> abstração.

**Processo (proposto):**
1. Implementar `ExportService` (interface a definir em `core/services/export_service.py`)
2. Registar em factory ou router
3. Expor via endpoint `/api/evidences/{id}/export/{format}/`

**Exemplo (proposto):** Exportador Excel
```python
# core/services/export_service.py
from abc import ABC, abstractmethod

class ExportService(ABC):
    @abstractmethod
    def export(self, evidence: Evidence) -> bytes:
        pass

# core/services/excel_export.py
import openpyxl
from .export_service import ExportService

class ExcelExporter(ExportService):
    def export(self, evidence: Evidence) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws['A1'] = f'Evidence {evidence.id}'
        ws['A2'] = evidence.description
        ws['A3'] = evidence.integrity_hash
        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

# core/views.py
@action(detail=True, methods=['get'])
def excel(self, request, pk=None):
    evidence = self.get_object()
    exporter = ExcelExporter()
    content = exporter.export(evidence)
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
```

### F. Módulo de Auditoria Transversal

Exemplo já implementado: `core/audit.py` e `core/models.py:AuditLog`

```python
# core/models.py
class AuditLog(models.Model):
    class Action(models.TextChoices):
        VIEW = 'VIEW', 'Visualização'
        CREATE = 'CREATE', 'Criação'
        EXPORT_PDF = 'EXPORT_PDF', 'Exportação PDF'
        EXPORT_CSV = 'EXPORT_CSV', 'Exportação CSV'
        AUDIT_PURGE = 'AUDIT_PURGE', 'Expurgo de Logs (retenção RGPD)'
        SYSTEM_ALERT = 'SYSTEM_ALERT', 'Alerta Operacional (quota/auth)'
        # Sem UPDATE/DELETE: as entidades auditadas são imutáveis (append-only).
    
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20, choices=Action.choices)
    resource_type = models.CharField(max_length=20)  # OCCURRENCE, EVIDENCE, CUSTODY, DEVICE, SYSTEM
    resource_id = models.IntegerField()
    ip_address = models.GenericIPAddressField()
    correlation_id = models.CharField(max_length=36, blank=True, default='')  # UUID da requisição
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict)

# Qualquer app pode chamar:
from core.audit import log_access
log_access(
    request=request,
    action=AuditLog.Action.EXPORT_PDF,
    resource_type='EVIDENCE',
    resource_id=evidence.id,
    details={'format': 'pdf'}
)
```

## Alternatives Considered

- **Herança de modelo** — Criar subclasses de Evidence (ex: `class DNAEvidence(Evidence)`)
  - Alternativa: Multi-table inheritance, mas complica queries e migrações
  - **Rejeitada:** FK é mais simples, menos overhead de BD, mais flexível

- **Settings globals para extensão** — Configurar tudo em `settings.py`
  - **Rejeitada:** Acoplamento centralizado, não escalável além de 5-10 tipos

- **Monolito único** — Colocar tudo em `core`
  - **Rejeitada:** Violaria princípio de responsabilidade única (SRP), dificultaria manutenção

## Consequences

### Positivas
- **Desacoplamento modular** — Novos tipos de prova/módulos sem afetar `core`
- **Testabilidade isolada** — Cada app tem suite de testes própria
- **Reutilização de código** — Services (hash, export, audit) partilhados
- **Escalabilidade organizacional** — Diferentes equipas (digitais, biólogos, químicos) desenvolvem em paralelo
- **Conformidade** — Auditoria transversal via `AuditLog` cobre novos módulos automaticamente
- **Deploy modular** — Possibilidade de ativar/desativar módulos (ex: `INSTALLED_APPS` conditional)

### Negativas
- **Complexidade inicial** — Mais ficheiros, mais estrutura (10-15 ficheiros por nova app)
- **Over-engineering para MVP** — Se apenas DIGITAL_DEVICE for necessário, é overhead
- **Custo de sincronização** — Actualizar interface `ExportService` requer mudanças em múltiplas apps
- **Risco de fragmentação** — Se guidelines não forem estritas, cada app pode ter padrões diferentes
- **Testes de integração complexos** — Apps interdependentes requerem testes E2E (core + bio + chem)

### Mitigações

> Estas mitigações são o plano a executar quando o primeiro módulo de domínio for
> criado; ainda não estão implementadas. Em particular, `scripts/create_forensics_app.sh`
> não existe (em `scripts/` há apenas `run_lighthouse.ps1`) — é uma proposta.

- Criar **template Django app** (proposto: `scripts/create_forensics_app.sh`) para consistência
- Documentar **convenções de naming** e **estrutura de ficheiros** neste ADR
- Criar **testes de integração genéricos** que verifiquem o contrato de `ExportService` para todas as apps
- Guardar **exemplos de implementação** em cada módulo novo como referência
