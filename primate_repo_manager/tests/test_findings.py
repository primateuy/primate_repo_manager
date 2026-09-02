# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El motor de hallazgos.

Incluye los tres que el encargo pide demostrar: un permiso excedido, una rama sin
protección y un fork desfasado.
"""
import uuid

from odoo.tests.common import TransactionCase


class TestFindings(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Hallazgos %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected",
		})
		self.run = self.env["repo.audit.run"].create({
			"name": "Corrida de prueba", "backend_id": self.backend.id,
		})

	def _repo(self, name, clasificacion="cliente", **extra):
		valores = {
			"backend_id": self.backend.id,
			"github_id": uuid.uuid4().hex[:8],
			"name": name, "full_name": "cuenta/%s" % name,
			"classification": clasificacion,
			"classification_source": "manual",
			"sync_state": "done", "default_branch": "19.0",
		}
		valores.update(extra)
		return self.env["repo.repository"].create(valores)

	def _tipos(self):
		return self.run.finding_ids.mapped("finding_type")

	def _hallazgo(self, tipo):
		return self.run.finding_ids.filtered(lambda f: f.finding_type == tipo)

	# --- los tres del criterio de aceptación ---

	def test_detecta_un_permiso_excedido(self):
		repo = self._repo("cliente-uno")
		miembro = self.env["repo.member"].create({"github_login": "alguien"})
		self.env["repo.collaborator"].create({
			"repository_id": repo.id, "member_id": miembro.id, "permission": "admin"})

		self.env["repo.audit.engine"].evaluate(self.run)

		hallazgo = self._hallazgo("permission_admin_exceeded")
		self.assertTrue(hallazgo)
		self.assertEqual(hallazgo.severity, "critical")
		self.assertEqual(hallazgo.remediation_action, "revoke_permission")
		self.assertTrue(hallazgo.is_destructive,
						"revocar acceso nunca puede aprobarse por lote")

	def test_detecta_una_rama_sin_proteccion(self):
		repo = self._repo("cliente-dos")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "19.0", "role": "base",
			"protected": False, "protection_readable": True})

		self.env["repo.audit.engine"].evaluate(self.run)

		hallazgo = self._hallazgo("branch_unprotected")
		self.assertTrue(hallazgo)
		self.assertEqual(hallazgo.severity, "high")
		self.assertEqual(hallazgo.remediation_action, "apply_ruleset")

	def test_detecta_un_fork_desfasado(self):
		repo = self._repo("forkOCA", "fork_upstream", is_fork=True,
						  upstream_full_name="OCA/web", governance_status="governed")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "17.0", "role": "mirror",
			"behind_upstream": 42, "protection_readable": True, "protected": True})

		self.env["repo.audit.engine"].evaluate(self.run)

		hallazgo = self._hallazgo("fork_behind_upstream")
		self.assertTrue(hallazgo)
		self.assertEqual(hallazgo.severity, "medium")

	# --- moduladores ---

	def test_el_atraso_grande_sube_la_severidad(self):
		repo = self._repo("forkOCA2", "fork_upstream", is_fork=True,
						  governance_status="governed")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "17.0", "role": "mirror",
			"behind_upstream": 500, "protection_readable": True, "protected": True})

		self.env["repo.audit.engine"].evaluate(self.run)

		hallazgo = self._hallazgo("fork_behind_upstream")
		self.assertEqual(hallazgo.severity, "high")
		self.assertTrue(hallazgo.severity_modulated,
						"el informe tiene que poder aclarar por qué subió")

	def test_el_umbral_del_atraso_es_configurable(self):
		"""La lógica es código; el número es criterio y se edita sin tocar código."""
		self.env["ir.config_parameter"].sudo().set_param(
			"repo_manager.fork_behind_threshold", "10")
		repo = self._repo("forkOCA3", "fork_upstream", is_fork=True,
						  governance_status="governed")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "17.0", "role": "mirror",
			"behind_upstream": 42, "protection_readable": True, "protected": True})

		self.env["repo.audit.engine"].evaluate(self.run)

		self.assertEqual(self._hallazgo("fork_behind_upstream").severity, "high")

	def test_sin_proteccion_pesa_distinto_segun_la_plantilla(self):
		interno = self._repo("primate-tool", "interno")
		self.env["repo.branch"].create({
			"repository_id": interno.id, "name": "19.0", "role": "base",
			"protected": False, "protection_readable": True})
		loca = self._repo("LocalizacionX", "localizacion")
		self.env["repo.branch"].create({
			"repository_id": loca.id, "name": "19.0", "role": "base",
			"protected": False, "protection_readable": True})

		self.env["repo.audit.engine"].evaluate(self.run)

		por_repo = {f.repository_id.name: f.severity
					for f in self._hallazgo("branch_unprotected")}
		self.assertEqual(por_repo["primate-tool"], "medium")
		self.assertEqual(por_repo["LocalizacionX"], "critical")

	# --- la causa, que tiene que salir por query ---

	def test_la_causa_de_la_ilegibilidad_se_guarda_como_dato(self):
		"""Techo de plan y falta de permisos se resuelven distinto: plata vs reinstalar."""
		plan = self._repo("privado-plan")
		self.env["repo.branch"].create({
			"repository_id": plan.id, "name": "19.0", "role": "base",
			"protection_readable": False, "protection_cause": "plan_limit"})
		permiso = self._repo("sin-admin")
		self.env["repo.branch"].create({
			"repository_id": permiso.id, "name": "19.0", "role": "base",
			"protection_readable": False, "protection_cause": "no_admin_permission"})

		self.env["repo.audit.engine"].evaluate(self.run)

		hallazgos = self._hallazgo("branch_protection_unreadable")
		por_causa = {f.unreadable_cause: f.remediation_action for f in hallazgos}
		self.assertEqual(por_causa["plan_limit"], "upgrade_plan")
		self.assertEqual(por_causa["no_admin_permission"], "reinstall_app")
		# Y se pueden contar por separado, que es el punto.
		self.assertEqual(len(hallazgos.filtered(
			lambda f: f.unreadable_cause == "plan_limit")), 1)

	# --- cobertura: lo que no se pudo auditar ---

	def test_un_repo_que_fallo_es_un_hallazgo_tipado(self):
		"""Una auditoría que no dice qué no pudo auditar miente por omisión."""
		self._repo("roto", sync_state="error", sync_error="403 sin permiso")

		self.env["repo.audit.engine"].evaluate(self.run)

		hallazgo = self._hallazgo("repo_sync_error")
		self.assertTrue(hallazgo)
		self.assertEqual(hallazgo.severity, "high")
		self.assertIn("403", hallazgo.detail)

	# --- forks sin migrar ---

	def test_un_fork_sin_migrar_da_un_solo_hallazgo_agregado(self):
		repo = self._repo("webOCA", "fork_upstream", is_fork=True,
						  governance_status="pending_migration")
		for nombre in ("17.0", "18.0", "19.0"):
			self.env["repo.branch"].create({
				"repository_id": repo.id, "name": nombre, "role": "base",
				"protected": False, "protection_readable": True})

		self.env["repo.audit.engine"].evaluate(self.run)

		propios = self.run.finding_ids.filtered(lambda f: f.repository_id == repo)
		self.assertEqual(propios.mapped("finding_type"), ["fork_not_migrated"],
						 "no se evalúa el detalle hasta que se lo marque gobernado")

	# --- nivel cuenta ---

	def test_la_adopcion_de_convencion_es_un_hallazgo_de_cuenta(self):
		repo = self._repo("con-main", default_branch="main")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "main", "role": "other",
			"protection_readable": True, "protected": True})

		self.env["repo.audit.engine"].evaluate(self.run)

		adopcion = self._hallazgo("convention_adoption")
		self.assertTrue(adopcion)
		self.assertFalse(adopcion.repository_id, "va a nivel cuenta, no de un repo")
		self.assertEqual(adopcion.severity, "info")
		self.assertIn("main", adopcion.detail)
		# Y el repo concreto también tiene el suyo.
		self.assertTrue(self._hallazgo("default_branch_off_convention"))

	def test_sin_clasificar_es_un_hallazgo(self):
		self._repo("desconocido", clasificacion=False)

		self.env["repo.audit.engine"].evaluate(self.run)

		self.assertIn("classification_missing", self._tipos())

	# --- idempotencia del propio motor ---

	def test_reevaluar_no_duplica_hallazgos(self):
		repo = self._repo("cliente-tres")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "19.0", "role": "base",
			"protected": False, "protection_readable": True})

		self.env["repo.audit.engine"].evaluate(self.run)
		primera = len(self.run.finding_ids)
		self.env["repo.audit.engine"].evaluate(self.run)

		self.assertEqual(len(self.run.finding_ids), primera)
