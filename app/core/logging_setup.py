"""Logging for the whole app: our own messages at INFO, libraries at WARNING."""

import logging

# The Azure SDKs and the App Service monitoring agent log every HTTP call at INFO,
# including a telemetry upload every few seconds. Keep only their warnings and errors.
NOISY_LIBRARIES = ("azure", "httpx", "httpx2", "httpcore", "httpcore2", "openai", "opentelemetry")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)
    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
