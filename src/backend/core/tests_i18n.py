"""
ForensiQ — Testes de localização pt-PT das mensagens de biblioteca.

Contexto: com ``LANGUAGE_CODE='pt-pt'`` o SimpleJWT não traz catálogo
``pt``/``pt_PT`` (só ``pt_BR``), pelo que as suas mensagens saíam em
INGLÊS — incluindo o erro de login ``"No active account found with the
given credentials"``. A DRF, por seu lado, resolve para o catálogo ``pt``
(português do Brasil, com erros gramaticais). O catálogo de projeto em
``locale/pt_PT/LC_MESSAGES/`` (via ``LOCALE_PATHS``) sobrepõe ambos.

Estes testes são também o guarda contra *msgid drift*: se uma atualização
de uma biblioteca mudar o texto-fonte inglês, a tradução deixa de casar e
estes testes falham (em vez de a regressão passar despercebida).
"""

from django.core.management import call_command
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation
from rest_framework import status
from rest_framework.test import APITestCase

from core.tests_factories import TEST_PASSWORD, UserFactory

LOGIN_NO_ACCOUNT = 'Credenciais inválidas. Verifique o utilizador e a palavra-passe.'


class LibraryMessageTranslationTest(SimpleTestCase):
    """As mensagens de biblioteca user-facing resolvem para pt-PT."""

    # (msgid exato da biblioteca, tradução pt-PT esperada)
    CASES = [
        # SimpleJWT — sem catálogo pt na lib; sairia em inglês sem override.
        ('No active account found with the given credentials', LOGIN_NO_ACCOUNT),
        ('Token is invalid or expired', 'Sessão inválida ou expirada. Inicie sessão novamente.'),
        ('Token is blacklisted', 'Token revogado.'),
        # DRF — catálogo efetivo é pt-BR; reescrito em pt-PT.
        ('You do not have permission to perform this action.',
         'Não tem permissão para executar esta ação.'),
        ('Request was throttled.', 'Demasiados pedidos. Tente novamente mais tarde.'),
        ('"{input}" is not a valid choice.', '"{input}" não é uma opção válida.'),
        ('Must be a valid boolean.', 'Tem de ser um valor booleano válido.'),
        ('This field must be unique.', 'Este campo tem de ser único.'),
        ('No file was submitted.', 'Não foi enviado nenhum ficheiro.'),
    ]

    def test_library_messages_resolve_to_pt_pt(self):
        with translation.override('pt-pt'):
            for msgid, expected in self.CASES:
                with self.subTest(msgid=msgid):
                    self.assertEqual(translation.gettext(msgid), expected)

    def test_throttle_wait_plural_resolves_to_pt_pt(self):
        with translation.override('pt-pt'):
            singular = translation.ngettext(
                'Expected available in {wait} second.',
                'Expected available in {wait} seconds.',
                1,
            )
            plural = translation.ngettext(
                'Expected available in {wait} second.',
                'Expected available in {wait} seconds.',
                5,
            )
        self.assertEqual(singular, 'Disponível dentro de {wait} segundo.')
        self.assertEqual(plural, 'Disponível dentro de {wait} segundos.')

    def test_app_already_pt_message_is_preserved(self):
        # Controlo: uma mensagem que já era pt-PT correta não é afetada.
        with translation.override('pt-pt'):
            self.assertEqual(
                translation.gettext('This field is required.'),
                'Este campo é obrigatório.',
            )


class LoginErrorMessageI18nTest(APITestCase):
    """O bug reportado: login falhado devolve a mensagem em pt-PT, não em inglês."""

    def setUp(self):
        self.user = UserFactory.create(password=TEST_PASSWORD)
        self.url = reverse('auth_login')

    def test_wrong_password_detail_is_pt_pt(self):
        with translation.override('pt-pt'):
            response = self.client.post(
                self.url,
                {'username': self.user.username, 'password': 'PalavraErrada!'},
            )
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        detail = str(response.data.get('detail', ''))
        self.assertEqual(detail, LOGIN_NO_ACCOUNT)
        # Garantia explícita: nada do texto inglês original sobrou.
        self.assertNotIn('No active account', detail)

    def test_missing_fields_errors_are_pt_pt(self):
        with translation.override('pt-pt'):
            response = self.client.post(self.url, {})
        # Erros de campo da DRF também em pt-PT (não em inglês).
        blob = str(response.data)
        self.assertNotIn('This field is required', blob)
        self.assertIn('obrigatório', blob)


class CatalogCompiledInSyncTest(SimpleTestCase):
    """O .mo versionado está sincronizado com o .po (anti-drift)."""

    def test_mo_is_up_to_date_with_po(self):
        # Falha (CommandError) se `compilemessages_pure` produzir um .mo
        # diferente do versionado — i.e., alguém editou o .po sem recompilar.
        call_command('compilemessages_pure', '--check')
