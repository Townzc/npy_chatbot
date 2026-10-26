"""Pure mode contract, shared by the persistent coordinator and tests."""

from chattwin.domain import DomainError, Mode

ENABLE_NOTICE = "对方已切换为ai模式"
TAKEOVER_NOTICE = "本人已接管"


def transition(mode: Mode, action: str) -> tuple[Mode, str | None]:
    if action == "enable":
        return (mode, None) if mode == Mode.AI_ACTIVE else (Mode.ENABLING, ENABLE_NOTICE)
    if action == "takeover":
        return (Mode.HUMAN, None if mode == Mode.HUMAN else TAKEOVER_NOTICE)
    if action == "pause":
        return (Mode.HUMAN if mode == Mode.HUMAN else Mode.PAUSED), None
    raise DomainError("INVALID_ACTION", "Unknown mode action", 422)
