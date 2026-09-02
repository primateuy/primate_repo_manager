# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El motor que compara lo observado contra lo declarado y produce hallazgos.

Nada de esto escribe en GitHub: lee los modelos del espejo, los compara con las plantillas
y crea `repo.audit.finding`. La remediación se calcula y se guarda; ejecutarla es F2/F3.

Los MODULADORES de severidad viven acá, con sus umbrales leídos de configuración. La
lógica es código testeado; los números son criterio y el criterio cambia.
"""
import logging

from odoo import _, api, fields, models

from .repo_audit_finding import BASE_SEVERITY
from .repo_collaborator import PERMISSION_LEVELS
from .res_config_settings import DEFAULTS, ResConfigSettings

_logger = logging.getLogger(__name__)


class RepoAuditEngine(models.AbstractModel):
	_name = "repo.audit.engine"
	_description = "Evaluación de hallazgos de auditoría"

	# ------------------------------------------------------------------
	# Entrada
	# ------------------------------------------------------------------

	@api.model
	def evaluate(self, run):
		"""Recalcula TODOS los hallazgos de una corrida. Idempotente: borra y rehace."""
		run.finding_ids.unlink()
		repos = run.backend_id.repository_ids.filtered(lambda r: not r.archived)

		for repo in repos:
			if repo.sync_state == "error":
				# Un repo que no se pudo auditar es un hallazgo, no una nota al pie: si no,
				# el informe afirma sobre 94 repos habiendo mirado 91.
				self._finding(run, repo, "repo_sync_error",
							  _("No se pudo auditar «%s»") % repo.full_name,
							  detail=repo.sync_error)
				continue
			self._evaluate_repository(run, repo)

		self._evaluate_account(run, repos)
		self._evaluate_members(run)
		self._evaluate_templates(run, repos)
		return run.finding_ids

	# ------------------------------------------------------------------
	# Por repositorio
	# ------------------------------------------------------------------

	@api.model
	def _evaluado_contra_plantilla(self, repo):
		"""¿Este repo se compara ítem por ítem contra una plantilla?

		Es el mismo criterio que aplica `_evaluate_repository` con sus dos salidas
		tempranas, en un solo lugar: si el conteo del resumen usa otra definición que la
		que genera los hallazgos, el informe se contradice a sí mismo.
		"""
		if not repo.classification:
			return False
		if repo.is_fork and repo.governance_status == "pending_migration":
			return False
		return bool(self.env["repo.policy.template"].search(
			[("classification_default", "=", repo.classification)], limit=1))

	@api.model
	def _evaluate_repository(self, run, repo):
		if not repo.classification:
			self._finding(run, repo, "classification_missing",
						  _("«%s» no coincide con ninguna regla de clasificación")
						  % repo.full_name)
			# Sin clasificación no hay plantilla contra la cual comparar el resto.
			return

		plantilla = self.env["repo.policy.template"].search(
			[("classification_default", "=", repo.classification)], limit=1)
		if not plantilla:
			return

		# Un fork sin migrar se resume en UN hallazgo: compararlo ítem por ítem contra el
		# patrón espejo+parches daría cientos de líneas de trabajo no hecho, no de
		# incumplimiento.
		if repo.is_fork and repo.governance_status == "pending_migration":
			self._finding(run, repo, "fork_not_migrated",
						  _("«%s» es un fork sin estructura espejo+parches")
						  % repo.full_name,
						  detail=_("No se evalúa contra el detalle de la plantilla hasta "
								   "marcarlo como gobernado."),
						  remediation_payload={"upstream": repo.upstream_full_name})
			self._evaluate_fork_drift(run, repo)
			return

		self._evaluate_permissions(run, repo, plantilla)
		self._evaluate_branches(run, repo, plantilla)
		self._evaluate_commits(run, repo, plantilla)
		self._evaluate_pull_requests(run, repo)
		self._evaluate_fork_drift(run, repo)


	@api.model
	def _evaluate_permissions(self, run, repo, plantilla):
		owner = (repo.backend_id.owner_login or "").lower()
		for colaborador in repo.collaborator_ids:
			if owner and (colaborador.member_id.github_login or "").lower() == owner:
				# La matriz de acceso NO aplica a la cuenta dueña. Su admin es inherente a
				# la propiedad del repositorio: no se puede bajar, y pedirlo como acción
				# crítica manda al lector a hacer algo que GitHub no permite. El dato de
				# que figura además como colaboradora explícita sí se conserva, como nota.
				self._finding(
					run, repo, "owner_account_admin",
					_("«%(persona)s» es la cuenta dueña y figura como colaboradora con "
					  "%(tiene)s en «%(repo)s»") % {
						"persona": colaborador.member_id.github_login,
						"tiene": colaborador.permission, "repo": repo.full_name},
					subject=colaborador.member_id.github_login,
					detail=_("No es un exceso de permiso: la cuenta dueña administra sus "
							 "repositorios por definición. Se lista para que el inventario "
							 "de accesos esté completo."),
					observed={"permission": colaborador.permission, "owner": True})
				continue
			maximo = plantilla.max_permission_for(colaborador.member_id)
			if self._nivel(colaborador.permission) <= self._nivel(maximo):
				continue
			tipo = ("permission_admin_exceeded" if colaborador.permission == "admin"
					else "permission_exceeded")
			self._finding(
				run, repo, tipo,
				_("%(persona)s tiene %(tiene)s en «%(repo)s»; el máximo es %(max)s") % {
					"persona": colaborador.member_id.github_login,
					"tiene": colaborador.permission, "repo": repo.full_name, "max": maximo},
				subject=colaborador.member_id.github_login,
				expected={"max_permission": maximo},
				observed={"permission": colaborador.permission},
				remediation_payload={
					"repository": repo.full_name,
					"login": colaborador.member_id.github_login,
					"from": colaborador.permission, "to": maximo,
				})

	@api.model
	def _evaluate_branches(self, run, repo, plantilla):
		for rama in repo.branch_ids:
			regla = plantilla.rule_for_role(rama.role)
			protegible = regla.get("require_pr") or regla.get("block_force_push")

			if not rama.protection_readable:
				causa = rama.protection_cause or "unknown"
				self._finding(
					run, repo, "branch_protection_unreadable",
					_("No se pudo leer la protección de «%(rama)s» en «%(repo)s»") % {
						"rama": rama.name, "repo": repo.full_name},
					subject=rama.name, unreadable_cause=causa,
					remediation_action=("upgrade_plan" if causa == "plan_limit"
										else "reinstall_app"))
				continue

			if protegible and not rama.protected:
				severidad, modulada = self._severidad_rama(repo)
				self._finding(
					run, repo, "branch_unprotected",
					_("«%(rama)s» de «%(repo)s» no tiene protección") % {
						"rama": rama.name, "repo": repo.full_name},
					subject=rama.name, severity=severidad, severity_modulated=modulada,
					expected=regla, observed={"protected": False},
					remediation_payload={"repository": repo.full_name, "branch": rama.name})

			if rama.role == "mirror" and rama.ahead_upstream:
				self._finding(
					run, repo, "mirror_branch_drift",
					_("La rama espejo «%(rama)s» tiene %(n)s commit(s) propios") % {
						"rama": rama.name, "n": rama.ahead_upstream},
					subject=rama.name,
					detail=_("La espejo sólo debería avanzar por el job de sync con "
							 "ff-only. Commits propios ahí van a hacer fallar el próximo "
							 "sync."),
					observed={"ahead": rama.ahead_upstream})

		if repo.default_branch and repo.default_branch.lower() in ("main", "master"):
			self._finding(
				run, repo, "default_branch_off_convention",
				_("«%(repo)s» tiene «%(rama)s» como rama por defecto") % {
					"repo": repo.full_name, "rama": repo.default_branch},
				subject=repo.default_branch,
				expected={"convention": "rama de versión, ej. 19.0"},
				observed={"default_branch": repo.default_branch})

	@api.model
	def _evaluate_commits(self, run, repo, plantilla):
		muestras = repo.commit_sample_ids
		if not muestras:
			return

		malos = muestras.filtered(lambda c: not c.message_ok)
		if malos:
			ratio = len(malos) / len(muestras) * 100
			umbral = ResConfigSettings._repo_param(
				self.env, "repo_manager.commit_violation_ratio",
				DEFAULTS["repo_manager.commit_violation_ratio"])
			modulada = ratio > umbral
			self._finding(
				run, repo, "commit_format_violations",
				_("%(malos)s de %(total)s commits de «%(repo)s» no siguen la convención") % {
					"malos": len(malos), "total": len(muestras), "repo": repo.full_name},
				severity="high" if modulada else BASE_SEVERITY["commit_format_violations"],
				severity_modulated=modulada,
				detail=_("Supera el %(umbral)s%% configurado.") % {"umbral": umbral}
				if modulada else False,
				expected={"pattern": plantilla.commit_message_pattern},
				observed={"violations": len(malos), "sample": len(muestras),
						  "ratio": round(ratio, 1)})

		if plantilla.require_signed_commits:
			sin_firmar = muestras.filtered(lambda c: not c.signed)
			if sin_firmar:
				self._finding(
					run, repo, "signed_commits_missing",
					_("%(n)s commit(s) sin firmar en «%(repo)s», que exige firma") % {
						"n": len(sin_firmar), "repo": repo.full_name},
					observed={"unsigned": len(sin_firmar), "sample": len(muestras)})

	@api.model
	def _evaluate_pull_requests(self, run, repo):
		umbral = ResConfigSettings._repo_param(
			self.env, "repo_manager.pr_stale_days", DEFAULTS["repo_manager.pr_stale_days"])
		for pr in repo.pull_request_ids.filtered(
				lambda p: p.state == "open" and p.age_days > umbral):
			self._finding(
				run, repo, "pr_stale",
				_("PR #%(n)s de «%(repo)s» lleva %(dias)s días abierta") % {
					"n": pr.number, "repo": repo.full_name, "dias": pr.age_days},
				subject="#%s" % pr.number,
				observed={"age_days": pr.age_days, "author": pr.author_member_id.github_login})

	@api.model
	def _evaluate_fork_drift(self, run, repo):
		if not repo.is_fork:
			return
		umbral = ResConfigSettings._repo_param(
			self.env, "repo_manager.fork_behind_threshold",
			DEFAULTS["repo_manager.fork_behind_threshold"])
		for rama in repo.branch_ids.filtered(lambda b: b.behind_upstream):
			modulada = rama.behind_upstream > umbral
			self._finding(
				run, repo, "fork_behind_upstream",
				_("«%(repo)s» está %(n)s commits detrás de %(up)s en «%(rama)s»") % {
					"repo": repo.full_name, "n": rama.behind_upstream,
					"up": repo.upstream_full_name or "upstream", "rama": rama.name},
				subject=rama.name,
				severity="high" if modulada else BASE_SEVERITY["fork_behind_upstream"],
				severity_modulated=modulada,
				observed={"behind": rama.behind_upstream, "ahead": rama.ahead_upstream})

	@api.model
	def _evaluate_templates(self, run, repos):
		"""Un hallazgo POR PLANTILLA, no por repo.

		Que una plantilla no tenga checks definidos es una sola deuda nuestra. Emitirla
		por cada repositorio afectado llenaría el informe de noventa filas idénticas y
		taparía lo que sí hay que mirar. Se dice una vez, con cuántos repos alcanza.
		"""
		for plantilla in self.env["repo.policy.template"].search([]):
			if plantilla.status_checks_defined:
				continue
			alcanzados = repos.filtered(
				lambda r, p=plantilla: r.classification == p.classification_default)
			if not alcanzados:
				continue
			self._finding(
				run, None, "checks_not_evaluable",
				_("La plantilla «%(plantilla)s» no tiene checks de CI definidos "
				  "(%(n)s repositorio(s))") % {
					"plantilla": plantilla.name, "n": len(alcanzados)},
				detail=_("Hasta definirlos no se puede evaluar si la CI requerida se "
						 "cumple. La auditoría releva qué workflows corren hoy para "
						 "poder proponer la lista."),
				observed={"repositories": alcanzados.mapped("full_name")})

	# ------------------------------------------------------------------
	# A nivel cuenta
	# ------------------------------------------------------------------

	@api.model
	def _evaluate_account(self, run, repos):
		"""Un único hallazgo con la foto de adopción de convenciones."""
		ramas = self.env["repo.branch"].search([("repository_id", "in", repos.ids)])
		por_rol = {}
		for rama in ramas:
			por_rol[rama.role] = por_rol.get(rama.role, 0) + 1
		# El conteo se parte en dos A PROPÓSITO. «main/master como rama por defecto» sólo
		# es un incumplimiento en los repositorios que se evalúan contra una plantilla; en
		# un fork sin migrar la rama por defecto la puso el upstream, y en uno sin
		# clasificar no hay convención contra la cual medir. Un número único sobre los 113
		# no cerraba con las 2 filas de la tabla de hallazgos y dejaba al lector sin saber
		# cuál de los dos creer.
		con_main = repos.filtered(
			lambda r: (r.default_branch or "").lower() in ("main", "master"))
		fuera_de_convencion = con_main.filtered(
			lambda r: self._evaluado_contra_plantilla(r))
		main_no_evaluados = con_main - fuera_de_convencion

		self._finding(
			run, None, "convention_adoption",
			_("Adopción de convenciones en %s repositorios") % len(repos),
			detail=_(
				"De %(ramas)s ramas relevadas: %(prod)s de producción, %(support)s de "
				"support, %(staging)s de staging. Con main o master como rama por "
				"defecto: %(main)s entre los evaluados contra plantilla, y %(otros)s más "
				"entre los que no se evalúan (forks sin migrar y repositorios sin "
				"clasificar), donde no hay convención contra la cual medirlo."
			) % {
				"ramas": len(ramas), "prod": por_rol.get("prod", 0),
				"support": por_rol.get("support", 0), "staging": por_rol.get("staging", 0),
				"main": run._report_plural(len(fuera_de_convencion), "repositorio"),
				"otros": len(main_no_evaluados),
			},
			observed={
				"branches_total": len(ramas),
				"by_role": por_rol,
				"default_off_convention": fuera_de_convencion.mapped("full_name"),
				"default_main_not_evaluated": main_no_evaluados.mapped("full_name"),
			})

	@api.model
	def _evaluate_members(self, run):
		owner = (run.backend_id.owner_login or "").lower()
		for miembro in self.env["repo.member"].search(
				[("state", "=", "active"), ("employee_id", "=", False)]):
			if owner and (miembro.github_login or "").lower() == owner:
				# «Asociar la cuenta con la persona» no aplica: detrás de la cuenta dueña
				# no hay un empleado, es la identidad de la empresa. Se dice como nota
				# para que el inventario de cuentas quede completo, no como pendiente.
				self._finding(
					run, None, "institutional_account",
					_("«%s» es la cuenta institucional dueña de los repositorios")
					% miembro.github_login,
					subject=miembro.github_login,
					detail=_("No corresponde vincularla a un empleado. Sí conviene que "
							 "tenga dueño declarado y 2FA, que es una revisión aparte."),
					observed={"owner": True})
				continue
			self._finding(
				run, None, "member_without_employee",
				_("La cuenta «%s» no está vinculada a ningún empleado")
				% miembro.github_login,
				subject=miembro.github_login,
				remediation_payload={"login": miembro.github_login})

	# ------------------------------------------------------------------
	# Auxiliares
	# ------------------------------------------------------------------

	@api.model
	def _severidad_rama(self, repo):
		"""Modulador: la falta de protección pesa distinto según la plantilla.

		En `interno` la spec no pide ramas de entorno, así que baja a medio; en
		`localizacion`, la plantilla más estricta, sube a crítico.
		"""
		if repo.classification == "interno":
			return "medium", True
		if repo.classification == "localizacion":
			return "critical", True
		return BASE_SEVERITY["branch_unprotected"], False

	@api.model
	def _nivel(self, permiso):
		try:
			return PERMISSION_LEVELS.index(permiso)
		except ValueError:
			return -1

	@api.model
	def _finding(self, run, repo, tipo, resumen, **kwargs):
		return self.env["repo.audit.finding"].build(run, tipo, resumen, repo, **kwargs)
