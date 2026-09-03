# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Vincular una cuenta de GitHub con un empleado. Lo confirma una persona, siempre.

POR QUÉ UN ASISTENTE Y NO UN CAMPO EDITABLE A SECAS. El campo `employee_id` se puede
editar en el formulario y así queda: quien sabe quién es quién, lo pone y listo. Este
asistente existe para el otro caso, el que produce el hallazgo «cuenta sin persona
asociada»: alguien que no conoce a toda la empresa tiene que decidir, y necesita ver los
candidatos con lo que los hace candidatos —el mail, el puesto— antes de elegir.

LO QUE NO HACE, Y ES EL PUNTO: no vincula solo. Las coincidencias son pistas, no pruebas
—hay homónimos, y un login de GitHub puede no tener nada que ver con el nombre de nadie—.
Un vínculo equivocado pone los permisos de una persona a nombre de otra, y eso no se nota
hasta que alguien audita accesos y saca justo la conclusión contraria a la verdadera.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RepoMemberLinkWizard(models.TransientModel):
	_name = "repo.member.link.wizard"
	_description = "Vincular una cuenta de GitHub con un empleado"

	member_id = fields.Many2one(
		"repo.member", string="Cuenta de GitHub", required=True, ondelete="cascade")
	github_login = fields.Char(related="member_id.github_login", readonly=True)
	github_name = fields.Char(related="member_id.name", readonly=True)
	suggestion_ids = fields.Many2many(
		"hr.employee", string="Candidatos", related="member_id.employee_suggestion_ids",
		readonly=True)
	employee_id = fields.Many2one(
		"hr.employee", string="Es esta persona",
		help="Elegir de los candidatos, o buscar cualquier otro empleado.")

	@api.onchange("member_id")
	def _onchange_member(self):
		"""Si hay UN solo candidato se propone, pero se propone: queda a la vista y se
		puede cambiar antes de confirmar. Con varios no se elige ninguno, porque elegir el
		primero de una lista de iguales es adivinar con cara de saber."""
		for asistente in self:
			candidatos = asistente.member_id.employee_suggestion_ids
			asistente.employee_id = candidatos if len(candidatos) == 1 else False

	def action_confirm(self):
		self.ensure_one()
		if not self.employee_id:
			raise UserError(_(
				"Elegí un empleado. Si ninguno es, cerrá el asistente: dejar la cuenta sin "
				"vincular es una respuesta válida y el hallazgo va a seguir avisando."))
		self.member_id.employee_id = self.employee_id
		self.member_id.message_post(body=_(
			"Cuenta de GitHub «%(login)s» vinculada a %(empleado)s."
		) % {"login": self.member_id.github_login,
			 "empleado": self.employee_id.display_name})
		return {"type": "ir.actions.act_window_close"}
