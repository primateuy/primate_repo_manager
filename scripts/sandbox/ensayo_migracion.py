#!/usr/bin/env python3
# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Ensayo de la transferencia de repositorios — §10.1 de la spec.

ES EL ÚNICO CONTACTO DE TODA LA FASE 2 CON LA CUENTA REAL, y el alcance es angosto a
propósito: crea repositorios NUEVOS y descartables en `primateuy` y los transfiere a la
organización sandbox. Ningún repositorio existente se toca, se lee ni se modifica.

POR QUÉ EXISTE. La transferencia no se puede orquestar desde el módulo: un token de
instalación está acotado a UNA cuenta y transferir cruza dos. Falla con token de
instalación y con token de usuario user-to-server; el único que funciona es un PAT
clásico, que la spec §3 descarta como credencial del módulo. Así que la migración va por
procedimiento aparte, y esto ensaya ese procedimiento antes de usarlo con repos de verdad.

LA GUARDA DURA. Toda operación pasa por `_permitido()`, que exige que el nombre matchee
`^prm-test-migracion-`. No es una convención ni un filtro de conveniencia: es una función
que corta el programa. Un repositorio real nunca va a matchear ese prefijo.

LA CREDENCIAL. PAT clásico de un solo uso, de la cuenta `primateuy` —tiene que ser esa,
porque sólo el dueño puede crear repositorios en su propia cuenta—. Se lee de
`PRM_PAT_MIGRACION` o del .rtf con `--token-desde-rtf`. Nunca entra a Odoo.

USO — el ensayo va por fases, y cada una se corre a mano:

    python3 ensayo_migracion.py preflight
    python3 ensayo_migracion.py crear            # dry-run
    python3 ensayo_migracion.py crear --apply
    python3 ensayo_migracion.py transferir       # dry-run
    python3 ensayo_migracion.py transferir --apply
    python3 ensayo_migracion.py limpiar --apply
    python3 ensayo_migracion.py revocacion       # tras revocar el PAT a mano
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
CUENTA = "primateuy"          # origen: la cuenta real
ORG = "prm-sandbox"           # destino: el sandbox
PREFIJO = re.compile(r"^prm-test-migracion-")
NOMBRES = ["prm-test-migracion-uno", "prm-test-migracion-dos",
		   "prm-test-migracion-tres"]
RTF = ("/Users/darylyturraldelopez/Desktop/Odoo/Desarrollos Documentos/"
	   "PRM(Primate Repo Manager)/prm-ensayo-migracion.rtf")


def _permitido(nombre):
	"""La guarda dura. Corta el programa; no devuelve False para que alguien lo ignore."""
	if not PREFIJO.match(nombre or ""):
		raise SystemExit(
			"\nGUARDA: «%s» no matchea ^prm-test-migracion- y este script no toca nada "
			"que no sea un repositorio de ensayo.\n" % nombre)
	return nombre


class Github:
	def __init__(self, token, aplicar):
		self._token = token
		self.aplicar = aplicar
		self.plan = []

	def _pedir(self, metodo, ruta, cuerpo=None, tolerar=()):
		datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
		req = urllib.request.Request(
			ruta if ruta.startswith("http") else API + ruta,
			data=datos, method=metodo, headers={
				"Authorization": "token %s" % self._token,
				"Accept": "application/vnd.github+json",
				"X-GitHub-Api-Version": "2022-11-28",
				"Content-Type": "application/json",
			})
		try:
			r = urllib.request.urlopen(req)
			crudo = r.read()
			return r.status, (json.loads(crudo) if crudo else {}), dict(r.headers)
		except urllib.error.HTTPError as e:
			cuerpo_err = e.read().decode()[:300]
			if e.code in tolerar:
				return e.code, cuerpo_err, dict(e.headers)
			raise SystemExit("\nFALLÓ %s %s -> %s\n%s\n"
							 % (metodo, ruta, e.code, cuerpo_err))

	def leer(self, ruta, tolerar=(404,)):
		return self._pedir("GET", ruta, tolerar=tolerar)

	def escribir(self, metodo, ruta, cuerpo=None, *, que, tolerar=()):
		self.plan.append("%-6s %-52s %s" % (metodo, ruta, que))
		if not self.aplicar:
			return None, None
		cod, res, _h = self._pedir(metodo, ruta, cuerpo, tolerar=tolerar)
		return cod, res


# ---------------------------------------------------------------------------
# Fases
# ---------------------------------------------------------------------------

def preflight(gh, fase="preflight"):
	"""Nada se crea si el terreno no está como tiene que estar.

	EL CHEQUEO DE EXISTENCIA DEPENDE DE LA FASE, y hacerlo genérico fue un error: que los
	repositorios de ensayo ya existan bloquea a `crear` —sería duplicar— y es un requisito
	de `transferir`, que sin ellos no tiene qué mover. Un preflight que no distingue la
	fase termina impidiendo justo el paso siguiente.
	"""
	print("PREFLIGHT")
	problemas = []

	cod, quien, hdrs = gh.leer("/user")
	login = (quien or {}).get("login")
	scopes = {s.strip() for s in (hdrs.get("X-OAuth-Scopes") or "").split(",") if s.strip()}
	print("  PAT de la cuenta ............. %s" % login)
	print("  scopes ....................... %s" % (", ".join(sorted(scopes)) or "ninguno"))
	if login != CUENTA:
		problemas.append(
			"el PAT es de «%s» y tiene que ser de «%s»: sólo el dueño puede crear "
			"repositorios en su propia cuenta" % (login, CUENTA))
	for scope in ("repo", "delete_repo"):
		if scope not in scopes:
			problemas.append("falta el scope `%s`" % scope)

	cod, mem, _h = gh.leer("/orgs/%s/memberships/%s" % (ORG, CUENTA))
	rol = (mem or {}).get("role") if cod == 200 else None
	print("  rol de %s en %s ... %s" % (CUENTA, ORG, rol))
	if rol != "admin":
		problemas.append(
			"«%s» tiene rol `%s` en la organización y para recibir una transferencia "
			"necesita `admin` (Owner). Es la subida TEMPORAL de la ventana del ensayo: "
			"se hace a mano, y se baja a `member` al terminar — la bajada es un ítem "
			"verificable de este guion, no un recordatorio." % (CUENTA, rol))

	cod, org, _h = gh.leer("/orgs/%s" % ORG)
	if cod == 200 and org.get("members_can_create_repositories"):
		problemas.append(
			"`members_can_create_repositories` quedó en true. No hace falta abrirlo: la "
			"vía elegida fue el rol, que es puntual y reversible.")

	existentes = [n for n in NOMBRES if gh.leer("/repos/%s/%s" % (CUENTA, n))[0] == 200]
	if fase == "crear" and existentes:
		problemas.append("ya existen en %s: %s — corré `limpiar` antes"
						 % (CUENTA, existentes))
	if fase == "transferir" and not existentes:
		problemas.append(
			"no hay repositorios de ensayo en %s para transferir — corré `crear` antes"
			% CUENTA)

	if problemas:
		print("\nPREFLIGHT FALLÓ:")
		for p in problemas:
			print("  · %s" % p)
		raise SystemExit(1)
	print("  todo en orden\n")


def crear(gh):
	"""Crea los repositorios de ensayo EN LA CUENTA REAL. Nada existente se toca."""
	for nombre in NOMBRES:
		_permitido(nombre)
		if gh.leer("/repos/%s/%s" % (CUENTA, nombre))[0] == 200:
			print("  ya existe: %s" % nombre)
			continue
		gh.escribir("POST", "/user/repos", {
			"name": nombre,
			"description": "Descartable: ensayo de transferencia (PRM). Borrar.",
			"private": True, "auto_init": True,
		}, que="crear %s/%s" % (CUENTA, nombre))


def transferir(gh):
	for nombre in NOMBRES:
		_permitido(nombre)
		cod, _r, _h = gh.leer("/repos/%s/%s" % (CUENTA, nombre))
		if cod != 200:
			print("  no está en %s (¿ya transferido?): %s" % (CUENTA, nombre))
			continue
		gh.escribir("POST", "/repos/%s/%s/transfer" % (CUENTA, nombre),
					{"new_owner": ORG},
					que="transferir %s -> %s" % (nombre, ORG))
	if not gh.aplicar:
		return
	# La transferencia es asincrónica: se confirma releyendo del lado del destino.
	for nombre in NOMBRES:
		for _ in range(30):
			if gh.leer("/repos/%s/%s" % (ORG, nombre))[0] == 200:
				print("  confirmado en %s: %s" % (ORG, nombre))
				break
			time.sleep(2)
		else:
			raise SystemExit("  %s no apareció en %s tras 60s" % (nombre, ORG))


def duenio_real(gh, nombre):
	"""Quién es el dueño HOY, o None si no existe.

	OJO CON LA REDIRECCIÓN. Después de una transferencia, GitHub sigue resolviendo la
	ruta vieja: `GET /repos/primateuy/prm-test-migracion-uno` devuelve 200 y responde con
	`prm-sandbox/prm-test-migracion-uno`. Verificar «se fue del origen» por el código HTTP
	de la ruta vieja da un FALSO POSITIVO garantizado, y borrar por esa ruta borraría el
	repositorio en su dueño nuevo creyendo que se limpia el viejo.

	Lo único que dice la verdad es `owner.login` del cuerpo.
	"""
	for candidato in (ORG, CUENTA):
		cod, datos, _h = gh.leer("/repos/%s/%s" % (candidato, nombre))
		if cod == 200:
			return ((datos.get("owner") or {}).get("login"), datos.get("full_name"))
	return (None, None)


def limpiar(gh):
	"""Borra los repos de ensayo, una sola vez y por su dueño REAL."""
	for nombre in NOMBRES:
		_permitido(nombre)
		duenio, full = duenio_real(gh, nombre)
		if not duenio:
			print("  ya no existe: %s" % nombre)
			continue
		gh.escribir("DELETE", "/repos/%s" % full, que="borrar %s" % full)


def verificar_transferencia(gh):
	"""Los tres del lado del destino, comprobado por `owner.login`."""
	print("VERIFICACIÓN DE LA TRANSFERENCIA")
	mal = []
	for nombre in NOMBRES:
		duenio, full = duenio_real(gh, nombre)
		print("  %-30s dueño: %s" % (nombre, duenio or "no existe"))
		if duenio != ORG:
			mal.append(nombre)
	if mal:
		raise SystemExit("\nNO llegaron a %s: %s" % (ORG, mal))
	print("  los %s están en %s\n" % (len(NOMBRES), ORG))


def revocacion(gh):
	"""La revocación es un PASO DEL ENSAYO, no la limpieza.

	Un PAT clásico se revoca a mano —GitHub no expone endpoint para eso— así que lo que
	se comprueba acá es el efecto: el mismo token tiene que dejar de servir. Sin esta
	comprobación, «lo revoqué» es una creencia.
	"""
	cod, cuerpo, _h = gh._pedir("GET", "/user", tolerar=(401, 403, 404))
	print("GET /user con el PAT del ensayo -> %s" % cod)
	if cod == 401:
		print("\nREVOCACIÓN COMPROBADA: el token ya no sirve.")
		return
	print("\nEL TOKEN SIGUE VIVO. Revocalo en GitHub → Settings → Developer settings →")
	print("Personal access tokens → Tokens (classic) → prm-ensayo-migracion → Delete,")
	print("y volvé a correr esta fase.")
	raise SystemExit(1)


def rol_restaurado(gh):
	"""La bajada de primateuy a Member, verificada por relectura."""
	cod, mem, _h = gh.leer("/orgs/%s/memberships/%s" % (ORG, CUENTA))
	rol = (mem or {}).get("role") if cod == 200 else None
	print("rol de %s en %s: %s" % (CUENTA, ORG, rol))
	if rol == "member":
		print("BAJADA COMPROBADA.")
		return
	print("TODAVÍA ES %s. Bajalo a Member y volvé a correr esta fase." % rol)
	raise SystemExit(1)


FASES = {
	"preflight": preflight, "crear": crear, "transferir": transferir,
	"verificar": verificar_transferencia,
	"limpiar": limpiar, "revocacion": revocacion, "rol": rol_restaurado,
}


def token_desde_rtf():
	txt = subprocess.run(["textutil", "-convert", "txt", "-stdout", RTF],
						 capture_output=True, text=True).stdout
	m = re.search(r"(ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)", txt)
	if not m:
		raise SystemExit("no encontré el PAT en %s" % RTF)
	return m.group(1)


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("fase", choices=sorted(FASES))
	ap.add_argument("--apply", action="store_true")
	ap.add_argument("--token-desde-rtf", action="store_true")
	args = ap.parse_args()

	token = os.environ.get("PRM_PAT_MIGRACION")
	if not token and args.token_desde_rtf:
		token = token_desde_rtf()
	if not token:
		raise SystemExit("Falta el PAT: exportá PRM_PAT_MIGRACION o pasá --token-desde-rtf.")

	gh = Github(token, aplicar=args.apply)
	print("=" * 74)
	print("Ensayo de migración — fase «%s» — %s"
		  % (args.fase, "APPLY" if args.apply else "DRY-RUN"))
	print("origen: %s (cuenta REAL)   destino: %s" % (CUENTA, ORG))
	print("=" * 74)

	if args.fase not in ("preflight", "revocacion", "rol", "verificar"):
		preflight(gh, fase=args.fase)
	FASES[args.fase](gh)

	if gh.plan:
		print("\nOPERACIONES (%s)" % len(gh.plan))
		for i, p in enumerate(gh.plan, 1):
			print("%3d. %s" % (i, p))
	if not args.apply and args.fase in ("crear", "transferir", "limpiar"):
		print("\nDRY-RUN: no se envió ninguna escritura.")


if __name__ == "__main__":
	main()
