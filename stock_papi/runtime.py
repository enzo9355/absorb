"""Lightweight runtime helpers and lazy heavy-client loaders."""

import importlib
import threading


class _LazyModule:
    def __init__(self, name):
        self._name = name
        self._module = None
        self._lock = threading.Lock()

    def __getattr__(self, name):
        if self._module is None:
            with self._lock:
                if self._module is None:
                    self._module = importlib.import_module(self._name)
        return getattr(self._module, name)


class _LazyGeminiModel:
    def __init__(self, api_key):
        self._api_key = api_key
        self._model = None
        self._lock = threading.Lock()

    def generate_content(self, *args, **kwargs):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    genai = importlib.import_module("google.generativeai")
                    genai.configure(api_key=self._api_key)
                    self._model = genai.GenerativeModel("gemini-2.5-flash")
        return self._model.generate_content(*args, **kwargs)


def get_gcp_access_token(line_store, requests_module):
    if line_store and hasattr(line_store, "token_provider"):
        try:
            return line_store.token_provider()
        except Exception:
            pass
    try:
        import google.auth
        import google.auth.transport.requests
        credentials, project = google.auth.default()
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        return credentials.token
    except Exception:
        try:
            res = requests_module.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
                timeout=3
            )
            if res.status_code == 200:
                return res.json().get("access_token")
        except Exception:
            pass
    return None
