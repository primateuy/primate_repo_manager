# CLAUDE.md — primate_repo_manager

Módulo Odoo 19.0 Enterprise de PrimateUY para gobernanza de repositorios GitHub.
El spec completo está en `spec-primate-repo-manager.md` en la raíz del repo. Leelo antes de cualquier tarea.

## Regla de oro del workflow

Trabajás por fases chicas y verificables (F0–F6 del spec). **Antes de cualquier commit, frená y escribí `FRENO`** con un resumen de: qué cambiaste, qué tests corriste y su resultado, y qué falta. No commitees hasta recibir aprobación explícita. Nunca ejecutes una fase completa de una: proponé el desglose en pasos, esperá OK, implementá de a un paso.

## Contexto del proyecto

- Odoo 19.0 Enterprise. Python 3.12+.
- El módulo NO ejecuta git ni clona repos. Toda interacción con GitHub es vía REST/GraphQL API autenticada como GitHub App (tokens de instalación de corta vida).
- Principio rector: Odoo declara y aplica la política; GitHub es el enforcement. Nunca implementes validaciones "solo en Odoo" que dependan de que la gente no use GitHub directo.
- Prefijo de modelos: `repo.*`. Módulo core: `primate_repo_manager`. Bridge (F6): `primate_repo_manager_pcm_bridge` con `auto_install: True`.

## Convenciones de código PrimateUY

- **Indentación: tabs.** En Python, XML y JS. No espacios.
- Commits: `[ADD]|[IMP]|[FIX][<nro_ticket>] descripción en español`. Ejemplo: `[ADD][2041] modelo repo.backend con cifrado de credenciales`.
- Rama base del repo: `19.0`. Ramas de trabajo: `feature/<nro>-descripcion` o `fix/<nro>-descripcion` desde `19.0`.
- Estructura de módulo estilo OCA: `models/`, `views/`, `wizards/`, `controllers/`, `data/`, `security/`, `tests/`, `static/description/`.
- Docstrings estilo Google, en español. Comentarios inline solo donde el porqué no es obvio.
- Logging con `_logger`, nunca `print()`.
- Todo `sudo()` lleva comentario justificativo. SQL crudo prohibido salvo justificación documentada.

## Convenciones Odoo 19

- Vistas de lista: `<list>`, NO `<tree>` (deprecado).
- Sin `attrs`/`states` en vistas: usar atributos directos (`invisible`, `readonly`, `required` con expresiones Python).
- `_description` obligatorio en todos los modelos.
- Chatter: heredar `mail.thread` + `mail.activity.mixin` en modelos con estados o acciones humanas (`repo.access.grant`, `repo.promotion`, `repo.repository`, `repo.patch`).
- Traducciones con `_()`; strings de UI en español.

## Patrones obligatorios del módulo

- **queue_job para toda llamada a la API de GitHub.** Ninguna llamada HTTP en el hilo del request del usuario, salvo el "Probar conexión" del backend (con timeout corto). Canales: `root.repo_manager` (sync), `root.repo_manager.apply` (escrituras a GitHub).
- **Escrituras a GitHub idempotentes:** antes de aplicar (grant, ruleset, CODEOWNERS), leer estado actual y aplicar solo el diff. Reintento seguro.
- **Errores de API nunca silenciosos:** fallo en un job → estado de error en el registro + mensaje en chatter. Prohibido `except: pass`.
- **Secretos:** private key y webhook secret cifrados at-rest (Fernet con clave derivada de secreto de instancia; NO texto plano en `ir.config_parameter`). Campos write-only en UI: una vez guardado, no se vuelve a mostrar el valor.
- **Webhook controller:** `auth='public'`, `csrf=False`, verificación HMAC `X-Hub-Signature-256` con `hmac.compare_digest` ANTES de cualquier procesamiento; firma inválida → 403 y log de warning. El controller solo valida y encola; responde 200 inmediato.
- **`repo.audit.log` es inmutable:** ACL sin write/unlink para ningún grupo; `create` solo desde código de sistema. No agregues botones de edición.
- **Nada destructivo sin confirmación:** revocaciones masivas, reaplicación de política, offboarding → wizard con resumen de lo que va a pasar antes de ejecutar.
- **Flags de seguridad cross-proceso se leen frescos** (search/read en el momento de uso, no cacheados) — lección permanente de PCM.
- **Defaults silenciosos de primitivos son el enemigo:** validá configuración explícitamente; un campo vacío no puede colapsar a un comportamiento peligroso.

## Testing

- Tests por fase, obligatorios antes de cada FRENO. `odoo-bin -c <conf> -d <db_test> -i primate_repo_manager --test-enable --stop-after-init`.
- Toda interacción con la API de GitHub en tests va **mockeada** (responses/vcr o mocks manuales de la capa cliente). Ningún test pega a GitHub real.
- Un test verde no alcanza: verificá que la semántica del test refleja el escenario real del spec (lección PCM). Los fixtures deben describir escenarios reales (un repo fork con espejo+parches, un grant vigente y uno vencido, etc.).
- **LA MUTACIÓN AUDITA LOS TESTS, NO EL CÓDIGO.** Toda guarda se verifica ROMPIÉNDOLA una
  vez: se introduce a propósito el error que la guarda debería impedir y se comprueba que
  algún test se ponga en rojo. Una guarda que nunca falló no está probada, está supuesta.

  El rendimiento real de esta práctica, medido en F2: de las mutaciones que corrimos, tres
  **no** se cazaron — y en los tres casos el problema estaba en el test, no en el código.

  1. El arnés registraba método y URL pero no el **cuerpo** de la petición, así que los
     tests afirmaban «hubo una escritura» sin decir con qué. Una reversión que devolviera
     un permiso menor que el original pasaba en verde.
  2. Un test decía comprobar que el umbral se decide con lo enumerado y no con el espejo,
     pero su premisa —«el espejo arranca vacío»— era falsa: el enumerado corre antes de la
     decisión y lo llena. No distinguía las dos lógicas.
  3. Un test de F1 sobre el upstream de los forks pasaba contra un fixture donde el listado
     de GitHub traía `parent`, cosa que GitHub no hace nunca. Probaba una propiedad que no
     se cumplía en la realidad, y por eso la auditoría real salió con los upstreams vacíos
     sin que nada se pusiera rojo.

  Ninguno de los tres se habría encontrado leyendo los tests. La mutación es lo que
  convierte «tengo cobertura» en «sé qué cubre».
- Casos de seguridad mínimos: webhook con firma inválida → 403; usuario del grupo Lectura no puede crear grants; audit log no editable ni por admin.

## Capa cliente GitHub

- Un solo punto de acceso: `models/github_client.py` (clase `GithubClient`), sin dependencia de PyGithub — cliente propio fino sobre `requests` para controlar exactamente permisos, headers, rate limits y errores. Todos los modelos usan el cliente, nunca `requests` directo.
- Manejo de rate limit: leer headers `x-ratelimit-*`; si quedan <100 requests, los jobs de sync se re-encolan con eta diferida.
- Paginación siempre manejada (Link header).

## Qué NO hacer

- No implementar nada de deploy, servidores ni AWS: eso es PCM. Si una tarea parece necesitarlo, frenar y preguntar.
- No crear repositorios, ramas, merges ni ninguna escritura en la org real de Primate durante desarrollo: todo contra la org/repo sandbox de pruebas definida en la config de dev (`repo.backend` de test apunta a una org sandbox).
- No usar PATs en ningún flujo, ni siquiera para tests manuales.
- No tocar la rama espejo de forks por ningún camino que no sea el job de sync ff-only.
