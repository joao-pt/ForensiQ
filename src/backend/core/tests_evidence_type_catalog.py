"""
ForensiQ — Catálogo editável de tipos de evidência (``EvidenceTypeRef``, ADR-0018).

Cobre o comportamento que a tarefa #21 entrega: acrescentar um tipo novo SEM
deploy, rever rótulos em runtime, desactivar sem afectar itens já registados, e
a regra de governança *slug write-once*. Complementa ``tests_adr0018_catalogo_tipos``
(que prova que nada disto toca no hash/imutabilidade).

A tabela é semeada pela migração ``0030`` (18 tipos); ``TestCase`` preserva esses
dados (não faz flush), pelo que cada teste arranca com o catálogo completo.
"""

from django.test import TestCase
from rest_framework.exceptions import ValidationError as DRFValidationError

from core import evidence_type_config
from core.models import EvidenceTypeRef
from core.serializers import EvidenceSerializer
from core.tests_factories import EvidenceMobileFactory


class CatalogoSeedTests(TestCase):
    def test_migracao_semeia_os_18_tipos(self):
        self.assertEqual(EvidenceTypeRef.objects.count(), 18)
        self.assertTrue(EvidenceTypeRef.objects.filter(code='MOBILE_DEVICE').exists())


class CatalogoLeituraTests(TestCase):
    def test_active_choices_exclui_inativos_mas_all_choices_mantem(self):
        EvidenceTypeRef.objects.filter(code='MOBILE_DEVICE').update(is_active=False)
        active = [c for c, _ in evidence_type_config.active_choices()]
        todos = [c for c, _ in evidence_type_config.all_choices()]
        self.assertNotIn('MOBILE_DEVICE', active)
        self.assertIn('MOBILE_DEVICE', todos)  # display de itens antigos sobrevive

    def test_active_codes_segue_o_estado(self):
        self.assertIn('MOBILE_DEVICE', evidence_type_config.active_codes())
        EvidenceTypeRef.objects.filter(code='MOBILE_DEVICE').update(is_active=False)
        self.assertNotIn('MOBILE_DEVICE', evidence_type_config.active_codes())

    def test_active_choices_ordena_por_order(self):
        EvidenceTypeRef.objects.create(code='AAA_TARDE', label='Z', order=99)
        EvidenceTypeRef.objects.create(code='ZZZ_CEDO', label='A', order=1)
        codes = [c for c, _ in evidence_type_config.active_choices()]
        self.assertLess(codes.index('ZZZ_CEDO'), codes.index('AAA_TARDE'))


class TipoNovoSemDeployTests(TestCase):
    def test_tipo_criado_em_bd_e_aceite_e_exibe_o_rotulo(self):
        EvidenceTypeRef.objects.create(
            code='SMART_GLASSES', label='Óculos inteligentes', is_active=True, order=50
        )
        # full_clean (no save da factory) valida contra o catálogo vivo → aceita.
        ev = EvidenceMobileFactory(type='SMART_GLASSES')
        self.assertEqual(ev.type, 'SMART_GLASSES')
        self.assertEqual(ev.get_type_display(), 'Óculos inteligentes')

    def test_tipo_desconhecido_e_recusado_no_full_clean(self):
        from django.core.exceptions import ValidationError as DjangoValidationError

        with self.assertRaises(DjangoValidationError):
            EvidenceMobileFactory(type='NAO_EXISTE')


class RotuloEditavelTests(TestCase):
    def test_editar_rotulo_reflecte_em_get_type_display(self):
        EvidenceTypeRef.objects.filter(code='MOBILE_DEVICE').update(
            label='Telemóvel (rótulo editado)'
        )
        ev = EvidenceMobileFactory()  # type=MOBILE_DEVICE
        self.assertEqual(ev.get_type_display(), 'Telemóvel (rótulo editado)')

    def test_desativar_mantem_display_de_item_existente(self):
        ev = EvidenceMobileFactory()  # type=MOBILE_DEVICE
        EvidenceTypeRef.objects.filter(code='MOBILE_DEVICE').update(is_active=False)
        # Continua a resolver o rótulo (all_choices inclui inactivos)…
        self.assertEqual(ev.get_type_display(), 'Telemóvel / Smartphone / Tablet')
        # …mas já não é oferecido em novos formulários.
        self.assertNotIn('MOBILE_DEVICE', evidence_type_config.active_codes())


class SlugWriteOnceTests(TestCase):
    def test_code_e_chave_primaria(self):
        self.assertEqual(EvidenceTypeRef._meta.pk.name, 'code')

    def test_renomear_code_cria_nova_linha_nao_renomeia(self):
        ref = EvidenceTypeRef.objects.get(code='MOBILE_DEVICE')
        ref.code = 'RENAMED'
        ref.save()
        # Com code=PK, "renomear" é inserir: a linha original mantém-se.
        self.assertTrue(EvidenceTypeRef.objects.filter(code='MOBILE_DEVICE').exists())
        self.assertTrue(EvidenceTypeRef.objects.filter(code='RENAMED').exists())


class SerializerTypeValidationTests(TestCase):
    def test_validate_type_aceita_ativo(self):
        self.assertEqual(EvidenceSerializer().validate_type('MOBILE_DEVICE'), 'MOBILE_DEVICE')

    def test_validate_type_recusa_desconhecido(self):
        with self.assertRaises(DRFValidationError):
            EvidenceSerializer().validate_type('NAO_EXISTE')

    def test_validate_type_recusa_inativo(self):
        EvidenceTypeRef.objects.filter(code='MOBILE_DEVICE').update(is_active=False)
        with self.assertRaises(DRFValidationError):
            EvidenceSerializer().validate_type('MOBILE_DEVICE')
