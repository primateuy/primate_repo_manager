# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Workflows de GitHub Actions que corren hoy en cada repo.

Existe para cerrar con datos el hueco de los checks requeridos: la spec los hace
obligatorios pero no nombra ninguno, y hay que saber qué corre de verdad antes de exigir
nada. Un check inexistente en un ruleset bloquea todos los merges del repo.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RepoWorkflow(models.Model):
	_name = "repo.workflow"
	_description = "Workflow de CI relevado en un repositorio"
	_order = "repository_id, name"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	name = fields.Char(string="Nombre", required=True)
	path = fields.Char(string="Archivo", required=True)
	state = fields.Char(string="Estado en GitHub")

	_workflow_uniq = models.Constraint(
		"UNIQUE (repository_id, path)",
		"Ese workflow ya está relevado en el repositorio.")

	@api.model
	def propose_required_checks(self, backend=None):
		"""OBSOLETA A PROPÓSITO. Proponía nombres que bloquean merges.

		Se escribió en F1 con lo único que había —los workflows declarados en un archivo
		yml— y la idea era cerrar el hueco de los checks con esos nombres. **Es
		incorrecta, y la corrección es de fondo**: un ruleset exige checks por el nombre
		del CHECK RUN, que no es el del workflow. Un workflow `CI` con dos jobs produce
		checks con el nombre de los jobs.

		Exigir el nombre equivocado no falla al aplicar: aplica bien, y después **ningún
		merge del repositorio vuelve a pasar**, porque GitHub espera para siempre un check
		que nadie va a reportar. Es la advertencia original por la que este hueco se dejó
		abierto en vez de llenarse con defaults razonables — y la propuesta de F1 la
		habría desoído.

		La buena es `repo.policy.template.candidatos_de_check()`, que sale de lo que
		GitHub reportó de verdad.
		"""
		raise UserError(_(
			"Esta propuesta salía de los workflows declarados, y un ruleset exige el "
			"nombre del check run, que no es el mismo. Exigir el equivocado bloquea "
			"todos los merges del repositorio.\n\n"
			"La propuesta buena está en la plantilla de política: sale de los checks que "
			"GitHub reportó de verdad."))
