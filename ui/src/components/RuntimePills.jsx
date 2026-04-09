import React from "react";
import { shortenModel } from "../lib/formatting.js";

export default function RuntimePills({ mode, setMode, runtime, contextPercent }) {
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
                <span className="runtime-pill">Model · {shortenModel(runtime?.model)}</span>
                <span className="runtime-pill">Context · {contextPercent}%</span>
            </div>
        </section>
    );
}
