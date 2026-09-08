# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B5.4 · el nacimiento gobernado, entero, contra GitHub.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/ensayo_b54_nacimiento.py

El asistente arma el plan, se aprueba con el tipeo del irreversible, se aplica encadenado
por la barrera, y la primera auditoría mira al recién nacido. **El objetivo es el cero sin
asterisco**: si encuentra algo, es un hallazgo del producto y se reporta tal cual.

LA LIMPIEZA NO LA HACE EL MÓDULO. Este módulo no borra repositorios —es la decisión de
B5.1— así que el ensayo lo borra con una llamada suelta, por fuera del embudo, y lo dice.
"""
import time

from odoo import fields
from odoo.exceptions import UserError

BACKEND_ID = 188
LIDER = "desarrollo@primate.uy"
SELLO = time.strftime("%H%M%S")
BASE = "Ensayo B54 %s" % SELLO

lider = env["res.users"].search([("login", "=", LIDER)], limit=1)
assert lider, "no está el usuario con rol de líder"
env = env(user=lider)
backend = env["repo.backend"].browse(BACKEND_ID)

fase = [0]
def titulo(t):
	fase[0] += 1
	print("\n" + "=" * 78); print("FASE %s · %s" % (fase[0], t)); print("=" * 78)

def linea(k, v):
	print("   %-44s %s" % (k + ":", v))

veredictos = {}
creado = None
try:
	titulo("El asistente: tres pasos, y lo que promete")
	asistente = env["repo.repository.create.wizard"].create({
		"backend_id": backend.id, "base": BASE, "classification": "cliente",
		"version": "19.0", "private": True,
	})
	linea("nombre previsto", asistente.nombre_previsto)
	linea("problema", asistente.problema or "—")
	prometidas = env["repo.write.plan"].resumen_de_nacimiento({
		"base": BASE, "clasificacion": "cliente", "version": "19.0", "privado": True,
	})["operaciones"]
	linea("operaciones prometidas", prometidas)

	titulo("El plan armado — sin escribir nada todavía")
	accion = asistente.action_armar_plan()
	plan = env["repo.write.plan"].browse(accion["res_id"])
	env.cr.commit()
	linea("estado del plan", plan.state)
	linea("operaciones armadas", len(plan.operation_ids))
	veredictos["promete_lo_que_arma"] = prometidas == len(plan.operation_ids)
	for op in plan.operation_ids.sorted("sequence"):
		depende = ", ".join(str(d.sequence) for d in op.depends_on_ids) or "—"
		print("   %-3s %-20s %-34s depende de %s" % (
			op.sequence, op.kind, (op.target or "")[:34], depende))

	titulo("La aprobación, con el tipeo del irreversible")
	irreversibles = plan.operation_ids.filtered("is_irreversible")
	linea("irreversibles", ", ".join(irreversibles.mapped("kind")) or "ninguna")
	try:
		plan._aprobar(confirmadas=env["repo.write.operation"])
		linea("sin confirmar", "SE APROBÓ — la guarda no funcionó")
		veredictos["exige_confirmacion"] = False
	except UserError as exc:
		linea("sin confirmar se niega", str(exc).split("\n")[0][:90])
		veredictos["exige_confirmacion"] = True
	env.cr.rollback()

	plan = env["repo.write.plan"].browse(accion["res_id"])
	plan._aprobar(confirmadas=plan.operation_ids.filtered(
		lambda o: o.is_destructive or o.is_irreversible))
	env.cr.commit()
	linea("estado tras aprobar", plan.state)
	linea("huella", (plan.approval_fingerprint or "")[:16] + "…")

	titulo("El apply, encadenado por la barrera")
	try:
		plan.action_apply()
		env.cr.commit()
	except Exception as exc:
		# Un apply que levanta no puede tumbar el ensayo: lo que importa es QUÉ quedó y
		# qué dijo. Se reporta y se sigue hasta la limpieza.
		env.cr.rollback()
		plan = env["repo.write.plan"].browse(accion["res_id"])
		linea("el apply levantó", "%s: %s" % (type(exc).__name__, str(exc)[:110]))
	for op in plan.operation_ids.sorted("sequence"):
		print("   %-3s %-20s %-12s %s" % (
			op.sequence, op.kind, op.state, (op.error or "")[:60]))
	aplicadas = plan.operation_ids.filtered(lambda o: o.state == "applied")
	veredictos["todas_aplicadas"] = len(aplicadas) == len(plan.operation_ids)

	repo = plan.operation_ids.mapped("repository_id")[:1]
	creado = repo.full_name if repo else None
	linea("repositorio", creado or "no se creó")

	titulo("Lo que quedó en GitHub")
	cliente = backend.write_client()
	if creado:
		ramas = cliente.paginate("/repos/%s/branches" % creado)
		linea("ramas", ", ".join(sorted(b["name"] for b in ramas)))
		rulesets = cliente.get("/repos/%s/rulesets" % creado) or []
		linea("rulesets", ", ".join(r["name"] for r in rulesets) or "ninguno")
		try:
			cliente.get("/repos/%s/vulnerability-alerts" % creado)
			dependabot = "ENCENDIDO"
		except Exception:
			dependabot = "apagado"
		linea("Dependabot", dependabot)
		veredictos["dependabot_de_nacimiento"] = dependabot == "ENCENDIDO"

	titulo("La primera auditoría sobre el recién nacido")
	if creado:
		repo._job_sync_repository(False)
		env.cr.commit()
		corrida = env["repo.audit.run"].create({
			"name": "Primera auditoría de %s" % creado, "backend_id": backend.id,
			"state": "done", "finished_at": fields.Datetime.now()})
		env["repo.audit.engine"].evaluate(corrida)
		env.cr.commit()
		suyos = corrida.finding_ids.filtered(lambda h: h.repository_id == repo)
		linea("hallazgos sobre el recién nacido", len(suyos))
		for hallazgo in suyos:
			print("   [%s] %s" % (hallazgo.severity.upper(), hallazgo.summary[:95]))
		veredictos["cero_sin_asterisco"] = not suyos

finally:
	titulo("Limpieza — la hace el ENSAYO, no el módulo")
	print("   El módulo no borra repositorios (B5.1). Esta llamada va por fuera del")
	print("   embudo, a propósito, y por eso está acá y no en un manejador.")
	if creado:
		try:
			backend.write_client().delete("/repos/%s" % creado)
			linea("borrado", creado)
		except Exception as exc:
			linea("NO se pudo borrar", str(exc)[:100])
			linea("queda en el sandbox", creado)
		# Y la fila del espejo, que si no queda de FANTASMA. El módulo no tiene hoy
		# ninguna noción de «el repositorio ya no está»: `_sync_from_backend` upsertea
		# lo que el listado trae y no marca lo que dejó de venir, así que un repo
		# borrado en GitHub sigue en el espejo y sigue produciendo hallazgos sobre
		# ramas que no existen. Lo dejó a la vista esta serie de ensayos: seis
		# fantasmas, dieciocho hallazgos. Está anotado como hallazgo de producto; acá
		# se limpia porque es basura del ENSAYO, no porque el módulo lo resuelva.
		repo.unlink()
	env.cr.commit()

print("\n" + "=" * 78); print("VEREDICTO"); print("=" * 78)
for k, ok in veredictos.items():
	print("   %s  %s" % ("[OK] " if ok else "[MAL]", k))
print("\n%s" % ("TODO BIEN" if all(veredictos.values()) else "HAY AL MENOS UN PUNTO EN ROJO"))
