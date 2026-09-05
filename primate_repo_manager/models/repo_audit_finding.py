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
from odoo.exceptions import UserError

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
	("audit_log_chain_broken", "La cadena de la bitácora está rota"),
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
	"audit_log_chain_broken": "critical",
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
	# El módulo auditándose a sí mismo: si la cadena de la bitácora está rota, alguien
	# escribió en la base por fuera de la aplicación. No hay hallazgo más grave que ése,
	# porque pone en duda todo lo demás que la bitácora afirma.
	"audit_log_chain_broken": "review_manually",
}

# Las que quitan acceso o cambian algo que puede romper el trabajo de otro.
DESTRUCTIVE_ACTIONS = ("revoke_permission", "rename_default_branch")

# QUÉ ACCIONES SE PUEDEN CONVERTIR EN UNA OPERACIÓN DE PLAN, Y CUÁLES NO.
#
# Sale de mirar el catálogo completo: de las dieciséis acciones de remediación, sólo dos
# son escrituras a GitHub que el módulo sepa armar hoy. Las demás se resuelven en otro
# lado —en Odoo, en la cuenta de una persona, en la consola de GitHub, o en una fase que
# todavía no existe— y ofrecer «Remediar esto» sobre ellas sería un botón que promete algo
# que no puede cumplir.
#
# La lista es explícita y no una heurística: agregar un tipo de operación nuevo obliga a
# venir acá y decidir, en vez de que el botón aparezca solo el día que alguien amplíe
# `OPERATION_KINDS` sin pensar en esto.
# LA LECCIÓN QUE ESTE CATÁLOGO APRENDIÓ A LOS GOLPES:
# **`remediation_payload` IDENTIFICA, NO CONFIGURA.**
#
# Lo generó F1 como «sobre qué hay que actuar»: para una rama sin proteger dice
# `{"repository": "org/repo", "branch": "17.0"}`. A4.1 lo copió tal cual como payload
# ejecutable de la operación, y el resultado fue que GitHub recibió eso como cuerpo de la
# protección, ignoró las claves que no conoce y aplicó una protección con todo en default
# —sin PR, sin revisiones— que nadie había diseñado. La verificación por relectura la
# rechazó, con razón, pero la escritura ya había salido.
#
# Antes de agregar una acción acá hay que comprobar que su payload sea EJECUTABLE para el
# tipo de operación de destino, no sólo que exista.
PLANIFICABLES = {
	"revoke_permission": "collaborator_revoke",
}

# Por qué NO se puede planificar cada una de las otras. Se muestra en pantalla: un botón
# ausente sin explicación se lee como un olvido del producto.
POR_QUE_NO_PLANIFICABLE = {
	"apply_ruleset": (
		"La configuración de protección sale de la plantilla de política del repositorio "
		"—cuántas aprobaciones, si exige revisión de owner, si bloquea force-push—, no del "
		"hallazgo. Llega con la aplicación de política por plantilla (B1). Hasta entonces "
		"se arma a mano desde el asistente del plan, eligiendo la rama y las casillas."),
	"set_classification": (
		"Se resuelve en Odoo, en el propio repositorio: campo «Clasificación»."),
	"link_employee": (
		"Se resuelve en Odoo, en «Personas»: el botón «¿Quién es?» de esa cuenta."),
	"define_required_checks": (
		"Ninguna plantilla define checks requeridos todavía. Es el ítem B3."),
	"sync_fork": "Sincronizar forks es la fase de forks (bloque C).",
	"migrate_fork": (
		"Migrar un fork al patrón espejo+parches es la fase de forks (bloque C). "
		"Mientras tanto se marca «Gobernado» a mano en el repositorio."),
	"reinstall_app": (
		"Se resuelve en GitHub, reinstalando la App con una cuenta que tenga admin. "
		"Ningún token puede darse a sí mismo un permiso que no tiene."),
	"check_app_access": "Se resuelve en GitHub, revisando el alcance de la instalación.",
	"upgrade_plan": (
		"Es una decisión de plan de GitHub, con costo. No hay nada que aplicar."),
	"configure_signing": (
		"Lo configura cada persona en su propia cuenta de GitHub. El módulo lo verifica, "
		"no lo puede hacer por ella."),
	"enforce_commit_convention": (
		"Los mensajes ya escritos no se cambian sin reescribir la historia. Lo que sí se "
		"puede es exigir la convención de acá en adelante, que es una protección de rama."),
	"rename_default_branch": (
		"Renombrar la rama por defecto rompe los clones de todo el mundo y las URLs "
		"guardadas. Se hace a mano y avisando, no desde un plan."),
	"create_version_branch": (
		"Crear ramas todavía no es un tipo de operación del plan."),
	"review_manually": "No hay una acción automática: hay que mirarlo.",
	"no_action_owner": "No requiere acción.",
}

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

	# --- A4.1: de un hallazgo a una operación de plan ---------------------

	operation_ids = fields.One2many(
		"repo.write.operation", "finding_id", string="Operaciones planificadas")
	planned_operation_id = fields.Many2one(
		"repo.write.operation", string="Ya planificado en",
		compute="_compute_planificacion",
		help="La operación VIVA que remedia este hallazgo, si ya hay una.")
	planned_plan_id = fields.Many2one(
		"repo.write.plan", string="Plan", compute="_compute_planificacion")
	can_be_planned = fields.Boolean(
		string="Se puede remediar con un plan", compute="_compute_planificacion")
	why_not_planned = fields.Char(
		string="Dónde se resuelve", compute="_compute_planificacion")

	@api.depends("operation_ids.state", "operation_ids.plan_id.state",
				 "remediation_action")
	def _compute_planificacion(self):
		"""Qué se puede hacer con este hallazgo, y si ya se hizo.

		«Viva» es una operación pendiente en un plan que todavía no se ejecutó. Una ya
		aplicada no cuenta: si el hallazgo volvió a aparecer en una auditoría posterior,
		hay que poder planificarlo de nuevo.
		"""
		for hallazgo in self:
			viva = hallazgo.operation_ids.filtered(
				lambda o: o.state == "pending"
				and o.plan_id.state in ("draft", "approved"))[:1]
			hallazgo.planned_operation_id = viva
			hallazgo.planned_plan_id = viva.plan_id
			accion = hallazgo.remediation_action
			hallazgo.can_be_planned = accion in PLANIFICABLES
			hallazgo.why_not_planned = (
				False if hallazgo.can_be_planned
				else POR_QUE_NO_PLANIFICABLE.get(accion, ""))

	@api.depends("severity")
	def _compute_severity_order(self):
		for hallazgo in self:
			hallazgo.severity_order = SEVERITY_ORDER.get(hallazgo.severity, 9)
			hallazgo.severity_rank = RANK_BY_SEVERITY.get(hallazgo.severity, False)

	# ------------------------------------------------------------------
	# Remediar: armar la operación. NADA se escribe en GitHub desde acá.
	# ------------------------------------------------------------------

	def action_remediate(self):
		"""Arma la operación de plan de este hallazgo y lleva al plan.

		LO QUE ESTE BOTÓN NO HACE, Y ES LO IMPORTANTE: no escribe en GitHub. Arma una
		operación en un plan en borrador y termina. Después hace falta aprobar —con
		confirmación individual de cada destructiva— y recién ahí aplicar. La tentación de
		que «remediar» remedie de una es fuerte y es exactamente la que saltearía las tres
		guardas de F2.
		"""
		self.ensure_one()
		if self.planned_operation_id:
			# Ya está planificado: se lleva ahí en vez de crear la misma operación otra
			# vez. Es el caso del doble clic y el de dos personas mirando la misma lista.
			return self._ir_al_plan(_(
				"Este hallazgo ya está en el plan «%s», pendiente de aplicar."
			) % self.planned_plan_id.display_name)
		if not self.can_be_planned:
			raise UserError(_(
				"Este hallazgo no se remedia con un plan de escritura.\n\n%s"
			) % (self.why_not_planned or _("No hay una acción automática.")))

		plan = self._plan_destino()
		self.env["repo.write.operation"].create(self._valores_de_operacion(plan))
		return self._ir_al_plan(_(
			"Operación agregada al plan «%s». Todavía no se aplicó nada: falta aprobarlo."
		) % plan.display_name)

	def _plan_destino(self):
		"""El borrador abierto de esa conexión, o uno nuevo si no hay.

		Acumular es lo que evita veinte planes de una operación y veinte aprobaciones. Se
		elige el borrador MÁS RECIENTE si hubiera varios, que es el que alguien está
		armando ahora.
		"""
		self.ensure_one()
		backend = self.run_id.backend_id
		plan = self.env["repo.write.plan"].search(
			[("backend_id", "=", backend.id), ("state", "=", "draft")],
			order="id desc", limit=1)
		if plan:
			return plan
		return self.env["repo.write.plan"].create({
			"name": _("Remediaciones de %s") % backend.name,
			"backend_id": backend.id,
		})

	def _valores_de_operacion(self, plan):
		"""Traduce el hallazgo a los campos de la operación."""
		self.ensure_one()
		payload = self.remediation_payload
		if not payload:
			raise UserError(_(
				"El hallazgo no trae el detalle de la remediación, así que no hay con qué "
				"armar la operación. Es un problema del motor de auditoría, no algo que "
				"se resuelva desde acá."))
		siguiente = max(plan.operation_ids.mapped("sequence") or [0]) + 10
		return {
			"plan_id": plan.id,
			"kind": PLANIFICABLES[self.remediation_action],
			"repository_id": self.repository_id.id,
			"target": self.subject or "",
			"payload_json": payload,
			"finding_id": self.id,
			"sequence": siguiente,
		}

	def _ir_al_plan(self, mensaje):
		self.ensure_one()
		plan = self.planned_plan_id
		return {
			"type": "ir.actions.act_window",
			"name": plan.display_name,
			"res_model": "repo.write.plan",
			"res_id": plan.id,
			"view_mode": "form",
			"context": dict(self.env.context, prm_aviso=mensaje),
		}

	def action_remediate_many(self):
		"""Varios hallazgos de una. Veinte ramas sin proteger son UN plan, no veinte.

		Los que ya están planificados y los que no se planifican no cortan el lote: se
		saltean y se cuentan. Un botón que se niega entero porque uno de veinte no
		aplicaba obliga a seleccionar de a uno, que es justamente lo que este botón viene
		a evitar.
		"""
		agregados = self.env["repo.write.operation"]
		ya_estaban = self.browse()
		sin_camino = self.browse()
		plan = False
		for hallazgo in self:
			if hallazgo.planned_operation_id:
				ya_estaban |= hallazgo
				continue
			if not hallazgo.can_be_planned or not hallazgo.remediation_payload:
				sin_camino |= hallazgo
				continue
			plan = plan or hallazgo._plan_destino()
			agregados |= self.env["repo.write.operation"].create(
				hallazgo._valores_de_operacion(plan))
		if not agregados:
			raise UserError(_(
				"No se agregó ninguna operación.\n\n"
				"· %(ya)s ya estaban en un plan.\n"
				"· %(no)s no se remedian con un plan de escritura."
			) % {"ya": len(ya_estaban), "no": len(sin_camino)})
		accion = self.env["ir.actions.actions"]._for_xml_id(
			"primate_repo_manager.action_repo_write_plan")
		accion.update({
			"res_id": plan.id, "view_mode": "form",
			"views": [(False, "form")],
		})
		return accion

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
