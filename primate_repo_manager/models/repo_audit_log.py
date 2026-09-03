# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Bitácora inmutable de todo lo que el módulo hace sobre GitHub.

LA INMUTABILIDAD ES DEL MODELO, NO DE LOS PERMISOS. `write()` y `unlink()` levantan
excepción SIEMPRE, incluso con `sudo()`. Los ACL son la segunda capa, no la primera.

El motivo es simple: un ACL protege del usuario, no del código. Cualquier método del
módulo —o de otro addon— que haga `.sudo().write(...)` pasa por encima de los permisos
sin que nada se entere. Una bitácora que un `sudo()` puede reescribir no es una bitácora:
es una tabla de notas que además da una falsa sensación de rastro.

LAS ENTRADAS SOBREVIVEN AL BORRADO DE LO QUE DESCRIBEN. Los enlaces a repositorio, backend
y persona son `ondelete="set null"`, y el nombre de cada uno se guarda ADEMÁS como texto
al crear la entrada. Con `ondelete="cascade"` habría un camino silencioso de destrucción:
Postgres borra en cascada a nivel base de datos, sin pasar por `unlink()`, así que borrar
un repositorio se llevaría puesta su bitácora sin que la guarda de inmutabilidad llegara
a enterarse. Verificado con un test.
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EVENT_TYPES = [
	# Los de la spec §4.4.
	("apply_policy", "Aplicación de política"),
	("grant", "Alta de permiso"),
	("revoke", "Baja de permiso"),
	("promotion", "Promoción entre ramas"),
	("bypass_detected", "Bypass detectado"),
	("drift_detected", "Drift detectado"),
	("drift_resolved", "Drift resuelto"),
	("sync", "Sincronización"),
	("offboarding", "Offboarding"),
	("signing_change", "Cambio en la firma de commits"),
	# Los que agrega el ciclo plan -> aprobación -> apply de F2.
	("write_applied", "Escritura aplicada"),
	("write_failed", "Escritura fallida"),
	# Distinto de fallida a propósito: un techo de plan no es un error del sistema.
	("write_blocked", "Escritura bloqueada por el plan de GitHub"),
	# Paso 2b de las operaciones que crean identidad: el id que devolvió GitHub, guardado
	# antes de verificar nada. Ver la taxonomía en repo_write_apply.
	("write_identity", "Identidad creada, registrada antes de verificar"),
	("write_rolled_back", "Escritura revertida"),
	# Cambiar la política es la escritura más silenciosa de todas: no toca un solo
	# repositorio y sin embargo redefine qué cuenta como incumplimiento para todos los de
	# esa clasificación, en todas las auditorías que vengan. El chatter no alcanza —es
	# editable y se va con el registro—; el mismo argumento que hizo inmutable esta
	# bitácora para las escrituras a GitHub vale más acá, no menos.
	("policy_changed", "Cambio de política"),
]


class RepoAuditLog(models.Model):
	_name = "repo.audit.log"
	_description = "Bitácora inmutable de operaciones sobre GitHub"
	_order = "id desc"

	timestamp = fields.Datetime(
		string="Momento", required=True, default=fields.Datetime.now, index=True)
	event_type = fields.Selection(
		EVENT_TYPES, string="Evento", required=True, index=True)

	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", ondelete="set null", index=True)
	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", ondelete="set null", index=True)
	member_id = fields.Many2one(
		"repo.member", string="Persona", ondelete="set null", index=True)

	# Copias en texto: lo que hace que la entrada siga contando la historia aunque el
	# registro enlazado ya no exista.
	repository_name = fields.Char(string="Repositorio (texto)")
	member_login = fields.Char(string="Persona (texto)")

	user_id = fields.Many2one(
		"res.users", string="Ejecutado por", default=lambda s: s.env.user,
		ondelete="set null", index=True,
		help="Quién lo disparó desde Odoo. Distinto de la persona de GitHub afectada.")

	summary = fields.Char(string="Resumen", required=True)
	payload_json = fields.Text(string="Detalle (JSON)")
	# El estado ANTES de la escritura. Es lo que hace posible el rollback, y por eso vive
	# en la bitácora inmutable y no en el plan: si viviera en el plan, quien pueda editar
	# el plan podría reescribir el punto de retorno.
	previous_state_json = fields.Text(string="Estado previo (JSON)")

	# ------------------------------------------------------------------
	# Inmutabilidad
	# ------------------------------------------------------------------

	def write(self, vals):
		raise UserError(_(
			"La bitácora de auditoría no se modifica.\n\n"
			"Si el registro quedó mal, la corrección es una entrada NUEVA que lo explique, "
			"no la edición de la vieja: el valor de una bitácora es que lo escrito ahí no "
			"cambia después."))

	def unlink(self):
		raise UserError(_(
			"La bitácora de auditoría no se borra.\n\n"
			"Las entradas son el rastro de lo que el sistema hizo sobre GitHub, incluida "
			"la información de estado previo que permite revertir. Borrarlas dejaría "
			"operaciones aplicadas sin punto de retorno."))

	# ------------------------------------------------------------------
	# Alta
	# ------------------------------------------------------------------

	@api.model
	def registrar(self, event_type, summary, *, backend=None, repository=None,
				  member=None, payload=None, previous_state=None, extra=None):
		"""Única forma prevista de escribir en la bitácora.

		Rellena las copias en texto en el momento del alta, que es cuando los registros
		enlazados todavía existen.

		`extra` existe porque la entrada se escribe UNA VEZ y completa: como `write()`
		está prohibido, un campo que agregue otra capa —el enlace a la operación de
		escritura, por ejemplo— no se puede setear después. Se pasa acá o no se pasa.
		"""
		valores = {
			"event_type": event_type,
			"summary": summary[:255] if summary else "",
			"backend_id": backend.id if backend else False,
			"repository_id": repository.id if repository else False,
			"repository_name": repository.full_name if repository else False,
			"member_id": member.id if member else False,
			"member_login": member.github_login if member else False,
			"payload_json": json.dumps(payload, default=str) if payload else False,
			"previous_state_json": (
				json.dumps(previous_state, default=str) if previous_state else False),
		}
		valores.update(extra or {})
		return self.sudo().create(valores)

	def _compute_display_name(self):
		etiquetas = dict(EVENT_TYPES)
		for entrada in self:
			entrada.display_name = "[%s] %s" % (
				etiquetas.get(entrada.event_type, entrada.event_type), entrada.summary)
