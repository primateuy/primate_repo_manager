# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Hallazgos de la auditoría.

Cada hallazgo lleva, además de qué está mal, **cómo se arreglaría**: `remediation_action`
y `remediation_payload` describen la acción concreta que lo resolvería. En Fase 1 se
calculan y no se ejecutan nunca. Es la base del plan/apply de F2/F3: la auditoría detecta,
el plan propone acciones tipadas, y recién con aprobación explícita se aplican.

`is_destructive` marca las que quitan acceso o borran algo. Esas nunca entran en una
aprobación por lote: van de a una, a mano.
"""
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

SEVERITIES = [
	("critical", "Crítico"),
	("high", "Alto"),
	("medium", "Medio"),
	("info", "Informativo"),
]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}

# LA MISMA SEVERIDAD, CON VALORES QUE ORDENAN SOLOS. Existe por una razón de pantalla y
# no de modelo: al agrupar por un campo de selección, Odoo ordena los grupos por el VALOR
# guardado, alfabéticamente, y no por el orden en que la selección está declarada. Con los
# valores naturales eso deja «Informativo» arriba de «Medio» —critical, high, info,
# medium— en una lista cuyo único propósito es triaje. El prefijo numérico es interno;
# en pantalla se lee la misma palabra de siempre.
SEVERITY_RANKS = [
	("1_critical", "Crítico"),
	("2_high", "Alto"),
	("3_medium", "Medio"),
	("4_info", "Informativo"),
]
RANK_BY_SEVERITY = {
	"critical": "1_critical", "high": "2_high", "medium": "3_medium", "info": "4_info",
}

# Severidad BASE por tipo. Los moduladores la ajustan según plantilla y magnitud; sus
# umbrales son configurables (ver res.config.settings), la lógica vive acá y está testeada.
FINDING_TYPES = [
	("mirror_branch_drift", "Push en rama espejo"),
	("permission_admin_exceeded", "Permiso de administrador excedido"),
	("permission_exceeded", "Permiso excedido"),
	("branch_unprotected", "Rama sin protección"),
	("repo_sync_error", "Repositorio no auditado"),
	("signed_commits_missing", "Commits sin firmar donde se exige firma"),
	("branch_protection_unreadable", "Protección no legible"),
	("commit_format_violations", "Mensajes de commit fuera de convención"),
	("classification_missing", "Repositorio sin clasificar"),
	("fork_behind_upstream", "Fork atrasado respecto del upstream"),
	("pr_stale", "Pull request estancada"),
	("member_without_employee", "Cuenta de GitHub sin persona asociada"),
	("default_branch_off_convention", "Rama por defecto fuera de convención"),
	("version_branch_missing", "Sin rama de la versión esperada"),
	("fork_not_migrated", "Fork sin migrar al patrón espejo+parches"),
	("checks_not_evaluable", "Checks requeridos sin definir"),
	("convention_adoption", "Adopción de convenciones"),
	# La cuenta DUEÑA de los repositorios no se mide con la matriz de acceso: su admin es
	# inherente a la propiedad y no se puede bajar. El dato igual se conserva, como nota.
	("owner_account_admin", "La cuenta dueña figura como colaboradora"),
	("institutional_account", "Cuenta institucional sin persona asociada"),
]

BASE_SEVERITY = {
	"mirror_branch_drift": "critical",
	"permission_admin_exceeded": "critical",
	"permission_exceeded": "high",
	"branch_unprotected": "high",
	"repo_sync_error": "high",
	"signed_commits_missing": "high",
	"branch_protection_unreadable": "medium",
	"commit_format_violations": "medium",
	"classification_missing": "medium",
	"fork_behind_upstream": "medium",
	"pr_stale": "medium",
	"member_without_employee": "medium",
	"default_branch_off_convention": "medium",
	"version_branch_missing": "medium",
	"fork_not_migrated": "info",
	"checks_not_evaluable": "info",
	"convention_adoption": "info",
	"owner_account_admin": "info",
	"institutional_account": "info",
}

# Acción de remediación que resolvería cada tipo. Se calcula en F1, se ejecuta en F2/F3.
REMEDIATION_ACTIONS = [
	("apply_ruleset", "Aplicar ruleset de la plantilla"),
	("revoke_permission", "Revocar o bajar el permiso"),
	("set_classification", "Clasificar el repositorio"),
	("sync_fork", "Sincronizar el fork con su upstream"),
	("migrate_fork", "Migrar el fork al patrón espejo+parches"),
	("link_employee", "Vincular la cuenta con un empleado"),
	("rename_default_branch", "Cambiar la rama por defecto"),
	("create_version_branch", "Crear la rama de versión"),
	("reinstall_app", "Reinstalar la App con una cuenta con admin"),
	("upgrade_plan", "Requiere decisión de plan de GitHub"),
	("define_required_checks", "Definir los checks requeridos"),
	("enforce_commit_convention", "Corregir la convención de mensajes de commit"),
	("configure_signing", "Configurar la firma de commits del equipo"),
	("check_app_access", "Revisar el acceso de la App al repositorio"),
	("review_manually", "Revisar a mano"),
	("no_action_owner", "No requiere acción: es la cuenta dueña"),
]

REMEDIATION_BY_TYPE = {
	"mirror_branch_drift": "review_manually",
	"permission_admin_exceeded": "revoke_permission",
	"permission_exceeded": "revoke_permission",
	"branch_unprotected": "apply_ruleset",
	"repo_sync_error": "check_app_access",
	"signed_commits_missing": "configure_signing",
	"commit_format_violations": "enforce_commit_convention",
	"classification_missing": "set_classification",
	"fork_behind_upstream": "sync_fork",
	"pr_stale": "review_manually",
	"member_without_employee": "link_employee",
	"default_branch_off_convention": "rename_default_branch",
	"version_branch_missing": "create_version_branch",
	"fork_not_migrated": "migrate_fork",
	"checks_not_evaluable": "define_required_checks",
	"convention_adoption": "review_manually",
	"owner_account_admin": "no_action_owner",
	"institutional_account": "no_action_owner",
}

# Las que quitan acceso o cambian algo que puede romper el trabajo de otro.
DESTRUCTIVE_ACTIONS = ("revoke_permission", "rename_default_branch")

UNREADABLE_CAUSES = [
	("plan_limit", "Límite del plan de GitHub"),
	("no_admin_permission", "La App no tiene permiso de administrador"),
	("unknown", "Sin determinar"),
]


class RepoAuditFinding(models.Model):
	_name = "repo.audit.finding"
	_description = "Hallazgo de auditoría"
	_order = "severity_order, finding_type, id"

	run_id = fields.Many2one(
		"repo.audit.run", string="Corrida", required=True, ondelete="cascade", index=True)
	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", ondelete="cascade", index=True,
		help="Vacío en los hallazgos a nivel cuenta, como la adopción de convenciones.")
	finding_type = fields.Selection(
		FINDING_TYPES, string="Tipo", required=True, index=True)
	severity = fields.Selection(
		SEVERITIES, string="Severidad", required=True, index=True)
	severity_order = fields.Integer(
		string="Orden", compute="_compute_severity_order", store=True)
	severity_rank = fields.Selection(
		SEVERITY_RANKS, string="Severidad (agrupada)",
		compute="_compute_severity_order", store=True, index=True,
		help="La misma severidad, con valores que ordenan bien al agrupar. Ver el "
			 "comentario de SEVERITY_RANKS.")
	severity_modulated = fields.Boolean(
		string="Severidad ajustada",
		help="Verdadero cuando un modulador la movió de su valor base. El informe lo "
			 "aclara para que el mismo tipo en dos severidades no parezca un error.")

	subject = fields.Char(
		string="Sujeto", help="Rama, persona o PR concreta a la que apunta el hallazgo.")
	summary = fields.Char(string="Resumen", required=True)
	detail = fields.Text(string="Detalle")

	expected_json = fields.Text(string="Esperado (JSON)")
	observed_json = fields.Text(string="Observado (JSON)")

	# --- causa, para los que no se pudieron evaluar ---
	unreadable_cause = fields.Selection(
		UNREADABLE_CAUSES, string="Causa",
		help="Por qué no se pudo leer. Se guarda como dato y no sólo como texto para que "
			 "los filtros y los conteos distingan un techo de plan —que se resuelve con "
			 "una decisión de plan— de una App instalada sin permisos, que se resuelve "
			 "reinstalándola.")

	# --- remediación futura: se calcula, nunca se ejecuta en F1 ---
	remediation_action = fields.Selection(
		REMEDIATION_ACTIONS, string="Acción de remediación")
	remediation_payload = fields.Text(string="Payload de la acción (JSON)")
	is_destructive = fields.Boolean(
		string="Destructiva",
		help="Quita acceso o cambia algo que puede romper el trabajo de otro. Nunca entra "
			 "en una aprobación por lote.")

	@api.depends("severity")
	def _compute_severity_order(self):
		for hallazgo in self:
			hallazgo.severity_order = SEVERITY_ORDER.get(hallazgo.severity, 9)
			hallazgo.severity_rank = RANK_BY_SEVERITY.get(hallazgo.severity, False)

	@api.model
	def build(self, run, finding_type, summary, repository=None, **kwargs):
		"""Crea un hallazgo con su severidad, remediación y flags ya resueltos."""
		accion = REMEDIATION_BY_TYPE.get(finding_type)
		valores = {
			"run_id": run.id,
			"repository_id": repository.id if repository else False,
			"finding_type": finding_type,
			"severity": kwargs.pop("severity", None) or BASE_SEVERITY.get(finding_type, "info"),
			"summary": summary,
			"remediation_action": kwargs.pop("remediation_action", None) or accion,
			"is_destructive": accion in DESTRUCTIVE_ACTIONS,
		}
		for clave in ("subject", "detail", "unreadable_cause", "severity_modulated"):
			if clave in kwargs:
				valores[clave] = kwargs.pop(clave)
		for clave in ("expected", "observed", "remediation_payload"):
			if clave in kwargs:
				destino = clave if clave == "remediation_payload" else "%s_json" % clave
				valores[destino] = json.dumps(kwargs.pop(clave), ensure_ascii=False, default=str)
		if kwargs:
			_logger.warning("Repo Manager: claves ignoradas al crear hallazgo: %s", list(kwargs))
		return self.create(valores)

	def _remediation_label(self):
		"""Cómo se resuelve, en una frase corta y sin jerga."""
		self.ensure_one()
		frases = {
			"apply_ruleset": _("Aplicar las reglas de protección de la plantilla."),
			"revoke_permission": _("Bajar el permiso de esa persona."),
			"set_classification": _("Definir de qué tipo es el repositorio."),
			"sync_fork": _("Sincronizar el fork con el proyecto original."),
			"migrate_fork": _("Migrarlo al esquema de espejo y parches."),
			"link_employee": _("Asociar la cuenta de GitHub con la persona."),
			"rename_default_branch": _("Cambiar la rama por defecto."),
			"create_version_branch": _("Crear la rama de la versión."),
			"reinstall_app": _("Reinstalar la aplicación con permisos de administrador."),
			"upgrade_plan": _("Requiere una decisión sobre el plan de GitHub."),
			"define_required_checks": _("Definir qué controles de CI son obligatorios."),
			"enforce_commit_convention": _(
				"Corregir la convención de mensajes de commit del equipo."),
			"configure_signing": _(
				"Configurar la firma de commits en las cuentas del equipo."),
			"check_app_access": _(
				"Revisar los permisos de la aplicación sobre este repositorio."),
			"review_manually": _("Revisar a mano."),
		}
		return frases.get(self.remediation_action, "")
