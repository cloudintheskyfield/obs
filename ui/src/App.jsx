import React, { useEffect, useRef, useState } from "react";
import Composer from "./components/Composer.jsx";
import LogsDrawer from "./components/LogsDrawer.jsx";
import RuntimePills from "./components/RuntimePills.jsx";
import SkillsDrawer from "./components/SkillsDrawer.jsx";
import TranscriptView from "./components/TranscriptView.jsx";
import WorkspaceModal from "./components/WorkspaceModal.jsx";
import { formatWorkspaceBreadcrumb, shortenModel } from "./lib/formatting.js";

const STORAGE_VERSION = "20260408-01";
const SETTINGS_KEY = "obs-agent-settings";
const SESSIONS_KEY = "obs-agent-sessions";
const VERSION_KEY = "obs-agent-storage-version";
const DEFAULT_SELECTED_SKILLS = ["code-sandbox", "file-operations", "terminal", "web-search"];
const IMAGE_TOKEN_PATTERN = /\[\[image:([^\]]+)\]\]/g;

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

function buildContextPayload(toolContext, workspacePath) {
    const breadcrumb = formatWorkspaceBreadcrumb(workspacePath, 6);
    const contextMap = {
        workspace: [
            "Focus on the current workspace, local files, directories, code structure, and repository state.",
            workspacePath ? `Current workspace root: ${workspacePath}` : null,
            workspacePath ? `Workspace hierarchy (leaf to root): ${breadcrumb}` : null,
            "The workspace should be treated as the main writable environment for solving the user's goal."
        ].filter(Boolean).join("\n")
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
    const contextBonus = 4;
    return historySize > 0
        ? Math.min(98, Math.max(1, Math.round(historySize / 140) + contextBonus))
        : contextBonus;
}

function computeNextContextPercent(session, toolContext, input) {
    const baseline = typeof session?.contextPercentOverride === "number" ? session.contextPercentOverride : null;
    const historySize = (session?.transcript || []).reduce((sum, entry) => sum + (entry.content?.length || 0), 0) + input.length;
    const contextBonus = 4;
    const estimated = Math.min(98, Math.max(1, Math.round(historySize / 140) + contextBonus));
    return baseline !== null
        ? Math.min(98, Math.max(baseline, baseline + Math.round(input.length / 120)))
        : estimated;
}

function buildImageToken(id) {
    return `[[image:${id}]]`;
}

function createImageLabel(index) {
    return `Image ${index + 1}`;
}

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(reader.error || new Error("Failed to read image"));
        reader.readAsDataURL(file);
    });
}

function buildMessageParts(rawValue, images) {
    const imageMap = new Map((images || []).map((image, index) => [image.id, { ...image, order: index }]));
    const source = String(rawValue || "");
    const parts = [];
    let cursor = 0;
    let match;

    IMAGE_TOKEN_PATTERN.lastIndex = 0;
    while ((match = IMAGE_TOKEN_PATTERN.exec(source)) !== null) {
        const before = source.slice(cursor, match.index);
        if (before) {
            parts.push({ type: "text", text: before });
        }
        const image = imageMap.get(match[1]);
        if (image) {
            parts.push({
                type: "image",
                id: image.id,
                name: image.name || createImageLabel(image.order || 0),
                data_url: image.dataUrl,
            });
        }
        cursor = match.index + match[0].length;
    }

    const tail = source.slice(cursor);
    if (tail) {
        parts.push({ type: "text", text: tail });
    }

    const matchedIds = new Set(parts.filter((part) => part.type === "image").map((part) => part.id));
    (images || []).forEach((image, index) => {
        if (!matchedIds.has(image.id)) {
            parts.push({
                type: "image",
                id: image.id,
                name: image.name || createImageLabel(index),
                data_url: image.dataUrl,
            });
        }
    });

    return parts;
}

function buildVisibleMessageText(rawValue, images) {
    const imageMap = new Map((images || []).map((image, index) => [image.id, createImageLabel(index)]));
    return String(rawValue || "").replace(IMAGE_TOKEN_PATTERN, (_, id) => `[${imageMap.get(id) || "Image"}]`);
}

function hasSendableInput(rawValue, images) {
    const visibleText = buildVisibleMessageText(rawValue, images).replace(/\[Image \d+\]/g, "").trim();
    return Boolean(visibleText || (images || []).length);
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
    const [workspacePath, setWorkspacePath] = useState("");
    const [workspaceModalOpen, setWorkspaceModalOpen] = useState(false);
    const [workspaceDraftPath, setWorkspaceDraftPath] = useState("");
    const [workspaceBrowserPath, setWorkspaceBrowserPath] = useState("");
    const [workspaceBrowserParent, setWorkspaceBrowserParent] = useState("");
    const [workspaceBrowserEntries, setWorkspaceBrowserEntries] = useState([]);
    const [workspaceLoading, setWorkspaceLoading] = useState(false);
    const [workspaceError, setWorkspaceError] = useState("");
    const [thinkingMode, setThinkingMode] = useState(true);
    const [permissionMode, setPermissionMode] = useState("ask");
    const [availableModels, setAvailableModels] = useState(["MiniMax-M2"]);
    const [selectedModel, setSelectedModel] = useState("MiniMax-M2");
    const [messageInput, setMessageInput] = useState("");
    const [composerImages, setComposerImages] = useState([]);
    const [isSending, setIsSending] = useState(false);
    const [requestIndicator, setRequestIndicator] = useState(null);
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
                if (stored.workspacePath) {
                    setWorkspacePath(stored.workspacePath);
                    setWorkspaceDraftPath(stored.workspacePath);
                }
                if (Array.isArray(stored.selectedSkills) && stored.selectedSkills.length > 0) {
                    setSelectedSkills(stored.selectedSkills);
                }
                if (stored.selectedModel) {
                    setSelectedModel(stored.selectedModel);
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
            workspacePath,
            selectedSkills,
            selectedModel
        }));
    }, [permissionMode, thinkingMode, toolContext, workspacePath, selectedSkills, selectedModel]);

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
        refreshWorkspaceState();
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
            const modelOptions = runtimePayload.runtime?.available_models?.length
                ? runtimePayload.runtime.available_models
                : [runtimePayload.runtime?.model || "MiniMax-M2"];
            setAvailableModels(modelOptions);
            setSelectedModel((current) => modelOptions.includes(current) ? current : (runtimePayload.runtime?.model || modelOptions[0] || "MiniMax-M2"));
            const runtimeWorkspace = runtimePayload.runtime?.work_dir || "";
            if (runtimeWorkspace) {
                setWorkspacePath(runtimeWorkspace);
                setWorkspaceDraftPath((current) => current || runtimeWorkspace);
            }
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

    async function refreshWorkspaceState() {
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/workspace`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            const nextPath = payload.workspace?.path || "";
            if (nextPath) {
                setWorkspacePath(nextPath);
                setWorkspaceDraftPath((current) => current || nextPath);
            }
        } catch (error) {
            console.debug("Failed to load workspace state", error);
        }
    }

    async function browseWorkspace(nextPath) {
        setWorkspaceLoading(true);
        setWorkspaceError("");
        try {
            const params = new URLSearchParams();
            if (nextPath) {
                params.set("path", nextPath);
            }
            const response = await fetch(`${settingsRef.current.apiUrl}/workspace/browser?${params.toString()}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            setWorkspaceBrowserPath(payload.current || "");
            setWorkspaceBrowserParent(payload.parent || "");
            setWorkspaceBrowserEntries(payload.entries || []);
            setWorkspaceDraftPath(payload.current || nextPath || "");
        } catch (error) {
            setWorkspaceError(error.message || "Failed to browse directories");
        } finally {
            setWorkspaceLoading(false);
        }
    }

    async function openWorkspaceModal() {
        setWorkspaceModalOpen(true);
        const initialPath = workspacePath || runtime?.work_dir || "";
        setWorkspaceDraftPath(initialPath);
        await browseWorkspace(initialPath);
    }

    async function openNativeWorkspacePicker() {
        if (typeof window.showDirectoryPicker !== "function") {
            setWorkspaceError("Native folder picking is not available in this browser. Use the path field or directory browser below.");
            return;
        }
        try {
            const handle = await window.showDirectoryPicker();
            setWorkspaceError(
                `Selected “${handle.name}”. Browsers usually do not expose the absolute local path here, so please confirm it with the path field or directory browser before saving.`
            );
        } catch (error) {
            if (error?.name !== "AbortError") {
                setWorkspaceError(error.message || "Failed to open folder picker");
            }
        }
    }

    async function saveWorkspaceSelection() {
        if (!workspaceDraftPath.trim()) {
            setWorkspaceError("Workspace path is required");
            return;
        }
        setWorkspaceLoading(true);
        setWorkspaceError("");
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/workspace`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: workspaceDraftPath.trim() })
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.success === false) {
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            const resolved = payload.workspace?.path || workspaceDraftPath.trim();
            setWorkspacePath(resolved);
            setWorkspaceDraftPath(resolved);
            setWorkspaceModalOpen(false);
            await refreshRuntime();
        } catch (error) {
            setWorkspaceError(error.message || "Failed to update workspace");
        } finally {
            setWorkspaceLoading(false);
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

    function cycleModel() {
        setSelectedModel((current) => {
            if (!availableModels.length) {
                return current;
            }
            const index = availableModels.indexOf(current);
            const nextIndex = index === -1 ? 0 : (index + 1) % availableModels.length;
            return availableModels[nextIndex];
        });
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
        setToolContext(nextToolContext || "workspace");
    }

    function toggleThinkingEntry(entryId) {
        setExpandedThinking((current) => ({
            ...current,
            [entryId]: !current[entryId]
        }));
    }

    async function handleComposerPaste(event) {
        const clipboardItems = Array.from(event.clipboardData?.items || []);
        const imageFiles = clipboardItems
            .filter((item) => item.kind === "file")
            .map((item) => item.getAsFile())
            .filter((file) => file && file.type.startsWith("image/"));

        if (!imageFiles.length) {
            return;
        }

        event.preventDefault();
        const start = messageInputRef.current?.selectionStart ?? messageInput.length;
        const end = messageInputRef.current?.selectionEnd ?? messageInput.length;

        const nextImages = [];
        for (let index = 0; index < imageFiles.length; index += 1) {
            const file = imageFiles[index];
            const imageId = `img_${Date.now()}_${Math.random().toString(16).slice(2, 8)}_${index}`;
            const dataUrl = await readFileAsDataUrl(file);
            nextImages.push({
                id: imageId,
                name: file.name || createImageLabel(composerImages.length + index),
                dataUrl,
            });
        }

        const insertion = nextImages.map((image) => buildImageToken(image.id)).join(" ");
        setComposerImages((current) => [...current, ...nextImages]);
        setMessageInput((current) => `${current.slice(0, start)}${insertion}${current.slice(end)}`);

        requestAnimationFrame(() => {
            if (!messageInputRef.current) return;
            const cursor = start + insertion.length;
            messageInputRef.current.focus();
            messageInputRef.current.setSelectionRange(cursor, cursor);
        });
    }

    async function sendMessage() {
        if (isSending) return;
        const rawInput = messageInput;
        const messageParts = buildMessageParts(rawInput, composerImages);
        const content = buildVisibleMessageText(rawInput, composerImages).trim();
        if (!hasSendableInput(rawInput, composerImages) || !currentSessionId) return;

        const sessionId = currentSessionId;
        const requestMode = isSimpleChat(content) ? "agent" : mode;
        const { toolContext: selectedToolContext, context } = buildContextPayload("workspace", workspacePath || runtime?.work_dir || "");
        setIsSending(true);
        setRequestIndicator({
            active: true,
            label: thinkingMode ? "Preparing reasoning" : "Working on your request",
        });
        setContextPercent(computeContextPercent(currentSession, toolContext));

        appendTranscriptEntry(sessionId, {
            role: "user",
            content,
            kind: "user_text",
            taskId: "main",
            images: composerImages,
        });
        updateSessionById(sessionId, (session) => {
            if (session.transcript.length <= 1) {
                session.title = content.slice(0, 36) || "New thread";
            }
        });
        setMessageInput("");
        setComposerImages([]);

        let assistantEntry = null;
        let thinkingEntry = null;
        let answerBuffer = "";

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
                    model: selectedModel,
                    tool_context: selectedToolContext,
                    workspace_path: workspacePath || runtime?.work_dir || "",
                    enabled_skills: selectedSkills,
                    message_parts: messageParts,
                    context,
                    parameters: {
                        message: content,
                        session_id: sessionId,
                        permission_mode: permissionMode,
                        permission_confirmed: permissionMode !== "ask",
                        thinking_mode: thinkingMode,
                        mode: requestMode,
                        model: selectedModel,
                        tool_context: selectedToolContext,
                        workspace_path: workspacePath || runtime?.work_dir || "",
                        enabled_skills: selectedSkills,
                        message_parts: messageParts,
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

                const appendThinkingTrace = (line) => {
                    if (!thinkingMode || !line) {
                        return;
                    }
                    const nextThinking = `${thinkingEntry?.content || ""}${thinkingEntry?.content ? "\n" : ""}${line}`;
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
                };

                if (payload.type === "task_start") {
                    setRequestIndicator((current) => current?.active ? {
                        ...current,
                        label: `Running ${payload.skill || "tool"}`,
                    } : current);
                    appendThinkingTrace(`- Running \`${payload.skill || "tool"}\``);
                    return;
                }

                if (payload.type === "task_complete") {
                    appendThinkingTrace(
                        payload.success === false
                            ? `- \`${payload.description || payload.skill || "tool"}\` failed`
                            : `- \`${payload.description || payload.skill || "tool"}\` completed`
                    );
                    return;
                }

                if (payload.type === "compression_start" || payload.type === "compression_complete") {
                    appendTranscriptEntry(sessionId, {
                        role: "assistant",
                        content: payload.content || (
                            payload.type === "compression_start"
                                ? "Automatically compacting context"
                                : "Context compacted"
                        ),
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
                    setRequestIndicator(null);
                    const separator = thinkingEntry?.content && payload.delta && !String(thinkingEntry.content).endsWith("\n") && !String(payload.delta).startsWith("\n")
                        ? "\n"
                        : "";
                    const nextThinking = `${thinkingEntry?.content || ""}${separator}${payload.delta || ""}`;
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
                    setRequestIndicator(null);
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
                    setRequestIndicator(null);
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
                        patchTranscriptEntry(sessionId, thinkingEntry.id, {
                            streaming: false,
                            pendingPlaceholder: false
                        });
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
            setRequestIndicator(null);
            if (thinkingEntry) {
                patchTranscriptEntry(sessionId, thinkingEntry.id, {
                    streaming: false,
                    pendingPlaceholder: false
                });
            }
            appendTranscriptEntry(sessionId, {
                role: "assistant",
                content: `请求失败: ${error.message}`,
                kind: "assistant_text",
                taskId: "main",
                streaming: false
            });
        } finally {
            setRequestIndicator(null);
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
    const activeWorkspacePath = workspacePath || runtime?.work_dir || "";
    const workspaceSummary = formatWorkspaceBreadcrumb(activeWorkspacePath, 6);
    const nativeWorkspaceLabel = /mac/i.test(window.navigator.platform || "")
        ? "Pick Folder (macOS)"
        : (/win/i.test(window.navigator.platform || "") ? "Pick Folder (Windows)" : "Pick Folder");

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

                <RuntimePills mode={mode} setMode={setMode} contextPercent={contextPercent} />

                <TranscriptView
                    transcript={currentSession?.transcript || []}
                    chatMessagesRef={chatMessagesRef}
                    expandedThinking={expandedThinking}
                    onToggleThinking={toggleThinkingEntry}
                    onReplay={setMessageInput}
                    requestIndicator={requestIndicator}
                />

                <Composer
                    selectedModel={selectedModel}
                    onModelToggle={cycleModel}
                    permissionMode={permissionMode}
                    onPermissionToggle={cyclePermissionMode}
                    thinkingMode={thinkingMode}
                    onThinkingToggle={() => setThinkingMode((current) => !current)}
                    value={messageInput}
                    onChange={setMessageInput}
                    onKeyDown={handleComposerKeyDown}
                    onPaste={handleComposerPaste}
                    onSend={sendMessage}
                    isSending={isSending}
                    images={composerImages}
                    logsOpen={logsOpen}
                    onLogsToggle={() => setLogsOpen((current) => !current)}
                    skillsOpen={skillsOpen}
                    onSkillsToggle={() => setSkillsOpen((current) => !current)}
                    workspacePath={activeWorkspacePath}
                    workspaceSummary={workspaceSummary}
                    onWorkspaceOpen={openWorkspaceModal}
                    statusItems={[
                        `mode:${mode}`,
                        `permission:${permissionMode}`,
                        `workspace:${activeWorkspacePath || "--"}`,
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
            <WorkspaceModal
                open={workspaceModalOpen}
                currentPath={activeWorkspacePath}
                browserPath={workspaceBrowserPath}
                browserEntries={workspaceBrowserEntries}
                browserParent={workspaceBrowserParent}
                isLoading={workspaceLoading}
                draftPath={workspaceDraftPath}
                error={workspaceError}
                onDraftChange={setWorkspaceDraftPath}
                onBrowse={browseWorkspace}
                onOpenParent={() => browseWorkspace(workspaceBrowserParent)}
                onNativePick={openNativeWorkspacePicker}
                nativePickLabel={nativeWorkspaceLabel}
                onClose={() => setWorkspaceModalOpen(false)}
                onSave={saveWorkspaceSelection}
            />
        </div>
    );
}

export default App;
