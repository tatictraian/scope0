// --- 06_init.js ---
// App initialization, login check, session restore

(async function init() {
    'use strict';

    try {
        const resp = await fetch('/auth/me');
        if (!resp.ok) {
            document.getElementById('loginOverlay').classList.remove('hidden');
            return;
        }

        const user = await resp.json();
        if (!user.authenticated) {
            document.getElementById('loginOverlay').classList.remove('hidden');
            return;
        }

        currentUser = user;

        // Show loading indicator
        const loader = document.getElementById('loadingIndicator');
        if (loader) loader.classList.remove('hidden');

        // Show dashboard
        document.getElementById('dashboard').classList.remove('hidden');
        if (typeof setCanvasDashboardMode === 'function') setCanvasDashboardMode(true);

        // Display user info + connection status
        const userInfo = document.getElementById('userInfo');
        if (userInfo) userInfo.textContent = user.email || user.name || user.sub;
        renderConnectionStatus();

        // Restore thread ID if available
        const savedThread = sessionStorage.getItem('scope0_thread_id');
        if (savedThread) currentThreadId = savedThread;

        // Load tool toggles from FGA
        await loadToolToggles();

        // Try to restore last session
        const sessionResp = await apiFetch('/api/session');
        if (sessionResp && sessionResp.ok) {
            const sessionData = await sessionResp.json();
            if (sessionData.found) {
                // Restore scan findings
                if (sessionData.scans) {
                    if (sessionData.scans.scanGitHubExposure) {
                        updateFindings('scanGitHubExposure', sessionData.scans.scanGitHubExposure);
                        markConnected('github');
                        updateScopeInfo('github', sessionData.scans.scanGitHubExposure);
                    }
                    if (sessionData.scans.scanGoogleExposure) {
                        updateFindings('scanGoogleExposure', sessionData.scans.scanGoogleExposure);
                        markConnected('google-oauth2');
                        updateScopeInfo('google', sessionData.scans.scanGoogleExposure);
                    }
                }
                // Restore score
                if (sessionData.score) {
                    updateExposureGauge(sessionData.score);
                }
                // Load timeline
                loadAuditTimeline();
                // Show restore message
                if (loader) loader.classList.add('hidden');
                addSystemMessage('Previous scan loaded. Type a message or click Rescan to scan again.');
                showActionButtons();
                return;
            }
        }

        // No saved session — initialize fresh
        if (loader) loader.classList.add('hidden');
        renderScoreGauge(0);
        loadAuditTimeline();
        sendMessage('Scan my connected services.');

    } catch (e) {
        console.error('Init error:', e);
        document.getElementById('loginOverlay').classList.remove('hidden');
        showToast('Connection error. Check your network.');
    }
})();
