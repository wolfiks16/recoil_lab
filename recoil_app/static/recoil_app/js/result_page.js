/* RecoilLab — страница результата расчёта.

   1. Осциллограмма: фигура строится на сервере (charting.make_oscillogram_figure),
      здесь — отрисовка, считыватель курсора (все каналы в один момент времени)
      и кнопки участка цикла (это диапазон общей оси, а не другой набор графиков).
      Переключатель «Осциллограмма / Отдельные графики»: второй вид — прежний формат
      (x(t); v и a (t); силы F(t)) в цветах нового интерфейса, JSON фигур грузится при
      первом переключении (/run/<id>/chart/classic/), выбор запоминается в localStorage.
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
        // Высота — от контейнера (он тянется до высоты боковой колонки, минимум 640 px):
        // задаём её явно, чтобы первая отрисовка не зависела от отложенного autosize.
        if (el.clientHeight > 0) fig.layout.height = el.clientHeight;
        Plotly.newPlot(el, fig.data, fig.layout, config);
        // После загрузки шрифтов боковая колонка может стать выше — подогнать высоту ещё раз.
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(function () {
                var h = el.clientHeight;
                if (h > 0 && el._fullLayout && Math.abs(h - el._fullLayout.height) > 2) {
                    Plotly.relayout(el, { height: h });
                }
            });
        }

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

        // Участок цикла = диапазон общей оси времени (и у осциллограммы, и у отдельных графиков)
        var ranges = extra.ranges || {};
        var currentRange = 'all';
        var buttons = document.querySelectorAll('[data-range]');
        function press(key) {
            currentRange = key;
            buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.range === key ? 'true' : 'false'); });
        }
        function renderedClassic() {
            return Array.prototype.filter.call(document.querySelectorAll('[data-classic-plot]'),
                function (d) { return !!d._fullLayout; });
        }
        function applyRange(key) {
            var r = ranges[key];
            if (!r) return;
            press(key);
            Plotly.relayout(el, { 'xaxis.range': r.slice() });
            renderedClassic().forEach(function (d) { Plotly.relayout(d, { 'xaxis.range': r.slice() }); });
        }
        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () { applyRange(btn.dataset.range); });
        });
        // Выделение мышью / двойной щелчок — кнопки больше не соответствуют выбранному участку
        function onRelayout(ev) {
            if (ev && ev['xaxis.autorange']) {
                applyRange('all');
            } else if (ev && (ev['xaxis.range[0]'] !== undefined)) {
                press('');
            }
        }
        el.on('plotly_relayout', onRelayout);

        initClassicView({
            config: config,
            osc: el,
            rangeFor: function () { return currentRange && ranges[currentRange] && currentRange !== 'all' ? ranges[currentRange] : null; },
            onRelayout: onRelayout
        });
    }

    // ---------------- «Отдельные графики» (прежний формат) ----------------
    var VIEW_KEY = 'recoillab.resultView';

    function initClassicView(opts) {
        var box = document.querySelector('[data-view-panel="classic"]');
        var viewButtons = document.querySelectorAll('[data-view]');
        if (!box || !viewButtons.length) return;
        var oscPanel = document.querySelector('[data-view-panel="osc"]');
        var hint = document.querySelector('.rb-osc-hint');
        var tabs = box.querySelectorAll('[data-classic-tab]');
        var figures = null;
        var loading = null;
        var activeTab = 'x_t';

        function load() {
            if (figures) return Promise.resolve(figures);
            if (!loading) {
                loading = fetch(box.dataset.classicUrl, { credentials: 'same-origin' })
                    .then(function (r) {
                        if (!r.ok) throw new Error('HTTP ' + r.status);
                        return r.json();
                    })
                    .then(function (data) {
                        figures = data.figures || {};
                        // Вкладка есть только у графиков, которые построены (у свободного падения нет входной силы)
                        tabs.forEach(function (tab) { tab.hidden = !figures[tab.dataset.classicTab]; });
                        return figures;
                    })
                    .catch(function (err) {
                        loading = null;
                        var first = box.querySelector('[data-classic-plot]');
                        if (first) first.innerHTML = '<p class="rb-chart-missing">Графики не загрузились. Обновите страницу.</p>';
                        throw err;
                    });
            }
            return loading;
        }

        function render(key) {
            var div = box.querySelector('[data-classic-plot="' + key + '"]');
            if (!div) return;
            if (div._fullLayout) {
                try { Plotly.Plots.resize(div); } catch (e) { /* noop */ }
                return;
            }
            var fig = figures && figures[key];
            if (!fig) return;
            div.innerHTML = '';
            if (div.clientHeight > 0) fig.layout.height = div.clientHeight;
            var r = opts.rangeFor();
            if (r) fig.layout.xaxis.range = r.slice();
            Plotly.newPlot(div, fig.data, fig.layout, opts.config);
            div.on('plotly_relayout', opts.onRelayout);
            if (window.RecoilStages) window.RecoilStages.apply(div, window.RecoilStages.isOn());
        }

        function showTab(key) {
            activeTab = key;
            tabs.forEach(function (tab) {
                var on = tab.dataset.classicTab === key;
                tab.classList.toggle('is-active', on);
                tab.setAttribute('aria-selected', on ? 'true' : 'false');
            });
            box.querySelectorAll('[data-classic-plot]').forEach(function (div) {
                div.hidden = div.dataset.classicPlot !== key;
            });
            if (figures) render(key);
        }

        function setView(view, remember) {
            var classic = view === 'classic';
            box.hidden = !classic;
            if (oscPanel) oscPanel.hidden = classic;
            if (hint) hint.hidden = classic;
            viewButtons.forEach(function (b) {
                b.setAttribute('aria-pressed', b.dataset.view === view ? 'true' : 'false');
            });
            if (remember) {
                try { localStorage.setItem(VIEW_KEY, view); } catch (e) { /* приватный режим */ }
            }
            if (classic) {
                load().then(function () { showTab(activeTab); }).catch(function () { /* сообщение уже показано */ });
            } else {
                try { Plotly.Plots.resize(opts.osc); } catch (e) { /* noop */ }
            }
        }

        viewButtons.forEach(function (b) {
            b.addEventListener('click', function () { setView(b.dataset.view, true); });
        });
        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () { showTab(tab.dataset.classicTab); });
        });

        var saved = null;
        try { saved = localStorage.getItem(VIEW_KEY); } catch (e) { saved = null; }
        if (saved === 'classic') setView('classic', false);
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
