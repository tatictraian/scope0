// --- 03_exposure.js ---
// Exposure panel: SVG gauge, finding cards, score updates, particle burst

// escapeHtml defined in 04_chat.js — define locally for load-order safety
function escapeForHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

let lastScore = null;

function renderScoreGauge(score) {
    const gauge = document.getElementById('scoreGauge');
    if (!gauge) return;

    // Score color: green (low) → amber (medium) → red (high)
    let color;
    if (score < 30) color = '#22c55e';
    else if (score < 60) color = '#f59e0b';
    else color = '#ef4444';

    // Arc calculation (semicircle gauge)
    const cx = 80, cy = 80, r = 65;
    const startAngle = Math.PI;
    const endAngle = Math.PI + (score / 100) * Math.PI;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const largeArc = score > 50 ? 1 : 0;

    const delta = lastScore !== null ? score - lastScore : null;
    let deltaHtml = '';
    if (delta !== null && delta !== 0) {
        const cls = delta > 0 ? 'positive' : 'negative';
        const sign = delta > 0 ? '+' : '';
        deltaHtml = `<div class="score-delta ${cls}">${sign}${delta}</div>`;
    }
    lastScore = score;

    gauge.innerHTML = `
        <svg viewBox="0 0 160 100" xmlns="http://www.w3.org/2000/svg">
            <path d="M ${x1} ${y1} A ${r} ${r} 0 0 1 ${cx + r} ${cy}"
                  fill="none" stroke="rgba(0,255,0,0.1)" stroke-width="8" stroke-linecap="round"/>
            <path d="M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}"
                  fill="none" stroke="${color}" stroke-width="8" stroke-linecap="round"/>
        </svg>
        <div id="scoreValue" style="color:${color}">${score}</div>
        <div id="scoreLabel">exposure score</div>
        ${deltaHtml}
    `;

    // Trigger particle burst on score reveal
    if (typeof triggerScoreBurst === 'function') {
        const rect = gauge.getBoundingClientRect();
        triggerScoreBurst(rect.left + rect.width / 2, rect.top + rect.height / 2);
    }
}

function updateExposureGauge(result) {
    if (!result) return;
    renderScoreGauge(result.score || 0);

    // Append score breakdown + remediation to findings panel (below scan findings)
    const findings = document.getElementById('findings');
    if (!findings) return;

    // Re-render scan findings first (preserves them)
    renderScanFindings();

    // Then append score breakdown
    let html = findings.innerHTML;

    if (result.components) {
        html += '<h3>Score Breakdown</h3>';
        for (const [key, comp] of Object.entries(result.components)) {
            const name = escapeForHtml(key.replace(/_/g, ' '));
            html += `
                <div class="score-component">
                    <span class="score-component-name">${name}</span>
                    <span class="score-component-value">${parseInt(comp.score) || 0}</span>
                    <div class="score-component-bar">
                        <div class="score-component-fill" style="width:${parseInt(comp.score) || 0}%"></div>
                    </div>
                </div>
            `;
        }
    }

    if (result.remediation_actions && result.remediation_actions.length > 0) {
        html += '<h3>Remediation Queue</h3>';
        for (const a of result.remediation_actions) {
            const cls = severityClass(a.severity);
            const ciba = a.ciba_required ? ' [CIBA]' : ' [AUTO]';
            html += `<div class="finding-card ${cls}"><div class="finding-severity">${escapeForHtml(a.severity)}${ciba}</div>${escapeForHtml(a.description)}</div>`;
        }
    }

    findings.innerHTML = html;

    // Canvas glitch on score reveal + reload timeline
    if (typeof triggerGlitchBurst === 'function') triggerGlitchBurst(0.3);
    if (typeof loadAuditTimeline === 'function') loadAuditTimeline();
}

// Store scan results for findings panel
let scanData = {};

function updateFindings(toolName, result) {
    if (!result) return;
    scanData[toolName] = result;

    // Add exposure tags to canvas
    if (toolName === 'scanGitHubExposure') {
        const secrets = (result.secrets || {}).alerts || [];
        for (const s of secrets) {
            if (typeof addExposureTag === 'function') addExposureTag(s.secret_type + ' in ' + s.repo, 'CRITICAL');
        }
        const emails = (result.email_exposure || {}).emails || [];
        for (const e of emails) {
            if (typeof addExposureTag === 'function') addExposureTag('PII: ' + e, 'WARNING');
        }
        if (result.scope_analysis) {
            if (typeof addExposureTag === 'function') addExposureTag('Overprivilege: ' + result.scope_analysis.overprivilege_pct + '%', 'WARNING');
        }
    }
    if (toolName === 'scanGoogleExposure') {
        const email = (result.email || {}).address;
        if (email && typeof addExposureTag === 'function') addExposureTag('Google: ' + email, 'INFO');
        const events = (result.calendar || {}).upcomingEvents;
        if (events && typeof addExposureTag === 'function') addExposureTag(events + ' calendar events exposed', 'INFO');
    }

    // Render scan-specific findings into the panel
    renderScanFindings();
}

function renderScanFindings() {
    const container = document.getElementById('findings');
    if (!container) return;

    let html = '';

    // --- GitHub Secret Scanning (their built-in) ---
    const gh = scanData['scanGitHubExposure'];
    if (gh) {
        const secrets = (gh.secrets || {}).alerts || [];
        if (secrets.length > 0) {
            html += '<h3>GitHub Secret Scanning</h3>';
            html += '<div style="font-size:10px;color:rgba(0,255,0,0.3);margin-bottom:6px">200+ patterns via GitHub built-in scanner</div>';
            for (const s of secrets) {
                html += '<div class="finding-card critical"><div class="finding-severity">CRITICAL</div>' +
                    escapeForHtml(s.secret_type) + ' in ' + escapeForHtml(s.repo) + '</div>';
            }
        } else {
            html += '<h3>GitHub Secret Scanning</h3>';
            html += '<div class="finding-card info"><div class="finding-severity" title="GitHub\'s built-in secret scanner found no exposed credentials">CLEAR</div>No secrets detected (200+ patterns checked)</div>';
        }
    }

    // --- Cross-Service Analysis (OUR unique value) ---
    const go = scanData['scanGoogleExposure'];
    if (gh || go) {
        html += '<h3>Cross-Service Analysis</h3>';
        html += '<div style="font-size:10px;color:rgba(0,255,0,0.3);margin-bottom:6px">What Scope0 reveals by combining services</div>';

        // PII bridges — user's email is IDENTITY BRIDGE (warning), others are just exposed PII (dimmer)
        if (gh) {
            const emails = (gh.email_exposure || {}).emails || [];
            if (emails.length > 0) {
                const googleEmail = go ? (go.email || {}).address : null;
                // Show user's own email first as bridge, then others grouped
                const bridges = [];
                const others = [];
                for (const e of emails) {
                    const isBridge = googleEmail && e.toLowerCase() === googleEmail.toLowerCase();
                    if (isBridge) bridges.push(e);
                    else others.push(e);
                }
                for (const e of bridges) {
                    html += '<div class="finding-card critical"><div class="finding-severity" title="Personally Identifiable Information bridging multiple services">IDENTITY BRIDGE</div>' +
                        escapeForHtml(e) + ' - same email across GitHub + Google</div>';
                }
                if (others.length > 0) {
                    html += '<div class="finding-card info"><div class="finding-severity" title="Personally Identifiable Information found in public commits">EXPOSED EMAILS</div>' +
                        others.length + ' other email(s) in public commits: ' +
                        others.map(function(e) { return '<span style="opacity:0.7">' + escapeForHtml(e) + '</span>'; }).join(', ') +
                        '</div>';
                }
            }
        }

        // Work pattern + calendar correlation
        if (gh && gh.work_pattern && gh.work_pattern.peak_hour_utc !== null) {
            const wp = gh.work_pattern;
            const hasCalendar = go && go.calendar && go.calendar.upcomingEvents > 0;
            const offset = wp.inferred_utc_offset;
            const aw = wp.active_window;
            let detail = 'Peak commit hour: ' + wp.peak_hour_utc + ':00 UTC';
            if (aw) {
                detail += ' | Active: ' + aw.start_utc + ':00-' + aw.end_utc + ':00 UTC (' + aw.sleep_gap_hours + 'h offline gap)';
            }
            if (offset !== null && offset !== undefined) {
                detail += ' | Likely timezone: UTC' + (offset >= 0 ? '+' : '') + offset;
            }
            if (hasCalendar) {
                detail += ' | Cross-referenced with ' + go.calendar.upcomingEvents + ' calendar events';
            }
            html += '<div class="finding-card warning"><div class="finding-severity" title="Work schedule inferred from commit timestamps + activity gaps">SCHEDULE</div>' +
                escapeForHtml(detail) + '</div>';
        }

        // Scope overprivilege
        if (gh && gh.scope_analysis) {
            html += '<div class="finding-card warning"><div class="finding-severity" title="OAuth permissions exceed what is needed">OVERPRIVILEGE</div>' +
                'GitHub: ' + gh.scope_analysis.overprivilege_pct + '% more access than needed</div>';
        }
        if (go && go.scope_analysis) {
            html += '<div class="finding-card warning"><div class="finding-severity" title="OAuth permissions exceed what is needed">OVERPRIVILEGE</div>' +
                'Google: ' + go.scope_analysis.overprivilege_pct + '% more access than needed</div>';
        }

        // Data surface
        if (gh && go) {
            const repos = (gh.repos || {}).total || 0;
            const threads = (go.email || {}).totalThreads || 0;
            const events = (go.calendar || {}).upcomingEvents || 0;
            if (repos + threads + events > 0) {
                html += '<div class="finding-card info"><div class="finding-severity" title="Total data accessible via granted tokens">DATA SURFACE</div>' +
                    repos + ' repos + ' + threads + ' email threads + ' + events + ' calendar events accessible to any agent with these tokens</div>';
            }
        }
    }

    container.innerHTML = html;
}

// --- Tab switching ---
function switchExposureTab(tab) {
    const findings = document.getElementById('findings');
    const timeline = document.getElementById('auditTimeline');
    const tabs = document.querySelectorAll('.panel-tab');
    if (!findings || !timeline) return;

    tabs.forEach(function(t) { t.classList.remove('active'); });

    if (tab === 'findings') {
        findings.classList.remove('hidden');
        timeline.classList.add('hidden');
        tabs[0].classList.add('active');
    } else {
        findings.classList.add('hidden');
        timeline.classList.remove('hidden');
        tabs[1].classList.add('active');
        loadAuditTimeline();
    }
}

// --- Audit Timeline ---
async function loadAuditTimeline() {
    const resp = await apiFetch('/api/timeline');
    if (!resp || !resp.ok) return;
    const events = await resp.json();
    renderTimeline(events);
}

function renderTimeline(events) {
    const container = document.getElementById('auditTimeline');
    const header = document.getElementById('timelineHeader');
    if (!container || !events || events.length === 0) return;

    if (header) header.classList.remove('hidden');
    let html = '';

    for (const evt of events) {
        const time = new Date(evt.created_at).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });

        if (evt.type === 'score') {
            const scoreColor = evt.score < 30 ? '#22c55e' : evt.score < 60 ? '#f59e0b' : '#ef4444';
            html += '<div class="timeline-entry timeline-score">' +
                '<span class="timeline-time">' + time + '</span>' +
                '<span style="color:' + scoreColor + ';font-weight:bold">Score: ' + evt.score + '</span>' +
                '</div>';
        } else if (evt.type === 'scan') {
            const label = evt.scan_type.replace('scan', '').replace('Exposure', '');
            html += '<div class="timeline-entry">' +
                '<span class="timeline-time">' + time + '</span>' +
                'Scanned ' + escapeForHtml(label) +
                '</div>';
        } else if (evt.type === 'self_restrict') {
            html += '<div class="timeline-entry timeline-restrict">' +
                '<span class="timeline-time">' + time + '</span>' +
                'Disabled ' + escapeForHtml(evt.tool_name) +
                '</div>';
        }
    }

    container.innerHTML = html;
}
