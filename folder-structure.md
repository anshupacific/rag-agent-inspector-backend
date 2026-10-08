# Backend folder guide

```
agent-inspector-backend/
  app/
    main.py
    core/
    agent/
    evaluation/
      rule_based/
      llm_judge/
    guardrails/
    api/
  scripts/
  tests/
```

## app/

The application that gets deployed. `main.py` builds the FastAPI app and plugs in the routes; it holds no logic of its own.

## app/core/

Shared plumbing that every other folder relies on: settings read from environment variables, log levels, and the rate limiter that caps requests per visitor and per day.

## app/agent/

Everything about calling the Foundry agent and reading what it returns. It creates the Foundry client, sends the question, turns the raw response into an answer with sources, evidence and steps, streams those steps to the browser, and remembers recent answers so they can be evaluated.

## app/evaluation/

Scoring an answer after it has been given. It has two parts, one per evaluation technique.

### app/evaluation/rule_based/

Checks written in our own Python code, with no model call, so they are instant and free. They cover whether the answer cites a source, whether it cites nothing when it says "I don't know", and whether it matches the expected answer for a known test question. `data/golden.jsonl` holds those known questions and expected answers.

### app/evaluation/llm_judge/

Scores from Foundry's built-in evaluators (groundedness, relevance, task adherence), where a judge model grades the answer. This code sends the answer's response ID to Foundry and reads back the scores and reasons. It has no dataset and no rules file, because Foundry looks up the stored answer itself and the grading instructions are built into the evaluators.

## app/guardrails/

Reporting what the agent's guardrail did. The guardrail is created in Foundry and assigned to the agent there, so Foundry enforces it inside the normal agent call and this folder makes no calls of its own. It recognises when a question was blocked, works out which risk fired (for example a user input attack, hate or violence) and at which point, and turns that into a clear "blocked" result. For answers that were allowed, it lists what the guardrail checked.

## app/api/

The HTTP routes the frontend calls. Each file is one group of routes: health check, asking a question, and evaluating an answer. Routes validate the request and call into `agent/` and `evaluation/`; they contain no business logic.

## scripts/

Command-line helpers for development. They are not deployed. `try_evaluation.py` asks one question, evaluates the answer and prints how long it took. `try_guardrail.py` sends test prompts and prints exactly what Foundry returns when the guardrail blocks or allows them.

## tests/

Automated tests, arranged in the same folders as `app/`. They use a fake agent and a fake Foundry service, so they run without Azure and cost nothing.

## How a request flows

1. The browser calls a route in `api/`.
2. The route uses `agent/` to ask the Foundry agent and parse the answer.
3. The browser then asks for an evaluation of that answer.
4. `evaluation/rule_based/` returns its checks immediately, and `evaluation/llm_judge/` returns Foundry's scores when they are ready.
5. `core/` supplies the settings, logging and rate limiting used along the way.