// --- 04_chat.js ---
// Chat panel: message rendering, CIBA approval cards, input handling

function addUserMessage(text) {
    const container = document.getElementById('messages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'message user';
    div.innerHTML = '<span class="msg-time">' + formatTime() + '</span>' + escapeHtml(text);
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function addSystemMessage(text) {
    const container = document.getElementById('messages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'message system';
    div.textContent = text;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendToChat(content) {
    const container = document.getElementById('messages');
    if (!container) return;

    if (!currentAssistantMsg) {
        currentAssistantMsg = document.createElement('div');
        currentAssistantMsg.className = 'message assistant';
        currentAssistantMsg._rawText = '';
        container.appendChild(currentAssistantMsg);
    }
    currentAssistantMsg._rawText += content;
    // During streaming: plain text for smooth character-by-character flow
    currentAssistantMsg.textContent = currentAssistantMsg._rawText;
    container.scrollTop = container.scrollHeight;
}

// Called when streaming ends — apply markdown formatting + add timestamp + copy button
function finalizeAssistantMessage() {
    if (currentAssistantMsg && currentAssistantMsg._rawText) {
        const time = '<span class="msg-time">' + formatTime() + '</span>';
        const copyBtn = '<button class="btn-copy" onclick="copyFindings(this)" title="Copy to clipboard">copy</button>';
        currentAssistantMsg.innerHTML = '<div class="msg-header">' + time + copyBtn + '</div>' + renderMarkdown(currentAssistantMsg._rawText);
    }
}

function copyFindings(btn) {
    const msg = btn.closest('.message');
    if (!msg) return;
    // Use _rawText if available, otherwise extract from rendered text
    const text = msg._rawText || msg.textContent || '';
    navigator.clipboard.writeText(text).then(function() {
        btn.textContent = 'copied';
        setTimeout(function() { btn.textContent = 'copy'; }, 2000);
    }).catch(function() {
        btn.textContent = 'failed';
        setTimeout(function() { btn.textContent = 'copy'; }, 2000);
    });
}

function renderMarkdown(text) {
    // Escape HTML first
    let html = escapeHtml(text);
    // Severity tags — color coded
    html = html.replace(/\[CRITICAL\]/g, '<span style="color:#ef4444;font-weight:bold">[CRITICAL]</span>');
    html = html.replace(/\[WARNING\]/g, '<span style="color:#f59e0b;font-weight:bold">[WARNING]</span>');
    html = html.replace(/\[INFO\]/g, '<span style="color:#38bdf8;font-weight:bold">[INFO]</span>');
    // Bold **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Headers ### and ##
    html = html.replace(/^### (.+)$/gm, '<div style="color:rgba(0,255,0,0.9);font-weight:bold;margin-top:8px">$1</div>');
    html = html.replace(/^## (.+)$/gm, '<div style="color:rgba(0,255,0,0.95);font-weight:bold;font-size:15px;margin-top:10px">$1</div>');
    // Bullet points
    html = html.replace(/^\* (.+)$/gm, '<div style="padding-left:12px">&#8226; $1</div>');
    html = html.replace(/^- (.+)$/gm, '<div style="padding-left:12px">&#8226; $1</div>');
    // Inline code `text`
    html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(0,255,0,0.08);padding:1px 4px;border-radius:2px">$1</code>');
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    return html;
}

function showCIBACard(data) {
    const card = document.getElementById('cibaCard');
    if (!card) return;
    card.classList.remove('hidden');
    card.classList.add('ciba-pulse');
    const message = data.message || data.binding_message || 'Waiting for approval...';
    card.innerHTML = `
        <div class="ciba-title">Approval Required</div>
        <div class="ciba-message">${escapeHtml(message)}</div>
        <div style="color: rgba(245,158,11,0.6); font-size: 11px;">
            Check your phone for the Guardian notification
        </div>
    `;
}

function hideCIBACard() {
    const card = document.getElementById('cibaCard');
    if (!card) return;
    card.classList.add('hidden');
    card.classList.remove('ciba-pulse');
    card.innerHTML = '';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// --- Action buttons after scan ---
function showActionButtons() {
    const container = document.getElementById('messages');
    if (!container) return;
    // Remove existing action buttons
    const existing = container.querySelector('.action-buttons');
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.className = 'action-buttons';
    const actions = [
        { label: 'Fix PII exposure', msg: 'Create a GitHub issue to configure noreply email for commits. Use the repo where my email was found exposed in the scan results.' },
        { label: 'Check my PRs', msg: 'What pull requests need my attention?' },
        { label: 'Search emails', msg: 'Search my recent emails for anything security-related.' },
        { label: 'Analyze session', msg: 'Run analyzeSession to show scope utilization and exposure delta.' },
    ];
    actions.forEach(function(action) {
        const btn = document.createElement('button');
        btn.className = 'action-btn';
        btn.textContent = action.label;
        btn.onclick = function() {
            div.remove();
            sendMessage(action.msg);
        };
        div.appendChild(btn);
    });
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// Enter key sends message
document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        const input = document.getElementById('messageInput');
        if (input && document.activeElement === input && !isStreaming) {
            e.preventDefault();
            sendMessage();
        }
    }
});
