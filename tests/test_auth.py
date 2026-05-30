import hashlib
from app.api import auth


def test_hash_api_key():
    key = "grain_test123"
    h = auth.hash_api_key(key)
    assert isinstance(h, str)
    assert len(h) == 64
    assert h == hashlib.sha256(key.encode()).hexdigest()


def test_generate_api_key_prefix():
    key = auth.generate_api_key()
    assert key.startswith("grain_")


def test_extract_bearer_token_bearer():
    assert auth._extract_bearer_token("Bearer grain_abc123") == "grain_abc123"


def test_extract_bearer_token_raw():
    assert auth._extract_bearer_token("grain_abc123") == "grain_abc123"


def test_extract_bearer_token_empty():
    assert auth._extract_bearer_token(None) == ""
    assert auth._extract_bearer_token("") == ""


def test_build_telegram_link_url(monkeypatch):
    monkeypatch.setattr(auth.settings, "TELEGRAM_BOT_USERNAME", "higrain_bot")
    assert auth.build_telegram_link_url("abc123") == "https://t.me/higrain_bot?start=abc123"


def test_generate_code_is_6_digits():
    code = auth._generate_code()
    assert len(code) == 6
    assert code.isdigit()
