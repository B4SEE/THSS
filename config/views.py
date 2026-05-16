import re
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods


@staff_member_required
@require_http_methods(['GET', 'POST'])
def debug_toggle(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden()

    if request.method == 'POST':
        new_val = request.POST.get('debug') == '1'
        settings.DEBUG = new_val

        env_path = Path(settings.BASE_DIR) / '.env'
        text = env_path.read_text(encoding='utf-8')
        text = re.sub(r'^DEBUG=.*$', f'DEBUG={new_val}', text, flags=re.MULTILINE)
        env_path.write_text(text, encoding='utf-8')

        return redirect('debug_toggle')

    return render(request, 'admin/debug_toggle.html', {'debug': settings.DEBUG})
