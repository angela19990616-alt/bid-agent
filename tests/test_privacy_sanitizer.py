from types import SimpleNamespace

from app.core.model_client import ModelClient
from app.core.privacy_sanitizer import PrivacySanitizer


def test_sensitive_values_are_replaced_and_restored_locally():
    sanitizer = PrivacySanitizer.load()
    original = (
        "联系人：张三，手机13800138000，邮箱zhangsan@example.com，"
        "身份证110105199001011234，联系地址：北京市朝阳区测试路1号"
    )

    safe, mapping = sanitizer.sanitize_text(original)

    assert "张三" not in safe
    assert "13800138000" not in safe
    assert "zhangsan@example.com" not in safe
    assert "110105199001011234" not in safe
    assert "北京市朝阳区测试路1号" not in safe
    assert PrivacySanitizer.restore(safe, mapping) == original


def test_model_client_sends_only_sanitized_message_and_restores_output():
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=kwargs["messages"][0]["content"]
                        )
                    )
                ],
                usage=None,
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    original = "联系人：李四，手机号13900139000"

    result = ModelClient(client=client).chat(
        [{"role": "user", "content": original}],
        task="extraction",
        max_tokens=100,
    )

    sent = calls[0]["messages"][0]["content"]
    assert "李四" not in sent
    assert "13900139000" not in sent
    assert result == original
