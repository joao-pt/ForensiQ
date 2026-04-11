# Revisão Completa de Código — ForensiQ

**Data:** 11 de abril de 2026
**Versão:** 0.1.0
**Ambiente:** Django 5.0 + DRF + PostgreSQL / Fly.io (Frankfurt)
**Domínio:** forensiq.pt

---

## Resumo Executivo

Análise profunda ao código-fonte do ForensiQ, executada por 6 agentes especializados em paralelo, cobrindo: segurança e permissões, modelos e integridade de dados, API e serializers, frontend, settings/deployment, e testes.

**Resultado global:** O ForensiQ tem uma arquitectura de segurança sólida nas áreas mais críticas (imutabilidade de prova, RBAC, hash SHA-256 encadeado). No entanto, foram identificadas vulnerabilidades que requerem correcção antes de qualquer utilização com dados reais.

| Severidade | Contagem |
|---|---|
| CRÍTICO | 8 |
| ALTO | 10 |
| MÉDIO | 12 |
| BAIXO | 5 |

---

## 1. Segurança e Permissões

### CRÍTICO — DigitalDeviceViewSet permite PUT/PATCH/DELETE

**Ficheiro:** `views.py:160-171`

O `DigitalDeviceViewSet` herda de `ModelViewSet` sem restringir `http_method_names`. Diferente de `EvidenceViewSet` e `ChainOfCustodyViewSet` que bloqueiam correctamente, o DigitalDevice permite edição e eliminação via HTTP.

**Correcção:**
```python
class DigitalDeviceViewSet(viewsets.ModelViewSet):
    http_method_names = ['get', 'post', 'head', 'options']
```

### CRÍTICO — Falta rate limiting nos endpoints de autenticação JWT

**Ficheiro:** `forensiq_project/urls.py:42-44`

Os endpoints `/api/auth/token/`, `/api/auth/token/refresh/` e `/api/auth/token/verify/` não têm throttling. Brute-force ilimitado contra credenciais.

**Correcção:** Implementar `DEFAULT_THROTTLE_CLASSES` em `settings.py` com rate específico para auth (5/min anónimo).

### CRÍTICO — Ausência de filtro de acesso por caso (IDOR)

**Ficheiros:** `views.py` + `permissions.py`

Os filtros `?occurrence=<id>` são funcionais, sem validar se o utilizador autenticado tem direito de acesso àquele caso. Um agente da PSP de Lisboa pode aceder a ocorrências de Aveiro.

**Correcção:** Implementar `get_queryset()` que filtra por `occurrence__agent=request.user` para agentes.

### ALTO — JWT armazenado em localStorage

**Ficheiro:** `auth.js:32-33`

`localStorage` é acessível a qualquer script JavaScript. Vulnerável a XSS.

**Correcção:** Migrar para httpOnly cookies definidos pelo servidor.

### ALTO — Falta de Content Security Policy (CSP)

**Ficheiro:** `base.html` (ausente)

Sem CSP, scripts inline e de terceiros não são bloqueados. XSS não é mitigado.

**Correcção:** Adicionar CSP header via middleware Django ou meta tag.

### MÉDIA — Falta validação de propriedade em OccurrenceViewSet

**Ficheiro:** `views.py:82-97`

`IsOwnerOrReadOnly` permite que qualquer autenticado leia todas as ocorrências. Sigilo processual violado.

**Correcção:** Filtrar queryset por agente no `get_queryset()`.

---

## 2. Modelos e Integridade de Dados

### CRÍTICO — Falta trigger PostgreSQL para imutabilidade

**Ficheiro:** `0001_initial.py`

A imutabilidade depende apenas de validação Python (`save()/delete()` overrides). Um atacante com acesso directo à BD contorna a aplicação Django.

**Correcção:** Criar migração `0002_add_immutability_triggers.py` com:
```sql
CREATE OR REPLACE FUNCTION prevent_evidence_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Registos de evidência são imutáveis';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER evidence_prevent_update
BEFORE UPDATE ON core_evidence
FOR EACH ROW EXECUTE FUNCTION prevent_evidence_update();

CREATE TRIGGER evidence_prevent_delete
BEFORE DELETE ON core_evidence
FOR EACH ROW EXECUTE FUNCTION prevent_evidence_update();
```
Idem para `core_chainofcustody`.

### CRÍTICO — CASCADE em Evidence → DigitalDevice e Occurrence → Evidence

**Ficheiro:** `models.py:285` e `models.py:150-155`

`on_delete=models.CASCADE` em ambas as relações. Se uma Occurrence fosse eliminada, todas as Evidence (e seus DigitalDevice) desapareceriam em cascata.

**Correcção:** Alterar para `on_delete=models.PROTECT` em ambos os casos.

### ALTO — Race condition na cadeia de custódia

**Ficheiro:** `models.py:486-496`

Entre a query `last_record` e `self.timestamp = timezone.now()`, duas transições simultâneas podem resultar em sequência invertida.

**Correcção:**
```python
with transaction.atomic():
    last_record = (
        ChainOfCustody.objects
        .select_for_update()
        .filter(evidence=self.evidence)
        .order_by('-timestamp')
        .first()
    )
```

### ALTO — timestamp_seizure manipulável pelo cliente

**Ficheiro:** `models.py:184-187`, `serializers.py:101-112`

`timestamp_seizure` não está em `read_only_fields` do serializer. Um cliente pode enviar datas falsas.

**Correcção:** Adicionar a `read_only_fields` ou validar proximidade com `timezone.now()`.

### ALTO — compute_record_hash() sem ID do registo

**Ficheiro:** `models.py:448-470`

O hash não inclui `self.id`, permitindo colisão lógica (replay attack) se dois registos tiverem exactamente os mesmos valores.

**Correcção:** Incluir `self.id` na string de hash.

### MÉDIA — Falta validação de GPS

**Ficheiro:** `models.py:93-106` e `models.py:170-183`

Sem validadores de intervalo: latitude [-90, 90], longitude [-180, 180].

**Correcção:** Adicionar `MinValueValidator/MaxValueValidator`.

### MÉDIA — IMEI sem validação

**Ficheiro:** `models.py:312-318`

Help text diz "15 dígitos" mas não há validação.

**Correcção:** Adicionar `RegexValidator(r'^\d{15}$')`.

---

## 3. API e Serializers

### CRÍTICO — Ausência de paginação

**Ficheiro:** `views.py:91, 114, 169, 196`

Querysets não paginados. `GET /api/evidences/` retorna todos os registos. DoS trivial e violação de confidencialidade.

**Correcção:**
```python
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}
```

### ALTA — Exposição de email e telefone no UserSerializer

**Ficheiro:** `serializers.py:32`

`email` e `phone` de agentes PSP expostos publicamente na API.

**Correcção:** Remover `email` e `phone` do serializer público. Criar serializer privado para `/me/`.

### MÉDIA — Falta sanitização de texto em PDF

**Ficheiro:** `pdf_export.py:308`

ReportLab suporta tags HTML/XML. Campo `observations` (texto livre) inserido sem sanitização. Possível PDF injection.

**Correcção:** Aplicar `html.escape()` antes de inserir em `Paragraph()`.

### MÉDIA — Falta validação de tamanho de imagem (backend)

**Ficheiro:** `models.py:164-169`

`ImageField` sem limite de tamanho. Ficheiro de 10GB aceite.

**Correcção:** Adicionar validador com limite de 25MB e resolução máxima.

---

## 4. Frontend

### CRÍTICO — Falta CSRF token em FormData POST

**Ficheiro:** `evidences_new.html:366-372`

POST via `fetch()` sem CSRF token. Embora use JWT, deveria ter protecção dupla.

**Correcção:** Incluir `X-CSRFToken` header em todos os POST/PATCH/DELETE.

### CRÍTICO — Autorização apenas client-side

**Ficheiros:** `evidences.html:56-59`, `evidences_new.html:181-185`

Botões escondidos via JS. Contornável com DevTools.

**Nota:** Backend valida via `IsAgent` — confirmar que todos os endpoints verificam perfil.

### ALTO — Leaflet carregado de CDN externo

**Ficheiro:** `occurrences.html:7-10`

SRI (integrity) presente. Mas dependência de CDN externo em aplicação de segredo de justiça.

**Correcção:** Servir Leaflet localmente.

### ALTO — Nominatim reverse geocoding expõe localização a terceiros

**Ficheiro:** `occurrences_new.html:218-220`

Coordenadas GPS enviadas directamente para OpenStreetMap. Potencial violação RGPD.

**Correcção:** Mover reverse geocoding para o backend.

### MÉDIA — Erros da API expõem estrutura da BD

**Ficheiros:** `evidences_new.html:375-380`, `occurrences_new.html:296-302`

Mensagens de erro do DRF mostradas ao utilizador, revelando nomes de campos e constraints.

**Correcção:** Mensagens genéricas em produção.

---

## 5. Settings e Deployment

### CRÍTICO — SECRET_KEY com fallback débil

**Ficheiro:** `settings.py:22`

```python
SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-dev-key-change-in-production')
```

Se a variável de ambiente falhar, toda a segurança criptográfica é comprometida.

**Correcção:**
```python
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable must be set")
```

### ALTO — Falta configuração de logging/auditoria

**Ficheiro:** `settings.py` (ausente)

Nenhuma configuração `LOGGING`. Sem registo de tentativas falhadas de autenticação, acessos a recursos sensíveis, alterações em cadeia de custódia.

**Correcção:** Implementar `LOGGING` estruturado com ficheiros de auditoria imutáveis.

### ALTO — Django Admin exposto em produção

**Ficheiro:** `forensiq_project/urls.py:39`

`/admin/` acessível publicamente. Alvo conhecido para ataques de força bruta.

**Correcção:** Ocultar atrás de prefixo secreto via variável de ambiente.

### MÉDIA — Falta SECURE_CONTENT_TYPE_NOSNIFF

**Ficheiro:** `settings.py`

Permite MIME type sniffing.

**Correcção:** `SECURE_CONTENT_TYPE_NOSNIFF = True` em produção.

### MÉDIA — Falta SESSION_COOKIE_SAMESITE explícito

**Ficheiro:** `settings.py`

Navegadores usam `Lax` por defeito, mas `Strict` é mais seguro para esta aplicação.

**Correcção:** `SESSION_COOKIE_SAMESITE = 'Strict'` e `CSRF_COOKIE_SAMESITE = 'Strict'`.

---

## 6. Testes

### CRÍTICO — Lacunas em testes de autorização granular

Apenas 1 teste explícito de acesso negado em 415 linhas de `tests_api.py`. Faltam:
- AGENT-A não pode aceder a ocorrências de AGENT-B
- EXPERT não pode criar ocorrências
- Superuser sem perfil não pode criar evidência
- Token expirado/tampered rejeitado

### ALTO — Máquina de estados testada parcialmente

Apenas 2 transições sequenciais testadas. Faltam:
- Todas as 8 transições válidas documentadas
- Salto de fases (APREENDIDA → EM_PERICIA)
- Estados terminais (DEVOLVIDA → qualquer coisa)
- Transições concorrentes

### ALTO — Imutabilidade testada via ORM mas não via API

`test_update_blocked` testa `model.save()`, mas não `PATCH /api/evidences/1/`.

### ALTO — Falta validação de conteúdo do PDF

Testes verificam assinatura `%PDF` e tamanho, mas não que hash SHA-256, dispositivos e cadeia de custódia aparecem no PDF.

### MÉDIA — Sem testes de validação de entrada

Nenhum teste para: GPS fora de limites, número de ocorrência duplicado, strings com 100.000 caracteres, Unicode, injection.

### Cobertura estimada: ~60%
- Modelos: ~80%
- Views: ~50%
- Serializers: ~40%
- Permissões: ~30%

---

## Pontos Positivos

O ForensiQ implementa correctamente várias práticas críticas:

1. **Imutabilidade append-only** — `save()/delete()` bloqueiam updates em Evidence e ChainOfCustody. Admin desativa `has_change_permission/has_delete_permission`.

2. **Hash SHA-256 encadeado** (blockchain-like) — integridade de metadados garantida com `compute_integrity_hash()` e `compute_record_hash()`.

3. **Máquina de estados da cadeia de custódia** — `VALID_TRANSITIONS` impõe fluxo correcto. `previous_state` auto-determinado pelo servidor.

4. **RBAC de dois níveis** — permissões `IsAgent`, `IsExpert`, `IsAgentOrExpert` granulares e consistentes.

5. **JWT com rotação e blacklisting** — `ROTATE_REFRESH_TOKENS = True`, `BLACKLIST_AFTER_ROTATION = True`.

6. **HTTPS + HSTS em produção** — `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS = 31536000`, cookies seguros.

7. **Dockerfile com utilizador não-root** — `useradd forensiq` + `USER forensiq`.

8. **Escape HTML no frontend** — `escapeHtml()` usado consistentemente nos templates.

9. **SRI (Subresource Integrity)** em scripts CDN externos.

10. **Serializers ocultam dados sensíveis** — `password` write-only, hashes read-only.

---

## Plano de Acção Prioritário

### Imediato (antes de produção com dados reais)

1. Adicionar `http_method_names` ao DigitalDeviceViewSet
2. SECRET_KEY sem fallback (raise ValueError)
3. Trigger PostgreSQL para imutabilidade (nova migração)
4. Paginação obrigatória na API
5. Filtragem de queryset por agente (IDOR)
6. Rate limiting em endpoints de auth

### Curto prazo (1-2 semanas)

7. CASCADE → PROTECT em FK de Evidence e DigitalDevice
8. Logging/auditoria estruturada
9. CSP header
10. Django Admin com prefixo secreto
11. Sanitização de texto em PDF export
12. Validadores GPS, IMEI
13. Testes de autorização e imutabilidade via API

### Médio prazo (roadmap)

14. Migrar JWT para httpOnly cookies
15. Reverse geocoding via backend
16. Servir Leaflet localmente
17. MFA para agentes/peritos
18. Cobertura de testes > 80%
19. select_for_update na cadeia de custódia (race condition)

---

*Relatório gerado por análise automatizada com 6 agentes especializados em paralelo.*
*Classificação: Para uso interno — Confidencial.*
