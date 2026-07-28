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
