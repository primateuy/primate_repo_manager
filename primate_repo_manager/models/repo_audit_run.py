# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Una corrida de auditoría.

Existe para que la auditoría sea REANUDABLE y comparable entre corridas. 94 repos por sus
ramas, colaboradores, PRs y commits no entran en un request ni en un cron sincrónico: se
enumera una vez y se encola un job por repo. Cada repo lleva su propio estado, así que
retomar una corrida cortada saltea lo que ya cerró en vez de empezar de cero y volver a
gastar cuota de API.
"""
import logging

from odoo import _, api, fields, models
from odoo.addons.queue_job.delay import chain, group
from odoo.exceptions import UserError

from .res_config_settings import DEFAULTS, ResConfigSettings

_logger = logging.getLogger(__name__)


class RepoAuditRun(models.Model):
	_name = "repo.audit.run"
	_description = "Corrida de auditoría"
	_inherit = ["mail.thread", "bus.listener.mixin"]
	_order = "id desc"

	name = fields.Char(string="Referencia", default="Auditoría", required=True)
	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True, ondelete="cascade", index=True)
	state = fields.Selection(
		[("draft", "Preparada"), ("running", "En curso"), ("done", "Terminada"),
		 ("partial", "Terminada con errores"), ("error", "Fallida")],
		string="Estado", default="draft", required=True, tracking=True, index=True)
	origin = fields.Selection(
		[("manual", "Lanzada a mano"), ("scheduled", "Programada")],
		string="Origen", default="manual", required=True, index=True,
		help="Quién la pidió: una persona o el cron semanal. La pantalla lo dice porque "
			 "«empezó 10:02, lanzada a mano por @gsosa» y «programada: lunes 08:00» se "
			 "leen distinto cuando algo salió mal.")
	started_at = fields.Datetime(string="Inicio", readonly=True)
	finished_at = fields.Datetime(string="Fin", readonly=True)

	# A10 · LOS CONTADORES SE CUENTAN, NO SE INCREMENTAN.
	#
	# Antes eran tres enteros que cada job sumaba al terminar su repositorio. Como la
	# transacción de un job dura todo el recorrido —unos ocho segundos— cualquier otro job
	# que confirmara en esa ventana lo mataba con «could not serialize access». queue_job
	# reintentaba y el número final salía bien, así que nadie lo notaba: lo que se pagaba
	# era que CADA REPOSITORIO se recorriera dos o tres veces. Medido: 7 repositorios, 19
	# ejecuciones; en producción, ~20 minutos donde alcanzaban 7.
	#
	# Ahora cada job escribe SU PROPIA fila —`repo.audit.run.line`— y nadie comparte una.
	# Los totales se derivan contando, que es el patrón que ya se probó en el avance del
	# plan (A4.5): un conteo no puede desfasarse de la realidad porque ES la realidad.
	#
	# El efecto que importa para lo que viene: la fila de la corrida deja de escribirse en
	# cada repositorio y pasa a escribirse UNA vez, al cerrar. Sin eso, los webhooks de F4
	# —que escribirían en paralelo con las auditorías— volverían a chocar contra lo mismo.
	line_ids = fields.One2many(
		"repo.audit.run.line", "run_id", string="Repositorios de la corrida")
	# SIN `store=True`, Y ES EL PUNTO ENTERO DE A10. Guardarlos parecía gratis y no lo
	# es: un campo calculado y almacenado hace que Odoo ESCRIBA la fila de la corrida cada
	# vez que cambia una línea, o sea exactamente la escritura compartida que este cambio
	# vino a eliminar. Se descubrió midiendo contra el sandbox: con `store=True` y dos
	# hilos, la mitad de los jobs murió con «could not serialize access».
	#
	# El precio es que no se pueden ordenar las listas por estas columnas. Es barato: los
	# números de una corrida vieja siguen siendo suyos porque las LÍNEAS se guardan, que
	# es lo que había que preservar.
	repos_total = fields.Integer(
		string="Repos a recorrer", compute="_compute_conteos")
	repos_done = fields.Integer(string="Recorridos", compute="_compute_conteos")
	repos_error = fields.Integer(string="Con error", compute="_compute_conteos")
	progress = fields.Float(string="Avance", compute="_compute_progress")

	error_detail = fields.Text(string="Detalle del error", readonly=True)

	finding_ids = fields.One2many("repo.audit.finding", "run_id", string="Hallazgos")
	finding_count = fields.Integer(string="Hallazgos", compute="_compute_findings")
	critical_count = fields.Integer(string="Críticos", compute="_compute_findings")
	high_count = fields.Integer(string="Altos", compute="_compute_findings")

	@api.depends("finding_ids.severity")
	def _compute_findings(self):
		for run in self:
			run.finding_count = len(run.finding_ids)
			run.critical_count = len(run.finding_ids.filtered(
				lambda f: f.severity == "critical"))
			run.high_count = len(run.finding_ids.filtered(lambda f: f.severity == "high"))

	def action_evaluate(self):
		"""Recalcula los hallazgos sin volver a pegarle a GitHub."""
		self.ensure_one()
		self.env["repo.audit.engine"].evaluate(self)
		self.message_post(body=_("Hallazgos recalculados: %s.") % self.finding_count)
		return True

	@api.depends("line_ids.state")
	def _compute_conteos(self):
		for run in self:
			estados = run.line_ids.mapped("state")
			run.repos_total = len(estados)
			run.repos_done = estados.count("done")
			run.repos_error = estados.count("error")

	@api.depends("repos_total", "repos_done", "repos_error")
	def _compute_progress(self):
		for run in self:
			total = run.repos_total or 0
			run.progress = ((run.repos_done + run.repos_error) / total * 100) if total else 0.0

	# ------------------------------------------------------------------
	# Avance en vivo
	# ------------------------------------------------------------------

	# El tipo de mensaje que escucha el componente de la pantalla.
	AVISO = "repo_manager.audit_progress"

	def _emitir_avance(self, actual=None, inmediato=False):
		"""Avisa a las pantallas abiertas cómo va la corrida.

		El mensaje lleva TODO el estado y no un incremento: si un aviso se pierde —una
		pestaña que estaba dormida, una reconexión— el siguiente la deja al día igual.
		Mandar «+1» obligaría al navegador a llevar la cuenta y a quedar desfasado para
		siempre en cuanto se pierda uno.

		`actual` es el repositorio que se está recorriendo en este momento. Es la señal de
		que hay vida: sin ella, una corrida lenta y una colgada se ven igual.

		POR QUÉ EXISTE `inmediato`. El bus de Odoo NO manda nada hasta que la transacción
		confirma: `_sendone` deja la fila en un hook de precommit y el NOTIFY en uno de
		postcommit. Cada repositorio se recorre dentro de un job, y un job confirma recién
		cuando termina — así que un aviso «arranqué con X» emitido por el camino normal
		llega junto con el «terminé con X», siempre tarde y siempre mintiendo: la pantalla
		diría «Ahora: X» cuando X ya está hecho.

		Con `inmediato` el aviso sale por una conexión propia que confirma en el acto, y
		«Ahora:» dice la verdad. Es deliberado que estos avisos NO sean transaccionales:
		son señales de vida, no datos. Si el job después se cae, lo que quedó dicho es que
		se empezó a recorrer ese repositorio — que es exactamente lo que pasó.

		Sólo escribe filas nuevas en `bus.bus`, nunca actualiza nada: una conexión aparte
		que hiciera UPDATE sobre filas que la transacción principal también toca termina
		en «could not serialize access», que es como se descubrió esto en el paso 3e.
		"""
		self.ensure_one()
		# Se arma con los valores de ESTA transacción. Una conexión nueva no ve lo que
		# todavía no se confirmó, así que leer allá daría números viejos.
		aviso = {
			"id": self.id,
			"state": self.state,
			"total": self.repos_total,
			"done": self.repos_done,
			"error": self.repos_error,
			"actual": actual,
			"findings": self.finding_count if self.state in ("done", "partial") else 0,
			"criticos": self.critical_count if self.state in ("done", "partial") else 0,
			"altos": self.high_count if self.state in ("done", "partial") else 0,
		}
		if not inmediato:
			self._bus_send(self.AVISO, aviso)
			return
		with self._cursor_de_avisos() as cr:
			self.env(cr=cr)["repo.audit.run"].browse(self.id)._bus_send(self.AVISO, aviso)

	# --- las columnas Nuevos / Resueltos de la lista de corridas ---
	#
	# SE CALCULAN, NO SE GUARDAN. Un contador guardado es una fila que alguien escribe, y
	# la regla del módulo es derivar contando (A4.5 y A10 lo midieron). Acá además sería
	# peor: el delta depende de CUÁL sea la corrida anterior, y esa respuesta cambia sola
	# —una corrida vieja que se reevalúa, una fallida que deja de contar— así que un
	# número guardado envejecería mal sin que nadie lo tocara.
	delta_new_count = fields.Integer(
		string="Nuevos", compute="_compute_delta", help=(
			"Hallazgos que no estaban en la corrida anterior comparable."))
	delta_resolved_count = fields.Integer(
		string="Resueltos", compute="_compute_delta", help=(
			"Estaban en la anterior y ya no. No incluye los de repositorios que no se "
			"pudieron volver a leer: ésos no se resolvieron, no se miraron."))
	delta_note = fields.Char(string="Comparación", compute="_compute_delta")

	@api.depends("state", "finding_ids")
	def _compute_delta(self):
		Delta = self.env["repo.audit.delta"]
		for corrida in self:
			datos = Delta.calcular(corrida)
			corrida.delta_new_count = len(datos["nuevos"])
			corrida.delta_resolved_count = len(datos["resueltos"])
			corrida.delta_note = "" if datos["comparable"] else datos["motivo"]

	def _notificar_delta(self):
		"""El correo del lunes y el aviso en Discuss. Una sola llamada para los dos.

		`message_post` con destinatarios hace las dos cosas a la vez: deja el mensaje en
		la conversación de la corrida —que es lo que aparece en Discuss— y lo manda por
		correo a quien esté en la lista. Dos mecanismos separados serían dos textos que
		se desincronizan, y el que se lee menos envejece mal.

		SÓLO PARA LAS CORRIDAS PROGRAMADAS. Una auditoría lanzada a mano ya tiene a
		alguien mirando la pantalla; mandarle un correo de lo que está viendo es la clase
		de ruido que hace que el correo del lunes se ignore.

		Y SE MANDA AUNQUE LA CORRIDA HAYA FALLADO. Ver `repo.delta.mail`: no mandar nada
		dejaría creer que no hay novedades, y la semana que la auditoría no corre es
		justamente la semana en la que nadie está mirando.
		"""
		self.ensure_one()
		if self.origin != "scheduled":
			return False
		destinatarios = self.env["repo.settings"]._destinatarios()
		if not destinatarios:
			_logger.warning(
				"Repo Manager: la corrida %s terminó y no hay destinatarios para el "
				"resumen. Se puede configurar en Ajustes.", self.id)
			return False
		Correo = self.env["repo.delta.mail"]
		try:
			cuerpo = Correo.cuerpo(self)
			asunto = Correo.asunto(self)
		except Exception:  # noqa: BLE001 - el resumen no puede tumbar la auditoría
			_logger.exception(
				"Repo Manager: no se pudo armar el resumen de la corrida %s", self.id)
			return False
		self.message_post(
			body=cuerpo, subject=asunto,
			partner_ids=destinatarios.ids,
			message_type="notification",
			subtype_xmlid="mail.mt_comment")
		return True

	@api.model
	def avisos_de_barra(self):
		"""Los dos avisos permanentes de la barra. UNA sola llamada para los dos.

		SÓLO LO QUE EL USUARIO PUEDE VER. Se buscan con los permisos de quien pregunta,
		sin `sudo()`: la barra está en todas las pantallas y no puede ser la rendija por
		la que alguien se entera de que existe una conexión que no tiene permiso de
		mirar.

		Y SÓLO LOS PLANES QUE LE TOCAN. Un aviso permanente sobre algo que uno no puede
		aprobar es ruido que además no se puede sacar: quien no tiene el rol lo vería
		para siempre.
		"""
		en_curso = self.search([("state", "=", "running")], order="id desc", limit=1)
		aviso_auditoria = False
		if en_curso:
			lineas = en_curso.line_ids
			aviso_auditoria = {
				"id": en_curso.id,
				"leidos": len(lineas.filtered(lambda l: l.state == "done")),
				"total": len(lineas),
			}
		aviso_plan = False
		if self.env.user.has_group("primate_repo_manager.group_repo_lead"):
			borradores = self.env["repo.write.plan"].search(
				[("state", "=", "draft"), ("operation_ids", "!=", False)],
				order="id desc")
			if borradores:
				aviso_plan = {
					"id": borradores[0].id,
					"nombre": borradores[0].display_name,
					"cuantos": len(borradores),
					"operaciones": len(borradores[0].operation_ids),
				}
		return {"auditoria": aviso_auditoria, "plan": aviso_plan}

	def delta(self):
		"""Qué cambió respecto de la corrida anterior. Atajo hacia `repo.audit.delta`.

		Vive como método de la corrida porque es donde se lo busca —la pantalla, el
		correo y el test entran por acá— pero la lógica está en un modelo aparte: la
		comparación no es de una corrida contra el mundo, es entre dos, y meterla en el
		modelo de una de ellas la habría atado a `run_id` justo en la parte que no puede
		depender de él.
		"""
		self.ensure_one()
		return self.env["repo.audit.delta"].calcular(self)

	def action_armar_plan_con_los_nuevos(self, hallazgo_ids=None):
		"""«Armar plan con los N nuevos». ARMA Y NO EJECUTA, como todo acá.

		NO ESTRENA UNA PUERTA. Los hallazgos entran al plan por `action_remediate_many`,
		que es la misma que usan el botón de la lista y el arrastre: tres caminos que
		crearan operaciones por su cuenta divergirían, y el que se mira menos envejece
		mal. Lo único que agrega este método es de QUÉ conjunto salen —los nuevos de
		este delta— y la comprobación de que ese conjunto sea de esta corrida.

		Un plan armado queda en borrador. Después alguien tiene que aprobarlo operación
		por operación, y recién ahí se escribe en GitHub.
		"""
		self.ensure_one()
		Hallazgo = self.env["repo.audit.finding"]
		if hallazgo_ids:
			hallazgos = Hallazgo.browse(hallazgo_ids).exists()
			# QUE SEAN DE ESTA CORRIDA. Los ids llegan del navegador, y armar un plan
			# con hallazgos de otra corrida —o de otra cuenta— sería una escritura
			# planificada sobre algo que esta pantalla nunca mostró.
			ajenos = hallazgos.filtered(lambda h: h.run_id != self)
			if ajenos:
				raise UserError(_(
					"Esos hallazgos no son de esta corrida. Volvé a abrir la pantalla: "
					"lo que se ve y lo que se planifica tienen que ser lo mismo."))
		else:
			hallazgos = self.delta()["nuevos"]
		if not hallazgos:
			raise UserError(_(
				"No hay hallazgos nuevos respecto de la corrida anterior."))
		return hallazgos.action_remediate_many()

	def action_open_findings(self):
		"""Los hallazgos de esta corrida.

		Existe además del botón del componente porque aquél sólo aparece cuando la corrida
		terminó, y una corrida vieja se abre para mirar lo que encontró, no para verla
		correr. Un camino que depende del estado en que se abrió la pantalla es un camino
		que a veces no está.
		"""
		self.ensure_one()
		accion = self.env["ir.actions.actions"]._for_xml_id(
			"primate_repo_manager.action_repo_audit_finding")
		accion["domain"] = [("run_id", "=", self.id)]
		accion["context"] = {"search_default_g_sev": 1}
		accion["display_name"] = _("Hallazgos de %s") % self.display_name
		return accion

	def action_refresh_progress(self):
		"""Vuelve a emitir el estado actual a las pantallas abiertas.

		Existe por el caso degradado que el propio componente sabe reconocer: cuando hace
		rato que no llegan novedades, el usuario no tiene forma de saber si la corrida
		avanza sin novedades o si se cortó el hilo que las trae. Recargar la página entera
		para averiguarlo es lo que este componente vino a evitar, así que hay un «volver a
		preguntar» que cuesta una consulta y no pierde nada de lo que haya en pantalla.

		`actual` NO se guarda en ningún lado y no hace falta: el repositorio que se está
		recorriendo es el que tiene el espejo en «en curso». Derivarlo de ahí en vez de
		pasearlo por parámetros es lo que hace que este método pueda decir la verdad sin
		que nadie se la cuente.
		"""
		self.ensure_one()
		en_curso = self.backend_id.repository_ids.filtered(
			lambda r: r.sync_state == "running")
		self._emitir_avance(actual=en_curso[:1].full_name or None)
		return True

	def _cursor_de_avisos(self):
		"""Conexión propia para los avisos que tienen que salir antes de confirmar.

		Costura de test, igual que `repo.write.operation._cursor_durable`: en un test no
		hay nada confirmado y abrir otra conexión no vería ni la corrida, así que se la
		reemplaza por el cursor actual. Con ese reemplazo se verifica QUÉ se manda; que
		salga antes de confirmar se verifica contra el sandbox, mirando la pantalla.
		"""
		return self.pool.cursor()

	# ------------------------------------------------------------------
	# Ciclo
	# ------------------------------------------------------------------

	@api.model
	def _cron_auditoria_programada(self):
		"""La auditoría de los lunes. Una corrida POR CONEXIÓN verificada.

		POR QUÉ UNA POR CONEXIÓN Y NO UNA SOLA. Una corrida pertenece a un backend —sus
		repositorios, sus líneas, sus hallazgos y su delta salen de ahí—, así que auditar
		dos cuentas en una corrida mezclaría dos inventarios que no se comparan entre sí.

		LO QUE NO ESTÁ VERIFICADO NO SE AUDITA. Una conexión que no pasó su prueba gasta
		la ventana entera para terminar en error; se saltea diciéndolo, que es distinto de
		no intentarlo.

		Y NO SE PISA UNA CORRIDA EN CURSO. El cron semanal puede caer sobre una auditoría
		lanzada a mano que todavía no terminó; empezar otra encima duplicaría el trabajo
		contra la misma cuenta y dejaría dos deltas que se contradicen. Se saltea **con
		constancia en el chatter de la conexión**: un salteo silencioso se lee, la semana
		siguiente, como «el cron no corrió».

		Returns:
			dict: cuántas corridas se lanzaron y cuántas se saltearon, con el motivo. Lo
				devuelve para que el test —y quien lo llame a mano— pueda afirmar sobre
				el resultado y no sobre el log.
		"""
		lanzadas, salteadas = self.browse(), []
		for backend in self.env["repo.backend"].search([]):
			if backend.state != "connected":
				salteadas.append((backend, _("la conexión no está verificada")))
				continue
			en_curso = self.search([
				("backend_id", "=", backend.id),
				("state", "in", ("draft", "running"))], limit=1)
			if en_curso:
				motivo = _(
					"ya hay una auditoría en curso (%s), lanzada antes de esta ventana"
				) % en_curso.display_name
				salteadas.append((backend, motivo))
				# LA CONSTANCIA, en el chatter de la conexión y no sólo en el log: el log
				# del servidor no lo mira nadie el lunes a la mañana.
				backend.message_post(body=_(
					"Auditoría programada salteada: %s. No se lanza otra encima para no "
					"duplicar el trabajo contra la misma cuenta.") % motivo)
				continue
			corrida = self.create({
				"name": _("Auditoría programada de %s") % backend.name,
				"backend_id": backend.id,
				"origin": "scheduled",
			})
			corrida.action_start()
			lanzadas |= corrida

		for backend, motivo in salteadas:
			_logger.info(
				"Repo Manager: auditoría programada salteada en «%s»: %s",
				backend.name, motivo)
		_logger.info(
			"Repo Manager: auditoría programada — %s lanzada(s), %s salteada(s).",
			len(lanzadas), len(salteadas))
		return {"lanzadas": lanzadas, "salteadas": salteadas}

	def action_start(self):
		"""Lanza la auditoría. Corre en el momento o se encola, según cuántos repos haya.

		POR QUÉ EL ENUMERADO VA SIEMPRE EN EL MOMENTO. Es una sola llamada paginada, y es
		la única forma de saber cuántos repositorios hay ANTES de decidir. Un umbral
		evaluado sobre el espejo que ya existe sería inútil justo en la primera corrida,
		que es cuando el espejo está vacío.

		POR QUÉ HAY DOS CAMINOS. Encolar exige un procesador de tareas en segundo plano
		corriendo; para una organización chica eso es infraestructura que alguien tiene
		que entender y mantener para nada. Por encima del umbral, en cambio, el recorrido
		no entra en el tiempo de una petición y encolar es la única opción.

		SIN COMMITS POR REPOSITORIO en el camino sincrónico. Confirmar a mitad de una
		petición es exactamente lo que `queue_job` existe para evitar, y no hace falta:
		los errores de cada repositorio ya se capturan sin abortar el recorrido, así que
		lo único que pierde una caída dura es una corrida que se vuelve a lanzar. Lo que
		no queremos es media corrida guardada que parezca completa.
		"""
		self.ensure_one()
		if self.backend_id.state != "connected":
			raise UserError(_(
				"La conexión «%s» no está verificada. Probá la conexión antes de auditar: "
				"una corrida con credenciales rotas gasta tiempo para terminar en error."
			) % self.backend_id.name)
		self.write({
			"state": "running", "started_at": fields.Datetime.now(),
			"error_detail": False,
		})

		repos = self._enumerar()
		umbral = int(ResConfigSettings._repo_param(
			self.env, "repo_manager.sync_threshold",
			DEFAULTS["repo_manager.sync_threshold"]))

		if len(repos) <= umbral:
			self.message_post(body=_(
				"Auditando %(n)s repositorio(s) en el momento (el umbral para encolar es "
				"%(umbral)s).") % {"n": len(repos), "umbral": umbral})
			for repo in repos:
				repo._job_sync_repository(self.id)
			# En el camino sincrónico todo pasa en la MISMA transacción, así que acá sí se
			# sabe que no queda nada: no hace falta job de cierre.
			self._cerrar_si_termino()
			self._emitir_avance()
			return True

		self.message_post(body=_(
			"%(n)s repositorio(s) encolados: son más de %(umbral)s y el recorrido no "
			"entra en el tiempo de una pantalla.") % {"n": len(repos), "umbral": umbral})
		self._encolar(repos)
		return True

	def _encolar(self, repos):
		"""Un job por repositorio, y UN job de cierre que espera a todos.

		POR QUÉ EL CIERRE NO LO HACE EL ÚLTIMO REPOSITORIO. Parece lo natural —el que
		termina último cierra— y con un solo hilo funcionaba. Con dos no: cada job corre en
		su propia transacción, así que cuando A pregunta «¿queda algo pendiente?» ve su
		línea hecha y la de B todavía en curso, porque B no confirmó. B ve exactamente lo
		mismo al revés. **Ninguno se cree el último y la corrida queda abierta para
		siempre.** Medido contra el sandbox: 6 repositorios, 6 jobs sin un solo reintento,
		y la corrida en «en curso» con todo terminado.

		No hay forma de arreglarlo mirando desde adentro de una transacción: quién es el
		último sólo se sabe DESPUÉS de que todos confirmaron. Por eso el cierre es un job
		aparte que depende de los demás — `queue_job` lo ejecuta cuando el grupo entero
		terminó, que es justamente la información que a los jobs les falta.
		"""
		self.ensure_one()
		trabajos = group(*[
			repo.delayable(channel="root.repo_manager")._job_sync_repository(self.id)
			for repo in repos
		])
		cierre = self.delayable(channel="root.repo_manager")._job_cerrar()
		chain(trabajos, cierre).delay()

	def _job_cerrar(self):
		"""Cierra la corrida. Corre cuando todos los repositorios terminaron.

		Sigue pasando por `_cerrar_si_termino`, con su candado: el job de cierre es uno
		solo, pero el camino sincrónico y una reanudación también cierran, y una guarda que
		depende de que haya un único llamador no es una guarda.
		"""
		self.ensure_one()
		self._cerrar_si_termino()
		self._emitir_avance()

	def action_resume(self):
		"""Retoma una corrida cortada: sólo los repos que no cerraron bien."""
		self.ensure_one()
		pendientes = self.backend_id.repository_ids.filtered(
			lambda r: r.sync_state in ("pending", "running", "error"))
		if not pendientes:
			raise UserError(_("No quedan repositorios pendientes en esta corrida."))
		self.write({"state": "running", "error_detail": False})
		# Una reanudación puede encontrarse repositorios que no tenían fila —corridas
		# anteriores a A10, o repos que aparecieron después del enumerado—. Se crean acá
		# para que el conteo cierre.
		conocidos = self.line_ids.mapped("repository_id")
		nuevos = pendientes - conocidos
		if nuevos:
			self.env["repo.audit.run.line"].create([
				{"run_id": self.id, "repository_id": r.id} for r in nuevos])
		self.line_ids.filtered(
			lambda l: l.repository_id in pendientes).write({"state": "pending"})
		self._encolar(pendientes)
		self.message_post(body=_(
			"Reanudada: %s repositorio(s) pendientes encolados.") % len(pendientes))
		return True

	def _enumerar(self):
		"""Trae la lista de repositorios y los deja listos para recorrer."""
		self.ensure_one()
		try:
			repos = self.env["repo.repository"]._sync_from_backend(self.backend_id)
		except Exception as exc:  # noqa: BLE001 - el error se muestra, nunca se traga
			_logger.exception("Repo Manager: falló el enumerado de la corrida %s", self.id)
			self.write({
				"state": "error", "error_detail": str(exc),
				"finished_at": fields.Datetime.now(),
			})
			self.message_post(body=_("La auditoría falló al enumerar repositorios: %s") % exc)
			# EL CORREO SALE IGUAL. Es la honestidad de pantalla aplicada al silencio:
			# una semana sin correo se lee como «no hubo novedades», y lo que pasó es
			# que nadie miró.
			self._notificar_delta()
			raise
		# Una fila por repositorio de ESTA corrida. Es lo que después permite contar sin
		# que dos jobs se pisen, y lo que hace que los números de una corrida vieja sigan
		# siendo los suyos y no los del espejo de hoy.
		self.line_ids.unlink()
		self.env["repo.audit.run.line"].create([
			{"run_id": self.id, "repository_id": repo.id} for repo in repos])
		repos.write({"sync_state": "pending"})
		return repos

	def _job_enumerate(self):
		"""Enumerado diferido, para reanudar una corrida encolada."""
		self.ensure_one()
		repos = self._enumerar()
		self._encolar(repos)
		self.message_post(body=_("%s repositorio(s) encolados.") % len(repos))

	def _register_repo_done(self, repositorio, con_error=False, error=None):
		"""Lo llama cada job al terminar SU repositorio. Escribe su fila y nada más.

		Ya no toca los contadores de la corrida: eso era la fila compartida que hacía
		chocar a los jobs entre sí. Lo único que se sigue escribiendo en la corrida es el
		cierre, y de eso se encarga un solo job — el último — bajo candado.
		"""
		self.ensure_one()
		linea = self.line_ids.filtered(lambda l: l.repository_id == repositorio)[:1]
		if not linea:
			# Puede pasar en una reanudación de una corrida vieja, anterior a las filas.
			linea = self.env["repo.audit.run.line"].create({
				"run_id": self.id, "repository_id": repositorio.id})
		linea.write({
			"state": "error" if con_error else "done",
			"error": (error or "")[:500] or False,
			"finished_at": fields.Datetime.now(),
		})
		# NO se intenta cerrar acá: un job no puede saber si es el último, porque no ve las
		# transacciones de los demás. Lo hace el job de cierre. Ver `_encolar`.
		self._emitir_avance()

	def _cerrar_si_termino(self):
		"""Cierra la corrida cuando no queda ninguna fila pendiente.

		EL CANDADO NO ES PARANOIA. Dos jobs pueden terminar casi a la vez y ver los dos
		que «ya no queda nada», y cerrar dos veces significa evaluar los hallazgos dos
		veces, o sea duplicarlos. El `FOR UPDATE` serializa a los candidatos a cerrar, y
		la re-lectura del estado hace que el segundo encuentre la corrida ya cerrada y se
		vaya. Es el único lugar donde dos jobs pueden querer escribir la misma fila, y por
		eso es el único con candado.
		"""
		self.ensure_one()
		self.env.flush_all()
		self.env.cr.execute(
			"SELECT state FROM repo_audit_run WHERE id = %s FOR UPDATE", (self.id,))
		fila = self.env.cr.fetchone()
		if not fila or fila[0] != "running":
			return False
		self.invalidate_recordset(["repos_total", "repos_done", "repos_error"])
		if self.line_ids.filtered(lambda l: l.state in ("pending", "running")):
			return False
		self.write({
			"state": "partial" if self.repos_error else "done",
			"finished_at": fields.Datetime.now(),
		})
		self.backend_id.last_sync = fields.Datetime.now()
		# Los hallazgos se calculan al cerrar: recién ahí están todos los datos.
		self.env["repo.audit.engine"].evaluate(self)
		# Y la foto de las métricas, por el mismo motivo y en el mismo momento. La
		# tendencia no se reconstruye hacia atrás: si esto empezara con el panel que las
		# muestra, ese panel abriría con un solo punto.
		self.env["repo.metric"].registrar_corrida(self)
		# Y el resumen, después de los hallazgos y de la foto: antes no habría qué
		# contar. Sólo sale para las corridas programadas.
		self._notificar_delta()
		self.message_post(body=_(
			"Auditoría terminada: %(ok)s repositorio(s) recorridos, %(mal)s con error. "
			"%(hallazgos)s hallazgo(s)."
		) % {"ok": self.repos_done, "mal": self.repos_error,
			 "hallazgos": self.finding_count})
		return True

	# ------------------------------------------------------------------
	# Ayudantes del informe
	# ------------------------------------------------------------------
	# Viven acá y no en el QWeb a propósito: una plantilla llena de lógica es imposible
	# de leer y de testear. Acá se pueden probar como cualquier método.

	# Tipos que tienen su propia sección en el informe y por eso NO se repiten en las
	# tablas de hallazgos. El resumen los cuenta aparte para que los números cierren:
	# un lector que suma las tablas y no llega al total del resumen deja de confiar.
	TIPOS_CON_SECCION_PROPIA = (
		"convention_adoption", "repo_sync_error", "branch_protection_unreadable")

	def _report_severity_summary(self):
		"""Conteo por severidad con una explicación en lenguaje llano."""
		self.ensure_one()
		significados = {
			"critical": _("Requiere acción inmediata: acceso o integridad comprometidos."),
			"high": _("Hay que resolverlo pronto; deja repositorios sin control efectivo."),
			"medium": _("Conviene ordenarlo, pero no bloquea el trabajo del día a día."),
			"info": _("Para tener presente al decidir; no es un incumplimiento."),
		}
		etiquetas = dict(self.env["repo.audit.finding"]._fields["severity"].selection)
		resumen = []
		colores = self._report_severity_colors()
		for clave in ("critical", "high", "medium", "info"):
			todos = self.finding_ids.filtered(lambda f, c=clave: f.severity == c)
			aparte = todos.filtered(
				lambda f: f.finding_type in self.TIPOS_CON_SECCION_PROPIA)
			if todos:
				resumen.append({
					"key": clave, "label": etiquetas.get(clave, clave),
					# El conteo es de TODOS los hallazgos de esa severidad, sin
					# excepciones: si el resumen no suma el total, el lector deja de
					# confiar en el resto del documento.
					"count": len(todos), "aside": len(aparte),
					"meaning": significados[clave], "color": colores[clave],
				})
		return resumen

	def _report_aside_total(self):
		"""Cuántos hallazgos se desarrollan en secciones propias en vez de en las tablas."""
		self.ensure_one()
		return len(self.finding_ids.filtered(
			lambda f: f.finding_type in self.TIPOS_CON_SECCION_PROPIA))

	def _report_findings_by_severity(self):
		"""Hallazgos agrupados, de lo más grave a lo informativo."""
		self.ensure_one()
		etiquetas = dict(self.env["repo.audit.finding"]._fields["severity"].selection)
		grupos = []
		for clave in ("critical", "high", "medium", "info"):
			hallazgos = self.finding_ids.filtered(
				lambda f, c=clave: f.severity == c
				and f.finding_type not in self.TIPOS_CON_SECCION_PROPIA)
			if hallazgos:
				grupos.append({
					"key": clave, "label": etiquetas.get(clave, clave),
					"findings": hallazgos,
					"color": self._report_severity_colors()[clave],
				})
		return grupos

	@api.model
	def _report_severity_colors(self):
		"""Color por severidad. En un documento que se usa para decidir, lo grave tiene
		que distinguirse antes de leer la palabra."""
		return {
			"critical": "#B02A37",
			"high": "#D97706",
			"medium": "#6B7280",
			"info": "#9CA3AF",
		}

	def _ramas_ilegibles(self):
		"""Ramas cuya protección no se pudo leer, en TODO el espejo de la conexión.

		SALE DEL ESPEJO Y NO DE LOS HALLAZGOS, y la diferencia importa. Los hallazgos por
		rama sólo se emiten para los repositorios que se comparan ítem por ítem contra una
		plantilla: un fork sin migrar y uno sin clasificar se saltean a propósito, porque
		no hay contra qué compararlos. Pero la COBERTURA es otra pregunta: "¿de cuántos
		repositorios no sabemos si están protegidos?" no depende de si los evaluamos.

		Contándolo desde los hallazgos, el informe decía 4 repositorios cuando eran 30, y
		ese número es justamente el insumo de la decisión de plan.
		"""
		self.ensure_one()
		return self.env["repo.branch"].search([
			("repository_id", "in",
			 self.backend_id.repository_ids.filtered(lambda r: not r.archived).ids),
			("protection_readable", "=", False),
		])

	@staticmethod
	def _agrupar_por_repo(ramas, extra=None):
		"""De un recordset de ramas a filas por repositorio, ordenadas por nombre."""
		por_repo = {}
		for rama in ramas:
			por_repo.setdefault(rama.repository_id, []).append(rama.name or "")
		filas = []
		for repo, nombres in sorted(por_repo.items(), key=lambda kv: kv[0].full_name or ""):
			fila = {"repository": repo, "branches": sorted(nombres), "count": len(nombres)}
			if extra:
				fila.update(extra(repo, nombres))
			filas.append(fila)
		return filas

	def _report_parcialmente_legibles(self):
		"""Cuántos repositorios tuvieron alguna lectura que GitHub no permitió.

		Distinto de `repos_error`: esos no se recorrieron. Estos sí, y por eso el resumen
		de cobertura no puede decir «se pudo revisar la totalidad» a secas cuando arriba,
		en la misma página, hay una sección diciendo que en 30 no se pudo leer la
		protección. Una de las dos frases sobra, y la que sobra es la optimista.
		"""
		self.ensure_one()
		return len(self.backend_id.repository_ids.filtered(
			lambda r: not r.archived and r.unreadable_json))

	def _report_unreadable(self, causa):
		"""Agrupado POR REPOSITORIO, no por rama.

		El número que importa en la conversación del plan es cuántos repositorios quedan
		fuera de control, no cuántas ramas: un repo con seis ramas ilegibles es un
		repositorio, y contar ramas contra un total de repositorios compara peras con
		manzanas.
		"""
		self.ensure_one()
		return self._agrupar_por_repo(
			self._ramas_ilegibles().filtered(
				lambda b: (b.protection_cause or "unknown") == causa))

	def _report_unreadable_otras(self):
		"""Las causas de ilegibilidad que NO tienen sección propia en el informe.

		Existe para que agregar una causa nueva a `UNREADABLE_CAUSES` no la haga
		desaparecer del documento en silencio. Hoy debería dar vacío; el día que no, el
		informe lo dice en vez de perderlo.
		"""
		self.ensure_one()
		etiquetas = dict(
			self.env["repo.branch"]._fields["protection_cause"].selection)
		con_seccion = ("plan_limit", "no_admin_permission")
		ramas = self._ramas_ilegibles().filtered(
			lambda b: (b.protection_cause or "unknown") not in con_seccion)
		por_clave = {}
		for rama in ramas:
			clave = (rama.repository_id, rama.protection_cause or "unknown")
			por_clave.setdefault(clave, []).append(rama.name or "")
		return [
			{"repository": repo, "cause": causa,
			 "cause_label": etiquetas.get(causa, causa),
			 "branches": sorted(nombres), "count": len(nombres)}
			for (repo, causa), nombres in sorted(
				por_clave.items(), key=lambda kv: (kv[0][0].full_name or "", kv[0][1]))
		]

	def _report_unaudited(self):
		"""Repos no auditados, con el motivo en lenguaje del informe.

		El error crudo de la API no le dice nada a quien lee: se traduce a qué pasó y qué
		hacer, y el texto técnico queda entre paréntesis para quien lo necesite.
		"""
		self.ensure_one()
		filas = []
		for hallazgo in self.finding_ids.filtered(
				lambda f: f.finding_type == "repo_sync_error"):
			tecnico = (hallazgo.detail or "").strip()
			if "403" in tecnico or "not accessible" in tecnico.lower():
				motivo = _(
					"La aplicación no tiene acceso a este repositorio. Se resuelve con la "
					"misma revisión de permisos descrita más arriba.")
			elif "404" in tecnico:
				motivo = _(
					"El repositorio no estaba disponible al momento de la auditoría; puede "
					"haber sido renombrado o eliminado.")
			elif "rate" in tecnico.lower() or "cuota" in tecnico.lower():
				motivo = _(
					"Se agotó la cuota de consultas a GitHub. Se resuelve volviendo a "
					"correr la auditoría más tarde.")
			else:
				motivo = _("No se pudo completar la lectura de este repositorio.")
			filas.append({
				"repository": hallazgo.repository_id,
				"reason": motivo,
				"technical": tecnico,
			})
		return filas

	def _report_finding(self, tipo, todos=False):
		self.ensure_one()
		hallazgos = self.finding_ids.filtered(lambda f: f.finding_type == tipo)
		return hallazgos if todos else hallazgos[:1]

	def _report_has_modulated(self):
		"""¿Hay alguna severidad ajustada? Si no, la leyenda sobra."""
		self.ensure_one()
		return bool(self.finding_ids.filtered("severity_modulated"))

	def _report_date(self):
		"""Fecha en dd/mm/yyyy y hora en 24 h, como el resto del documento en español."""
		self.ensure_one()
		if not self.started_at:
			return ""
		local = fields.Datetime.context_timestamp(self, self.started_at)
		return local.strftime("%d/%m/%Y %H:%M")

	@api.model
	def _report_plural(self, cantidad, singular, plural=None):
		"""«1 repositorio» y no «1 repositorios».

		Es un detalle, pero el informe se lee en una reunión y los detalles de redacción
		son los que hacen que un documento parezca cuidado o generado.
		"""
		if cantidad == 1:
			return "%s %s" % (cantidad, singular)
		return "%s %s" % (cantidad, plural or "%ss" % singular)
