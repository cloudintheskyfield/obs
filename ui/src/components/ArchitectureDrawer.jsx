import React from "react";

const ARCHITECTURE_SECTIONS = [
    {
        title: "UI Workbench",
        detail: "React + Vite 控制台，负责会话列表、Thinking、Logs、Skills、Workspace 和模型选择。"
    },
    {
        title: "Streaming Agent",
        detail: "统一处理 system + user 压缩上下文、工具规划、工具执行、最终总结输出。"
    },
    {
        title: "Skill Router",
        detail: "按当前选中的 skill 暴露工具，避免把所有 tool schema 一次性喂给模型。"
    },
    {
        title: "Workspace Runtime",
        detail: "用户可切换工作区，终端、文件和 Python 默认都在当前工作区内执行。"
    },
    {
        title: "Context Memory",
        detail: "会话历史、本地摘要缓存、压缩后的上下文和线程工作目录全部落盘。"
    },
    {
        title: "Traceability",
        detail: "每轮 LLM request / response、SSE 关键事件和运行状态都可在本地日志里追踪。"
    }
];

export default function ArchitectureDrawer({ open, onClose }) {
    return (
        <section className={`logs-drawer architecture-drawer${open ? "" : " hidden"}`} aria-hidden={open ? "false" : "true"}>
            <div className="logs-backdrop" onClick={onClose} />
            <div className="logs-sheet architecture-sheet">
                <div className="logs-header">
                    <div>
                        <strong>Project Architecture</strong>
                        <span className="logs-meta">How OBS Code is structured from UI to runtime.</span>
                    </div>
                    <button className="icon-button" type="button" title="关闭项目架构" onClick={onClose}>
                        <i className="fas fa-times" />
                    </button>
                </div>
                <div className="architecture-list">
                    {ARCHITECTURE_SECTIONS.map((section) => (
                        <article key={section.title} className="architecture-card">
                            <strong>{section.title}</strong>
                            <p>{section.detail}</p>
                        </article>
                    ))}
                </div>
            </div>
        </section>
    );
}
