"""Seed idempotente da taxonomia de crimes + Política Criminal (ADR-0014).

Lê ``core/data/tabela_crimes_2024.json`` (3 níveis da Tabela de Crimes
Registados 1.7) e ``core/data/mapa_politica_criminal.json`` (Lei 51/2023 →
códigos, por eixo) e popula ``CrimeCategoria``/``CrimeSubcategoria``/
``CrimeTipo`` + ``PoliticaCriminalPrioridade`` + ``PrioridadeCrimeTipo``.

Idempotente (``update_or_create`` por código oficial). É **dados de referência**
— não mexe em prova nem em dados de demonstração (esses são do ``seed_demo``).

    python manage.py seed_crime_taxonomy
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    CrimeCategoria,
    CrimeSubcategoria,
    CrimeTipo,
    PoliticaCriminalPrioridade,
    PrioridadeCrimeTipo,
)

DATA_DIR = Path(__file__).resolve().parents[2] / 'data'


class Command(BaseCommand):
    help = (
        'Semeia a taxonomia de crimes (Tabela de Crimes Registados 1.7) e a '
        'Política Criminal (Lei 51/2023) a partir de core/data/*.json. Idempotente.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--tabela', default=str(DATA_DIR / 'tabela_crimes_2024.json'))
        parser.add_argument('--mapa', default=str(DATA_DIR / 'mapa_politica_criminal.json'))

    @transaction.atomic
    def handle(self, *args, **opts):
        tabela = self._load(opts['tabela'])
        mapa = self._load(opts['mapa'])
        n_cat, n_sub, n_tipo = self._seed_taxonomia(tabela)
        n_assoc = self._seed_politica(mapa)
        self.stdout.write(
            self.style.SUCCESS(
                f'Taxonomia: {n_cat} categorias, {n_sub} subcategorias, {n_tipo} tipos. '
                f'Política Criminal: {n_assoc} associações.'
            )
        )

    @staticmethod
    def _load(path):
        p = Path(path)
        if not p.exists():
            raise CommandError(f'Ficheiro não encontrado: {p}')
        return json.loads(p.read_text(encoding='utf-8'))

    def _seed_taxonomia(self, tabela):
        cat_by_codigo = {}
        for c in tabela['categorias']:
            obj, _ = CrimeCategoria.objects.update_or_create(
                codigo=c['codigo'], defaults={'nome': c['nome']}
            )
            cat_by_codigo[c['codigo']] = obj

        sub_by_codigo = {}
        for s in tabela['subcategorias']:
            obj, _ = CrimeSubcategoria.objects.update_or_create(
                codigo=s['codigo'],
                defaults={'nome': s['nome'], 'categoria': cat_by_codigo[s['categoria']]},
            )
            sub_by_codigo[s['codigo']] = obj

        for t in tabela['tipos']:
            CrimeTipo.objects.update_or_create(
                codigo=t['codigo'],
                defaults={
                    'descritivo': t['descritivo'],
                    'subcategoria': sub_by_codigo[t['subcategoria']],
                    'is_active': True,
                },
            )
        return len(tabela['categorias']), len(tabela['subcategorias']), len(tabela['tipos'])

    def _seed_politica(self, mapa):
        meta = mapa['meta']
        vigente_ate = meta.get('vigente_ate')
        politica, _ = PoliticaCriminalPrioridade.objects.update_or_create(
            lei=meta['lei'],
            defaults={
                'biennium': meta['biennium'],
                'vigente_desde': date.fromisoformat(meta['vigente_desde']),
                'vigente_ate': date.fromisoformat(vigente_ate) if vigente_ate else None,
                'is_active': meta.get('is_active', True),
            },
        )
        # Substituição limpa das associações desta versão (sem legado).
        politica.associacoes.all().delete()
        n = 0
        for a in mapa['associacoes']:
            tipo = CrimeTipo.objects.filter(codigo=a['codigo']).first()
            if tipo is None:
                raise CommandError(
                    f'Código {a["codigo"]} do mapa de política criminal não existe na taxonomia.'
                )
            PrioridadeCrimeTipo.objects.create(politica=politica, crime_tipo=tipo, eixo=a['eixo'])
            n += 1
        return n
