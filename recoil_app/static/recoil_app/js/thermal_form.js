// Тепловая форма: выбор модели, калькулятор G = h·A, подстановка размеров тормоза,
// условные блоки 9-узловой / упрощённой сети.
(function () {
    "use strict";

    // ----- Смена тепловой модели (перезагрузка формы с ?preset=) -----
    document.querySelectorAll('input[name="network_preset_switch"]').forEach((radio) => {
        radio.addEventListener("change", (e) => {
            const url = new URL(window.location.href);
            url.searchParams.set("preset", e.target.dataset.presetValue);
            window.location.href = url.toString();
        });
    });

    // ----- Калькулятор G = h·A (общая всплывашка для всех G-полей) -----
    (function () {
        const popup = document.getElementById("tf-calc-popup");
        if (!popup) return;
        const fldH = document.getElementById("tf-calc-h");
        const fldA = document.getElementById("tf-calc-A");
        const fldG = document.getElementById("tf-calc-G");
        let targetInputId = null;
        let opener = null;

        function recalc() {
            const h = parseFloat(fldH.value) || 0;
            const A = parseFloat(fldA.value) || 0;
            fldG.textContent = (h * A).toFixed(3);
        }
        fldH.addEventListener("input", recalc);
        fldA.addEventListener("input", recalc);

        function openCalc(targetId, anchorEl) {
            targetInputId = targetId;
            opener = anchorEl;
            const rect = anchorEl.getBoundingClientRect();
            popup.style.position = "fixed";
            popup.style.top = (rect.bottom + 6) + "px";
            popup.style.left = Math.max(8, rect.right - 280) + "px";
            popup.style.right = "auto";
            popup.hidden = false;
            popup.classList.add("open");
            fldH.value = "";
            fldA.value = "";
            fldG.textContent = "0.000";
            setTimeout(() => fldH.focus(), 50);
        }
        function closeCalc() {
            popup.hidden = true;
            popup.classList.remove("open");
            targetInputId = null;
            if (opener) opener.focus();
            opener = null;
        }

        document.querySelectorAll(".tf-calc-btn").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                openCalc(btn.dataset.calcTarget, btn);
            });
        });

        document.getElementById("tf-calc-cancel").addEventListener("click", closeCalc);
        document.getElementById("tf-calc-apply").addEventListener("click", () => {
            if (!targetInputId) { closeCalc(); return; }
            const h = parseFloat(fldH.value) || 0;
            const A = parseFloat(fldA.value) || 0;
            const targetInput = document.getElementById(targetInputId);
            if (targetInput) {
                targetInput.value = (h * A).toFixed(3);
                targetInput.dataset.calcH = h;
                targetInput.dataset.calcA = A;
                targetInput.dispatchEvent(new Event("input", { bubbles: true }));
            }
            closeCalc();
        });
        popup.addEventListener("keydown", (e) => {
            if (e.key === "Escape") closeCalc();
        });
        document.addEventListener("click", (e) => {
            if (popup.hidden) return;
            if (popup.contains(e.target)) return;
            if (e.target.classList.contains("tf-calc-btn")) return;
            closeCalc();
        });
    })();

    // ----- Подстановка размеров из параметров тормоза (9-узловая / 1 узел) -----
    const metaScript = document.getElementById("brake-meta-data");
    if (!metaScript) return;

    let brakeMeta = [];
    try {
        brakeMeta = JSON.parse(metaScript.textContent);
    } catch (e) {
        console.error("brake-meta-data parse error", e);
        return;
    }

    // Условные блоки по preset (select в форме — у legacy-моделей)
    const presetSelect = document.querySelector('select[name="network_preset"]');

    function applyPresetVisibility() {
        const preset = presetSelect ? presetSelect.value : "nine_node";
        document.querySelectorAll(".tf-conditional[data-preset-only]").forEach((el) => {
            el.style.display = el.dataset.presetOnly === preset ? "" : "none";
        });
    }
    if (presetSelect) {
        presetSelect.addEventListener("change", applyPresetVisibility);
        applyPresetVisibility();
    }

    function field(formIndex, name) {
        return document.querySelector(`[name="thermal_brakes-${formIndex}-${name}"]`);
    }

    function setValue(input, value) {
        if (!input) return;
        if (value === undefined || value === null || isNaN(value)) return;
        input.value = (typeof value === "number") ? +value.toPrecision(6) : value;
    }

    function prefillBrake(formIndex) {
        const meta = brakeMeta[formIndex];
        if (!meta || !meta.is_parametric) return;
        const p = meta.params || {};
        // Активная длина = n·xm
        if (p.n != null && p.xm != null) {
            setValue(field(formIndex, "L_active"), p.n * p.xm);
            setValue(field(formIndex, "L_pole"), p.n * p.xm);
            setValue(field(formIndex, "L_magnet"), p.n * p.xm);
        }
        // Рабочий магнитный зазор ≈ ym
        if (p.ym != null) {
            setValue(field(formIndex, "delta_gap_working"), p.ym);
        }
        // D_outer не угадываем — пользователь увидит пустое поле и заполнит.
        if (window.RecoilLab && window.RecoilLab.toast) {
            window.RecoilLab.toast("Размеры подставлены из параметров тормоза «" + meta.display_name + "»");
        }
    }

    document.querySelectorAll(".tf-prefill-btn").forEach((btn) => {
        const idx = Number(btn.dataset.prefillTarget);
        if (Number.isNaN(idx)) return;
        btn.addEventListener("click", () => prefillBrake(idx));
    });
})();
