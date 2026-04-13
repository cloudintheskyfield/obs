import React from "react";

function formatTokenCount(tokens) {
    const value = Number(tokens) || 0;
    if (value >= 1000) {
        const kiloValue = value / 1000;
        return `${kiloValue >= 100 ? Math.round(kiloValue) : kiloValue.toFixed(1).replace(/\.0$/, "")}K`;
    }
    return `${Math.round(value)}`;
}

export default function RuntimePills({ mode, setMode, contextPercent, contextTokens, contextMaxTokens }) {
    return (
        <section className="modebar">
            <div className="mode-selector">
                <label className="mode-selector-label" htmlFor="mode-select">Mode</label>
                <select id="mode-select" className="mode-select" value={mode} onChange={(event) => setMode(event.target.value || "agent")}>
                    <option value="agent">Agent</option>
                    <option value="plan">Plan</option>
                    <option value="review">Review</option>
                </select>
            </div>
            <div className="runtime-pills">
                <span className="runtime-pill">
                    Context · {formatTokenCount(contextMaxTokens)} · {contextPercent}%
                </span>
            </div>
        </section>
    );
}
