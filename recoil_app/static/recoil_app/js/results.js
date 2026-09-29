/* RecoilLab — «Все расчёты»: выбор пары для сравнения (запоминается в sessionStorage
   между страницами списка) и автоотправка сортировки. */
(function () {
    'use strict';

    var sortSelect = document.querySelector('[data-autosubmit]');
    if (sortSelect) sortSelect.addEventListener('change', function () { sortSelect.form.submit(); });

    var STORAGE_KEY = 'rb-cmp-picked';
    var bar = document.getElementById('rb-cmp-bar');
    if (!bar) return;
    var status = document.getElementById('rb-cmp-bar-status');
    var runsEl = document.getElementById('rb-cmp-bar-runs');
    var goBtn = document.getElementById('rb-cmp-go-btn');
    var clearBtn = document.getElementById('rb-cmp-clear-btn');
    var compareUrl = bar.dataset.compareUrl;

    var picked = [];
    try {
        picked = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]');
        if (!Array.isArray(picked)) picked = [];
    } catch (e) { picked = []; }

    function save() {
        try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(picked)); } catch (e) { /* noop */ }
    }

    function refresh() {
        var ids = picked.map(function (p) { return String(p.id); });
        document.querySelectorAll('.rb-cmp-pick-cb').forEach(function (cb) {
            var on = ids.indexOf(String(cb.dataset.runId)) !== -1;
            cb.checked = on;
            var row = cb.closest('tr');
            if (row) row.classList.toggle('is-picked', on);
        });
        bar.hidden = picked.length === 0;
        status.textContent = 'Выбрано: ' + picked.length + ' из 2';
        runsEl.textContent = picked.map(function (p) { return p.name; }).join(' и ');
        if (picked.length === 2) {
            goBtn.href = compareUrl + '?run_a=' + picked[0].id + '&run_b=' + picked[1].id;
            goBtn.setAttribute('aria-disabled', 'false');
        } else {
            goBtn.href = '#';
            goBtn.setAttribute('aria-disabled', 'true');
        }
    }

    document.querySelectorAll('.rb-cmp-pick-cb').forEach(function (cb) {
        cb.addEventListener('change', function () {
            var id = parseInt(cb.dataset.runId, 10);
            if (cb.checked) {
                if (picked.length >= 2) picked.shift();
                if (!picked.some(function (p) { return p.id === id; })) picked.push({ id: id, name: cb.dataset.runName });
            } else {
                picked = picked.filter(function (p) { return p.id !== id; });
            }
            save();
            refresh();
        });
    });
    goBtn.addEventListener('click', function (e) {
        if (goBtn.getAttribute('aria-disabled') === 'true') e.preventDefault();
    });
    clearBtn.addEventListener('click', function () { picked = []; save(); refresh(); });
    refresh();
})();
