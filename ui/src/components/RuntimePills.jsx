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
    plan:   { label: "Plan",   icon: "fa-list-check",              tip: "只生成执行计划，不实际运行工具" },
    battle: { label: "Battle", icon: "fa-code-compare",            tip: "多模型并行对比，择优输出" },
    review: { label: "Review", icon: "fa-magnifying-glass-chart",  tip: "通过审查引擎处理，适合代码审核" },
};

export default function RuntimePills({
    mode, setMode,
    contextPercent, contextTokens, contextMaxTokens,
    threadContextPercent, threadContextTokens, threadTurnCount,
    githubUrl, onExport,
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
                        className={`mode-chip${mode === value ? " active" : ""}`}
                        onClick={() => setMode(value)}
                    >
                        <i className={`fas ${meta.icon}`} aria-hidden="true" />
                        <span>{meta.label}</span>
                    </button>
                ))}
            </div>

            {/* ── Centre: context meter ── */}
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
            </div>
        </header>
    );
}
