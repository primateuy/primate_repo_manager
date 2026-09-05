# Ensayo de D2 — la primera vez que el embudo borra contenido

**Cuándo:** 5 de septiembre de 2026 · **Contra:** `prm-sandbox`, con la App de escritura
· **Módulo de ensayo:** `prm_ensayo`, sembrado para esto.

Siete fases, en el orden en que se diseñaron. Cada una dice qué se hizo, qué se vio y qué
se aprendió. Lo que sigue no es un resumen optimista: las dos cosas que salieron distinto
de lo esperado están en «Hallazgos», que es la parte que importa.

---

## Fase 1 · Sembrar

`addons/prm_ensayo` —cuatro archivos— en `sbx-cliente-publico@17.0` y
`sbx-cliente-privado@17.0`, con los **mismos bytes**.

```
SEMBRADO prm-sandbox/sbx-cliente-publico   commit=f488e96d  arbol=b4a3e5d8237086fd229843640e4b2f205a17d86a
SEMBRADO prm-sandbox/sbx-cliente-privado   commit=a4de03c1  arbol=b4a3e5d8237086fd229843640e4b2f205a17d86a
```

**El mismo SHA de subárbol en dos repositorios distintos.** Es la propiedad sobre la que
se apoya todo D2 —git nombra los árboles por su contenido— confirmada contra GitHub real
y no contra un doble.

## Fase 2 · El plan, leído antes de aplicar nada

Un plan, tres operaciones: copiar al repositorio común, y dos borrados que **dependen** de
esa copia.

```
[10] Se copia el módulo «prm_ensayo» a prm-sandbox/prm-sbx-interno, rama 17.0, desde
     prm-sandbox/sbx-cliente-publico@17.0. Es un solo commit: o entra completo o no entra.
     saca algo=False  irreversible=False  se puede aplicar=True   depende de=—
[20] De prm-sandbox/sbx-cliente-publico, rama 17.0, SE BORRA el módulo «prm_ensayo»
     (addons/prm_ensayo). Las instancias que lo tomen de este repositorio dejan de
     encontrarlo: eso es addons_path, y Repo Manager no lo cambia.
     saca algo=True   irreversible=False  se puede aplicar=True   depende de=[3260]
[21] …ídem sbx-cliente-privado…
```

La aprobación, con el rol de líder técnico:

```
1 · sin confirmar ninguna  → se niega: «Quedan 2 operación(es) destructiva(s) sin confirmar: …»
2 · confirmando una sola   → se niega: «Quedan 1 operación(es) destructiva(s) sin confirmar: …»
3 · confirmando las dos    → estado=approved  huella intacta=True
```

## Fases 3 y 4 · Copiar, verificar, y matar el proceso en el medio

El apply corre y se lo mata con `os._exit(9)` **entre la copia y el primer borrado**: sin
`finally`, sin commit. Lo más parecido a que el servidor se caiga.

Desde un proceso nuevo, las tres fuentes por separado:

```
BASE · plan=approved
      [10] module_copy    pending
      [20] module_delete  pending
      [21] module_delete  pending
BITÁCORA · 2 entradas que sobrevivieron: write_emitted, selladas
GITHUB · prm-sbx-interno       prm_ensayo: b4a3e5d8237086fd229843640e4b2f205a17d86a
GITHUB · sbx-cliente-publico   prm_ensayo: b4a3e5d8…
GITHUB · sbx-cliente-privado   prm_ensayo: b4a3e5d8…
CADENA · ok
```

Tres cosas, y las tres importan:

1. **No se borró nada.** El peor caso que este diseño permite es duplicación benigna, y es
   exactamente lo que quedó: el módulo en tres lados.
2. **La base no sabe nada** —todo volvió a «pendiente»— y eso es correcto: la transacción
   murió. Lo único que quedó del intento es lo que se escribió en la conexión aparte.
3. **La cadena de la bitácora quedó en verde**, con entradas escritas por dos conexiones
   distintas. Es la verificación en dos procesos de la corrección del sellado.

## Fase 5 · Completar

```
PLAN=applied
  [10] module_copy    applied
  [20] module_delete  applied
  [21] module_delete  applied
GITHUB prm-sbx-interno       prm_ensayo: b4a3e5d82370
GITHUB sbx-cliente-publico   prm_ensayo: NO ESTÁ
GITHUB sbx-cliente-privado   prm_ensayo: NO ESTÁ
```

La promoción, completa: el módulo vive en el repositorio común y salió de los dos
clientes.

## Fase 6 · Revertir

Puntos de retorno guardados, uno por operación:

```
[10] module_copy    prm-sbx-interno       commit previo=b7282e38  árbol=b4a3e5d82370
[20] module_delete  sbx-cliente-publico   commit previo=f488e96d  árbol=b4a3e5d82370
[21] module_delete  sbx-cliente-privado   commit previo=a4de03c1  árbol=b4a3e5d82370
```

```
PLAN=rolled_back   (las tres operaciones revertidas)
GITHUB sbx-cliente-publico   prm_ensayo: b4a3e5d82370   ← volvió
GITHUB sbx-cliente-privado   prm_ensayo: b4a3e5d82370   ← volvió
GITHUB prm-sbx-interno       prm_ensayo: b4a3e5d82370   ← SE QUEDÓ
```

Los borrados se deshicieron: el módulo volvió a los dos clientes, byte a byte. El destino
se quedó con el módulo — ver el hallazgo 1, que es por qué.

## Fase 7 · El caso feo

Con el plan **ya aprobado**, alguien empuja un parche urgente al módulo en el origen, por
fuera de Repo Manager:

```
alguien empujó: el módulo en el origen pasó de b4a3e5d82370 a 419a833e0021

PLAN=failed
  copia   : failed  «La escritura respondió bien pero la relectura no lo confirma: la copia
                     NO quedó idéntica — esperado b4a3e5d8…, obtenido 419a833e…»
  borrado : blocked_by_dependency
GITHUB sbx-cliente-publico   prm_ensayo: 419a833e0021   ← el parche sigue ahí
```

**El parche de otro no se perdió.** La copia se negó a darse por buena porque lo que copió
no era lo que se aprobó, y el borrado no se intentó: quedó en «no ejecutada por
dependencia», que no es lo mismo que fallida.

Y el cierre del arreglo de ayer: esa copia **falló después de escribir**, así que el
embudo tiene que ofrecer deshacerla.

```
copia: estado=failed  ¿tiene efecto en GitHub? True  ¿hay constancia de emisión? True
tras revertir: estado=rolled_back
GITHUB prm-sbx-interno   prm_ensayo: b4a3e5d82370   ← volvió al estado anterior
```

---

## Hallazgos

### 1 · Una escritura huérfana de una caída se cuela en el punto de retorno

**Qué pasó.** Las dos corridas que se mataron en la fase 4 dejaron el módulo copiado en el
destino. La base volvió a «pendiente», así que para el módulo esas copias nunca pasaron.
Cuando la fase 5 volvió a aplicar, la operación leyó su estado previo —y ese estado previo
**ya incluía su propia escritura huérfana**—. Por eso, al revertir en la fase 6, el destino
volvió a un estado que contiene el módulo: el rollback fue fiel a lo que se registró.

**Por qué importa.** El embudo no miente en ningún paso, y aun así el resultado final tiene
un objeto que ningún plan aplicado explica. La constancia de emisión existe —está en la
bitácora, sellada— pero nadie la concilia: hoy sólo la mira la operación que la escribió,
para decidir si se puede revertir.

**Qué haría falta.** Antes de aplicar, una operación tendría que preguntarse si ya tiene
escrituras emitidas sin desenlace registrado. Si las tiene, negarse y pedir conciliación
—verificar qué hay allá afuera y decidir si eso cuenta como aplicado o se revierte— en vez
de arrancar de nuevo y absorber lo huérfano como si fuera el paisaje.

**No está hecho.** Es el primer punto del próximo tramo de D2.

### 2 · La pantalla del plan no cuenta la caída

Después de matar el apply, el plan se ve idéntico a como se veía antes: aprobado, todo
pendiente. Nada indica que hubo un intento y que algo salió. Quien mire sólo Odoo no tiene
manera de saberlo; la única señal está en la bitácora, y hay que ir a buscarla.

Es la misma conciliación del hallazgo 1, del lado de la pantalla.

---

## Estado en que quedó el sandbox

`prm_ensayo` quedó en los tres repositorios: `prm-sbx-interno` y `sbx-cliente-privado` con
`b4a3e5d8`, y `sbx-cliente-publico` con `419a833e` (el del parche de la fase 7). Es el
residuo del ensayo y se limpia cuando se pida.
