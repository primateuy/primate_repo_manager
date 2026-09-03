#!/usr/bin/env python3
# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Provoca un fallo REAL a mitad de una auditoría del sandbox, para poder mirarlo.

POR QUÉ HACE FALTA. El camino feliz se prueba solo: se aprieta Auditar y todo sale verde.
El camino feo —un repositorio que falla mientras la corrida avanza— no se puede mirar si
no ocurre, y en el sandbox no ocurre nunca: la App ve todos los repos y todos responden.
Sin verlo, la barra en ámbar y el contador de errores son código que nadie ejercitó.

QUÉ FALLO PROVOCA, Y POR QUÉ ÉSE. El más real de todos: un repositorio que se enumera al
arrancar la corrida y deja de existir antes de que le llegue el turno. Pasa de verdad
—alguien lo borra, lo saca de la instalación, lo transfiere— y es exactamente el caso
para el que existe el ámbar. No se simula nada: se crea un repositorio descartable, se
arranca la auditoría, y se lo borra en GitHub mientras corre. El job pide
`GET /repos/prm-sandbox/sbx-desaparece` y GitHub contesta 404.

NO ES PRODUCTO NI FIXTURE PERMANENTE. `sbx-desaparece` no forma parte del manifiesto de
`poblar_sandbox.py`: nace para una corrida y muere en ella.

USO
    python3 provocar_fallo.py crear      # deja los dos repositorios descartables listos
    python3 provocar_fallo.py vigilar    # espera la corrida y borra el que tiene que fallar
    python3 provocar_fallo.py limpiar    # borra los dos, al terminar
    python3 provocar_fallo.py estado     # dice cuáles existen

El orden para mirarlo: `crear`, después `vigilar` en una terminal, y con el vigía
esperando, apretar «Auditar» en Odoo.

CREDENCIAL: la misma que `poblar_sandbox.py` — `PRM_SANDBOX_TOKEN` o el .rtf de la
carpeta PRM. Nunca se imprime.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ORG = "prm-sandbox"
API = "https://api.github.com"
NOMBRE = "sbx-desaparece"

# EL COMPAÑERO EXISTE POR UNA RAZÓN DE ORDEN, no de cobertura. GitHub enumera la
# instalación por id ascendente, así que un repositorio recién creado sale SIEMPRE último.
# Con el descartable solo, el error cae en el último turno y la barra se tiñe recién al
# cerrar: nunca se ve el ámbar mientras la corrida avanza, que es justo lo que hay que
# mirar. `sbx-sobrevive` se crea DESPUÉS, queda detrás en la fila y no se borra, así que
# después del fallo todavía queda un repositorio por recorrer y el ámbar se ve en marcha.
COMPANERO = "sbx-sobrevive"
RTF = ("/Users/darylyturraldelopez/Desktop/Odoo/Desarrollos Documentos/"
	   "PRM(Primate Repo Manager)/token-poblado.rtf")

# La corrida que se vigila tiene que incluir el repositorio descartable. Con 6 sembrados
# más éste son 7: por debajo de eso, el vigía sabe que está mirando otra cosa.
REPOS_ESPERADOS = 8
ESPERA_MAX = 600

BD = os.environ.get("PRM_BD", "o19_primate_stg_12082026")


def token():
	t = os.environ.get("PRM_SANDBOX_TOKEN")
	if t:
		return t
	txt = subprocess.run(["textutil", "-convert", "txt", "-stdout", RTF],
						 capture_output=True, text=True).stdout
	m = re.search(r"(github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+)", txt)
	if not m:
		raise SystemExit("no encontré el token: exportá PRM_SANDBOX_TOKEN")
	return m.group(1)


def pedir(metodo, ruta, cuerpo=None, tolerar=()):
	req = urllib.request.Request(
		API + ruta, data=json.dumps(cuerpo).encode() if cuerpo else None,
		method=metodo, headers={
			"Authorization": "token %s" % TOKEN,
			"Accept": "application/vnd.github+json",
			"X-GitHub-Api-Version": "2022-11-28",
			"Content-Type": "application/json"})
	try:
		r = urllib.request.urlopen(req)
		crudo = r.read()
		return r.status, (json.loads(crudo) if crudo else {})
	except urllib.error.HTTPError as e:
		if e.code in tolerar:
			return e.code, e.read().decode()[:200]
		raise SystemExit("FALLÓ %s %s -> %s\n%s"
						 % (metodo, ruta, e.code, e.read().decode()[:300]))


def _crear_uno(nombre, para_que):
	code, _ = pedir("GET", "/repos/%s/%s" % (ORG, nombre), tolerar=(404,))
	if code == 200:
		print("ya existe %s/%s" % (ORG, nombre))
		return
	pedir("POST", "/orgs/%s/repos" % ORG, {
		"name": nombre, "private": False, "auto_init": True,
		"description": para_que})
	print("creado %s/%s" % (ORG, nombre))


def crear():
	# El orden importa: el que se borra tiene que quedar ANTES del que sobrevive.
	_crear_uno(NOMBRE, "descartable: se borra a mitad de corrida para provocar el fallo")
	_crear_uno(COMPANERO, "descartable: queda detrás del que falla, para que el ámbar "
						  "se vea con la corrida todavía en marcha")


def borrar():
	"""Borra sólo el que tiene que fallar. El compañero se limpia con `limpiar`."""
	code, _ = pedir("DELETE", "/repos/%s/%s" % (ORG, NOMBRE), tolerar=(404,))
	print("borrado" if code == 204 else "no estaba (%s)" % code)


def limpiar():
	for nombre in (NOMBRE, COMPANERO):
		code, _ = pedir("DELETE", "/repos/%s/%s" % (ORG, nombre), tolerar=(404,))
		print("%s: %s" % (nombre, "borrado" if code == 204 else "no estaba"))


def vigilar():
	"""Mira la base y borra el repositorio en cuanto la corrida pasa a «en curso».

	Se mira la base y no se coordina a ojo porque el momento importa: hay que borrar
	DESPUÉS del enumerado —si no, el repositorio ni aparece en la corrida— y ANTES de que
	le toque el turno. Entre las dos cosas hay unos segundos, y acertarlos a mano es
	cuestión de suerte.
	"""
	import psycopg2

	for nombre in (NOMBRE, COMPANERO):
		code, _ = pedir("GET", "/repos/%s/%s" % (ORG, nombre), tolerar=(404,))
		if code != 200:
			raise SystemExit("falta %s/%s: corré primero `crear`" % (ORG, nombre))

	cnx = psycopg2.connect(host="localhost", user="odoo", password="odoo", dbname=BD)
	cnx.autocommit = True
	cur = cnx.cursor()
	cur.execute("SELECT COALESCE(MAX(id), 0) FROM repo_audit_run")
	ultima = cur.fetchone()[0]
	print("Vigía listo (última corrida: %s)." % ultima)
	print("Ahora andá a Odoo y apretá «Auditar». Borro %s apenas arranque.\n" % NOMBRE)

	t0 = time.time()
	corrida = None
	while time.time() - t0 < ESPERA_MAX:
		cur.execute("SELECT id, state, repos_total FROM repo_audit_run "
					"WHERE id > %s ORDER BY id DESC LIMIT 1", (ultima,))
		fila = cur.fetchone()
		if fila and fila[1] == "running" and (fila[2] or 0) >= REPOS_ESPERADOS:
			corrida = fila[0]
			print("Corrida %s en curso con %s repositorios -> borrando %s"
				  % (corrida, fila[2], NOMBRE))
			borrar()
			break
		time.sleep(0.3)
	if corrida is None:
		raise SystemExit("no arrancó ninguna corrida en %s s" % ESPERA_MAX)

	while time.time() - t0 < ESPERA_MAX:
		cur.execute("SELECT state, repos_done, repos_error FROM repo_audit_run "
					"WHERE id=%s", (corrida,))
		estado, hechos, malos = cur.fetchone()
		if estado in ("done", "partial", "error"):
			print("\nCorrida %s -> %s | recorridos: %s | con error: %s"
				  % (corrida, estado, hechos, malos))
			cur.execute("SELECT full_name, sync_error FROM repo_repository "
						"WHERE sync_state='error'")
			for nombre, err in cur.fetchall():
				print("   %s -> %s" % (nombre, (err or "")[:140]))
			return
		time.sleep(0.5)
	print("la corrida no cerró en %s s" % ESPERA_MAX)


TOKEN = token()
ACCIONES = {"crear": crear, "borrar": borrar, "limpiar": limpiar,
			"vigilar": vigilar}
accion = sys.argv[1] if len(sys.argv) > 1 else "estado"
if accion in ACCIONES:
	ACCIONES[accion]()
else:
	for nombre in (NOMBRE, COMPANERO):
		code, _ = pedir("GET", "/repos/%s/%s" % (ORG, nombre), tolerar=(404,))
		print("%s: %s" % (nombre, "existe" if code == 200 else "no existe"))
