from hashlib import sha256
from typing import Optional, Dict, Any


def _stable_session(user_id: str, chat_id: str) -> str:
    seed = f"{user_id}:{chat_id}".encode("utf-8")
    return sha256(seed).hexdigest()[:64]


def inlet(
    body: Dict[str, Any],
    __user__: Optional[Dict[str, Any]] = None,
    __metadata__: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Function signature compatibile con Open WebUI filters."""
    if not __metadata__:
        return body

    chat_id = __metadata__.get("chat_id")
    if not chat_id:
        return body

    user_id = (__user__ or {}).get("id", "anon")
    body["user"] = _stable_session(user_id, chat_id)
    return body


def outlet(body: Dict[str, Any], **_) -> Dict[str, Any]:
    return body
