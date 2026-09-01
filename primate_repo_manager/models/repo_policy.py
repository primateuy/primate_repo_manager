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
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .repo_collaborator import PERMISSIONS
from .repo_rules import BRANCH_ROLES, CLASSIFICATIONS

MERGE_STRATEGIES = [
	("squash", "Squash"),
	("merge_commit", "Merge commit"),
	("rebase", "Rebase"),
]


class RepoPolicyTemplate(models.Model):
	_name = "repo.policy.template"
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

	max_permission_default = fields.Selection(
		PERMISSIONS, string="Permiso máximo por defecto", default="push",
		help="El techo para cualquier persona que no tenga una excepción declarada. "
			 "Un permiso observado por encima de esto es un hallazgo.")

	_code_uniq = models.Constraint(
		"UNIQUE (code)", "Ya existe una plantilla con ese código.")

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


class RepoPolicyBranchRule(models.Model):
	_name = "repo.policy.branch.rule"
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
	_description = "Check de CI requerido por una plantilla"
	_order = "template_id, name"

	template_id = fields.Many2one(
		"repo.policy.template", string="Plantilla", required=True, ondelete="cascade")
	name = fields.Char(
		string="Nombre del check", required=True,
		help="Tiene que coincidir EXACTAMENTE con el nombre del job en GitHub.")


class RepoPolicyAccessRule(models.Model):
	_name = "repo.policy.access.rule"
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
