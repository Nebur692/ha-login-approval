"""Builds the notification text in a single language (HA's configured
language, falling back to English for anything we don't have a translation
for), enriched with real details of the login attempt.

The app being signed in to never arrives with the login itself; when ZITADEL
can be asked, app/target_app.py finds it and it heads the body. Without it the
body is browser, IP and location only."""

from app import burburito

_TEMPLATES = {
    "es": {
        "title": "Intento de inicio de sesión",
        "body": "{app}Navegador: {browser}\nIP: {ip}{location}\n\n¿Eres tú?",
        "app_label": "App",
        "location_label": "Ubicación",
        "approve": "Aprobar",
        "reject": "Rechazar",
    },
    "en": {
        "title": "Sign-in attempt",
        "body": "{app}Browser: {browser}\nIP: {ip}{location}\n\nWas this you?",
        "app_label": "App",
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
    app = f"{template['app_label']}: {user_agent['app']}\n" if user_agent.get("app") else ""
    return {
        "title": template["title"],
        "body": template["body"].format(app=app, browser=browser, ip=ip, location=location),
        "approve": template["approve"],
        "reject": template["reject"],
    }


_RECOVERY_WARNING_TEMPLATES = {
    "es": {
        "never_title": "Sin códigos de recuperación",
        "never_body": (
            "Esta cuenta no tiene ningún código de recuperación configurado, así que no hay forma "
            "de entrar si pierdes el acceso a tus dispositivos. Genera un lote desde el panel de "
            "administración."
        ),
        "exhausted_title": "Códigos de recuperación agotados",
        "exhausted_body": (
            "Ya no queda ningún código de recuperación sin usar en esta cuenta — genera un lote "
            "nuevo desde el panel de administración cuanto antes."
        ),
        "low_title": "Quedan pocos códigos de recuperación",
        "low_body": "Solo quedan {remaining} código(s) de recuperación para esta cuenta.",
    },
    "en": {
        "never_title": "No recovery codes",
        "never_body": (
            "This account has no recovery codes set up, so there is no way back in if you lose "
            "access to your devices. Generate a batch from the admin panel."
        ),
        "exhausted_title": "Recovery codes exhausted",
        "exhausted_body": (
            "There are no unused recovery codes left on this account — generate a new batch from "
            "the admin panel as soon as possible."
        ),
        "low_title": "Recovery codes running low",
        "low_body": "Only {remaining} recovery code(s) left for this account.",
    },
}
_RECOVERY_WARNING_DEFAULT_LANG = "en"


def recovery_warning_notification(lang: str, remaining: int, *, ever_generated: bool = True) -> dict:
    """Returns {title, body} for the low/exhausted recovery-codes push
    warning, in HA's configured language — same source as the sign-in
    notification itself (build_notification/get_ha_language), since this
    fires from background approval-flow code with no browser request to
    read an Accept-Language header from.

    `ever_generated` separates "you have run out" from "you never had any":
    this warning fires both after a code is consumed and after an ordinary
    approved login, so wording that assumes a code was just used is plainly
    wrong for an account that never generated a batch at all.
    """
    template = _RECOVERY_WARNING_TEMPLATES.get(lang, _RECOVERY_WARNING_TEMPLATES[_RECOVERY_WARNING_DEFAULT_LANG])
    footer_lang = lang if lang in _RECOVERY_WARNING_TEMPLATES else _RECOVERY_WARNING_DEFAULT_LANG
    if remaining == 0 and not ever_generated:
        title, body, key = template["never_title"], template["never_body"], "aviso/recibir-aviso/falta-config"
    elif remaining == 0:
        title, body, key = template["exhausted_title"], template["exhausted_body"], "aviso/recibir-aviso/limite-propio"
    else:
        title, body = template["low_title"], template["low_body"].format(remaining=remaining)
        key = "aviso/recibir-aviso/regla-propia"
    return {"title": title, "body": with_burburito(body, key, footer_lang)}


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
        "returning_in": "Volviendo a la aplicación en {s} s…",
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
        "returning_in": "Going back to the app in {s} s…",
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


# What went wrong on the sign-in page, in the reader's words, keyed by the
# short name the page's script uses. Each has its burburito key; the page
# shows the message, whether the reader needs to act, and the footer.
_BRIDGE_PROBLEMS = {
    "denied": ("login/iniciar-sesion/no-autorizado", {
        "es": "Esta cuenta no puede iniciar sesión así ahora mismo.",
        "en": "This account can't sign in this way right now.",
    }),
    "rejected": ("login/aprobar-acceso/cancelado", {
        "es": "Se ha pulsado «Rechazar» en el móvil, así que no se ha iniciado sesión.",
        "en": "“Reject” was tapped on the phone, so you have not been signed in.",
    }),
    "timeout": ("login/aprobar-acceso/tiempo-agotado", {
        "es": "Nadie ha respondido a la notificación a tiempo.",
        "en": "Nobody answered the notification in time.",
    }),
    "send_failed": ("login/aprobar-acceso/error-remoto", {
        "es": "No se ha podido enviar la notificación al móvil. Puedes entrar con un código de recuperación.",
        "en": "The notification could not be sent to your phone. You can sign in with a recovery code.",
    }),
    "expired": ("login/iniciar-sesion/codigo-caducado", {
        "es": "Este intento de inicio de sesión ha caducado. Vuelve a la aplicación y empieza de nuevo.",
        "en": "This sign-in attempt has expired. Go back to the app and start again.",
    }),
    "conflict": ("login/iniciar-sesion/conflicto-estado", {
        "es": "Este intento ya iba por otro paso, quizá desde otra pestaña. Vuelve a la aplicación y empieza de nuevo.",
        "en": "This sign-in attempt had already moved on, maybe in another tab. Go back to the app and start again.",
    }),
    "recovery_invalid": ("login/recuperar-acceso/credencial-invalida", {
        "es": "Ese código de recuperación no es válido.",
        "en": "That recovery code isn't valid.",
    }),
    "recovery_not_yet": ("login/recuperar-acceso/regla-propia", {
        "es": "Todavía no se puede usar un código de recuperación. Espera a que la página te lo ofrezca.",
        "en": "A recovery code can't be used yet. Wait until the page offers it.",
    }),
    "offline": ("login/iniciar-sesion/sin-conexion", {
        "es": "No hay conexión con el servidor. Comprueba tu conexión y recarga la página.",
        "en": "The server can't be reached. Check your connection and reload the page.",
    }),
    "bad_client": ("login/iniciar-sesion/config-invalida", {
        "es": "Este inicio de sesión no está bien configurado, así que no se puede continuar.",
        "en": "This sign-in isn't set up correctly, so it can't continue.",
    }),
    "bad_request": ("login/iniciar-sesion/dato-invalido", {
        "es": "La petición de inicio de sesión ha llegado mal formada, así que no se puede continuar.",
        "en": "The sign-in request arrived malformed, so it can't continue.",
    }),
}
_ACT_LINE = {
    True: {"es": "SÍ tienes que hacer algo.", "en": "You DO need to do something."},
    False: {"es": "NO tienes que hacer nada.", "en": "You do NOT need to do anything."},
}


def bridge_problem(name: str, lang: str) -> dict:
    """{message, act, footer, label, code} for one problem on the sign-in page."""
    lang = lang if lang in ("es", "en") else _BRIDGE_DEFAULT_LANG
    key, texts = _BRIDGE_PROBLEMS[name]
    footer = burburito.footer(key, lang)
    return {
        "message": texts[lang],
        "act": _ACT_LINE[footer["act"]][lang],
        "footer": footer["text"],
        "label": footer["label"],
        "code": footer["code"],
    }


def bridge_problems(lang: str) -> dict:
    """Every problem the sign-in page can show, ready for its script: the page
    renders them itself, so it needs no request to explain a failed one."""
    return {name: bridge_problem(name, lang) for name in _BRIDGE_PROBLEMS}


def with_burburito(body: str, key: str, lang: str) -> str:
    """A push-notification body with the act line and burburito footer at the end."""
    lang = lang if lang in ("es", "en") else "en"
    footer = burburito.footer(key, lang)
    return f"{body}\n\n{_ACT_LINE[footer['act']][lang]}\n{footer['text']}\n{footer['label']}: {footer['code']}"
