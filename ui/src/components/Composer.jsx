import React from "react";

function renderComposerImages(images) {
    return (images || []).map((image, index) => (
        <span key={image.id} className="composer-image-chip">
            <span className="composer-image-chip-label">{image.name || `Image ${index + 1}`}</span>
            <span className="composer-image-preview">
                <img src={image.dataUrl} alt={image.name || `Image ${index + 1}`} />
            </span>
        </span>
    ));
}

export default function Composer({
    selectedModel,
    availableModels,
    onModelChange,
    permissionMode,
    onPermissionToggle,
    thinkingMode,
    onThinkingToggle,
    value,
    onChange,
    onKeyDown,
    onPaste,
    onSend,
    isSending,
    images,
    logsOpen,
    onLogsToggle,
    skillsOpen,
    onSkillsToggle,
    architectureOpen,
    onArchitectureToggle,
    workspacePath,
    workspaceSummary,
    onWorkspaceOpen,
    statusItems,
    inputRef
}) {
    return (
        <section className="composer-wrap">
            <div className="composer-card">
                <div className="composer-head">
                    <div className="composer-meta">
                        <div className="composer-workspace">
                            <span className="composer-placeholder">Current workspace</span>
                            <strong className="workspace-inline-path">{workspacePath || "No workspace selected"}</strong>
                            <span className="workspace-inline-breadcrumb">Parents · {workspaceSummary}</span>
                        </div>
                        <div className="composer-toggles">
                            <label className="tiny-select-shell" htmlFor="model-select">
                                <span>Model</span>
                                <select id="model-select" className="tiny-select" value={selectedModel} onChange={(event) => onModelChange(event.target.value)}>
                                    {(availableModels || []).map((model) => (
                                        <option key={model} value={model}>{model}</option>
                                    ))}
                                </select>
                            </label>
                            <button className="tiny-pill" type="button" onClick={onPermissionToggle}>
                                Permission · {permissionMode}
                            </button>
                            <button className={`tiny-pill thinking-pill${thinkingMode ? " active" : ""}`} type="button" onClick={onThinkingToggle}>
                                Thinking · {thinkingMode ? "on" : "off"}
                            </button>
                        </div>
                    </div>
                </div>
                {images?.length ? (
                    <div className="composer-rich-preview" aria-hidden="true">
                        {renderComposerImages(images)}
                    </div>
                ) : null}
                <textarea
                    id="message-input"
                    ref={inputRef}
                    rows="1"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onKeyDown={onKeyDown}
                    onPaste={onPaste}
                    placeholder="Describe the task, mention files, or ask for a coordinated refactor"
                />
                <div className="composer-foot">
                    <div className="composer-left">
                        <button className="small-tool workspace-tool active" type="button" onClick={onWorkspaceOpen}>
                            <i className="fas fa-folder-tree" />
                            <span>Workspace</span>
                        </button>
                        <button className={`small-tool${logsOpen ? " active" : ""}`} type="button" onClick={onLogsToggle}>
                            <i className="fas fa-wave-square" />
                            <span>Logs</span>
                        </button>
                        <button className={`small-tool${skillsOpen ? " active" : ""}`} type="button" onClick={onSkillsToggle}>
                            <i className="fas fa-sliders" />
                            <span>Skills</span>
                        </button>
                        <button className={`small-tool${architectureOpen ? " active" : ""}`} type="button" onClick={onArchitectureToggle}>
                            <i className="fas fa-diagram-project" />
                            <span>Architecture</span>
                        </button>
                    </div>
                    <div className="composer-right">
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
