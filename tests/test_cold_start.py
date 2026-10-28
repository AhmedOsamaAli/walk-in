"""What a cold start costs (Render's free instance has 0.1 CPU): the app imports without the openai package, the
heaviest import it has, and loads it only when a model is first asked, in a worker thread, so the event loop keeps
serving meanwhile; each provider's client is made then, with the TLS setup every outgoing client shares."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import openai

from app import llm as llm_module
from app import tls
from app.llm import LLM, Provider
from tests.test_llm import completion, mock_llm

REPO = Path(__file__).resolve().parent.parent


def test_the_app_imports_and_builds_its_ai_chain_without_openai(tmp_path):
    """A fresh process, as on a server's start: openai is not imported by the app, even with AI keys set."""
    probe = (
        "import sys\n"
        "import app.main\n"
        "from dataclasses import replace\n"
        "from app.config import settings\n"
        "from app.providers import build_llm\n"
        "chain = build_llm(replace(settings, llm_api_key='key', groq_api_key='key'))\n"
        "print(chain.enabled, 'openai' in sys.modules)\n"
    )
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'walkin.db').as_posix()}", "LLM_API_KEY": "",
           "GROQ_API_KEY": "", "QLOO_API_KEY": "", "KEEP_AWAKE_URL": "", "EXAMPLES": "", "PUBLIC_URL": ""}
    done = subprocess.run([sys.executable, "-c", probe], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split() == ["True", "False"]


def test_the_first_call_loads_openai_in_a_worker_thread_then_makes_the_client(monkeypatch):
    threads: list[bool] = []
    real = llm_module._openai

    def recorded():
        threads.append(threading.current_thread() is threading.main_thread())
        return real()

    monkeypatch.setattr(llm_module, "_openai", recorded)
    chain = mock_llm([httpx.Response(200, json=completion({"role": "assistant", "content": '{"ok": 1}'}))], [])
    route = chain._routes["test-model"]
    assert route._client is None and threads == []  # nothing loaded or made before a model is asked
    assert asyncio.run(chain.complete_json("system", "user")) == ({"ok": 1}, "test-model")
    assert threads[0] is False  # the import ran off the event loop's thread; later lookups find it loaded
    assert route._client is not None and chain._loaded


def test_each_provider_s_client_is_made_when_first_asked_with_the_shared_tls_setup(monkeypatch):
    made: list[dict] = []

    class Recording(openai.DefaultAsyncHttpxClient):
        def __init__(self, **kwargs):
            made.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(openai, "DefaultAsyncHttpxClient", Recording)
    chain = LLM("main-key", "https://llm.test/v1/", "model-a", timeout=30.0,
                also=[Provider("other-key", "https://other.test/v1/", ("model-b",))])
    first = chain._routes["model-a"].client
    assert chain._routes["model-a"].client is first and len(made) == 1  # one client per provider, made once
    assert made[0]["verify"] is tls.context() and made[0]["timeout"] == 30.0
    assert str(first.base_url) == "https://llm.test/v1/" and first.api_key == "main-key" and first.max_retries == 0
    assert chain._routes["model-b"]._client is None  # the other provider's waits until one of its models is asked
    asyncio.run(first.close())
