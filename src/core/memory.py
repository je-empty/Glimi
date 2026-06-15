"""App shim for the Glimi-kernel memory module.

The memory engine now lives in ``glimi.memory`` (kernel, storage/profile/
observer-neutral). This shim wires the Hangout app's adapters into the kernel
and re-exports the public API so existing ``from src.core.memory import ...``
call sites keep working unchanged.
"""
from glimi.memory import *  # noqa: F401,F403  (re-export kernel memory API)
from glimi import memory as _km
from src.adapters.kernel_store import (
    kernel_store as _kernel_store,
    profile_provider as _profile_provider,
    owner_context as _owner_context,
    observer as _observer_impl,
)

# 앱 어댑터 주입 (이 모듈 import 시점 = 앱 부팅 초기 → 사용 전에 주입됨)
_km.set_store(_kernel_store)
_km.set_profiles(_profile_provider)
_km.set_owner(_owner_context)
_km.set_observer(_observer_impl)
