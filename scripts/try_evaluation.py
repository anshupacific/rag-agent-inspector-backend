"""Ask the agent one question, score that answer with Foundry's evaluators, and time it.

    python -m scripts.try_evaluation "What is the currency of the US?"
    python -m scripts.try_evaluation "What is the capital of Peru?" --raw

Run from the backend folder after `az login`. Use this before wiring the UI:
it shows how long one evaluation takes and exactly what Foundry returns.
"""

import argparse
import json
import time

from app.agent import agent_client
from app.agent.response_parser import build_result
from app.core.config import get_settings
from app.evaluation.llm_judge import evaluator
from app.evaluation.rule_based import quick_checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate one answer with Foundry's built-in evaluators.")
    parser.add_argument("question", nargs="?", default="What is the currency of the US?")
    parser.add_argument("--raw", action="store_true", help="also print Foundry's raw output items")
    args = parser.parse_args()
    settings = get_settings()

    result = build_result(agent_client.ask(args.question))
    response_id = result["response_id"]
    print(f"\nQuestion    : {args.question}")
    print(f"Answer      : {result['answer']}")
    print(f"Response ID : {response_id}")

    quick = quick_checks.run(args.question, result)
    print("\nQuick checks (no model)")
    for check in quick["checks"]:
        print(f"  {'pass' if check['passed'] else 'FAIL'}  {check['name']}")
    if quick["expected"]:
        expected = quick["expected"]
        print(f"  {'pass' if expected['passed'] else 'FAIL'}  Matches the expected answer ({expected['expected']})")

    print(f"\nFoundry evaluators: {', '.join(settings.evaluators)} (judge: {settings.eval_model_deployment})")
    started = time.perf_counter()
    state = evaluator.start(response_id)
    while state["status"] == "running":
        time.sleep(3)
        state = evaluator.status(response_id)
        print(f"  {state['status']:<10} {time.perf_counter() - started:5.1f}s")

    if state["status"] == "failed":
        print(f"\nFailed: {state['error']} (see the log lines above for the cause)")
    for entry in state["evaluators"]:
        if "error" in entry:
            print(f"\n  {entry['label']}: no score ({entry['error']})")
        else:
            verdict = "pass" if entry["passed"] else "FAIL"
            print(f"\n  {entry['label']}: {entry['score']} (threshold {entry['threshold']}, {verdict})")
            print(f"    {entry['reason']}")
    print(f"\nEvaluation took {time.perf_counter() - started:.1f}s")

    if args.raw:
        run = evaluator._runs[response_id]
        if "run_id" in run:
            items = evaluator._client().evals.runs.output_items.list(run_id=run["run_id"], eval_id=run["eval_id"])
            print(json.dumps([evaluator._as_dict(item) for item in items], indent=2, default=str))


if __name__ == "__main__":
    main()
