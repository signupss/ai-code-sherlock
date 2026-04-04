"""
Skill Registry — loads, stores, and queries agent skills.

Skills come from:
  1. Built-in defaults (BUILTIN_SKILLS in agent_models)
  2. User-created skills (stored in JSON)
  3. Project-specific skills (in .sherlock_versions/skills/)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from services.agent_models import Skill, SkillCategory, BUILTIN_SKILLS


class SkillRegistry:
    """Manages the skill database for AI agents."""

    USER_SKILLS_DIR = ".sherlock_versions/skills"
    USER_SKILLS_FILE = "user_skills.json"

    def __init__(self, project_root: str = ""):
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._skills: dict[str, Skill] = {}
        self._load_builtins()
        self._load_user_skills()

    def _load_builtins(self) -> None:
        for skill in BUILTIN_SKILLS:
            self._skills[skill.id] = skill

    def _load_user_skills(self) -> None:
        skills_file = self._project_root / self.USER_SKILLS_DIR / self.USER_SKILLS_FILE
        if not skills_file.exists():
            return
        try:
            data = json.loads(skills_file.read_text(encoding="utf-8"))
            for item in data:
                skill = Skill.from_dict(item)
                self._skills[skill.id] = skill
        except (json.JSONDecodeError, Exception):
            pass

    def save_user_skills(self) -> None:
        """Save non-builtin skills to disk."""
        builtin_ids = {s.id for s in BUILTIN_SKILLS}
        user_skills = [s.to_dict() for s in self._skills.values()
                       if s.id not in builtin_ids]
        skills_dir = self._project_root / self.USER_SKILLS_DIR
        skills_dir.mkdir(parents=True, exist_ok=True)
        path = skills_dir / self.USER_SKILLS_FILE
        path.write_text(
            json.dumps(user_skills, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Query ────────────────────────────────────────────

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def get_many(self, skill_ids: list[str]) -> list[Skill]:
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def by_category(self, category: SkillCategory) -> list[Skill]:
        return [s for s in self._skills.values() if s.category == category]

    def search(self, query: str) -> list[Skill]:
        q = query.lower()
        return [s for s in self._skills.values()
                if q in s.name.lower() or q in s.description.lower()
                or any(q in t for t in s.tags)]

    # ── CRUD ──────────────────────────────────────────────

    def add(self, skill: Skill) -> None:
        self._skills[skill.id] = skill
        self.save_user_skills()

    def update(self, skill: Skill) -> None:
        self._skills[skill.id] = skill
        self.save_user_skills()

    def remove(self, skill_id: str) -> None:
        builtin_ids = {s.id for s in BUILTIN_SKILLS}
        if skill_id in builtin_ids:
            return  # Don't delete builtins
        self._skills.pop(skill_id, None)
        self.save_user_skills()

    def build_prompt_for_agent(self, skill_ids: list[str]) -> str:
        """Build combined system prompt from multiple skills."""
        skills = self.get_many(skill_ids)
        if not skills:
            return ""
        parts = ["## СКИЛЛЫ АГЕНТА\n"]
        for skill in skills:
            parts.append(f"### {skill.icon} {skill.name}")
            parts.append(f"{skill.description}")
            if skill.system_prompt:
                parts.append(f"Инструкции: {skill.system_prompt}")
            if skill.example_input:
                parts.append(f"Пример входа: {skill.example_input}")
            if skill.example_output:
                parts.append(f"Пример выхода: {skill.example_output}")
            parts.append("")
        return "\n".join(parts)

    def set_project_root(self, root: str) -> None:
        self._project_root = Path(root)
        self._skills.clear()
        self._load_builtins()
        self._load_user_skills()
    
    def load_from_folder(self, folder_path: str) -> list[Skill]:
        """Load skills from any folder (project-specific skills)"""
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return []
        
        loaded = []
        # Load JSON files
        for json_file in folder.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        skill = Skill.from_dict(item)
                        self._skills[skill.id] = skill
                        loaded.append(skill)
                else:
                    skill = Skill.from_dict(data)
                    self._skills[skill.id] = skill
                    loaded.append(skill)
            except Exception as e:
                print(f"Error loading {json_file}: {e}")
        
        # Also check subfolder 'skills' if exists
        skills_subfolder = folder / "skills"
        if skills_subfolder.exists():
            loaded.extend(self.load_from_folder(str(skills_subfolder)))
        
        return loaded
    
    def load_global_skills(self):
        """Загрузить встроенные + глобальные скиллы из папки программы"""
        global_path = Path(__file__).parent.parent / "skills" / "global"
        if global_path.exists():
            self.load_from_folder(str(global_path))
            
    def suggest_skills_for_task(self, task_description: str, model_provider=None) -> list[Skill]:
        """Использовать LLM для рекомендации скиллов под задачу"""
        all_skills = self.all_skills()
        
        prompt = f"""Task: {task_description}
Available skills:
{chr(10).join([f"- {s.id}: {s.name} ({s.category.value}) - {s.description}" for s in all_skills])}

Select skills that would help complete this task. Return only skill IDs, comma separated:"""

        if model_provider:
            response = model_provider.complete(prompt)
            selected_ids = [s.strip() for s in response.split(",")]
            return [self.get(sid) for sid in selected_ids if self.get(sid)]
        
        # Fallback: keyword matching
        keywords = set(task_description.lower().split())
        scored = []
        for skill in all_skills:
            score = len(keywords & set(skill.tags + [skill.category.value]))
            if score > 0:
                scored.append((skill, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:5]]
    
    def update(self, skill: Skill) -> None:
        """Update existing skill"""
        if skill.id in self._skills:
            self._skills[skill.id] = skill
            self.save_user_skills()
