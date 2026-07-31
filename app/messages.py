"""Builds the notification text in a single language (HA's configured
language, falling back to English for anything we don't have a translation
for), enriched with real details of the login attempt.

Note: ZITADEL's CreateSession payload — confirmed by capturing two real
requests during this project's design phase — never includes which
application/service the session will end up being used for (SAML SP, OIDC
client, etc.). Session creation happens generically, before ZITADEL knows
which app the login will complete for, so that detail genuinely isn't
available at this hook point. Only the browser and the source IP are."""

_TEMPLATES = {
    "es": {
        "title": "Intento de inicio de sesión",
        "body": "Navegador: {browser}\nIP: {ip}{location}\n\n¿Eres tú?",
        "location_label": "Ubicación",
        "approve": "Aprobar",
        "reject": "Rechazar",
    },
    "en": {
        "title": "Sign-in attempt",
        "body": "Browser: {browser}\nIP: {ip}{location}\n\nWas this you?",
        "location_label": "Location",
        "approve": "Approve",
        "reject": "Reject",
    },
}
_DEFAULT_LANG = "en"


def extract_browser_name(description: str) -> str:
    """ZITADEL's userAgent.description is a raw, comma-separated dump from
    its device-fingerprinting library (e.g. 'Edge, 152.0.0.0, ,    , Blink,
    152.0.0.0, , Windows, 10, ') — the browser name, with no version
    number, is reliably always the first field."""
    first = description.split(",", 1)[0].strip()
    return first or "unknown browser"


def build_notification(lang: str, user_agent: dict) -> dict:
    """Returns {title, body, approve, reject} in a single language, with the
    browser/IP details from the CreateSession payload's userAgent field
    filled in. Location/ISP (geo_city/geo_country/geo_asn_org) are optional —
    left out of the body entirely when GeoIP isn't configured or the lookup
    came up empty, rather than showing a blank "Location: " line."""
    template = _TEMPLATES.get(lang, _TEMPLATES[_DEFAULT_LANG])
    browser = extract_browser_name(user_agent.get("description", ""))
    ip = user_agent.get("ip", "unknown")
    geo_parts = [p for p in (user_agent.get("geo_city"), user_agent.get("geo_country"), user_agent.get("geo_asn_org")) if p]
    location = f"\n{template['location_label']}: {', '.join(geo_parts)}" if geo_parts else ""
    return {
        "title": template["title"],
        "body": template["body"].format(browser=browser, ip=ip, location=location),
        "approve": template["approve"],
        "reject": template["reject"],
    }


_RECOVERY_WARNING_TEMPLATES = {
    "es": {
        "exhausted_title": "Códigos de recuperación agotados",
        "exhausted_body": (
            "Acabas de usar tu último código de recuperación de un solo uso para esta cuenta — "
            "genera un lote nuevo desde el panel de administración cuanto antes."
        ),
        "low_title": "Quedan pocos códigos de recuperación",
        "low_body": "Solo quedan {remaining} código(s) de recuperación para esta cuenta.",
    },
    "en": {
        "exhausted_title": "Recovery codes exhausted",
        "exhausted_body": (
            "You've just used your last one-time recovery code for this account — generate a "
            "new batch from the admin panel as soon as possible."
        ),
        "low_title": "Recovery codes running low",
        "low_body": "Only {remaining} recovery code(s) left for this account.",
    },
}
_RECOVERY_WARNING_DEFAULT_LANG = "en"


def recovery_warning_notification(lang: str, remaining: int) -> dict:
    """Returns {title, body} for the low/exhausted recovery-codes push
    warning, in HA's configured language — same source as the sign-in
    notification itself (build_notification/get_ha_language), since this
    fires from background approval-flow code with no browser request to
    read an Accept-Language header from."""
    template = _RECOVERY_WARNING_TEMPLATES.get(lang, _RECOVERY_WARNING_TEMPLATES[_RECOVERY_WARNING_DEFAULT_LANG])
    if remaining == 0:
        return {"title": template["exhausted_title"], "body": template["exhausted_body"]}
    return {"title": template["low_title"], "body": template["low_body"].format(remaining=remaining)}


_BRIDGE_PAGE_STRINGS = {
    "es": {
        "page_title": "Iniciar sesión",
        "email_prompt": "Escribe tu email para continuar.",
        "continue_button": "Continuar",
        "waiting_message": "Comprueba tu móvil y aprueba la solicitud de inicio de sesión…",
        "still_nothing": "¿Sigue sin llegar? Puedes:",
        "resend_button": "Reenviar la notificación",
        "recovery_button": "Usar un código de recuperación",
        "recovery_prompt": "Escribe un código de recuperación de un solo uso para tu cuenta.",
        "recovery_submit_button": "Iniciar sesión con código de recuperación",
        "go_back_button": "← Volver al inicio de sesión",
        "error_generic": "Algo ha ido mal. Inténtalo de nuevo.",
        "error_recovery_invalid": "Ese código de recuperación no es válido.",
        "error_not_approved": "El inicio de sesión no se ha aprobado.",
    },
    "en": {
        "page_title": "Sign in",
        "email_prompt": "Enter your email to continue.",
        "continue_button": "Continue",
        "waiting_message": "Check your phone and approve the sign-in request…",
        "still_nothing": "Still nothing? You can:",
        "resend_button": "Resend the notification",
        "recovery_button": "Use a recovery code",
        "recovery_prompt": "Enter a one-time recovery code for your account.",
        "recovery_submit_button": "Sign in with recovery code",
        "go_back_button": "← Back to login",
        "error_generic": "Something went wrong. Please try again.",
        "error_recovery_invalid": "That recovery code isn't valid.",
        "error_not_approved": "Sign-in was not approved.",
    },
}
_BRIDGE_DEFAULT_LANG = "en"


def detect_browser_lang(accept_language_header: str | None) -> str:
    """Picks 'es' or 'en' from the browser's own Accept-Language header —
    this is what a real visitor's browser sends, independent of whatever
    language Home Assistant happens to be configured in (that's a separate,
    unrelated detection used only for the push notification text)."""
    if accept_language_header and accept_language_header.strip().lower().startswith("es"):
        return "es"
    return _BRIDGE_DEFAULT_LANG


def bridge_page_strings(lang: str) -> dict:
    return _BRIDGE_PAGE_STRINGS.get(lang, _BRIDGE_PAGE_STRINGS[_BRIDGE_DEFAULT_LANG])
