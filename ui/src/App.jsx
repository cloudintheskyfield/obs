import React, { useEffect, useRef, useState } from "react";
import Composer from "./components/Composer.jsx";
import ArchitectureDrawer from "./components/ArchitectureDrawer.jsx";
import LogsDrawer from "./components/LogsDrawer.jsx";
import RuntimePills from "./components/RuntimePills.jsx";
import SkillsDrawer from "./components/SkillsDrawer.jsx";
import TranscriptView from "./components/TranscriptView.jsx";
import { formatWorkspaceBreadcrumb, normalizeDisplayText, shortenModel } from "./lib/formatting.js";

const STORAGE_VERSION = "20260415-01";
const SETTINGS_KEY = "obs-agent-settings";
const SESSIONS_KEY = "obs-agent-sessions";
const VERSION_KEY = "obs-agent-storage-version";
const DEFAULT_SELECTED_SKILLS = ["file-manager", "desktop-commander", "computer-use"];
const CREATE_MODE_SKILLS = ["file-manager", "desktop-commander", "computer-use"];
const HARNESS_ALLOWED_LOCAL_SKILLS = new Set([
    "skill-manager",
    "desktop-commander",
    "file-manager",
    "filesystem",
    "agent-skills",
    "skill-management-python-runtime",
    "computer-use",
    "web-e2e",
    "playwright-e2e",
    "web-testing-playwright-e2e",
    "e2e",
    "web-search-free",
    "search",
    "web-scraper-pro",
    "firecrawl-scraper",
    "skill-lookup",
]);
const IMAGE_TOKEN_PATTERN = /\[\[image:([^\]]+)\]\]/g;
const PREVIEW_URL_PATTERN = /((?:https?:\/\/|localhost(?::\d+)?|127(?:\.\d{1,3}){3}(?::\d+)?|0\.0\.0\.0(?::\d+)?)(?:\/[^\s<>"')\]]*)?)/gi;
const GITHUB_REPO_URL = "https://github.com/cloudintheskyfield/obs";
const LOGO_SRC = "/static/obs-code-logo.svg";
const MODEL_CONTEXT_WINDOWS = {
    "MiniMax-M2": 200000,
};
const VALID_PERMISSION_MODES = ["ask", "auto"];
const VALID_THEME_MODES = ["system", "light", "dark"];
const CREATE_GUIDED_TIMEOUT_MS = 5000;
const CREATE_GUIDED_FLOW_ENABLED = false;
const CREATE_GAME_REQUEST_PATTERN = /(game|游戏|僵尸|zombie|迷宫|maze|射击|shoot|fps|生存|boss|关卡|穿越火线|cf)/i;
const CREATE_WEB_REQUEST_PATTERN = /(网页|web|网站|前端|html|css|react|vue|vite|dashboard|landing\s*page)/i;
const CREATE_API_REQUEST_PATTERN = /(接口|api|后端|backend|server|服务|fastapi|flask|django|express|node)/i;
const CREATE_SCRIPT_REQUEST_PATTERN = /(脚本|script|cli|工具|tool|自动化|automation|爬虫|crawler|parser|转换|converter|generator)/i;

function resolveDefaultApiBaseUrl() {
    const { protocol, origin, hostname } = window.location;
    if ((hostname === "localhost" || hostname === "127.0.0.1") && window.location.port === "5173") {
        return `${protocol}//${hostname}:8213`;
    }
    if ((protocol === "http:" || protocol === "https:") && hostname) {
        return origin;
    }
    return "http://127.0.0.1:8213";
}

function nowIso() {
    return new Date().toISOString();
}

function normalizePermissionMode(value) {
    return VALID_PERMISSION_MODES.includes(value) ? value : "ask";
}

function normalizeThemeMode(value) {
    return VALID_THEME_MODES.includes(value) ? value : "system";
}

function getSystemTheme() {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
        return "dark";
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolveEffectiveTheme(themeMode, systemTheme) {
    const normalizedMode = normalizeThemeMode(themeMode);
    return normalizedMode === "system" ? systemTheme : normalizedMode;
}

function applyDocumentTheme(themeMode, systemTheme) {
    if (typeof document === "undefined") {
        return;
    }
    const normalizedMode = normalizeThemeMode(themeMode);
    const effectiveTheme = resolveEffectiveTheme(normalizedMode, systemTheme);
    document.documentElement.dataset.themeMode = normalizedMode;
    document.documentElement.dataset.theme = effectiveTheme;
    document.documentElement.style.colorScheme = effectiveTheme;
}

function filterHarnessSkills(skills) {
    return (Array.isArray(skills) ? skills : []).filter((skill) => {
        if (!skill?.name) {
            return false;
        }
        return skill.protected || HARNESS_ALLOWED_LOCAL_SKILLS.has(skill.name);
    });
}

function normalizeTodo(todo) {
    if (!todo || !Array.isArray(todo.items)) {
        return null;
    }
    const items = todo.items
        .map((item) => {
            if (typeof item === "string") {
                return { text: item.trim(), done: false };
            }
            const text = String(item?.text || "").trim();
            if (!text) {
                return null;
            }
            return {
                text,
                done: Boolean(item?.done),
            };
        })
        .filter(Boolean);
    if (!items.length) {
        return null;
    }
    return {
        items,
        completed: Boolean(todo.completed) || items.every((item) => item.done),
    };
}

const HARNESS_ROLES = ["Planner", "Search", "Generator", "Runner", "Evaluator"];

function normalizeHarnessRole(role) {
    return HARNESS_ROLES.includes(role) ? role : "Generator";
}

function normalizeUserEvent(event) {
    if (!event || typeof event !== "object") {
        return null;
    }
    return {
        type: String(event.type || "").trim(),
        severity: String(event.severity || "info").trim(),
        title: String(event.title || "").trim(),
        summary: String(event.summary || "").trim(),
        details: String(event.details || "").trim(),
        recommendedAction: String(event.recommended_action || event.recommendedAction || "").trim(),
        debugRef: String(event.debug_ref || event.debugRef || "").trim(),
        hiddenByDefault: Boolean(event.hiddenByDefault),
    };
}

function normalizeDisplaySummary(summary) {
    if (!summary || typeof summary !== "object") {
        return null;
    }
    return {
        title: String(summary.title || "").trim(),
        status: String(summary.status || "info").trim(),
        summary: String(summary.summary || "").trim(),
        highlights: Array.isArray(summary.highlights)
            ? summary.highlights.map((item) => String(item || "").trim()).filter(Boolean)
            : [],
        nextStep: String(summary.next_step || summary.nextStep || "").trim(),
        userVisible: summary.user_visible !== false,
    };
}

function normalizeHarnessDecision(decision) {
    if (!decision || typeof decision !== "object") {
        return null;
    }
    return {
        decision: String(decision.decision || "").trim(),
        reason: String(decision.reason || "").trim(),
        nextState: String(decision.next_state || "").trim(),
        nextAgent: String(decision.next_agent || "").trim(),
        roundId: Number(decision.round_id) || 0,
        budgetRemaining: decision.budget_remaining && typeof decision.budget_remaining === "object"
            ? { ...decision.budget_remaining }
            : {},
    };
}

function userFacingStep(step) {
    const userEvent = normalizeUserEvent(step?.user_event || step?.userEvent);
    if (userEvent?.title) {
        return {
            role: normalizeHarnessRole(step?.role),
            status: step?.status || (userEvent.severity === "warning" ? "error" : "running"),
            title: userEvent.title,
            detail: userEvent.summary || userEvent.details || "",
            evidence: userEvent.details || userEvent.debugRef || "",
            recommendedAction: userEvent.recommendedAction || "",
        };
    }

    const displaySummary = normalizeDisplaySummary(step?.display_summary || step?.displaySummary);
    if (displaySummary?.title) {
        return {
            role: normalizeHarnessRole(step?.role),
            status: step?.status || displaySummary.status || "success",
            title: displaySummary.title,
            detail: displaySummary.summary || "",
            evidence: displaySummary.highlights.join(" · "),
            recommendedAction: displaySummary.nextStep || "",
        };
    }

    const role = normalizeHarnessRole(step?.role);
    const rawTitle = String(step?.title || "");
    const rawDetail = String(step?.detail || "");
    const rawEvidence = String(step?.evidence || "");
    const combined = `${rawTitle}\n${rawDetail}\n${rawEvidence}`;

    if (/Locator can't be used in 'await'|object Locator/i.test(combined)) {
        return {
            role,
            status: "error",
            title: "自动化验证脚本出错",
            detail: "页面验证脚本的点击写法有问题，这通常不是业务代码错误。",
            evidence: "Playwright locator() 不应直接 await；技术细节已放入日志。",
        };
    }

    if (/max iterations reached without verdict/i.test(combined)) {
        return {
            role: "Evaluator",
            status: "error",
            title: "验收未完成",
            detail: "自动化验收没有在预算内得到有效结论，需要带证据重新验证。",
            evidence: rawEvidence,
        };
    }

    if (/^执行\s+bash/i.test(rawTitle)) {
        return {
            role: "Runner",
            status: step.status || "running",
            title: "运行命令",
            detail: rawDetail,
            evidence: rawEvidence,
        };
    }

    if (/bash\s+完成/i.test(rawTitle)) {
        return {
            role: "Runner",
            status: step.status || "success",
            title: "命令执行完成",
            detail: rawDetail,
            evidence: rawEvidence,
        };
    }

    if (/bash\s+失败/i.test(rawTitle)) {
        return {
            role: "Runner",
            status: "error",
            title: "命令执行失败",
            detail: rawDetail,
            evidence: rawEvidence,
        };
    }

    if (/执行\s+str_replace_editor/i.test(rawTitle)) {
        return {
            role: "Generator",
            status: step.status || "running",
            title: "修改文件",
            detail: rawDetail,
            evidence: rawEvidence,
        };
    }

    if (/str_replace_editor\s+完成/i.test(rawTitle)) {
        return {
            role: "Generator",
            status: step.status || "success",
            title: "文件修改完成",
            detail: rawDetail,
            evidence: rawEvidence,
        };
    }

    if (/执行\s+(web_search|advanced_web_search)/i.test(rawTitle)) {
        return {
            role: "Search",
            status: step.status || "running",
            title: "检索外部资料",
            detail: rawDetail,
            evidence: rawEvidence,
        };
    }

    if (/执行\s+(computer|code_sandbox)/i.test(rawTitle)) {
        return {
            role: "Runner",
            status: step.status || "running",
            title: "验证页面行为",
            detail: rawDetail,
            evidence: rawEvidence,
        };
    }

    return {
        role,
        status: step?.status || "running",
        title: rawTitle || "处理中",
        detail: rawDetail,
        evidence: rawEvidence,
        recommendedAction: "",
    };
}

function normalizeAgentProcess(process) {
    const source = process && typeof process === "object" ? process : {};
    const roleState = {};
    HARNESS_ROLES.forEach((role) => {
        const current = source.roles?.[role] || {};
        roleState[role] = {
            status: current.status || "pending",
            title: current.title || "",
            detail: current.detail || "",
            evidence: current.evidence || "",
            updatedAt: current.updatedAt || null,
        };
    });
    const events = Array.isArray(source.events)
        ? source.events
            .filter((event) => event && typeof event === "object")
            .slice(-24)
            .map((event) => {
                const friendly = userFacingStep(event);
                return {
                    role: friendly.role,
                    status: friendly.status || "running",
                    title: String(friendly.title || "").slice(0, 120),
                    detail: String(friendly.detail || "").slice(0, 260),
                    evidence: String(friendly.evidence || "").slice(0, 320),
                    timestamp: event.timestamp || nowIso(),
                };
            })
        : [];
    const latestErrorEvent = [...events].reverse().find((event) => event.status === "error") || null;
    return {
        roles: roleState,
        events,
        statusLine: String(source.statusLine || ""),
        currentIssue: latestErrorEvent
            ? {
                title: latestErrorEvent.title || "",
                detail: latestErrorEvent.detail || "",
                evidence: latestErrorEvent.evidence || "",
            }
            : source.currentIssue && typeof source.currentIssue === "object"
            ? {
                title: String(source.currentIssue.title || ""),
                detail: String(source.currentIssue.detail || ""),
                evidence: String(source.currentIssue.evidence || ""),
            }
            : null,
        nextAction: String(source.nextAction || ""),
        latestSummary: source.latestSummary && typeof source.latestSummary === "object"
            ? normalizeDisplaySummary(source.latestSummary)
            : null,
        decision: source.decision && typeof source.decision === "object"
            ? normalizeHarnessDecision(source.decision)
            : null,
        roundId: Number(source.roundId || 0),
    };
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
        selectedModel: "",   // "" means "use the global default"
        createdAt: nowIso(),
        updatedAt: nowIso()
    };
}

function normalizeEntry(entry) {
    const kind = entry.kind || "assistant_text";
    const normalizedContent = (
        kind === "assistant_text"
        || kind === "thinking_text"
        || kind === "system_notice"
        || kind === "tool_result"
    )
        ? normalizeDisplayText(entry.content || "")
        : (entry.content || "");
    return {
        id: entry.id || `entry_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
        role: entry.role || "assistant",
        content: normalizedContent,
        kind,
        taskId: entry.taskId || "main",
        toolName: entry.toolName || null,
        phase: entry.phase || null,
        compressionState: entry.compressionState || null,
        success: entry.success,
        isError: Boolean(entry.isError),
        pendingPlaceholder: Boolean(entry.pendingPlaceholder),
        elapsedLabel: typeof entry.elapsedLabel === "string" ? entry.elapsedLabel : null,
        todo: normalizeTodo(entry.todo),
        agentProcess: entry.agentProcess ? normalizeAgentProcess(entry.agentProcess) : null,
        userEvent: normalizeUserEvent(entry.userEvent || entry.user_event),
        displaySummary: normalizeDisplaySummary(entry.displaySummary || entry.display_summary),
        harnessDecision: normalizeHarnessDecision(entry.harnessDecision || entry.harness_decision),
        guidedChoice: entry.guidedChoice && typeof entry.guidedChoice === "object" ? entry.guidedChoice : null,
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

function buildCreateGuidedQuestions(content) {
    const text = String(content || "").trim();
    if (!text) {
        return [];
    }
    const questions = [];
    const hasWebPlatform = /(web|网页|浏览器|html|canvas|webgl|three\.?js|phaser|react|vite)/i.test(text);
    const hasDesktopPlatform = /(桌面|desktop|electron|pc客户端)/i.test(text);
    const hasMobilePlatform = /(移动端|mobile|ios|android|手机)/i.test(text);
    const hasSingleMode = /(单人|single\s*-?player|solo|pve)/i.test(text);
    const hasMultiMode = /(多人|联机|在线|online|coop|co-op|局域网|pvp)/i.test(text);
    const hasGameStack = /(three\.?js|phaser|canvas|webgl|babylon|unity)/i.test(text);
    const hasFrontendStack = /(react|vue|svelte|next\.?js|nuxt|html|vite)/i.test(text);
    const hasBackendStack = /(fastapi|flask|django|express|nest|spring|laravel)/i.test(text);
    const hasScriptRuntime = /(python|node|bun|deno|bash|shell)/i.test(text);
    const prefers3d = /(3d|fps|第一人称|third\s*-?person|穿越火线|cf|zombie|僵尸|three\.?js|webgl)/i.test(text);

    if (CREATE_GAME_REQUEST_PATTERN.test(text)) {
        if (!hasWebPlatform && !hasDesktopPlatform && !hasMobilePlatform) {
            questions.push({
                key: "platform",
                title: "你希望这个游戏运行在哪个平台？",
                description: "5 秒内不选择会自动采用默认方案。",
                options: [
                    { value: "Web 浏览器", label: "Web 浏览器", hint: "HTML5 / WebGL，最容易直接预览", isDefault: true },
                    { value: "桌面端 Electron", label: "桌面端", hint: "适合封装成本地客户端" },
                    { value: "移动端 H5", label: "移动端", hint: "优先触屏与竖屏适配" },
                ],
                defaultValue: "Web 浏览器",
            });
        }
        if (!hasSingleMode && !hasMultiMode) {
            questions.push({
                key: "mode",
                title: "你希望优先实现哪种玩法模式？",
                description: "默认先做最容易跑通的主流方案。",
                options: [
                    { value: "单人模式", label: "单人模式", hint: "先做 AI 敌人与可玩主循环", isDefault: true },
                    { value: "多人在线模式", label: "多人在线", hint: "需要房间、同步和服务器支持" },
                    { value: "单人 + 多人", label: "两种都要", hint: "范围更大，开发时间更长" },
                ],
                defaultValue: "单人模式",
            });
        }
        if (!hasGameStack) {
            questions.push({
                key: "stack",
                title: "你希望优先使用什么技术栈？",
                description: "默认会选最贴近当前任务体验的方案。",
                options: prefers3d
                    ? [
                        { value: "Three.js（3D）", label: "Three.js（3D）", hint: "适合 FPS / 3D 场景", isDefault: true },
                        { value: "Phaser.js（2.5D / 2D）", label: "Phaser.js", hint: "开发效率更高" },
                        { value: "纯 JavaScript + Canvas", label: "纯 JS + Canvas", hint: "零依赖，适合轻量原型" },
                    ]
                    : [
                        { value: "Phaser.js（2.5D / 2D）", label: "Phaser.js", hint: "适合快速做可玩原型", isDefault: true },
                        { value: "Three.js（3D）", label: "Three.js（3D）", hint: "更强的 3D 表现" },
                        { value: "纯 JavaScript + Canvas", label: "纯 JS + Canvas", hint: "实现更轻量" },
                    ],
                defaultValue: prefers3d ? "Three.js（3D）" : "Phaser.js（2.5D / 2D）",
            });
        }
    } else if (CREATE_WEB_REQUEST_PATTERN.test(text) && !hasFrontendStack) {
        questions.push({
            key: "frontend_stack",
            title: "你希望这个页面优先用什么前端方案？",
            description: "默认采用当前项目里最顺手的主流方案。",
            options: [
                { value: "React + Vite", label: "React + Vite", hint: "当前项目前端就是这个栈", isDefault: true },
                { value: "纯 HTML + CSS + JavaScript", label: "纯 HTML", hint: "更轻量，适合单页原型" },
                { value: "Vue + Vite", label: "Vue + Vite", hint: "适合组件化页面" },
            ],
            defaultValue: "React + Vite",
        });
    } else if (CREATE_API_REQUEST_PATTERN.test(text) && !hasBackendStack) {
        questions.push({
            key: "backend_stack",
            title: "你希望这个后端优先用什么框架？",
            description: "默认采用最主流、也最适合当前仓库的方案。",
            options: [
                { value: "FastAPI", label: "FastAPI", hint: "Python API 开发很高效", isDefault: true },
                { value: "Flask", label: "Flask", hint: "更轻量的 Python 后端" },
                { value: "Express", label: "Express", hint: "Node.js 生态更常见" },
            ],
            defaultValue: "FastAPI",
        });
    } else if (CREATE_SCRIPT_REQUEST_PATTERN.test(text) && !hasScriptRuntime) {
        questions.push({
            key: "script_runtime",
            title: "你希望这个工具优先用什么运行时？",
            description: "默认会选最通用、最容易维护的方案。",
            options: [
                { value: "Python", label: "Python", hint: "适合自动化、解析和脚本工具", isDefault: true },
                { value: "Node.js", label: "Node.js", hint: "适合 CLI 和工程脚本" },
                { value: "Bash", label: "Bash", hint: "适合简单串联命令" },
            ],
            defaultValue: "Python",
        });
    }

    return questions.slice(0, 3);
}

function buildCreateGuidedRequest(baseContent, answers) {
    const normalized = String(baseContent || "").trim();
    const lines = Object.values(answers || {}).map((item) => {
        if (!item?.label) {
            return null;
        }
        const suffix = item.autoSelected ? "（默认主流方案）" : "";
        return `- ${item.title}：${item.label}${suffix}`;
    }).filter(Boolean);
    if (!lines.length) {
        return normalized;
    }
    return `${normalized}\n\n补充实现约束（来自 Create 引导问题，请按这些选择继续实现）：\n${lines.join("\n")}`;
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

function normalizePreviewUrl(rawUrl) {
    const trimmed = String(rawUrl || "").trim().replace(/[),.;]+$/, "");
    if (!trimmed) {
        return "";
    }
    const hasProtocol = /^https?:\/\//i.test(trimmed);
    const candidate = hasProtocol ? trimmed : `http://${trimmed}`;
    try {
        const parsed = new URL(candidate);
        if (["localhost", "127.0.0.1", "0.0.0.0"].includes(parsed.hostname)) {
            parsed.hostname = window.location.hostname || parsed.hostname;
        }
        return parsed.toString();
    } catch {
        return "";
    }
}

function detectPreviewUrls(session) {
    const transcript = Array.isArray(session?.transcript) ? session.transcript : [];
    const seen = new Set();
    const urls = [];
    for (let index = transcript.length - 1; index >= 0; index -= 1) {
        const entry = transcript[index];
        const text = String(entry?.content || "");
        let match;
        PREVIEW_URL_PATTERN.lastIndex = 0;
        while ((match = PREVIEW_URL_PATTERN.exec(text)) !== null) {
            const normalized = normalizePreviewUrl(match[1]);
            if (normalized && !seen.has(normalized)) {
                seen.add(normalized);
                urls.push(normalized);
            }
        }
    }
    return urls;
}

function scoreWorkspaceHtmlFile(f) {
    const p = String(f.path || "").toLowerCase();
    const ins = Number(f.insertions) || 0;
    const mtime = Number(f.mtime) || 0;
    if (p.endsWith("index.html")) {
        return 1_000_000 + ins + mtime / 1_000_000;
    }
    if (p.includes("jump") || p.includes("game") || p.includes("play")) {
        return 500_000 + ins + mtime / 1_000_000;
    }
    return ins + mtime / 1_000_000;
}

/** All workspace .html/.htm entries as /preview/local-file URLs, best-first (for multi-artifact picker). */
function buildWorkspaceHtmlPreviewEntries(workspaceChanges, apiBase) {
    if (!workspaceChanges || !apiBase) {
        return [];
    }
    const candidates = [
        ...(Array.isArray(workspaceChanges.previewFiles) ? workspaceChanges.previewFiles : []),
        ...(Array.isArray(workspaceChanges.files) ? workspaceChanges.files : []),
    ];
    const seenPaths = new Set();
    const htmlFiles = candidates.filter((f) => {
        const path = String(f.path || "");
        const hostPath = String(f.absolute_path || "");
        const key = hostPath || path;
        if (!/\.html?$/i.test(path) || !hostPath || seenPaths.has(key)) {
            return false;
        }
        seenPaths.add(key);
        return true;
    });
    if (!htmlFiles.length) {
        return [];
    }
    const sorted = [...htmlFiles].sort((a, b) => scoreWorkspaceHtmlFile(b) - scoreWorkspaceHtmlFile(a));
    const base = String(apiBase || "").replace(/\/$/, "");
    return sorted
        .map((f) => {
            const hostPath = String(f.absolute_path || "").trim();
            if (!hostPath) {
                return null;
            }
            return {
                path: String(f.path || ""),
                url: `${base}/preview/local-file?path=${encodeURIComponent(hostPath)}`,
            };
        })
        .filter(Boolean);
}

function shortPreviewLabel(url) {
    const u = String(url || "");
    if (!u) {
        return "";
    }
    if (u.includes("/preview/local-file")) {
        try {
            const q = new URL(u, "http://_").searchParams.get("path") || "";
            const base = q.split(/[/\\]/).filter(Boolean).pop() || q;
            return base || "local HTML";
        } catch {
            return "local HTML";
        }
    }
    return u.replace(/^https?:\/\//i, "").replace(/\/$/, "").slice(0, 56) || u;
}

function buildPreviewArtifactOptions(detectedUrls, workspaceChanges, apiBase) {
    const out = [];
    const seen = new Set();
    const push = (label, url) => {
        if (!url || seen.has(url)) {
            return;
        }
        seen.add(url);
        out.push({ label: label || shortPreviewLabel(url), url });
    };
    (detectedUrls || []).forEach((u) => push(shortPreviewLabel(u), u));
    buildWorkspaceHtmlPreviewEntries(workspaceChanges, apiBase).forEach((e) => push(e.path, e.url));
    return out;
}

function firstUserPrompt(session) {
    const transcript = Array.isArray(session?.transcript) ? session.transcript : [];
    const entry = transcript.find((item) => item?.role === "user" && typeof item.content === "string" && item.content.trim());
    return entry?.content?.trim() || "";
}

function latestAssistantSummary(session) {
    const transcript = Array.isArray(session?.transcript) ? [...session.transcript] : [];
    const entry = transcript.reverse().find((item) => item?.role === "assistant" && item?.kind === "assistant_text" && typeof item.content === "string" && item.content.trim());
    if (!entry?.content) {
        return "";
    }
    return entry.content.replace(/\s+/g, " ").slice(0, 180).trim();
}

function inferProjectTags(session, previewUrl) {
    const source = `${session?.title || ""} ${firstUserPrompt(session)} ${previewUrl || ""}`.toLowerCase();
    const tags = [];
    if (/(game|游戏|zombie|僵尸|fps|maze|迷宫)/i.test(source)) tags.push("游戏");
    if (/(react|vue|html|网页|web|dashboard|landing)/i.test(source)) tags.push("网页");
    if (/(tool|工具|script|脚本|automation|自动化)/i.test(source)) tags.push("工具");
    if (!tags.length) tags.push("创意原型");
    return tags.slice(0, 3);
}

function buildRemixPrompt(project) {
    const lines = [
        `二次创作这个已发布作品：${project.title}`,
        project.prompt ? `原始需求：${project.prompt}` : null,
        project.description ? `当前作品说明：${project.description}` : null,
        project.preview_url ? `参考预览：${project.preview_url}` : null,
        "请保留核心玩法，但做出明显的创意改造，并优先生成一个稳定、可运行、可继续发布的新版本。",
    ].filter(Boolean);
    return lines.join("\n");
}

function App() {
    const [settings, setSettings] = useState({
        apiUrl: resolveDefaultApiBaseUrl(),
        autoSave: true,
        theme: "system",
        permissionMode: "ask",
        thinkingMode: true,
        toolContext: "workspace"
    });
    const [themeMode, setThemeMode] = useState("system");
    const [systemTheme, setSystemTheme] = useState(() => getSystemTheme());
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
    const [guidedCreateFlow, setGuidedCreateFlow] = useState(null);
    const [guidedChoiceNow, setGuidedChoiceNow] = useState(() => Date.now());
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
    const [previewOpen, setPreviewOpen] = useState(false);
    const [previewUrl, setPreviewUrl] = useState("");
    const [previewNonce, setPreviewNonce] = useState(0);
    const [publishToast, setPublishToast] = useState("");
    const [publishedProjects, setPublishedProjects] = useState([]);
    const [leaderboardProjects, setLeaderboardProjects] = useState([]);
    const [discoverTab, setDiscoverTab] = useState("discover");
    const [createHubOpen, setCreateHubOpen] = useState(false);
    const [publishingProject, setPublishingProject] = useState(false);
    const [workspaceChanges, setWorkspaceChanges] = useState({
        isGit: false,
        changedFiles: 0,
        insertions: 0,
        deletions: 0,
        files: [],
        previewFiles: [],
    });

    const messageInputRef = useRef(null);
    const chatMessagesRef = useRef(null);
    const shouldStickToBottomRef = useRef(true);
    const previewDismissedKeyRef = useRef("");
    const sessionsRef = useRef([]);
    const currentSessionIdRef = useRef(null);
    const settingsRef = useRef(settings);
    const initialLoadDoneRef = useRef(false);
    const abortControllerRef = useRef(null);

    const effectiveTheme = resolveEffectiveTheme(themeMode, systemTheme);

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
        if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
            return undefined;
        }
        const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
        const handleChange = (event) => {
            setSystemTheme(event.matches ? "dark" : "light");
        };
        setSystemTheme(mediaQuery.matches ? "dark" : "light");
        if (typeof mediaQuery.addEventListener === "function") {
            mediaQuery.addEventListener("change", handleChange);
            return () => mediaQuery.removeEventListener("change", handleChange);
        }
        mediaQuery.addListener(handleChange);
        return () => mediaQuery.removeListener(handleChange);
    }, []);

    useEffect(() => {
        applyDocumentTheme(themeMode, systemTheme);
    }, [themeMode, systemTheme]);

    // Keep the sidebar activity badge in sync for the currently generating thread,
    // whether or not the user is looking at that thread right now.
    useEffect(() => {
        const genId = sendingSessionIdRef.current;
        if (isSending && genId) {
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
                const { workspacePath: _legacyWorkspacePath, ...storedSettings } = stored;
                setSettings((current) => ({ ...current, ...storedSettings }));
                if (typeof stored.thinkingMode === "boolean") {
                    setThinkingMode(stored.thinkingMode);
                }
                if (stored.permissionMode) {
                    setPermissionMode(normalizePermissionMode(stored.permissionMode));
                }
                if (stored.theme) {
                    setThemeMode(normalizeThemeMode(stored.theme));
                }
                if (stored.toolContext) {
                    setToolContext(stored.toolContext);
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
            theme: themeMode,
            permissionMode,
            thinkingMode,
            toolContext,
            selectedSkills,
            selectedModel
        }));
    }, [themeMode, permissionMode, thinkingMode, toolContext, selectedSkills, selectedModel]);

    useEffect(() => {
        if (!currentSessionId || !selectedModel) return;
        updateSessionById(currentSessionId, (sess) => {
            sess.selectedModel = selectedModel;
        }, { touchUpdatedAt: false });
    }, [selectedModel, currentSessionId]);

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
    const activeWorkspacePath = workspacePath || "";
    const detectedPreviewUrls = detectPreviewUrls(currentSession);
    const previewArtifactOptions = buildPreviewArtifactOptions(
        detectedPreviewUrls,
        workspaceChanges,
        settings.apiUrl,
    );
    const previewAutoOpenKey = `${currentSessionId || ""}:${previewArtifactOptions.map((option) => option.url).join("|")}`;
    const activePreviewUrl = previewUrl || previewArtifactOptions[0]?.url || "";
    const previewHeadline = activePreviewUrl
        ? (activePreviewUrl.includes("/preview/local-file")
            ? `Workspace HTML · ${shortPreviewLabel(activePreviewUrl)}`
            : `URL · ${shortPreviewLabel(activePreviewUrl)}`)
        : "Preview waiting for a runnable URL";
    const recallableUserInputs = (currentSession?.transcript || [])
        .filter((entry) => entry?.role === "user" && typeof entry.content === "string" && entry.content.trim())
        .map((entry) => entry.content);
    const threadContextMaxTokens = typeof currentSession?.serverContextMaxTokens === "number"
        ? currentSession.serverContextMaxTokens
        : getModelContextWindow(selectedModel);
    const threadContextTokens = estimateContextTokensFromTranscript(currentSession);
    const threadContextPercent = threadContextMaxTokens > 0
        ? Math.min(98, (threadContextTokens / threadContextMaxTokens) * 100)
        : 0;
    const threadTurnCount = (currentSession?.transcript || []).filter((entry) => entry?.role === "user").length;
    const discoverProjects = discoverTab === "leaderboard" ? leaderboardProjects : publishedProjects;
    const fileChangeSummary = {
        visible: workspaceChanges.isGit && workspaceChanges.changedFiles > 0,
        changedFiles: workspaceChanges.changedFiles || 0,
        insertions: workspaceChanges.insertions || 0,
        deletions: workspaceChanges.deletions || 0,
        files: Array.isArray(workspaceChanges.files) ? workspaceChanges.files : [],
    };

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
        const el = chatMessagesRef.current;
        if (!el) return undefined;
        const updateStickiness = () => {
            const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
            shouldStickToBottomRef.current = distanceFromBottom < 140;
        };
        updateStickiness();
        el.addEventListener("scroll", updateStickiness, { passive: true });
        return () => el.removeEventListener("scroll", updateStickiness);
    }, [currentSessionId]);

    useEffect(() => {
        const el = chatMessagesRef.current;
        if (!el || !shouldStickToBottomRef.current) return;
        requestAnimationFrame(() => {
            if (shouldStickToBottomRef.current) {
                el.scrollTop = el.scrollHeight;
            }
        });
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
        if (!guidedCreateFlow?.entryId || !guidedCreateFlow?.deadlineAt) {
            return undefined;
        }
        setGuidedChoiceNow(Date.now());
        const ticker = window.setInterval(() => {
            setGuidedChoiceNow(Date.now());
        }, 200);
        const timeout = window.setTimeout(() => {
            resolveGuidedCreateChoice(guidedCreateFlow.entryId, guidedCreateFlow.questions?.[guidedCreateFlow.currentIndex]?.defaultValue, true);
        }, Math.max(0, guidedCreateFlow.deadlineAt - Date.now()));
        return () => {
            window.clearInterval(ticker);
            window.clearTimeout(timeout);
        };
    }, [guidedCreateFlow?.entryId, guidedCreateFlow?.deadlineAt, guidedCreateFlow?.currentIndex]);

    useEffect(() => {
        setComposerHistoryIndex(null);
        setComposerHistoryDraft("");
    }, [currentSessionId]);

    useEffect(() => {
        refreshRuntime();
        fetchSkillCatalog();
        refreshArchitectureManifest();
        refreshPublishedProjects();
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
            setWorkspacePath("");
            setWorkspaceDraftPath("");
            refreshWorkspaceState(currentSessionId);
            const sess = sessionsRef.current.find((s) => s.id === currentSessionId);
            if (sess) {
                if (sess.selectedModel) {
                    setSelectedModel(sess.selectedModel);
                }
            }
        }
    }, [currentSessionId]);

    useEffect(() => {
        const options = buildPreviewArtifactOptions(
            detectedPreviewUrls,
            workspaceChanges,
            settingsRef.current.apiUrl,
        );
        setPreviewUrl((prev) => {
            if (prev && options.some((o) => o.url === prev)) {
                return prev;
            }
            return options[0]?.url || "";
        });
    }, [currentSessionId, detectedPreviewUrls, workspaceChanges]);

    // 自动打开 Preview 面板当检测到 URL 或工作区 HTML 时
    useEffect(() => {
        if (
            previewArtifactOptions.length > 0
            && !previewOpen
            && previewDismissedKeyRef.current !== previewAutoOpenKey
        ) {
            setPreviewOpen(true);
        }
    }, [previewArtifactOptions, previewAutoOpenKey, previewOpen]);

    useEffect(() => {
        if (!activeWorkspacePath) {
            setWorkspaceChanges({
                isGit: false,
                changedFiles: 0,
                insertions: 0,
                deletions: 0,
                files: [],
                previewFiles: [],
            });
            return;
        }

        let cancelled = false;
        const refreshChanges = async () => {
            try {
                const params = new URLSearchParams({ path: activeWorkspacePath });
                const response = await fetch(`${settingsRef.current.apiUrl}/workspace/changes?${params.toString()}`);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const payload = await response.json();
                if (cancelled) return;
                setWorkspaceChanges({
                    isGit: Boolean(payload.is_git),
                    changedFiles: payload.changed_files || 0,
                    insertions: payload.insertions || 0,
                    deletions: payload.deletions || 0,
                    files: payload.files || [],
                    previewFiles: payload.preview_files || [],
                });
            } catch (error) {
                if (!cancelled) {
                    console.debug("Failed to load workspace changes", error);
                }
            }
        };

        refreshChanges();
        return () => {
            cancelled = true;
        };
    }, [activeWorkspacePath, currentSession?.updatedAt, isSending]);

    useEffect(() => {
        if (!currentSessionId || requestIndicator?.active || isSending || !currentSession?.transcript?.length) {
            return;
        }
        const staleStreamingIds = currentSession.transcript
            .filter((entry) => entry?.streaming)
            .map((entry) => entry.id);
        if (!staleStreamingIds.length) {
            return;
        }
        updateSessionById(currentSessionId, (session) => {
            session.transcript.forEach((entry) => {
                if (!entry?.streaming) {
                    return;
                }
                entry.streaming = false;
                if (entry.kind === "thinking_text") {
                    entry.pendingPlaceholder = false;
                }
            });
        }, { touchUpdatedAt: false });
    }, [currentSessionId, currentSession, requestIndicator?.active, isSending]);

    useEffect(() => {
        const flushCurrentSession = () => {
            const sessionId = currentSessionIdRef.current;
            const session = sessionsRef.current.find((item) => item.id === sessionId);
            if (!sessionId || !session) {
                return;
            }
            persistUiSessionSnapshot(sessionId, upgradeSession(session), { keepalive: true });
        };

        window.addEventListener("beforeunload", flushCurrentSession);
        window.addEventListener("pagehide", flushCurrentSession);
        return () => {
            window.removeEventListener("beforeunload", flushCurrentSession);
            window.removeEventListener("pagehide", flushCurrentSession);
        };
    }, []);

    useEffect(() => {
        if (logsOpen) {
            refreshLogsFromBackend();
        }
    }, [logsOpen, logRange, logsFrom, logsTo, currentSessionId]);

    function updateSessions(updater) {
        setSessions((previous) => updater(previous.map((session) => upgradeSession(session))));
    }

    function buildSlimSessionSnapshot(session) {
        return {
            ...session,
            transcript: (session.transcript || []).map((entry) => {
                if (!entry.images || !entry.images.length) return entry;
                return { ...entry, images: entry.images.map(({ dataUrl: _d, ...rest }) => rest) };
            }),
            logs: (session.logs || []).map(({ payload: _p, ...rest }) => rest),
        };
    }

    function persistUiSessionSnapshot(sessionId, session, { keepalive = false } = {}) {
        const apiUrl = settingsRef.current.apiUrl;
        if (!apiUrl || !sessionId || !session) {
            return;
        }
        const slim = buildSlimSessionSnapshot(session);
        fetch(`${apiUrl}/ui-sessions/${sessionId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(slim),
            keepalive,
        }).catch(() => {});
    }

    function updateSessionById(sessionId, transform, { touchUpdatedAt = true, persistKeepalive = false } = {}) {
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
            persistUiSessionSnapshot(sessionId, clone, { keepalive: persistKeepalive });
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

    function patchTranscriptEntry(sessionId, entryId, patch, options = {}) {
        updateSessionById(sessionId, (session) => {
            const target = session.transcript.find((entry) => entry.id === entryId);
            if (!target) return;
            Object.assign(target, patch);
        }, options);
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
            const skills = filterHarnessSkills(payload.skills || []);
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

    async function refreshPublishedProjects() {
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/published-projects`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            setPublishedProjects(Array.isArray(payload.discover) ? payload.discover : []);
            setLeaderboardProjects(Array.isArray(payload.leaderboard) ? payload.leaderboard : []);
        } catch (error) {
            console.debug("Failed to load published projects", error);
            setPublishedProjects([]);
            setLeaderboardProjects([]);
        }
    }

    async function reloadSkillCatalog() {
        const response = await fetch(`${settingsRef.current.apiUrl}/skills/reload`, { method: "POST" });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${response.status}`);
        }
        const payload = await response.json();
        const skills = filterHarnessSkills(payload.skills || []);
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
        const skills = filterHarnessSkills(payload.skills || []);
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
        const skills = filterHarnessSkills(payload.skills || []);
        setSkillCatalog(skills);
        setSelectedSkills((current) => {
            const available = new Set(skills.map((s) => s.name));
            return current.filter((n) => available.has(n));
        });
    }

    async function refreshWorkspaceState(sessionId = currentSessionId) {
        try {
            const params = new URLSearchParams();
            if (sessionId) {
                params.set("session_id", sessionId);
            }
            const suffix = params.toString() ? `?${params.toString()}` : "";
            const response = await fetch(`${settingsRef.current.apiUrl}/workspace${suffix}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            const nextPath = payload.workspace?.path || "";
            if (nextPath) {
                setWorkspacePath((current) => current || nextPath);
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
            } else if (currentSessionId) {
                params.set("session_id", currentSessionId);
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
        const initialPath = workspacePath || "";
        setWorkspaceDraftPath(initialPath);
        await browseWorkspace(initialPath);
    }

    async function openNativeWorkspacePicker() {
        setWorkspaceError("");
        try {
            const params = new URLSearchParams();
            if (currentSessionId) {
                params.set("session_id", currentSessionId);
            }
            const suffix = params.toString() ? `?${params.toString()}` : "";
            const response = await fetch(`${settingsRef.current.apiUrl}/workspace/pick${suffix}`, {
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
                body: JSON.stringify({ path: workspaceDraftPath.trim(), session_id: currentSessionId })
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

    function cycleThemeMode() {
        setThemeMode((current) => {
            const order = ["system", "light", "dark"];
            const currentIndex = order.indexOf(normalizeThemeMode(current));
            return order[(currentIndex + 1) % order.length];
        });
    }

    function cyclePermissionMode() {
        setPermissionMode((current) => normalizePermissionMode(current) === "ask" ? "auto" : "ask");
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

    function clearComposerDraft() {
        setComposerValue("");
        setComposerImages([]);
        setComposerHistoryIndex(null);
        setComposerHistoryDraft("");
    }

    function appendUserTranscript(sessionId, content, snapshotImages) {
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
    }

    function queueGuidedCreateQuestion(flow, index, answers) {
        const question = flow.questions[index];
        if (!question) {
            setGuidedCreateFlow(null);
            return;
        }
        const deadlineAt = Date.now() + CREATE_GUIDED_TIMEOUT_MS;
        const entry = appendTranscriptEntry(flow.sessionId, {
            role: "assistant",
            content: question.title,
            kind: "guided_choice",
            taskId: "main",
            guidedChoice: {
                ...question,
                status: "pending",
                questionIndex: index + 1,
                questionCount: flow.questions.length,
                deadlineAt,
            },
        });
        setGuidedCreateFlow({
            ...flow,
            currentIndex: index,
            answers,
            entryId: entry.id,
            deadlineAt,
        });
    }

    function startGuidedCreateFlow(sessionId, content, snapshotImages) {
        const questions = buildCreateGuidedQuestions(content);
        if (!questions.length) {
            return false;
        }
        appendUserTranscript(sessionId, content, snapshotImages);
        clearComposerDraft();
        queueGuidedCreateQuestion({
            sessionId,
            baseContent: content,
            snapshotImages,
            questions,
        }, 0, {});
        return true;
    }

    function resolveGuidedCreateChoice(entryId, optionValue, autoSelected = false) {
        const flow = guidedCreateFlow;
        if (!flow || flow.entryId !== entryId) {
            return;
        }
        const question = flow.questions[flow.currentIndex];
        const option = question?.options?.find((item) => item.value === optionValue)
            || question?.options?.find((item) => item.value === question.defaultValue)
            || question?.options?.[0];
        if (!question || !option) {
            setGuidedCreateFlow(null);
            return;
        }
        patchTranscriptEntry(flow.sessionId, flow.entryId, {
            content: `${question.title}\n${autoSelected ? "已自动采用默认方案" : "已选择"}：${option.label}`,
            guidedChoice: {
                ...question,
                status: "resolved",
                selectedValue: option.value,
                selectedLabel: option.label,
                autoSelected,
                questionIndex: flow.currentIndex + 1,
                questionCount: flow.questions.length,
            },
        });
        const nextAnswers = {
            ...flow.answers,
            [question.key]: {
                title: question.title.replace(/[？?]$/, ""),
                label: option.label,
                value: option.value,
                autoSelected,
            },
        };
        const nextIndex = flow.currentIndex + 1;
        if (nextIndex < flow.questions.length) {
            queueGuidedCreateQuestion(flow, nextIndex, nextAnswers);
            return;
        }
        setGuidedCreateFlow(null);
        void sendMessage({
            rawInput: flow.baseContent,
            requestContent: buildCreateGuidedRequest(flow.baseContent, nextAnswers),
            snapshotImages: flow.snapshotImages,
            sessionId: flow.sessionId,
            skipUserTranscript: true,
            skipGuidedFlowLock: true,
        });
    }

    async function sendMessage(options = {}) {
        if (guidedCreateFlow && !options.skipGuidedFlowLock) {
            return;
        }
        const targetSessionId = options.sessionId || currentSessionId;
        if (isSending && sendingSessionIdRef.current === targetSessionId) return;
        const rawInput = String(options.rawInput ?? messageInputRef.current?.value ?? "").trim();
        const snapshotImages = Array.isArray(options.snapshotImages) ? [...options.snapshotImages] : [...composerImages];
        const content = String(options.displayContent ?? rawInput).trim();
        const requestContent = String(options.requestContent ?? rawInput).trim();
        if (!content && snapshotImages.length === 0) return;
        if (!targetSessionId) return;
        if (
            CREATE_GUIDED_FLOW_ENABLED
            && !options.skipGuidedCreate
            && mode === "create"
            && content
            && startGuidedCreateFlow(targetSessionId, content, snapshotImages)
        ) {
            return;
        }

        const messageParts = [
            ...(requestContent ? [{ type: "text", text: requestContent }] : []),
            ...snapshotImages.map((image) => ({ type: "image", id: image.id, name: image.name, data_url: image.dataUrl })),
        ];

        const sessionId = targetSessionId;
        const requestMode = mode;
        const effectiveSelectedSkills = requestMode === "create"
            ? Array.from(new Set([...selectedSkills, ...CREATE_MODE_SKILLS]))
            : selectedSkills;
        const effectivePermissionMode = normalizePermissionMode(permissionMode);
        const { toolContext: selectedToolContext, context } = buildContextPayload("workspace", "");
        sendingSessionIdRef.current = sessionId;
        setIsSending(true);
        setSessionBadges((prev) => ({ ...prev, [sessionId]: "working" }));
        setCompletedLabel(null);
        sendStartTimeRef.current = Date.now();
        setRequestIndicator({
            active: true,
            startedAt: Date.now(),
            label: requestMode === "battle"
                ? "Running battle contenders"
                : requestMode === "create"
                    ? "Scaffolding runnable app"
                : (thinkingMode ? "Preparing request" : "Working on your request"),
        });
        if (requestMode === "create") {
            setPreviewOpen(true);
        }
        setContextPercent(computeContextPercent(currentSession, toolContext));

        if (!options.skipUserTranscript) {
            appendUserTranscript(sessionId, content, snapshotImages);
        }
        clearComposerDraft();

        let assistantEntry = null;
        let thinkingEntry = null;
        let agentProcessEntry = null;
        let pendingTodo = null;
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
                    message: requestContent,
                    session_id: sessionId,
                    permission_mode: effectivePermissionMode,
                    permission_confirmed: effectivePermissionMode !== "ask",
                    thinking_mode: thinkingMode,
                    mode: requestMode,
                    model: selectedModel,
                    tool_context: selectedToolContext,
                    enabled_skills: effectiveSelectedSkills,
                    message_parts: messageParts,
                    context,
                    parameters: {
                        message: requestContent,
                        session_id: sessionId,
                        permission_mode: effectivePermissionMode,
                        permission_confirmed: effectivePermissionMode !== "ask",
                        thinking_mode: thinkingMode,
                        mode: requestMode,
                        model: selectedModel,
                        tool_context: selectedToolContext,
                        enabled_skills: effectiveSelectedSkills,
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

                const syncTodoAttachment = () => {
                    if (!pendingTodo) {
                        return;
                    }
                    const nextTodo = normalizeTodo(pendingTodo);
                    if (!nextTodo) {
                        return;
                    }
                    const targetEntry = assistantEntry || agentProcessEntry || thinkingEntry;
                    if (!targetEntry?.id) {
                        return;
                    }
                    patchTranscriptEntry(sessionId, targetEntry.id, { todo: nextTodo });
                    if (assistantEntry?.id && agentProcessEntry?.id && agentProcessEntry.id !== assistantEntry.id) {
                        patchTranscriptEntry(sessionId, agentProcessEntry.id, { todo: null });
                    }
                    if (assistantEntry?.id && thinkingEntry?.id && thinkingEntry.id !== assistantEntry.id) {
                        patchTranscriptEntry(sessionId, thinkingEntry.id, { todo: null });
                    }
                };

                const upsertAgentProcess = (step) => {
                    const friendlyStep = userFacingStep(step);
                    const role = normalizeHarnessRole(friendlyStep.role);
                    const timestamp = step.timestamp || nowIso();
                    const currentProcess = normalizeAgentProcess(agentProcessEntry?.agentProcess);
                    const nextEvent = {
                        role,
                        status: friendlyStep.status || "running",
                        title: friendlyStep.title || "Working",
                        detail: friendlyStep.detail || "",
                        evidence: friendlyStep.evidence || "",
                        timestamp,
                    };
                    const nextProcess = normalizeAgentProcess({
                        roles: {
                            ...currentProcess.roles,
                            [role]: {
                                status: nextEvent.status,
                                title: nextEvent.title,
                                detail: nextEvent.detail,
                                evidence: nextEvent.evidence,
                                updatedAt: timestamp,
                            },
                        },
                        events: [...(currentProcess.events || []), nextEvent],
                        statusLine: step.statusLine || currentProcess.statusLine || "",
                        currentIssue: nextEvent.status === "error"
                            ? {
                                title: nextEvent.title,
                                detail: nextEvent.detail,
                                evidence: nextEvent.evidence,
                            }
                            : step.currentIssue || (step.decision?.decision === "PASS" ? null : currentProcess.currentIssue),
                        nextAction: step.nextAction || friendlyStep.recommendedAction || currentProcess.nextAction || "",
                        latestSummary: normalizeDisplaySummary(step.displaySummary || step.display_summary) || currentProcess.latestSummary,
                        decision: normalizeHarnessDecision(step.decision) || currentProcess.decision,
                        roundId: Number(step.roundId || step.round_id || currentProcess.roundId || 0),
                    });
                    if (!agentProcessEntry) {
                        agentProcessEntry = appendTranscriptEntry(sessionId, {
                            role: "assistant",
                            content: "",
                            kind: "agent_process",
                            taskId: "main",
                            streaming: true,
                            agentProcess: nextProcess,
                        });
                    } else {
                        agentProcessEntry = { ...agentProcessEntry, agentProcess: nextProcess, streaming: true };
                        patchTranscriptEntry(sessionId, agentProcessEntry.id, {
                            agentProcess: nextProcess,
                            streaming: true,
                        });
                    }
                    syncTodoAttachment();
                };

                const appendThinkingTrace = (line) => {
                    if (!thinkingMode || !line) {
                        return;
                    }
                    const nextThinking = normalizeDisplayText(
                        `${thinkingEntry?.content || ""}${thinkingEntry?.content ? "\n" : ""}${line}`
                    );
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
                    syncTodoAttachment();
                };

                if (payload.type === "agent_step") {
                    upsertAgentProcess({
                        ...payload,
                        user_event: payload.user_event,
                    });
                    setRequestIndicator((current) => current?.active ? {
                        ...current,
                        label: userFacingStep(payload).title || "Working",
                    } : current);
                    return;
                }

                if (payload.type === "agent_summary") {
                    const displaySummary = normalizeDisplaySummary(payload.display_summary);
                    upsertAgentProcess({
                        role: payload.role,
                        status: displaySummary?.status === "warning" ? "error" : (displaySummary?.status || "success"),
                        title: displaySummary?.title || `${payload.role || "Agent"} 输出已记录`,
                        detail: displaySummary?.summary || "",
                        evidence: (displaySummary?.highlights || []).join(" · "),
                        displaySummary,
                        statusLine: displaySummary?.title || "",
                        nextAction: displaySummary?.nextStep || "",
                        round_id: payload.round_id,
                    });
                    setRequestIndicator((current) => current?.active ? {
                        ...current,
                        label: displaySummary?.title || current.label,
                    } : current);
                    return;
                }

                if (payload.type === "harness_decision") {
                    const decision = normalizeHarnessDecision(payload.decision);
                    upsertAgentProcess({
                        role: decision?.nextAgent && decision.nextAgent !== "None" ? decision.nextAgent : "Evaluator",
                        status: decision?.decision === "PASS" ? "success" : "running",
                        title: decision?.decision === "PASS" ? "任务已通过 Harness 验收" : "Harness 已决定下一步",
                        detail: decision?.reason || "",
                        decision,
                        statusLine: decision?.decision === "PASS"
                            ? `已完成 · 第 ${decision.roundId || 0} 轮`
                            : `${decision?.decision || "处理中"} · 第 ${decision?.roundId || 0} 轮`,
                        nextAction: decision?.nextAgent && decision.nextAgent !== "None"
                            ? `下一步交由 ${decision.nextAgent}，进入 ${decision.nextState || "下一阶段"}`
                            : "",
                        round_id: decision?.roundId || 0,
                    });
                    if (decision?.decision) {
                        setRequestIndicator((current) => current?.active ? {
                            ...current,
                            label: decision.decision === "PASS" ? "已完成验收" : "准备进入下一步",
                        } : current);
                    }
                    return;
                }

                if (payload.type === "task_start") {
                    toolCallsReceived += 1;
                    const taskStep = userFacingStep(payload);
                    setRequestIndicator((current) => current?.active ? {
                        ...current,
                        label: taskStep.title || "Working",
                    } : current);
                    if (!payload.agent_role) {
                        upsertAgentProcess({
                            ...payload,
                            role: payload.skill === "bash" ? "Runner" : "Generator",
                            status: "running",
                        });
                    }
                    return;
                }

                if (payload.type === "task_complete") {
                    if (!payload.agent_role) {
                        upsertAgentProcess({
                            ...payload,
                            role: payload.skill === "bash" ? "Runner" : "Generator",
                            status: payload.success === false ? "error" : "success",
                        });
                    }
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
                    pendingTodo = normalizeTodo({
                        items: (payload.items || []).map((text) => ({ text, done: false })),
                        completed: false,
                    });
                    syncTodoAttachment();
                    return;
                }

                if (payload.type === "todo_done") {
                    const idx = payload.index;
                    if (!pendingTodo) {
                        return;
                    }
                    pendingTodo = normalizeTodo({
                        ...pendingTodo,
                        items: pendingTodo.items.map((item, index) => (
                            index === idx ? { ...item, done: true } : item
                        )),
                    });
                    syncTodoAttachment();
                    return;
                }

                if (payload.type === "thinking_delta") {
                    // Raw provider reasoning is intentionally not rendered as user-facing
                    // process. The visible progress surface is `agent_step`, which is
                    // structured, role-scoped, and safe to inspect.
                    return;
                }

                const isLegacyAnswerPayload = !payload.type && typeof payload.content === "string";
                if (payload.type === "answer_delta" || isLegacyAnswerPayload) {
                    setRequestIndicator(null);
                    answerBuffer = normalizeDisplayText(`${answerBuffer}${payload.delta || payload.content || ""}`);
                    if (!answerBuffer.trim()) {
                        return;
                    }
                    if (!assistantEntry) {
                        assistantEntry = appendTranscriptEntry(sessionId, {
                            role: "assistant",
                            content: answerBuffer,
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: true,
                            todo: pendingTodo,
                        });
                    } else {
                        patchTranscriptEntry(sessionId, assistantEntry.id, {
                            content: answerBuffer,
                            streaming: true
                        });
                    }
                    syncTodoAttachment();
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
                    if (assistantEntry) {
                        patchTranscriptEntry(sessionId, assistantEntry.id, { streaming: false });
                    } else if (answerBuffer.trim()) {
                        assistantEntry = appendTranscriptEntry(sessionId, {
                            role: "assistant",
                            content: answerBuffer.trim(),
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: false,
                            todo: pendingTodo,
                        });
                    } else {
                        // Build a diagnostic: what events DID arrive before done?
                        const gotTools = toolCallsReceived > 0;
                        const hint = gotTools
                            ? `（已收到 ${toolCallsReceived} 个工具调用，但未返回文字回复）`
                            : "（服务端未发送任何文字内容）";
                        throw new Error(`模型没有返回可显示的正文 ${hint}`);
                    }
                    syncTodoAttachment();

                    if (thinkingEntry) {
                        patchTranscriptEntry(sessionId, thinkingEntry.id, {
                            streaming: false,
                            pendingPlaceholder: false
                        });
                    }
                    if (agentProcessEntry) {
                        patchTranscriptEntry(sessionId, agentProcessEntry.id, {
                            streaming: false,
                            agentProcess: normalizeAgentProcess(agentProcessEntry.agentProcess),
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
            if (agentProcessEntry) {
                patchTranscriptEntry(sessionId, agentProcessEntry.id, {
                    streaming: false,
                    agentProcess: normalizeAgentProcess(agentProcessEntry.agentProcess),
                });
            }
                if (error.name === "AbortError") {
                    if (assistantEntry) {
                        patchTranscriptEntry(sessionId, assistantEntry.id, { streaming: false });
                    } else if (answerBuffer.trim()) {
                        assistantEntry = appendTranscriptEntry(sessionId, {
                            role: "assistant",
                            content: answerBuffer.trim(),
                            kind: "assistant_text",
                            taskId: "main",
                            streaming: false,
                            todo: pendingTodo,
                        });
                    }
                } else {
                    assistantEntry = appendTranscriptEntry(sessionId, {
                        role: "assistant",
                        content: `请求失败: ${error.message}`,
                        kind: "assistant_text",
                        isError: true,
                        taskId: "main",
                        streaming: false,
                        todo: null,
                    });
                }
                if (assistantEntry?.id && pendingTodo && !assistantEntry?.isError) {
                    patchTranscriptEntry(sessionId, assistantEntry.id, { todo: normalizeTodo(pendingTodo) });
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
                    patchTranscriptEntry(sessionId, assistantEntry.id, { elapsedLabel: label }, { persistKeepalive: true });
                }
                sendStartTimeRef.current = null;
            }
            // Trigger the "just moved to top" animation on the session item
            setJustSentSessionId(sessionId);
            setTimeout(() => setJustSentSessionId(null), 1600);
            setSessionBadges((prev) => ({ ...prev, [sessionId]: "done" }));
            if (currentSessionIdRef.current === sessionId) {
                setTimeout(() => {
                    setSessionBadges((prev) => {
                        if (!prev[sessionId]) return prev;
                        return { ...prev, [sessionId]: "fading" };
                    });
                    setTimeout(() => {
                        setSessionBadges((prev) => {
                            if (!prev[sessionId]) return prev;
                            const next = { ...prev };
                            delete next[sessionId];
                            return next;
                        });
                    }, 500);
                }, 1200);
            }
            sendingSessionIdRef.current = null;
            setRequestIndicator(null);
            setIsSending(false);
            abortControllerRef.current = null;
        }
    }

    function stopGeneration() {
        if (guidedCreateFlow?.entryId && guidedCreateFlow?.sessionId) {
            patchTranscriptEntry(guidedCreateFlow.sessionId, guidedCreateFlow.entryId, {
                content: `${guidedCreateFlow.questions?.[guidedCreateFlow.currentIndex]?.title || "Create 引导问题"}\n已取消本轮引导。`,
                guidedChoice: {
                    ...(guidedCreateFlow.questions?.[guidedCreateFlow.currentIndex] || {}),
                    status: "cancelled",
                },
            });
            setGuidedCreateFlow(null);
            return;
        }
        abortControllerRef.current?.abort();
    }

    function togglePreview() {
        setPreviewOpen((current) => {
            const next = !current;
            previewDismissedKeyRef.current = next ? "" : previewAutoOpenKey;
            return next;
        });
    }

    function closePreviewPane() {
        previewDismissedKeyRef.current = previewAutoOpenKey;
        setPreviewOpen(false);
    }

    function refreshPreviewPane() {
        setPreviewNonce((current) => current + 1);
    }

    async function publishPreviewLink() {
        if (!activePreviewUrl || !currentSession) {
            return;
        }
        setPublishingProject(true);
        try {
            const response = await fetch(`${settingsRef.current.apiUrl}/published-projects`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: currentSession.id,
                    title: currentSession.title || "未命名作品",
                    prompt: firstUserPrompt(currentSession),
                    description: latestAssistantSummary(currentSession),
                    preview_url: activePreviewUrl,
                    preview_label: previewHeadline,
                    workspace_path: activeWorkspacePath,
                    mode,
                    tags: inferProjectTags(currentSession, activePreviewUrl),
                    remixable: true,
                }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.ok === false) {
                throw new Error(payload.error || `HTTP ${response.status}`);
            }
            setPublishToast("作品已发布到发现页");
            setDiscoverTab("discover");
            await refreshPublishedProjects();
        } catch (error) {
            console.debug("Failed to publish project", error);
            setPublishToast("发布失败，请稍后重试");
        } finally {
            setPublishingProject(false);
        }
        window.setTimeout(() => setPublishToast(""), 2400);
    }

    function remixProject(project) {
        const session = createEmptySession(`session_${Date.now()}`);
        session.title = `${project.title} · 二创`;
        updateSessions((previous) => [session, ...previous]);
        setCurrentSessionId(session.id);
        setMode("create");
        setPreviewOpen(true);
        setDiscoverTab("discover");
        setCreateHubOpen(false);
        const apiUrl = settingsRef.current.apiUrl || resolveDefaultApiBaseUrl();
        fetch(`${apiUrl}/ui-sessions/${session.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(session),
        }).catch(() => {});
        requestAnimationFrame(() => {
            setComposerValue(buildRemixPrompt(project));
            focusComposerWithCursor();
        });
    }

    function focusFilesChanged() {
        setPreviewOpen(true);
    }

    function toggleCreateHub() {
        setCreateHubOpen((current) => !current);
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
    const nativeWorkspaceLabel = "Pick Folder";
    const nativeWorkspaceHelp = explainWorkspacePickerBoundary();
    const workingTimerLabel = requestIndicator?.active && requestIndicator?.startedAt
        ? formatWorkingDuration(requestTimerNow - requestIndicator.startedAt)
        : "";

    return (
        <div className={`app-shell${previewOpen ? " preview-active" : ""}`}>
            <aside className={`sidebar${previewOpen ? " preview-compact" : ""}`}>
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

            <main className={`workspace${previewOpen ? " workspace-split" : ""}`}>
                <RuntimePills
                    mode={mode}
                    contextPercent={contextPercent}
                    contextTokens={contextTokens}
                    contextMaxTokens={contextMaxTokens}
                    threadContextPercent={threadContextPercent}
                    threadContextTokens={threadContextTokens}
                    threadTurnCount={threadTurnCount}
                    githubUrl={GITHUB_REPO_URL}
                    onExport={exportCurrentSession}
                    previewOpen={previewOpen}
                    onTogglePreview={togglePreview}
                    createHubOpen={createHubOpen}
                    onToggleCreateHub={toggleCreateHub}
                    fileChangeSummary={fileChangeSummary}
                    onFocusFiles={focusFilesChanged}
                    themeMode={themeMode}
                    effectiveTheme={effectiveTheme}
                    onThemeToggle={cycleThemeMode}
                />

                <section className={`create-hub-dropdown${createHubOpen ? " open" : ""}`} aria-hidden={!createHubOpen}>
                    <section className="create-hub">
                        <div className="create-hub-header">
                            <div>
                                <span className="create-hub-kicker">Create Hub</span>
                                <h2>发布、发现、二创在一条链路里完成</h2>
                                <p>先把作品稳定生成出来，再一键发布到发现页，让其他玩家可见、可继续二创。</p>
                            </div>
                            <div className="create-hub-tabs">
                                <button
                                    type="button"
                                    className={`create-hub-tab${discoverTab === "discover" ? " active" : ""}`}
                                    onClick={() => setDiscoverTab("discover")}
                                >
                                    发现
                                </button>
                                <button
                                    type="button"
                                    className={`create-hub-tab${discoverTab === "leaderboard" ? " active" : ""}`}
                                    onClick={() => setDiscoverTab("leaderboard")}
                                >
                                    排行榜
                                </button>
                            </div>
                        </div>
                        <div className="create-hub-grid">
                            <article className="create-priority-card">
                                <span className="create-priority-eyebrow">当前优先级</span>
                                <h3>先确保第一次生成就能跑，再发布</h3>
                                <p>当前的发布会记录作品标题、原始需求、预览入口和标签，发布后立即进入首页发现区，后续可以继续补热度、评分和后台管理。</p>
                                <div className="create-priority-pills">
                                    <span>稳定可玩</span>
                                    <span>发布可见</span>
                                    <span>支持二创</span>
                                </div>
                            </article>

                            <section className="create-gallery">
                                <div className="create-gallery-head">
                                    <div>
                                        <span className="create-gallery-title">{discoverTab === "leaderboard" ? "本周排行榜" : "发现新作品"}</span>
                                        <span className="create-gallery-subtitle">
                                            {discoverTab === "leaderboard" ? "按热度、启动次数、二创数综合排序" : "最新发布的 create 作品会优先出现在这里"}
                                        </span>
                                    </div>
                                    <button type="button" className="ghost-icon" title="刷新作品列表" onClick={refreshPublishedProjects}>
                                        <i className="fas fa-rotate-right" />
                                    </button>
                                </div>
                                {discoverProjects.length ? (
                                    <div className="create-gallery-grid">
                                        {discoverProjects.map((project, index) => (
                                            <article key={project.id} className="published-project-card">
                                                <div className="published-project-topline">
                                                    <span className="published-project-rank">
                                                        {discoverTab === "leaderboard" ? `#${index + 1}` : "NEW"}
                                                    </span>
                                                    <span className="published-project-score">
                                                        热度 {project.leaderboard_score || 0}
                                                    </span>
                                                </div>
                                                <h3>{project.title}</h3>
                                                <p>{project.description || project.prompt || "已发布作品，等待下一位创作者继续扩展。"}</p>
                                                <div className="published-project-tags">
                                                    {(project.tags || []).slice(0, 3).map((tag) => (
                                                        <span key={`${project.id}-${tag}`}>{tag}</span>
                                                    ))}
                                                </div>
                                                <div className="published-project-meta">
                                                    <span>二创 {project.remix_count || 0}</span>
                                                    <span>启动 {project.launch_count || 0}</span>
                                                </div>
                                                <div className="published-project-actions">
                                                    {project.preview_url ? (
                                                        <button
                                                            type="button"
                                                            className="small-tool active"
                                                            onClick={() => {
                                                                setPreviewOpen(true);
                                                                setPreviewUrl(project.preview_url);
                                                                setPreviewNonce((n) => n + 1);
                                                            }}
                                                        >
                                                            <i className="fas fa-play" />
                                                            <span>预览</span>
                                                        </button>
                                                    ) : null}
                                                    <button
                                                        type="button"
                                                        className="small-tool"
                                                        onClick={() => remixProject(project)}
                                                    >
                                                        <i className="fas fa-code-branch" />
                                                        <span>二创</span>
                                                    </button>
                                                </div>
                                            </article>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="create-gallery-empty">
                                        <i className="fas fa-rocket" aria-hidden="true" />
                                        <p>还没有已发布作品。完成 create 产物后点右侧“发布作品”，这里就会开始积累内容。</p>
                                    </div>
                                )}
                            </section>
                        </div>
                    </section>
                </section>

                <div className={`workspace-content-shell${previewOpen ? " split" : ""}`}>
                    <section className="workspace-main-pane">
                        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                            <TranscriptView
                                transcript={currentSession?.transcript || []}
                                chatMessagesRef={chatMessagesRef}
                                expandedThinking={expandedThinking}
                                onToggleThinking={toggleThinkingEntry}
                                onGuidedChoiceSelect={resolveGuidedCreateChoice}
                                guidedChoiceNow={guidedChoiceNow}
                                requestIndicator={requestIndicator}
                                workingTimerLabel={workingTimerLabel}
                                completedLabel={completedLabel}
                            />
                        </div>

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
                            statusItems={[
                                `agent:harness`,
                                `permission:${permissionMode}`,
                                `thread:${currentSessionId || "--"}`,
                                `messages:${currentSession?.transcript?.length || 0}`,
                                `model:${shortenModel(runtime?.model)}`
                            ]}
                            inputRef={messageInputRef}
                        />
                    </section>

                    {previewOpen ? (
                        <aside className="preview-pane">
                            <div className="preview-pane-shell">
                                <div className="preview-pane-header">
                                    <div className="preview-pane-copy">
                                        <div className="preview-pane-identity">
                                            <span className="preview-pane-kicker">Live Preview</span>
                                            {previewArtifactOptions.length > 1 ? (
                                                <label className="preview-artifact-picker preview-artifact-picker--merged">
                                                    <span className="visually-hidden">切换预览产物</span>
                                                    <select
                                                        className="preview-artifact-select preview-artifact-select--merged"
                                                        value={activePreviewUrl}
                                                        onChange={(e) => {
                                                            setPreviewUrl(e.target.value);
                                                            setPreviewNonce((n) => n + 1);
                                                        }}
                                                        title="工作区内多个 HTML 或对话中有多个 URL 时可在此切换"
                                                    >
                                                        {previewArtifactOptions.map((o) => (
                                                            <option key={o.url} value={o.url}>{o.label}</option>
                                                        ))}
                                                    </select>
                                                </label>
                                            ) : (
                                                <div
                                                    className="preview-pane-target-static"
                                                    title={activePreviewUrl || previewHeadline}
                                                >
                                                    {previewHeadline}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    <div className="preview-pane-actions">
                                        {publishToast ? (
                                            <span className="preview-publish-toast" role="status">{publishToast}</span>
                                        ) : null}
                                        {activePreviewUrl ? (
                                            <>
                                                <button
                                                    type="button"
                                                    className="preview-publish-btn"
                                                    title="将当前 create 作品发布到发现页，供其他人可见和二创"
                                                    onClick={publishPreviewLink}
                                                    disabled={publishingProject}
                                                >
                                                    {publishingProject ? "发布中..." : "发布作品"}
                                                </button>
                                                <button type="button" className="icon-button" title="Refresh preview" onClick={refreshPreviewPane}>
                                                    <i className="fas fa-rotate-right" />
                                                </button>
                                                <a className="icon-button" href={activePreviewUrl} target="_blank" rel="noreferrer noopener" title="Open preview in a new tab">
                                                    <i className="fas fa-arrow-up-right-from-square" />
                                                </a>
                                            </>
                                        ) : null}
                                        <button type="button" className="icon-button" title="Close preview" onClick={closePreviewPane}>
                                            <i className="fas fa-xmark" />
                                        </button>
                                    </div>
                                </div>

                                {activePreviewUrl ? (
                                    <div className="preview-frame-wrap">
                                        <iframe
                                            key={`${activePreviewUrl}:${previewNonce}`}
                                            className="preview-frame"
                                            src={activePreviewUrl}
                                            title="App preview"
                                        />
                                    </div>
                                ) : (
                                    <div className="preview-empty">
                                        <i className="fas fa-window-restore" aria-hidden="true" />
                                        <p>
                                            对话里出现可访问的 http(s) URL 时会自动加载；若只有本地 HTML 文件，
                                            会在当前 thread 的默认工作区检测到变更后尝试打开 HTML 预览。
                                        </p>
                                    </div>
                                )}
                            </div>
                        </aside>
                    ) : null}
                </div>
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
                threadTitle={currentSession?.title || ""}
                threadId={currentSessionId || ""}
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
        </div>
    );
}

export default App;
