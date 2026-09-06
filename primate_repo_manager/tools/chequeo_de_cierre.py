# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""¿Producción sigue cerrada? Los tres puntos, con su evidencia.

    cd <odoo>
    ./odoo-bin shell -c <conf> -d <base> --no-http \
        < primate_repo_manager/tools/chequeo_de_cierre.py

Consulta la API de GitHub y la base. No usa nada de lo que alguien recuerde.
"""
import json

resultado = env["repo.backend"].chequeo_de_cierre()

TITULOS = {
	"produccion_sin_escritura": "Producción sin escritura",
	"alcance_de_escritura": "Alcance de la App de escritura",
	"permisos_de_lectura": "Permisos de la App",
	"app_sin_credenciales": "App declarada, sin credenciales acá",
	"alcance_no_verificable": "Alcance NO verificable desde acá",
	"registro_al_día": "Registro de Apps al día",
}
MARCA = {True: "[OK]  ", False: "[MAL] ", None: "[?]   "}

print("")
print("CHEQUEO DE CIERRE · %s" % resultado["cuando"])
print("=" * 78)
for punto in resultado["puntos"]:
	print("%s  %s" % (MARCA[punto["ok"]],
					  TITULOS.get(punto["punto"], punto["punto"])))
	print("        sujeto: %s" % punto["sujeto"])
	for clave, valor in punto["evidencia"].items():
		if isinstance(valor, (list, dict)):
			valor = json.dumps(valor, ensure_ascii=False, sort_keys=True)
		print("        %-22s %s" % (clave + ":", valor))
	print("")
print("=" * 78)
veredicto = "todo cerrado" if resultado["todo_ok"] else "HAY AL MENOS UN PUNTO EN ROJO"
if resultado["no_verificables"]:
	# Lo que no se pudo leer NO se cuenta como bueno. Se dice, y se dice en el veredicto,
	# que es donde alguien mira cuando tiene apuro.
	veredicto += " · %s punto(s) NO verificables desde acá" % resultado["no_verificables"]
print("VEREDICTO: %s" % veredicto)
