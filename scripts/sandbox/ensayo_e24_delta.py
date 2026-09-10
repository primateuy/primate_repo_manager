# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E2.4 · el delta contra GitHub real, con las TRES atribuciones ejercitadas.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/ensayo_e24_delta.py

POR QUÉ NO ALCANZA CON LOS TESTS. Las tres frases del delta —«lo corrigió PLAN-X»,
«se resolvió en la app», «se resolvió fuera de la app»— son afirmaciones sobre lo que pasó
FUERA de esta pantalla, y en los tests el «afuera» lo fabricamos nosotros. Acá cada una se
produce por su camino de verdad: un plan aplicado por el embudo contra GitHub, un acto en
Odoo sin plan, y un cambio hecho a mano en GitHub por fuera de todo.

EL GUION
  1. Se limpian las sobras de ensayos anteriores.
  2. Se prepara el escenario: dos rulesets nuestros con drift, y un repositorio que
     ninguna regla de clasificación reconoce.
  3. Corrida #1, a mano. Deja tres hallazgos.
  4. Los tres cambios, cada uno por su camino.
  5. Corrida #2, PROGRAMADA. Produce el delta y dispara el correo.
  6. Se comprueba que cada resuelto salga con la atribución que le toca.
  7. El correo: el del lunes y el de la auditoría fallida, guardados para mirarlos.

DEJA UNA REFERENCIA ABIERTA, igual que el de B4.4 y por lo mismo: la limpieza borra
rulesets por fuera del embudo. Ver `docs/ENSAYO-B4.4.md`.
"""
import json
import time

from odoo import fields

REPO_DRIFT_PLAN = "prm-sandbox/sbx-cliente-publico"
REPO_DRIFT_FUERA = "prm-sandbox/sbx-localizacion"
SELLO = time.strftime("%Y%m%d-%H%M%S")
LIDER = "desarrollo@primate.uy"

lider = env["res.users"].search([("login", "=", LIDER)], limit=1)
assert lider, "no está el usuario con rol de líder"
env = env(user=lider)

backend = env["repo.backend"].search([("environment", "=", "sandbox")], limit=1)
escritura = backend.write_client()
lectura = backend.client()
Log = env["repo.audit.log"]
Delta = env["repo.audit.delta"]

fase = [0]
def titulo(texto):
	fase[0] += 1
	print("\n" + "=" * 78)
	print("FASE %s · %s" % (fase[0], texto))
	print("=" * 78)

def linea(clave, valor):
	print("   %-44s %s" % (clave + ":", valor))

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

# EL UMBRAL DE LA BASE DE TRABAJO ESTÁ EN 0 —todo se encola— y este ensayo corre en un
# shell sin procesador de tareas detrás: las corridas quedarían «en curso» para siempre.
# Se sube para que la auditoría corra en el momento, y se deja como estaba al terminar.
# Es configuración de esta base, no del módulo.
Config = env["ir.config_parameter"].sudo()
UMBRAL_ORIGINAL = Config.get_param("repo_manager.sync_threshold")
Config.set_param("repo_manager.sync_threshold", "500")
env.cr.commit()

def auditar(origen):
	corrida = env["repo.audit.run"].create({
		"name": "E2.4 %s (%s)" % (SELLO, origen), "backend_id": backend.id,
		"origin": origen})
	corrida.action_start()
	env.cr.commit()
	return corrida

veredictos = {}
creados = []
repo_nuevo = None
try:
	titulo("Limpiar las sobras de ensayos anteriores")
	sobras = [r["full_name"] for r in lectura.paginate(
		"/installation/repositories", envoltorio="repositories")
		if r["name"].startswith(("cliente-ensayo-", "zzz-e24-"))]
	for nombre in sobras:
		try:
			escritura.delete("/repos/%s" % nombre)
			linea("borrado", nombre)
		except Exception as exc:
			linea("no se pudo borrar %s" % nombre, str(exc)[:70])
	if not sobras:
		linea("sobras", "ninguna")

	titulo("Preparar el escenario: dos drifts y un repo sin clasificar")
	nombres = {}
	for repo_full, etiqueta in ((REPO_DRIFT_PLAN, "plan"),
								(REPO_DRIFT_FUERA, "fuera")):
		repo = env["repo.repository"].search([("full_name", "=", repo_full)], limit=1)
		nombre = "primate/ensayo-e24-%s/base" % etiqueta
		rama = "refs/heads/ensayo-e24-%s" % etiqueta
		nombres[etiqueta] = (repo, nombre, rama)
		# Se aplica POR EL EMBUDO para que la bitácora diga «esto aplicamos»: sin esa
		# marca no hay contra qué comparar y el drift no existe.
		creado = escritura.post("/repos/%s/rulesets" % repo_full,
								definicion(nombre, 2, rama))
		creados.append((repo_full, creado["id"]))
		plan = env["repo.write.plan"].create({
			"name": "E2.4 alta %s %s" % (etiqueta, SELLO), "backend_id": backend.id})
		env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "ruleset_update", "repository_id": repo.id,
			"target": nombre, "payload_json": json.dumps(definicion(nombre, 2, rama))})
		plan._aprobar(confirmadas=plan.operation_ids.filtered(
			lambda o: o.is_destructive or o.is_irreversible))
		env.cr.commit()
		plan.action_apply()
		env.cr.commit()
		# Y ahora el desvío: alguien lo cambia en GitHub, por fuera.
		escritura.put("/repos/%s/rulesets/%s" % (repo_full, creado["id"]),
					  definicion(nombre, 1, rama))
		linea("drift sembrado en %s" % etiqueta, nombre)

	# Un repositorio que NINGUNA regla de clasificación reconoce.
	nombre_nuevo = "zzz-e24-%s" % SELLO[-6:]
	hecho = escritura.post("/orgs/%s/repos" % backend.owner_login,
						   {"name": nombre_nuevo, "private": True, "auto_init": True})
	creados.append((hecho["full_name"], None))
	linea("repositorio sin clasificar", hecho["full_name"])

	titulo("Corrida #1 — a mano")
	primera = auditar("manual")
	linea("estado", primera.state)
	linea("hallazgos", len(primera.finding_ids))
	repo_nuevo = env["repo.repository"].search(
		[("full_name", "=", hecho["full_name"])], limit=1)
	de_interes = {}
	for etiqueta, (repo, nombre, _r) in nombres.items():
		hallazgo = primera.finding_ids.filtered(
			lambda h: h.finding_type == "policy_drift_external"
			and h.subject == nombre)[:1]
		de_interes[etiqueta] = hallazgo
		linea("drift detectado (%s)" % etiqueta, bool(hallazgo))
	sin_clasificar = primera.finding_ids.filtered(
		lambda h: h.finding_type == "classification_missing"
		and h.repository_id == repo_nuevo)[:1]
	de_interes["app"] = sin_clasificar
	linea("hallazgo de clasificación", bool(sin_clasificar))
	veredictos["los_tres_hallazgos_aparecen"] = all(
		bool(h) for h in de_interes.values())

	titulo("Los tres cambios, cada uno por SU camino")
	# 1 · POR EL EMBUDO.
	hallazgo = de_interes["plan"]
	if hallazgo:
		accion = hallazgo.action_remediate()
		plan = env["repo.write.plan"].browse(accion["res_id"])
		plan._aprobar(confirmadas=plan.operation_ids.filtered(
			lambda o: o.is_destructive or o.is_irreversible))
		env.cr.commit()
		plan.action_apply()
		env.cr.commit()
		# LA OPERACIÓN QUE IMPORTA ES LA NUESTRA, no la primera del plan. `_plan_destino`
		# reutiliza el borrador abierto de la conexión, y en el sandbox ese borrador
		# arrastra operaciones de ensayos que se cayeron a la mitad. La primera vez este
		# renglón imprimió el estado de una de ellas —`needs_reconciliation`— y pareció
		# que el apply había fallado cuando lo que pasó es que la guarda de conciliación
		# hizo su trabajo: congeló la vieja, aplicó la nuestra, y cerró el plan en
		# `failed` porque un plan que no hizo todo lo aprobado no está aplicado.
		mia = plan.operation_ids.filtered(lambda o: o.finding_id == hallazgo)[:1]
		linea("1 · plan aplicado", "%s · nuestra operación: %s" % (
			plan.display_name, mia.state or "no se encontró"))
		linea("   (otras del borrador reusado)", ", ".join(
			"%s=%s" % (o.kind, o.state)
			for o in plan.operation_ids - mia) or "ninguna")
	# 2 · UN ACTO EN LA APP, sin plan y sin tocar GitHub.
	if repo_nuevo:
		repo_nuevo.write({"classification": "interno",
						  "classification_source": "manual"})
		env.cr.commit()
		linea("2 · acto en la app", "clasificado a mano como interno")
	# 3 · A MANO EN GITHUB, por fuera de todo.
	repo_f, nombre_f, rama_f = nombres["fuera"]
	id_f = [i for r, i in creados if r == REPO_DRIFT_FUERA][0]
	escritura.put("/repos/%s/rulesets/%s" % (REPO_DRIFT_FUERA, id_f),
				  definicion(nombre_f, 2, rama_f))
	linea("3 · cambio directo en GitHub", "el ruleset volvió a 2 revisiones")

	titulo("Corrida #2 — PROGRAMADA (la que dispara el correo)")
	segunda = auditar("scheduled")
	linea("estado", segunda.state)
	delta = segunda.delta()
	linea("comparable", delta["comparable"])
	linea("nuevos / resueltos / sin confirmar",
		  "%s / %s / %s" % (len(delta["nuevos"]), len(delta["resueltos"]),
							len(delta["sin_confirmar"])))

	titulo("Las tres atribuciones")
	esperado = {"plan": "plan", "app": "app", "fuera": "fuera"}
	obtenido = {}
	for etiqueta, hallazgo in de_interes.items():
		if not hallazgo:
			obtenido[etiqueta] = "sin hallazgo previo"
			continue
		if hallazgo not in delta["resueltos"]:
			obtenido[etiqueta] = "NO se resolvió"
			continue
		atribucion = Delta.atribucion(hallazgo, segunda, delta["anterior"])
		obtenido[etiqueta] = atribucion["categoria"]
		print("   [%s] %s" % (atribucion["categoria"].upper(), atribucion["texto"]))
	for etiqueta, esperada in esperado.items():
		linea("atribución de «%s»" % etiqueta,
			  "%s (esperada: %s)" % (obtenido.get(etiqueta), esperada))
	veredictos["las_tres_atribuciones"] = all(
		obtenido.get(k) == v for k, v in esperado.items())

	titulo("El correo del lunes")
	Correo = env["repo.delta.mail"]
	cuerpo = Correo.cuerpo(segunda)
	with open("/tmp/correo_e24_lunes.html", "w", encoding="utf-8") as f:
		f.write(cuerpo)
	linea("asunto", Correo.asunto(segunda))
	linea("guardado en", "/tmp/correo_e24_lunes.html")
	linea("tamaño", "%s caracteres" % len(cuerpo))
	linea("sin hojas de estilo externas", "<link" not in cuerpo)
	mensaje = segunda.message_ids.filtered(lambda m: m.partner_ids)[:1]
	linea("mensaje con destinatarios (Discuss + correo)", bool(mensaje))
	if mensaje:
		linea("destinatarios", ", ".join(mensaje.partner_ids.mapped("name")))
	veredictos["el_correo_sale_solo_en_la_programada"] = bool(mensaje)

	titulo("El correo CON la caja punteada — provocando una lectura fallida de verdad")
	print("   La caja de «sin leer» sólo aparece cuando hay un repositorio que no se")
	print("   pudo mirar, y es justo la pieza que hace honesto al resto del correo. Se")
	print("   provoca como pasa en la realidad: el repositorio desaparece DESPUÉS del")
	print("   enumerado, así que la corrida lo tiene en su lista y no lo puede leer.")
	victima = escritura.post("/orgs/%s/repos" % backend.owner_login,
							 {"name": "zzz-e24-victima-%s" % SELLO[-6:],
							  "private": True, "auto_init": True})
	tercera = env["repo.audit.run"].create({
		"name": "E2.4 con caída %s" % SELLO, "backend_id": backend.id,
		"origin": "scheduled"})
	tercera.write({"state": "running", "started_at": fields.Datetime.now()})
	enumerados = tercera._enumerar()
	env.cr.commit()
	escritura.delete("/repos/%s" % victima["full_name"])
	linea("borrado después del enumerado", victima["full_name"])
	for repo in enumerados:
		try:
			repo._job_sync_repository(tercera.id)
		except Exception:
			pass
	env.cr.commit()
	tercera._cerrar_si_termino()
	env.cr.commit()
	linea("estado de la corrida", tercera.state)
	linea("repositorios con error", tercera.repos_error)
	cuerpo_punteado = Correo.cuerpo(tercera)
	with open("/tmp/correo_e24_sin_leer.html", "w", encoding="utf-8") as f:
		f.write(cuerpo_punteado)
	linea("la caja punteada está", "dashed" in cuerpo_punteado)
	linea("dice la frase", "no dice nada sobre ellos" in cuerpo_punteado)
	linea("guardado en", "/tmp/correo_e24_sin_leer.html")
	veredictos["la_caja_punteada_llega"] = (
		"dashed" in cuerpo_punteado
		and "no dice nada sobre ellos" in cuerpo_punteado)

	titulo("El correo de la auditoría que NO pudo terminar")
	fallida = env["repo.audit.run"].create({
		"name": "E2.4 fallida %s" % SELLO, "backend_id": backend.id,
		"origin": "scheduled", "state": "error",
		"error_detail": "El token venció (401)",
		"finished_at": fields.Datetime.now()})
	cuerpo_malo = Correo.cuerpo(fallida)
	with open("/tmp/correo_e24_fallida.html", "w", encoding="utf-8") as f:
		f.write(cuerpo_malo)
	linea("asunto", Correo.asunto(fallida))
	linea("dice la causa", "401" in cuerpo_malo)
	linea("guardado en", "/tmp/correo_e24_fallida.html")
	veredictos["la_fallida_tambien_avisa"] = (
		"401" in cuerpo_malo and "no pudo terminar" in cuerpo_malo)

finally:
	titulo("Limpieza — por fuera del embudo, a propósito")
	for repo_full, ruleset_id in creados:
		try:
			if ruleset_id:
				escritura.delete("/repos/%s/rulesets/%s" % (repo_full, ruleset_id))
				linea("ruleset borrado", "%s · %s" % (repo_full, ruleset_id))
			else:
				escritura.delete("/repos/%s" % repo_full)
				linea("repositorio borrado", repo_full)
		except Exception as exc:
			linea("no se pudo limpiar %s" % repo_full, str(exc)[:70])
	Config.set_param("repo_manager.sync_threshold", UMBRAL_ORIGINAL or "25")
	env.cr.commit()

print("\n" + "=" * 78); print("VEREDICTO"); print("=" * 78)
for clave, ok in veredictos.items():
	print("   %s  %s" % ("[OK] " if ok else "[MAL]", clave))
print("\n%s" % ("TODO BIEN" if veredictos and all(veredictos.values())
				else "HAY AL MENOS UN PUNTO EN ROJO"))
