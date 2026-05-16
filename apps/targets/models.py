from django.db import models


class Target(models.Model):
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
    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    members     = models.ManyToManyField(Target, blank=True, related_name='groups')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'target_groups'
        ordering = ['name']

    def __str__(self):
        return self.name

    def member_count(self):
        return self.members.count()
