"""Tegsoft-адаптер звонилки (бэкенд-only). Публичный API пакета.

Использование из Flask-слоя (api/calls.py):
    from tegsoft import get_provider
    provider = get_provider()            # mock|tegsoft по env CALL_PROVIDER
    call_ref = provider.originate(ext, phone)
"""
from tegsoft.adapter import (
    CallProvider,
    CallProviderError,
    MockProvider,
    TegsoftAuthError,
    TegsoftError,
    TegsoftProvider,
    get_provider,
    reset_provider,
)

__all__ = [
    "CallProvider",
    "CallProviderError",
    "TegsoftError",
    "TegsoftAuthError",
    "TegsoftProvider",
    "MockProvider",
    "get_provider",
    "reset_provider",
]
