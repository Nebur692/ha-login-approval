"""The admin panel's words, in Spanish (Spain) and English, picked from the
browser's Accept-Language like the sign-in page (messages.detect_browser_lang).

Every page gets the chosen set as `t` (see routers/admin/_templates.py), so a
page cannot end up half in one language: a test checks both sets carry the
same keys and that every `t.<key>` a template uses exists.
"""
from fastapi import Request

from app.messages import detect_browser_lang

STRINGS = {
    "es": {
        # navigation
        "nav_home": "Inicio", "nav_accounts": "Cuentas", "nav_audit": "Auditoría",
        "nav_recovery": "Códigos de recuperación", "nav_blocked": "IP bloqueadas", "nav_branding": "Marca",
        "nav_signing_key": "Clave de firma", "nav_activity": "Actividad", "sign_out": "Cerrar sesión",
        "act_yes": "SÍ tienes que hacer algo.", "act_no": "NO tienes que hacer nada.",
        "save": "Guardar",
        # sign in
        "login_title": "Entrar", "login_heading": "Panel de administración",
        "username": "Usuario", "password": "Contraseña", "sign_in": "Entrar",
        "panel_off": "El panel de administración está apagado: {problem} Pon en ADMIN_PASSWORD una de al menos 12 caracteres y recrea el contenedor. Los inicios de sesión a través de este servicio siguen funcionando mientras tanto; solo está apagado este panel.",
        "pw_short": "ADMIN_PASSWORD tiene menos de {n} caracteres.",
        "pw_known": "ADMIN_PASSWORD es una contraseña por defecto o muy conocida.",
        "login_wrong": "Usuario o contraseña incorrectos.",
        "login_locked": "Demasiados intentos fallidos. Vuelve a intentarlo dentro de 15 minutos.",
        # refused change
        "refused_title": "No guardado", "refused_heading": "No se ha cambiado nada",
        "refused_session": "Tu sesión había terminado (30 minutos sin uso, 8 horas desde que entraste, o se cerró desde Actividad), así que este cambio no se ha guardado.",
        "refused_csrf": "Este formulario no llevaba el código de seguridad de tu sesión (suele ser una página que se quedó abierta desde antes de volver a entrar), así que el cambio no se ha guardado.",
        "back_to_panel": "Volver al panel", "sign_in_again": "Volver a entrar",
        # home
        "home_title": "Inicio", "home_heading": "De un vistazo",
        "home_accounts": "{total} cuenta(s), {with_devices} con al menos un dispositivo asignado.",
        "home_blocked": "{n} IP bloqueada(s) ahora mismo", "review": "revisar",
        "home_recovery": "Códigos de recuperación que quedan",
        "home_recovery_none": "Ninguna cuenta tiene códigos de recuperación generados todavía.",
        "account": "Cuenta", "remaining": "Quedan",
        # accounts
        "accounts_title": "Cuentas", "accounts_heading": "Cuentas sin contraseña",
        "accounts_intro": "Las cuentas que usa el inicio de sesión sin contraseña, independientes de cualquier proveedor (ZITADEL, Keycloak, Authentik…). Una cuenta sin ningún dispositivo marcado nunca puede completar un inicio de sesión.",
        "accounts_no_devices": "Home Assistant no tiene ningún dispositivo notify.mobile_app_*.",
        "accounts_ha_down": "Home Assistant no responde, así que no se pueden listar sus dispositivos. Las cuentas se muestran tal cual y se podrán editar en cuanto responda.",
        "add_account": "Añadir cuenta", "no_device": "Ningún dispositivo asignado.",
        "device_missing": "no aparece ahora en Home Assistant: se conserva mientras esté marcado",
        # audit
        "audit_title": "Auditoría", "audit_heading": "Historial de intentos de inicio de sesión",
        "audit_none": "Todavía no hay intentos registrados para esta cuenta.",
        "when": "Cuándo", "result": "Resultado", "browser": "Navegador", "location": "Ubicación",
        "audit_events": {
            "approved": "aprobado", "rejected": "rechazado", "timeout": "sin respuesta",
            "recovery_code_used": "código de recuperación usado", "send_failed": "no se pudo enviar",
            "blocked": "bloqueado", "denied": "denegado",
        },
        # recovery
        "recovery_title": "Códigos de recuperación", "recovery_heading": "Códigos de recuperación",
        "new_codes_for": "Códigos nuevos para {email}",
        "codes_once": "Se muestran una sola vez: cópialos o guárdalos ahora, no se pueden volver a ver. Generar un lote nuevo invalida al momento todos los anteriores.",
        "generate": "Generar", "regenerate": "Regenerar",
        # blocked IPs
        "blocked_title": "IP bloqueadas", "blocked_heading": "IP bloqueadas",
        "blocked_intro": "3 fallos seguidos (rechazos explícitos y códigos de recuperación erróneos) en la misma cuenta y desde la misma IP bloquean esa pareja; nunca se bloquea una IP para todas las cuentas.",
        "blocked_none": "Ahora mismo no hay ninguna IP bloqueada.", "blocked_at": "Bloqueada", "unblock": "Desbloquear",
        # branding
        "branding_title": "Marca", "branding_heading": "Marca de la página de inicio de sesión",
        "branding_intro": "Se muestra en la página pública de inicio de sesión. Se acepta cualquier formato y tamaño de imagen: el logo y el favicon se convierten a PNG y el fondo a JPEG, cada uno reducido a un tamaño razonable.",
        "title_field": "Título", "logo": "Logo", "background": "Fondo", "favicon": "Favicon", "current": "Actual:",
        # signing key
        "key_title": "Clave de firma", "key_heading": "Clave de firma",
        "key_intro": "La clave que firma cada id_token que emite este servicio. Los proveedores la encuentran en /jwks.json y recogen una nueva por su cuenta.",
        "key_id": "ID de la clave", "created": "Creada", "state": "Estado", "signing": "firmando",
        "retired": "retirada el {at} UTC; sigue sirviendo para verificar hasta que acabe el solape",
        "rotate_heading": "Rotar",
        "rotate_intro": "Una clave nueva empieza a firmar al momento. La actual sigue sirviendo para verificar durante {minutes} minutos y después se borra.",
        "rotate_discard": "Borrar la clave actual ahora en su lugar, si puede haberse filtrado. Un inicio de sesión que termine justo en ese momento falla y hay que repetirlo.",
        "rotate_button": "Rotar la clave de firma",
        # activity
        "activity_title": "Actividad", "activity_heading": "Actividad del panel",
        "signed_in_now": "Con la sesión abierta ahora", "user": "Usuario", "since": "Desde",
        "last_seen": "Último uso", "from": "Desde dónde", "this_one": "(esta)",
        "last_events": "Últimos {n} sucesos", "nothing_yet": "Todavía no hay nada registrado.",
        "event": "Suceso", "detail": "Detalle",
        "events": {
            "login_ok": "entrada", "login_failed": "entrada fallida", "login_refused": "entrada rechazada",
            "logout": "salida", "session_ended": "sesión cerrada", "account_saved": "cuenta guardada",
            "recovery_codes_generated": "códigos generados", "ip_unblocked": "IP desbloqueada",
            "branding_saved": "marca guardada", "signing_key_rotated": "clave rotada",
        },
    },
    "en": {
        "nav_home": "Home", "nav_accounts": "Accounts", "nav_audit": "Audit",
        "nav_recovery": "Recovery codes", "nav_blocked": "Blocked IPs", "nav_branding": "Branding",
        "nav_signing_key": "Signing key", "nav_activity": "Activity", "sign_out": "Sign out",
        "act_yes": "You DO need to do something.", "act_no": "You do NOT need to do anything.",
        "save": "Save",
        "login_title": "Sign in", "login_heading": "Admin panel",
        "username": "Username", "password": "Password", "sign_in": "Sign in",
        "panel_off": "The admin panel is turned off: {problem} Set ADMIN_PASSWORD to something at least 12 characters long and recreate the container. Sign-ins through this service keep working meanwhile — only this panel is off.",
        "pw_short": "ADMIN_PASSWORD is shorter than {n} characters.",
        "pw_known": "ADMIN_PASSWORD is a default or well-known password.",
        "login_wrong": "Wrong username or password.",
        "login_locked": "Too many failed attempts. Try again in 15 minutes.",
        "refused_title": "Not saved", "refused_heading": "Nothing was changed",
        "refused_session": "Your session had ended (30 minutes without use, 8 hours since signing in, or signed out from Activity), so this change was not saved.",
        "refused_csrf": "This form did not carry your session's security token — usually a page left open from before you signed in again — so the change was not saved.",
        "back_to_panel": "Back to the panel", "sign_in_again": "Sign in again",
        "home_title": "Home", "home_heading": "At a glance",
        "home_accounts": "{total} account(s), {with_devices} with at least one device assigned.",
        "home_blocked": "{n} IP(s) currently blocked", "review": "review",
        "home_recovery": "Recovery codes remaining",
        "home_recovery_none": "No account has any recovery codes generated yet.",
        "account": "Account", "remaining": "Remaining",
        "accounts_title": "Accounts", "accounts_heading": "Passwordless accounts",
        "accounts_intro": "Accounts used by the passwordless sign-in, independent of any relying party (ZITADEL, Keycloak, Authentik, ...). An account with no device checked can never complete a sign-in.",
        "accounts_no_devices": "No notify.mobile_app_* device found in Home Assistant.",
        "accounts_ha_down": "Home Assistant isn't answering, so its devices can't be listed. The accounts are shown as they are, and can be edited again once it answers.",
        "add_account": "Add account", "no_device": "No device assigned.",
        "device_missing": "not in Home Assistant right now: kept while it stays checked",
        "audit_title": "Audit", "audit_heading": "Login attempt history",
        "audit_none": "No login attempts recorded for this account yet.",
        "when": "When", "result": "Result", "browser": "Browser", "location": "Location",
        "audit_events": {
            "approved": "approved", "rejected": "rejected", "timeout": "timeout",
            "recovery_code_used": "recovery code used", "send_failed": "send failed",
            "blocked": "blocked", "denied": "denied",
        },
        "recovery_title": "Recovery codes", "recovery_heading": "Recovery codes",
        "new_codes_for": "New codes for {email}",
        "codes_once": "Shown once — copy or save these now, they can't be retrieved again. Generating a new batch invalidates every previous code immediately.",
        "generate": "Generate", "regenerate": "Regenerate",
        "blocked_title": "Blocked IPs", "blocked_heading": "Blocked IPs",
        "blocked_intro": "3 consecutive failures (explicit rejects + wrong recovery codes) on the same account + IP block that pair — never a global IP block.",
        "blocked_none": "No IP is currently blocked.", "blocked_at": "Blocked at", "unblock": "Unblock",
        "branding_title": "Branding", "branding_heading": "Sign-in page branding",
        "branding_intro": "Shown on the public sign-in page. Any image format/size is accepted — logo and favicon are converted to PNG, background to JPEG, each resized down to a sane maximum.",
        "title_field": "Title", "logo": "Logo", "background": "Background", "favicon": "Favicon", "current": "Current:",
        "key_title": "Signing key", "key_heading": "Signing key",
        "key_intro": "The key that signs every id_token this service issues. Relying parties find it in /jwks.json and pick up a new one on their own.",
        "key_id": "Key ID", "created": "Created", "state": "State", "signing": "signing",
        "retired": "retired {at} UTC — still verifies until the overlap ends",
        "rotate_heading": "Rotate",
        "rotate_intro": "A new key starts signing straight away. The current one keeps verifying for {minutes} minutes, then is deleted.",
        "rotate_discard": "Delete the current key now instead — if it may have leaked. A login completing at that exact moment fails and has to be retried.",
        "rotate_button": "Rotate signing key",
        "activity_title": "Activity", "activity_heading": "Admin activity",
        "signed_in_now": "Signed in now", "user": "User", "since": "Since",
        "last_seen": "Last seen", "from": "From", "this_one": "(this one)",
        "last_events": "Last {n} events", "nothing_yet": "Nothing recorded yet.",
        "event": "Event", "detail": "Detail",
        "events": {
            "login_ok": "signed in", "login_failed": "failed sign-in", "login_refused": "sign-in refused",
            "logout": "signed out", "session_ended": "session ended", "account_saved": "account saved",
            "recovery_codes_generated": "codes generated", "ip_unblocked": "IP unblocked",
            "branding_saved": "branding saved", "signing_key_rotated": "key rotated",
        },
    },
}


def lang_for(request: Request) -> str:
    return detect_browser_lang(request.headers.get("accept-language"))


def strings_for(request: Request) -> dict:
    return STRINGS[lang_for(request)]
