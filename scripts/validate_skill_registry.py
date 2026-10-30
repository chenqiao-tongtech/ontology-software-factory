from pathlib import Path
from ontology_software_factory.skill_registry import SkillRegistry

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    registry = SkillRegistry(ROOT)
    skills = registry.list_skills()
    print(f"Skill registry valid: {len(skills)} Skills")
    for item in skills:
        print(f"- {item.skill_id}@{item.version} [{item.digest[:12]}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
