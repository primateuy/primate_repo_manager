# Ensayo de B4.4 — el drift externo contra GitHub, y sus dos caras de resolución

**Cuándo:** 7 de septiembre de 2026 · **Contra:** `prm-sandbox/sbx-cliente-publico`
**Script:** `scripts/sandbox/ensayo_b44_drift.py`

Un desvío se cierra de dos maneras y las dos tenían que funcionar: **por reversión
externa** —alguien deshace el cambio en GitHub— y **por reaplicación desde el plan**. La
segunda era además la **primera corrida real del único `remediation_payload` ejecutable
del catálogo**: hasta acá su ejecutabilidad era un argumento escrito, no un hecho medido.

## Las ocho fases

| # | Fase | Resultado |
|---|---|---|
| 1 | Sembrar el ruleset y dejar la referencia (`write_applied`) | `applied` · 0 hallazgos de drift |
| 2 | El cambio externo: se baja a 1 aprobación por fuera del embudo | 1 hallazgo · **alto** · planificable · propone `reapply_ruleset` |
| 3 | Auditar otra vez el mismo desvío | entradas: **6 → 6**, no duplica |
| 4 | **Cara 1** · reversión externa | 0 hallazgos · `drift_resolved` |
| 5 | Volver a romperlo | 1 hallazgo · `drift_detected` |
| 6 | **Cara 2** · reaplicar desde el plan, con el payload del hallazgo | `applied` · 0 hallazgos · `drift_resolved` |
| 7 | El ruleset al final | 2 aprobaciones — como se había aplicado |
| 8 | Limpieza | borrado |

**El payload del hallazgo se ejecutó tal cual, sin tocarlo.** El argumento que lo hace la
única excepción a «`remediation_payload` identifica, no configura» dejó de ser un
argumento: se ejecutó contra GitHub y quedó verificado por relectura.

---

## Los dos defectos que el ensayo encontró

Ninguno de los dos era visible con un doble, y el segundo **sólo aparece corriendo dos
veces**.

### 1 · Un ruleset dado de baja seguía siendo referencia para siempre

La bitácora es inmutable y decía la verdad —«esto aplicamos»—, pero el drift leía sólo las
altas y actualizaciones. Un ruleset que el módulo aplicó y después **dio de baja** seguía
siendo referencia, así que cada auditoría reportaba «lo aplicamos y ya no está», con
severidad crítica, para siempre.

**Un desvío que nadie puede cerrar es ruido permanente, y el ruido permanente enseña a
ignorar la lista entera.**

Quedó arreglado leyendo **lo último que se le hizo a cada ruleset**, sea lo que sea: si lo
último fue darlo de baja, deja de ser referencia. `ruleset_delete` todavía no tiene
manejador, así que hoy no se dispara por el embudo — la regla está igual, porque no
depende del manejador.

*Cómo apareció:* el ensayo de B1.6 había borrado su ruleset por fuera del módulo, y su
referencia seguía viva en la bitácora del sandbox.

### 2 · El ruleset recreado y la fila homónima muerta

Borrado y vuelto a crear con el mismo nombre, GitHub le da un **id nuevo**. El espejo
quedaba con dos filas del mismo nombre —la vieja dada de baja y la nueva viva— y el drift,
que busca **por nombre**, tocaba la muerta: alarma **crítica** «el ruleset que aplicamos ya
no está» sobre uno que estaba ahí.

Es la peor forma del falso positivo: la que grita más fuerte. Una alarma crítica sobre algo
sano enseña a desconfiar de las alarmas críticas.

Quedó arreglado por los dos lados: el upsert **retira los homónimos** al escribir —un
ruleset recreado con el mismo nombre es, para la política, el mismo objeto gobernado— y la
búsqueda del drift **prefiere la fila viva**.

*Cómo apareció:* corriendo el ensayo una segunda vez. La primera corrida no podía verlo.

### Y un tercer rojo que era del medidor, no del código

`no_duplica` contaba el **total histórico** de entradas para ese nombre, que crece entre
corridas del ensayo porque el nombre se repite. Medido como **delta** dentro de la corrida
—6 → 6— dice lo que tenía que decir. Es el mismo error de medición que ya se había comido
tres mutaciones en B4.2: **el número que se mira tiene que ser el de esta corrida.**
