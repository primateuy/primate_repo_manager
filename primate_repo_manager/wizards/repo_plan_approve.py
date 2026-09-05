# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Aprobar un plan, con cada operación destructiva confirmada por separado.

POR QUÉ UNA CONFIRMACIÓN POR OPERACIÓN Y NO UNA LISTA CON UN BOTÓN AL FINAL. «Nunca en
lote» de la spec de F2 se refiere a la DECISIÓN, no al armado: armar un plan con veinte
revocaciones está bien y es el flujo real; aprobarlas con un click no. Una lista que
enumera lo destructivo y termina en «Aprobar» es enumeración visual, y una enumeración
visual se saltea leyendo en diagonal — que es exactamente lo que uno hace cuando ya
decidió aprobar antes de abrir la pantalla.

Un tilde por operación, con su descripción delante, obliga a pasar por cada una. No
garantiza que se lea, nada garantiza eso; garantiza que no se pueda decir después que no
estaba a la vista.

LA GUARDA NO VIVE ACÁ. Vive en `repo.write.plan._aprobar`, porque un asistente es una
pantalla y una pantalla se saltea llamando al método. Esto arma la confirmación; el modelo
la exige.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RepoPlanApproveWizard(models.TransientModel):
	_name = "repo.plan.approve.wizard"
	_description = "Aprobar un plan de escritura"

	plan_id = fields.Many2one(
		"repo.write.plan", string="Plan", required=True, ondelete="cascade")
	line_ids = fields.One2many(
		"repo.plan.approve.line", "wizard_id", string="Operaciones")
	destructive_count = fields.Integer(
		string="Destructivas", compute="_compute_conteos")
	pending_count = fields.Integer(
		string="Sin confirmar", compute="_compute_conteos")

	@api.model
	def default_get(self, campos):
		valores = super().default_get(campos)
		plan = self.env["repo.write.plan"].browse(
			valores.get("plan_id") or self.env.context.get("default_plan_id"))
		if plan:
			valores["line_ids"] = [
				(0, 0, {"operation_id": op.id})
				for op in plan.operation_ids.sorted(lambda o: (o.sequence, o.id))
			]
		return valores

	@api.model_create_multi
	def create(self, vals_list):
		"""Las líneas se arman también cuando el plan llega por `vals` y no por contexto.

		`default_get` sólo ve los defaults del contexto, que es como lo llama la acción.
		Pero crear el asistente con `{"plan_id": X}` es igual de válido —lo hace otro
		addon, o un test— y ahí se quedaba sin líneas: una pantalla de aprobación vacía
		que aprueba todo sin mostrar nada. Es el peor resultado posible para esta
		pantalla, así que se cubre el caso en vez de confiar en cómo se la llama.
		"""
		asistentes = super().create(vals_list)
		for asistente in asistentes:
			if asistente.plan_id and not asistente.line_ids:
				asistente.line_ids = [
					(0, 0, {"operation_id": op.id})
					for op in asistente.plan_id.operation_ids.sorted(
						lambda o: (o.sequence, o.id))
				]
		return asistentes

	# DOS BARRAS SEPARADAS, como en el prototipo: las reversibles y las irreversibles no
	# se mezclan en un solo progreso. Mezclarlas diría «vas por el 80%» cuando lo que
	# falta es justamente lo único que no tiene vuelta atrás.
	reversible_count = fields.Integer(
		string="Reversibles", compute="_compute_conteos")
	reversible_done = fields.Integer(
		string="Reversibles aprobadas", compute="_compute_conteos")
	irreversible_count = fields.Integer(
		string="Irreversibles", compute="_compute_conteos")
	irreversible_done = fields.Integer(
		string="Irreversibles confirmadas", compute="_compute_conteos")

	@api.depends("line_ids.is_destructive", "line_ids.is_irreversible",
				 "line_ids.confirmed")
	def _compute_conteos(self):
		for asistente in self:
			destructivas = asistente.line_ids.filtered("is_destructive")
			asistente.destructive_count = len(destructivas)
			asistente.pending_count = len(destructivas.filtered(lambda l: not l.confirmed))
			irreversibles = asistente.line_ids.filtered("is_irreversible")
			reversibles = asistente.line_ids - irreversibles
			asistente.irreversible_count = len(irreversibles)
			asistente.irreversible_done = len(irreversibles.filtered("confirmed"))
			asistente.reversible_count = len(reversibles)
			asistente.reversible_done = len(reversibles.filtered("confirmed"))

	def action_approve_reversibles(self):
		"""Aprobar en bloque TODO lo que se puede revertir.

		Del triage de producto. No contradice el «nunca en lote»: eso es sobre lo que
		puede sacarle el acceso a alguien o borrar algo, y esas siguen una por una. Pedir
		veinte tildes para veinte protecciones de rama que se deshacen con un click no
		agrega criterio, agrega fatiga — y la fatiga es lo que hace que después se tilde
		sin leer también lo que sí importa.
		"""
		self.ensure_one()
		(self.line_ids - self.line_ids.filtered("is_irreversible")).confirmed = True
		return {
			"type": "ir.actions.act_window", "res_model": self._name,
			"res_id": self.id, "view_mode": "form", "target": "new",
		}

	def action_confirm(self):
		self.ensure_one()
		confirmadas = self.line_ids.filtered(
			lambda l: l.is_destructive and l.confirmed).mapped("operation_id")
		self.plan_id._aprobar(confirmadas=confirmadas)
		return {"type": "ir.actions.act_window_close"}


class RepoPlanApproveLine(models.TransientModel):
	_name = "repo.plan.approve.line"
	_description = "Operación a confirmar al aprobar un plan"
	_order = "sequence, id"

	wizard_id = fields.Many2one(
		"repo.plan.approve.wizard", required=True, ondelete="cascade")
	operation_id = fields.Many2one(
		"repo.write.operation", string="Operación", required=True, ondelete="cascade")
	sequence = fields.Integer(related="operation_id.sequence", store=True)
	description = fields.Char(related="operation_id.description", readonly=True)
	is_destructive = fields.Boolean(
		related="operation_id.is_destructive", readonly=True)
	is_irreversible = fields.Boolean(
		related="operation_id.is_irreversible", readonly=True)
	confirmed = fields.Boolean(
		string="Confirmo",
		help="Sólo hace falta en las destructivas, y hace falta en cada una.")

	# EL TIPEO DEL NOMBRE, exacto al prototipo. Para lo irreversible no alcanza un tilde:
	# hay que escribir el nombre del objeto que se va a tocar.
	#
	# La diferencia entre las dos fricciones no es de grado sino de naturaleza. Un tilde se
	# marca sin leer —la mano va antes que el ojo—; escribir «hotfix-viejo» obliga a mirar
	# QUÉ se está por perder, que es lo único que puede hacer que alguien se detenga.
	target_name = fields.Char(
		related="operation_id.target", string="Nombre del objeto", readonly=True)
	typed_name = fields.Char(
		string="Escribí el nombre para aprobar",
		help="Tal cual figura. Es lo que separa apretar un botón de tomar una decisión.")

	@api.onchange("typed_name")
	def _onchange_typed_name(self):
		"""El tilde se prende solo cuando el nombre coincide, y se apaga si deja de hacerlo."""
		for linea in self:
			if linea.is_irreversible:
				linea.confirmed = (
					(linea.typed_name or "").strip() == (linea.target_name or ""))
