import hashlib
import hmac
from types import SimpleNamespace

from app.api import auth


def _telegram_widget_hash(payload: dict, bot_token: str) -> str:
    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted((k, v) for k, v in payload.items() if k != "hash" and v)
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    return hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def test_verify_telegram_login_widget_signature(monkeypatch):
    bot_token = "123456:widget-test-token"
    monkeypatch.setattr(auth.settings, "TELEGRAM_BOT_TOKEN", bot_token)

    payload = {
        "id": 123456789,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "username": "adalovelace",
        "photo_url": "https://t.me/i/userpic/320/abc.jpg",
        "auth_date": 1710000000,
    }
    payload["hash"] = _telegram_widget_hash(payload, bot_token)

    data = auth.TelegramLoginData(**payload)

    assert auth._verify_telegram_login(data) is True


def test_verify_telegram_login_widget_signature_rejects_bad_hash(monkeypatch):
    monkeypatch.setattr(auth.settings, "TELEGRAM_BOT_TOKEN", "123456:widget-test-token")

    data = auth.TelegramLoginData(
        id=123456789,
        first_name="Ada",
        last_name="Lovelace",
        username="adalovelace",
        photo_url="https://t.me/i/userpic/320/abc.jpg",
        auth_date=1710000000,
        hash="deadbeef",
    )

    assert auth._verify_telegram_login(data) is False


def test_build_telegram_link_url(monkeypatch):
    monkeypatch.setattr(auth.settings, "TELEGRAM_BOT_USERNAME", "higrain_bot")

    assert auth.build_telegram_link_url("abc123") == "https://t.me/higrain_bot?start=abc123"