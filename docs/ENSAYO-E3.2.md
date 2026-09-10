# Ensayo E3.2 · la higiene contra GitHub real

`scripts/sandbox/ensayo_e32_higiene.py`, contra `prm-sandbox`. 10-sep-2026.

## Por qué contra GitHub y no con dobles

La distinción entera de E3 —integrada contra abandonada— sale de una comparación que hace
GitHub, no nosotros. Un doble que conteste `ahead_by` prueba que sabemos leer un número;
lo que hay que probar es que ese número signifique lo que creemos sobre ramas de verdad.

Se provocan las tres situaciones: un repositorio nuevo con la línea `19.0`, una rama
creada en el mismo commit (integrada) y otra con un commit propio (trabajo sin integrar).

## Resultado

    [OK] las_tres_situaciones_se_detectan
    [OK] la_abandonada_no_se_ofrece
    [OK] borrado_y_vuelta_exacta
    [OK] no_se_borra_lo_que_dejo_de_estar_integrado
    [OK] archivar_y_desarchivar

Lo que se midió, y no se dedujo:

- La rama integrada se borró por el embudo —con el nombre escrito a mano— y **volvió en
  el mismo commit**. El SHA de antes y el de después son el mismo, leídos de GitHub.
- Se empujó un commit a esa rama **después de la auditoría** y antes del apply: la
  operación quedó `failed` con «ya no está integrada», y **la rama siguió ahí**. Sin esa
  relectura el embudo habría hecho lo que el motor se niega a proponer.
- El repositorio se archivó, GitHub lo confirmó archivado, y se desarchivó.

## Dos defectos que sólo el ensayo podía encontrar

**1 · `last_commit_date` no lo llenaba nadie.** El campo existía desde F1 y ningún sync lo
escribía, así que el hallazgo de rama abandonada —que lo mira— **no podía dispararse
nunca**: media E3 era código muerto. Los tests unitarios no lo veían porque escribían la
fecha a mano en el fixture; es el antipatrón de siempre, esta vez del lado de los datos y
no de las entradas.

Arreglado sin pagar una llamada más: la comparación que E3.2a ya hace trae los commits que
están adelante, y el más nuevo de ésos **es** la punta de la rama cuando hay trabajo sin
integrar — que es el único caso donde la fecha se usa.

**2 · Archivar no estaba en el catálogo de planificables.** El hallazgo salía con su
remediación, la pantalla ofrecía el botón, y al apretarlo respondía «este hallazgo no se
remedia con un plan de escritura». La operación existía y el camino hacia ella no.

Los dos tienen su test.

## Lo que el ensayo mueve, y por qué está bien

Baja los dos umbrales a cero mientras corre. No se puede envejecer una rama seis meses en
un ensayo de tres minutos, y lo que se prueba es **la regla**, no la aritmética de la
fecha. Los deja como estaban al terminar.
