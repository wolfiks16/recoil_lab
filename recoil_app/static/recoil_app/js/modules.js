/* RecoilLab — вкладки [data-tab-group].

   Разметка:
     <div class="rb-tabs" data-tab-group="brake-3d">
       <button class="rb-tab is-active" data-tab="b1">…</button>
     </div>
     <div class="rb-tab-panel is-active" data-tab-group="brake-3d" data-tab="b1">…</div>

   Используется на странице результата (3D-модели тормозов) и на странице теплового
   сценария (графики). Графики Plotly в только что показанной панели пересчитывают размер.
   (Раньше здесь же были чекбоксы видимости модулей страницы результата — после
   редизайна их заменили сворачиваемые разделы <details class="rb-fold">.)
*/

(function () {
    'use strict';

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
                                try { window.Plotly.Plots.resize(div); } catch (e) { /* noop */ }
                            });
                        });
                    }
                });
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTabs);
    } else {
        initTabs();
    }
})();
