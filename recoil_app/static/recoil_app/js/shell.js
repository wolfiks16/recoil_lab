/* RecoilLab — поведение каркаса страницы (разметку рендерит сервер, base_v2.html).

   - сворачивание боковой навигации (запоминается в localStorage);
   - меню на узком экране (выезжающая панель + затемнение);
   - подтверждение действий: <form data-confirm="Текст вопроса">;
   - индикатор фоновых задач: пока есть запущенные — раз в 8 с спрашиваем сервер;
   - window.RecoilLab.toast(text, kind) — короткое уведомление.
*/
(function () {
    'use strict';

    var NAV_KEY = 'recoillab.navCollapsed';
    var root = document.documentElement;

    function store(key, value) {
        try { localStorage.setItem(key, value); } catch (e) { /* приватный режим */ }
    }

    // --- Навигация: свернуть/развернуть (широкий экран) ---
    function syncCollapseButton() {
        var btn = document.querySelector('[data-nav-collapse]');
        if (!btn) return;
        var collapsed = root.classList.contains('rb-nav-collapsed');
        btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        btn.title = collapsed ? 'Развернуть меню' : 'Свернуть меню';
        var sr = btn.querySelector('.rb-visually-hidden');
        if (sr) sr.textContent = btn.title;
    }

    function initCollapse() {
        var btn = document.querySelector('[data-nav-collapse]');
        if (!btn) return;
        syncCollapseButton();
        btn.addEventListener('click', function () {
            var collapsed = root.classList.toggle('rb-nav-collapsed');
            store(NAV_KEY, collapsed ? '1' : '0');
            syncCollapseButton();
            // Графики Plotly подстраиваются под новую ширину контента.
            if (window.Plotly) {
                setTimeout(function () {
                    document.querySelectorAll('.js-plotly-plot').forEach(function (div) {
                        try { window.Plotly.Plots.resize(div); } catch (e) { /* noop */ }
                    });
                }, 180);
            }
        });
    }

    // --- Навигация на узком экране ---
    function initMobileNav() {
        var openBtn = document.querySelector('[data-nav-open]');
        var backdrop = document.querySelector('.rb-nav-backdrop');
        if (!openBtn) return;

        function setOpen(open) {
            root.classList.toggle('rb-nav-open', open);
            openBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (backdrop) backdrop.hidden = !open;
            if (open) {
                var first = document.querySelector('#rb-nav a, #rb-nav button');
                if (first) first.focus();
            }
        }
        openBtn.addEventListener('click', function () { setOpen(true); });
        document.querySelectorAll('[data-nav-close]').forEach(function (el) {
            el.addEventListener('click', function () { setOpen(false); });
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && root.classList.contains('rb-nav-open')) {
                setOpen(false);
                openBtn.focus();
            }
        });
    }

    // --- Подтверждение действий и запрос имени ---
    //   <form data-confirm="Удалить …?">                       — вопрос «да/нет»;
    //   <form data-prompt="Имя копии:" data-prompt-default="…"> — спросить имя и
    //       положить его в поле формы name (пустое имя не отправляем).
    function initConfirm() {
        document.addEventListener('submit', function (e) {
            var form = e.target;
            if (!(form instanceof HTMLFormElement)) return;
            var question = form.getAttribute('data-confirm');
            if (question && !window.confirm(question)) {
                e.preventDefault();
                return;
            }
            var ask = form.getAttribute('data-prompt');
            if (ask) {
                var value = window.prompt(ask, form.getAttribute('data-prompt-default') || '');
                if (value === null || !value.trim()) {
                    e.preventDefault();
                    return;
                }
                var field = form.elements.namedItem('name');
                if (field) field.value = value.trim();
            }
        }, true);
    }

    // --- Уведомление ---
    function toast(text, kind) {
        var el = document.getElementById('rb-toast');
        if (!el) {
            el = document.createElement('div');
            el.id = 'rb-toast';
            el.className = 'rb-toast';
            el.setAttribute('role', 'status');
            document.body.appendChild(el);
        }
        el.textContent = text;
        el.classList.remove('is-success', 'is-error');
        if (kind === 'success') el.classList.add('is-success');
        if (kind === 'error') el.classList.add('is-error');
        el.classList.add('is-visible');
        clearTimeout(el._timer);
        el._timer = setTimeout(function () { el.classList.remove('is-visible'); }, 3200);
    }

    // --- Индикатор фоновых задач ---
    function escapeHtml(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function renderTasks(box, tasks) {
        if (!tasks.length) {
            box.innerHTML = '<span class="rb-tasks-idle"><span class="rb-tasks-dot" aria-hidden="true"></span>Фоновых задач нет</span>';
            return;
        }
        var items = tasks.map(function (t) {
            return '<li><a href="' + escapeHtml(t.url) + '">' + escapeHtml(t.label) + '</a><span>' +
                escapeHtml(t.status) + '</span></li>';
        }).join('');
        var wasOpen = box.querySelector('details[open]') !== null;
        box.innerHTML = '<details class="rb-tasks-menu"' + (wasOpen ? ' open' : '') + '><summary>' +
            '<span class="rb-tasks-dot is-running" aria-hidden="true"></span>Фоновых задач: ' + tasks.length +
            '</summary><ul class="rb-tasks-list">' + items + '</ul></details>';
    }

    function initTasks() {
        var box = document.querySelector('[data-tasks]');
        if (!box || box.dataset.running !== '1') return;
        var url = box.dataset.tasksUrl;
        // Задачи, отрисованные сервером, — чтобы по их исчезновению сказать «готово».
        var known = Array.prototype.map.call(
            box.querySelectorAll('.rb-tasks-list a'), function (a) { return a.textContent; });

        function poll() {
            fetch(url, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data) return;
                    var tasks = data.tasks || [];
                    var labels = tasks.map(function (t) { return t.label; });
                    known.forEach(function (label) {
                        if (labels.indexOf(label) === -1) toast(label + ': завершена', 'success');
                    });
                    known = labels;
                    renderTasks(box, tasks);
                    if (tasks.length) setTimeout(poll, 8000);
                })
                .catch(function () { /* сеть моргнула — индикатор просто замрёт */ });
        }
        setTimeout(poll, 8000);
    }

    function init() {
        initCollapse();
        initMobileNav();
        initConfirm();
        initTasks();
    }

    window.RecoilLab = window.RecoilLab || {};
    window.RecoilLab.toast = toast;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
