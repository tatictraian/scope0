// --- 05_controls.js ---
// Tool toggles (with category groups), audit trail, scope utilization bars

const TOOL_CATEGORIES = {
    read_tools: {
        label: 'Read Tools',
        tools: ['scanGitHubExposure', 'scanGoogleExposure',
                'listPullRequests', 'searchEmails', 'listCalendarEvents'],
    },
    write_tools: {
        label: 'Write Tools',
        tools: ['createIssue', 'sendEmail'],
    },
};

const COMING_SOON_TOOLS = ['scanSlackExposure', 'listSlackChannels'];

const TOOL_DISPLAY_NAMES = {
    scanGitHubExposure: 'Scan GitHub',
    scanGoogleExposure: 'Scan Google',
    scanSlackExposure: 'Scan Slack',
    listPullRequests: 'List PRs',
    searchEmails: 'Search Emails',
    listCalendarEvents: 'Calendar Events',
    listSlackChannels: 'Slack Channels',
    createIssue: 'Create Issue',
    sendEmail: 'Send Email',
};

// --- Load tool toggles from FGA ---
async function loadToolToggles() {
    const resp = await apiFetch('/api/tools');
    if (!resp || !resp.ok) return;
    const statuses = await resp.json();
    renderToggles(statuses);
}

function renderToggles(statuses) {
    const container = document.getElementById('toolToggles');
    if (!container) return;
    container.innerHTML = '';

    for (const [catKey, cat] of Object.entries(TOOL_CATEGORIES)) {
        const catTools = cat.tools.filter(function(t) { return t in statuses; });
        if (catTools.length === 0) continue;

        const allEnabled = catTools.every(function(t) { return statuses[t]; });

        const catDiv = document.createElement('div');
        catDiv.className = 'tool-category';
        catDiv.innerHTML = `
            <div class="tool-toggle category-toggle" id="cat-${escapeForHtml(catKey)}">
                <span class="tool-toggle-name" style="font-weight:bold;font-size:11px;text-transform:uppercase;letter-spacing:1px;">${escapeForHtml(cat.label)}</span>
                <label class="tool-toggle-switch">
                    <input type="checkbox" ${allEnabled ? 'checked' : ''} data-category="${escapeForHtml(catKey)}" />
                    <span class="tool-toggle-slider"></span>
                </label>
            </div>
        `;
        const catCheckbox = catDiv.querySelector('input');
        catCheckbox.addEventListener('change', function() {
            toggleCategory(catKey, this.checked, statuses);
        });
        container.appendChild(catDiv);

        // Individual tools in this category
        for (const name of catTools) {
            const enabled = statuses[name];
            const displayName = TOOL_DISPLAY_NAMES[name] || name;
            const div = document.createElement('div');
            div.className = 'tool-toggle';
            div.id = 'toggle-' + name;
            div.style.paddingLeft = '12px';
            div.innerHTML = `
                <span class="tool-toggle-name">${escapeForHtml(displayName)}</span>
                <label class="tool-toggle-switch">
                    <input type="checkbox" ${enabled ? 'checked' : ''} data-tool="${escapeForHtml(name)}" />
                    <span class="tool-toggle-slider"></span>
                </label>
            `;
            const checkbox = div.querySelector('input');
            checkbox.addEventListener('change', function() {
                toggleTool(name, this.checked);
            });
            container.appendChild(div);
        }
    }

    // Coming Soon section for unconfigured connections
    if (COMING_SOON_TOOLS.length > 0) {
        const csDiv = document.createElement('div');
        csDiv.className = 'coming-soon-section';
        csDiv.innerHTML = '<div style="margin-top:12px;padding:8px 0;border-top:1px solid rgba(0,255,0,0.08)">' +
            '<span style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(0,255,0,0.3)">Coming Soon</span></div>';
        COMING_SOON_TOOLS.forEach(function(toolName) {
            const name = TOOL_DISPLAY_NAMES[toolName] || toolName;
            const item = document.createElement('div');
            item.className = 'tool-toggle coming-soon';
            item.style.paddingLeft = '12px';
            item.style.opacity = '0.25';
            item.style.cursor = 'default';
            item.title = 'Slack integration coming soon';
            item.innerHTML = '<span class="tool-toggle-name">' + escapeForHtml(name) + '</span>' +
                '<span style="font-size:9px;color:rgba(0,255,0,0.2);letter-spacing:1px">SOON</span>';
            csDiv.appendChild(item);
        });
        container.appendChild(csDiv);
    }
}

async function toggleCategory(catKey, enabled, statuses) {
    const cat = TOOL_CATEGORIES[catKey];
    if (!cat) return;
    // Toggle all tools in category
    const promises = [];
    for (const toolName of cat.tools) {
        if (toolName in statuses) {
            promises.push(toggleTool(toolName, enabled));
            // Update individual checkboxes immediately
            updateToggle(toolName, enabled);
        }
    }
    await Promise.all(promises);
}

async function toggleTool(toolName, enabled) {
    const displayName = TOOL_DISPLAY_NAMES[toolName] || toolName;
    const resp = await apiFetch('/api/tools/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: toolName, enabled: enabled }),
    });
    if (!resp || !resp.ok) {
        showToast('Failed to toggle ' + displayName);
        loadToolToggles();
    } else {
        showToast(displayName + (enabled ? ' enabled' : ' disabled'));
    }
}

function updateToggle(toolName, enabled) {
    const container = document.getElementById('toggle-' + toolName);
    if (!container) return;
    const checkbox = container.querySelector('input');
    if (checkbox) checkbox.checked = enabled;
    // Glitch flash effect
    container.style.transition = 'background 0.3s';
    container.style.background = 'rgba(245,158,11,0.15)';
    setTimeout(function() { container.style.background = ''; }, 500);
}

// escapeForHtml defined in 03_exposure.js (loaded before this file)

// --- Audit trail ---
function addAuditEntry(tool, detail) {
    const trail = document.getElementById('auditTrail');
    if (!trail) return;
    const entry = document.createElement('div');
    const isSelf = typeof tool === 'string' && tool.startsWith('[SELF]');
    entry.className = 'audit-entry' + (isSelf ? ' self-restrict' : '');
    entry.innerHTML = `<span class="audit-time">${formatTime()}</span><span class="audit-tool">${escapeForHtml(tool)}</span>${detail ? ' - ' + escapeForHtml(detail) : ''}`;
    trail.insertBefore(entry, trail.firstChild);
}

// --- Scope info from scans (auto-populated) ---
let scopeInfoData = {};

function updateScopeInfo(service, scanResult) {
    if (!scanResult || !scanResult.scope_analysis) return;
    const sa = scanResult.scope_analysis;
    scopeInfoData[service] = {
        granted: (sa.granted || []).length,
        overprivilege: sa.overprivilege_pct || 0,
    };
    renderScopeInfo();
}

function renderScopeInfo() {
    const container = document.getElementById('scopeUtil');
    if (!container) return;
    let html = '';
    for (const [svc, info] of Object.entries(scopeInfoData)) {
        const label = svc === 'github' ? 'GitHub' : svc === 'google' ? 'Google' : svc;
        const used = Math.round(info.granted * (100 - info.overprivilege) / 100);
        html += renderScopeBar(label, 100 - info.overprivilege, used, info.granted);
    }
    container.innerHTML = html;
}

// --- Scope utilization from analyzeSession ---
function updateScopeUtilization(result) {
    const container = document.getElementById('scopeUtil');
    if (!container || !result) return;
    let html = '';

    if (result.github) {
        html += renderScopeBar('GitHub', result.github.utilization_pct,
            result.github.scopes_used.length, result.github.scopes_granted.length);
    }
    if (result.google) {
        html += renderScopeBar('Google', result.google.utilization_pct,
            result.google.scopes_used.length, result.google.scopes_granted.length);
    }
    if (result.exposure_delta) {
        const d = result.exposure_delta;
        if (d.initial !== d.current) {
            const change = parseInt(d.change) || 0;
            const cls = change > 0 ? 'positive' : 'negative';
            html += `<div style="margin-top: 8px; font-size: 12px;">
                Score: ${parseInt(d.initial) || 0} &rarr; ${parseInt(d.current) || 0}
                <span class="score-delta ${cls}">
                    (${change > 0 ? '+' : ''}${change})
                </span>
            </div>`;
        }
    }

    container.innerHTML = html;
}

function renderScopeBar(label, pct, used, total) {
    pct = parseInt(pct) || 0;
    used = parseInt(used) || 0;
    total = parseInt(total) || 0;
    return `
        <div class="scope-bar">
            <div class="scope-bar-label">
                <span>${escapeForHtml(label)}</span>
                <span>${used}/${total} scopes (${pct}%)</span>
            </div>
            <div class="scope-bar-track">
                <div class="scope-bar-fill" style="width: ${pct}%"></div>
            </div>
        </div>
    `;
}
