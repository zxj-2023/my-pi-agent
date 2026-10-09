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


def test_empty_image_data_filtered():
    msg = Message(role="user", content=[{"type": "text", "text": "hi"}, {"type": "image", "data": "   ", "mime_type": "image/png"}])
    assert len(msg.content) == 1
    assert msg.content[0]["type"] == "text"


def test_image_jpg_normalized():
    msg = Message(role="user", content=[{"type": "image", "data": "abc", "mime_type": "image/jpg"}])
    assert msg.content[0]["mime_type"] == "image/jpeg"


def test_provider_role_contracts():
    config = Config(api_key="test")
    openai = OpenAIProvider(config, client=object())
    anthropic = AnthropicProvider(config, client=object())
    gemini = AntigravityProvider(config, client=object())

    img_msg = Message(role="tool", content=[{"type": "text", "text": "result"}, {"type": "image", "data": "abc", "mime_type": "image/png"}], metadata={"tool_call_id": "call_1"})
    # OpenAI tool 必须是 string
    conv = openai._convert_messages([img_msg])
    assert conv[0]["content"] == "result"
    assert isinstance(conv[0]["content"], str)

    # Anthropic assistant 严禁 image 块
    asst_msg = Message(role="assistant", content=[{"type": "text", "text": "hello"}, {"type": "image", "data": "abc", "mime_type": "image/png"}])
    _, a_conv = anthropic._convert_messages([asst_msg])
    assert a_conv[0]["content"] == [{"type": "text", "text": "hello"}]

    # Gemini system 过滤 inlineData
    sys_msg = Message(role="system", content=[{"type": "text", "text": "sys instruction"}, {"type": "image", "data": "abc", "mime_type": "image/png"}])
    _, sys_inst = gemini._convert_antigravity_messages([sys_msg])
    assert sys_inst["parts"] == [{"text": "sys instruction"}]

