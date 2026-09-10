# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El motor que compara lo observado contra lo declarado y produce hallazgos.

Nada de esto escribe en GitHub: lee los modelos del espejo, los compara con las plantillas
y crea `repo.audit.finding`. La remediación se calcula y se guarda; ejecutarla es F2/F3.

Los MODULADORES de severidad viven acá, con sus umbrales leídos de configuración. La
lógica es código testeado; los números son criterio y el criterio cambia.
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models

from .repo_audit_finding import BASE_SEVERITY
from .repo_write_apply import _coincide_con_lo_pedido
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
			if not repo.present:
				# AUSENTE: se deja de auditar y se dice por qué. Sus hallazgos no se
				# regeneran —la corrida los rehace desde cero— así que quedan cerrados
				# con esta entrada como causa. Seguir midiéndolo sería afirmar sobre
				# ramas y permisos que ya no se pueden mirar: el espejo guarda la última
				# foto, no el estado de hoy.
				self._finding(
					run, repo, "repository_absent",
					_("«%s» ya no viene en el listado de la conexión") % repo.full_name,
					severity="info",
					detail=_("Ausente desde %s. Puede que lo hayan borrado, "
							 "transferido, o que la instalación haya perdido acceso: "
							 "desde acá las tres se ven igual. Deja de auditarse; la "
							 "fila del espejo se conserva porque la bitácora la "
							 "referencia.") % (repo.absent_since or "?"),
					remediation_action="review_manually",
					observed={"absent_since": str(repo.absent_since or "")})
				continue
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
		self._evaluate_policy_not_reapplied(run, repos)
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
		# LA SEGURIDAD NO DEPENDE DE LA POLÍTICA, y por eso va ANTES de cualquier
		# compuerta. Un repositorio sin clasificar igual puede tener un secreto filtrado,
		# y esconderlo hasta que alguien lo clasifique sería callar lo más grave que el
		# módulo sabe decir justo sobre los repositorios que nadie miró todavía.
		self._evaluate_security(run, repo)
		# LA HIGIENE TAMPOCO DEPENDE DE LA POLÍTICA. Se trata del ciclo de vida —qué está
		# integrado y qué no se toca hace un año—, y eso es cierto de un repositorio
		# clasificado y de uno que nadie clasificó todavía. Justamente los repositorios
		# que nadie miró son los que más ramas viejas juntan.
		self._evaluate_higiene(run, repo)
		self._evaluate_archivable(run, repo)
		if not repo.classification:
			self._finding(run, repo, "classification_missing",
						  _("«%s» no coincide con ninguna regla de clasificación")
						  % repo.full_name)
			# Sin clasificación no hay plantilla contra la cual comparar el resto.
			return

		# El mismo criterio que usa el armado de rulesets: se compara contra la
		# plantilla que después se va a escribir, no contra otra parecida.
		plantilla = repo.plantilla_efectiva()
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

		self._evaluate_ruleset_drift(run, repo)
		self._evaluate_permissions(run, repo, plantilla)
		self._evaluate_branches(run, repo, plantilla)
		self._evaluate_commits(run, repo, plantilla)
		self._evaluate_pull_requests(run, repo)
		self._evaluate_fork_drift(run, repo)


	@api.model
	def _evaluate_ruleset_drift(self, run, repo):
		"""B4 · sentido 1: alguien cambió por fuera lo que el módulo aplicó.

		SE COMPARA CONTRA LO APLICADO, NO CONTRA LA PLANTILLA, y ésa es la decisión que
		hace posible todo el bloque. Comparando contra la plantilla, «GitHub cambió» y
		«la política se movió acá» dan el mismo resultado, y separarlos es exactamente
		para lo que B4 existe: uno es un incidente y el otro es trabajo pendiente.

		La referencia es la bitácora inmutable: la última escritura aplicada sobre ese
		ruleset, con el payload que se verificó por relectura en su momento. Que la
		referencia sea inmutable importa — si viviera en el plan, quien edita el plan
		reescribiría contra qué se mide el desvío.

		Y EL CRITERIO DE COMPARACIÓN ES EL DE LA ESCRITURA, compartido: «difiere en lo que
		gobernamos» no es lo mismo que «difiere en lo que GitHub agrega solo». Sin eso,
		cada auditoría reportaría drift sobre rulesets intactos, por los defaults que
		GitHub completa — el mismo defecto que el ensayo de B1.6 encontró en la
		verificación, que acá saldría multiplicado por cada corrida.
		"""
		Espejo = self.env["repo.ruleset"]
		for aplicado in self.env["repo.audit.log"]._ultimas_escrituras_de_ruleset(repo):
			nombre = aplicado["target"]
			esperado = aplicado["payload"]
			# LA FILA VIVA MANDA. Un ruleset borrado y recreado con el mismo nombre deja
			# una fila vieja dada de baja; buscar «la primera con ese nombre» podía tocar
			# la muerta y gritar «ya no está» sobre uno que estaba. Lo encontró el ensayo.
			fila = Espejo.search([
				("repository_id", "=", repo.id), ("name", "=", nombre),
				("present", "=", True),
			], limit=1) or Espejo.search([
				("repository_id", "=", repo.id), ("name", "=", nombre),
			], order="last_seen_at desc", limit=1)

			if not fila or not fila.present:
				self._drift(run, repo, nombre, esperado, _(
					"El ruleset «%(nombre)s» que este módulo aplicó en «%(repo)s» ya no "
					"está en GitHub") % {"nombre": nombre, "repo": repo.full_name},
					observado={"presente": False}, severidad="critical")
				continue

			coincide, donde = _coincide_con_lo_pedido(esperado, fila.definicion())
			if coincide:
				# Volvió a coincidir: si había un desvío abierto, se cierra. Si no había,
				# no pasa nada — y no pasar nada NO se anota.
				self.env["repo.audit.log"]._cerrar_drift(repo, nombre)
				continue

			self._drift(run, repo, nombre, esperado, _(
				"El ruleset «%(nombre)s» de «%(repo)s» cambió fuera de la aplicación: "
				"difiere en «%(donde)s»") % {
					"nombre": nombre, "repo": repo.full_name, "donde": donde},
				observado=fila.definicion(), severidad="high", donde=donde)

	@api.model
	def _drift(self, run, repo, nombre, esperado, resumen, observado, severidad,
			   donde=None):
		"""El hallazgo del desvío, y la entrada de bitácora SÓLO si el estado cambió."""
		self._finding(
			run, repo, "policy_drift_external", resumen,
			subject=nombre, severity=severidad,
			expected=esperado, observed=observado,
			# PLANIFICABLE, y su payload es ejecutable de verdad: es la definición que
			# este módulo aplicó y verificó. Ver la nota en PLANIFICABLES.
			remediation_payload=esperado)
		self.env["repo.audit.log"]._abrir_drift(
			repo, nombre, resumen, esperado, observado, donde,
			# Quién lo detectó viaja como DATO y no se supone: hoy es una corrida, y con
			# los webhooks de F4 va a ser un evento de GitHub sin corrida ninguna.
			detectado_por=(_("la auditoría #%s") % run.id) if run else None)

	# Cómo se ordenan las severidades de GitHub, para saber cuál es la peor. El
	# vocabulario es suyo y no se traduce: GitHub ya clasificó con un análisis que no
	# vamos a rehacer, y renombrarlo sólo agregaría una capa donde perder información.
	SEVERIDAD_DEPENDABOT = {
		"critical": "critical", "high": "high", "medium": "medium", "low": "info",
	}
	ORDEN_DEPENDABOT = ("critical", "high", "medium", "low")

	# Cuánto dura «recién creado». Una hora es holgado para lo que en la práctica son
	# segundos, y corto frente a cualquier repositorio real: si a la hora las fuentes
	# siguen sin contestar, ya no es que GitHub no llegó, es que algo pasa — y ahí el
	# hallazgo vuelve a ser MEDIUM con su causa de siempre.
	VENTANA_DE_NACIMIENTO = timedelta(hours=1)

	@api.model
	def _es_recien_creado(self, repo):
		"""¿Este repositorio es de hace un rato, según GITHUB y no según el espejo?

		La fecha es la de GitHub a propósito: la del espejo diría «recién creado» de un
		repositorio de 2019 que se sincronizó por primera vez hoy, y con eso una
		conexión nueva estrenaría todos sus hallazgos de seguridad en informativo.
		"""
		if not repo.created_at:
			return False
		return (fields.Datetime.now() - repo.created_at) < self.VENTANA_DE_NACIMIENTO

	@api.model
	def _evaluate_security(self, run, repo):
		"""B6.2 · las alertas de seguridad, con sus dos tratamientos y el apagado.

		DOS TRATAMIENTOS PORQUE SON DOS OBJETOS DISTINTOS:

		· **Un hallazgo por secreto.** Un secreto filtrado es un incidente con nombre
		  propio: agruparlos escondería cuál es cuál, y son cosas que se rotan de a una.
		· **Un hallazgo por repositorio en dependencias.** Cuarenta vulnerabilidades son
		  UN trabajo —actualizar—, no cuarenta; emitir cuarenta filas taparía todo lo demás
		  del informe.

		EL CICLO DE VIDA SIGUE A LA ALERTA DE GITHUB. Si allá se resolvió o se descartó,
		acá no se emite: un secreto que ya se rotó y se cerró no puede seguir gritando,
		porque es la fábrica de ruido permanente otra vez y en el lugar más sensible. El
		desenlace viaja en el espejo, con su valor CODIFICADO.

		Y EL HALLAZGO NO CONTIENE EL SECRETO: tipo, dónde, y el enlace a GitHub.
		"""
		Scan = self.env["repo.security.scan"]
		Alerta = self.env["repo.security.alert"]
		for lectura in Scan.search([("repository_id", "=", repo.id)]):
			if lectura.state == "apagado":
				self._security_apagado(run, repo, lectura)
				continue
			if lectura.state == "no_legible":
				# EL TERCER ESTADO SE MANTIENE, LA CAUSA CAMBIA. En un repositorio de
				# segundos las dos fuentes de seguridad contestan 404, y no es lo mismo
				# que un 404 por falta de permiso: GitHub todavía no expone el estado de
				# algo que acaba de crear. Se sigue sin afirmar nada —eso es el punto del
				# tercer estado— pero con la causa que corresponde y en informativo: no
				# hay nada que hacer salvo esperar a la próxima corrida, y un MEDIUM que
				# se resuelve solo es ruido con la severidad equivocada.
				# LA FALTA DE PERMISO NUNCA ES UN PROBLEMA DE NACIMIENTO. Medido contra
				# prm-sandbox el 8-sep-2026: los dos 404 que parecían «GitHub todavía no
				# lo expone» eran 403 «Resource not accessible by integration», y salían
				# igual sobre un repositorio de meses — la instalación no tenía aprobados
				# los permisos de seguridad. Con la ventana de nacimiento sola, eso se
				# habría mostrado en informativo durante la primera hora de vida de cada
				# repositorio nuevo: justo cuando se lo mira, y justo lo accionable.
				recien = self._es_recien_creado(repo) and not lectura.es_falta_de_permiso()
				self._finding(
					run, repo, "security_feature_disabled",
					_("No se pudo leer «%(que)s» en «%(repo)s»") % {
						"que": dict(Scan._fields["source"].selection)[lectura.source],
						"repo": repo.full_name},
					subject=lectura.source,
					severity="info" if recien else "medium",
					detail=(
						_("Recién creado: GitHub todavía no expone su estado en esa "
						  "fuente. Se relee en la próxima corrida.") if recien
						else _("No se afirma nada sobre este repositorio en esa fuente: "
							   "no se pudo mirar. Causa: %s") % (lectura.cause or "?")),
					remediation_action=(
						"no_action_recien_creado" if recien else "check_app_access"),
					observed={"causa": "recien_creado" if recien else lectura.cause})
				continue

		abiertas = Alerta.search([
			("repository_id", "=", repo.id), ("state", "=", "open")])
		for alerta in abiertas.filtered(lambda a: a.source == "secret_scanning"):
			self._finding(
				run, repo, "secret_leaked",
				_("Secreto filtrado en «%(repo)s»: %(tipo)s") % {
					"repo": repo.full_name,
					"tipo": alerta.secret_type or _("tipo no informado")},
				subject=alerta.secret_type or str(alerta.external_id),
				detail=_("Rotarlo donde se emitió y cerrar la alerta en GitHub. El valor "
						 "no se copia acá a propósito: %s") % (alerta.html_url or ""),
				# NUNCA el secreto: tipo, dónde y el enlace. Nada más.
				observed={"tipo": alerta.secret_type, "donde": alerta.location,
						  "enlace": alerta.html_url, "numero": alerta.external_id})

		dependencias = abiertas.filtered(lambda a: a.source == "dependabot")
		if dependencias:
			self._finding_de_dependencias(run, repo, dependencias)

	@api.model
	def _security_apagado(self, run, repo, lectura):
		"""La función está apagada. Las dos causas se resuelven distinto y se dicen así."""
		etiqueta = dict(
			self.env["repo.security.scan"]._fields["source"].selection)[lectura.source]
		if lectura.needs_advanced_security:
			detalle = _(
				"Encenderlo en un repositorio privado exige GitHub Advanced Security, "
				"que es una decisión comercial y no una casilla. Es la misma familia que "
				"el techo de plan de las protecciones de rama.")
			accion = "upgrade_plan"
		else:
			detalle = _("Se enciende gratis desde la configuración del repositorio.")
			accion = "enable_security_feature"
		self._finding(
			run, repo, "security_feature_disabled",
			_("«%(que)s» está apagado en «%(repo)s»") % {
				"que": etiqueta, "repo": repo.full_name},
			subject=lectura.source, detail=detalle, remediation_action=accion,
			observed={"causa": lectura.cause,
					  "exige_advanced_security": lectura.needs_advanced_security})

	@api.model
	def _finding_de_dependencias(self, run, repo, alertas):
		"""UN hallazgo por repositorio, con la severidad PEOR y el desglose adentro."""
		por_severidad = {}
		for alerta in alertas:
			clave = (alerta.severity or "low").lower()
			por_severidad[clave] = por_severidad.get(clave, 0) + 1
		peor = next((s for s in self.ORDEN_DEPENDABOT if s in por_severidad), "low")
		self._finding(
			run, repo, "dependency_vulnerabilities",
			_("%(n)s vulnerabilidad(es) de dependencias en «%(repo)s», la peor "
			  "%(peor)s") % {
				"n": len(alertas), "repo": repo.full_name, "peor": peor},
			subject=repo.full_name,
			severity=self.SEVERIDAD_DEPENDABOT.get(peor, "medium"),
			detail=_("La severidad es la que asigna GitHub: ya clasificó cada aviso con "
					 "un análisis que este módulo no rehace."),
			observed={"por_severidad": por_severidad,
					  "paquetes": sorted(set(alertas.mapped("package_name")))[:20]})

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
			if colaborador.permission == "admin" and colaborador.source != "direct":
				# EL ADMIN QUE NO ES DIRECTO ES ESTRUCTURA, NO EXCESO — Y NO ES HALLAZGO.
				# En una organización, quien la posee tiene admin sobre todos sus
				# repositorios por definición: no hay grant que revocar, y proponerlo
				# mandaría a alguien a intentar una operación que GitHub no permite.
				# Medido contra el sandbox: el dueño NO figura en `affiliation=direct`,
				# y ésa es la señal que distingue estructura de permiso otorgado.
				#
				# No se emite nada. El dato no se pierde: la pestaña Colaboradores lo
				# muestra con su columna Origen, que es donde vive el inventario de
				# accesos. Un hallazgo es algo sobre lo que se puede actuar; esto no lo
				# es, y una bandeja con hallazgos que nadie puede resolver se ignora
				# entera.
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

			# LA COMPARACIÓN DE B1.4 ES LA QUE DECIDE, y no el flag de la protección
			# clásica. GitHub protege de dos maneras y este módulo aplica rulesets: mirar
			# sólo el flag hacía que el informe acusara al módulo de no haber protegido
			# lo que acababa de proteger. Una sola definición de «esta rama cumple»,
			# usada por la pantalla y por el motor.
			comparacion = rama.comparacion_de_politica()
			if protegible and comparacion["estado"] in ("sin_proteccion", "parcial"):
				severidad, modulada = self._severidad_rama(repo)
				self._finding(
					run, repo, "branch_unprotected",
					_("«%(rama)s» de «%(repo)s» no cumple: le falta %(falta)s") % {
						"rama": rama.name, "repo": repo.full_name,
						"falta": ", ".join(comparacion["exige"])},
					subject=rama.name, severity=severidad, severity_modulated=modulada,
					expected=regla,
					observed={"protected": rama.protected,
							  "tiene": comparacion["tiene"],
							  "falta": comparacion["faltan"]},
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

	# Los mensajes que GitHub escribe por su cuenta al inicializar un repositorio. No
	# los escribió nadie del equipo, así que exigirles el formato de ticket es ruido de
	# nacimiento — y el ruido enseña a ignorar la lista. Es la misma familia que la rama
	# «otra», que no incumple porque no hay convención contra la cual medirla.
	COMMITS_FUNDACIONALES = ("initial commit", "create readme.md", "add .gitignore",
							 "add license")

	@api.model
	def _evaluate_commits(self, run, repo, plantilla):
		muestras = repo.commit_sample_ids
		if not muestras:
			return

		# EL COMMIT FUNDACIONAL NO CUENTA. Lo escribe GitHub al crear el repositorio con
		# README, y un repositorio recién nacido salía con «1 de 1 commits fuera de
		# convención» por un commit que ninguna persona escribió. Lo destapó el ensayo
		# del nacimiento.
		muestras = muestras.filtered(
			lambda c: (c.message_first_line or "").strip().lower()
			not in self.COMMITS_FUNDACIONALES)
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
	def _evaluate_higiene(self, run, repo):
		"""E3.2b · los tres hallazgos de higiene, atados al CICLO DE VIDA y no a la fecha.

		LA DISTINCIÓN ES EL PRODUCTO. Una rama vieja e integrada es basura y se ofrece
		borrar; una rama vieja con trabajo que nunca se mergeó puede ser trabajo por
		rescatar y **no se ofrece borrar nunca**, ni siquiera detrás de una confirmación.
		Una regla por fecha no puede hacer esa distinción: las dos ramas se ven iguales.

		Y LO QUE NO SE PUDO COMPARAR NO ES NINGUNA DE LAS DOS. Sin `compare` no se sabe
		si tiene trabajo propio, así que no se propone nada — es el mismo tercer estado
		de siempre, en el lugar donde más caro sale equivocarse.
		"""
		meses_abandono = ResConfigSettings._repo_param(
			self.env, "repo_manager.branch_abandoned_months",
			DEFAULTS["repo_manager.branch_abandoned_months"])
		limite = fields.Datetime.now() - timedelta(days=30 * meses_abandono)

		for rama in repo.branch_ids:
			if not rama.line_comparison_readable or not rama.line_branch_name:
				continue
			if rama.ahead_of_line == 0:
				# INTEGRADA. Dice contra QUÉ se midió: «integrada a 17.0-prod» y
				# «integrada a 17.0» son afirmaciones distintas, y quien decide borrar
				# necesita saber cuál de las dos está leyendo.
				self._finding(
					run, repo, "branch_integrated_candidate",
					_("«%(rama)s» de «%(repo)s» está integrada a «%(prod)s»: no tiene "
					  "commits propios") % {
						"rama": rama.name, "repo": repo.full_name,
						"prod": rama.line_branch_name},
					subject=rama.name,
					detail=_("Todo lo que tenía ya está en «%s». Borrarla no pierde nada, "
							 "y se hace por el embudo con el nombre escrito a mano.")
						   % rama.line_branch_name,
					remediation_payload={"repository": repo.full_name,
										 "branch": rama.name,
										 "sha": rama.last_commit_sha or "",
										 "integrated_into": rama.line_branch_name},
					observed={"ahead": 0, "integrated_into": rama.line_branch_name})
				continue
			# CON TRABAJO PROPIO. Sólo se dice si además hace rato que nadie la toca:
			# una rama activa con commits sin integrar es trabajo en curso, no higiene.
			if rama.last_commit_date and rama.last_commit_date < limite:
				self._finding(
					run, repo, "branch_abandoned",
					_("«%(rama)s» de «%(repo)s» tiene %(n)s commit(s) que nunca llegaron "
					  "a «%(prod)s» y no se toca desde %(fecha)s") % {
						"rama": rama.name, "repo": repo.full_name,
						"n": rama.ahead_of_line, "prod": rama.line_branch_name,
						"fecha": rama.last_commit_date.date()},
					subject=rama.name,
					detail=_("Este módulo NO ofrece borrarla: esos commits no están en "
							 "ningún otro lado. Se mira a mano y se decide con quien la "
							 "escribió."),
					observed={"ahead": rama.ahead_of_line,
							  "last_commit": str(rama.last_commit_date)})

	@api.model
	def _evaluate_archivable(self, run, repo):
		"""Un repositorio sin push hace mucho. Archivar es reversible y sin pérdida."""
		meses = ResConfigSettings._repo_param(
			self.env, "repo_manager.repo_archive_months",
			DEFAULTS["repo_manager.repo_archive_months"])
		if repo.archived or not repo.pushed_at:
			return
		limite = fields.Datetime.now() - timedelta(days=30 * meses)
		if repo.pushed_at >= limite:
			return
		self._finding(
			run, repo, "repository_archivable",
			_("«%(repo)s» no recibe un push desde %(fecha)s") % {
				"repo": repo.full_name, "fecha": repo.pushed_at.date()},
			detail=_("Archivarlo lo deja en sólo lectura para todos, y se puede "
					 "desarchivar sin perder nada. La aprobación dice qué depende de él "
					 "hoy."),
			remediation_payload={"repository": repo.full_name},
			observed={"pushed_at": str(repo.pushed_at), "meses": meses})

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
				# EL SUJETO NO ES DECORACIÓN: es lo que hace único al hallazgo. Sin él,
				# dos plantillas sin checks producían la misma clave —(tipo, sin repo,
				# sin sujeto)— y el delta las contaba como una sola: definir los checks
				# de una plantilla se leía como si se hubieran definido los de las dos.
				subject=plantilla.name,
				detail=_("Hasta definirlos no se puede evaluar si la CI requerida se "
						 "cumple. La auditoría releva qué workflows corren hoy para "
						 "poder proponer la lista."),
				observed={"repositories": alcanzados.mapped("full_name")})

	@api.model
	def _evaluate_policy_not_reapplied(self, run, repos):
		"""B4 · sentido 2: la política se movió acá y los repositorios quedaron atrás.

		UN HALLAZGO POR PLANTILLA, con su fecha y con cuántos repositorios alcanza. Es la
		misma razón que en `_evaluate_templates`: la deuda es de la plantilla, no de cada
		repositorio, y emitirla noventa veces taparía lo que sí hay que mirar.

		DESDE CUÁNDO, Y UNA SOLA VEZ. Si la plantilla se tocó tres veces sin reaplicarse,
		el hallazgo lleva la fecha del PRIMER cambio sin aplicar y es uno solo. Tres
		hallazgos dirían que hay tres cosas que hacer, y hay una: **la deuda es contra la
		política vigente, no contra cada versión intermedia**. Lo que decía la plantilla en
		el medio da igual — lo único que se va a reaplicar es lo que dice hoy.

		NO DEJA ENTRADA EN LA BITÁCORA, y es deliberado. Que la política cambió acá **ya
		está registrado** por A5 como `policy_changed`, con su antes y su después.
		Anotarlo otra vez como «cambio detectado fuera de la app» sería mentir sobre dónde
		pasó, que es justamente la distinción que este bloque existe para sostener.

		Y «NUNCA SE APLICÓ» NO ES «QUEDÓ ATRÁS». Un repositorio donde la política nunca se
		escribió no tiene una deuda contra un cambio: tiene la política entera sin aplicar,
		que es otro hallazgo y otro trabajo. Contarlo acá inflaría la deuda con repos que
		nadie prometió tener al día.
		"""
		Log = self.env["repo.audit.log"]
		for plantilla in self.env["repo.policy.template"].search([]):
			if not plantilla.classification_default:
				continue
			alcanzados = repos.filtered(
				lambda r, p=plantilla: r.classification == p.classification_default)
			atrasados, desde = [], None
			for repo in alcanzados:
				aplicado = Log._ultima_aplicacion_de_plantilla(repo, plantilla)
				if not aplicado:
					continue
				cambio = Log._primer_cambio_sin_aplicar(plantilla, aplicado)
				if not cambio:
					continue
				atrasados.append(repo)
				desde = min(desde, cambio) if desde else cambio
			if not atrasados:
				continue
			self._finding(
				run, None, "policy_not_reapplied",
				_("«%(plantilla)s» cambió el %(cuando)s y %(n)s repositorio(s) siguen "
				  "con lo de antes") % {
					"plantilla": plantilla.name,
					"cuando": fields.Date.to_string(desde.date()),
					"n": len(atrasados)},
				detail=_(
					"No es un incidente: nadie tocó GitHub por fuera. Es trabajo "
					"pendiente — la política se movió acá y todavía no se escribió allá. "
					"Si la plantilla cambió varias veces, la fecha es la del primer "
					"cambio sin aplicar: la deuda es contra la política vigente, no "
					"contra cada versión intermedia."),
				expected={"plantilla": plantilla.code, "cambio_desde": str(desde)},
				observed={"repositories": [r.full_name for r in atrasados]})

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
