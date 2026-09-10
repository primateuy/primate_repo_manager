# Recorrido de validación

> Documento de trabajo, no guía de usuario. La guía dice **cómo se usa**; esto dice **qué
> hay que comprobar y qué sería señal de problema**. Cuando este recorrido salga completo,
> el criterio de salida del flujo existente queda cerrado.

**Para:** Daryl · **Con:** `desarrollo@primate.uy` · **Contra:** `prm-sandbox`
**Escrito:** 4 de septiembre de 2026 · **Actualizado:** 10 de septiembre
**Estado:** la **Parte 2 se recorrió entera y pasó** — la deuda de A5+A6+A8 quedó saldada
**Cubre:** A4 completo, la deuda visual de A5+A6+A8, la cadena de la bitácora y los
cuatro tipos de entrada — y, desde el 10-sep, la **Parte 4** con todo lo que se construyó
después y que **ninguna persona miró todavía**: el delta y su pantalla, los correos, la
higiene entera, el nacimiento desde el asistente, y el panel con su tendencia.

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

## Parte 2 · La deuda de A5 + A6 + A8 — RECORRIDA Y PASADA (7-sep-2026)

> **Saldada.** Esta parte se recorrió completa en la sesión grande de validación y salió
> bien. A5, A6 y A8 dejan de estar aprobados en forma provisoria. Lo que sigue se conserva
> como guion —sirve para volver a correrlo cuando estas pantallas cambien—, no como deuda
> abierta.

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

---

# Parte 4 · Lo que nunca pasó por tus ojos

**Agregada el 10-sep-2026, con los bloques B, E2, E3.2 y E4 cerrados.** Todo lo de acá
funciona y está probado —790 tests, ensayos contra `prm-sandbox`, instalación desde
cero— pero **ninguna de estas pantallas la miró una persona todavía**. Ése es el punto de
esta parte: no es «comprobar que anda», es «ver si dice lo que tiene que decir».

**Antes de empezar:** `Repo Manager → Configuración → Ajustes` y anotá cómo están los
umbrales. Los pasos 4.6 y 4.7 los mueven, y hay que dejarlos como estaban.

---

## 4.1 — El panel, que es lo primero que ve Diego (10 min)

**Hago:** entro con mi usuario y **no navego**: miro dónde aterricé.

**Tengo que ver:** si mi usuario tiene rol de Líder o Administrador, aterrizo en
**Hallazgos**; si sólo tiene Lectura, en el **Panel**. Es un default: el menú entero sigue
estando.

**Sería problema:** aterrizar en la pantalla de Odoo genérica, o que la puerta pise una
acción de inicio que yo haya configurado antes.

**Hago:** *Ver y entender → Panel de salud*. Leo los tres números **sin abrir nada más**.

**Tengo que ver:** tres números con su unidad y su pie («1 de 38», «últimos 30 días»),
la frase de estado con su chip, y los botones. Si algo no se pudo medir, un guion — no un
cero.

**Sería problema:** un `0 %` donde no hay nada que medir; un número sin decir sobre cuántos;
la frase de estado hablando de repositorios que no se pudieron leer.

**Hago:** despliego **Ver el detalle** y miro la tendencia.

**Tengo que ver:** tres series, cada una con su escala a la derecha (los valores reales de
esa serie). **La línea se corta** donde una corrida no se pudo medir, con una banda rayada
en el hueco, y debajo la frase «N corrida(s) sin medición: la línea se corta ahí, no se
rellena».

**Sería problema:** una línea continua de punta a punta cuando hay huecos — eso sería el
gráfico afirmando que se midió una semana que nadie miró. **Si ves eso, cortá el recorrido
y avisame.**

---

## 4.2 — La meta, que se muestra y no reclama (5 min)

**Hago:** *Configuración → Ajustes → Metas del panel*. Pongo **85** en «commits con
convención». Guardo. Vuelvo al panel.

**Tengo que ver:** debajo del número de convención, «meta 85 %» en gris. En la tendencia
de esa serie, una línea punteada horizontal a la altura de 85 — **o ninguna**, si 85 queda
fuera de la escala de la serie (que es lo esperable hoy, con la convención en 12 %).

**Sería problema:** que la meta pinte el número de rojo, que aparezca un hallazgo nuevo
que hable de la meta, o que la línea punteada se dibuje pegada al borde de arriba
fingiendo que estamos cerca.

**Hago:** *Ver y entender → Hallazgos*, busco cualquier cosa que mencione la meta.

**Tengo que ver:** nada. La meta no genera hallazgos.

**Hago:** dejo la meta vacía otra vez y guardo.

---

## 4.3 — El delta: qué cambió respecto de la anterior (15 min)

**Hago:** *Ver y entender → Auditorías*. Miro la lista.

**Tengo que ver:** las columnas **Nuevos** y **Resueltos** con números, y en las corridas
que fallaron, la columna *Comparación* diciendo por qué no hay delta en vez de un cero.

**Sería problema:** una corrida fallida mostrando «0 nuevos, 0 resueltos» — eso se lee
igual que «no cambió nada», y lo que pasó es que no se pudo comparar.

**Hago:** abro la última corrida terminada.

**Tengo que ver:** arriba del todo, **«Qué cambió · #N respecto de #M»** con las dos
fechas, un desplegable **Comparar con otra**, y una frase en castellano («Aparecieron N
hallazgos… y se resolvieron M»). Debajo, los bloques **Nuevos**, **Resueltos** y —si hubo
repositorios ilegibles— **Sin confirmar**.

**Lo que más me interesa que mires:** cada **resuelto** dice **por qué** dejó de estar. Hay
tres frases posibles y las tres significan cosas distintas:

| frase | qué quiere decir |
|---|---|
| «Lo corrigió PLAN-X el dd/mm · verificado» | lo arregló un plan de este módulo, y el apply lo comprobó releyendo |
| «Se resolvió en la app: clasificación definida» | alguien lo resolvió acá, sin plan (clasificar, vincular una cuenta) |
| «Se resolvió fuera de la app: alguien lo cambió en GitHub» | nadie lo tocó desde acá |

**Sería problema:** que un hallazgo que vos sabés que se arregló por un plan diga «fuera de
la app», o al revés. Ésa es la afirmación más delicada de esta pantalla.

**Hago:** si hay bloque **Sin confirmar**, lo leo entero.

**Tengo que ver:** los repositorios con **el motivo de cada uno** (el error de GitHub tal
cual), y la frase «No cuentan como resueltos ni como nuevos».

**Hago:** aprieto **Armar plan con los N nuevos**.

**Tengo que ver:** se abre un plan **en borrador**, con las operaciones de los que sí se
pueden remediar. Los que no —una rama sin protección, por ejemplo— no entran, y el botón
no se niega por eso.

**Sería problema:** que aplique algo. El botón arma; no ejecuta.

---

## 4.4 — Los correos del lunes, en tu cliente (10 min)

**No se pudieron mandar**, y el motivo está anotado: los ocho servidores de correo de
staging están desactivados y su cola tiene 232 mensajes en excepción con **destinatarios
reales de clientes**. Activar uno para probar el render los soltaría.

**Hago:** abro los tres archivos que están en `~/Downloads/`, con doble clic o
arrastrándolos a mi cliente de correo:

| archivo | qué es |
|---|---|
| `correo_e24_lunes.html` | el resumen del lunes: tres números con su movimiento, lo nuevo por gravedad, el plan que espera |
| `correo_e24_sin_leer.html` | el mismo, con la **caja punteada** de los repositorios que no se pudieron leer |
| `correo_e24_fallida.html` | el que llega **igual** cuando la auditoría no pudo terminar |

**Tengo que ver:** los colores enteros (el chip de severidad, el delta en verde o rojo
según si el movimiento es bueno o malo), la caja punteada con su borde, y los nombres de
repositorio en monoespaciada. En el de los no leídos, la frase en negrita **«Este correo no
dice nada sobre ellos»**.

**Sería problema:** que llegue como texto plano o sin colores — querría decir que algún
estilo se escapó a una hoja externa, que los clientes de correo no cargan.

**Y el que más importa:** el de la auditoría fallida tiene que decir la causa y que **los
números de la aplicación son los de la semana pasada**. No mandar nada dejaría creer que no
hay novedades.

---

## 4.5 — El nacimiento de un repositorio, desde el asistente (20 min)

> **Esto escribe en GitHub de verdad**, en `prm-sandbox`. El repositorio queda creado; hay
> un paso final para borrarlo.

**Hago:** *Decidir y aplicar → Crear repositorio*. Paso 1: cliente o producto **«Ensayo
Daryl»**, clasificación **Cliente**, versión **19.0**, sin responsable.

**Tengo que ver:** el nombre que arma la regla —`cliente-ensayo-daryl`— y que **no lo
escribí yo**.

**Hago:** paso 2 y 3, leo el resumen.

**Tengo que ver:** el número de operaciones prometidas, y que coincida con el que después
tiene el plan. Cuatro ramas, la rama por defecto, los rulesets que la política exige,
Dependabot.

**Sería problema:** que prometa un número y arme otro.

**Hago:** **Revisar el plan y crear**.

**Tengo que ver:** un plan **en borrador**. Nada se escribió todavía. En la pantalla del
plan, la operación de crear el repositorio marcada **IRREVERSIBLE**, y para confirmarla hay
que **escribir el nombre a mano** — un tilde no alcanza.

**Hago:** confirmo todo y aplico.

**Tengo que ver:** las diez operaciones en `applied`, y en GitHub el repositorio con sus
cuatro ramas, `19.0-prod` como rama por defecto, tres rulesets y Dependabot encendido.

**Hago:** lanzo una auditoría y miro los hallazgos **de ese repositorio**.

**Tengo que ver: cero accionables y uno informativo.** Ese uno dice que **secret scanning
está apagado** y que encenderlo exige Advanced Security.

Y es la verdad, no una excusa: los permisos de la App están aprobados desde el
10-sep —Dependabot lee bien y el plan lo enciende al nacer, así que esa fuente queda
limpia— y secret scanning está apagado en toda la organización, también en los
repositorios públicos. **Que aparezca es el producto funcionando**: no dice «no hay
secretos», dice que nadie miró y por qué. La alternativa —callarlo— sería afirmar que un
repositorio está limpio sin haberlo mirado.

Ese hallazgo, además, es mejor diapositiva que un cero pelado: nombra una decisión
comercial concreta que alguien tiene que tomar, en vez de un número que no invita a nada.

**Sería problema:**

- que sean **dos** y el otro diga «no se pudo leer» en vez de «apagado» → los permisos se
  cayeron, avisame;
- un hallazgo de rama sin protección sobre las ramas gobernadas;
- uno de convención de commits sobre el commit inicial del README;
- **cero hallazgos y ninguno informativo** → eso NO sería una buena noticia: querría decir
  que el módulo dejó de decir que hay una fuente que no miró.

---

## 4.6 — La higiene: lo que se ofrece borrar y lo que no (20 min)

**Hago:** en el repositorio que acabás de crear, desde GitHub, creá dos ramas a partir de
`19.0`: **`19.0_limpia`** (sin tocarla) y **`19.0_trabajo`**, y a la segunda hacele un
commit cualquiera desde la web.

**Hago:** *Configuración → Ajustes* y poné **0** en «meses sin actividad para llamar
abandonada a una rama». Guardá. Lanzá una auditoría.

**Tengo que ver:** dos hallazgos distintos sobre ese repositorio:

- **`19.0_limpia`**: «está integrada a «19.0»: no tiene commits propios» — y **dice contra
  qué rama se midió**.
- **`19.0_trabajo`**: «tiene 1 commit(s) que nunca llegaron a «19.0»…»

**Hago:** intento planificar la **abandonada**: la abro, busco el botón de remediar, y
también pruebo arrastrarla a la bandeja del plan.

**Tengo que ver:** que **no se puede, por ninguno de los dos caminos**, y que diga por qué:
«Tiene commits que nunca llegaron a producción. Borrarla los tira».

**Sería problema — y es el más grave de todo este recorrido:** que el módulo ofrezca
borrar la rama con trabajo sin integrar. **Si eso pasa, cortá y avisame.**

**Hago:** planifico la **integrada**, apruebo y aplico.

**Tengo que ver:** la frase de la aprobación dice que **se borra**, contra qué estaba
integrada, y **la salvedad**: «la reversión recrea la rama en el mismo commit mientras
GitHub conserve el objeto — eso no lo controlamos». Y para confirmarla hay que **escribir
el nombre de la rama**, aunque sea reversible.

**Hago:** desde la pestaña Detalle del plan, **revierto** esa operación.

**Tengo que ver:** la rama de vuelta en GitHub, **en el mismo commit**.

**Hago:** dejá el umbral de abandono como estaba.

---

## 4.7 — Archivar, con el aviso de qué depende de ese repositorio (10 min)

**Hago:** *Ajustes*, poné **0** en «meses sin push para proponer archivar». Auditá.

**Tengo que ver:** el hallazgo «no recibe un push desde…».

**Hago:** lo planifico y **leo la pantalla de aprobación entera antes de aprobar**.

**Tengo que ver:** un bloque **«Qué depende hoy de …»** con los hechos concretos de ese
repositorio: PRs abiertas que se congelan, forks nuestros que lo tienen de upstream,
módulos que una promoción movió. Si no hay nada, tiene que decir que **eso es lo que el
espejo ve** — no «no depende nada de él».

**Sería problema:** una advertencia genérica sobre archivar, sin los datos de ese repo.

**Hago:** aplico, compruebo en GitHub que quedó archivado, y **revierto**.

**Tengo que ver:** desarchivado, sin haber perdido nada.

**Hago:** dejá el umbral como estaba, y **borrá el repositorio de ensayo** desde GitHub.

**Hago, al final:** lanzá una auditoría más.

**Tengo que ver:** el repositorio borrado aparece como **ausente** —con su fecha— y **deja
de auditarse**: un solo hallazgo informativo que dice que ya no viene en el listado, y
ninguno sobre sus ramas.

---

## 4.8 — Los avisos de la barra (5 min)

**Hago:** lanzo una auditoría y **me voy a otra pantalla** cualquiera del módulo.

**Tengo que ver:** arriba, en la barra, **«Auditoría en curso · N/M»** con un punto vivo. Y
si hay un plan en borrador esperando, **«N plan(es) espera(n) tu aprobación»**.

**Hago:** abro el panel mientras la auditoría corre.

**Tengo que ver:** una tarjeta arriba con el avance y la frase **«Los números de abajo son
de la auditoría anterior. Se actualizan al terminar; hasta entonces no cambian solos.»**

**Sería problema:** que los tres números cambien solos a mitad de una corrida, o que la
barra avise de un plan que yo no puedo aprobar.

---

## 4.9 — Los controles de siempre (10 min)

**Hago:** *Configuración → Ajustes*, bloque **Estado de la instancia**.

**Tengo que ver:** procesamiento en segundo plano **funcionando**, cadena de la bitácora
**íntegra**, clave de cifrado **cargada**. Y la **próxima corrida programada**, en tu zona
horaria.

**Hago:** *Ver y entender → Bitácora*. Miro las entradas de todo lo que hiciste hoy.

**Tengo que ver:** cada escritura con su antes y su después, la reversión del borrado de
rama con su punto de retorno, y la cadena sin cortes.

**Sería problema:** una entrada editable, o la cadena marcada como rota.

**Hago:** abro cualquier entrada de la bitácora e intento cambiarle algo.

**Tengo que ver:** que no se puede. Ni siquiera como administrador.

---

## Qué hacer con lo que anotes

Todo lo de la columna «sería problema» va a una lista y lo miramos junto. Los tres que
piden **cortar el recorrido** si aparecen:

1. La tendencia dibujando una línea continua sobre un hueco.
2. El módulo ofreciendo borrar una rama con trabajo sin integrar.
3. Una entrada de la bitácora que se deje editar.

Los tres significan lo mismo: el producto afirmando algo que no puede sostener.
