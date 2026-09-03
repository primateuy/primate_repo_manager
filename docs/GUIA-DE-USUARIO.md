# Guía de usuario — Repo Manager

> Esta guía crece con el producto. Cada sección se escribe **después** de operar esa
> funcionalidad desde la interfaz contra la organización de pruebas, no antes.
>
> Si algo sólo se puede hacer desde la consola, no está acá: está en
> [`PLAN-ETAPA-SANDBOX.md`](PLAN-ETAPA-SANDBOX.md) como funcionalidad faltante. Que un
> paso no aparezca en esta guía no es un olvido — es la forma en que decimos que todavía
> no se puede hacer desde la aplicación.

**Última actualización:** 2 de septiembre de 2026
**Cubre:** conexión con GitHub · lanzar una auditoría.

---

## Índice

1. [Qué hace Repo Manager](#1-qué-hace-repo-manager)
2. [Conectar Odoo con GitHub](#2-conectar-odoo-con-github)
3. [Traer los repositorios y auditarlos](#3-traer-los-repositorios-y-auditarlos)
4. [Secciones que faltan](#4-secciones-que-faltan)

**Anexo:** [Configuración del servidor](#anexo--configuración-del-servidor) — sólo para
quien administra la instancia de Odoo.

---

## 1. Qué hace Repo Manager

Repo Manager mira los repositorios de GitHub de la empresa y responde tres preguntas:

- **Qué hay.** Cuántos repositorios, quién tiene acceso a cada uno, qué ramas existen,
  qué se está trabajando.
- **Qué se aparta de lo acordado.** Permisos de más, ramas sin proteger, mensajes de
  commit fuera de convención, cuentas sin dueño.
- **Qué habría que cambiar** — y, cuando se aprueba, lo cambia.

Trabaja en dos modos que conviene tener claros desde el principio:

**Leer.** Trae la información de GitHub y la guarda en Odoo. No modifica nada allá afuera.
Se puede repetir todas las veces que uno quiera sin consecuencias.

**Escribir.** Aplica cambios reales en GitHub: proteger una rama, dar o quitar un permiso.
Nunca ocurre sola: hace falta armar un plan, aprobarlo, y recién entonces ejecutarlo. Todo
lo que se escribe queda registrado con cómo estaba antes, para poder deshacerlo.

---

## 2. Conectar Odoo con GitHub

Una **conexión** es la cuenta u organización de GitHub que Repo Manager va a mirar, junto
con la credencial para hacerlo. Es lo primero que hay que crear: sin una conexión no hay
nada que ver.

### 2.1 Antes de empezar, lo que se necesita de GitHub

Repo Manager no entra a GitHub con un usuario y una contraseña, sino con una **GitHub
App**: una aplicación registrada que se instala sobre la cuenta y recibe permisos
acotados. Si no la tenés creada, esto lo hace quien administre la cuenta de GitHub y
después te pasa tres datos:

| Dato | Dónde está en GitHub |
|---|---|
| **App ID** | Settings → Developer settings → GitHub Apps → la app → arriba de todo |
| **Installation ID** | En la URL de la app instalada, el número final de `…/installations/<número>` |
| **Private key** | Un archivo `.pem` que GitHub deja descargar **una sola vez** al generarlo |

> **Sobre el archivo `.pem`:** es la llave de la conexión. Guardalo donde guardarías una
> contraseña. GitHub no lo vuelve a mostrar; si se pierde, se genera uno nuevo y el
> anterior deja de servir.

### 2.2 Crear la conexión

**Menú: Repo Manager → Configuración → Conexiones → Nuevo**

Completá:

- **Nombre.** Cómo la vas a reconocer en la lista. Por ejemplo *GitHub — prm-sandbox*.
- **Cuenta.** El nombre exacto de la cuenta u organización en GitHub, tal como aparece en
  la URL. Si los repositorios están en `github.com/prm-sandbox/…`, acá va `prm-sandbox`.
- **Tipo de cuenta.** *Organización* o *Cuenta de usuario*. **Elegí bien**: cambia qué
  cosas existen. Una cuenta de usuario **no tiene equipos**, así que todo lo que dependa
  de equipos no va a estar disponible. Si no estás seguro, mirá la página de la cuenta en
  GitHub: las organizaciones muestran una pestaña «People» con equipos.
- **Entorno.** *Sandbox* para la organización de pruebas, *Producción* para la real. Hoy
  es informativo: lo que decide si se puede escribir es si la conexión tiene cargada una
  App de escritura, no esta etiqueta.
- **App ID** e **Installation ID**: los dos números de la tabla de arriba.
- **Private key (PEM)**: abrí el archivo `.pem` con cualquier editor de texto, copiá
  **todo** el contenido —incluidas las líneas `-----BEGIN…` y `-----END…`— y pegalo acá.

Guardá.

> **La clave no se vuelve a ver.** Después de guardar, el campo aparece vacío y al lado
> figura *Clave cargada: sí*. Es a propósito: se guarda cifrada y no se muestra nunca más,
> ni siquiera a quien la cargó. Si necesitás cambiarla, pegás una nueva encima.

### 2.3 Probar que funciona

Con la conexión guardada, apretá **Probar conexión**.

**Si sale bien:** el estado pasa a **Conectado**, aparece la cuota de consultas que queda
disponible, y en la conversación de abajo queda anotado contra qué cuenta se verificó.

**Si sale mal**, el mensaje dice qué pasó. Los tres casos habituales:

| El mensaje dice | Qué significa | Qué hacer |
|---|---|---|
| Falta App ID o Installation ID | Quedó alguno vacío | Completar los dos números |
| La cuenta es de tipo *X* pero está configurada como *Y* | El campo **Tipo de cuenta** no coincide con la realidad | Corregir el tipo. No se corrige solo a propósito: cambia qué se consulta |
| Falta `repo_manager_key` en odoo.conf | Falta el secreto con el que se cifran las claves | Lo resuelve quien administra el servidor de Odoo (ver 2.4) |

### 2.4 Una nota para quien administra el servidor

Las private keys se guardan cifradas con una clave derivada de un secreto que vive en el
archivo de configuración de Odoo, **no en la base de datos**. Si viviera en la base, una
copia de respaldo se llevaría el texto cifrado y la llave para descifrarlo juntos.

En `odoo.conf` tiene que existir:

```
repo_manager_key = <cadena larga y aleatoria>
```

Se genera con `openssl rand -base64 48`. **El respaldo de la base y el respaldo de este
secreto van juntos:** uno sin el otro no sirve. Si se restaura la base en otro servidor
con otro secreto, las claves guardadas dejan de poder descifrarse y hay que volver a
cargarlas — Repo Manager lo va a decir con ese mensaje exacto cuando pase.

---

## 3. Traer los repositorios y auditarlos

Una **auditoría** hace dos cosas de una vez: trae el estado actual de GitHub a Odoo, y lo
compara con la política para producir la lista de cosas que no cierran. No modifica nada
en GitHub — se puede repetir cuantas veces se quiera.

### 3.1 Lanzarla

**Menú: Repo Manager → Auditorías → Nuevo**

- **Referencia:** un nombre para reconocerla después. Por ejemplo *Auditoría de septiembre*.
- **Conexión:** cuál de las conexiones auditar.

Guardá y apretá **Auditar**.

### 3.2 Qué pasa después, y por qué a veces tarda

Depende de cuántos repositorios tenga la cuenta, y el producto elige solo:

**Pocos repositorios** (hasta 25 por defecto). La auditoría se hace **en el momento**: la
pantalla queda esperando y, cuando responde, la corrida ya está terminada con todo
adentro. Con seis repositorios son unos 70 segundos. Es normal que parezca colgada un
rato: está trabajando.

**Muchos repositorios.** El trabajo se **reparte en tareas** que se procesan en segundo
plano. El botón responde enseguida y la corrida queda *En curso*. Los contadores
—*Recorridos*, *Con error*— y la barra de avance van subiendo a medida que termina cada
repositorio.

> **La pantalla no se actualiza sola.** Para ver cómo avanza, volvé a entrar a la corrida
> o refrescá. Cuando el estado pase a *Terminada*, está lista.

El límite entre un caso y otro se puede cambiar (ver el anexo). Si tu instancia no tiene
el procesamiento en segundo plano configurado y la cuenta supera el límite, la corrida se
va a quedar *En curso* sin avanzar: eso no es un error del producto, es que falta esa
pieza del servidor.

### 3.3 Cómo saber que salió bien

Al terminar, el estado queda en uno de estos:

| Estado | Qué significa |
|---|---|
| **Terminada** | Se recorrieron todos los repositorios sin problemas |
| **Terminada con errores** | Se recorrieron todos, pero alguno no se pudo leer del todo. El número está en *Con error* |
| **Fallida** | No se pudo ni siquiera listar los repositorios. El motivo está en *Detalle del error* |

Que un repositorio quede *con error* no invalida la auditoría: los demás se auditaron
igual, y el que falló aparece como un hallazgo propio para que nadie suponga que se revisó.

### 3.4 Volver a intentar lo que falló

Si quedaron repositorios con error, **Reanudar** vuelve a recorrer sólo esos. No repite
los que ya salieron bien, así que no gasta tiempo ni cuota de GitHub de más.

---

## 4. Secciones que faltan

Están construidas por dentro pero **todavía no se pueden operar desde la interfaz**, así
que no se documentan. Cada una tiene su ítem en el plan de la etapa:

| Sección | Qué falta para poder escribirla | Ítem |
|---|---|---|
| Ver los hallazgos | No hay ninguna pantalla de hallazgos; el resultado sólo se ve en el PDF | A2 |
| Abrir un repositorio y clasificarlo | Sólo hay lista, sin formulario. Clasificar a mano es un paso obligatorio del flujo | A3 |
| Armar un plan de cambios | Hoy hay que escribir el detalle de cada operación en formato JSON | A4 |
| Ver y ajustar la política | Las plantillas no tienen menú | A5 |
| Vincular cuentas de GitHub con empleados | Las personas no tienen pantalla | A6 |

El informe en PDF, la aprobación y ejecución de un plan, el registro de bitácora y la
reversión **sí funcionan**, pero dependen de pasos anteriores que todavía no son
operables. Se documentan cuando el camino completo se pueda recorrer desde la aplicación.


---

## Anexo — Configuración del servidor

Esta parte no es del flujo de trabajo: la necesita quien administra la instancia de Odoo,
una sola vez.

### El procesamiento en segundo plano

Cuando una cuenta supera el límite de repositorios, la auditoría se reparte en tareas que
alguien tiene que ejecutar. Ese «alguien» es un componente de Odoo que hay que encender en
el archivo de configuración.

**Qué cambió en `odoo.conf` y por qué:**

```ini
[options]
; Carga el módulo de tareas en segundo plano al arrancar la instancia. Sin esto el
; procesador no existe y las tareas se acumulan sin que nadie las tome.
server_wide_modules = base,web,queue_job

[queue_job]
; Cuántas tareas se procesan a la vez, por canal.
;   root              : capacidad general de la instancia
;   root.repo_manager : el canal propio de Repo Manager
channels = root:2,root.repo_manager:2
```

**Hay que reiniciar Odoo** para que tome el cambio.

**Dos consecuencias que conviene saber:**

- `server_wide_modules` aplica a **todas** las bases de datos que sirva esa instancia, no
  sólo a la que usa Repo Manager. Es como está pensado el componente. El arranque tarda un
  poco más y el registro muestra el procesador conectándose a cada base.
- El canal `root.repo_manager` **existe porque el módulo lo declara**. Tener canal propio
  permite darle capacidad sin competir con el resto del sistema; si no se declarara,
  compartiría la del canal general con todo lo demás.

**Cómo verificar que quedó andando.** En el registro de arranque tienen que aparecer estas
líneas:

```
queue_job.jobrunner: starting jobrunner thread (in threaded server)
queue_job.jobrunner.channels: Configured channel: root(C:2,...)
queue_job.jobrunner.channels: Configured channel: root.repo_manager(C:2,...)
queue_job.jobrunner.runner: queue job runner ready for db <tu base>
```

Si no aparecen, el procesador no arrancó y las auditorías grandes se van a quedar
esperando.

### El límite entre las dos formas de auditar

**Ajustes → Repo Manager → Repositorios que se auditan en el momento** (por defecto 25).

El valor por defecto sale de una medición, no de un número redondo: 11,5 segundos por
repositorio contra una cuenta real de 113. Con 25 son unos 5 minutos, cómodos dentro del
tiempo máximo que Odoo le da a una pantalla.

Subirlo mucho hace que auditorías grandes corten por tiempo agotado; bajarlo a 0 fuerza
que todo pase por segundo plano, lo que es razonable si el procesador está configurado.
