"""
Skill Loader - Load Claude Code Skills from .claude/skills directory
"""
import os
import sys
import importlib.util
from pathlib import Path
from typing import Dict, Optional, Any, Type
import re
from loguru import logger


class SkillDefinition:
    """Claude Code Skill definition loaded from SKILL.md"""
    
    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        skill_dir: Path,
        skill_class: Optional[Type] = None
    ):
        self.name = name
        self.description = description
        self.instructions = instructions
        self.skill_dir = skill_dir
        self.skill_class = skill_class
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "skill_dir": str(self.skill_dir),
            "has_implementation": self.skill_class is not None
        }


class SkillLoader:
    """
    Load Claude Code Skills from .claude/skills directory
    
    Skills follow three-level structure:
    - Level 1: Metadata (YAML frontmatter - always loaded)
    - Level 2: Instructions (Markdown content - loaded when triggered)
    - Level 3: Resources (additional files - loaded as needed)
    """
    
    def __init__(self, skills_root: Optional[Path] = None):
        if skills_root is not None:
            self.skills_root = Path(skills_root)
        else:
            self.skills_root = self._resolve_default_skills_root()
        
        self.skills: Dict[str, SkillDefinition] = {}

    @staticmethod
    def _find_upwards(start_dir: Path, relative_path: Path) -> Optional[Path]:
        for base in [start_dir, *start_dir.parents]:
            candidate = base / relative_path
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def _resolve_default_skills_root(self) -> Path:
        env_override = os.getenv("SKILLS_DIR")
        if env_override:
            return Path(env_override)

        rel = Path(".claude") / "skills"

        from_cwd = self._find_upwards(Path.cwd(), rel)
        if from_cwd:
            return from_cwd

        from_module = self._find_upwards(Path(__file__).resolve().parent, rel)
        if from_module:
            return from_module

        return Path.cwd() / rel
        
    def load_all_skills(self) -> Dict[str, SkillDefinition]:
        """Load all skills from .claude/skills directory"""
        if not self.skills_root.exists():
            logger.warning(f"Skills directory not found: {self.skills_root}")
            return {}
        
        for skill_dir in self.skills_root.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    try:
                        skill = self._load_skill_file(skill_file, skill_dir)
                        if skill:
                            # 尝试加载Python实现 (Level 3)
                            skill_class = self._load_skill_implementation(skill_dir, skill.name)
                            if skill_class:
                                skill.skill_class = skill_class
                                logger.info(f"Loaded skill with implementation: {skill.name}")
                            else:
                                logger.info(f"Loaded skill definition only: {skill.name}")
                            
                            self.skills[skill.name] = skill
                    except Exception as e:
                        logger.error(f"Failed to load skill from {skill_file}: {e}")
        
        logger.info(f"Loaded {len(self.skills)} skills from {self.skills_root}")
        return self.skills
    
    def _load_skill_file(
        self,
        skill_file: Path,
        skill_dir: Path
    ) -> Optional[SkillDefinition]:
        """
        Load a single SKILL.md file
        
        Format:
        ---
        name: skill-name
        description: Brief description
        ---
        
        # Detailed Instructions
        ...
        """
        content = skill_file.read_text(encoding="utf-8")
        content = content.lstrip("\ufeff")

        frontmatter_match = re.match(
            r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$",
            content,
            re.DOTALL,
        )
        
        if not frontmatter_match:
            logger.warning(f"No frontmatter found in {skill_file}")
            return None
        
        frontmatter = frontmatter_match.group(1)
        instructions = frontmatter_match.group(2).strip()
        
        name = None
        description = None
        
        for raw_line in re.split(r"\r?\n", frontmatter):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            key, sep, value = line.partition(":")
            if not sep:
                continue

            key = key.strip()
            value = value.strip()

            if key == "name":
                name = value
            elif key == "description":
                description = value
        
        if not name or not description:
            logger.warning(f"Missing name or description in {skill_file}")
            return None
        
        return SkillDefinition(
            name=name,
            description=description,
            instructions=instructions,
            skill_dir=skill_dir
        )
    
    def _load_skill_implementation(self, skill_dir: Path, skill_name: str) -> Optional[Type]:
        """
        Load Level 3 Python implementation from skill directory
        
        Looks for Python files and tries to find skill class implementations
        """
        # 映射skill名称到可能的Python文件名
        filename_candidates = [
            f"{skill_name.replace('-', '_')}.py",
            "computer_use.py" if skill_name == "computer-use" else None,
            "text_editor.py" if skill_name == "file-operations" else None,
            "bash.py" if skill_name == "terminal" else None,
        ]
        
        # 移除None值
        filename_candidates = [f for f in filename_candidates if f]
        
        for filename in filename_candidates:
            py_file = skill_dir / filename
            if py_file.exists():
                try:
                    # 动态加载Python模块
                    spec = importlib.util.spec_from_file_location(
                        f"skill_{skill_name.replace('-', '_')}", 
                        py_file
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        
                        # 添加到sys.modules以避免重复加载
                        sys.modules[spec.name] = module
                        
                        spec.loader.exec_module(module)
                        
                        # 查找skill类
                        skill_class = self._find_skill_class(module, skill_name)
                        if skill_class:
                            logger.info(f"Loaded Python implementation: {py_file}")
                            return skill_class
                        
                except Exception as e:
                    logger.error(f"Failed to load Python file {py_file}: {e}")
                    continue
        
        return None
    
    def _find_skill_class(self, module: Any, skill_name: str) -> Optional[Type]:
        """从模块中查找skill类"""
        # 常见的skill类名模式
        class_candidates = [
            "ComputerUseSkill" if skill_name == "computer-use" else None,
            "TextEditorSkill" if skill_name == "file-operations" else None,
            "BashSkill" if skill_name == "terminal" else None,
        ]
        
        # 移除None值并添加通用模式
        class_candidates = [c for c in class_candidates if c]
        class_candidates.extend([
            f"{skill_name.replace('-', ' ').title().replace(' ', '')}Skill",
            f"{skill_name.replace('-', '_').title()}Skill"
        ])
        
        for class_name in class_candidates:
            if hasattr(module, class_name):
                skill_class = getattr(module, class_name)
                # 验证这是一个有效的skill类
                if hasattr(skill_class, 'execute') and callable(getattr(skill_class, 'execute')):
                    return skill_class
        
        # 如果找不到特定名称，查找所有包含"Skill"的类
        for attr_name in dir(module):
            if attr_name.endswith('Skill') and not attr_name.startswith('_'):
                skill_class = getattr(module, attr_name)
                if hasattr(skill_class, 'execute') and callable(getattr(skill_class, 'execute')):
                    return skill_class
        
        return None
    
    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Get a specific skill by name"""
        return self.skills.get(name)
    
    def get_all_skill_metadata(self) -> Dict[str, Dict[str, str]]:
        """
        Get Level 1 metadata for all skills
        (name and description only - lightweight for context)
        """
        return {
            name: {
                "name": skill.name,
                "description": skill.description
            }
            for name, skill in self.skills.items()
        }
    
    def get_skill_instructions(self, name: str) -> Optional[str]:
        """
        Get Level 2 instructions for a specific skill
        (loaded when skill is triggered)
        """
        skill = self.get_skill(name)
        return skill.instructions if skill else None
    
    def create_skill_instance(self, name: str, **kwargs) -> Optional[Any]:
        """
        Create Level 3 skill instance from loaded class
        """
        skill = self.get_skill(name)
        if skill and skill.skill_class:
            try:
                return skill.skill_class(**kwargs)
            except Exception as e:
                logger.error(f"Failed to create skill instance {name}: {e}")
                return None
        return None
