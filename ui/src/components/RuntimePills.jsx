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
    githubUrl, onExport,
}) {
    const pct = Math.min(100, Math.max(0, Number(contextPercent) || 0));
    const barColor = pct > 85
        ? "rgba(220, 80, 80, 0.75)"
        : pct > 65
        ? "rgba(210, 160, 60, 0.70)"
        : "rgba(217, 201, 171, 0.50)";
    const pctLabel = pct < 0.1 ? "<0.1%" : `${pct.toFixed(pct >= 10 ? 0 : 1)}%`;

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
                title={`Context: ${formatTokenCount(contextTokens)} / ${formatTokenCount(contextMaxTokens)} tokens`}
            >
                <div className="context-meter-labels">
                    <span className="context-meter-name">Context</span>
                    <span className="context-meter-value">
                        {contextTokens > 0 ? `${formatTokenCount(contextTokens)} / ` : ""}
                        {formatTokenCount(contextMaxTokens)}
                        <em>{pctLabel}</em>
                    </span>
                </div>
                <div className="context-meter-track">
                    <div className="context-meter-fill" style={{ width: `${pct}%`, background: barColor }} />
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
