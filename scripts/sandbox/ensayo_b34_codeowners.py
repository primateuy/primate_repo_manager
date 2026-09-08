# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B3.4 · los cuatro estados del CODEOWNERS, contra GitHub de verdad.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/ensayo_b34_codeowners.py

El archivo es UNO SOLO y el que está tapa a cualquier otro, así que la guarda del ajeno
carga más peso que la del ruleset ajeno. Y el estado intermedio —el nuestro editado a
mano— es el que decide si el módulo respeta el trabajo de otro o lo pisa en cuotas.

DEJA EL REPOSITORIO COMO ESTABA: borra el archivo al terminar.
"""
import base64
import json
import time

from odoo import fields
from odoo.exceptions import UserError

from odoo.addons.primate_repo_manager.models.repo_codeowners import MARCA

BACKEND_ID = 188
REPO = "prm-sandbox/sbx-cliente-publico"
RUTA = ".github/CODEOWNERS"
SELLO = time.strftime("%Y%m%d-%H%M%S")
LIDER = "desarrollo@primate.uy"

lider = env["res.users"].search([("login", "=", LIDER)], limit=1)
assert lider, "no está el usuario con rol de líder"
env = env(user=lider)

backend = env["repo.backend"].browse(BACKEND_ID)
repo = env["repo.repository"].search([("full_name", "=", REPO)], limit=1)
cliente = backend.write_client()
RAMA = repo.default_branch

fase = [0]
def titulo(t):
	fase[0] += 1
	print("\n" + "=" * 78); print("FASE %s · %s" % (fase[0], t)); print("=" * 78)

def linea(k, v):
	print("   %-42s %s" % (k + ":", v))

NUESTRO = "%s\n# Repositorio: %s\n#\n# declarado en la plantilla de ensayo\n* @dyturralbe\n" % (
	MARCA, REPO)

def leer():
	datos = cliente.get("/repos/%s/contents/%s" % (REPO, RUTA),
						params={"ref": RAMA}, tolerar_404=True)
	if not datos:
		return None
	return {"sha": datos["sha"],
			"contenido": base64.b64decode(datos["content"]).decode()}

def escribir_a_mano(contenido, mensaje):
	actual = leer()
	cuerpo = {"message": mensaje, "branch": RAMA,
			  "content": base64.b64encode(contenido.encode()).decode()}
	if actual:
		cuerpo["sha"] = actual["sha"]
	cliente.put("/repos/%s/contents/%s" % (REPO, RUTA), cuerpo)

def plan_con(payload):
	plan = env["repo.write.plan"].create(
		{"name": "Ensayo B3.4 %s" % SELLO, "backend_id": backend.id})
	op = env["repo.write.operation"].create({
		"plan_id": plan.id, "kind": "codeowners_write", "repository_id": repo.id,
		"target": RAMA, "payload_json": json.dumps(payload)})
	plan._aprobar(confirmadas=plan.operation_ids.filtered(
		lambda o: o.is_destructive or o.is_irreversible))
	env.cr.commit()
	return plan, op

def aplicar(plan):
	try:
		plan.action_apply()
		env.cr.commit()
		return None
	except UserError as exc:
		env.cr.rollback()
		return str(exc).split("\n")[0][:130]

veredictos = {}
try:
	titulo("Estado AUSENTE — no hay ningún CODEOWNERS")
	if leer():
		cliente.delete("/repos/%s/contents/%s" % (REPO, RUTA), {
			"message": "limpieza previa del ensayo", "sha": leer()["sha"],
			"branch": RAMA})
	linea("hay archivo", bool(leer()))
	plan, op = plan_con({"contenido": NUESTRO})
	error = aplicar(plan)
	linea("estado de la operación", op.state)
	linea("error", error or op.error or "—")
	veredictos["ausente_se_escribe"] = op.state == "applied"
	linea("contenido en GitHub", (leer() or {}).get("contenido", "").splitlines()[:1])

	titulo("Estado NUESTRO — ya está igual: no se escribe")
	plan, op = plan_con({"contenido": NUESTRO})
	aplicar(plan)
	linea("estado de la operación", op.state)
	linea("resultado", op.result_json)
	veredictos["nuestro_no_reescribe"] = (
		op.state == "applied" and "sin cambios" in (op.result_json or ""))

	titulo("Estado EDITADO — alguien agregó una línea a mano")
	editado = NUESTRO + "docs/ @otra-persona\n"
	escribir_a_mano(editado, "alguien edita el CODEOWNERS a mano")
	linea("línea agregada a mano", "docs/ @otra-persona")

	print("\n   -- sin confirmación --")
	plan, op = plan_con({"contenido": NUESTRO})
	error = aplicar(plan)
	linea("se negó con", error or "NO se negó")
	linea("la línea sigue en GitHub", "docs/" in (leer() or {})["contenido"])
	veredictos["editado_no_se_pisa"] = bool(error) and "docs/" in leer()["contenido"]

	print("\n   -- con la diferencia LEGIBLE y su confirmación --")
	cambios = repo.ediciones_manuales(NUESTRO, leer()["contenido"])
	frase = repo.frase_de_ediciones(cambios)
	linea("lo que se le muestra a quien decide", frase)
	veredictos["la_frase_dice_que_se_pierde"] = "Alguien agregó a mano" in frase
	plan, op = plan_con({"contenido": NUESTRO, "perder_ediciones": True,
						 "ediciones_perdidas": frase})
	error = aplicar(plan)
	linea("estado de la operación", op.state)
	linea("la línea de otro ya no está", "docs/" not in (leer() or {})["contenido"])
	veredictos["con_confirmacion_se_pisa"] = op.state == "applied"

	titulo("Estado AJENO — un CODEOWNERS que este módulo no puso")
	escribir_a_mano("* @gente-de-otro-equipo\n", "un CODEOWNERS ajeno")
	plan, op = plan_con({"contenido": NUESTRO})
	error = aplicar(plan)
	linea("se negó con", error or "NO se negó")
	linea("el ajeno sigue intacto",
		  leer()["contenido"].strip() == "* @gente-de-otro-equipo")
	veredictos["ajeno_no_se_pisa"] = (
		bool(error) and leer()["contenido"].strip() == "* @gente-de-otro-equipo")

finally:
	titulo("Limpieza")
	actual = leer()
	if actual:
		cliente.delete("/repos/%s/contents/%s" % (REPO, RUTA), {
			"message": "[REM] fin del ensayo B3.4", "sha": actual["sha"],
			"branch": RAMA})
		linea("archivo borrado", RUTA)
	env.cr.commit()

print("\n" + "=" * 78); print("VEREDICTO"); print("=" * 78)
for k, ok in veredictos.items():
	print("   %s  %s" % ("[OK] " if ok else "[MAL]", k))
print("\n%s" % ("TODO BIEN" if all(veredictos.values()) else "HAY AL MENOS UN PUNTO EN ROJO"))
