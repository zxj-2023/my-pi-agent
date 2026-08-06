"""Provider 注册表：provider 名 → 实现类，门面据此路由。"""
from ._base import Provider
from .anthropic import AnthropicProvider
from .deepseek import DeepSeekProvider
from .openai import OpenAIProvider

PROVIDER_REGISTRY: dict[str, type[Provider]] = {
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "anthropic": AnthropicProvider,
}
