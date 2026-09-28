/* RecoilLab · Переключатель «Этапы на графиках» (итерационный расчёт).

   Полосы этапов, линии переключений, их подписи и ромбы переключений на v(x) рисуются
   на графиках СКРЫТЫМИ (charting: shapes/annotations с name="stage-*", трассы с
   meta="stage"). Переключатель показывает/скрывает их на всех графиках страницы.
   Выбор запоминается в браузере (localStorage) — одинаково для страницы результата
   и страницы сессии.

   Разметка: <input type="checkbox" data-stage-toggle> (их может быть несколько — синхронны).
   iterative.js после Plotly.react зовёт window.RecoilStages.apply(el, RecoilStages.isOn()).
*/
(function () {
    'use strict';

    const STORAGE_KEY = 'recoillab.showStages';

    function readPref() {
        try { return window.localStorage.getItem(STORAGE_KEY) === '1'; } catch (e) { return false; }
    }

    function writePref(value) {
        try { window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0'); } catch (e) { /* приватный режим */ }
    }

    function isStageName(name) {
        return typeof name === 'string' && name.indexOf('stage-') === 0;
    }

    function apply(gd, visible) {
        if (!gd || !gd.layout || typeof Plotly === 'undefined') return;
        const update = {};
        (gd.layout.shapes || []).forEach(function (shape, i) {
            if (isStageName(shape.name)) update['shapes[' + i + '].visible'] = visible;
        });
        (gd.layout.annotations || []).forEach(function (ann, i) {
            if (isStageName(ann.name)) update['annotations[' + i + '].visible'] = visible;
        });
        if (Object.keys(update).length) Plotly.relayout(gd, update);
        const traces = [];
        (gd.data || []).forEach(function (trace, i) {
            if (trace.meta === 'stage') traces.push(i);
        });
        if (traces.length) Plotly.restyle(gd, { visible: visible }, traces);
    }

    function applyAll(visible) {
        document.querySelectorAll('.js-plotly-plot').forEach(function (gd) { apply(gd, visible); });
    }

    window.RecoilStages = { isOn: readPref, apply: apply, applyAll: applyAll };

    function init() {
        const toggles = document.querySelectorAll('[data-stage-toggle]');
        if (!toggles.length) return;
        const on = readPref();
        toggles.forEach(function (toggle) {
            toggle.checked = on;
            toggle.addEventListener('change', function () {
                writePref(toggle.checked);
                toggles.forEach(function (other) { other.checked = toggle.checked; });
                applyAll(toggle.checked);
            });
        });
        if (on) applyAll(true);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
