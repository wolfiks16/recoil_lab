/* JS формы создания расчёта (templates/recoil_app/index.html).

   Подключается в конце body, после рендера контента.
   URL для AJAX-сохранения тормоза в каталог берётся из data-атрибута
   на форме `#calculation-form` (data-catalog-save-url).
*/

/* ============================================================================
   FORMSET: добавление/удаление/копирование тормозов + sync со списком слева
   ============================================================================ */
(function () {
    const formsContainer = document.getElementById("brake-forms");
    const addBtn = document.getElementById("add-brake-btn");
    const totalFormsInput = document.getElementById("id_brakes-TOTAL_FORMS");
    const emptyFormTemplate = document.getElementById("empty-brake-form");
    const brakeList = document.getElementById("brake-list");
    const brakeCount = document.getElementById("brake-count");
    const emptyState = document.getElementById("brake-empty-state");
    const calcForm = document.getElementById("calculation-form");
    const catalogSaveUrl = calcForm ? (calcForm.dataset.catalogSaveUrl || "") : "";

    if (!formsContainer || !addBtn || !totalFormsInput || !emptyFormTemplate) return;

    let activeIndex = 0;

    function getBrakeName(card, index) {
        const nameInput = card.querySelector('input[name$="-name"]');
        const value = nameInput ? (nameInput.value || "").trim() : "";
        return value || `Тормоз ${index + 1}`;
    }

    function getBrakeType(card) {
        const select = card.querySelector('select[name$="-model_type"]');
        return select ? select.value : "parametric";
    }

    function hasErrors(card) {
        return card.querySelectorAll(".field-error, .notice").length > 0
            && Array.from(card.querySelectorAll(".notice")).some(n => n.textContent.trim());
    }

    /* Срез 6a: статус заполненности тормоза для индикатора в sidebar */
    const PARAM_FIELD_NAMES = [
        "gamma", "delta", "n", "xm", "ym", "dh1", "dh2", "dm",
        "mu", "bz", "lya", "wn0",
    ];

    function getBrakeStatus(card) {
        if (hasErrors(card)) return "error";

        const modelType = getBrakeType(card);

        if (modelType === "curve") {
            const fileInput = card.querySelector('input[name$="-force_curve_file"]');
            const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;

            const catalogIdInput = card.querySelector('input[name$="-catalog_source_id"]');
            const hasCatalog = catalogIdInput && (catalogIdInput.value || "").trim() !== "";

            const sourceBrakeInput = card.querySelector('input[name$="-curve_source_brake_id"]');
            const hasSource = sourceBrakeInput && (sourceBrakeInput.value || "").trim() !== "";

            return (hasFile || hasCatalog || hasSource) ? "complete" : "partial";
        }

        let filled = 0;
        PARAM_FIELD_NAMES.forEach(p => {
            const el = card.querySelector('[name$="-' + p + '"]');
            if (el && (el.value || "").trim() !== "") filled += 1;
        });
        if (filled === PARAM_FIELD_NAMES.length) return "complete";
        if (filled === 0) return "empty";
        return "partial";
    }

    const STATUS_ICONS = { complete: "✓", partial: "⚠", empty: "○", error: "✗" };
    const STATUS_TITLES = {
        complete: "Все параметры заполнены",
        partial: "Заполнены не все параметры",
        empty: "Параметры не заполнены",
        error: "Есть ошибки валидации",
    };

    function rebuildBrakeList() {
        const items = formsContainer.querySelectorAll(".brake-form-item");
        brakeList.innerHTML = "";

        items.forEach((card, index) => {
            const name = getBrakeName(card, index);
            const type = getBrakeType(card);
            const status = getBrakeStatus(card);
            const errored = (status === "error");

            const li = document.createElement("div");
            li.className = "rb-cad-brake-item";
            if (index === activeIndex) li.classList.add("is-active");
            if (errored) li.classList.add("has-errors");
            li.dataset.brakeIndex = String(index);

            li.innerHTML = `
                <div class="rb-cad-brake-item-icon">${index + 1}</div>
                <div class="rb-cad-brake-item-name" title="${name}">${name}</div>
                <span class="rb-cad-brake-item-status is-${status}" title="${STATUS_TITLES[status]}">${STATUS_ICONS[status]}</span>
                <div class="rb-cad-brake-item-badge">${type === "curve" ? "F(v)" : "пар"}</div>
            `;

            li.addEventListener("click", () => {
                setActiveBrake(index);
            });

            brakeList.appendChild(li);
        });

        brakeCount.textContent = items.length;
        updateEmptyState();
    }

    function updateEmptyState() {
        const items = formsContainer.querySelectorAll(".brake-form-item");
        if (items.length === 0) {
            emptyState.style.display = "";
        } else {
            emptyState.style.display = "none";
        }
    }

    function setActiveBrake(index) {
        const items = formsContainer.querySelectorAll(".brake-form-item");
        if (items.length === 0) {
            activeIndex = 0;
            updateEmptyState();
            return;
        }

        if (index < 0) index = 0;
        if (index >= items.length) index = items.length - 1;

        activeIndex = index;

        items.forEach((card, i) => {
            card.classList.toggle("is-active", i === activeIndex);
        });

        rebuildBrakeList();
        syncBrakeHeader();
    }

    function syncBrakeHeader() {
        const items = formsContainer.querySelectorAll(".brake-form-item");
        items.forEach((card, index) => {
            const name = getBrakeName(card, index);
            const display = card.querySelector("[data-brake-display-name]");
            if (display) display.textContent = name;
            const prefix = card.querySelector(".rb-cad-brake-head-prefix");
            if (prefix) prefix.textContent = `Тормоз ${index + 1}`;
        });
    }

    /* Реиндексация formset (нужна для add/delete) */
    function reindexForms() {
        const items = formsContainer.querySelectorAll(".brake-form-item");
        items.forEach((item, index) => {
            item.dataset.brakeIndex = String(index);
            item.querySelectorAll("input, select, textarea, label").forEach((el) => {
                ["name", "id", "for"].forEach((attr) => {
                    if (el.hasAttribute && el.hasAttribute(attr)) {
                        const value = el.getAttribute(attr);
                        if (value) {
                            el.setAttribute(attr, value.replace(/brakes-\d+-/g, `brakes-${index}-`));
                        }
                    }
                });
            });
        });
        totalFormsInput.value = items.length;
    }

    /* === Превью кривой F(v) === */
    function hideCurvePreview(card) {
        const previewBlock = card.querySelector(".curve-preview-block");
        const previewError = card.querySelector(".curve-preview-error");
        const previewPlot = card.querySelector(".curve-preview-plot");
        if (previewBlock) previewBlock.style.display = "none";
        if (previewError) { previewError.style.display = "none"; previewError.textContent = ""; }
        if (previewPlot) previewPlot.innerHTML = "";
    }

    function showCurvePreviewError(card, message) {
        const previewBlock = card.querySelector(".curve-preview-block");
        const previewError = card.querySelector(".curve-preview-error");
        const previewPlot = card.querySelector(".curve-preview-plot");
        if (previewBlock) previewBlock.style.display = "none";
        if (previewPlot) previewPlot.innerHTML = "";
        if (previewError) { previewError.textContent = message; previewError.style.display = ""; }
    }

    function renderCurvePreview(card, points) {
        const previewBlock = card.querySelector(".curve-preview-block");
        const previewError = card.querySelector(".curve-preview-error");
        const previewPlot = card.querySelector(".curve-preview-plot");
        if (!previewBlock || !previewPlot) return;
        if (previewError) { previewError.style.display = "none"; previewError.textContent = ""; }

        const velocities = points.map((p) => p.velocity);
        const forces = points.map((p) => p.force);

        previewBlock.style.display = "";

        Plotly.newPlot(previewPlot, [{
            x: velocities, y: forces, type: "scatter", mode: "lines+markers",
            line: { color: "#3D73EB", width: 2.5 },
            marker: { color: "#B44D7A", size: 6 },
            name: "F(v)",
        }], {
            margin: { l: 50, r: 20, t: 20, b: 50 },
            xaxis: { title: "v, м/с" },
            yaxis: { title: "F, Н" },
            showlegend: false,
        }, { responsive: true, displayModeBar: false });
    }

    function isEmptyCell(v) {
        return v === null || v === undefined || (typeof v === "string" && v.trim() === "");
    }
    function coerceNumber(v) {
        if (typeof v === "number") return v;
        if (typeof v === "string") {
            const n = v.trim().replace(",", ".");
            if (!n) return null;
            const p = Number(n);
            return Number.isFinite(p) ? p : null;
        }
        return null;
    }
    function parseCurveRows(rows) {
        const points = [];
        let headerSkipped = false;
        rows.forEach((row, idx) => {
            const rowNo = idx + 1;
            const velocityRaw = Array.isArray(row) && row.length > 0 ? row[0] : null;
            const forceRaw = Array.isArray(row) && row.length > 1 ? row[1] : null;
            if (isEmptyCell(velocityRaw) && isEmptyCell(forceRaw)) return;
            if (isEmptyCell(velocityRaw) || isEmptyCell(forceRaw)) {
                throw new Error(`Строка ${rowNo}: должны быть заполнены и v, и F.`);
            }
            const velocity = coerceNumber(velocityRaw);
            const force = coerceNumber(forceRaw);
            if (velocity === null || force === null) {
                if (!headerSkipped && points.length === 0) { headerSkipped = true; return; }
                throw new Error(`Строка ${rowNo}: значения должны быть числами.`);
            }
            if (velocity < 0) throw new Error(`Строка ${rowNo}: v < 0.`);
            if (force < 0) throw new Error(`Строка ${rowNo}: F < 0.`);
            points.push({ velocity, force });
        });
        if (points.length < 2) throw new Error("Минимум 2 точки.");
        for (let i = 1; i < points.length; i += 1) {
            if (points[i].velocity <= points[i - 1].velocity) {
                throw new Error("Скорости должны быть строго возрастающими.");
            }
        }
        return points;
    }
    function parseCurveFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = function (event) {
                try {
                    const data = event.target.result;
                    const workbook = XLSX.read(data, { type: "array" });
                    const firstSheetName = workbook.SheetNames[0];
                    if (!firstSheetName) { reject(new Error("Excel пуст.")); return; }
                    const sheet = workbook.Sheets[firstSheetName];
                    const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true });
                    resolve(parseCurveRows(rows));
                } catch (err) { reject(err); }
            };
            reader.onerror = function () { reject(new Error("Ошибка чтения файла.")); };
            reader.readAsArrayBuffer(file);
        });
    }

    function updateBrakeMode(card) {
        if (!card) return;
        const select = card.querySelector('select[name$="-model_type"]');
        const parametricBlock = card.querySelector(".brake-parametric-fields");
        const curveBlock = card.querySelector(".brake-curve-fields");
        if (!select || !parametricBlock || !curveBlock) return;
        const isCurve = select.value === "curve";
        parametricBlock.style.display = isCurve ? "none" : "";
        curveBlock.style.display = isCurve ? "" : "none";
        if (!isCurve) hideCurvePreview(card);

        rebuildBrakeList();
    }

    function fillNewCardFromSource(sourceCard, newCard) {
        const sourceInputs = sourceCard.querySelectorAll("input, select, textarea");
        const newInputs = newCard.querySelectorAll("input, select, textarea");
        sourceInputs.forEach((src, index) => {
            const dst = newInputs[index];
            if (!dst) return;
            if (src.type === "file") return;
            if (src.type === "checkbox" || src.type === "radio") dst.checked = src.checked;
            else dst.value = src.value;
        });
        hideCurvePreview(newCard);
        updateBrakeMode(newCard);
    }

    function createBrakeForm() {
        const formIndex = parseInt(totalFormsInput.value, 10);
        let templateHtml = emptyFormTemplate.innerHTML
            .replace(/__prefix__/g, formIndex)
            .replace(/__number__/g, formIndex + 1);
        const wrapper = document.createElement("div");
        wrapper.innerHTML = templateHtml.trim();
        const newForm = wrapper.firstElementChild;
        formsContainer.appendChild(newForm);
        totalFormsInput.value = formIndex + 1;
        bindCardActions(newForm);
        updateBrakeMode(newForm);
        rebuildBrakeList();
        syncBrakeHeader();
        return newForm;
    }

    function bindCardActions(card) {
        const deleteBtn = card.querySelector(".delete-brake-btn");
        const copyBtn = card.querySelector(".copy-brake-btn");
        const select = card.querySelector('select[name$="-model_type"]');
        const fileInput = card.querySelector('input[name$="-force_curve_file"]');
        const nameInput = card.querySelector('input[name$="-name"]');
        const saveCatalogBtn = card.querySelector(".rb-cad-save-to-catalog-btn");

        if (deleteBtn) {
            deleteBtn.addEventListener("click", function () {
                const items = formsContainer.querySelectorAll(".brake-form-item");
                if (items.length <= 1) {
                    showToast("Должен остаться хотя бы один тормоз", "error");
                    return;
                }
                const wasIndex = parseInt(card.dataset.brakeIndex || "0", 10);
                card.remove();
                reindexForms();

                const newCount = formsContainer.querySelectorAll(".brake-form-item").length;
                let newActive = wasIndex;
                if (newActive >= newCount) newActive = newCount - 1;
                if (newActive < 0) newActive = 0;
                setActiveBrake(newActive);
            });
        }

        if (copyBtn) {
            copyBtn.addEventListener("click", function () {
                const newCard = createBrakeForm();
                fillNewCardFromSource(card, newCard);
                const items = formsContainer.querySelectorAll(".brake-form-item");
                setActiveBrake(items.length - 1);
            });
        }

        if (select) {
            select.addEventListener("change", function () {
                updateBrakeMode(card);
            });
        }

        if (fileInput) {
            fileInput.addEventListener("change", async function () {
                if (!fileInput.files || fileInput.files.length === 0) {
                    hideCurvePreview(card);
                    return;
                }
                const file = fileInput.files[0];
                try {
                    const points = await parseCurveFile(file);
                    renderCurvePreview(card, points);
                } catch (err) {
                    showCurvePreviewError(card, err.message || "Ошибка построения предпросмотра.");
                }
            });
        }

        if (nameInput) {
            nameInput.addEventListener("input", function () {
                rebuildBrakeList();
                syncBrakeHeader();
            });
        }

        /* Срез 6a: любое изменение поля карточки → пересчёт статуса в sidebar */
        card.addEventListener("input", function () { rebuildBrakeList(); });
        card.addEventListener("change", function () { rebuildBrakeList(); });

        if (saveCatalogBtn) {
            saveCatalogBtn.addEventListener("click", function () {
                saveBrakeToCatalog(card);
            });
        }

        updateBrakeMode(card);
    }

    /* === AJAX: сохранить тормоз в каталог === */
    async function saveBrakeToCatalog(card) {
        if (!catalogSaveUrl) {
            showToast("Не настроен URL для сохранения", "error");
            return;
        }

        const data = new FormData();

        const csrf = document.querySelector("[name=csrfmiddlewaretoken]");
        if (csrf) data.append("csrfmiddlewaretoken", csrf.value);

        function getVal(name) {
            const el = card.querySelector('[name$="-' + name + '"]');
            return el ? (el.value || "").trim() : "";
        }
        function getFile(name) {
            const el = card.querySelector('input[name$="-' + name + '"][type="file"]');
            return el && el.files && el.files[0] ? el.files[0] : null;
        }

        const name = getVal("name");
        if (!name) {
            showToast("Заполните имя тормоза перед сохранением", "error");
            return;
        }

        data.append("name", name);
        data.append("model_type", getVal("model_type"));

        const modelType = getVal("model_type");
        if (modelType === "parametric") {
            ["gamma", "delta", "n", "xm", "ym", "dh1", "dh2", "dm",
             "mu", "bz", "lya", "wn0"].forEach(k => {
                data.append(k, getVal(k));
            });
        } else {
            const file = getFile("force_curve_file");
            if (file) {
                data.append("curve_file", file);
            } else {
                const catSrc = getVal("catalog_source_id");
                if (catSrc) data.append("catalog_source_id", catSrc);
            }
        }

        try {
            const response = await fetch(catalogSaveUrl, {
                method: "POST",
                body: data,
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const result = await response.json();
            if (result.ok) {
                showToast(`Тормоз «${result.name}» добавлен в каталог`, "success");
            } else {
                showToast(result.error || "Ошибка сохранения", "error");
            }
        } catch (err) {
            showToast("Сетевая ошибка: " + err.message, "error");
        }
    }

    function showToast(message, kind) {
        const toast = document.getElementById("rb-toast");
        if (!toast) return;
        toast.textContent = message;
        toast.classList.remove("is-success", "is-error");
        if (kind === "success") toast.classList.add("is-success");
        if (kind === "error") toast.classList.add("is-error");
        toast.classList.add("is-visible");
        setTimeout(() => { toast.classList.remove("is-visible"); }, 3500);
    }

    function focusFirstErrorForm() {
        const items = formsContainer.querySelectorAll(".brake-form-item");
        for (let i = 0; i < items.length; i += 1) {
            if (hasErrors(items[i])) {
                setActiveBrake(i);
                return;
            }
        }
    }

    addBtn.addEventListener("click", function () {
        const newCard = createBrakeForm();
        const items = formsContainer.querySelectorAll(".brake-form-item");
        setActiveBrake(items.length - 1);
    });

    formsContainer.querySelectorAll(".brake-form-item").forEach(bindCardActions);
    setActiveBrake(0);
    focusFirstErrorForm();

    /* Глобальный экспорт для каталог-скрипта (Срез 3b) */
    window.__rbRebuildBrakeList = rebuildBrakeList;
    window.__rbSyncBrakeHeader = syncBrakeHeader;
})();


/* ============================================================================
   Срез 3b: каталог тормозов — переключатель источника параметров
   ============================================================================ */
(function () {
    "use strict";

    function readCatalog() {
        const node = document.getElementById("rb-catalog-data");
        if (!node) return [];
        try { return JSON.parse(node.textContent); } catch (e) { return []; }
    }

    const CATALOG = readCatalog();
    const CATALOG_BY_ID = {};
    CATALOG.forEach(item => { CATALOG_BY_ID[String(item.id)] = item; });

    function findFields(card) {
        const out = {};
        const FIELD_NAMES = [
            "name", "model_type",
            "gamma", "delta", "n", "xm", "ym", "dh1", "dh2", "dm",
            "mu", "bz", "lya", "wn0",
            "catalog_source_id", "force_curve_file",
        ];
        FIELD_NAMES.forEach(fname => {
            const candidates = card.querySelectorAll('[name$="-' + fname + '"]');
            if (candidates.length) out[fname] = candidates[0];
        });
        return out;
    }

    function setField(field, value) {
        if (!field) return;
        field.value = (value === null || value === undefined) ? "" : value;
        field.classList.add("rb-from-catalog");
    }

    function clearCatalogHighlight(card) {
        card.querySelectorAll(".rb-from-catalog").forEach(el => el.classList.remove("rb-from-catalog"));
    }

    function applyCatalogItem(card, item) {
        const fields = findFields(card);
        const params = item.params || {};

        if (fields.name) setField(fields.name, item.name);
        if (fields.model_type) {
            fields.model_type.value = item.model_type;
            fields.model_type.dispatchEvent(new Event("change", { bubbles: true }));
        }
        if (fields.catalog_source_id) fields.catalog_source_id.value = String(item.id);

        ["gamma", "delta", "n", "xm", "ym", "dh1", "dh2", "dm",
         "mu", "bz", "lya", "wn0"].forEach(key => setField(fields[key], params[key]));

        const picker = card.querySelector(".rb-catalog-picker");
        const info = picker ? picker.querySelector(".rb-catalog-picker-info") : null;
        if (info) {
            const parts = [item.summary];
            if (item.description) parts.push(item.description);
            if (item.is_curve) parts.push("Файл F(v) будет взят из каталога");
            info.textContent = parts.join(" — ");
        }

        if (window.__rbRebuildBrakeList) window.__rbRebuildBrakeList();
        if (window.__rbSyncBrakeHeader) window.__rbSyncBrakeHeader();
    }

    function clearCatalogSource(card) {
        const fields = findFields(card);
        if (fields.catalog_source_id) fields.catalog_source_id.value = "";
        clearCatalogHighlight(card);
        const picker = card.querySelector(".rb-catalog-picker");
        if (picker) {
            const info = picker.querySelector(".rb-catalog-picker-info");
            if (info) info.textContent = "";
            const sel = picker.querySelector(".rb-catalog-select");
            if (sel) sel.value = "";
        }
    }

    function setMode(card, mode) {
        const tabs = card.querySelectorAll(".rb-source-tab");
        tabs.forEach(t => t.classList.toggle("is-active", t.dataset.sourceMode === mode));
        const picker = card.querySelector(".rb-catalog-picker");
        if (picker) picker.hidden = (mode !== "catalog");
        if (mode === "manual") clearCatalogSource(card);
    }

    document.addEventListener("click", function (e) {
        const tab = e.target.closest(".rb-source-tab");
        if (!tab || tab.disabled) return;
        const card = tab.closest(".brake-form-item");
        if (!card) return;
        e.preventDefault();
        setMode(card, tab.dataset.sourceMode);
    });

    document.addEventListener("change", function (e) {
        const sel = e.target.closest(".rb-catalog-select");
        if (!sel) return;
        const card = sel.closest(".brake-form-item");
        if (!card) return;
        const value = sel.value;
        if (!value) { clearCatalogSource(card); return; }
        const item = CATALOG_BY_ID[value];
        if (item) applyCatalogItem(card, item);
    });
})();


/* ============================================================================
   Submit-кнопка в hero + Loader при сабмите
   ============================================================================ */
(function () {
    const form = document.getElementById("calculation-form");
    const overlay = document.getElementById("calculation-overlay");
    const submitBtn = document.getElementById("submit-calc-btn");

    if (!form) return;

    if (submitBtn) {
        submitBtn.addEventListener("click", function (e) {
            e.preventDefault();
            if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
            } else {
                form.submit();
            }
        });
    }

    form.addEventListener("submit", function () {
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = "Идёт расчёт...";
        }
        if (overlay) overlay.classList.add("active");
        form.classList.add("is-submitting");
    });
})();
