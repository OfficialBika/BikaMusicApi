from app.security import (
    hash_secret,
    parse_api_key,
    sign_playback,
    verify_playback_signature,
)


def test_api_key_parser_keeps_underscores_in_secret():
    token = "bika_live_ab12cd34ef56_secret_with_underscores_and_0123456789abcdef"
    assert parse_api_key(token) == (
        "ab12cd34ef56",
        "secret_with_underscores_and_0123456789abcdef",
    )


def test_api_key_parser_rejects_malformed_keys():
    assert parse_api_key(None) is None
    assert parse_api_key("not-a-key") is None
    assert parse_api_key("bika_live_bad_short") is None
    assert parse_api_key("bika_live_ab12cd34ef56_too-short") is None


def test_secret_hash_is_peppered_and_deterministic():
    secret = "example-secret-material"
    first = hash_secret(secret, pepper="a" * 64)
    second = hash_secret(secret, pepper="a" * 64)
    other_pepper = hash_secret(secret, pepper="b" * 64)
    assert first == second
    assert first != other_pepper
    assert len(first) == 64


def test_playback_signature_validity_and_tampering():
    now = 2_000_000_000
    expires = now + 300
    secret = "s" * 64
    signature = sign_playback("track-1", "ab12cd34ef56", expires, secret=secret)
    assert verify_playback_signature(
        "track-1", "ab12cd34ef56", expires, signature,
        secret=secret, now=now,
    )
    assert not verify_playback_signature(
        "track-2", "ab12cd34ef56", expires, signature,
        secret=secret, now=now,
    )
    assert not verify_playback_signature(
        "track-1", "ab12cd34ef56", expires, signature,
        secret=secret, now=expires + 1,
    )


def test_playback_signature_rejects_unreasonably_long_expiry():
    now = 2_000_000_000
    expires = now + 7200
    signature = sign_playback("track-1", "ab12cd34ef56", expires, secret="s" * 64)
    assert not verify_playback_signature(
        "track-1", "ab12cd34ef56", expires, signature,
        secret="s" * 64, now=now,
    )
