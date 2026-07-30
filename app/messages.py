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
        "body": "Navegador: {browser}\nIP: {ip}\n\n¿Eres tú?",
        "approve": "Aprobar",
        "reject": "Rechazar",
    },
    "en": {
        "title": "Sign-in attempt",
        "body": "Browser: {browser}\nIP: {ip}\n\nWas this you?",
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
    filled in."""
    template = _TEMPLATES.get(lang, _TEMPLATES[_DEFAULT_LANG])
    browser = extract_browser_name(user_agent.get("description", ""))
    ip = user_agent.get("ip", "unknown")
    return {
        "title": template["title"],
        "body": template["body"].format(browser=browser, ip=ip),
        "approve": template["approve"],
        "reject": template["reject"],
    }


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
