"""
Phishing simulation targets — people who receive phishing emails.

Distinct from platform Users (admins).  A Target may belong to a Department
and can be assigned to one or more TargetGroups for bulk campaign assignment.
"""
from django.db import models


class Target(models.Model):
    """A single email recipient for phishing campaigns."""
    email      = models.EmailField(unique=True)
    full_name  = models.CharField(max_length=255)
    department = models.ForeignKey(
        'organizations.Department', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='targets',
    )
    opt_out    = models.BooleanField(default=False, help_text='Exclude from all future campaigns')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'targets'
        ordering = ['full_name']

    def __str__(self):
        return f'{self.full_name} <{self.email}>'


class TargetGroup(models.Model):
    """Named collection of Targets for bulk assignment to campaigns."""
    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    members     = models.ManyToManyField(Target, blank=True, related_name='groups')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'target_groups'
        ordering = ['name']

    def __str__(self):
        return self.name

    def member_count(self) -> int:
        """Return the current number of targets in this group."""
        return self.members.count()
