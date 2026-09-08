# Cobertura del entregable de diseño

**Qué es esto.** El recorrido del entregable —`Repo Manager-print.html`, 24 páginas—
elemento por elemento, con cada uno en una de tres columnas:

| | |
|---|---|
| **✅ Implementado** | está en el producto y se puede abrir |
| **🔒 Apagado a propósito** | se ve, no se toca, y dice con qué bloque llega (regla 2 de `CLAUDE.md`) |
| **⛔ Sin representación** | el diseño lo muestra y en el producto **no hay ni rastro**: ni pantalla, ni casillero |
| **📋 Ítem de plan** | no tiene pantalla donde poner un casillero (o su pantalla llega en el próximo tramo), así que vive en `PLAN-ETAPA-SANDBOX.md` con su bloque |
| **↔️ Desvío deliberado** | el producto se aparta del diseño a propósito, por una decisión tomada y escrita. No es un faltante ni una omisión: es una diferencia con motivo |

**Para qué sirve, y por qué la tercera columna es la única que importa.** Mirar el producto
y compararlo con el prototipo detecta lo que está *mal*; no detecta lo que *falta*, porque
el ojo no echa de menos lo que nunca vio. Esta tabla es la respuesta permanente a «¿esto
está completo?».

**Se actualiza con cada tramo.** Un elemento que pasa de ⛔ a 🔒 o a ✅ se mueve acá en el
mismo commit que lo mueve en el código.

**Última revisión:** 6 de septiembre de 2026, tras implementar la variante de modo
oscuro (turno 7 del entregable).

---

## Resumen

| columna | cuántos |
|---|---|
| ✅ Implementado | 88 |
| 🔒 Apagado con su cartel | 18 |
| 📋 Ítem de plan, con su bloque | 11 |
| ↔️ Desvío deliberado, con su motivo | 2 |
| ⛔ Sin representación | **0** |

**La tercera columna quedó vacía en esta revisión**, y así tiene que quedar cada vez: los
siete que aparecieron pasaron a cartel o a ítem del plan en el mismo commit. La tabla del
final cuenta cuáles eran y dónde fueron.

---

## 1a · Sistema de diseño

| elemento | estado | dónde |
|---|---|---|
| Paleta completa (tinta, neutrales, acento pizarra) | ✅ | `tokens.scss`, traducida valor por valor |
| Severidades en par sólido/tenue | ✅ | `tokens.scss` + `.rm-chip` |
| Estados de proceso (vivo, terminado, error) | ✅ | `tokens.scss`, usados en chips y barras |
| «No se pudo leer» rayado con su causa | ✅ | mixin `rm-no-legible`, usado en panel, plan y bitácora |
| IBM Plex Mono para todo identificador git | ✅ | vendorizada (OFL) y aplicada |
| IBM Plex Sans para leer | 🔒 | **decisión C**: se hereda la sans de Odoo. La identidad vive en tokens, patrones y mono |
| Escala de espaciado 4/8/12/16/24/32 | ✅ | `tokens.scss` |
| Radios 4 / 6 / 8 + sombra sólo en capas flotantes | ✅ | tokens; la sombra sólo en el fantasma de arrastre |
| Borde punteado reservado a lo destructivo y lo soltable | ✅ | `.rm-tipeo`, `.rm-apagado`, zona de la bandeja |
| Chip de severidad sólido y con texto | ✅ | `.rm-chip`, nunca sólo color |
| Chips de estado (en curso, verificado, falló, pendiente) | ✅ | `.rm-chip-*` |
| Barras de progreso con sus cuatro estados | ✅ | `live_progress`, incluido el tramo rayado de «sin leer» |
| Tarjeta de hallazgo (severidad, hecho, propuesta) | ✅ | pantalla de hallazgos |
| Tarjeta compacta para listas densas | ✅ | es la fila de la lista de hallazgos |
| Botón destructivo que nace deshabilitado | ✅ | el de confirmar irreversible se habilita al escribir el nombre |
| Confirmación destructiva con nombre escrito | ✅ | plan, fila por fila |
| Bloque de honestidad «no se pudo leer» | ✅ | panel de salud y diagnóstico |
| Voz rioplatense, números siempre con unidad | ✅ | criterio aplicado en todo el módulo |

## 1b + 3a · Panel de salud

| elemento | estado | dónde |
|---|---|---|
| Tres números arriba | ✅ | protegidas · convención · hallazgos |
| Frase de estado redactada desde los críticos | ✅ | con su chip |
| Día uno sin maquillaje (guiones, cero explicado, SIN POLÍTICA) | ✅ | verificado en navegador con una conexión recién auditada |
| Detalle plegado que recuerda su estado | ✅ | por usuario, en su navegador |
| Por gravedad | ✅ | dentro del pliegue |
| Por tipo de repositorio | ✅ | dentro del pliegue |
| Cuentas sin dueño | ✅ | por conexión |
| Bloque de repositorios sin leer con su causa | ✅ | y fuera de los porcentajes |
| Tendencia de las últimas 8 corridas | 🔒 | llega con **E2** |
| «Comparar con auditoría anterior» | 🔒 | llega con **E2** |
| Meta configurable del 85 % | 🔒 | llega con **E4** |
| Delta «▲ 6 puntos desde la anterior» en los números | 🔒 | llega con **E2**, nombrado en el cartel de «comparar con la anterior» |
| Aviso de auditoría en curso dentro del panel | 🔒 | es uno de los dos avisos de barra: **E4**, ver abajo |

## 2a · Navegación

| elemento | estado | dónde |
|---|---|---|
| Siete secciones fijas | ✅ | `repo_menus.xml` |
| Entradas futuras grises con su etapa | ✅ | nueve casilleros con su página honesta |
| Página vacía honesta: qué hace y con qué bloque llega | ✅ | `repo.coming.soon` |
| Aviso permanente «auditoría en curso» en la barra | 📋 | ítem de plan, **E4** — es systray, no hay pantalla donde poner un casillero |
| Aviso permanente «1 plan espera tu aprobación» | 📋 | ítem de plan, **E4** — ídem |
| Dos puertas de entrada (gerencia → panel, técnica → hallazgos) | 📋 | ítem de plan, **E4** — es la acción de inicio por grupo |

## 2b · Plan de escritura

| elemento | estado | dónde |
|---|---|---|
| Statusbar del plan | ✅ | estados reales del modelo |
| «Qué va a pasar si aprobás» en castellano | ✅ | resumen arriba |
| Operaciones agrupadas por repositorio | ✅ | con su encabezado y conteo |
| Grupo sin nada que decidir, plegado | ✅ | |
| Confirmación en la fila, no en un modal | ✅ | |
| Dos niveles: tilde y nombre escrito | ✅ | |
| Dos barras separadas, nunca sumadas | ✅ | reversibles / irreversibles |
| «Confirmar todas las reversibles» | ✅ | las irreversibles nunca en lote |
| Columna que se vuelve progreso al aplicar | ✅ | reusa el componente vivo |
| Aviso de ejecución interrumpida | ✅ | agregado por el hallazgo 2 del ensayo |
| «Ver los hallazgos que originaron el plan» | ✅ | |
| «Detener después de esta operación» | 🔒 | llega con **D2.6** |
| «Sacar la 04 del plan y aprobar el resto» | 📋 | ítem de plan, **D2.3b** — se hace con D2.3, que ya toca esta pantalla |
| «Devolver a borrador con un comentario» | ✅ | existe sin el comentario; el comentario va al chatter |

## 2c · Hallazgos

| elemento | estado | dónde |
|---|---|---|
| Lista agrupada por severidad con sus conteos | ✅ | |
| Chip sólido con texto | ✅ | |
| Columna «Se propone» con la frase real de la operación | ✅ | se le pregunta a la operación |
| Fila expandida: en castellano + operaciones que generaría | ✅ | |
| Bandeja lateral del plan en borrador | ✅ | sticky |
| Arrastre con los cuatro estados de la 6d | ✅ | |
| Camino por clic equivalente | ✅ | «Agregar al plan» |
| Camino por teclado | ✅ | mango enfocable, espacio, Escape |
| Informativos sin mango | ✅ | prevención antes que explicación |
| Bloque «Historia» del hallazgo | 🔒 | llega con **E2** |
| «Regla que incumple» y «Evidencia leída de GitHub» | 📋 | ítem de plan, **D2.3b** — los datos ya están, falta mostrarlos |

## 2d · Bitácora

| elemento | estado | dónde |
|---|---|---|
| Línea de tiempo agrupada por día | ✅ | |
| Hora en mono y referencia al plan y operación | ✅ | |
| Riel con marca por tipo (forma además de color) | ✅ | |
| Antes/después en dos columnas, mono | ✅ | |
| Chip de resultado | ✅ | |
| Leyenda de los cuatro tipos | ✅ | sale del modelo |
| «Por qué es inmutable» con el estado de la cadena | ✅ | |
| «Revertir esta operación» | ✅ | pasa por el mismo embudo |
| Filtros nativos de Odoo | ✅ | el panel de control queda intacto |
| «Exportar firmado (CSV + hash)» | 🔒 | llega con **E3** |
| Entradas de cambio detectado fuera de la app | ✅ | B4: la detección, la frase que admite no saber quién fue, y el enlace al audit log |

## 3b · Repositorios

| elemento | estado | dónde |
|---|---|---|
| Lista con clasificación, ramas, colaboradores, hallazgos | ✅ | |
| Agrupado por clasificación con su resumen | ✅ | |
| Repositorio no legible con su causa | ✅ | |
| Formulario con botones inteligentes | ✅ | |
| Clasificación a mano que la auditoría no pisa | ✅ | con su origen y quién la fijó |
| Pestañas de ramas, colaboradores, hallazgos, bitácora | ✅ | |
| Pestaña de módulos | ✅ | llegó con D1 |
| Pestaña de PRs | 🔒 | llega con **F4** |
| Por rama: «Exige … · Tiene …» | 📋 | ítem de plan, **B1** |
| Atraso por rama (+4 / −0) | ✅ | campos de adelanto/atraso del espejo |

## 3c · Auditorías

| elemento | estado | dónde |
|---|---|---|
| Corrida viva con barra, «ahora» y cronómetro | ✅ | |
| Historial de corridas | ✅ | lista Odoo |
| Corrida detenida con error, conservando lo leído | ✅ | |
| Delta «qué cambió» entre dos corridas | 🔒 | cartel en el formulario de la corrida; llega con **E2** |
| «Detener después de este repo» | 🔒 | botón apagado en la cabecera mientras corre; llega con **E1** |

## 4a · Plantillas de política

| elemento | estado | dónde |
|---|---|---|
| Formulario con cada exigencia en castellano y su clave técnica | ✅ | |
| Exigencia que no se puede leer, marcada como tal | ✅ | firma de commits |
| Versionado y rastro de cambios | ✅ | chatter nativo |
| Botones inteligentes (repos gobernados, hallazgos) | ✅ | |
| Columna «Incumplen hoy» por exigencia | 📋 | ítem de plan, **B1** |

## 4b · Reglas de clasificación y de rol de rama

| elemento | estado | dónde |
|---|---|---|
| Dos tablas, la primera que matchea gana | ✅ | |
| Orden por arrastre | ✅ | `widget="handle"` de Odoo |
| Regla desactivable | ✅ | |
| Ramas sin rol, listadas y no ocultadas | ✅ | |
| Columna «Decide hoy» | 📋 | ítem de plan, **E4** — una lista Odoo no admite un bloque apagado; el casillero llega con la pantalla |
| Columna «Tapada por» | 📋 | ítem de plan, **E4** — ídem |
| Recálculo en vivo mientras se arrastra | 📋 | ítem de plan, **E4** — ídem |

## 4c · Personas

| elemento | estado | dónde |
|---|---|---|
| Cuenta, empleado vinculado, accesos en una tabla | ✅ | |
| «Le llega por» (directo o equipo) | ✅ | campo `source` |
| Cuentas sin dueño, siempre críticas | ✅ | |
| Asistente que propone el vínculo sin decidirlo | ✅ | |
| Firma configurada | 🔒 | el permiso para leer firmas no está concedido; se dice, no se supone |
| «Según su rol» por repositorio | ✅ | política + permiso máximo |

## 4d · Configuración

| elemento | estado | dónde |
|---|---|---|
| Conexión con su estado y credencial | ✅ | |
| Permisos concedidos | ✅ | y ahora también en `chequeo_de_cierre` |
| Parámetros (ventana de convención, umbrales) | ✅ | |
| Diagnóstico en vivo | ✅ | incluida la cadena de la bitácora |
| Cuota de API | ✅ | el cliente la registra |
| Auditoría programada | ✅ | cron |
| Notificaciones | 🔒 | llega con **E3** |
| Pausa entre operaciones al aplicar | 🔒 | va con «detener», **D2.6** |

## 5a–5d · Módulos, seguridad e higiene, forks

| elemento | estado | dónde |
|---|---|---|
| Inventario de módulos: dónde vive cada uno | ✅ | D1 |
| Duplicados y divergencia por hash | ✅ | D1.3 |
| Promoción de un módulo | ✅ | pantalla propia, se abre desde el módulo del inventario |
| Elegir qué versión gana con copias divergentes | ✅ | elección forzada, sin preselección |
| «Si elegís ésta» — qué desaparece, antes de aprobar | ✅ | con los hechos del inventario |
| «Ver el diff A ↔ C» | ✅ | bajo pedido, sobre un par ya elegido |
| Etiqueta «referencia» en una de las copias | ↔️ | **desvío deliberado**: se quitó por instrucción explícita — cualquier distintivo funciona como recomendación, y el punto de la pantalla es que nadie elija por el que mira |
| «Llevar las diferencias como PR aparte» | 📋 | ítem de plan, **F4** — abrir PRs desde la app es F4 |
| Paso 1 · elegir destino con su explicación por repo | ✅ | selector; la explicación por repositorio llega con B1 |
| Aviso de despliegue (addons_path) | ✅ | queda en el plan, antes de aprobar |
| Tarea manual «reconfigurar instancias» con lista de instancias | 📋 | ítem de plan, **F6** — nombrar instancias necesita el puente con PCM |
| Hallazgos de seguridad (secretos, dependencias) | ✅ | B6: la de hallazgos filtrada, con los tres estados |
| Higiene (ramas, repos a archivar) | 🔒 | casillero, **bloque E** |
| Forks y su upstream | 🔒 | casillero, **bloque C** |

## 7a · Modo oscuro *(llegó el 6-sep-2026)*

| elemento | estado | dónde |
|---|---|---|
| Neutrales dark (bg, surface, border, las tres tintas) | ✅ | `tokens.dark.scss`, valor por valor de la tabla |
| `--rm-surface-2` — encabezados de grupo y celdas de antes/después | ✅ | token nuevo, en los dos modos |
| `--rm-accent-solid` y su texto | ✅ | token nuevo; el acento de TEXTO se aclara en oscuro y un relleno de ese color sería ilegible |
| `--rm-unread-bg` — la base de la trama | ✅ | token nuevo; la trama se invierte sola |
| Acento dark (enlaces, foco, tinte) | ✅ | |
| Severidad · sólidos recalibrados | ✅ | crítico sube, medio e informativo bajan |
| Severidad · tenues dark | ✅ | |
| Severidad · **borde tenue** (columna nueva) | ✅ | sólo tabulada en dark; en claro toma el borde neutro |
| Severidad · **texto sobre tenue** (columna nueva) | ✅ | sólo tabulada en dark; en claro es el propio sólido |
| Estados dark (live, done, error y sus tintes) | ✅ | |
| Trama invertida: rayas claras sobre `--rm-unread-bg` | ✅ | la forma no cambia —135°, 2 px— así se reconoce igual |
| Regla 1 · el chip de severidad invierte su texto | ✅ | vía `--rm-chip-ink`; único cambio de estructura |
| Regla 2 · nada se apaga con opacidad | ✅ | escrita en `tokens.scss`; los tenues son colores propios |
| Regla 3 · el modo lo decide Odoo, ningún componente pregunta | ✅ | bundle `web.assets_web_dark` de Odoo 19 Enterprise |
| Jerarquía crítico > alto > medio > informativo en oscuro | ✅ | verificada en pantalla; si se retoca un nivel se vuelve a medir |
| `--rm-accent-dark` en oscuro | ↔️ | **decisión de traducción**: la tabla nueva no lo trae. Se usa como color de TEXTO sobre tinte, así que en oscuro toma el valor del acento; un «pizarra oscuro» sobre tinte oscuro sería ilegible |

**Verificado en Chromium con el tema oscuro de Odoo activo**, en las cuatro pantallas del
tramo: bundle oscuro servido, `--rm-bg` en `#14171C`, tarjetas en `#1C2027`, texto en
`#E7EAEF`, y el chip crítico en `#FF7A73` con texto `#14171C`. La isla clara desapareció.

## 6a–6c · F4 y notificaciones

| elemento | estado | dónde |
|---|---|---|
| Promoción entre ramas | 🔒 | casillero, **F4** |
| Pull requests desde la app | 🔒 | casillero, **F4** |
| Crear rama desde una tarea | 🔒 | casillero, **F4** |
| Crear repositorio | ✅ | B5: asistente de tres pasos que arma un plan |
| · Paso 1 · nombre derivado de la convención | ✅ | prefijo por clasificación, con su ida y vuelta probada |
| · Paso 2 · lo que se va a crear, enumerado | ✅ | resumen que promete el mismo número de operaciones que arma |
| · Paso 3 · revisión y salida al plan | ✅ | «Revisar el plan y crear» — no escribe: arma el plan |
| · La creación es irreversible y lo dice | ✅ | tipeo del nombre; el rollback **jamás** borra un repositorio |
| · Encadenamiento de las diez operaciones | ✅ | barrera `depends_on_ids` de D2.0; verificado aplicando contra el sandbox |
| · Dependabot nace encendido | ✅ | operación propia; medido: la App de escritura puede |
| · Rama por defecto puesta por el plan | ✅ | operación N+2, tras crear la rama de producción |
| · «Nace con cero hallazgos» | ✅ | Verificado contra el sandbox: nace con dos, y los dos dicen la verdad — a la instalación de `prm-sandbox` le faltan los permisos de seguridad que sí tiene `primateuy`. No es deuda del módulo; con esa aprobación queda en cero. Medido en `ENSAYO-B5.4.md` |
| Notificaciones (tres canales) | 🔒 | casillero, **E3** |

## 6d · Especificación de drag & drop

| elemento | estado | dónde |
|---|---|---|
| Uso 1 · hallazgos → plan | ✅ | con sus cuatro estados |
| Uso 2 · reordenar reglas | ✅ | con el handle de Odoo, sin el recálculo en vivo (E4) |
| Uso 3 · promover entre ramas | 🔒 | **F4** |
| Umbral de 4 px | ✅ | el del navegador |
| Sin auto-scroll agresivo · bandeja sticky | ✅ | |
| Nada se guarda a mitad de gesto | ✅ | y probado |
| Ningún arrastre escribe en GitHub | ✅ | y probado |
| Lo destructivo no se arrastra | ✅ | el arrastre arma planes, no los aplica |

## 6e · Guía de tono para pantallas no diseñadas

| elemento | estado | dónde |
|---|---|---|
| Criterios de tono aplicados a lo no diseñado | ✅ | vocabulario compartido en `components.scss` |

---

# Los siete que aparecieron, y adónde fueron

Éstos estaban en ⛔ cuando se hizo el recorrido: el diseño los muestra y el producto no los
representaba de ninguna forma — ni pantalla, ni casillero. **Ninguno quedó así.**

| # | qué falta | qué se hace |
|---|---|---|
| 1 | **Delta en los tres números del panel** («▲ 6 puntos desde la anterior»). El panel compara contra la corrida anterior en su diseño; hoy muestra el valor de hoy y nada más. | → **casillero apagado con E2**, junto al de «comparar con la anterior», que es el mismo dato |
| 2 | **Los dos avisos permanentes de la barra**: auditoría en curso, y plan esperando tu aprobación. Son los únicos dos avisos globales del diseño y hoy no existen en ninguna pantalla. | → **ítem de plan, E4**: es un componente de systray de Odoo, no una pantalla |
| 3 | **Dos puertas de entrada** (gerencia aterriza en el panel, técnica en hallazgos, definido en el usuario). | → **ítem de plan, E4**: es configuración de la acción de inicio por grupo |
| 4 | **«Sacar la 04 del plan y aprobar el resto»** como salida explícita del plan. Hoy se puede borrar la operación desde la pestaña Detalle, pero la salida no está ofrecida donde se decide. | → **se implementa en D2.3**, que ya toca esa pantalla |
| 5 | **«Regla que incumple» y «Evidencia leída de GitHub»** en el hallazgo expandido. Los datos existen (`expected_json`, `observed_json`) y la pantalla no los muestra. | → **se implementa en D2.3**: es mostrar dos campos que ya están |
| 6 | **«Exige … · Tiene …» por rama** en el formulario de repositorio. Es la comparación que hace legible por qué una rama incumple. | → **ítem de plan, B1**, que es cuando la política se aplica por plantilla |
| 7 | **Columna «Incumplen hoy»** por exigencia en la plantilla de política. | → **ítem de plan, B1**, mismo tramo |

**Cuatro pasan a casillero o se implementan en el próximo tramo; tres van al plan** con su
bloque. Ninguno queda sin representación después de este commit.

---

## Desvíos deliberados de B5 (8-sep-2026)

| lo que dice el diseño | lo que hace el producto | por qué |
|---|---|---|
| «Permisos por equipo: `@primateuy/dev` escribe» | **Grants por persona** | Los teams no existen en una cuenta de usuario. **El paso a teams es parte del procedimiento de migración** — no se adelanta por separado |
| «9 operaciones, **todas reversibles**» | Ocho reversibles; **crear el repositorio no lo es** | Revertirla sería borrar un repositorio, y entre que el rollback lee y borra cabe un push de otro. **La realidad corrige al diseño hacia la honestidad** |

Y una tercera diferencia que no es desvío sino límite: el asistente **no puede crear
repositorios en una cuenta de usuario** —GitHub no expone el endpoint para una App—, así
que en `primateuy` la pantalla existe y se niega con el motivo. Funciona en la
organización, que es donde se ensaya. Ver spec §10.1.5.
