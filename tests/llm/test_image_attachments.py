"""有序图片内容转换：保留文字和图片的交错顺序。"""

import pytest
from pydantic import ValidationError

from my_agent_llm import Message
from my_agent_llm.config import Config
from my_agent_llm.providers.anthropic import AnthropicProvider
from my_agent_llm.providers.antigravity import AntigravityProvider
from my_agent_llm.providers.openai import OpenAIProvider


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text"}],
        [{"type": "image", "mime_type": "image/png"}],
        [{"type": "unknown", "text": "bad"}],
    ],
)
def test_invalid_content_block_is_rejected(content):
    with pytest.raises(ValidationError):
        Message(role="user", content=content)


@pytest.mark.parametrize("image_only", [False, True])
def test_provider_preserves_ordered_content(image_only):
    image = {"type": "image", "data": "aGVsbG8=", "mime_type": "image/png"}
    image2 = {"type": "image", "data": "d29ybGQ=", "mime_type": "image/jpeg"}
    before = {"type": "text", "text": "before"}
    between = {"type": "text", "text": "between"}
    after = {"type": "text", "text": "after"}
    content = [image] if image_only else [before, image, between, image2, after]
    message = Message(role="user", content=content)
    assert Message.model_validate_json(message.model_dump_json()).content == content
    config = Config(api_key="test")
    openai = OpenAIProvider(config, client=object())
    anthropic = AnthropicProvider(config, client=object())
    gemini = AntigravityProvider(config, client=object())

    openai_image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}}
    openai_image2 = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,d29ybGQ="}}
    assert openai._convert_messages([message]) == [
        {
            "role": "user",
            "content": [openai_image] if image_only else [before, openai_image, between, openai_image2, after],
        }
    ]
    anthropic_image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}}
    anthropic_image2 = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "d29ybGQ="}}
    assert anthropic._convert_messages([message]) == (
        None,
        [
            {
                "role": "user",
                "content": [anthropic_image]
                if image_only
                else [before, anthropic_image, between, anthropic_image2, after],
            }
        ],
    )
    gemini_image = {"inlineData": {"mimeType": "image/png", "data": "aGVsbG8="}}
    gemini_image2 = {"inlineData": {"mimeType": "image/jpeg", "data": "d29ybGQ="}}
    assert gemini._convert_antigravity_messages([message]) == (
        [
            {
                "role": "user",
                "parts": [gemini_image]
                if image_only
                else [{"text": "before"}, gemini_image, {"text": "between"}, gemini_image2, {"text": "after"}],
            }
        ],
        None,
    )
