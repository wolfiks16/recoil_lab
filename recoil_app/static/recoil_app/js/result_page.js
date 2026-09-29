/* RecoilLab — страница результата расчёта.

   1. Осциллограмма: фигура строится на сервере (charting.make_oscillogram_figure),
      здесь — отрисовка, считыватель курсора (все каналы в один момент времени)
      и кнопки участка цикла (это диапазон общей оси, а не другой набор графиков).
   2. Вторичные графики (<div data-lazy-chart="url">) догружаются, когда
      подходят к экрану или раскрывается их раздел, — страница открывается быстро.
*/
(function () {
    'use strict';

    function readJson(id) {
        var el = document.getElementById(id);
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) { return null; }
    }

    function fmt(value, digits) {
        if (value === null || value === undefined || isNaN(value)) return '—';
        return Number(value).toFixed(digits);
    }

    // ---------------- Осциллограмма ----------------
    function initOscillogram() {
        var fig = readJson('osc-figure');
        var extra = readJson('osc-extra') || {};
        var el = document.getElementById('osc');
        if (!fig || !el || typeof Plotly === 'undefined') return;

        var config = {
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
            toImageButtonOptions: { filename: 'oscillogram', scale: 2 }
        };
        Plotly.newPlot(el, fig.data, fig.layout, config);

        var t = fig.data[0].x;
        var ch = fig.data.map(function (trace) { return trace.y; });
        var stage = extra.stage || null;
        var readout = document.getElementById('osc-readout');
        function setR(key, text) {
            var b = readout && readout.querySelector('[data-r="' + key + '"]');
            if (b) b.textContent = text;
        }
        el.on('plotly_hover', function (ev) {
            if (!ev.points || !ev.points.length) return;
            var i = ev.points[0].pointIndex;
            setR('t', fmt(t[i], 4) + ' с');
            setR('x', fmt(ch[0][i], 1) + ' мм');
            setR('v', fmt(ch[1][i], 3) + ' м/с');
            setR('a', fmt(ch[2][i], 1) + ' g');
            setR('f', fmt(ch[3][i], 1) + ' ' + (extra.f_unit || 'кН'));
            if (stage) setR('s', String(stage[i]));
        });

        // Участок цикла = диапазон общей оси времени
        var ranges = extra.ranges || {};
        var buttons = document.querySelectorAll('[data-range]');
        function press(key) {
            buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.range === key ? 'true' : 'false'); });
        }
        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var r = ranges[btn.dataset.range];
                if (!r) return;
                press(btn.dataset.range);
                Plotly.relayout(el, { 'xaxis.range': r.slice() });
            });
        });
        // Выделение мышью / двойной щелчок — кнопки больше не соответствуют выбранному участку
        el.on('plotly_relayout', function (ev) {
            if (ev && ev['xaxis.autorange']) {
                press('all');
                Plotly.relayout(el, { 'xaxis.range': ranges.all.slice() });
            } else if (ev && (ev['xaxis.range[0]'] !== undefined)) {
                press('');
            }
        });
    }

    // ---------------- Ленивые графики ----------------
    function runScripts(container) {
        // innerHTML не исполняет <script> — пересоздаём их (Plotly-фрагменты).
        container.querySelectorAll('script').forEach(function (old) {
            var s = document.createElement('script');
            if (old.type) s.type = old.type;
            s.text = old.textContent;
            old.parentNode.replaceChild(s, old);
        });
    }

    function applyStages(container) {
        if (!window.RecoilStages) return;
        var on = window.RecoilStages.isOn();
        container.querySelectorAll('.js-plotly-plot').forEach(function (gd) {
            window.RecoilStages.apply(gd, on);
        });
    }

    function loadChart(box) {
        if (box.dataset.loaded) return;
        box.dataset.loaded = '1';
        fetch(box.dataset.lazyChart, { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.text();
            })
            .then(function (html) {
                box.innerHTML = html;
                box.classList.add('is-loaded');
                runScripts(box);
                setTimeout(function () { applyStages(box); }, 50);
            })
            .catch(function () {
                box.innerHTML = '<p class="rb-chart-missing">График не загрузился. Обновите страницу.</p>';
                box.classList.add('is-loaded');
            });
    }

    function isShown(el) {
        // Внутри закрытого <details> или неактивной вкладки — не грузим, пока не покажут.
        return el.offsetParent !== null;
    }

    function initLazy() {
        var boxes = Array.prototype.slice.call(document.querySelectorAll('[data-lazy-chart]'));
        if (!boxes.length) return;

        var observer = null;
        if ('IntersectionObserver' in window) {
            observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting && isShown(entry.target)) {
                        observer.unobserve(entry.target);
                        loadChart(entry.target);
                    }
                });
            }, { rootMargin: '300px 0px' });
            boxes.forEach(function (b) { observer.observe(b); });
        } else {
            boxes.forEach(function (b) { if (isShown(b)) loadChart(b); });
        }

        // Раскрыли раздел или переключили вкладку — догрузить видимое содержимое
        function loadVisibleIn(root) {
            root.querySelectorAll('[data-lazy-chart]').forEach(function (b) {
                if (!b.dataset.loaded && isShown(b)) loadChart(b);
            });
            root.querySelectorAll('.js-plotly-plot').forEach(function (gd) {
                try { Plotly.Plots.resize(gd); } catch (e) { /* noop */ }
            });
        }
        document.querySelectorAll('details.rb-fold').forEach(function (d) {
            d.addEventListener('toggle', function () { if (d.open) loadVisibleIn(d); });
        });
        document.addEventListener('click', function (e) {
            var tab = e.target.closest && e.target.closest('.rb-tab');
            if (!tab) return;
            setTimeout(function () { loadVisibleIn(document); }, 30);
        });
    }

    function init() {
        initOscillogram();
        initLazy();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
