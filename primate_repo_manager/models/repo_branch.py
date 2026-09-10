# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Ramas relevantes de un repo. Las feature branches no se persisten: son efímeras y
serían ruido; de 503 ramas leídas, 84 caían en 'otras' y la mayoría son de trabajo."""
import ast
import json
import logging

import re

from odoo import _, fields, models

from .repo_rules import BRANCH_ROLES

_logger = logging.getLogger(__name__)


def _cuando(momento):
	"""«hace 3 h», «ayer», «14 feb». Corto, como en el entregable."""
	if not momento:
		return ""
	transcurrido = fields.Datetime.now() - momento
	horas = transcurrido.days * 24 + transcurrido.seconds // 3600
	if horas < 1:
		return _("hace %s min") % max(1, transcurrido.seconds // 60)
	if horas < 24:
		return _("hace %s h") % horas
	if transcurrido.days == 1:
		return _("ayer")
	if transcurrido.days < 30:
		return _("hace %s días") % transcurrido.days
	return fields.Date.to_string(momento.date())


class RepoBranch(models.Model):
	_name = "repo.branch"
	_description = "Rama de un repositorio"
	_order = "repository_id, name"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	name = fields.Char(string="Nombre", required=True)
	role = fields.Selection(BRANCH_ROLES, string="Rol", index=True)
	is_default = fields.Boolean(string="Es la rama por defecto")

	# Estado REAL en GitHub, no el declarado.
	protected = fields.Boolean(string="Protegida")
	protection_json = fields.Text(string="Protección (JSON crudo)")
	# La distinción que evita un informe mentiroso: leer la protección exige permiso de
	# admin, y sin él GitHub devuelve 404 —el mismo código que cuando no hay protección—.
	protection_readable = fields.Boolean(
		string="Protección legible", default=True,
		help="False cuando la API no dejó leerla. NO es lo mismo que 'no tiene protección': "
			 "el endpoint devuelve 404 en los dos casos y confundirlos arruina la auditoría.")
	protection_cause = fields.Selection(
		[("plan_limit", "Límite del plan de GitHub"),
		 ("no_admin_permission", "La App no tiene permiso de administrador"),
		 ("unknown", "Sin determinar")],
		string="Causa de la ilegibilidad",
		help="Sólo cuando `protection_readable` es falso. Se guarda como dato para que "
			 "los conteos separen lo que se resuelve con una decisión de plan de lo que "
			 "se resuelve reinstalando la App.")
	ruleset_count = fields.Integer(string="Rulesets que la alcanzan")

	last_commit_sha = fields.Char(string="Último commit")
	last_commit_date = fields.Datetime(string="Fecha del último commit")

	# Sólo para ramas espejo de forks.
	ahead_upstream = fields.Integer(string="Commits adelante del upstream")
	behind_upstream = fields.Integer(string="Commits detrás del upstream")
	comparison_readable = fields.Boolean(string="Comparación legible", default=True)

	# --- E3.2a · la comparación contra la rama de producción de SU línea ---
	#
	# NO SE REUSAN `ahead_upstream` / `behind_upstream`: ésos miden contra el upstream de
	# un fork, que es otra pregunta. Dos significados en un campo es cómo se llega a un
	# informe que afirma una cosa habiendo medido otra.
	line_branch_name = fields.Char(
		string="Rama de producción de su línea", readonly=True,
		help="Contra cuál se comparó. La del rol «prod» de la línea si existe; si no, la "
			 "base de la línea.")
	ahead_of_line = fields.Integer(
		string="Commits propios sin integrar", readonly=True,
		help="Commits que están en esta rama y NO en la de producción de su línea. Cero "
			 "significa integrada: lo que tenía ya está del otro lado.")
	line_comparison_readable = fields.Boolean(
		string="Se pudo comparar con su línea", readonly=True,
		help="Falso mientras no se haya comparado o cuando la comparación falló. Sin "
			 "esto, «cero commits propios» y «no se pudo mirar» serían el mismo cero.")
	line_comparison_cause = fields.Char(
		string="Por qué no se pudo comparar", readonly=True)

	# El árbol de git viene truncado en repositorios muy grandes. Se guarda como dato para
	# que el inventario de módulos pueda decir «acá no pude ver todo» en vez de dejar que
	# alguien lea el silencio como «no hay módulos».
	module_scan_truncated = fields.Boolean(
		string="Árbol truncado al escanear", copy=False)

	_branch_uniq = models.Constraint(
		"UNIQUE (repository_id, name)",
		"Esa rama ya está registrada en el repositorio.")


class RepoBranchComparacion(models.Model):
	"""La comparación «Exige … · Tiene …» de una rama — página 3b del entregable.

	TRES ESTADOS, NO DOS, Y ES TODO EL PUNTO. GitHub devuelve el mismo 404 cuando una rama
	no está protegida y cuando quien pregunta no puede saberlo, y F1 se construyó entero
	alrededor de no confundirlos. Una rama ILEGIBLE dibujada como «no tiene» sería ese
	mismo defecto volviendo por la ventana de la interfaz: el informe dejó de mentir y la
	pantalla empezaría a hacerlo, que es peor, porque la pantalla es lo que la gente mira.

	Por eso `estado` distingue `ilegible` de `sin_proteccion`, y lo ilegible no aporta
	NADA a las listas de exige/tiene: de lo que no se pudo leer no se afirma nada.

	Y UNA SOLA IMPLEMENTACIÓN. La usa la pestaña de ramas (B1.4) para explicar por qué una
	rama incumple, y la plantilla (B1.5) para contar cuántas incumplen cada exigencia. Dos
	comparadores darían dos respuestas para la misma pregunta y ninguna forma de saber
	cuál mirar.
	"""
	_inherit = "repo.branch"

	def _proteccion_observada(self):
		"""El JSON de protección, parseado. `{}` si no hay o no se puede leer.

		Se guarda con `str(datos)` —repr de Python, comillas simples—, así que `json.loads`
		no alcanza. Se intenta primero igual: el día que eso se corrija, esto sigue
		andando sin tocarlo.
		"""
		self.ensure_one()
		crudo = self.protection_json
		if not crudo:
			return {}
		for parsear in (json.loads, ast.literal_eval):
			try:
				valor = parsear(crudo)
				return valor if isinstance(valor, dict) else {}
			except (ValueError, SyntaxError):
				continue
		_logger.warning(
			"Repo Manager: no se pudo interpretar la protección de %s", self.display_name)
		return {}

	def linea(self):
		"""La línea de versión de esta rama: `19.0-dev` → `19.0`, `17.0_pos` → `17.0`.

		Una rama que no empieza con una versión no pertenece a ninguna línea —`main`,
		`gh-pages`— y para ellas no hay contra qué comparar. Devuelve vacío y quien
		pregunta decide qué hacer con eso; inventar una línea sería inventar la
		comparación entera.
		"""
		self.ensure_one()
		encontrado = re.match(r"^(\d+\.\d+)", self.name or "")
		return encontrado.group(1) if encontrado else ""

	def rama_de_produccion_de_la_linea(self):
		"""Contra qué se mide «ya está integrada»: la jerarquía de línea.

		**Rol `prod` si existe; si no, la base de la línea.** Los dos casos son reales:
		un repositorio gobernado por el módulo tiene `19.0-prod`, y uno que todavía no se
		migró tiene sólo `19.0`. Medir el segundo contra nada lo dejaría sin higiene
		posible justamente donde más ramas viejas hay.

		Nunca se compara una rama contra sí misma: la rama de producción no es candidata
		a nada, y `ahead 0` sobre sí misma sería un «integrada» que no significa nada.
		"""
		self.ensure_one()
		linea = self.linea()
		if not linea:
			return self.browse()
		hermanas = self.repository_id.branch_ids.filtered(
			lambda b: b.linea() == linea and b != self)
		prod = hermanas.filtered(lambda b: b.role == "prod")[:1]
		if prod:
			return prod
		return hermanas.filtered(lambda b: b.name == linea)[:1]

	def _rulesets_que_la_cubren(self):
		"""Los rulesets del espejo cuyas condiciones nombran a esta rama."""
		self.ensure_one()
		ref = "refs/heads/%s" % self.name
		cubren = self.env["repo.ruleset"]
		for fila in self.env["repo.ruleset"].search([
				("repository_id", "=", self.repository_id.id),
				("present", "=", True)]):
			condiciones = (fila.definicion() or {}).get("conditions") or {}
			incluidas = (condiciones.get("ref_name") or {}).get("include") or []
			if ref in incluidas or "~ALL" in incluidas:
				cubren |= fila
		return cubren

	def _proteccion_efectiva(self):
		"""Lo que protege esta rama HOY, venga de donde venga.

		DOS MECANISMOS, UNA RESPUESTA. GitHub protege ramas de dos maneras —la protección
		clásica y los rulesets— y el módulo aplica **rulesets**. La auditoría miraba sólo
		el flag de la protección clásica, así que un repositorio gobernado por este mismo
		módulo salía reportado como «sin protección»: **el informe acusaba al módulo de no
		haber hecho lo que el módulo acababa de hacer**, sobre todos los repositorios de
		B1. Lo destapó el ensayo del nacimiento (B5.4).

		Los rulesets se traducen de vuelta al vocabulario de la protección clásica, que es
		el que la comparación ya habla. Es la INVERSA de lo que hace `repo.ruleset`
		—plantilla → ruleset— y las dos tienen que decir lo mismo: si una agrega una
		exigencia y la otra no la reconoce, vuelve el falso «sin protección».
		"""
		self.ensure_one()
		efectiva = dict(self._proteccion_observada())
		for fila in self._rulesets_que_la_cubren():
			for regla in (fila.definicion() or {}).get("rules") or []:
				tipo = regla.get("type")
				parametros = regla.get("parameters") or {}
				if tipo == "pull_request":
					revisiones = efectiva.get("required_pull_request_reviews") or {}
					pedidas = parametros.get("required_approving_review_count") or 0
					# El MÁXIMO de los dos mecanismos: si la protección clásica ya exige
					# dos y el ruleset una, la rama sigue exigiendo dos.
					revisiones["required_approving_review_count"] = max(
						revisiones.get("required_approving_review_count") or 0, pedidas)
					if parametros.get("require_code_owner_review"):
						revisiones["require_code_owner_reviews"] = True
					efectiva["required_pull_request_reviews"] = revisiones
				elif tipo == "non_fast_forward":
					efectiva["allow_force_pushes"] = {"enabled": False}
				elif tipo == "deletion":
					efectiva["allow_deletions"] = {"enabled": False}
				elif tipo == "required_signatures":
					efectiva["required_signatures"] = {"enabled": True}
				elif tipo == "required_status_checks":
					contextos = [
						c.get("context") for c in
						parametros.get("required_status_checks") or []]
					previos = (efectiva.get("required_status_checks") or {}).get(
						"contexts") or []
					efectiva["required_status_checks"] = {
						"contexts": sorted(set(previos) | set(filter(None, contextos)))}
		return efectiva

	def comparacion_de_politica(self):
		"""Qué exige la política para esta rama y qué tiene de verdad.

		Returns:
			dict: ``estado`` (uno de `ilegible`, `no_exige`, `sin_proteccion`, `parcial`,
			`completa`), ``exige`` y ``tiene`` como listas de textos legibles, ``faltan``
			con las claves técnicas de lo que se exige y no está, y ``causa`` cuando el
			estado es ilegible.
		"""
		self.ensure_one()
		plantilla = self.repository_id.plantilla_efectiva()
		regla = plantilla.rule_for_role(self.role) if plantilla else {}
		exigencias = self._exigencias(regla, plantilla)

		if not self.protection_readable:
			# De lo que no se pudo leer no se afirma nada: ni que cumple ni que no.
			return {
				"estado": "ilegible",
				"causa": dict(self._fields["protection_cause"].selection).get(
					self.protection_cause, _("Sin determinar")),
				"exige": [e["etiqueta"] for e in exigencias],
				"tiene": [],
				"faltan": [],
			}

		if not exigencias:
			return {"estado": "no_exige", "causa": False,
					"exige": [], "tiene": [], "faltan": []}

		# LA PROTECCIÓN EFECTIVA, no sólo la clásica: un ruleset protege igual.
		observada = self._proteccion_efectiva()
		cumplidas = [e for e in exigencias if e["cumple"](observada)]
		faltantes = [e for e in exigencias if e not in cumplidas]
		if not faltantes:
			estado = "completa"
		elif cumplidas:
			estado = "parcial"
		else:
			estado = "sin_proteccion"
		return {
			"estado": estado,
			"causa": False,
			"exige": [e["etiqueta"] for e in faltantes] or [e["etiqueta"] for e in exigencias],
			"tiene": [e["etiqueta"] for e in cumplidas],
			"faltan": [e["clave"] for e in faltantes],
		}

	def _exigencias(self, regla, plantilla):
		"""Las exigencias de la política, cada una con cómo se comprueba.

		La lista es la misma que traduce B1.1 a un ruleset. Si alguna vez dejan de ser la
		misma, la pantalla estaría explicando un incumplimiento contra reglas distintas de
		las que el módulo aplica.
		"""
		exigencias = []
		if regla.get("require_pr"):
			cuantas = regla.get("required_approvals") or 0
			exigencias.append({
				"clave": "require_pr",
				"etiqueta": (_("%s revisión(es)") % cuantas) if cuantas
							else _("pull request"),
				"cumple": lambda o, n=cuantas: (
					((o.get("required_pull_request_reviews") or {})
					 .get("required_approving_review_count") or 0) >= n
					if n else bool(o.get("required_pull_request_reviews"))),
			})
		if regla.get("require_codeowner_review"):
			exigencias.append({
				"clave": "require_codeowner_review",
				"etiqueta": _("revisión de owner"),
				"cumple": lambda o: bool((o.get("required_pull_request_reviews") or {})
										 .get("require_code_owner_reviews")),
			})
		if regla.get("block_force_push"):
			exigencias.append({
				"clave": "block_force_push",
				"etiqueta": _("sin escritura directa"),
				# `bool(o)` primero, y no es un detalle: sin objeto de protección la clave
				# no está, y «no está la clave que lo permite» se leería como «está
				# prohibido». Una rama SIN protección aparecería teniendo «sin escritura
				# directa, sin borrado» — el estado más peligroso del sistema disfrazado
				# del segundo mejor. Lo cazó un test antes de que llegara a la pantalla.
				"cumple": lambda o: bool(o) and not (
					o.get("allow_force_pushes") or {}).get("enabled"),
			})
		if regla.get("block_deletion"):
			exigencias.append({
				"clave": "block_deletion",
				"etiqueta": _("sin borrado"),
				"cumple": lambda o: bool(o) and not (
					o.get("allow_deletions") or {}).get("enabled"),
			})
		if regla.get("require_signed_commits"):
			exigencias.append({
				"clave": "require_signed_commits",
				"etiqueta": _("commits firmados"),
				"cumple": lambda o: bool((o.get("required_signatures") or {})
										 .get("enabled")),
			})
		# Los checks SÓLO si la plantilla los da por confirmados. Es la misma guarda que
		# en el armado del ruleset: un nombre de check equivocado bloquea todos los merges,
		# y mientras no estén confirmados no se exige ninguno — así que tampoco se cuenta
		# a nadie como incumplidor por no tenerlos.
		if plantilla and plantilla.status_checks_defined and plantilla.required_check_ids:
			nombres = plantilla.required_check_ids.mapped("name")
			exigencias.append({
				"clave": "required_status_checks",
				"etiqueta": _("checks de CI"),
				"cumple": lambda o, n=nombres: set(n).issubset(set(
					(o.get("required_status_checks") or {}).get("contexts") or [])),
			})
		return exigencias


class RepoRepositoryRamas(models.Model):
	"""Las filas de la pestaña de ramas — página 3b, columna por columna."""
	_inherit = "repo.repository"

	def datos_de_ramas(self):
		"""Todo lo que la tabla de ramas dibuja, en una sola llamada.

		Se arma en el servidor y no en el componente porque la comparación exige/tiene es
		política, y la política se decide en un solo lugar. Un componente que la
		recalculara en JavaScript sería el segundo lugar.
		"""
		self.ensure_one()
		Regla = self.env["repo.branch.role.rule"]
		roles = dict(self.env["repo.branch"]._fields["role"].selection)
		filas = []
		for rama in self.branch_ids:
			regla = Regla.regla_para(rama.name)
			comparacion = rama.comparacion_de_politica()
			filas.append({
				"id": rama.id,
				"nombre": rama.name,
				"es_default": rama.is_default,
				"rol": roles.get(rama.role, _("Sin rol")),
				"regla": regla.name or _("ninguna regla"),
				"comparacion": comparacion,
				"commit": {
					"sha": (rama.last_commit_sha or "")[:7],
					"cuando": _cuando(rama.last_commit_date),
				},
				# El atraso sólo tiene sentido donde hay contra qué compararse.
				"atraso": (
					"+%s / −%s" % (rama.ahead_upstream, rama.behind_upstream)
					if rama.role in ("mirror", "patch") and rama.comparison_readable
					else None),
				"legibilidad": (
					_("Leída") if rama.protection_readable else comparacion["causa"]),
			})
		return filas
