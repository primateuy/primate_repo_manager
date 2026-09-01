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

	branch_count = fields.Integer(string="Ramas", compute="_compute_counts")
	collaborator_count = fields.Integer(string="Colaboradores", compute="_compute_counts")
	open_pr_count = fields.Integer(string="PRs abiertas", compute="_compute_counts")

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

	@api.depends("branch_ids", "collaborator_ids", "pull_request_ids")
	def _compute_counts(self):
		for repo in self:
			repo.branch_count = len(repo.branch_ids)
			repo.collaborator_count = len(repo.collaborator_ids)
			repo.open_pr_count = len(repo.pull_request_ids.filtered(
				lambda pr: pr.state == "open"))

	# ------------------------------------------------------------------
	# Clasificación
	# ------------------------------------------------------------------

	def _apply_classification(self, datos_repo):
		"""Clasifica por heurística, salvo que alguien la haya fijado a mano."""
		self.ensure_one()
		if self.classification_source == "manual":
			return self.classification
		clasificacion = self.env["repo.classification.rule"].classify(datos_repo)
		if clasificacion != self.classification:
			self.classification = clasificacion
		return clasificacion

	def action_set_classification_manual(self):
		"""Marca la clasificación como decidida por una persona, para que el sync la respete."""
		self.ensure_one()
		if not self.classification:
			return False
		self.classification_source = "manual"
		self.message_post(body=_(
			"Clasificación fijada a mano como «%s». Las auditorías ya no la van a cambiar."
		) % dict(self._fields["classification"].selection).get(self.classification))
		return True
