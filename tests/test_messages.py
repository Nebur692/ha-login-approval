from app.messages import build_notification, extract_browser_name


def test_extract_browser_name_drops_version_and_rest():
    raw = "Edge, 152.0.0.0, ,    , Blink, 152.0.0.0, , Windows, 10, "
    assert extract_browser_name(raw) == "Edge"


def test_extract_browser_name_handles_empty_string():
    assert extract_browser_name("") == "unknown browser"


def test_build_notification_spanish():
    text = build_notification("es", {"description": "Edge, 152.0.0.0", "ip": "1.2.3.4"})
    assert text["title"] == "Intento de inicio de sesión"
    assert "Edge" in text["body"]
    assert "152.0.0.0" not in text["body"]  # version must not leak into the message
    assert "1.2.3.4" in text["body"]
    assert text["approve"] == "Aprobar"
    assert text["reject"] == "Rechazar"


def test_build_notification_english():
    text = build_notification("en", {"description": "Chrome, 120.0", "ip": "5.6.7.8"})
    assert text["title"] == "Sign-in attempt"
    assert text["approve"] == "Approve"


def test_build_notification_unknown_language_falls_back_to_english():
    text = build_notification("de", {"description": "", "ip": "1.1.1.1"})
    assert text["title"] == "Sign-in attempt"


def test_build_notification_missing_user_agent_fields_does_not_crash():
    text = build_notification("es", {})
    assert "unknown browser" in text["body"]
    assert "unknown" in text["body"]
