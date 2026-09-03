# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Personas con cuenta de GitHub. En F1 sólo se releva; los grants vienen en F2."""
import re

from odoo import _, api, fields, models


class RepoMember(models.Model):
	_name = "repo.member"
	_description = "Persona con cuenta de GitHub"
	_inherit = ["mail.thread"]
	_order = "github_login"

	github_login = fields.Char(string="Usuario de GitHub", required=True, index=True)
	github_id = fields.Char(string="ID en GitHub", index=True)
	name = fields.Char(string="Nombre")
	avatar_url = fields.Char(string="Avatar")

	user_id = fields.Many2one("res.users", string="Usuario de Odoo", ondelete="set null")
	employee_id = fields.Many2one("hr.employee", string="Empleado", ondelete="set null")

	signing_configured = fields.Boolean(
		string="Firma SSH configurada",
		help="Verificado contra las signing keys registradas en GitHub.")
	signing_checked_at = fields.Datetime(string="Firma verificada el")

	state = fields.Selection(
		[("active", "Activo"), ("offboarded", "Dado de baja")],
		string="Estado", default="active", required=True, tracking=True)

	collaborator_ids = fields.One2many("repo.collaborator", "member_id", string="Accesos")

	# --- la propuesta de vínculo con un empleado -------------------------
	# Se PROPONE y una persona confirma. Nunca se vincula solo: un vínculo equivocado
	# pone los permisos de alguien a nombre de otro, y eso no se nota hasta que alguien
	# audita accesos y saca la conclusión contraria a la verdadera.
	employee_suggestion_ids = fields.Many2many(
		"hr.employee", string="Empleados que podrían ser",
		compute="_compute_employee_suggestions")
	suggestion_count = fields.Integer(
		string="Candidatos", compute="_compute_employee_suggestions")

	_login_uniq = models.Constraint(
		"UNIQUE (github_login)", "Ese usuario de GitHub ya está registrado.")

	@api.depends("github_login", "name", "employee_id")
	def _compute_employee_suggestions(self):
		"""Busca empleados que PODRÍAN ser esta cuenta. No decide: ofrece.

		Tres señales, de la más confiable a la menos: el mail de trabajo que empieza con el
		login de GitHub, el nombre igual, y el apellido en común. Ninguna alcanza sola para
		afirmar nada —hay homónimos, y un login puede no tener nada que ver con el nombre—
		y por eso el resultado es una lista para elegir y no un campo ya completado.
		"""
		Empleado = self.env["hr.employee"]
		for persona in self:
			if persona.employee_id:
				persona.employee_suggestion_ids = Empleado
				persona.suggestion_count = 0
				continue
			dominio = []
			login = (persona.github_login or "").strip()
			if login:
				dominio.append(("work_email", "=ilike", "%s@%%" % login))
			nombre = (persona.name or "").strip()
			if nombre:
				dominio.append(("name", "=ilike", nombre))
				partes = [p for p in re.split(r"\s+", nombre) if len(p) > 3]
				if partes:
					dominio.append(("name", "ilike", partes[-1]))
			if not dominio:
				persona.employee_suggestion_ids = Empleado
				persona.suggestion_count = 0
				continue
			candidatos = Empleado.search(
				["|"] * (len(dominio) - 1) + dominio, limit=5)
			persona.employee_suggestion_ids = candidatos
			persona.suggestion_count = len(candidatos)

	def action_link_employee(self):
		"""Abre la elección del empleado. La confirmación es de una persona, siempre."""
		self.ensure_one()
		return {
			"type": "ir.actions.act_window",
			"name": _("¿Quién es %s?") % self.github_login,
			"res_model": "repo.member.link.wizard",
			"view_mode": "form",
			"target": "new",
			"context": {"default_member_id": self.id},
		}
