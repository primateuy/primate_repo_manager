# primate_repo_manager

Gobernanza de repositorios GitHub desde Odoo 19. Odoo declara la política, GitHub la
aplica: el módulo compara lo declarado con lo real, detecta desvíos y audita.

**Estado: Fase 1 — auditoría de solo lectura.** No escribe absolutamente nada en GitHub.

---

## Qué hace hoy

Recorre la cuenta, arma el espejo de lo que hay (repositorios, ramas, permisos, PRs,
muestra de commits, workflows de CI) y produce un informe con hallazgos tipados, cada uno
con su severidad y con la acción que lo resolvería — **calculada y nunca ejecutada**.

La corrida va por `queue_job`, un job por repositorio. Es reanudable: si se corta, retoma
sólo los que no cerraron. Correrla dos veces actualiza, no duplica.

## Setup

### 1. La GitHub App

El módulo se autentica como App instalada, no con un token personal. Necesitás tres datos:

| Dato | Dónde está |
|---|---|
| **App ID** | *Settings → Developer settings → GitHub Apps →* la app *→ About* |
| **Installation ID** | *Settings → Applications → Installed GitHub Apps → Configure*. Está **en la URL**: termina en `/installations/<número>` |
| **Private key** | Misma pantalla del App ID, sección *Private keys*. Una clave ya generada **no se puede volver a descargar**: si nadie guardó el `.pem`, generá una nueva |

**Dónde se instala importa más que dónde se crea.** La App puede crearse desde cualquier
cuenta, pero tiene que instalarse en la cuenta **dueña de los repositorios**, y eso sólo
lo puede hacer quien controle esa cuenta. Una App instalada en tu cuenta personal sólo
alcanza repos tuyos.

Y hereda el techo de quien la instaló: si la instala alguien sin permiso de administrador
sobre los repos, la auditoría no va a poder leer las protecciones de rama. No falla —lo
reporta como "no legible"— pero el informe queda incompleto.

Permisos mínimos para la Fase 1, **todos en solo lectura**:

`Metadata`, `Administration` (protecciones y colaboradores), `Contents` (commits y firmas),
`Pull requests`, `Commit statuses`.

### 2. El secreto de cifrado

La private key se guarda cifrada con una clave derivada de un secreto que vive **fuera de
la base de datos**, en `odoo.conf`:

```ini
repo_manager_key = <cadena larga y aleatoria>   ; openssl rand -base64 48
```

Es a propósito: si la clave saliera de la base, un `pg_dump` se llevaría el texto cifrado
y el material para descifrarlo juntos. Sin el parámetro el módulo **se niega a guardar**
la credencial en vez de cifrarla con cualquier otra cosa.

> **El backup de la base y el respaldo de `repo_manager_key` van juntos.** Uno sin el otro
> no sirve: restaurar la base en otro servidor sin ese secreto deja la credencial
> ilegible. Para cambiarlo hay un asistente (*Configuración → Rotar secreto de cifrado*)
> que descifra con el anterior y recifra con el nuevo; editar el `odoo.conf` a mano sin
> ese paso rompe la conexión en silencio.

### 3. Correr la auditoría

*Repo Manager → Conexiones* → cargar los tres datos → **Probar conexión**. Después
*Auditorías → Nueva → Auditar*. El informe en PDF sale del botón de imprimir de la corrida.

---

## Lo que NO se puede hacer desde Odoo

No por falta de implementación: **la API de GitHub no lo permite**. Conviene saberlo antes
de esperar que salga de acá.

**La configuración de la App misma.** Sus permisos, su private key, dónde está instalada y
a qué repositorios alcanza se administran en la interfaz de GitHub. Una App no puede
modificarse a sí misma. Si hace falta ampliar permisos —por ejemplo para escribir en F2—
hay que hacerlo en GitHub y volver a aceptar la instalación.

**El plan y la facturación.** Ni consultarlos ni cambiarlos. Esto importa más de lo que
parece: GitHub sólo permite proteger ramas de repositorios **privados** en planes pagos,
así que en una cuenta gratuita esos repos no se pueden gobernar. El módulo lo detecta
—queda registrado como causa `plan_limit`— pero resolverlo es una decisión comercial que
se toma en la web de GitHub.

**Las claves SSH de firma de cada persona.** Se pueden *verificar* (el módulo consulta las
signing keys públicas registradas) pero no crear ni instalar: la clave privada vive en la
máquina de cada uno y no debe salir de ahí. El onboarding incluye la guía; configurarla es
tarea de la persona.

**Transferir un repositorio entre cuentas.** La API expone la operación, pero requiere
aceptación de la cuenta destino y permisos que exceden los de una App. En la práctica se
hace a mano.

**El contenido de un repositorio.** El módulo no clona ni ejecuta git: todo es REST/GraphQL.
No hay checkout, no hay build, no hay acceso al árbol de archivos más allá de lo que
devuelve la API.

---

## Cómo leer el informe

Tres cosas que el informe distingue a propósito, y que conviene no colapsar al leerlo:

**Protegida / sin protección / no legible.** No son dos estados sino tres. GitHub devuelve
el mismo `404` cuando una rama no tiene protección y cuando el que pregunta no tiene
permiso para saberlo. El informe nunca dice "sin protección" sobre algo que no pudo leer.

**Techo de plan / falta de permisos.** Las dos hacen que una protección sea ilegible, pero
una se resuelve pagando y la otra reinstalando la App. Van en secciones separadas.

**Auditado / no auditado.** Si un repositorio falla, la corrida sigue con los demás y el
informe abre diciendo cuántos se revisaron y cuántos no. De los no auditados no se afirma
nada.

## Desarrollo

```bash
odoo-bin -c <conf> -d <db> -i primate_repo_manager --stop-after-init
odoo-bin -c <conf> -d <db> -u primate_repo_manager \
         --test-enable --test-tags /primate_repo_manager --stop-after-init
```

`primate_repo_manager_pcm_bridge` se instala solo cuando están el core y
`primate_cloud_manager`. El core no contiene ninguna referencia a PCM, y hay un test que
lo verifica recorriendo los archivos.

El PDF necesita `wkhtmltopdf` con Qt parcheado, el mismo que usa Odoo para el resto de sus
informes.
