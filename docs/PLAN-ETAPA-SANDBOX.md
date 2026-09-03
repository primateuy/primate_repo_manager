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

**A2 · Vista de hallazgos.** Hoy no existe ninguna: el resultado central de la auditoría
sólo se ve en el PDF. Hace falta lista y formulario, agrupables por severidad, tipo y
repositorio, y accesibles desde la corrida que los produjo.

**A3 · Formulario de repositorio.** Hoy sólo hay lista. Sin formulario no se puede abrir
un repositorio para ver sus ramas, sus colaboradores y sus hallazgos, ni **clasificarlo a
mano** — que es un paso obligatorio del flujo real: 43 de los 113 repositorios no
clasifican por regla, a propósito.

**A4 · Armar un plan sin escribir JSON.** Hoy el payload de cada operación se escribe a
mano. Eso es interfaz de desarrollador. Hacen falta dos caminos:
- desde un hallazgo, «remediar esto», que arme la operación con el payload derivado de la
  plantilla;
- un asistente por tipo de operación, para lo que no nace de un hallazgo.

**A5 · Vistas de política.** Plantillas, reglas por rol de rama y excepciones de acceso no
tienen menú. Sin eso, la política que gobierna todo es invisible desde la aplicación.

**A6 · Personas y empleados.** `repo.member` no tiene vista. El hallazgo «cuenta sin
persona asociada» no se puede resolver desde la interfaz.

**A7 · Flag explícito «escritura habilitada en producción».**
Durante toda la F2, `write_client()` rechazaba cualquier escritura desde una conexión de
entorno *Producción*, sin excepción. Esa compuerta **se quitó** al pasar a la arquitectura
de dos Apps (commit `1f64af2`): hoy la única condición es tener credenciales de escritura
cargadas.

El reemplazo —el alcance de la instalación de la App— acota el radio del daño, pero no es
lo mismo: **no exige un acto deliberado para empezar a escribir en producción.** Cargar
las credenciales alcanza, y el primer apply real salió sin ninguna confirmación adicional.

Lo que falta: con entorno *Producción* **y** App de escritura cargada, el cliente exige
además un flag explícito de habilitación. Activarlo deja entrada en la bitácora —quién y
cuándo—, igual que cualquier otra decisión con consecuencias.

Va en el bloque A porque es de la misma naturaleza que el resto: no agrega capacidad,
protege la que ya existe. No es urgente mientras producción esté sin credenciales, pero
tiene que estar antes de volver a cargarlas.

**A8 · Pantalla de configuración.** El módulo no tiene vista de `res.config.settings`:
sus parámetros —el umbral, los umbrales de severidad— existen pero no aparecen en
*Ajustes*, y sólo se tocan por *Técnico → Parámetros del sistema*. Lo descubrió el primer
recorrido de la guía, que documentaba una pantalla inexistente.

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

---

## Bloque B — F3, política

**B1 · Aplicación de rulesets por plantilla**, no operación por operación: «aplicar la
política de esta plantilla a este repositorio» como una acción.

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
2. **A9** — el componente de estado vivo, primero: define el lenguaje visual con el que nacen las dos pantallas siguientes.
3. **A2 + A3** — hallazgos y repositorio: cierran el tramo de lectura, que es la mitad del criterio de salida.
4. **A5 + A6 + A8** — política, personas y configuración visibles.
5. **A7** — el flag de producción, antes de que producción vuelva a tener credenciales.
6. **A4** — armar planes sin JSON; cierra el tramo de escritura.
7. **B** — F3.
8. **C** — F5.

Con A completo, el criterio de salida ya es alcanzable para el flujo de auditoría y
escritura que existe hoy. B y C agregan funcionalidad; A la hace usable.

## FRENOs

Los de siempre: desglose antes de cada bloque, aprobación antes de implementar, commit al
cierre de cada paso con el log mostrado antes del push. Todo contra el sandbox.
