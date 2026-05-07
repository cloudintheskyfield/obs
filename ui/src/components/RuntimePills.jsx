import React from "react";

function formatTokenCount(tokens) {
    const value = Number(tokens) || 0;
    if (value >= 1000) {
        const k = value / 1000;
        return `${k >= 100 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, "")}K`;
    }
    return `${Math.round(value)}`;
}

const MODE_META = {
    agent:  { label: "Agent",  icon: "fa-robot",                   tip: "全自动工具调用，直接执行任务" },
    create: { label: "Create", icon: "fa-wand-magic-sparkles",     tip: "一句话生成可运行的前后端应用" },
    plan:   { label: "Plan",   icon: "fa-list-check",              tip: "只生成执行计划，不实际运行工具" },
    battle: { label: "Battle", icon: "fa-code-compare",            tip: "多模型并行对比，择优输出" },
    review: { label: "Review", icon: "fa-magnifying-glass-chart",  tip: "通过审查引擎处理，适合代码审核" },
};

export default function RuntimePills({
    mode, setMode,
    contextPercent, contextTokens, contextMaxTokens,
    threadContextPercent, threadContextTokens, threadTurnCount,
    githubUrl, onExport,
    previewOpen, onTogglePreview,
    fileChangeSummary, onFocusFiles,
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

    return (
        <header className="unified-bar">
            {/* ── Left: mode chips ── */}
            <div className="mode-chips">
                {Object.entries(MODE_META).map(([value, meta]) => (
                    <button
                        key={value}
                        type="button"
                        title={meta.tip}
                        className={`mode-chip mode-${value}${mode === value ? " active" : ""}`}
                        onClick={() => setMode(value)}
                    >
                        <i className={`fas ${meta.icon}`} aria-hidden="true" />
                        <span>{meta.label}</span>
                    </button>
                ))}
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
                                    在右侧打开预览与完整列表
                                </button>
                            ) : null}
                        </div>
                    </details>
                ) : null}
            </div>

            {/* ── Right: icon actions ── */}
            <div className="unified-bar-actions">
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
