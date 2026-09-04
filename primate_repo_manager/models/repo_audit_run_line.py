# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Una fila por repositorio y por corrida. Existe para que nadie comparta un contador.

Ver el comentario de los contadores en `repo.audit.run`. En dos frases: los tres enteros
que cada job incrementaba eran una fila compartida, y como la transacción de un job dura
todo el recorrido del repositorio, los jobs se mataban entre sí y `queue_job` los
reintentaba — el resultado salía bien y se pagaba en recorrer cada repositorio dos o tres
veces.

Con una fila propia por job no hay nada que compartir. Y de yapa queda algo que antes no
existía: **qué le pasó a cada repositorio en cada corrida**, que es lo que permite que los
números de una auditoría vieja sigan siendo los suyos y no los del espejo de hoy.
"""
from odoo import fields, models


class RepoAuditRunLine(models.Model):
	_name = "repo.audit.run.line"
	_description = "Repositorio dentro de una corrida de auditoría"
	_order = "run_id, id"

	run_id = fields.Many2one(
		"repo.audit.run", string="Corrida", required=True, ondelete="cascade", index=True)
	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True, ondelete="cascade",
		index=True)
	state = fields.Selection(
		[("pending", "Pendiente"), ("running", "En curso"),
		 ("done", "Recorrido"), ("error", "Con error")],
		string="Estado", default="pending", required=True, index=True)
	error = fields.Text(string="Error")
	started_at = fields.Datetime(string="Inicio")
	finished_at = fields.Datetime(string="Fin")

	_run_repo_uniq = models.Constraint(
		"UNIQUE (run_id, repository_id)",
		"Ese repositorio ya está en esta corrida.")
