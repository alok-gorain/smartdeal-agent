"""Gemini chat model with automatic fallback to other models.

Google's popular models regularly return 503 "high demand" or time out, so every
call goes to GEMINI_MODEL first and then to each of GEMINI_FALLBACK_MODELS.
Retries are kept low so a busy model fails over in seconds instead of minutes.
"""

import warnings

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from core.config import settings

# Newer Gemini models ignore temperature; the library warns on every call
warnings.filterwarnings("ignore", message=".*uses fixed sampling defaults.*")

TRANSIENT_ERRORS = ("503", "UNAVAILABLE", "high demand", "RESOURCE_EXHAUSTED", "429")


def is_transient(exc: BaseException) -> bool:
    """Overload / rate-limit errors worth one more try after a short pause."""
    text = str(exc)
    return any(marker in text for marker in TRANSIENT_ERRORS)


def make_llm(model: str, temperature: float = 0.3) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.google_api_key,
        temperature=temperature,
        max_retries=0,  # fail over to the next model instead of waiting on a busy one
        timeout=settings.llm_timeout_seconds,
    )


def model_chain() -> list[str]:
    models = [settings.gemini_model]
    models += [m for m in settings.gemini_fallback_list if m not in models]
    return models


def make_chat_runnable(tools: list | None = None, temperature: float = 0.3) -> Runnable:
    """Primary model with fallbacks, optionally with tools bound to each model."""
    runnables = []
    for model in model_chain():
        llm = make_llm(model, temperature)
        runnables.append(llm.bind_tools(tools) if tools else llm)
    primary, fallbacks = runnables[0], runnables[1:]
    return primary.with_fallbacks(fallbacks) if fallbacks else primary
