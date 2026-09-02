# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Plan de escritura: nada se aplica sobre GitHub sin pasar por acá.

EL CONGELAMIENTO SE VERIFICA POR HUELLA DE CONTENIDO, NO POR ESTADO. Al aprobar se
calcula un hash de lo que el plan VA A EJECUTAR —operaciones, orden, destinos y
payloads— y se guarda junto a quién aprobó y cuándo. El apply recalcula la huella y
compara: si no coincide, no ejecuta, sin importar en qué estado figure el plan.

Por qué no alcanza con un flag ni con `write_date`:

  · un flag de "aprobado" lo apaga y lo prende cualquier método, y una operación
    agregada después de aprobar viajaría dentro de una aprobación que nunca la vio.
    Aprobar sería firmar un cheque en blanco.
  · `write_date` cambia por editar el nombre del plan o una nota, y no cambia si alguien
    modifica un payload por SQL. Mide actividad, no contenido.

La huella cubre exactamente lo que se ejecuta y nada más: renombrar el plan o escribirle
una nota NO la invalida, porque no cambia lo que va a pasar en GitHub. Cambiar un payload,
reordenar las operaciones, agregar una o borrarla, sí.

Y la huella viaja a la bitácora al ejecutar, así queda registrado exactamente qué se
aprobó y qué se aplicó, comparable después sin depender de que el plan siga existiendo.
"""
import hashlib
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Tipos de operación que un plan puede expresar. El ejecutor implementa de a uno; los que
# todavía no, fallan diciéndolo, en vez de pasar de largo en silencio.
#
# ANTES DE AGREGAR UN TIPO: leer la taxonomía en repo_write_apply.py — «dos clases de
# operación, y cuál lleva un paso más». Decide si el tipo nuevo necesita persistir la
# identidad que crea, y de eso depende que su rollback funcione cuando el apply se cae a
# mitad de camino.
OPERATION_KINDS = [
	("branch_protection_apply", "Aplicar protección de rama"),
	("branch_protection_remove", "Quitar protección de rama"),
	("ruleset_create", "Crear ruleset"),
	("ruleset_delete", "Borrar ruleset"),
	("collaborator_grant", "Dar permiso directo"),
	("collaborator_revoke", "Quitar permiso directo"),
	("team_repo_grant", "Dar permiso por team"),
	("team_repo_revoke", "Quitar permiso por team"),
	("team_member_remove", "Sacar a una persona de un team"),
	("team_member_add", "Poner a una persona en un team"),
]


class RepoWritePlan(models.Model):
	_name = "repo.write.plan"
	_description = "Plan de escritura sobre GitHub"
	_inherit = ["mail.thread"]
	_order = "id desc"

	name = fields.Char(string="Referencia", required=True, default="Plan de escritura")
	# Cosmético a propósito: no entra en la huella.
	note = fields.Text(string="Notas")

	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True, ondelete="cascade", index=True,
		help="Sobre qué conexión se ejecuta. Entra en la huella: mover un plan de "
			 "conexión cambia qué se toca y por eso invalida la aprobación.")

	state = fields.Selection(
		[("draft", "Borrador"), ("approved", "Aprobado"), ("applying", "Aplicando"),
		 ("applied", "Aplicado"), ("failed", "Fallido"), ("rolled_back", "Revertido")],
		string="Estado", default="draft", required=True, tracking=True, index=True,
		copy=False)

	operation_ids = fields.One2many(
		"repo.write.operation", "plan_id", string="Operaciones", copy=True)
	operation_count = fields.Integer(compute="_compute_operation_count")

	approved_by_id = fields.Many2one(
		"res.users", string="Aprobado por", readonly=True, copy=False,
		ondelete="set null", tracking=True)
	approved_at = fields.Datetime(string="Aprobado el", readonly=True, copy=False,
								  tracking=True)
	approval_fingerprint = fields.Char(
		string="Huella aprobada", readonly=True, copy=False,
		help="Hash del contenido ejecutable al momento de aprobar.")

	current_fingerprint = fields.Char(
		string="Huella actual", compute="_compute_current_fingerprint",
		help="Se recalcula siempre. Si difiere de la aprobada, el plan cambió.")
	is_frozen = fields.Boolean(
		string="Intacto desde la aprobación", compute="_compute_current_fingerprint")

	@api.depends("operation_ids")
	def _compute_operation_count(self):
		for plan in self:
			plan.operation_count = len(plan.operation_ids)

	# ------------------------------------------------------------------
	# Huella
	# ------------------------------------------------------------------

	@api.depends("backend_id", "operation_ids", "operation_ids.sequence",
				 "operation_ids.kind", "operation_ids.repository_id",
				 "operation_ids.target", "operation_ids.payload_json")
	def _compute_current_fingerprint(self):
		for plan in self:
			plan.current_fingerprint = plan._huella()
			plan.is_frozen = bool(
				plan.approval_fingerprint
				and plan.approval_fingerprint == plan.current_fingerprint)

	def _huella(self):
		"""Hash de lo que el plan VA A EJECUTAR. Nada cosmético entra acá.

		El payload se normaliza antes de hashear: se parsea y se vuelve a serializar con
		las claves ordenadas, para que reordenar un JSON equivalente no cuente como
		cambio y para que un cambio real no se esconda detrás de un reordenamiento.
		"""
		self.ensure_one()
		cuerpo = {
			"backend": self.backend_id.id,
			"operaciones": [
				{
					"sequence": op.sequence,
					"kind": op.kind,
					"repository": op.repository_id.full_name or op.repository_id.id,
					"target": op.target or "",
					"payload": _normalizar(op.payload_json),
				}
				for op in self.operation_ids.sorted(lambda o: (o.sequence, o.id))
			],
		}
		crudo = json.dumps(cuerpo, sort_keys=True, separators=(",", ":"), default=str)
		return hashlib.sha256(crudo.encode()).hexdigest()

	# ------------------------------------------------------------------
	# Ciclo
	# ------------------------------------------------------------------

	def action_approve(self):
		self.ensure_one()
		if self.state != "draft":
			raise UserError(_("Sólo se aprueba un plan en borrador."))
		if not self.operation_ids:
			raise UserError(_("Un plan sin operaciones no se aprueba."))
		if not self.env.user.has_group("primate_repo_manager.group_repo_lead"):
			raise UserError(_(
				"Aprobar un plan de escritura requiere el rol de líder técnico."))
		self.write({
			"state": "approved",
			"approved_by_id": self.env.user.id,
			"approved_at": fields.Datetime.now(),
			"approval_fingerprint": self._huella(),
		})
		self.message_post(body=_(
			"Plan aprobado. Huella: %s") % self.approval_fingerprint[:16])
		return True

	def action_back_to_draft(self):
		self.ensure_one()
		self._invalidar_aprobacion(_("Vuelto a borrador a mano."))
		return True

	def _invalidar_aprobacion(self, motivo):
		"""Devuelve el plan a borrador y borra la aprobación.

		Es la parte AMABLE del congelamiento: deja el plan en un estado coherente en vez
		de dejarlo diciendo "aprobado" cuando ya no lo está. La parte dura es la
		comparación de huella en `_verificar_congelado`, que no depende de que esto haya
		corrido.
		"""
		for plan in self:
			# UN PLAN YA APLICADO NO VUELVE A BORRADOR. El registro de qué se aprobó y se
			# ejecutó tiene que quedar en pie: degradarlo borraría la evidencia de la
			# aprobación bajo la cual se escribió en GitHub. Que su contenido después
			# cambie no lo devuelve a borrador — lo detecta la huella, y el rollback se
			# niega por eso.
			if plan.state not in ("draft", "approved"):
				continue
			if not plan.approval_fingerprint and plan.state == "draft":
				continue
			plan.write({
				"state": "draft",
				"approved_by_id": False,
				"approved_at": False,
				"approval_fingerprint": False,
			})
			plan.message_post(body=_("Aprobación invalidada: %s") % motivo)

	def _verificar_congelado(self, estados=("approved",)):
		"""LA guarda. La llaman el apply Y el rollback, antes de tocar nada.

		Compara huellas y no mira el estado para decidir: un plan que figure como
		aprobado pero cuya huella no coincida NO se ejecuta. Al revés también: sin
		aprobación previa no hay con qué comparar, y tampoco se ejecuta.

		`estados` es lo único que cambia entre una y otra. El apply corre sobre un plan
		`approved`. El rollback pasa `None`, que significa SIN REQUISITO DE ESTADO: su
		admisibilidad la justifica de otra forma —que existan operaciones cuyo objeto ya
		está en GitHub— porque una caída puede llevarse el campo de estado y dejar igual
		los objetos creados. La huella se exige en los dos casos: revertir es escribir, y
		no tiene por qué pedir menos.
		"""
		self.ensure_one()
		if not self.approval_fingerprint:
			raise UserError(_(
				"El plan «%s» no tiene aprobación registrada. No se ejecuta.") % self.name)
		actual = self._huella()
		if actual != self.approval_fingerprint:
			raise UserError(_(
				"El plan «%(nombre)s» cambió después de que lo aprobaran y no se va a "
				"ejecutar.\n\n"
				"Huella aprobada: %(vieja)s\n"
				"Huella actual:   %(nueva)s\n\n"
				"Aprobar un plan es aprobar operaciones concretas, no un lugar donde "
				"después se escriben otras. Revisá los cambios y volvé a aprobarlo."
			) % {"nombre": self.name, "vieja": self.approval_fingerprint[:16],
				 "nueva": actual[:16]})
		if estados is not None and self.state not in estados:
			raise UserError(_(
				"El plan «%(nombre)s» está en estado «%(estado)s» y esta acción sólo "
				"corre sobre: %(admitidos)s."
			) % {"nombre": self.name, "estado": self.state,
				 "admitidos": ", ".join(estados)})
		return True

	# ------------------------------------------------------------------
	# Invalidación automática
	# ------------------------------------------------------------------

	# Campos del encabezado que SÍ cambian lo que se ejecuta. `name` y `note` no están
	# acá a propósito: renombrar un plan no cambia lo que va a pasar en GitHub.
	CAMPOS_EJECUTABLES = ("backend_id",)

	def write(self, vals):
		if any(campo in vals for campo in self.CAMPOS_EJECUTABLES):
			aprobados = self.filtered(lambda p: p.approval_fingerprint)
			res = super().write(vals)
			aprobados._invalidar_aprobacion(_("cambió la conexión del plan"))
			return res
		return super().write(vals)


class RepoWriteOperation(models.Model):
	_name = "repo.write.operation"
	_description = "Operación de un plan de escritura"
	_order = "plan_id, sequence, id"

	plan_id = fields.Many2one(
		"repo.write.plan", string="Plan", required=True, ondelete="cascade", index=True)
	sequence = fields.Integer(string="Orden", default=10)
	kind = fields.Selection(OPERATION_KINDS, string="Operación", required=True)

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", ondelete="cascade", index=True)
	target = fields.Char(
		string="Destino",
		help="Rama, login o slug sobre el que opera, según el tipo.")
	payload_json = fields.Text(string="Payload (JSON)")

	state = fields.Selection(
		[("pending", "Pendiente"), ("applied", "Aplicada"), ("failed", "Fallida"),
		 ("rolled_back", "Revertida")],
		string="Estado", default="pending", required=True, copy=False)
	result_json = fields.Text(string="Resultado", readonly=True, copy=False)
	error = fields.Text(string="Error", readonly=True, copy=False)
	audit_log_id = fields.Many2one(
		"repo.audit.log", string="Entrada de bitácora", readonly=True, copy=False,
		ondelete="set null")

	# Campos que entran en la huella del plan.
	CAMPOS_EJECUTABLES = ("sequence", "kind", "repository_id", "target", "payload_json")

	@api.model_create_multi
	def create(self, vals_list):
		operaciones = super().create(vals_list)
		operaciones.plan_id._invalidar_aprobacion(_("se agregó una operación"))
		return operaciones

	def write(self, vals):
		res = super().write(vals)
		if any(campo in vals for campo in self.CAMPOS_EJECUTABLES):
			self.plan_id._invalidar_aprobacion(_("cambió una operación"))
		return res

	def unlink(self):
		planes = self.plan_id
		res = super().unlink()
		planes._invalidar_aprobacion(_("se borró una operación"))
		return res


def _normalizar(payload_json):
	"""JSON con claves ordenadas, o el texto crudo si no parsea.

	Devolver el crudo ante un JSON inválido es deliberado: así un payload roto igual
	entra en la huella y un cambio sobre él se detecta, en vez de colapsar todos los
	payloads inválidos en el mismo valor.
	"""
	if not payload_json:
		return None
	try:
		return json.loads(payload_json)
	except (TypeError, ValueError):
		return {"__crudo__": payload_json}
