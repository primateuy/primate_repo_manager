# CLAUDE.md — primate_repo_manager

Este archivo le da a Claude Code (claude.ai/code) las instrucciones para trabajar en
este repositorio.

Módulo Odoo 19.0 Enterprise de PrimateUY para gobernanza de repositorios GitHub.
El spec completo está en `spec-primate-repo-manager.md` en la raíz del repo. Leelo antes de cualquier tarea.

## Regla de oro del workflow

Trabajás por fases chicas y verificables (F0–F6 del spec). Nunca ejecutes una fase completa de una: proponé el desglose en pasos, esperá OK, implementá de a un paso.

### El orden del cierre de un paso — no se altera

1. Terminás el paso y corrés los tests.
2. **Commiteás en local.**
3. **Mostrás el log de commits** (`git log --oneline` de lo que subiría) junto con el resumen del paso: qué cambiaste, qué tests corriste y su resultado, qué falta.
4. **Esperás.** La aprobación del paso en la respuesta del usuario **es** el OK del push.
5. Recién ahí pusheás.

**El log se ve siempre ANTES del push, sin excepción.** Que el paso vaya a ser aprobado no autoriza a adelantarse: el punto de mostrar el log es que el usuario decida con él delante, no que se entere después. «Hecho y pusheado» en el mismo mensaje que muestra el log es una violación de esta regla aunque el contenido esté bien — lo que falla es el orden, y el orden es la garantía.

Esta regla reemplaza al `FRENO` previo al commit: commitear en local es reversible y no necesita permiso; publicar sí.

## Reglas de construcción para B, C y D — leer antes de tocar el espejo

Los webhooks llegan en F4, pero **B y D se construyen como si ya estuvieran**. Hoy el
espejo sólo cambia cuando corre una auditoría; el día que un evento de GitHub pueda
cambiarlo en cualquier momento, lo que se haya construido asumiendo lo contrario hay que
rehacerlo. Estas cuatro reglas cuestan poco ahora y mucho después.

1. **`run_id` no siempre va a estar.** Un hallazgo nacido de un webhook no tiene corrida.
   El campo sigue siendo obligatorio hoy —cambiarlo sin necesidad es peor— pero **no
   escribas lógica nueva que asuma que todo hallazgo pertenece a una corrida**. Si
   necesitás «lo último», pensá si «lo último que se supo» sirve igual que «lo de la
   última corrida». *Deuda conocida:* el conteo de A3 ya lo asume.

2. **Un objeto del espejo, un método que lo actualiza.** Si tu código lee de GitHub y
   escribe en el espejo, tiene que hacerlo por el mismo upsert que usa el sync. Dos
   caminos que escriben el mismo objeto divergen, y el día del webhook habrá tres.

3. **`last_seen_at` y origen en lo que agregues al espejo.** Cuándo se supo y por dónde
   entró. Sin eso, «¿esto está desactualizado o es así?» no tiene respuesta, y con
   webhooks conviviendo con auditorías esa pregunta se vuelve diaria.

4. **Nada que incremente lo que puede contarse.** Un contador que alguien suma es una fila
   compartida: dos procesos se pisan y el resultado es un reintento silencioso que
   multiplica el trabajo. Derivá contando. Está probado dos veces —el avance del plan
   (A4.5) y los contadores de la corrida (A10)— y en A10 costó medir contra el sandbox
   para descubrir que un `store=True` inocente reintroducía el problema entero.

   *Corolario que también costó medir:* **no escribas valores que no cambiaron.** Un
   `write` con los mismos datos igual genera un `UPDATE ... SET write_date`, y sobre una
   fila compartida —la de una persona que colabora en varios repos— eso basta para matar
   al job de al lado.

## Lo visual: tres reglas que no se negocian

Decididas el 5-sep-2026, después del ensayo de D2. Valen para **toda** pantalla nueva y
para toda migración: lo que queda de D2 (D2.4 en adelante), B, C, E y lo
que venga.

### 1 · El entregable de diseño es la especificación, no una referencia

`~/Downloads/Repo Manager-print.html` (24 páginas de mockups) y
`Repo Manager Prototipo.dc.html` (el interactivo) mandan. **Exactos, no parecidos.** Los
tokens ya están traducidos en `static/src/scss/tokens.scss` y se usan por variable, nunca
por valor literal. Antes de dibujar una pantalla se lee su página del print; el prototipo
manda en lo que se mueve (drag & drop, confirmación irreversible).

### 1b · Modo oscuro: NO se improvisa — decidido el 5-sep-2026

Odoo 19 resuelve el tema por preferencia del navegador o del usuario, así que la app
puede estar en oscuro. El entregable de diseño es un sistema **claro** y no trae variante
oscura.

**La variante se le pide al diseño; el módulo no la inventa.** El sistema tiene dueño, y
los pares sólido/tenue de severidad en oscuro son exactamente la clase de decisión que no
se improvisa desde el código: un rojo que funciona sobre blanco no funciona sobre #1B1D26,
y elegirlo a ojo rompe la única cosa que el color tiene asignada en este sistema —qué tan
grave es algo—.

Mientras llega la respuesta: **las pantallas quedan claras y NO se tocan los tokens.**
Cada componente pinta su propio fondo, así que se leen bien sobre cualquier tema; se ven
como una isla clara dentro de una app oscura, y eso es aceptado a sabiendas. Un `@media
(prefers-color-scheme: dark)` puesto por las nuestras sería inventar el sistema que
estamos esperando.

### 2 · El producto completo siempre se ve; lo no implementado se muestra APAGADO

La filosofía del menú —«lo futuro se ve, no se toca»— vale **dentro de cada pantalla**, no
sólo en la navegación. Un botón, una pestaña, una columna o un bloque de una funcionalidad
que todavía no existe va **visible y desactivado**, con dos cosas escritas: qué es, y con
qué bloque llega.

    Comparar con anterior — llega con E2
    Pestaña Módulos — llega con D2
    Meta configurable — llega con E4

Por qué: un producto que se muestra a pedazos parece más chico de lo que es, y quien lo
opera no puede planificar contra lo que no ve. Y al revés: un botón que existe y no hace
nada es peor que uno apagado que explica. Ya lo hace el asistente de operaciones con los
tipos sin manejador (`is_supported`), y ésa es la forma: **derivar el apagado de un hecho
del código**, no de una lista que alguien mantiene a mano.

Hay una sola implementación del patrón —la clase y la plantilla de «casillero apagado»—:
cinco copias divergen y la que se mira menos envejece mal.

### 3 · Cada pantalla nace visual y funcional a la vez

Cuando arranca un bloque, su pantalla se construye **desde el día uno** contra el mockup
exacto, con tokens y patrones.

- **Nunca** funcionalidad sobre cara vieja «para migrar después». La deuda visual se paga
  cara: ya pasó, y obligó a un tramo de migración entero.
- **Nunca** maqueta detallada de algo que todavía no existe. Una pantalla linda sobre nada
  es una promesa que alguien va a leer como un hecho — para eso está la regla 2, que
  muestra el casillero apagado y no la maqueta.

El precedente que la fija: D1.4 y el patrón irreversible salieron bien porque se
construyeron así.

## Vistas y acciones: dos cosas que el servidor no valida

1. **El `context` y el `domain` de una acción van en UNA SOLA LÍNEA.** El evaluador de
   expresiones del NAVEGADOR no acepta la concatenación implícita de literales adyacentes
   —`'una parte' 'otra parte'`—, que en Python sí es válida. El servidor guarda ese texto
   sin mirarlo: el módulo carga perfecto y la pantalla revienta al hacer clic con
   «Can not parse python expression». Hay un test que lo vigila
   (`test_acciones_abren.py`), y el script `scripts/sandbox/abrir_todas_las_pantallas.py`
   abre todas las acciones en un Chromium de verdad.

2. **Que el módulo instale no significa que las pantallas abran.** Es la misma familia que
   el punto anterior y ya mordió tres veces: un `groups_id` que en 19 se llama `group_ids`,
   un `target` inválido, un campo calculado sin `search` en un filtro. Ninguna la vio la
   instalación. Antes de dar por terminada una pantalla, abrila.

## Contexto del proyecto

- Odoo 19.0 Enterprise. Python 3.12+.
- El módulo NO ejecuta git ni clona repos. Toda interacción con GitHub es vía REST/GraphQL API autenticada como GitHub App (tokens de instalación de corta vida).
- Principio rector: Odoo declara y aplica la política; GitHub es el enforcement. Nunca implementes validaciones "solo en Odoo" que dependan de que la gente no use GitHub directo.
- Prefijo de modelos: `repo.*`. Módulo core: `primate_repo_manager`. Bridge (F6): `primate_repo_manager_pcm_bridge` con `auto_install: True`.

## Comandos

```bash
# instalar / actualizar
odoo-bin -c <conf> -d <db> -i primate_repo_manager --stop-after-init
odoo-bin -c <conf> -d <db> -u primate_repo_manager --stop-after-init

# la suite entera del módulo. El --db-filter NO es opcional: ver abajo.
odoo-bin -c <conf> -d <db> --db-filter='^<db>$' -u primate_repo_manager \
         --test-enable --test-tags /primate_repo_manager --stop-after-init

# UNA clase / UN test
odoo-bin -c <conf> -d <db> -u primate_repo_manager --test-enable --stop-after-init \
         --test-tags /primate_repo_manager:TestConciliacion
odoo-bin -c <conf> -d <db> -u primate_repo_manager --test-enable --stop-after-init \
         --test-tags /primate_repo_manager:TestConciliacion.test_emision_huerfana

# los tours: la sintaxis es TAG/módulo, NO /módulo:tag
# (`/primate_repo_manager:post_install` corre CERO tests y sale en verde — post_install
#  se lee como nombre de clase. Verificado el 7-sep-2026.)
odoo-bin -c <conf> -d <db> -u primate_repo_manager --test-enable --stop-after-init \
         --test-tags post_install/primate_repo_manager

# ¿producción sigue cerrada? consulta GitHub y la base, no la memoria de nadie
odoo-bin shell -c <conf> -d <db> --no-http < primate_repo_manager/tools/chequeo_de_cierre.py
```

### El entorno, que no está escrito en ningún otro lado

| qué | dónde |
|---|---|
| `odoo-bin` | `~/Desktop/Odoo/shared/odoo/community-19.0/odoo-bin` |
| conf | `~/Desktop/Odoo/clients/primate-innobyt/primate.conf` — es el **único** que tiene el módulo en su `addons_path`, y el que lleva `repo_manager_key` |
| intérprete | `~/Desktop/Odoo/clients/19.0/Primate-Cloude-Manager/.venv/bin/python` (3.12.13). El del sistema no tiene las dependencias de Odoo |
| base de trabajo | `o19_primate_stg_12082026` (la de las capturas) · `o19_prm_dev` (con el bridge y PCM) |
| base de tests | una limpia y descartable: `-d prm_test_<fecha> -i primate_repo_manager` |

### Dos formas en que la suite sale verde sin haber probado los tours

Las dos aparecieron el 7-sep-2026 midiendo, y las dos dan **«0 failed»** — que es lo que
las hace peligrosas. **Antes de creerle a un verde, mirá el conteo de `skipped` y que el
total sea 426.**

1. **Sin `websocket-client` en el venv, los 7 tours no fallan: se saltean.** La corrida
   dice «0 failed, 0 error(s) of 426 tests» habiendo ejecutado 419. Instalado en el venv
   de PCM el 7-sep-2026; un venv nuevo lo vuelve a traer.

2. **El `dbfilter` del conf apunta a la base de staging, y la de test no le pasa.** El
   navegador del tour pide `http://127.0.0.1:8069/odoo/...`, el servidor no le sirve la
   base de test, y el tour muere por **timeout de 60 s** sin un error que diga qué pasó
   —Chrome arranca bien, así que parece un tour roto—. Con `--db-filter='^<db>$'` los
   mismos 7 tours pasan en 12 s. **Un tour que tarda exactamente 60 s no está fallando:
   no está llegando.**

**El número de referencia, medido el 7-sep-2026 sobre base limpia: 426 tests, 0 fallos, 0
errores, 0 salteados.** 419 unitarios + 7 tours.

**Un test que no está en `tests/__init__.py` no corre y nadie avisa.** Lo mismo con
`models/__init__.py`, donde además **el orden importa**: `repo_policy_audited` (el mixin)
va antes que quienes lo heredan.

### Scripts que no son producto — `scripts/sandbox/`

Se corren a mano, contra `prm-sandbox`, y ninguno forma parte del addon. Cada uno tiene su
docstring con el uso exacto; lo que hay que saber de cada uno:

| script | qué hace | cuándo se usa |
|---|---|---|
| `abrir_todas_las_pantallas.py` | abre TODAS las acciones del menú en un Chromium real y falla si alguna tira error de cliente | antes de dar por terminada cualquier pantalla (ver «Vistas y acciones») |
| `mirar_pantalla.py` | abre una corrida, aprieta Auditar y anota lo que se ve, con capturas | verificar un componente OWL de verdad, no razonando sobre el código |
| `poblar_sandbox.py` | siembra la org sandbox de forma idempotente; dry-run por defecto, `--apply` para ejecutar | preparar el banco de pruebas |
| `provocar_fallo.py` | borra un repo en GitHub mientras la auditoría corre, para ejercitar el camino feo | probar el ámbar y el contador de errores |
| `sonda_permisos.py` | pregunta a la API qué puede hacer la credencial | antes de asumir un permiso |

Necesitan `websocket-client`, Chromium en `/Applications`, y —los que escriben en
GitHub— un PAT fine-grained de sandbox en `PRM_SANDBOX_TOKEN`. Nunca un PAT de producción.

## Arquitectura — el recorrido completo, de la API a la bitácora

Cinco capas. Cada archivo nombrado abajo abre con un docstring largo que explica **por
qué** está como está; ese docstring es la fuente, esto es el índice.

**1 · Acceso a GitHub — dos clientes, y la separación es una garantía.**
`github_client.py` (`GithubAppAuth` + `GithubReadClient`) es incapaz de escribir: los
verbos no están escritos, y `test_read_only.py` parsea el módulo y exige que contenga
exactamente **una** escritura HTTP —el POST del token de instalación—. La escritura vive
aparte, en `github_write_client.py`, y sólo se llega por `repo.backend.write_client()`,
que se niega si el backend no es de entorno `sandbox`. Ese archivo también tiene el **mapa
de vocabularios de GitHub** (`role_name` vs `permission` vs el setter): leerlo antes de
comparar cualquier permiso, mordió cuatro veces.

**2 · El espejo — se llena por auditoría, un job por repositorio.**
`repo.audit.run` enumera y encola (`repo_audit_run.py`), `repo_sync.py` recorre y hace
upsert por `github_id`, y cada job escribe **su propia** `repo.audit.run.line`: los totales
se derivan contando, sin `store=True` (regla 4 de arriba; A10 lo midió). Modelos del
espejo: `repo.repository`, `repo.branch`, `repo.collaborator`, `repo.member`,
`repo.pull.request`, `repo.commit.sample`, `repo.workflow`, `repo.module` /
`repo.module.copy`.

**3 · El juicio — comparar lo observado contra lo declarado.**
`repo.audit.engine` (abstracto, idempotente: borra y rehace) lee el espejo, lo compara
contra `repo.policy.template` y sus reglas, y produce `repo.audit.finding` con severidad y
remediación **calculada y nunca ejecutada**. Los umbrales son configuración
(`repo.settings` + `DEFAULTS` en `res_config_settings.py`), la lógica es código testeado.

**4 · El embudo de escritura — la única forma de tocar GitHub.**
`repo.write.plan` + `repo.write.operation` (`repo_write_plan.py`, catálogo en
`OPERATION_KINDS`) → aprobación con confirmación por operación
(`wizards/repo_plan_approve.py`) → `repo_write_apply.py`. Tres cosas que definen el
embudo:

- **El congelamiento es por huella de contenido, no por estado.** Al aprobar se hashea lo
  que el plan va a ejecutar; el apply recalcula y compara. Renombrar el plan no invalida
  nada; agregar una operación sí.
- **El ciclo de cada operación:** leer estado previo → ejecutar → **verificar releyendo**
  (lo que devolvió la escritura no cuenta como verdad) → registrar. Las operaciones que
  *crean identidad* llevan un paso 2b: persistir el id devuelto antes de verificar.
- **B no estrena forma de escribir.** Los tipos nuevos entran al catálogo existente; el
  motor no se toca.

**5 · La bitácora — inmutable en el modelo, no en los ACL.**
`repo.audit.log` levanta excepción en `write()` y `unlink()` **incluso con `sudo()`**, los
enlaces son `ondelete="set null"` y guarda además el nombre en texto. **El rollback sale de
la bitácora, no del plan**: si el punto de retorno viviera en el plan, quien edita el plan
reescribe el punto de retorno. Ahí viven también los tres desenlaces de una emisión
huérfana (`action_conciliar`).

**Pantalla.** Componentes OWL en `static/src/`: `apagado` (la única implementación de la
regla 2), `bitacora`, `hallazgos`, `panel`, `plan/plan_ops`, `promocion`, `live_progress`.
Los tokens van primero en el bundle y el modo oscuro entra sólo por
`web.assets_web_dark` → `tokens.dark.scss`, así que **ningún componente pregunta en qué
tema está**. El avance en vivo va por bus; qué canal puede escuchar el navegador se decide
en `ir_websocket.py`, con lista blanca de modelos y chequeo de lectura.

**Trabajo en segundo plano.** Canal `root.repo_manager`, declarado en
`data/repo_queue_data.xml` — declararlo es lo que permite darle capacidad propia.

**Seguridad.** Tres grupos escalonados en `security/repo_security.xml`: Lectura → Líder →
Administrador, colgando de un `res.groups.privilege` (en Odoo 19 los grupos ya no llevan
`category_id`).

**El bridge (F6).** `primate_repo_manager_pcm_bridge`, `auto_install: True`. El core no
tiene **ninguna** referencia a PCM y hay un test que lo verifica recorriendo los archivos.

## Mapa de documentos — cuál contesta qué

| documento | la pregunta que contesta |
|---|---|
| `spec-primate-repo-manager.md` | qué es el producto, modelo de datos, fases F0–F6. **Leelo antes de cualquier tarea.** |
| `docs/PLAN-ETAPA-SANDBOX.md` | qué falta y en qué orden. Bloques A–E. Si algo sólo se puede hacer por shell, es funcionalidad faltante y vive acá |
| `docs/COBERTURA-DEL-DISENO.md` | ¿esto está completo? El entregable de diseño elemento por elemento. Se actualiza **en el mismo commit** que mueve el código |
| `docs/DESGLOSE-BLOQUE-B.md` | el bloque que sigue, desglosado, con los permisos de GitHub que hay que pedir a mano primero |
| `docs/GUIA-DE-USUARIO.md` | cómo se opera desde la pantalla. Ninguna sección se publica sin haber recorrido la pantalla real |
| `docs/RECORRIDO-DE-VALIDACION.md` | qué comprobar a mano y qué sería señal de problema |
| `docs/ENSAYO-D2.md`, `docs/REPORTE-TRAMO-D2.md` | qué pasó la primera vez que el embudo borró contenido |
| `docs/TRAMO-VISUAL.md` | el dimensionado de la migración visual y qué dejó hecho V0 |
| `README.md` | setup de la GitHub App, `repo_manager_key`, y **lo que la API de GitHub no permite** (transferir repos, plan y facturación, config de la App) |

## Convenciones de código PrimateUY

- **Indentación: tabs.** En Python, XML y JS. No espacios.
- Commits: `[ADD]|[IMP]|[FIX] descripción en español`. Ejemplo: `[ADD] modelo repo.backend con cifrado de credenciales`.
- **Sin número de ticket, y es deliberado hasta nuevo aviso:** el proyecto PRM todavía
  no existe en el Odoo de Primate, así que no hay número que poner. Inventar uno o
  dejar el corchete vacío sería peor que omitirlo. Cuando el proyecto exista se vuelve
  al formato con ticket —`[ADD][2041] …`— y se corrige esta línea, no los commits
  viejos.
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

### `git checkout <archivo>` para deshacer una mutación BORRA lo no commiteado

Pasó el 7-sep-2026 y llegó a estar pusheado. Una mutación tocó `repo_sync.py`; para
restaurarlo usé `git checkout` en vez de una copia, y el archivo volvió a HEAD — llevándose
puesta la integración del paso que estaba escribiendo y que todavía no estaba commiteada.
La suite había pasado ANTES de la mutación, así que el commit salió con un agujero y los
tests del paso quedaron rojos en el árbol publicado.

**La restauración de una mutación sale de una copia hecha antes, nunca de git**:

    cp <archivo> /tmp/<archivo>.orig     # antes de mutar
    cp /tmp/<archivo>.orig <archivo>     # después

Y hay una segunda forma de la misma trampa, que mordió el mismo día: sobre un archivo
**sin trackear** —uno recién creado por el paso en curso— `git checkout` no falla ni
restaura: **no hace nada**, y la mutación se queda puesta. El comando devuelve error
silencioso y el árbol queda mutado. Con la copia, los dos casos se comportan igual.

Y **la suite se corre después de restaurar, no sólo antes de mutar.** El verde previo no
dice nada sobre el árbol que se va a commitear.

### Con `--log-level=warn`, un verde NO IMPRIME NADA

Y una mutación que **sobrevive** se ve exactamente igual que un run que no llegó a
correr: las dos cosas son silencio. Pasó el 7-sep-2026 mutando B4.2 — tres mutaciones se
dieron por cazadas mirando una salida vacía, y las tres estaban vivas.

**Corré las mutaciones con `--log-level=info` y leé el renglón de `odoo.tests.result`
siempre**, tanto para el rojo como para el verde. Un rojo se anuncia solo; un verde hay
que ir a buscarlo, y es justo el que hay que ver cuando lo que se está probando es que
algo se rompa.

### Quitar una guarda del código NO la quita de la base

Medido el 7-sep-2026 mutando el índice único de plantillas. Odoo **no borra** un índice
declarado con `models.UniqueIndex` cuando alguien saca la declaración: sólo lo recrea si
la definición cambió. Así que la mutación «borro la guarda» corrió con la guarda todavía
puesta en Postgres y **pareció cazada por los tests equivocados**.

Para mutar una guarda que vive en la base hay que sacarla **de los dos lados**:

    psql -d <db> -c 'drop index if exists <nombre_del_indice>;'

Con el índice realmente ausente aparecieron los cuatro rojos que tenían que aparecer. Sin
ese paso, la mutación habría firmado una cobertura que no existía.

## Dos formas en que un test tapa el defecto que buscaba

Las dos costaron un defecto real y las dos se ven bien mientras se escriben.

### Un test de un mecanismo de registro NO fabrica las entradas

Si el mecanismo escribe entradas —bitácora, constancias, desenlaces—, el test las produce
**por el camino real**: aplica, revierte, concilia. Nunca las crea a mano.

Fabricarlas verifica **lo que el código debería hacer en vez de lo que hace**, y ahí el
test absorbe justo el defecto que venía a buscar. Pasó: la prueba de «un desenlace cierra
la cuenta abierta» creaba la entrada con el enlace a la operación puesto por el test,
cuando el código no lo ponía. Resultado: cada apply exitoso dejaba cuentas abiertas falsas
y la guarda de frenar se habría disparado sobre planes impecables — un falso positivo en
una guarda, que es la peor clase, porque **la guarda que grita sin razón termina ignorada**.

Vale igual para los dobles: uno que imita media interfaz miente en la mitad que no imita.
El GitHub simulado de la promoción tuvo que aprender a borrar de verdad por esto mismo.

### Un tour que se rompe tras una migración visual NO es ruido por definición

Cuando una pantalla cambia de estructura, los tours que la verificaban por su HTML se
rompen, y la reacción natural es ajustar el selector. **Antes de ajustarlo hay que leer qué
comprobaba el paso.** De tres tours rotos en la migración de hallazgos, dos eran
efectivamente selectores viejos y el tercero avisaba de un callejón sin salida: el clic en
la fila había dejado de abrir la ficha y con eso desapareció el camino hallazgo →
repositorio. Ajustar los tres de una habría tapado una funcionalidad perdida.

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

- Dos puntos de acceso y ninguno más: `models/github_client.py` (`GithubAppAuth` + `GithubReadClient`) y `models/github_write_client.py` (`GithubWriteClient`, al que sólo se llega por `repo.backend.write_client()`). Sin dependencia de PyGithub — cliente propio fino sobre `requests` para controlar exactamente permisos, headers, rate limits y errores. Todos los modelos usan el cliente, nunca `requests` directo.
- La separación lectura/escritura en dos archivos **es la garantía de F1**, no una preferencia de organización: hay un test que parsea `github_client.py` y exige que contenga exactamente una escritura HTTP. Agregar un verbo ahí obliga a aflojar el test, y un test aflojado deja de probar lo que probaba.
- Manejo de rate limit: leer headers `x-ratelimit-*`; si quedan <100 requests, los jobs de sync se re-encolan con eta diferida.
- Paginación siempre manejada (Link header).

## Qué NO hacer

- No implementar nada de deploy, servidores ni AWS: eso es PCM. Si una tarea parece necesitarlo, frenar y preguntar.
- No crear repositorios, ramas, merges ni ninguna escritura en la org real de Primate durante desarrollo: todo contra la org/repo sandbox de pruebas definida en la config de dev (`repo.backend` de test apunta a una org sandbox).
- No usar PATs en ningún flujo, ni siquiera para tests manuales.
- No tocar la rama espejo de forks por ningún camino que no sea el job de sync ff-only.
