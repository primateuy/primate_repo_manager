#!/usr/bin/env python3
# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Sonda de permisos: qué puede hacer de verdad la App del sandbox.

POR QUÉ EXISTE. La lección más cara de F1 fue que el módulo DEDUJO lo que la credencial
podía hacer —miró `permissions.admin`— en vez de preguntárselo a la API. Nunca consultó
el endpoint de protección y el informe declaró "no sabemos" sobre 113 repositorios.

Esta sonda hace lo contrario: llama cada endpoint que F2/F3 necesita, con el token de
instalación real, y registra qué responde. El set mínimo de permisos de la App de
producción sale de acá, con evidencia, no de una tabla escrita de memoria.

CONTROL NEGATIVO. Incluye a propósito un endpoint cuyo permiso NO se concedió
(`/actions/workflows`). Si ese diera 200, la sonda no estaría probando nada y todos los
demás resultados serían sospechosos.

CADA ESCRITURA SE REVIERTE. Las operaciones van de a pares: aplicar y deshacer, crear y
borrar. Al terminar, el sandbox tiene que quedar como lo dejó el poblado — y el script
lo comprueba corriendo la verificación del manifiesto al final.

SÓLO TOCA EL SANDBOX. La organización está fija en el código y el repositorio de pruebas
también. No recibe parámetros que puedan apuntarla a otro lado.

USO
    python3 sonda_permisos.py            # dry-run: lista las llamadas que haría
    python3 sonda_permisos.py --apply    # las ejecuta y reporta qué respondió cada una
"""
import argparse
import base64
import json
import time
import urllib.error
import urllib.request

import jwt

ORG = "prm-sandbox"
API = "https://api.github.com"
APP_ID = "4808079"
INSTALLATION_ID = "158565221"
PEM = ("/Users/darylyturraldelopez/Desktop/Odoo/Desarrollos Documentos/"
	   "PRM(Primate Repo Manager)/prm-sandbox.2026-09-02.private-key.pem")

# Repositorio de ensayo: público, para que las protecciones funcionen en plan gratuito.
REPO = "sbx-cliente-publico"
RAMA = "17.0"
# El control negativo necesita un privado: ver el comentario en correr().
REPO_PRIVADO = "sbx-cliente-privado"
# Repositorio efímero que la sonda crea y borra: es la única forma de probar la creación
# en la organización, que es la fila «a confirmar» de la tabla de permisos.
#
# El nombre está FUERA de los prefijos del manifiesto (`sbx-`, `prm-sbx-`, `webOCA`) a
# propósito: ningún script que filtre por esos prefijos lo va a tocar por accidente, y a
# ojo en el listado de la organización se distingue de un repo sembrado.
REPO_EFIMERO = "zz-sonda-efimera-borrar"
TEAM_EFIMERO = "zz-sonda-team-borrar"


def token_instalacion():
	ahora = int(time.time())
	j = jwt.encode({"iat": ahora - 60, "exp": ahora + 540, "iss": APP_ID},
				   open(PEM).read(), algorithm="RS256")
	req = urllib.request.Request(
		"%s/app/installations/%s/access_tokens" % (API, INSTALLATION_ID),
		method="POST",
		headers={"Authorization": "Bearer %s" % j,
				 "Accept": "application/vnd.github+json"})
	return json.loads(urllib.request.urlopen(req).read())["token"]


RTF_TOKEN = ("/Users/darylyturraldelopez/Desktop/Odoo/Desarrollos Documentos/"
			 "PRM(Primate Repo Manager)/token-poblado.rtf")


def borrar_con_pat(nombre):
	"""Red de seguridad: limpia el repo efímero con el PAT de poblado.

	Se usa SÓLO si la App no pudo borrarlo. No cambia el veredicto de la sonda —el
	hallazgo queda registrado igual—; existe para no dejar residuo en la organización.
	"""
	import re as _re
	import subprocess as _sp
	txt = _sp.run(["textutil", "-convert", "txt", "-stdout", RTF_TOKEN],
				  capture_output=True, text=True).stdout
	m = _re.search(r"(github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+)", txt)
	if not m:
		print("  !! no pude leer el PAT de poblado: borrá %s/%s a mano" % (ORG, nombre))
		return
	req = urllib.request.Request(
		"%s/repos/%s/%s" % (API, ORG, nombre), method="DELETE",
		headers={"Authorization": "token %s" % m.group(1),
				 "Accept": "application/vnd.github+json"})
	try:
		urllib.request.urlopen(req)
		print("  limpieza: %s/%s borrado con el PAT de poblado" % (ORG, nombre))
	except urllib.error.HTTPError as e:
		print("  !! tampoco el PAT pudo borrarlo (%s): borralo a mano" % e.code)


class Sonda:
	def __init__(self, token, aplicar):
		self._token = token
		self.aplicar = aplicar
		self.resultados = []
		self.hallazgos = []

	def _pedir_directo(self, metodo, ruta, cuerpo=None):
		"""Llamada que NO entra al informe: se usa para la limpieza previa."""
		datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
		req = urllib.request.Request("%s%s" % (API, ruta), data=datos, method=metodo,
									 headers={
										 "Authorization": "token %s" % self._token,
										 "Accept": "application/vnd.github+json",
										 "Content-Type": "application/json",
									 })
		try:
			r = urllib.request.urlopen(req)
			crudo = r.read()
			return r.status, (json.loads(crudo) if crudo else None)
		except urllib.error.HTTPError as e:
			e.read()
			return e.code, None

	def llamar(self, metodo, ruta, cuerpo=None, *, que, permiso, espera_403=False,
			   ok_extra=()):
		"""Ejecuta una llamada y registra qué respondió, sin abortar nunca.

		Una sonda que corta en el primer 403 sólo informa del primero; lo que se necesita
		es el mapa completo de qué se puede y qué no.
		"""
		if not self.aplicar:
			self.resultados.append(
				(metodo, ruta, que, permiso, None, espera_403, ok_extra))
			return None, None
		url = "%s%s" % (API, ruta)
		datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
		req = urllib.request.Request(url, data=datos, method=metodo, headers={
			"Authorization": "token %s" % self._token,
			"Accept": "application/vnd.github+json",
			"X-GitHub-Api-Version": "2022-11-28",
			"Content-Type": "application/json",
		})
		try:
			r = urllib.request.urlopen(req)
			crudo = r.read()
			cod, res = r.status, (json.loads(crudo) if crudo else {})
			# En un 200 esta cabecera es la ÚNICA forma de saber qué permiso consumió el
			# endpoint. Va en su propio campo y NO dentro del cuerpo: varias respuestas
			# son listas, y meterle una clave las convertía en dict y rompía al iterar.
			exigido = r.headers.get("X-Accepted-GitHub-Permissions")
		except urllib.error.HTTPError as e:
			cuerpo_err = e.read().decode()
			cod = e.code
			try:
				res = json.loads(cuerpo_err)
			except ValueError:
				res = {"message": cuerpo_err[:120]}
			# GitHub dice en esta cabecera qué permiso exigía el endpoint. Es la
			# respuesta directa a "cuál es el mínimo", sin adivinar.
			exigido = e.headers.get("X-Accepted-GitHub-Permissions")
		self.resultados.append(
			(metodo, ruta, que, permiso, (cod, res, exigido), espera_403, ok_extra))
		return cod, res


PROTECCION = {
	"required_status_checks": None,
	"enforce_admins": False,
	"required_pull_request_reviews": {"required_approving_review_count": 1},
	"restrictions": None,
	"allow_force_pushes": False,
}

RULESET = {
	"name": "sonda-efimera",
	"target": "branch",
	"enforcement": "active",
	"conditions": {"ref_name": {"include": ["refs/heads/19.0"], "exclude": []}},
	"rules": [{"type": "non_fast_forward"}],
}


def limpiar_residuo(s):
	"""Borra lo que una corrida anterior pueda haber dejado a mitad de camino.

	Una sonda que se cae después de abrir la PR y antes de cerrarla deja el sandbox
	sucio, y la corrida siguiente choca con 422 en cada creación. Limpiar al arrancar
	la hace repetible.
	"""
	if not s.aplicar:
		return
	cod, prs = s._pedir_directo(
		"GET", "/repos/%s/%s/pulls?head=%s:sonda-efimera&state=open" % (ORG, REPO, ORG))
	for pr in (prs or []):
		s._pedir_directo("PATCH", "/repos/%s/%s/pulls/%s" % (ORG, REPO, pr["number"]),
						 {"state": "closed"})
		print("  limpieza previa: PR #%s cerrada" % pr["number"])
	cod, _ = s._pedir_directo(
		"DELETE", "/repos/%s/%s/git/refs/heads/sonda-efimera" % (ORG, REPO))
	if 200 <= cod < 300:
		print("  limpieza previa: rama sonda-efimera borrada")
	cod, _ = s._pedir_directo("DELETE", "/repos/%s/%s" % (ORG, REPO_EFIMERO))
	if 200 <= cod < 300:
		print("  limpieza previa: %s borrado" % REPO_EFIMERO)
	cod, _ = s._pedir_directo("DELETE", "/orgs/%s/teams/%s" % (ORG, TEAM_EFIMERO))
	if 200 <= cod < 300:
		print("  limpieza previa: team %s borrado" % TEAM_EFIMERO)


def correr(s):
	r = "/repos/%s/%s" % (ORG, REPO)

	# --- lecturas gated por permisos de lectura -----------------------------
	s.llamar("GET", "%s/branches/%s/protection" % (r, RAMA),
			 que="leer protección de rama", permiso="Administration: read",
			 # Un 404 «Branch not protected» ES la respuesta correcta: la rama existe y
			 # no está protegida. Tratarlo como falla sería repetir exactamente el error
			 # que el módulo tenía en F1, colapsando dos 404 opuestos en "no pude".
			 ok_extra=(404,))
	s.llamar("GET", "%s/rulesets" % r, que="listar rulesets",
			 permiso="Administration: read")
	s.llamar("GET", "/orgs/%s/teams" % ORG, que="listar teams",
			 permiso="Members: read")

	# --- CONTROL NEGATIVO ---------------------------------------------------
	# CONTRA EL PRIVADO, NO CONTRA EL PÚBLICO. En un repositorio público los workflows se
	# leen sin el permiso de Actions —es metadata pública—, así que el control corrido
	# contra `sbx-cliente-publico` daba 200 y no controlaba nada. Es la misma asimetría
	# que en producción: los workflows de los 82 públicos se leían con 5 permisos y los
	# de los 31 privados daban 403.
	s.llamar("GET", "/repos/%s/%s/actions/workflows" % (ORG, REPO_PRIVADO),
			 que="listar workflows de un PRIVADO (permiso NO concedido)",
			 permiso="Actions: read — ausente a propósito", espera_403=True)

	# --- protección de rama: aplicar y deshacer -----------------------------
	s.llamar("PUT", "%s/branches/%s/protection" % (r, RAMA), PROTECCION,
			 que="APLICAR protección de rama", permiso="Administration: write")
	s.llamar("DELETE", "%s/branches/%s/protection" % (r, RAMA),
			 que="  revertir: quitar la protección", permiso="Administration: write")

	# --- ruleset: crear y borrar --------------------------------------------
	cod, res = s.llamar("POST", "%s/rulesets" % r, RULESET,
						que="CREAR ruleset", permiso="Administration: write")
	rid = (res or {}).get("id") if cod in (200, 201) else None
	if rid:
		s.llamar("DELETE", "%s/rulesets/%s" % (r, rid),
				 que="  revertir: borrar el ruleset", permiso="Administration: write")
	elif not s.aplicar:
		s.resultados.append(("DELETE", "%s/rulesets/{id}" % r,
							 "  revertir: borrar el ruleset",
							 "Administration: write", None, False, ()))

	# --- contenidos: rama y commit ------------------------------------------
	cod, ref = s.llamar("GET", "%s/git/ref/heads/%s" % (r, RAMA),
						que="leer la ref de la rama", permiso="Contents: read")
	sha = ((ref or {}).get("object") or {}).get("sha") if cod == 200 else None
	if sha or not s.aplicar:
		s.llamar("POST", "%s/git/refs" % r,
				 {"ref": "refs/heads/sonda-efimera", "sha": sha},
				 que="CREAR rama", permiso="Contents: write")
		s.llamar("PUT", "%s/contents/sonda/prueba.md" % r, {
			"message": "[ADD][9999] archivo de la sonda",
			"content": base64.b64encode(b"sonda\n").decode(),
			"branch": "sonda-efimera",
		}, que="COMMITEAR un archivo", permiso="Contents: write")
		s.llamar("POST", "%s/pulls" % r, {
			"title": "[ADD][9999] PR de la sonda", "head": "sonda-efimera",
			"base": RAMA, "body": "Efímera: la sonda la cierra enseguida.",
		}, que="ABRIR pull request", permiso="Pull requests: write")

	# --- statuses y checks (lectura) ----------------------------------------
	if sha:
		s.llamar("GET", "%s/commits/%s/status" % (r, sha),
				 que="leer estado de commit", permiso="Commit statuses: read")
		s.llamar("GET", "%s/commits/%s/check-runs" % (r, sha),
				 que="leer check-runs", permiso="Checks: read")

	# --- grant por team: dar y quitar ---------------------------------------
	# Se usa `sbx-sin-clasificar`, que en el manifiesto NO tiene grant de este team: así
	# darlo y quitarlo devuelve el sandbox exactamente a su estado, sin pisar un grant
	# que el manifiesto sí declara.
	s.llamar("PUT", "/orgs/%s/teams/desarrollo/repos/%s/sbx-sin-clasificar" % (ORG, ORG),
			 {"permission": "push"}, que="DAR grant por team",
			 permiso="Members: write")
	s.llamar("DELETE", "/orgs/%s/teams/desarrollo/repos/%s/sbx-sin-clasificar" % (ORG, ORG),
			 que="  revertir: quitar el grant por team", permiso="Members: write")

	# --- teams: crear, poner una persona, borrar ----------------------------
	# Sobre un team EFÍMERO, no sobre `desarrollo`: sacar y volver a poner a alguien del
	# team real dejaría el sandbox fuera del manifiesto si el re-alta fallara a mitad.
	# Esto además responde si `members: write` se usa para algo, porque el grant por team
	# resultó exigir sólo `members: read`.
	cod, res = s.llamar("POST", "/orgs/%s/teams" % ORG,
						{"name": TEAM_EFIMERO, "privacy": "closed"},
						que="CREAR team", permiso="Members: write")
	if cod in (200, 201) or not s.aplicar:
		s.llamar("PUT", "/orgs/%s/teams/%s/memberships/primateuy" % (ORG, TEAM_EFIMERO),
				 {"role": "member"}, que="AGREGAR persona al team",
				 permiso="Members: write")
		s.llamar("DELETE", "/orgs/%s/teams/%s/memberships/primateuy" % (ORG, TEAM_EFIMERO),
				 que="  revertir: sacar la persona del team", permiso="Members: write")
		s.llamar("DELETE", "/orgs/%s/teams/%s" % (ORG, TEAM_EFIMERO),
				 que="  revertir: borrar el team", permiso="Members: write")

	# --- colaborador directo: dar y quitar ----------------------------------
	s.llamar("PUT", "/repos/%s/sbx-sin-clasificar/collaborators/%s" % (ORG, "primateuy"),
			 {"permission": "triage"}, que="DAR grant directo",
			 permiso="Administration: write")
	s.llamar("DELETE", "/repos/%s/sbx-sin-clasificar/collaborators/%s" % (ORG, "primateuy"),
			 que="  revertir: quitar el grant directo", permiso="Administration: write")

	# --- crear y borrar un repo en la organización --------------------------
	# Es la fila «a confirmar» de la tabla: si esto anda con lo concedido, el permiso
	# de organización que hace falta queda demostrado en vez de supuesto.
	s.llamar("POST", "/orgs/%s/repos" % ORG,
			 {"name": REPO_EFIMERO, "private": False, "auto_init": True},
			 que="CREAR repositorio en la org",
			 permiso="Organization administration: write (a confirmar)")
	cod, res = s.llamar("DELETE", "/repos/%s/%s" % (ORG, REPO_EFIMERO),
						que="  revertir: borrar el repositorio",
						permiso="Administration: write")
	if s.aplicar and cod is not None and not (200 <= cod < 300):
		# «Crea pero no borra» NO es un error de la sonda: es justamente el dato que la
		# tabla definitiva necesita. Se registra con lo que GitHub dijo que exigía, y el
		# repo se limpia igual con el PAT de poblado para no dejar basura en la org.
		s.hallazgos.append(
			"La App CREA repositorios en la org pero NO puede borrarlos (%s: %s)."
			% (cod, (res or {}).get("message")))
		borrar_con_pat(REPO_EFIMERO)


def revertir_pr_y_rama(s):
	"""Cierra la PR de la sonda y borra su rama. Va aparte porque necesita el número."""
	if not s.aplicar:
		s.resultados.append(("PATCH", "/repos/%s/%s/pulls/{n}" % (ORG, REPO),
							 "  revertir: cerrar la PR", "Pull requests: write",
							 None, False, ()))
		s.resultados.append(("DELETE", "/repos/%s/%s/git/refs/heads/sonda-efimera" % (ORG, REPO),
							 "  revertir: borrar la rama", "Contents: write",
							 None, False, ()))
		return
	cod, prs = s.llamar("GET", "/repos/%s/%s/pulls?head=%s:sonda-efimera" % (ORG, REPO, ORG),
						que="buscar la PR de la sonda", permiso="Pull requests: read")
	for pr in (prs or []):
		s.llamar("PATCH", "/repos/%s/%s/pulls/%s" % (ORG, REPO, pr["number"]),
				 {"state": "closed"}, que="  revertir: cerrar la PR",
				 permiso="Pull requests: write")
	s.llamar("DELETE", "/repos/%s/%s/git/refs/heads/sonda-efimera" % (ORG, REPO),
			 que="  revertir: borrar la rama", permiso="Contents: write")


def informe(s):
	print("\n" + "=" * 78)
	if not s.aplicar:
		print("DRY-RUN — %s llamadas planificadas, ninguna enviada" % len(s.resultados))
		print("=" * 78)
		for i, (metodo, ruta, que, permiso, _, neg, _ok) in enumerate(s.resultados, 1):
			print("%3d. %-6s %-58s" % (i, metodo, ruta))
			print("     %s%s" % (que, "   [CONTROL NEGATIVO]" if neg else ""))
			print("     permiso esperado: %s" % permiso)
		return

	print("RESULTADO DE LA SONDA")
	print("=" * 78)
	problemas = []
	for metodo, ruta, que, permiso, res, neg, ok_extra in s.resultados:
		cod, cuerpo, exigido = res if res else ("?", {}, None)
		bien = (cod == 403) if neg else (200 <= cod < 300 or cod in ok_extra)
		print("  %s %-4s %-50s %s" % ("ok  " if bien else "MAL ", cod, que,
									  exigido or permiso))
		if not bien:
			mensaje = (cuerpo or {}).get("message") if isinstance(cuerpo, dict) else None
			problemas.append((que, cod, mensaje, exigido))
	print("\n" + "-" * 78)
	if problemas:
		print("LO QUE NO PUDO:")
		for que, cod, msg, exigido in problemas:
			print("  · %s -> %s %s" % (que, cod, msg))
			if exigido:
				print("      GitHub dice que exige: %s" % exigido)
	else:
		print("Todas las operaciones de F2/F3 son posibles con los permisos concedidos,")
		print("y el control negativo falló como debía.")
	if s.hallazgos:
		print("\nHALLAZGOS DE LA SONDA:")
		for h in s.hallazgos:
			print("  · %s" % h)


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--apply", action="store_true",
					help="ejecuta las llamadas; sin esto sólo las lista")
	args = ap.parse_args()

	print("=" * 78)
	print("Sonda de permisos — App %s sobre %s — %s"
		  % (APP_ID, ORG, "APPLY" if args.apply else "DRY-RUN"))
	print("=" * 78)

	s = Sonda(token_instalacion() if args.apply else "", aplicar=args.apply)
	limpiar_residuo(s)
	correr(s)
	revertir_pr_y_rama(s)
	informe(s)

	if args.apply:
		print("\nAhora corré la verificación del manifiesto para confirmar que el")
		print("sandbox quedó como estaba:")
		print("  python3 poblar_sandbox.py --token-desde-rtf --verificar")


if __name__ == "__main__":
	main()
