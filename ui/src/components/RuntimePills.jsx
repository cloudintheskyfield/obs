import React from "react";

function formatTokenCount(tokens) {
    const value = Number(tokens) || 0;
    if (value >= 1000) {
        const k = value / 1000;
        return `${k >= 100 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, "")}K`;
    }
    return `${Math.round(value)}`;
}

export default function RuntimePills({
    contextPercent, contextTokens, contextMaxTokens,
    threadContextPercent, threadContextTokens, threadTurnCount,
    githubUrl, onExport,
    previewOpen, onTogglePreview,
    createHubOpen, onToggleCreateHub,
    fileChangeSummary, onFocusFiles,
    themeMode, effectiveTheme, onThemeToggle,
    taskStatus,
}) {
    const workingPct = Math.min(100, Math.max(0, Number(contextPercent) || 0));
    const threadPct = Math.min(100, Math.max(0, Number(threadContextPercent) || 0));
    const threadBarColor = threadPct > 85
        ? "rgba(220, 80, 80, 0.75)"
        : threadPct > 65
        ? "rgba(210, 160, 60, 0.70)"
        : "rgba(217, 201, 171, 0.50)";
    const workingBarColor = workingPct > 85
        ? "rgba(255, 143, 143, 0.92)"
        : workingPct > 65
        ? "rgba(242, 212, 120, 0.95)"
        : "rgba(243, 239, 231, 0.95)";
    const threadPctLabel = threadPct < 0.1 ? "<0.1%" : `${threadPct.toFixed(threadPct >= 10 ? 0 : 1)}%`;
    const workingPctLabel = workingPct < 0.1 ? "<0.1%" : `${workingPct.toFixed(workingPct >= 10 ? 0 : 1)}%`;
    const roundsLabel = threadTurnCount === 1 ? "1 round" : `${threadTurnCount || 0} rounds`;
    const themeIcon = themeMode === "system"
        ? "fa-circle-half-stroke"
        : effectiveTheme === "light"
        ? "fa-sun"
        : "fa-moon";
    const themeLabel = themeMode === "system"
        ? `主题：跟随系统（当前${effectiveTheme === "light" ? "浅色" : "深色"}）`
        : `主题：${effectiveTheme === "light" ? "浅色" : "深色"}`;

    return (
        <header className="unified-bar">
            <div className="mode-chips">
                <span
                    className="mode-chip mode-agent active"
                    title="Unified OBS Agent: Planner -> Search Gate -> Generator -> Runner -> Evaluator harness"
                >
                    <i className="fas fa-robot" aria-hidden="true" />
                    <span>Agent</span>
                </span>
            </div>

            {/* ── Centre: context meter + file changes (dropdown) ── */}
            <div className="unified-bar-context-cluster">
                <div
                    className="context-meter"
                    title={`Current thread: ${formatTokenCount(threadContextTokens)} / ${formatTokenCount(contextMaxTokens)} tokens. Working set sent to the model this turn: ${formatTokenCount(contextTokens)} / ${formatTokenCount(contextMaxTokens)} tokens.`}
                >
                    <div className="context-meter-labels">
                        <span className="context-meter-name">Context</span>
                        <span className="context-meter-value">
                            {formatTokenCount(threadContextTokens)} / 
                            {formatTokenCount(contextMaxTokens)}
                            <em>{threadPctLabel}</em>
                        </span>
                    </div>
                    <div className="context-meter-track">
                        <div className="context-meter-fill context-meter-fill-thread" style={{ width: `${threadPct}%`, background: threadBarColor }} />
                        <div className="context-meter-fill context-meter-fill-working" style={{ width: `${workingPct}%`, background: workingBarColor }} />
                    </div>
                    <div className="context-meter-meta">
                        <span>Current thread · {roundsLabel}</span>
                        <span>Working set · {formatTokenCount(contextTokens)} · {workingPctLabel}</span>
                    </div>
                </div>

                {onToggleCreateHub ? (
                    <button
                        type="button"
                        className={`create-hub-link${createHubOpen ? " active" : ""}`}
                        title="打开 Create Hub 的发布、发现和排行榜"
                        onClick={onToggleCreateHub}
                        aria-expanded={Boolean(createHubOpen)}
                    >
                        <i className="fas fa-compass" aria-hidden="true" />
                        <span>Create Hub</span>
                    </button>
                ) : null}

	                {fileChangeSummary?.visible ? (
	                    <details className="files-changed-dropdown">
                        <summary
                            className="files-changed-dropdown-summary"
                            title={`${fileChangeSummary.changedFiles} files changed — 点击展开列表`}
                        >
                            <span className="files-changed-dropdown-label">
                                {fileChangeSummary.changedFiles} files
                            </span>
                            <span className="files-changed-dropdown-stats">
                                <em>+{fileChangeSummary.insertions}</em>
                                <strong>-{fileChangeSummary.deletions}</strong>
                            </span>
                            <i className="fas fa-chevron-down files-changed-dropdown-chevron" aria-hidden="true" />
                        </summary>
                        <div className="files-changed-dropdown-panel">
                            {(fileChangeSummary.files || []).length > 0 ? (
                                <ul className="files-changed-dropdown-list">
                                    {(fileChangeSummary.files || []).slice(0, 40).map((file) => (
                                        <li key={file.path} className="files-changed-dropdown-row">
                                            <span className="files-changed-dropdown-status">{String(file.status || "").trim() || "M"}</span>
                                            <span className="files-changed-dropdown-path" title={file.path}>{file.path}</span>
                                            <span className="files-changed-dropdown-delta">
                                                {file.insertions || file.deletions
                                                    ? `+${file.insertions || 0} -${file.deletions || 0}`
                                                    : "untracked"}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="files-changed-dropdown-empty">暂无逐文件明细（仅汇总统计）。</p>
                            )}
                            {onFocusFiles ? (
                                <button
                                    type="button"
                                    className="files-changed-dropdown-open-preview"
                                    onClick={(event) => {
                                        event.preventDefault();
                                        onFocusFiles();
                                    }}
                                >
                                    打开右侧预览
                                </button>
                            ) : null}
                        </div>
	                    </details>
	                ) : null}

	                {taskStatus ? (
	                    <span className={`workspace-status-pill ${taskStatus.status || "idle"}`} title={taskStatus.subtitle || ""}>
	                        <i
	                            className={`fas ${
	                                taskStatus.status === "done"
	                                    ? "fa-check"
	                                    : taskStatus.status === "blocked"
	                                    ? "fa-triangle-exclamation"
	                                    : taskStatus.status === "running"
	                                    ? "fa-spinner fa-spin"
	                                    : "fa-circle"
	                            }`}
	                            aria-hidden="true"
	                        />
	                        <span>{taskStatus.label || "Idle"}</span>
	                        {taskStatus.duration ? <em>{taskStatus.duration}</em> : null}
	                    </span>
	                ) : null}
	            </div>

            {/* ── Right: icon actions ── */}
            <div className="unified-bar-actions">
                {onThemeToggle ? (
                    <button
                        className={`icon-button theme-toggle-button${themeMode !== "system" ? " active" : ""}`}
                        type="button"
                        title={`${themeLabel} · 点击切换 system / light / dark`}
                        onClick={onThemeToggle}
                        aria-label={themeLabel}
                    >
                        <i className={`fas ${themeIcon}`} />
                    </button>
                ) : null}
                {githubUrl && (
                    <a className="icon-button" href={githubUrl} target="_blank" rel="noreferrer noopener" title="Open GitHub repository">
                        <i className="fab fa-github" />
                    </a>
                )}
                {onExport && (
                    <button className="icon-button" type="button" title="导出会话" onClick={onExport}>
                        <i className="fas fa-download" />
                    </button>
                )}
                <button
                    className={`icon-button${previewOpen ? " active" : ""}`}
                    type="button"
                    title={previewOpen ? "恢复全屏编辑" : "打开右侧预览"}
                    onClick={onTogglePreview}
                >
                    <i className={`fas ${previewOpen ? "fa-pen-ruler" : "fa-up-right-and-down-left-from-center"}`} />
                </button>
            </div>
        </header>
    );
}
