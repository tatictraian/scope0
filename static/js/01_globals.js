// --- 01_globals.js ---
// Global state, API helpers, formatters

let currentThreadId = null;
let currentUser = null;
let isStreaming = false;
let currentAssistantMsg = null;
let toolCallCount = 0;
let connectedServices = { github: false, 'google-oauth2': false };

// --- API helper ---
async function apiFetch(url, options) {
    const resp = await fetch(url, options);
    if (resp.status === 401) {
        window.location.href = '/auth/login';
        return null;
    }
    return resp;
}

// --- Toast notification ---
function showToast(message) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 8000);
}

// --- Timestamp formatter ---
function formatTime() {
    const now = new Date();
    return now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// --- Severity class ---
function severityClass(severity) {
    switch ((severity || '').toUpperCase()) {
        case 'CRITICAL': return 'critical';
        case 'WARNING': case 'HIGH': case 'MEDIUM': return 'warning';
        default: return 'info';
    }
}

// --- Connection status ---
function markConnected(connection) {
    connectedServices[connection] = true;
    renderConnectionStatus();
}

function renderConnectionStatus() {
    const container = document.getElementById('connStatus');
    if (!container) return;
    container.innerHTML = '';
    const services = [
        { key: 'github', label: 'GitHub' },
        { key: 'google-oauth2', label: 'Google' },
    ];
    services.forEach(function(svc) {
        const dot = document.createElement('span');
        dot.className = 'conn-dot' + (connectedServices[svc.key] ? ' connected' : '');
        dot.textContent = svc.label;
        dot.title = svc.key + (connectedServices[svc.key] ? ' (connected)' : ' (not connected)');
        container.appendChild(dot);
    });
}

// --- Tool call counter ---
function incrementToolCount() {
    toolCallCount++;
    updateToolCountDisplay();
}

function updateToolCountDisplay() {
    let el = document.getElementById('toolCallCount');
    if (!el) {
        const trail = document.getElementById('auditTrail');
        if (!trail) return;
        el = document.createElement('div');
        el.id = 'toolCallCount';
        el.style.cssText = 'font-size:10px;color:rgba(0,255,0,0.3);margin-bottom:6px;letter-spacing:1px';
        trail.parentElement.insertBefore(el, trail);
    }
    el.textContent = toolCallCount + ' API call' + (toolCallCount !== 1 ? 's' : '');
}
