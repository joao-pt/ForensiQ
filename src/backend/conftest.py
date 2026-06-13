"""Fixtures globais da suite pytest (core/ + e2e/).

A cache default é DatabaseCache (settings.CACHES → tabela forensiq_cache),
que NÃO é tabela de modelo: o flush dos TransactionTestCase não a trunca,
pelo que estado de cache committed (ex.: histórico de throttle dos testes
que o reativam) ACUMULAVA ao longo da suite completa e envenenava testes
posteriores (logins a devolver 429 em cadeia — centenas de ERRORs que não
reproduziam em isolamento). Limpar a cache entre testes devolve a
hermeticidade que o rollback transacional não cobre.
"""

import pytest
from django.core.cache import caches
from django.test.testcases import DatabaseOperationForbidden


@pytest.fixture(autouse=True)
def _clear_caches_between_tests():
    yield
    try:
        for cache in caches.all():
            cache.clear()
    except DatabaseOperationForbidden:
        # SimpleTestCase não pode tocar na BD — e por isso também não pode
        # ter sujado a cache de BD; não há nada para limpar.
        pass
