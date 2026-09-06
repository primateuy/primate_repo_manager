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

**Lo que hay que cuidar:** si los permisos del paso manual no están, los endpoints devuelven
403 y eso **no es «no hay alertas»**. Es «no se pudo leer», con su trama rayada y su causa
— la regla de la casa aplicada a lo nuevo. Un panel que dice «cero secretos filtrados»
porque no pudo mirar es la peor pantalla que este módulo podría tener.

---

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
