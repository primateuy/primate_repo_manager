# Bloque B · aplicar la política — desglose antes de implementar

**Escrito:** 6 de septiembre de 2026, con el Bloque D cerrado.
**Qué es B:** hasta hoy el módulo **lee** la política y dice quién la incumple. B es donde
empieza a **aplicarla**: escribir las reglas en GitHub, proponer los checks, generar
CODEOWNERS, detectar cuando alguien las cambia por fuera, y crear repositorios que nacen
gobernados. Es el bloque más grande que queda y el corazón de la demo.

**Todo entra por el embudo que ya existe.** B no estrena forma de escribir: arma planes,
que se leen, se aprueban con confirmación por operación y se aplican con verificación por
relectura. Lo nuevo son los tipos de operación y las pantallas, no el motor.

---

## ⚠️ Antes de nada: el paso manual tuyo, con los clics exactos

**E1 no puede leerse con los permisos que la App de auditoría tiene hoy.** Los verifiqué
contra GitHub esta semana: `actions`, `administration`, `contents`, `metadata`,
`pull_requests`, `statuses` — todos en *read*. Ninguno alcanza para alertas de seguridad.

Faltan **dos permisos**, los dos de sólo lectura:

| permiso en GitHub | para qué | endpoint que habilita |
|---|---|---|
| **Secret scanning alerts** · Read-only | secretos filtrados | `GET /repos/{o}/{r}/secret-scanning/alerts` |
| **Dependabot alerts** · Read-only | vulnerabilidades de dependencias | `GET /repos/{o}/{r}/dependabot/alerts` |

### El paso, clic por clic — App 4805796 (auditoría, cuenta `primateuy`)

1. `github.com/settings/apps/<la app de auditoría>` → pestaña **Permissions & events**.
2. En **Repository permissions**, buscar **Dependabot alerts** → poner **Read-only**.
3. En la misma lista, **Secret scanning alerts** → **Read-only**.
4. Abajo de todo, **Save changes**.

**Y ACÁ ESTÁ LO QUE NOS MORDIÓ DOS VECES: guardar NO alcanza.** Al agregar permisos, GitHub
deja la instalación pidiendo consentimiento y **el token sigue saliendo con los permisos
viejos** hasta que alguien acepta. No falla ruidosamente: los endpoints nuevos devuelven
403 como si el recurso no existiera.

5. Ir a `github.com/settings/installations` → la instalación de esa App → aparece un aviso
   **«Review request» / «This app is requesting updated permissions»** → **Review** →
   **Accept new permissions**.
6. Recién ahí el token nuevo los trae.

**Cómo comprobar que quedó**, sin creerle a nadie:

```
./odoo-bin shell -c <conf> -d <base> --no-http \
    < primate_repo_manager/tools/chequeo_de_cierre.py
```

El punto «Permisos de la App» tiene que listar `dependabot_alerts: read` y
`secret_scanning_alerts: read`. Si no están, el paso 5 no se completó — y el chequeo lo va
a decir, que para eso existe.

> **Nota:** son permisos de **lectura** y van en la App de **auditoría**, no en la de
> escritura. E1 lee alertas; no las resuelve ni las silencia.

---

## B1 · Rulesets por plantilla

**Qué hace.** Traduce una plantilla de política a un ruleset de GitHub y lo aplica a los
repositorios que esa plantilla gobierna. Hoy el módulo compara exigido contra observado; B1
es escribir el exigido.

**Decisiones ya tomadas que hay que respetar:**

- **`prm-writer` va como bypass actor** en todo ruleset que el módulo aplique. Quedó
  decidido cuando se diseñó D2: si el ruleset exige PR y la App no está exenta, el propio
  módulo no puede escribir — y el embudo plan/aprobación/bitácora **es una revisión más
  estricta que una PR**. Sin esto, la guarda de «destino escribible» que ya existe frenaría
  cada apply.
- **El payload de un ruleset sale de la plantilla, no del hallazgo.** Es la lección de
  A4.1: `remediation_payload` identifica, no configura.

**Lo que trae de la tercera columna del checklist** (ver `COBERTURA-DEL-DISENO.md`): la
comparación **«Exige … · Tiene …» por rama** en el formulario del repositorio, y la columna
**«Incumplen hoy»** por exigencia en la plantilla. Las dos son la misma comparación mirada
desde los dos lados, y este es su bloque.

**Riesgo específico:** un ruleset mal armado bloquea *todos* los merges del repositorio.
Por eso la verificación por relectura acá no es opcional y el rollback tiene que devolver
el ruleset anterior, no borrarlo — borrar un ruleset que ya existía sería destruir
configuración que no pusimos nosotros. *(Ya hay un test que cubre esto en el motor.)*

### B1, en pasos — aprobado el 7-sep-2026

| paso | qué deja hecho | estado |
|---|---|---|
| **B1.1** | La traducción plantilla → JSON de ruleset, **pura**: no toca GitHub ni la base | **hecho** |
| **B1.2** | `ruleset_update` entra al catálogo de operaciones | **hecho** |
| **B1.3** | El apply: leer, aplicar el diff, verificar releyendo, registrar | **hecho** |
| **B1.4** | «Exige … · Tiene …» por rama, en el formulario del repositorio | **hecho** |
| **B1.5** | «Incumplen hoy» por exigencia, en la plantilla | **hecho** |
| **B1.6** | Ensayo contra el sandbox y mutación de las guardas nuevas | **hecho** — ver [`ENSAYO-B1.6.md`](ENSAYO-B1.6.md) |

**Dos confirmaciones que se pidieron y quedan escritas acá para que no se pierdan:**

1. **`ruleset_update` va con el ciclo de cuatro pasos**, y su lugar en la taxonomía de
   `repo_write_apply.py` queda documentado **en el commit que lo agrega**: es
   **idempotente por destino** —el ruleset ya existe y tiene id propio; escribir dos veces
   deja el mismo resultado— y **no crea identidad**, así que no lleva el paso 2b. Es
   justamente por esto que hace falta: con sólo `ruleset_create` y `ruleset_delete`,
   reaplicar una política significa borrar y crear, y eso destruye el id por el que el
   rollback vuelve.

2. **La mutación de B1.6 cubre las dos guardas nuevas, cada una con su rojo:**
   «no se borra un ruleset ajeno» y «el rollback devuelve el ruleset anterior, no lo
   borra». Una guarda que nunca falló no está probada, está supuesta.

**Y B1.4/B1.5 nacen visuales** —tokens y patrones desde el primer commit, regla 3—: son la
tercera columna del checklist de cobertura volviéndose pantalla, no una lista sobre la
cara vieja.

#### Lo que el ensayo contra GitHub real agregó (B1.6)

La primera corrida salió **en rojo, y con razón**: la verificación comparaba por igualdad
exacta y GitHub **completa el objeto con parámetros que nadie mandó**
(`allowed_merge_methods`), así que rechazó una escritura que había salido perfecta. El
mismo criterio mataba el atajo de «si ya está como se pide, no se escribe»: contra la API
real nunca se habría tomado. Ningún test lo vio porque el doble devolvía lo que recibía.
Detalle completo en [`ENSAYO-B1.6.md`](ENSAYO-B1.6.md).

#### Las dos guardas de B1.3, con su mutación hecha

| guarda | qué impide | mutación | rojo |
|---|---|---|---|
| **No se toca un ruleset ajeno** | escribir sobre configuración que no puso este módulo, reconocida por el prefijo del nombre | la guarda deja de comprobar | 🔴 1 |
| **El rollback devuelve, nunca borra** | que revertir una actualización destruya un ruleset que existía antes del plan | el rollback borra en vez de restaurar | 🔴 1 |

Y una tercera, del diff: **si ya está como se pide, no se escribe**. Mutación —escribir
siempre— 🔴 1. Un PUT con los mismos valores gasta cuota, aparece en la auditoría de la
organización como un cambio que nadie hizo y deja una constancia de emisión que después
hay que conciliar contra un efecto inexistente.

La guarda del ruleset ajeno se comprueba **dos veces**, al leer y al revertir, y la
segunda no es redundante: entre una y otra pasó una escritura, y pudo pasar cualquier otra
cosa —incluido que alguien renombrara el ruleset—.

#### B1.4 y B1.5: el tercer estado, y un defecto que la pantalla destapó

Las dos pantallas salen del **mismo comparador** —`repo.branch.comparacion_de_politica()`—
y eso es deliberado: dos implementaciones de «esta rama cumple» darían dos números para la
misma pregunta y ninguna forma de saber cuál mirar.

**El tercer estado manda en las dos.** Una rama ilegible no se dibuja como «no tiene» ni
engrosa el número de «Incumplen hoy»: va con la trama del sistema y su causa, y las
ilegibles se cuentan aparte. Es la distinción de F1 —GitHub devuelve el mismo 404 para «no
está protegida» y para «no podés saberlo»— defendida ahora también en la interfaz, que es
donde más caro sale perderla porque es lo que la gente mira.

**Lo que la pantalla destapó al construirse:** el comparador daba por cumplidas
«sin escritura directa» y «sin borrado» en una rama SIN protección, porque leía la ausencia
de `allow_force_pushes` como si fuera la restricción puesta. Una rama sin ninguna
protección habría aparecido como «Parcial», que es el estado más peligroso del sistema
disfrazado del segundo mejor. Lo cazó un test antes de llegar a pantalla.

| mutación | rojo |
|---|---|
| Lo ilegible se dibuja como «sin protección» | 🔴 3 |
| La ausencia de protección vuelve a leerse como restricción puesta | 🔴 2 |
| Lo ilegible se cuenta como incumplimiento en «Incumplen hoy» | 🔴 1 |

#### Lo que B1.1 dejó decidido, y conviene saber antes de B1.3

- **Las condiciones del ruleset nombran las ramas observadas, una por una.** Los roles de
  rama se deciden con expresiones regulares y las condiciones de GitHub son fnmatch:
  traducir regex a glob no se puede en general, y aproximarlo inventaría el alcance de una
  regla que bloquea merges. El agujero —una rama creada después de la última auditoría no
  queda cubierta hasta la próxima— **está dicho en el código y se muestra**, no tapado.
- **El actor exento sale de la conexión** (`write_app_id`), nunca de una constante: es
  4808079 en el sandbox y 4811232 en producción. Sin App de escritura declarada **no se
  arma el ruleset** — uno sin exención se aplica bien y frena el apply siguiente.
- **Lo que no se traduce viaja en `no_traducido` y se ve.** Hoy son tres: los checks sin
  confirmar, el patrón de nombre de rama —que gobierna las ramas nuevas y necesita su
  propio ruleset sobre todas— y las ramas de fork.

## B2 · Checks requeridos, con la propuesta armada

**El problema que resuelve.** Un check requerido cuyo nombre no existe **bloquea todos los
merges para siempre**. Por eso hoy ninguna plantilla define checks: inventar un nombre era
peor que no tener ninguno, y hay un test que lo vigila.

**Cómo se sale de ahí sin inventar:** el módulo ya releva los workflows de CI de cada
repositorio (`repo.workflow`: nombre, archivo, estado). B2 **propone** los checks a partir
de lo relevado — «estos son los workflows que corren hoy en los repos de esta plantilla; en
cuántos de ellos existe cada uno» — y una persona elige. Nunca se define un check que no se
haya visto correr.

**La propuesta se ordena por cobertura**, no por nombre: un workflow que corre en 20 de 21
repositorios es candidato; uno que corre en 2 es una excepción y se dice.

### B2 · lo que la medición cambió, antes de escribir una línea

**El hueco no se cierra eligiendo de una lista, porque la lista está vacía — y está vacía
por el motivo correcto.** Medido contra la cuenta real el 7-sep-2026:

| | |
|---|---|
| Repositorios | 113 |
| Con workflows **declarados** en un archivo yml | **17** |
| Con **check runs de verdad** en su rama por defecto | **0** |

**La propuesta que dejó F1 era incorrecta por construcción.** Salía de los nombres de
workflow —`pre-commit`, `tests`— y un ruleset exige el nombre del **check run**, que no es
el mismo: un workflow `CI` con dos jobs produce checks con el nombre de los jobs. Exigir el
equivocado **no falla al aplicar**: aplica bien, y después ningún merge de ese repositorio
vuelve a pasar, porque GitHub espera para siempre un check que nadie reporta. Era
exactamente la advertencia por la que el hueco se dejó abierto — y esa propuesta la habría
desoído. Quedó desactivada, levantando con el motivo escrito.

**Lo que hay ahora:** `repo.check.context` guarda **verbatim** los nombres que GitHub
reportó, y `candidatos_de_check()` los ordena por cobertura marcando las excepciones. Con
cero checks observados, la propuesta sale vacía **con sus dos números al lado** —17
declaran, 0 corrieron—, que es lo que distingue «no hay candidatos» de «no miramos».

**La decisión que queda sobre la mesa no es cuál check exigir: es que la CI no corre.**

## B3 · CODEOWNERS generado

**Qué hace.** Genera el archivo `CODEOWNERS` a partir del responsable del repositorio y de
las reglas de la plantilla, y lo escribe por el mismo embudo.

**Dos cosas que hay que decidir al implementar** (no ahora):
- Qué pasa si el repositorio **ya tiene** un CODEOWNERS escrito a mano. La respuesta que
  propongo: no se pisa. Se muestra el diff y se ofrece reemplazarlo como operación
  destructiva con confirmación — es configuración que alguien escribió.
- Si el owner de una regla **no tiene acceso** al repositorio, GitHub ignora esa línea en
  silencio. Hay que detectarlo y decirlo: una línea ignorada es una revisión que nadie va a
  pedir nunca.

## B4 · Drift, en los dos sentidos

**Qué es.** Detectar que la configuración de GitHub y la política se separaron. Los dos
sentidos son distintos y por eso son dos:

- **Alguien cambió GitHub por fuera.** La protección que el módulo aplicó ya no está, o
  cambió. Es el `drift_detected` que la bitácora ya tiene como tipo de entrada y que hoy
  nadie produce.
- **Alguien cambió la política.** La plantilla se editó y los repositorios que la aplicaban
  quedaron atrás. Esto **se lee del registro de cambios de política** —`repo.policy.audited`
  ya lleva ese rastro— y no de una comparación a ciegas: sin saber cuándo cambió qué, no se
  puede distinguir «el repo se desvió» de «la política se movió».

**Por qué importa la distinción:** el primero es un incidente y el segundo es trabajo
pendiente. Mostrarlos juntos convierte los dos en ruido.

### B4, en pasos — aprobado el 7-sep-2026

| paso | qué deja hecho | estado |
|---|---|---|
| **B4.1** | Sentido 1: lo aplicado contra lo observado. Hallazgo planificable + bitácora sólo en el cambio de estado. Y el modelo de métricas, escribiendo desde ya | **hecho** |
| **B4.2** | Sentido 2: la política se movió y no se reaplicó, leyendo `policy_changed` | **hecho** |
| **B4.3** | La bitácora dibuja las entradas «Fuera de la app»; la cobertura pasa de 🔒 a ✅ | **hecho** |
| **B4.4** | Mutación y ensayo contra el sandbox, con las dos caras | **hecho** — ver [`ENSAYO-B4.4.md`](ENSAYO-B4.4.md) |

**Los cinco criterios, decididos:**

1. **La referencia es lo APLICADO, no la plantilla.** Sale de la entrada `write_applied`
   de la bitácora inmutable. Comparando contra la plantilla, «GitHub cambió» y «la
   política se movió acá» dan el mismo resultado — y separarlos es para lo que existe B4.
   La bitácora deja de ser sólo registro y pasa a ser **referencia**: que sea inmutable
   ya no es sólo virtud de auditoría, es garantía de la detección.
2. **Corre con la auditoría**, pero escrito sin asumir corrida: un drift de webhook no va
   a tener `run_id`.
3. **El criterio de comparación es el de la escritura, compartido.** «Difiere en lo que
   gobernamos» no es «difiere en lo que GitHub agrega solo».
4. **La bitácora anota el CAMBIO de estado**, no la persistencia: nace el desvío, se
   cierra el desvío. El estado se **deriva** de la última entrada `drift_*`, sin bandera.
5. **El sentido 2 no produce entrada de bitácora**, produce hallazgo: que la política se
   movió acá ya lo registró A5 como `policy_changed`; anotarlo como «cambio fuera de la
   app» sería mentir sobre dónde pasó.

**Y el hallazgo de drift externo es planificable:** su remediación es `ruleset_update` con
el payload de la última `write_applied`. El módulo que detecta el incidente ofrece su
corrección por el mismo embudo que todo lo demás.

## B5 · Wizard de crear repositorio

**Qué hace.** Crear un repositorio que **nace gobernado**: con su clasificación, su
plantilla, sus ramas, su ruleset y su CODEOWNERS, en un solo paso.

Es la pantalla **6b** del entregable y está diseñada — no se rediseña. Requiere permiso de
escritura de administración, que la App de escritura ya tiene en el sandbox.

**Ojo con el orden:** crear el repositorio y aplicarle la política son dos escrituras. Si
la segunda falla, queda un repositorio vacío sin gobierno — el mismo problema que D2
resolvió con la barrera, así que se resuelve igual: la política depende de la creación, y
si no se aplica, el repositorio queda marcado y visible, no a medias y en silencio.

## B6 · E1 integrado — seguridad

**Dos fuentes, dos tratamientos, y la diferencia es deliberada:**

| fuente | severidad | por qué |
|---|---|---|
| **Secret scanning** | **crítico, siempre** | un secreto filtrado es riesgo hoy, sin matices. No se mapea ni se modula |
| **Dependabot** | **mapeada de GitHub** | GitHub ya clasifica (critical/high/medium/low) y esa clasificación tiene detrás un análisis que nosotros no vamos a rehacer |

### Los TRES estados de una alerta — medidos el 7-sep-2026, no supuestos

El paso manual está hecho y verificado: la App 4805796 reporta `secret_scanning_alerts` y
`vulnerability_alerts` en *read*, y **cero** respuestas «not accessible by integration».
Pero el relevamiento sobre 25 repositorios mostró que «tengo permiso» no alcanza:

**Censo completo sobre los 113 repositorios** (B6.4, 7-sep-2026). Un primer sondeo sobre
25 dio «4 legibles» y **era un artefacto de la muestra**: los primeros 25 por orden de
instalación son casi todos privados. Corregido contra el total:

| respuesta de GitHub | secret scanning | dependabot | qué significa |
|---|---|---|---|
| 200 con la lista | **78** | 0 | **hay alertas** (o no hay ninguna, y eso es un dato) |
| «disabled on this repository» | **35** | **113** | **apagado en el repo** — un interruptor, no un permiso |
| «not accessible by integration» | 0 | 0 | **no se pudo leer** — sería el permiso |

**Cero alertas abiertas** en los 78 legibles: GitHub no encontró secretos filtrados en
ninguno. Y **Dependabot está apagado en los 113**, que es gratis de encender — el dato de
gobernanza más accionable que salió de este bloque. De los 35 con secret scanning apagado,
**31 son privados** y encenderlo ahí exige Advanced Security.

**Los tres se dibujan distinto, y ninguno se colapsa con otro.** Un panel que diga «cero
secretos filtrados» porque la función estaba apagada es la peor pantalla que este módulo
podría tener: afirma sobre algo que nunca miró.

Y el apagado tiene dos causas que se resuelven distinto: Dependabot se enciende gratis;
**secret scanning en repositorios privados necesita Advanced Security**, que es decisión
comercial y cae en la familia `plan_limit` que el módulo ya modela — la misma que las
protecciones de rama en repos privados de plan gratuito.

**Lo que hay que cuidar:** si los permisos del paso manual no están, los endpoints devuelven
403 y eso **no es «no hay alertas»**. Es «no se pudo leer», con su trama rayada y su causa
— la regla de la casa aplicada a lo nuevo. Un panel que dice «cero secretos filtrados»
porque no pudo mirar es la peor pantalla que este módulo podría tener.

---

### B6, en pasos — aprobado el 7-sep-2026

| paso | qué deja hecho | estado |
|---|---|---|
| **B6.1** | El cliente y el espejo, con los tres estados y sin copiar el secreto | **hecho** |
| **B6.2** | Los hallazgos, con sus dos tratamientos | **hecho** |
| **B6.3** | La pantalla: la de hallazgos filtrada a las tres clases de seguridad | **hecho** |
| **B6.4** | Verificación contra la cuenta real, sólo lectura | **hecho** — censo de 113 |

**Las tres decisiones:**

1. **Se espejan.** Sin espejo no hay «esto apareció desde la corrida anterior» —lo que E2
   va a querer— y cada pantalla tendría que volver a pegarle a GitHub.
2. **Por alerta en secretos, por repositorio en Dependabot.** La asimetría es correcta
   porque los objetos lo son: un secreto filtrado es un incidente con nombre propio;
   cuarenta vulnerabilidades de dependencias son **un** trabajo, no cuarenta.
3. **«Apagado» es informativo, con su causa distinguida:** Dependabot se enciende gratis
   (acción concreta) y secret scanning en privados exige Advanced Security (decisión
   comercial, familia `plan_limit`). B6 **lee**: no enciende nada.

#### La regla que manda en B6.2 — el hallazgo NO contiene el secreto

Ubicación, tipo y enlace a GitHub. **Nunca el valor, ni el fragmento** que la API ofrece.
Ni la pantalla, ni la bitácora, ni el informe pueden contenerlo: **un módulo de
gobernanza no replica la filtración que reporta**. Copiarlo multiplicaría por seis los
lugares donde ese secreto existe, que es lo contrario de lo que se está arreglando.

En B6.1 la garantía ya es **estructural**: el espejo no tiene ningún campo donde ponerlo,
y hay un test que falla si aparece uno. El filtrado es por **lista blanca** —se nombra lo
que entra— porque una lista negra deja pasar el campo nuevo que GitHub agregue mañana, y
acá el campo nuevo que se cuele puede ser el secreto.

## Orden propuesto, y por qué

1. **B1 · rulesets** — es lo que hace que el módulo *aplique* y no sólo *mire*; todo lo
   demás se apoya en que eso funcione.
2. **B4 · drift** — inmediatamente después: sin drift, B1 escribe y nadie se entera cuando
   alguien lo deshace. Además usa lo que B1 acaba de escribir como referencia.
3. **B6 · E1** — depende de tu paso manual, así que conviene arrancarlo temprano para que
   el re-consentimiento no bloquee al final. **Lo puedo construir contra el sandbox aunque
   producción no tenga los permisos todavía.**
4. **B2 · checks** — necesita B1 (el ruleset es donde el check se exige).
5. **B3 · CODEOWNERS** — independiente, se puede mover.
6. **B5 · crear repositorio** — último: usa todo lo anterior junto, y es la mejor demo
   cuando todo lo demás ya anda.

**Dimensión:** B es comparable a todo A junto. Seis piezas, cuatro con escritura nueva, dos
pantallas nuevas y dos comparaciones que el checklist ya reclamó.

## Lo que NO entra en B, para que quede dicho

- Resolver o silenciar alertas de seguridad desde el módulo: E1 **lee**.
- Abrir PRs desde la app: es F4, y ya está diseñado (turno 6 del entregable).
- Cambiar `addons_path` de ninguna instancia: eso es despliegue, y no lo hace este módulo.
