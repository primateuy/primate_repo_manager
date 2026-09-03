# Guía de usuario — Repo Manager

> Esta guía crece con el producto. Cada sección se escribe **después** de operar esa
> funcionalidad desde la interfaz contra la organización de pruebas, no antes.
>
> Si algo sólo se puede hacer desde la consola, no está acá: está en
> [`PLAN-ETAPA-SANDBOX.md`](PLAN-ETAPA-SANDBOX.md) como funcionalidad faltante. Que un
> paso no aparezca en esta guía no es un olvido — es la forma en que decimos que todavía
> no se puede hacer desde la aplicación.

**Última actualización:** 2 de septiembre de 2026
**Cubre:** conexión con GitHub.

---

## Índice

1. [Qué hace Repo Manager](#1-qué-hace-repo-manager)
2. [Conectar Odoo con GitHub](#2-conectar-odoo-con-github)
3. [Secciones que faltan](#3-secciones-que-faltan)

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

## 3. Secciones que faltan

Están construidas por dentro pero **todavía no se pueden operar desde la interfaz**, así
que no se documentan. Cada una tiene su ítem en el plan de la etapa:

| Sección | Qué falta para poder escribirla | Ítem |
|---|---|---|
| Traer los repositorios y auditarlos | El botón *Auditar* deja la corrida esperando: encola el trabajo y nadie lo ejecuta | A1 |
| Ver los hallazgos | No hay ninguna pantalla de hallazgos; el resultado sólo se ve en el PDF | A2 |
| Abrir un repositorio y clasificarlo | Sólo hay lista, sin formulario. Clasificar a mano es un paso obligatorio del flujo | A3 |
| Armar un plan de cambios | Hoy hay que escribir el detalle de cada operación en formato JSON | A4 |
| Ver y ajustar la política | Las plantillas no tienen menú | A5 |
| Vincular cuentas de GitHub con empleados | Las personas no tienen pantalla | A6 |

El informe en PDF, la aprobación y ejecución de un plan, el registro de bitácora y la
reversión **sí funcionan**, pero dependen de pasos anteriores que todavía no son
operables. Se documentan cuando el camino completo se pueda recorrer desde la aplicación.
