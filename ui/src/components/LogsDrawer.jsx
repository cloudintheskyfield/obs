import React from "react";

const LOG_RANGE_OPTIONS = [
    ["all", "All"],
    ["15m", "Last 15m"],
    ["1h", "Last 1h"],
    ["24h", "Last 24h"],
    ["custom", "Custom"]
];

export default function LogsDrawer({
    open,
    logRange,
    setLogRange,
    logsFrom,
    setLogsFrom,
    logsTo,
    setLogsTo,
    onRefresh,
    onClose,
    logs
}) {
    return (
        <section id="logs-drawer" className={`logs-drawer${open ? "" : " hidden"}`} aria-hidden={open ? "false" : "true"}>
            <div className="logs-backdrop" onClick={onClose} />
            <div className="logs-sheet">
                <div className="logs-header">
                    <div>
                        <strong>LLM Logs</strong>
                        <span className="logs-meta">Structured request / response events</span>
                    </div>
                    <div className="logs-filters">
                        <select className="mode-select logs-range-select" value={logRange} onChange={(event) => setLogRange(event.target.value || "all")}>
                            {LOG_RANGE_OPTIONS.map(([value, label]) => (
                                <option key={value} value={value}>{label}</option>
                            ))}
                        </select>
                        {logRange === "custom" ? (
                            <>
                                <input className="logs-time-input" type="datetime-local" value={logsFrom} onChange={(event) => setLogsFrom(event.target.value)} />
                                <input className="logs-time-input" type="datetime-local" value={logsTo} onChange={(event) => setLogsTo(event.target.value)} />
                            </>
                        ) : null}
                        <button className="tiny-pill" type="button" onClick={onRefresh}>Refresh</button>
                    </div>
                    <button className="icon-button" type="button" title="关闭日志" onClick={onClose}>
                        <i className="fas fa-times" />
                    </button>
                </div>
                <div className="logs-list">
                    {logs.length === 0 ? (
                        <p className="panel-empty">No LLM logs yet.</p>
                    ) : (
                        logs.map((entry) => {
                            const title = [entry.type, entry.phase, entry.direction].filter(Boolean).join(" · ");
                            return (
                                <article key={entry.id} className="log-entry">
                                    <div className="log-entry-head">
                                        <strong>{title || "log"}</strong>
                                        <span>{new Date(entry.timestamp || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                                    </div>
                                    <pre className="log-entry-body"><code>{JSON.stringify(entry.payload || {}, null, 2)}</code></pre>
                                </article>
                            );
                        })
                    )}
                </div>
            </div>
        </section>
    );
}
