# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Armar una operación de plan sin escribir JSON, para lo que no nace de un hallazgo.

A4.1 cubre el camino corto: un hallazgo trae su remediación calculada y el botón la
convierte en operación. Esto es el otro camino — proteger una rama que ninguna auditoría
señaló todavía, sacarle acceso a alguien que se va, mover a una persona de team— donde no
hay hallazgo del que derivar nada y hasta hoy había que escribir el payload a mano.

QUÉ NO ESTÁ ACÁ, Y POR QUÉ. Los rulesets. Un ruleset se define por las reglas de una
plantilla de política, no por un formulario suelto: armarlo campo por campo acá sería
tener dos lugares donde se decide lo mismo, y el día que difieran nadie va a saber cuál
manda. «Aplicar la política de esta plantilla a este repositorio» es el ítem B1, y es de
donde tienen que salir. Mientras tanto, el tipo existe y se puede usar con payload a mano
desde el plan: lo que falta es la comodidad, no la capacidad.

MISMA DOCTRINA QUE A4.1: esto arma la operación y termina. No escribe en GitHub.
"""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.repo_write_plan import OPERATION_KINDS

# Los tipos que este asistente sabe armar, y qué campos necesita cada uno. La lista es
# explícita por la misma razón que la de A4.1: agregar un tipo de operación obliga a venir
# acá y decidir si tiene formulario, en vez de que aparezca a medias.
TIPOS_CON_FORMULARIO = (
	"branch_protection_apply", "branch_protection_remove",
	"collaborator_grant", "collaborator_revoke",
	"team_repo_grant", "team_repo_revoke",
	"team_member_add", "team_member_remove",
)


class RepoOperationBuilder(models.TransientModel):
	_name = "repo.operation.builder"
	_description = "Armar una operación de plan"

	plan_id = fields.Many2one(
		"repo.write.plan", string="Plan", required=True, ondelete="cascade")
	backend_id = fields.Many2one(
		related="plan_id.backend_id", readonly=True)
	kind = fields.Selection(
		[(k, e) for k, e in OPERATION_KINDS if k in TIPOS_CON_FORMULARIO],
		string="Qué hacer", required=True, default="branch_protection_apply")

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio",
		domain="[('backend_id', '=', backend_id)]")
	branch = fields.Char(string="Rama")
	member_id = fields.Many2one("repo.member", string="Persona")
	team_slug = fields.Char(string="Team (slug)")
	permission = fields.Selection(
		[("pull", "Lectura (pull)"), ("triage", "Triage"), ("push", "Escritura (push)"),
		 ("maintain", "Mantenimiento"), ("admin", "Administrador")],
		string="Permiso")

	# --- las reglas de protección, como casillas y no como JSON ---
	require_pr = fields.Boolean(string="Exigir pull request", default=True)
	required_approvals = fields.Integer(string="Aprobaciones requeridas", default=1)
	require_codeowner = fields.Boolean(string="Exigir revisión de owner")
	block_force_push = fields.Boolean(string="Bloquear force-push", default=True)
	block_deletion = fields.Boolean(string="Bloquear borrado de la rama", default=True)
	require_signed = fields.Boolean(string="Exigir commits firmados")

	preview = fields.Char(string="Va a decir", compute="_compute_preview")

	@api.depends("kind", "repository_id", "branch", "member_id", "team_slug",
				 "permission", "require_pr", "required_approvals", "require_codeowner",
				 "block_force_push", "block_deletion", "require_signed")
	def _compute_preview(self):
		"""La misma frase que va a mostrar el plan, antes de agregarla.

		Se arma con el MISMO método que usa la operación real —no con una copia— porque
		dos redacciones que se parecen son peores que una sola: la del asistente diría una
		cosa y la del plan otra, y la que se aprueba es la del plan.
		"""
		Operacion = self.env["repo.write.operation"]
		for asistente in self:
			try:
				valores = asistente._valores(validar=False)
			except UserError:
				asistente.preview = False
				continue
			borrador = Operacion.new({
				k: v for k, v in valores.items() if k != "plan_id"})
			asistente.preview = borrador.description

	def _valores(self, validar=True):
		"""Los campos de la operación, con el payload derivado de las casillas."""
		self.ensure_one()
		necesita_repo = self.kind not in ("team_member_add", "team_member_remove")
		if validar:
			if necesita_repo and not self.repository_id:
				raise UserError(_("Elegí el repositorio."))
			if self.kind.startswith("branch_protection") and not self.branch:
				raise UserError(_("Elegí la rama."))
			if self.kind.startswith("collaborator") and not self.member_id:
				raise UserError(_("Elegí la persona."))
			if self.kind.startswith("team_") and not self.team_slug:
				raise UserError(_("Escribí el slug del team."))
			if self.kind.endswith("_grant") and not self.permission:
				raise UserError(_("Elegí el permiso."))

		payload = {}
		destino = ""
		if self.kind == "branch_protection_apply":
			destino = self.branch or ""
			if self.require_pr:
				payload["required_pull_request_reviews"] = {
					"required_approving_review_count": self.required_approvals,
					"require_code_owner_reviews": self.require_codeowner,
				}
			payload["allow_force_pushes"] = not self.block_force_push
			payload["allow_deletions"] = not self.block_deletion
			payload["required_signatures"] = self.require_signed
		elif self.kind == "branch_protection_remove":
			destino = self.branch or ""
		elif self.kind.startswith("collaborator"):
			destino = self.member_id.github_login or ""
			if self.kind.endswith("_grant"):
				payload["permission"] = self.permission
		elif self.kind.startswith("team_repo"):
			destino = self.team_slug or ""
			if self.kind.endswith("_grant"):
				payload["permission"] = self.permission
		elif self.kind.startswith("team_member"):
			destino = self.team_slug or ""
			payload["username"] = self.member_id.github_login or ""

		siguiente = max(self.plan_id.operation_ids.mapped("sequence") or [0]) + 10
		return {
			"plan_id": self.plan_id.id,
			"kind": self.kind,
			"repository_id": self.repository_id.id if necesita_repo else False,
			"target": destino,
			"payload_json": json.dumps(payload) if payload else False,
			"sequence": siguiente,
		}

	def action_add(self):
		self.ensure_one()
		if self.plan_id.state != "draft":
			raise UserError(_(
				"«%s» no está en borrador. Agregarle operaciones le rompería la "
				"aprobación por la espalda.") % self.plan_id.display_name)
		self.env["repo.write.operation"].create(self._valores())
		return {"type": "ir.actions.act_window_close"}
