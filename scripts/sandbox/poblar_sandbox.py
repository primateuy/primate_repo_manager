#!/usr/bin/env python3
# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Puebla la organización sandbox con repositorios dummy, de forma reproducible.

POR QUÉ ESTE SCRIPT NO ES PARTE DEL MÓDULO. Sembrar fixtures exige crear repositorios,
teams y grants; darle esa capacidad al addon significaría que el módulo pueda escribir
sobre cualquier organización sólo para armarse un banco de pruebas. Vive afuera, se corre
a mano, y usa un token distinto del de la App.

QUÉ GARANTIZA
  · Idempotencia: correrlo dos veces deja el mismo estado, no el doble de repos. Cada
    operación consulta antes de escribir.
  · Dry-run por defecto: sin `--apply` no manda una sola escritura.
  · Preflight que falla ruidosamente: si la organización no está como se verificó en el
    FRENO 1, no siembra nada. Un desfase silencioso en la matriz de permisos invalida
    todo lo que se pruebe después.

CREDENCIAL
  Fine-grained PAT con resource owner `prm-sandbox`. Se lee de la variable de entorno
  `PRM_SANDBOX_TOKEN`, o del .rtf de la carpeta PRM con `--token-desde-rtf`. Nunca se
  imprime, ni siquiera truncado.

USO
    python3 poblar_sandbox.py                 # dry-run: dice qué haría
    python3 poblar_sandbox.py --apply         # ejecuta
    python3 poblar_sandbox.py --limpiar       # dry-run del borrado
    python3 poblar_sandbox.py --limpiar --apply
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

ORG = "prm-sandbox"
API = "https://api.github.com"
RTF_TOKEN = ("/Users/darylyturraldelopez/Desktop/Odoo/Desarrollos Documentos/"
			 "PRM(Primate Repo Manager)/token-poblado.rtf")

# La cuenta que NO es owner de la organización. Su rol se verifica en el preflight.
MIEMBRO = "primateuy"

# ---------------------------------------------------------------------------
# El manifiesto. Cada repositorio existe para que un hallazgo concreto tenga
# dónde ocurrir; el comentario de cada uno dice cuál.
#
# OJO CON LOS NOMBRES: la clasificación NO tiene regla catch-all a «cliente», a
# propósito (ver data/repo_rules_data.xml). Un repo que no matchea ninguna regla
# queda sin clasificar, y eso ES un hallazgo. Por eso:
#   · `sbx-localizacion`  matchea (?i)(localizacion|localización|l10n)  -> localizacion
#   · `prm-sbx-interno`   matchea (?i)^(primate|pcm|prm)[-_]?           -> interno
#   · `webOCA`            es fork                                       -> fork_upstream
#   · los dos `sbx-cliente-*` NO matchean nada: se clasifican A MANO en Odoo como
#     `cliente`. No es una limitación del script, es el flujo real que van a seguir
#     los 43 repos sin clasificar de la cuenta de producción.
#   · `sbx-sin-clasificar` se deja sin tocar para que el hallazgo
#     `classification_missing` siga teniendo un caso vivo después de clasificar el resto.
# ---------------------------------------------------------------------------

CONVENCION = "[%s][%s] %s"          # -> "[ADD][1042] agrega el modelo de ejemplo"
RAMAS_ESTANDAR = ["17.0", "17.0.Staging", "19.0"]

# LA RAMA `main` RESIDUAL ES UNA DECISIÓN, NO UN DESCUIDO.
#
# `auto_init: true` crea `main` con un «Initial commit», y ese commit es el punto de
# partida de las tres ramas de versión. Después la rama por defecto se mueve a 17.0 y
# `main` queda ahí. Se deja a propósito, por tres motivos:
#
#   1. El espejo NO la va a ver. `_sync_branches` persiste sólo los roles de
#      ROLES_PERSISTIDOS más la rama por defecto, y `role_for("main")` devuelve `other`.
#      O sea: en Odoo ni siquiera aparece como ruido — se saltea. Que exista en GitHub y
#      no en el espejo es exactamente el comportamiento que hay que poder confirmar.
#   2. Es fiel a la cuenta real, donde 15 repositorios tienen main o master.
#   3. En `prm-sbx-interno` se la deja ADEMÁS como rama por defecto, y ahí sí se persiste
#      y dispara `default_branch_off_convention`. Es el mismo nombre de rama cumpliendo
#      dos papeles opuestos según sea o no la default: el contraste es el punto.
#
# Su «Initial commit» sí entra en las muestras de commits de cada rama, y eso está
# contemplado en los ratios de más abajo.

REPOS = [
	{
		"name": "sbx-cliente-publico",
		"private": False,
		"description": "Dummy: camino completo de apply sobre un repo público.",
		"branches": RAMAS_ESTANDAR,
		"default_branch": "17.0",
		# EL RATIO SE CUENTA COMO LO MIDE LA AUDITORÍA, no como se lee este manifiesto.
		# `_sync_commit_samples` muestrea el HISTORIAL de cada rama principal, y todas
		# las ramas salen del «Initial commit» que crea `auto_init`: ese commit entra en
		# la muestra UNA VEZ POR RAMA y no cumple la convención.
		#
		#   17.0          initial + 6 = 7        17.0.Staging  initial + 1 = 2
		#   19.0          initial + 1 = 2        total muestreado = 11
		#   fuera de convención: 3 «Initial commit» + arreglo rapido + wip + subo cambios = 6
		#   ratio = 6/11 = 54,5 %  >  50 %  ->  el modulador SÍ se activa (severidad alta)
		#
		# El umbral se compara con `>` estricto: 50 % exacto NO alcanza. Por eso hay tres
		# mensajes malos en 17.0 y no dos — con dos el ratio daba 50 % clavado y el
		# modulador quedaba sin probar justo en el borde.
		"commits": [
			("17.0", CONVENCION % ("ADD", "1042", "modelo de ejemplo del cliente")),
			("17.0", CONVENCION % ("FIX", "1043", "corrige el cálculo del total")),
			("17.0", "arreglo rapido"),
			("17.0", "wip"),
			("17.0", "subo cambios"),
			("17.0", CONVENCION % ("IMP", "1044", "mejora el rendimiento del listado")),
			("17.0.Staging", CONVENCION % ("ADD", "1045", "backport a staging")),
			("19.0", CONVENCION % ("ADD", "1046", "port inicial a 19.0")),
		],
	},
	{
		"name": "sbx-cliente-privado",
		"private": True,
		"description": "Dummy: el techo de plan tiene que DETECTARSE, no chocarse.",
		"branches": RAMAS_ESTANDAR,
		"default_branch": "17.0",
		"commits": [
			("17.0", CONVENCION % ("ADD", "1050", "modelo privado de ejemplo")),
			("17.0", "cambios varios"),
			("19.0", CONVENCION % ("ADD", "1051", "port inicial a 19.0")),
		],
	},
	{
		"name": "sbx-localizacion",
		"private": False,
		"description": "Dummy: plantilla de localización, la más estricta de la spec.",
		"branches": RAMAS_ESTANDAR,
		"default_branch": "17.0",
		# La plantilla de localización exige firma. Estos commits se crean por API y
		# NO van firmados: el hallazgo `signed_commits_missing` tiene que aparecer.
		#
		# Y el ratio acá queda en 50 % CLAVADO a propósito (4 malos de 8: los 3 «Initial
		# commit» más «fix rapido de la adenda»). Es el caso de borde: con `>` estricto el
		# modulador NO se activa, y tenerlo al lado de sbx-cliente-publico —que da 54,5 %
		# y sí se activa— es lo que prueba que el umbral es `>` y no `>=`.
		"commits": [
			("17.0", CONVENCION % ("ADD", "2001", "comprobante fiscal de ejemplo")),
			("17.0", CONVENCION % ("FIX", "2002", "ajusta el tipo de cambio")),
			("17.0", "fix rapido de la adenda"),
			("17.0.Staging", CONVENCION % ("IMP", "2003", "validación previa al envío")),
			("19.0", CONVENCION % ("ADD", "2004", "port inicial a 19.0")),
		],
	},
	{
		"name": "prm-sbx-interno",
		"private": False,
		"description": "Dummy: herramienta interna. Queda con main por defecto a propósito.",
		"branches": RAMAS_ESTANDAR,
		# A PROPÓSITO se queda en `main`: es el único caso que dispara
		# `default_branch_off_convention`, que sólo se emite en repos evaluados
		# contra plantilla — y éste sí clasifica, como `interno`.
		"default_branch": "main",
		"commits": [
			("main", CONVENCION % ("ADD", "3001", "utilidad interna de ejemplo")),
			("17.0", "commit sin convencion"),
			("19.0", CONVENCION % ("IMP", "3002", "limpieza del script")),
		],
	},
	{
		"name": "sbx-sin-clasificar",
		"private": False,
		"description": "Dummy: mantiene vivo el hallazgo de repositorio sin clasificar.",
		"branches": ["17.0"],
		"default_branch": "17.0",
		"commits": [("17.0", "algo")],
	},
]

# Fork con upstream REAL: es lo que hace comprobable el atraso contra OCA.
FORK = {"upstream": "OCA/web", "name": "webOCA"}

# Un solo team, con permisos distintos por repositorio.
TEAMS = [
	{
		"name": "desarrollo",
		"description": "Team de prueba para los grants por equipo.",
		"members": [MIEMBRO],
		"repos": {
			"sbx-cliente-publico": "maintain",
			# `push` es como la API llama a `write`.
			"sbx-localizacion": "push",
		},
	},
]

# Grants directos. El de sbx-localizacion CONVIVE con el del team sobre el mismo
# repositorio: GitHub reporta el más alto de los dos, y ésa es la sutileza que hace
# que un drift se lea mal si el módulo sólo mira el team.
COLABORADORES = [
	{"repo": "prm-sbx-interno", "login": MIEMBRO, "permission": "admin"},
	{"repo": "sbx-localizacion", "login": MIEMBRO, "permission": "maintain"},
]


# ---------------------------------------------------------------------------
# Cliente HTTP mínimo
# ---------------------------------------------------------------------------

class Github:
	def __init__(self, token, aplicar):
		self._token = token
		self.aplicar = aplicar
		self.plan = []

	def _pedir(self, metodo, ruta, cuerpo=None, tolerar=()):
		url = ruta if ruta.startswith("http") else "%s%s" % (API, ruta)
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
			return r.status, (json.loads(crudo) if crudo else {})
		except urllib.error.HTTPError as e:
			cuerpo_err = e.read().decode()[:200]
			if e.code in tolerar:
				return e.code, cuerpo_err
			raise SystemExit(
				"\nFALLÓ %s %s -> %s\n%s\n" % (metodo, ruta, e.code, cuerpo_err))

	def leer(self, ruta, tolerar=(404,)):
		"""Lectura. Se hace SIEMPRE, también en dry-run: es lo que permite que el plan
		diga la verdad sobre lo que falta en vez de suponerlo."""
		return self._pedir("GET", ruta, tolerar=tolerar)

	def escribir(self, metodo, ruta, cuerpo=None, que=""):
		"""Toda mutación pasa por acá. En dry-run se anota y no se manda."""
		self.plan.append(que or "%s %s" % (metodo, ruta))
		if not self.aplicar:
			return None
		cod, res = self._pedir(metodo, ruta, cuerpo)
		return res


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight(gh):
	"""La organización tiene que estar EXACTAMENTE como se verificó en el FRENO 1.

	No es paranoia: entre el FRENO 1 y este script hubo un cambio de rol manual
	(primateuy subió a Owner y volvió a bajar). Un desfase así, si pasa silencioso,
	invalida todo lo que se pruebe después sobre la matriz de permisos — un Owner ve
	todos los repos por herencia y ningún grant se puede medir.
	"""
	print("PREFLIGHT")
	problemas = []

	cod, org = gh.leer("/orgs/%s" % ORG)
	if cod != 200:
		raise SystemExit("  la organización %s no responde (%s)" % (ORG, cod))
	print("  plan .......................... %s" % (org.get("plan") or {}).get("name"))
	print("  default_repository_permission . %s" % org.get("default_repository_permission"))
	print("  members_can_create_repositories %s" % org.get("members_can_create_repositories"))
	if org.get("default_repository_permission") != "none":
		problemas.append("base permissions debería ser `none`, está en `%s` — con permiso "
						 "heredado ningún grant explícito es medible"
						 % org.get("default_repository_permission"))
	if org.get("members_can_create_repositories") is not False:
		problemas.append("members_can_create_repositories debería estar en false")

	cod, mem = gh.leer("/orgs/%s/memberships/%s" % (ORG, MIEMBRO))
	rol = mem.get("role") if cod == 200 else None
	estado = mem.get("state") if cod == 200 else None
	print("  rol de %-22s %s (%s)" % (MIEMBRO, rol, estado))
	if rol != "member":
		problemas.append(
			"%s tiene rol `%s` y tiene que ser `member`. Un Owner accede a todos los "
			"repositorios por herencia: los grants por team y directos dejan de ser "
			"distinguibles y la matriz de permisos no prueba nada. Si lo subiste para la "
			"ventana del ensayo de migración, bajalo antes de sembrar." % (MIEMBRO, rol))
	if estado != "active":
		problemas.append("la membresía de %s está en `%s`, no `active`" % (MIEMBRO, estado))

	cod, inv = gh.leer("/orgs/%s/invitations" % ORG)
	if cod == 200 and inv:
		problemas.append("hay invitaciones sin aceptar: %s"
						 % [i.get("login") or i.get("email") for i in inv])

	if problemas:
		print("\nPREFLIGHT FALLÓ — no se siembra nada:")
		for p in problemas:
			print("  · %s" % p)
		raise SystemExit(1)
	print("  todo en orden\n")


# ---------------------------------------------------------------------------
# Siembra
# ---------------------------------------------------------------------------

def sha_de_rama(gh, repo, rama):
	cod, ref = gh.leer("/repos/%s/%s/git/ref/heads/%s" % (ORG, repo, rama))
	return ref.get("object", {}).get("sha") if cod == 200 else None


def sembrar_repo(gh, spec):
	nombre = spec["name"]
	cod, repo = gh.leer("/repos/%s/%s" % (ORG, nombre))
	existe = cod == 200

	if not existe:
		gh.escribir("POST", "/orgs/%s/repos" % ORG, {
			"name": nombre,
			"description": spec["description"],
			"private": spec["private"],
			"auto_init": True,           # nace con un commit inicial en `main`
			"has_issues": False,
			"has_projects": False,
			"has_wiki": False,
		}, que="crear repo %s (%s)" % (nombre, "privado" if spec["private"] else "público"))
	else:
		print("    ya existe: %s" % nombre)

	# En dry-run no hay repo del cual leer el SHA base: el plan se detiene acá y lo dice.
	if not existe and not gh.aplicar:
		gh.plan.append("  · ramas %s, %s commit(s), default=%s (requiere el repo creado)"
					   % (spec["branches"], len(spec["commits"]), spec["default_branch"]))
		return

	base = sha_de_rama(gh, nombre, repo.get("default_branch", "main") if existe else "main")
	for rama in spec["branches"]:
		if sha_de_rama(gh, nombre, rama):
			continue
		gh.escribir("POST", "/repos/%s/%s/git/refs" % (ORG, nombre),
					{"ref": "refs/heads/%s" % rama, "sha": base},
					que="  crear rama %s/%s" % (nombre, rama))

	for i, (rama, mensaje) in enumerate(spec["commits"]):
		ruta = "relleno/%02d.md" % i
		cod, _ = gh.leer("/repos/%s/%s/contents/%s?ref=%s" % (ORG, nombre, ruta, rama))
		if cod == 200:
			continue
		import base64
		gh.escribir("PUT", "/repos/%s/%s/contents/%s" % (ORG, nombre, ruta), {
			"message": mensaje,
			"content": base64.b64encode(
				("Relleno de sandbox.\n\n%s\n" % mensaje).encode()).decode(),
			"branch": rama,
		}, que="  commit en %s/%s: %r" % (nombre, rama, mensaje))

	actual = repo.get("default_branch") if existe else "main"
	if actual != spec["default_branch"]:
		gh.escribir("PATCH", "/repos/%s/%s" % (ORG, nombre),
					{"default_branch": spec["default_branch"]},
					que="  rama por defecto de %s: %s -> %s"
						% (nombre, actual, spec["default_branch"]))


def sembrar_fork(gh):
	destino = FORK["name"]
	cod, _ = gh.leer("/repos/%s/%s" % (ORG, destino))
	if cod == 200:
		print("    ya existe: %s" % destino)
		return
	corto = FORK["upstream"].split("/")[1]
	gh.escribir("POST", "/repos/%s/forks" % FORK["upstream"], {"organization": ORG},
				que="forkear %s -> %s (upstream real)" % (FORK["upstream"], ORG))

	# EL ORDEN IMPORTA Y LA ESPERA VA EN EL MEDIO. Forkear es asincrónico: GitHub
	# responde 202 y el repositorio aparece unos segundos después, con el nombre CORTO
	# del upstream. Renombrar inmediatamente le pega a un repo que todavía no existe, y
	# esperar a que aparezca el nombre NUEVO es esperar algo que sin el rename no va a
	# existir nunca. Se espera al corto, se renombra, y recién ahí se confirma el nuevo.
	gh.plan.append("  esperar a que %s/%s exista (el fork es asincrónico)" % (ORG, corto))
	if gh.aplicar:
		esperar_repo(gh, corto, "el fork")

	gh.escribir("PATCH", "/repos/%s/%s" % (ORG, corto), {"name": destino},
				que="  renombrar %s -> %s (para que clasifique como fork)" % (corto, destino))

	gh.plan.append("  verificar que %s/%s responde tras el rename" % (ORG, destino))
	if gh.aplicar:
		esperar_repo(gh, destino, "el repo renombrado")


def esperar_repo(gh, nombre, que, intentos=30, espera=2):
	"""Espera activa a que un repositorio exista. Falla ruidosamente si no aparece."""
	for _ in range(intentos):
		if gh.leer("/repos/%s/%s" % (ORG, nombre))[0] == 200:
			return
		time.sleep(espera)
	raise SystemExit("  %s (%s/%s) no apareció después de %ss"
					 % (que, ORG, nombre, intentos * espera))


def sembrar_teams(gh):
	for spec in TEAMS:
		slug = spec["name"]
		cod, _ = gh.leer("/orgs/%s/teams/%s" % (ORG, slug))
		if cod != 200:
			gh.escribir("POST", "/orgs/%s/teams" % ORG, {
				"name": spec["name"], "description": spec["description"],
				"privacy": "closed",
			}, que="crear team %s" % slug)
		else:
			print("    ya existe: team %s" % slug)

		for login in spec["members"]:
			cod, mem = gh.leer("/orgs/%s/teams/%s/memberships/%s" % (ORG, slug, login))
			if cod == 200 and mem.get("state") == "active":
				continue
			gh.escribir("PUT", "/orgs/%s/teams/%s/memberships/%s" % (ORG, slug, login),
						{"role": "member"}, que="  %s al team %s" % (login, slug))

		# Idempotencia del grant por team: hay que CONSULTAR antes, y con el vocabulario
		# de lectura. Sin esto el PUT se reemitía en cada corrida y el dry-run nunca
		# llegaba a cero operaciones, que es la señal de que el sandbox ya está en estado.
		cod, repos_team = gh.leer("/orgs/%s/teams/%s/repos?per_page=100" % (ORG, slug))
		actuales = {r["name"]: r.get("role_name") for r in repos_team} if cod == 200 else {}
		for repo, permiso in spec["repos"].items():
			if actuales.get(repo) == EQUIVALENTES.get(permiso, permiso):
				continue
			gh.escribir("PUT", "/orgs/%s/teams/%s/repos/%s/%s" % (ORG, slug, ORG, repo),
						{"permission": permiso},
						que="  team %s -> %s con %s" % (slug, repo, permiso))


def sembrar_colaboradores(gh):
	for c in COLABORADORES:
		cod, actual = gh.leer(
			"/repos/%s/%s/collaborators/%s/permission" % (ORG, c["repo"], c["login"]))
		# `role_name`, no `permission`: el campo legacy colapsa `maintain` en "write" y
		# hacía que un grant ya correcto se volviera a escribir en cada corrida.
		if cod == 200 and actual.get("role_name") == c["permission"]:
			continue
		gh.escribir("PUT", "/repos/%s/%s/collaborators/%s" % (ORG, c["repo"], c["login"]),
					{"permission": c["permission"]},
					que="grant directo %s -> %s con %s"
						% (c["login"], c["repo"], c["permission"]))


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------

# Los mismos patrones que data/repo_rules_data.xml, para poder calcular acá lo que la
# auditoría va a calcular en Odoo. Si divergen, el sandbox estaría verificándose contra
# una regla distinta de la que rige, así que van copiados textualmente y con su origen.
ROLES = [
	(r"^\d+\.\d+$", "base"),
	(r"(?i)(^|[._-])staging($|[._-])", "staging"),
	(r"(?i)(^|[._-])support($|[._-])", "support"),
	(r"(?i)(^|[._-])(produccion|producción|prod)($|[._-])", "prod"),
	(r"(?i)^\d+\.\d+[._-].+", "version"),
]
PATRON_COMMIT = r"^\[(ADD|IMP|FIX)\]\[\d+\] .+"
# Vocabulario de escritura -> vocabulario de lectura. Ver el comentario en verificar().
EQUIVALENTES = {"pull": "read", "push": "write"}
UMBRAL = 50            # repo_manager.commit_violation_ratio
MUESTRA = 30           # COMMIT_SAMPLE_SIZE


def rol_de(nombre):
	for patron, rol in ROLES:
		if re.search(patron, nombre or ""):
			return rol
	return "other"


def verificar(gh):
	"""Lee el estado real y lo compara con el manifiesto. Sólo lectura."""
	fallas = []

	def chequear(cond, texto):
		print("  %s %s" % ("ok  " if cond else "MAL ", texto))
		if not cond:
			fallas.append(texto)

	for spec in REPOS + [{"name": FORK["name"], "private": False, "fork": True}]:
		nombre = spec["name"]
		cod, repo = gh.leer("/repos/%s/%s" % (ORG, nombre))
		print("\n%s" % nombre)
		if cod != 200:
			chequear(False, "existe (respondió %s)" % cod)
			continue

		chequear(repo["private"] == spec["private"],
				 "visibilidad %s" % ("privado" if repo["private"] else "público"))
		if spec.get("fork"):
			padre = (repo.get("parent") or {}).get("full_name")
			chequear(repo.get("fork") and padre == FORK["upstream"],
					 "es fork de %s" % padre)
		else:
			chequear(repo["default_branch"] == spec["default_branch"],
					 "rama por defecto %s" % repo["default_branch"])

		cod, ramas = gh.leer("/repos/%s/%s/branches?per_page=100" % (ORG, nombre))
		nombres = sorted(b["name"] for b in ramas) if cod == 200 else []
		if not spec.get("fork"):
			faltan = [r for r in spec["branches"] if r not in nombres]
			chequear(not faltan, "ramas %s%s" % (nombres, " faltan %s" % faltan if faltan else ""))

			# El ratio, contado como lo cuenta la auditoría: historial de cada rama
			# principal, tope de 30, el «Initial commit» incluido una vez por rama.
			total = malos = 0
			detalle = []
			for r in nombres:
				if rol_de(r) not in ("base", "staging", "support", "prod") \
						and r != repo["default_branch"]:
					continue
				cod, commits = gh.leer(
					"/repos/%s/%s/commits?sha=%s&per_page=%s" % (ORG, nombre, r, MUESTRA))
				if cod != 200:
					continue
				mal_r = sum(
					1 for c in commits
					if not re.match(PATRON_COMMIT,
									(c["commit"]["message"] or "").split("\n")[0]))
				total += len(commits)
				malos += mal_r
				detalle.append("%s=%s/%s" % (r, mal_r, len(commits)))
			ratio = (malos / total * 100) if total else 0
			modula = ratio > UMBRAL
			print("       muestra: %s  ->  %s/%s fuera de convención = %.1f%%  %s"
				  % (" ".join(detalle), malos, total, ratio,
					 "MODULA (alta)" if modula else "no modula"))

	# --- teams y grants ---
	for spec in TEAMS:
		slug = spec["name"]
		print("\nteam %s" % slug)
		cod, _ = gh.leer("/orgs/%s/teams/%s" % (ORG, slug))
		chequear(cod == 200, "existe")
		for login in spec["members"]:
			cod, mem = gh.leer("/orgs/%s/teams/%s/memberships/%s" % (ORG, slug, login))
			chequear(cod == 200 and mem.get("state") == "active", "%s es miembro" % login)
		# OJO CON EL ENDPOINT. `GET /orgs/{org}/teams/{slug}/repos/{owner}/{repo}`
		# responde 204 SIN CUERPO salvo que se pida el media type
		# `application/vnd.github.v3.repository+json`; leerlo así devuelve None y parece
		# que el grant no existe cuando existe. Se usa el listado, que sí trae `role_name`.
		cod, repos_team = gh.leer("/orgs/%s/teams/%s/repos?per_page=100" % (ORG, slug))
		reales = {r["name"]: r.get("role_name") for r in repos_team} if cod == 200 else {}
		for repo, permiso in spec["repos"].items():
			real = reales.get(repo)
			# GitHub ESCRIBE y LEE con vocabularios distintos: el PUT toma
			# pull/push/maintain/admin y el role_name devuelve read/write/maintain/admin.
			# `push` y `write` son el mismo permiso con dos nombres; compararlos crudos
			# reporta un desvío que no existe.
			chequear(EQUIVALENTES.get(permiso, permiso) == real,
					 "%s con %s (real: %s)" % (repo, permiso, real))

	print("\ngrants directos")
	for c in COLABORADORES:
		cod, res = gh.leer(
			"/repos/%s/%s/collaborators/%s/permission" % (ORG, c["repo"], c["login"]))
		# `permission` es el campo LEGACY y COLAPSA los roles: `maintain` y `write` salen
		# los dos como "write", `triage` sale como "read". El valor fino está en
		# `role_name`, que es el que usa el módulo (repo_collaborator.permission_from_role_name).
		# Comparar contra `permission` haría fallar un grant correcto.
		legacy = res.get("permission") if cod == 200 else None
		real = res.get("role_name") if cod == 200 else None
		# Es el permiso EFECTIVO: donde hay grant por team y directo sobre el mismo repo,
		# gana el más alto. Por eso se informa y no se exige igualdad.
		chequear(real == c["permission"],
				 "%s: %s tiene %s (legacy lo colapsa a %s)"
				 % (c["repo"], c["login"], real, legacy))

	print("\n" + "=" * 74)
	if fallas:
		print("VERIFICACIÓN: %s desvío(s) respecto del manifiesto" % len(fallas))
		for f in fallas:
			print("  · %s" % f)
		raise SystemExit(1)
	print("VERIFICACIÓN: el sandbox coincide con el manifiesto")


def limpiar(gh):
	"""Borra lo que este script crea. Sólo toca nombres del manifiesto."""
	nombres = [r["name"] for r in REPOS] + [FORK["name"]]
	for nombre in nombres:
		if gh.leer("/repos/%s/%s" % (ORG, nombre))[0] == 200:
			gh.escribir("DELETE", "/repos/%s/%s" % (ORG, nombre), que="borrar %s" % nombre)
	for spec in TEAMS:
		if gh.leer("/orgs/%s/teams/%s" % (ORG, spec["name"]))[0] == 200:
			gh.escribir("DELETE", "/orgs/%s/teams/%s" % (ORG, spec["name"]),
						que="borrar team %s" % spec["name"])


# ---------------------------------------------------------------------------

def token_desde_rtf(path):
	txt = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
						 capture_output=True, text=True).stdout
	m = re.search(r"(github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+)", txt)
	if not m:
		raise SystemExit("no encontré un token en %s" % path)
	return m.group(1)


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--apply", action="store_true",
					help="ejecuta de verdad; sin esto sólo dice qué haría")
	ap.add_argument("--limpiar", action="store_true", help="borra lo sembrado")
	ap.add_argument("--verificar", action="store_true",
					help="compara el estado real contra el manifiesto (sólo lectura)")
	ap.add_argument("--token-desde-rtf", action="store_true",
					help="lee el token del .rtf de la carpeta PRM")
	args = ap.parse_args()

	token = os.environ.get("PRM_SANDBOX_TOKEN")
	if not token and args.token_desde_rtf:
		token = token_desde_rtf(RTF_TOKEN)
	if not token:
		raise SystemExit(
			"Falta el token. Exportá PRM_SANDBOX_TOKEN o pasá --token-desde-rtf.")

	gh = Github(token, aplicar=args.apply)
	modo = "APPLY" if args.apply else "DRY-RUN"
	print("=" * 74)
	print("Poblado de %s — %s%s" % (ORG, modo, " (limpieza)" if args.limpiar else ""))
	print("=" * 74)

	if args.verificar:
		preflight(gh)
		verificar(gh)
		return

	preflight(gh)

	if args.limpiar:
		limpiar(gh)
	else:
		print("REPOSITORIOS")
		for spec in REPOS:
			sembrar_repo(gh, spec)
		print("FORK")
		sembrar_fork(gh)
		print("TEAMS")
		sembrar_teams(gh)
		print("COLABORADORES")
		sembrar_colaboradores(gh)

	print("\n%s" % ("=" * 74))
	print("OPERACIONES (%s)" % len(gh.plan))
	print("=" * 74)
	for i, p in enumerate(gh.plan, 1):
		print("%3d. %s" % (i, p))
	if not gh.plan:
		print("  ninguna: el sandbox ya está en el estado del manifiesto")
	if not args.apply:
		print("\nDRY-RUN: no se envió ninguna escritura. Con --apply se ejecuta.")


if __name__ == "__main__":
	main()
