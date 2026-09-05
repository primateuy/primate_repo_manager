# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Ramas relevantes de un repo. Las feature branches no se persisten: son efímeras y
serían ruido; de 503 ramas leídas, 84 caían en 'otras' y la mayoría son de trabajo."""
from odoo import fields, models

from .repo_rules import BRANCH_ROLES


class RepoBranch(models.Model):
	_name = "repo.branch"
	_description = "Rama de un repositorio"
	_order = "repository_id, name"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	name = fields.Char(string="Nombre", required=True)
	role = fields.Selection(BRANCH_ROLES, string="Rol", index=True)
	is_default = fields.Boolean(string="Es la rama por defecto")

	# Estado REAL en GitHub, no el declarado.
	protected = fields.Boolean(string="Protegida")
	protection_json = fields.Text(string="Protección (JSON crudo)")
	# La distinción que evita un informe mentiroso: leer la protección exige permiso de
	# admin, y sin él GitHub devuelve 404 —el mismo código que cuando no hay protección—.
	protection_readable = fields.Boolean(
		string="Protección legible", default=True,
		help="False cuando la API no dejó leerla. NO es lo mismo que 'no tiene protección': "
			 "el endpoint devuelve 404 en los dos casos y confundirlos arruina la auditoría.")
	protection_cause = fields.Selection(
		[("plan_limit", "Límite del plan de GitHub"),
		 ("no_admin_permission", "La App no tiene permiso de administrador"),
		 ("unknown", "Sin determinar")],
		string="Causa de la ilegibilidad",
		help="Sólo cuando `protection_readable` es falso. Se guarda como dato para que "
			 "los conteos separen lo que se resuelve con una decisión de plan de lo que "
			 "se resuelve reinstalando la App.")
	ruleset_count = fields.Integer(string="Rulesets que la alcanzan")

	last_commit_sha = fields.Char(string="Último commit")
	last_commit_date = fields.Datetime(string="Fecha del último commit")

	# Sólo para ramas espejo de forks.
	ahead_upstream = fields.Integer(string="Commits adelante del upstream")
	behind_upstream = fields.Integer(string="Commits detrás del upstream")
	comparison_readable = fields.Boolean(string="Comparación legible", default=True)

	# El árbol de git viene truncado en repositorios muy grandes. Se guarda como dato para
	# que el inventario de módulos pueda decir «acá no pude ver todo» en vez de dejar que
	# alguien lea el silencio como «no hay módulos».
	module_scan_truncated = fields.Boolean(
		string="Árbol truncado al escanear", copy=False)

	_branch_uniq = models.Constraint(
		"UNIQUE (repository_id, name)",
		"Esa rama ya está registrada en el repositorio.")
