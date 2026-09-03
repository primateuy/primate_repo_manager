# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El componente de avance en vivo, recorrido en un navegador de verdad.

POR QUÉ HAY UN TEST DE NAVEGADOR Y NO ALCANZAN LOS DE `test_avance_vivo`. Aquéllos prueban
que el servidor emita lo que tiene que emitir, y lo prueban bien. Los dos defectos que
dejaron la pantalla muda en el primer recorrido real eran de MONTAJE del componente —el
estado copiado en `setup()`, que corre una sola vez; la suscripción atada al id que el
registro tenía al montar, que en un formulario nuevo todavía no existe— y ninguno de los
dos es observable desde el servidor. El bus emitía, los tests pasaban, el bundle
compilaba, y en pantalla no había nada.

De ahí la regla del proyecto: nada visual se da por hecho sin abrirlo en un navegador.
Este test es esa regla hecha código.
"""
import uuid

from odoo.tests import HttpCase, tagged

from .test_backend import _clave_rsa_de_prueba


@tagged("post_install", "-at_install")
class TestTourAvanceVivo(HttpCase):

	def setUp(self):
		super().setUp()
		clave = _clave_rsa_de_prueba()
		self.backend = self.env["repo.backend"].create({
			"name": "GitHub — tour",
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox",
		})
		self.backend.private_key = clave

		Repo = self.env["repo.repository"]
		self.repos = Repo.browse()
		for n, estado in (("sbx-uno", "running"), ("sbx-dos", "pending"),
						  ("sbx-tres", "pending")):
			self.repos |= Repo.create({
				"backend_id": self.backend.id,
				"full_name": "%s/%s" % (self.backend.owner_login, n),
				"name": n, "github_id": uuid.uuid4().hex[:8], "sync_state": estado,
			})

		self.run_ = self.env["repo.audit.run"].create({
			"name": "Corrida del tour", "backend_id": self.backend.id,
		})
		self.run_.write({
			"state": "running", "repos_total": 3, "repos_done": 0, "repos_error": 0,
		})
		# Dos hallazgos: el resumen del cierre tiene que decir «2 hallazgos», y la lista
		# tiene que mostrar el texto y no una columna de ids.
		Finding = self.env["repo.audit.finding"]
		Finding.create({
			"run_id": self.run_.id, "repository_id": self.repos[0].id,
			"finding_type": "branch_unprotected", "severity": "high",
			"summary": "rama sin protección efectiva",
		})
		Finding.create({
			"run_id": self.run_.id, "repository_id": self.repos[1].id,
			"finding_type": "classification_missing", "severity": "info",
			"summary": "sin clasificar",
		})

		# El tour necesita entrar. `base.user_admin` existe en toda base de Odoo; acá está
		# desactivado, así que se lo despierta para el test. Todo esto vive dentro de la
		# transacción del test y se deshace al terminar.
		self.admin = self.env.ref("base.user_admin")
		self.admin.write({
			"active": True, "password": "admin",
			"group_ids": [(4, self.env.ref(
				"primate_repo_manager.group_repo_admin").id),
				(4, self.env.ref("primate_repo_manager.group_repo_lead").id),
				(4, self.env.ref("primate_repo_manager.group_repo_reader").id)],
		})

	def test_la_pantalla_muestra_el_avance_y_el_error_sin_recargar(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_audit_run/%s" % self.run_.id,
			"prm_live_progress", login="admin")

	def test_una_corrida_creada_con_nuevo_tambien_recibe_avisos(self):
		"""El recorrido exacto que falló la primera vez. Ver el comentario del tour."""
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_audit_run",
			"prm_live_progress_nuevo", login="admin")


@tagged("post_install", "-at_install")
class TestTourRepositorio(HttpCase):
	"""El tramo de lectura: repositorio, sus datos, su clasificación y sus hallazgos."""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "GitHub — tour repo",
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox",
		})
		self.backend.private_key = _clave_rsa_de_prueba()
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "name": "sbx-uno",
			"full_name": "%s/sbx-uno" % self.backend.owner_login,
			"github_id": uuid.uuid4().hex[:8], "visibility": "private",
			"default_branch": "19.0",
		})
		self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": "19.0", "role": "base",
			"is_default": True, "protected": False, "protection_readable": True,
		})
		miembro = self.env["repo.member"].create({"github_login": "alguien"})
		self.env["repo.collaborator"].create({
			"repository_id": self.repo.id, "member_id": miembro.id,
			"permission": "admin", "source": "direct",
		})
		corrida = self.env["repo.audit.run"].create({
			"name": "Corrida del tour", "backend_id": self.backend.id, "state": "done"})
		self.env["repo.audit.finding"].create({
			"run_id": corrida.id, "repository_id": self.repo.id,
			"finding_type": "branch_unprotected", "severity": "high",
			"summary": "rama sin protección efectiva",
		})

		self.env.ref("base.user_admin").write({
			"active": True, "password": "admin",
			"group_ids": [(4, self.env.ref(
				"primate_repo_manager.group_repo_admin").id),
				(4, self.env.ref("primate_repo_manager.group_repo_lead").id),
				(4, self.env.ref("primate_repo_manager.group_repo_reader").id)],
		})

	def test_el_camino_de_lectura_no_tiene_callejones(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_repository",
			"prm_repositorio", login="admin")


@tagged("post_install", "-at_install")
class TestTourPolitica(HttpCase):
	"""Política y personas: que la consecuencia se vea desde la aplicación."""

	def setUp(self):
		super().setUp()
		backend = self.env["repo.backend"].create({
			"name": "GitHub — tour política",
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox",
		})
		backend.private_key = _clave_rsa_de_prueba()
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "Plantilla del tour", "code": "tour-%s" % uuid.uuid4().hex[:6],
			"classification_default": "interno", "required_approvals": 2,
		})
		for n in range(2):
			self.env["repo.repository"].create({
				"backend_id": backend.id, "name": "sbx-int-%s" % n,
				"full_name": "%s/sbx-int-%s" % (backend.owner_login, n),
				"github_id": uuid.uuid4().hex[:8], "classification": "interno",
			})
		self.persona = self.env["repo.member"].create({
			"github_login": "sin-duenio", "name": "Nadie Todavía"})
		# No se crean empleados: crear uno arrastra un partner, y en esta base eso no se
		# puede dentro de un test. Ver el docstring de TestPropuestaDeEmpleado.
		self.empleado = self.env["hr.employee"].search([], limit=1)
		self.assertTrue(self.empleado, "la base necesita al menos un empleado")
		self.empleado.name = "Empleado Del Tour"

		self.env.ref("base.user_admin").write({
			"active": True, "password": "admin",
			"group_ids": [(4, self.env.ref(
				"primate_repo_manager.group_repo_admin").id),
				(4, self.env.ref("primate_repo_manager.group_repo_lead").id),
				(4, self.env.ref("primate_repo_manager.group_repo_reader").id)],
		})

	def test_un_cambio_de_politica_se_ve_en_la_bitacora_desde_la_aplicacion(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_policy_template",
			"prm_politica", login="admin")

	def test_vincular_una_cuenta_hace_desaparecer_el_aviso(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_member",
			"prm_personas", login="admin")
