# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Umbrales de los moduladores de severidad.

La LÓGICA de qué sube y qué baja vive en el código y está testeada; los NÚMEROS son
configuración, porque son criterio y el criterio cambia sin que cambie la regla.
"""
from odoo import fields, models

# Defaults propuestos y aprobados el 1-sep-2026.
DEFAULTS = {
	"repo_manager.commit_violation_ratio": "50",
	"repo_manager.fork_behind_threshold": "100",
	"repo_manager.pr_stale_days": "7",
}


class ResConfigSettings(models.TransientModel):
	_inherit = "res.config.settings"

	repo_commit_violation_ratio = fields.Integer(
		string="% de commits fuera de convención que eleva la severidad",
		config_parameter="repo_manager.commit_violation_ratio", default=50,
		help="Por encima de este porcentaje, el hallazgo de formato de commits sube de "
			 "medio a alto: veinte commits mal no es lo mismo que uno.")
	repo_fork_behind_threshold = fields.Integer(
		string="Commits de atraso que elevan la severidad de un fork",
		config_parameter="repo_manager.fork_behind_threshold", default=100,
		help="A esa distancia el merge de parches ya es un problema y no un pendiente.")
	repo_pr_stale_days = fields.Integer(
		string="Días para considerar estancada una PR",
		config_parameter="repo_manager.pr_stale_days", default=7,
		help="Regla de vida de rama de los lineamientos.")

	@classmethod
	def _repo_param(cls, env, clave, default):
		"""Lee un umbral. Ante un valor basura usa el default en vez de reventar el informe."""
		crudo = env["ir.config_parameter"].sudo().get_param(clave, default)
		try:
			return int(crudo)
		except (TypeError, ValueError):
			return int(default)
