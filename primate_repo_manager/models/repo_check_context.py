# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Los nombres de check que GitHub REPORTA de verdad — B2.

POR QUÉ NO ALCANZA CON LOS WORKFLOWS, QUE ES LO QUE F1 DEJÓ. Un ruleset exige checks por
el nombre del **check run**, y ése no es el nombre del workflow: un workflow llamado `CI`
con dos jobs produce checks llamados como los jobs. Proponer nombres de workflow sería
proponer strings que GitHub nunca reporta — y **un check requerido cuyo nombre no existe
bloquea TODOS los merges del repositorio, para siempre**. Es exactamente la advertencia
por la que este hueco se dejó abierto en vez de llenarse con defaults razonables.

Así que se guarda lo que GitHub reporta, **verbatim**. No se normaliza, no se recorta, no
se junta con el workflow del que salió: el string que se guarda es el string que se va a
exigir, byte por byte.

MEDIDO EL 7-SEP-2026 SOBRE LOS 113 REPOSITORIOS: 17 declaran workflows en un archivo yml
y **0 produjeron jamás un check run** en su rama por defecto. La lista de candidatos está
vacía, y está vacía por el motivo correcto — no porque no hayamos mirado.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class RepoCheckContext(models.Model):
	_name = "repo.check.context"
	_description = "Nombre de check que GitHub reportó en un repositorio"
	_order = "repository_id, name"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	name = fields.Char(
		string="Nombre del check", required=True, index=True,
		help="Tal cual lo reporta GitHub. Es el string que un ruleset tiene que exigir: "
			 "no se normaliza ni se edita, porque un nombre aproximado bloquea todos los "
			 "merges del repositorio.")
	last_conclusion = fields.Char(string="Último resultado")
	last_seen_at = fields.Datetime(string="Visto por última vez", readonly=True)
	origin = fields.Selection(
		[("sync", "Auditoría"), ("webhook", "Evento de GitHub")],
		string="Por dónde entró", default="sync", required=True)

	_context_uniq = models.Constraint(
		"UNIQUE (repository_id, name)",
		"Ese check ya está relevado en el repositorio.")

	@api.model
	def upsert(self, repo, nombre, conclusion=False, origin="sync"):
		"""La única forma de registrar un nombre de check observado."""
		if not nombre:
			return self.browse()
		fila = self.search([
			("repository_id", "=", repo.id), ("name", "=", nombre)], limit=1)
		valores = {
			"repository_id": repo.id, "name": nombre,
			"last_conclusion": conclusion or False,
			"last_seen_at": fields.Datetime.now(), "origin": origin,
		}
		if not fila:
			return self.create(valores)
		fila.write(valores if fila.last_conclusion != valores["last_conclusion"]
				   else {"last_seen_at": valores["last_seen_at"], "origin": origin})
		return fila
