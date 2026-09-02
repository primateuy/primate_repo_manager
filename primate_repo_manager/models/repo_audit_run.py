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
