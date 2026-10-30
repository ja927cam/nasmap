from app.auth import create_access_token, decode_access_token, hash_password, verify_password
from app.models import User


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_missing_hash_is_not_valid():
    assert not verify_password("anything", None)


def test_access_token_roundtrip():
    user = User(id="00000000-0000-0000-0000-000000000001", email="a@example.org", role="editor")
    token, expires_in = create_access_token(user)
    payload = decode_access_token(token)
    assert payload["sub"] == str(user.id)
    assert payload["role"] == "editor"
    assert expires_in > 0
