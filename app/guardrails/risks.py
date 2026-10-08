"""Plain-language name and description for each risk a Foundry guardrail reports."""

RISKS = {
    "jailbreak": ("User input attack", "An attempt to override the agent's instructions"),
    "indirect_attack": ("Indirect prompt injection", "Instructions hidden inside content the agent was given"),
    "hate": ("Hate", "Hateful or discriminatory content"),
    "violence": ("Violence", "Violent content or threats"),
    "sexual": ("Sexual content", "Sexually explicit content"),
    "self_harm": ("Self-harm", "Content about harming oneself"),
    "protected_material_text": ("Protected text", "Copyrighted text reproduced in the answer"),
    "protected_material_code": ("Protected code", "Licensed source code reproduced in the answer"),
}

# Foundry labels each scan with where the text came from.
STAGES = {"prompt": "user_input", "completion": "output"}


def describe(risk_id: str) -> tuple:
    """(label, description) for a risk, with a readable fallback for ones not listed above."""
    return RISKS.get(risk_id, (risk_id.replace("_", " ").capitalize(), ""))