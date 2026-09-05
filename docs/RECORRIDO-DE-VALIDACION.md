# Recorrido de validación del Bloque A

> Documento de trabajo, no guía de usuario. La guía dice **cómo se usa**; esto dice **qué
> hay que comprobar y qué sería señal de problema**. Cuando este recorrido salga completo,
> el criterio de salida del flujo existente queda cerrado.

**Para:** Daryl · **Con:** `desarrollo@primate.uy` · **Contra:** `prm-sandbox`
**Escrito:** 4 de septiembre de 2026 · **Actualizado:** 5 de septiembre
**Cubre:** A4 completo, la deuda visual de A5+A6+A8, y lo que trajo el entregable de
diseño: la cadena de la bitácora y los cuatro tipos de entrada.

> **Qué hay que repetir de la corrida del 5 de septiembre.** La Parte 1 entera, con una
> diferencia: la remediación va ahora por los **hallazgos de permisos**, que son los
> planificables de verdad. Los de rama sin protección quedaron fuera —el paso 1.3 explica
> por qué y comprueba que lo diga—. Además, el **Paso 0** tiene que verse sin el botón
> *Habilitar escritura*. Las Partes 2 y 3 no cambiaron: ya salieron bien.

Cada paso tiene tres partes: **hago**, **tengo que ver**, **sería problema**. Si algo de
la tercera columna aparece, anotalo y seguí — no hace falta cortar el recorrido salvo que
diga lo contrario.

---

## Paso 0 — Prerrequisitos (10 minutos, una sola vez)

**Sin esto, el recorrido llega hasta «aprobar» y no puede aplicar nada.**

La conexión `GitHub — prm-sandbox` **no tiene cargadas las credenciales de escritura**.
Comprobado el 4-sep-2026: `write_app_id` vacío. Es a propósito —quedaron fuera al cerrar
F2— pero el tramo de apply y rollback las necesita.

**Hago:** *Repo Manager → Configuración → Conexiones → GitHub — prm-sandbox*. En el bloque
**App de escritura**: App ID `4808079`, Installation ID `158565221`, y cargar el archivo
`prm-sandbox.2026-09-02.private-key.pem` de la carpeta PRM en *Private key de escritura*.
Guardar.

**Tengo que ver:** *Clave de escritura cargada* tildado. El campo del PEM vuelve a estar
vacío — no se muestra nunca más.

**Tampoco tiene que aparecer** el botón **Habilitar escritura**: esa habilitación es sólo
para conexiones de **producción**, y ésta es de sandbox. En la corrida anterior aparecía
—la condición miraba las credenciales y se olvidaba del entorno—; está arreglado y hay un
test que lee la vista para que no vuelva.

**Sería problema:** que aparezca igual.

> **Verificación de que el módulo también levantó:** *Auditorías* tiene que mostrar
> corridas anteriores, y la última en *Terminada*.

---

## Parte 1 · El camino completo, de punta a punta

### 1.1 Una auditoría fresca

**Hago:** *Auditorías → Nuevo*, conexión `GitHub — prm-sandbox`, guardar, **Auditar**.

**Tengo que ver:** la barra llenándose sola, *N de 6*, «Ahora: …» cambiando de
repositorio, el cronómetro corriendo. **Debería terminar en unos 25–30 segundos.**

**Sería problema:**
- Que tarde más de 70 segundos. Antes de A10 tardaba eso, con un solo hilo; si volvió a
  ese número, la corrida está reintentando y hay contención otra vez.
- Que quede en *En curso* con todo terminado. Es el defecto que A10 arregló con el job de
  cierre; si vuelve, es que el job de cierre no corrió.
- Que la pantalla no se mueva sola.

### 1.2 Remediar un hallazgo

> **Cambió respecto de la corrida anterior, y por qué.** Antes este paso remediaba una
> **rama sin protección**, y eso salió mal: el hallazgo trae la *identificación* del
> objeto (`repositorio`, `rama`) y no una *configuración* de protección, así que la
> operación viajaba a GitHub con un cuerpo que no configuraba nada. GitHub la aceptó,
> ignoró lo que no entendía y dejó puesta una protección con todo en default. Se limpió y
> se verificó por relectura. Ahora las ramas sin protección **no se remedian desde el
> hallazgo**: su configuración sale de la plantilla de política y llega con B1. Los
> planificables de verdad son los de **permisos**, cuyo payload sí dice qué hacer.

**Hago:** *Hallazgos*, buscar uno de tipo **«Permiso de administrador excedido»** (hay
cuatro). Abrirlo y apretar **Remediar esto**.

**Tengo que ver:** te lleva a un plan **en borrador** llamado *Remediaciones de GitHub —
prm-sandbox*, con **una** operación, y su frase en castellano diciendo qué se pierde:
«…SE LE QUITA el permiso directo. Si además está en un team con acceso, va a conservar el
del team». La columna *Saca algo* **tildada**, la fila en rojo.

**Sería problema:**
- Que la frase no esté, o que muestre JSON.
- Que el plan salga en cualquier estado que no sea borrador.
- Que *Saca algo* no esté tildada: sin eso, la aprobación no pediría confirmarla.
- **Que algo haya cambiado en GitHub.** Este botón no escribe nada. Si mirás el repo en
  GitHub y el permiso ya cambió, eso es grave y hay que cortar.

### 1.3 Lo que NO se puede remediar lo dice, y dice por qué

**Hago:** en *Hallazgos*, abrí uno de **«Rama sin protección»** en `sbx-localizacion` (hay
tres: `17.0`, `17.0.Staging`, `19.0`) y apretá **Remediar esto**.

**Tengo que ver:** se niega, con un mensaje que explica que la configuración de protección
sale de la **plantilla de política** y llega con **B1**, y que mientras tanto se arma a
mano desde el asistente del plan.

**Sería problema:** que lo arme igual. O que se niegue **sin decir por qué**: un «no se
puede» mudo manda a buscar un botón que no existe.

### 1.4 El segundo clic no duplica

**Hago:** volvé al hallazgo de permisos de 1.2 y apretá **Remediar esto** otra vez. Y si
podés, abrí el mismo hallazgo en dos pestañas y apretá en las dos.

**Tengo que ver:** el botón ahora dice **«Ver el plan donde ya está»**, y arriba un aviso
*«Ya está en el plan …»*. Te lleva al mismo plan. **Sigue habiendo una sola operación.**

**Sería problema:** dos operaciones iguales en el plan. Hay dos capas para impedirlo —la
comprobación y un índice en la base—; si aparecen dos, fallaron las dos.

### 1.5 Sumar por lote, con dos que no aplican

**Hago:** *Hallazgos*. Seleccioná con los tildes de la izquierda: **dos hallazgos más de
«Permiso de administrador excedido»**, **uno de «Rama sin protección»** y **uno de «Cuenta
sin persona asociada»** — los dos últimos a propósito, porque no se remedian con un plan.
Menú de acciones (el engranaje) → **Remediar: armar plan con estos**.

**Tengo que ver:** te lleva al **mismo** plan en borrador, que ahora tiene **tres**
operaciones: la de 1.2 más las dos de permisos. Las otras dos no están, y el lote no se
cayó por eso.

**Sería problema:**
- Que se abra un plan nuevo en vez de acumular en el borrador.
- Que el lote falle entero por los hallazgos que no aplicaban.
- Que la de «rama sin protección» o la de «cuenta sin persona» sí hayan entrado.

### 1.6 Leer el plan antes de aprobarlo

**Hago:** quedate en el plan y leé la lista de operaciones.

**Tengo que ver:**
- Las tres frases en castellano, legibles sin abrir nada.
- **Las tres en rojo**, con *Saca algo* tildado —todas sacan acceso— y cada una nombrando
  a su persona y su repositorio.
- El payload JSON escondido (se puede prender desde el botón de columnas).

**Sería problema:** que una operación que saca acceso no esté marcada, o que su frase diga
sólo «quitar permiso» sin explicar la consecuencia.

### 1.7 Aprobar, con confirmación individual

**Hago:** botón **Aprobar**. Se abre el asistente. **Primero probá apretar *Aprobar* sin
tildar nada.**

**Tengo que ver:** se niega, y el mensaje **enumera las tres operaciones destructivas por
su descripción**. Después tildá **una sola** y volvé a intentar: se sigue negando, ahora
por dos. Tildá las que faltan y aprobá.

**Tengo que ver al cerrar:** el plan en *Aprobado*, con *Intacto desde la aprobación*
tildado, y un mensaje en el chatter que dice cuántas operaciones y cuántas destructivas se
confirmaron una por una.

**Sería problema:** que apruebe sin tildar nada. Es el control central de F2 y si falla,
**cortá el recorrido y avisame**.

### 1.8 La huella congela lo que leíste

**Hago:** con el plan ya aprobado, apretá **Volver a borrador** y después cambiá algo — por
ejemplo, borrá una de las tres operaciones. Volvé a mirar el estado.

**Tengo que ver:** el plan en *Borrador*, la aprobación borrada, y *Intacto desde la
aprobación* **sin** tildar. Volvé a aprobarlo (con sus tildes) para seguir.

**Sería problema:** que siga diciendo *Aprobado* después de cambiarle una operación.

### 1.9 Aplicar, mirando la barra

**Hago:** botón **Aplicar**.

**Tengo que ver:** la **misma barra** que en la auditoría, ahora sobre el plan: se llena
operación por operación, dice cuál se está haciendo, y el cronómetro corre. Al terminar,
el plan en *Aplicado* y cada operación en *Aplicada*.

**Sería problema:**
- Que la barra no se mueva y todo salte al final de golpe.
- Que alguna operación quede en *Fallida* — leé el error y anotalo.
- *Bloqueada* **no** es un fallo: es un techo del plan de GitHub, y está bien que aparezca.

**Comprobación fuera de Odoo:** entrá a
`github.com/prm-sandbox/<el repo de una de las operaciones>/settings/access` y mirá que la
persona ya **no** tenga el permiso directo de admin.

### 1.10 La bitácora, con antes y después

**Hago:** *Bitácora*.

**Tengo que ver:** una entrada por operación aplicada, con **el estado previo guardado**.
Abrí una de las de permisos: tiene que decir qué permiso tenía esa persona **antes**.

**Sería problema:** entradas sin estado previo. Sin eso el rollback no tiene a qué volver.

### 1.11 Revertir

**Hago:** volvé al plan y usá **Revertir** sobre **una** operación de permisos — la de
`primateuy`, no la tuya, para no sacarte el acceso a vos mismo.

**Tengo que ver:** la operación en *Revertida*, una entrada nueva en la bitácora, y en
GitHub el permiso **de vuelta como estaba** — no borrado, sino en el valor previo.

**Sería problema:** que el permiso quede en algo distinto del original, o que el rollback
pida confirmaciones que la operación original no pidió.

### 1.12 Una operación que falla DESPUÉS de escribir también se revierte *(nuevo)*

No hay forma de provocarlo a mano sin romper algo, así que **esto es sólo para leer**: es
el agujero que el incidente de más arriba dejó a la vista y que ya está tapado.

Cuando GitHub acepta la escritura pero la relectura no la confirma, la operación queda en
*Fallida* — y sin embargo allá afuera hay un cambio. Antes, la admisibilidad de revertir
salía del **estado** de la operación, así que *Fallida* significaba «no hay nada que
deshacer» y el efecto quedaba afuera del embudo: hubo que sacarlo a mano en GitHub, que es
justamente lo que el embudo existe para evitar.

Ahora sale de los **hechos**: apenas la escritura sale, y **antes** de verificarla, se
deja constancia en la bitácora en su propia conexión —para que sobreviva a una caída— con
el estado previo adentro. **Si ves una operación *Fallida* que tiene el botón *Revertir*
activo, está bien: quiere decir que escribió.** El caso contrario también está probado:
una que falla antes de escribir no ofrece revertir nada.

---

## Parte 2 · La deuda de A5 + A6 + A8

Cuatro puntos, ninguno depende de la Parte 1.

### 2.1 Ajustes abre y diagnostica

**Hago:** *Repo Manager → Configuración → Ajustes*.

**Tengo que ver:** la pantalla **abre**. Tres bloques, y en *Estado de la instancia*:
**Procesamiento en segundo plano: Funcionando** en verde, y *Clave de cifrado cargada*
tildada.

**Sería problema:** **un «Access Error»**. Es exactamente el defecto que se corrigió
rehaciendo la pantalla sin `res.config.settings`; si vuelve, volvió el problema de fondo.
También sería problema que la clave apareciera escrita en algún lado: no se muestra nunca.

### 2.2 Un cambio de política queda en la bitácora

**Hago:** *Configuración → Plantillas de política → «Cliente estándar»*. Cambiá
*Aprobaciones requeridas* de 1 a 2 y guardá. Después andá a *Bitácora*.

**Tengo que ver:** una entrada nueva de tipo **Cambio de política**, con **tu nombre**, y
en su detalle el campo, el valor anterior y el nuevo — «Aprobaciones requeridas: 1 → 2».
En la plantilla, antes de tocar nada, tenía que estar el aviso de que cambiarla no toca
ningún repositorio pero cambia qué cuenta como incumplimiento.

**Sería problema:** que el cambio no aparezca en la bitácora. El chatter no alcanza: es
editable y se va con el registro.

*(Dejalo en 2 o volvelo a 1, da igual: queda registrado en los dos sentidos.)*

### 2.3 El asistente de personas propone sin decidir

**Hago:** *Personas*. Filtro **Sin persona asociada** (hay 18). Abrí una y apretá
**¿Quién es?**.

**Tengo que ver:** el asistente con el aviso de que las coincidencias son **pistas, no
pruebas**, la lista de candidatos si los hay, y el campo *Es esta persona* **vacío** si hay
más de un candidato. Probá **Vincular** sin elegir: se niega. Elegí y confirmá: el aviso
amarillo de la ficha **desaparece**.

**Sería problema:** que el empleado venga elegido de antemano cuando hay varios candidatos.
Un vínculo equivocado pone los permisos de una persona a nombre de otra.

### 2.4 La cadena de la bitácora *(nuevo)*

**Hago:** *Configuración → Ajustes*, bloque **Estado de la instancia**.

**Tengo que ver:** **Cadena de la bitácora: Íntegra** en verde, y debajo *«Íntegra desde el
… · N entradas verificadas»*. La fecha es la del día en que la cadena arrancó, no la de la
primera entrada de la bitácora — y eso es a propósito.

**Sería problema:** que diga **ROTA**. Significa que alguien escribió en la base por fuera
de Odoo, y no es un falso positivo: la cadena sólo se rompe si el contenido de una entrada
cambió o si falta una del medio. **Si aparece, avisame y no sigas** — con la bitácora en
duda, todo lo demás que el módulo afirma queda en duda.

**Para entender qué garantiza:** abrí una entrada cualquiera de la *Bitácora* y mirá el
bloque **Sello de integridad**. Cada entrada guarda el hash de la anterior. Buscá la
entrada más vieja de todas, la de *«Inicio de la cadena de integridad»*: dice cuántas
entradas quedaron **afuera** de la cadena. No se sembró hacia atrás a propósito — una
cadena que «verificara» un pasado que nadie encadenó estaría fabricando confianza.

### 2.5 La leyenda de cuatro tipos *(nuevo)*

**Hago:** *Ver y entender → Bitácora*. Abrí el desplegable de filtros.

**Tengo que ver:** cuatro filtros con el texto del diseño — *Escritura verificada, se puede
revertir* · *Irreversible, o falló* · *Lectura (auditoría), no cambia nada* · *Cambio
detectado fuera de la app*. Probá cada uno: la columna **Tipo** de la lista tiene que
coincidir con el filtro, y el chip lleva **texto**, no sólo color.

Agrupá por **Tipo de entrada** y mirá el reparto. Hoy casi todo va a caer en *Lectura* y
*Escritura verificada*; **Cambio detectado fuera de la app** va a estar vacío, y eso es
correcto: ese tipo se llena con el drift de política, que es B4.

**Sería problema:** un chip que sólo se distinga por color, o una entrada de escritura
aplicada que aparezca como lectura.

### 2.6 El tipeo del nombre — POR QUÉ NO SE PUEDE VER TODAVÍA

**No hay paso que hacer acá, y conviene decir por qué en vez de dejarlo sin mencionar.**

El patrón está construido: una operación irreversible exige escribir el nombre del objeto
en un campo mono con borde punteado, y no entra en el «aprobar todas las reversibles».
Pero **hoy ninguna operación es irreversible**, y no por casualidad: ser irreversible se
deriva de si el manejador declara cómo revertir, y los ocho tipos implementados lo
declaran. Hay un test que lo comprueba y que va a fallar el día que eso cambie.

**No hay forma de provocar una irreversible real en el sandbox sin tocar código**, y tocar
código para una demo sería mostrarte una pantalla que no corresponde a lo que el sistema
hace. Lo que se puede ver hoy, y vale la pena:

- Armá un plan y agregale una operación de tipo **Quitar protección de rama** —desde la
  lista de operaciones del plan, escribiendo el payload a mano, porque el asistente ya no
  la ofrece—. La frase va a decir **«ESTE TIPO TODAVÍA NO ESTÁ IMPLEMENTADO»** y al
  aprobar el plan se va a negar. Es el otro lado de la misma moneda: *no implementado* no
  es *irreversible*, y el módulo no los confunde.

**Lo irreversible de verdad llega con «borrar una rama», en E3.2**, y con la promoción de
módulos de D2, que borra contenido. Ese día este paso deja de ser un párrafo y pasa a ser
un recorrido.

### 2.7 Las reglas de clasificación se entienden mirándolas

**Hago:** *Configuración → Reglas de clasificación*.

**Tengo que ver:** la lista ordenable por arrastre, cada regla con su *Por qué*, y —si
alguna vez la lista queda vacía— el texto que explica que **gana la primera que matchea** y
que **no hay regla comodín a propósito**.

**Prueba de lectura, que es el punto:** mirando esa pantalla, ¿podés explicar por qué
`sbx-cliente-publico` no se clasificó solo? Si la respuesta es no, la pantalla falló.

**Sería problema:** que el orden no se pueda cambiar, o que no se vea que el orden importa.

---

## Parte 3 · Armar una operación desde cero (A4.3)

**Hago:** creá un plan nuevo —*Planes de escritura → Nuevo*, conexión `prm-sandbox`,
guardar— y apretá **Agregar operación**. Elegí *Aplicar protección de rama*, repositorio
`sbx-cliente-publico`, rama `17.0.Staging`, y tildá: exigir pull request con **2**
aprobaciones, bloquear force-push, bloquear borrado.

**Tengo que ver:** abajo, en *Cómo va a quedar escrito*, la frase armada. **Copiala
mentalmente.** Apretá *Agregar al plan*.

**Y esto es lo que se valida:** la frase de la columna *Qué va a pasar* en el plan tiene
que ser **exactamente la misma** que mostraba la vista previa.

**Sería problema:** que difieran, aunque sea en una palabra. La que se aprueba es la del
plan; si el asistente dice otra cosa, alguien va a aprobar algo distinto de lo que leyó.

**Probá también:** elegí *Crear ruleset* en el desplegable. **No está**, y es a propósito:
un ruleset se define por las reglas de una plantilla y tenerlo también acá haría que dos
lugares decidan lo mismo. Es B1.

---

## Al terminar

Con la Parte 1 completa, el criterio de salida del flujo existente queda cumplido:

    espejo → auditoría → hallazgos → informe → armar plan → aprobar → apply
           → bitácora → rollback

todo desde la aplicación, sin consola.

**Limpieza opcional:** el plan aplicado y sus cambios quedan en el sandbox. Si querés
dejarlo como estaba, revertí las operaciones restantes desde el plan — que además es una
segunda pasada por el rollback.

**Lo que este recorrido NO cubre**, y no es olvido: el informe en PDF (funciona desde F1 y
no cambió), y todo lo que todavía no existe — política aplicada por plantilla (B), forks
(C), inventario de módulos (D).
