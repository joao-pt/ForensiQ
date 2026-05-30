# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ForensiQ — modular digital evidence management platform for first responders. Academic project for UC 21184 (Universidade Aberta). Backend Django 6 + DRF, frontend HTML/CSS/JS vanilla (no build step). Deployed at <https://forensiq.pt> on Fly.io (Frankfurt) with PostgreSQL on Neon.tech.

**Language convention:** all docs, commit messages, code comments, commit message tooling and conventional-commit types are in **Portuguese (PT-PT)**. Preserve PT-PT when editing existing strings/comments.

## Common commands

All Python commands run from `src/backend/` with the virtualenv at `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (Unix).

```bash
# Setup (from repo root)
python -m venv .venv
.venv/Scripts/activate
pip install -r src/backend/requirements.txt -r src/backend/requirements-dev.txt
pre-commit install
cp .env.example .env  # then fill in SECRET_KEY, DATABASE_URL, etc.

# Run dev server
cd src/backend
python manage.py migrate
python manage.py runserver

# Tests — IMPORTANT: always use test_settings (SQLite in-memory, no Neon required)
python -m pytest -q                                                 # via pytest (pyproject sets DJANGO_SETTINGS_MODULE)
python manage.py test core --settings=forensiq_project.test_settings  # via Django runner (what CI uses)

# Single test
python -m pytest core/tests_api.py::EvidenceAPITest::test_create_evidence -q
python manage.py test core.tests_api.EvidenceAPITest.test_create_evidence --settings=forensiq_project.test_settings

# Coverage — gate único enforçado em CI: pyproject `fail_under=80` (real ~84%).
# `coverage report` falha o build se descer abaixo de 80% (T13).
coverage run --source='core,forensiq_project' manage.py test core --settings=forensiq_project.test_settings
coverage report --show-missing

# Lint / format (configured in pyproject.toml — line length 100, single quotes)
ruff check src/backend --fix
ruff format src/backend
black src/backend

# Seed demo data (interactive prompts for AGENT/EXPERT credentials)
python manage.py seed_demo --reset
python manage.py seed_demo --users-only        # only the 2 demo users
python manage.py seed_demo --reset --no-input --agent-username=ag --agent-password=Aa12345! --expert-username=pe --expert-password=Ee12345!
```

`seed_demo` never creates superusers — use `python manage.py createsuperuser` separately.

## Architecture

### Layout

```
src/backend/
  forensiq_project/     # Django project: settings.py, test_settings.py, urls.py
  core/                 # The only app — all models, views, serializers, tests live here
    models.py           # User, Occurrence, Evidence, DigitalDevice, ChainOfCustody, AuditLog
    views.py            # DRF ViewSets (API)
    frontend_views.py   # Server-rendered HTML views
    auth.py             # JWTCookieAuthentication (HttpOnly cookies)
    auth_views.py       # /api/auth/{login,refresh,logout}/
    middleware.py       # CorrelationIDMiddleware, ContentSecurityPolicyMiddleware (CSP nonce per request)
    services/           # External integrations (imei_lookup, vin_lookup)
    pdf_export.py       # ReportLab PDF generation for evidence
    management/commands/seed_demo.py
src/frontend/
  templates/            # Django templates (loaded via TEMPLATES['DIRS'])
  static/               # CSS/JS/img served via WhiteNoise
```

There is exactly one Django app (`core`). Do not create new apps; extend `core` instead unless the work justifies a split.

### Forensic invariants — do not break these

The codebase enforces **immutability of evidence** at three layers (see ADR-0009/0010 and `docs/architecture/diagrams/immutability-3-layers`). Any change touching `Evidence`, `ChainOfCustody`, or `AuditLog` must preserve all three:

1. **DB triggers** — migration `0002_add_immutability_triggers` + `0008_extend_immutability` install PostgreSQL triggers (`prevent_evidence_modification`, etc.) that block `UPDATE`/`DELETE` on `Evidence` and `ChainOfCustody`. These triggers don't fire on SQLite (test DB), so tests verifying immutability must explicitly use `@override_settings` or assert at the ORM layer.
2. **Admin** — `has_change_permission`/`has_delete_permission` return `False` on `EvidenceAdmin`, `ChainOfCustodyAdmin`, `AuditLogAdmin` **even for superusers**. This is intentional (ISO/IEC 27037 §5.4).
3. **API** — `EvidenceViewSet` and `ChainOfCustodyViewSet` permit `POST` only; no `PUT`/`PATCH`/`DELETE` is exposed.

`ChainOfCustody` is a **hash-chained append-only ledger** (SHA-256 of previous record's hash + new fields). State transitions follow a strict linear FSM: `APREENDIDA → EM_TRANSPORTE → RECEBIDA_LABORATORIO → EM_PERICIA → CONCLUIDA → DEVOLVIDA | DESTRUIDA`. The transition validator lives in the model — don't replicate it in views.

`Evidence` taxonomy is 18 types (14 root + 4 sub-component) with self-FK `parent_evidence`, max depth 3, anti-cycle validation. Adding new types means updating the choices enum + the validator + the frontend type selector together.

### Auth model (ADR-0009)

JWT lives in **HttpOnly cookies** (`fq_access`, `fq_refresh`) — not in `Authorization: Bearer` headers and not in localStorage. The CSRF cookie is non-HttpOnly (must be readable by JS) and is enforced on all non-safe methods. `JWTCookieAuthentication` (custom, in `core/auth.py`) is the DRF default — do not switch back to header-based JWT without a new ADR.

Tests using DRF `APIClient.force_authenticate` bypass cookie auth — that's intentional. Tests that exercise CSRF/IDOR explicitly must use real cookie flow.

### Settings split

`forensiq_project/settings.py` is the production-shaped config; it auto-detects test mode (`TESTING` var) and relaxes throttles + skips HTTPS hardening when running under `pytest` / `manage.py test`. `forensiq_project/test_settings.py` further overrides for SQLite in-memory + no throttles + no WhiteNoise. **Always pass `--settings=forensiq_project.test_settings` when invoking `manage.py test`** — the CI workflow does this, the dev convenience commands in README do not.

Throttle scopes (`auth`, `evidence_upload`, `pdf_export`, `csv_export`, `schema`, `reverse_geocode`) are set in production settings; tests reactivate them with `@override_settings` when validating throttling specifically.

### Frontend

No build step, no framework. Templates in `src/frontend/templates/`, vanilla JS/CSS in `src/frontend/static/`. CSP is enforced with a **per-request nonce** injected by `ContentSecurityPolicyMiddleware` — every `<script>` and `<style>` block needs `nonce="{{ request.csp_nonce }}"`. No `unsafe-inline`. External assets must come from the CSP allowlist (currently `cdnjs.cloudflare.com` + Leaflet/OSM origins); drf-spectacular's swagger uses `drf-spectacular-sidecar` to serve assets locally instead of jsdelivr.

`tests_frontend_js_namespace.py` scans templates for top-level JS identifier collisions across pages — keep top-level names unique or wrap in IIFE/module scope.

## Conventional Commits (PT-PT)

CI/contrib expects Portuguese conventional commits — see `CONTRIBUTING.md`. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Description in lowercase Portuguese.

```
feat: adicionar validação de IMEI Luhn no formulário
fix: corrigir cálculo de hash em transições de custódia
docs: actualizar ADR-0010 com novos tipos de evidência
```

## CI

- `.github/workflows/ci.yml` — runs `manage.py test core --settings=forensiq_project.test_settings` with coverage on Python 3.12, SQLite.
- `.github/workflows/security.yml` — pip-audit, bandit (severity HIGH, confidence HIGH on `src/backend/core`), gitleaks, trivy fs scan (CRITICAL/HIGH, fail on findings). Pre-commit also runs semgrep `p/owasp-top-ten` + `p/django`.

A failing security scan should be fixed at the root (upgrade the pinned dep, remove the secret, rewrite the pattern). Do not add ignores without a comment explaining why.

## Commit identity

**All commits and PRs are solo-authored as `joao-pt` (João M. M. Rodrigues).** Never add `Co-Authored-By: Claude …`, `🤖 Generated with Claude Code`, or any reference to Claude / Anthropic / AI assistants in commit messages, PR titles, PR bodies, or branch names. This is an academic project where authorship attribution matters; AI assistance is acknowledged once in the README, not on every commit. If the built-in commit recipe tries to inject those trailers, strip them before committing.

## Things to avoid

- Don't add a new Django app — extend `core`.
- Don't bypass the immutability layers (admin, API, DB triggers) — even for "fix-up" or "data migration" tasks. If data really needs editing, write a one-shot migration with a clear comment justifying why this isn't compromising the audit story.
- Don't add new CDN origins to CSP without updating both the middleware allowlist and an ADR.
- Don't introduce a JS build step or framework — ADR-0004 commits to vanilla.
- Don't switch JWT back to `Authorization: Bearer` headers — ADR-0009 commits to HttpOnly cookies.
- Don't write English commit messages or comments in files that are already in PT-PT.
