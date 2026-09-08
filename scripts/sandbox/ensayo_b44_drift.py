# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B4.4 · el drift externo contra GitHub real, con sus dos caras de resolución.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/ensayo_b44_drift.py

Un desvío se puede cerrar de dos maneras y las dos tienen que funcionar:

  · **por reversión externa** — alguien deshace el cambio en GitHub;
  · **por reaplicación desde el plan** — el módulo vuelve a poner lo que había, usando el
    payload del hallazgo.

La segunda es, además, la PRIMERA CORRIDA REAL del único `remediation_payload` ejecutable
del catálogo: hasta acá su ejecutabilidad era un argumento escrito, no un hecho medido.

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

from odoo import fields

from odoo.addons.primate_repo_manager.models.repo_write_apply import (
	_definicion_comparable,
)

BACKEND_ID = 188
REPO = "prm-sandbox/sbx-cliente-publico"
SELLO = time.strftime("%Y%m%d-%H%M%S")
NUESTRO = "primate/ensayo-b44/base"
RAMA = "refs/heads/ensayo-b44"
LIDER = "desarrollo@primate.uy"

lider = env["res.users"].search([("login", "=", LIDER)], limit=1)
assert lider, "no está el usuario con rol de líder"
env = env(user=lider)

backend = env["repo.backend"].browse(BACKEND_ID)
repo = env["repo.repository"].search([("full_name", "=", REPO)], limit=1)
cliente = backend.write_client()
Log = env["repo.audit.log"]

fase = [0]
def titulo(texto):
	fase[0] += 1
	print("\n" + "=" * 78)
	print("FASE %s · %s" % (fase[0], texto))
	print("=" * 78)

def linea(clave, valor):
	print("   %-40s %s" % (clave + ":", valor))

def definicion(aprobaciones):
	return {
		"name": NUESTRO, "target": "branch", "enforcement": "active",
		"bypass_actors": [{"actor_id": int(backend.write_app_id),
						   "actor_type": "Integration", "bypass_mode": "always"}],
		"conditions": {"ref_name": {"include": [RAMA], "exclude": []}},
		"rules": [{"type": "pull_request", "parameters": {
			"required_approving_review_count": aprobaciones,
			"require_code_owner_review": False,
			"dismiss_stale_reviews_on_push": False,
			"require_last_push_approval": False,
			"required_review_thread_resolution": False,
		}}],
	}

def sincronizar():
	"""Lo que hace la auditoría con los rulesets, y sólo eso."""
	listado = cliente.get("/repos/%s/rulesets" % REPO) or []
	repo._sync_rulesets_propios(cliente, listado, [])
	env.cr.commit()

def auditar():
	"""Una corrida cerrada, como la que produce los hallazgos de verdad."""
	corrida = env["repo.audit.run"].create({
		"name": "Ensayo B4.4 %s" % SELLO, "backend_id": backend.id, "state": "done",
		"finished_at": fields.Datetime.now(),
	})
	env["repo.audit.engine"].evaluate(corrida)
	env.cr.commit()
	return corrida.finding_ids.filtered(
		lambda h: h.finding_type == "policy_drift_external"
		and h.subject == NUESTRO)

def estado():
	return Log._estado_de_drift(repo, NUESTRO) or "sin entradas"

def entradas(tipo):
	"""Entradas de ESTE ruleset, no del repositorio entero.

	Contarlas por repositorio mezclaba las de otros ensayos —el de B1.6 dejó su propia
	referencia— y daba un rojo que no era del código. El rojo sí sirvió para encontrar un
	defecto de verdad: ver el ensayo.
	"""
	return len(Log.search([
		("repository_id", "=", repo.id), ("event_type", "=", tipo),
	]).filtered(lambda e: (e._payload() or {}).get("ruleset") == NUESTRO))

creado = None
veredictos = {}
try:
	titulo("Sembrar el ruleset y dejar la marca de «esto aplicamos»")
	creado = cliente.post("/repos/%s/rulesets" % REPO, definicion(2))
	plan = env["repo.write.plan"].create(
		{"name": "Ensayo B4.4 alta %s" % SELLO, "backend_id": backend.id})
	env["repo.write.operation"].create({
		"plan_id": plan.id, "kind": "ruleset_update", "repository_id": repo.id,
		"target": NUESTRO, "payload_json": json.dumps(definicion(2)),
	})
	plan._aprobar(confirmadas=plan.operation_ids.filtered(
		lambda o: o.is_destructive or o.is_irreversible))
	env.cr.commit()
	plan.action_apply()
	env.cr.commit()
	linea("id del ruleset", creado["id"])
	linea("estado de la operación", plan.operation_ids.state)
	linea("la referencia quedó en la bitácora",
		  bool(Log._ultimas_escrituras_de_ruleset(repo)))
	sincronizar()
	linea("hallazgos de drift tras aplicar", len(auditar()))
	veredictos["sin_desvio_no_hay_hallazgo"] = not auditar()

	titulo("EL CAMBIO EXTERNO — alguien toca GitHub por fuera del embudo")
	cliente.put("/repos/%s/rulesets/%s" % (REPO, creado["id"]), definicion(1))
	linea("aprobaciones ahora en GitHub", 1)
	sincronizar()
	hallazgos = auditar()
	linea("hallazgos de drift", len(hallazgos))
	if hallazgos:
		linea("resumen", hallazgos[0].summary[:110])
		linea("severidad", hallazgos[0].severity)
		linea("planificable", hallazgos[0].can_be_planned)
		linea("propone", hallazgos[0].remediation_action)
	linea("estado del desvío", estado())
	linea("entradas drift_detected", entradas("drift_detected"))
	veredictos["aparece"] = bool(hallazgos) and estado() == "drift_detected"

	titulo("Auditar OTRA VEZ el mismo desvío — no puede duplicar la entrada")
	# EL DELTA, no el total: el nombre del ruleset se repite entre corridas del ensayo,
	# así que el acumulado histórico crece y no dice nada sobre esta corrida. Medir el
	# total daba un rojo que no era del código — el mismo error de medición que ya me
	# comió tres mutaciones.
	antes = entradas("drift_detected")
	sincronizar(); auditar()
	despues = entradas("drift_detected")
	linea("entradas antes / después", "%s / %s" % (antes, despues))
	veredictos["no_duplica"] = despues == antes

	titulo("CARA 1 · se resuelve por REVERSIÓN EXTERNA")
	cliente.put("/repos/%s/rulesets/%s" % (REPO, creado["id"]), definicion(2))
	sincronizar()
	linea("hallazgos de drift", len(auditar()))
	linea("estado del desvío", estado())
	linea("entradas drift_resolved", entradas("drift_resolved"))
	veredictos["cierra_por_reversion_externa"] = (
		not auditar() and estado() == "drift_resolved")

	titulo("Volver a romperlo, para la segunda cara")
	cliente.put("/repos/%s/rulesets/%s" % (REPO, creado["id"]), definicion(1))
	sincronizar()
	hallazgos = auditar()
	linea("hallazgos de drift", len(hallazgos))
	linea("estado del desvío", estado())
	veredictos["reabre"] = bool(hallazgos) and estado() == "drift_detected"

	titulo("CARA 2 · se resuelve REAPLICANDO DESDE EL PLAN")
	print("   Primera corrida real del único remediation_payload ejecutable del catálogo.")
	hallazgo = hallazgos[0]
	plan_remediacion = hallazgo._plan_de_remediacion() if hasattr(
		hallazgo, "_plan_de_remediacion") else None
	if plan_remediacion is None:
		plan_remediacion = env["repo.write.plan"].create(
			{"name": "Ensayo B4.4 remediar %s" % SELLO, "backend_id": backend.id})
		env["repo.write.operation"].create({
			"plan_id": plan_remediacion.id,
			"kind": "ruleset_update", "repository_id": repo.id,
			"target": hallazgo.subject,
			"payload_json": hallazgo.remediation_payload,
		})
	linea("payload que se va a ejecutar", "el del hallazgo, tal cual")
	plan_remediacion._aprobar(confirmadas=plan_remediacion.operation_ids.filtered(
		lambda o: o.is_destructive or o.is_irreversible))
	env.cr.commit()
	plan_remediacion.action_apply()
	env.cr.commit()
	operacion = plan_remediacion.operation_ids
	linea("estado de la operación", operacion.state)
	linea("error", operacion.error or "—")
	veredictos["payload_del_hallazgo_es_ejecutable"] = operacion.state == "applied"

	sincronizar()
	linea("hallazgos de drift después de remediar", len(auditar()))
	linea("estado del desvío", estado())
	linea("entradas drift_resolved", entradas("drift_resolved"))
	veredictos["cierra_por_reaplicacion"] = (
		not auditar() and estado() == "drift_resolved")

	titulo("El ruleset, al final")
	final = _definicion_comparable(
		cliente.get("/repos/%s/rulesets/%s" % (REPO, creado["id"])))
	linea("aprobaciones exigidas",
		  final["rules"][0]["parameters"]["required_approving_review_count"])
	veredictos["quedo_como_se_aplico"] = (
		final["rules"][0]["parameters"]["required_approving_review_count"] == 2)

finally:
	titulo("Limpieza")
	if creado:
		cliente.delete("/repos/%s/rulesets/%s" % (REPO, creado["id"]), tolerar_404=True)
		linea("borrado", creado["id"])
	env.cr.commit()

print("\n" + "=" * 78)
print("VEREDICTO DEL ENSAYO")
print("=" * 78)
for clave, ok in veredictos.items():
	print("   %s  %s" % ("[OK] " if ok else "[MAL]", clave))
print("\n%s" % ("TODO BIEN" if all(veredictos.values())
				else "HAY AL MENOS UN PUNTO EN ROJO"))
