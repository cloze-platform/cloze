"""A failed LLM call returns a friendly message, even when the debug dump
can't be written (as in the container, where the app directory is read-only)."""
import pathlib
from types import SimpleNamespace

from llm_chat.services.llm_interface import LLMInterface


def test_failed_call_survives_unwritable_dump_dir(app, monkeypatch):
    def read_only(*args, **kwargs):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(pathlib.Path, "mkdir", read_only)
    monkeypatch.setattr(LLMInterface, "_provider_clients", {})  # every call fails
    model = SimpleNamespace(provider="openai", model_identifier="gpt-test", name="Test", config="{}")

    reply, _ = LLMInterface.call_llm(model, [{"role": "user", "content": "hi"}])

    assert reply.startswith("Something went wrong on my end")
