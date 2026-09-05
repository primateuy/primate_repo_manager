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
	# D2 · promoción de módulos. `module_copy` escribe CONTENIDO, que es lo que ninguna
	# operación hacía hasta ahora.
	("module_copy", "Copiar un módulo a otro repositorio"),
	# Y ésta BORRA contenido. Es la única del catálogo que saca código de un repositorio
	# de cliente, y por eso nunca corre sola: depende de que su copia haya quedado
	# verificada (D2.0). El peor caso permitido es duplicación benigna, jamás borrado sin
	# copia.
	("module_delete", "Retirar un módulo de un repositorio"),
]


class RepoWritePlan(models.Model):
	_name = "repo.write.plan"
	_description = "Plan de escritura sobre GitHub"
	_inherit = ["mail.thread", "bus.listener.mixin"]
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
	# --- A4.5: el plan aplicándose se mira, no se refresca ----------------
	applied_count = fields.Integer(
		string="Aplicadas", compute="_compute_avance")
	failed_count = fields.Integer(string="Con problema", compute="_compute_avance")
	progress = fields.Float(string="Avance", compute="_compute_avance")
	started_at = fields.Datetime(string="Aplicación iniciada", readonly=True, copy=False)
	finished_at = fields.Datetime(string="Aplicación terminada", readonly=True, copy=False)

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

	@api.depends("operation_ids.state")
	def _compute_avance(self):
		"""Se DERIVA de las operaciones, no se lleva en contadores propios.

		Es el patrón que quedó de A9 y de A10: un contador que alguien incrementa es una
		fila compartida que dos procesos pueden pisarse, y además puede quedar mintiendo
		si algo se cae en el medio. Contar las operaciones no puede desfasarse de la
		realidad, porque ES la realidad.
		"""
		for plan in self:
			estados = plan.operation_ids.mapped("state")
			plan.applied_count = estados.count("applied") + estados.count("blocked")
			plan.failed_count = estados.count("failed")
			total = len(estados)
			hechas = plan.applied_count + plan.failed_count
			plan.progress = (hechas / total * 100) if total else 0.0

	# ------------------------------------------------------------------
	# Avance en vivo del apply
	# ------------------------------------------------------------------

	AVISO = "repo_manager.audit_progress"

	def _emitir_avance(self, actual=None, inmediato=False):
		"""Mismo mensaje que la corrida de auditoría: el componente es el mismo.

		Los nombres de las claves son los del componente y no los del modelo —`done`,
		`error`, `total`— justamente para que la pieza de pantalla no tenga que saber si
		la está alimentando una auditoría o un plan.
		"""
		self.ensure_one()
		aviso = {
			"id": self.id,
			"state": self.state,
			"total": self.operation_count,
			"done": self.applied_count,
			"error": self.failed_count,
			"actual": actual,
			"findings": 0, "criticos": 0, "altos": 0,
		}
		if not inmediato:
			self._bus_send(self.AVISO, aviso)
			return
		with self.pool.cursor() as cr:
			self.env(cr=cr)["repo.write.plan"].browse(self.id)._bus_send(
				self.AVISO, aviso)

	def action_refresh_progress(self):
		"""Reemite el estado. Lo usa el «Volver a preguntar» del componente."""
		self.ensure_one()
		en_curso = self.operation_ids.filtered(lambda o: o.state == "pending")[:1]
		self._emitir_avance(actual=en_curso.description or None)
		return True

	# ------------------------------------------------------------------
	# Huella
	# ------------------------------------------------------------------

	@api.depends("backend_id", "operation_ids", "operation_ids.sequence",
				 "operation_ids.kind", "operation_ids.repository_id",
				 "operation_ids.target", "operation_ids.payload_json",
				 "operation_ids.description", "operation_ids.is_destructive",
				 "operation_ids.depends_on_ids")
	def _compute_current_fingerprint(self):
		for plan in self:
			plan.current_fingerprint = plan._huella()
			plan.is_frozen = bool(
				plan.approval_fingerprint
				and plan.approval_fingerprint == plan.current_fingerprint)

	def _huella(self):
		"""Hash de lo que el plan va a ejecutar Y DE CÓMO SE LO CONTÓ AL APROBARLO.

		El payload se normaliza antes de hashear: se parsea y se vuelve a serializar con
		las claves ordenadas, para que reordenar un JSON equivalente no cuente como
		cambio y para que un cambio real no se esconda detrás de un reordenamiento.

		POR QUÉ LA DESCRIPCIÓN ENTRA EN LA HUELLA, SIENDO QUE SE DERIVA DEL PAYLOAD.
		Parece redundante y no lo es. Hashear un valor derivado no detecta cambios en el
		origen —para eso ya está el payload— sino cambios **en quien lo deriva**. Si
		mañana alguien mejora la redacción de una descripción, o corrige un error en cómo
		se traduce una regla de protección, los planes aprobados y todavía sin aplicar
		pasarían a mostrar una frase distinta de la que se aprobó, y nada avisaría.

		Con la descripción adentro, ese caso deja el plan fuera de la huella y lo devuelve
		a borrador: hay que volver a leerlo y volver a aprobarlo. Es más molesto y es lo
		correcto — lo que se aprobó fue la frase, no el JSON.

		La consecuencia hay que aceptarla de frente: **actualizar el módulo puede invalidar
		aprobaciones pendientes.** Es el precio de que la aprobación signifique algo.
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
					"descripcion": op.description or "",
					"destructiva": op.is_destructive,
					"depende_de": sorted(op.depends_on_ids.mapped("sequence")),
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
		"""Abre la aprobación. Si hay destructivas, cada una pide su tilde.

		«Nunca en lote» de la spec de F2 se refiere a la DECISIÓN, no al armado: armar un
		plan con veinte revocaciones está bien; aprobarlas con un solo click no. Una lista
		que enumera las destructivas y un botón «Aprobar» al final es enumeración visual,
		y una enumeración visual se saltea leyendo en diagonal.
		"""
		self.ensure_one()
		self._verificar_aprobable()
		return {
			"type": "ir.actions.act_window",
			"name": _("Aprobar «%s»") % self.name,
			"res_model": "repo.plan.approve.wizard",
			"view_mode": "form",
			"target": "new",
			"context": {"default_plan_id": self.id},
		}

	def _verificar_destino_escribible(self):
		"""Si la rama de destino exige PR, el plan NO se arma. Nunca falla a mitad del apply.

		POR QUÉ ACÁ Y NO AL APLICAR. Una rama protegida que exige pull request rechaza el
		push, y descubrirlo en el apply significa haber subido los blobs, creado el árbol y
		el commit, y recién ahí chocar contra la referencia. No es un desastre —el commit
		queda huérfano y GitHub lo recoge solo— pero es un fallo evitable, y el embudo
		existe para que las cosas se sepan ANTES.

		LA SALIDA DURABLE ES OTRA, y va en B1: los rulesets que el propio módulo aplique
		tienen que incluir a `prm-writer` como bypass actor. El embudo
		plan → aprobación individual → bitácora → reversión es una revisión MÁS estricta
		que una pull request, no menos; sin esa exención, la gobernanza que B viene a
		instalar estrangularía a D2 — el módulo se prohibiría a sí mismo hacer lo que el
		mismo módulo aprobó.
		"""
		self.ensure_one()
		copias = self.operation_ids.filtered(lambda o: o.kind == "module_copy")
		if not copias:
			return True
		cliente = self.backend_id.client()
		for op in copias:
			datos = op._datos_modulo()
			rama = op.repository_id.branch_ids.filtered(
				lambda b, r=datos["destino_rama"]: b.name == r)[:1]
			if not rama:
				continue
			if not rama.protected:
				continue
			# LA CLAVE PRESENTE YA SIGNIFICA «EXIGE PR», aunque venga vacía. En la API de
			# GitHub, `required_pull_request_reviews: {}` es una rama que pide pull
			# request con cero aprobaciones obligatorias — sigue rechazando el push
			# directo. Preguntar por el valor con `bool()` dejaba pasar ese caso, y el
			# plan habría fallado recién al aplicar. Lo encontró un test.
			exige_pr = False
			try:
				proteccion = json.loads(rama.protection_json or "{}")
				exige_pr = "required_pull_request_reviews" in proteccion
			except (TypeError, ValueError):
				# Una protección que no se puede leer NO se interpreta como «no exige
				# nada»: se avisa y se deja pasar, porque negarse sobre un dato ilegible
				# bloquearía el trabajo por una sospecha. El apply, si falla, lo va a decir.
				_logger.warning(
					"Repo Manager: la protección de %s@%s no se pudo leer al armar el "
					"plan", op.repository_id.full_name, datos["destino_rama"])
			if exige_pr:
				raise UserError(_(
					"La rama «%(rama)s» de %(repo)s exige pull request, así que un commit "
					"directo va a ser rechazado por GitHub.\n\n"
					"El plan no se arma para no fallar a mitad de camino. La salida "
					"definitiva es que los rulesets que aplique este módulo incluyan a la "
					"App de escritura como excepción — el embudo de aprobación es una "
					"revisión más estricta que una PR—, y eso llega con la aplicación de "
					"política por plantilla."
				) % {"rama": datos["destino_rama"],
					 "repo": op.repository_id.full_name})
		return True

	def _verificar_aprobable(self):
		"""Las condiciones de siempre, sin las cuales ni se abre la aprobación."""
		self.ensure_one()
		if self.state != "draft":
			raise UserError(_("Sólo se aprueba un plan en borrador."))
		if not self.operation_ids:
			raise UserError(_("Un plan sin operaciones no se aprueba."))
		if not self.env.user.has_group("primate_repo_manager.group_repo_lead"):
			raise UserError(_(
				"Aprobar un plan de escritura requiere el rol de líder técnico."))
		return True

	def _aprobar(self, confirmadas=None):
		"""Aprueba de verdad. Lo llama el asistente, después de las confirmaciones.

		LA GUARDA VIVE ACÁ Y NO EN EL ASISTENTE, a propósito: un asistente es una pantalla
		y una pantalla se puede saltear llamando al método. Si las destructivas del plan no
		están todas confirmadas, esto se niega venga de donde venga.
		"""
		self.ensure_one()
		self._verificar_aprobable()
		self._verificar_destino_escribible()
		sin_soporte = self.operation_ids.filtered(lambda o: not o.is_supported)
		if sin_soporte:
			# Se corta ACÁ y no al aplicar. Fallar a mitad del apply dejaría parte del plan
			# escrito en GitHub y parte no, que es el estado que todo este embudo existe
			# para evitar.
			raise UserError(_(
				"Este plan tiene %(n)s operación(es) de un tipo que todavía no está "
				"implementado:\n\n%(lista)s\n\n"
				"Aplicarlo fallaría a mitad de camino, con parte de las operaciones ya "
				"escritas en GitHub. Sacalas del plan."
			) % {"n": len(sin_soporte),
				 "lista": "\n".join("• %s" % o.description for o in sin_soporte)})
		destructivas = self.operation_ids.filtered("is_destructive")
		faltan = destructivas - (confirmadas or self.env["repo.write.operation"])
		if faltan:
			raise UserError(_(
				"Quedan %(cuantas)s operación(es) destructiva(s) sin confirmar:\n\n%(lista)s"
				"\n\nCada una se confirma por separado. Aprobar en lote lo que puede "
				"sacarle el acceso a alguien es exactamente lo que esta pantalla evita."
			) % {
				"cuantas": len(faltan),
				"lista": "\n".join("• %s" % op.description for op in faltan),
			})
		self.write({
			"state": "approved",
			"approved_by_id": self.env.user.id,
			"approved_at": fields.Datetime.now(),
			"approval_fingerprint": self._huella(),
		})
		destructivas = self.operation_ids.filtered("is_destructive")
		self.message_post(body=_(
			"Plan aprobado. Huella: %(huella)s. Operaciones: %(total)s, de las cuales "
			"%(malas)s destructivas confirmadas una por una."
		) % {"huella": self.approval_fingerprint[:16],
			 "total": len(self.operation_ids), "malas": len(destructivas)})
		return True

	def action_add_operation(self):
		"""Abre el asistente que arma una operación sin escribir JSON."""
		self.ensure_one()
		if self.state != "draft":
			raise UserError(_(
				"«%s» no está en borrador: agregarle operaciones le rompería la "
				"aprobación.") % self.display_name)
		return {
			"type": "ir.actions.act_window",
			"name": _("Agregar una operación a «%s»") % self.name,
			"res_model": "repo.operation.builder",
			"view_mode": "form",
			"target": "new",
			"context": {"default_plan_id": self.id},
		}

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

	# De dónde salió esta operación. Es PROCEDENCIA, no contenido ejecutable, así que NO
	# entra en la huella: cambiar de qué hallazgo vino no cambia lo que se va a ejecutar.
	# Sirve para dos cosas: que el hallazgo sepa que ya está planificado, y que la
	# bitácora pueda decir por qué se hizo cada cosa.
	finding_id = fields.Many2one(
		"repo.audit.finding", string="Hallazgo de origen", ondelete="set null",
		index=True, copy=False)

	# --- A4.4: qué va a pasar, en castellano -----------------------------
	description = fields.Char(
		string="Qué va a pasar", compute="_compute_description", store=True,
		help="La operación dicha en palabras. Es lo que una persona lee y aprueba, y por "
			 "eso entra en la huella del plan.")
	is_destructive = fields.Boolean(
		string="Destructiva", compute="_compute_description", store=True,
		help="Quita acceso o borra algo que otro puede estar usando. Cada una exige su "
			 "confirmación propia al aprobar el plan.")
	is_irreversible = fields.Boolean(
		string="Irreversible", compute="_compute_description", store=True,
		help="No tiene vuelta atrás por el mismo camino: NO entra en el rollback. Exige "
			 "escribir el nombre del objeto para aprobarla.")
	is_supported = fields.Boolean(
		string="Se puede aplicar", compute="_compute_description", store=True,
		help="Falso cuando el tipo existe en el selector pero todavía no tiene "
			 "implementación. Un plan con una de éstas no se puede aprobar.")

	# Las que sacan algo que ya está funcionando. Quitar una protección no borra código,
	# pero deja pasar lo que antes se frenaba: es destructiva en el sentido que importa,
	# que es «alguien puede perder algo con esto».
	KINDS_DESTRUCTIVOS = (
		"branch_protection_remove", "ruleset_delete", "collaborator_revoke",
		"team_repo_revoke", "team_member_remove",
		# La más destructiva de todas: saca código de un repositorio ajeno.
		"module_delete",
	)

	state = fields.Selection(
		[("pending", "Pendiente"), ("applied", "Aplicada"), ("failed", "Fallida"),
		 ("rolled_back", "Revertida"),
		 # NO es «fallida», y la diferencia importa: esta operación nunca se intentó.
		 # Marcarla como fallida diría que se probó y salió mal, y mandaría a alguien a
		 # buscar un error de GitHub que no existe. Lo que pasó es que la que la habilitaba
		 # no llegó a buen puerto, así que ésta ni se tocó — que es exactamente lo que se
		 # quería.
		 ("blocked_by_dependency", "No ejecutada por dependencia")],
		string="Estado", default="pending", required=True, copy=False)

	# --- D2.0 · LA BARRERA -------------------------------------------------
	#
	# POR QUÉ NO EXISTÍA ANTES, Y POR QUÉ AHORA SÍ. En F2 las operaciones de un plan son
	# INDEPENDIENTES: proteger una rama y bajarle el permiso a alguien no tienen nada que
	# ver entre sí, así que si una falla lo correcto es que las demás sigan. El bucle del
	# apply está escrito así a propósito y estaba bien.
	#
	# La promoción de módulos rompe ese supuesto. «Copiar al destino» y «borrar del origen»
	# son la misma operación partida en dos, y ejecutar la segunda cuando la primera falló
	# es el peor resultado posible: contenido borrado que no está en ninguna otra parte.
	# El peor caso PERMITIDO es duplicación benigna; borrado sin copia no es un caso, es un
	# desastre.
	depends_on_ids = fields.Many2many(
		"repo.write.operation", "repo_write_op_dep_rel", "op_id", "depende_de_id",
		string="Depende de",
		help="Esta operación sólo se ejecuta si TODAS éstas quedaron aplicadas y "
			 "verificadas. Si alguna no, ésta no se intenta.")
	dependency_blocked_by = fields.Char(
		string="Bloqueada por", readonly=True, copy=False)
	result_json = fields.Text(string="Resultado", readonly=True, copy=False)
	error = fields.Text(string="Error", readonly=True, copy=False)
	audit_log_id = fields.Many2one(
		"repo.audit.log", string="Entrada de bitácora", readonly=True, copy=False,
		ondelete="set null")

	# Campos que entran en la huella del plan. `description` está incluida a propósito:
	# ver el docstring de `repo.write.plan._huella`.
	# `depends_on_ids` entra: cambiar de qué depende una operación cambia EN QUÉ
	# CONDICIONES se va a ejecutar, que es tan parte de lo aprobado como el payload.
	CAMPOS_EJECUTABLES = (
		"sequence", "kind", "repository_id", "target", "payload_json", "description",
		"depends_on_ids")

	def init(self):
		"""Un hallazgo no puede tener DOS operaciones vivas al mismo tiempo.

		POR QUÉ UN ÍNDICE Y NO UNA COMPROBACIÓN EN PYTHON. La comprobación existe igual
		—es la que da el mensaje amable «ya está en el plan N»— pero entre comprobar y
		crear hay una ventana, y el caso que hay que cerrar es exactamente ése: dos
		personas mirando la misma lista de hallazgos, o un doble clic. Un índice único
		parcial lo hace imposible en la base, no improbable.

		Es PARCIAL —sólo sobre las operaciones pendientes— porque una operación ya aplicada
		o revertida no estorba: si el hallazgo vuelve a aparecer en una auditoría
		posterior, tiene que poder planificarse de nuevo.
		"""
		super().init()
		from odoo.tools.sql import create_index

		create_index(
			self.env.cr, "repo_write_operation_finding_viva_uniq",
			self._table, ["finding_id"], unique=True,
			where="finding_id IS NOT NULL AND state = 'pending'",
			comment="Un hallazgo, una operación viva. Ver init().")

	@api.depends("kind", "repository_id", "target", "payload_json")
	def _compute_description(self):
		"""Traduce la operación a una frase. Es lo que se aprueba.

		POR QUÉ NO ALCANZA CON MOSTRAR EL PAYLOAD. Aprobar mirando
		`{"required_approving_review_count": 2, "allow_force_pushes": false}` no es
		aprobar: es confiar en que alguien más lo leyó. La frase «en primateuy/x, la rama
		17.0 pasa a exigir 2 aprobaciones y a bloquear force-push» se puede refutar de un
		vistazo, que es lo único que hace útil a una aprobación.
		"""
		for op in self:
			datos = {}
			if op.payload_json:
				try:
					datos = json.loads(op.payload_json)
				except (TypeError, ValueError):
					datos = {}
			op.is_destructive = op.kind in self.KINDS_DESTRUCTIVOS
			# IRREVERSIBLE SE DERIVA DE LOS HECHOS, no de una lista que alguien mantiene.
			# Una operación es irreversible cuando su manejador está implementado pero NO
			# declara cómo revertirla. Preguntárselo al manejador es lo que hace que el día
			# que se agregue «borrar una rama» la pantalla se entere sola.
			#
			# «No implementado» NO es lo mismo que «irreversible», y confundirlos sería
			# mentir en la dirección tranquilizadora: le diría a alguien «esto no tiene
			# vuelta atrás» cuando la verdad es «esto ni siquiera se puede hacer». Lo
			# encontró un test que recorría los diez tipos del selector y descubrió que dos
			# no tienen manejador.
			manejador = (op._manejadores() or {}).get(op.kind) if op.kind else {}
			op.is_supported = bool(manejador)
			op.is_irreversible = bool(manejador) and not manejador.get("revertir")
			op.description = op._describir(datos)

	def _describir(self, datos):
		"""La frase de esta operación. Un método por si un tipo nuevo necesita más."""
		self.ensure_one()
		repo = self.repository_id.full_name or _("(sin repositorio)")
		destino = self.target or "—"
		# PRIMERO lo que no se puede aplicar. Si esta comprobación fuera al final, un tipo
		# sin manejador saldría con su frase normal y bien redactada, y nadie sospecharía
		# nada hasta el apply. Una frase que suena bien sobre algo que no funciona es peor
		# que no tener frase.
		if not self.is_supported:
			return _(
				"%(tipo)s sobre %(repo)s / %(destino)s — ESTE TIPO TODAVÍA NO ESTÁ "
				"IMPLEMENTADO: el plan no se va a poder aplicar mientras esté."
			) % {"tipo": dict(OPERATION_KINDS).get(self.kind, self.kind),
				 "repo": repo, "destino": destino}
		if self.kind == "branch_protection_apply":
			return _("En %(repo)s, la rama %(rama)s pasa a %(reglas)s.") % {
				"repo": repo, "rama": destino,
				"reglas": self._frase_de_proteccion(datos)}
		if self.kind == "branch_protection_remove":
			return _(
				"En %(repo)s, la rama %(rama)s QUEDA SIN PROTECCIÓN: lo que hoy se frena "
				"—force-push, borrado, merges sin revisión— va a pasar."
			) % {"repo": repo, "rama": destino}
		if self.kind == "ruleset_create":
			return _("En %(repo)s se crea el ruleset «%(nombre)s».") % {
				"repo": repo, "nombre": datos.get("name") or destino}
		if self.kind == "ruleset_delete":
			return _(
				"En %(repo)s SE BORRA el ruleset «%(nombre)s» y dejan de aplicarse sus "
				"reglas.") % {"repo": repo, "nombre": datos.get("name") or destino}
		if self.kind == "collaborator_grant":
			return _("En %(repo)s, %(quien)s pasa a tener permiso de %(permiso)s.") % {
				"repo": repo, "quien": destino,
				"permiso": self._nombre_de_permiso(datos.get("permission"))}
		if self.kind == "collaborator_revoke":
			return _(
				"En %(repo)s, a %(quien)s SE LE QUITA el permiso directo. Si además está "
				"en un team con acceso, va a conservar el del team."
			) % {"repo": repo, "quien": destino}
		if self.kind == "team_repo_grant":
			return _("En %(repo)s, el team «%(team)s» pasa a tener %(permiso)s.") % {
				"repo": repo, "team": destino,
				"permiso": self._nombre_de_permiso(datos.get("permission"))}
		if self.kind == "team_repo_revoke":
			return _(
				"En %(repo)s, al team «%(team)s» SE LE QUITA el acceso, y con él lo "
				"pierden todos sus integrantes.") % {"repo": repo, "team": destino}
		if self.kind == "team_member_add":
			return _("%(quien)s entra al team «%(team)s».") % {
				"quien": datos.get("username") or "—", "team": destino}
		if self.kind == "module_copy":
			return _(
				"Se copia el módulo «%(modulo)s» a %(destino)s, rama %(rama)s, desde "
				"%(origen)s. Es un solo commit: o entra completo o no entra."
			) % {
				"modulo": datos.get("modulo") or (datos.get("ruta") or "").split("/")[-1],
				"destino": repo, "rama": datos.get("destino_rama") or "—",
				"origen": "%s@%s" % (datos.get("origen_repo") or "—",
									 datos.get("origen_rama") or "—"),
			}
		if self.kind == "module_delete":
			return _(
				"De %(repo)s, rama %(rama)s, SE BORRA el módulo «%(modulo)s» (%(ruta)s). "
				"Las instancias que lo tomen de este repositorio dejan de encontrarlo: "
				"eso es addons_path, y Repo Manager no lo cambia."
			) % {
				"repo": repo, "rama": datos.get("rama") or "—",
				"modulo": datos.get("modulo") or (datos.get("ruta") or "").split("/")[-1],
				"ruta": datos.get("ruta") or "—",
			}
		if self.kind == "team_member_remove":
			return _(
				"%(quien)s SALE del team «%(team)s» y pierde todo lo que ese team le daba."
			) % {"quien": datos.get("username") or "—", "team": destino}
		# Un tipo nuevo sin frase propia no puede quedarse mudo: se dice lo que se sabe y
		# se avisa que no está descrito, en vez de mostrar un vacío que parece un «nada».
		return _("%(tipo)s sobre %(repo)s / %(destino)s — sin descripción todavía.") % {
			"tipo": dict(OPERATION_KINDS).get(self.kind, self.kind),
			"repo": repo, "destino": destino}

	@api.model
	def _nombre_de_permiso(self, valor):
		from .repo_collaborator import PERMISSIONS

		return dict(PERMISSIONS).get(valor, valor or "—")

	@api.model
	def _frase_de_proteccion(self, datos):
		"""Las reglas de protección, enumeradas en el orden en que se piensan."""
		partes = []
		revisiones = (datos.get("required_pull_request_reviews") or {})
		if revisiones:
			cuantas = revisiones.get("required_approving_review_count")
			partes.append(_("exigir pull request con %s aprobación(es)") % cuantas
						  if cuantas is not None else _("exigir pull request"))
			if revisiones.get("require_code_owner_reviews"):
				partes.append(_("exigir revisión de owner"))
		if datos.get("allow_force_pushes") is False:
			partes.append(_("bloquear force-push"))
		if datos.get("allow_deletions") is False:
			partes.append(_("bloquear el borrado de la rama"))
		if datos.get("required_signatures"):
			partes.append(_("exigir commits firmados"))
		if not partes:
			return _("aplicar la protección del payload (sin reglas reconocidas)")
		return ", ".join(partes[:-1]) + (_(" y ") + partes[-1] if len(partes) > 1
										 else partes[0])

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
