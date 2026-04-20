import React from "react";

function renderComposerImages(images, onRemoveImage) {
    return (images || []).map((image, index) => (
        <div key={image.id} className="composer-image-item">
            <button
                type="button"
                className="composer-image-remove"
                onClick={() => onRemoveImage?.(image.id)}
                aria-label={`Delete ${image.name || `image ${index + 1}`}`}
            >
                <i className="fas fa-times" aria-hidden="true" />
            </button>
            <div className="message-image-chip composer-image-chip">
                {image.dataUrl ? (
                    <img
                        src={image.dataUrl}
                        alt={image.name || `Image ${index + 1}`}
                        className="message-image-thumb composer-image-thumb"
                    />
                ) : (
                    <i className="fas fa-image" aria-hidden="true" />
                )}
                <span className="message-image-chip-name">{image.name || `Image ${index + 1}`}</span>
            </div>
            <span className="composer-image-preview">
                <img src={image.dataUrl} alt={image.name || `Image ${index + 1}`} />
            </span>
        </div>
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
    onChange,
    onKeyDown,
    onPaste,
    onSend,
    onStop,
    isSending,
    images,
    onRemoveImage,
    logsOpen,
    onLogsToggle,
    skillsOpen,
    onSkillsToggle,
    architectureOpen,
    onArchitectureToggle,
    workspacePath,
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
                            <strong className="workspace-inline-path">{workspacePath || "No workspace selected"}</strong>
                        </div>
                        <div className="composer-toggles">
                            <select id="model-select" className="model-pill-select" value={selectedModel} onChange={(event) => onModelChange(event.target.value)}>
                                {(availableModels || []).map((model) => (
                                    <option key={model} value={model}>{model}</option>
                                ))}
                            </select>
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
                    <div className="composer-rich-preview">
                        {renderComposerImages(images, onRemoveImage)}
                    </div>
                ) : null}
                <textarea
                    id="message-input"
                    ref={inputRef}
                    rows="1"
                    defaultValue=""
                    onChange={onChange}
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
                        {isSending ? (
                            <button className="send-btn stop-btn" type="button" onClick={onStop} title="Stop generation">
                                <i className="fas fa-stop" />
                            </button>
                        ) : (
                            <button className="send-btn" type="button" onClick={onSend}>
                                <i className="fas fa-arrow-up" />
                            </button>
                        )}
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
