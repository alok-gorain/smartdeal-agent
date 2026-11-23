import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_smartdeal_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Quiet noisy libraries
    for name in ("httpx", "httpcore", "asyncio", "urllib3", "google_genai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    root._smartdeal_configured = True  # type: ignore[attr-defined]
