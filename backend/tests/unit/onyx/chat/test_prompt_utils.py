from types import SimpleNamespace

from onyx.chat import prompt_utils as chat_prompt_utils
from onyx.prompts.chat_prompts import DEFAULT_SYSTEM_PROMPT


def test_build_system_prompt_includes_eva_extension_by_default(monkeypatch) -> None:
    def fake_build_eva_system_prompt_extension(*args, **kwargs) -> str:
        return "\nEVA_EXTENSION"

    monkeypatch.setattr(
        chat_prompt_utils,
        "build_eva_system_prompt_extension",
        fake_build_eva_system_prompt_extension,
    )

    result = chat_prompt_utils.build_system_prompt(base_system_prompt="Base prompt")

    assert "EVA_EXTENSION" in result


def test_build_system_prompt_can_skip_eva_extension(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_build_eva_system_prompt_extension(*args, **kwargs) -> str:
        calls.append((args, kwargs))
        return "\nEVA_EXTENSION"

    monkeypatch.setattr(
        chat_prompt_utils,
        "build_eva_system_prompt_extension",
        fake_build_eva_system_prompt_extension,
    )

    result = chat_prompt_utils.build_system_prompt(
        base_system_prompt="Base prompt",
        include_eva_system_prompt=False,
    )

    assert "EVA_EXTENSION" not in result
    assert calls == []


def test_get_default_base_system_prompt_uses_default_for_empty_prompt(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chat_prompt_utils,
        "get_default_behavior_persona",
        lambda _db_session: SimpleNamespace(system_prompt=""),
    )

    assert (
        chat_prompt_utils.get_default_base_system_prompt(None) == DEFAULT_SYSTEM_PROMPT
    )


def test_get_default_base_system_prompt_uses_default_for_blank_prompt(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chat_prompt_utils,
        "get_default_behavior_persona",
        lambda _db_session: SimpleNamespace(system_prompt="   "),
    )

    assert (
        chat_prompt_utils.get_default_base_system_prompt(None) == DEFAULT_SYSTEM_PROMPT
    )
