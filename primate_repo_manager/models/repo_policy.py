# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La política, como datos comparables.

En Fase 1 estas tablas SOLO se leen: la auditoría compara lo observado en GitHub contra
lo declarado acá y produce hallazgos. Nada se aplica. Son las mismas filas que en F3 van
a generar los rulesets, así que el trabajo de F1 no se tira.

Un valor que no está decidido NO se completa con un default razonable: se marca como sin
definir y la auditoría reporta "no evaluable". Comparar contra un número inventado
produce hallazgos falsos, que es peor que no reportar nada — sobre todo con checks
requeridos, donde un nombre equivocado en un ruleset bloquea todos los merges del repo.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .repo_collaborator import PERMISSIONS
from .repo_rules import BRANCH_ROLES, CLASSIFICATIONS, ROLES_GOBERNADOS

MERGE_STRATEGIES = [
	("squash", "Squash"),
	("merge_commit", "Merge commit"),
	("rebase", "Rebase"),
]


def _mensaje_de_clasificacion_ocupada(env, diagnostics):
	"""El mensaje del índice único, nombrando a la plantilla que ya estaba si se puede.

	Un «ya existe un registro» manda a buscar a mano cuál es. Postgres dice en el detalle
	del error qué clasificación se pisó; con eso se busca la vigente y se la nombra.

	Si el detalle no viene o no se entiende —otra versión de Postgres, otro idioma—, se
	devuelve el mensaje general, que igual dice qué hacer. Nunca se rompe por adornar.
	"""
	generico = _(
		"Ya hay una plantilla de política activa para esa clasificación, y los "
		"repositorios de una clasificación se gobiernan con UNA sola. Archivá la vigente "
		"antes de activar otra: archivada sigue existiendo y se puede editar, pero no "
		"compite.")
	detalle = getattr(diagnostics, "message_detail", None) or ""
	encontrado = re.search(r"=\(([^)]+)\)", detalle)
	if not encontrado:
		return generico
	clasificacion = encontrado.group(1).strip()
	vigente = env["repo.policy.template"].search(
		[("classification_default", "=", clasificacion), ("active", "=", True)], limit=1)
	if not vigente:
		return generico
	return _(
		"«%(vigente)s» ya gobierna la clasificación «%(clasificacion)s», y se gobierna "
		"con UNA sola plantilla. Archivá «%(vigente)s» antes de activar otra: archivada "
		"sigue existiendo y se puede editar, pero no compite."
	) % {
		"vigente": vigente.name,
		"clasificacion": dict(
			vigente._fields["classification_default"].selection
		).get(clasificacion, clasificacion),
	}


class RepoPolicyTemplate(models.Model):
	_name = "repo.policy.template"
	_inherit = ["repo.policy.audited", "mail.thread"]
	_description = "Plantilla de política de gobernanza"
	_order = "sequence, name"

	name = fields.Char(string="Nombre", required=True)
	code = fields.Char(string="Código", required=True, index=True)
	sequence = fields.Integer(string="Secuencia", default=10)
	active = fields.Boolean(string="Activa", default=True)
	classification_default = fields.Selection(
		CLASSIFICATIONS, string="Clasificación que la usa por defecto")
	note = fields.Text(string="Notas")

	# --- reglas generales, heredadas por los roles de rama que no las pisen ---
	require_pr = fields.Boolean(string="Exige pull request", default=True)
	required_approvals = fields.Integer(string="Aprobaciones requeridas", default=1)
	require_codeowner_review = fields.Boolean(string="Exige revisión de owner")
	block_force_push = fields.Boolean(string="Bloquea force-push", default=True)
	block_deletion = fields.Boolean(string="Bloquea borrado de rama", default=True)
	require_signed_commits = fields.Boolean(string="Exige commits firmados")

	branch_name_pattern = fields.Char(string="Patrón de nombre de rama")
	commit_message_pattern = fields.Char(string="Patrón de mensaje de commit")

	merge_strategy_base = fields.Selection(
		MERGE_STRATEGIES, string="Estrategia hacia base", default="squash")
	merge_strategy_promotion = fields.Selection(
		MERGE_STRATEGIES, string="Estrategia en promociones", default="merge_commit")

	# --- checks requeridos: obligatorios por decisión, pero SIN NOMBRES definidos ---
	status_checks_defined = fields.Boolean(
		string="Checks definidos", default=False,
		help="Falso mientras no se sepan los nombres exactos de los checks de CI. La "
			 "decisión de la spec es que sean obligatorios, pero no nombra ninguno, y un "
			 "nombre equivocado en un ruleset bloquea TODOS los merges del repo. Mientras "
			 "esté en falso la auditoría reporta el ítem como no evaluable.")
	required_check_ids = fields.One2many(
		"repo.policy.status.check", "template_id", string="Checks requeridos")

	branch_rule_ids = fields.One2many(
		"repo.policy.branch.rule", "template_id", string="Reglas por rol de rama")
	access_rule_ids = fields.One2many(
		"repo.policy.access.rule", "template_id", string="Permisos máximos")

	repository_count = fields.Integer(
		string="Repositorios que gobierna", compute="_compute_repository_count",
		help="Los que tienen la clasificación por defecto de esta plantilla. Es lo que "
			 "convierte un formulario de configuración en una decisión con alcance.")

	max_permission_default = fields.Selection(
		PERMISSIONS, string="Permiso máximo por defecto", default="push",
		help="El techo para cualquier persona que no tenga una excepción declarada. "
			 "Un permiso observado por encima de esto es un hallazgo.")

	_code_uniq = models.Constraint(
		"UNIQUE (code)", "Ya existe una plantilla con ese código.")

	# UNA PLANTILLA ACTIVA POR CLASIFICACIÓN
	#
	# POR QUÉ ES UNA RESTRICCIÓN Y NO UN HALLAZGO. `plantilla_efectiva()` resuelve con
	# `limit=1`: con dos plantillas activas para la misma clasificación ganaba la primera
	# por `sequence, name` y nadie se enteraba. Mientras eso decidía sólo contra qué se
	# COMPARABA era un empate silencioso; desde B1 decide qué se ESCRIBE en GitHub, y un
	# empate silencioso que elige reglas de merge no es un dato: es un accidente esperando.
	# Se previene en la fuente. El `limit=1` queda como defensa en profundidad —la
	# resolución sigue siendo determinista— pero deja de ser el árbitro.
	#
	# POR QUÉ UN ÍNDICE Y NO UN `@api.constrains`. Se escribió primero como constrains, y
	# con el índice puesto al lado quedaba INALCANZABLE: Postgres rechaza el INSERT antes
	# de que el ORM llegue a correr sus validaciones, así que el mensaje lindo no se veía
	# nunca. Una guarda que no puede dispararse es peor que ninguna —parece cubrir algo—.
	# `UniqueIndex` da las dos cosas: la garantía la hace cumplir la base, incluso entre
	# dos transacciones simultáneas que un constrains no podría ver, y el mensaje es el
	# nuestro. Verificado rompiéndolo.
	#
	# LA PLANTILLA EN PREPARACIÓN TIENE SALIDA: archivarla. El índice es PARCIAL —sólo
	# sobre las activas y con clasificación—, así que se puede tener la próxima versión
	# escrita al lado de la vigente sin pelearse por la clasificación.

	_una_activa_por_clasificacion = models.UniqueIndex(
		"(classification_default) WHERE active AND classification_default IS NOT NULL",
		lambda env, diagnostics: _mensaje_de_clasificacion_ocupada(env, diagnostics),
	)

	def rule_for_role(self, branch_role):
		"""Reglas efectivas para un rol de rama: la específica si existe, o la general."""
		self.ensure_one()
		especifica = self.branch_rule_ids.filtered(lambda r: r.branch_role == branch_role)
		if especifica:
			return especifica[0]._as_dict()
		return {
			"require_pr": self.require_pr,
			"required_approvals": self.required_approvals,
			"require_codeowner_review": self.require_codeowner_review,
			"block_force_push": self.block_force_push,
			"block_deletion": self.block_deletion,
			"require_signed_commits": self.require_signed_commits,
			"block_human_push": False,
			"heredada": True,
		}

	def max_permission_for(self, member):
		"""Permiso máximo admitido para esa persona bajo esta plantilla."""
		self.ensure_one()
		excepcion = self.access_rule_ids.filtered(lambda r: r.member_id == member)
		if excepcion:
			return excepcion[0].max_permission
		return self.max_permission_default


	@api.depends("classification_default")
	def _compute_repository_count(self):
		Repo = self.env["repo.repository"]
		for plantilla in self:
			plantilla.repository_count = Repo.search_count(
				[("classification", "=", plantilla.classification_default)]
			) if plantilla.classification_default else 0

	def action_open_repositories(self):
		"""Los repositorios que esta plantilla gobierna."""
		self.ensure_one()
		accion = self.env["ir.actions.actions"]._for_xml_id(
			"primate_repo_manager.action_repo_repository")
		accion["domain"] = [("classification", "=", self.classification_default)]
		accion["display_name"] = _("Repositorios bajo «%s»") % self.name
		return accion


class RepoPolicyBranchRule(models.Model):
	_name = "repo.policy.branch.rule"
	_inherit = ["repo.policy.audited"]
	_description = "Override de política para un rol de rama"
	_order = "template_id, branch_role"

	template_id = fields.Many2one(
		"repo.policy.template", string="Plantilla", required=True, ondelete="cascade")
	branch_role = fields.Selection(BRANCH_ROLES, string="Rol de rama", required=True)
	require_pr = fields.Boolean(string="Exige pull request", default=True)
	required_approvals = fields.Integer(string="Aprobaciones requeridas", default=1)
	require_codeowner_review = fields.Boolean(string="Exige revisión de owner")
	block_force_push = fields.Boolean(string="Bloquea force-push", default=True)
	block_deletion = fields.Boolean(string="Bloquea borrado", default=True)
	require_signed_commits = fields.Boolean(string="Exige commits firmados")
	block_human_push = fields.Boolean(
		string="Bloquea el push de humanos",
		help="Para las ramas espejo de forks: sólo el job de sync las avanza, con ff-only. "
			 "Si alguien pushea ahí, es drift crítico.")
	note = fields.Char(string="Por qué")

	_role_uniq = models.Constraint(
		"UNIQUE (template_id, branch_role)",
		"Esa plantilla ya tiene una regla para ese rol de rama.")

	def _as_dict(self):
		self.ensure_one()
		return {
			"require_pr": self.require_pr,
			"required_approvals": self.required_approvals,
			"require_codeowner_review": self.require_codeowner_review,
			"block_force_push": self.block_force_push,
			"block_deletion": self.block_deletion,
			"require_signed_commits": self.require_signed_commits,
			"block_human_push": self.block_human_push,
			"heredada": False,
		}


class RepoPolicyStatusCheck(models.Model):
	_name = "repo.policy.status.check"
	_inherit = ["repo.policy.audited"]
	_description = "Check de CI requerido por una plantilla"
	_order = "template_id, name"

	template_id = fields.Many2one(
		"repo.policy.template", string="Plantilla", required=True, ondelete="cascade")
	name = fields.Char(
		string="Nombre del check", required=True,
		help="Tiene que coincidir EXACTAMENTE con el nombre del job en GitHub.")


class RepoPolicyAccessRule(models.Model):
	_name = "repo.policy.access.rule"
	_inherit = ["repo.policy.audited"]
	_description = "Permiso máximo admitido para una persona"
	_order = "template_id, member_id"

	template_id = fields.Many2one(
		"repo.policy.template", string="Plantilla", required=True, ondelete="cascade")
	member_id = fields.Many2one(
		"repo.member", string="Persona", required=True, ondelete="cascade")
	max_permission = fields.Selection(PERMISSIONS, string="Permiso máximo", required=True)
	reason = fields.Char(string="Motivo", required=True)

	_member_uniq = models.Constraint(
		"UNIQUE (template_id, member_id)",
		"Esa persona ya tiene una excepción en esta plantilla.")

	@api.constrains("max_permission", "reason")
	def _check_reason(self):
		for regla in self:
			if regla.max_permission == "admin" and not (regla.reason or "").strip():
				raise ValidationError(_(
					"Una excepción de administrador necesita un motivo escrito."))


class RepoPolicyTemplateIncumplimientos(models.Model):
	"""«Incumplen hoy», por exigencia — página 4a del entregable.

	QUÉ AGREGA. El formulario dice qué exige la plantilla; esto dice A CUÁNTOS les falta.
	Sin el número, endurecer una exigencia es una decisión a ciegas: subir las
	aprobaciones de 1 a 2 puede no afectar a nadie o romperle el día a veinte equipos, y
	desde el formulario las dos cosas se ven igual.

	LO ILEGIBLE NO CUENTA COMO INCUMPLIMIENTO — NI COMO CUMPLIMIENTO. Es la misma
	doctrina del panel de salud: meter lo que no se pudo leer en el numerador acusa a
	repositorios sanos; dejarlo afuera sin decirlo los cuenta como sanos. Se cuenta
	aparte y se muestra aparte.

	Y SALE DEL MISMO COMPARADOR QUE LA PESTAÑA DE RAMAS. Dos implementaciones de «esta
	rama cumple» darían dos números para la misma pregunta, y el día que difieran nadie
	va a saber cuál mirar.
	"""
	_inherit = "repo.policy.template"

	def incumplimientos_por_exigencia(self):
		"""Cuántas ramas gobernadas incumplen cada exigencia, hoy.

		Returns:
			list: un dict por exigencia con ``clave``, ``etiqueta``, ``incumplen``,
			``ilegibles`` y ``evaluadas``.
		"""
		self.ensure_one()
		Rama = self.env["repo.branch"]
		ramas = Rama.search([
			("repository_id.classification", "=", self.classification_default),
			("role", "in", list(ROLES_GOBERNADOS)),
		]) if self.classification_default else Rama.browse()

		# El catálogo de exigencias sale de una rama cualquiera de las gobernadas: es el
		# mismo que usa la comparación. Sin ramas no hay nada que contar y tampoco nada
		# que prometer.
		conteo, ilegibles, evaluadas = {}, 0, 0
		for rama in ramas:
			comparacion = rama.comparacion_de_politica()
			if comparacion["estado"] == "ilegible":
				ilegibles += 1
				continue
			evaluadas += 1
			for clave in comparacion["faltan"]:
				conteo[clave] = conteo.get(clave, 0) + 1

		return [
			{
				"clave": clave,
				"etiqueta": etiqueta,
				"incumplen": conteo.get(clave, 0),
				"ilegibles": ilegibles,
				"evaluadas": evaluadas,
			}
			for clave, etiqueta in self._catalogo_de_exigencias()
		]

	def _catalogo_de_exigencias(self):
		"""Las exigencias que esta plantilla declara, en el orden en que se leen."""
		self.ensure_one()
		catalogo = []
		if self.require_pr:
			catalogo.append(("require_pr", _("Exige pull request")))
		if self.require_codeowner_review:
			catalogo.append(("require_codeowner_review", _("Exige revisión de owner")))
		if self.block_force_push:
			catalogo.append(("block_force_push", _("Bloquea force-push")))
		if self.block_deletion:
			catalogo.append(("block_deletion", _("Bloquea borrado de rama")))
		if self.require_signed_commits:
			catalogo.append(("require_signed_commits", _("Exige commits firmados")))
		if self.status_checks_defined and self.required_check_ids:
			catalogo.append(("required_status_checks", _("Exige checks de CI")))
		return catalogo


class RepoPolicyTemplateChecks(models.Model):
	"""La propuesta de checks requeridos — B2.

	PROPONE, NO DECIDE. Qué checks quedan exigidos por plantilla es una decisión humana
	que se toma UNA vez con los datos delante; esto arma los datos. Por eso no hay nada
	acá que escriba `required_check_ids` ni que encienda `status_checks_defined`.

	ORDENADA POR COBERTURA, y la cobertura es lo que separa un candidato de una excepción:
	un check que corre en 20 de 21 repositorios de la plantilla es lo que esa plantilla
	hace; uno que corre en 2 es de esos dos, y exigirlo a los 21 bloquearía 19.

	NUNCA UN CHECK QUE NO SE HAYA VISTO CORRER. Los nombres salen de `repo.check.context`
	—lo que GitHub reportó— y no de los workflows declarados: el nombre del workflow no es
	el que el ruleset exige, y el equivocado bloquea todos los merges. Si nada corrió, la
	lista sale vacía, y eso es una respuesta.
	"""
	_inherit = "repo.policy.template"

	# Debajo de esta cobertura, un check es una excepción de unos pocos repositorios y no
	# una convención de la plantilla. No es un umbral de calidad: es el punto donde
	# exigirlo a todos rompe a más de los que ordena.
	COBERTURA_DE_EXCEPCION = 50.0

	def candidatos_de_check(self):
		"""Qué checks se podrían exigir en esta plantilla, con sus números.

		Returns:
			dict: ``repositorios`` (cuántos gobierna), ``con_workflows`` (cuántos declaran
			CI en un archivo), ``con_checks`` (cuántos produjeron algún check de verdad),
			y ``candidatos``: por nombre, en cuántos corre, su cobertura y si es una
			excepción. La diferencia entre `con_workflows` y `con_checks` es la que
			explica una lista vacía sin que nadie tenga que adivinar.
		"""
		self.ensure_one()
		Repo = self.env["repo.repository"]
		repos = Repo.search([
			("classification", "=", self.classification_default),
			("archived", "=", False),
		]) if self.classification_default else Repo.browse()

		conteo = {}
		for repo in repos:
			for nombre in set(repo.check_context_ids.mapped("name")):
				conteo[nombre] = conteo.get(nombre, 0) + 1

		total = len(repos)
		candidatos = [
			{
				"nombre": nombre,
				"en_cuantos": cuantos,
				"de_cuantos": total,
				"cobertura": round(100.0 * cuantos / total, 1) if total else 0.0,
				"es_excepcion": (100.0 * cuantos / total) < self.COBERTURA_DE_EXCEPCION
				if total else True,
				"ya_exigido": nombre in self.required_check_ids.mapped("name"),
			}
			for nombre, cuantos in conteo.items()
		]
		candidatos.sort(key=lambda c: (-c["en_cuantos"], c["nombre"]))
		return {
			"repositorios": total,
			"con_workflows": len(repos.filtered("workflow_ids")),
			"con_checks": len(repos.filtered("check_context_ids")),
			"candidatos": candidatos,
		}
