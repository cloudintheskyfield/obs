class AppStateStore {
    constructor() {
        this.state = {
            mode: "agent",
            permissionMode: "ask",
            thinkingMode: true,
            runtime: null,
            selectedTaskId: "main",
            contextPercent: 0,
            toolContext: "workspace",
            tasks: [],
            transcriptFilter: "all"
        };
    }

    get() {
        return this.state;
    }

    set(patch) {
        this.state = { ...this.state, ...patch };
        return this.state;
    }
}

class ObsAgentConsole {
    constructor() {
        this.storageVersion = "20260415-01";
        this.apiBaseUrl = this.resolveDefaultApiBaseUrl();
        this.sessions = new Map();
        this.currentSessionId = null;
        this.isSending = false;
        this.settings = {
            apiUrl: this.apiBaseUrl,
            autoSave: true,
            theme: "dark",
            permissionMode: "ask",
            thinkingMode: true,
            toolContext: "workspace"
        };
        this.store = new AppStateStore();
        this.collapsedMessages = new Set();
        this.pendingPermissionAction = null;
        this.permissionConfirmedForSubmit = false;
        this.pinnedThinkingMessages = new Set();
        this.workflowPhases = ["queued", "planning", "execution", "synthesis", "verification", "complete"];
        this.logRange = "all";

        this.init();
    }

    resolveDefaultApiBaseUrl() {
        const { protocol, origin, hostname } = window.location;
        if ((protocol === "http:" || protocol === "https:") && hostname) {
            return origin;
        }
        return "http://127.0.0.1:8000";
    }

    safeSetLocalStorage(key, value) {
        try {
            localStorage.setItem(key, value);
            return true;
        } catch (error) {
            console.warn(`Failed to persist localStorage key: ${key}`, error);
            if (error?.name === "QuotaExceededError") {
                try {
                    localStorage.removeItem("obs-agent-sessions");
                } catch (cleanupError) {
                    console.warn("Failed to clear oversized session cache", cleanupError);
                }
            }
            return false;
        }
    }

    init() {
        this.bindElements();
        this.loadSettings();
        this.applyStoredPreferences();
        this.bindEvents();
        this.loadSessions();
        this.ensureSession();
        this.refreshRuntime();
        this.fetchSkills();
        this.renderPermissionState();
        this.renderThinkingMode();
        this.renderModePills();
        this.setActiveToolContext(this.store.get().toolContext);
    }

    bindElements() {
        this.sessionList = document.getElementById("session-list");
        this.chatMessages = document.getElementById("chat-messages");
        this.messageInput = document.getElementById("message-input");
        this.sendBtn = document.getElementById("send-btn");
        this.newChatBtn = document.getElementById("new-chat-btn");
        this.clearChatBtn = document.getElementById("clear-chat-btn");
        this.exportChatBtn = document.getElementById("export-chat-btn");
        this.settingsBtn = document.getElementById("settings-btn");
        this.closeDetailsBtn = document.getElementById("close-details-btn");
        this.inspector = document.getElementById("inspector");
        this.logsDrawer = document.getElementById("logs-drawer");
        this.logsList = document.getElementById("logs-list");
        this.logsToggleBtn = document.getElementById("logs-toggle-btn");
        this.logsCloseBtn = document.getElementById("logs-close-btn");
        this.logsRangeFilter = document.getElementById("logs-range-filter");
        this.logsFromInput = document.getElementById("logs-from-input");
        this.logsToInput = document.getElementById("logs-to-input");
        this.logsRefreshBtn = document.getElementById("logs-refresh-btn");
        this.searchShellBtn = document.getElementById("search-shell-btn");
        this.historyLinkBtn = document.getElementById("history-link-btn");
        this.sidebarNavButtons = [
            this.searchShellBtn,
            this.historyLinkBtn
        ].filter(Boolean);
        this.currentSessionTitle = document.getElementById("current-session-title");
        this.welcomeScreen = document.getElementById("welcome-screen");
        this.agentStatus = document.getElementById("agent-status");
        this.transcriptTitle = document.getElementById("transcript-title");
        this.returnMainBtn = document.getElementById("return-main-btn");
        this.modeSelect = document.getElementById("mode-select");
        this.phaseRail = document.getElementById("phase-rail");
        this.phaseTitle = document.getElementById("phase-title");
        this.phaseTrack = document.getElementById("phase-track");
        this.composerPlaceholder = document.querySelector(".composer-placeholder");

        this.modelPill = document.getElementById("model-pill");
        this.contextPill = document.getElementById("context-pill");
        this.modelBadge = document.getElementById("model-badge");
        this.runtimeBadge = document.getElementById("runtime-badge");
        this.runtimeApi = document.getElementById("runtime-api");
        this.runtimeModel = document.getElementById("runtime-model");
        this.runtimeWorkdir = document.getElementById("runtime-workdir");
        this.runtimeSkills = document.getElementById("runtime-skills");
        this.runtimeTools = document.getElementById("runtime-tools");

        this.permissionModeBtn = document.getElementById("permission-mode-btn");
        this.thinkingModeBtn = document.getElementById("thinking-mode-btn");
        this.permissionSummary = document.getElementById("permission-summary");
        this.policyFiles = document.getElementById("policy-files");
        this.policyTerminal = document.getElementById("policy-terminal");
        this.policyComputer = document.getElementById("policy-computer");

        this.taskCount = document.getElementById("task-count");
        this.taskStrip = document.getElementById("task-strip");
        this.taskList = document.getElementById("task-list");
        this.selectedTaskLabel = document.getElementById("selected-task-label");

        this.skillsList = document.getElementById("skills-list");
        this.skillsCount = document.getElementById("skills-count");

        this.statuslineLeft = document.getElementById("statusline-left");

        this.settingsModal = document.getElementById("settings-modal");
        this.closeSettingsBtn = document.getElementById("close-settings");
        this.saveSettingsBtn = document.getElementById("save-settings");
        this.resetSettingsBtn = document.getElementById("reset-settings");
        this.apiUrlInput = document.getElementById("api-url");
        this.autoSaveInput = document.getElementById("auto-save");
        this.themeSelect = document.getElementById("theme-select");

        this.permissionModal = document.getElementById("permission-modal");
        this.closePermissionModalBtn = document.getElementById("close-permission-modal");
        this.permissionCancelBtn = document.getElementById("permission-cancel-btn");
        this.permissionOnceBtn = document.getElementById("permission-once-btn");
        this.permissionModalCopy = document.getElementById("permission-modal-copy");
        this.smallToolButtons = Array.from(document.querySelectorAll(".small-tool"));
    }

    bindEvents() {
        this.newChatBtn.addEventListener("click", () => this.createSession());
        this.clearChatBtn.addEventListener("click", () => this.clearCurrentSession());
        this.exportChatBtn.addEventListener("click", () => this.exportCurrentSession());
        this.settingsBtn.addEventListener("click", () => this.openSettings());
        if (this.closeDetailsBtn) {
            this.closeDetailsBtn.addEventListener("click", () => this.closeDetails());
        }
        this.searchShellBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.searchShellBtn);
            this.focusComposer("Search workspace, tasks, or previous threads");
        });
        this.historyLinkBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.historyLinkBtn);
            this.scrollSidebarSection(".history-panel", "History panel focused");
        });
        this.closeSettingsBtn.addEventListener("click", () => this.closeSettings());
        this.saveSettingsBtn.addEventListener("click", () => this.saveSettings());
        this.resetSettingsBtn.addEventListener("click", () => this.resetSettings());
        this.returnMainBtn.addEventListener("click", () => this.selectTask("main"));

        this.sendBtn.addEventListener("click", () => this.handleSubmitRequest());
        this.messageInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                this.handleSubmitRequest();
            }
        });
        this.messageInput.addEventListener("input", () => this.autoResizeInput());

        this.modeSelect.addEventListener("change", () => {
            const nextMode = this.modeSelect.value || "agent";
            const patch = { mode: nextMode };
            if (nextMode === "review" && this.store.get().permissionMode === "ask") {
                patch.permissionMode = "plan";
            }
            this.store.set(patch);
            this.renderModePills();
            this.renderPermissionState();
            this.updateStatusLine();
            this.persistPreferenceState();
        });

        this.permissionModeBtn.addEventListener("click", () => this.openPermissionModal());
        this.closePermissionModalBtn.addEventListener("click", () => this.closePermissionModal());
        this.permissionCancelBtn.addEventListener("click", () => {
            this.pendingPermissionAction = null;
            this.closePermissionModal();
        });
        this.permissionOnceBtn.addEventListener("click", () => {
            this.permissionConfirmedForSubmit = true;
            this.closePermissionModal();
            if (this.pendingPermissionAction) {
                const action = this.pendingPermissionAction;
                this.pendingPermissionAction = null;
                action();
            }
        });
        this.permissionModal.addEventListener("click", (event) => {
            if (event.target === this.permissionModal) {
                this.closePermissionModal();
            }
        });
        document.querySelectorAll(".permission-option").forEach((button) => {
            button.addEventListener("click", () => {
                this.store.set({ permissionMode: button.dataset.permissionMode || "ask" });
                this.permissionConfirmedForSubmit = true;
                this.closePermissionModal();
                this.renderPermissionState();
                this.updateStatusLine();
                this.persistPreferenceState();
                if (this.pendingPermissionAction) {
                    const action = this.pendingPermissionAction;
                    this.pendingPermissionAction = null;
                    action();
                }
            });
        });

        this.thinkingModeBtn.addEventListener("click", () => {
            const next = !this.store.get().thinkingMode;
            this.store.set({ thinkingMode: next });
            this.renderThinkingMode();
            this.updateStatusLine();
            this.persistPreferenceState();
        });

        this.smallToolButtons.forEach((button) => {
            button.addEventListener("click", () => {
                if (button === this.logsToggleBtn) {
                    this.toggleLogsDrawer();
                    return;
                }
                this.setActiveToolContext(button.dataset.toolContext || "computer");
            });
        });
        if (this.logsCloseBtn) {
            this.logsCloseBtn.addEventListener("click", () => this.toggleLogsDrawer(false));
        }
        if (this.logsRangeFilter) {
            this.logsRangeFilter.addEventListener("change", () => {
                this.logRange = this.logsRangeFilter.value || "all";
                const custom = this.logRange === "custom";
                if (this.logsFromInput) {
                    this.logsFromInput.classList.toggle("hidden", !custom);
                }
                if (this.logsToInput) {
                    this.logsToInput.classList.toggle("hidden", !custom);
                }
                this.refreshLogsFromBackend();
            });
        }
        if (this.logsFromInput) {
            this.logsFromInput.addEventListener("change", () => this.refreshLogsFromBackend());
        }
        if (this.logsToInput) {
            this.logsToInput.addEventListener("change", () => this.refreshLogsFromBackend());
        }
        if (this.logsRefreshBtn) {
            this.logsRefreshBtn.addEventListener("click", () => this.refreshLogsFromBackend());
        }
        if (this.logsDrawer) {
            const backdrop = this.logsDrawer.querySelector(".logs-backdrop");
            if (backdrop) {
                backdrop.addEventListener("click", () => this.toggleLogsDrawer(false));
            }
        }

        this.settingsModal.addEventListener("click", (event) => {
            if (event.target === this.settingsModal) {
                this.closeSettings();
            }
        });
    }

    toggleDetails(force = null) {
        if (!this.inspector) {
            return;
        }
        const shouldOpen = typeof force === "boolean"
            ? force
            : this.inspector.classList.contains("hidden");
        this.inspector.classList.toggle("hidden", !shouldOpen);
    }

    closeDetails() {
        this.toggleDetails(false);
    }

    ensureSession() {
        if (this.sessions.size === 0) {
            this.createSession();
            return;
        }
        const latestSession = Array.from(this.sessions.values()).sort(
            (left, right) => new Date(right.updatedAt) - new Date(left.updatedAt)
        )[0];
        this.switchSession(latestSession.id);
    }

    focusComposer(placeholderText = null) {
        if (placeholderText) {
            this.composerPlaceholder.textContent = placeholderText;
        }
        this.messageInput.focus();
    }

    setActiveSidebarNav(targetButton) {
        this.sidebarNavButtons.forEach((button) => {
            button.classList.toggle("active", button === targetButton);
        });
    }

    scrollSidebarSection(selector, placeholderText = null) {
        const target = document.querySelector(selector);
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        this.focusComposer(placeholderText);
    }

    setActiveToolContext(context) {
        this.store.set({ toolContext: context });
        this.smallToolButtons.forEach((button) => {
            button.classList.toggle("active", button.dataset.toolContext === context);
        });

        const placeholderMap = {
            computer: "Use the computer context to inspect screenshots, browsers, and visual flows",
            workspace: "Describe files, directories, or code paths you want OBS to inspect",
            agents: "Ask OBS to coordinate sub-tasks, review architecture, or manage execution flow"
        };

        this.composerPlaceholder.textContent = placeholderMap[context] || "Ask OBS to inspect code, use tools, or coordinate agents";
        this.refreshContextPercent();
        this.updateStatusLine();
        this.persistPreferenceState();
        this.messageInput.focus();
    }

    createEmptySession(id) {
        return {
            id,
            title: "New thread",
            transcript: [],
            logs: [],
            contextPercentOverride: null,
            tasks: {},
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
        };
    }

    createSession() {
        const id = `session_${Date.now()}`;
        const session = this.createEmptySession(id);
        this.sessions.set(id, session);
        this.store.set({ mode: "agent", selectedTaskId: "main", toolContext: "workspace" });
        this.switchSession(id);
        this.hydrateSessionLocation(id);
        this.renderModePills();
        this.setActiveToolContext("workspace");
        this.persistSessions();
    }

    upgradeSession(session) {
        if (!session.transcript) {
            session.transcript = (session.messages || []).map((message, index) => ({
                id: `legacy_${index}`,
                role: message.role,
                content: message.content,
                kind: message.role === "assistant" ? "assistant_text" : "user_text",
                taskId: "main",
                timestamp: new Date().toISOString()
            }));
        }
        if (!session.tasks) {
            session.tasks = {};
        }
        if (!session.logs) {
            session.logs = [];
        }
        if (typeof session.contextPercentOverride !== "number") {
            session.contextPercentOverride = null;
        }
        session.logs = (session.logs || []).filter((entry) => entry && entry.type === "llm_log");
        session.transcript = (session.transcript || []).filter((entry) => {
            if (!entry) return false;
            if (entry.kind === "tool_use" || entry.kind === "tool_result") return false;
            const content = typeof entry.content === "string" ? entry.content.trim() : "";
            if (entry.kind === "thinking_text" && !content) return Boolean(entry.pendingPlaceholder);
            if (entry.kind === "assistant_text" && !content) return false;
            if (entry.kind === "assistant_text" && /^(OBS is replying|Thinking\.\.\.)$/i.test(content)) return false;
            return true;
        });
        delete session.messages;
        return session;
    }

    getCurrentSession() {
        const session = this.sessions.get(this.currentSessionId);
        return session ? this.upgradeSession(session) : null;
    }

    switchSession(sessionId) {
        const session = this.sessions.get(sessionId);
        if (!session) {
            return;
        }
        this.upgradeSession(session);
        this.currentSessionId = sessionId;
        this.currentSessionTitle.textContent = session.title;
        this.store.set({ selectedTaskId: "main", tasks: Object.values(session.tasks) });
        this.renderSessionList();
        this.renderTranscript();
        this.renderLogs();
        this.toggleWelcome(session.transcript.length === 0);
        this.renderTasks();
        this.renderPhaseRail();
        this.refreshContextPercent();
        this.updateStatusLine();
        this.hydrateSessionLocation(sessionId);
    }

    async hydrateSessionLocation(sessionId) {
        const apiUrl = this.settings.apiUrl;
        if (!apiUrl || !sessionId) {
            return;
        }

        try {
            const resolved = await fetch(`${apiUrl}/location/resolve`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId })
            });
            const payload = await resolved.json().catch(() => ({}));
            if (resolved.ok && payload?.success) {
                return;
            }
        } catch (error) {
            console.debug("Server-side location resolve failed", error);
        }

        try {
            const browserResolved = await fetch("https://ipwho.is/");
            const payload = await browserResolved.json().catch(() => ({}));
            if (!browserResolved.ok || payload?.success === false || payload?.latitude == null || payload?.longitude == null) {
                return;
            }

            await fetch(`${apiUrl}/location`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: sessionId,
                    lat: payload.latitude,
                    lon: payload.longitude,
                    city: payload.city || null,
                    region: payload.region || null,
                    country_name: payload.country_name || payload.country || null,
                    source: "browser_ip",
                    ip: payload.ip || null,
                    provider: "ipwhois_browser"
                })
            });
        } catch (error) {
            console.debug("Browser-side IP location resolve failed", error);
        }
    }

    clearCurrentSession() {
        const session = this.getCurrentSession();
        if (!session) {
            return;
        }
        session.transcript = [];
        session.logs = [];
        session.tasks = {};
        session.contextPercentOverride = null;
        session.title = "New thread";
        session.updatedAt = new Date().toISOString();
        this.currentSessionTitle.textContent = session.title;
        this.store.set({ selectedTaskId: "main", tasks: [] });
        this.renderTranscript();
        this.toggleWelcome(true);
        this.renderTasks();
        this.renderPhaseRail();
        this.refreshContextPercent();
        this.persistSessions();
        this.renderSessionList();
        this.updateStatusLine();
    }

    exportCurrentSession() {
        const session = this.getCurrentSession();
        if (!session) {
            return;
        }
        const blob = new Blob([JSON.stringify(session, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${session.title.replace(/\s+/g, "_").toLowerCase() || "session"}.json`;
        link.click();
        URL.revokeObjectURL(url);
    }

    renderSessionList() {
        const sessions = Array.from(this.sessions.values())
            .map((session) => this.upgradeSession(session))
            .sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt));

        this.sessionList.innerHTML = "";
        sessions.forEach((session) => {
            const preview = session.transcript.at(-1)?.content || "Start a new thread...";
            const item = document.createElement("button");
            item.type = "button";
            item.className = `session-item${session.id === this.currentSessionId ? " active" : ""}`;
            item.innerHTML = `
                <span class="session-active-indicator" aria-hidden="true"></span>
                <div class="session-name">${this.escapeHtml(session.title)}</div>
                <div class="session-preview">${this.escapeHtml(preview.slice(0, 90))}</div>
            `;
            item.addEventListener("click", () => this.switchSession(session.id));
            this.sessionList.appendChild(item);
        });
    }

    getFilteredTranscriptEntries() {
        const session = this.getCurrentSession();
        if (!session) {
            return [];
        }
        const selectedTaskId = this.store.get().selectedTaskId;
        const filter = this.store.get().transcriptFilter;
        const taskScoped = selectedTaskId === "main"
            ? session.transcript
            : session.transcript.filter((entry) => entry.taskId === selectedTaskId);

        return taskScoped.filter((entry) => {
            if (entry.kind === "tool_use" || entry.kind === "tool_result") return false;
            if (filter === "all") return true;
            if (filter === "tool") return entry.kind === "tool_use" || entry.kind === "tool_result";
            if (filter === "system") return entry.kind === "system_notice";
            if (filter === "assistant") {
                return entry.role === "assistant" && (entry.kind === "assistant_text" || entry.kind === "thinking_text");
            }
            if (filter === "user") return entry.role === "user";
            return true;
        });
    }

    renderTranscript(preserveScroll = false) {
        const selectedTaskId = this.store.get().selectedTaskId;
        this.transcriptTitle.textContent = selectedTaskId === "main" ? "Conversation" : selectedTaskId;
        this.returnMainBtn.classList.toggle("hidden", selectedTaskId === "main");
        this.chatMessages.innerHTML = "";

        const entries = this.buildRenderEntries(this.getFilteredTranscriptEntries());
        if (entries.length === 0) {
            const empty = document.createElement("div");
            empty.className = "transcript-empty";
            empty.textContent = "No transcript items yet. Start with a task request, or switch to Plan mode to generate a structured task graph first.";
            this.chatMessages.appendChild(empty);
            return;
        }

        const list = document.createElement("div");
        list.className = "message-list";
        entries.forEach((entry) => this.renderTranscriptEntry(entry, list));
        this.chatMessages.appendChild(list);

        if (!preserveScroll) {
            this.scrollMessagesToBottom();
        }
    }

    buildRenderEntries(entries) {
        return [...entries];
    }

    renderMarkdown(text) {
        const source = String(text || "").replace(/\r\n/g, "\n").trim();
        if (!source) return "";

        const lines = source.split("\n");
        const html = [];
        let index = 0;

        const renderInline = (value) => {
            let escaped = this.escapeHtml(value);
            escaped = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
            escaped = escaped.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
            escaped = escaped.replace(/\*([^*]+)\*/g, "<em>$1</em>");
            escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>');
            return escaped;
        };

        while (index < lines.length) {
            const line = lines[index];
            const trimmed = line.trim();

            if (!trimmed) {
                index += 1;
                continue;
            }

            if (trimmed.startsWith("```")) {
                const codeLines = [];
                index += 1;
                while (index < lines.length && !lines[index].trim().startsWith("```")) {
                    codeLines.push(lines[index]);
                    index += 1;
                }
                if (index < lines.length) index += 1;
                html.push(`<pre><code>${this.escapeHtml(codeLines.join("\n"))}</code></pre>`);
                continue;
            }

            const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
            if (headingMatch) {
                const level = headingMatch[1].length;
                html.push(`<h${level}>${renderInline(headingMatch[2])}</h${level}>`);
                index += 1;
                continue;
            }

            if (/^\d+\.\s+/.test(trimmed)) {
                const items = [];
                while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
                    items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
                    index += 1;
                }
                html.push(`<ol>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
                continue;
            }

            if (/^[-*+]\s+/.test(trimmed)) {
                const items = [];
                while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) {
                    items.push(lines[index].trim().replace(/^[-*+]\s+/, ""));
                    index += 1;
                }
                html.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
                continue;
            }

            if (/^>\s+/.test(trimmed)) {
                const quotes = [];
                while (index < lines.length && /^>\s+/.test(lines[index].trim())) {
                    quotes.push(lines[index].trim().replace(/^>\s+/, ""));
                    index += 1;
                }
                html.push(`<blockquote>${quotes.map((item) => renderInline(item)).join("<br>")}</blockquote>`);
                continue;
            }

            const paragraphLines = [];
            while (index < lines.length && lines[index].trim()) {
                paragraphLines.push(lines[index].trim());
                index += 1;
            }
            html.push(`<p>${renderInline(paragraphLines.join("\n")).replace(/\n/g, "<br>")}</p>`);
        }

        return html.join("");
    }

    setMessageBodyContent(target, text, entry) {
        if (entry.kind === "thinking_text" && entry.pendingPlaceholder && !String(text || "").trim()) {
            target.innerHTML = `
                <div class="thinking-pending">
                    <span class="thinking-pending-label">Waiting for first reasoning token</span>
                    <span class="thinking-pending-dots" aria-hidden="true">
                        <span></span><span></span><span></span>
                    </span>
                </div>
            `;
            return;
        }
        if (entry.kind === "system_notice" && entry.phase === "compression") {
            target.innerHTML = `
                <div class="compression-inline">
                    <span class="compression-spinner"><i class="fas fa-spinner"></i></span>
                    <span>${this.escapeHtml(text || "Compressing context...")}</span>
                </div>
            `;
            return;
        }
        const supportsMarkdown = ["assistant_text", "system_notice", "tool_result"].includes(entry.kind);
        if (supportsMarkdown) {
            target.innerHTML = this.renderMarkdown(text);
            return;
        }
        target.textContent = text;
    }

    renderTranscriptEntry(entry, parent) {
        const wrapper = document.createElement("article");
        wrapper.className = `message ${this.mapEntryRole(entry)}`;
        if (entry.kind === "system_notice" && entry.phase === "compression") {
            wrapper.classList.add("compression-notice");
        }
        if (entry.taskId && entry.taskId !== "main" && entry.taskId === this.store.get().selectedTaskId) {
            wrapper.classList.add("active-task");
        }
        const meta = document.createElement("div");
        meta.className = "message-meta";
        const metaLabel = document.createElement("span");
        metaLabel.textContent = this.getEntryLabel(entry);
        const metaTime = document.createElement("span");
        metaTime.textContent = new Date(entry.timestamp || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        meta.append(metaLabel, metaTime);
        if (entry.kind === "tool_use" || entry.kind === "tool_result") {
            const state = document.createElement("span");
            state.className = `message-state ${entry.kind === "tool_use" ? "running" : (entry.success === false ? "error" : "done")}`;
            state.textContent = entry.kind === "tool_use" ? "running" : (entry.success === false ? "error" : "done");
            meta.appendChild(state);
        }

        const body = document.createElement("div");
        const isThinkingEntry = entry.kind === "thinking_text";
        const isCollapsible = isThinkingEntry;
        const isPinnedThinking = isThinkingEntry && this.pinnedThinkingMessages.has(entry.id);
        const isCollapsed = isCollapsible && !(isPinnedThinking || this.collapsedMessages.has(entry.id));
        const displayContent = entry.content || "";
        body.className = `message-body${entry.streaming ? " is-streaming" : ""}${isCollapsed ? " collapsed" : ""}`;
        this.setMessageBodyContent(body, displayContent, entry);
        if (isCollapsible) {
            body.style.maxHeight = isCollapsed ? "0px" : `${Math.max(body.scrollHeight + 24, 160)}px`;
            body.style.opacity = isCollapsed ? "0" : "1";
        }

        wrapper.appendChild(meta);
        let summary = null;
        if (isThinkingEntry) {
            summary = document.createElement("div");
            summary.className = "thinking-summary";
            summary.textContent = this.getThinkingSummary(entry.content, entry.streaming);
            summary.style.maxHeight = isCollapsed ? "72px" : "0px";
            summary.style.opacity = isCollapsed ? "1" : "0";
            wrapper.appendChild(summary);
        }
        if (entry.kind === "tool_use" || entry.kind === "tool_result") {
            wrapper.appendChild(this.buildToolCard(entry));
        }
        wrapper.appendChild(body);

        const actions = document.createElement("div");
        actions.className = "message-actions";

        if (isCollapsible) {
            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = isThinkingEntry ? "message-toggle thinking-toggle" : "message-toggle";
            if (isThinkingEntry) {
                toggle.innerHTML = `<i class="fas fa-chevron-${isCollapsed ? "down" : "up"}" aria-hidden="true"></i>`;
                toggle.classList.toggle("expanded", !isCollapsed);
                toggle.setAttribute("aria-label", isCollapsed ? "Expand thinking" : "Collapse thinking");
                toggle.title = isCollapsed ? "Expand thinking" : "Collapse thinking";
            } else {
                toggle.textContent = isCollapsed ? "Expand" : "Collapse";
            }
            toggle.addEventListener("click", () => {
                if (isThinkingEntry) {
                    const willExpand = !this.pinnedThinkingMessages.has(entry.id);
                    if (willExpand) {
                        this.pinnedThinkingMessages.add(entry.id);
                    } else {
                        this.pinnedThinkingMessages.delete(entry.id);
                    }
                    this.animateThinkingToggle({ wrapper, body, summary, toggle, entry, expand: willExpand });
                }
            });
            actions.appendChild(toggle);
        }

        if (entry.role === "user" || entry.kind === "tool_result") {
            const replay = document.createElement("button");
            replay.type = "button";
            replay.className = "message-toggle";
            replay.textContent = "Replay";
            replay.addEventListener("click", () => {
                this.messageInput.value = entry.content || "";
                this.autoResizeInput();
                this.messageInput.focus();
            });
            actions.appendChild(replay);
        }

        if (actions.children.length > 0) {
            wrapper.appendChild(actions);
        }

        parent.appendChild(wrapper);
    }

    animateThinkingToggle({ wrapper, body, summary, toggle, entry, expand }) {
        wrapper.classList.toggle("thinking-expanded", expand);
        body.classList.toggle("collapsed", !expand);
        toggle.innerHTML = `<i class="fas fa-chevron-${expand ? "up" : "down"}" aria-hidden="true"></i>`;
        toggle.classList.toggle("expanded", expand);
        toggle.setAttribute("aria-label", expand ? "Collapse thinking" : "Expand thinking");
        toggle.title = expand ? "Collapse thinking" : "Expand thinking";

        const fullHeight = `${Math.max(body.scrollHeight + 24, 160)}px`;
        body.style.maxHeight = expand ? "0px" : fullHeight;
        if (summary) {
            summary.style.maxHeight = expand ? "72px" : `${Math.max(summary.scrollHeight + 16, 56)}px`;
        }
        requestAnimationFrame(() => {
            body.style.maxHeight = expand ? fullHeight : "0px";
            body.style.opacity = expand ? "1" : "0";
            if (summary) {
                summary.style.maxHeight = expand ? "0px" : "72px";
                summary.style.opacity = expand ? "0" : "1";
            }
        });

        window.setTimeout(() => {
            if (expand) {
                body.style.maxHeight = "none";
            }
            this.updateTranscriptEntry(entry.id, {});
        }, 220);
    }

    buildToolCard(entry) {
        const card = document.createElement("div");
        card.className = `tool-card ${entry.kind}`;

        const statusIcon = document.createElement("div");
        statusIcon.className = `tool-card-icon ${entry.kind === "tool_use" ? "running" : (entry.success === false ? "error" : "done")}`;
        statusIcon.innerHTML = entry.kind === "tool_use"
            ? '<i class="fas fa-spinner"></i>'
            : (entry.success === false ? '<i class="fas fa-triangle-exclamation"></i>' : '<i class="fas fa-check"></i>');
        card.appendChild(statusIcon);

        const contentWrap = document.createElement("div");
        contentWrap.className = "tool-card-content";

        const title = document.createElement("div");
        title.className = "tool-card-title";
        title.textContent = entry.toolName || entry.taskId || "tool";
        contentWrap.appendChild(title);

        const subtitle = document.createElement("div");
        subtitle.className = "tool-card-subtitle";
        subtitle.textContent = entry.kind === "tool_use"
            ? "Invoking tool"
            : (entry.success === false ? "Tool finished with an error" : "Tool result captured");
        contentWrap.appendChild(subtitle);

        if (entry.taskId) {
            const pillRow = document.createElement("div");
            pillRow.className = "tool-card-pills";
            const taskPill = document.createElement("span");
            taskPill.className = "tool-card-pill";
            taskPill.textContent = entry.taskId;
            pillRow.appendChild(taskPill);
            if (entry.phase) {
                const phasePill = document.createElement("span");
                phasePill.className = "tool-card-pill";
                phasePill.textContent = entry.phase;
                pillRow.appendChild(phasePill);
            }
            contentWrap.appendChild(pillRow);
        }

        card.appendChild(contentWrap);
        return card;
    }

    mapEntryRole(entry) {
        if (entry.kind === "thinking_text") return "thinking";
        if (entry.kind === "tool_use") return "tool";
        if (entry.kind === "tool_result") return "tool-result";
        if (entry.kind === "system_notice") return "system";
        return entry.role === "user" ? "user" : "assistant";
    }

    getEntryLabel(entry) {
        if (entry.kind === "thinking_text") return "Thinking";
        if (entry.kind === "tool_use") return `Task · ${entry.toolName || entry.taskId || "tool"}`;
        if (entry.kind === "tool_result") return `Result · ${entry.toolName || entry.taskId || "tool"}`;
        if (entry.kind === "system_notice") return "System";
        return entry.role === "user" ? "User" : "OBS";
    }

    addTranscriptEntry(entry) {
        const session = this.getCurrentSession();
        if (!session) return null;

        const normalized = {
            id: entry.id || `entry_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
            role: entry.role || "assistant",
            content: entry.content || "",
            kind: entry.kind || "assistant_text",
            taskId: entry.taskId || "main",
            toolName: entry.toolName || null,
            phase: entry.phase || null,
            success: entry.success,
            pendingPlaceholder: Boolean(entry.pendingPlaceholder),
            timestamp: entry.timestamp || new Date().toISOString(),
            streaming: Boolean(entry.streaming)
        };
        session.transcript.push(normalized);
        session.updatedAt = new Date().toISOString();
        this.persistSessions();
        this.renderTranscript();
        this.renderLogs();
        this.renderSessionList();
        this.renderPhaseRail();
        this.refreshContextPercent();
        this.updateStatusLine();
        return normalized;
    }

    updateTranscriptEntry(entryId, patch) {
        const session = this.getCurrentSession();
        if (!session) return;

        const target = session.transcript.find((entry) => entry.id === entryId);
        if (!target) return;

        Object.assign(target, patch);
        if (target.kind === "thinking_text" && patch.streaming === false && !this.pinnedThinkingMessages.has(entryId)) {
            this.collapsedMessages.delete(entryId);
        }
        session.updatedAt = new Date().toISOString();
        this.persistSessions();
        this.renderTranscript(true);
        this.renderLogs();
        this.renderSessionList();
        this.renderPhaseRail();
        this.refreshContextPercent();
        this.updateStatusLine();
    }

    removeTranscriptEntry(entryId) {
        const session = this.getCurrentSession();
        if (!session) return;

        const nextTranscript = session.transcript.filter((entry) => entry.id !== entryId);
        if (nextTranscript.length === session.transcript.length) {
            return;
        }

        session.transcript = nextTranscript;
        session.updatedAt = new Date().toISOString();
        this.persistSessions();
        this.renderTranscript(true);
        this.renderLogs();
        this.renderSessionList();
        this.renderPhaseRail();
        this.refreshContextPercent();
        this.updateStatusLine();
    }

    getCurrentWorkflowPhase() {
        const session = this.getCurrentSession();
        if (!session) return null;
        const phaseEntries = [...session.transcript].reverse().filter((entry) => entry.phase);
        return phaseEntries[0]?.phase || null;
    }

    renderPhaseRail() {
        if (this.phaseRail) {
            this.phaseRail.classList.add("hidden");
        }
    }

    handleSubmitRequest() {
        const content = this.messageInput.value.trim();
        if (!content) return;

        const permissionMode = this.getEffectivePermissionMode();
        const shouldAsk = permissionMode === "ask" && this.mightNeedTooling(content) && !this.permissionConfirmedForSubmit;
        if (shouldAsk) {
            this.pendingPermissionAction = () => this.sendMessage();
            this.openPermissionModal();
            return;
        }
        this.sendMessage();
    }

    mightNeedTooling(content) {
        return /(run|test|edit|file|search|grep|bash|command|docker|fix|review|修复|修改|测试|搜索|执行|命令|文件|审查)/i.test(content);
    }

    isSimpleChat(content) {
        return /^(hi|hello|hey|你好|嗨|在吗|早上好|下午好|晚上好)\W*$/i.test((content || "").trim());
    }

    getEffectivePermissionMode() {
        const state = this.store.get();
        if (state.mode === "review" && state.permissionMode === "ask") {
            return "plan";
        }
        return state.permissionMode;
    }

    getEffectiveMode(content) {
        const selectedMode = this.store.get().mode;
        if (this.isSimpleChat(content)) {
            return "agent";
        }
        return selectedMode;
    }

    buildContextPayload() {
        const { toolContext } = this.store.get();
        const contextMap = {
            computer: "Focus on visual/browser/computer-use context. Prefer screenshot, page-state, and UI interaction reasoning when relevant.",
            workspace: "Focus on the current workspace, local files, directories, code structure, and repository state.",
            agents: "Focus on agent coordination, task breakdown, review flow, and multi-step execution planning only when the request actually requires it."
        };
        return {
            toolContext,
            context: contextMap[toolContext] || contextMap.workspace
        };
    }

    getThinkingSummary(content, streaming = false) {
        const normalized = (content || "").replace(/\s+/g, " ").trim();
        if (!normalized) {
            return streaming ? "Analyzing request..." : "Reasoning captured.";
        }

        const firstSentence = normalized.split(/(?<=[.!?。！？])\s/)[0] || normalized;
        const clipped = firstSentence.length > 110 ? `${firstSentence.slice(0, 110)}...` : firstSentence;
        return streaming ? `${clipped} · streaming` : clipped;
    }

    parseAssistantStream(rawText) {
        const openTag = "<think>";
        const closeTag = "</think>";
        const openIndex = rawText.indexOf(openTag);

        if (openIndex === -1) {
            return {
                hasThinking: false,
                thinkingText: "",
                answerText: rawText,
                inThinking: false
            };
        }

        const beforeOpen = rawText.slice(0, openIndex);
        const afterOpen = rawText.slice(openIndex + openTag.length);
        const closeIndex = afterOpen.indexOf(closeTag);

        if (closeIndex === -1) {
            return {
                hasThinking: true,
                thinkingText: afterOpen.trimStart(),
                answerText: beforeOpen.trim(),
                inThinking: true
            };
        }

        const thinkingText = afterOpen.slice(0, closeIndex).trim();
        const afterClose = afterOpen.slice(closeIndex + closeTag.length);

        return {
            hasThinking: true,
            thinkingText,
            answerText: `${beforeOpen}${afterClose}`.trim(),
            inThinking: false
        };
    }

    async sendMessage() {
        if (this.isSending) return;

        const content = this.messageInput.value.trim();
        if (!content) return;

        const session = this.getCurrentSession();
        if (!session) return;

        const permissionConfirmed = this.permissionConfirmedForSubmit;
        const effectivePermissionMode = this.getEffectivePermissionMode();
        this.permissionConfirmedForSubmit = false;
        this.isSending = true;
        this.setSendingState(true);
        this.toggleWelcome(false);
        const requestMode = this.getEffectiveMode(content);
        const { toolContext, context } = this.buildContextPayload();

        this.addTranscriptEntry({
            role: "user",
            content,
            kind: "user_text",
            taskId: "main"
        });

        if (session.transcript.length <= 1) {
            session.title = content.slice(0, 36);
            this.currentSessionTitle.textContent = session.title;
        }

        this.bumpContextPercent(content);
        if (requestMode !== this.store.get().mode) {
            this.store.set({ mode: requestMode });
            this.renderModePills();
        }

        this.messageInput.value = "";
        this.autoResizeInput();
        this.resetTasks();

        let assistantEntry = null;
        let thinkingEntry = null;
        let answerBuffer = "";
        let workflowNoticeEntry = null;

        try {
            if (requestMode === "review") {
                workflowNoticeEntry = this.addTranscriptEntry({
                    role: "assistant",
                    content: "Review workflow queued. Building execution plan and waiting for the first phase update...",
                    kind: "system_notice",
                    taskId: "main",
                    phase: "queued"
                });
            } else if (requestMode === "plan") {
                workflowNoticeEntry = this.addTranscriptEntry({
                    role: "assistant",
                    content: "Planning workflow queued. Generating task graph and coordinator outline...",
                    kind: "system_notice",
                    taskId: "main",
                    phase: "queued"
                });
            } else {
                assistantEntry = null;
            }

            if (this.store.get().thinkingMode && !thinkingEntry) {
                thinkingEntry = this.addTranscriptEntry({
                    role: "assistant",
                    content: "",
                    kind: "thinking_text",
                    taskId: "main",
                    streaming: true,
                    pendingPlaceholder: true
                });
            }

            const response = await fetch(`${this.settings.apiUrl}/chat/stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tool_name: "chat",
                    message: content,
                    session_id: this.currentSessionId,
                    permission_mode: effectivePermissionMode,
                    permission_confirmed: permissionConfirmed || effectivePermissionMode !== "ask",
                    thinking_mode: this.store.get().thinkingMode,
                    mode: requestMode,
                    tool_context: toolContext,
                    context,
                    parameters: {
                        message: content,
                        session_id: this.currentSessionId,
                        permission_mode: effectivePermissionMode,
                        permission_confirmed: permissionConfirmed || effectivePermissionMode !== "ask",
                        thinking_mode: this.store.get().thinkingMode,
                        mode: requestMode,
                        tool_context: toolContext,
                        context
                    }
                })
            });

            if (!response.ok || !response.body) {
                throw new Error(`HTTP ${response.status}`);
            }

            const processSseChunk = (chunkText) => {
                const line = chunkText.split("\n").find((part) => part.startsWith("data: "));
                if (!line) return;

                const payload = JSON.parse(line.slice(6));

                if (payload.type === "plan") {
                    const planText = this.formatPlanPayload(payload);
                    if (!assistantEntry) {
                        assistantEntry = this.addTranscriptEntry({
                            role: "assistant",
                            content: planText,
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: false
                        });
                    } else {
                        this.updateTranscriptEntry(assistantEntry.id, {
                            content: planText,
                            streaming: false
                        });
                    }
                    return;
                }

                if (payload.type === "task_start") {
                    const task = this.registerTask(
                        payload.task_id || `task_${Date.now()}`,
                        payload.description || payload.skill || "Task"
                    );
                    this.addTranscriptEntry({
                        role: "assistant",
                        content: payload.description || `Started ${task.title}`,
                        kind: "tool_use",
                        taskId: task.id,
                        toolName: payload.skill || task.title,
                        phase: payload.phase || "execution"
                    });
                    return;
                }

                if (payload.type === "task_complete") {
                    const task = this.completeTaskById(
                        payload.task_id,
                        payload.success,
                        payload.content || payload.description || "Task completed."
                    );
                    if (task) {
                        this.addTranscriptEntry({
                            role: "assistant",
                            content: payload.content || "Task completed.",
                            kind: "tool_result",
                            taskId: task.id,
                            toolName: task.title,
                            phase: payload.phase || "execution",
                            success: payload.success
                        });
                    }
                    return;
                }

                if (payload.type === "phase" || payload.type === "layer_start" || payload.type === "verification" || payload.type === "complete") {
                    if (workflowNoticeEntry) {
                        this.updateTranscriptEntry(workflowNoticeEntry.id, {
                            content: payload.content || payload.phase || "System update",
                            phase: payload.phase || null
                        });
                        workflowNoticeEntry = null;
                    }
                    this.addTranscriptEntry({
                        role: "assistant",
                        content: payload.content || payload.phase || "System update",
                        kind: "system_notice",
                        taskId: "main",
                        phase: payload.phase || null
                    });
                    return;
                }

                if (payload.type === "compression_start" || payload.type === "compression_complete") {
                    const session = this.getCurrentSession();
                    this.addTranscriptEntry({
                        role: "assistant",
                        content: payload.content || (payload.type === "compression_start" ? "Compressing context..." : "Context compression complete."),
                        kind: "system_notice",
                        taskId: "main",
                        phase: payload.type === "compression_start" ? "compression" : "complete"
                    });
                    const nextPercent = payload.type === "compression_complete"
                        ? (payload.after_percent ?? this.store.get().contextPercent)
                        : (payload.target_percent ?? this.store.get().contextPercent);
                    if (session) {
                        session.contextPercentOverride = nextPercent;
                        this.persistSessions();
                    }
                    this.store.set({ contextPercent: nextPercent });
                    this.contextPill.textContent = `Context · ${nextPercent}%`;
                    return;
                }

                if (payload.type === "llm_log") {
                    this.appendSessionLog({
                        type: "llm_log",
                        timestamp: payload.timestamp || new Date().toISOString(),
                        phase: payload.phase,
                        direction: payload.direction,
                        payload: payload.payload
                    });
                    if (this.logsDrawer && !this.logsDrawer.classList.contains("hidden")) {
                        this.refreshLogsFromBackend();
                    }
                    return;
                }

                if (payload.type === "thinking_delta") {
                    if (!this.store.get().thinkingMode) {
                        return;
                    }
                    const nextThinking = `${thinkingEntry?.content || ""}${payload.delta || ""}`;
                    if (!thinkingEntry) {
                        thinkingEntry = this.addTranscriptEntry({
                            role: "assistant",
                            content: nextThinking,
                            kind: "thinking_text",
                            taskId: "main",
                            streaming: true
                        });
                    } else {
                        this.updateTranscriptEntry(thinkingEntry.id, {
                            content: nextThinking,
                            streaming: true,
                            pendingPlaceholder: false
                        });
                    }
                    return;
                }

                if (payload.type === "answer_delta") {
                    answerBuffer += payload.delta || "";
                    if (!answerBuffer.trim()) {
                        return;
                    }
                    if (!assistantEntry) {
                        assistantEntry = this.addTranscriptEntry({
                            role: "assistant",
                            content: answerBuffer,
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: true
                        });
                    } else {
                        this.updateTranscriptEntry(assistantEntry.id, {
                            content: answerBuffer,
                            streaming: true
                        });
                    }
                    return;
                }

                if (payload.content) {
                    answerBuffer += payload.content || "";
                    if (!answerBuffer.trim()) {
                        return;
                    }
                    if (!assistantEntry) {
                        assistantEntry = this.addTranscriptEntry({
                            role: "assistant",
                            content: answerBuffer,
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: true
                        });
                    } else {
                        this.updateTranscriptEntry(assistantEntry.id, {
                            content: answerBuffer,
                            streaming: true
                        });
                    }
                }

                if (payload.error) {
                    throw new Error(payload.error);
                }

                if (payload.done) {
                    if (workflowNoticeEntry) {
                        this.updateTranscriptEntry(workflowNoticeEntry.id, {
                            content: requestMode === "review"
                                ? "Review workflow finished waiting for planner output."
                                : "Planning workflow finished waiting for planner output."
                        });
                        workflowNoticeEntry = null;
                    }
                    if (assistantEntry) {
                        this.updateTranscriptEntry(assistantEntry.id, { streaming: false });
                    } else if (answerBuffer.trim()) {
                        assistantEntry = this.addTranscriptEntry({
                            role: "assistant",
                            content: answerBuffer.trim(),
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: false
                        });
                    } else if (!payload.error) {
                        throw new Error("模型没有返回可显示的正文");
                    }
                    if (thinkingEntry) {
                        if (thinkingEntry.pendingPlaceholder && !(thinkingEntry.content || "").trim()) {
                            this.removeTranscriptEntry(thinkingEntry.id);
                            thinkingEntry = null;
                        } else {
                            this.updateTranscriptEntry(thinkingEntry.id, {
                                streaming: false,
                                pendingPlaceholder: false
                            });
                        }
                    }
                }
            };
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (value) {
                    buffer += decoder.decode(value, { stream: !done });
                }

                // 更即时地处理每一行，不等待完整的 chunk
                const normalizedBuffer = buffer.replace(/\r\n/g, "\n");
                const lines = normalizedBuffer.split("\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    const trimmedLine = line.trim();
                    if (trimmedLine && trimmedLine.startsWith("data: ")) {
                        processSseChunk(trimmedLine);
                    }
                }

                if (done) {
                    const tail = buffer.trim();
                    if (tail && tail.startsWith("data: ")) {
                        processSseChunk(tail);
                    }
                    break;
                }
            }

            if (assistantEntry) {
                this.updateTranscriptEntry(assistantEntry.id, { streaming: false });
            }
            if (thinkingEntry) {
                if (thinkingEntry.pendingPlaceholder && !(thinkingEntry.content || "").trim()) {
                    this.removeTranscriptEntry(thinkingEntry.id);
                } else {
                    this.updateTranscriptEntry(thinkingEntry.id, {
                        streaming: false,
                        pendingPlaceholder: false
                    });
                }
            }
        } catch (error) {
            if (workflowNoticeEntry) {
                this.updateTranscriptEntry(workflowNoticeEntry.id, {
                    content: `Workflow interrupted: ${error.message}`
                });
            }
            if (thinkingEntry) {
                if (thinkingEntry.pendingPlaceholder && !(thinkingEntry.content || "").trim()) {
                    this.removeTranscriptEntry(thinkingEntry.id);
                } else {
                    this.updateTranscriptEntry(thinkingEntry.id, {
                        streaming: false,
                        pendingPlaceholder: false
                    });
                }
            }
            this.addTranscriptEntry({
                role: "assistant",
                content: `请求失败: ${error.message}`,
                kind: "assistant_text",
                taskId: "main",
                streaming: false
            });
        } finally {
            this.isSending = false;
            this.setSendingState(false);
            this.updateStatusLine();
        }
    }

    setSendingState(isSending) {
        this.sendBtn.disabled = isSending;
        this.sendBtn.classList.toggle("is-sending", isSending);
        this.sendBtn.innerHTML = isSending
            ? '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>'
            : '<i class="fas fa-arrow-up" aria-hidden="true"></i>';
    }

    formatPlanPayload(payload) {
        const plan = payload.plan || {};
        const tasks = payload.task_graph?.tasks || [];
        const lines = [];
        if (plan.reasoning) {
            lines.push(plan.reasoning);
            lines.push("");
        }
        lines.push("Planned tasks:");
        tasks.forEach((task) => {
            lines.push(`- ${task.task_id}: ${task.description || task.action}`);
        });
        return lines.join("\n");
    }

    getPendingAssistantText() {
        const mode = this.store.get().mode;
        if (mode === "plan") {
            return "Planning task graph and execution outline...";
        }
        if (mode === "review") {
            return "Reviewing the request and preparing structured execution...";
        }
        return "Thinking...";
    }

    registerTask(taskId, title) {
        const session = this.getCurrentSession();
        if (!session) return null;

        const existing = session.tasks[taskId];
        const task = existing || {
            id: taskId,
            title,
            state: "running",
            detail: "Running task",
            startedAt: Date.now()
        };
        task.title = title || task.title;
        task.state = "running";
        task.phase = "execution";
        session.tasks[taskId] = task;
        this.store.set({ tasks: Object.values(session.tasks) });
        this.renderTasks();
        this.renderTranscript();
        return task;
    }

    completeTaskById(taskId, success, detail) {
        const session = this.getCurrentSession();
        if (!session || !session.tasks[taskId]) return null;

        const task = session.tasks[taskId];
        task.state = success ? "done" : "error";
        task.detail = detail || task.detail;
        task.finishedAt = Date.now();
        this.store.set({ tasks: Object.values(session.tasks) });
        this.renderTasks();
        this.updateStatusLine();
        return task;
    }

    resetTasks() {
        const session = this.getCurrentSession();
        if (!session) return;

        session.tasks = {};
        this.store.set({ tasks: [], selectedTaskId: "main" });
        this.renderTasks();
        this.updateStatusLine();
    }

    selectTask(taskId) {
        this.store.set({ selectedTaskId: taskId });
        this.renderTasks();
        this.renderTranscript();
    }

    renderTasks() {
        const session = this.getCurrentSession();
        const tasks = session ? Object.values(session.tasks) : [];
        const selectedTaskId = this.store.get().selectedTaskId;

        this.taskCount.textContent = `${tasks.length} tasks`;
        this.selectedTaskLabel.textContent = selectedTaskId;
        this.taskStrip.innerHTML = "";

        const mainButton = document.createElement("button");
        mainButton.type = "button";
        mainButton.className = `task-pill main${selectedTaskId === "main" ? " active" : ""}`;
        mainButton.textContent = "main";
        mainButton.addEventListener("click", () => this.selectTask("main"));
        this.taskStrip.appendChild(mainButton);

        tasks.forEach((task) => {
            const pill = document.createElement("button");
            pill.type = "button";
            pill.className = `task-pill ${task.state}${task.state === "running" ? " pulse" : ""}${selectedTaskId === task.id ? " active" : ""}`;
            pill.textContent = task.id;
            pill.addEventListener("click", () => this.selectTask(task.id));
            this.taskStrip.appendChild(pill);
        });

        this.taskList.innerHTML = "";
        const visibleTasks = selectedTaskId === "main" ? tasks : tasks.filter((task) => task.id === selectedTaskId);
        if (visibleTasks.length === 0) {
            this.taskList.innerHTML = '<p class="panel-empty">Tool runs and agent steps will appear here.</p>';
            return;
        }

        visibleTasks.forEach((task) => {
            const item = document.createElement("div");
            item.className = `task-item ${task.state}${selectedTaskId === task.id ? " active" : ""}`;
            const duration = task.finishedAt && task.startedAt
                ? ` · ${Math.max(1, Math.round((task.finishedAt - task.startedAt) / 1000))}s`
                : "";
            item.innerHTML = `
                <div class="task-title">${this.escapeHtml(task.title)}</div>
                <div class="task-meta">${this.escapeHtml(task.detail || "")}${duration}</div>
            `;
            item.addEventListener("click", () => this.selectTask(task.id));
            this.taskList.appendChild(item);
        });
        this.renderTranscript();
    }

    openPermissionModal() {
        this.permissionModal.classList.remove("hidden");
        const currentMode = this.store.get().permissionMode;
        const effectiveMode = this.getEffectivePermissionMode();
        const currentTask = this.messageInput.value.trim();
        document.querySelectorAll(".permission-option").forEach((button) => {
            button.classList.toggle("active", button.dataset.permissionMode === currentMode);
        });
        this.permissionModalCopy.textContent = currentTask
            ? `当前请求可能会调用工具：${currentTask.slice(0, 80)}${currentTask.length > 80 ? "..." : ""}`
            : "选择这次请求的执行方式。你可以只确认一次，也可以直接切换到更顺滑的工作流模式。";
        this.permissionOnceBtn.textContent = effectiveMode === "ask" ? "Continue Once" : `Continue with ${effectiveMode}`;
    }

    closePermissionModal() {
        this.permissionModal.classList.add("hidden");
    }

    renderPermissionState() {
        const { permissionMode, runtime, mode } = this.store.get();
        const effectiveMode = this.getEffectivePermissionMode();
        this.permissionModeBtn.textContent = `Permission · ${permissionMode}`;
        this.permissionSummary.textContent = effectiveMode === permissionMode ? permissionMode : `${permissionMode} -> ${effectiveMode}`;
        this.policyFiles.textContent = effectiveMode === "plan"
            ? "read-only"
            : runtime?.allow_file_operations ? "enabled" : "blocked";
        this.policyTerminal.textContent = effectiveMode === "plan"
            ? "planning"
            : runtime?.allow_terminal_execution ? "enabled" : "blocked";
        this.policyComputer.textContent = effectiveMode === "plan"
            ? "planning"
            : runtime?.enable_computer_use ? "enabled" : "blocked";
        this.permissionModeBtn.classList.toggle("active", mode === "review" && permissionMode === "ask");
    }

    renderThinkingMode() {
        const thinkingOn = this.store.get().thinkingMode;
        this.thinkingModeBtn.classList.toggle("active", thinkingOn);
        this.thinkingModeBtn.textContent = `Thinking · ${thinkingOn ? "on" : "off"}`;
    }

    renderModePills() {
        const mode = this.store.get().mode;
        if (this.modeSelect) {
            this.modeSelect.value = mode;
        }
    }

    async refreshRuntime() {
        try {
            const [healthResponse, runtimeResponse] = await Promise.all([
                fetch(`${this.settings.apiUrl}/health`),
                fetch(`${this.settings.apiUrl}/runtime`)
            ]);
            if (!healthResponse.ok || !runtimeResponse.ok) {
                throw new Error("runtime unavailable");
            }

            const health = await healthResponse.json();
            const runtimePayload = await runtimeResponse.json();
            const runtime = runtimePayload.runtime || null;
            this.store.set({ runtime });

            this.agentStatus.classList.add("online");
            this.agentStatus.classList.remove("offline");
            this.agentStatus.lastElementChild.textContent = "Runtime online";
            this.runtimeBadge.textContent = runtimePayload.status || "ok";
            this.runtimeApi.textContent = health.status || "ok";
            this.runtimeModel.textContent = this.shortenModel(runtime?.model);
            this.runtimeWorkdir.textContent = runtime?.work_dir || "--";
            this.runtimeSkills.textContent = `${runtime?.skills_count || 0} loaded`;
            this.runtimeTools.textContent = [
                runtime?.enable_bash ? "bash" : null,
                runtime?.enable_text_editor ? "edit" : null,
                runtime?.enable_computer_use ? "computer" : null
            ].filter(Boolean).join(" · ") || "--";

            this.modelPill.textContent = `Model · ${this.shortenModel(runtime?.model)}`;
            this.modelBadge.textContent = this.shortenModel(runtime?.model);
            this.renderPermissionState();
            this.updateStatusLine();
        } catch (error) {
            this.agentStatus.classList.add("offline");
            this.agentStatus.classList.remove("online");
            this.agentStatus.lastElementChild.textContent = "Runtime offline";
            this.runtimeBadge.textContent = "offline";
            this.runtimeApi.textContent = "unreachable";
        }
    }

    async fetchSkills() {
        try {
            const response = await fetch(`${this.settings.apiUrl}/skills`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const payload = await response.json();
            const skills = this.deduplicateSkills(payload.skills || []);
            this.skillsCount.textContent = String(skills.length);
            this.skillsList.innerHTML = "";

            if (skills.length === 0) {
                this.skillsList.innerHTML = '<p class="panel-empty">No tools reported by the backend.</p>';
                return;
            }

            skills.slice(0, 12).forEach((skill) => {
                const item = document.createElement("div");
                item.className = "skill-item";
                item.innerHTML = `
                    <div class="skill-name">${this.escapeHtml(skill.name || "unknown")}</div>
                    <div class="skill-description">${this.escapeHtml(skill.description || "No description")}</div>
                `;
                this.skillsList.appendChild(item);
            });
        } catch (error) {
            this.skillsList.innerHTML = '<p class="panel-empty">Failed to load skills.</p>';
        }
    }

    deduplicateSkills(skills) {
        const seen = new Set();
        return skills.filter((skill) => {
            const key = [skill?.name || "", skill?.description || ""].join("::");
            if (seen.has(key)) {
                return false;
            }
            seen.add(key);
            return true;
        });
    }

    updateStatusLine() {
        const state = this.store.get();
        const session = this.getCurrentSession();
        const tasks = Object.values(session?.tasks || {});
        const transcriptCount = session?.transcript.length || 0;

        this.statuslineLeft.innerHTML = "";

        [
            `mode:${state.mode}`,
            `permission:${this.getEffectivePermissionMode()}`,
            `context:${state.toolContext}`,
            `messages:${transcriptCount}`,
            `model:${this.shortenModel(state.runtime?.model)}`
        ].forEach((text) => this.statuslineLeft.appendChild(this.createStatusItem(text)));
    }

    createStatusItem(text) {
        const item = document.createElement("span");
        item.className = "status-item";
        item.textContent = text;
        return item;
    }

    bumpContextPercent(input) {
        const session = this.getCurrentSession();
        const baseline = typeof session?.contextPercentOverride === "number" ? session.contextPercentOverride : null;
        const historySize = (session?.transcript || []).reduce((sum, entry) => sum + (entry.content?.length || 0), 0) + input.length;
        const contextBonus = this.store.get().toolContext === "agents" ? 8 : 4;
        const estimated = Math.min(98, Math.max(1, Math.round(historySize / 140) + contextBonus));
        const contextPercent = baseline !== null
            ? Math.min(98, Math.max(baseline, baseline + Math.round(input.length / 120)))
            : estimated;
        this.store.set({ contextPercent });
        this.contextPill.textContent = `Context · ${contextPercent}%`;
    }

    refreshContextPercent() {
        const session = this.getCurrentSession();
        if (typeof session?.contextPercentOverride === "number") {
            this.store.set({ contextPercent: session.contextPercentOverride });
            this.contextPill.textContent = `Context · ${session.contextPercentOverride}%`;
            return;
        }
        const historySize = (session?.transcript || []).reduce((sum, entry) => sum + (entry.content?.length || 0), 0);
        const contextBonus = this.store.get().toolContext === "agents" ? 8 : 4;
        const contextPercent = historySize > 0
            ? Math.min(98, Math.max(1, Math.round(historySize / 140) + contextBonus))
            : contextBonus;
        this.store.set({ contextPercent });
        this.contextPill.textContent = `Context · ${contextPercent}%`;
    }

    appendSessionLog(entry) {
        const session = this.getCurrentSession();
        if (!session) return;
        session.logs = session.logs || [];
        const normalized = {
            id: `log_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
            ...entry
        };
        const fingerprint = JSON.stringify([
            normalized.type,
            normalized.phase || null,
            normalized.direction || null,
            normalized.timestamp || null,
            normalized.payload || null
        ]);
        const duplicate = session.logs.some((item) => JSON.stringify([
            item.type,
            item.phase || null,
            item.direction || null,
            item.timestamp || null,
            item.payload || null
        ]) === fingerprint);
        if (duplicate) {
            return;
        }
        session.logs.push(normalized);
        session.logs = session.logs.slice(-400);
        session.updatedAt = new Date().toISOString();
        this.persistSessions();
        this.renderLogs();
    }

    toggleLogsDrawer(force = null) {
        if (!this.logsDrawer) return;
        const shouldOpen = typeof force === "boolean" ? force : this.logsDrawer.classList.contains("hidden");
        this.logsDrawer.classList.toggle("hidden", !shouldOpen);
        this.logsDrawer.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
        if (this.logsToggleBtn) {
            this.logsToggleBtn.classList.toggle("active", shouldOpen);
        }
        if (shouldOpen) {
            this.refreshLogsFromBackend();
        }
    }

    async refreshLogsFromBackend() {
        const session = this.getCurrentSession();
        if (!session || !this.settings.apiUrl) {
            this.renderLogs();
            return;
        }

        try {
            const params = new URLSearchParams({ limit: "400" });
            const { start, end } = this.getLogFilterIsoRange();
            if (start) params.set("start", start);
            if (end) params.set("end", end);

            const response = await fetch(`${this.settings.apiUrl}/logs/${encodeURIComponent(session.id)}?${params.toString()}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            const logs = (payload.logs || []).map((entry, index) => ({
                id: entry.id || `server_log_${index}_${entry.timestamp || Date.now()}`,
                type: "llm_log",
                ...entry
            }));
            session.logs = logs;
            this.persistSessions();
        } catch (error) {
            console.debug("Failed to refresh logs from backend", error);
        }
        this.renderLogs();
    }

    renderLogs() {
        if (!this.logsList) return;
        const session = this.getCurrentSession();
        const logs = this.getFilteredLogs(session?.logs || []);
        if (logs.length === 0) {
            this.logsList.innerHTML = '<p class="panel-empty">No LLM logs yet.</p>';
            return;
        }

        this.logsList.innerHTML = logs.slice().reverse().map((entry) => {
            const title = [entry.type, entry.phase, entry.direction].filter(Boolean).join(" · ");
            const timestamp = new Date(entry.timestamp || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            const body = this.escapeHtml(JSON.stringify(entry.payload || {}, null, 2));
            return `
                <article class="log-entry">
                    <div class="log-entry-head">
                        <strong>${this.escapeHtml(title || "log")}</strong>
                        <span>${timestamp}</span>
                    </div>
                    <pre class="log-entry-body"><code>${body}</code></pre>
                </article>
            `;
        }).join("");
    }

    getFilteredLogs(logs) {
        const { fromMs, toMs } = this.getLogFilterRange();

        return logs.filter((entry) => {
            const ts = new Date(entry.timestamp || Date.now()).getTime();
            if (Number.isFinite(fromMs) && ts < fromMs) return false;
            if (Number.isFinite(toMs) && ts > toMs) return false;
            return true;
        });
    }

    getLogFilterRange() {
        const now = Date.now();
        let fromMs = null;
        let toMs = null;

        if (this.logRange === "15m") {
            fromMs = now - 15 * 60 * 1000;
        } else if (this.logRange === "1h") {
            fromMs = now - 60 * 60 * 1000;
        } else if (this.logRange === "24h") {
            fromMs = now - 24 * 60 * 60 * 1000;
        } else if (this.logRange === "custom") {
            fromMs = this.logsFromInput?.value ? new Date(this.logsFromInput.value).getTime() : null;
            toMs = this.logsToInput?.value ? new Date(this.logsToInput.value).getTime() : null;
        }

        return { fromMs, toMs };
    }

    getLogFilterIsoRange() {
        const { fromMs, toMs } = this.getLogFilterRange();
        return {
            start: Number.isFinite(fromMs) ? new Date(fromMs).toISOString() : null,
            end: Number.isFinite(toMs) ? new Date(toMs).toISOString() : null
        };
    }

    openSettings() {
        this.apiUrlInput.value = this.settings.apiUrl;
        this.autoSaveInput.checked = this.settings.autoSave;
        this.themeSelect.value = this.settings.theme;
        this.settingsModal.classList.remove("hidden");
    }

    closeSettings() {
        this.settingsModal.classList.add("hidden");
    }

    saveSettings() {
        this.settings.apiUrl = this.apiUrlInput.value.trim() || this.apiBaseUrl;
        this.settings.autoSave = this.autoSaveInput.checked;
        this.settings.theme = this.themeSelect.value || "dark";
        this.persistPreferenceState();
        this.closeSettings();
        this.refreshRuntime();
        this.fetchSkills();
    }

    resetSettings() {
        this.settings = {
            apiUrl: this.apiBaseUrl,
            autoSave: true,
            theme: "dark",
            permissionMode: "ask",
            thinkingMode: true,
            toolContext: "workspace"
        };
        localStorage.removeItem("obs-agent-settings");
        this.applyStoredPreferences();
        this.openSettings();
    }

    loadSettings() {
        try {
            const stored = JSON.parse(localStorage.getItem("obs-agent-settings") || "null");
            if (stored) {
                this.settings = { ...this.settings, ...stored };
            }
            const currentOriginApi = this.resolveDefaultApiBaseUrl();
            const legacyDefaultApi = "http://127.0.0.1:8000";
            if (!this.settings.apiUrl || this.settings.apiUrl === legacyDefaultApi) {
                this.settings.apiUrl = currentOriginApi;
            }
        } catch (error) {
            console.warn("Failed to load settings", error);
        }
    }

    applyStoredPreferences() {
        this.store.set({
            permissionMode: this.settings.permissionMode || "ask",
            thinkingMode: typeof this.settings.thinkingMode === "boolean" ? this.settings.thinkingMode : true,
            toolContext: this.settings.toolContext || "workspace"
        });
    }

    persistPreferenceState() {
        this.settings.permissionMode = this.store.get().permissionMode;
        this.settings.thinkingMode = this.store.get().thinkingMode;
        this.settings.toolContext = this.store.get().toolContext;
        this.safeSetLocalStorage("obs-agent-settings", JSON.stringify(this.settings));
    }

    loadSessions() {
        try {
            const storedVersion = localStorage.getItem("obs-agent-storage-version");
            if (storedVersion !== this.storageVersion) {
                localStorage.removeItem("obs-agent-sessions");
                this.safeSetLocalStorage("obs-agent-storage-version", this.storageVersion);
            }
            const raw = localStorage.getItem("obs-agent-sessions");
            if (!raw) {
                this.renderSessionList();
                return;
            }
            const sessions = JSON.parse(raw);
            sessions.forEach((session) => this.sessions.set(session.id, this.upgradeSession(session)));
            this.persistSessions();
            this.renderSessionList();
        } catch (error) {
            console.warn("Failed to load sessions", error);
        }
    }

    persistSessions() {
        if (!this.settings.autoSave) return;
        this.safeSetLocalStorage("obs-agent-sessions", JSON.stringify(Array.from(this.sessions.values())));
    }

    toggleWelcome(visible) {
        this.welcomeScreen.classList.toggle("hidden", !visible);
    }

    autoResizeInput() {
        this.messageInput.style.height = "auto";
        this.messageInput.style.height = `${Math.min(this.messageInput.scrollHeight, 240)}px`;
    }

    scrollMessagesToBottom() {
        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
    }

    shortenModel(model) {
        if (!model) return "--";
        const normalized = String(model).split("/").filter(Boolean).pop() || String(model);
        return normalized.length > 22 ? `${normalized.slice(0, 22)}…` : normalized;
    }

    escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }
}

window.addEventListener("DOMContentLoaded", () => {
    new ObsAgentConsole();
});
