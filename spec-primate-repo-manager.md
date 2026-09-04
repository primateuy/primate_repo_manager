# Spec — primate_repo_manager

**Versión:** 1.0 — 29 de julio de 2026
**Odoo:** 19.0 Enterprise
**Estado:** Aprobado para implementación por fases con Claude Code
**Decisor:** Daryl (líder técnico, PrimateUY)

---

## 1. Resumen

Módulo Odoo que gobierna los repositorios git de la organización GitHub de Primate: permisos de personas sobre repos, política de protección de ramas, promociones entre entornos, gestión de forks de upstream, onboarding/offboarding de desarrolladores y auditoría completa. Implementa operativamente los lineamientos git de Primate (v1.1).

**Principio rector:** Odoo es el plano de control; GitHub es el enforcement. El módulo declara la política, la aplica sobre GitHub vía API (rulesets, permisos, CODEOWNERS), detecta desvíos (drift) y audita. GitHub es quien bloquea. El módulo NO clona repos ni ejecuta git en servidores: todo por REST/GraphQL API de GitHub.

## 2. Arquitectura de módulos

```
primate_repo_manager             depends: [base, mail, queue_job, hr]
primate_repo_manager_pcm_bridge  depends: [primate_repo_manager, <módulo core PCM>], auto_install: True
```

- El core no contiene ninguna referencia a PCM.
- `hr` es necesario para el vínculo `repo.member` ↔ `hr.employee`, que el DoD de F1 usa
  para reportar cuentas de GitHub sin persona asociada.
- El bridge aporta: menú de entrada en el shell de PCM hacia la acción raíz del core; vínculo Many2one entre `repo.repository` y el modelo de repositorio de deploy de PCM; hook de pre-validación de promociones que consulta estado de deploy en PCM.

## 3. Autenticación GitHub

- **GitHub App** propia de la org (no PAT). App ID + Installation ID + private key.
- Private key cifrada en Odoo (mismo estándar de secretos que PCM: nunca texto plano en campos ni en ir.config_parameter sin cifrar).
- Permisos de la App (mínimos): Repository Administration (RW), Organization Members (RW), Pull requests (RW), Contents (RW — necesario para merges y creación de ramas), Webhooks (RW), Commit statuses / Checks (R).
- Tokens de instalación de corta vida generados on-demand; nunca persistidos más allá de su TTL.
- **Autorización por usuario (user-to-server OAuth):** la App habilita "Request user authorization during installation". Cada miembro que opera PRs desde Odoo conecta su cuenta GitHub una vez (flujo OAuth con callback en Odoo); su token de usuario se guarda cifrado en `repo.member`. Las acciones de revisión y merge ejecutadas desde Odoo usan el token DEL USUARIO, no el de la App → GitHub atribuye la acción a la persona real, las reglas de owners/aprobaciones se satisfacen genuinamente y la auditoría refleja quién hizo qué. Las operaciones de gobernanza (rulesets, grants, sync) siguen usando el token de instalación de la App.

## 4. Modelo de datos

Prefijo de modelos: `repo.*`. Todos con `mail.thread` donde haya estados o acciones humanas.

### 4.1 Conexión y estructura

**`repo.backend`**
- `name`, `provider` (selection: github; extensible), `org_name`
- `app_id`, `installation_id`, `private_key_encrypted`
- `webhook_secret_encrypted` (HMAC)
- `state` (draft/connected/error), `last_sync`, botón "Probar conexión"

**`repo.repository`**
- `backend_id`, `name`, `full_name`, `github_id`, `visibility`, `default_branch`
- `classification` (selection: `localizacion` / `cliente` / `interno` / `fork_upstream`)
- `policy_template_id` (Many2one a `repo.policy.template`)
- `sync_state`, `drift` (boolean computado), `drift_detail` (Html)
- `upstream_full_name` (solo forks: p. ej. `OCA/web`, `odoo/enterprise`)
- `active_patch_ids` (One2many a `repo.patch`, solo forks)

**`repo.branch`**
- `repository_id`, `name`, `role` (selection: `base` / `staging` / `support` / `prod` / `version` / `mirror` / `patch` / `other`)
- `protected` (boolean, estado real en GitHub), `ahead_upstream` / `behind_upstream` (solo mirror/patch)
- Solo se persisten ramas relevantes (entorno, base, espejo, parches); no todas las feature branches.

### 4.2 Personas y permisos

**`repo.member`**
- `github_username`, `github_id`, `user_id` (res.users), `employee_id` (hr.employee, opcional)
- `signing_configured` (boolean: firma de commits SSH configurada y verificada)
- `oauth_token_encrypted` (token user-to-server, cifrado, write-only), `oauth_state` (not_connected / connected / expired) — requerido para operar PRs desde Odoo; botón "Conectar mi GitHub"
- `state` (active/offboarded) — el offboarding también revoca y borra el token OAuth

**`repo.team`**
- Espejo de teams de GitHub: `name`, `slug`, `member_ids`. Gestionable desde Odoo (crear team, agregar/quitar miembros → aplicado por API).

**`repo.access.grant`**
- `subject`: `member_id` XOR `team_id`
- `repository_id`, `role` (selection: pull/triage/push/maintain/admin)
- `date_from`, `date_to` (opcional), `reason` (obligatorio para role admin)
- `state` (draft → applied → revoked), aplicación/revocación real por API vía queue_job
- Constraint: el estado en GitHub debe reflejar exactamente la suma de grants activos; diferencia = drift.

### 4.3 Política

**`repo.policy.template`**
- `name`, `classification_default`
- Reglas de ruleset (generan JSON de rulesets de GitHub, aplicado por API):
	- `require_pr` (bool), `required_approvals` (int), `require_codeowner_review` (bool)
	- `required_status_checks` (One2many: nombre del check)
	- `block_force_push` (bool, default True), `block_deletion` (bool, default True)
	- `branch_name_pattern` (regex; default: `^(feature|fix)\/\d+-[a-z0-9-]+$`)
	- `commit_message_pattern` (regex; default: `^\[(ADD|IMP|FIX)\]\[\d+\] .+`)
	- `require_signed_commits` (bool)
	- `bypass_member_ids` (Many2many a repo.member — lista mínima; todo uso auditado)
- Reglas por rol de rama (One2many `repo.policy.branch.rule`): a qué roles de rama aplica cada ruleset y con qué overrides (p. ej. prod: `required_approvals=2`; base: `required_approvals=1` + codeowner).
- `merge_strategy_base` (squash), `merge_strategy_promotion` (merge_commit) — informativo + validado en `repo.promotion`.
- Generación de CODEOWNERS: One2many `repo.policy.codeowner` (path pattern → team owner). El archivo CODEOWNERS lo escribe el módulo por API (commit vía la App a la rama base con PR automática si la base está protegida).

**Plantillas de datos iniciales (data XML):**

> **Nota (1-sep-2026):** `interno` exige PR y checks pero **0 aprobaciones**. La versión
> anterior de esta tabla pedía 1 aprobación, lo que contradecía "sin ramas de entorno" y
> frenaba el trabajo en herramientas internas donde muchas veces hay una sola persona. Se
> conservan la trazabilidad del PR y el CI pre-merge, se quita la espera por aprobación.
> Staging y support heredan de base (PR + 1 aprobación) en las plantillas que tienen esas
> ramas; endurecer support se hace por override en `repo.policy.branch.rule`.

| Plantilla | Aprobaciones base | Aprobaciones prod | CODEOWNERS | Firma | Notas |
|---|---|---|---|---|---|
| `cliente-estandar` | 1 | 2 | no | no (fase 2 de rollout) | CI requerida |
| `localizacion` | 1 (de owner) | 2 (1 de owner) | sí (team owners) | sí | La más estricta |
| `interno` | 0 (PR obligatorio) | — | no | no | Sin ramas de entorno; CI sí |
| `fork-upstream` | (ver §5) | — | no | no | Espejo + parches |

### 4.4 Operación

**`repo.pull.request`** — gestión completa del PR desde Odoo (no solo espejo)

*Datos (alimentados por webhooks + sync):*
- `repository_id`, `number`, `title`, `author_member_id`, `source_branch`, `target_branch`
- `state` (open / approved / changes_requested / merged / closed), `approvals` y quiénes, `checks_state`, `age_days` (computado), `mergeable` (estado real de GitHub)
- `task_id` (project.task) y `project_id`: vínculo automático por parseo de `[TIPO][NRO]` en título y `feature|fix/NRO-` en rama; editable a mano si el parseo falla
- `reviewer_activity_id`: la actividad de revisión generada

*Menú "PRs Pendientes":* vista lista/kanban de todos los PRs abiertos de la org, con proyecto, tarea que resuelve, autor, destino, checks, aprobaciones y antigüedad. Filtros por repo, proyecto, revisor, "me toca revisar". Es el tablero diario del revisor.

*Acciones desde Odoo (ejecutadas con el token OAuth del usuario que las hace — ver §3):*
- **Aprobar** / **Pedir cambios** / **Comentar** (review de GitHub real, atribuida a la persona)
- **Mergear** (estrategia según política: squash hacia base; bloqueado si GitHub reporta requisitos incompletos — el botón muestra qué falta)
- Precondición de cualquier acción: `oauth_state = connected` del usuario; si no, se le ofrece el flujo de conexión.

*Visor de diff (sub-entregable F4-B):* pestaña en el form del PR con los archivos del diff traídos por API (paginado, colapsable por archivo, syntax highlight básico). Read-only. Siempre acompañado del link directo al diff en GitHub. Si F4-B se pospone, el flujo funciona igual con el link.

*Ciclo de actividades:*
1. **PR abierta** (webhook) → actividad de revisión al revisor que corresponda: revisores por defecto del repo (`default_reviewer_ids`, fallback: líder técnico); si el PR toca rutas con CODEOWNERS, la actividad va al team de owners. La actividad incluye: proyecto, tarea que resuelve, resumen y link.
2. **PR aprobada** (desde Odoo o detectada por webhook si se aprobó en GitHub) → la actividad de revisión se marca hecha automáticamente.
3. **PR mergeada** → actividad de testeo en la `task_id` vinculada, asignada al **responsable de testeo del proyecto** (`qa_user_id` en project.project; fallback configurable), con referencia al PR y al repo; opcional por proyecto: mover la tarea a la etapa "A probar" automáticamente. La actividad de revisión, si seguía abierta, se cierra.
4. **PR cerrada sin merge** → actividad de revisión cancelada + nota en chatter.
- Parámetro de configuración `qa_trigger` (merge / approval, default: merge) por si se prefiere disparar el testeo en la aprobación.
- Regla anti-duplicación: si la revisión ocurrió directamente en GitHub, Odoo NO genera actividades nuevas — solo refleja y cierra las existentes. Las dos vías (Odoo y GitHub) conviven; Odoo siempre queda consistente vía webhooks.

*Cron:* PR abierta > 7 días → actividad al autor (regla de vida de rama de los lineamientos).

**`repo.promotion`** — promoción entre entornos como flujo de negocio
- `repository_id`, `source_branch_id`, `target_branch_id`, `requested_by`, `approver_ids`
- `state`: draft → pending_checks → pending_approval → ready → merging → done / failed / rejected
- **Pre-validaciones (alcance completo, configurables por plantilla):**
	1. CI verde en la rama origen (checks de GitHub)
	2. Sin drift de política en el repo
	3. Sin PRs abiertas contra la rama origen marcadas como bloqueantes
	4. (Vía bridge, si PCM instalado) instancia de staging del proyecto deployada con la rama origen y healthy
	5. Aprobaciones en Odoo según destino (prod: 2, una de ellas owner si aplica CODEOWNERS)
- Ejecución: merge por API con estrategia merge-commit; verificación post-merge (SHA esperado en destino); registro en auditoría. Fallo → estado failed con detalle, nunca reintento silencioso.

**`repo.patch`** — parches vivos sobre forks (ver §5)
- `repository_id`, `commit_sha`, `title`, `task_id` (ticket), `upstream_pr_url` (opcional), `state` (active / merged_upstream / dropped)
- Computado por comparación espejo vs rama de parches en cada sync.

**`repo.audit.log`**
- Inmutable (sin write/unlink por ACL; solo create del sistema).
- `event_type` (apply_policy / grant / revoke / promotion / bypass_detected / drift_detected / drift_resolved / sync / offboarding / signing_change), `repository_id`, `member_id`, `payload` (Json), `timestamp`.
- Todo bypass detectado (merge o push que evadió reglas por lista de bypass) → además de log, actividad al líder técnico y a leadership.

### 4.5 Wizards

- **Crear repositorio** — los repos nacen gobernados:
	- Datos: nombre, descripción, visibilidad (private por defecto), `classification`, plantilla de política, proyecto Odoo asociado (opcional), versiones de Odoo a soportar.
	- Estructura inicial de ramas según lineamientos: rama base por versión (`17.0`/`18.0`/`19.0`) y, si la clasificación lo requiere, ramas de entorno (`<v>_staging`, `support`, `prod`) creadas desde la base.
	- Scaffolding vía **repositorio plantilla de GitHub** (uno por clasificación, mantenido por Primate): README, `.gitignore` Odoo, workflow de CI base (lint + tests), estructura de módulo vacía. El wizard usa el endpoint `generate` de template repos.
	- Aplicación inmediata post-creación (mismo job encadenado): ruleset de la plantilla de política, CODEOWNERS, teams y grants iniciales según clasificación.
	- Variante **"Crear fork gobernado"**: dado un `upstream_full_name` (p. ej. `OCA/partner-contact`), forkea a la org y configura de una la estructura espejo + parches del §5 (ramas espejo bloqueadas, rama `<v>_primate`, job de sync activado).
	- Todo idempotente y por queue_job; si un paso intermedio falla (p. ej. ruleset), el repo queda en estado `provisioning_error` con detalle y botón de reintento — nunca un repo a medio configurar sin marcar.
	- Permiso: solo grupo Líder o Administrador.
- **Onboarding de dev:** alta de `repo.member` + selección de plantilla de puesto (conjunto de grants) → aplica todo por API + checklist de firma SSH.
- **Offboarding:** un click → revoca todos los grants, saca de todos los teams, cierra sesiones de la App si aplica, genera reporte de lo revocado. (No toca la cuenta GitHub de la persona: solo su acceso a la org.)
- **Crear rama desde ticket** (se instala como server action / botón en `project.task`):
	- Detecta número de ticket; pide tipo (ADD/IMP/FIX) y repo (default configurable por proyecto; permite multi-repo → N ramas)
	- Crea `feature/1234-slug` o `fix/1234-slug` desde la rama base por API; vincula rama ↔ ticket
	- Automatización opcional (config): disparo al pasar a etapa "En proceso" con etiqueta de desarrollo — OFF por defecto en MVP
- **Aplicar/reaplicar política:** preview del JSON de rulesets + diff contra estado actual → aplicar.
- **Resolver drift:** por cada desvío detectado, dos salidas: adoptar (actualizar la política declarada) o revertir (reaplicar la política sobre GitHub). Nunca resolución silenciosa.

## 5. Forks de upstream (OCA / odoo enterprise)

Patrón espejo + parches, por versión:

- **Rama espejo** (`17.0`, `18.0`…): rol `mirror`. Push bloqueado para TODOS los humanos (ruleset). Solo el job de sync actualiza desde upstream con `--ff-only` (vía API: comparar y avanzar la ref). Nunca puede haber conflicto; si el ff falla, es que alguien pusheó a la espejo → drift crítico + actividad.
- **Rama de parches** (`17.0_primate`): rol `patch`. Aquí van los fixes propios con el flujo normal (PR + 1 aprobación + CI). El `addons_path` de los clientes apunta a esta rama.
- **Job de sync** (cron por repo fork):
	1. Avanza espejo desde upstream (ff-only)
	2. Reaplica parches: merge de espejo → rama de parches por API; si hay conflicto, NO fuerza: crea actividad "conflicto de sync en <repo>" con detalle
	3. Recomputa `repo.patch`: commits en parches que no están en espejo = parches vivos; parche cuyo contenido ya está en upstream → estado `merged_upstream` + actividad para limpiarlo
- **Buena ciudadanía OCA:** al crear un parche sobre un fork OCA, el wizard pide (opcional pero recomendado) la URL de la PR al upstream. Reporte "parches sin PR upstream" disponible.
- **Fork de enterprise:** mismo patrón, sin PR upstream (repo privado). Regla de lineamientos reforzada en la UI: preferir módulo de extensión; el parche directo a enterprise requiere `reason` obligatorio y aprobación del líder técnico.

## 6. Webhooks y sincronización

- Controller HTTP `/repo_manager/webhook/<backend_id>`: verificación HMAC (`X-Hub-Signature-256`) contra `webhook_secret_encrypted`; firma inválida → 403 + log. Eventos: `push`, `pull_request`, `pull_request_review`, `member`, `team`, `branch_protection_rule` / ruleset events, `repository`.
- Procesamiento asíncrono: el controller solo valida y encola (queue_job); respuesta 200 inmediata.
- Cron de reconciliación completa cada 6 h: fuente de verdad = GitHub para el estado real, Odoo para la política declarada. Diferencias → drift.

## 7. Seguridad Odoo

Grupos:
- `Repo Manager / Lectura`: ver inventario, PRs, auditoría propia.
- `Repo Manager / Líder`: todo lo anterior + grants, políticas, promociones, wizards, resolución de drift.
- `Repo Manager / Administrador`: backend, credenciales, plantillas de política, listas de bypass.

Reglas duras:
- `repo.audit.log`: create-only para todos (ni admin edita/borra).
- Credenciales: nunca visibles en UI después de guardadas (write-only), cifradas at-rest.
- Ninguna operación destructiva en GitHub sin confirmación explícita (patrón PCM).

### 7.1 Roles operativos (configuración, no código)

Los roles concretos se configuran en ajustes del módulo (`res.config.settings`, sección Repo Manager) y en datos — el código nunca hardcodea personas:

- **Líder técnico** (`technical_lead_user_id`, res.users): receptor por defecto de drift, bypass, conflictos de sync de forks y repos creados fuera de Odoo. Integra la lista de bypass por defecto. *(Asignación inicial: Daryl.)*
- **Leadership** (`leadership_user_ids`, res.users múltiple): reciben copia de todo uso de bypass y del reporte de offboarding. *(Asignación inicial: Diego.)*
- **Owners por plantilla**: cada plantilla de política con CODEOWNERS referencia un `repo.team` de owners; los miembros del team SON los owners (se administran desde Odoo, se reflejan como team real en GitHub). Debe tener mínimo 2 miembros para no ser cuello de botella (validación al aplicar la política). *(Owners de localización iniciales: Daryl y Diego.)*
- **Responsables de forks** (`forks_responsible_user_ids`, múltiple; default = líder técnico, overrideable por repo): reciben los conflictos de sync y el reporte de parches vivos. *(Asignación inicial: Daryl y Diego.)*
- **Revisores por defecto por repo** (`default_reviewer_ids` en `repo.repository`, fallback: líder técnico): destinatarios de la actividad de revisión al abrirse un PR (ver `repo.pull.request`).
- **Responsable de testeo por proyecto** (`qa_user_id` en `project.project`, con fallback global configurable): destinatario de la actividad de testeo al mergearse el PR que resuelve una tarea del proyecto.
- **Revisión efectiva de PRs**: puede hacerse desde Odoo (acciones con OAuth del usuario) o directo en GitHub; el módulo mantiene consistencia en ambos casos.

### 7.2 Matriz de notificaciones

| Evento | Destinatario | Mecanismo |
|---|---|---|
| PR abierta | Revisores por defecto del repo (u owners si toca rutas CODEOWNERS) | Actividad con proyecto/tarea/link |
| PR aprobada | — (se marca hecha la actividad de revisión) | Automático |
| PR mergeada | Responsable de testeo del proyecto, en la tarea vinculada | Actividad (+ mover a "A probar" si está configurado) |
| PR cerrada sin merge | — (actividad de revisión cancelada) | Nota en chatter |
| PR > 7 días abierta | Autor | Actividad |
| PR sin PR upstream en fork OCA (mensual) | Responsables de forks | Actividad |
| Promoción pendiente de aprobación | Aprobadores requeridos | Actividad + chatter |
| Promoción fallida | Solicitante + líder técnico | Actividad |
| Drift detectado (permisos o política) | Líder técnico | Actividad + chatter en el repo |
| Bypass usado | Líder técnico + leadership | Actividad (no silenciable) + audit log |
| Conflicto de sync de fork | Responsables de forks | Actividad |
| Repo nuevo creado fuera de Odoo | Líder técnico | Actividad |
| Firma inválida / miembro sin firma en repo con firma requerida | Miembro + líder técnico | Actividad |
| Offboarding ejecutado | Leadership + administrador | Reporte por chatter |
| Error de conexión del backend / rate limit crítico | Administrador | Actividad |

Regla general: Odoo es el cockpit del ciclo de PR (actividades de revisión y testeo) y de la gobernanza (drift, bypass, promociones, forks). Las notificaciones nativas de GitHub siguen existiendo para quien trabaje allí; el módulo garantiza consistencia entre ambas vías sin generar actividades duplicadas para un mismo evento (una actividad por PR, cerrada automáticamente sea cual sea la vía por la que se resolvió).

## 8. Política de bypass (para lineamientos v1.1)

- El bypass existe solo para incidentes en los que el flujo de hotfix es demasiado lento. No es un carril rápido de conveniencia.
- Lista de bypass por plantilla, mínima (líder técnico; extensible por decisión del administrador).
- Todo uso: registro inmutable + actividad automática a leadership. Nunca silencioso.
- El módulo detecta bypasses vía audit log de GitHub / eventos y los registra aunque ocurran fuera de Odoo.

## 9. Firma de commits (rollout)

- Método: firma SSH (no GPG). Guía de setup de 3 comandos incluida en el onboarding.
- `repo.member.signing_configured` se verifica contra las signing keys registradas en GitHub (API).
- El ruleset `require_signed_commits` se activa por repo solo cuando el 100% de los miembros con push a ese repo tienen firma configurada (validación en el wizard de aplicar política; bloquea la activación prematura).
- Orden de rollout: `localizacion` → `cliente-estandar` → resto.

## 10. Fases de implementación

Cada fase termina con FRENO (sin commit) hasta aprobación de Daryl. Tests + smoke por fase.

**F0 — Fundaciones**
Esqueleto del módulo, grupos de seguridad, `repo.backend` con cifrado de secretos y prueba de conexión (GitHub App real de la org), infra queue_job, controller de webhook con HMAC (solo validación + log).
*DoD:* conexión verde contra la org real; webhook de prueba verificado; secreto ilegible en DB.

**F1 — Espejo + Auditoría inicial (entregable indispensable)**
Sync de solo lectura: repos, teams, members, colaboradores, ramas relevantes, protecciones existentes. Clasificación de repos. **Entregable formal: Reporte de Auditoría Inicial** (documento generado por el módulo): por repo — quién tiene qué acceso, qué ramas están sin proteger, forks y su atraso vs upstream, cuentas sin vínculo a empleado. Sin aplicar ningún cambio en GitHub.
*DoD:* inventario completo de la org; reporte de auditoría entregado y revisado; 0 escrituras a GitHub.

**F2 — Permisos**
`repo.member` ↔ usuarios/empleados, `repo.access.grant` con aplicación real, teams gestionables, onboarding/offboarding, drift de permisos.
*DoD:* alta y revocación de un grant reflejadas en GitHub; offboarding de un usuario de prueba limpio; drift sintético detectado.

**F3 — Política**
`repo.policy.template` + generación/aplicación de rulesets por API, CODEOWNERS generado, patrones de rama y commit, drift de política, validación de firma. Aplicación piloto sobre 1 repo de prueba, luego rollout por clasificación. Cierra con el **wizard "Crear repositorio"** (incluye variante fork gobernado): con plantillas de política ya operativas, los repos nuevos nacen gobernados.
*DoD:* ruleset aplicado y verificado en repo piloto; push con mensaje inválido rechazado por GitHub; drift de política detectado y resoluble en ambos sentidos; repo creado end-to-end desde el wizard en la org sandbox con ramas + ruleset + CODEOWNERS + grants verificados; fallo intermedio simulado deja el repo en `provisioning_error` reintentabl​e.

**F4 — Operación (gestión de PRs desde Odoo + promociones)**
Gestión completa de PRs: menú "PRs Pendientes", vínculo a proyectos/tareas, OAuth user-to-server por miembro, acciones aprobar/pedir cambios/comentar/mergear con atribución real, ciclo de actividades (revisión → cierre automático → testeo en la tarea al merge, con `qa_user_id` por proyecto y etapa "A probar" opcional), alertas de antigüedad; wizard "Crear rama desde ticket"; `repo.promotion` con pre-validaciones (sin bridge) y merge por API; auditoría completa.
*DoD:* PR real abierto por webhook genera actividad con proyecto y tarea correctos; aprobación desde Odoo aparece en GitHub atribuida al usuario y satisface la required review; merge desde Odoo cierra la actividad de revisión y crea la de testeo en la tarea; revisión hecha directo en GitHub deja Odoo consistente sin actividades duplicadas; rama creada desde un ticket real; promoción staging→support completa en repo piloto; promoción bloqueada correctamente al fallar un check.

**F4-B — Visor de diff en Odoo** (sub-entregable separable)
Pestaña de diff read-only en el form del PR (archivos por API, colapsable, highlight básico). Si se pospone, F4 sale con el link directo al diff de GitHub sin bloquear el flujo.
*DoD:* diff de un PR de ≥5 archivos legible en Odoo; archivos grandes truncados con aviso y link.

**F5 — Forks**
Rol mirror/patch, job de sync ff-only + reaplicación de parches, `repo.patch`, reporte de parches vivos, manejo de conflicto de sync.
*DoD:* fork OCA piloto sincronizado; parche de prueba trackeado; conflicto simulado genera actividad sin forzar nada.

**F6 — Bridge PCM**
`primate_repo_manager_pcm_bridge`: menú en PCM, vínculo de repos, pre-validación de promociones consultando deploy/health de staging en PCM.
*DoD:* menú visible solo con PCM instalado; promoción a prod bloqueada si staging no está healthy en PCM.

## 10.1 Límite verificado: la transferencia de repositorios no es orquestable

**Verificado en septiembre de 2026.** El endpoint `POST /repos/{owner}/{repo}/transfer`
existe, pero un token de instalación de App está acotado a UNA cuenta y la transferencia
es una operación entre dos. Falla con `Resource not accessible by integration` tanto con
token de instalación como con **token de usuario user-to-server** —el mismo que §3 prevé
para atribuir las aprobaciones de PR en F4—. El único que funciona es un PAT clásico, que
§3 descarta explícitamente.

Fuente: https://github.com/orgs/community/discussions/60014 (explicación de gr2m,
mantenedor de Octokit, más errores reproducidos por usuarios con los tres tipos de token).

**Consecuencia:** la migración de la cuenta `primateuy` a la organización `PrimateUy-SAS`
NO se puede ejecutar desde el módulo. Va por procedimiento aparte. El módulo sí puede
identificar qué falta migrar, ordenar el trabajo y verificar cada transferencia después de
hecha, aplicando la gobernanza al repositorio ya movido.

### 10.1.1 La ruta vieja MIENTE después de una transferencia

**Verificado en el ensayo del 2-sep-2026**, contra repositorios descartables creados en
`primateuy` y transferidos a la organización de pruebas.

GitHub deja una **redirección permanente** desde la ruta anterior. Después de mover
`primateuy/X` a `destino/X`:

```
GET /repos/primateuy/X   ->  200 OK
                             { "full_name": "destino/X",
                               "owner": { "login": "destino" } }
```

Es decir: **el código de estado de la ruta vieja no sirve para verificar nada.** Quien
compruebe «ya no está en el origen» pidiendo la ruta vieja y mirando si da 404 va a
concluir que la transferencia no ocurrió, cuando ocurrió.

Y hay una consecuencia peor que un informe equivocado. Un procedimiento de limpieza que
recorra los dueños posibles borrando «lo que responda 200» va a emitir un
`DELETE /repos/primateuy/X` creyendo que limpia el origen — y esa ruta **apunta al
repositorio en su dueño nuevo**. Borraría el repositorio ya migrado.

**REGLA PARA LA MIGRACIÓN REAL. Toda verificación va por `owner.login` del cuerpo de la
respuesta, nunca por el código de estado ni por la ruta consultada.** Un repositorio está
migrado cuando su `owner.login` es el destino, y sólo entonces.

El script del ensayo lo resuelve en `duenio_real()`
(`scripts/sandbox/ensayo_migracion.py`), que pregunta por ambos dueños posibles y devuelve
el que declara el cuerpo; la fase `verificar` compara dueños, y la limpieza borra una sola
vez por la ruta real. El procedimiento definitivo tiene que hacer lo mismo.

### 10.1.2 Lo demás que dejó el ensayo

- **El PAT clásico tiene que ser de la cuenta dueña** (`primateuy`), no de un colaborador
  con permiso de escritura: sólo el dueño puede crear repositorios en su propia cuenta.
- **La cuenta que transfiere necesita poder crear repositorios en el destino.** Con
  `members_can_create_repositories` cerrado en la organización, la vía elegida fue subir
  la cuenta a Owner durante la ventana y bajarla al terminar — puntual, visible y
  reversible, en vez de abrir la política global.
- **La revocación del PAT se comprueba, no se declara.** Se reintenta una llamada con el
  mismo token y se exige 401. En el ensayo, la primera comprobación devolvió 200 y la
  segunda 401: entre revocar y que el token deje de responder puede pasar un momento, así
  que la fase se reintenta hasta el 401 en vez de darla por buena.
- **La transferencia es asincrónica**: responde y el repositorio aparece en el destino
  unos segundos después. Se confirma releyendo, no por la respuesta del POST.


## 10.1.3 Sin organización no hay teams: qué significa «permisos» hasta la migración

**Registrado el 2-sep-2026, al instalar la App de escritura sobre la cuenta real.**

`primateuy` es una CUENTA DE USUARIO, no una organización (ver §10.1 y la auditoría de
F1). De ahí se sigue algo que conviene tener escrito antes de que alguien lo busque como
un bug:

- **No existen teams.** Los teams sólo viven dentro de una organización.
- **Los permisos de organización de una GitHub App no aplican.** Al instalar la App de
  escritura sobre `primateuy` se pidió `Members: Read-only` y GitHub simplemente **no lo
  concedió**: la instalación quedó con `administration` y `metadata` y nada más. No es un
  error de configuración ni un permiso pendiente de aprobar — es que ese permiso no
  significa nada sobre una cuenta de usuario.

**Consecuencia operativa.** De las operaciones de permisos que el módulo implementa, sobre
la cuenta real hoy sólo pueden ejecutarse las de **grant directo de colaborador**:

    collaborator_grant · collaborator_revoke        -> funcionan
    team_repo_grant · team_repo_revoke              -> no hay teams
    team_member_add · team_member_remove            -> no hay teams

Están implementadas y probadas contra la organización sandbox, que sí es una org. No
fallan por un bug: fallan porque no hay sustrato. Un offboarding contra `primateuy`
significa quitar grants directos, y nada más.

**Y es un argumento más para la migración**, además de los ya registrados: la gobernanza
por equipos —que es la forma escalable de manejar accesos, y la que la plantilla de
CODEOWNERS presupone— no existe hasta que los repositorios vivan en la organización.

### 10.1.4 Otro argumento de migración: el escaneo de secretos

Verificado el 4-sep-2026 sobre los permisos concedidos. **Secret scanning sobre
repositorios privados es una función paga** (Advanced Security); en los públicos funciona
con el plan gratuito. De los 113 repositorios de la cuenta, **31 son privados**, y son
justamente los de cliente — donde un secreto filtrado cuesta más.

Con la cuenta personal el resultado esperable es un `403` de techo de plan sobre esos 31.
El módulo lo va a reportar como *no legible por límite de plan*, que es honesto pero no es
una respuesta: **«no pudimos mirar» no es «no hay secretos»**.

Se suma a los argumentos de §10.1 y §10.1.3 —sin organización no hay teams, la
transferencia no es orquestable— con una diferencia de naturaleza que conviene notar: los
otros son límites de la API; éste es un límite de plan, y se levanta pagando sin migrar
nada. Pero el plan de organización es donde esa función tiene precio razonable, así que en
la práctica empuja en la misma dirección.

## 10.2 Decisiones abiertas

**Doble aprobación de planes de escritura — sin resolver, para el rollout de F3.**
Registrado el 2-sep-2026, al construir `repo.write.plan`.

Hoy quien arma un plan puede aprobarlo: NO hay regla de "no aprobar lo propio". Se dejó
así a propósito y no por descuido.

- En el sandbox sería inaplicable: hay dos cuentas y las dos son de la misma persona.
- Y es una decisión de política, no un parámetro que corresponda fijar desde el código.

Si alguna vez se activa, la forma correcta **no es global sino por tipo de acción**: las
operaciones destructivas —revocar accesos, borrar ramas o repositorios, cambiar la rama
por defecto— piden un segundo aprobador, y las demás no. Una regla global agregaría
fricción a lo rutinario sin agregar seguridad donde importa, y la fricción inútil termina
buscándole la vuelta.

Se conversa en el rollout de F3, cuando la gobernanza empiece a aplicarse sobre
repositorios reales y haya más de un aprobador posible.

## 11. Decisiones registradas (29-jul-2026)

1. Nombre: `primate_repo_manager`. Odoo 19.0 Enterprise.
2. Required status checks: obligatorios en toda plantilla; se agregan a lineamientos v1.1.
3. Rama desde ticket: por botón/wizard (no automática); automatización por etapa+etiqueta opcional y OFF por defecto. Multi-repo por ticket soportado. Vínculo inverso por parseo de nombres.
4. Bypass: permitido, lista mínima (líder técnico), solo emergencias, siempre auditado y notificado. Doble aprobación a prod se mantiene (1 de las 2 debe ser owner donde aplique CODEOWNERS).
5. CODEOWNERS: team de owners definible desde Odoo (líder técnico + designados); 1 sola aprobación de owner en flujo diario a base.
6. Formato de commit propio `[ADD]/[IMP]/[FIX][NRO]` en español, exigido por regex (push rule + CI). Mapeo documentado a Conventional Commits por si se adopta tooling futuro.
7. Firma de commits: sí, SSH, rollout gradual gated por configuración del 100% de los pushers del repo.
8. Promociones: alcance completo con pre-validaciones (incluye estado de deploy en PCM vía bridge).
9. Forks: patrón espejo + parches; espejo intocable (solo sync ff-only); parches con flujo normal de PR; tracking de parches vivos; PR a OCA upstream recomendada; parche a enterprise con justificación obligatoria.
10. Auditoría inicial: entregable formal e indispensable de F1, previo a cualquier escritura en GitHub.
11. Creación de repositorios desde el módulo (F3): wizard con clasificación, plantilla de política, estructura de ramas de lineamientos, scaffolding por template repo y aplicación inmediata de gobernanza; variante de fork gobernado con estructura espejo + parches de nacimiento. La creación manual de repos en GitHub queda desaconsejada en lineamientos v1.1 (y detectada como evento en la auditoría: repo nuevo sin origen en Odoo → actividad al líder).
12. Roles iniciales: líder técnico = Daryl; leadership = Diego; owners de localización = Daryl y Diego; responsables de forks = Daryl y Diego. Todos configurables en ajustes, nunca hardcodeados.
13. Gestión completa de PRs desde Odoo (F4): menú "PRs Pendientes"; actividad de revisión al abrirse un PR (con proyecto y tarea que resuelve); acciones de aprobar/pedir cambios/comentar/mergear desde Odoo ejecutadas con OAuth user-to-server para atribución real a la persona; al aprobar se cierra la actividad de revisión; al mergear se genera actividad de testeo en la tarea vinculada para el responsable de QA del proyecto (`qa_trigger` configurable merge/approval, default merge). Convivencia con revisión directa en GitHub garantizada por webhooks sin duplicación.
