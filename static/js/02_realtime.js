// --- 02_realtime.js ---
// SSE streaming via fetch(), interrupt handlers
// Pattern: Auth0 example uses fetch() POST with response.body.getReader()

// Shared SSE parser — buffers across TCP chunk boundaries, awaits async handlers
async function readSSEStream(response, handlers) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Split on double newlines (SSE event boundary)
        const events = buffer.split('\n\n');
        buffer = events.pop(); // Last element may be incomplete

        for (const eventStr of events) {
            if (!eventStr.trim()) continue;
            const lines = eventStr.split('\n');
            let eventType = '';
            let eventData = '';
            for (const line of lines) {
                if (line.startsWith('event: ')) eventType = line.slice(7);
                // SSE spec: multiple data: lines concatenated with newlines
                else if (line.startsWith('data: ')) {
                    eventData = eventData ? eventData + '\n' + line.slice(6) : line.slice(6);
                }
            }
            if (eventType && eventData) {
                try {
                    const data = JSON.parse(eventData);
                    if (handlers[eventType]) {
                        // Await async handlers (critical for handleCIBAPending)
                        const result = handlers[eventType](data);
                        if (result && typeof result.then === 'function') {
                            await result;
                        }
                    }
                } catch (e) {
                    console.error('SSE parse error:', e, eventData);
                }
            }
        }
    }
}

// Shared event handlers for both sendMessage and resumeAgent
const sseHandlers = {
    thread_id: function(data) {
        currentThreadId = data.thread_id;
        sessionStorage.setItem('scope0_thread_id', data.thread_id);
    },
    text: function(data) {
        hideThinking();
        appendToChat(data.content);
    },
    tool_result: function(data) {
        // Finalize current assistant message before new tool result
        // This prevents text from different tool responses merging into one block
        if (currentAssistantMsg && currentAssistantMsg._rawText) {
            if (typeof finalizeAssistantMessage === 'function') finalizeAssistantMessage();
            currentAssistantMsg = null;
        }
        incrementToolCount();
        addAuditEntry(data.tool, 'completed');
        if (data.tool === 'scanGitHubExposure') {
            markConnected('github');
            updateScopeInfo('github', data.result);
        }
        if (data.tool === 'scanGoogleExposure') {
            markConnected('google-oauth2');
            updateScopeInfo('google', data.result);
        }
        if (data.tool === 'generateExposureScore') {
            updateExposureGauge(data.result);
        }
        if (data.tool === 'scanGitHubExposure' || data.tool === 'scanGoogleExposure') {
            updateFindings(data.tool, data.result);
        }
        if (data.tool === 'disableMyTool' && data.result) {
            updateToggle(data.result.disabled, false);
            addAuditEntry('[SELF] Disabled ' + data.result.disabled, data.result.reason);
            if (typeof triggerGlitchBurst === 'function') triggerGlitchBurst(0.6);
            showToast(data.result.disabled + ' auto-disabled (least privilege)');
        }
        // Show action buttons after score is computed
        if (data.tool === 'generateExposureScore') {
            showActionButtons();
        }
        if (data.tool === 'analyzeSession') {
            updateScopeUtilization(data.result);
        }
    },
    token_vault_interrupt: function(data) {
        hideThinking();
        handleTokenVaultInterrupt(data);
    },
    ciba_pending: function(data) {
        hideThinking();
        return handleCIBAPending(data);
    },
    auth0_interrupt: function(data) {
        showToast('Auth0 interrupt: ' + (data.message || data.code || 'unknown'));
    },
    error: function(data) {
        hideThinking();
        showToast('Agent error: ' + (data.message || 'unknown'));
    },
};

async function sendMessage(content) {
    if (isStreaming) return;
    if (typeof content !== 'string') {
        const input = document.getElementById('messageInput');
        content = input.value.trim();
        if (!content) return;
        input.value = '';
    }
    addUserMessage(content);
    popupAttempts = 0;
    startStreaming();

    try {
        const response = await apiFetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id: currentThreadId, message: content }),
        });

        if (!response || !response.ok) {
            showToast('Request failed: ' + (response ? response.status : 'network error'));
            return;
        }

        await readSSEStream(response, sseHandlers);
    } catch (e) {
        console.error('sendMessage error:', e);
        showToast('Connection error');
    } finally {
        finishStreaming();
    }
}

async function resumeAgent() {
    startStreaming();

    try {
        const response = await apiFetch('/api/resume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_id: currentThreadId }),
        });

        if (!response || !response.ok) {
            showToast('Resume failed: ' + (response ? response.status : 'network error'));
            return;
        }

        await readSSEStream(response, sseHandlers);
    } catch (e) {
        console.error('resumeAgent error:', e);
        showToast('Connection error');
    } finally {
        finishStreaming();
    }
}

let streamDepth = 0;

function startStreaming() {
    streamDepth++;
    isStreaming = true;
    currentAssistantMsg = null;
    const btn = document.getElementById('sendBtn');
    if (btn) btn.disabled = true;
    const input = document.getElementById('messageInput');
    if (input) input.disabled = true;
    // Show thinking indicator
    showThinking();
}

const THINKING_VERBS = [
    'Probing tokens', 'Mapping exposure', 'Tracing connections',
    'Analyzing surface', 'Checking permissions', 'Scanning scopes',
    'Correlating identities', 'Inspecting grants'
];
let thinkingInterval = null;

function showThinking() {
    hideThinking();
    const container = document.getElementById('messages');
    if (!container) return;
    const div = document.createElement('div');
    div.id = 'thinkingIndicator';
    div.className = 'message system thinking-msg';
    let verbIdx = Math.floor(Math.random() * THINKING_VERBS.length);
    div.innerHTML = '<span class="thinking-verb">' + THINKING_VERBS[verbIdx] + '</span><span class="thinking-dots"></span>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    // Rotate verbs
    thinkingInterval = setInterval(function() {
        verbIdx = (verbIdx + 1) % THINKING_VERBS.length;
        const el = div.querySelector('.thinking-verb');
        if (el) el.textContent = THINKING_VERBS[verbIdx];
    }, 3000);
}

function hideThinking() {
    if (thinkingInterval) { clearInterval(thinkingInterval); thinkingInterval = null; }
    const el = document.getElementById('thinkingIndicator');
    if (el) el.remove();
}

function finishStreaming() {
    streamDepth = Math.max(0, streamDepth - 1);
    if (streamDepth === 0) {
        isStreaming = false;
        if (typeof finalizeAssistantMessage === 'function') finalizeAssistantMessage();
        currentAssistantMsg = null;
        hideThinking();
        const btn = document.getElementById('sendBtn');
        if (btn) btn.disabled = false;
        const input = document.getElementById('messageInput');
        if (input) input.disabled = false;
    }
}

// --- Token Vault interrupt: open connect popup ---
let popupAttempts = 0;
const MAX_POPUP_ATTEMPTS = 3;
const POPUP_CHECK_TIMEOUT = 120000; // 2 minutes max wait for popup (My Account API flow takes time)

function handleTokenVaultInterrupt(data) {
    const connection = data.connection || 'github';
    popupAttempts++;

    if (popupAttempts > MAX_POPUP_ATTEMPTS) {
        addSystemMessage('Connection failed after ' + MAX_POPUP_ATTEMPTS + ' attempts. Please refresh and try again.');
        popupAttempts = 0;
        return;
    }

    // Show a connect button in chat — user click = user gesture = popup allowed
    const connName = connection === 'google-oauth2' ? 'Google' : connection === 'sign-in-with-slack' ? 'Slack' : 'GitHub';
    showConnectButton(connName, connection);
}

function showConnectButton(label, connection) {
    const container = document.getElementById('messages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'message system';
    div.innerHTML = 'Token Vault needs access to ' + escapeForHtml(label) + '. <button class="btn-connect" onclick="openConnectPopup(\'' + escapeForHtml(connection) + '\', this.parentElement)">Connect ' + escapeForHtml(label) + '</button>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function openConnectPopup(connection, msgEl) {
    // Called from user click — popup will NOT be blocked
    const popup = window.open(
        '/auth/connect/' + connection,
        'auth0_connect',
        'width=500,height=600'
    );
    if (!popup) {
        // Last resort fallback — should not happen from user click
        window.location.href = '/auth/connect/' + connection;
        return;
    }

    if (msgEl) msgEl.textContent = 'Connecting... Complete authorization in the popup window.';

    const startTime = Date.now();
    const check = setInterval(function() {
        if (Date.now() - startTime > POPUP_CHECK_TIMEOUT) {
            clearInterval(check);
            addSystemMessage('Connection timed out. Please try again.');
            return;
        }
        if (popup.closed) {
            clearInterval(check);
            resumeAgent();
        }
    }, 500);
}

// --- CIBA interrupt: show approval card, poll for completion ---
const MAX_CIBA_ATTEMPTS = 60; // 60 * 5s = 5 minutes

async function handleCIBAPending(data) {
    showCIBACard(data);
    let resolved = false;
    let attempts = 0;

    while (!resolved && attempts < MAX_CIBA_ATTEMPTS) {
        attempts++;
        await new Promise(function(r) { setTimeout(r, 5000); });

        try {
            const response = await apiFetch('/api/resume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ thread_id: currentThreadId }),
            });
            if (!response || !response.ok) continue;

            let gotCIBA = false;
            await readSSEStream(response, {
                ...sseHandlers,
                ciba_pending: function() { gotCIBA = true; },
            });
            if (!gotCIBA) resolved = true;
        } catch (e) {
            console.error('CIBA poll error:', e);
        }
    }

    hideCIBACard();
    if (!resolved) {
        addSystemMessage('Approval timed out after 5 minutes. You can ask the agent to try again.');
    }
}
