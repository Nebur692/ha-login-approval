from app.messages import bridge_page_strings, build_notification, detect_browser_lang, extract_browser_name


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


def test_detect_browser_lang_spanish():
    assert detect_browser_lang("es-ES,es;q=0.9,en;q=0.8") == "es"


def test_detect_browser_lang_english():
    assert detect_browser_lang("en-US,en;q=0.9") == "en"


def test_detect_browser_lang_unsupported_defaults_to_english():
    assert detect_browser_lang("fr-FR,fr;q=0.9") == "en"


def test_detect_browser_lang_missing_header_defaults_to_english():
    assert detect_browser_lang(None) == "en"


def test_bridge_page_strings_spanish():
    strings = bridge_page_strings("es")
    assert strings["continue_button"] == "Continuar"


def test_bridge_page_strings_unknown_falls_back_to_english():
    strings = bridge_page_strings("de")
    assert strings["continue_button"] == "Continue"
