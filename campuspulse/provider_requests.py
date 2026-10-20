"""One bounded retry for transient Gemini errors, with a shared time budget.

The configured SDK client must disable its own automatic HTTP retries
(``HttpRetryOptions(attempts=1)``), so two SDK calls also mean at most two
provider attempts. No alternative provider or model is selected here.
"""
from asyncio import sleep, wait_for
import math
from time import monotonic

from campuspulse.provider_errors import classify_provider_error


async def generate_content(client, *, timeout=45, **kwargs):
    """Return the SDK response unchanged within at most 45 seconds total.

    Retry HTTP 500/502/503 once after one second, only when at least five
    seconds remain in the original budget. Timeout, cancellation, quota,
    permission and other failures are never retried. The last exception is
    propagated without rendering its message or logging request data.
    """
    if isinstance(timeout, bool):
        raise ValueError("Gemini timeout must be a positive number")
    try:
        requested = float(timeout)
    except (TypeError, ValueError):
        raise ValueError("Gemini timeout must be a positive number") from None
    if not math.isfinite(requested) or requested <= 0:
        raise ValueError("Gemini timeout must be a positive number")
    deadline = monotonic() + min(requested, 45.0)
    for attempt in range(2):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Gemini request deadline exceeded")
        try:
            return await wait_for(client.aio.models.generate_content(**kwargs), timeout=remaining)
        except Exception as error:
            classification = classify_provider_error(error)
            if (attempt != 0 or classification["code"] == "timeout"
                    or classification["http_status"] not in (500, 502, 503)
                    or deadline - monotonic() < 5):
                raise
            await sleep(1)
