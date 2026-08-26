"""extension 机制 —— 外部扩展加载（事件订阅 + 工具注册 + 命令）。

ExtensionAPI 是传给 extension 的能力面（on / tool / command 三件套）；
ExtensionManager 是 Repository（发现 / 加载 / 命令调度），对标 SkillManager /
SubagentManager。加载协议：扩展文件定义 `def extension(api)`（或 default /
第一个形参名含 api 的函数），由 importlib 动态加载。
"""

from __future__ import annotations

import importlib.util
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

from my_agent_core.events import Event
from my_agent_core.tools import Tool
from my_agent_core.tools import tool as _tool

if TYPE_CHECKING:
    from my_agent_core.agent import Agent

CommandHandler = Callable[..., Any]


class ExtensionAPI:
    """暴露给 extension 的能力面：事件订阅 + 工具注册 + 命令。"""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self._commands: dict[str, CommandHandler] = {}

    # ── 事件订阅（类型化事件 + 双参 handler，复用 HookRegistry）────────

    @overload
    def on(
        self, event_cls: type[Event], handler: None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

    @overload
    def on(self, event_cls: type[Event], handler: Callable[..., Any]) -> None: ...

    def on(
        self, event_cls: type[Event], handler: Callable[..., Any] | None = None
    ) -> Any:
        """注册事件 handler（可作装饰器）。handler 签名 (event, api)：
        返回 None=观察，返回 HookResult=干预（block/updated_args/updated_result）。"""

        def _register(h: Callable[..., Any]) -> Callable[..., Any]:
            def wrapped(event: Event):
                return h(event, self)

            self.agent.hooks.register(event_cls, wrapped)
            return h

        if handler is not None:
            _register(handler)
            return None
        return _register

    # ── 工具注册（复用 @tool）────────────────────────────────────────

    def register_tool(self, tool: Tool) -> None:
        """注册工具 → agent.registry（撞名静默覆盖，registry 语义）。"""
        self.agent.registry.register(tool)

    def tool(self, **kwargs: Any):
        """@api.tool(description=...) 装饰器：@tool 包装 + register_tool。"""

        def decorator(func) -> Tool:
            t = _tool(**kwargs)(func)
            self.register_tool(t)
            return t

        return decorator

    # ── 命令（注册 + 存表，调度在 ExtensionManager）────────────────────

    def register_command(
        self, name: str, handler: CommandHandler, description: str = ""
    ) -> None:
        """注册命令（name 不含 /）。"""
        self._commands[name] = handler

    def command(self, name: str, description: str = ""):
        """@api.command("now") 装饰器。"""

        def decorator(func: CommandHandler) -> CommandHandler:
            self.register_command(name, func, description)
            return func

        return decorator

    def get_commands(self) -> dict[str, CommandHandler]:
        """已注册命令的拷贝（name → handler）。"""
        return self._commands.copy()


class ExtensionManager:
    """扩展管理器（Repository）：发现 / 加载 / 命令调度。"""

    DEFAULT_DIR_NAME = "extensions"  # <cwd>/.agents/extensions

    def __init__(self, agent: Agent, extension_dirs: list[str | Path] | None = None):
        """解析目录（三态同 skill_dirs）：None → 探测 <cwd>/.agents/extensions；
        [] → 禁用；非空 → 只扫这些目录。load() 显式加载（有副作用）。"""
        self.agent = agent
        self.api = ExtensionAPI(agent)
        self.extensions: dict[str, Any] = {}
        if extension_dirs is None:
            extension_dirs = [Path.cwd() / ".agents" / self.DEFAULT_DIR_NAME]
        self._dirs: list[Path] = [Path(d) for d in extension_dirs]

    def discover(self, directory: Path | str) -> list[Path]:
        """扫目录下 **/*.py（递归），跳过 _ 开头私有文件；目录不存在 → []。"""
        directory = Path(directory)
        if not directory.exists():
            return []
        return [p for p in directory.glob("**/*.py") if not p.name.startswith("_")]

    async def load_extension(self, path: Path | str) -> None:
        """importlib 动态加载 .py；找 extension → default → 第一个形参名含 api 的函数；
        找不到 → ValueError；找到则 extension_func(self.api) 执行并登记。支持 async/sync 扩展。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Extension not found: {path}")
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load extension: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        extension_func = None
        if hasattr(module, "extension"):
            extension_func = module.extension
        elif hasattr(module, "default"):
            extension_func = module.default
        else:
            for _name, obj in inspect.getmembers(module, inspect.isfunction):
                sig = inspect.signature(obj)
                params = list(sig.parameters.values())
                if params and "api" in params[0].name.lower():
                    extension_func = obj
                    break
        if extension_func is None:
            raise ValueError(
                f"Extension {path} must define an 'extension' function that takes ExtensionAPI"
            )
        if inspect.iscoroutinefunction(extension_func):
            await extension_func(self.api)
        else:
            extension_func(self.api)
        self.extensions[path.name] = module

    async def load(self) -> None:
        """遍历 self._dirs 逐个 load_extension；单个失败只 print 不抛（隔离坏扩展）。"""
        for directory in self._dirs:
            for path in self.discover(directory):
                try:
                    await self.load_extension(path)
                except Exception as exc:
                    print(f"Failed to load extension {path}: {exc}")

    def handle_command(self, command: str, args: str | None = None) -> Any:
        """查表调用命令（未知命令 ValueError；0 参直接调，>0 参传 args）。"""
        commands = self.api.get_commands()
        if command not in commands:
            raise ValueError(f"Unknown command: /{command}")
        handler = commands[command]
        if len(inspect.signature(handler).parameters) > 0:
            return handler(args)
        return handler()
