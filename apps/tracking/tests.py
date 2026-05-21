"""Unit tests for the tracking app — tokens, helpers, models, and views."""
from unittest.mock import patch

from django.core import signing
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.campaigns.models import Campaign, CampaignTarget, Template, SenderProfile
from apps.organizations.models import User
from apps.targets.models import Target
from apps.tracking.models import Interaction
from apps.tracking.tokens import make_token, resolve_token
from apps.tracking.views import (
    _capture_js_tracking,
    _get_ip,
    _is_finished,
    _is_scanner,
    _parse_ua,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_template(category='microsoft365'):
    return Template.objects.create(
        name='Test Template',
        subject='Test Subject',
        body='Hello, {{first_name}}!',
        category=category,
    )


def make_campaign(template, status=Campaign.Status.RUNNING):
    return Campaign.objects.create(
        name='TestCampaign',
        template=template,
        status=status,
        target_type=Campaign.TargetType.ALL,
    )


def make_target(email='target@example.com', full_name='Target User'):
    return Target.objects.create(email=email, full_name=full_name)


def make_ct(campaign, target):
    return CampaignTarget.objects.create(campaign=campaign, target=target)


# ---------------------------------------------------------------------------
# Token tests
# ---------------------------------------------------------------------------

class TokenTests(TestCase):

    def test_round_trip(self):
        token = make_token(42)
        self.assertEqual(resolve_token(token), 42)

    def test_different_ids_produce_different_tokens(self):
        self.assertNotEqual(make_token(1), make_token(2))

    def test_tampered_token_raises_bad_signature(self):
        token = make_token(99)
        tampered = token[:-3] + 'xxx'
        with self.assertRaises(signing.BadSignature):
            resolve_token(tampered)

    def test_token_is_string(self):
        self.assertIsInstance(make_token(1), str)

    def test_resolve_wrong_salt_raises(self):
        evil = signing.dumps(7, salt='evil-salt')
        with self.assertRaises(signing.BadSignature):
            resolve_token(evil)


# ---------------------------------------------------------------------------
# _parse_ua tests
# ---------------------------------------------------------------------------

class ParseUATests(TestCase):

    def test_windows_chrome_desktop(self):
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
        result = _parse_ua(ua)
        self.assertEqual(result['os'], 'Windows 10/11')
        self.assertEqual(result['browser'], 'Chrome')
        self.assertEqual(result['device'], 'Desktop')

    def test_iphone_safari_mobile(self):
        ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit Mobile Safari/604.1'
        result = _parse_ua(ua)
        self.assertEqual(result['os'], 'iOS')
        self.assertEqual(result['device'], 'Mobile')

    def test_edge_detected_before_chrome(self):
        ua = 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/120.0 Edg/120.0'
        result = _parse_ua(ua)
        self.assertEqual(result['browser'], 'Edge')

    def test_firefox_linux(self):
        ua = 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0'
        result = _parse_ua(ua)
        self.assertEqual(result['browser'], 'Firefox')
        self.assertEqual(result['os'], 'Linux')

    def test_empty_ua_returns_unknowns(self):
        result = _parse_ua('')
        self.assertEqual(result['browser'], 'Other')
        self.assertEqual(result['os'], 'Unknown')
        self.assertEqual(result['device'], 'Desktop')

    def test_android_mobile(self):
        ua = 'Mozilla/5.0 (Linux; Android 13; Pixel) Chrome/120 Mobile Safari/537'
        result = _parse_ua(ua)
        self.assertEqual(result['os'], 'Android')
        self.assertEqual(result['device'], 'Mobile')

    def test_macos_safari(self):
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605 Safari/605.1'
        result = _parse_ua(ua)
        self.assertEqual(result['os'], 'macOS')
        self.assertEqual(result['browser'], 'Safari')

    def test_older_windows(self):
        ua = 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit Chrome/50.0'
        result = _parse_ua(ua)
        self.assertEqual(result['os'], 'Windows (older)')

    def test_opera_detected(self):
        ua = 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/120 OPR/105.0'
        result = _parse_ua(ua)
        self.assertEqual(result['browser'], 'Opera')


# ---------------------------------------------------------------------------
# _is_scanner tests
# ---------------------------------------------------------------------------

class IsScannerTests(TestCase):

    def _request(self, ua):
        factory = RequestFactory()
        req = factory.get('/')
        req.META['HTTP_USER_AGENT'] = ua
        return req

    def test_msnbot_detected(self):
        self.assertTrue(_is_scanner(self._request('msnbot/2.0')))

    def test_bingbot_detected(self):
        self.assertTrue(_is_scanner(self._request('Mozilla/5.0 (compatible; bingbot/2.0)')))

    def test_ms_applinks_detected(self):
        self.assertTrue(_is_scanner(self._request('ms-applinks/1.0')))

    def test_normal_browser_not_scanner(self):
        self.assertFalse(_is_scanner(self._request(
            'Mozilla/5.0 (Windows NT 10.0) Chrome/120.0'
        )))

    def test_empty_ua_not_scanner(self):
        self.assertFalse(_is_scanner(self._request('')))


# ---------------------------------------------------------------------------
# _get_ip tests
# ---------------------------------------------------------------------------

class GetIPTests(TestCase):

    def _request(self, remote='1.2.3.4', xff=None):
        factory = RequestFactory()
        req = factory.get('/')
        req.META['REMOTE_ADDR'] = remote
        if xff:
            req.META['HTTP_X_FORWARDED_FOR'] = xff
        return req

    def test_uses_remote_addr_when_no_xff(self):
        self.assertEqual(_get_ip(self._request(remote='5.6.7.8')), '5.6.7.8')

    def test_uses_first_xff_entry(self):
        self.assertEqual(
            _get_ip(self._request(xff='10.0.0.1, 192.168.1.1')),
            '10.0.0.1',
        )

    def test_xff_whitespace_stripped(self):
        self.assertEqual(
            _get_ip(self._request(xff='  10.0.0.2  , 192.168.1.1')),
            '10.0.0.2',
        )


# ---------------------------------------------------------------------------
# _capture_js_tracking tests
# ---------------------------------------------------------------------------

class CaptureJsTrackingTests(TestCase):

    def test_maps_known_keys(self):
        post = {'_t_time': '30', '_t_scroll': '1', '_t_focus': '3', '_t_screen': '1920x1080'}
        result = _capture_js_tracking(post)
        self.assertEqual(result['time_on_page_s'], '30')
        self.assertEqual(result['scrolled'], '1')
        self.assertEqual(result['field_focus_count'], '3')
        self.assertEqual(result['screen_resolution'], '1920x1080')

    def test_missing_keys_not_included(self):
        result = _capture_js_tracking({'_t_time': '5'})
        self.assertNotIn('scrolled', result)

    def test_empty_post_returns_empty_dict(self):
        self.assertEqual(_capture_js_tracking({}), {})

    def test_unknown_keys_ignored(self):
        result = _capture_js_tracking({'unknown': 'value'})
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# _is_finished tests
# ---------------------------------------------------------------------------

class IsFinishedTests(TestCase):

    def setUp(self):
        template = make_template()
        self.campaign = make_campaign(template)
        self.target = make_target()
        self.ct = make_ct(self.campaign, self.target)

    def test_finished_status_returns_true(self):
        self.campaign.status = Campaign.Status.FINISHED
        self.campaign.save()
        self.ct.refresh_from_db()
        self.assertTrue(_is_finished(self.ct))

    def test_running_status_returns_false(self):
        self.assertFalse(_is_finished(self.ct))

    def test_past_finish_date_returns_true(self):
        from datetime import timedelta
        self.campaign.finish_date = timezone.now() - timedelta(hours=1)
        self.campaign.save()
        self.ct.refresh_from_db()
        self.assertTrue(_is_finished(self.ct))

    def test_future_finish_date_returns_false(self):
        from datetime import timedelta
        self.campaign.finish_date = timezone.now() + timedelta(days=1)
        self.campaign.save()
        self.ct.refresh_from_db()
        self.assertFalse(_is_finished(self.ct))


# ---------------------------------------------------------------------------
# Interaction model tests
# ---------------------------------------------------------------------------

class InteractionModelTests(TestCase):

    def setUp(self):
        template = make_template()
        campaign = make_campaign(template)
        target = make_target()
        self.ct = make_ct(campaign, target)

    def test_str_format(self):
        i = Interaction.objects.create(
            campaign_target=self.ct,
            event_type=Interaction.EventType.CLICKED,
        )
        self.assertIn('clicked', str(i))

    def test_event_timestamp_defaults_to_now(self):
        before = timezone.now()
        i = Interaction.objects.create(
            campaign_target=self.ct,
            event_type=Interaction.EventType.OPENED,
        )
        self.assertGreaterEqual(i.event_timestamp, before)

    def test_submitted_data_nullable(self):
        i = Interaction.objects.create(
            campaign_target=self.ct,
            event_type=Interaction.EventType.OPENED,
        )
        self.assertIsNone(i.submitted_data)


# ---------------------------------------------------------------------------
# View integration tests
# ---------------------------------------------------------------------------

class TrackingViewSetup(TestCase):
    """Base class that builds a full CampaignTarget + valid token."""

    def setUp(self):
        self.template = make_template()
        self.campaign = make_campaign(self.template)
        self.target = make_target()
        self.ct = make_ct(self.campaign, self.target)
        self.token = make_token(self.ct.pk)
        self.name = 'target.user'

    def url(self, view_name, **kwargs):
        return reverse(
            f'tracking:{view_name}',
            kwargs={'name': self.name, 'token': self.token, **kwargs},
        )


class PixelViewTests(TrackingViewSetup):

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_pixel_returns_gif(self, _):
        resp = self.client.get(self.url('pixel'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/gif')

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_pixel_logs_opened_event(self, _):
        self.client.get(self.url('pixel'))
        self.assertTrue(
            Interaction.objects.filter(
                campaign_target=self.ct,
                event_type=Interaction.EventType.OPENED,
            ).exists()
        )

    def test_pixel_with_invalid_token_returns_404(self):
        url = reverse('tracking:pixel', kwargs={'name': 'x', 'token': 'bad-token'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_pixel_does_not_log_when_campaign_finished(self, _):
        self.campaign.status = Campaign.Status.FINISHED
        self.campaign.save()
        self.client.get(self.url('pixel'))
        self.assertFalse(
            Interaction.objects.filter(campaign_target=self.ct).exists()
        )


class LandingViewTests(TrackingViewSetup):

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_landing_returns_200(self, _):
        resp = self.client.get(self.url('landing'))
        self.assertEqual(resp.status_code, 200)

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_landing_logs_clicked_event(self, _):
        self.client.get(self.url('landing'))
        self.assertTrue(
            Interaction.objects.filter(
                campaign_target=self.ct,
                event_type=Interaction.EventType.CLICKED,
            ).exists()
        )

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_landing_does_not_double_log_click(self, _):
        self.client.get(self.url('landing'))
        self.client.get(self.url('landing'))
        count = Interaction.objects.filter(
            campaign_target=self.ct,
            event_type=Interaction.EventType.CLICKED,
        ).count()
        self.assertEqual(count, 1)

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_landing_scanner_ua_not_logged(self, _):
        self.client.get(
            self.url('landing'),
            HTTP_USER_AGENT='msnbot/2.0',
        )
        self.assertFalse(
            Interaction.objects.filter(
                campaign_target=self.ct,
                event_type=Interaction.EventType.CLICKED,
            ).exists()
        )

    def test_landing_finished_campaign_shows_finished_page(self):
        self.campaign.status = Campaign.Status.FINISHED
        self.campaign.save()
        resp = self.client.get(self.url('landing'))
        self.assertTemplateUsed(resp, 'tracking/campaign_finished.html')


class SubmitViewTests(TrackingViewSetup):

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_submit_logs_submitted_event(self, _):
        resp = self.client.post(
            self.url('submit'),
            data={'email': 'target@example.com', 'password': 'secret'},
        )
        self.assertTrue(
            Interaction.objects.filter(
                campaign_target=self.ct,
                event_type=Interaction.EventType.SUBMITTED,
            ).exists()
        )

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_submit_redirects_to_feedback_for_non_ctu(self, _):
        resp = self.client.post(self.url('submit'), data={'email': 'x@x.com'})
        self.assertRedirects(
            resp,
            self.url('feedback'),
            fetch_redirect_response=False,
        )

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_submit_redirects_to_mfa_for_ctu(self, _):
        ctu_template = make_template(category='ctu')
        campaign = make_campaign(ctu_template)
        target = make_target(email='ctu@example.com', full_name='CTU User')
        ct = make_ct(campaign, target)
        token = make_token(ct.pk)
        resp = self.client.post(
            reverse('tracking:submit', kwargs={'name': 'ctu.user', 'token': token}),
            data={'email': 'ctu@example.com'},
        )
        self.assertRedirects(
            resp,
            reverse('tracking:mfa', kwargs={'name': 'ctu.user', 'token': token}),
            fetch_redirect_response=False,
        )

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_submit_idempotent_after_submission(self, _):
        Interaction.objects.create(
            campaign_target=self.ct,
            event_type=Interaction.EventType.SUBMITTED,
        )
        resp = self.client.post(self.url('submit'), data={})
        self.assertRedirects(
            resp,
            self.url('feedback'),
            fetch_redirect_response=False,
        )


class ReportViewTests(TrackingViewSetup):

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_report_logs_reported_event(self, _):
        resp = self.client.get(self.url('report'))
        self.assertTrue(
            Interaction.objects.filter(
                campaign_target=self.ct,
                event_type=Interaction.EventType.REPORTED,
            ).exists()
        )

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_report_returns_200(self, _):
        resp = self.client.get(self.url('report'))
        self.assertEqual(resp.status_code, 200)

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_report_not_logged_twice(self, _):
        self.client.get(self.url('report'))
        self.client.get(self.url('report'))
        count = Interaction.objects.filter(
            campaign_target=self.ct,
            event_type=Interaction.EventType.REPORTED,
        ).count()
        self.assertEqual(count, 1)


class FeedbackViewTests(TrackingViewSetup):

    def test_feedback_returns_200(self):
        resp = self.client.get(self.url('feedback'))
        self.assertEqual(resp.status_code, 200)

    def test_ctu_feedback_uses_ctu_template(self):
        ctu_template = make_template(category='ctu')
        campaign = make_campaign(ctu_template)
        target = make_target(email='ctu2@example.com', full_name='CTU2')
        ct = make_ct(campaign, target)
        token = make_token(ct.pk)
        resp = self.client.get(
            reverse('tracking:feedback', kwargs={'name': 'ctu2', 'token': token})
        )
        self.assertTemplateUsed(resp, 'tracking/educational_feedback_ctu.html')

    def test_non_ctu_feedback_uses_generic_template(self):
        resp = self.client.get(self.url('feedback'))
        self.assertTemplateUsed(resp, 'tracking/educational_feedback.html')


class MfaViewTests(TrackingViewSetup):

    def setUp(self):
        super().setUp()
        # Override with CTU campaign
        ctu_template = make_template(category='ctu')
        self.ctu_campaign = make_campaign(ctu_template)
        target = make_target(email='mfauser@example.com', full_name='MFA User')
        self.mfa_ct = make_ct(self.ctu_campaign, target)
        self.mfa_token = make_token(self.mfa_ct.pk)
        self.mfa_name = 'mfa.user'

    def mfa_url(self, view):
        return reverse(
            f'tracking:{view}',
            kwargs={'name': self.mfa_name, 'token': self.mfa_token},
        )

    def test_mfa_get_returns_200(self):
        resp = self.client.get(self.mfa_url('mfa'))
        self.assertEqual(resp.status_code, 200)

    def test_mfa_approval_number_in_context(self):
        resp = self.client.get(self.mfa_url('mfa'))
        self.assertIn('approval_number', resp.context)

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_mfa_post_logs_mfa_submitted(self, _):
        self.client.post(self.mfa_url('mfa'), data={})
        self.assertTrue(
            Interaction.objects.filter(
                campaign_target=self.mfa_ct,
                event_type=Interaction.EventType.MFA_SUBMITTED,
            ).exists()
        )

    @patch('apps.tracking.signals.broadcast_interaction')
    def test_mfa_post_redirects_to_feedback(self, _):
        resp = self.client.post(self.mfa_url('mfa'), data={})
        self.assertRedirects(
            resp,
            self.mfa_url('feedback'),
            fetch_redirect_response=False,
        )
