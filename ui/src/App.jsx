import React, { useEffect, useRef, useState } from "react";
import Composer from "./components/Composer.jsx";
import ArchitectureDrawer from "./components/ArchitectureDrawer.jsx";
import LogsDrawer from "./components/LogsDrawer.jsx";
import RuntimePills from "./components/RuntimePills.jsx";
import SkillsDrawer from "./components/SkillsDrawer.jsx";
import TranscriptView from "./components/TranscriptView.jsx";
import WorkspaceModal from "./components/WorkspaceModal.jsx";
import { formatWorkspaceBreadcrumb, shortenModel } from "./lib/formatting.js";

const STORAGE_VERSION = "20260415-01";
const SETTINGS_KEY = "obs-agent-settings";
const SESSIONS_KEY = "obs-agent-sessions";
const VERSION_KEY = "obs-agent-storage-version";
const DEFAULT_SELECTED_SKILLS = ["code-sandbox", "file-operations", "terminal", "web-search", "weather"];
const IMAGE_TOKEN_PATTERN = /\[\[image:([^\]]+)\]\]/g;
const GITHUB_REPO_URL = "https://github.com/cloudintheskyfield/obs";
const LOGO_SRC = "/static/obs-code-logo.svg";
const MODEL_CONTEXT_WINDOWS = {
    "MiniMax-M2": 200000,
};

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

function safeSetLocalStorage(key, value) {
    try {
        localStorage.setItem(key, value);
        return true;
    } catch (error) {
        console.warn(`Failed to persist localStorage key: ${key}`, error);
        if (error?.name === "QuotaExceededError") {
            try {
                localStorage.removeItem(SESSIONS_KEY);
            } catch (cleanupError) {
                console.warn("Failed to clear oversized session cache", cleanupError);
            }
        }
        return false;
    }
}

function explainWorkspacePickerBoundary() {
    return "Pick Folder opens on the machine running the OBS backend. If you opened this page from another computer, browsers cannot provide that computer's absolute local folder path to the server workspace. To use your own computer's real local path, run OBS locally on that computer.";
}

function formatWorkingDuration(durationMs) {
    const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) {
        return `Working for ${hours}h ${minutes}m ${seconds}s`;
    }
    if (minutes > 0) {
        return `Working for ${minutes}m ${seconds}s`;
    }
    return `Working for ${seconds}s`;
}

function createEmptySession(id) {
    return {
        id,
        title: "New thread",
        transcript: [],
        logs: [],
        contextPercentOverride: null,
        serverContextPercent: null,
        serverContextTokens: 0,
        serverContextMaxTokens: null,
        tasks: {},
        workspacePath: "",
        activeTodo: null,
        selectedModel: "",   // "" means "use the global default"
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
        compressionState: entry.compressionState || null,
        success: entry.success,
        pendingPlaceholder: Boolean(entry.pendingPlaceholder),
        timestamp: entry.timestamp || nowIso(),
        streaming: Boolean(entry.streaming),
        images: compactTranscriptImages(entry.images),
    };
}

function compactTranscriptImages(images) {
    if (!Array.isArray(images) || images.length === 0) {
        return undefined;
    }
    return images
        .filter((image) => image && typeof image === "object")
        .map((image, index) => ({
            id: image.id || `image_${index}`,
            name: image.name || createImageLabel(index),
            dataUrl: image.dataUrl || image.data_url,
        }));
}

function upgradeSession(session) {
    const next = {
        ...session,
        transcript: Array.isArray(session.transcript)
            ? session.transcript.map((entry) => normalizeEntry(entry || {}))
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
        // server context values are request-scoped snapshots; clear them on load so the
        // frontend always derives a fresh estimate from the transcript until the next
        // backend request provides authoritative values.
        serverContextPercent: null,
        serverContextTokens: 0,
        serverContextMaxTokens: typeof session.serverContextMaxTokens === "number" ? session.serverContextMaxTokens : null,
        title: session.title || "New thread",
        workspacePath: typeof session.workspacePath === "string" ? session.workspacePath : "",
        activeTodo: session.activeTodo || null,
        selectedModel: typeof session.selectedModel === "string" ? session.selectedModel : "",
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
            workspacePath ? `Workspace parent chain: ${breadcrumb}` : null,
            "The workspace should be treated as the main writable environment for solving the user's goal."
        ].filter(Boolean).join("\n")
    };
    return {
        toolContext,
        context: contextMap[toolContext] || contextMap.workspace
    };
}

function computeContextPercent(session, maxTokens) {
    if (typeof session?.serverContextPercent === "number") {
        return session.serverContextPercent;
    }
    if (typeof session?.contextPercentOverride === "number") {
        return session.contextPercentOverride;
    }
    // Derive percent from the same token estimate used to display contextTokens so
    // both numbers are always consistent (e.g. 1.2K / 200K · 0.6%).
    const tokens = estimateContextTokensFromTranscript(session);
    const max = maxTokens || 200000;
    if (tokens <= 0) return 0;
    return Math.min(98, (tokens / max) * 100);
}

function getModelContextWindow(modelName) {
    return MODEL_CONTEXT_WINDOWS[modelName] || 128000;
}

function estimateContextTokensFromTranscript(session) {
    const text = (session?.transcript || []).map((entry) => entry.content || "").join("\n");
    if (!text) {
        return 0;
    }
    const cjkCount = (text.match(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g) || []).length;
    const remaining = text.replace(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g, " ");
    const wordLike = remaining.match(/[A-Za-z0-9_]+/g) || [];
    const punctuationLike = remaining.match(/[^\sA-Za-z0-9_]/g) || [];
    const wordTokens = wordLike.reduce((sum, word) => sum + Math.max(1, Math.round(word.length / 4)), 0);
    const punctuationTokens = Math.round(punctuationLike.length * 0.35);
    return cjkCount + wordTokens + punctuationTokens;
}

function computeNextContextPercent(session, toolContext, input) {
    // Estimate tokens for current transcript + new input, then compute percent
    const existingTokens = estimateContextTokensFromTranscript(session);
    const inputTokens = Math.round(input.length / 4); // rough: 4 chars per token for latin
    const totalTokens = existingTokens + inputTokens;
    const maxTokens = getModelContextWindow(session?.selectedModel) || 200000;
    return Math.min(98, (totalTokens / maxTokens) * 100);
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
    const [contextTokens, setContextTokens] = useState(0);
    const [contextMaxTokens, setContextMaxTokens] = useState(200000);
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
    const [composerImages, setComposerImages] = useState([]);
    const [composerHistoryIndex, setComposerHistoryIndex] = useState(null);
    const [composerHistoryDraft, setComposerHistoryDraft] = useState("");
    const [isSending, setIsSending] = useState(false);
    const [requestIndicator, setRequestIndicator] = useState(null);
    const [requestTimerNow, setRequestTimerNow] = useState(() => Date.now());
    const [completedLabel, setCompletedLabel] = useState(null);
    const [justSentSessionId, setJustSentSessionId] = useState(null);
    const sendStartTimeRef = React.useRef(null);
    // Background-session activity badges: { [sessionId]: 'working' | 'done' | 'fading' }
    const [sessionBadges, setSessionBadges] = useState({});
    const sendingSessionIdRef = React.useRef(null);
    const [logsOpen, setLogsOpen] = useState(false);
    const [skillsOpen, setSkillsOpen] = useState(false);
    const [architectureOpen, setArchitectureOpen] = useState(false);
    const [architectureManifest, setArchitectureManifest] = useState(null);
    const [logRange, setLogRange] = useState("1h");
    const [logsFrom, setLogsFrom] = useState("");
    const [logsTo, setLogsTo] = useState("");
    const [expandedThinking, setExpandedThinking] = useState({});
    const [skillCatalog, setSkillCatalog] = useState([]);
    const [selectedSkills, setSelectedSkills] = useState(DEFAULT_SELECTED_SKILLS);

    const [activeTodo, setActiveTodo] = useState(null); // { items: [{text,done}], visible: true }

    const messageInputRef = useRef(null);
    const chatMessagesRef = useRef(null);
    const sessionsRef = useRef([]);
    const currentSessionIdRef = useRef(null);
    const settingsRef = useRef(settings);
    const initialLoadDoneRef = useRef(false);
    const abortControllerRef = useRef(null);

    useEffect(() => {
        settingsRef.current = settings;
    }, [settings]);

    useEffect(() => {
        sessionsRef.current = sessions;
    }, [sessions]);

    useEffect(() => {
        currentSessionIdRef.current = currentSessionId;
    }, [currentSessionId]);

    // When the user switches away from the generating session, show a "working" badge
    // on that session in the sidebar.
    useEffect(() => {
        const genId = sendingSessionIdRef.current;
        if (isSending && genId && currentSessionId !== genId) {
            setSessionBadges((prev) => {
                if (prev[genId] && prev[genId] !== "fading") return prev;
                return { ...prev, [genId]: "working" };
            });
        }
    }, [currentSessionId, isSending]);

    useEffect(() => {
        try {
            const storedVersion = localStorage.getItem(VERSION_KEY);
            if (storedVersion !== STORAGE_VERSION) {
                localStorage.removeItem(SESSIONS_KEY);
                safeSetLocalStorage(VERSION_KEY, STORAGE_VERSION);
            }
        } catch (error) {
            console.warn("Failed to migrate local storage version", error);
        }

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

        const apiUrl = resolveDefaultApiBaseUrl();
        fetch(`${apiUrl}/ui-sessions`)
            .then((response) => response.json())
            .then((data) => {
                const loaded = (data.sessions || []).map((session) => upgradeSession(session)).filter(Boolean);
                if (loaded.length > 0) {
                    setSessions(loaded);
                    const latest = loaded.slice().sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt))[0];
                    setCurrentSessionId(latest.id);
                } else {
                    const next = createEmptySession(`session_${Date.now()}`);
                    setSessions([next]);
                    setCurrentSessionId(next.id);
                    fetch(`${apiUrl}/ui-sessions/${next.id}`, {
                        method: "PUT",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(next),
                    }).catch(() => {});
                }
            })
            .catch(() => {
                const next = createEmptySession(`session_${Date.now()}`);
                setSessions([next]);
                setCurrentSessionId(next.id);
            });
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

    // Persist workspace path, selected model and active todo back to the current session whenever they change
    useEffect(() => {
        if (!currentSessionId) return;
        updateSessionById(currentSessionId, (sess) => {
            sess.workspacePath = workspacePath;
        }, { touchUpdatedAt: false });
    }, [workspacePath, currentSessionId]);

    useEffect(() => {
        if (!currentSessionId || !selectedModel) return;
        updateSessionById(currentSessionId, (sess) => {
            sess.selectedModel = selectedModel;
        }, { touchUpdatedAt: false });
    }, [selectedModel, currentSessionId]);

    useEffect(() => {
        if (!currentSessionId) return;
        updateSessionById(currentSessionId, (sess) => {
            sess.activeTodo = activeTodo;
        }, { touchUpdatedAt: false });
    }, [activeTodo, currentSessionId]);

    useEffect(() => {
        safeSetLocalStorage(SETTINGS_KEY, JSON.stringify(settings));
    }, [settings]);

    useEffect(() => {
        if (sessions.length === 0) {
            return;
        }
        if (!currentSessionId || !sessions.some((session) => session.id === currentSessionId)) {
            setCurrentSessionId(sessions[0].id);
        }
    }, [sessions, currentSessionId]);

    const currentSession = sessions.find((session) => session.id === currentSessionId) || null;
    const recallableUserInputs = (currentSession?.transcript || [])
        .filter((entry) => entry?.role === "user" && typeof entry.content === "string" && entry.content.trim())
        .map((entry) => entry.content);

    useEffect(() => {
        if (!currentSession) return; // avoid flash from null-session heuristic on initial mount
        const maxToks = typeof currentSession?.serverContextMaxTokens === "number"
            ? currentSession.serverContextMaxTokens
            : getModelContextWindow(selectedModel);
        const tokens = typeof currentSession?.serverContextTokens === "number"
            ? currentSession.serverContextTokens
            : estimateContextTokensFromTranscript(currentSession);
        // Pass maxToks so percent and token count are derived from the same base
        const pct = computeContextPercent(currentSession, maxToks);
        setContextMaxTokens(maxToks);
        setContextTokens(tokens);
        setContextPercent(pct);
    }, [currentSession, toolContext, selectedModel]);

    useEffect(() => {
        setContextMaxTokens(getModelContextWindow(selectedModel));
        if (currentSessionId) {
            refreshSessionContextState(currentSessionId);
        }
    }, [selectedModel]);

    function resizeComposerTextarea() {
        const el = messageInputRef.current;
        if (!el) return;
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
    }

    useEffect(() => {
        if (!chatMessagesRef.current) return;
        chatMessagesRef.current.scrollTop = chatMessagesRef.current.scrollHeight;
    }, [currentSession?.updatedAt, logsOpen]);

    useEffect(() => {
        if (!requestIndicator?.active || !requestIndicator?.startedAt) {
            return undefined;
        }
        setRequestTimerNow(Date.now());
        const timer = window.setInterval(() => {
            setRequestTimerNow(Date.now());
        }, 1000);
        return () => window.clearInterval(timer);
    }, [requestIndicator?.active, requestIndicator?.startedAt]);

    useEffect(() => {
        setComposerHistoryIndex(null);
        setComposerHistoryDraft("");
    }, [currentSessionId]);

    useEffect(() => {
        refreshRuntime();
        refreshWorkspaceState();
        fetchSkillCatalog();
        refreshArchitectureManifest();
    }, []);

    useEffect(() => {
        let es = null;
        let retryTimer = null;

        function connect() {
            const url = `${settingsRef.current.apiUrl}/skills/events`;
            es = new EventSource(url);
            es.onmessage = (event) => {
                try {
                    const payload = JSON.parse(event.data);
                    if (payload.type === "catalog" && Array.isArray(payload.skills)) {
                        const skills = payload.skills;
                        setSkillCatalog(skills);
                        setSelectedSkills((current) => {
                            const available = new Set(skills.map((s) => s.name));
                            const protectedNames = skills.filter(s => s.protected).map(s => s.name);
                            const preserved = current.filter((n) => available.has(n));
                            const base = preserved.length > 0
                                ? preserved
                                : DEFAULT_SELECTED_SKILLS.filter((n) => available.has(n));
                            // Always include protected skills
                            const merged = [...new Set([...base, ...protectedNames])];
                            return merged;
                        });
                    }
                } catch {
                    // ignore parse errors
                }
            };
            es.onerror = () => {
                es.close();
                retryTimer = setTimeout(connect, 3000);
            };
        }

        connect();
        return () => {
            es?.close();
            if (retryTimer) clearTimeout(retryTimer);
        };
    }, []);

    useEffect(() => {
        if (architectureOpen) {
            refreshArchitectureManifest();
        }
    }, [architectureOpen]);

    useEffect(() => {
        if (currentSessionId) {
            hydrateSessionLocation(currentSessionId);
            refreshSessionContextState(currentSessionId);
            // Restore per-session workspace and todo state
            const sess = sessionsRef.current.find((s) => s.id === currentSessionId);
            if (sess) {
                if (typeof sess.workspacePath === "string") {
                    setWorkspacePath(sess.workspacePath);
                    setWorkspaceDraftPath(sess.workspacePath);
                }
                if (sess.selectedModel) {
                    setSelectedModel(sess.selectedModel);
                }
                setActiveTodo(sess.activeTodo || null);
            }
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

    function updateSessionById(sessionId, transform, { touchUpdatedAt = true } = {}) {
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
            if (touchUpdatedAt) {
                clone.updatedAt = nowIso();
            }
            const apiUrl = settingsRef.current.apiUrl;
            if (apiUrl) {
                const slim = {
                    ...clone,
                    transcript: (clone.transcript || []).map((entry) => {
                        if (!entry.images || !entry.images.length) return entry;
                        return { ...entry, images: entry.images.map(({ dataUrl: _d, ...rest }) => rest) };
                    }),
                    logs: (clone.logs || []).map(({ payload: _p, ...rest }) => rest),
                };
                fetch(`${apiUrl}/ui-sessions/${sessionId}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(slim),
                }).catch(() => {});
            }
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
        const apiUrl = settingsRef.current.apiUrl || resolveDefaultApiBaseUrl();
        fetch(`${apiUrl}/ui-sessions/${session.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(session),
        }).catch(() => {});
        setMode("agent");
        setToolContext("workspace");
        setExpandedThinking({});
        setActiveTodo(null);
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
            session.serverContextTokens = 0;
            session.serverContextMaxTokens = getModelContextWindow(selectedModel);
        });
        setExpandedThinking({});
    }

    function deleteSession(sessionId) {
        setSessions((prev) => {
            const next = prev.filter((s) => s.id !== sessionId);
            if (sessionId === currentSessionId) {
                const replacement = next.length > 0 ? next[0] : createEmptySession(`session_${Date.now()}`);
                setTimeout(() => setCurrentSessionId(replacement.id), 0);
                return next.length > 0 ? next : [replacement];
            }
            return next.length > 0 ? next : [createEmptySession(`session_${Date.now()}`)];
        });
        setExpandedThinking((prev) => {
            const next = { ...prev };
            Object.keys(next).forEach((k) => { if (k.startsWith(sessionId)) delete next[k]; });
            return next;
        });
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
            refreshArchitectureManifest();
        } catch (error) {
            setRuntime(null);
            setRuntimeStatus("Runtime offline");
        }
    }

    async function refreshArchitectureManifest() {
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/architecture`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            setArchitectureManifest(payload || null);
        } catch (error) {
            console.debug("Failed to load architecture manifest", error);
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

    async function reloadSkillCatalog() {
        const response = await fetch(`${settingsRef.current.apiUrl}/skills/reload`, { method: "POST" });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${response.status}`);
        }
        const payload = await response.json();
        const skills = payload.skills || [];
        setSkillCatalog(skills);
        setSelectedSkills((current) => {
            const available = new Set(skills.map((skill) => skill.name));
            const preserved = current.filter((name) => available.has(name));
            if (preserved.length > 0) return preserved;
            return DEFAULT_SELECTED_SKILLS.filter((name) => available.has(name));
        });
    }

    async function installSkill({ name, skill_md, python_code }) {
        const response = await fetch(`${settingsRef.current.apiUrl}/skills/install`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, skill_md, python_code }),
        });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        const skills = payload.skills || [];
        setSkillCatalog(skills);
        setSelectedSkills((current) => {
            const available = new Set(skills.map((skill) => skill.name));
            const preserved = current.filter((n) => available.has(n));
            return preserved.length > 0 ? preserved : DEFAULT_SELECTED_SKILLS.filter((n) => available.has(n));
        });
    }

    async function deleteSkill(name) {
        const response = await fetch(`${settingsRef.current.apiUrl}/skills/${encodeURIComponent(name)}`, {
            method: "DELETE",
        });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        const skills = payload.skills || [];
        setSkillCatalog(skills);
        setSelectedSkills((current) => {
            const available = new Set(skills.map((s) => s.name));
            return current.filter((n) => available.has(n));
        });
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
        setWorkspaceError("");
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/workspace/pick`, {
                method: "POST"
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.success === false) {
                if (payload.cancelled) {
                    return;
                }
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            const selectedPath = payload.workspace?.path || "";
            if (!selectedPath) {
                throw new Error("No folder was returned from the picker");
            }
            await browseWorkspace(selectedPath);
        } catch (error) {
            const message = error?.message || "Failed to open folder picker";
            if (message.includes("Native folder picker is unavailable in the current runtime environment")) {
                setWorkspaceError(explainWorkspacePickerBoundary());
                return;
            }
            setWorkspaceError(message);
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
            const response = await fetch(
                `${settingsRef.current.apiUrl}/session/${encodeURIComponent(sessionId)}/context?model=${encodeURIComponent(selectedModel)}`
            );
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            updateSessionById(sessionId, (session) => {
                session.serverContextPercent = payload.context_percent ?? 0;
                session.serverContextTokens = payload.estimated_context_tokens ?? 0;
                session.serverContextMaxTokens = payload.max_context_tokens ?? getModelContextWindow(selectedModel);
            }, { touchUpdatedAt: false });
            setContextPercent(payload.context_percent ?? 0);
            setContextTokens(payload.estimated_context_tokens ?? 0);
            setContextMaxTokens(payload.max_context_tokens ?? getModelContextWindow(selectedModel));
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
            }, { touchUpdatedAt: false });
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
        const skill = skillCatalog.find(s => s.name === skillName);
        if (skill?.protected) return; // protected skills are always-on, no toggling
        setSelectedSkills((current) => current.includes(skillName)
            ? current.filter((name) => name !== skillName)
            : [...current, skillName]
        );
    }

    function toggleAllSkills() {
        const protectedNames = skillCatalog.filter(s => s.protected).map(s => s.name);
        const toggleableNames = skillCatalog.filter(s => !s.protected).map(s => s.name);
        const allSelected = toggleableNames.length > 0 && toggleableNames.every(n => selectedSkills.includes(n));
        // When toggling all off, keep protected skills selected
        setSelectedSkills(allSelected ? [...protectedNames] : [...skillCatalog.map(s => s.name)]);
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

    function focusComposerWithCursor(position = null) {
        requestAnimationFrame(() => {
            const input = messageInputRef.current;
            if (!input) return;
            const nextPosition = typeof position === "number" ? position : input.value.length;
            input.focus();
            input.setSelectionRange(nextPosition, nextPosition);
        });
    }

    function handleMessageInputChange() {
        resizeComposerTextarea();
        if (composerHistoryIndex !== null) {
            setComposerHistoryIndex(null);
            setComposerHistoryDraft("");
        }
    }

    function setComposerValue(nextValue) {
        if (messageInputRef.current) {
            messageInputRef.current.value = nextValue;
            resizeComposerTextarea();
        }
    }

    function recallComposerHistory(direction) {
        if (!recallableUserInputs.length) {
            return;
        }

        if (direction === "up") {
            if (composerHistoryIndex === null) {
                const nextIndex = recallableUserInputs.length - 1;
                const nextValue = recallableUserInputs[nextIndex];
                setComposerHistoryDraft(messageInputRef.current?.value ?? "");
                setComposerHistoryIndex(nextIndex);
                setComposerValue(nextValue);
                focusComposerWithCursor(nextValue.length);
                return;
            }

            if (composerHistoryIndex <= 0) {
                return;
            }

            const nextIndex = composerHistoryIndex - 1;
            const nextValue = recallableUserInputs[nextIndex];
            setComposerHistoryIndex(nextIndex);
            setComposerValue(nextValue);
            focusComposerWithCursor(nextValue.length);
            return;
        }

        if (composerHistoryIndex === null) {
            return;
        }

        if (composerHistoryIndex >= recallableUserInputs.length - 1) {
            setComposerHistoryIndex(null);
            setComposerValue(composerHistoryDraft);
            focusComposerWithCursor(composerHistoryDraft.length);
            setComposerHistoryDraft("");
            return;
        }

        const nextIndex = composerHistoryIndex + 1;
        const nextValue = recallableUserInputs[nextIndex];
        setComposerHistoryIndex(nextIndex);
        setComposerValue(nextValue);
        focusComposerWithCursor(nextValue.length);
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
        const currentLen = messageInputRef.current?.value?.length ?? 0;
        const start = messageInputRef.current?.selectionStart ?? currentLen;
        const end = messageInputRef.current?.selectionEnd ?? currentLen;

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

        setComposerImages((current) => [...current, ...nextImages]);
        focusComposerWithCursor(start);
    }

    function handleRemoveComposerImage(imageId) {
        setComposerImages((current) => current.filter((image) => image.id !== imageId));
        focusComposerWithCursor();
    }

    async function sendMessage() {
        if (isSending && sendingSessionIdRef.current === currentSessionId) return;
        const rawInput = (messageInputRef.current?.value ?? "").trim();
        const snapshotImages = [...composerImages];
        const content = rawInput;
        if (!rawInput && snapshotImages.length === 0) return;
        if (!currentSessionId) return;

        const messageParts = [
            ...(rawInput ? [{ type: "text", text: rawInput }] : []),
            ...snapshotImages.map((image) => ({ type: "image", id: image.id, name: image.name, data_url: image.dataUrl })),
        ];

        const sessionId = currentSessionId;
        const requestMode = isSimpleChat(content) ? "agent" : mode;
        const { toolContext: selectedToolContext, context } = buildContextPayload("workspace", workspacePath || runtime?.work_dir || "");
        sendingSessionIdRef.current = sessionId;
        setIsSending(true);
        setCompletedLabel(null);
        sendStartTimeRef.current = Date.now();
        setRequestIndicator({
            active: true,
            startedAt: Date.now(),
            label: requestMode === "battle"
                ? "Running battle contenders"
                : (thinkingMode ? "Preparing request" : "Working on your request"),
        });
        setContextPercent(computeContextPercent(currentSession, toolContext));

        appendTranscriptEntry(sessionId, {
            role: "user",
            content,
            kind: "user_text",
            taskId: "main",
            images: compactTranscriptImages(snapshotImages),
        });
        updateSessionById(sessionId, (session) => {
            if (session.transcript.length <= 1) {
                session.title = content.slice(0, 36) || "New thread";
            }
        });
        setComposerValue("");
        setComposerImages([]);
        setComposerHistoryIndex(null);
        setComposerHistoryDraft("");

        let assistantEntry = null;
        let thinkingEntry = null;
        let answerBuffer = "";
        let toolCallsReceived = 0;

        const controller = new AbortController();
        abortControllerRef.current = controller;

        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/chat/stream`, {
                method: "POST",
                signal: controller.signal,
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
                    toolCallsReceived += 1;
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
                        phase: "compression",
                        compressionState: payload.type === "compression_start" ? "running" : "complete",
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
                    const nextTokens = payload.estimated_context_tokens ?? 0;
                    const nextMaxTokens = payload.max_context_tokens ?? getModelContextWindow(selectedModel);
                    updateSessionById(sessionId, (session) => {
                        session.serverContextPercent = nextPercent;
                        session.serverContextTokens = nextTokens;
                        session.serverContextMaxTokens = nextMaxTokens;
                    });
                    setContextPercent(nextPercent);
                    setContextTokens(nextTokens);
                    setContextMaxTokens(nextMaxTokens);
                    return;
                }

                if (payload.type === "phase" || payload.type === "layer_start" || payload.type === "verification" || payload.type === "complete") {
                    if (payload.transient) {
                        setRequestIndicator((current) => current?.active ? {
                            ...current,
                            label: payload.content || "Preparing request",
                        } : current);
                        return;
                    }
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

                if (payload.type === "todo_list") {
                    const items = (payload.items || []).map(text => ({ text, done: false }));
                    setActiveTodo({ items, visible: true });
                    return;
                }

                if (payload.type === "todo_done") {
                    const idx = payload.index;
                    setActiveTodo(prev => {
                        if (!prev) return prev;
                        const items = prev.items.map((it, i) => i === idx ? { ...it, done: true } : it);
                        return { ...prev, items };
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
                    const parts = [];
                    if (payload.error_type) parts.push(`[${payload.error_type}]`);
                    parts.push(payload.error);
                    if (payload.error_detail && payload.error_detail !== payload.error) {
                        parts.push(`\n↳ ${payload.error_detail}`);
                    }
                    const err = new Error(parts.join(" "));
                    err.errorType = payload.error_type || "";
                    err.errorDetail = payload.error_detail || "";
                    throw err;
                }

                if (payload.done) {
                    setRequestIndicator(null);
                    // Keep todo visible after completion — user dismisses manually
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
                        // Build a diagnostic: what events DID arrive before done?
                        const gotTools = toolCallsReceived > 0;
                        const hint = gotTools
                            ? `（已收到 ${toolCallsReceived} 个工具调用，但未返回文字回复）`
                            : "（服务端未发送任何文字内容）";
                        throw new Error(`模型没有返回可显示的正文 ${hint}`);
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
            // Don't clear todo on abort/error — keep visible so user can see what was completed
            if (error.name === "AbortError") {
                if (assistantEntry) {
                    patchTranscriptEntry(sessionId, assistantEntry.id, { streaming: false });
                } else if (answerBuffer.trim()) {
                    appendTranscriptEntry(sessionId, {
                        role: "assistant",
                        content: answerBuffer.trim(),
                        kind: "assistant_text",
                        taskId: "main",
                        streaming: false
                    });
                }
            } else {
                appendTranscriptEntry(sessionId, {
                    role: "assistant",
                    content: `请求失败: ${error.message}`,
                    kind: "assistant_text",
                    isError: true,
                    taskId: "main",
                    streaming: false
                });
            }
        } finally {
            if (sendStartTimeRef.current) {
                const elapsedMs = Date.now() - sendStartTimeRef.current;
                const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
                const hours = Math.floor(totalSeconds / 3600);
                const minutes = Math.floor((totalSeconds % 3600) / 60);
                const seconds = totalSeconds % 60;
                let label;
                if (hours > 0) label = `${hours}h ${minutes}m ${seconds}s`;
                else if (minutes > 0) label = `${minutes}m ${seconds}s`;
                else label = `${seconds}s`;
                setCompletedLabel(label);
                // Persist elapsed time into the assistant entry so historical
                // messages retain their timing after new messages are sent.
                if (assistantEntry?.id) {
                    patchTranscriptEntry(sessionId, assistantEntry.id, { elapsedLabel: label });
                }
                sendStartTimeRef.current = null;
            }
            // Trigger the "just moved to top" animation on the session item
            setJustSentSessionId(sessionId);
            setTimeout(() => setJustSentSessionId(null), 1600);
            // If the user is watching a different session, mark this one as "done"
            if (currentSessionIdRef.current !== sessionId) {
                setSessionBadges((prev) => ({ ...prev, [sessionId]: "done" }));
            } else {
                // User is already looking at it — no badge needed
                setSessionBadges((prev) => {
                    if (!prev[sessionId]) return prev;
                    const next = { ...prev };
                    delete next[sessionId];
                    return next;
                });
            }
            sendingSessionIdRef.current = null;
            setRequestIndicator(null);
            setIsSending(false);
            abortControllerRef.current = null;
        }
    }

    function stopGeneration() {
        abortControllerRef.current?.abort();
    }

    function handleComposerKeyDown(event) {
        const input = messageInputRef.current;
        const selectionStart = input?.selectionStart ?? 0;
        const selectionEnd = input?.selectionEnd ?? 0;

        if (event.key === "ArrowUp" && !event.shiftKey) {
            if (selectionStart === 0 && selectionEnd === 0) {
                event.preventDefault();
                recallComposerHistory("up");
                return;
            }
        }

        if (event.key === "ArrowDown" && !event.shiftKey && composerHistoryIndex !== null) {
            if (selectionStart === selectionEnd && selectionEnd === (messageInputRef.current?.value?.length ?? 0)) {
                event.preventDefault();
                recallComposerHistory("down");
                return;
            }
        }

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
    const nativeWorkspaceLabel = "Pick Folder";
    const nativeWorkspaceHelp = explainWorkspacePickerBoundary();
    const workingTimerLabel = requestIndicator?.active && requestIndicator?.startedAt
        ? formatWorkingDuration(requestTimerNow - requestIndicator.startedAt)
        : "";

    return (
        <div className="app-shell">
            <aside className="sidebar">
                <div className="brand-panel">
                    <div className="brand-lockup">
                        <img className="brand-mark" src={LOGO_SRC} alt="OBS Code logo" />
                        <div className="brand-copy">
                            <span className="brand-name">OBS Code</span>
                            <span className="brand-tagline">Local AI workbench for real tasks</span>
                        </div>
                    </div>
                </div>

                <div className="sidebar-group">
                    <button className="sidebar-action" type="button" onClick={createSession}>
                        <i className="fas fa-plus" />
                        <span>New thread</span>
                    </button>
                </div>

                <div className="history-panel">
                    <div className="session-list">
                        {sessionPreviewList.map((session) => {
                            const preview = session.transcript.at(-1)?.content || "Start a new thread...";
                            return (
                                <button
                                    key={session.id}
                                    type="button"
                                    className={`session-item${session.id === currentSessionId ? " active" : ""}${session.id === justSentSessionId ? " just-sent" : ""}`}
                                    onClick={() => {
                                        setCurrentSessionId(session.id);
                                        if (sessionBadges[session.id]) {
                                            setSessionBadges((prev) => ({ ...prev, [session.id]: "fading" }));
                                            setTimeout(() => setSessionBadges((prev) => {
                                                const next = { ...prev };
                                                delete next[session.id];
                                                return next;
                                            }), 500);
                                        }
                                    }}
                                >
                                    <span className="session-active-indicator" aria-hidden="true" />
                                    <div className="session-name">{session.title}</div>
                                    <div className="session-preview">{preview.slice(0, 90)}</div>
                                    {sessionBadges[session.id] && (
                                        <span
                                            className={`session-activity-badge${sessionBadges[session.id] === "done" ? " done" : ""}${sessionBadges[session.id] === "fading" ? " fading" : ""}`}
                                            aria-label={sessionBadges[session.id] === "done" ? "完成" : "生成中"}
                                        >
                                            {sessionBadges[session.id] === "done" || sessionBadges[session.id] === "fading"
                                                ? <i className="fas fa-check" aria-hidden="true" />
                                                : <span className="session-badge-spinner" aria-hidden="true" />
                                            }
                                        </span>
                                    )}
                                    <button
                                        type="button"
                                        className="session-delete-btn"
                                        title="删除此对话"
                                        onClick={(e) => { e.stopPropagation(); deleteSession(session.id); }}
                                        aria-label="Delete thread"
                                    >
                                        <i className="fas fa-times" aria-hidden="true" />
                                    </button>
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
                <RuntimePills
                    mode={mode}
                    setMode={setMode}
                    contextPercent={contextPercent}
                    contextTokens={contextTokens}
                    contextMaxTokens={contextMaxTokens}
                    githubUrl={GITHUB_REPO_URL}
                    onExport={exportCurrentSession}
                />

                <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                    <TranscriptView
                        transcript={currentSession?.transcript || []}
                        chatMessagesRef={chatMessagesRef}
                        expandedThinking={expandedThinking}
                        onToggleThinking={toggleThinkingEntry}
                        requestIndicator={requestIndicator}
                        workingTimerLabel={workingTimerLabel}
                        completedLabel={completedLabel}
                    />
                </div>

                {activeTodo && (
                    <div className="todo-strip">
                        <div className="todo-strip-header">
                            <i className="fas fa-list-check todo-strip-icon" aria-hidden="true" />
                            <span className="todo-strip-title">任务列表</span>
                            <span className="todo-strip-progress">
                                {activeTodo.items.filter(i => i.done).length} / {activeTodo.items.length}
                            </span>
                            <button
                                type="button"
                                className="todo-strip-close"
                                onClick={() => setActiveTodo(null)}
                                aria-label="关闭任务列表"
                            >
                                <i className="fas fa-times" aria-hidden="true" />
                            </button>
                        </div>
                        <ol className="todo-strip-list">
                            {activeTodo.items.map((item, i) => (
                                <li key={i} className={`todo-strip-item${item.done ? " done" : ""}`}>
                                    <span className="todo-checkbox" aria-hidden="true">
                                        {item.done && <i className="fas fa-check" />}
                                    </span>
                                    <span className="todo-item-text">{item.text}</span>
                                </li>
                            ))}
                        </ol>
                    </div>
                )}

                <Composer
                    selectedModel={selectedModel}
                    availableModels={availableModels}
                    onModelChange={setSelectedModel}
                    permissionMode={permissionMode}
                    onPermissionToggle={cyclePermissionMode}
                    thinkingMode={thinkingMode}
                    onThinkingToggle={() => setThinkingMode((current) => !current)}
                    onChange={handleMessageInputChange}
                    onKeyDown={handleComposerKeyDown}
                    onPaste={handleComposerPaste}
                    onSend={sendMessage}
                    onStop={stopGeneration}
                    isSending={isSending && sendingSessionIdRef.current === currentSessionId}
                    images={composerImages}
                    onRemoveImage={handleRemoveComposerImage}
                    logsOpen={logsOpen}
                    onLogsToggle={() => setLogsOpen((current) => !current)}
                    skillsOpen={skillsOpen}
                    onSkillsToggle={() => setSkillsOpen((current) => !current)}
                    architectureOpen={architectureOpen}
                    onArchitectureToggle={() => setArchitectureOpen((current) => !current)}
                    workspacePath={activeWorkspacePath}
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
                onReload={reloadSkillCatalog}
                onInstall={installSkill}
                onDelete={deleteSkill}
            />
            <ArchitectureDrawer
                open={architectureOpen}
                runtime={runtime}
                architectureManifest={architectureManifest}
                workspacePath={activeWorkspacePath}
                selectedSkills={selectedSkills}
                skillCatalog={skillCatalog}
                mode={mode}
                currentSession={currentSession}
                sessionCount={sessions.length}
                contextPercent={contextPercent}
                permissionMode={permissionMode}
                thinkingMode={thinkingMode}
                toolContext={toolContext}
                selectedModel={selectedModel}
                onClose={() => setArchitectureOpen(false)}
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
                nativePickHelp={nativeWorkspaceHelp}
                onClose={() => setWorkspaceModalOpen(false)}
                onSave={saveWorkspaceSelection}
            />
        </div>
    );
}

export default App;
