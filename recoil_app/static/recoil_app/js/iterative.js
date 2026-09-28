/* RecoilLab · Итерационный расчёт (Срез 12)

   Две страницы:
   - /iterative/new/  — старт: переключатель режима + редактор исходной конфигурации тормозов;
   - /iterative/<id>/ — сессия: кнопки (Шаг / N шагов / До точки через Δx / Изменить конфигурацию /
     Досчитать до конца / Остановить), AJAX-ответ обновляет панели и графики без перезагрузки.

   Редактор тормозов (formset `slots`) — делегированные обработчики на document: после AJAX его
   HTML заменяется целиком, повторная привязка не нужна.
*/
(function () {
    'use strict';

    const CATALOG = readJson('rb-catalog-data') || [];
    const PARAM_NAMES = ['gamma', 'delta', 'xm', 'ym', 'dh1', 'dh2', 'dm', 'n', 'mu', 'bz', 'lya', 'wn0'];

    function readJson(id) {
        const el = document.getElementById(id);
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) { return null; }
    }

    // ================================================================ редактор тормозов

    function slotField(slot, name) {
        return slot.querySelector('[name$="-' + name + '"]');
    }

    function updateSlotKind(slot) {
        const kindSelect = slotField(slot, 'kind');
        if (!kindSelect) return;
        const kind = kindSelect.value;
        slot.querySelectorAll('[data-kind-block]').forEach(function (block) {
            block.hidden = block.dataset.kindBlock !== kind;
        });
    }

    function initEditors(root) {
        (root || document).querySelectorAll('[data-slot]').forEach(updateSlotKind);
        renumber(root || document);
    }

    function renumber(root) {
        (root.querySelectorAll ? root : document).querySelectorAll('[data-editor]').forEach(function (editor) {
            let number = 0;
            editor.querySelectorAll('[data-slots] > [data-slot]').forEach(function (slot) {
                if (slot.hidden) return;
                number += 1;
                const title = slot.querySelector('[data-slot-title]');
                if (title) title.textContent = 'Тормоз ' + number;
            });
        });
    }

    function isChanged(el) {
        if (el.type === 'file') return el.files && el.files.length > 0;
        if (el.tagName === 'SELECT') {
            const opt = el.options[el.selectedIndex];
            return opt ? !opt.defaultSelected : false;
        }
        return el.value !== el.defaultValue;
    }

    function markChanged(el) {
        const editor = el.closest('[data-editor]');
        if (!editor || editor.dataset.editorMode !== 'reconfigure') return;
        const slot = el.closest('[data-slot]');
        if (slot && slot.querySelector('[data-new-badge]:not([hidden])')) return;  // новый тормоз — весь «новый»
        el.classList.toggle('it-changed', isChanged(el));
    }

    function applyCatalog(slot, catalogId) {
        const hidden = slotField(slot, 'catalog_source_id');
        const note = slot.querySelector('[data-catalog-note]');
        const item = CATALOG.find(function (c) { return String(c.id) === String(catalogId); });
        if (hidden) hidden.value = item ? item.id : '';
        if (!item) {
            if (note) note.hidden = true;
            return;
        }
        const kindSelect = slotField(slot, 'kind');
        if (item.is_parametric) {
            kindSelect.value = 'parametric';
            PARAM_NAMES.forEach(function (name) {
                const input = slotField(slot, name);
                const value = item.params[name];
                if (input && value !== null && value !== undefined) {
                    input.value = value;
                    markChanged(input);
                }
            });
            if (note) note.hidden = true;
        } else {
            kindSelect.value = 'curve';
            const file = slotField(slot, 'force_curve_file');
            if (file) file.value = '';
            if (note) {
                note.textContent = 'Таблица F(v) будет взята из каталога: «' + item.name + '».';
                note.hidden = false;
            }
        }
        markChanged(kindSelect);
        updateSlotKind(slot);
    }

    function addSlot(editor) {
        const template = editor.querySelector('template[data-slot-template]');
        const total = editor.querySelector('input[name$="-TOTAL_FORMS"]');
        if (!template || !total) return;
        const index = parseInt(total.value, 10) || 0;
        const html = template.innerHTML.replace(/__prefix__/g, String(index));
        const holder = document.createElement('div');
        holder.innerHTML = html.trim();
        const slot = holder.firstElementChild;
        editor.querySelector('[data-slots]').appendChild(slot);
        total.value = String(index + 1);
        updateSlotKind(slot);
        renumber(editor);
        slot.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function removeSlot(slot) {
        const editor = slot.closest('[data-editor]');
        const visible = editor.querySelectorAll('[data-slots] > [data-slot]:not([hidden])');
        if (visible.length <= 1) {
            showMessage('Нужен хотя бы один тормоз.', 'warning');
            return;
        }
        const del = slotField(slot, 'DELETE');
        if (del) del.checked = true;
        slot.hidden = true;
        renumber(editor);
    }

    document.addEventListener('change', function (e) {
        const el = e.target;
        const slot = el.closest && el.closest('[data-slot]');
        if (!slot) return;
        if (el.matches('[data-catalog-select]')) {
            applyCatalog(slot, el.value);
            return;
        }
        if (el.name && /-kind$/.test(el.name)) updateSlotKind(slot);
        if (el.name && /-force_curve_file$/.test(el.name) && el.files.length) {
            // Загруженный файл важнее выбранного каталога.
            const hidden = slotField(slot, 'catalog_source_id');
            if (hidden) hidden.value = '';
            const note = slot.querySelector('[data-catalog-note]');
            if (note) note.hidden = true;
        }
        markChanged(el);
    });

    document.addEventListener('input', function (e) {
        if (e.target.closest && e.target.closest('[data-slot]')) markChanged(e.target);
    });

    document.addEventListener('click', function (e) {
        const add = e.target.closest('[data-add-slot]');
        if (add) {
            addSlot(add.closest('[data-editor]'));
            return;
        }
        const remove = e.target.closest('[data-remove-slot]');
        if (remove) removeSlot(remove.closest('[data-slot]'));
    });

    // ================================================================ страница старта

    function initNewPage() {
        const form = document.getElementById('it-new-form');
        if (!form) return;
        const angle = form.querySelector('[name="angle_deg"]');

        function currentMode() {
            const checked = form.querySelector('[name="mode"]:checked');
            return checked ? checked.value : 'recoil';
        }

        function applyMode(changedByUser) {
            const mode = currentMode();
            form.querySelectorAll('[data-mode-only]').forEach(function (el) {
                el.hidden = el.dataset.modeOnly !== mode;
            });
            // Угол по умолчанию: откат — 70°, свободное падение — 90° (если пользователь не менял).
            if (changedByUser && angle) {
                const value = parseFloat(angle.value);
                if (mode === 'free_fall' && value === 70) angle.value = '90';
                if (mode === 'recoil' && value === 90) angle.value = '70';
            }
        }

        form.querySelectorAll('[name="mode"]').forEach(function (radio) {
            radio.addEventListener('change', function () { applyMode(true); });
        });
        applyMode(false);
    }

    // ================================================================ страница сессии

    const controls = document.getElementById('it-controls');
    let busy = false;
    let closeEditorOnSuccess = false;

    function showMessage(text, level, extraHtml) {
        const box = document.getElementById('it-message');
        if (!box) {
            if (text) window.alert(text);
            return;
        }
        if (!text) {
            box.hidden = true;
            return;
        }
        box.className = 'rb-flash rb-flash-' + (level || 'info');
        box.textContent = text;
        if (extraHtml) box.insertAdjacentHTML('beforeend', extraHtml);
        box.hidden = false;
    }

    function renderCharts(charts) {
        if (!charts || typeof Plotly === 'undefined') return;
        Object.keys(charts).forEach(function (key) {
            const el = document.getElementById('it-chart-' + key);
            if (!el) return;
            const fig = charts[key];
            Plotly.react(el, fig.data, fig.layout, { responsive: true, displaylogo: false })
                .then(function () {
                    // Этапы приходят скрытыми — показать, если включён переключатель.
                    if (window.RecoilStages && window.RecoilStages.isOn()) window.RecoilStages.apply(el, true);
                });
        });
    }

    function setBusy(value) {
        busy = value;
        const overlay = document.getElementById('it-busy');
        if (overlay) overlay.hidden = !value;
        document.querySelectorAll('#it-controls button, #it-editor-form button').forEach(function (b) {
            b.disabled = value;
        });
        // После запроса доступность кнопок задают флаги сессии (завершён / можно ли менять).
        if (!value) applyFlags(currentFlags());
    }

    function currentFlags() {
        return {
            finished: controls.dataset.finished === '1',
            can_reconfigure: controls.dataset.canReconfigure === '1',
            can_undo: controls.dataset.canUndo === '1',
            phase: controls.dataset.phase || null,
        };
    }

    function applyFlags(flags) {
        if (!controls || !flags) return;
        controls.dataset.finished = flags.finished ? '1' : '0';
        controls.dataset.canReconfigure = flags.can_reconfigure ? '1' : '0';
        controls.dataset.canUndo = flags.can_undo ? '1' : '0';
        controls.dataset.phase = flags.phase || '';
        // Отмена доступна и после «досчитался до конца» (итог ещё не сохранён).
        const undo = controls.querySelector('[data-undo]');
        if (undo) undo.disabled = !flags.can_undo;
        const undoHint = controls.querySelector('[data-undo-hint]');
        if (undoHint && flags.undo_hint !== undefined) undoHint.textContent = flags.undo_hint || '';
        controls.querySelectorAll('[data-advance]').forEach(function (el) {
            el.disabled = !!flags.finished;
        });
        const toggle = controls.querySelector('[data-toggle-editor]');
        if (toggle) toggle.disabled = !flags.can_reconfigure;
        const hint = controls.querySelector('[data-reconfigure-hint]');
        if (hint && flags.phase === 'return') hint.textContent = 'на накате — только автоматически';
        if (!flags.can_reconfigure) toggleEditor(false);
    }

    function toggleEditor(show) {
        const panel = document.getElementById('it-editor-panel');
        if (!panel) return;
        const visible = show === undefined ? panel.hidden : show;
        panel.hidden = !visible;
        if (visible) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function csrfToken() {
        const input = document.querySelector('#it-controls [name="csrfmiddlewaretoken"]');
        return input ? input.value : '';
    }

    function send(formData) {
        if (busy) return;
        setBusy(true);
        fetch(controls.dataset.actionUrl, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(function (resp) {
                return resp.json().catch(function () {
                    throw new Error('Сервер вернул ошибку ' + resp.status + '.');
                });
            })
            .then(handleResponse)
            .catch(function (err) { showMessage(err.message || String(err), 'error'); })
            .finally(function () { setBusy(false); });
    }

    function handleResponse(data) {
        const closeEditor = closeEditorOnSuccess;
        closeEditorOnSuccess = false;
        if (data.redirect) {
            window.location.href = data.redirect;
            return;
        }
        if (data.background) {
            // Долгий досчёт ушёл в фон — страница покажет индикатор и будет опрашивать статус.
            window.location.reload();
            return;
        }
        if (!data.ok) {
            const reload = data.stale
                ? ' <a href="" onclick="window.location.reload(); return false;">Обновить страницу</a>'
                : '';
            showMessage(data.error || 'Ошибка.', data.stale ? 'warning' : 'error', reload);
            return;
        }
        const html = data.html || {};
        if (html.state) document.getElementById('it-state').innerHTML = html.state;
        if (html.stages) document.getElementById('it-stages').innerHTML = html.stages;
        const editorHolder = document.getElementById('it-editor');
        if (html.editor && editorHolder) {
            editorHolder.innerHTML = html.editor;
            initEditors(editorHolder);
        }
        renderCharts(data.charts);
        applyFlags(data.flags);
        showMessage(data.message, 'info');
        if (closeEditor) {
            toggleEditor(false);
            controls.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function initSessionPage() {
        renderCharts(readJson('it-charts'));
        if (!controls) return;

        applyFlags(currentFlags());

        controls.addEventListener('click', function (e) {
            const button = e.target.closest('[data-action]');
            if (!button || button.disabled) return;
            if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) return;
            const fd = new FormData();
            fd.append('csrfmiddlewaretoken', csrfToken());
            fd.append('action', button.dataset.action);
            if (button.dataset.action === 'steps') fd.append('n', controls.querySelector('[name="n"]').value);
            if (button.dataset.action === 'distance') fd.append('dx', controls.querySelector('[name="dx"]').value);
            if (button.dataset.action === 'to_end' || button.dataset.action === 'stop') {
                fd.append('result_name', controls.querySelector('[name="result_name"]').value);
            }
            send(fd);
        });

        document.querySelectorAll('[data-toggle-editor]').forEach(function (btn) {
            btn.addEventListener('click', function () { toggleEditor(); });
        });

        const editorForm = document.getElementById('it-editor-form');
        if (editorForm) {
            editorForm.addEventListener('submit', function (e) {
                e.preventDefault();
                const fd = new FormData(editorForm);
                fd.append('action', 'configure');
                closeEditorOnSuccess = true;
                send(fd);
            });
        }

        // → — один шаг (если фокус не в поле ввода).
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'ArrowRight' || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
            const tag = (document.activeElement && document.activeElement.tagName) || '';
            if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
            const stepButton = controls.querySelector('[data-action="step"]');
            if (stepButton && !stepButton.disabled && !busy) {
                e.preventDefault();
                stepButton.click();
            }
        });
    }

    // Фоновый «Досчитать до конца»: опрос статуса → страница итога (или перезагрузка с ошибкой).
    function pollFinishing() {
        const box = document.getElementById('it-finishing');
        if (!box) return;
        const url = box.dataset.statusUrl;
        const timer = setInterval(function () {
            fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    if (data.redirect) {
                        clearInterval(timer);
                        window.location.href = data.redirect;
                    } else if (data.status !== 'finishing') {
                        clearInterval(timer);
                        window.location.reload();
                    }
                })
                .catch(function () {});
        }, 2000);
    }

    function init() {
        initEditors(document);
        initNewPage();
        initSessionPage();
        pollFinishing();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
