/* RecoilLab Shell v2
   Декларативный shell: топбар + rail.

   Использование в шаблоне:
     <div id="rb-shell-mount"
          data-active="result"             // dashboard | workspace | result | optimize | compare | catalog
          data-crumb="H155-v4-optimal"     // что показывать в breadcrumb после "Проекты / RecoilLab /"
          data-index-url="{% url 'index' %}"
          data-compare-url="{% url 'compare' %}"
          data-user-initials="ИК">
     </div>

   Здесь же иконки для рейла.  shell.js монтирует HTML и помечает активный пункт.
*/

(function () {
    'use strict';

    const RAIL_ITEMS = [
        {
            key: 'dashboard',
            title: 'Дашборд',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>'
        },
        {
            key: 'workspace',
            title: 'Расчёт',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>'
        },
        {
            key: 'result',
            title: 'Результаты',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>'
        },
        {
            key: 'optimize',
            title: 'Оптимизация',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>'
        },
        {
            key: 'compare',
            title: 'Сравнение',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5"/><path d="M21 3 14 10"/><path d="M8 21H3v-5"/><path d="m3 21 7-7"/></svg>'
        },
        {
            key: 'catalog',
            title: 'Каталог',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/><path d="M15 3v18"/></svg>'
        }
    ];

    const LOGO_SVG = `
        <svg viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg" aria-label="RecoilLab">
            <defs>
                <linearGradient id="rb-logo-grad" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0" stop-color="#3D73EB"/>
                    <stop offset="1" stop-color="#B44D7A"/>
                </linearGradient>
            </defs>
            <rect width="36" height="36" rx="6" fill="#0F1724"/>
            <path d="M5 26 Q 12 8, 18 14 T 31 26"
                  fill="none" stroke="url(#rb-logo-grad)" stroke-width="2.4" stroke-linecap="round"/>
            <circle cx="18" cy="14" r="2.2" fill="#B44D7A"/>
            <line x1="5" y1="28" x2="31" y2="28" stroke="#3D73EB" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>
        </svg>`;

    function buildShell(mountEl) {
        const active        = mountEl.dataset.active || 'workspace';
        const crumb         = mountEl.dataset.crumb || '';
        const indexUrl      = mountEl.dataset.indexUrl || '/';
        const dashboardUrl  = mountEl.dataset.dashboardUrl || indexUrl;
        const resultsUrl    = mountEl.dataset.resultsUrl || '#';
        const compareUrl    = mountEl.dataset.compareUrl || '/compare/';
        const catalogUrl    = mountEl.dataset.catalogUrl || '#';
        const userInit      = mountEl.dataset.userInitials || 'ИК';

        // --- Auth state -----
        const loginUrl       = mountEl.dataset.loginUrl    || '/login/';
        const registerUrl    = mountEl.dataset.registerUrl || '/register/';
        const logoutUrl      = mountEl.dataset.logoutUrl   || '/logout/';
        const usersUrl       = mountEl.dataset.usersUrl    || '/users/';
        const profileUrl     = mountEl.dataset.profileUrl  || '/profile/';
        const isAuthed       = mountEl.dataset.userAuthenticated === '1';
        const userName       = mountEl.dataset.userName     || '';
        const userRole       = mountEl.dataset.userRole     || '';
        const userRoleLabel  = mountEl.dataset.userRoleLabel|| '';
        const userAvatar     = mountEl.dataset.userAvatarEmoji || '';

        const railUrls = {
            dashboard: dashboardUrl,
            workspace: indexUrl,
            result:    resultsUrl,
            optimize:  '#',
            compare:   compareUrl,
            catalog:   catalogUrl
        };

        // Auth chip (правая часть топбара).
        let authChip;
        if (isAuthed) {
            const isAdmin = userRole === 'admin';
            const roleBadge = userRoleLabel
                ? `<span class="rb-auth-role rb-auth-role-${escapeHtml(userRole)}">${escapeHtml(userRoleLabel)}</span>`
                : '';
            const usersLink = isAdmin
                ? `<a href="${usersUrl}" title="Управление пользователями">Пользователи</a><span style="opacity:.4">·</span>`
                : '';
            authChip = `
                <div class="rb-auth-chip">
                    <span><b>${escapeHtml(userName)}</b></span>
                    ${roleBadge}
                    ${usersLink}
                    <form method="post" action="${logoutUrl}" style="display:inline; margin:0; padding:0;">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${getCsrf()}">
                        <button type="submit" style="background:none;border:none;color:var(--rb-accent,#3D73EB);
                                cursor:pointer;font-size:12px;padding:0;">Выйти</button>
                    </form>
                </div>`;
        } else {
            authChip = `
                <div class="rb-auth-chip">
                    <a href="${loginUrl}">Войти</a>
                    <span style="opacity:.4">·</span>
                    <a href="${registerUrl}">Регистрация</a>
                </div>`;
        }

        // Аватар-кружок справа: если залогинен и есть эмодзи — кликабельная мордочка
        // ведёт на /profile/. Для гостей — статичный кружок с прочерком.
        let avatarBlock;
        if (isAuthed) {
            const avatarChar = userAvatar || escapeHtml(userInit);
            avatarBlock = `
                <a class="rb-user rb-user-link" href="${profileUrl}" title="Профиль">
                    <div class="rb-avatar rb-avatar-emoji">${escapeHtml(avatarChar)}</div>
                </a>`;
        } else {
            avatarBlock = `
                <div class="rb-user">
                    <div class="rb-avatar">${escapeHtml(userInit)}</div>
                </div>`;
        }

        // Topbar HTML
        const topbar = `
            <header class="rb-topbar">
                <div class="rb-logo">${LOGO_SVG}</div>
                <div class="rb-logo-text">Recoil<span class="dot">·</span>Lab</div>
                <nav class="rb-breadcrumb">
                    <span>Проекты</span>
                    <span class="sep">/</span>
                    <a href="${dashboardUrl}">RecoilLab</a>
                    ${crumb ? `<span class="sep">/</span><span class="current">${escapeHtml(crumb)}</span>` : ''}
                </nav>
                <div class="rb-status-pill">Solver v2 · Ready</div>
                <div class="rb-topbar-spacer"></div>
                ${authChip}
                ${avatarBlock}
            </header>`;

        // Rail HTML. Нативный `title` не используем — рендерим красивый CSS-tooltip
        // через `data-tip`; справа от иконки появляется тёмная плашка с названием.
        const railItems = RAIL_ITEMS.map(item => {
            const url = railUrls[item.key] || '#';
            const cls = active === item.key ? 'rb-rail-item active' : 'rb-rail-item';
            const tip = url === '#'
                ? `${item.title} — в разработке`
                : item.title;
            const link = url === '#'
                ? `<span class="${cls}" data-tip="${escapeHtml(tip)}" data-disabled="1">${item.icon}</span>`
                : `<a class="${cls}" href="${url}" data-tip="${escapeHtml(tip)}">${item.icon}</a>`;
            return link;
        }).join('');

        const rail = `<aside class="rb-rail">${railItems}</aside>`;

        // Вставляем топбар и рейл как СИБЛИНГИ перед mount-элементом.
        // Так они становятся прямыми детьми .rb-shell и корректно встают в grid.
        const parent = mountEl.parentNode;
        if (!parent) {
            mountEl.innerHTML = topbar + rail;
            return;
        }
        const fragment = document.createRange().createContextualFragment(topbar + rail);
        parent.insertBefore(fragment, mountEl);
        // Скрываем сам mount, он больше не нужен
        mountEl.style.display = 'none';
    }

    function getCsrf() {
        // Стандартный Django CSRF cookie (если CsrfViewMiddleware включён).
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function init() {
        const mount = document.getElementById('rb-shell-mount');
        if (mount) buildShell(mount);

        // Disabled rail items: подсказка при клике
        document.querySelectorAll('.rb-rail-item[data-disabled="1"]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                showToast('Раздел в разработке — появится в следующих версиях');
            });
        });
    }

    function showToast(text) {
        let toast = document.getElementById('rb-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'rb-toast';
            toast.style.cssText = `
                position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
                background: #0F1724; color: white; padding: 12px 18px; border-radius: 8px;
                font-family: Manrope, sans-serif; font-size: 13px; font-weight: 500;
                box-shadow: 0 8px 24px rgba(0,0,0,0.2); z-index: 9999;
                opacity: 0; transition: opacity .25s;
            `;
            document.body.appendChild(toast);
        }
        toast.textContent = text;
        toast.style.opacity = '1';
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => { toast.style.opacity = '0'; }, 2500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
