/* Форма исследования подбора тормоза (optimize_form.html).

   - Режим строки границ «подбирать / зафиксировать»: класс is-fixed приглушает
     неактивные поля (они отправляются, сервер их игнорирует — значения не теряются).
   - «Подставить из расчёта-донора»: параметры параметрического тормоза донора
     → столбец «значение» (+ γ). Если у донора несколько тормозов — выбор номера.
*/
(function () {
    'use strict';

    var form = document.getElementById('optimize-form');
    if (!form) return;

    function toast(text, kind) {
        if (window.RecoilLab && window.RecoilLab.toast) window.RecoilLab.toast(text, kind);
    }

    // --- Режим строки ---
    function syncRow(select) {
        var row = select.closest('[data-space-row]');
        if (row) row.classList.toggle('is-fixed', select.value === 'fixed');
    }
    form.querySelectorAll('[data-space-mode]').forEach(syncRow);
    form.addEventListener('change', function (e) {
        if (e.target.matches('[data-space-mode]')) syncRow(e.target);
    });

    // --- Подстановка из донора ---
    var fillBtn = form.querySelector('[data-donor-fill]');
    var brakeSelect = form.querySelector('[data-donor-brake]');
    var donorSelect = form.elements.namedItem('source_run');
    var loaded = null;  // {runId, run, brakes}

    function setValue(name, value) {
        var input = form.elements.namedItem(name);
        if (input && value !== null && value !== undefined) input.value = value;
    }

    function applyBrake(brake) {
        Object.keys(brake.values).forEach(function (key) {
            setValue(key === 'gamma' ? 'gamma' : key + '_value', brake.values[key]);
        });
        toast('Подставлены значения тормоза ' + brake.index + ' из расчёта «' + loaded.run + '».', 'success');
    }

    function selectedBrake() {
        var idx = brakeSelect && !brakeSelect.hidden ? Number(brakeSelect.value) : null;
        return loaded.brakes.find(function (b) { return idx === null || b.index === idx; });
    }

    function showBrakeChoice() {
        brakeSelect.innerHTML = '';
        loaded.brakes.forEach(function (b) {
            var opt = document.createElement('option');
            opt.value = b.index;
            opt.textContent = 'Тормоз ' + b.index;
            brakeSelect.appendChild(opt);
        });
        brakeSelect.hidden = loaded.brakes.length < 2;
    }

    if (fillBtn && donorSelect) {
        fillBtn.addEventListener('click', function () {
            var runId = donorSelect.value;
            if (!runId) { toast('Сначала выберите расчёт-донор.', 'error'); return; }
            if (loaded && loaded.runId === runId) { applyBrake(selectedBrake()); return; }

            var url = form.dataset.donorUrl.replace(/\/0\/$/, '/' + encodeURIComponent(runId) + '/');
            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) {
                    if (!r.ok) throw new Error(r.status);
                    return r.json();
                })
                .then(function (data) {
                    if (!data.brakes.length) {
                        loaded = null;
                        brakeSelect.hidden = true;
                        toast('У расчёта-донора нет параметрического тормоза — подставлять нечего.', 'error');
                        return;
                    }
                    loaded = { runId: runId, run: data.run, brakes: data.brakes };
                    showBrakeChoice();
                    applyBrake(selectedBrake());
                })
                .catch(function () { toast('Не удалось получить параметры донора.', 'error'); });
        });
    }

    if (brakeSelect) {
        brakeSelect.addEventListener('change', function () {
            if (loaded) applyBrake(selectedBrake());
        });
    }
    if (donorSelect) {
        donorSelect.addEventListener('change', function () {
            loaded = null;
            if (brakeSelect) brakeSelect.hidden = true;
        });
    }
})();
