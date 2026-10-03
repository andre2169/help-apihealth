import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core import security_policy as policy
from app.core.config import settings


class EvolutionDeliveryError(RuntimeError):
    """Falha sanitizada de comunicação com a Evolution API."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Provider credentials and recipient data must stay on the configured URL.
        return None


def _provider_message_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None

    key = payload.get("key")
    if isinstance(key, dict) and key.get("id"):
        return str(key["id"])[:120]

    data = payload.get("data")
    if isinstance(data, dict):
        nested_key = data.get("key")
        if isinstance(nested_key, dict) and nested_key.get("id"):
            return str(nested_key["id"])[:120]

    return None


def send_text_message(*, number: str, text: str) -> str | None:
    """Envia texto pela Evolution API usando uma instância Baileys.

    A chave da Evolution fica somente no backend. O corpo da resposta do
    provedor não é registrado, pois pode conter dados da conversa.
    """

    if not settings.whatsapp_configured:
        raise EvolutionDeliveryError("whatsapp_not_configured")

    endpoint = (
        f"{settings.EVOLUTION_API_URL}/message/sendText/"
        f"{quote(settings.EVOLUTION_INSTANCE or '', safe='')}"
    )
    payload = {
        "number": number,
        "options": {"delay": 0},
        "textMessage": {"text": text},
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apikey": settings.EVOLUTION_API_KEY or "",
        },
        method="POST",
    )

    try:
        with build_opener(_NoRedirect()).open(request, timeout=policy.EVOLUTION_TIMEOUT_SECONDS) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # O corpo da resposta pode conter dados do destinatário ou da sessão.
        raise EvolutionDeliveryError(f"provider_http_{exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EvolutionDeliveryError("provider_unavailable") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvolutionDeliveryError("provider_invalid_response") from exc

    return _provider_message_id(response_payload)
