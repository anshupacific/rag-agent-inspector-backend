# Agent Inspector API

FastAPI backend that calls the Foundry agent and returns the answer, sources,
evidence and steps for the Agent Inspector UI.

## Layout

    app/
      main.py                       builds the app and plugs in the routes
      core/                         shared plumbing
        config.py                   settings from environment variables
        logging_setup.py            log levels
        rate_limit.py               per-visitor and daily request limits
      agent/                        calling the Foundry agent
        agent_client.py             the only module that creates the Foundry client
        response_parser.py          answer, sources, evidence and steps from a raw response
        sse.py                      streaming events for the live steps panel
        recent_answers.py           recent answers, so only this API's own responses can be scored
      evaluation/
        rule_based/                 checks written in our own code, no model call
          quick_checks.py           citation checks and the expected-answer lookup
          scoring.py                rules for comparing an answer with a known expected answer
          golden.py                 loads the known questions
          data/golden.jsonl         218 known questions with their expected outcomes
        llm_judge/                  scores from Foundry's built-in evaluators
          evaluator.py              starts and reads the Foundry evaluation for one answer
      guardrails/                   reporting a block by the agent's Foundry guardrail
        block_detector.py           recognises a block and says which risk fired and where
        risks.py                    plain-language name for each risk
      api/                          HTTP routes
        common.py                   settings, rate limiter and question validation shared by routes
        health.py                   GET /health
        ask.py                      POST /api/ask and /api/ask/stream
        evaluations.py              POST and GET /api/evaluations
    scripts/
      try_evaluation.py             score one live answer from the command line and time it
      try_guardrail.py              show what Foundry returns for blocked and allowed prompts
    tests/                          mirrors app/: agent, api, evaluation, guardrails (no Azure calls)

## Run locally

    python -m venv .venv
    .venv\Scripts\activate          # Windows; use `source .venv/bin/activate` elsewhere
    pip install -r requirements-dev.txt
    copy .env.example .env          # then edit if needed
    az login
    uvicorn app.main:app --reload --port 8000

Try it (PowerShell):

    curl.exe http://localhost:8000/health
    curl.exe -X POST http://localhost:8000/api/ask -H "Content-Type: application/json" -d '{\"question\": \"What is the currency of the US?\"}'
    curl.exe -N -X POST http://localhost:8000/api/ask/stream -H "Content-Type: application/json" -d '{\"question\": \"Which countries use the Euro?\"}'

The interactive docs at http://localhost:8000/docs are the easiest way to try
`/api/ask`. Run the tests with `pytest`.

## Per-answer evaluation

Every answer can be scored right after it is given:

- **Quick checks** (no model, instant): does it cite a source, or cite nothing when
  it says it does not know; and, for a known test question, does it match the
  guide's fact.
- **Foundry evaluators** (judge model): Foundry scores the stored response by its
  response ID with the built-in evaluators listed in `EVALUATORS`. Each returns a
  score, a pass/fail against its threshold, and a one-line reason. The run is also
  visible in the Foundry project.

Foundry runs are asynchronous, so the UI starts one and polls for the result.
Try one from the command line first; it prints how long the evaluation took:

    python -m scripts.try_evaluation "What is the currency of the US?"
    python -m scripts.try_evaluation "What is the capital of Peru?" --raw

## Endpoints

| Route | Purpose |
|---|---|
| `GET /health` | Liveness check; the UI also calls it on page load to wake the app |
| `POST /api/ask` | Body `{"question": "..."}`; returns the full parsed answer as JSON |
| `POST /api/ask/stream` | Same body; server-sent events: `step`, `delta`, `result`, `error` |
| `POST /api/evaluations` | Body `{"response_id": "..."}`; starts scoring that answer and returns the quick checks |
| `GET /api/evaluations/{response_id}` | Quick checks plus Foundry's scores once `status` is `completed` |

Result shape: `answer`, `sources[]`, `evidence[]`, `steps[]`, `usage`, `counts`,
`agent`, `duration_ms`, `response_id`.

## Deploy to App Service (Linux, Python 3.12)

Replace the `<...>` values. The plan can be `F1` (free) or `B1`.

    az appservice plan create -g <rg> -n plan-agent-inspector --is-linux --sku F1
    az webapp create -g <rg> -p plan-agent-inspector -n <app-name> --runtime "PYTHON:3.12"

    az webapp identity assign -g <rg> -n <app-name>
    az role assignment create --assignee <principalId-from-previous-command> --role "Foundry User" --scope <foundry-project-resource-id>

    az webapp config appsettings set -g <rg> -n <app-name> --settings PROJECT_ENDPOINT=<project-endpoint> AGENT_NAME=agent-v2-for-rag AGENT_VERSION=3 ALLOWED_ORIGINS=<https://your-frontend-domain> SCM_DO_BUILD_DURING_DEPLOYMENT=true
    az webapp config set -g <rg> -n <app-name> --startup-file "gunicorn -w 1 -k uvicorn.workers.UvicornWorker --timeout 120 app.main:app"

    az webapp deploy -g <rg> -n <app-name> --src-path agent-inspector-backend.zip --type zip

Notes:

- If the role name "Foundry User" is not found, use its previous name, "Azure AI User".
- Keep one worker (`-w 1`): the rate limiter counts in memory, per process.
- There are no secrets. The app authenticates to Foundry with its managed identity.