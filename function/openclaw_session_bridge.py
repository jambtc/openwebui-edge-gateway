"""
title: OpenClaw Session Bridge
author: boxedai
version: 0.1
"""

import hashlib


class Filter:
    """
    Filter Function (Open WebUI)
    In `inlet` impostiamo body['user'] = sha256(user_id:chat_id).
    """

    def inlet(
        self, body: dict, __user__: dict = None, __metadata__: dict = None, **kwargs
    ):
        user_id = None
        if isinstance(__user__, dict):
            user_id = __user__.get("id") or __user__.get("email")

        chat_id = None
        if isinstance(__metadata__, dict):
            chat_id = __metadata__.get("chat_id")

        if user_id and chat_id:
            session_key = hashlib.sha256(
                f"{user_id}:{chat_id}".encode("utf-8")
            ).hexdigest()
            body["user"] = session_key

        return body
