import csv
import io

from django.contrib import admin
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path

from apps.admin_mixins import StaffAccessMixin, audit
from .models import Target, TargetGroup


# ── Target ────────────────────────────────────────────────────────────────────

@admin.register(Target)
class TargetAdmin(StaffAccessMixin, admin.ModelAdmin):
    change_list_template = 'admin/targets/target_changelist.html'
    list_display  = ('email', 'full_name', 'department', 'opt_out')
    list_filter   = ('department', 'opt_out')
    search_fields = ('email', 'full_name')
    ordering      = ('full_name',)
    fields        = ('email', 'full_name', 'department', 'opt_out')
    actions       = ['opt_out_selected', 'opt_in_selected']

    def get_urls(self):
        return [
            path('import-csv/', self.admin_site.admin_view(self.import_csv_view),
                 name='target_import_csv'),
        ] + super().get_urls()

    def import_csv_view(self, request):
        if request.method == 'POST':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                self.message_user(request, 'No file selected.', level='error')
                return HttpResponseRedirect(request.path)

            replace = 'replace' in request.POST
            text    = csv_file.read().decode('utf-8-sig')
            reader  = csv.DictReader(io.StringIO(text))

            if replace:
                Target.objects.all().delete()

            from apps.organizations.models import Department
            created = updated = skipped = 0
            for row in reader:
                email = (row.get('email') or '').strip().lower()
                if not email:
                    skipped += 1
                    continue
                full_name = (row.get('full_name') or email).strip()
                dept_name = (row.get('department') or '').strip()
                department = None
                if dept_name:
                    department, _ = Department.objects.get_or_create(name=dept_name)

                _, was_created = Target.objects.update_or_create(
                    email=email,
                    defaults={'full_name': full_name, 'department': department},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            self.message_user(
                request,
                f'Import complete: {created} created, {updated} updated, {skipped} skipped.',
            )
            return HttpResponseRedirect('..')

        return render(request, 'admin/targets/import_csv.html', {
            'title': 'Import Targets from CSV',
            'opts':  self.model._meta,
        })

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit(request, 'target_updated' if change else 'target_created', obj,
              changes={'fields': form.changed_data} if change and form.changed_data else None)

    def delete_model(self, request, obj):
        audit(request, 'target_deleted', obj, changes={
            'email': obj.email,
            'full_name': obj.full_name,
            'department': str(obj.department) if obj.department else None,
        })
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            audit(request, 'target_deleted', obj, changes={
                'email': obj.email,
                'full_name': obj.full_name,
                'department': str(obj.department) if obj.department else None,
            })
        super().delete_queryset(request, queryset)

    @admin.action(description='Opt out — exclude from future campaigns')
    def opt_out_selected(self, request, queryset):
        n = queryset.update(opt_out=True)
        self.message_user(request, f'{n} target(s) opted out.')

    @admin.action(description='Opt in — include in future campaigns')
    def opt_in_selected(self, request, queryset):
        n = queryset.update(opt_out=False)
        self.message_user(request, f'{n} target(s) opted in.')


# ── Target Group ──────────────────────────────────────────────────────────────

@admin.register(TargetGroup)
class TargetGroupAdmin(StaffAccessMixin, admin.ModelAdmin):
    list_display      = ('name', 'description', 'member_count')
    search_fields     = ('name',)
    filter_horizontal = ['members']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit(request, 'targetgroup_updated' if change else 'targetgroup_created', obj,
              changes={'fields': form.changed_data} if change and form.changed_data else None)

    def delete_model(self, request, obj):
        audit(request, 'targetgroup_deleted', obj)
        super().delete_model(request, obj)

    @admin.display(description='Members')
    def member_count(self, obj):
        return obj.members.count()
