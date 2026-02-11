"""
Skill Loader - Load Claude Code Skills from .claude/skills directory
"""
from pathlib import Path
from typing import Dict, Optional
import re
from loguru import logger


class SkillDefinition:
    """Claude Code Skill definition loaded from SKILL.md"""
    
    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        skill_dir: Path
    ):
        self.name = name
        self.description = description
        self.instructions = instructions
        self.skill_dir = skill_dir
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary representation"""
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "skill_dir": str(self.skill_dir)
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
        if skills_root is None:
            self.skills_root = Path.cwd() / ".claude" / "skills"
        else:
            self.skills_root = Path(skills_root)
        
        self.skills: Dict[str, SkillDefinition] = {}
        
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
                            self.skills[skill.name] = skill
                            logger.info(f"Loaded skill: {skill.name}")
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
        content = skill_file.read_text(encoding='utf-8')
        
        frontmatter_match = re.match(
            r'^---\s*\n(.*?)\n---\s*\n(.*)$',
            content,
            re.DOTALL
        )
        
        if not frontmatter_match:
            logger.warning(f"No frontmatter found in {skill_file}")
            return None
        
        frontmatter = frontmatter_match.group(1)
        instructions = frontmatter_match.group(2).strip()
        
        name = None
        description = None
        
        for line in frontmatter.split('\n'):
            line = line.strip()
            if line.startswith('name:'):
                name = line.split(':', 1)[1].strip()
            elif line.startswith('description:'):
                description = line.split(':', 1)[1].strip()
        
        if not name or not description:
            logger.warning(f"Missing name or description in {skill_file}")
            return None
        
        return SkillDefinition(
            name=name,
            description=description,
            instructions=instructions,
            skill_dir=skill_dir
        )
    
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
