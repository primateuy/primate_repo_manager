# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Personas con cuenta de GitHub. En F1 sólo se releva; los grants vienen en F2."""
from odoo import fields, models


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

	_login_uniq = models.Constraint(
		"UNIQUE (github_login)", "Ese usuario de GitHub ya está registrado.")
