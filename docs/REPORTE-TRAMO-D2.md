# Reporte del tramo D2 — los tres asuntos, completos

**Fecha:** 5 y 6 de septiembre de 2026 · **Contra:** el sandbox `prm-sandbox`, con la App
de escritura cargada · **Estado de la suite al cierre:** 374 tests, 0 fallos, 0 errores.

Tres asuntos, en el orden en que conviene leerlos:

1. **El ensayo de D2**, fase por fase, con sus dos hallazgos abiertos.
2. **Las dos guardas del retiro de módulos**, y por qué son dos y no una.
3. **La bifurcación de la cadena de la bitácora**: cómo se bifurcaba, qué se perdía, cómo
   quedó y con qué prueba.

---

# 1 · El ensayo de D2

La primera vez que el embudo borra contenido de un repositorio. Siete fases, en el orden
en que se diseñaron, y con la frontera que se había puesto: nada de borrados hasta que la
sesión grande de validación estuviera pasada.

## Fase 1 · Sembrar

Se creó un módulo de ensayo, `addons/prm_ensayo` —cuatro archivos—, en dos repositorios de
cliente del sandbox, con **los mismos bytes**.

```
SEMBRADO prm-sandbox/sbx-cliente-publico   commit=f488e96d  arbol=b4a3e5d8237086fd229843640e4b2f205a17d86a
SEMBRADO prm-sandbox/sbx-cliente-privado   commit=a4de03c1  arbol=b4a3e5d8237086fd229843640e4b2f205a17d86a
```

**El mismo identificador de directorio en dos repositorios distintos.** Es la propiedad
sobre la que se apoya todo D2: git nombra cada directorio por su contenido, así que dos
copias idénticas tienen el mismo identificador en cualquier repositorio, y comparar dos
textos de 40 caracteres reemplaza a bajar y comparar los archivos. Quedó confirmada contra
GitHub real, no contra una simulación.

## Fase 2 · El plan, leído antes de aplicar nada

Un plan con tres operaciones: copiar el módulo al repositorio común, y dos borrados que
**dependen** de que esa copia haya quedado verificada.

```
[10] Se copia el módulo «prm_ensayo» a prm-sandbox/prm-sbx-interno, rama 17.0, desde
     prm-sandbox/sbx-cliente-publico@17.0. Es un solo commit: o entra completo o no entra.
     saca algo=No   irreversible=No   se puede aplicar=Sí   depende de=—
[20] De prm-sandbox/sbx-cliente-publico, rama 17.0, SE BORRA el módulo «prm_ensayo»
     (addons/prm_ensayo). Las instancias que lo tomen de este repositorio dejan de
     encontrarlo: eso es addons_path, y Repo Manager no lo cambia.
     saca algo=Sí   irreversible=No   se puede aplicar=Sí   depende de=[la copia]
[21] …ídem sbx-cliente-privado…
```

La aprobación, con el rol de líder técnico:

| intento | resultado |
|---|---|
| sin confirmar ninguna destructiva | se niega, y **enumera las dos** por su descripción |
| confirmando una sola | se niega, y nombra **la que falta** |
| confirmando las dos | aprobado, con la huella intacta |

## Fases 3 y 4 · Copiar, verificar, y matar el proceso en el medio

Se aplicó el plan y se mató el proceso **entre la copia y el primer borrado**, con una
señal que no deja correr ninguna limpieza ni confirmar nada — lo más parecido a que el
servidor se caiga de golpe.

Desde un proceso nuevo, las tres fuentes por separado:

```
LA BASE      el plan sigue «aprobado» y las tres operaciones, «pendientes»
LA BITÁCORA  2 entradas «escritura emitida» sobrevivieron, y están selladas
GITHUB       prm-sbx-interno      prm_ensayo: b4a3e5d8…   ← la copia SÍ entró
             sbx-cliente-publico  prm_ensayo: b4a3e5d8…
             sbx-cliente-privado  prm_ensayo: b4a3e5d8…
LA CADENA    íntegra
```

Tres cosas, y las tres importan:

1. **No se borró nada.** El peor caso que este diseño permite es que el módulo quede en dos
   lados —duplicación molesta y arreglable—; el que no permite es que no quede en ninguno.
   Salió el caso permitido.
2. **La base no sabe nada, y es correcto**: la transacción murió sin confirmar. Lo único
   que quedó del intento es lo que se escribió por fuera de esa transacción, a propósito.
3. **La cadena de la bitácora quedó en verde** con entradas escritas por dos conexiones
   distintas. Es la verificación en dos procesos del arreglo del asunto 3 de este reporte.

## Fase 5 · Completar

Se volvió a aplicar el plan.

```
PLAN aplicado · las tres operaciones aplicadas
GITHUB  prm-sbx-interno      prm_ensayo: b4a3e5d8…
        sbx-cliente-publico  NO ESTÁ
        sbx-cliente-privado  NO ESTÁ
```

La promoción completa: el módulo vive en el repositorio común y salió de los dos clientes.

## Fase 6 · Revertir

Cada operación había guardado su punto de retorno antes de escribir:

```
[10] copia    prm-sbx-interno       volver al commit b7282e38
[20] borrado  sbx-cliente-publico   volver al commit f488e96d
[21] borrado  sbx-cliente-privado   volver al commit a4de03c1
```

```
PLAN revertido · las tres operaciones revertidas
GITHUB  sbx-cliente-publico  prm_ensayo volvió
        sbx-cliente-privado  prm_ensayo volvió
        prm-sbx-interno      prm_ensayo SE QUEDÓ   ← ver el hallazgo 1
```

Los borrados se deshicieron y el módulo volvió a los dos clientes, byte a byte.

## Fase 7 · El caso feo

Con el plan **ya aprobado**, alguien empuja un parche urgente al módulo en el origen, por
fuera de Repo Manager:

```
el módulo en el origen pasó de b4a3e5d8… a 419a833e…

PLAN fallido
  copia   : falló — «la escritura respondió bien pero la relectura no lo confirma: la copia
            NO quedó idéntica — esperado b4a3e5d8…, obtenido 419a833e…»
  borrado : no ejecutada por dependencia
GITHUB  sbx-cliente-publico  prm_ensayo: 419a833e…   ← el parche sigue ahí
```

**El trabajo de otro no se perdió.** La copia se negó a darse por buena porque lo que copió
no era lo que se aprobó, y el borrado ni se intentó: quedó en «no ejecutada por
dependencia», que no es lo mismo que «fallida» y por eso tiene un nombre propio — marcarla
como fallida mandaría a alguien a buscar un error de GitHub que no existe.

Y el cierre de la corrección de la semana: esa copia **falló después de escribir**, así que
el embudo tiene que ofrecer deshacerla.

```
la copia: estado «fallida» · ¿tiene efecto en GitHub? SÍ · ¿hay constancia de que escribió? SÍ
tras revertir: revertida — el destino volvió a b4a3e5d8…
```

---

## Los dos hallazgos del ensayo

### Hallazgo 1 · Una escritura huérfana de una caída se cuela en el punto de retorno

**Qué pasó.** Las corridas que se mataron en la fase 4 dejaron el módulo copiado en el
destino. Para la base, esas copias nunca ocurrieron: la transacción murió. Cuando la fase 5
volvió a aplicar, la operación leyó su estado previo —y ese estado previo **ya incluía su
propia escritura huérfana**—. Por eso, al revertir en la fase 6, el destino volvió a un
estado que contiene el módulo.

**Por qué importa.** Ningún paso mintió. El rollback fue fiel a lo que se había registrado,
y aun así el resultado final tiene un objeto en GitHub que **ningún plan aplicado explica**.
La constancia de que la escritura salió existe, está en la bitácora y está sellada; lo que
falta es que alguien la concilie: hoy la mira sólo la operación que la escribió, y sólo
para decidir si se puede revertir.

**Qué haría falta.** Antes de aplicar, una operación tendría que preguntarse si ya tiene
escrituras emitidas sin desenlace registrado. Si las tiene, negarse y pedir conciliación
—verificar qué hay allá afuera y decidir si eso cuenta como aplicado o se revierte— en vez
de arrancar de nuevo y absorber lo huérfano como si fuera el paisaje.

**Estado: abierto.** Es el primer punto del próximo tramo de D2.

### Hallazgo 2 · La pantalla del plan no cuenta que hubo una caída

Después de matar el apply, el plan se ve idéntico a antes del intento: aprobado, todo
pendiente. Nada indica que hubo una ejecución y que algo salió. Quien mire sólo Odoo no
tiene manera de saberlo; la única señal está en la bitácora y hay que ir a buscarla.

Es la misma conciliación del hallazgo 1, del lado de la pantalla. **Estado: abierto.**

---

# 2 · Las dos guardas del retiro de módulos

El retiro —sacar un módulo de un repositorio— es la única operación del catálogo que borra
código de un repositorio de cliente. Tiene **dos comprobaciones distintas**, y que sean dos
no es redundancia: responden preguntas diferentes.

## Guarda 1 · La barrera: «¿la copia salió bien?»

Es la dependencia entre operaciones. El borrado **declara** que depende de la copia, y si
la copia no quedó aplicada, el borrado **no se intenta**: queda en «no ejecutada por
dependencia».

Por qué existe: el motor de escritura, hasta ese momento, **no se detenía ante un fallo**, y
estaba bien que no lo hiciera —proteger una rama y bajarle el permiso a alguien son
independientes, y que una falle no debe frenar la otra—. La promoción rompe ese supuesto:
«copiar» y «borrar» son la misma operación partida en dos.

**El peor caso que este diseño permite es duplicación benigna. El que no permite es que el
módulo no quede en ningún lado.**

## Guarda 2 · La propia: «¿lo que voy a borrar es lo que se copió?»

La barrera habla de la copia. Esta pregunta es otra: entre que se armó el plan y se aplica,
alguien pudo tocar el módulo **en el origen**. Ese cambio no está en ninguna copia, y
borrarlo lo perdería para siempre.

El plan declara el identificador del directorio que se copió. Si al momento de borrar el
directorio ya no tiene ese identificador, la operación **se niega** y pide volver a
promover. Es la guarda que actuó en la fase 7 del ensayo, con el parche urgente de otro.

## Lo demás del diseño, en una línea cada uno

- **Un solo commit.** Se nombran los archivos del módulo para borrar sobre el árbol actual y
  se hace un commit; la API alternativa habría sido un commit por archivo, y una
  interrupción dejaría un módulo a la mitad.
- **Sólo lo que cuelga del módulo.** Lo que no se nombra se conserva. Nombrar de más
  borraría el repositorio.
- **Sin forzar la rama.** Si alguien empujó entre que leímos y escribimos, GitHub rechaza.
  Perder nuestro commit es molesto; pisar el de otro es inaceptable.
- **Se verifica releyendo**: el directorio tiene que haber dejado de existir. No se confía
  en que la API hizo lo que dijo.
- **Se revierte por avance rápido.** Se guarda el commit donde estaba la rama; si alguien
  empujó después, revertir pisaría su trabajo, así que el módulo **se niega y explica** de
  qué commit se restaura a mano.
- **La frase avisa de lo que este módulo NO hace:** las instancias que tomaban el módulo de
  ese repositorio necesitan un cambio de `addons_path`. Un módulo que borra código sin
  decirlo rompe producciones ajenas en silencio.
- **No está en el catálogo de remediación automática:** un retiro se arma a mano, en un
  plan, y pasa por confirmación individual como toda destructiva.

## Con qué está probado

Once pruebas sobre el retiro, con un GitHub simulado que sabe de árboles, commits y
referencias —y que **borra de verdad**, porque uno que devolviera siempre el árbol original
diría «no se borró» sobre una simulación que nunca borra—:

```
es destructivo y es reversible          la frase avisa del addons_path
aprobar sin confirmarlo se niega         saca el módulo en UN commit y sin forzar
borra SÓLO lo que cuelga del módulo      la verificación relee y el módulo YA NO ESTÁ
NO borra si el módulo cambió             NO da por hecho un borrado sobre una ruta que no existe
revertir devuelve la rama                revertir se NIEGA si alguien empujó encima
si la copia falla, el BORRADO no se intenta
```

Y cuatro pruebas de sabotaje —se rompe el código a propósito y se comprueba que alguna
prueba lo detecte—, las cuatro detectadas:

| sabotaje | prueba que lo detectó |
|---|---|
| se saca la comparación con lo que se copió | «NO borra si el módulo cambió» |
| se fuerza la rama al escribir | «saca el módulo en UN commit y sin forzar» |
| la reversión deja de mirar si la rama se movió | «revertir se NIEGA si alguien empujó encima» |
| el borrado nombra todo el árbol, no sólo el módulo | «borra SÓLO lo que cuelga del módulo» |

---

# 3 · La bifurcación de la cadena de la bitácora

## Qué es la cadena, en una línea

Cada entrada de la bitácora guarda el identificador de la anterior. Nadie puede impedir que
alguien edite la base de datos por fuera de la aplicación, pero con la cadena **eso se
detecta**: tocar una entrada rompe todas las que siguen, y el diagnóstico lo dice.

## Cómo se bifurcaba

El 4 de septiembre se agregó una constancia que se escribe **apenas la escritura sale hacia
GitHub y antes de verificarla**, en una conexión aparte, para que sobreviva a una caída del
proceso. Eso es correcto y es lo que salvó el ensayo de la fase 4.

Lo que no se vio: **el sellado suponía que había un solo escritor.** La conexión aparte
confirma su entrada de inmediato, mientras la transacción principal mantiene una foto de la
base **anterior a esa confirmación**, en la que esa entrada no existe. Las dos sellan contra
la misma punta.

Así quedó en la base, después de la corrida de validación del 5 de septiembre:

```
 id   | tipo              | eslabón previo | identificador
------+-------------------+----------------+---------------
 2748 | escritura emitida | c063857a       | e6564664        ← conexión aparte
 2749 | escritura aplicada| c063857a       | 23514533        ← transacción principal
 2750 | escritura emitida | e6564664       | 36610f1d
 2751 | escritura aplicada| 23514533       | bc2e884c
 2752 | escritura emitida | 36610f1d       | 2f31b5a4
 2753 | escritura aplicada| bc2e884c       | c220b7c9
```

**2748 y 2749 apuntan al mismo eslabón previo.** A partir de ahí no hay una cadena: hay dos
corriendo en paralelo. Tres bifurcaciones en una sola corrida.

## Qué se perdía

**No se perdió ninguna entrada, y ninguna se alteró.** Todo lo que la bitácora registró
sigue ahí, íntegro y legible, con su estado previo — el rollback nunca estuvo en riesgo.

Lo que se perdió fue **la capacidad de demostrar eso**. Una cadena bifurcada no verifica, y
el diagnóstico pasó a decir «ROTA», que es lo que tiene que decir. El problema del falso
positivo no es la molestia: es que **una alarma que suena sin motivo enseña a ignorarla**, y
el día que suene por una edición real nadie la va a mirar. Eso era lo que estaba en juego.

## Cómo quedó

**El sello se pone después de confirmar la transacción**, que es el único momento en que
existe un orden total sobre el que todos los escritores coinciden, y lo pone un **sellador
único** serializado con un candado de la base. Tres consecuencias, todas buscadas:

- Sella **todas** las entradas pendientes, no sólo las suyas: si un proceso muere entre
  confirmar y sellar, el siguiente las recoge y no queda un agujero permanente.
- La cadena se recorre **por orden de sellado**, no por número de entrada. Los números se
  entregan al insertar y los sellos se ponen al confirmar; dos transacciones que terminan al
  revés de como empezaron habrían dado «rota» sin que nadie tocara nada.
- Una entrada **sin sellar todavía no es una rotura**: es una entrada que confirmó y aún no
  pasó por el sellador. Se cuenta aparte y se dice con esas palabras.

### Qué se hizo con el tramo ya bifurcado

**No se recalcularon los sellos viejos.** Reescribirlos habría hecho que el diagnóstico
dijera «íntegra» sobre un pasado reescrito, que es fabricar exactamente la confianza que la
cadena existe para no fabricar — y es la misma decisión que se tomó al arrancar la cadena,
cuando se resolvió no sembrarla sobre las entradas anteriores.

En su lugar se **cerró el tramo y se abrió uno nuevo**, con la causa escrita adentro de la
entrada de corte y sellada con ella (entrada 3335):

> «El tramo anterior quedó bifurcado por un defecto del propio módulo, no por una edición
> externa: desde el 4-sep-2026 la constancia de escritura se escribe en una conexión aparte
> —para que sobreviva a una caída— y sellaba contra la misma punta que la transacción
> principal, que no podía verla. Tres bifurcaciones el 5-sep-2026 (entradas 2748/2749,
> 2750/2751, 2752/2753). Los sellos viejos NO se recalcularon. Desde acá el sellado es único
> y serializado, después del commit.»

La verificación arranca en el último corte y **cuenta los tramos cerrados**, así que un
corte nuevo es visible y tiene que serlo. Y cerrar un tramo **no es automático**: exige un
motivo escrito. Si el módulo cerrara el tramo solo cada vez que encuentra la cadena rota,
cualquier manipulación quedaría tapada por el siguiente arranque — el diagnóstico diría
«íntegra» sobre una base editada, que es peor que no tener cadena.

Estado hoy: **íntegra desde el corte, con un tramo anterior cerrado que declara por qué.**

## Con qué está probado

Diecisiete pruebas sobre la cadena. Cada una trabaja **sobre su propio tramo** —lo abre al
empezar—, porque una prueba que verificara «la cadena» estaría verificando también lo que
haya en la base de cada instalación, y se pondría roja por usos legítimos.

Las que cubren este arreglo en particular:

- **una entrada recién creada NO está sellada todavía** — el sello llega al confirmar, y eso
  es el arreglo, no un defecto;
- **al sellar queda con su sello y su posición**;
- **cada entrada guarda el sello de la anterior**, y su posición es la siguiente;
- **varias entradas pendientes se sellan en UNA sola línea** — el invariante que la
  corrección tiene que sostener;
- **un UPDATE directo en la base ROMPE la cadena** y **la cadena detecta una entrada
  BORRADA** — las dos que dan sentido a todo lo demás;
- **el sello cubre el estado previo que usa el rollback** — si alguien lo cambiara, una
  reversión devolvería el sistema a un estado inventado;
- **cerrar un tramo EXIGE un motivo**, y **el motivo queda sellado en la entrada**;
- **la verificación arranca en el último corte y cuenta los tramos**;
- **el diagnóstico de Ajustes acepta todos los estados que el modelo puede devolver** — el
  estado «sellado pendiente» es nuevo, y la pantalla tenía tres opciones; asignar una que no
  está habría hecho reventar el diagnóstico.

### Lo que estas pruebas NO prueban, y hay que decirlo

El escenario real necesita **dos conexiones con fotos distintas de la base**, y eso no se
puede montar dentro de una transacción de prueba: no hay confirmación y hay una sola
conexión. Las pruebas verifican el invariante —que todo termine en una sola línea— y no el
escenario.

**El escenario se verificó contra el sandbox, en dos procesos, y es la fase 4 del ensayo de
este mismo reporte:** un apply real emite la constancia por la conexión aparte y la entrada
de aplicada por la principal; después de matar el proceso en el medio, la cadena verificó en
verde.

---

# Qué queda abierto

| # | asunto | dónde entra |
|---|---|---|
| 1 | Conciliar las escrituras huérfanas de una caída | primer punto del próximo tramo de D2 |
| 2 | Que la pantalla del plan cuente que hubo una caída | el mismo tramo, del lado visual |
| 3 | La variante oscura del sistema de diseño | pedido al diseño; mientras tanto las pantallas quedan claras |

## Estado en que quedó el sandbox

El módulo de ensayo `prm_ensayo` quedó en los tres repositorios: `prm-sbx-interno` y
`sbx-cliente-privado` con el contenido original, y `sbx-cliente-publico` con el del parche
de la fase 7. Es el residuo del ensayo y se limpia cuando se pida.
