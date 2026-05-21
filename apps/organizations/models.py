"""
Platform administrator accounts and organizational hierarchy.

Department — org chart node, optionally nested.
User       — platform admins who log in to manage campaigns; NOT phishing targets.
"""
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class Department(models.Model):
    """Organizational unit in the company hierarchy, optionally nested under a parent."""
    name        = models.CharField(max_length=100)
    parent_dept = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children'
    )
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'departments'

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    """Custom manager using email as the unique identifier instead of username."""

    def create_user(self, email, full_name, password=None, **extra_fields):
        """Create and save a platform user with the given email, full_name, and password."""
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user  = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra_fields):
        """Create and save a superuser; forces is_staff=True and is_superuser=True."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, full_name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Platform administrators — the only people who log in to this system."""
    email      = models.EmailField(max_length=255, unique=True, db_index=True)
    full_name  = models.CharField(max_length=255)
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = UserManager()

    class Meta:
        db_table = 'users'

    def __str__(self):
        return f'{self.full_name} <{self.email}>'
