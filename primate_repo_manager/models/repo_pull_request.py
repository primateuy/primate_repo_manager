# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""PRs abiertas. En F1 son espejo de lectura; la gestión desde Odoo es F4."""
from odoo import api, fields, models


class RepoPullRequest(models.Model):
	_name = "repo.pull.request"
	_description = "Pull request"
	_order = "created_at desc"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	number = fields.Integer(string="Número", required=True, index=True)
	title = fields.Char(string="Título")
	url = fields.Char(string="Link")
	author_member_id = fields.Many2one("repo.member", string="Autor", ondelete="set null")
	source_branch = fields.Char(string="Rama origen")
	target_branch = fields.Char(string="Rama destino")
	state = fields.Selection(
		[("open", "Abierta"), ("merged", "Mergeada"), ("closed", "Cerrada")],
		string="Estado", index=True)
	draft = fields.Boolean(string="Borrador")
	created_at = fields.Datetime(string="Creada")
	updated_at = fields.Datetime(string="Actualizada")
	age_days = fields.Integer(string="Antigüedad (días)", compute="_compute_age", store=True)
	reviewer_member_ids = fields.Many2many("repo.member", string="Revisores solicitados")
	review_count = fields.Integer(string="Revisiones")

	_pr_uniq = models.Constraint(
		"UNIQUE (repository_id, number)", "Esa PR ya está registrada.")

	@api.depends("created_at", "state")
	def _compute_age(self):
		ahora = fields.Datetime.now()
		for pr in self:
			# Sólo tiene sentido para las abiertas: la antigüedad de una PR cerrada no
			# es una alerta, es historia.
			if pr.created_at and pr.state == "open":
				pr.age_days = (ahora - pr.created_at).days
			else:
				pr.age_days = 0
