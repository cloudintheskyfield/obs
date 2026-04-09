import React, { useEffect, useRef, useState } from "react";
import Composer from "./components/Composer.jsx";
import LogsDrawer from "./components/LogsDrawer.jsx";
import RuntimePills from "./components/RuntimePills.jsx";
import SkillsDrawer from "./components/SkillsDrawer.jsx";
import TranscriptView from "./components/TranscriptView.jsx";
import { shortenModel } from "./lib/formatting.js";

const STORAGE_VERSION = "20260408-01";
const SETTINGS_KEY = "obs-agent-settings";
const SESSIONS_KEY = "obs-agent-sessions";
const VERSION_KEY = "obs-agent-storage-version";
const DEFAULT_SELECTED_SKILLS = ["code-sandbox", "file-operations", "terminal", "web-search"];

function resolveDefaultApiBaseUrl() {
    const { protocol, origin, hostname } = window.location;
    if ((protocol === "http:" || protocol === "https:") && hostname) {
        return origin;
    }
    return "http://127.0.0.1:8000";
}

function nowIso() {
    return new Date().toISOString();
}

function createEmptySession(id) {
    return {
        id,
        title: "New thread",
        transcript: [],
        logs: [],
        contextPercentOverride: null,
        serverContextPercent: null,
        tasks: {},
        createdAt: nowIso(),
        updatedAt: nowIso()
    };
}

function normalizeEntry(entry) {
    return {
        id: entry.id || `entry_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
        role: entry.role || "assistant",
        content: entry.content || "",
        kind: entry.kind || "assistant_text",
        taskId: entry.taskId || "main",
        toolName: entry.toolName || null,
        phase: entry.phase || null,
        success: entry.success,
        pendingPlaceholder: Boolean(entry.pendingPlaceholder),
        timestamp: entry.timestamp || nowIso(),
        streaming: Boolean(entry.streaming)
    };
}

function upgradeSession(session) {
    const next = {
        ...session,
        transcript: Array.isArray(session.transcript)
            ? session.transcript
            : Array.isArray(session.messages)
                ? session.messages.map((message, index) => ({
                    id: `legacy_${index}`,
                    role: message.role,
                    content: message.content,
                    kind: message.role === "assistant" ? "assistant_text" : "user_text",
                    taskId: "main",
                    timestamp: nowIso()
                }))
                : [],
        tasks: session.tasks || {},
        logs: Array.isArray(session.logs) ? session.logs.filter((entry) => entry && entry.type === "llm_log") : [],
        contextPercentOverride: typeof session.contextPercentOverride === "number" ? session.contextPercentOverride : null,
        serverContextPercent: typeof session.serverContextPercent === "number" ? session.serverContextPercent : null,
        title: session.title || "New thread",
        createdAt: session.createdAt || nowIso(),
        updatedAt: session.updatedAt || nowIso()
    };
    delete next.messages;
    next.transcript = next.transcript.filter((entry) => {
        if (!entry) return false;
        const content = typeof entry.content === "string" ? entry.content.trim() : "";
        if (entry.kind === "thinking_text" && !content) return Boolean(entry.pendingPlaceholder);
        if (entry.kind === "assistant_text" && !content) return false;
        return true;
    });
    return next;
}

function isSimpleChat(content) {
    return /^(hi|hello|hey|你好|嗨|在吗|早上好|下午好|晚上好)\W*$/i.test((content || "").trim());
}

function buildContextPayload(toolContext) {
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

function computeContextPercent(session, toolContext) {
    if (typeof session?.serverContextPercent === "number") {
        return session.serverContextPercent;
    }
    if (typeof session?.contextPercentOverride === "number") {
        return session.contextPercentOverride;
    }
    const historySize = (session?.transcript || []).reduce((sum, entry) => sum + (entry.content?.length || 0), 0);
    const contextBonus = toolContext === "agents" ? 8 : 4;
    return historySize > 0
        ? Math.min(98, Math.max(1, Math.round(historySize / 140) + contextBonus))
        : contextBonus;
}

function computeNextContextPercent(session, toolContext, input) {
    const baseline = typeof session?.contextPercentOverride === "number" ? session.contextPercentOverride : null;
    const historySize = (session?.transcript || []).reduce((sum, entry) => sum + (entry.content?.length || 0), 0) + input.length;
    const contextBonus = toolContext === "agents" ? 8 : 4;
    const estimated = Math.min(98, Math.max(1, Math.round(historySize / 140) + contextBonus));
    return baseline !== null
        ? Math.min(98, Math.max(baseline, baseline + Math.round(input.length / 120)))
        : estimated;
}

function App() {
    const [settings, setSettings] = useState({
        apiUrl: resolveDefaultApiBaseUrl(),
        autoSave: true,
        theme: "dark",
        permissionMode: "ask",
        thinkingMode: true,
        toolContext: "workspace"
    });
    const [mode, setMode] = useState("agent");
    const [runtime, setRuntime] = useState(null);
    const [runtimeStatus, setRuntimeStatus] = useState("Checking runtime");
    const [sessions, setSessions] = useState([]);
    const [currentSessionId, setCurrentSessionId] = useState(null);
    const [contextPercent, setContextPercent] = useState(0);
    const [toolContext, setToolContext] = useState("workspace");
    const [thinkingMode, setThinkingMode] = useState(true);
    const [permissionMode, setPermissionMode] = useState("ask");
    const [messageInput, setMessageInput] = useState("");
    const [isSending, setIsSending] = useState(false);
    const [logsOpen, setLogsOpen] = useState(false);
    const [skillsOpen, setSkillsOpen] = useState(false);
    const [logRange, setLogRange] = useState("all");
    const [logsFrom, setLogsFrom] = useState("");
    const [logsTo, setLogsTo] = useState("");
    const [expandedThinking, setExpandedThinking] = useState({});
    const [skillCatalog, setSkillCatalog] = useState([]);
    const [selectedSkills, setSelectedSkills] = useState(DEFAULT_SELECTED_SKILLS);

    const messageInputRef = useRef(null);
    const chatMessagesRef = useRef(null);
    const sessionsRef = useRef([]);
    const currentSessionIdRef = useRef(null);
    const settingsRef = useRef(settings);

    useEffect(() => {
        settingsRef.current = settings;
    }, [settings]);

    useEffect(() => {
        sessionsRef.current = sessions;
    }, [sessions]);

    useEffect(() => {
        currentSessionIdRef.current = currentSessionId;
    }, [currentSessionId]);

    useEffect(() => {
        try {
            const stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null");
            if (stored) {
                setSettings((current) => ({ ...current, ...stored }));
                if (typeof stored.thinkingMode === "boolean") {
                    setThinkingMode(stored.thinkingMode);
                }
                if (stored.permissionMode) {
                    setPermissionMode(stored.permissionMode);
                }
                if (stored.toolContext) {
                    setToolContext(stored.toolContext);
                }
                if (Array.isArray(stored.selectedSkills) && stored.selectedSkills.length > 0) {
                    setSelectedSkills(stored.selectedSkills);
                }
            }
        } catch (error) {
            console.warn("Failed to load settings", error);
        }

        try {
            const storedVersion = localStorage.getItem(VERSION_KEY);
            if (storedVersion !== STORAGE_VERSION) {
                localStorage.setItem(VERSION_KEY, STORAGE_VERSION);
            }
            const raw = localStorage.getItem(SESSIONS_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                const upgraded = parsed.map((session) => upgradeSession(session));
                setSessions(upgraded);
                if (upgraded[0]) {
                    const latest = upgraded.slice().sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt))[0];
                    setCurrentSessionId(latest.id);
                }
            }
        } catch (error) {
            console.warn("Failed to load sessions", error);
        }
    }, []);

    useEffect(() => {
        setSettings((current) => ({
            ...current,
            permissionMode,
            thinkingMode,
            toolContext,
            selectedSkills
        }));
    }, [permissionMode, thinkingMode, toolContext, selectedSkills]);

    useEffect(() => {
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    }, [settings]);

    useEffect(() => {
        if (!settings.autoSave) {
            return;
        }
        localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
    }, [sessions, settings.autoSave]);

    useEffect(() => {
        if (sessions.length === 0) {
            const next = createEmptySession(`session_${Date.now()}`);
            setSessions([next]);
            setCurrentSessionId(next.id);
            return;
        }
        if (!currentSessionId || !sessions.some((session) => session.id === currentSessionId)) {
            setCurrentSessionId(sessions[0].id);
        }
    }, [sessions, currentSessionId]);

    const currentSession = sessions.find((session) => session.id === currentSessionId) || null;

    useEffect(() => {
        setContextPercent(computeContextPercent(currentSession, toolContext));
    }, [currentSession, toolContext]);

    useEffect(() => {
        if (!messageInputRef.current) return;
        messageInputRef.current.style.height = "auto";
        messageInputRef.current.style.height = `${Math.min(messageInputRef.current.scrollHeight, 240)}px`;
    }, [messageInput]);

    useEffect(() => {
        if (!chatMessagesRef.current) return;
        chatMessagesRef.current.scrollTop = chatMessagesRef.current.scrollHeight;
    }, [currentSession?.updatedAt, logsOpen]);

    useEffect(() => {
        refreshRuntime();
        fetchSkillCatalog();
    }, []);

    useEffect(() => {
        if (currentSessionId) {
            hydrateSessionLocation(currentSessionId);
            refreshSessionContextState(currentSessionId);
        }
    }, [currentSessionId]);

    useEffect(() => {
        if (logsOpen) {
            refreshLogsFromBackend();
        }
    }, [logsOpen, logRange, logsFrom, logsTo, currentSessionId]);

    function updateSessions(updater) {
        setSessions((previous) => updater(previous.map((session) => upgradeSession(session))));
    }

    function updateSessionById(sessionId, transform) {
        updateSessions((previous) => previous.map((session) => {
            if (session.id !== sessionId) {
                return session;
            }
            const clone = upgradeSession({
                ...session,
                transcript: [...(session.transcript || [])],
                logs: [...(session.logs || [])],
                tasks: { ...(session.tasks || {}) }
            });
            transform(clone);
            clone.updatedAt = nowIso();
            return clone;
        }));
    }

    function appendTranscriptEntry(sessionId, entry) {
        const normalized = normalizeEntry(entry);
        updateSessionById(sessionId, (session) => {
            session.transcript.push(normalized);
        });
        return normalized;
    }

    function patchTranscriptEntry(sessionId, entryId, patch) {
        updateSessionById(sessionId, (session) => {
            const target = session.transcript.find((entry) => entry.id === entryId);
            if (!target) return;
            Object.assign(target, patch);
        });
    }

    function removeTranscriptEntry(sessionId, entryId) {
        updateSessionById(sessionId, (session) => {
            session.transcript = session.transcript.filter((entry) => entry.id !== entryId);
        });
    }

    function appendLog(sessionId, entry) {
        updateSessionById(sessionId, (session) => {
            const normalized = {
                id: entry.id || `log_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
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
            if (!duplicate) {
                session.logs = [...session.logs, normalized].slice(-400);
            }
        });
    }

    function createSession() {
        const session = createEmptySession(`session_${Date.now()}`);
        updateSessions((previous) => [session, ...previous]);
        setCurrentSessionId(session.id);
        setMode("agent");
        setToolContext("workspace");
        setExpandedThinking({});
    }

    function clearCurrentSession() {
        if (!currentSessionId) return;
        updateSessionById(currentSessionId, (session) => {
            session.title = "New thread";
            session.transcript = [];
            session.logs = [];
            session.tasks = {};
            session.contextPercentOverride = null;
            session.serverContextPercent = null;
        });
        setExpandedThinking({});
    }

    function exportCurrentSession() {
        if (!currentSession) return;
        const blob = new Blob([JSON.stringify(currentSession, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${currentSession.title.replace(/\s+/g, "_").toLowerCase() || "session"}.json`;
        link.click();
        URL.revokeObjectURL(url);
    }

    async function refreshRuntime() {
        try {
            const [healthResponse, runtimeResponse] = await Promise.all([
                fetch(`${settingsRef.current.apiUrl}/health`),
                fetch(`${settingsRef.current.apiUrl}/runtime`)
            ]);
            if (!healthResponse.ok || !runtimeResponse.ok) {
                throw new Error("runtime unavailable");
            }
            const health = await healthResponse.json();
            const runtimePayload = await runtimeResponse.json();
            setRuntime(runtimePayload.runtime || null);
            setRuntimeStatus(health.status === "ok" ? "Runtime online" : "Runtime degraded");
        } catch (error) {
            setRuntime(null);
            setRuntimeStatus("Runtime offline");
        }
    }

    async function fetchSkillCatalog() {
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/skill-catalog`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            const skills = payload.skills || [];
            setSkillCatalog(skills);
            setSelectedSkills((current) => {
                const available = new Set(skills.map((skill) => skill.name));
                const preserved = current.filter((name) => available.has(name));
                if (preserved.length > 0) {
                    return preserved;
                }
                return DEFAULT_SELECTED_SKILLS.filter((name) => available.has(name));
            });
        } catch (error) {
            console.debug("Failed to load skill catalog", error);
        }
    }

    async function refreshSessionContextState(sessionId) {
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/session/${encodeURIComponent(sessionId)}/context`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            updateSessionById(sessionId, (session) => {
                session.serverContextPercent = payload.context_percent ?? 0;
            });
            setContextPercent(payload.context_percent ?? 0);
        } catch (error) {
            console.debug("Failed to refresh session context state", error);
        }
    }

    async function hydrateSessionLocation(sessionId) {
        try {
            const resolved = await fetch(`${settingsRef.current.apiUrl}/location/resolve`, {
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
            await fetch(`${settingsRef.current.apiUrl}/location`, {
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

    function getLogFilterRange() {
        const now = Date.now();
        let fromMs = null;
        let toMs = null;

        if (logRange === "15m") {
            fromMs = now - 15 * 60 * 1000;
        } else if (logRange === "1h") {
            fromMs = now - 60 * 60 * 1000;
        } else if (logRange === "24h") {
            fromMs = now - 24 * 60 * 60 * 1000;
        } else if (logRange === "custom") {
            fromMs = logsFrom ? new Date(logsFrom).getTime() : null;
            toMs = logsTo ? new Date(logsTo).getTime() : null;
        }

        return { fromMs, toMs };
    }

    function getLogFilterIsoRange() {
        const { fromMs, toMs } = getLogFilterRange();
        return {
            start: Number.isFinite(fromMs) ? new Date(fromMs).toISOString() : null,
            end: Number.isFinite(toMs) ? new Date(toMs).toISOString() : null
        };
    }

    async function refreshLogsFromBackend() {
        if (!currentSessionId) {
            return;
        }
        try {
            const params = new URLSearchParams({ limit: "400" });
            const { start, end } = getLogFilterIsoRange();
            if (start) params.set("start", start);
            if (end) params.set("end", end);
            const response = await fetch(`${settingsRef.current.apiUrl}/logs/${encodeURIComponent(currentSessionId)}?${params.toString()}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            updateSessionById(currentSessionId, (session) => {
                session.logs = (payload.logs || []).map((entry, index) => ({
                    id: entry.id || `server_log_${index}_${entry.timestamp || Date.now()}`,
                    type: "llm_log",
                    ...entry
                }));
            });
        } catch (error) {
            console.debug("Failed to refresh logs from backend", error);
        }
    }

    function filteredLogs() {
        const logs = currentSession?.logs || [];
        const { fromMs, toMs } = getLogFilterRange();
        return logs.filter((entry) => {
            const ts = new Date(entry.timestamp || Date.now()).getTime();
            if (Number.isFinite(fromMs) && ts < fromMs) return false;
            if (Number.isFinite(toMs) && ts > toMs) return false;
            return true;
        });
    }

    function cyclePermissionMode() {
        setPermissionMode((current) => current === "ask" ? "plan" : "ask");
    }

    function toggleSkillSelection(skillName) {
        setSelectedSkills((current) => current.includes(skillName)
            ? current.filter((name) => name !== skillName)
            : [...current, skillName]
        );
    }

    function toggleAllSkills() {
        const allNames = skillCatalog.map((skill) => skill.name);
        const allSelected = allNames.length > 0 && allNames.every((name) => selectedSkills.includes(name));
        setSelectedSkills(allSelected ? [] : allNames);
    }

    function handleToolContextChange(nextToolContext) {
        setToolContext(nextToolContext);
    }

    function toggleThinkingEntry(entryId) {
        setExpandedThinking((current) => ({
            ...current,
            [entryId]: !current[entryId]
        }));
    }

    async function sendMessage() {
        if (isSending) return;
        const content = messageInput.trim();
        if (!content || !currentSessionId) return;

        const sessionId = currentSessionId;
        const requestMode = isSimpleChat(content) ? "agent" : mode;
        const { toolContext: selectedToolContext, context } = buildContextPayload(toolContext);
        setIsSending(true);
        setContextPercent(computeContextPercent(currentSession, toolContext));

        appendTranscriptEntry(sessionId, {
            role: "user",
            content,
            kind: "user_text",
            taskId: "main"
        });
        updateSessionById(sessionId, (session) => {
            if (session.transcript.length <= 1) {
                session.title = content.slice(0, 36) || "New thread";
            }
        });
        setMessageInput("");

        let assistantEntry = null;
        let thinkingEntry = null;
        let answerBuffer = "";

        if (thinkingMode) {
            thinkingEntry = appendTranscriptEntry(sessionId, {
                role: "assistant",
                content: "",
                kind: "thinking_text",
                taskId: "main",
                streaming: true,
                pendingPlaceholder: true
            });
        }

        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/chat/stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tool_name: "chat",
                    message: content,
                    session_id: sessionId,
                    permission_mode: permissionMode,
                    permission_confirmed: permissionMode !== "ask",
                    thinking_mode: thinkingMode,
                    mode: requestMode,
                    tool_context: selectedToolContext,
                    enabled_skills: selectedSkills,
                    context,
                    parameters: {
                        message: content,
                        session_id: sessionId,
                        permission_mode: permissionMode,
                        permission_confirmed: permissionMode !== "ask",
                        thinking_mode: thinkingMode,
                        mode: requestMode,
                        tool_context: selectedToolContext,
                        enabled_skills: selectedSkills,
                        context
                    }
                })
            });

            if (!response.ok || !response.body) {
                throw new Error(`HTTP ${response.status}`);
            }

            const processSseChunk = (rawLine) => {
                if (!rawLine.startsWith("data: ")) {
                    return;
                }
                const payload = JSON.parse(rawLine.slice(6));

                if (payload.type === "task_start") {
                    appendTranscriptEntry(sessionId, {
                        role: "assistant",
                        content: payload.description || `Started ${payload.skill || "tool"}`,
                        kind: "tool_use",
                        taskId: payload.task_id || `task_${Date.now()}`,
                        toolName: payload.skill || "tool",
                        phase: payload.phase || "execution"
                    });
                    return;
                }

                if (payload.type === "task_complete") {
                    appendTranscriptEntry(sessionId, {
                        role: "assistant",
                        content: payload.content || payload.description || "Task completed.",
                        kind: "tool_result",
                        taskId: payload.task_id || `task_${Date.now()}`,
                        toolName: payload.skill || payload.description || "tool",
                        phase: payload.phase || "execution",
                        success: payload.success
                    });
                    return;
                }

                if (payload.type === "compression_start" || payload.type === "compression_complete") {
                    appendTranscriptEntry(sessionId, {
                        role: "assistant",
                        content: payload.content || (payload.type === "compression_start" ? "Compressing context..." : "Context compression complete."),
                        kind: "system_notice",
                        taskId: "main",
                        phase: "compression"
                    });
                    const nextPercent = payload.type === "compression_complete"
                        ? (payload.after_percent ?? contextPercent)
                        : (payload.target_percent ?? contextPercent);
                    updateSessionById(sessionId, (session) => {
                        session.contextPercentOverride = nextPercent;
                        session.serverContextPercent = nextPercent;
                    });
                    setContextPercent(nextPercent);
                    return;
                }

                if (payload.type === "context_state") {
                    const nextPercent = payload.context_percent ?? 0;
                    updateSessionById(sessionId, (session) => {
                        session.serverContextPercent = nextPercent;
                    });
                    setContextPercent(nextPercent);
                    return;
                }

                if (payload.type === "phase" || payload.type === "layer_start" || payload.type === "verification" || payload.type === "complete") {
                    appendTranscriptEntry(sessionId, {
                        role: "assistant",
                        content: payload.content || payload.phase || "System update",
                        kind: "system_notice",
                        taskId: "main",
                        phase: payload.phase || null
                    });
                    return;
                }

                if (payload.type === "llm_log") {
                    appendLog(sessionId, {
                        type: "llm_log",
                        timestamp: payload.timestamp || nowIso(),
                        phase: payload.phase,
                        direction: payload.direction,
                        payload: payload.payload
                    });
                    return;
                }

                if (payload.type === "thinking_delta") {
                    if (!thinkingMode) {
                        return;
                    }
                    const nextThinking = `${thinkingEntry?.content || ""}${payload.delta || ""}`;
                    if (!thinkingEntry) {
                        thinkingEntry = appendTranscriptEntry(sessionId, {
                            role: "assistant",
                            content: nextThinking,
                            kind: "thinking_text",
                            taskId: "main",
                            streaming: true
                        });
                    } else {
                        thinkingEntry = { ...thinkingEntry, content: nextThinking, pendingPlaceholder: false };
                        patchTranscriptEntry(sessionId, thinkingEntry.id, {
                            content: nextThinking,
                            streaming: true,
                            pendingPlaceholder: false
                        });
                    }
                    return;
                }

                if (payload.type === "answer_delta" || payload.content) {
                    answerBuffer += payload.delta || payload.content || "";
                    if (!answerBuffer.trim()) {
                        return;
                    }
                    if (!assistantEntry) {
                        assistantEntry = appendTranscriptEntry(sessionId, {
                            role: "assistant",
                            content: answerBuffer,
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: true
                        });
                    } else {
                        patchTranscriptEntry(sessionId, assistantEntry.id, {
                            content: answerBuffer,
                            streaming: true
                        });
                    }
                }

                if (payload.error) {
                    throw new Error(payload.error);
                }

                if (payload.done) {
                    if (assistantEntry) {
                        patchTranscriptEntry(sessionId, assistantEntry.id, { streaming: false });
                    } else if (answerBuffer.trim()) {
                        assistantEntry = appendTranscriptEntry(sessionId, {
                            role: "assistant",
                            content: answerBuffer.trim(),
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: false
                        });
                    } else {
                        throw new Error("模型没有返回可显示的正文");
                    }

                    if (thinkingEntry) {
                        if (thinkingEntry.pendingPlaceholder && !(thinkingEntry.content || "").trim()) {
                            removeTranscriptEntry(sessionId, thinkingEntry.id);
                            thinkingEntry = null;
                        } else {
                            patchTranscriptEntry(sessionId, thinkingEntry.id, {
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
                const normalizedBuffer = buffer.replace(/\r\n/g, "\n");
                const lines = normalizedBuffer.split("\n");
                buffer = lines.pop() || "";
                for (const line of lines) {
                    const trimmed = line.trim();
                    if (trimmed.startsWith("data: ")) {
                        processSseChunk(trimmed);
                    }
                }
                if (done) {
                    const tail = buffer.trim();
                    if (tail.startsWith("data: ")) {
                        processSseChunk(tail);
                    }
                    break;
                }
            }
        } catch (error) {
            if (thinkingEntry) {
                if (thinkingEntry.pendingPlaceholder && !(thinkingEntry.content || "").trim()) {
                    removeTranscriptEntry(sessionId, thinkingEntry.id);
                } else {
                    patchTranscriptEntry(sessionId, thinkingEntry.id, {
                        streaming: false,
                        pendingPlaceholder: false
                    });
                }
            }
            appendTranscriptEntry(sessionId, {
                role: "assistant",
                content: `请求失败: ${error.message}`,
                kind: "assistant_text",
                taskId: "main",
                streaming: false
            });
        } finally {
            setIsSending(false);
        }
    }

    function handleComposerKeyDown(event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    }

    const sessionPreviewList = sessions
        .slice()
        .sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt));

    const logEntries = filteredLogs().slice().reverse();

    return (
        <div className="app-shell">
            <aside className="sidebar">
                <div className="brand-panel">
                    <button className="search-shell active" type="button">
                        <i className="fas fa-sparkles" />
                        <span>Search</span>
                    </button>
                </div>

                <div className="sidebar-group">
                    <button className="sidebar-action" type="button" onClick={createSession}>
                        <i className="fas fa-plus" />
                        <span>New thread</span>
                    </button>
                    <button className="sidebar-link active" type="button">
                        <i className="fas fa-clock-rotate-left" />
                        <span>History</span>
                    </button>
                </div>

                <div className="history-panel">
                    <div className="section-heading">
                        <span>Threads</span>
                        <button className="ghost-icon" type="button" title="清空当前会话" onClick={clearCurrentSession}>
                            <i className="fas fa-trash" />
                        </button>
                    </div>
                    <div className="session-list">
                        {sessionPreviewList.map((session) => {
                            const preview = session.transcript.at(-1)?.content || "Start a new thread...";
                            return (
                                <button
                                    key={session.id}
                                    type="button"
                                    className={`session-item${session.id === currentSessionId ? " active" : ""}`}
                                    onClick={() => setCurrentSessionId(session.id)}
                                >
                                    <span className="session-active-indicator" aria-hidden="true" />
                                    <div className="session-name">{session.title}</div>
                                    <div className="session-preview">{preview.slice(0, 90)}</div>
                                </button>
                            );
                        })}
                    </div>
                    {sessionPreviewList.length === 0 ? (
                        <p className="history-empty">Recent and active threads will appear here.</p>
                    ) : null}
                </div>
            </aside>

            <main className="workspace">
                <header className="topbar">
                    <div>
                        <p className="eyebrow">OBS Agent Workspace</p>
                        <h1>{currentSession?.title || "New thread"}</h1>
                    </div>
                    <div className="topbar-actions">
                        <div className={`status-chip ${runtime ? "online" : "offline"}`}>
                            <span className="status-dot" />
                            <span>{runtimeStatus}</span>
                        </div>
                        <button className="icon-button" type="button" title="导出会话" onClick={exportCurrentSession}>
                            <i className="fas fa-download" />
                        </button>
                    </div>
                </header>

                <RuntimePills mode={mode} setMode={setMode} runtime={runtime} contextPercent={contextPercent} />

                {!currentSession?.transcript?.length ? (
                    <section className="hero" id="welcome-screen">
                        <div className="hero-mark">obs</div>
                        <p className="hero-copy">
                            参考 Claude Code 的真实源码结构，把消息流、状态行、任务面板和权限/模式信息合并成一个统一工作台。
                        </p>
                    </section>
                ) : null}

                <TranscriptView
                    transcript={currentSession?.transcript || []}
                    chatMessagesRef={chatMessagesRef}
                    expandedThinking={expandedThinking}
                    onToggleThinking={toggleThinkingEntry}
                    onReplay={setMessageInput}
                />

                <Composer
                    toolContext={toolContext}
                    onToolContextChange={handleToolContextChange}
                    permissionMode={permissionMode}
                    onPermissionToggle={cyclePermissionMode}
                    thinkingMode={thinkingMode}
                    onThinkingToggle={() => setThinkingMode((current) => !current)}
                    value={messageInput}
                    onChange={setMessageInput}
                    onKeyDown={handleComposerKeyDown}
                    onSend={sendMessage}
                    isSending={isSending}
                    runtime={runtime}
                    logsOpen={logsOpen}
                    onLogsToggle={() => setLogsOpen((current) => !current)}
                    skillsOpen={skillsOpen}
                    onSkillsToggle={() => setSkillsOpen((current) => !current)}
                    statusItems={[
                        `mode:${mode}`,
                        `permission:${permissionMode}`,
                        `context:${toolContext}`,
                        `messages:${currentSession?.transcript?.length || 0}`,
                        `model:${shortenModel(runtime?.model)}`
                    ]}
                    inputRef={messageInputRef}
                />
            </main>

            <LogsDrawer
                open={logsOpen}
                logRange={logRange}
                setLogRange={setLogRange}
                logsFrom={logsFrom}
                setLogsFrom={setLogsFrom}
                logsTo={logsTo}
                setLogsTo={setLogsTo}
                onRefresh={refreshLogsFromBackend}
                onClose={() => setLogsOpen(false)}
                logs={logEntries}
            />
            <SkillsDrawer
                open={skillsOpen}
                skills={skillCatalog}
                selectedSkills={selectedSkills}
                onToggleAll={toggleAllSkills}
                onToggleSkill={toggleSkillSelection}
                onClose={() => setSkillsOpen(false)}
            />
        </div>
    );
}

export default App;
