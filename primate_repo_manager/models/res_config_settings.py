# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Los umbrales de los moduladores de severidad, y de dónde salen sus valores.

La LÓGICA de qué sube y qué baja vive en el código y está testeada; los NÚMEROS son
configuración, porque son criterio y el criterio cambia sin que cambie la regla.

La PANTALLA para tocarlos NO está acá: está en `repo.settings`. Ver el docstring de ese
modelo — resumido, `res.config.settings` exige ser administrador de Odoo entero, y quien
administra Repo Manager no tiene por qué serlo.
"""
from odoo import models

# Defaults propuestos y aprobados el 1-sep-2026.
DEFAULTS = {
	"repo_manager.commit_violation_ratio": "50",
	"repo_manager.fork_behind_threshold": "100",
	"repo_manager.pr_stale_days": "7",
	# A partir de cuántos repositorios la auditoría deja de correr en el momento y pasa a
	# encolarse. Ver el docstring de `action_start`.
	"repo_manager.sync_threshold": "25",
}


class ResConfigSettings(models.TransientModel):
	_inherit = "res.config.settings"

	@classmethod
	def _repo_param(cls, env, clave, default):
		"""Lee un umbral. Ante un valor basura usa el default en vez de reventar el informe."""
		crudo = env["ir.config_parameter"].sudo().get_param(clave, default)
		try:
			return int(crudo)
		except (TypeError, ValueError):
			return int(default)
