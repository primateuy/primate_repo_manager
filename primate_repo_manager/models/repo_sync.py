# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El recorrido de lectura: de la API de GitHub a los modelos del espejo.

Todo upsert va por `github_id` o por la clave natural del registro, así que correr la
auditoría N veces actualiza en lugar de duplicar.

LOS TRES ESTADOS DE PROTECCIÓN. GitHub devuelve 404 en el endpoint de protección tanto
cuando la rama no está protegida como cuando quien pregunta no puede verla. Para no
confundirlos se mira el MENSAJE de la respuesta, que es lo único que los separa:
«Branch not protected» es un dato ("no está protegida"); «Not Found» es la ausencia de un
dato ("no puedo saberlo"). El 403 «Upgrade to GitHub Pro» es el tercero: techo de plan.

POR QUÉ NO SE MIRA `permissions.admin`. Fue el primer intento y es sencillamente FALSO
bajo autenticación de GitHub App: en `GET /repos/{owner}/{repo}` ese objeto describe el
permiso de un USUARIO colaborador, y con un token de instalación vuelve
`{admin: False, push: False, pull: False, ...}` SIEMPRE — incluso con el permiso
`administration: read` concedido, que es justo el que habilita leer la protección.
Usarlo como compuerta hacía que el recorrido no consultara el endpoint ni una sola vez y
que los 113 repositorios de primateuy salieran como "protección no legible". El informe
declaraba no saber algo que la credencial podía averiguar perfectamente.

La lección general: no se deduce lo que la credencial puede hacer; se le pregunta a la
API y se clasifica la respuesta.
"""
import logging
from datetime import datetime

from odoo import _, api, fields, models

from .github_client import (
	GithubError,
	GithubNotFound,
	GithubPlanLimit,
	GithubRateLimit,
)

_logger = logging.getLogger(__name__)

# Cuántos commits se miran por rama principal para evaluar formato y firma.
COMMIT_SAMPLE_SIZE = 30
# Ramas cuyo rol amerita guardarse. Las feature branches son efímeras y serían ruido.
ROLES_PERSISTIDOS = ("base", "staging", "support", "prod", "mirror", "patch", "version")


def _fecha(valor):
	"""ISO 8601 de GitHub → naive UTC, que es lo que guarda Odoo."""
	if not valor:
		return False
	try:
		return datetime.strptime(valor, "%Y-%m-%dT%H:%M:%SZ")
	except (TypeError, ValueError):
		return False


class RepoRepositorySync(models.Model):
	_inherit = "repo.repository"

	# ------------------------------------------------------------------
	# Enumerado
	# ------------------------------------------------------------------

	@api.model
	def _sync_from_backend(self, backend):
		"""Trae la lista de repos que abarca la instalación y los upsertea.

		POR QUÉ `/installation/repositories` Y NO `/users/{login}/repos`. El segundo
		devuelve SÓLO los repositorios públicos de la cuenta, aunque se lo llame con un
		token de instalación que tiene acceso a los privados: el token no amplía lo que
		ese endpoint muestra. Contra la cuenta `primateuy` la diferencia es 83 contra 113
		— se perdían los 31 privados enteros, que son justamente donde caen el límite de
		plan para proteger ramas y la mayoría de los repos de cliente.

		Y el modo de falla era el peor posible: la auditoría terminaba en verde, con un
		informe que afirmaba sobre "todos los repositorios" habiendo mirado el 73%. Nada
		en el resultado delataba lo que faltaba.

		`/installation/repositories` es la fuente autoritativa para una GitHub App:
		devuelve exactamente los repos que la instalación puede ver, públicos y privados,
		y sirve igual para una cuenta de usuario que para una organización.
		"""
		client = backend.client()
		datos = client.paginate(
			"/installation/repositories", envoltorio="repositories")
		backend.rate_remaining = client.last_rate_remaining or 0

		repos = self.browse()
		ajenos = []
		for item in datos:
			login = ((item.get("owner") or {}).get("login") or "")
			if login and login.lower() != (backend.owner_login or "").lower():
				# La instalación podría abarcar repos de otra cuenta. No se auditan bajo
				# esta conexión —su dueño es otro— pero tampoco se ocultan.
				ajenos.append(item.get("full_name"))
				continue
			repos |= self._upsert(backend, item)
		if ajenos:
			_logger.warning(
				"Repo Manager: la instalación abarca %s repositorio(s) de otra cuenta, "
				"fuera del alcance de «%s»: %s",
				len(ajenos), backend.owner_login, ", ".join(ajenos))
		return repos

	@api.model
	def _upsert(self, backend, item):
		"""Crea o actualiza un repo por su github_id, que es estable ante renombres."""
		github_id = str(item.get("id"))
		repo = self.search(
			[("backend_id", "=", backend.id), ("github_id", "=", github_id)], limit=1)
		valores = {
			"backend_id": backend.id,
			"github_id": github_id,
			"name": item.get("name"),
			"full_name": item.get("full_name"),
			"description": (item.get("description") or "")[:255],
			"visibility": "private" if item.get("private") else "public",
			"default_branch": item.get("default_branch"),
			"archived": bool(item.get("archived")),
			"pushed_at": _fecha(item.get("pushed_at")),
			"is_fork": bool(item.get("fork")),
		}
		if item.get("parent"):
			valores["upstream_full_name"] = (item["parent"] or {}).get("full_name")
		if repo:
			repo.write(valores)
		else:
			repo = self.create(valores)
		repo._apply_classification(item)
		return repo

	# ------------------------------------------------------------------
	# Job por repositorio
	# ------------------------------------------------------------------

	def _job_sync_repository(self, run_id):
		"""Recorre un repo entero. Un job por repo: si uno falla, los demás siguen."""
		self.ensure_one()
		run = self.env["repo.audit.run"].browse(run_id).exists()
		self.write({"sync_state": "running", "sync_error": False})
		no_legible = []
		try:
			client = self.backend_id.client()
			client.get("/repos/%s" % self.full_name)

			self._sync_branches(client, no_legible)
			self._sync_collaborators(client, no_legible)
			self._sync_pull_requests(client)
			self._sync_commit_samples(client)
			self._sync_workflows(client, no_legible)

			self.write({
				"sync_state": "done",
				"last_synced_at": fields.Datetime.now(),
				"unreadable_json": ", ".join(no_legible) or False,
			})
			if run:
				run._register_repo_done()
		except GithubRateLimit:
			# La cuota se repone sola: reintentar es lo correcto, no fallar la corrida.
			self.sync_state = "pending"
			from odoo.addons.queue_job.exception import RetryableJobError

			raise RetryableJobError(
				"Cuota de API agotada; se reintenta en 15 minutos.", seconds=900) from None
		except Exception as exc:  # noqa: BLE001
			_logger.exception("Repo Manager: falló el sync de %s", self.full_name)
			self.write({"sync_state": "error", "sync_error": str(exc)[:500]})
			if run:
				run._register_repo_done(con_error=True)
			# No se re-lanza: un repo roto no puede tumbar la auditoría de los otros 93.

	# ------------------------------------------------------------------
	# Piezas
	# ------------------------------------------------------------------

	def _sync_branches(self, client, no_legible=None):
		"""Ramas relevantes, su rol y el estado real de protección."""
		self.ensure_one()
		Rama = self.env["repo.branch"]
		Reglas = self.env["repo.branch.role.rule"]
		no_legible = no_legible if no_legible is not None else []
		try:
			rulesets = client.get(
				"/repos/%s/rulesets" % self.full_name, tolerar_404=True) or []
		except GithubPlanLimit:
			# Repo PRIVADO en plan free: GitHub responde 403 «Upgrade to GitHub Pro» en
			# rulesets. Es un techo de plan sobre UNA lectura, no un repo inauditable:
			# dejarlo escapar hacía fallar el job entero y los 31 privados de primateuy
			# terminaban como «no se pudo auditar», perdiendo ramas, colaboradores, PRs y
			# commits que sí se leen perfectamente. Se anota la causa y se sigue.
			rulesets = []
			if "rulesets" not in no_legible:
				no_legible.append("rulesets")

		for item in client.paginate("/repos/%s/branches" % self.full_name):
			nombre = item.get("name")
			rol = Reglas.role_for(nombre)
			if rol not in ROLES_PERSISTIDOS and nombre != self.default_branch:
				continue

			protegida = bool(item.get("protected"))
			protection_json = False
			legible = True
			causa = False
			try:
				datos = client.get(
					"/repos/%s/branches/%s/protection" % (self.full_name, nombre))
				protection_json = str(datos) if datos else False
				protegida = bool(datos)
			except GithubNotFound as exc:
				# Los dos 404 que hay que separar. Ver el docstring del módulo.
				if "not protected" in (exc.message or "").lower():
					protegida = False
				else:
					legible, causa = False, "no_admin_permission"
			except GithubPlanLimit:
				# Repo privado en plan free: proteger ramas no está disponible. Se
				# distingue porque se resuelve pagando, no cambiando permisos.
				legible, causa = False, "plan_limit"
			if not legible and "branch_protection" not in no_legible:
				no_legible.append("branch_protection")

			valores = {
				"repository_id": self.id, "name": nombre, "role": rol,
				"is_default": nombre == self.default_branch,
				"protected": protegida,
				"protection_json": protection_json,
				"protection_readable": legible,
				"protection_cause": causa,
				"ruleset_count": len(rulesets),
				"last_commit_sha": (item.get("commit") or {}).get("sha"),
			}
			rama = Rama.search(
				[("repository_id", "=", self.id), ("name", "=", nombre)], limit=1)
			if rama:
				rama.write(valores)
			else:
				Rama.create(valores)

	def _sync_collaborators(self, client, no_legible):
		"""Permisos observados. Requiere push o más; sin eso se anota como no legible."""
		self.ensure_one()
		try:
			datos = client.paginate("/repos/%s/collaborators" % self.full_name)
		except GithubError:
			no_legible.append("collaborators")
			return

		Colaborador = self.env["repo.collaborator"]
		vistos = Colaborador.browse()
		for item in datos:
			miembro = self.env["repo.member"]._upsert(item)
			permiso = Colaborador.permission_from_role_name(item.get("role_name"))
			existente = Colaborador.search([
				("repository_id", "=", self.id), ("member_id", "=", miembro.id)], limit=1)
			if existente:
				existente.permission = permiso
				vistos |= existente
			else:
				vistos |= Colaborador.create({
					"repository_id": self.id, "member_id": miembro.id,
					"permission": permiso,
				})
		# A quien ya no figura en GitHub se le saca el registro: si no, un permiso
		# revocado seguiría apareciendo como hallazgo para siempre.
		(self.collaborator_ids - vistos).unlink()

	def _sync_pull_requests(self, client):
		"""Sólo las abiertas: las cerradas no son insumo del informe de F1."""
		self.ensure_one()
		datos = client.paginate(
			"/repos/%s/pulls" % self.full_name, params={"state": "open"})
		PR = self.env["repo.pull.request"]
		abiertas = PR.browse()
		for item in datos:
			autor = self.env["repo.member"]._upsert(item.get("user") or {})
			valores = {
				"repository_id": self.id,
				"number": item.get("number"),
				"title": (item.get("title") or "")[:255],
				"url": item.get("html_url"),
				"author_member_id": autor.id if autor else False,
				"source_branch": (item.get("head") or {}).get("ref"),
				"target_branch": (item.get("base") or {}).get("ref"),
				"state": "open",
				"draft": bool(item.get("draft")),
				"created_at": _fecha(item.get("created_at")),
				"updated_at": _fecha(item.get("updated_at")),
			}
			existente = PR.search([
				("repository_id", "=", self.id), ("number", "=", item.get("number"))], limit=1)
			if existente:
				existente.write(valores)
				abiertas |= existente
			else:
				abiertas |= PR.create(valores)
		# Las que ya no están abiertas se marcan cerradas en vez de borrarse: sirven de
		# historia y evitan que una PR mergeada reaparezca como abierta.
		(self.pull_request_ids.filtered(lambda p: p.state == "open") - abiertas).write(
			{"state": "closed"})

	def _sync_commit_samples(self, client):
		"""Últimos N commits de las ramas principales: formato y firma."""
		self.ensure_one()
		Muestra = self.env["repo.commit.sample"]
		patron = self._commit_pattern()
		principales = self.branch_ids.filtered(
			lambda b: b.role in ("base", "staging", "support", "prod") or b.is_default)
		for rama in principales:
			try:
				commits = client.paginate(
					"/repos/%s/commits" % self.full_name,
					params={"sha": rama.name}, max_items=COMMIT_SAMPLE_SIZE)
			except GithubError:
				continue
			for item in commits:
				sha = item.get("sha")
				commit = (item.get("commit") or {})
				verificacion = commit.get("verification") or {}
				mensaje = (commit.get("message") or "").split("\n")[0]
				valores = {
					"repository_id": self.id, "branch_name": rama.name, "sha": sha,
					"message_first_line": mensaje[:255],
					"author_login": ((item.get("author") or {}) or {}).get("login"),
					"committed_at": _fecha((commit.get("committer") or {}).get("date")),
					"message_ok": Muestra.message_matches(mensaje, patron),
					"signed": bool(verificacion.get("verified")),
					"signature_reason": verificacion.get("reason"),
				}
				existente = Muestra.search([
					("repository_id", "=", self.id), ("branch_name", "=", rama.name),
					("sha", "=", sha)], limit=1)
				if existente:
					existente.write(valores)
				else:
					Muestra.create(valores)

	def _sync_workflows(self, client, no_legible):
		"""Releva qué workflows corren, para poder proponer los checks requeridos con datos."""
		self.ensure_one()
		try:
			datos = client.get(
				"/repos/%s/actions/workflows" % self.full_name, tolerar_404=True)
		except GithubError:
			# 403 «Resource not accessible by integration»: a la GitHub App no le dieron
			# el permiso de Actions. Es UNA lectura que no se puede hacer, no un repo
			# inauditable — mismo criterio que en colaboradores. Dejarlo escapar hacía
			# fallar el job entero al final del recorrido, tirando ramas, colaboradores,
			# PRs y commits ya leídos.
			no_legible.append("workflows")
			return
		if datos is None:
			no_legible.append("workflows")
			return
		Workflow = self.env["repo.workflow"]
		vistos = Workflow.browse()
		for item in (datos.get("workflows") or []):
			valores = {
				"repository_id": self.id,
				"name": item.get("name"),
				"path": item.get("path"),
				"state": item.get("state"),
			}
			existente = Workflow.search([
				("repository_id", "=", self.id), ("path", "=", item.get("path"))], limit=1)
			if existente:
				existente.write(valores)
				vistos |= existente
			else:
				vistos |= Workflow.create(valores)
		(self.workflow_ids - vistos).unlink()

	def _commit_pattern(self):
		"""El patrón de la plantilla que le corresponde al repo, o el de la convención."""
		self.ensure_one()
		plantilla = self.env["repo.policy.template"].search(
			[("classification_default", "=", self.classification)], limit=1)
		return plantilla.commit_message_pattern if plantilla else None


class RepoMemberSync(models.Model):
	_inherit = "repo.member"

	@api.model
	def _upsert(self, item):
		"""Crea o actualiza una persona por su login. Devuelve recordset vacío si no hay dato."""
		login = (item or {}).get("login")
		if not login:
			return self.browse()
		miembro = self.search([("github_login", "=", login)], limit=1)
		valores = {
			"github_login": login,
			"github_id": str(item.get("id")) if item.get("id") else False,
			"avatar_url": item.get("avatar_url"),
		}
		if miembro:
			miembro.write(valores)
			return miembro
		return self.create(valores)
