import React, { useState } from "react";

function joinList(items, fallback = "none") {
    return items.length ? items.join(" · ") : fallback;
}

function localizeValue(node, key, locale, fallback = "") {
    if (!node || typeof node !== "object") {
        return fallback;
    }
    const localized = node[`${key}_${locale}`];
    if (localized) {
        return localized;
    }
    return node[key] || fallback;
}

function buildSkillSnapshot(selectedSkills, skillCatalog) {
    const safeSkillCatalog = Array.isArray(skillCatalog) ? skillCatalog : [];
    const safeSelectedSkills = Array.isArray(selectedSkills) ? selectedSkills : [];
    const selected = safeSkillCatalog
        .filter((skill) => safeSelectedSkills.includes(skill.name))
        .map((skill) => ({
            name: skill.name,
            description: skill.description || "Runtime-enabled skill",
            tools: Array.isArray(skill.tool_names) ? skill.tool_names.filter(Boolean) : [],
        }));

    return {
        selected,
        selectedNames: selected.map((skill) => skill.name),
        selectedToolNames: selected.flatMap((skill) => skill.tools),
    };
}

function getCopy(locale) {
    if (locale === "zh") {
        return {
            headerTitle: "项目架构",
            headerMeta: "按当前后端真实分层与运行态生成的流程图 / 数据流图。",
            heroKicker: "Agent 核心设计",
            heroTitle: "参考 Claude Code 的 harness 分层后，当前项目从请求入口到工具循环、再到持久化回流的真实代码路径。",
            heroBody: "重点不是宣传文案，而是项目里真实存在的请求编排层、SessionStore 持久化层、RequestLifecycle 生命周期层、StreamingAgent 模式路由与工具循环层，以及最终的 SSE 可观测面。",
            languageLabel: "语言",
            zh: "中文",
            en: "English",
            promptKicker: "简化 Prompt",
            promptTitle: "当前工程里送入模型的工作上下文骨架",
            promptBadge: "代码同构",
            eventKicker: "生命周期 / SSE 事件",
            detailRuntime: "运行时快照",
            detailSkill: "已选技能与真实工具",
            detailRoute: "模式路由",
            detailTrace: "观测与持久化",
            noSkills: "当前未勾选技能，因此只会保留基础 Agent 路径。",
            outputLabel: "输出对象",
            moduleLabel: "代码模块",
        };
    }

    return {
        headerTitle: "Project Architecture",
        headerMeta: "Flowchart / dataflow generated from the current backend layering and runtime state.",
        heroKicker: "Agent Core Design",
        heroTitle: "Actual code path after aligning the project to a Claude Code-style harness: ingress, routing, tool loop, and persistence replay.",
        heroBody: "This panel is intentionally concrete. It reflects the real request harness, SessionStore persistence layer, RequestLifecycle phase layer, StreamingAgent routing/tool loop, and the final SSE observability surface.",
        languageLabel: "Language",
        zh: "中文",
        en: "English",
        promptKicker: "Simplified Prompt",
        promptTitle: "Working-context skeleton that actually goes into the model",
        promptBadge: "Code-aligned",
        eventKicker: "Lifecycle / SSE Events",
        detailRuntime: "Runtime Snapshot",
        detailSkill: "Selected Skills and Real Tools",
        detailRoute: "Mode Routing",
        detailTrace: "Observability and Persistence",
        noSkills: "No skill is selected, so only the base agent path remains active.",
        outputLabel: "Outputs",
        moduleLabel: "Module",
    };
}

function buildPromptPreview({
    locale,
    promptSections,
    toolContext,
    workspace,
    activeModel,
    permissionMode,
    thinkingMode,
    selectedSkillLine,
}) {
    const sectionOrder = Array.isArray(promptSections) && promptSections.length
        ? promptSections
        : [
            "workspace_context",
            "runtime_context",
            "historical_summary",
            "recent_summary",
            "skill_index",
            "skill_instructions",
            "tool_guidance",
            "current_user_request",
        ];

    const sectionText = {
        zh: {
            workspace_context: [
                "[Workspace / tool context]",
                `Tool context: ${toolContext || "workspace"}`,
                `Workspace path: ${workspace}`,
            ],
            runtime_context: [
                "[Runtime context]",
                `Current model: ${activeModel}`,
                `Permission mode: ${permissionMode}`,
                `Thinking mode: ${thinkingMode ? "on" : "off"}`,
                "日期、时间、时区、位置信息由后端运行时注入。",
            ],
            historical_summary: [
                "[Historical summary]",
                "长会话时由模型压缩生成，用来保留长期目标、约束、历史结论与关键事实。",
            ],
            recent_summary: [
                "[Recent summary]",
                "保留最近几轮的工具结果、未完成事项和连续语义。",
            ],
            skill_index: [
                "[Available skills index]",
                selectedSkillLine,
            ],
            skill_instructions: [
                "[Relevant skill instructions]",
                "只对当前可用技能加载对应 SKILL.md 指令，不做整仓拼接。",
            ],
            tool_guidance: [
                "[Tool guidance]",
                "实时问题优先走真实工具，本地问题优先走工作区技能。",
            ],
            current_user_request: [
                "[Current user request]",
                "最后一段才是当前用户问题，上面都是压缩后的工作上下文。",
            ],
        },
        en: {
            workspace_context: [
                "[Workspace / tool context]",
                `Tool context: ${toolContext || "workspace"}`,
                `Workspace path: ${workspace}`,
            ],
            runtime_context: [
                "[Runtime context]",
                `Current model: ${activeModel}`,
                `Permission mode: ${permissionMode}`,
                `Thinking mode: ${thinkingMode ? "on" : "off"}`,
                "Date, time, timezone, and location are injected by backend runtime state.",
            ],
            historical_summary: [
                "[Historical summary]",
                "Model-compressed long-horizon memory preserving goals, constraints, decisions, and durable facts.",
            ],
            recent_summary: [
                "[Recent summary]",
                "Short-horizon memory preserving recent tool outputs, unresolved asks, and conversational continuity.",
            ],
            skill_index: [
                "[Available skills index]",
                selectedSkillLine,
            ],
            skill_instructions: [
                "[Relevant skill instructions]",
                "Only the instructions for currently eligible SKILL.md entries are loaded.",
            ],
            tool_guidance: [
                "[Tool guidance]",
                "Prefer real tools for current information and workspace-bound tools for local tasks.",
            ],
            current_user_request: [
                "[Current user request]",
                "The final section is the active user ask; everything above is compacted working context.",
            ],
        },
    };

    return sectionOrder
        .flatMap((sectionKey) => sectionText[locale][sectionKey] || [sectionKey])
        .join("\n");
}

function buildFlowModel({
    locale,
    runtime,
    architectureManifest,
    workspacePath,
    selectedSkills,
    skillCatalog,
    mode,
    currentSession,
    sessionCount,
    contextPercent,
    permissionMode,
    thinkingMode,
    toolContext,
    selectedModel,
}) {
    const copy = getCopy(locale);
    const safeSession = currentSession || {};
    const transcriptCount = safeSession?.transcript?.length || 0;
    const logCount = safeSession?.logs?.length || 0;
    const backendArchitecture = architectureManifest?.architecture || {};
    const backendRuntime = architectureManifest?.runtime || {};
    const runtimeSnapshot = { ...(backendRuntime || {}), ...(runtime || {}) };
    const contextValue = typeof contextPercent === "number" ? `${contextPercent}%` : "0%";
    const runtimeStatus = runtimeSnapshot?.status || runtime?.status || "unknown";
    const activeModel = selectedModel || runtimeSnapshot?.model || runtime?.model || "unknown";
    const workspace = workspacePath || runtimeSnapshot?.workspace_path || runtimeSnapshot?.work_dir || runtime?.work_dir || "not set";
    const runtimeThreadDir = runtimeSnapshot?.runtime_workspace_path || runtime?.runtime_work_dir || "unknown";
    const screenshotDir = runtime?.screenshot_dir || "unknown";
    const skills = buildSkillSnapshot(selectedSkills, skillCatalog);
    const selectedSkillLine = joinList(skills.selectedNames, locale === "zh" ? "未选择技能" : "No skill selected");
    const selectedToolLine = joinList(
        [...new Set(skills.selectedToolNames)],
        locale === "zh" ? "仅基础 Agent 路径" : "Base agent path only"
    );

    const flowRows = Array.isArray(backendArchitecture.flow) && backendArchitecture.flow.length
        ? backendArchitecture.flow.map((row) => ({
            lane: localizeValue(row, "lane", locale, row.id),
            title: localizeValue(row, "title", locale, row.id),
            code: `${row.module}${Array.isArray(row.entrypoints) && row.entrypoints.length ? ` -> ${row.entrypoints.join(" / ")}` : ""}`,
            detail: localizeValue(row, "role", locale, ""),
            tags: Array.isArray(row.inputs) ? row.inputs : [],
            storeTitle: copy.outputLabel,
            storeItems: Array.isArray(row.outputs) ? row.outputs : [],
        }))
        : [];

    const promptPreview = buildPromptPreview({
        locale,
        promptSections: backendArchitecture.prompt_sections,
        toolContext,
        workspace,
        activeModel,
        permissionMode,
        thinkingMode,
        selectedSkillLine,
    });

    const moduleCards = [
        ...(Array.isArray(backendArchitecture.layers) ? backendArchitecture.layers.map((layer) => ({
            title: layer.module?.split(".").slice(-1)[0] || layer.id,
            detail: layer.role,
            bullets: [
                `${copy.moduleLabel}: ${layer.module}`,
                locale === "zh" ? `层标识: ${layer.id}` : `Layer id: ${layer.id}`,
            ],
        })) : []),
        ...(Array.isArray(backendArchitecture.stores) ? backendArchitecture.stores.map((store) => ({
            title: store.name,
            detail: localizeValue(store, "detail", locale, store.name),
            bullets: [
                locale === "zh" ? "服务真实读写这个对象。" : "This object is read and written by the runtime.",
                locale === "zh" ? "用于恢复线程状态、压缩记忆或调试轨迹。" : "Used to restore thread state, compacted memory, or debugging traces.",
            ],
        })) : []),
    ];

    const modeRouteLine = Array.isArray(backendArchitecture.mode_routes)
        ? backendArchitecture.mode_routes
            .map((route) => {
                const purpose = localizeValue(route, "purpose", locale, route.handler);
                return `${route.mode} -> ${route.handler} -> ${purpose}`;
            })
            .join(" | ")
        : "";

    const phaseCatalog = Array.isArray(backendArchitecture.phase_catalog) ? backendArchitecture.phase_catalog : [];
    const eventChips = [
        ...new Set([
            ...phaseCatalog.map((phase) => phase.event_type === "phase" ? phase.key : phase.event_type),
            "thinking_delta",
            "answer_delta",
            "task_start",
            "task_complete",
            "plan",
            "battle_result",
            "done",
        ]),
    ];

    const detailCards = [
        {
            title: copy.detailRuntime,
            detail: locale === "zh"
                ? `状态: ${runtimeStatus} · 工作区: ${workspace} · 运行目录: ${runtimeThreadDir} · 截图目录: ${screenshotDir} · 线程数: ${backendRuntime?.thread_count ?? sessionCount ?? 0}`
                : `Status: ${runtimeStatus} · Workspace: ${workspace} · Runtime dir: ${runtimeThreadDir} · Screenshot dir: ${screenshotDir} · Threads: ${backendRuntime?.thread_count ?? sessionCount ?? 0}`,
        },
        {
            title: copy.detailSkill,
            detail: skills.selected.length
                ? skills.selected.map((skill) => `${skill.name}${skill.tools.length ? ` -> ${skill.tools.join(", ")}` : ""}`).join(" | ")
                : copy.noSkills,
        },
        {
            title: copy.detailRoute,
            detail: modeRouteLine || (locale === "zh" ? `当前模式: ${mode}` : `Current mode: ${mode}`),
        },
        {
            title: copy.detailTrace,
            detail: locale === "zh"
                ? `Transcript ${transcriptCount} 条，Logs ${logCount} 条。SessionStore 会持久化 chat_sessions、context_cache、llm_traces 和 ui_sessions。`
                : `Transcript ${transcriptCount}, Logs ${logCount}. SessionStore persists chat_sessions, context_cache, llm_traces, and ui_sessions.`,
        },
    ];

    return {
        copy,
        flowRows,
        promptPreview,
        moduleCards,
        detailCards,
        eventChips,
        summaryChips: [
            `${locale === "zh" ? "模式" : "Mode"} ${mode}`,
            `${locale === "zh" ? "模型" : "Model"} ${activeModel}`,
            `${locale === "zh" ? "上下文" : "Context"} ${contextValue}`,
            `${locale === "zh" ? "技能" : "Skills"} ${skills.selectedNames.length}`,
            `${locale === "zh" ? "工具" : "Tools"} ${[...new Set(skills.selectedToolNames)].length || backendRuntime?.tools_count || 0}`,
            `${locale === "zh" ? "线程" : "Threads"} ${backendRuntime?.thread_count ?? sessionCount ?? 0}`,
        ],
    };
}

export default function ArchitectureDrawer(props) {
    const [locale, setLocale] = useState("zh");
    const { open, onClose } = props;

    if (!open) {
        return (
            <section className="logs-drawer architecture-drawer hidden" aria-hidden="true">
                <div className="logs-backdrop" onClick={onClose} />
                <div className="logs-sheet architecture-sheet" />
            </section>
        );
    }

    const architecture = buildFlowModel({ ...props, locale });

    return (
        <section className={`logs-drawer architecture-drawer${open ? "" : " hidden"}`} aria-hidden={open ? "false" : "true"}>
            <div className="logs-backdrop" onClick={onClose} />
            <div className="logs-sheet architecture-sheet">
                <div className="logs-header">
                    <div>
                        <strong>{architecture.copy.headerTitle}</strong>
                        <span className="logs-meta">{architecture.copy.headerMeta}</span>
                    </div>
                    <div className="architecture-language-toggle" aria-label={architecture.copy.languageLabel}>
                        <button
                            className={`tiny-pill${locale === "zh" ? " active" : ""}`}
                            type="button"
                            onClick={() => setLocale("zh")}
                        >
                            {architecture.copy.zh}
                        </button>
                        <button
                            className={`tiny-pill${locale === "en" ? " active" : ""}`}
                            type="button"
                            onClick={() => setLocale("en")}
                        >
                            {architecture.copy.en}
                        </button>
                    </div>
                    <button className="icon-button" type="button" title="关闭项目架构" onClick={onClose}>
                        <i className="fas fa-times" />
                    </button>
                </div>

                <div className="architecture-body">
                    <section className="architecture-hero">
                        <div className="architecture-hero-copy">
                            <span className="architecture-kicker">{architecture.copy.heroKicker}</span>
                            <h3>{architecture.copy.heroTitle}</h3>
                            <p>{architecture.copy.heroBody}</p>
                        </div>
                        <div className="architecture-chip-row">
                            {architecture.summaryChips.map((chip) => (
                                <span key={chip} className="architecture-chip">{chip}</span>
                            ))}
                        </div>
                    </section>

                    <section className="architecture-flowboard" aria-label="Architecture flow diagram">
                        {architecture.flowRows.map((row, index) => (
                            <React.Fragment key={`${row.lane}-${row.title}`}>
                                <div className="architecture-flow-row">
                                    <div className="architecture-flow-lane">{row.lane}</div>
                                    <article className="architecture-flow-card">
                                        <span className="architecture-step-eyebrow">{row.code}</span>
                                        <strong>{row.title}</strong>
                                        <p>{row.detail}</p>
                                        <div className="architecture-meta-row">
                                            {row.tags.map((item) => (
                                                <span key={item} className="architecture-meta-pill">{item}</span>
                                            ))}
                                        </div>
                                    </article>
                                    <aside className="architecture-flow-store">
                                        <span className="architecture-flow-store-label">{row.storeTitle}</span>
                                        <ul className="architecture-flow-store-list">
                                            {row.storeItems.map((item) => (
                                                <li key={item}>{item}</li>
                                            ))}
                                        </ul>
                                    </aside>
                                </div>
                                {index < architecture.flowRows.length - 1 && (
                                    <div className="architecture-flow-connector" aria-hidden="true">
                                        <span />
                                        <i />
                                    </div>
                                )}
                            </React.Fragment>
                        ))}
                    </section>

                    <section className="architecture-prompt-card">
                        <div className="architecture-prompt-head">
                            <div>
                                <span className="architecture-kicker">{architecture.copy.promptKicker}</span>
                                <strong>{architecture.copy.promptTitle}</strong>
                            </div>
                            <span className="architecture-prompt-badge">{architecture.copy.promptBadge}</span>
                        </div>
                        <pre>{architecture.promptPreview}</pre>
                    </section>

                    <section className="architecture-module-grid">
                        {architecture.moduleCards.map((layer) => (
                            <article key={`${layer.title}-${layer.detail}`} className="architecture-module-card">
                                <strong>{layer.title}</strong>
                                <p>{layer.detail}</p>
                                <ul className="architecture-bullet-list">
                                    {layer.bullets.map((item) => (
                                        <li key={item}>{item}</li>
                                    ))}
                                </ul>
                            </article>
                        ))}
                    </section>

                    <section className="architecture-event-strip">
                        <span className="architecture-kicker">{architecture.copy.eventKicker}</span>
                        <div className="architecture-chip-row">
                            {architecture.eventChips.map((chip) => (
                                <span key={chip} className="architecture-chip">{chip}</span>
                            ))}
                        </div>
                    </section>

                    <div className="architecture-list">
                        {architecture.detailCards.map((section) => (
                            <article key={section.title} className="architecture-card">
                                <strong>{section.title}</strong>
                                <p>{section.detail}</p>
                            </article>
                        ))}
                    </div>
                </div>
            </div>
        </section>
    );
}
