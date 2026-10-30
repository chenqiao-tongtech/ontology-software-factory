from pathlib import Path
from ontology_software_factory.harness import HarnessBudget

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    budget = HarnessBudget()
    if min(budget.max_tool_calls, budget.max_context_bytes, budget.max_input_tokens, budget.max_output_tokens) <= 0:
        raise SystemExit("Harness default budgets must be positive")
    print("Harness configuration baseline valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
