"""LLM 客户端配置：集中校验、可复用、不可变。"""
from pydantic import BaseModel, Field


class Config(BaseModel):
    """统一配置：provider/model/api_key/采样参数/网络参数。"""

    provider: str = "openai"
    model: str | None = None
    api_key: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout: int = Field(default=30, ge=1)
    max_retries: int = Field(default=3, ge=0)
    base_url: str | None = None

    class Config:
        frozen = True
