import React from "react";

const DISPLAY_NAME_MAP = {
    "code-sandbox": "Python",
    "file-operations": "File",
    "terminal": "Terminal",
    "web-search": "Web Search",
    "computer-use": "Computer Use",
    "weather": "Weather"
};

function displayName(skill) {
    return DISPLAY_NAME_MAP[skill.name] || skill.name;
}

export default function SkillsDrawer({
    open,
    skills,
    selectedSkills,
    onToggleAll,
    onToggleSkill,
    onClose
}) {
    const sortedSkills = [...skills].sort((left, right) =>
        displayName(left).localeCompare(displayName(right), "en", { sensitivity: "base" })
    );
    const allSelected = sortedSkills.length > 0 && sortedSkills.every((skill) => selectedSkills.includes(skill.name));

    return (
        <section className={`logs-drawer skills-drawer${open ? "" : " hidden"}`} aria-hidden={open ? "false" : "true"}>
            <div className="logs-backdrop" onClick={onClose} />
            <div className="logs-sheet skills-sheet">
                <div className="logs-header">
                    <div>
                        <strong>Available Skills</strong>
                        <span className="logs-meta">Selected skills are the only ones the model can use.</span>
                    </div>
                    <button className="icon-button" type="button" title="关闭技能面板" onClick={onClose}>
                        <i className="fas fa-times" />
                    </button>
                </div>
                <div className="skills-list">
                    <button
                        type="button"
                        className={`skill-option all${allSelected ? " active" : ""}`}
                        onClick={onToggleAll}
                    >
                        <span className="skill-option-name">All</span>
                        <span className="skill-option-meta">{allSelected ? "Selected" : "Select all"}</span>
                    </button>
                    {sortedSkills.map((skill) => {
                        const active = selectedSkills.includes(skill.name);
                        return (
                            <button
                                key={skill.name}
                                type="button"
                                className={`skill-option${active ? " active" : ""}`}
                                onClick={() => onToggleSkill(skill.name)}
                            >
                                <span className="skill-option-name">{displayName(skill)}</span>
                                <span className="skill-option-meta">{skill.description || skill.name}</span>
                            </button>
                        );
                    })}
                </div>
            </div>
        </section>
    );
}
