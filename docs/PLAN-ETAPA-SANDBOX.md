# Plan de la etapa «producto completo sobre sandbox»

> Estado: abierto · Iniciado 2-sep-2026 · Todo el trabajo va contra `prm-sandbox`.

## El marco

Producción no se toca hasta que el producto esté terminado. Desarrollo, pruebas, ajustes
y funcionalidad nueva pasan sobre la organización sandbox. Cuando el producto esté
completo, Daryl lo valida operándolo entero desde Odoo, y recién después se agrega la
organización real como conexión, se migran los repositorios (§10.1) y se aplican las
reglas.

**Estado de producción:** la conexión `GitHub — primateuy` quedó **sin credenciales de
escritura** el 2-sep-2026. La puerta se niega por la guarda estructural, no por una
casilla. La instalación de `prm-writer` queda dormida. La App de auditoría `4805796`
sigue leyendo lo real como referencia, con sus 6 permisos de lectura.

## El criterio de salida de la etapa

Daryl ejecuta el flujo completo en la aplicación **siguiendo únicamente la guía de
usuario**, sin necesitar nada que la guía no diga y sin tocar la shell:

    espejo → auditoría → hallazgos → informe → armar plan → aprobar → apply
           → bitácora → rollback

De ahí sale la regla que ordena todo este plan: **si algo sólo se puede hacer por shell,
es funcionalidad faltante.** No va a la guía; va acá.

---

## Lo que ya está construido

| Pieza | Estado |
|---|---|
| Conexión, credenciales cifradas, prueba de conexión | completa y operable por interfaz |
| Espejo (repos, ramas, colaboradores, PRs, commits, workflows) | completo; **sin formulario** para abrir un repositorio |
| Motor de hallazgos y clasificación | completo; **sin vista** de hallazgos |
| Informe PDF | completo |
| Plan de escritura, huella, aprobación, apply, rollback | completo; **el payload se escribe a mano** |
| Bitácora inmutable | completa y navegable |
| 5 tipos de operación con su reversión | completos, probados contra el sandbox |

---

## Bloque A — Hacer operable lo que ya funciona

Es lo que separa «el módulo hace esto» de «se puede hacer esto desde la aplicación». Va
primero porque sin esto la guía no puede existir, y porque cada ítem se descubrió mirando
las vistas declaradas contra el flujo del criterio de salida.

**A1 · La auditoría se lanza y termina desde la interfaz.**
`action_start` encola con `queue_job`, y el runner no está configurado: hoy el botón
«Auditar» deja la corrida en «en curso» para siempre. Hay que decidir entre configurar el
runner o dar un camino sincrónico para organizaciones chicas — con 6 repositorios el
sincrónico alcanza y no agrega infraestructura que el usuario tenga que entender.
*Sin esto, el primer paso del criterio de salida no se puede dar.*

**A2 · Vista de hallazgos.** *(hecho)* Lista, formulario, buscador y menú. Agrupable por
severidad, tipo, repositorio y **causa de ilegibilidad** —que separa un techo de plan, que
se resuelve con una decisión de plan, de una App sin permisos, que se resuelve
reinstalándola—. Botón inteligente desde la corrida, siempre visible y no sólo al terminar.

*Hallazgo de la implementación:* agrupada por severidad, la lista mostraba «Crítico, Alto,
**Informativo, Medio**». Odoo ordena los grupos de un campo de selección por el valor
guardado, alfabéticamente, y no por el orden en que la selección está declarada. En una
lista cuyo único propósito es triaje, eso no es estético. Resuelto con `severity_rank`, un
campo espejo cuyos valores ordenan como la gravedad. Lo destapó una captura para la guía.

*Doctrina fijada:* **ninguna acción de escritura fuera del embudo.** La remediación de cada
hallazgo se muestra como dato —incluido el marcado de destructiva— y se ejecuta en A4, por
plan → aprobación → apply. Un botón «remediar» en una lista saltearía las tres guardas.

**A3 · Formulario de repositorio.** *(hecho)* Formulario con ramas, colaboradores
—con el ORIGEN del permiso, que es lo que decide si revertir un grant deja a alguien sin
acceso o con el del equipo—, hallazgos, PRs, commits y workflows; buscador con los filtros
del trabajo real; clasificación editable de a uno y **por lote** desde la lista.

*El hallazgo del paso, y era caro:* `action_set_classification_manual` existía y hacía lo
correcto, pero **nadie lo llamaba desde un formulario**. Editar la clasificación y guardar
dejaba el origen en «heurística», y la corrida siguiente la pisaba en silencio — justo lo
que el `help` del campo promete que no pasa. Con 43 repositorios para clasificar a mano, se
habría descubierto con los 43 ya perdidos. Resuelto en `write`: editar el campo ES el acto
manual, y el default es «lo hizo una persona» — la heurística tiene que decir
explícitamente que no fue ella. El olvido de un desarrollador futuro se paga con una
clasificación respetada de más: molesto, visible y reversible, en vez de callado y caro.

Verificado por mutación en las dos direcciones: sin el marcado, la auditoría pisa la
decisión y el test se pone rojo; sin la bandera de la heurística, la clasificación
automática se congela en la primera corrida y también se pone rojo.

También se agregó `finding_ids` al repositorio: el vínculo existía en un solo sentido.

**A4 · Armar un plan sin escribir JSON.** Hoy el payload de cada operación se escribe a
mano. Eso es interfaz de desarrollador.

- **A4.4 · Que el plan se lea antes de aprobarlo.** *(hecho, y va primero a propósito: sin
  poder leer un plan, los demás pasos producen planes que nadie puede revisar.)* Cada
  operación se dice en castellano —«en primateuy/x, la rama 17.0 pasa a exigir 2
  aprobaciones y a bloquear force-push»— y esa frase **entra en la huella**. La aprobación
  exige **una confirmación por cada operación destructiva**, con su descripción delante:
  «nunca en lote» de la spec de F2 es sobre la decisión, no sobre el armado, y una lista
  que enumera y termina en un botón se saltea leyendo en diagonal. La guarda vive en el
  modelo, no en el asistente, porque una pantalla se saltea llamando al método.
- **A4.1 · «Remediar esto» desde un hallazgo** *(hecho)*, con el payload derivado. Acumula
  en el borrador abierto de esa conexión. **El botón arma y termina: no escribe nada.**
  Si el hallazgo ya está planificado, no crea una segunda operación — dice en qué plan
  está y lleva ahí. Esa no-duplicación tiene dos capas: la comprobación en Python, que da
  el mensaje, y un **índice único parcial** sobre las operaciones vivas, que cierra la
  ventana entre comprobar y crear. Verificado: sacando la comprobación, la base rechaza
  igual.

  *Hallazgo del paso:* de las 16 acciones de remediación del catálogo, **sólo 2 son
  escrituras a GitHub** que el módulo sepa armar (`revoke_permission` y `apply_ruleset`).
  Las otras 14 se resuelven en Odoo, en la cuenta de una persona, en la consola de GitHub
  o en una fase que todavía no existe. Cada una tiene escrito dónde se resuelve, y la
  pantalla lo muestra: un botón ausente sin explicación se lee como un olvido del
  producto. Hay un test que falla si alguien agrega una acción sin decidir de qué lado cae.
- **A4.2 · Remediar varios de una vez** *(hecho, salió con A4.1)* desde la lista de
  hallazgos. Los que ya están planificados y los que no se planifican se saltean y se
  cuentan, en vez de cortar el lote: negarse entero porque uno de veinte no aplicaba
  obliga a ir de a uno, que es lo que este botón viene a evitar.
- **A4.3 · Asistente por tipo de operación**, para lo que no nace de un hallazgo.
- **A4.5 · El apply y el rollback con estado vivo**, reusando el componente de A9 y su
  patrón: derivar del espejo, no de parámetros.

*Consecuencia aceptada de que la frase entre en la huella:* actualizar el módulo puede
invalidar aprobaciones pendientes, porque la frase que se aprobó ya no es la que se
mostraría. Es el precio de que la aprobación signifique algo.

**A5 · Vistas de política.** *(hecho)* Plantillas con sus reglas por rol de rama, checks y
excepciones; reglas de clasificación y de rol de rama, ordenables. Cada plantilla dice a
cuántos repositorios gobierna y lleva a ellos.

*La pieza de fondo:* **todo cambio de política va a la bitácora inmutable** —campo, valor
anterior, valor nuevo, quién y cuándo—, no sólo al chatter. Cambiar la política es la
escritura más silenciosa del módulo: no toca un repositorio y redefine qué cuenta como
incumplimiento para todos. Se registra TODO campo que cambie, sin lista blanca: una lista
de «campos importantes» es una lista que alguien va a olvidar de actualizar el día que
agregue el que importaba. **B4 va a leer de este registro** — es la única fuente que dice
cuándo cambió la política y qué cambió. Verificado por mutación: sin la entrada, rojo.

**A6 · Personas y empleados.** *(hecho)* Lista, formulario con sus accesos —lo que hay que
mirar antes de un offboarding— y buscador. El hallazgo «cuenta sin persona asociada» se
resuelve con un asistente que **propone candidatos y nunca vincula solo**: las
coincidencias por mail y por nombre son pistas, no pruebas, y un vínculo equivocado pone
los permisos de una persona a nombre de otra.

**A7 · Flag explícito «escritura habilitada en producción».** *(hecho)*
Durante toda la F2, `write_client()` rechazaba cualquier escritura desde una conexión de
entorno *Producción*, sin excepción. Esa compuerta **se quitó** al pasar a la arquitectura
de dos Apps (commit `1f64af2`): la única condición pasó a ser tener credenciales cargadas,
y el primer apply real salió sin ninguna confirmación adicional.

Ahora sobre producción hace falta además `write_enabled`, que **no se edita como un
campo**: el `write` del modelo rechaza tocarlo fuera de los métodos sancionados, porque un
flag que se pueda poner en true sin dejar rastro no protege de nada. Se activa desde un
asistente que muestra, antes de decidir, **qué repositorios abarca la instalación según
GitHub** —preguntado, no supuesto— y pide escribir el nombre de la cuenta. Habilitar y
deshabilitar dejan entrada en la bitácora; la de habilitación guarda el alcance vigente en
ese momento, que es la pregunta que se hace después de un incidente.

*Hallazgo de la implementación:* un test viejo en rojo destapó que las guardas estaban en
el orden equivocado. Decirle «habilitá la escritura» a alguien que no tiene App de
escritura lo manda a resolver el problema equivocado; la guarda estructural va primero.

El refactor dejó **una sola** construcción de `GithubWriteClient` en todo el módulo
—`_construir_cliente_de_escritura`— con la puerta y sus guardas aparte, así que el test que
vigila «una sola puerta» sigue valiendo sin aflojarse.

**A8 · Pantalla de configuración.** *(hecho)* Los cuatro parámetros con su explicación, y
un bloque de diagnóstico de sólo lectura que responde con evidencia —hay tareas esperando
hace rato, o no— en vez de con configuración. Es la respuesta a «¿por qué mi auditoría se
quedó En curso?», que antes obligaba a entrar al servidor.

*Hallazgo de la implementación:* se hizo primero como `res.config.settings`, que era lo
obvio, y la pantalla tiraba **Access Error** para cualquiera que no fuera administrador de
Odoo: ese modelo exige `base.group_system`, que da la administración entera de la
instancia. Darle ese grupo a quien administra Repo Manager para que pueda mover un umbral
sería cambiar un problema chico por uno grande. Rehecho como modelo propio, `repo.settings`,
con el `sudo()` del guardado acotado a cuatro claves fijas en el código. Lo destapó una
captura para la guía; desde el código la vista cargaba bien.

**A9 · Componente de estado vivo.** Requisito de producto: lo que está en pantalla y
cambia, tiene que actualizarse solo. Nada de refrescar para ver avanzar una auditoría.

Un componente OWL propio, reutilizable, que se embebe donde hay estado cambiante —la
corrida de auditoría primero, después el plan aplicándose y el sync— se suscribe al bus de
Odoo y pinta el avance sin recargar la pantalla.

*Corte adoptado:* **lo vivo es propio, los datos son estándar.** Los hallazgos se
benefician de la búsqueda y el agrupado que Odoo da gratis; el progreso no se puede
resolver con vistas estándar. Si más adelante se decide una interfaz completa, este
componente se reutiliza adentro.

*Consecuencia técnica aceptada:* las notificaciones del bus se entregan al confirmar la
transacción, así que **el camino sincrónico es estructuralmente incapaz de mostrar
avance** —corre entero en una transacción—. Por eso el encolado pasa a ser el default, con
umbral 0 cuando hay procesador configurado, y el inmediato queda como respaldo
documentado.

La misma regla muerde adentro del camino encolado: un job confirma recién cuando termina
el repositorio, así que el aviso «arranqué con X» emitido por el camino normal llegaría
junto con el «terminé con X» y la pantalla diría «Ahora: X» con X ya hecho. Por eso el
aviso de apertura sale por una conexión propia que confirma en el acto (`inmediato=True`).
Es deliberado que esos avisos no sean transaccionales: son señales de vida, no datos.

*Estado:* **A9 completo (A9.1, A9.2 y A9.3).** Queda reutilizar el componente en el plan
aplicándose y en el sync, que es trabajo de esos bloques y no de éste.

*El tour SÍ corre en el entorno* —Chromium y `websocket-client` están instalados— así que
A9.3 quedó como dos `HttpCase` de verdad y no como verificación visual delegada. El tour
maneja el reloj: escribe los contadores y pide `action_refresh_progress` en vez de esperar
a que el servidor emita solo. Los estados intermedios son transitorios —la barra en ámbar
CON la corrida en marcha dura lo que dure el repositorio siguiente— y un test que depende
de ganar esa carrera falla por motivos que no son el código.

El segundo tour, el de la corrida creada con «Nuevo», **encontró un defecto que seguía
vivo después del arreglo de A9.2**: la suscripción se rehacía con `onWillUpdateProps`, y
ese hook puede no dispararse nunca porque Odoo le pone el id encima al MISMO objeto en vez
de entregar otro. Corregido con `useEffect` sobre el valor de `resId`. Es el error original
—reaccionar al montaje en vez de al dato— corrido un paso más adelante, y sólo se ve
abriendo la pantalla.

*Aviso operativo:* después de correr tours, `--stop-after-init` puede tardar en cerrar el
proceso (queda un hilo del websocket). El resultado de los tests ya está impreso; no es un
cuelgue de la suite.

**A11 · `action_refresh_progress`, y lo que abre.** Nació para el tour pero es producto: el
bloque de «sin novedades» ahora ofrece «Volver a preguntar», que reemite el estado por el
mismo canal sin recargar nada. El repositorio que se está recorriendo se deriva del espejo
—el que está en «en curso»— y no de un parámetro, así que el método puede decir la verdad
sin que nadie se la cuente. Sirve como base para el mismo botón en el plan aplicándose.

**A10 · Los contadores de la corrida no pueden ser una fila compartida.**
Lo destapó la primera corrida encolada mirada de cerca. Con dos hilos en
`root.repo_manager`, cada job actualiza `repos_done`/`repos_error` de la MISMA fila de
`repo.audit.run` al terminar. La transacción del job dura todo el recorrido del
repositorio —unos 8 segundos—, así que cualquier otro job que confirme en esa ventana lo
mata con «could not serialize access». `queue_job` reintenta y el resultado final es
correcto, pero **cada repositorio se recorre 2 o 3 veces**: el triple de llamadas a la API
de GitHub, el triple de tiempo y el triple de cuota. Medido: 7 repositorios, 19 ejecuciones.

Mitigación aplicada el 3-sep-2026: `channels = root:2,root.repo_manager:1`. Sin
concurrencia no hay colisión — 7 repositorios, 7 ejecuciones, 71 segundos— pero también
sin paralelismo, y con 113 repositorios eso se nota.

El arreglo de fondo tiene dos formas, y la elección no es obvia:
- *Contadores calculados*: los jobs sólo escriben el estado de SU repositorio —fila propia,
  sin contención— y la corrida cuenta. Hay que congelar los números al cerrar, porque un
  conteo vivo sobre el espejo haría cambiar las cifras de corridas viejas.
- *Contador en micro-transacción*: `UPDATE ... SET repos_done = repos_done + 1 RETURNING`
  en una conexión propia que abre y cierra en microsegundos. Más chico, pero rompe la
  atomicidad que hoy existe entre «el repositorio quedó guardado» y «se contó».

---

## Bloque B — F3, política

**B1 · Aplicación de rulesets por plantilla**, no operación por operación: «aplicar la
política de esta plantilla a este repositorio» como una acción.

**Requisito que viene de D2 y no se puede olvidar:** los rulesets que el propio módulo
aplique tienen que incluir a **`prm-writer` como bypass actor**. El embudo
plan → aprobación con confirmación individual → bitácora encadenada → reversión es una
revisión **más estricta** que una pull request, no menos. Sin esa exención, la gobernanza
que B viene a instalar estrangularía a D2: el módulo se prohibiría a sí mismo hacer lo que
el mismo módulo aprobó, y la promoción de un módulo a un repositorio bien gobernado sería
imposible justamente por estar bien gobernado.

Mientras B no exista, D2 se protege por el otro lado: al armar el plan se lee la protección
de la rama de destino y, si exige PR, **el plan se niega a armarse con el motivo** — nunca
falla a mitad del apply. Abrir pull requests desde el módulo es F4, no un atajo para acá.

**B2 · CODEOWNERS generado** desde la política, con su operación de escritura y su
reversión. Requiere permiso `contents`.

**B3 · Checks requeridos.** Hoy el hallazgo `checks_not_evaluable` dice que ninguna
plantilla los define. Hay que poder definirlos, y proponerlos a partir de los workflows
que la auditoría ya releva.

**B4 · Drift de política en los dos sentidos**: detectar que un repositorio se apartó de
su plantilla, y detectar que la plantilla cambió y hay repositorios sin actualizar.

**B5 · Wizard «Crear repositorio»**, con clasificación, plantilla, estructura de ramas y
gobernanza aplicada al nacer. Es el cierre de F3 según la spec.

---

## Bloque C — F5, forks

**C1 · Roles de rama `mirror` y `patch`.** No existen reglas que los asignen: hoy ninguna
rama puede salir con esos roles, así que la evaluación que los usa nunca se dispara.

**C2 · Medición del atraso contra el upstream.** Los campos `behind_upstream` y
`ahead_upstream` existen y nadie los llena. La captura del upstream **ya está resuelta**
(2-sep-2026, `_completar_desde_el_detalle`), que era la mitad del problema; falta la
comparación.

**C3 · Modelo `repo.patch`** y el reporte de parches vivos.

**C4 · Job de sync ff-only** del espejo, con manejo de conflicto que genere actividad y no
fuerce nada.

---

## Bloque D — Guía de usuario

Crece con el producto: cada funcionalidad que se completa se opera por la interfaz contra
el sandbox y en ese momento se escribe su sección. Documento único versionado:
`docs/GUIA-DE-USUARIO.md`.

Lenguaje de usuario: qué hago, qué veo, qué significa. No de desarrollador.

---

## Orden propuesto

1. **A1** — sin la auditoría lanzable desde la interfaz no hay flujo que documentar. *(hecho)*
2. **A9** — el componente de estado vivo, primero: define el lenguaje visual con el que nacen las dos pantallas siguientes. *(hecho)*
3. **A2 + A3** — hallazgos y repositorio: cierran el tramo de lectura, que es la mitad del criterio de salida.
4. **A5 + A6 + A8** — política, personas y configuración visibles.
5. **A7** — el flag de producción, antes de que producción vuelva a tener credenciales.
6. **A4** — armar planes sin JSON; cierra el tramo de escritura.
7. **B** — F3.
8. **C** — F5.

Con A completo, el criterio de salida ya es alcanzable para el flujo de auditoría y
escritura que existe hoy. B y C agregan funcionalidad; A la hace usable.

---

## Bloque D — Ciclo de vida de módulos entre repositorios

Requisito de producto agregado el 3-sep-2026. El caso real: un módulo nace en el repo de
un cliente, se copia a otros porque sirve, y cuando mantenerlo en cuatro lugares se vuelve
tedioso se **promueve** al repo general que se decida —`general_primate` o
`LocalizacionUy`— y se saca de los particulares. También la dirección general →
localización.

### Una aclaración de vocabulario, antes de que se mezclen

**«Promoción» ya significa otra cosa en este proyecto.** F4 tiene `repo.promotion`: mover
código **entre ramas** de un mismo repositorio (staging → support), con merge por API y
pre-validaciones. Lo de este bloque es entre **repositorios** y su objeto es un módulo, no
una rama. Son cosas distintas y el modelo se llama distinto: **`repo.module.promotion`**, decidido
el 4-sep-2026. `repo.promotion` queda reservado para F4, entre ramas.

### D1 · Inventario de módulos *(sólo lectura)*

Hoy el espejo sabe de repos, ramas, colaboradores, PRs, commits y workflows. **No sabe qué
módulos Odoo viven en cada repositorio**, que es el dato sobre el que se apoya todo lo
demás.

**D1.1 · Escanear manifests.** Modelo `repo.module` (nombre técnico, repositorio, rama,
ruta, versión, `depends`, autor, licencia) y `repo.module.copy` para cada aparición.

*El camino barato:* `GET /repos/{o}/{r}/git/trees/{sha}?recursive=1` devuelve el árbol
entero en **una llamada por rama**, y de ahí salen todos los `__manifest__.py` por su ruta.
Recién después se baja el contenido de cada manifest. No hay que caminar directorios.

*El techo:* la respuesta viene con `truncated: true` en repos muy grandes —el fork de
`enterprise` seguro—. Se trata como todo lo que no se pudo leer en este módulo: se marca
como no legible con su causa, **nunca se reporta como «no tiene módulos»**.

*Costo:* ~113 repos × 3-4 ramas relevantes ≈ **400 llamadas de árbol**, más una por
manifest encontrado. Entra en la cuota de una App (5.000/hora) con holgura, pero no entra
en el tiempo de una pantalla: va como job del canal propio, igual que la auditoría.

**D1.2 · Detectar el mismo módulo en varios repositorios.** Agrupar por nombre técnico.
Sale gratis una vez que existe D1.1.

**D1.3 · Detectar si las copias divergieron.** *Y acá está el hallazgo de diseño de este
bloque:* **no hace falta bajar ni comparar contenido.** El árbol recursivo trae, para cada
subdirectorio, una entrada `tree` con su propio SHA, que es un hash de contenido de todo
el subárbol. **Dos copias con el mismo SHA de directorio son idénticas byte a byte; dos
SHAs distintos son divergencia.** Una comparación por copia, cero llamadas extra.

Lo que ese hash NO dice es *en qué* difieren ni *cuál va adelante*. Para eso hace falta
bajar los dos y diferenciarlos, y sólo se hace bajo pedido, sobre las que ya se sabe que
divergen. La pregunta «¿hay divergencia?» es barata; «¿cuál gana?» es cara y es humana.

**D1.4 · La pantalla.** Un módulo con sus copias, cuáles coinciden y cuáles no, y desde
dónde se promovería. Es lo que convierte el inventario en una decisión.

*Dimensión de D1:* comparable a A2+A3 juntos — un modelo nuevo con su sync, un job, dos
pantallas. **Sin permisos nuevos:** la App de auditoría ya tiene `contents:read`,
verificado contra GitHub el 3-sep-2026. Es el bloque de lectura más grande que queda.

### Tramo visual · antes de seguir con D2

Decidido el 5-sep-2026: cuatro pantallas migradas al entregable de diseño —bitácora, plan
de escritura, hallazgos y el panel de salud en versión 1, adelanto acotado de E4— antes de
D2.3. Dimensionado completo en `TRAMO-VISUAL.md`; las tres reglas de proceso que salieron
con él —el mockup manda, lo no implementado se muestra apagado, y cada pantalla nace
visual y funcional a la vez— están en `CLAUDE.md` y valen para B, C, D y E.

### D2 · La promoción *(escritura)*

*Hallazgo del motor, encontrado al construir D2.0 y ya corregido:* el bucle del apply **no
se detenía ante un fallo**. En F2 eso era correcto —proteger una rama y bajar un permiso
son independientes, y que una falle no debe frenar la otra— pero la promoción rompe ese
supuesto: «copiar» y «borrar» son la misma operación partida en dos. Ahora una operación
puede declarar de cuáles depende, y si alguna no quedó aplicada, la que sigue queda en
**«no ejecutada por dependencia»** — un estado propio, distinto de «fallida», porque no se
intentó: marcarla como fallida mandaría a alguien a buscar un error de GitHub que no
existe.

**D2.0 · La barrera.** *(hecho)* Una operación declara de cuáles depende; si alguna no
quedó aplicada, la que sigue no se intenta y queda en **«no ejecutada por dependencia»**.
Sin esto nada de lo demás es seguro.

**D2.1 · Copiar al destino.** *(hecho, sin ejecutar contra GitHub)* **Un solo commit** por
la API de datos de git: leer el árbol del origen, subir los blobs al destino, construir el
árbol, crear el commit y mover la referencia **sin `force`**. La API de contenidos habría
sido un commit por archivo, y una interrupción dejaría un módulo a la mitad.

**D2.2 · Verificar por relectura.** *(hecho)* Se compara el **SHA del subárbol**: git
nombra los árboles por su contenido, así que dos directorios idénticos tienen el mismo hash
en cualquier repositorio. No hay que bajar nada ni confiar en que la API hizo lo que dijo.

**El ensayo se corrió el 5-sep-2026**, en siete fases y contra el sandbox: sembrar en dos
repos, leer el plan antes de aplicar, copiar y verificar, **matar el proceso entre la copia
y el primer borrado**, completar, revertir, y el caso feo —alguien empuja al módulo después
de aprobado el plan—. Está entero en `ENSAYO-D2.md`, con sus dos hallazgos: una escritura
huérfana de una caída se cuela en el punto de retorno, y la pantalla del plan no cuenta que
hubo una caída. Los dos abren el próximo tramo.

**D2.3 · Limpiar los orígenes.** *(hecho)* Son **commits de borrado en repositorios de clientes**, y
entran por el embudo como toda escritura: plan → aprobación → apply → bitácora → rollback.
No hay excepción; si algo la merecía menos, es justamente esto.

**D2.3b · El plan de promoción como una sola unidad.** Una promoción es una escritura al
destino y N borrados en orígenes. Media promoción aplicada —copiado al general, borrado de
dos de cuatro clientes— es un estado peor que no haber empezado. Hay que decidir si el
plan se aplica todo-o-nada o si el rollback alcanza; ver «decisiones abiertas».

**D2.4 · Con copias divergentes, primero se decide.** Si D1.3 dice que las copias no son
idénticas, la promoción **no puede armarse sola**: alguien tiene que elegir qué versión
gana y qué se hace con lo que se pierde. La pantalla tiene que forzar esa elección, no
resolverla por antigüedad ni por tamaño.

*Dimensión de D2:* comparable a A4 — reusa todo el motor de escritura de F2, que ya está
probado; lo nuevo es el tipo de operación y su reversión.

*Dependencia dura:* hoy **producción no tiene App de escritura**. D2 sobre repos reales
exige crear e instalar una segunda App con `contents:write` sobre los repos de la tanda, y
después habilitar la escritura por A7. En el sandbox ya se puede: `prm-sandbox` tiene
`contents:write`.

### D3 · El borde con el despliegue — lo que Repo Manager NO hace

Sacar un módulo del repo de un cliente significa que su instancia tiene que empezar a
tomarlo de otro lado. **Eso es `addons_path`, y Repo Manager no lo toca.** Cambiar dónde
busca módulos una instancia es despliegue: es PCM, o es una intervención en el servidor.

Decirlo no alcanza con ponerlo en un comentario. Lo que sí puede hacer Repo Manager, y
tiene que hacer, es **no dejar que la omisión sea silenciosa**:

- La promoción **avisa, en la pantalla de aprobación**, que el módulo va a dejar de estar
  en esos repositorios y que las instancias que los usan necesitan un cambio de
  `addons_path` que este módulo no hace.
- Si el bridge de PCM está instalado (F6), puede además **nombrar qué instancias** quedan
  afectadas. Sin el bridge, avisa igual pero en general.

Un módulo que borra código de un repo de cliente y no dice que algo más tiene que cambiar
es un módulo que rompe producciones ajenas en silencio.

### Dónde encaja D en el orden

**D1 va temprano, y en paralelo conceptual con B — no después.** Tres razones:

1. **Es sólo lectura y no depende de nada de B ni de C.** Escanea árboles y manifests; no
   toca política ni forks.
2. **Responde una pregunta que hoy no tiene respuesta y que no depende de que se decida
   nada.** Cuántos módulos duplicados hay, y cuántos divergieron, es un dato que cambia la
   conversación sobre qué promover — y conviene tenerlo antes de discutirlo, no después.
3. **B4 —el drift de política— y D1 leen cosas distintas del mismo árbol.** Hacer D1 antes
   deja el escaneo del árbol ya resuelto para cuando B4 lo necesite.

**D2 va después de A4**, y no por capricho: A4 es lo que hace que un plan se pueda armar y
leer sin escribir JSON. D2 es un tipo de operación más dentro de ese plan; construirlo
antes obligaría a armar promociones a mano en JSON, que es exactamente lo que A4 viene a
eliminar.

*Orden recomendado:* `A4 → D1 → B → D2 → C`.

### Decisiones abiertas de D

1. **¿La promoción es todo-o-nada?** Un plan que copia al general y borra en cuatro
   clientes puede fallar en el tercero. El motor de F2 ya sabe revertir operación por
   operación, pero «revertir un borrado» significa volver a commitear archivos, que no es
   lo mismo que restaurar un permiso.
2. **¿Qué rama del destino?** Un módulo vive en `17.0` en un cliente y el general tiene
   `17.0` y `19.0`. Hay que decidir si la promoción es por rama, o si es una matriz.
3. **¿Se deja rastro en el origen?** Borrar el módulo y ya, o dejar una nota —un README, o
   una entrada en el propio repo— que diga dónde vive ahora. Lo segundo es lo que evita
   que alguien lo vuelva a crear en seis meses.


---

## Bloque E — Lo que entró en la pausa de producto (4-sep-2026)

### E1 · Seguridad: Dependabot y secret scanning como hallazgos

**Permisos nuevos, y no son gratis.** Verificado contra la API: hoy la App de auditoría
tiene `actions`, `administration`, `contents`, `metadata`, `pull_requests` y `statuses`,
todos de lectura. Faltan **dos permisos nuevos** en la App de auditoría:

| Qué | Permiso | Endpoint |
|---|---|---|
| Alertas de Dependabot | `vulnerability_alerts: read` | `GET /repos/{o}/{r}/dependabot/alerts` |
| Secret scanning | `secret_scanning_alerts: read` | `GET /repos/{o}/{r}/secret-scanning/alerts` |

Dos avisos que hay que dar antes de prometer nada:

1. **Secret scanning en repos privados es una función paga** (Advanced Security). En los
   públicos anda con el plan gratuito. Con 31 repos privados en la cuenta real, el
   resultado esperable es un `403` de techo de plan sobre la mayoría — que el módulo ya
   sabe reportar como *no legible por límite de plan*, no como «no hay secretos». Esa
   distinción, que costó construir en F1, es exactamente lo que hace que este ítem se
   pueda entregar sin mentir.
2. **Ampliar los permisos de la App 4805796 requiere re-consentir la instalación.** Es la
   misma operación que rompió el OAuth de Outlook al migrar: se toca y hay que aceptar de
   nuevo.

*Dónde encaja:* **en B, junto a los checks requeridos (B3)**, y por una razón de fondo: es
la misma conversación. B3 pregunta «¿qué tiene que pasar antes de mergear?» y E1 pregunta
«¿qué encontró GitHub por su cuenta?». Las dos alimentan la misma decisión sobre un
repositorio y comparten la pantalla de política.

*Definición funcional (4-sep-2026):*
- **Secret scanning → crítico SIEMPRE.** Un secreto en el historial no prescribe: rotarlo
  es urgente aunque la alerta sea vieja, porque el historial sigue ahí.
- **Dependabot → severidad mapeada de GitHub:** `critical`→crítico, `high`→alto,
  `moderate`→medio, `low`→informativo. GitHub ya hizo ese trabajo y rehacerlo sería
  inventar un criterio propio peor informado.
- **Sin remediación por plan, y el hallazgo lo dice:** un secreto se rota, no se aplica.
  Una alerta de Dependabot se resuelve con un PR. Van al catálogo de A4.1 como *se
  resuelve en otro lado*, con esa frase.
- El techo de plan en los 31 privados se reporta como *no legible por plan*, como siempre.
  Anotado además en la spec (§10.1.4) como argumento de migración.

*El paso exacto del re-consentimiento*, para cuando B llegue:
1. GitHub → *Settings* de la cuenta → *Developer settings* → *GitHub Apps* → **App 4805796**.
2. *Permissions & events* → *Repository permissions*: poner **Dependabot alerts: Read-only**
   y **Secret scanning alerts: Read-only**. Guardar.
3. GitHub manda la solicitud a la instalación. Ir a *Settings* → *Applications* →
   *Installed GitHub Apps* → la App → **Review request** → *Accept new permissions*.
4. Avisar. El módulo lo verifica solo: la respuesta del token de instalación trae los
   permisos concedidos, y sin los dos nuevos los hallazgos se reportan como no legibles en
   vez de fallar.

*Dimensión:* chica-media. Dos tipos de hallazgo nuevos, dos llamadas en el sync, su
severidad y su lugar en el informe.

### E2 · Auditoría programada, y el delta contra la corrida anterior

**E2.1 · Cron configurable.** Un `ir.cron` que lanza la auditoría, con su frecuencia
editable desde la pantalla de Ajustes (A8) y no desde *Técnico*.

**E2.2 · El delta.** Lo que importa de la corrida N no es la lista completa: es **qué
apareció y qué se resolvió** contra la N-1. Comparar por `(tipo, repositorio, sujeto)` —no
por id, que cambia en cada corrida— y clasificar cada hallazgo en *nuevo*, *sigue*,
*resuelto*.

*Esto vale por sí solo, aunque no haya notificación*: es lo que convierte 273 hallazgos en
«tres cosas nuevas esta semana». Y es la mitad de **B4**, el drift de política, que
pregunta lo mismo sobre otra dimensión.

**E2.3 · La notificación.** *Definido:* **Discuss + mail**, destinatarios configurables,
por ahora sólo Daryl. El delta lleva **nuevos y resueltos**: los resueltos son la evidencia
de progreso y son la mitad que un informe de incumplimientos nunca muestra.

*Definido para E2.1:* **cron semanal, lunes por la mañana**, frecuencia editable desde
Ajustes.

*Dónde encaja:* **E2.1 y E2.2 después de B4**, para no construir dos veces la comparación
entre corridas. E2.3 con ellas.

*Dimensión:* E2.2 es media —un modelo de comparación y su pantalla—; E2.1 y E2.3 son
chicas.

### E3 · Higiene: ramas muertas y repos candidatos a archivar

**E3.1 · Hallazgos de higiene (lectura).** *Redefinido el 4-sep-2026, y el cambio es de
fondo: la higiene se ata al CICLO DE VIDA, no a las fechas.* El flujo real es
`prod (ej. 17.0) → staging → support → producción`, y los **roles de rama que ya existen**
definen cuál es prod en cada repositorio.

| Situación | Hallazgo | Qué se puede hacer |
|---|---|---|
| Rama **integrada a prod**: 0 commits propios pendientes, verificado contra la rama de producción | *Candidata a borrar*, severidad informativa | Borrado por el embudo, como **destructiva** |
| Rama con **commits que nunca llegaron** y sin actividad hace 6 meses | *Abandonada* | **Sólo se lista. Jamás se propone borrar** |
| Repositorio **sin push hace 18 meses** (configurable) | *Candidato a archivar* | Archivar por el embudo, con el aviso de despliegue estilo D3 |

La distinción entre las dos primeras es la que importa y es la que una regla por fecha no
puede hacer: **una rama vieja e integrada es basura; una rama vieja con trabajo que nunca
se mergeó puede ser trabajo por rescatar.** Proponer borrar la segunda sería ofrecer perder
algo, y por eso el producto no lo ofrece — ni siquiera detrás de una confirmación.

*Verificar «0 commits propios pendientes» no es mirar fechas*: es comparar contra la rama
de producción del repositorio. Ese dato hay que traerlo; es la única parte de E3.1 que
agrega sync y no sólo evaluación. `last_commit_date` y `pushed_at` ya están desde F1.

**E3.2 · Archivar por el embudo.** Un tipo de operación nuevo, `repository_archive`, con su
reversión (desarchivar). Es de las pocas operaciones **reversibles de verdad y sin pérdida**
—GitHub archiva y desarchiva sin tocar contenido—, lo que la hace un buen primer caso para
una operación de nivel repositorio.

*Cuidado que hay que tener:* archivar un repositorio lo pone en sólo lectura para todos, y
si alguna instancia de cliente lo tiene en su `addons_path` como origen de un submódulo,
sigue funcionando para leer pero no para escribir. **Es el mismo borde que D3**, y merece el
mismo aviso en la aprobación.

*Dónde encaja:* **E3.1 puede ir con D1** —las dos son lectura y no dependen de nada—;
**E3.2 después de D2**, cuando las operaciones a nivel repositorio ya tengan un camino
hecho.

*Dimensión:* E3.1 chica (es evaluación sobre datos que ya están). E3.2 chica-media.

### E4 · Panel de salud

Dimensión funcional, que es lo que se pide acá; el diseño visual va por su carril.

*Definido:* **tres números arriba** —% de ramas de entorno protegidas, críticos+altos
abiertos con su tendencia, repositorios gobernados sobre el total— y todo lo demás debajo.
La prueba ácida que tiene que pasar: **sin jerga, cinco segundos, ¿mejoramos o
empeoramos?** El visual viene de la sesión de diseño que va aparte.

**Lo que el panel necesita del backend, y no existe todavía:**

1. **Métricas por corrida, guardadas.** % de ramas protegidas, adopción de convención de
   commits, conteo por severidad, repos sin clasificar. Hoy se pueden calcular al vuelo
   sobre la última corrida, pero **la tendencia exige tenerlas guardadas por corrida**:
   recalcular el pasado desde el espejo daría el estado de HOY, no el de entonces. Un
   modelo `repo.audit.metric` de una fila por corrida y métrica.
2. **La tendencia sale gratis una vez guardadas**, y sólo entonces.
3. **Nada de esto necesita pantalla nueva del lado del backend**: son campos y un modelo.

*Dónde encaja:* **las métricas, con E2.2** — el delta y la tendencia leen lo mismo y
conviene que se guarden una sola vez. **El panel, al final del bloque E**, cuando haya al
menos tres o cuatro corridas guardadas: un panel de tendencia con un punto es un número con
un gráfico alrededor.

*Dimensión:* métricas chica; panel medio, y depende del diseño visual que va aparte.

### Backlog post-criterio-de-salida

No entran en esta etapa y quedan anotados para no perderlos: **Sagui sobre el espejo**
(preguntarle en lenguaje natural al inventario), **validación de convención de commits
contra tareas reales** (que el `[TAG][nro]` apunte a una tarea que existe — necesita el
vínculo con proyectos de F4), y **releases / settings / secrets** como dimensiones nuevas
del espejo.

---

## La pregunta de los webhooks, contestada

*¿Qué costaría que B y D se construyan «webhook-ready», sin asumir que el espejo sólo
cambia por auditoría, aunque los webhooks lleguen en F4?*

**Casi nada, y buena parte ya está hecha sin habérselo propuesto.** Lo verifiqué en el
código antes de contestar:

- **El sync ya es por repositorio y es idempotente.** `_job_sync_repository` recorre UN
  repositorio y hace upsert por `github_id`, que es estable ante renombres. Un evento que
  diga «cambió el repo X» puede llamar a eso mismo. No hay nada que rehacer.
- **El apply ya lee el estado previo de GitHub EN EL MOMENTO de aplicar**, no del plan.
  Es el punto que más me preocupaba —un plan aprobado el martes y aplicado el jueves sobre
  un mundo que se movió— y resulta que la decisión correcta ya estaba tomada en F2.
- **El componente de pantalla ya es de empuje.** Se alimenta del bus; no le importa quién
  emita.

**Lo que sí hay que cuidar, y es barato hacerlo ahora:**

1. **No atar los hallazgos nuevos a `run_id` como única procedencia.** Hoy `run_id` es
   obligatorio en `repo.audit.finding`. Un hallazgo que nazca de un webhook no tiene
   corrida. Cambiar eso después de que B y D hayan creado sus tipos de hallazgo es una
   migración; preverlo ahora es una decisión de diseño de diez minutos. **Recomendación:**
   dejar el campo obligatorio hoy —cambiarlo sin necesidad es peor— pero **no escribir
   lógica nueva que asuma que todo hallazgo tiene corrida**. Lo que sí conviene revisar es
   el conteo «de la última corrida» de A3, que sí lo asume.
2. **Que todo lo que escriba en el espejo pase por los mismos métodos de upsert.** Si B o
   D leen de GitHub y escriben en el espejo por su cuenta, el día que llegue un webhook va
   a haber dos caminos que hacen lo mismo distinto. Regla: **un objeto del espejo, un
   método que lo actualiza.**
3. **`last_seen_at` y origen en las filas del espejo.** Saber *cuándo* se supo algo y *por
   dónde* entró. Sin eso, la pregunta «¿esto está desactualizado o es así?» no tiene
   respuesta, y con webhooks conviviendo con auditorías esa pregunta se vuelve diaria.
   Son dos campos y cuestan nada ahora.
4. **A10 se agrava.** El defecto de los contadores compartidos —dos jobs pisándose la fila
   de la corrida— hoy se mitiga con un solo hilo. Con webhooks escribiendo en paralelo, esa
   mitigación deja de alcanzar. **A10 pasa de «molesto» a bloqueante para F4**, y conviene
   resolverlo antes y no durante. El patrón ya está probado en A4.5: **derivar contando, no
   incrementando.**

**Costo de las cuatro:** los puntos 2 y 3 son disciplina y dos campos. El 1 es una decisión
escrita, no código. El 4 es trabajo real —A10— pero ya estaba pendiente y ahora tiene fecha
de vencimiento.

---

## Orden final (4-sep-2026)

    A10 ✓ → D1 (+E3.1) → B (+E1) → D2 → E3.2 → C → E2 → E4

Confirmado, **con un ajuste que no cambia el orden sino qué entra en B**: las **métricas**
de E4 —una fila por corrida y métrica— se empiezan a guardar **junto con B4**, aunque el
panel se construya al final.

El motivo es que la tendencia no se puede reconstruir hacia atrás: recalcular el pasado
desde el espejo daría el estado de HOY, no el de entonces. Si las métricas empiezan a
guardarse recién en E4, el panel abre con un punto — y un gráfico de tendencia con un solo
punto es un número con adornos. Guardarlas desde B4 cuesta un modelo chico y hace que para
cuando llegue E4 haya meses de historia.

Es la misma razón por la que E2.2 va con B4: las tres cosas —delta, métricas y drift— leen
lo mismo, y conviene recorrerlo una sola vez.


---

## El conflicto de fuentes, para decidir

El sistema de diseño pide **IBM Plex Sans para leer e IBM Plex Mono para todo identificador
de git**. Verificado contra Odoo 19 antes de tocar nada:

- Odoo define `$o-font-family-sans-serif: $o-system-fonts` y
  `$o-font-family-monospace: (SFMono-Regular, Menlo, Monaco, Consolas, …)` en
  `web/static/src/scss/primary_variables.scss`, como variables `!default`.
- Las fuentes que Odoo empaqueta son **lato**, **google** y **sign**. **IBM Plex no está.**

**El conflicto concreto:** cambiar la sans exige sobrescribir `$o-font-family-sans-serif`
en `web._assets_primary_variables`, y eso **cambia la tipografía de TODO el backend de
Odoo** —Ventas, Contabilidad, Ajustes—, no sólo de Repo Manager. Un módulo que le cambia
la fuente a la instancia entera es un módulo que se nota donde no debería.

Tres caminos, con su precio:

| | Qué pasa | Precio |
|---|---|---|
| **A. Global** | Plex Sans en todo Odoo | Un módulo de gobernanza cambia la cara de toda la instancia |
| **B. Sólo Repo Manager** | Plex Sans en nuestras pantallas | Conviven dos tipografías: la app en Plex, el cromo de Odoo —migas, botones, chatter— en la del sistema |
| **C. Sólo la mono** *(aplicado por ahora)* | Plex Mono en identificadores de git; la sans queda la del sistema | Es donde el diseño tiene su intención más fuerte —separar «lo que dice la app» de «lo que dice GitHub»— y donde Odoo no aporta nada que valga conservar. La sans del sistema es neutra y no pelea |

**Decidido el 5-sep-2026: C, y es definitiva.** La sans de Odoo se hereda; Plex Sans no se
impone. El porqué, en las palabras que lo cerraron: *Repo Manager vive adentro de Odoo y no
tiene que sentirse extranjero; la identidad está en los tokens, los patrones y la mono.*

**Hecho (5-sep-2026):** los `.woff2` de IBM Plex Mono viajan con el módulo, en
`static/src/fonts/`, con su licencia OFL al lado. Verificado en el navegador: sobre el
inventario de módulos, 80 celdas en mono y el peso 400 cargado desde el módulo.


---

## Hallazgo del entregable de diseño: la bitácora encadenada

Leyendo el documento apareció un requisito que **no estaba en la spec ni en ningún bloque**,
y que es de fondo:

> *«Cada entrada guarda el hash de la anterior. Si alguien tocara la base, la cadena se
> rompe y el diagnóstico lo avisa.»*

Hoy `repo.audit.log` es inmutable **a nivel modelo** —`write` y `unlink` levantan excepción
siempre, incluso con `sudo()`— y eso protege del código. **No protege de un `UPDATE`
directo en Postgres**, que es justamente contra lo que sirve una cadena de hashes: no lo
impide, pero lo hace **detectable**.

Va junto con el otro pedido de la pausa de producto —**export firmado de bitácora, CSV +
hash**— porque son la misma pieza: sin cadena, la firma del export sólo dice «esto es lo
que la base tenía hoy», no «esto es lo que pasó».

**Decidido e implementado el 5-sep-2026.** La cadena arranca ahora, sin sembrar sobre lo
viejo: una cadena que «verificara» un pasado que nadie encadenó estaría fabricando
confianza, que es lo contrario de su propósito. La entrada de génesis declara cuántas
entradas quedaron afuera. La verificación vive en el diagnóstico de Ajustes —«Íntegra desde
el …» / «ROTA en la entrada N»— y una cadena rota es hallazgo crítico del propio módulo.

*Consecuencia que quedó escrita en el código:* cambiar la lista de campos sellados
invalida todas las cadenas existentes. Si alguna vez hay que cambiarla, el camino honesto
es el mismo que se eligió para arrancar: una génesis nueva que declare desde cuándo vale el
sello nuevo. Recalcular los viejos en silencio sería, otra vez, fabricar confianza.


## Validación visual pendiente

> **El guion está escrito:** [`RECORRIDO-DE-VALIDACION.md`](RECORRIDO-DE-VALIDACION.md).
> Cubre el flujo completo de A4, la deuda de A5+A6+A8 y el asistente de A4.3, cada paso con
> qué hacer, qué hay que ver y qué sería señal de problema.

**A5 + A6 + A8 quedaron aprobados en forma provisoria**, sin recorrido visual: Daryl estaba
fuera. No está salteado, está en deuda. Se suma al guion del recorrido de **A4**, que
valida los dos bloques de una:

1. *Ajustes* abre —no tira Access Error— y el diagnóstico dice «Funcionando».
2. Cambiar una plantilla aparece en la *Bitácora* con su nombre y el antes/después.
3. El asistente de personas propone candidatos y no decide solo.
4. Las reglas de clasificación se entienden mirándolas.

## FRENOs

Los de siempre: desglose antes de cada bloque, aprobación antes de implementar, commit al
cierre de cada paso con el log mostrado antes del push. Todo contra el sandbox.
