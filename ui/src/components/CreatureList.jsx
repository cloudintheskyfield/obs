import React, { useState, useEffect } from "react";

/**
 * Creature 产物列表组件
 * 显示当前 session 的所有产物，支持启动/停止/预览
 */
export default function CreatureList({
    sessionId,
    apiUrl,
    onPreview,
    onError
}) {
    const [creatures, setCreatures] = useState([]);
    const [loading, setLoading] = useState(false);
    const [starting, setStarting] = useState({});

    // 获取产物列表
    const fetchCreatures = async () => {
        if (!sessionId) return;
        
        try {
            const response = await fetch(`${apiUrl}/api/creatures/session/${sessionId}`);
            const data = await response.json();
            
            if (data.success) {
                setCreatures(data.creatures || []);
            }
        } catch (error) {
            console.error("Error fetching creatures:", error);
        }
    };

    // 启动产物
    const handleStart = async (creatureName) => {
        setStarting(prev => ({ ...prev, [creatureName]: true }));
        
        try {
            const response = await fetch(`${apiUrl}/api/creatures/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: sessionId,
                    creature_name: creatureName
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // 更新状态
                await fetchCreatures();
                
                // 打开预览
                if (result.preview_url && onPreview) {
                    onPreview(result.preview_url);
                }
            } else {
                if (onError) {
                    onError(`启动失败: ${result.error}`);
                }
            }
        } catch (error) {
            console.error("Error starting creature:", error);
            if (onError) {
                onError(`启动失败: ${error.message}`);
            }
        } finally {
            setStarting(prev => ({ ...prev, [creatureName]: false }));
        }
    };

    // 停止产物
    const handleStop = async (creatureName) => {
        try {
            const response = await fetch(`${apiUrl}/api/creatures/stop`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    creature_name: creatureName
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // 更新状态
                await fetchCreatures();
            } else {
                if (onError) {
                    onError(`停止失败: ${result.error}`);
                }
            }
        } catch (error) {
            console.error("Error stopping creature:", error);
            if (onError) {
                onError(`停止失败: ${error.message}`);
            }
        }
    };

    // 预览产物
    const handlePreview = (creature) => {
        if (onPreview && creature.preview_url) {
            onPreview(creature.preview_url);
        }
    };

    // 定期刷新产物列表
    useEffect(() => {
        fetchCreatures();
        
        const interval = setInterval(fetchCreatures, 5000); // 每 5 秒刷新
        
        return () => clearInterval(interval);
    }, [sessionId]);

    if (!sessionId) {
        return (
            <div className="creature-list-empty">
                <p>请先创建一个 session</p>
            </div>
        );
    }

    if (creatures.length === 0) {
        return (
            <div className="creature-list-empty">
                <i className="fas fa-box-open" style={{ fontSize: "2rem", color: "#9ca3af", marginBottom: "0.5rem" }} />
                <p>暂无产物</p>
                <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                    创建游戏、网页或应用后会显示在这里
                </p>
            </div>
        );
    }

    return (
        <div className="creature-list">
            <div className="creature-list-header">
                <h3>
                    <i className="fas fa-cube" /> 产物列表
                </h3>
                <span className="creature-count">{creatures.length}</span>
            </div>
            
            <div className="creature-items">
                {creatures.map((creature) => (
                    <div key={creature.name} className="creature-item">
                        <div className="creature-info">
                            <div className="creature-name">
                                {getCreatureIcon(creature.type)}
                                <span>{creature.name}</span>
                            </div>
                            
                            {creature.description && (
                                <div className="creature-description">
                                    {creature.description}
                                </div>
                            )}
                            
                            <div className="creature-meta">
                                <span className="creature-type">{getTypeLabel(creature.type)}</span>
                                <span className="creature-port">:{creature.port}</span>
                                <span className={`creature-status creature-status-${creature.status}`}>
                                    {getStatusLabel(creature.status)}
                                </span>
                            </div>
                        </div>
                        
                        <div className="creature-actions">
                            {creature.status === "running" ? (
                                <>
                                    <button
                                        className="creature-btn creature-btn-preview"
                                        onClick={() => handlePreview(creature)}
                                        title="预览"
                                    >
                                        <i className="fas fa-eye" />
                                    </button>
                                    <button
                                        className="creature-btn creature-btn-stop"
                                        onClick={() => handleStop(creature.name)}
                                        title="停止"
                                    >
                                        <i className="fas fa-stop" />
                                    </button>
                                </>
                            ) : (
                                <button
                                    className="creature-btn creature-btn-start"
                                    onClick={() => handleStart(creature.name)}
                                    disabled={starting[creature.name]}
                                    title="启动"
                                >
                                    {starting[creature.name] ? (
                                        <i className="fas fa-spinner fa-spin" />
                                    ) : (
                                        <i className="fas fa-play" />
                                    )}
                                </button>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

// 辅助函数

function getCreatureIcon(type) {
    const icons = {
        html: "🌐",
        react: "⚛️",
        python: "🐍",
        node: "📗"
    };
    return <span className="creature-icon">{icons[type] || "📦"}</span>;
}

function getTypeLabel(type) {
    const labels = {
        html: "HTML",
        react: "React",
        python: "Python",
        node: "Node.js"
    };
    return labels[type] || type;
}

function getStatusLabel(status) {
    const labels = {
        ready: "就绪",
        running: "运行中",
        stopped: "已停止"
    };
    return labels[status] || status;
}
