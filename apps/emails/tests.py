"""Unit tests for the emails app — PhishingEmailService helpers."""
from django.test import SimpleTestCase

from apps.emails.service import PhishingEmailService, _name_slug, _convincing_base


class NameSlugTests(SimpleTestCase):

    def test_simple_two_word_name(self):
        self.assertEqual(_name_slug('John Doe'), 'john.doe')

    def test_special_characters_replaced(self):
        self.assertEqual(_name_slug('Mary-Anne O\'Brien'), 'mary.anne.o.brien')

    def test_empty_string_returns_user(self):
        self.assertEqual(_name_slug(''), 'user')

    def test_all_spaces_returns_user(self):
        self.assertEqual(_name_slug('   '), 'user')

    def test_numbers_preserved(self):
        self.assertEqual(_name_slug('User2Test'), 'user2test')

    def test_leading_trailing_special_chars_stripped(self):
        self.assertEqual(_name_slug('  John  '), 'john')

    def test_unicode_letters_lowercased(self):
        result = _name_slug('Anna')
        self.assertEqual(result, 'anna')


class ConvincingBaseTests(SimpleTestCase):

    def test_microsoft365_prefix(self):
        result = _convincing_base('https://myplatform.example.com', 'microsoft365')
        self.assertEqual(result, 'https://microsoft.security@myplatform.example.com')

    def test_google_prefix(self):
        result = _convincing_base('https://myplatform.example.com', 'google')
        self.assertEqual(result, 'https://google.security@myplatform.example.com')

    def test_ctu_prefix(self):
        result = _convincing_base('https://myplatform.example.com', 'ctu')
        self.assertEqual(result, 'https://login.cvut.cz@myplatform.example.com')

    def test_unknown_category_uses_fallback(self):
        result = _convincing_base('https://myplatform.example.com', 'unknown')
        self.assertEqual(result, 'https://it.security@myplatform.example.com')

    def test_preserves_scheme_https(self):
        result = _convincing_base('https://host.example.com', 'microsoft365')
        self.assertTrue(result.startswith('https://'))

    def test_preserves_host(self):
        result = _convincing_base('https://phish.myorg.com', 'ctu')
        self.assertIn('phish.myorg.com', result)


class RenderTests(SimpleTestCase):

    def test_single_placeholder_replaced(self):
        body = 'Hello, {{first_name}}!'
        result = PhishingEmailService._render(body, {'first_name': 'Alice'})
        self.assertEqual(result, 'Hello, Alice!')

    def test_multiple_placeholders_replaced(self):
        body = '{{greeting}}, {{name}}. Click {{url}}.'
        ctx = {'greeting': 'Hi', 'name': 'Bob', 'url': 'http://example.com'}
        result = PhishingEmailService._render(body, ctx)
        self.assertEqual(result, 'Hi, Bob. Click http://example.com.')

    def test_missing_placeholder_left_intact(self):
        body = 'Hello, {{first_name}}! Your code is {{code}}.'
        result = PhishingEmailService._render(body, {'first_name': 'Alice'})
        self.assertEqual(result, 'Hello, Alice! Your code is {{code}}.')

    def test_empty_context_returns_body_unchanged(self):
        body = 'No placeholders here.'
        self.assertEqual(PhishingEmailService._render(body, {}), body)

    def test_non_string_value_converted(self):
        body = 'Year: {{year}}'
        result = PhishingEmailService._render(body, {'year': 2025})
        self.assertEqual(result, 'Year: 2025')

    def test_placeholder_replaced_all_occurrences(self):
        body = '{{x}} and {{x}}'
        result = PhishingEmailService._render(body, {'x': 'yes'})
        self.assertEqual(result, 'yes and yes')
