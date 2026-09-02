# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El motor de hallazgos.

Incluye los tres que el encargo pide demostrar: un permiso excedido, una rama sin
protección y un fork desfasado.
"""
import json
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

	# --- la cuenta dueña no se mide con la matriz de acceso ---

	def test_la_cuenta_duena_no_es_un_permiso_excedido(self):
		"""El admin de la cuenta dueña es inherente a la propiedad: no se puede bajar, y
		pedirlo como crítico manda a hacer algo que GitHub no permite."""
		repo = self._repo("del-dueno")
		duena = self.env["repo.member"].create(
			{"github_login": self.backend.owner_login})
		self.env["repo.collaborator"].create({
			"repository_id": repo.id, "member_id": duena.id, "permission": "admin"})

		self.env["repo.audit.engine"].evaluate(self.run)

		self.assertNotIn("permission_admin_exceeded", self._tipos())
		nota = self._hallazgo("owner_account_admin")
		self.assertTrue(nota, "el dato de que figura como colaboradora se conserva")
		self.assertEqual(nota.severity, "info")
		self.assertEqual(nota.remediation_action, "no_action_owner")
		self.assertFalse(nota.is_destructive)

	def test_un_colaborador_que_no_es_el_dueno_sigue_siendo_critico(self):
		"""La exención es para la cuenta dueña y sólo para ella."""
		repo = self._repo("de-otro")
		otro = self.env["repo.member"].create({"github_login": "alguien-mas"})
		self.env["repo.collaborator"].create({
			"repository_id": repo.id, "member_id": otro.id, "permission": "admin"})

		self.env["repo.audit.engine"].evaluate(self.run)

		self.assertEqual(self._hallazgo("permission_admin_exceeded").severity, "critical")

	def test_la_cuenta_duena_no_pide_vincular_empleado(self):
		"""Detrás de la cuenta institucional no hay un empleado: el consejo no aplica."""
		self.env["repo.member"].create({"github_login": self.backend.owner_login})
		self.env["repo.member"].create({"github_login": "una-persona"})

		self.env["repo.audit.engine"].evaluate(self.run)

		institucional = self._hallazgo("institutional_account")
		self.assertEqual(institucional.subject, self.backend.owner_login)
		self.assertEqual(institucional.severity, "info")
		self.assertEqual(institucional.remediation_action, "no_action_owner")
		sin_empleado = self._hallazgo("member_without_employee").mapped("subject")
		self.assertIn("una-persona", sin_empleado,
					  "las personas de verdad se siguen reportando")
		self.assertNotIn(self.backend.owner_login, sin_empleado)

	# --- el resumen tiene que cerrar con la tabla ---

	def test_el_conteo_de_main_habla_de_la_poblacion_que_se_evalua(self):
		"""Contar main/master sobre TODOS y flaggear sólo los evaluados daba dos números
		distintos para el mismo hecho, y el lector no sabía cuál creer."""
		evaluado = self._repo("evaluado-con-main", default_branch="main")
		self.env["repo.branch"].create({
			"repository_id": evaluado.id, "name": "main", "role": "other",
			"protection_readable": True, "protected": True})
		self._repo("sin-clasificar-con-main", clasificacion=False, default_branch="main")

		self.env["repo.audit.engine"].evaluate(self.run)

		flaggeados = self._hallazgo("default_branch_off_convention")
		self.assertEqual(len(flaggeados), 1, "sólo el evaluado contra plantilla")
		adopcion = self._hallazgo("convention_adoption")
		observado = json.loads(adopcion.observed_json)
		self.assertEqual(observado["default_off_convention"],
						 ["cuenta/evaluado-con-main"])
		self.assertEqual(observado["default_main_not_evaluated"],
						 ["cuenta/sin-clasificar-con-main"])
		self.assertIn("1 más", adopcion.detail,
					  "los no evaluados se dicen aparte, no se esconden")

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

	# --- coherencia del informe ---

	def test_el_resumen_suma_todos_los_hallazgos_sin_excepciones(self):
		"""El conteo del resumen tiene que dar el total. Sin asteriscos.

		Un lector que suma las severidades y no llega al total de hallazgos deja de
		confiar en el resto del documento, y con razón: si esa cuenta no cierra, no hay
		motivo para creerle a las demás.
		"""
		repo = self._repo("cliente-suma")
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "19.0", "role": "base",
			"protected": False, "protection_readable": True})
		self._repo("roto-suma", sync_state="error", sync_error="403 sin acceso")
		ilegible = self._repo("ilegible-suma")
		self.env["repo.branch"].create({
			"repository_id": ilegible.id, "name": "19.0", "role": "base",
			"protection_readable": False, "protection_cause": "plan_limit"})

		self.env["repo.audit.engine"].evaluate(self.run)

		suma = sum(fila["count"] for fila in self.run._report_severity_summary())
		self.assertEqual(
			suma, len(self.run.finding_ids),
			"el resumen tiene que contar TODOS los hallazgos, incluidos los que se "
			"detallan en secciones propias")

	def test_los_que_van_aparte_se_declaran(self):
		self._repo("roto-aparte", sync_state="error", sync_error="403")

		self.env["repo.audit.engine"].evaluate(self.run)

		self.assertTrue(self.run._report_aside_total(),
						"el resumen tiene que poder decir cuántos se desarrollan aparte")

	def test_los_ilegibles_se_agrupan_por_repositorio(self):
		"""El número que importa es cuántos repos quedan fuera de control, no cuántas ramas."""
		repo = self._repo("multi-rama")
		for nombre in ("17.0", "18.0", "19.0"):
			self.env["repo.branch"].create({
				"repository_id": repo.id, "name": nombre, "role": "base",
				"protection_readable": False, "protection_cause": "plan_limit"})

		self.env["repo.audit.engine"].evaluate(self.run)

		filas = self.run._report_unreadable("plan_limit")
		self.assertEqual(len(filas), 1, "tres ramas de un repo son UN repositorio")
		self.assertEqual(filas[0]["count"], 3)

	def test_la_cobertura_cuenta_tambien_los_repos_que_no_se_evaluan(self):
		"""«¿De cuántos repos no sabemos si están protegidos?» no depende de si los
		comparamos contra una plantilla. Contado desde los hallazgos daba 4 de 30, y ese
		número es el insumo de la decisión de plan."""
		evaluado = self._repo("evaluado")
		self.env["repo.branch"].create({
			"repository_id": evaluado.id, "name": "19.0", "role": "base",
			"protection_readable": False, "protection_cause": "plan_limit"})
		sin_clasificar = self._repo("sin-clasificar", clasificacion=False)
		self.env["repo.branch"].create({
			"repository_id": sin_clasificar.id, "name": "19.0", "role": "base",
			"protection_readable": False, "protection_cause": "plan_limit"})

		self.env["repo.audit.engine"].evaluate(self.run)

		# El hallazgo por rama sigue siendo sólo del evaluado: no hay plantilla contra la
		# cual medir al otro, y eso está bien.
		self.assertEqual(
			self._hallazgo("branch_protection_unreadable").mapped("repository_id"),
			evaluado)
		# La cobertura, en cambio, tiene que hablar de los dos.
		filas = self.run._report_unreadable("plan_limit")
		self.assertEqual(
			sorted(f["repository"].full_name for f in filas),
			["cuenta/evaluado", "cuenta/sin-clasificar"])

	def test_el_motivo_del_repo_no_auditado_esta_en_lenguaje_del_informe(self):
		self._repo("sin-acceso", sync_state="error",
				   sync_error="GitHub 403: Resource not accessible by integration")

		self.env["repo.audit.engine"].evaluate(self.run)

		fila = self.run._report_unaudited()[0]
		self.assertIn("no tiene acceso", fila["reason"])
		self.assertIn("permisos", fila["reason"])
		self.assertIn("403", fila["technical"], "el error técnico se conserva entre paréntesis")

	def test_ninguna_remediacion_esta_reciclada_de_otro_tipo(self):
		"""Cada tipo tiene la acción que le corresponde, no la del vecino."""
		from ..models.repo_audit_finding import REMEDIATION_BY_TYPE

		self.assertEqual(
			REMEDIATION_BY_TYPE["commit_format_violations"], "enforce_commit_convention",
			"el formato de commits no se arregla con reglas de protección de rama")
		self.assertEqual(REMEDIATION_BY_TYPE["signed_commits_missing"], "configure_signing")
		self.assertEqual(REMEDIATION_BY_TYPE["repo_sync_error"], "check_app_access")
		# apply_ruleset queda sólo donde de verdad se aplica un ruleset de protección.
		con_ruleset = [t for t, a in REMEDIATION_BY_TYPE.items() if a == "apply_ruleset"]
		self.assertEqual(con_ruleset, ["branch_unprotected"])
