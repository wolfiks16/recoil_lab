/* RecoilLab Modules Controller v2
   Управление видимостью модулей и табами через чекбоксы в боковой панели.

   Конвенции в HTML:
     <section class="rb-module-section" data-module="overview">...</section>
     <input type="checkbox" class="rb-module-checkbox" data-module="overview" checked>
     <button class="rb-tab" data-tab-group="phases" data-tab="recoil">Откат</button>
     <div class="rb-tab-panel" data-tab-group="phases" data-tab="recoil">...</div>

   Состояние сохраняется в localStorage (по ключу страницы), чтобы пользователь
   не терял настройку при перезагрузке.
*/

(function () {
    'use strict';

    const STORAGE_KEY = 'rb-modules-state-v1';

    function readState() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (e) {
            return {};
        }
    }

    function writeState(state) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (e) {
            // ignore quota
        }
    }

    function applyVisibility(moduleKey, visible) {
        document.querySelectorAll(`.rb-module-section[data-module="${moduleKey}"]`).forEach(el => {
            if (visible) {
                el.classList.remove('is-hidden');
            } else {
                el.classList.add('is-hidden');
            }
        });
        // Trigger Plotly relayout — иначе графики при первом показе сжаты.
        if (visible && window.Plotly) {
            requestAnimationFrame(() => {
                document.querySelectorAll(`.rb-module-section[data-module="${moduleKey}"] .plotly-graph-div`).forEach(div => {
                    try { window.Plotly.Plots.resize(div); } catch (e) { /* noop */ }
                });
            });
        }
    }

    function initModuleToggles() {
        const state = readState();
        const checkboxes = document.querySelectorAll('.rb-module-checkbox');

        checkboxes.forEach(cb => {
            const key = cb.dataset.module;
            if (!key) return;

            // Восстановить состояние
            if (key in state) {
                cb.checked = !!state[key];
            }
            applyVisibility(key, cb.checked);

            cb.addEventListener('change', () => {
                applyVisibility(key, cb.checked);
                const cur = readState();
                cur[key] = cb.checked;
                writeState(cur);
            });
        });

        // Кнопки «Показать все» / «Скрыть все»
        const showAll = document.getElementById('rb-modules-show-all');
        const hideAll = document.getElementById('rb-modules-hide-all');
        if (showAll) showAll.addEventListener('click', () => bulkSet(true));
        if (hideAll) hideAll.addEventListener('click', () => bulkSet(false));

        function bulkSet(value) {
            checkboxes.forEach(cb => {
                cb.checked = value;
                cb.dispatchEvent(new Event('change'));
            });
        }
    }

    function initTabs() {
        document.querySelectorAll('.rb-tabs').forEach(tabBar => {
            const group = tabBar.dataset.tabGroup;
            if (!group) return;

            const tabs = tabBar.querySelectorAll('.rb-tab');
            const panels = document.querySelectorAll(`.rb-tab-panel[data-tab-group="${group}"]`);

            // Дефолтный таб — первый или с .is-active
            let activeTab = Array.from(tabs).find(t => t.classList.contains('is-active'));
            if (!activeTab && tabs.length) activeTab = tabs[0];
            if (activeTab) activate(activeTab.dataset.tab);

            tabs.forEach(tab => {
                tab.addEventListener('click', (e) => {
                    e.preventDefault();
                    activate(tab.dataset.tab);
                });
            });

            function activate(tabKey) {
                tabs.forEach(t => t.classList.toggle('is-active', t.dataset.tab === tabKey));
                panels.forEach(p => {
                    const isActive = p.dataset.tab === tabKey;
                    p.classList.toggle('is-active', isActive);
                    // resize графиков в свежеактивированной панели
                    if (isActive && window.Plotly) {
                        requestAnimationFrame(() => {
                            p.querySelectorAll('.plotly-graph-div').forEach(div => {
                                try { window.Plotly.Plots.resize(div); } catch (e) {}
                            });
                        });
                    }
                });
            }
        });
    }

    function init() {
        initModuleToggles();
        initTabs();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
