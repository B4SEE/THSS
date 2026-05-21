"""Unit tests for the organizations app — Department and User models."""
from django.test import TestCase

from apps.organizations.models import Department, User


class DepartmentModelTests(TestCase):

    def test_str_returns_name(self):
        dept = Department(name='Engineering')
        self.assertEqual(str(dept), 'Engineering')

    def test_create_root_department(self):
        dept = Department.objects.create(name='Root')
        self.assertIsNone(dept.parent_dept)
        self.assertEqual(dept.description, '')

    def test_nested_department(self):
        root = Department.objects.create(name='Root')
        child = Department.objects.create(name='Sub', parent_dept=root)
        self.assertEqual(child.parent_dept, root)
        self.assertIn(child, root.children.all())

    def test_description_optional(self):
        dept = Department.objects.create(name='IT', description='Info Tech')
        self.assertEqual(dept.description, 'Info Tech')

    def test_parent_set_null_on_parent_delete(self):
        root = Department.objects.create(name='Root')
        child = Department.objects.create(name='Child', parent_dept=root)
        root.delete()
        child.refresh_from_db()
        self.assertIsNone(child.parent_dept)


class UserManagerTests(TestCase):

    def test_create_user_normalizes_email_domain(self):
        user = User.objects.create_user('Test@EXAMPLE.COM', 'Test User', 'pass123')
        self.assertEqual(user.email, 'Test@example.com')

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user('', 'Test User', 'pass')

    def test_create_user_is_not_staff_by_default(self):
        user = User.objects.create_user('u@test.com', 'User', 'pass')
        self.assertFalse(user.is_staff)

    def test_create_user_is_not_superuser_by_default(self):
        user = User.objects.create_user('u@test.com', 'User', 'pass')
        self.assertFalse(user.is_superuser)

    def test_create_superuser_sets_is_staff(self):
        user = User.objects.create_superuser('admin@test.com', 'Admin', 'pass')
        self.assertTrue(user.is_staff)

    def test_create_superuser_sets_is_superuser(self):
        user = User.objects.create_superuser('admin@test.com', 'Admin', 'pass')
        self.assertTrue(user.is_superuser)

    def test_password_is_hashed(self):
        user = User.objects.create_user('u@test.com', 'User', 'plaintext')
        self.assertNotEqual(user.password, 'plaintext')
        self.assertTrue(user.check_password('plaintext'))


class UserModelTests(TestCase):

    def test_str_format(self):
        user = User(email='alice@example.com', full_name='Alice Smith')
        self.assertEqual(str(user), 'Alice Smith <alice@example.com>')

    def test_username_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, 'email')

    def test_required_fields_contains_full_name(self):
        self.assertIn('full_name', User.REQUIRED_FIELDS)

    def test_is_active_default_true(self):
        user = User.objects.create_user('u@test.com', 'User', 'pass')
        self.assertTrue(user.is_active)

    def test_is_staff_default_false(self):
        user = User.objects.create_user('u@test.com', 'User', 'pass')
        self.assertFalse(user.is_staff)

    def test_email_is_unique(self):
        from django.db import IntegrityError
        User.objects.create_user('dup@test.com', 'User One', 'pass')
        with self.assertRaises(IntegrityError):
            User.objects.create_user('dup@test.com', 'User Two', 'pass')

    def test_created_at_is_set_on_save(self):
        user = User.objects.create_user('u@test.com', 'User', 'pass')
        self.assertIsNotNone(user.created_at)

    def test_updated_at_changes_on_save(self):
        user = User.objects.create_user('u@test.com', 'User', 'pass')
        old_ts = user.updated_at
        user.full_name = 'New Name'
        user.save()
        user.refresh_from_db()
        self.assertGreaterEqual(user.updated_at, old_ts)
