# Ensayo E2.4 · el delta contra GitHub real

`scripts/sandbox/ensayo_e24_delta.py`, contra `prm-sandbox`. 10-sep-2026.

## Qué vino a buscar

Las tres frases del delta —«lo corrigió PLAN-X», «se resolvió en la app», «se resolvió
fuera de la app»— son afirmaciones sobre lo que pasó **fuera de la pantalla**, y en los
tests ese «afuera» lo fabricamos nosotros. Acá cada una se produce por su camino real.

| # | Cambio | Camino |
|---|---|---|
| 1 | Un ruleset con drift, remediado | Plan armado desde el hallazgo → aprobado → aplicado contra GitHub |
| 2 | Un repositorio sin clasificar | Clasificado a mano en Odoo. **No toca GitHub** |
| 3 | Otro ruleset con drift | Restaurado a mano con una llamada directa a la API, por fuera del embudo |

## Resultado

    [PLAN]  Lo corrigió Ensayo B1.6 20260907-161914 el 10/09/2026 · verificado
    [APP]   Se resolvió en la app: clasificación definida
    [FUERA] Se resolvió fuera de la app: alguien lo cambió en GitHub.

Las tres, como debían. Y el correo del lunes salió sólo en la corrida **programada**; la
lanzada a mano no mandó nada.

## Un defecto que sólo aparecía con GitHub de verdad

**La caja punteada de «sin leer» no salía.** La corrida terminó `partial` con un
repositorio ilegible —se lo borró de GitHub *después* del enumerado, que es como pasa en
la realidad— y el correo salió sin nombrarlo.

La causa: la caja se armaba desde el bloque «sin confirmar» del delta, que habla de
**hallazgos** que no se pueden dar por resueltos y por eso sólo lista repositorios que ya
tenían alguno. El repositorio era nuevo: no tenía hallazgos anteriores, así que no
aparecía — pero **sí** quedaba fuera de los tres números de arriba.

Son dos afirmaciones distintas y las dos son correctas:

- La pantalla dice de qué **hallazgos** no se puede afirmar que se resolvieron.
- El correo dice de qué **números** no se está hablando.

Arreglado: la frase del correo sale de las filas de la corrida. Con su test.

## Lo que el ensayo confirmó de paso

`action_remediate` reutiliza el borrador abierto de la conexión, y en el sandbox ese
borrador arrastraba una operación `needs_reconciliation` de un ensayo que se cayó a la
mitad. Al aplicar, **la guarda hizo exactamente lo suyo**: congeló la vieja, aplicó la
nuestra —verificada por relectura— y cerró el plan en `failed`, porque un plan que no hizo
todo lo aprobado no está aplicado. No es un defecto; es la precaución funcionando en un
caso que nadie preparó.

## El correo, mirado

Los tres HTML quedan en `/tmp/correo_e24_*.html` y se revisaron renderizados en Chromium:

- **El del lunes**: los tres números con su movimiento, «lo nuevo» por gravedad con su
  chip de severidad, el plan que espera, y el pie que explica por qué llega.
- **El de la caja punteada**: el borde punteado, el nombre en monoespaciada, la causa de
  GitHub tal cual, y la frase en negrita. El delta de hallazgos abiertos salió **▲ 1 en
  rojo** — más hallazgos es peor, que es la regla del color funcionando en el correo.
- **El de la auditoría fallida**: la causa, y que los números de la aplicación son los de
  la semana pasada.

**NO se pudo probar en un cliente de correo real, y hay que decir por qué.** Los ocho
servidores de correo saliente de la base de staging están **desactivados**, y en la cola
hay 232 mensajes en excepción y 171 cancelados, muchos dirigidos a direcciones reales de
clientes. Activar un servidor para probar este correo soltaría esa cola. El envío quedó
pendiente de un servidor dedicado.
