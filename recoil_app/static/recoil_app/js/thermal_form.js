// Тепловая форма: prefill из brake-параметров и условные блоки 9-узл./упрощ.
(function () {
    "use strict";

    const metaScript = document.getElementById("brake-meta-data");
    if (!metaScript) return;

    let brakeMeta = [];
    try {
        brakeMeta = JSON.parse(metaScript.textContent);
    } catch (e) {
        console.error("brake-meta-data parse error", e);
        return;
    }

    // ----- Условные блоки по preset -----
    const presetSelect = document.querySelector('select[name="network_preset"]');

    function applyPresetVisibility() {
        const preset = presetSelect ? presetSelect.value : "nine_node";
        const conds = document.querySelectorAll(".tf-conditional[data-preset-only]");
        conds.forEach((el) => {
            const need = el.dataset.presetOnly;
            el.style.display = need === preset ? "" : "none";
        });
    }
    if (presetSelect) {
        presetSelect.addEventListener("change", applyPresetVisibility);
    }
    applyPresetVisibility();

    // ----- Prefill кнопки -----
    function field(formIndex, name) {
        return document.querySelector(
            `[name="thermal_brakes-${formIndex}-${name}"]`,
        );
    }

    function setIfEmpty(input, value) {
        if (!input) return;
        if (value === undefined || value === null || isNaN(value)) return;
        input.value = (typeof value === "number") ? +value.toPrecision(6) : value;
    }

    function prefillBrake(formIndex) {
        const meta = brakeMeta[formIndex];
        if (!meta || !meta.is_parametric) return;
        const p = meta.params || {};
        // L_active = n * xm
        if (p.n != null && p.xm != null) {
            setIfEmpty(field(formIndex, "L_active"), p.n * p.xm);
            setIfEmpty(field(formIndex, "L_pole"), p.n * p.xm);
            setIfEmpty(field(formIndex, "L_magnet"), p.n * p.xm);
        }
        // delta_gap_working ≈ ym (рабочий магнитный зазор)
        if (p.ym != null) {
            setIfEmpty(field(formIndex, "delta_gap_working"), p.ym);
        }
        // Толщина шины = delta (из MagneticParams)
        // Без D_outer не можем поставить D_inner, но если оба пустые — пользователь
        // увидит и поправит. Это намеренно — не угадываем D_outer.
    }

    document.querySelectorAll(".tf-prefill-btn").forEach((btn) => {
        const idx = Number(btn.dataset.prefillTarget);
        if (Number.isNaN(idx)) return;
        btn.addEventListener("click", () => prefillBrake(idx));
    });
})();
