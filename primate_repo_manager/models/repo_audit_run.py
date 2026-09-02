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
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RepoAuditRun(models.Model):
	_name = "repo.audit.run"
	_description = "Corrida de auditoría"
	_inherit = ["mail.thread"]
	_order = "id desc"

	name = fields.Char(string="Referencia", default="Auditoría", required=True)
	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True, ondelete="cascade", index=True)
	state = fields.Selection(
		[("draft", "Preparada"), ("running", "En curso"), ("done", "Terminada"),
		 ("partial", "Terminada con errores"), ("error", "Fallida")],
		string="Estado", default="draft", required=True, tracking=True, index=True)
	started_at = fields.Datetime(string="Inicio", readonly=True)
	finished_at = fields.Datetime(string="Fin", readonly=True)

	repos_total = fields.Integer(string="Repos a recorrer", readonly=True)
	repos_done = fields.Integer(string="Recorridos", readonly=True)
	repos_error = fields.Integer(string="Con error", readonly=True)
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

	@api.depends("repos_total", "repos_done", "repos_error")
	def _compute_progress(self):
		for run in self:
			total = run.repos_total or 0
			run.progress = ((run.repos_done + run.repos_error) / total * 100) if total else 0.0

	# ------------------------------------------------------------------
	# Ciclo
	# ------------------------------------------------------------------

	def action_start(self):
		"""Encola el recorrido. No hace ninguna llamada HTTP en el hilo del usuario."""
		self.ensure_one()
		if self.backend_id.state != "connected":
			raise UserError(_(
				"La conexión «%s» no está verificada. Probá la conexión antes de auditar: "
				"una corrida con credenciales rotas gasta tiempo para terminar en error."
			) % self.backend_id.name)
		self.write({
			"state": "running", "started_at": fields.Datetime.now(),
			"repos_done": 0, "repos_error": 0, "error_detail": False,
		})
		self.with_delay(channel="root.repo_manager")._job_enumerate()
		self.message_post(body=_("Auditoría encolada."))
		return True

	def action_resume(self):
		"""Retoma una corrida cortada: sólo los repos que no cerraron bien."""
		self.ensure_one()
		pendientes = self.backend_id.repository_ids.filtered(
			lambda r: r.sync_state in ("pending", "running", "error"))
		if not pendientes:
			raise UserError(_("No quedan repositorios pendientes en esta corrida."))
		self.write({"state": "running", "error_detail": False})
		for repo in pendientes:
			repo.with_delay(channel="root.repo_manager")._job_sync_repository(self.id)
		self.message_post(body=_(
			"Reanudada: %s repositorio(s) pendientes encolados.") % len(pendientes))
		return True

	def _job_enumerate(self):
		"""Lista los repos de la cuenta y encola un job por cada uno."""
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
			raise

		self.repos_total = len(repos)
		repos.write({"sync_state": "pending"})
		for repo in repos:
			repo.with_delay(channel="root.repo_manager")._job_sync_repository(self.id)
		self.message_post(body=_("%s repositorio(s) encolados.") % len(repos))

	def _register_repo_done(self, con_error=False):
		"""Lo llama cada job de repo al terminar. Cierra la corrida cuando no queda nada."""
		self.ensure_one()
		if con_error:
			self.repos_error += 1
		else:
			self.repos_done += 1
		if (self.repos_done + self.repos_error) >= (self.repos_total or 0):
			self.write({
				"state": "partial" if self.repos_error else "done",
				"finished_at": fields.Datetime.now(),
			})
			self.backend_id.last_sync = fields.Datetime.now()
			# Los hallazgos se calculan al cerrar: recién ahí están todos los datos.
			self.env["repo.audit.engine"].evaluate(self)
			self.message_post(body=_(
				"Auditoría terminada: %(ok)s repositorio(s) recorridos, %(mal)s con error. "
				"%(hallazgos)s hallazgo(s)."
			) % {"ok": self.repos_done, "mal": self.repos_error,
				 "hallazgos": self.finding_count})

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
