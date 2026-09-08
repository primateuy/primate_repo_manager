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
