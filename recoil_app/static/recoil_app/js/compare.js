/* RecoilLab — сравнение двух расчётов: осциллограмма A/B со считывателем курсора,
   v(x) и |F|(|v|); кнопка «A ⇄ B» меняет расчёты местами. Фигуры строит сервер
   (charting.make_compare_oscillogram_figure / make_compare_phase_figures). */
(function () {
    'use strict';

    function readJson(id) {
        var el = document.getElementById(id);
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) { return null; }
    }

    var CONFIG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] };

    // Поменять A и B местами
    var swap = document.querySelector('[data-swap]');
    if (swap) {
        swap.addEventListener('click', function () {
            var form = swap.closest('form');
            var a = form.querySelector('[name="run_a"]');
            var b = form.querySelector('[name="run_b"]');
            var tmp = a.value; a.value = b.value; b.value = tmp;
            if (a.value && b.value) form.submit();
        });
    }

    if (typeof Plotly === 'undefined') return;

    [['cmp-vx', 'cmp-vx-figure'], ['cmp-fv', 'cmp-fv-figure']].forEach(function (pair) {
        var fig = readJson(pair[1]);
        var el = document.getElementById(pair[0]);
        if (fig && el) Plotly.newPlot(el, fig.data, fig.layout, CONFIG);
    });

    var fig = readJson('cmp-osc-figure');
    var el = document.getElementById('cmp-osc');
    if (!fig || !el) return;
    Plotly.newPlot(el, fig.data, fig.layout, CONFIG);

    // Трассы идут парами (A, B) по каналам x, v, a, F.
    var UNITS = ['мм', 'м/с', 'g', ''];
    var DIGITS = [1, 3, 1, 1];
    var fUnit = (fig.layout.yaxis4 && fig.layout.yaxis4.title && fig.layout.yaxis4.title.text || '').split(', ').pop();
    UNITS[3] = fUnit;
    var readout = document.getElementById('cmp-readout');

    function valueAt(trace, t) {
        // Ближайшая точка по времени (ряды A и B имеют разные сетки t).
        var xs = trace.x, lo = 0, hi = xs.length - 1;
        if (!xs.length || t < xs[0] || t > xs[hi]) return null;
        while (hi - lo > 1) {
            var mid = (lo + hi) >> 1;
            if (xs[mid] < t) lo = mid; else hi = mid;
        }
        return (t - xs[lo] <= xs[hi] - t) ? trace.y[lo] : trace.y[hi];
    }
    function fmt(v, d) { return (v === null || v === undefined) ? '—' : Number(v).toFixed(d); }

    el.on('plotly_hover', function (ev) {
        if (!ev.points || !ev.points.length || !readout) return;
        var t = ev.points[0].x;
        readout.querySelector('[data-r="t"]').textContent = fmt(t, 4) + ' с';
        ['x', 'v', 'a', 'f'].forEach(function (key, i) {
            var a = valueAt(fig.data[2 * i], t);
            var b = valueAt(fig.data[2 * i + 1], t);
            readout.querySelector('[data-r="' + key + '"]').textContent =
                fmt(a, DIGITS[i]) + ' / ' + fmt(b, DIGITS[i]) + ' ' + UNITS[i];
        });
    });
})();
