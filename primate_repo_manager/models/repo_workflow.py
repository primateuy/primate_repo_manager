# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Workflows de GitHub Actions que corren hoy en cada repo.

Existe para cerrar con datos el hueco de los checks requeridos: la spec los hace
obligatorios pero no nombra ninguno, y hay que saber qué corre de verdad antes de exigir
nada. Un check inexistente en un ruleset bloquea todos los merges del repo.
"""
from collections import defaultdict

from odoo import api, fields, models


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
		"""Propuesta de checks requeridos por plantilla, a partir de lo que corre hoy.

		Devuelve, por clasificación, los workflows ordenados por cuántos repos los usan.
		Es el insumo para cerrar el hueco en UNA decisión: "estos N workflows corren en X
		repos de clasificación Y, candidatos a check requerido".

		No decide nada por su cuenta: propone con números y el humano elige.
		"""
		dominio = [("repository_id.archived", "=", False)]
		if backend:
			dominio.append(("repository_id.backend_id", "=", backend.id))

		por_clasificacion = defaultdict(lambda: defaultdict(set))
		repos_por_clasificacion = defaultdict(set)
		for workflow in self.search(dominio):
			repo = workflow.repository_id
			clasificacion = repo.classification or "sin_clasificar"
			repos_por_clasificacion[clasificacion].add(repo.id)
			por_clasificacion[clasificacion][workflow.name].add(repo.id)

		propuesta = {}
		for clasificacion, workflows in por_clasificacion.items():
			total = len(repos_por_clasificacion[clasificacion])
			filas = [
				{
					"workflow": nombre,
					"repos": len(repo_ids),
					"cobertura": round(len(repo_ids) / total * 100, 1) if total else 0.0,
				}
				for nombre, repo_ids in workflows.items()
			]
			filas.sort(key=lambda f: (-f["repos"], f["workflow"]))
			propuesta[clasificacion] = {
				"repos_en_la_clasificacion": total,
				"candidatos": filas,
			}
		return propuesta
