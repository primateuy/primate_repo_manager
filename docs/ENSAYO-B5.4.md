# Ensayo de B5.4 — el nacimiento gobernado, contra GitHub

**Cuándo:** 8 de septiembre de 2026 · **Contra:** la organización `prm-sandbox`
**Script:** `scripts/sandbox/ensayo_b54_nacimiento.py`

El asistente arma el plan, se aprueba con la confirmación del irreversible, se aplica
encadenado por la barrera, y la primera auditoría mira al recién nacido.

## Funciona de punta a punta

    10  repository_create    applied
    20  branch_create        applied     19.0-prod
    21  branch_create        applied     19.0-support
    22  branch_create        applied     19.0-staging
    23  branch_create        applied     19.0-dev
    41  ruleset_create       applied     primate/cliente-estandar/prod
    42  ruleset_create       applied     primate/cliente-estandar/staging
    43  ruleset_create       applied     primate/cliente-estandar/support
    70  dependabot_enable    applied

En GitHub: las cuatro ramas más `main`, los tres rulesets, y **Dependabot encendido**. El
repositorio se borró al terminar — el módulo no borra repositorios, así que esa llamada la
hace el ensayo, por fuera del embudo y a propósito.

## Cinco defectos que sólo aparecieron aplicando

Ninguno lo podía ver un doble.

1. **`ruleset_create` nunca había funcionado.** Su verificación busca la identidad que
   GitHub devolvió, y esa identidad se escribe en la **conexión durable** — pero Odoo abre
   sus transacciones en **REPEATABLE READ**, así que la transacción que aplica *no puede
   leer* lo que esa conexión acaba de confirmar. El ruleset quedaba creado en GitHub y la
   operación se marcaba fallida. **El defecto estaba desde B1**: el ensayo de B1.6 usó
   `ruleset_update`, que no crea identidad, y nadie más lo ejercitó.

2. **La misma invisibilidad, al revés.** Intenté escribir la fila del espejo del
   repositorio en la conexión durable —«existe en GitHub, debería sobrevivir a un
   rollback»— y la transacción principal no podía leerla: enlazaba las operaciones a un id
   invisible. Lo que garantiza no perder de vista un repositorio recién creado **no es el
   espejo sino la entrada de identidad en la bitácora**, que sí es durable. *El espejo es
   una copia; la bitácora es el registro.*

3. **Dos escritores sobre la misma fila.** Enlazar las operaciones desde la conexión
   durable las hacía chocar con la transacción principal —«could not serialize access»—.
   Es la lección de A10 otra vez.

4. **`dependabot_enable` fallaba en el paso previo.** Su lectura atrapaba `GithubNotFound`
   pero no `GithubFeatureDisabled`, que es lo que B6 introdujo para el mensaje «disabled».
   Justo en un repositorio recién creado, donde siempre está apagado.

5. **La ACL del asistente no existía.** Cualquiera que lo abriera recibía «No group
   currently allows this operation». **La suite no lo vio porque corre como
   superusuario**; ahora hay un test que lo usa como persona.

## El «cero hallazgos» NO se logró: la auditoría encuentra diez

Y hay que decirlo sin adornos, porque el eslogan del mockup —«un repositorio creado así
nace con cero hallazgos»— es hoy falso. Los diez se explican por **cuatro causas**:

| # | Hallazgos | Causa | Qué es |
|---|---|---|---|
| 1 | 5 × «rama sin protección» | **La auditoría no sabe que un ruleset protege.** Mira el flag de la API vieja de branch protection, y B1 aplica *rulesets* | **Defecto, y no es de B5**: alcanza a TODO repositorio gobernado por B1 |
| 2 | 1 × «main como rama por defecto» | El plan crea las cuatro ramas y **no cambia la rama por defecto** | Falta una operación en B5 |
| 3 | 1 × «4 de 4 commits fuera de convención» | El commit inicial del README lo hace GitHub y dice «Initial commit» | Real, y discutible: ¿se le exige convención al commit que no escribimos? |
| 4 | 1 × «admin excedido» + 2 × «no se pudo leer» | La cuenta dueña queda admin; y las dos fuentes de seguridad contestan 404 en un repositorio de segundos | Ruido de nacimiento, a decidir |

**El primero es el importante y excede a B5**: hoy el módulo aplica rulesets y después se
acusa a sí mismo de no haber protegido nada.

---

# La repetición — 8-sep-2026, con los cinco defectos cerrados

Mismo guion, mismo sandbox, código corregido. `cliente-ensayo-b54-185450`.

## Las diez operaciones, todas aplicadas

    10  repository_create    cliente-ensayo-b54-185450        depende de —
    20  branch_create        19.0-prod                        depende de 10
    21  branch_create        19.0-support                     depende de 10
    22  branch_create        19.0-staging                     depende de 10
    23  branch_create        19.0-dev                         depende de 10
    30  default_branch_set   19.0-prod                        depende de 20
    41  ruleset_create       primate/cliente-estandar/prod     depende de 20
    42  ruleset_create       primate/cliente-estandar/staging  depende de 22
    43  ruleset_create       primate/cliente-estandar/support  depende de 21
    70  dependabot_enable    cliente-ensayo-b54-185450        depende de 10

Las diez en `applied`. `ruleset_create` funcionó por primera vez. Dependabot nació
encendido. La confirmación con tipeo del irreversible se exigió y sin ella la aprobación
se negó.

## De diez hallazgos a seis, y las cuatro causas resueltas

| Causa del ensayo anterior | Estado |
|---|---|
| 5 × «rama sin protección» sobre ramas gobernadas por ruleset | **Cerrada.** Cero. Las tres ramas gobernadas leen `completa` |
| 1 × «main como rama por defecto» | **Cerrada en el plan** (operación 30) — pero ver abajo: el espejo no la refrescaba |
| 1 × «commits fuera de convención» | **Cerrada.** El commit inicial de GitHub queda exento |
| 1 × «admin excedido» de la cuenta dueña | **Cerrada.** El admin que llega por la organización no es hallazgo |

## Un defecto NUEVO que sólo apareció al arreglar el anterior

La auditoría seguía diciendo «tiene main como rama por defecto» sobre un repositorio cuya
rama por defecto **ya era `19.0-prod`** — y el apply lo había verificado releyendo de
GitHub. Causa: `_completar_desde_el_detalle` leía el GET del repositorio y **descartaba
`default_branch`**, así que el dato sólo se refrescaba en un enumerado completo de la
conexión. Un hecho viejo presentado como hecho.

Arreglado en el método que es dueño del dato —regla de «un objeto del espejo, un método
que lo actualiza»— y con su mutación.

## Lo que QUEDA, dicho sin adornos

Seis hallazgos sobre el recién nacido. Ninguno es falso; tres piden una decisión.

| # | Hallazgo | Qué es |
|---|---|---|
| 1 | «19.0-dev» sin protección | **Decisión pendiente.** La política exige protección en `dev` y el plan de nacimiento no le crea ruleset. O el plan la protege, o la política no la exige |
| 2 | «main» sin protección | **Decisión pendiente.** `main` la crea GitHub con el README y queda huérfana cuando la rama por defecto pasa a `19.0-prod`. ¿La borra el plan, o deja de exigírsele política a una rama fuera del esquema? |
| 3 | «main como rama por defecto» | Ya no aparece: era el espejo desactualizado |
| 4-5 | «No se pudo leer» Vulnerabilidades y Secretos | **Decisión pendiente.** En un repositorio de segundos las dos fuentes contestan 404. Es el tercer estado funcionando como corresponde —no dice «no tiene»— pero sobre un recién nacido es ruido |
| 6 | admin de la cuenta dueña | Ya no aparece |

## Un hallazgo de producto que el ensayo destapó de costado

**El espejo guarda repositorios que ya no existen en GitHub.** `_sync_from_backend`
upsertea lo que el listado trae y **no marca lo que dejó de venir**, así que un repositorio
borrado —o al que la instalación perdió acceso— queda en el espejo para siempre y sigue
produciendo hallazgos sobre ramas que ya no existen. Esta serie de ensayos dejó seis
fantasmas y dieciocho hallazgos falsos.

Es la misma familia que el «no se pudo leer»: **ausencia de dato no es dato**. Hoy el
módulo no distingue «no vino en el listado» de «no existe», y las dos cosas piden lo
mismo — decirlo, no callarlo. Queda anotado como hallazgo, sin arreglar: pide una
decisión sobre qué se hace con un repositorio que desaparece.

Mientras tanto el ensayo limpia su propia fila del espejo, que es basura suya.
