# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Habilitar la escritura sobre una conexión. Con lo que hay que mirar, delante.

POR QUÉ UN ASISTENTE Y NO UN BOTÓN A SECAS. Un botón que habilita escritura sobre
producción y devuelve «listo» es un botón que se aprieta sin pensar. Lo que hace falta no
es una fricción cualquiera —una fricción arbitraria se aprende a saltear— sino que la
información que debería hacer dudar esté a la vista en el momento de decidir: **qué
repositorios abarca la instalación de la App de escritura, según GitHub**.

Ese alcance se PREGUNTA, no se supone. Es el límite duro, el que GitHub hace cumplir del
otro lado, y es lo único que acota el daño de un plan mal armado. Si la App está instalada
en «All repositories», esta pantalla lo va a mostrar y esa es justamente la información
que tiene que llegar antes y no después.

Y se pide escribir el nombre de la cuenta. No es teatro: es lo que separa «apreté el botón
que estaba iluminado» de «leí sobre qué cuenta estoy habilitando esto».
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RepoWriteEnableWizard(models.TransientModel):
	_name = "repo.write.enable.wizard"
	_description = "Habilitar la escritura sobre una conexión"

	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True, ondelete="cascade")
	owner_login = fields.Char(related="backend_id.owner_login", readonly=True)
	environment = fields.Selection(
		related="backend_id.environment", readonly=True)
	scope_text = fields.Text(
		string="Repositorios que la App de escritura puede tocar",
		compute="_compute_scope", readonly=True)
	scope_count = fields.Integer(string="Cuántos", compute="_compute_scope")
	scope_error = fields.Char(string="Error al consultar", compute="_compute_scope")
	confirmation = fields.Char(
		string="Escribí el nombre de la cuenta para confirmar",
		help="Tal cual figura arriba. Es lo que separa apretar un botón de tomar una "
			 "decisión.")

	@api.depends("backend_id")
	def _compute_scope(self):
		for asistente in self:
			asistente.scope_text = False
			asistente.scope_count = 0
			asistente.scope_error = False
			if not asistente.backend_id:
				continue
			try:
				alcance = asistente.backend_id._alcance_para_confirmar()
			except Exception as exc:  # noqa: BLE001 - se muestra, nunca se traga
				asistente.scope_error = str(exc)[:500]
				continue
			asistente.scope_count = len(alcance)
			asistente.scope_text = "\n".join(sorted(alcance)) or _(
				"La instalación no abarca ningún repositorio.")

	def action_confirm(self):
		self.ensure_one()
		if (self.confirmation or "").strip() != (self.owner_login or ""):
			raise UserError(_(
				"El nombre no coincide. Escribí «%s» exactamente como figura arriba."
			) % self.owner_login)
		if self.scope_error:
			raise UserError(_(
				"No se pudo averiguar qué repositorios abarca la instalación, así que no "
				"hay forma de saber sobre qué se estaría habilitando la escritura:\n\n%s"
			) % self.scope_error)
		alcance = set((self.scope_text or "").splitlines()) if self.scope_count else set()
		self.backend_id._habilitar_escritura(alcance=alcance)
		return {"type": "ir.actions.act_window_close"}
