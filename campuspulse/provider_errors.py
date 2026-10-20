"""Safe, provider-specific guidance without exposing upstream error payloads.

Messages and response bodies can contain request URLs, credentials or student
content. They are used only for a few bounded classifications, never returned.
This module performs no requests and does not inspect environment variables.
"""
from __future__ import annotations

from typing import Literal


Provider = Literal["developer_api", "vertex_ai"]


def _attribute(value, name):
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _http_status(error) -> int | None:
    for value in (_attribute(error, "code"), _attribute(error, "status_code"),
                  _attribute(_attribute(error, "response"), "status_code")):
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return int(value)
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) == 3:
            number = int(value)
            if 100 <= number <= 599:
                return number
    return None


def _classification_text(error) -> str:
    # Do not call str(error): the GenAI SDK includes the full response in it.
    fragments = []
    for name in ("message", "status", "reason"):
        value = _attribute(error, name)
        if isinstance(value, str):
            fragments.append(value[:4096])
    # google.genai.errors.APIError stores its JSON body in .details.
    for name in ("details", "response_json"):
        payload = _attribute(error, name)
        if not isinstance(payload, dict):
            continue
        payload = payload.get("error", payload)
        if not isinstance(payload, dict):
            continue
        for key in ("message", "status", "reason"):
            value = payload.get(key)
            if isinstance(value, str):
                fragments.append(value[:4096])
        details = payload.get("details", [])
        if isinstance(details, list):
            for detail in details[:10]:
                if isinstance(detail, dict) and isinstance(detail.get("reason"), str):
                    fragments.append(detail["reason"][:256])
    return " ".join(fragments).casefold()


def classify_provider_error(error: BaseException, provider: Provider = "developer_api") -> dict:
    """Return an allowlisted error code and next step, never a raw error string.

    ``provider`` describes the route actually used, not merely whether Google
    Cloud is configured. In particular, a Developer API key does not use Vertex
    IAM or Vertex billing. ``retryable`` does not promise an automatic retry.
    """
    if provider not in ("developer_api", "vertex_ai"):
        raise ValueError("Unsupported Gemini provider")
    status = _http_status(error)
    text = _classification_text(error)
    names = {cls.__name__.casefold() for cls in type(error).__mro__}

    def result(code, action, retryable=False):
        return {"code": code, "http_status": status, "action": action, "retryable": retryable}

    if isinstance(error, TimeoutError) or status in (408, 504) or any(
        "timeout" in name or name == "deadlineexceeded" for name in names
    ):
        return result("timeout", "Gemini не ответил вовремя. Повторите запрос немного позже; проверьте интернет и доступность сервиса.", True)

    invalid_key = any(marker in text for marker in (
        "api_key_invalid", "api key not valid", "invalid api key", "api key is invalid",
        "api key expired", "api_key_expired", "api key was reported as leaked",
    ))
    if provider == "developer_api" and status in (400, 401, 403) and invalid_key:
        return result("invalid_api_key", "Gemini отклонил API-ключ. Проверьте или замените серверный ключ в Google AI Studio; не отправляйте его в чат.")

    if status == 400:
        return result("invalid_request", "Gemini не принял параметры запроса. Проверьте имя модели, формат и размер входных данных.")
    if status == 401:
        if provider == "developer_api":
            return result("authentication_failed", "Проверьте серверный API-ключ Google AI Studio и его ограничения. Не отправляйте ключ в чат.")
        return result("authentication_failed", "Обновите авторизацию Google Cloud ADC и проверьте выбранный аккаунт и проект.")
    if status == 403:
        if any(marker in text for marker in (
            "location is not supported", "location not supported", "unsupported location",
            "region is not supported", "unsupported region", "country is not supported",
            "not available in your country", "not supported in your country", "user location",
        )):
            action = ("Gemini Developer API недоступен для текущего местоположения. Проверьте официальную доступность сервиса в вашей стране."
                      if provider == "developer_api" else
                      "Модель Vertex AI недоступна в выбранном регионе. Проверьте поддерживаемые регионы модели и настройку региона проекта.")
            return result("region_unavailable", action)
        action = ("Проверьте доступ к Gemini API для проекта Google AI Studio, ограничения API-ключа и доступность выбранной модели."
                  if provider == "developer_api" else
                  "Проверьте права IAM аккаунта, включение Vertex AI API и доступ проекта к выбранной модели.")
        return result("permission_denied", action)
    if status == 404:
        return result("model_not_found", "Проверьте точное имя модели и её доступность для выбранного провайдера; модель может быть недоступна этому проекту или API.")
    if status == 429:
        action = ("Достигнут лимит Gemini API. Проверьте квоты модели и бесплатного тарифа проекта в Google AI Studio; подождите восстановления лимита или выберите доступную модель."
                  if provider == "developer_api" else
                  "Достигнута квота Vertex AI. Проверьте лимиты модели, проекта и региона; повторите запрос после восстановления квоты.")
        return result("quota_exhausted", action, True)
    if status in (500, 502, 503):
        return result("temporary_unavailable", "Gemini временно недоступен или перегружен. Повторите запрос немного позже; этот ответ не означает, что API-ключ неверный.", True)
    if any(name in names for name in ("connecterror", "connectionerror", "networkerror")):
        return result("connection_failed", "Не удалось подключиться к Gemini. Проверьте интернет и сетевой доступ к выбранному API.", True)
    if provider == "vertex_ai" and "defaultcredentialserror" in names:
        return result("credentials_missing", "Настройте авторизацию Google Cloud ADC для выбранного аккаунта и проекта.")
    return result("provider_error", "Запрос к Gemini не выполнен. Проверьте доступность выбранного провайдера и модели; подробности запроса и секреты не отображаются.")
