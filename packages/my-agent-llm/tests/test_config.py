"""Config 配置模型测试。"""
import pytest
from pydantic import ValidationError

from my_agent_llm.config import Config


def test_config_defaults():
    """默认值。"""
    c = Config()
    assert c.provider == "openai"
    assert c.model is None
    assert c.temperature == 0.7
    assert c.max_retries == 3


def test_config_rejects_temperature_out_of_range():
    """temperature 超范围 → ValidationError。"""
    with pytest.raises(ValidationError):
        Config(temperature=5.0)


def test_config_rejects_negative_max_retries():
    """max_retries 为负 → ValidationError。"""
    with pytest.raises(ValidationError):
        Config(max_retries=-1)


def test_config_frozen():
    """frozen：构造后不可改。"""
    c = Config()
    with pytest.raises(Exception):
        c.provider = "anthropic"
