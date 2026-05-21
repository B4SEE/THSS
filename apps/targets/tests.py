"""Unit tests for the targets app — Target and TargetGroup models."""
from django.test import TestCase

from apps.organizations.models import Department
from apps.targets.models import Target, TargetGroup


def make_target(email='t@example.com', full_name='Test User', opt_out=False):
    return Target.objects.create(email=email, full_name=full_name, opt_out=opt_out)


class TargetModelTests(TestCase):

    def test_str_format(self):
        t = Target(email='alice@example.com', full_name='Alice Smith')
        self.assertEqual(str(t), 'Alice Smith <alice@example.com>')

    def test_opt_out_default_false(self):
        t = make_target()
        self.assertFalse(t.opt_out)

    def test_email_is_unique(self):
        from django.db import IntegrityError
        make_target(email='dup@test.com')
        with self.assertRaises(IntegrityError):
            make_target(email='dup@test.com', full_name='Another')

    def test_department_optional(self):
        t = make_target()
        self.assertIsNone(t.department)

    def test_department_set_null_on_department_delete(self):
        dept = Department.objects.create(name='Engineering')
        t = Target.objects.create(email='e@example.com', full_name='Eng User', department=dept)
        dept.delete()
        t.refresh_from_db()
        self.assertIsNone(t.department)

    def test_created_at_auto_set(self):
        t = make_target()
        self.assertIsNotNone(t.created_at)

    def test_ordering_by_full_name(self):
        Target.objects.create(email='z@example.com', full_name='Zoe')
        Target.objects.create(email='a@example.com', full_name='Alice')
        names = list(Target.objects.values_list('full_name', flat=True))
        self.assertEqual(names, sorted(names))


class TargetGroupModelTests(TestCase):

    def test_str_returns_name(self):
        g = TargetGroup(name='Finance')
        self.assertEqual(str(g), 'Finance')

    def test_member_count_empty(self):
        g = TargetGroup.objects.create(name='Empty Group')
        self.assertEqual(g.member_count(), 0)

    def test_member_count_with_members(self):
        g = TargetGroup.objects.create(name='Group A')
        t1 = make_target(email='t1@example.com', full_name='T1')
        t2 = make_target(email='t2@example.com', full_name='T2')
        g.members.set([t1, t2])
        self.assertEqual(g.member_count(), 2)

    def test_name_is_unique(self):
        from django.db import IntegrityError
        TargetGroup.objects.create(name='Unique')
        with self.assertRaises(IntegrityError):
            TargetGroup.objects.create(name='Unique')

    def test_description_optional(self):
        g = TargetGroup.objects.create(name='G1', description='Desc')
        self.assertEqual(g.description, 'Desc')

    def test_ordering_by_name(self):
        TargetGroup.objects.create(name='Zebra')
        TargetGroup.objects.create(name='Alpha')
        names = list(TargetGroup.objects.values_list('name', flat=True))
        self.assertEqual(names, sorted(names))

    def test_target_can_belong_to_multiple_groups(self):
        t = make_target()
        g1 = TargetGroup.objects.create(name='G1')
        g2 = TargetGroup.objects.create(name='G2')
        g1.members.add(t)
        g2.members.add(t)
        self.assertEqual(t.groups.count(), 2)
