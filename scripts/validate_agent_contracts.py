#!/usr/bin/env python3
"""Validate Agent roles, Skills, tools, context policies, and sample handoffs."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ontology_software_factory.agent_contracts import main_validation_summary  # noqa: E402

def main() -> int:
    errors,stats=main_validation_summary(ROOT)
    if errors:
        print(f"Agent contract validation FAILED ({len(errors)} issue(s))")
        for error in errors: print(f"- {error}")
        return 1
    print("Agent contract validation: PASS")
    print(f"Roles: {stats['roles']}; Skills: {stats['skills']}; tool definitions: {stats['tools']}")
    print("Validated: role/Skill references, tool allowlists, global deny policy, context scopes, task/result handoff examples.")
    print("NOTE: this validates configuration contracts; it does not run LLM agents or enforce runtime IAM by itself.")
    return 0
if __name__=="__main__": raise SystemExit(main())
