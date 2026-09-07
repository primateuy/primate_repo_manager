# Ensayo de B1.6 — las dos guardas del ruleset, contra GitHub de verdad

**Cuándo:** 7 de septiembre de 2026 · **Contra:** `prm-sandbox/sbx-cliente-publico`, con la
App de escritura 4808079 · **Script:** `scripts/sandbox/ensayo_b16_rulesets.py`

Los tests afirmaban dos cosas: que el rollback devuelve el ruleset anterior en vez de
borrarlo, y que un ruleset ajeno no se toca. Las dos dependen de cómo responde GitHub, y
**un doble que imita media interfaz miente en la mitad que no imita.** Este ensayo las
puso a prueba contra la API real, con un testigo que tenía que salir intacto.

**Antes de escribir nada** se corrió el chequeo de cierre: *todo cerrado*, producción sin
credenciales de escritura, la App de escritura acotada a los 6 repositorios del sandbox.

---

## El testigo

Un ruleset llamado `ajeno-no-tocar-<sello>` —**sin el prefijo del módulo**— creado con una
llamada suelta a la API, no por un plan. Se guardó su definición completa al nacer y se
comparó campo a campo dos veces: después del apply y al final del ensayo entero.

> Se creó con el token de la App de escritura del sandbox, no con un PAT. Para lo que la
> guarda mira —el prefijo del nombre— da igual quién lo creó; se deja dicho igual, porque
> un ensayo que redondea cómo se sembró su testigo empieza a parecerse a lo que viene a
> desmentir.

## Las nueve fases

| # | Fase | Resultado |
|---|---|---|
| 1 | Sembrar el testigo, sin nuestro prefijo | id 22465954 |
| 2 | Sembrar el nuestro, `primate/ensayo-b16/base`, con 1 aprobación | id 22465958 |
| 3 | Plan que sube a 2 aprobaciones, aprobado **con el rol de líder** | huella `442b9eaa…` |
| 4 | Aplicar contra GitHub | `applied` · aprobaciones ahora **2** |
| 5 | El testigo, después del apply | **IDÉNTICO**, campo a campo |
| 6 | Revertir y comparar campo a campo con la definición previa | `rolled_back` · **IDÉNTICO** · el ruleset **sigue existiendo con su id** |
| 7 | Provocar la guarda: un plan apuntando al testigo | se negó: «no es un ruleset de este módulo, así que no se toca» |
| 8 | El testigo, tras apply + rollback + intento sobre él | **IDÉNTICO** |
| 9 | Limpieza | los dos borrados; el sandbox queda como estaba |

**Aprobar y aplicar fueron como una persona con el rol**, no como superusuario: el embudo
exige líder técnico para aprobar, y saltearlo desde el shell habría probado un camino que
en la aplicación no existe.

---

## El hallazgo: la primera corrida salió en rojo, y tenía razón

**Fase 4 falló con `failed`: «la escritura respondió bien pero la relectura no lo
confirma».** Y sin embargo GitHub tenía las 2 aprobaciones: la escritura había salido
exactamente como se pidió.

**La causa.** GitHub **completa el objeto con parámetros que nadie mandó** y los devuelve
al releer. En la regla de pull request apareció:

```
"allowed_merge_methods": ["merge", "squash", "rebase"]
```

La verificación comparaba por **igualdad exacta**, así que rechazó una escritura impecable.

**Por qué ningún test lo vio.** El doble devolvía lo que recibía. Es la lección que este
proyecto ya tenía escrita —«el GitHub simulado de la promoción tuvo que aprender a borrar
de verdad»— repetida en otra forma: **el doble mentía en la mitad de la interfaz que no
imitaba.**

**Y el daño no era sólo el estado en rojo.** El mismo criterio gobierna el atajo de «si ya
está como se pide, no se escribe»: comparando por igualdad, el objeto de GitHub **nunca**
coincide con el nuestro, así que ese atajo no se habría tomado jamás. La idempotencia
estaba escrita y muerta, y sólo se veía contra la API real.

### Cómo quedó

La comparación pasó a ser **«lo que pedimos, tal como lo pedimos»**, no igualdad:

- los campos sueltos que mandamos, iguales;
- los **mismos tipos de regla**, ni uno más ni uno menos — una regla que aparece sola es
  una diferencia real y tiene que fallar;
- dentro de cada regla, **cada parámetro que mandamos** con nuestro valor. Los que GitHub
  agrega por su cuenta no se miran: no los pedimos y no los gobernamos.

Sigue cazando que GitHub haya guardado otra cosa de lo pedido, que es para lo que existe.
Deja de cazar que GitHub tenga defaults, que nunca fue asunto nuestro.

**El doble aprendió la forma real** —ahora devuelve `allowed_merge_methods` sin que nadie
se la mande— y quedaron cuatro tests de regresión: los defaults no cuentan como
diferencia; un parámetro **que sí mandamos** con otro valor sigue fallando; una regla de
más es una diferencia real; y el atajo de no escribir funciona contra la forma real.

## La segunda corrida

Las mismas nueve fases, todo en verde:

    [OK] apply · [OK] rollback_devuelve · [OK] rollback_no_borra
    [OK] guarda_ajeno · [OK] testigo_intacto
