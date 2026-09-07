# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B1.6 · las dos guardas de B1.3, ejercitadas contra GitHub de verdad.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/ensayo_b16_rulesets.py

POR QUÉ CONTRA GITHUB Y NO CONTRA EL DOBLE. Los tests afirman que el rollback no borra y
que un ruleset ajeno no se toca; los dos hechos dependen de cómo responde GitHub de
verdad, y un doble que imita media interfaz miente en la mitad que no imita. Acá el
testigo es un ruleset real que tiene que salir intacto del ensayo completo.

NO TOCA PRODUCCIÓN. La conexión es la de `prm-sandbox`, y el chequeo de cierre se corre
antes. Todo lo que este ensayo crea, lo borra al terminar.

AL TERMINAR, ESTE ENSAYO DEJA UNA REFERENCIA ABIERTA — Y HAY QUE SABERLO.

La limpieza borra los rulesets con una llamada suelta a la API, o sea POR FUERA del
embudo. La bitácora queda diciendo «esto aplicamos» sin que exista un registro de la
baja, así que la próxima auditoría reporta —con razón— «lo aplicamos y ya no está».

No se arregla borrando entradas: son eslabones sellados de la cadena y `unlink` levanta
incluso con `sudo`. Se cierra de una de dos maneras: volviendo a aplicar lo que la
bitácora dice que aplicamos, o dando de baja por el embudo el día que `ruleset_delete`
tenga manejador. Ver `docs/ENSAYO-B4.4.md`.
"""
import json
import time

from odoo.exceptions import UserError

from odoo.addons.primate_repo_manager.models.repo_write_apply import (
	_definicion_comparable,
)

BACKEND_ID = 188
REPO = "prm-sandbox/sbx-cliente-publico"
SELLO = time.strftime("%Y%m%d-%H%M%S")
AJENO = "ajeno-no-tocar-%s" % SELLO          # el TESTIGO: sin nuestro prefijo
NUESTRO = "primate/ensayo-b16/base"
# Ramas inventadas a propósito: el ensayo no puede bloquear el trabajo de nadie en el
# sandbox mientras corre. Las guardas no dependen de que la rama exista.
RAMA_AJENA = "refs/heads/ensayo-b16-ajena"
RAMA_NUESTRA = "refs/heads/ensayo-b16-nuestra"

# APROBAR Y APLICAR VAN COMO UNA PERSONA CON EL ROL, no como superusuario. El embudo
# exige rol de líder técnico para aprobar, y saltearlo desde el shell probaría un camino
# que en la aplicación no existe — justo lo que un ensayo no puede hacer.
LIDER = "desarrollo@primate.uy"
lider = env["res.users"].search([("login", "=", LIDER)], limit=1)
assert lider, "no está el usuario con rol de líder: %s" % LIDER
env = env(user=lider)

backend = env["repo.backend"].browse(BACKEND_ID)
repo = env["repo.repository"].search([("full_name", "=", REPO)], limit=1)
cliente = backend.write_client()
# La misma normalización que usa el apply: se comparan los seis campos que
# gobernamos, no los que GitHub agrega por su cuenta.
comparable = _definicion_comparable

fase = [0]
def titulo(texto):
	fase[0] += 1
	print("\n" + "=" * 78)
	print("FASE %s · %s" % (fase[0], texto))
	print("=" * 78)

def linea(clave, valor):
	print("   %-34s %s" % (clave + ":", valor))

def definicion(nombre, aprobaciones, rama):
	return {
		"name": nombre, "target": "branch", "enforcement": "active",
		"bypass_actors": [{"actor_id": int(backend.write_app_id),
						   "actor_type": "Integration", "bypass_mode": "always"}],
		"conditions": {"ref_name": {"include": [rama], "exclude": []}},
		"rules": [{"type": "pull_request", "parameters": {
			"required_approving_review_count": aprobaciones,
			"require_code_owner_review": False,
			"dismiss_stale_reviews_on_push": False,
			"require_last_push_approval": False,
			"required_review_thread_resolution": False,
		}}],
	}

def leer(id_ruleset):
	return cliente.get("/repos/%s/rulesets/%s" % (REPO, id_ruleset))

def campo_a_campo(esperada, actual, que):
	"""Compara campo por campo y devuelve la lista de diferencias."""
	diferencias = []
	for campo in ("name", "target", "enforcement", "bypass_actors", "conditions", "rules"):
		if esperada.get(campo) != actual.get(campo):
			diferencias.append(campo)
		print("   %-14s %-9s %s" % (
			campo, "IGUAL" if campo not in diferencias else "DISTINTO",
			json.dumps(actual.get(campo), ensure_ascii=False, sort_keys=True)[:120]))
	print("   → %s: %s" % (que, "IDÉNTICO" if not diferencias else
						   "CAMBIÓ EN %s" % ", ".join(diferencias)))
	return diferencias

creados = []
veredictos = {}
try:
	titulo("Sembrar el TESTIGO — un ruleset que el módulo no puso")
	testigo = cliente.post("/repos/%s/rulesets" % REPO,
						   definicion(AJENO, 1, RAMA_AJENA))
	creados.append(testigo["id"])
	testigo_previo = comparable(leer(testigo["id"]))
	linea("nombre", AJENO)
	linea("id", testigo["id"])
	linea("lleva nuestro prefijo", AJENO.startswith("primate/"))
	print("   Creado con una llamada suelta a la API, NO por un plan del módulo.")

	titulo("Sembrar el NUESTRO — el que el plan va a actualizar")
	nuestro = cliente.post("/repos/%s/rulesets" % REPO,
						   definicion(NUESTRO, 1, RAMA_NUESTRA))
	creados.append(nuestro["id"])
	previo = comparable(leer(nuestro["id"]))
	linea("nombre", NUESTRO)
	linea("id", nuestro["id"])
	linea("aprobaciones exigidas", previo["rules"][0]["parameters"]
		  ["required_approving_review_count"])

	titulo("El plan: subir de 1 a 2 aprobaciones, aprobado como lo aprueba una persona")
	plan = env["repo.write.plan"].create(
		{"name": "Ensayo B1.6 %s" % SELLO, "backend_id": backend.id})
	operacion = env["repo.write.operation"].create({
		"plan_id": plan.id, "kind": "ruleset_update", "repository_id": repo.id,
		"target": NUESTRO,
		"payload_json": json.dumps(definicion(NUESTRO, 2, RAMA_NUESTRA)),
	})
	plan._aprobar(confirmadas=plan.operation_ids.filtered("is_destructive"))
	env.cr.commit()
	linea("plan", plan.name)
	linea("huella de aprobación", (plan.approval_fingerprint or "")[:16] + "…")
	linea("se puede aplicar", operacion.is_supported)

	titulo("Aplicar contra GitHub")
	plan.action_apply()
	env.cr.commit()
	linea("estado de la operación", operacion.state)
	linea("error", operacion.error or "—")
	despues = comparable(leer(nuestro["id"]))
	linea("aprobaciones ahora", despues["rules"][0]["parameters"]
		  ["required_approving_review_count"])
	veredictos["apply"] = operacion.state == "applied"

	titulo("El TESTIGO, después del apply")
	campo_a_campo(testigo_previo, comparable(leer(testigo["id"])), "el testigo tras aplicar")

	titulo("Revertir — y comparar la definición restaurada CAMPO A CAMPO")
	plan.action_rollback()
	env.cr.commit()
	linea("estado de la operación", operacion.state)
	restaurada = comparable(leer(nuestro["id"]))
	linea("el ruleset SIGUE EXISTIENDO con su id", nuestro["id"])
	diferencias = campo_a_campo(previo, restaurada, "la definición restaurada vs la previa")
	veredictos["rollback_devuelve"] = not diferencias
	veredictos["rollback_no_borra"] = bool(leer(nuestro["id"]).get("id"))

	titulo("Provocar la guarda: un plan que apunta al TESTIGO")
	plan_ajeno = env["repo.write.plan"].create(
		{"name": "Ensayo B1.6 ajeno %s" % SELLO, "backend_id": backend.id})
	env["repo.write.operation"].create({
		"plan_id": plan_ajeno.id, "kind": "ruleset_update", "repository_id": repo.id,
		"target": AJENO, "payload_json": json.dumps(definicion(AJENO, 2, RAMA_AJENA)),
	})
	plan_ajeno._aprobar(confirmadas=plan_ajeno.operation_ids.filtered("is_destructive"))
	env.cr.commit()
	try:
		plan_ajeno.action_apply()
		linea("RESULTADO", "NO se negó — la guarda no funcionó")
		veredictos["guarda_ajeno"] = False
	except UserError as exc:
		linea("se negó con", str(exc).split("\n")[0][:150])
		veredictos["guarda_ajeno"] = True
	env.cr.rollback()

	titulo("El TESTIGO, al final del ensayo completo")
	final = campo_a_campo(testigo_previo, comparable(leer(testigo["id"])),
						  "el testigo tras apply + rollback + intento sobre él")
	veredictos["testigo_intacto"] = not final

finally:
	titulo("Limpieza — el sandbox queda como estaba")
	for id_ruleset in creados:
		cliente.delete("/repos/%s/rulesets/%s" % (REPO, id_ruleset), tolerar_404=True)
		linea("borrado", id_ruleset)
	env.cr.commit()

print("\n" + "=" * 78)
print("VEREDICTO DEL ENSAYO")
print("=" * 78)
for clave, ok in veredictos.items():
	print("   %s  %s" % ("[OK] " if ok else "[MAL]", clave))
print("\n%s" % ("TODO BIEN" if all(veredictos.values()) else "HAY AL MENOS UN PUNTO EN ROJO"))
