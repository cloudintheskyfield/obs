import React from "react";
import { shortenModel } from "../lib/formatting.js";

const TOOL_CONTEXTS = [
    ["computer", "fas fa-desktop", "Computer"],
    ["workspace", "fas fa-folder-tree", "Workspace"],
    ["agents", "fas fa-diagram-project", "Agents"]
];

export default function Composer({
    toolContext,
    onToolContextChange,
    permissionMode,
    onPermissionToggle,
    thinkingMode,
    onThinkingToggle,
    value,
    onChange,
    onKeyDown,
    onSend,
    isSending,
    runtime,
    logsOpen,
    onLogsToggle,
    skillsOpen,
    onSkillsToggle,
    statusItems,
    inputRef
}) {
    return (
        <section className="composer-wrap">
            <div className="composer-card">
                <div className="composer-head">
                    <div className="composer-meta">
                        <span className="composer-placeholder">
                            {toolContext === "computer"
                                ? "Use the computer context to inspect screenshots, browsers, and visual flows"
                                : toolContext === "agents"
                                    ? "Ask OBS to coordinate sub-tasks, review architecture, or manage execution flow"
                                    : "Describe files, directories, or code paths you want OBS to inspect"}
                        </span>
                        <div className="composer-toggles">
                            <button className="tiny-pill" type="button" onClick={onPermissionToggle}>
                                Permission · {permissionMode}
                            </button>
                            <button className={`tiny-pill${thinkingMode ? " active" : ""}`} type="button" onClick={onThinkingToggle}>
                                Thinking · {thinkingMode ? "on" : "off"}
                            </button>
                        </div>
                    </div>
                </div>
                <textarea
                    ref={inputRef}
                    rows="1"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder="Describe the task, mention files, or ask for a coordinated refactor"
                />
                <div className="composer-foot">
                    <div className="composer-left">
                        {TOOL_CONTEXTS.map(([context, icon, label]) => (
                            <button
                                key={context}
                                className={`small-tool${toolContext === context ? " active" : ""}`}
                                type="button"
                                onClick={() => onToolContextChange(context)}
                            >
                                <i className={icon} />
                                <span>{label}</span>
                            </button>
                        ))}
                        <button className={`small-tool${logsOpen ? " active" : ""}`} type="button" onClick={onLogsToggle}>
                            <i className="fas fa-wave-square" />
                            <span>Logs</span>
                        </button>
                        <button className={`small-tool${skillsOpen ? " active" : ""}`} type="button" onClick={onSkillsToggle}>
                            <i className="fas fa-sliders" />
                            <span>Skills</span>
                        </button>
                    </div>
                    <div className="composer-right">
                        <span className="model-badge">{shortenModel(runtime?.model)}</span>
                        <button className={`send-btn${isSending ? " is-sending" : ""}`} type="button" onClick={onSend} disabled={isSending}>
                            <i className={`fas ${isSending ? "fa-spinner fa-spin" : "fa-arrow-up"}`} />
                        </button>
                    </div>
                </div>
            </div>

            <div className="statusline">
                <div className="statusline-group">
                    {statusItems.map((item) => (
                        <span key={item} className="status-item">{item}</span>
                    ))}
                </div>
            </div>
        </section>
    );
}
