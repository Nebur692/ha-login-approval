<div align="center">

# ha-login-approval

*Truly passwordless sign-in, approved from your phone — for ZITADEL, Keycloak, Authentik, or any standard OIDC identity provider*

![Release](https://img.shields.io/github/v/release/Nebur692/ha-login-approval?label=release&color=blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-30363D?logo=githubsponsors&logoColor=EA4AAA)](https://github.com/sponsors/Nebur692)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/nebur69265723)
[![PayPal](https://img.shields.io/badge/PayPal-donate-00457C?logo=paypal&logoColor=white)](https://paypal.me/0SkillS)

🇬🇧 [English](#english) · 🇪🇸 [Español](#español)

</div>

---

## English

### ✨ What this is

This project turns your Home Assistant Companion App into your login method. Instead of typing a
password, you type your email, get a push notification with **Approve / Reject** buttons, and
tapping Approve logs you in — no password involved at any point.

It does this by acting as a **generic external OIDC identity provider**: any relying party that
supports "log in with an external OIDC provider" (ZITADEL, Keycloak, Authentik, and in principle
any other standards-compliant one) can redirect to this service, and it handles the rest.

- **Real passwordless login** — not just a second factor bolted in front of a password. Confirmed
  working end-to-end against a real ZITADEL instance (this project's own reference deployment);
  the provider itself is a standard OIDC implementation (authorization/token/JWKS/discovery, tested
  against Keycloak's own external-IDP button flow too), so it should work the same way with
  Keycloak, Authentik, or any other generic-OIDC-capable RP — see [Setting up the passwordless
  flow](#-setting-up-the-passwordless-flow-step-by-step) for exactly what's confirmed vs. what
  should work by protocol compliance.
- **Your own account directory** — this service keeps its own small list of email → assigned
  devices in a self-contained SQLite file. It never calls any identity provider's admin API to
  figure out who's who, so it works identically no matter which RP is in front of it.
- **Multiple devices per account**, discovered live from your own Home Assistant.
- **One-time recovery codes** as an emergency fallback if the push never arrives or you lose the
  device — shown once at generation time, stored only as irreversible hashes.
- **Anti-abuse built in**: an explicit Reject or a wrong recovery code counts toward a 3-strikes
  block (scoped to that one account + IP, never a global block), with manual unblock from the admin
  panel. A silent timeout does not count — only an explicit signal does.
- **Optional GeoIP enrichment** (self-hosted MaxMind GeoLite2 — no third-party API call per login)
  adds city/country/ISP to the audit log.
- **Expanded admin panel**: an at-a-glance home page, the account directory, per-account login
  history, recovery-code management, blocked-IP list, and page branding.

### 🕰️ About the older v1.0.0 mechanism (still included, now fully optional)

Before this passwordless flow existed, v1.0.0 shipped a different, **ZITADEL-specific** mechanism:
an Actions V2 webhook that approves/rejects *before* the password step (it does not replace it —
the password is still asked afterward). That mechanism has no equivalent in Keycloak/Authentik, so
it stays exactly as it was, entirely optional, and only activates if you fill in the `ZITADEL_*`
webhook variables below. You can use either flow, both at once, or neither — they're independent
(see the note in Troubleshooting about using both on the *same* account).

### 📦 Installation

Requires Home Assistant with the Companion App installed on at least one device. Environment
variables:

**Core (always required):**

| Variable | What it's for |
|---|---|
| `HA_BASE_URL` / `HA_TOKEN` | Your Home Assistant's internal URL and a [long-lived access token](https://developers.home-assistant.io/docs/auth_api/#long-lived-access-token). |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Login for this project's own `/admin` panel (HTTP Basic — a small internal tool, not worth a full session system). |

**Passwordless OIDC provider (required for the v2.0.0 login flow):**

| Variable | What it's for |
|---|---|
| `IDP_ISSUER_URL` | The URL your IDP will reach this container at, no trailing slash (e.g. `http://192.168.1.50:8000`). Used as the `iss` claim and to build the `/authorize`, `/token`, `/jwks.json` URLs. |
| `IDP_CLIENT_ID` / `IDP_CLIENT_SECRET` | Credentials your IDP will use to authenticate against this service's `/token` endpoint — you choose these yourself (e.g. a name and a long random string) and enter the *same* values when registering this service as an external IDP on your ZITADEL/Keycloak/Authentik. |
| `IDP_CLIENT_REDIRECT_URI` | The exact callback URL your IDP uses after login (for ZITADEL, typically `https://your-zitadel-domain/idps/callback`). Validated on every request to prevent an open redirect. |

**Legacy ZITADEL Actions V2 webhook (optional — leave unset to disable entirely):**

| Variable | What it's for |
|---|---|
| `ZITADEL_BASE_URL` | Your ZITADEL's public URL (External Domain, with `https://`). |
| `ZITADEL_CLIENT_ID` / `ZITADEL_CLIENT_SECRET` | Credentials of a ZITADEL **machine user** (Users → New → Machine) with enough permission to list users and read/write user metadata — `IAM_OWNER` is the simplest role that covers this. |
| `ZITADEL_TARGET_SIGNING_KEY` | The signing key ZITADEL gives you when creating the Target — see [Setting up the legacy webhook](#-setting-up-the-legacy-zitadel-webhook-optional-step-by-step). |

**Tuning (optional, sensible defaults):**

| Variable | Default | What it's for |
|---|---|---|
| `APPROVAL_TIMEOUT_SECONDS` | `120` | How long either flow waits for a tap before failing. If you use the legacy webhook, must stay below ZITADEL's own 270s hard limit. |
| `BRIDGE_RECOVERY_UNLOCK_DELAY_SECONDS` | `60` | Passwordless flow only: seconds with no response before the bridge page offers retry/recovery-code options. The original approval keeps waiting in the background regardless. |
| `IP_BLOCK_THRESHOLD` | `3` | Consecutive failures (explicit reject or wrong recovery code, same account + IP) before blocking. |
| `RECOVERY_CODE_BATCH_SIZE` | `10` | How many recovery codes get generated at once from `/admin/recovery`. |
| `RECOVERY_CODE_LOW_WARNING` | `3` | Push a warning once this many recovery codes (or fewer) remain. |
| `GEOIP_ACCOUNT_ID` / `GEOIP_LICENSE_KEY` | *(empty)* | Optional free [MaxMind](https://www.maxmind.com/) account, to add city/country/ISP to the audit log. Left empty, that part of the audit log just stays blank — nothing else is affected. |

A ready-to-use Unraid Community Applications template is included:
[`ha-login-approval.xml`](ha-login-approval.xml), pointing at the published image
`ghcr.io/nebur692/ha-login-approval:latest`. It also mounts a **persistent volume at `/data`** —
this holds the SQLite database (accounts, recovery codes, audit log, IP blocks, branding) and the
optional GeoIP files; without it, everything resets when the container is recreated.

#### Plain Docker / Docker Compose (no Unraid required)

The image is published on GHCR — no need to build it yourself:

```bash
docker pull ghcr.io/nebur692/ha-login-approval:latest
```

Or with Compose: grab just the [`docker-compose.yml`](docker-compose.yml) file from this repo (no
need to clone the whole thing), edit the environment values to match your own setup, then:

```bash
docker compose up -d
```

This exposes the service on port `8000` of the host running it — the `/admin` panel and the
`/.well-known/openid-configuration` discovery document both live there. Update in the future with
`docker compose pull && docker compose up -d`.

Available tags: `latest` (tracks the latest release), pinned version tags for each release.

### 🔐 Setting up the passwordless flow, step by step

The general shape, regardless of which IDP you use: register this service as a **generic external
OIDC provider**, pointing at `IDP_ISSUER_URL` (its discovery document is at
`<IDP_ISSUER_URL>/.well-known/openid-configuration`), using `IDP_CLIENT_ID`/`IDP_CLIENT_SECRET` as
the credentials, and configure that provider to redirect back to `IDP_CLIENT_REDIRECT_URI`. Then
add the accounts that should use it in this service's own **`/admin/accounts`** panel (email +
which devices get notified) — an account with no device assigned can never complete a passwordless
login, so nothing works by accident.

**ZITADEL — confirmed working end-to-end in a real deployment:**

1. **Console → Identity Providers → Add Provider → Generic OIDC.**
   - **Issuer:** your `IDP_ISSUER_URL`.
   - **Client ID / Client secret:** the same `IDP_CLIENT_ID` / `IDP_CLIENT_SECRET` you set on this
     container.
   - **Scopes:** `openid profile email`.
   - Under provider options: enable **"Is linking allowed"**, and leave automatic creation/update
     **off** — accounts must already exist in ZITADEL, this service only vouches for who they are,
     it doesn't create ZITADEL users.
   - If creating it fails with `Errors.Target.DeniedURL`: ZITADEL blocks private IP ranges by
     default (SSRF protection). Same fix as the legacy webhook below — see
     [Nebur692/unraid-zitadel-templates](https://github.com/Nebur692/unraid-zitadel-templates).
2. **Add it to your org's login policy** so the button actually shows up on the login screen
   (Console → your organization's Login Policy → Identity Providers → add the one you just
   created).
3. **Link a real account to it**: log in as that user, go to their account settings in ZITADEL,
   and link the new external IDP (the same self-service flow used to link Google or any other IDP).
   The identity this service asserts is simply the account's email, lowercased — make sure the
   ZITADEL account's own email matches exactly.
4. **Important, confirmed by hand**: ZITADEL does **not** forward whatever's typed in the
   `loginname` field to this service as a `login_hint` (a known, still-open ZITADEL bug — Keycloak's
   default external-IDP button doesn't send it either). This is why the bridge page always asks for
   the email itself. In practice this means: on ZITADEL's login screen, don't bother typing
   anything into the loginname field — just click this service's button directly and type the email
   on the next screen. Confirmed that clicking the button with an empty loginname field works fine.

**Keycloak — the button/redirect step has been confirmed live, the full token exchange has not:**

Register a generic **OpenID Connect v1.0** Identity Provider (Realm settings → Identity Providers),
same Issuer/Client ID/Client secret as above. Confirmed live that Keycloak's own external-IDP link
on its login screen is a plain server-rendered link independent of the username field — same
practical implication as ZITADEL: don't bother typing a username first, just click the button.

**Authentik and other generic-OIDC-capable IDPs — not tested, should work by protocol compliance:**

The provider this service exposes is a standard OIDC implementation with no ZITADEL-specific
assumptions in its wire format — any RP that supports "generic external OIDC provider" should be
able to use it the same way (register issuer + client credentials, point the redirect back here).
This just hasn't been verified hands-on the way ZITADEL and Keycloak's button behavior have. If you
try it, [an issue report](https://github.com/Nebur692/ha-login-approval/issues) with what worked or
didn't is very welcome.

### 🧑‍💻 Admin panel tour

All under `/admin`, protected by `ADMIN_USERNAME`/`ADMIN_PASSWORD`:

| Section | What it's for |
|---|---|
| **Home** | At-a-glance: total accounts, how many have devices assigned, recovery codes running low, currently blocked IPs. |
| **Accounts** | The passwordless flow's own directory — add an email, tick which devices get notified for it. This is what `idp.py` actually reads from; independent of any IDP. |
| **ZITADEL devices** *(only shown if the legacy webhook is configured)* | The old, ZITADEL-account-scoped device assignment for the v1.0.0 webhook. Also shows whether that same email already has a passwordless account, to catch mismatches. |
| **Audit** | Per-account history: approved / rejected / timed out / recovery code used / send failed, with timestamp, IP, browser, and (if GeoIP is configured) city/country/ISP. |
| **Recovery codes** | Generate or regenerate a batch per account — shown once, then never retrievable again. Regenerating instantly invalidates every code from the previous batch. |
| **Blocked IPs** | See who's currently blocked and unblock manually — important if three accidental rejects (or mistyped codes) lock out the real account owner. |
| **Branding** | Upload a logo/background/favicon and set a title for the bridge page. *(Saved, not wired into the bridge page's rendering yet — a future polish pass.)* |

### 🧭 Usage — what it looks like for the person logging in

1. On your IDP's login screen, click this service's button (no need to type a username first).
2. Type your email on the bridge page that appears.
3. Check your phone (or whichever devices are assigned to that account) — approve or reject.
4. **Approve** → you're logged in, no password ever asked.
5. **Nothing happens for a while** → after `BRIDGE_RECOVERY_UNLOCK_DELAY_SECONDS` (60s by default),
   the page offers to resend the notification or use a one-time recovery code — the original
   approval keeps waiting in the background too, so a late tap still works.
6. **Reject** → the login is denied; three rejects (or wrong recovery codes) in a row from the same
   place block further attempts until an admin unblocks it.

### ⚙️ Setting up the legacy ZITADEL webhook (optional), step by step

Only needed if you also want approve/reject *before* the password step, on top of (or instead of)
the passwordless flow above. This is the original v1.0.0 mechanism, unchanged.

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
     safety net for that: accounts with *no* device assigned are let through without being blocked
     at all.
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

- **Notification never arrives (passwordless flow)**: confirm the email is added in
  `/admin/accounts` with at least one device ticked.
- **Notification never arrives (legacy webhook)**: confirm the account has a device saved in
  `/admin/devices`, and that the Execution (step 2 above) actually lists your Target — creating a
  Target does *not* automatically wire it to anything.
- **Recovery code / retry option not showing up**: it's gated server-side and only appears after
  `BRIDGE_RECOVERY_UNLOCK_DELAY_SECONDS`, or immediately if the notification send itself failed
  outright — it's not just a client-side timer, so it won't appear early no matter what.
- **Logged in but got a second, redundant push right after**: if the *same* ZITADEL account has
  both the legacy webhook (`/admin/devices`) and a passwordless account (`/admin/accounts`) set up,
  a passwordless login still triggers ZITADEL's `CreateSession` event, which the legacy webhook
  always reacts to as well — you'll get one notification from each. Not a bug, just don't configure
  both mechanisms for the same account unless you actually want that.
- **Account (or its IP) not responding to anything**: check `/admin/blocked-ips` — three explicit
  rejects or wrong recovery codes block that account+IP pair until manually unblocked there.
- **Still asked for a password after approving**: expected if you're using the *legacy* webhook —
  that mechanism approves before the password, it doesn't remove it. Use the passwordless flow
  above for a login with no password at all.

### 💙 Support

None of this would be possible without the community's support. If this project has been useful to
you, consider supporting it via [GitHub Sponsors](https://github.com/sponsors/Nebur692),
[Ko-fi](https://ko-fi.com/nebur69265723) or [PayPal](https://paypal.me/0SkillS) — every bit helps
keep it maintained.

### ⚠️ Disclaimer

Not affiliated with, endorsed by, or associated with ZITADEL (ZITADEL GmbH), Keycloak, Authentik,
or Home Assistant / Nabu Casa Inc. All are trademarks of their respective owners.

### 📜 License

[MIT](LICENSE)

---

## Español

### ✨ Qué es esto

Este proyecto convierte la app Companion de Home Assistant en tu propio método de login. En vez de
escribir una contraseña, escribes tu email, te llega una notificación con botones **Aprobar /
Rechazar**, y pulsar Aprobar te da acceso — sin contraseña de por medio en ningún momento.

Lo consigue actuando como un **proveedor OIDC externo genérico**: cualquier aplicación que soporte
"iniciar sesión con un proveedor OIDC externo" (ZITADEL, Keycloak, Authentik, y en principio
cualquier otro que cumpla el estándar) puede redirigir a este servicio, que se encarga del resto.

- **Login realmente sin contraseña** — no es solo un segundo factor añadido delante de una
  contraseña. Confirmado funcionando de extremo a extremo contra una instancia real de ZITADEL
  (el propio despliegue de referencia de este proyecto); el proveedor en sí es una implementación
  OIDC estándar (authorization/token/JWKS/discovery, probado también contra el flujo de botón
  externo de Keycloak), así que debería funcionar igual con Keycloak, Authentik o cualquier otro RP
  compatible con OIDC genérico — ver [Configurar el flujo sin contraseña](#-configurar-el-flujo-sin-contraseña-paso-a-paso)
  para saber exactamente qué está confirmado y qué debería funcionar por cumplir el estándar.
- **Directorio de cuentas propio** — este servicio guarda su propia lista pequeña de email →
  dispositivos asignados en un fichero SQLite autocontenido. Nunca llama al API de gestión de
  ningún proveedor de identidad para saber quién es quién, así que funciona igual sin importar qué
  RP tenga delante.
- **Varios dispositivos por cuenta**, descubiertos en vivo desde tu propio Home Assistant.
- **Códigos de recuperación de un solo uso** como salvavidas si la notificación nunca llega o
  pierdes el dispositivo — se muestran una sola vez al generarlos, se guardan solo como hash
  irreversible.
- **Anti-abuso integrado**: un Rechazo explícito o un código de recuperación incorrecto cuentan
  para un bloqueo a los 3 fallos (limitado a esa cuenta + IP concretas, nunca un bloqueo global),
  con desbloqueo manual desde el panel admin. Un timeout silencioso no cuenta — solo una señal
  explícita.
- **Enriquecimiento GeoIP opcional** (MaxMind GeoLite2 autoalojado — sin llamar a ningún API de
  terceros en cada login) añade ciudad/país/operador a la auditoría.
- **Panel de administración ampliado**: resumen de un vistazo, directorio de cuentas, historial de
  login por cuenta, gestión de códigos de recuperación, lista de IPs bloqueadas, y personalización
  de la página.

### 🕰️ Sobre el mecanismo antiguo de v1.0.0 (sigue incluido, ahora del todo opcional)

Antes de que existiera este flujo sin contraseña, la v1.0.0 traía un mecanismo distinto y
**específico de ZITADEL**: un webhook de Actions V2 que aprueba/rechaza *antes* del paso de la
contraseña (no la sustituye — se sigue pidiendo después). Ese mecanismo no tiene equivalente en
Keycloak/Authentik, así que se queda exactamente igual que estaba, del todo opcional, y solo se
activa si rellenas las variables `ZITADEL_*` del webhook de abajo. Puedes usar cualquiera de los
dos flujos, los dos a la vez, o ninguno — son independientes (ver la nota de Solución de problemas
sobre usar ambos en la *misma* cuenta).

### 📦 Instalación

Necesita Home Assistant con la app Companion instalada en al menos un dispositivo. Variables de
entorno:

**Básicas (siempre requeridas):**

| Variable | Para qué sirve |
|---|---|
| `HA_BASE_URL` / `HA_TOKEN` | La URL interna de tu Home Assistant y un [token de acceso de larga duración](https://developers.home-assistant.io/docs/auth_api/#long-lived-access-token). |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Acceso al propio panel `/admin` (HTTP Basic — herramienta interna pequeña, no compensa un sistema de sesiones completo). |

**Proveedor OIDC sin contraseña (requerido para el flujo de login de la v2.0.0):**

| Variable | Para qué sirve |
|---|---|
| `IDP_ISSUER_URL` | La URL con la que tu IDP alcanzará este contenedor, sin barra final (ej. `http://192.168.1.50:8000`). Se usa como claim `iss` y para construir las URLs de `/authorize`, `/token`, `/jwks.json`. |
| `IDP_CLIENT_ID` / `IDP_CLIENT_SECRET` | Credenciales que tu IDP usará para autenticarse contra el `/token` de este servicio — las eliges tú (un nombre y una cadena aleatoria larga) y pones los *mismos* valores al registrar este servicio como IDP externo en tu ZITADEL/Keycloak/Authentik. |
| `IDP_CLIENT_REDIRECT_URI` | La URL de retorno exacta que usa tu IDP tras el login (para ZITADEL, normalmente `https://tu-dominio-zitadel/idps/callback`). Se valida en cada petición para evitar redirecciones no autorizadas. |

**Webhook legado de ZITADEL Actions V2 (opcional — vacío para desactivarlo del todo):**

| Variable | Para qué sirve |
|---|---|
| `ZITADEL_BASE_URL` | La URL pública de tu ZITADEL (External Domain, con `https://`). |
| `ZITADEL_CLIENT_ID` / `ZITADEL_CLIENT_SECRET` | Credenciales de un **usuario máquina** de ZITADEL (Users → New → Machine) con permiso suficiente para listar usuarios y leer/escribir metadatos — `IAM_OWNER` es el rol más simple que lo cubre. |
| `ZITADEL_TARGET_SIGNING_KEY` | La clave de firma que ZITADEL te da al crear el Target — ver [Configurar el webhook legado](#-configurar-el-webhook-legado-de-zitadel-opcional-paso-a-paso). |

**Ajustes (opcionales, con valores por defecto razonables):**

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `APPROVAL_TIMEOUT_SECONDS` | `120` | Cuánto espera cualquiera de los dos flujos a que pulses antes de fallar. Si usas el webhook legado, debe quedarse por debajo del límite fijo de 270s de ZITADEL. |
| `BRIDGE_RECOVERY_UNLOCK_DELAY_SECONDS` | `60` | Solo flujo sin contraseña: segundos sin respuesta antes de que la página ofrezca reintentar o usar un código de recuperación. La aprobación original sigue esperando en paralelo. |
| `IP_BLOCK_THRESHOLD` | `3` | Fallos consecutivos (rechazo explícito o código incorrecto, misma cuenta + IP) antes de bloquear. |
| `RECOVERY_CODE_BATCH_SIZE` | `10` | Cuántos códigos de recuperación se generan de golpe desde `/admin/recovery`. |
| `RECOVERY_CODE_LOW_WARNING` | `3` | Avisar por push cuando queden este número de códigos o menos. |
| `GEOIP_ACCOUNT_ID` / `GEOIP_LICENSE_KEY` | *(vacío)* | Cuenta gratuita opcional de [MaxMind](https://www.maxmind.com/), para añadir ciudad/país/operador a la auditoría. Vacío = esa parte de la auditoría queda en blanco, sin afectar a nada más. |

Incluye una plantilla lista para Community Applications de Unraid:
[`ha-login-approval.xml`](ha-login-approval.xml), que apunta a la imagen ya publicada
`ghcr.io/nebur692/ha-login-approval:latest`. También monta un **volumen persistente en `/data`** —
ahí vive la base de datos SQLite (cuentas, códigos de recuperación, auditoría, bloqueos de IP,
personalización) y los ficheros de GeoIP opcionales; sin él, todo se reinicia al recrear el
contenedor.

#### Docker normal / Docker Compose (sin necesidad de Unraid)

La imagen está publicada en GHCR — no hace falta construirla tú mismo:

```bash
docker pull ghcr.io/nebur692/ha-login-approval:latest
```

O con Compose: descarga solo el fichero [`docker-compose.yml`](docker-compose.yml) de este repo
(no hace falta clonarlo entero), edita los valores de entorno para que coincidan con tu propia
instalación, y luego:

```bash
docker compose up -d
```

Esto expone el servicio en el puerto `8000` del host donde lo ejecutes — ahí viven tanto el panel
`/admin` como el documento de descubrimiento `/.well-known/openid-configuration`. Para actualizar en
el futuro: `docker compose pull && docker compose up -d`.

Tags disponibles: `latest` (la última versión publicada), tags fijos por cada versión.

### 🔐 Configurar el flujo sin contraseña, paso a paso

La idea general, sea cual sea tu IDP: registra este servicio como **proveedor OIDC externo
genérico**, apuntando a `IDP_ISSUER_URL` (su documento de descubrimiento está en
`<IDP_ISSUER_URL>/.well-known/openid-configuration`), usando `IDP_CLIENT_ID`/`IDP_CLIENT_SECRET`
como credenciales, y configura ese proveedor para que redirija de vuelta a
`IDP_CLIENT_REDIRECT_URI`. Luego añade las cuentas que deban usarlo en el propio panel
**`/admin/accounts`** de este servicio (email + qué dispositivos se notifican) — una cuenta sin
ningún dispositivo asignado nunca puede completar un login sin contraseña, así que nada funciona
por accidente.

**ZITADEL — confirmado funcionando de extremo a extremo en un despliegue real:**

1. **Consola → Identity Providers → Add Provider → Generic OIDC.**
   - **Issuer:** tu `IDP_ISSUER_URL`.
   - **Client ID / Client secret:** los mismos `IDP_CLIENT_ID` / `IDP_CLIENT_SECRET` que pusiste en
     este contenedor.
   - **Scopes:** `openid profile email`.
   - En las opciones del proveedor: activa **"Is linking allowed"**, y deja la creación/actualización
     automática **desactivadas** — las cuentas ya deben existir en ZITADEL, este servicio solo
     confirma quién es quién, no crea usuarios de ZITADEL.
   - Si falla al crearlo con `Errors.Target.DeniedURL`: ZITADEL bloquea rangos de IP privados por
     defecto (protección SSRF). Mismo arreglo que el webhook legado de abajo — ver
     [Nebur692/unraid-zitadel-templates](https://github.com/Nebur692/unraid-zitadel-templates).
2. **Añádelo a la política de login de tu organización** para que el botón aparezca de verdad en
   la pantalla de login (Consola → Login Policy de tu organización → Identity Providers → añade el
   que acabas de crear).
3. **Vincula una cuenta real**: entra como ese usuario, ve a su configuración de cuenta en ZITADEL,
   y vincula el nuevo IDP externo (el mismo flujo de autoservicio que se usa para vincular Google o
   cualquier otro IDP). La identidad que afirma este servicio es simplemente el email de la cuenta
   en minúsculas — asegúrate de que el email de la cuenta de ZITADEL coincide exactamente.
4. **Importante, confirmado a mano**: ZITADEL **no** reenvía lo que se escriba en el campo
   `loginname` a este servicio como `login_hint` (un bug real y todavía abierto de ZITADEL — el
   botón por defecto de Keycloak tampoco lo manda). Por eso la página puente siempre pide el email
   ella misma. En la práctica: en la pantalla de login de ZITADEL, no hace falta escribir nada en
   el campo de usuario — pulsa directamente el botón de este servicio y escribe el email en la
   siguiente pantalla. Confirmado que pulsar el botón con el campo vacío funciona sin problema.

**Keycloak — el paso del botón/redirección está confirmado en vivo, el intercambio completo del token no:**

Registra un Identity Provider genérico **OpenID Connect v1.0** (Realm settings → Identity
Providers), mismo Issuer/Client ID/Client secret que arriba. Confirmado en vivo que el propio
enlace de IDP externo de Keycloak en su pantalla de login es un enlace estático generado por el
servidor, independiente del campo de usuario — misma implicación práctica que ZITADEL: no hace
falta escribir un usuario antes, pulsa directamente el botón.

**Authentik y otros IDP compatibles con OIDC genérico — sin probar, deberían funcionar por cumplir el estándar:**

El proveedor que expone este servicio es una implementación OIDC estándar sin ninguna suposición
específica de ZITADEL en su formato de comunicación — cualquier RP que soporte "proveedor OIDC
externo genérico" debería poder usarlo igual (registrar issuer + credenciales de cliente, apuntar
la redirección aquí). Simplemente no se ha comprobado a mano como sí se ha hecho con el
comportamiento del botón de ZITADEL y Keycloak. Si lo pruebas,
[un issue](https://github.com/Nebur692/ha-login-approval/issues) contando qué funcionó o no es muy
bienvenido.

### 🧑‍💻 Recorrido por el panel de administración

Todo bajo `/admin`, protegido por `ADMIN_USERNAME`/`ADMIN_PASSWORD`:

| Sección | Para qué sirve |
|---|---|
| **Home** | De un vistazo: cuentas totales, cuántas tienen dispositivo asignado, códigos de recuperación bajos, IPs bloqueadas ahora mismo. |
| **Accounts** | El directorio propio del flujo sin contraseña — añade un email, marca qué dispositivos se notifican. Es lo que `idp.py` lee de verdad; independiente de cualquier IDP. |
| **ZITADEL devices** *(solo se muestra si el webhook legado está configurado)* | La asignación antigua de dispositivos por cuenta de ZITADEL, para el webhook de v1.0.0. También muestra si ese mismo email ya tiene una cuenta sin contraseña, para detectar desajustes. |
| **Audit** | Historial por cuenta: aprobado / rechazado / timeout / código de recuperación usado / envío fallido, con fecha, IP, navegador y (si GeoIP está configurado) ciudad/país/operador. |
| **Recovery codes** | Generar o regenerar un lote por cuenta — se muestran una sola vez, luego nunca se pueden recuperar. Regenerar invalida al instante todos los códigos del lote anterior. |
| **Blocked IPs** | Ver quién está bloqueado ahora mismo y desbloquear manualmente — importante si tres rechazos accidentales (o códigos mal tecleados) dejan fuera al dueño real de la cuenta. |
| **Branding** | Sube un logo/fondo/favicon y pon un título para la página puente. *(Se guarda, todavía sin conectar al renderizado real de la página — pulido pendiente para más adelante.)* |

### 🧭 Uso — cómo lo vive quien inicia sesión

1. En la pantalla de login de tu IDP, pulsa el botón de este servicio (sin necesidad de escribir
   un usuario antes).
2. Escribe tu email en la página puente que aparece.
3. Mira tu móvil (o los dispositivos asignados a esa cuenta) — aprueba o rechaza.
4. **Aprobar** → sesión iniciada, sin pedir contraseña en ningún momento.
5. **Si no pasa nada durante un rato** → tras `BRIDGE_RECOVERY_UNLOCK_DELAY_SECONDS` (60s por
   defecto), la página ofrece reenviar la notificación o usar un código de recuperación de un solo
   uso — la aprobación original sigue esperando en segundo plano, así que una pulsación tardía
   también funciona.
6. **Rechazar** → el login se deniega; tres rechazos (o códigos incorrectos) seguidos desde el
   mismo sitio bloquean nuevos intentos hasta que un administrador lo desbloquee.

### ⚙️ Configurar el webhook legado de ZITADEL (opcional), paso a paso

Solo hace falta si además quieres aprobar/rechazar *antes* del paso de la contraseña, encima de (o
en vez de) el flujo sin contraseña de arriba. Es el mecanismo original de v1.0.0, sin cambios.

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
     incluye una salida para eso: las cuentas *sin* ningún dispositivo asignado dejan pasar el login
     sin bloquear nada.
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

- **La notificación nunca llega (flujo sin contraseña)**: comprueba que el email está añadido en
  `/admin/accounts` con al menos un dispositivo marcado.
- **La notificación nunca llega (webhook legado)**: comprueba que la cuenta tiene un dispositivo
  guardado en `/admin/devices`, y que la Execution (paso 2 de arriba) de verdad lista tu Target —
  crear un Target **no** lo engancha automáticamente a nada.
- **La opción de reintentar/código de recuperación no aparece**: está controlada en el servidor y
  solo aparece tras `BRIDGE_RECOVERY_UNLOCK_DELAY_SECONDS`, o de inmediato si el envío de la
  notificación falló del todo — no es solo un temporizador del navegador, así que no aparecerá
  antes pase lo que pase.
- **Login correcto pero llega una segunda notificación redundante justo después**: si esa misma
  cuenta de ZITADEL tiene configurados tanto el webhook legado (`/admin/devices`) como una cuenta
  sin contraseña (`/admin/accounts`), un login sin contraseña también dispara el evento
  `CreateSession` de ZITADEL, al que el webhook legado siempre reacciona igual — te llegará una
  notificación de cada uno. No es un fallo, simplemente no configures ambos mecanismos para la
  misma cuenta salvo que quieras justo eso.
- **La cuenta (o su IP) no responde a nada**: revisa `/admin/blocked-ips` — tres rechazos explícitos
  o códigos de recuperación incorrectos bloquean esa pareja cuenta+IP hasta desbloquearla ahí a
  mano.
- **Sigue pidiendo contraseña después de aprobar**: esperado si estás usando el webhook *legado* —
  ese mecanismo aprueba antes de la contraseña, no la elimina. Usa el flujo sin contraseña de arriba
  para un login sin ninguna contraseña de por medio.

### 💙 Apoya el proyecto

Sin el apoyo de la comunidad estos proyectos no serían posibles. Si te ha resultado útil, puedes
apoyarlo vía [GitHub Sponsors](https://github.com/sponsors/Nebur692),
[Ko-fi](https://ko-fi.com/nebur69265723) o [PayPal](https://paypal.me/0SkillS) — cualquier
aportación ayuda a seguir manteniéndolo.

### ⚠️ Aviso legal

No afiliado, respaldado ni asociado con ZITADEL (ZITADEL GmbH), Keycloak, Authentik, ni Home
Assistant / Nabu Casa Inc. Todas son marcas registradas de sus respectivos propietarios.

### 📜 Licencia

[MIT](LICENSE)
