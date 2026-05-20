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
    statusItems,
    inputRef,
    placeholder
}) {
    // 动态构建模型选项
    const modelOptions = [];
    (availableModels || []).forEach(model => {
        // 对于MiniMax-M2我们额外提供一个thinking选项
        if (model.toLowerCase().includes("minimax")) {
            modelOptions.push({ value: `${model}-thinking`, label: `${model} (thinking)` });
            modelOptions.push({ value: model, label: model });
        } else {
            modelOptions.push({ value: model, label: model });
        }
    });

    // 如果没有任何可用模型，给一个默认的选项防止崩溃
    if (modelOptions.length === 0) {
        modelOptions.push({ value: "minimax-m2", label: "MiniMax-M2" });
        if (selectedModel === "minimax-m2") {
            modelOptions.push({ value: "minimax-m2-thinking", label: "MiniMax-M2 (thinking)" });
        }
    }
    
    // 根据当前模型和thinking状态确定选中的选项
    const getCurrentOption = () => {
        if (!selectedModel) return modelOptions[0]?.value || "minimax-m2";
        
        // 如果当前选中的模型支持thinking并且开启了thinking，找到对应的选项
        if (thinkingMode && selectedModel.toLowerCase().includes("minimax")) {
            const thinkingOpt = `${selectedModel}-thinking`;
            if (modelOptions.some(opt => opt.value === thinkingOpt)) {
                return thinkingOpt;
            }
        }
        
        // 否则返回原模型名称
        if (modelOptions.some(opt => opt.value === selectedModel)) {
            return selectedModel;
        }
        
        return modelOptions[0]?.value || "minimax-m2";
    };
    
    // 处理选项变化
    const handleOptionChange = (value) => {
        // 判断是否是 thinking 组合项
        const isThinkingVariant = value.endsWith("-thinking");
        const actualModel = isThinkingVariant ? value.replace("-thinking", "") : value;
        
        onModelChange(actualModel);
        
        if (isThinkingVariant) {
            if (!thinkingMode) onThinkingToggle();
        } else {
            if (thinkingMode) onThinkingToggle();
        }
    };
    
    return (
        <section className="composer-wrap">
            <div className="composer-card">
                <div className="composer-head">
                    <div className="composer-meta">
                        <div className="composer-toggles">
                            <select 
                                id="model-select" 
                                className="model-pill-select" 
                                value={getCurrentOption()} 
                                onChange={(event) => handleOptionChange(event.target.value)}
                            >
                                {modelOptions.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                            </select>
                            <button className="tiny-pill" type="button" onClick={onPermissionToggle}>
                                Permission · {permissionMode}
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
                    placeholder={placeholder || "Describe the task, mention files, or ask for a coordinated refactor"}
                />
                <div className="composer-foot">
                    <div className="composer-left">
                        <button className={`small-tool${logsOpen ? " active" : ""}`} type="button" onClick={onLogsToggle}>
                            <i className="fas fa-wave-square" />
                            <span>Debug</span>
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
