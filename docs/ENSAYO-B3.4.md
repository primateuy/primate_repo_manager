# Ensayo de B3.4 — los cuatro estados del CODEOWNERS, contra GitHub

**Cuándo:** 7 de septiembre de 2026 · **Contra:** `prm-sandbox/sbx-cliente-publico`
**Script:** `scripts/sandbox/ensayo_b34_codeowners.py`

El archivo es **uno solo** y el que está tapa a cualquier otro, así que su guarda del ajeno
carga más peso que la del ruleset ajeno. Y el estado intermedio —el nuestro editado a
mano— es el que decide si el módulo respeta el trabajo de otro o lo pisa en cuotas.

## Las cinco fases

| # | Estado | Resultado |
|---|---|---|
| 1 | **Ausente** | se escribe · `applied` |
| 2 | **Nuestro**, ya igual | `applied` **sin escribir** — «sin cambios: ya estaba como se pedía» |
| 3a | **Editado**, sin confirmación | **se niega** · la línea de otro sigue en GitHub |
| 3b | **Editado**, con la diferencia y su confirmación | se escribe · la línea se pierde, habiéndola visto |
| 4 | **Ajeno** | **se niega** · el ajeno queda intacto |
| 5 | Limpieza | el archivo se borra; el repositorio queda como estaba |

## Lo que se le muestra a quien decide

```
Alguien agregó a mano: docs/ → @otra-persona
```

No un diff. **La pregunta de quien mira no es «qué bytes difieren» sino «qué trabajo de
otro se va».** Es la misma vara de D2.4, donde la pantalla que elige entre copias
divergentes dice qué desaparece si elegís, no qué hash cambió.

La cabecera que reescribimos nosotros —lleva la fecha— **no cuenta como edición ajena**:
mostrarla como cambio de otro sería acusar a alguien del ruido que hacemos nosotros. Se
comparan las líneas de owner, no el texto entero.

## Y la confirmación viaja dentro de la huella

`perder_ediciones` y el texto de lo que se pierde van en el payload, así que entran en la
huella que congela el plan al aprobarlo. Fuera de ella se podrían prender **después** de
aprobar — y aprobar habría sido firmar un cheque en blanco sobre el trabajo de otro. Se
exigen las dos cosas: la decisión **y** la diferencia que la fundamenta.

**Veredicto: todo bien**, los seis puntos en verde.
