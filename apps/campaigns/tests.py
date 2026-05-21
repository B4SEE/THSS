"""Unit tests for the campaigns app — models and CampaignService."""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.campaigns.models import (
    ABTest, Campaign, CampaignTarget, SenderProfile, Template,
)
from apps.campaigns.service import CampaignService
from apps.organizations.models import Department, User
from apps.targets.models import Target, TargetGroup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(email='admin@test.com'):
    return User.objects.create_user(email, 'Admin', 'pass')


def make_sender():
    return SenderProfile.objects.create(
        display_name='IT Security', email='security@example.com'
    )


def make_template(category='microsoft365'):
    return Template.objects.create(
        name='Test Template',
        subject='Test Subject',
        body='Hello, {{first_name}}!',
        category=category,
    )


def make_campaign(template, sender=None, status=Campaign.Status.DRAFT,
                  target_type=Campaign.TargetType.ALL, created_by=None):
    return Campaign.objects.create(
        name='Test Campaign',
        template=template,
        sender=sender,
        status=status,
        target_type=target_type,
        created_by=created_by,
    )


def make_target(email='t@example.com', full_name='Test User', opt_out=False, dept=None):
    return Target.objects.create(
        email=email, full_name=full_name, opt_out=opt_out, department=dept
    )


# ---------------------------------------------------------------------------
# SenderProfile model tests
# ---------------------------------------------------------------------------

class SenderProfileModelTests(TestCase):

    def test_str_format(self):
        s = SenderProfile(display_name='IT Security', email='security@org.com')
        self.assertEqual(str(s), 'IT Security <security@org.com>')

    def test_formatted_property(self):
        s = SenderProfile(display_name='IT Security', email='security@org.com')
        self.assertEqual(s.formatted, 'IT Security <security@org.com>')

    def test_reply_to_optional(self):
        s = SenderProfile.objects.create(
            display_name='IT', email='it@org.com', reply_to=''
        )
        self.assertEqual(s.reply_to, '')

    def test_is_active_default_true(self):
        s = SenderProfile.objects.create(display_name='IT', email='it@org.com')
        self.assertTrue(s.is_active)


# ---------------------------------------------------------------------------
# Template model tests
# ---------------------------------------------------------------------------

class TemplateModelTests(TestCase):

    def test_str_format(self):
        t = Template(name='MS Login', difficulty_level='medium')
        self.assertEqual(str(t), '[medium] MS Login')

    def test_difficulty_default_medium(self):
        t = Template.objects.create(name='T', subject='S', body='B')
        self.assertEqual(t.difficulty_level, Template.Difficulty.MEDIUM)

    def test_educational_content_optional(self):
        t = Template.objects.create(name='T', subject='S', body='B')
        self.assertEqual(t.educational_content, '')

    def test_category_optional(self):
        t = Template.objects.create(name='T', subject='S', body='B')
        self.assertEqual(t.category, '')


# ---------------------------------------------------------------------------
# Campaign model tests
# ---------------------------------------------------------------------------

class CampaignModelTests(TestCase):

    def setUp(self):
        self.template = make_template()

    def test_str_format(self):
        c = Campaign(name='Q1 Phish', status='draft')
        self.assertEqual(str(c), 'Q1 Phish (draft)')

    def test_default_status_is_draft(self):
        c = make_campaign(self.template)
        self.assertEqual(c.status, Campaign.Status.DRAFT)

    def test_default_target_type_is_all(self):
        c = make_campaign(self.template)
        self.assertEqual(c.target_type, Campaign.TargetType.ALL)

    def test_approved_by_nullable(self):
        c = make_campaign(self.template)
        self.assertIsNone(c.approved_by)

    def test_created_at_auto_set(self):
        c = make_campaign(self.template)
        self.assertIsNotNone(c.created_at)


# ---------------------------------------------------------------------------
# CampaignTarget model tests
# ---------------------------------------------------------------------------

class CampaignTargetModelTests(TestCase):

    def setUp(self):
        self.template = make_template()
        self.campaign = make_campaign(self.template)
        self.target = make_target()

    def test_str_format(self):
        ct = CampaignTarget(campaign=self.campaign, target=self.target)
        self.assertEqual(str(ct), 'Test Campaign → t@example.com')

    def test_sent_at_nullable(self):
        ct = CampaignTarget.objects.create(
            campaign=self.campaign, target=self.target
        )
        self.assertIsNone(ct.sent_at)

    def test_unique_together_campaign_target(self):
        from django.db import IntegrityError
        CampaignTarget.objects.create(campaign=self.campaign, target=self.target)
        with self.assertRaises(IntegrityError):
            CampaignTarget.objects.create(campaign=self.campaign, target=self.target)


# ---------------------------------------------------------------------------
# ABTest model tests
# ---------------------------------------------------------------------------

class ABTestModelTests(TestCase):

    def setUp(self):
        self.template = make_template()
        self.campaign = make_campaign(self.template)

    def test_str_format(self):
        ab = ABTest(
            campaign=self.campaign,
            variant_name='Variant B',
            template=self.template,
            allocation_percentage=30,
        )
        self.assertEqual(str(ab), 'Test Campaign – Variant B (30%)')


# ---------------------------------------------------------------------------
# CampaignService._build_variant_map tests
# ---------------------------------------------------------------------------

class BuildVariantMapTests(TestCase):

    def setUp(self):
        self.template = make_template()
        self.campaign = make_campaign(self.template)
        self.targets = [
            make_target(email=f't{i}@example.com', full_name=f'User {i}')
            for i in range(10)
        ]

    def test_no_ab_tests_returns_empty_dict(self):
        result = CampaignService._build_variant_map(self.campaign, self.targets)
        self.assertEqual(result, {})

    def test_with_ab_test_all_targets_assigned(self):
        ABTest.objects.create(
            campaign=self.campaign,
            variant_name='B',
            template=self.template,
            allocation_percentage=50,
        )
        result = CampaignService._build_variant_map(self.campaign, self.targets)
        self.assertEqual(len(result), len(self.targets))
        for pk in result:
            self.assertIn(result[pk], ('A', 'B'))

    def test_variant_allocation_approximate(self):
        ABTest.objects.create(
            campaign=self.campaign,
            variant_name='B',
            template=self.template,
            allocation_percentage=50,
        )
        targets = [
            make_target(email=f'x{i}@example.com', full_name=f'User X{i}')
            for i in range(100)
        ]
        result = CampaignService._build_variant_map(self.campaign, targets)
        b_count = sum(1 for v in result.values() if v == 'B')
        # Allow ±15% tolerance around the expected 50 for 100 targets
        self.assertGreater(b_count, 35)
        self.assertLess(b_count, 65)

    def test_multiple_ab_variants(self):
        ABTest.objects.create(
            campaign=self.campaign,
            variant_name='B',
            template=self.template,
            allocation_percentage=30,
        )
        ABTest.objects.create(
            campaign=self.campaign,
            variant_name='C',
            template=self.template,
            allocation_percentage=30,
        )
        result = CampaignService._build_variant_map(self.campaign, self.targets)
        for v in result.values():
            self.assertIn(v, ('A', 'B', 'C'))


# ---------------------------------------------------------------------------
# CampaignService._resolve_recipients tests
# ---------------------------------------------------------------------------

class ResolveRecipientsTests(TestCase):

    def setUp(self):
        self.template = make_template()
        self.dept = Department.objects.create(name='Engineering')
        self.t1 = make_target(email='a@example.com', full_name='Alice', dept=self.dept)
        self.t2 = make_target(email='b@example.com', full_name='Bob')
        self.t_optout = make_target(email='opt@example.com', full_name='Optout', opt_out=True)

    def test_all_target_type_returns_opted_in_targets(self):
        c = make_campaign(self.template, target_type=Campaign.TargetType.ALL)
        result = CampaignService._resolve_recipients(c)
        emails = {t.email for t in result}
        self.assertIn('a@example.com', emails)
        self.assertIn('b@example.com', emails)
        self.assertNotIn('opt@example.com', emails)

    def test_department_target_type(self):
        c = make_campaign(self.template, target_type=Campaign.TargetType.DEPARTMENT)
        c.target_departments.add(self.dept)
        result = CampaignService._resolve_recipients(c)
        emails = {t.email for t in result}
        self.assertIn('a@example.com', emails)
        self.assertNotIn('b@example.com', emails)

    def test_department_target_type_raises_when_no_department(self):
        c = make_campaign(self.template, target_type=Campaign.TargetType.DEPARTMENT)
        with self.assertRaises(ValueError):
            CampaignService._resolve_recipients(c)

    def test_group_target_type(self):
        group = TargetGroup.objects.create(name='Group1')
        group.members.add(self.t2)
        c = make_campaign(self.template, target_type=Campaign.TargetType.GROUP)
        c.target_groups.add(group)
        result = CampaignService._resolve_recipients(c)
        emails = {t.email for t in result}
        self.assertIn('b@example.com', emails)
        self.assertNotIn('a@example.com', emails)

    def test_group_target_type_raises_when_no_group(self):
        c = make_campaign(self.template, target_type=Campaign.TargetType.GROUP)
        with self.assertRaises(ValueError):
            CampaignService._resolve_recipients(c)

    def test_individual_target_type(self):
        c = make_campaign(self.template, target_type=Campaign.TargetType.INDIVIDUAL)
        c.individual_targets.add(self.t1)
        result = CampaignService._resolve_recipients(c)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].email, 'a@example.com')

    def test_excluded_targets_removed(self):
        c = make_campaign(self.template, target_type=Campaign.TargetType.ALL)
        c.excluded_targets.add(self.t1)
        result = CampaignService._resolve_recipients(c)
        emails = {t.email for t in result}
        self.assertNotIn('a@example.com', emails)

    def test_opted_out_never_included(self):
        c = make_campaign(self.template, target_type=Campaign.TargetType.INDIVIDUAL)
        c.individual_targets.add(self.t_optout)
        result = CampaignService._resolve_recipients(c)
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# CampaignService.reset tests
# ---------------------------------------------------------------------------

class ResetCampaignTests(TestCase):

    def setUp(self):
        self.template = make_template()
        self.user = make_user()
        self.campaign = make_campaign(
            self.template,
            status=Campaign.Status.COMPLETED,
            created_by=self.user,
        )
        self.campaign.approved_by = self.user
        self.campaign.save()
        self.target = make_target()
        from django.utils import timezone
        CampaignTarget.objects.create(
            campaign=self.campaign,
            target=self.target,
            sent_at=timezone.now(),
        )

    def test_reset_sets_status_to_draft(self):
        CampaignService.reset(self.campaign)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.DRAFT)

    def test_reset_clears_approved_by(self):
        CampaignService.reset(self.campaign)
        self.campaign.refresh_from_db()
        self.assertIsNone(self.campaign.approved_by)

    def test_reset_clears_sent_at_on_campaign_targets(self):
        CampaignService.reset(self.campaign)
        unsent = CampaignTarget.objects.filter(
            campaign=self.campaign, sent_at__isnull=True
        ).count()
        self.assertEqual(unsent, 1)


# ---------------------------------------------------------------------------
# CampaignService.send tests (with mocked email service)
# ---------------------------------------------------------------------------

class SendCampaignTests(TestCase):

    def setUp(self):
        self.template = make_template()
        self.campaign = make_campaign(self.template, target_type=Campaign.TargetType.ALL)
        self.t1 = make_target(email='t1@example.com', full_name='T1')
        self.t2 = make_target(email='t2@example.com', full_name='T2')
        self.svc = CampaignService()

    @patch('apps.emails.service.PhishingEmailService.send_for_target', return_value=True)
    def test_send_returns_correct_counts(self, mock_send):
        sent, failed, skipped, remaining = self.svc.send(self.campaign, send_delay=0)
        self.assertEqual(sent, 2)
        self.assertEqual(failed, 0)
        self.assertEqual(skipped, 0)
        self.assertEqual(remaining, 0)

    @patch('apps.emails.service.PhishingEmailService.send_for_target', return_value=False)
    def test_send_counts_failures(self, mock_send):
        sent, failed, skipped, remaining = self.svc.send(self.campaign, send_delay=0)
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 2)

    @patch('apps.emails.service.PhishingEmailService.send_for_target', return_value=True)
    def test_send_marks_campaign_completed(self, mock_send):
        self.svc.send(self.campaign, send_delay=0)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.COMPLETED)

    @patch('apps.emails.service.PhishingEmailService.send_for_target', return_value=True)
    def test_send_skips_already_sent_targets(self, mock_send):
        from django.utils import timezone
        ct = CampaignTarget.objects.create(
            campaign=self.campaign, target=self.t1, sent_at=timezone.now()
        )
        sent, failed, skipped, remaining = self.svc.send(self.campaign, send_delay=0)
        self.assertEqual(skipped, 1)
        self.assertEqual(sent, 1)

    @patch('apps.emails.service.PhishingEmailService.send_for_target', return_value=True)
    def test_send_respects_batch_limit(self, mock_send):
        sent, failed, skipped, remaining = self.svc.send(
            self.campaign, batch_limit=1, send_delay=0
        )
        self.assertEqual(sent, 1)

    def test_send_empty_recipients_returns_zeros(self):
        campaign = make_campaign(self.template, target_type=Campaign.TargetType.INDIVIDUAL)
        sent, failed, skipped, remaining = self.svc.send(campaign, send_delay=0)
        self.assertEqual((sent, failed, skipped, remaining), (0, 0, 0, 0))
