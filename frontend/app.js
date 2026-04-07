class AppStateStore {
    constructor() {
        this.state = {
            mode: "agent",
            permissionMode: "ask",
            thinkingMode: true,
            runtime: null,
            selectedTaskId: "main",
            contextPercent: 0,
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
        this.apiBaseUrl = "http://127.0.0.1:8000";
        this.sessions = new Map();
        this.currentSessionId = null;
        this.isSending = false;
        this.settings = {
            apiUrl: this.apiBaseUrl,
            autoSave: true,
            theme: "dark"
        };
        this.store = new AppStateStore();
        this.collapsedMessages = new Set();
        this.pendingPermissionAction = null;
        this.permissionConfirmedForSubmit = false;
        this.pinnedThinkingMessages = new Set();
        this.workflowPhases = ["queued", "planning", "execution", "synthesis", "verification", "complete"];

        this.init();
    }

    init() {
        this.bindElements();
        this.loadSettings();
        this.bindEvents();
        this.loadSessions();
        this.ensureSession();
        this.refreshRuntime();
        this.fetchSkills();
        this.renderPermissionState();
        this.renderThinkingMode();
        this.renderModePills();
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
        this.searchShellBtn = document.getElementById("search-shell-btn");
        this.computerNavBtn = document.getElementById("computer-nav-btn");
        this.historyLinkBtn = document.getElementById("history-link-btn");
        this.discoverLinkBtn = document.getElementById("discover-link-btn");
        this.agentsLinkBtn = document.getElementById("agents-link-btn");
        this.connectorsLinkBtn = document.getElementById("connectors-link-btn");
        this.permissionsLinkBtn = document.getElementById("permissions-link-btn");
        this.sidebarNavButtons = [
            this.searchShellBtn,
            this.computerNavBtn,
            this.historyLinkBtn,
            this.discoverLinkBtn,
            this.agentsLinkBtn,
            this.connectorsLinkBtn,
            this.permissionsLinkBtn
        ].filter(Boolean);
        this.currentSessionTitle = document.getElementById("current-session-title");
        this.welcomeScreen = document.getElementById("welcome-screen");
        this.agentStatus = document.getElementById("agent-status");
        this.transcriptTitle = document.getElementById("transcript-title");
        this.returnMainBtn = document.getElementById("return-main-btn");
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
        this.computerNavBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.computerNavBtn);
            this.setActiveToolContext("computer");
            this.focusComposer("Use the computer context to inspect screenshots, browsers, and visual flows");
        });
        this.historyLinkBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.historyLinkBtn);
            this.scrollSidebarSection(".history-panel", "History panel focused");
        });
        this.discoverLinkBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.discoverLinkBtn);
            this.store.set({ mode: "plan" });
            this.renderModePills();
            this.renderPermissionState();
            this.updateStatusLine();
            this.focusComposer("Draft a plan, discover relevant files, and outline the next steps");
        });
        this.agentsLinkBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.agentsLinkBtn);
            this.store.set({ mode: "review" });
            if (this.store.get().permissionMode === "ask") {
                this.store.set({ permissionMode: "plan" });
            }
            this.setActiveToolContext("agents");
            this.renderModePills();
            this.renderPermissionState();
            this.updateStatusLine();
            this.focusComposer("Coordinate agent work, review architecture, and inspect task flow");
        });
        this.connectorsLinkBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.connectorsLinkBtn);
            this.store.set({ transcriptFilter: "tool" });
            this.renderTranscript();
            this.focusComposer("Reference connectors, skills, or external tools for this request");
        });
        this.permissionsLinkBtn.addEventListener("click", () => {
            this.setActiveSidebarNav(this.permissionsLinkBtn);
            this.openPermissionModal();
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

        document.querySelectorAll(".mode-pill").forEach((button) => {
            button.addEventListener("click", () => {
                const nextMode = button.dataset.mode || "agent";
                const patch = { mode: nextMode };
                if (nextMode === "review" && this.store.get().permissionMode === "ask") {
                    patch.permissionMode = "plan";
                }
                this.store.set(patch);
                this.renderModePills();
                this.renderPermissionState();
                this.updateStatusLine();
            });
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
        });

        this.smallToolButtons.forEach((button) => {
            button.addEventListener("click", () => {
                this.setActiveToolContext(button.dataset.toolContext || "computer");
            });
        });

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
        this.smallToolButtons.forEach((button) => {
            button.classList.toggle("active", button.dataset.toolContext === context);
        });

        const placeholderMap = {
            computer: "Use the computer context to inspect screenshots, browsers, and visual flows",
            workspace: "Describe files, directories, or code paths you want OBS to inspect",
            agents: "Ask OBS to coordinate sub-tasks, review architecture, or manage execution flow"
        };

        this.composerPlaceholder.textContent = placeholderMap[context] || "Ask OBS to inspect code, use tools, or coordinate agents";
        this.messageInput.focus();
    }

    createEmptySession(id) {
        return {
            id,
            title: "New thread",
            transcript: [],
            tasks: {},
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
        };
    }

    createSession() {
        const id = `session_${Date.now()}`;
        const session = this.createEmptySession(id);
        this.sessions.set(id, session);
        this.switchSession(id);
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
        this.toggleWelcome(session.transcript.length === 0);
        this.renderTasks();
        this.renderPhaseRail();
        this.updateStatusLine();
    }

    clearCurrentSession() {
        const session = this.getCurrentSession();
        if (!session) {
            return;
        }
        session.transcript = [];
        session.tasks = {};
        session.title = "New thread";
        session.updatedAt = new Date().toISOString();
        this.currentSessionTitle.textContent = session.title;
        this.store.set({ selectedTaskId: "main", tasks: [] });
        this.renderTranscript();
        this.toggleWelcome(true);
        this.renderTasks();
        this.renderPhaseRail();
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
            ? session.transcript.filter((entry) => entry.taskId === "main" || entry.kind === "system_notice")
            : session.transcript.filter((entry) => entry.taskId === selectedTaskId);

        return taskScoped.filter((entry) => {
            if (filter === "all") return true;
            if (filter === "tool") return entry.kind === "tool_use" || entry.kind === "tool_result";
            if (filter === "system") return entry.kind === "system_notice";
            if (filter === "assistant") return entry.role === "assistant" && (entry.kind === "assistant_text" || entry.kind === "thinking_text");
            if (filter === "user") return entry.role === "user";
            return true;
        });
    }

    renderTranscript(preserveScroll = false) {
        const selectedTaskId = this.store.get().selectedTaskId;
        this.transcriptTitle.textContent = selectedTaskId === "main" ? "Conversation" : selectedTaskId;
        this.returnMainBtn.classList.toggle("hidden", selectedTaskId === "main");
        this.chatMessages.innerHTML = "";

        const entries = this.getFilteredTranscriptEntries();
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

    renderTranscriptEntry(entry, parent) {
        const wrapper = document.createElement("article");
        wrapper.className = `message ${this.mapEntryRole(entry)}`;
        if (entry.taskId && entry.taskId !== "main" && entry.taskId === this.store.get().selectedTaskId) {
            wrapper.classList.add("active-task");
        }

        const meta = document.createElement("div");
        meta.className = "message-meta";
        meta.innerHTML = `
            <span>${this.escapeHtml(this.getEntryLabel(entry))}</span>
            <span>${new Date(entry.timestamp || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
        `;
        if (entry.kind === "tool_use" || entry.kind === "tool_result") {
            const state = document.createElement("span");
            state.className = `message-state ${entry.kind === "tool_use" ? "running" : (entry.success === false ? "error" : "done")}`;
            state.textContent = entry.kind === "tool_use" ? "running" : (entry.success === false ? "error" : "done");
            meta.appendChild(state);
        }

        const body = document.createElement("div");
        const isThinkingEntry = entry.kind === "thinking_text";
        const isLong = (entry.content || "").length > 420;
        const isCollapsible = isThinkingEntry || isLong;
        const isPinnedThinking = isThinkingEntry && this.pinnedThinkingMessages.has(entry.id);
        const isCollapsed = isCollapsible && !(isPinnedThinking || this.collapsedMessages.has(entry.id));
        body.className = `message-body${entry.streaming ? " is-streaming" : ""}${isCollapsed ? " collapsed" : ""}`;
        body.textContent = entry.content || "";

        wrapper.appendChild(meta);
        if (isThinkingEntry) {
            const summary = document.createElement("div");
            summary.className = `thinking-summary${isCollapsed ? "" : " hidden"}`;
            summary.textContent = this.getThinkingSummary(entry.content, entry.streaming);
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
            toggle.className = "message-toggle";
            toggle.textContent = isCollapsed
                ? (isThinkingEntry ? "Pin open" : "Expand")
                : (isThinkingEntry ? "Unpin" : "Collapse");
            toggle.addEventListener("click", () => {
                if (isThinkingEntry) {
                    if (this.pinnedThinkingMessages.has(entry.id)) {
                        this.pinnedThinkingMessages.delete(entry.id);
                    } else {
                        this.pinnedThinkingMessages.add(entry.id);
                    }
                } else {
                    if (this.collapsedMessages.has(entry.id)) {
                        this.collapsedMessages.delete(entry.id);
                    } else {
                        this.collapsedMessages.add(entry.id);
                    }
                }
                this.renderTranscript(true);
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

    buildToolCard(entry) {
        const card = document.createElement("div");
        card.className = `tool-card ${entry.kind}`;

        const title = document.createElement("div");
        title.className = "tool-card-title";
        title.textContent = entry.toolName || entry.taskId || "tool";
        card.appendChild(title);

        const subtitle = document.createElement("div");
        subtitle.className = "tool-card-subtitle";
        subtitle.textContent = entry.kind === "tool_use"
            ? "Tool invocation started"
            : (entry.success === false ? "Tool finished with an error" : "Tool result captured");
        card.appendChild(subtitle);

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
            card.appendChild(pillRow);
        }

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
            timestamp: entry.timestamp || new Date().toISOString(),
            streaming: Boolean(entry.streaming)
        };
        session.transcript.push(normalized);
        session.updatedAt = new Date().toISOString();
        this.persistSessions();
        this.renderTranscript();
        this.renderSessionList();
        this.renderPhaseRail();
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
        this.renderSessionList();
        this.renderPhaseRail();
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

    getEffectivePermissionMode() {
        const state = this.store.get();
        if (state.mode === "review" && state.permissionMode === "ask") {
            return "plan";
        }
        return state.permissionMode;
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
        this.permissionConfirmedForSubmit = false;
        this.isSending = true;
        this.toggleWelcome(false);

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

        this.messageInput.value = "";
        this.autoResizeInput();
        this.resetTasks();

        try {
            let assistantEntry = null;
            let thinkingEntry = null;
            let rawAssistantText = "";
            let workflowNoticeEntry = null;

            if (this.store.get().mode === "review") {
                workflowNoticeEntry = this.addTranscriptEntry({
                    role: "assistant",
                    content: "Review workflow queued. Building execution plan and waiting for the first phase update...",
                    kind: "system_notice",
                    taskId: "main",
                    phase: "queued"
                });
            } else if (this.store.get().mode === "plan") {
                workflowNoticeEntry = this.addTranscriptEntry({
                    role: "assistant",
                    content: "Planning workflow queued. Generating task graph and coordinator outline...",
                    kind: "system_notice",
                    taskId: "main",
                    phase: "queued"
                });
            }

            const response = await fetch(`${this.settings.apiUrl}/chat/stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tool_name: "chat",
                    parameters: {
                        message: content,
                        session_id: this.currentSessionId,
                        permission_mode: this.getEffectivePermissionMode(),
                        permission_confirmed: permissionConfirmed || this.getEffectivePermissionMode() !== "ask",
                        thinking_mode: this.store.get().thinkingMode,
                        mode: this.store.get().mode
                    }
                })
            });

            if (!response.ok || !response.body) {
                throw new Error(`HTTP ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const chunks = buffer.split("\n\n");
                buffer = chunks.pop() || "";

                for (const chunk of chunks) {
                    const line = chunk.split("\n").find((part) => part.startsWith("data: "));
                    if (!line) continue;

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
                        continue;
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
                        continue;
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
                        continue;
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
                        continue;
                    }

                    if (payload.content) {
                        rawAssistantText += payload.content;
                        const parsed = this.parseAssistantStream(rawAssistantText);

                        if (parsed.hasThinking) {
                            if (!thinkingEntry && parsed.thinkingText) {
                                thinkingEntry = this.addTranscriptEntry({
                                    role: "assistant",
                                    content: parsed.thinkingText,
                                    kind: "thinking_text",
                                    taskId: "main",
                                    streaming: true
                                });
                            } else if (thinkingEntry) {
                                this.updateTranscriptEntry(thinkingEntry.id, {
                                    content: parsed.thinkingText,
                                    streaming: parsed.inThinking
                                });
                            }

                            if (parsed.answerText) {
                                if (!assistantEntry) {
                                    assistantEntry = this.addTranscriptEntry({
                                        role: "assistant",
                                        content: parsed.answerText,
                                        kind: "assistant_text",
                                        taskId: "main",
                                        streaming: true
                                    });
                                } else {
                                    this.updateTranscriptEntry(assistantEntry.id, {
                                        content: parsed.answerText,
                                        streaming: true
                                    });
                                }
                            }
                        } else {
                            if (!assistantEntry) {
                                assistantEntry = this.addTranscriptEntry({
                                    role: "assistant",
                                    content: parsed.answerText || this.getPendingAssistantText(),
                                    kind: "assistant_text",
                                    taskId: "main",
                                    streaming: true
                                });
                            } else {
                                this.updateTranscriptEntry(assistantEntry.id, {
                                    content: parsed.answerText,
                                    streaming: true
                                });
                            }
                        }
                    }

                    if (payload.type === "thinking_delta") {
                        if (!thinkingEntry) {
                            thinkingEntry = this.addTranscriptEntry({
                                role: "assistant",
                                content: payload.delta || "",
                                kind: "thinking_text",
                                taskId: "main",
                                streaming: true
                            });
                        } else {
                            this.updateTranscriptEntry(thinkingEntry.id, {
                                content: `${thinkingEntry.content || ""}${payload.delta || ""}`,
                                streaming: true
                            });
                        }
                        continue;
                    }

                    if (payload.type === "answer_delta") {
                        if (!assistantEntry) {
                            assistantEntry = this.addTranscriptEntry({
                                role: "assistant",
                                content: payload.delta || "",
                                kind: "assistant_text",
                                taskId: "main",
                                streaming: true
                            });
                        } else {
                            this.updateTranscriptEntry(assistantEntry.id, {
                                content: `${assistantEntry.content || ""}${payload.delta || ""}`,
                                streaming: true
                            });
                        }
                        continue;
                    }

                    if (payload.error) {
                        throw new Error(payload.error);
                    }

                    if (payload.done) {
                        if (workflowNoticeEntry) {
                            this.updateTranscriptEntry(workflowNoticeEntry.id, {
                                content: this.store.get().mode === "review"
                                    ? "Review workflow finished waiting for planner output."
                                    : "Planning workflow finished waiting for planner output."
                            });
                            workflowNoticeEntry = null;
                        }
                        if (thinkingEntry) {
                            this.updateTranscriptEntry(thinkingEntry.id, { streaming: false });
                        }
                        if (assistantEntry) {
                            this.updateTranscriptEntry(assistantEntry.id, { streaming: false });
                        } else if (!thinkingEntry) {
                            assistantEntry = this.addTranscriptEntry({
                                role: "assistant",
                                content: this.getPendingAssistantText(),
                                kind: "assistant_text",
                                taskId: "main",
                                streaming: false
                            });
                        }
                    }
                }
            }

            if (thinkingEntry) {
                this.updateTranscriptEntry(thinkingEntry.id, { streaming: false });
            }
            if (assistantEntry) {
                this.updateTranscriptEntry(assistantEntry.id, { streaming: false });
            }
        } catch (error) {
            if (workflowNoticeEntry) {
                this.updateTranscriptEntry(workflowNoticeEntry.id, {
                    content: `Workflow interrupted: ${error.message}`
                });
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
            this.updateStatusLine();
        }
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
        this.store.set({ tasks: Object.values(session.tasks), selectedTaskId: taskId });
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
        document.querySelectorAll(".mode-pill").forEach((button) => {
            button.classList.toggle("active", button.dataset.mode === mode);
        });
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
        const historySize = (session?.transcript || []).reduce((sum, entry) => sum + (entry.content?.length || 0), 0) + input.length;
        const contextPercent = Math.min(98, Math.max(1, Math.round(historySize / 120)));
        this.store.set({ contextPercent });
        this.contextPill.textContent = `Context · ${contextPercent}%`;
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
        localStorage.setItem("obs-agent-settings", JSON.stringify(this.settings));
        this.closeSettings();
        this.refreshRuntime();
        this.fetchSkills();
    }

    resetSettings() {
        this.settings = {
            apiUrl: this.apiBaseUrl,
            autoSave: true,
            theme: "dark"
        };
        localStorage.removeItem("obs-agent-settings");
        this.openSettings();
    }

    loadSettings() {
        try {
            const stored = JSON.parse(localStorage.getItem("obs-agent-settings") || "null");
            if (stored) {
                this.settings = { ...this.settings, ...stored };
            }
        } catch (error) {
            console.warn("Failed to load settings", error);
        }
    }

    loadSessions() {
        try {
            const raw = localStorage.getItem("obs-agent-sessions");
            if (!raw) {
                this.renderSessionList();
                return;
            }
            const sessions = JSON.parse(raw);
            sessions.forEach((session) => this.sessions.set(session.id, this.upgradeSession(session)));
            this.renderSessionList();
        } catch (error) {
            console.warn("Failed to load sessions", error);
        }
    }

    persistSessions() {
        if (!this.settings.autoSave) return;
        localStorage.setItem("obs-agent-sessions", JSON.stringify(Array.from(this.sessions.values())));
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
