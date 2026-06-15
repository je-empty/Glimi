"""App shim for the Glimi-kernel runtime module.

The agent runtime now lives in ``src.glimi.runtime`` (kernel, storage/profile/
observer-neutral). This shim wires the Hangout app's adapters into the kernel,
ensures the memory module is wired too, and re-exports the public API so
existing ``from src.core.runtime import runtime`` call sites keep working.
"""
from src.glimi.runtime import *  # noqa: F401,F403  (re-export kernel runtime API)
from src.glimi import runtime as _kr
from src.adapters.kernel_store import (
    kernel_store as _kernel_store,
    profile_provider as _profile_provider,
    owner_context as _owner_context,
    observer as _observer_impl,
)

# 앱 어댑터 주입 (kernel runtime 의 module-global _store 등을 채움)
_kr.set_store(_kernel_store)
_kr.set_profiles(_profile_provider)
_kr.set_owner(_owner_context)
_kr.set_observer(_observer_impl)

# memory 도 같이 주입 보장 (runtime → memory 호출 경로)
import src.core.memory  # noqa: F401,E402

# 재export 가 빠뜨리는 인스턴스/상수 명시 보강
runtime = _kr.runtime  # noqa: F811
