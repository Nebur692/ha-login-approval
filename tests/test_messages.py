from app.messages import (
    bridge_page_strings,
    build_notification,
    detect_browser_lang,
    extract_browser_name,
    recovery_warning_notification,
)


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


def test_build_notification_includes_location_when_geoip_available():
    text = build_notification("es", {
        "description": "Edge, 152.0.0.0", "ip": "1.2.3.4",
        "geo_city": "Madrid", "geo_country": "ES", "geo_asn_org": "Movistar",
    })
    assert "Ubicación: Madrid, ES, Movistar" in text["body"]


def test_build_notification_omits_location_line_without_geoip():
    text = build_notification("es", {"description": "Edge", "ip": "1.2.3.4"})
    assert "Ubicación" not in text["body"]


def test_build_notification_location_skips_missing_geo_fields():
    text = build_notification("en", {
        "description": "Edge", "ip": "1.2.3.4",
        "geo_city": None, "geo_country": "US", "geo_asn_org": None,
    })
    assert "Location: US" in text["body"]


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


def test_recovery_warning_exhausted_spanish():
    notification = recovery_warning_notification("es", remaining=0, ever_generated=True)
    assert notification["title"] == "Códigos de recuperación agotados"
    assert "panel de administración" in notification["body"]


def test_recovery_warning_exhausted_english():
    notification = recovery_warning_notification("en", remaining=0, ever_generated=True)
    assert notification["title"] == "Recovery codes exhausted"


def test_recovery_warning_never_generated_does_not_claim_a_code_was_used():
    """An account that never generated a batch was told "you've just used
    your last code", which is simply false — it never had one to use."""
    for lang, title in (("es", "Sin códigos de recuperación"), ("en", "No recovery codes")):
        notification = recovery_warning_notification(lang, remaining=0, ever_generated=False)
        assert notification["title"] == title
        body = notification["body"].lower()
        assert "usado" not in body and "used" not in body
        assert "agotad" not in body and "exhaust" not in body


def test_recovery_warning_exhausted_no_longer_claims_the_code_was_just_used():
    """The same warning fires after an ordinary approved login, not only
    right after consuming a code, so "you've just used" can't be asserted."""
    for lang in ("es", "en"):
        body = recovery_warning_notification(lang, remaining=0, ever_generated=True)["body"].lower()
        assert "acabas de usar" not in body
        assert "you've just used" not in body


def test_recovery_warning_low_includes_remaining_count_spanish():
    notification = recovery_warning_notification("es", remaining=2)
    assert notification["title"] == "Quedan pocos códigos de recuperación"
    assert "2" in notification["body"]


def test_recovery_warning_low_includes_remaining_count_english():
    notification = recovery_warning_notification("en", remaining=2)
    assert notification["title"] == "Recovery codes running low"
    assert "2" in notification["body"]


def test_recovery_warning_unknown_language_falls_back_to_english():
    notification = recovery_warning_notification("de", remaining=0)
    assert notification["title"] == "Recovery codes exhausted"
