"""RPC handler decorators and guards."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable


def require_agent(func: Callable[..., Any]) -> Callable[..., Any]:
    """前置门禁装饰器：检查 self.agent 是否存在，未初始化直接回复标准错误 -32001。"""
    sig = inspect.signature(func)
    accepts_params = len(sig.parameters) >= 3 or "params" in sig.parameters

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(
            self: Any, req_id: Any, params: dict[str, Any] | None = None, *args: Any, **kwargs: Any
        ) -> Any:
            if not getattr(self, "agent", None):
                return self.send_response(
                    req_id,
                    error={"code": -32001, "message": "Agent not initialized"},
                )
            if accepts_params:
                return await func(self, req_id, params or {}, *args, **kwargs)
            return await func(self, req_id, *args, **kwargs)

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(self: Any, req_id: Any, params: dict[str, Any] | None = None, *args: Any, **kwargs: Any) -> Any:
        if not getattr(self, "agent", None):
            return self.send_response(
                req_id,
                error={"code": -32001, "message": "Agent not initialized"},
            )
        if accepts_params:
            return func(self, req_id, params or {}, *args, **kwargs)
        return func(self, req_id, *args, **kwargs)

    return sync_wrapper


__all__ = [
    "require_agent",
]
