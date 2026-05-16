(function () {
    'use strict';

    function updateFields() {
        var typeEl = document.getElementById('id_target_type');
        if (!typeEl) return;
        var type = typeEl.value;

        var rowDepts = document.querySelector('.field-target_departments');
        var rowGroups = document.querySelector('.field-target_groups');
        var rowInd   = document.querySelector('.field-individual_targets');

        if (rowDepts)  rowDepts.style.display  = (type === 'department') ? '' : 'none';
        if (rowGroups) rowGroups.style.display = (type === 'group')      ? '' : 'none';

        if (rowInd) {
            rowInd.style.display = (type === 'all') ? 'none' : '';
            var label = rowInd.querySelector('label');
            if (label) {
                label.textContent = (type === 'individual')
                    ? 'Individual targets'
                    : 'Additional individual targets';
            }
        }
    }

    function initStaleWarning() {
        var preview = document.querySelector('.field-resolved_targets_preview');
        if (!preview) return;

        var warning = document.createElement('p');
        warning.id = 'rt-stale';
        warning.style.cssText = 'display:none;color:#b8860b;background:#fffbe6;border:1px solid #ffe58f;'
            + 'border-radius:3px;padding:5px 8px;margin-top:6px;font-size:12px';
        warning.textContent = 'Targeting changed — save to refresh the preview.';
        preview.appendChild(warning);

        function markStale() {
            warning.style.display = '';
        }

        // Watch target_type select
        var typeEl = document.getElementById('id_target_type');
        if (typeEl) typeEl.addEventListener('change', markStale);

        // Watch filter_horizontal chosen lists (suffix _to) and individual_targets
        ['target_departments', 'target_groups', 'individual_targets'].forEach(function (name) {
            var chosen = document.getElementById('id_' + name + '_to');
            if (chosen) {
                new MutationObserver(markStale).observe(chosen, { childList: true });
            }
        });
    }

    function initTargetSearch() {
        var searchEl = document.getElementById('rt-search');
        var list     = document.getElementById('rt-list');
        if (!searchEl || !list) return;

        searchEl.addEventListener('input', function () {
            var q = this.value.trim().toLowerCase();
            list.querySelectorAll('.rt-row').forEach(function (row) {
                var text = row.textContent.toLowerCase();
                row.style.display = (!q || text.indexOf(q) !== -1) ? '' : 'none';
            });
        });
    }

    function initTargetRemoval() {
        var list = document.getElementById('rt-list');
        if (!list) return;

        var countEl  = document.getElementById('rt-count');
        var removedEl = document.getElementById('rt-removed');
        var form     = list.closest('form');
        if (!form) return;

        var removedCount = 0;

        list.addEventListener('click', function (e) {
            var btn = e.target.closest('.rt-remove');
            if (!btn) return;

            var targetId = btn.getAttribute('data-id');
            var row      = list.querySelector('.rt-row[data-id="' + targetId + '"]');
            if (!row) return;

            var input = document.createElement('input');
            input.type  = 'hidden';
            input.name  = 'excluded_targets';
            input.value = targetId;
            form.appendChild(input);

            row.remove();
            removedCount++;

            var remaining = list.querySelectorAll('.rt-row').length;
            if (countEl) {
                countEl.textContent = remaining + ' target' + (remaining !== 1 ? 's' : '') + ' will receive this campaign';
                var badge = document.createElement('span');
                badge.id = 'rt-removed';
                badge.style.cssText = 'color:#a80000;margin-left:6px';
                badge.textContent = '(' + removedCount + ' excluded — save to confirm)';
                countEl.appendChild(badge);
                removedEl = badge;
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var select = document.getElementById('id_target_type');
        if (select) {
            select.addEventListener('change', updateFields);
            updateFields();
        }
        initStaleWarning();
        initTargetSearch();
        initTargetRemoval();
    });
}());
