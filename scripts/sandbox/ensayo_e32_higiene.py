# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E3.2e · la higiene contra GitHub real, con las tres situaciones provocadas.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/ensayo_e32_higiene.py

POR QUÉ CONTRA GITHUB Y NO CON DOBLES. La distinción entera de E3 —integrada contra
abandonada— sale de una comparación que hace GitHub, no nosotros. Un doble que conteste
`ahead_by` prueba que sabemos leer un número; lo que hay que probar es que ese número
signifique lo que creemos sobre ramas de verdad.

Y hay dos cosas que sólo existen acá:

  · **la guarda que vuelve a mirar**: alguien empuja a la rama DESPUÉS de la auditoría y
    antes del apply. Con dobles se simula; acá se hace.
  · **la reversión del borrado**: que la rama vuelva en el MISMO commit sólo se puede
    afirmar mirando el commit que quedó en GitHub.
"""
import json
import time

from odoo import fields

SELLO = time.strftime("%Y%m%d-%H%M%S")
LIDER = "desarrollo@primate.uy"

lider = env["res.users"].search([("login", "=", LIDER)], limit=1)
assert lider, "no está el usuario con rol de líder"
env = env(user=lider)

backend = env["repo.backend"].search([("environment", "=", "sandbox")], limit=1)
escritura = backend.write_client()
lectura = backend.client()
Config = env["ir.config_parameter"].sudo()

fase = [0]
def titulo(texto):
	fase[0] += 1
	print("\n" + "=" * 78); print("FASE %s · %s" % (fase[0], texto)); print("=" * 78)

def linea(clave, valor):
	print("   %-46s %s" % (clave + ":", valor))

def auditar():
	corrida = env["repo.audit.run"].create({
		"name": "E3.2 %s" % SELLO, "backend_id": backend.id})
	corrida.action_start()
	env.cr.commit()
	return corrida

def commit_en(repo_full, rama, texto):
	"""Un commit de verdad en esa rama, por la API de contenidos."""
	import base64
	return escritura.put(
		"/repos/%s/contents/notas-%s.md" % (repo_full, texto),
		{"message": "[ADD] %s" % texto, "branch": rama,
		 "content": base64.b64encode(texto.encode()).decode()})

veredictos = {}
creado = None
UMBRALES = {"repo_manager.branch_abandoned_months": None,
			"repo_manager.repo_archive_months": None,
			"repo_manager.sync_threshold": None}
try:
	titulo("Umbrales al mínimo, para que lo de hoy ya cuente como viejo")
	for clave in UMBRALES:
		UMBRALES[clave] = Config.get_param(clave)
	Config.set_param("repo_manager.branch_abandoned_months", "0")
	Config.set_param("repo_manager.repo_archive_months", "0")
	Config.set_param("repo_manager.sync_threshold", "500")
	env.cr.commit()
	print("   Los umbrales son CONFIGURACIÓN y esto los mueve para el ensayo: no se")
	print("   puede envejecer una rama seis meses en un ensayo de tres minutos. Lo que")
	print("   se prueba es la regla, no la aritmética de la fecha.")

	titulo("Crear el repositorio y las tres situaciones, de verdad")
	nombre = "zzz-e32-%s" % SELLO[-6:]
	hecho = escritura.post("/orgs/%s/repos" % backend.owner_login,
						   {"name": nombre, "private": True, "auto_init": True})
	creado = hecho["full_name"]
	linea("repositorio", creado)
	base_sha = escritura.get("/repos/%s/git/ref/heads/%s" % (
		creado, hecho["default_branch"]))["object"]["sha"]
	for rama in ("19.0", "19.0_integrada", "19.0_con_trabajo"):
		escritura.post("/repos/%s/git/refs" % creado,
					   {"ref": "refs/heads/%s" % rama, "sha": base_sha})
	linea("ramas creadas", "19.0 (línea) · 19.0_integrada · 19.0_con_trabajo")
	# Y a UNA de ellas se le mete trabajo propio. Ésa es la que nunca se propone borrar.
	commit_en(creado, "19.0_con_trabajo", "trabajo-sin-integrar")
	linea("commit propio en", "19.0_con_trabajo")

	titulo("La auditoría, y los tres hallazgos")
	corrida = auditar()
	repo = env["repo.repository"].search([("full_name", "=", creado)], limit=1)
	suyos = corrida.finding_ids.filtered(lambda h: h.repository_id == repo)
	integrada = suyos.filtered(
		lambda h: h.finding_type == "branch_integrated_candidate"
		and h.subject == "19.0_integrada")[:1]
	abandonada = suyos.filtered(
		lambda h: h.finding_type == "branch_abandoned"
		and h.subject == "19.0_con_trabajo")[:1]
	archivable = suyos.filtered(
		lambda h: h.finding_type == "repository_archivable")[:1]
	for etiqueta, hallazgo in (("integrada", integrada), ("abandonada", abandonada),
							   ("archivable", archivable)):
		linea(etiqueta, hallazgo.summary[:80] if hallazgo else "NO APARECIÓ")
	rama_integrada = repo.branch_ids.filtered(lambda b: b.name == "19.0_integrada")[:1]
	rama_trabajo = repo.branch_ids.filtered(lambda b: b.name == "19.0_con_trabajo")[:1]
	linea("commits propios · integrada", rama_integrada.ahead_of_line)
	linea("commits propios · con trabajo", rama_trabajo.ahead_of_line)
	linea("medidas contra", rama_integrada.line_branch_name)
	veredictos["las_tres_situaciones_se_detectan"] = bool(
		integrada and abandonada and archivable)

	titulo("La abandonada NO se planifica — las dos puertas")
	linea("can_be_planned", abandonada.can_be_planned if abandonada else "—")
	linea("dice por qué", (abandonada.why_not_planned or "")[:70] if abandonada else "—")
	rechazo = abandonada.agregar_al_borrador() if abandonada else {}
	linea("por el arrastre entran", rechazo.get("agregadas"))
	veredictos["la_abandonada_no_se_ofrece"] = bool(
		abandonada and not abandonada.can_be_planned
		and rechazo.get("agregadas") == 0)

	titulo("Borrar la integrada por el embudo, y devolverla")
	sha_antes = escritura.get(
		"/repos/%s/git/ref/heads/19.0_integrada" % creado)["object"]["sha"]
	accion = integrada.action_remediate()
	plan = env["repo.write.plan"].browse(accion["res_id"])
	mia = plan.operation_ids.filtered(lambda o: o.finding_id == integrada)[:1]
	linea("exige escribir el nombre", mia.requires_typed_name)
	linea("es irreversible", mia.is_irreversible)
	linea("la frase lleva la salvedad",
		  "mientras GitHub conserve el objeto" in (mia.description or ""))
	plan._aprobar(confirmadas=plan.operation_ids.filtered(
		lambda o: o.is_destructive or o.is_irreversible))
	env.cr.commit()
	plan.action_apply()
	env.cr.commit()
	linea("estado de la operación", mia.state)
	try:
		escritura.get("/repos/%s/git/ref/heads/19.0_integrada" % creado)
		sigue = True
	except Exception:
		sigue = False
	linea("la rama sigue en GitHub", sigue)

	mia.action_rollback_operation()
	env.cr.commit()
	vuelta = escritura.get(
		"/repos/%s/git/ref/heads/19.0_integrada" % creado)["object"]["sha"]
	linea("volvió en el MISMO commit", vuelta == sha_antes)
	veredictos["borrado_y_vuelta_exacta"] = (
		mia.state in ("applied", "rolled_back") and not sigue and vuelta == sha_antes)

	titulo("LA GUARDA: alguien empuja después de la auditoría")
	print("   El hallazgo dijo «integrada» cuando corrió la auditoría. Entre eso y el")
	print("   apply pueden pasar días — acá, segundos. Si nadie vuelve a mirar, el")
	print("   embudo termina haciendo lo que el motor se niega a proponer.")
	commit_en(creado, "19.0_integrada", "empujon-tardio")
	plan2 = env["repo.write.plan"].create({
		"name": "Higiene tardía %s" % SELLO, "backend_id": backend.id})
	op2 = env["repo.write.operation"].create({
		"plan_id": plan2.id, "kind": "branch_delete", "repository_id": repo.id,
		"target": "19.0_integrada",
		"payload_json": json.dumps({
			"repository": creado, "branch": "19.0_integrada",
			"integrated_into": "19.0"})})
	plan2._aprobar(confirmadas=plan2.operation_ids)
	env.cr.commit()
	plan2.action_apply()
	env.cr.commit()
	linea("estado de la operación", op2.state)
	linea("motivo", (op2.error or "")[:90])
	try:
		escritura.get("/repos/%s/git/ref/heads/19.0_integrada" % creado)
		quedo = True
	except Exception:
		quedo = False
	linea("la rama SIGUE ahí", quedo)
	veredictos["no_se_borra_lo_que_dejo_de_estar_integrado"] = (
		op2.state == "failed" and quedo)

	titulo("Archivar por el embudo, y desarchivar")
	accion3 = archivable.action_remediate()
	plan3 = env["repo.write.plan"].browse(accion3["res_id"])
	op3 = plan3.operation_ids.filtered(lambda o: o.finding_id == archivable)[:1]
	hechos = op3.hechos_de_archivado()
	linea("PRs abiertas que se congelan", len(hechos["prs_abiertas"]))
	linea("forks que lo tienen de upstream", len(hechos["forks"]))
	linea("módulos que una promoción movió", len(hechos["modulos_promovidos"]))
	plan3._aprobar(confirmadas=plan3.operation_ids.filtered(
		lambda o: o.is_destructive or o.is_irreversible))
	env.cr.commit()
	plan3.action_apply()
	env.cr.commit()
	linea("estado de la operación", op3.state)
	linea("archivado en GitHub", escritura.get("/repos/%s" % creado).get("archived"))
	op3.action_rollback_operation()
	env.cr.commit()
	linea("desarchivado en GitHub",
		  not escritura.get("/repos/%s" % creado).get("archived"))
	veredictos["archivar_y_desarchivar"] = (
		op3.state in ("applied", "rolled_back")
		and not escritura.get("/repos/%s" % creado).get("archived"))

finally:
	titulo("Limpieza y umbrales de vuelta como estaban")
	for clave, valor in UMBRALES.items():
		if valor is not None:
			Config.set_param(clave, valor)
	if creado:
		try:
			escritura.patch("/repos/%s" % creado, {"archived": False})
			escritura.delete("/repos/%s" % creado)
			linea("borrado", creado)
		except Exception as exc:
			linea("no se pudo borrar", str(exc)[:80])
	env.cr.commit()

print("\n" + "=" * 78); print("VEREDICTO"); print("=" * 78)
for clave, ok in veredictos.items():
	print("   %s  %s" % ("[OK] " if ok else "[MAL]", clave))
print("\n%s" % ("TODO BIEN" if veredictos and all(veredictos.values())
				else "HAY AL MENOS UN PUNTO EN ROJO"))
