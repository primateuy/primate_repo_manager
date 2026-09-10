# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E4.5 · el panel entero contra datos reales, y los avisos de la barra.

    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < scripts/sandbox/ensayo_e4_panel.py

QUÉ VIENE A COMPROBAR, y por qué no alcanza con los tests: el panel es la pantalla que
alguien abre para decidir, y sus afirmaciones dependen de datos que sólo existen después
de varias corridas reales. Un test le pone tres fotos y comprueba la aritmética; acá se
mira que lo que dice sea cierto sobre lo que de verdad pasó.
"""
from odoo import fields

# COMO EL LÍDER Y NO COMO SUPERUSUARIO. El aviso del plan sólo sale para quien puede
# aprobarlo, así que preguntándolo como root se contesta «ninguno» y parecería que la
# guarda está rota cuando lo que pasa es que root no tiene el rol.
lider = env["res.users"].search([("login", "=", "desarrollo@primate.uy")], limit=1)
if lider:
	env = env(user=lider)

backend = env["repo.backend"].search([("environment", "=", "sandbox")], limit=1)
Panel = env["repo.health.panel"]

fase = [0]
def titulo(t):
	fase[0] += 1
	print("\n" + "=" * 78); print("FASE %s · %s" % (fase[0], t)); print("=" * 78)

def linea(clave, valor):
	print("   %-46s %s" % (clave + ":", valor))

veredictos = {}

titulo("Los tres números, y de qué corrida salen")
datos = Panel.datos(backend_id=backend.id)
linea("conexión", datos["conexion"]["cuenta"])
linea("última corrida", datos["corrida"]["cuando"])
linea("leídos / total", "%s / %s" % (datos["corrida"]["leidos"],
									 datos["corrida"]["total"]))
for numero in datos["numeros"]:
	linea(numero["titulo"], "%s%s · %s" % (
		numero["valor"] if numero["valor"] is not None else "—",
		numero.get("unidad") or "", numero["pie"]))
	linea("   delta", numero.get("delta"))
	linea("   meta", numero.get("meta"))
veredictos["los_tres_numeros_salen"] = len(datos["numeros"]) == 3

titulo("La tendencia sobre las corridas REALES")
tendencia = datos["detalle"]["tendencia"]
if not tendencia["hay"]:
	linea("no hay tendencia", tendencia["motivo"])
else:
	for clave, puntos in tendencia["series"].items():
		medidos = [p for p in puntos if p["medida"]]
		huecos = [p for p in puntos if not p["medida"]]
		linea(clave, "%s puntos · %s medidos · %s huecos" % (
			len(puntos), len(medidos), len(huecos)))
		if huecos:
			linea("   por qué hay huecos",
				  "corridas sin métrica guardada (fallidas o anteriores a B4.1)")
		print("      " + " ".join(
			("%s" % p["valor"]) if p["medida"] else "·" for p in puntos))
	# LO QUE IMPORTA: que ningún hueco se haya rellenado con un número.
	inventados = [p for puntos in tendencia["series"].values() for p in puntos
				  if not p["medida"] and p["valor"] is not None]
	linea("huecos rellenados con un valor", len(inventados))
	veredictos["ningun_hueco_inventado"] = not inventados
veredictos["hay_tendencia"] = bool(tendencia["hay"])

titulo("La meta: se muestra y NO reclama")
Config = env["ir.config_parameter"].sudo()
anterior = Config.get_param("repo_manager.meta_protegidas")
Config.set_param("repo_manager.meta_protegidas", "85")
env.cr.commit()
con_meta = Panel.datos(backend_id=backend.id)
protegidas = [n for n in con_meta["numeros"] if n["clave"] == "protegidas"][0]
linea("meta leída", protegidas["meta"])
corrida = env["repo.audit.run"].search(
	[("backend_id", "=", backend.id), ("state", "in", ("done", "partial"))],
	order="id desc", limit=1)
tipos_antes = set(corrida.finding_ids.mapped("finding_type"))
env["repo.audit.engine"].evaluate(corrida)
tipos_despues = set(corrida.finding_ids.mapped("finding_type"))
linea("tipos de hallazgo nuevos por la meta", sorted(tipos_despues - tipos_antes))
veredictos["la_meta_no_genera_hallazgos"] = not (tipos_despues - tipos_antes)
Config.set_param("repo_manager.meta_protegidas", anterior or "")
env.cr.commit()

titulo("Los avisos de la barra, con lo que hay ahora")
avisos = env["repo.audit.run"].avisos_de_barra()
linea("auditoría en curso", avisos["auditoria"] or "ninguna")
linea("plan esperando", (avisos["plan"] or {}).get("nombre") or "ninguno")
if avisos["plan"]:
	linea("   operaciones", avisos["plan"]["operaciones"])
veredictos["los_avisos_contestan"] = isinstance(avisos, dict)

titulo("Las dos puertas de entrada")
for rol, esperada in (("group_repo_lead", "action_repo_audit_finding"),
					  ("group_repo_reader", "action_repo_panel_salud")):
	# Crear usuarios pide permisos de administración de Odoo y el líder no los tiene —lo
	# cual está bien—. La puerta se le pone al usuario en el `create`, así que se crea
	# elevado y se comprueba lo que quedó escrito.
	usuario = env["res.users"].sudo().create({
		"name": "Puerta %s" % rol, "login": "puerta-%s-%s" % (rol, fields.Datetime.now().strftime("%H%M%S")),
		"group_ids": [(4, env.ref("base.group_user").id),
					  (4, env.ref("primate_repo_manager.%s" % rol).id)]})
	# Se compara por ID contra la referencia, que es lo que el módulo escribe. Leer el
	# identificador externo desde el registro es otra pregunta —y la primera versión de
	# este ensayo la hacía mal, dando dos rojos con el código correcto.
	esperado = env.ref("primate_repo_manager.%s" % esperada)
	linea(rol, "%s (esperada: %s)" % (
		usuario.action_id.display_name or "ninguna", esperado.display_name))
	veredictos["puerta_%s" % rol] = usuario.action_id.id == esperado.id
	usuario.unlink()
env.cr.rollback()

print("\n" + "=" * 78); print("VEREDICTO"); print("=" * 78)
for clave, ok in veredictos.items():
	print("   %s  %s" % ("[OK] " if ok else "[MAL]", clave))
print("\n%s" % ("TODO BIEN" if veredictos and all(veredictos.values())
				else "HAY AL MENOS UN PUNTO EN ROJO"))
