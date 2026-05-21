"""Unit tests for the audit app — AuditLog model and admin_mixins helpers."""
from django.test import RequestFactory, TestCase

from apps.admin_mixins import _get_ip, audit
from apps.audit.models import AuditLog
from apps.organizations.models import User


def make_user(email='admin@test.com'):
    return User.objects.create_user(email, 'Admin', 'pass123')


# ---------------------------------------------------------------------------
# AuditLog model tests
# ---------------------------------------------------------------------------

class AuditLogModelTests(TestCase):

    def test_str_format_with_actor(self):
        log = AuditLog(actor_email='user@example.com', action='login')
        log.timestamp = __import__('django').utils.timezone.now()
        self.assertIn('user@example.com', str(log))
        self.assertIn('login', str(log))

    def test_str_format_unknown_actor(self):
        log = AuditLog(actor_email='', action='login')
        log.timestamp = __import__('django').utils.timezone.now()
        self.assertIn('(unknown)', str(log))

    def test_create_log_entry(self):
        AuditLog.objects.create(
            actor_email='admin@test.com',
            action='campaign_sent',
            entity_type='Campaign',
            entity_id=1,
        )
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_ordering_newest_first(self):
        AuditLog.objects.create(actor_email='a@test.com', action='first')
        AuditLog.objects.create(actor_email='b@test.com', action='second')
        logs = list(AuditLog.objects.values_list('action', flat=True))
        self.assertEqual(logs[0], 'second')

    def test_user_nullable(self):
        log = AuditLog.objects.create(
            actor_email='gone@test.com',
            action='login',
        )
        self.assertIsNone(log.user)

    def test_changes_json_field(self):
        log = AuditLog.objects.create(
            actor_email='a@test.com',
            action='update',
            changes={'old_status': 'draft', 'new_status': 'running'},
        )
        log.refresh_from_db()
        self.assertEqual(log.changes['new_status'], 'running')

    def test_timestamp_auto_set(self):
        log = AuditLog.objects.create(actor_email='a@test.com', action='x')
        self.assertIsNotNone(log.timestamp)


# ---------------------------------------------------------------------------
# admin_mixins._get_ip tests
# ---------------------------------------------------------------------------

class AdminMixinGetIPTests(TestCase):

    def _request(self, remote='1.2.3.4', xff=None):
        factory = RequestFactory()
        req = factory.get('/')
        req.META['REMOTE_ADDR'] = remote
        if xff:
            req.META['HTTP_X_FORWARDED_FOR'] = xff
        return req

    def test_uses_remote_addr_without_xff(self):
        self.assertEqual(_get_ip(self._request(remote='9.9.9.9')), '9.9.9.9')

    def test_uses_first_xff_ip(self):
        req = self._request(xff='10.0.0.1, 192.168.1.1')
        self.assertEqual(_get_ip(req), '10.0.0.1')

    def test_strips_whitespace_from_xff(self):
        req = self._request(xff='  10.0.0.5  , 192.168.1.1')
        self.assertEqual(_get_ip(req), '10.0.0.5')


# ---------------------------------------------------------------------------
# admin_mixins.audit tests
# ---------------------------------------------------------------------------

class AuditHelperTests(TestCase):

    def setUp(self):
        self.user = make_user()
        self.factory = RequestFactory()

    def _request(self):
        req = self.factory.get('/')
        req.META['REMOTE_ADDR'] = '127.0.0.1'
        req.user = self.user
        return req

    def test_audit_creates_log_entry(self):
        audit(self._request(), action='test_action')
        self.assertEqual(AuditLog.objects.filter(action='test_action').count(), 1)

    def test_audit_captures_actor_email(self):
        audit(self._request(), action='x')
        log = AuditLog.objects.first()
        self.assertEqual(log.actor_email, self.user.email)

    def test_audit_captures_actor_name(self):
        audit(self._request(), action='x')
        log = AuditLog.objects.first()
        self.assertEqual(log.actor_name, self.user.full_name)

    def test_audit_with_obj_sets_entity_type(self):
        from apps.campaigns.models import Template
        tmpl = Template.objects.create(name='T', subject='S', body='B')
        audit(self._request(), action='view', obj=tmpl)
        log = AuditLog.objects.first()
        self.assertEqual(log.entity_type, 'Template')
        self.assertEqual(log.entity_id, tmpl.pk)

    def test_audit_explicit_entity_type_overrides(self):
        audit(self._request(), action='y', entity_type='Campaign', entity_id=99)
        log = AuditLog.objects.first()
        self.assertEqual(log.entity_type, 'Campaign')
        self.assertEqual(log.entity_id, 99)

    def test_audit_changes_stored(self):
        audit(self._request(), action='z', changes={'key': 'value'})
        log = AuditLog.objects.first()
        self.assertEqual(log.changes['key'], 'value')

    def test_audit_unauthenticated_user(self):
        from django.contrib.auth.models import AnonymousUser
        req = self.factory.get('/')
        req.META['REMOTE_ADDR'] = '127.0.0.1'
        req.user = AnonymousUser()
        audit(req, action='anon_action')
        log = AuditLog.objects.first()
        self.assertIsNone(log.user)
        self.assertEqual(log.actor_email, '')


# ---------------------------------------------------------------------------
# Auth signal integration tests
# ---------------------------------------------------------------------------

class AuthSignalAuditTests(TestCase):

    def setUp(self):
        self.user = make_user()
        self.factory = RequestFactory()

    def _request(self):
        req = self.factory.get('/')
        req.META['REMOTE_ADDR'] = '10.0.0.1'
        return req

    def test_login_signal_creates_audit_log(self):
        from apps.audit.apps import _on_login
        _on_login(sender=None, request=self._request(), user=self.user)
        self.assertTrue(
            AuditLog.objects.filter(action='login', actor_email=self.user.email).exists()
        )

    def test_logout_signal_creates_audit_log(self):
        from apps.audit.apps import _on_logout
        _on_logout(sender=None, request=self._request(), user=self.user)
        self.assertTrue(
            AuditLog.objects.filter(action='logout', actor_email=self.user.email).exists()
        )

    def test_logout_signal_skipped_for_none_user(self):
        from apps.audit.apps import _on_logout
        _on_logout(sender=None, request=self._request(), user=None)
        self.assertFalse(AuditLog.objects.filter(action='logout').exists())

    def test_login_failed_creates_audit_log(self):
        from apps.audit.apps import _on_login_failed
        _on_login_failed(
            sender=None,
            credentials={'username': 'hacker@evil.com'},
            request=self._request(),
        )
        self.assertTrue(
            AuditLog.objects.filter(action='login_failed').exists()
        )

    def test_login_failed_records_attempted_email(self):
        from apps.audit.apps import _on_login_failed
        _on_login_failed(
            sender=None,
            credentials={'username': 'hacker@evil.com'},
            request=self._request(),
        )
        log = AuditLog.objects.get(action='login_failed')
        self.assertEqual(log.changes['attempted_email'], 'hacker@evil.com')

    def test_get_ip_returns_none_for_missing_request(self):
        from apps.audit.apps import _get_ip as audit_get_ip
        self.assertIsNone(audit_get_ip(None))
