# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El repositorio como lo ve Odoo: espejo de lectura + clasificación."""
import logging

from odoo import _, api, fields, models

from .repo_rules import CLASSIFICATIONS

_logger = logging.getLogger(__name__)


class RepoRepository(models.Model):
	_name = "repo.repository"
	_description = "Repositorio git"
	_inherit = ["mail.thread"]
	_order = "full_name"

	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True, ondelete="cascade", index=True)
	github_id = fields.Char(
		string="ID en GitHub", required=True, index=True, copy=False,
		help="Identificador numérico estable. Es la clave del upsert: sobrevive a que "
			 "renombren el repo, cosa que el nombre no hace.")
	name = fields.Char(string="Nombre", required=True)
	full_name = fields.Char(string="Nombre completo", required=True, index=True)
	description = fields.Char(string="Descripción")
	visibility = fields.Selection(
		[("public", "Público"), ("private", "Privado")], string="Visibilidad")
	default_branch = fields.Char(string="Rama por defecto")
	archived = fields.Boolean(string="Archivado")
	pushed_at = fields.Datetime(string="Último push")

	is_fork = fields.Boolean(string="Es fork")
	upstream_full_name = fields.Char(
		string="Upstream", help="Sólo forks. Ej: OCA/partner-contact")
	governance_status = fields.Selection(
		[("pending_migration", "Pendiente de migración"), ("governed", "Gobernado")],
		string="Estado de gobernanza", default="pending_migration", tracking=True,
		help="Sólo relevante en forks. La plantilla `fork-upstream` describe el patrón "
			 "espejo+parches; los forks actuales son forks normales, sin esa estructura. "
			 "Evaluarlos contra el detalle de la plantilla produciría cientos de hallazgos "
			 "que no son incumplimiento sino 'todavía no migrado'. Mientras esté pendiente "
			 "se emite UN hallazgo agregado; al marcarlo gobernado se evalúa completo.")

	classification = fields.Selection(
		CLASSIFICATIONS, string="Clasificación", tracking=True,
		help="Determina contra qué plantilla de política se compara en la auditoría.")
	classification_source = fields.Selection(
		[("auto", "Heurística"), ("manual", "Definida a mano")],
		string="Origen de la clasificación", default="auto", tracking=True,
		help="Una auditoría NUNCA pisa una clasificación manual: si lo hiciera, corregir "
			 "un repo a mano y ver cómo se revierte solo sería la forma más rápida de "
			 "perderle la confianza a la herramienta.")

	branch_ids = fields.One2many("repo.branch", "repository_id", string="Ramas")
	collaborator_ids = fields.One2many(
		"repo.collaborator", "repository_id", string="Colaboradores")
	pull_request_ids = fields.One2many(
		"repo.pull.request", "repository_id", string="Pull requests")
	commit_sample_ids = fields.One2many(
		"repo.commit.sample", "repository_id", string="Muestra de commits")
	workflow_ids = fields.One2many(
		"repo.workflow", "repository_id", string="Workflows de CI")

	# El vínculo existía en un solo sentido: el hallazgo apuntaba al repositorio y desde
	# el repositorio no se podía llegar a sus hallazgos. Sin esto, «abrir un repositorio y
	# ver qué se le encontró» —que es la pregunta que uno se hace parado en el
	# repositorio— obligaba a ir a la lista de hallazgos y filtrar a mano.
	finding_ids = fields.One2many(
		"repo.audit.finding", "repository_id", string="Hallazgos")

	branch_count = fields.Integer(string="Ramas", compute="_compute_counts")
	collaborator_count = fields.Integer(string="Colaboradores", compute="_compute_counts")
	open_pr_count = fields.Integer(string="PRs abiertas", compute="_compute_counts")
	finding_count = fields.Integer(
		string="Hallazgos abiertos", compute="_compute_counts",
		help="Los de la última corrida que miró este repositorio. Los de corridas "
			 "anteriores siguen guardados y se ven quitando el filtro.")
	last_run_id = fields.Many2one(
		"repo.audit.run", string="Última corrida", compute="_compute_counts",
		help="La corrida más reciente que produjo hallazgos sobre este repositorio.")

	# --- estado de la sincronización, que es lo que hace reanudable la auditoría ---
	sync_state = fields.Selection(
		[("pending", "Pendiente"), ("running", "En curso"),
		 ("done", "Sincronizado"), ("error", "Error")],
		string="Estado de sync", default="pending", index=True, copy=False)
	last_synced_at = fields.Datetime(string="Última sincronización", copy=False)
	sync_error = fields.Text(string="Error de sincronización", copy=False)
	# Lo que NO se pudo leer por permisos. Distinguirlo de "no existe" es central para
	# que el informe no afirme "sin protección" cuando en realidad era "sin permiso".
	unreadable_json = fields.Text(string="No legible (JSON)", copy=False)

	_github_id_uniq = models.Constraint(
		"UNIQUE (backend_id, github_id)",
		"Ese repositorio ya está registrado en esta conexión.")

	@api.depends("branch_ids", "collaborator_ids", "pull_request_ids", "finding_ids")
	def _compute_counts(self):
		for repo in self:
			repo.branch_count = len(repo.branch_ids)
			repo.collaborator_count = len(repo.collaborator_ids)
			repo.open_pr_count = len(repo.pull_request_ids.filtered(
				lambda pr: pr.state == "open"))
			# El conteo que se muestra es el de la ÚLTIMA corrida, no el histórico. Un
			# número que suma seis auditorías del mismo problema no dice cuántos problemas
			# hay: dice cuántas veces se miró. Los viejos no se borran ni se esconden —se
			# llega a ellos quitando el filtro— pero no son los que uno cuenta.
			ultima = max(repo.finding_ids.mapped("run_id"),
						 key=lambda r: r.id, default=repo.env["repo.audit.run"])
			repo.last_run_id = ultima
			repo.finding_count = len(repo.finding_ids.filtered(
				lambda f: f.run_id == ultima)) if ultima else 0

	# ------------------------------------------------------------------
	# Navegación
	# ------------------------------------------------------------------

	def action_open_findings(self):
		"""Los hallazgos de este repositorio, con la última corrida ya filtrada.

		El filtro viene puesto y NO cableado en el dominio: se ve en la barra de búsqueda
		y se saca con un click. Un dominio fijo escondería el historial sin decirlo, que
		es la clase de recorte que después hace dudar de los números.
		"""
		self.ensure_one()
		accion = self.env["ir.actions.actions"]._for_xml_id(
			"primate_repo_manager.action_repo_audit_finding")
		accion["domain"] = [("repository_id", "=", self.id)]
		# SIN agrupar, a diferencia de la lista general. Un repositorio tiene un puñado de
		# hallazgos: agruparlos por severidad los esconde detrás de un click y no ordena
		# nada. Agrupar sirve cuando hay cientos, que es el caso del menú de Hallazgos.
		accion["context"] = {}
		if self.last_run_id:
			accion["context"]["search_default_run_id"] = self.last_run_id.id
		accion["display_name"] = _("Hallazgos de %s") % self.full_name
		return accion

	# ------------------------------------------------------------------
	# Clasificación
	# ------------------------------------------------------------------

	# La bandera con la que la heurística se identifica al escribir. Ver `write`.
	SIN_MANO = "repo_clasificacion_automatica"

	def _apply_classification(self, datos_repo):
		"""Clasifica por heurística, salvo que alguien la haya fijado a mano."""
		self.ensure_one()
		if self.classification_source == "manual":
			return self.classification
		clasificacion = self.env["repo.classification.rule"].classify(datos_repo)
		if clasificacion != self.classification:
			# La bandera dice «esto no lo decidió una persona». Sin ella, `write` marcaría
			# la clasificación como manual y la heurística se congelaría a sí misma en la
			# primera corrida.
			self.with_context(**{self.SIN_MANO: True}).classification = clasificacion
		return clasificacion

	def write(self, vals):
		"""Editar la clasificación A MANO marca el origen como manual. Sin botón aparte.

		POR QUÉ NO ALCANZABA CON `action_set_classification_manual`. El método existía y
		hacía lo correcto, pero nadie lo llamaba desde un formulario: se podía cambiar la
		clasificación, guardar, y el origen quedaba en «heurística». La siguiente auditoría
		la pisaba en silencio. Es exactamente lo que el `help` del campo promete que no
		pasa —«corregir un repo a mano y ver cómo se revierte solo sería la forma más
		rápida de perderle la confianza a la herramienta»— y con 43 repositorios para
		clasificar a mano, se habría descubierto con los 43 ya perdidos.

		Editar el campo ES el acto manual. Pedir además que alguien se acuerde de apretar
		un botón no es una salvaguarda: es una trampa que se cobra callada.

		EL DEFAULT ES «LO HIZO UNA PERSONA», y la máquina tiene que decir que no.
		Al revés —marcar manual sólo cuando alguien avisa— el olvido de un desarrollador
		futuro se paga con una clasificación pisada. Así, el olvido se paga con una
		clasificación que la auditoría respeta de más: molesto, visible y reversible.
		"""
		if "classification" in vals and not self.env.context.get(self.SIN_MANO):
			vals = dict(vals, classification_source="manual")
		return super().write(vals)

	def action_set_classification_manual(self):
		"""Marca la clasificación como decidida por una persona, para que el sync la respete.

		Queda para quien quiera fijar una clasificación que la heurística ya había acertado
		—el valor no cambia, así que `write` no se entera— y para las acciones por lote.
		"""
		self.ensure_one()
		if not self.classification:
			return False
		self.classification_source = "manual"
		return True
