# Tramo de migración visual · dimensionado

**Decidido:** 5 de septiembre de 2026, después del ensayo de D2 y **antes** de seguir con
D2. Cuatro pantallas contra el entregable de diseño, exactas. Las tres reglas de proceso
que lo acompañan viven en `CLAUDE.md` («Lo visual: tres reglas que no se negocian»).

Páginas del print que mandan: **2b** plan · **2c** hallazgos · **2d** bitácora ·
**1b + 3a** panel de salud.

---

## V0 · La base compartida — va dentro de la primera pantalla, no como paso aparte

No es una pantalla y por eso no lleva número propio: es lo que la primera pantalla tiene
que dejar hecho para que las otras tres no lo reinventen.

- `components.scss`: chip de severidad **sólido y con texto** (nunca color solo), chip de
  estado, `.rm-mono` para todo identificador git, tarjeta, bloque antes/después de dos
  columnas, y el estado **«no se pudo leer»** rayado con su causa.
- **El patrón de la regla 2, una sola vez:** clase + plantilla QWeb de «casillero
  apagado», que recibe qué es y con qué bloque llega. Cinco copias divergen.
- Un widget OWL base del que cuelguen los tres componentes de pantalla, para no repetir el
  cableado de `record` / bus que ya se resolvió en `live_progress`.

Se paga una vez y la paga la pantalla más simple. Por eso el orden que sigue.

---

## El orden, y por qué difiere del que pediste

Pediste hallazgos → plan → bitácora → panel, que es el orden en que las operás. Propongo
**bitácora → plan → hallazgos → panel**, por una sola razón: la primera pantalla paga V0,
y conviene que la pague la que **más vocabulario usa con menos interacción**. La bitácora
es de sólo lectura: si la abstracción de chips, mono y antes/después sale mal, se ve
enseguida y se corrige barato. Si esa misma abstracción sale mal debajo del drag & drop de
hallazgos, se corrige caro y con riesgo funcional.

El panel va último en las dos versiones: consume el vocabulario de las otras tres y no
aporta ninguno propio.

Si preferís tu orden, se hace igual; lo que cambia es que V0 lo paga hallazgos, que es la
pantalla con más riesgo funcional del tramo.

---

## V1 · Bitácora *(página 2d)*

**Lo que hay hoy:** una lista Odoo con sus columnas. Los datos están todos: `entry_class`,
`previous_state_json`, la cadena y su verificación, el enlace a la operación.

**Lo que se construye:** lista Odoo con filtros nativos, renderizada como **línea de tiempo
OWL**. Agrupada por día con su encabezado en castellano («Hoy · jueves 4 de septiembre»).
Cada entrada: hora, referencia al plan y la operación, chip de clase, la frase en
castellano, y el bloque **antes/después en mono** —izquierda gris, derecha del color del
resultado—. Debajo, quién aprobó y «Verificado en GitHub». La **leyenda de los cuatro
tipos** y el bloque «Por qué es inmutable» con el estado de la cadena, que ya se calcula.

**Apagado (regla 2):** «Exportar firmado (CSV + hash)» — llega con E3. Las entradas de
cambio detectado fuera de la app no se maquetan con datos falsos: el tipo existe, la
detección de deriva es E1, y si no hay ninguna, no hay ninguna.

**Riesgo:** bajo. Sólo lectura, sin acciones nuevas.
**Peso:** medio, y carga V0 encima.

## V2 · Plan de escritura *(página 2b)*

**Lo que hay hoy:** formulario con statusbar, lista de operaciones, y la confirmación
individual **en un asistente aparte**.

**Lo que se construye:** la lista de operaciones como componente OWL agrupado por
repositorio, y **la confirmación baja a la fila** —que es el punto del diseño: se lee
junto a la consecuencia, no en un modal que la tapa—. Dos niveles, siempre: reversible un
tilde; irreversible, escribir el nombre exacto de lo que se destruye. Arriba, «Qué va a
pasar si aprobás» en castellano. Abajo, **las dos barras separadas**: reversibles
aprobadas *n/m*, irreversibles confirmadas *n/m*, y el botón que aprueba todas las
reversibles de una vez — las irreversibles, nunca en lote. El estado *aplicándose* usa la
misma pantalla, con la columna de aprobación convertida en progreso, reusando
`live_progress`.

**Lo que NO se mueve:** la guarda vive en el modelo (`_aprobar(confirmadas=...)`) y ahí se
queda. Esto cambia dónde se ve, no quién decide.

**Apagado (regla 2):** «Detener después de esta operación» — no está implementado; llega
con el tramo de conciliación que abrió el ensayo. «Sacar la 04 del plan y aprobar el
resto» se puede hacer hoy y va vivo.

**Deuda honesta que esta pantalla hace visible:** hoy **no existe ningún tipo de operación
irreversible con manejador**, así que el campo de escribir el nombre se construye y se
prueba, pero no se puede ver contra una operación real hasta que exista una. Es lo que el
guion de validación anota en su punto 2.6, y sigue vigente.

**Riesgo:** medio-alto — toca el camino de aprobación, que es el control central de F2.
**Peso:** el mayor de los cuatro.

## V3 · Hallazgos *(página 2c)*

**Lo que hay hoy:** lista agrupada por severidad y la acción de lote «armar plan con
estos».

**Lo que se construye:** las tarjetas de severidad del mockup —chip sólido con texto—,
encabezados de grupo con sus conteos y su línea de contexto («3 hallazgos · 2 en el plan
borrador · 1 requiere confirmación»), la fila expandida con **regla que incumple** y
**evidencia leída de GitHub** en mono, y la **bandeja lateral del plan en borrador** con
arrastre, según la especificación de la página 6d: fantasma a −2° con contador, origen al
50 %, zona soltable con borde punteado y tinte, entrada desde arriba en 120 ms, sin toast.
Los informativos no tienen mango, y al arrastrar sobre zona inválida la causa se dice en
una línea.

**Apagado (regla 2):** el bloque **Historia** («apareció en la auditoría #57, no estaba en
la #56») — llega con E2, que es quien compara corridas.

**Riesgo:** medio. La bandeja es la pieza más grande de todo el tramo y es una forma nueva
de armar planes; el camino de lote existente se mantiene mientras tanto.
**Peso:** grande, casi todo en la bandeja.

## V4 · Panel de salud, versión 1 *(páginas 3a y 1b)*

Adelanto de E4, acotado a lo que los datos de hoy sostienen sin inventar nada.

**Los tres números, con datos reales:**

| número | de dónde sale | qué muestra el día uno |
|---|---|---|
| Ramas principales protegidas | `repo.branch.protected` sobre las relevadas | `0 %` es `0 %` |
| Commits con convención | `repo.commit.sample.message_ok`, últimos 30 días | `—` si no hay convención definida |
| Hallazgos abiertos / críticos | los conteos de la corrida | `0` con su frase: cero porque nada se exige todavía |

**«Hoy vs anterior»:** el delta se calcula contra la corrida anterior, que ya está en la
base. El **tramo rayado de «sin leer»** sale de `protection_readable`, y es la misma regla
de siempre: lo que no se pudo leer no se cuenta como bueno.

**La frase de estado** se redacta desde los hallazgos críticos; sin ninguno, dice «dentro
de la política» con su chip. **El día uno, sin maquillaje:** el único chip es SIN POLÍTICA
y el botón lleva a definir la primera plantilla.

**El detalle plegado** trae lo que hay: por gravedad, por tipo de repositorio, y cuentas
sin dueño. El pliegue recuerda su estado por usuario.

**Apagado (regla 2):** la **tendencia de las últimas 8 corridas** y el botón «Comparar con
auditoría anterior» — llegan con E2. La **meta configurable** del 85 % — llega con E4.

**Riesgo:** bajo. No escribe nada.
**Peso:** medio; casi todo es composición de lo que las tres anteriores dejaron.

---

## Qué NO entra en este tramo

Las pantallas ya construidas que no están en la lista —repositorios, auditorías, política,
personas, configuración, inventario de módulos— **se migran cuando se las toque por otra
razón**, como quedó decidido. Este tramo son cuatro, no doce.
