<div align="center">

# zitadel-ha-login-approval

*Approve or reject ZITADEL logins from a Home Assistant push notification — per account*

![Release](https://img.shields.io/github/v/release/Nebur692/zitadel-ha-login-approval?label=release&color=blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-30363D?logo=githubsponsors&logoColor=EA4AAA)](https://github.com/sponsors/Nebur692)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/nebur69265723)
[![PayPal](https://img.shields.io/badge/PayPal-donate-00457C?logo=paypal&logoColor=white)](https://paypal.me/0SkillS)

🇬🇧 [English](#english) · 🇪🇸 [Español](#español)

</div>

---

## English

### ✨ What this is

Instead of (or alongside) a traditional second factor like TOTP or WebAuthn, this project sends a
push notification with **Approve / Reject** buttons to your phone (or any device running the Home
Assistant Companion App) every time someone signs in with a given ZITADEL account. The login only
completes if you tap **Approve**.

- **Multiple devices per account** — an admin panel lets you pick one or more `notify.mobile_app_*`
  targets per ZITADEL user (e.g. your phone *and* your watch), discovered live from your own Home
  Assistant instance.
- **No database of its own** — the device mapping is stored as ZITADEL user metadata, so ZITADEL
  itself stays the single source of truth for which accounts exist.
- **Notification in your language** — detected once from Home Assistant's own configured language
  (`GET /api/config`), not hardcoded or bilingual.
- **Real login details in the notification** — the browser (name only, no version) and the source
  IP of the actual sign-in attempt.

### ⚠️ v1.0.0 scope — read this before setting it up

- **Approval happens *before* the password step, it does not replace it.** After approving on your
  phone, ZITADEL still asks for the password as normal. This is deliberate: the hook point used
  here (`CreateSession`) never carries the password in its payload — a *different* ZITADEL step
  (`SetSession`) does carry it in plain text, and this project intentionally never touches that
  step, so this service is never in a position to see or mishandle a real password. A genuinely
  passwordless "approve-only" login (like Microsoft Authenticator's push sign-in) needs this
  project's service to act as ZITADEL's own external Identity Provider instead of a webhook hook —
  a bigger, different architecture, planned as a future v2.0.0, not this one.
- **The notification cannot show which application you're logging into** (Zabbix, WordPress,
  etc.). Confirmed by inspecting the real `CreateSession` payload twice: ZITADEL creates sessions
  generically, before it knows which app will end up using them — that detail simply isn't
  available at this hook point.

### 📦 Installation

Requires: a ZITADEL v4+ instance with Actions V2, and Home Assistant with the Companion App
installed on at least one device. Environment variables:

| Variable | What it's for |
|---|---|
| `HA_BASE_URL` / `HA_TOKEN` | Your Home Assistant's internal URL and a [long-lived access token](https://developers.home-assistant.io/docs/auth_api/#long-lived-access-token). |
| `ZITADEL_BASE_URL` | Your ZITADEL's public URL (External Domain, with `https://`). |
| `ZITADEL_CLIENT_ID` / `ZITADEL_CLIENT_SECRET` | Credentials of a ZITADEL **machine user** (Users → New → Machine) with enough permission to list users and read/write user metadata — `IAM_OWNER` is the simplest role that covers this. |
| `ZITADEL_TARGET_SIGNING_KEY` | The signing key ZITADEL gives you when creating the Target below — see [Setting up ZITADEL](#-setting-up-zitadel-side-by-side) for exactly where to find it. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Login for this project's own `/admin` panel (HTTP Basic — a small internal tool, not worth a full session system). |
| `APPROVAL_TIMEOUT_SECONDS` | How long to wait for a tap before failing the login (default `120`). Must stay below ZITADEL's own 270s hard limit on Action targets. |
| `METADATA_KEY` | Don't touch unless you know why — the ZITADEL user metadata key the device list is stored under. |

A ready-to-use Unraid Community Applications template is included:
[`zitadel-ha-login-approval.xml`](zitadel-ha-login-approval.xml). Since the image isn't published
to any registry, build it locally first: `docker build -t zitadel-ha-login-approval:latest .`

### ⚙️ Setting up the ZITADEL side, step by step

This is the fiddly part, and the Console UI presents several choices with no explanation — here's
exactly what to pick.

1. **Console → Actions → Targets → Create.**
   - **Type: "REST Webhook"** — not "REST Call" or "REST Async". Async never waits for a response
     (useless here, we need to wait for your tap); REST Call also inspects the response *body*
     (meant for requests that need their content rewritten); REST Webhook only checks the **status
     code**, which is exactly what this service returns (200 on approve, 403 on reject/timeout).
   - **Payload type: "JSON"** (the default) — not "unspecified", JWT, or encrypted JWT. This is
     what includes the `zitadel-signature` header this service verifies.
   - **Endpoint:** `http://<this-container's-IP>:8000/webhook/create-session`.
   - **Timeout:** something between your `APPROVAL_TIMEOUT_SECONDS` and ZITADEL's 270s ceiling —
     150–180s leaves comfortable margin.
   - **"Interrupt on error": turn it ON.** ZITADEL's own warning here is accurate and worth taking
     seriously: if this service is down or misconfigured, **every login for accounts with a device
     configured will be blocked**, not just rejected. This project's design already includes a
     safety net for that: accounts with *no* device assigned in the admin panel are let through
     without being blocked at all.
   - After creating it, the Console may not display the signing key on screen. If so, open the
     Target's own detail view, or fetch it via the API (`GET /v2/actions/targets/{id}`) — unlike
     some other ZITADEL secrets, this one isn't a one-time reveal, it stays retrievable.
2. **Console → Actions → Actions → Create** (a separate section from Targets): condition
   **Request**, method `/zitadel.session.v2.SessionService/CreateSession`, targets: the one you
   just created.
3. **If creating the Target fails with `[invalid_argument] Errors.Target.DeniedURL`**: ZITADEL
   blocks Target endpoints on private IP ranges by default (SSRF protection) — this includes your
   entire home LAN. Add `ZITADEL_HTTPCLIENT_DENYLIST` to your **ZITADEL core container itself**
   (not this one) with the stock deny list minus `192.168.0.0/16` — see
   [Nebur692/unraid-zitadel-templates](https://github.com/Nebur692/unraid-zitadel-templates) for
   the exact value and more detail. Requires recreating the ZITADEL container, not just a restart.

### 🩹 Troubleshooting

- **Notification never arrives**: confirm the account has at least one device saved in `/admin`,
  and that the Execution (step 2 above) actually lists your Target — creating a Target does *not*
  automatically wire it to anything; the condition/target binding is a separate step easy to miss
  or accidentally clear.
- **Login completes instantly, way faster than a human could tap anything**: same cause as above —
  the Execution has no target attached, so `CreateSession` never actually calls this service.
- **Still asked for a password after approving**: expected in v1.0.0 — see the scope note above.

### 💙 Support

None of this would be possible without the community's support. If this project has been useful to
you, consider supporting it via [GitHub Sponsors](https://github.com/sponsors/Nebur692),
[Ko-fi](https://ko-fi.com/nebur69265723) or [PayPal](https://paypal.me/0SkillS) — every bit helps
keep it maintained.

### ⚠️ Disclaimer

Not affiliated with, endorsed by, or associated with ZITADEL, ZITADEL GmbH, or Home Assistant /
Nabu Casa Inc. Both are trademarks of their respective owners.

### 📜 License

[MIT](LICENSE)

---

## Español

### ✨ Qué es esto

En vez de (o además de) un segundo factor tradicional tipo TOTP o WebAuthn, este proyecto manda una
notificación con botones **Aprobar / Rechazar** a tu móvil (o cualquier dispositivo con la app de
Home Assistant instalada) cada vez que alguien inicia sesión con una cuenta concreta de ZITADEL. El
login solo se completa si pulsas **Aprobar**.

- **Varios dispositivos por cuenta** — un panel de administración te deja elegir uno o más
  `notify.mobile_app_*` por cada usuario de ZITADEL (p.ej. tu móvil *y* tu reloj), descubiertos en
  vivo desde tu propio Home Assistant.
- **Sin base de datos propia** — el mapeo de dispositivos se guarda como metadato de usuario de
  ZITADEL, así que ZITADEL sigue siendo la única fuente de verdad de qué cuentas existen.
- **Notificación en tu idioma** — detectado una vez desde el propio idioma configurado en Home
  Assistant (`GET /api/config`), no bilingüe fijo ni predefinido.
- **Detalles reales del login en la notificación** — el navegador (solo el nombre, sin versión) y
  la IP de origen del intento real.

### ⚠️ Alcance de la v1.0.0 — lee esto antes de montarlo

- **La aprobación ocurre *antes* del paso de la contraseña, no lo sustituye.** Tras aprobar en el
  móvil, ZITADEL sigue pidiendo la contraseña con normalidad. Es deliberado: el punto de enganche
  usado aquí (`CreateSession`) nunca lleva la contraseña en su payload — un paso *distinto* de
  ZITADEL (`SetSession`) sí la lleva en texto plano, y este proyecto evita deliberadamente tocar
  ese paso, para que este servicio nunca esté en posición de ver ni manejar mal una contraseña
  real. Un login realmente sin contraseña (tipo "aprobar desde el móvil" de Microsoft Authenticator)
  exigiría que este proyecto actuara como Proveedor de Identidad externo propio de ZITADEL, en vez
  de un webhook — una arquitectura mayor y distinta, planeada como una futura v2.0.0, no esta.
- **La notificación no puede mostrar a qué aplicación estás entrando** (Zabbix, WordPress, etc.).
  Confirmado inspeccionando el payload real de `CreateSession` dos veces: ZITADEL crea las
  sesiones de forma genérica, antes de saber qué app las va a usar — ese dato simplemente no está
  disponible en este punto de enganche.

### 📦 Instalación

Necesita: una instancia de ZITADEL v4+ con Actions V2, y Home Assistant con la app Companion
instalada en al menos un dispositivo. Variables de entorno:

| Variable | Para qué sirve |
|---|---|
| `HA_BASE_URL` / `HA_TOKEN` | La URL interna de tu Home Assistant y un [token de acceso de larga duración](https://developers.home-assistant.io/docs/auth_api/#long-lived-access-token). |
| `ZITADEL_BASE_URL` | La URL pública de tu ZITADEL (External Domain, con `https://`). |
| `ZITADEL_CLIENT_ID` / `ZITADEL_CLIENT_SECRET` | Credenciales de un **usuario máquina** de ZITADEL (Users → New → Machine) con permiso suficiente para listar usuarios y leer/escribir metadatos — `IAM_OWNER` es el rol más simple que lo cubre. |
| `ZITADEL_TARGET_SIGNING_KEY` | La clave de firma que ZITADEL te da al crear el Target de abajo — ver [Configurar el lado de ZITADEL](#-configurar-el-lado-de-zitadel-paso-a-paso) para saber exactamente dónde encontrarla. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Acceso al propio panel `/admin` de este proyecto (HTTP Basic — una herramienta interna pequeña, no compensa un sistema de sesiones completo). |
| `APPROVAL_TIMEOUT_SECONDS` | Cuánto esperar a que pulses antes de cortar el login (por defecto `120`). Debe quedarse por debajo del límite fijo de 270s de ZITADEL para los Targets de Actions. |
| `METADATA_KEY` | No tocar salvo que sepas por qué — la clave de metadato de usuario de ZITADEL donde se guarda la lista de dispositivos. |

Incluye una plantilla lista para Community Applications de Unraid:
[`zitadel-ha-login-approval.xml`](zitadel-ha-login-approval.xml). Como la imagen no está publicada
en ningún registro, constrúyela primero en local: `docker build -t zitadel-ha-login-approval:latest .`

### ⚙️ Configurar el lado de ZITADEL, paso a paso

Esta es la parte lioso, y la Consola presenta varias opciones sin explicarlas — esto es exactamente
lo que hay que elegir.

1. **Consola → Actions → Targets → Create.**
   - **Tipo: "REST Webhook"** — no "REST Call" ni "REST Async". Async nunca espera respuesta (inútil
     aquí, necesitamos esperar tu pulsación); REST Call además mira el *cuerpo* de la respuesta
     (pensado para peticiones que necesitan reescribirse); REST Webhook solo comprueba el **código
     de estado**, que es justo lo que devuelve este servicio (200 al aprobar, 403 al rechazar o
     agotar el tiempo).
   - **Tipo de carga útil: "JSON"** (el que viene por defecto) — no "no especificado", JWT, ni JWT
     cifrado. Es el que incluye la cabecera `zitadel-signature` que este servicio verifica.
   - **Punto de conexión:** `http://IP-de-este-contenedor:8000/webhook/create-session`.
   - **Tiempo de espera:** algo entre tu `APPROVAL_TIMEOUT_SECONDS` y el límite de 270s de ZITADEL
     — 150-180s deja margen de sobra.
   - **"Interrumpir en error": actívalo.** El aviso de ZITADEL aquí es real y hay que tomárselo en
     serio: si este servicio se cae o está mal configurado, **se bloquearán todos los logins de las
     cuentas con algún dispositivo asignado**, no solo se rechazarán. El diseño de este proyecto ya
     incluye una salida para eso: las cuentas *sin* ningún dispositivo asignado en el panel de
     administración dejan pasar el login sin bloquear nada.
   - Tras crearlo, puede que la Consola no te muestre la clave de firma en pantalla. Si es así,
     entra al detalle del propio Target, o consúltala por API (`GET /v2/actions/targets/{id}`) — a
     diferencia de otros secretos de ZITADEL, este no es de un solo vistazo, se puede recuperar.
2. **Consola → Actions → Actions → Create** (una sección separada de Targets): condición
   **Request**, método `/zitadel.session.v2.SessionService/CreateSession`, targets: el que acabas
   de crear.
3. **Si crear el Target falla con `[invalid_argument] Errors.Target.DeniedURL`**: ZITADEL bloquea
   por defecto los endpoints de Target en rangos de IP privados (protección SSRF) — esto incluye
   toda tu red local. Añade `ZITADEL_HTTPCLIENT_DENYLIST` al **propio contenedor principal de
   ZITADEL** (no a este) con la lista de fábrica menos `192.168.0.0/16` — ver
   [Nebur692/unraid-zitadel-templates](https://github.com/Nebur692/unraid-zitadel-templates) para
   el valor exacto y más detalle. Requiere recrear el contenedor de ZITADEL, no solo reiniciarlo.

### 🩹 Solución de problemas

- **La notificación nunca llega**: comprueba que la cuenta tiene al menos un dispositivo guardado en
  `/admin`, y que la Execution (paso 2 de arriba) de verdad lista tu Target — crear un Target **no**
  lo engancha automáticamente a nada; el enlace condición/target es un paso aparte, fácil de pasar
  por alto o de vaciar sin querer.
- **El login se completa al instante, mucho más rápido de lo que alguien podría pulsar nada**:
  misma causa que arriba — la Execution no tiene ningún target enganchado, así que `CreateSession`
  nunca llega a llamar a este servicio.
- **Sigue pidiendo contraseña después de aprobar**: esperado en la v1.0.0 — ver el aviso de alcance
  de arriba.

### 💙 Apoya el proyecto

Sin el apoyo de la comunidad estos proyectos no serían posibles. Si te ha resultado útil, puedes
apoyarlo vía [GitHub Sponsors](https://github.com/sponsors/Nebur692),
[Ko-fi](https://ko-fi.com/nebur69265723) o [PayPal](https://paypal.me/0SkillS) — cualquier
aportación ayuda a seguir manteniéndolo.

### ⚠️ Aviso legal

No afiliado, respaldado ni asociado con ZITADEL, ZITADEL GmbH, ni Home Assistant / Nabu Casa Inc.
Ambos son marcas registradas de sus respectivos propietarios.

### 📜 Licencia

[MIT](LICENSE)
