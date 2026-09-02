# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El recorrido de lectura, contra respuestas de API mockeadas.

Los fixtures imitan la forma real de las respuestas de GitHub y usan nombres de la cuenta
primateuy, no ejemplos de manual.
"""
import uuid

from odoo.tests.common import TransactionCase

from .test_backend import RespuestaFalsa, _clave_rsa_de_prueba

# --- fixtures con la forma real de la API -------------------------------------

REPO_PRIVADO_SIN_ADMIN = {
	"id": 111, "name": "LocalizacionUy", "full_name": "primateuy/LocalizacionUy",
	"private": True, "fork": False, "default_branch": "17.0",
	"archived": False, "pushed_at": "2026-09-01T20:28:03Z",
	"description": "Localización uruguaya",
	# Sin admin: la protección NO se puede leer, y eso no es lo mismo que no tenerla.
	"permissions": {"admin": False, "maintain": False, "push": True},
}

REPO_FORK = {
	"id": 222, "name": "webOCA", "full_name": "primateuy/webOCA",
	"private": False, "fork": True, "default_branch": "17.0",
	"archived": False, "pushed_at": "2026-07-13T22:14:54Z",
	"parent": {"full_name": "OCA/web"},
	"permissions": {"admin": True, "maintain": True, "push": True},
}

BRANCHES = [
	{"name": "17.0", "protected": False, "commit": {"sha": "abc123"}},
	{"name": "17.0.Staging", "protected": False, "commit": {"sha": "def456"}},
	{"name": "feature/1234-algo", "protected": False, "commit": {"sha": "ghi789"}},
]

COLABORADORES = [
	{"login": "dyturralbe", "id": 1, "role_name": "write"},
	{"login": "primateuy", "id": 2, "role_name": "admin"},
]

COMMITS = [
	{"sha": "abc123", "author": {"login": "dyturralbe"},
	 "commit": {"message": "[ADD][2041] modelo nuevo\n\ndetalle",
				"committer": {"date": "2026-08-30T10:00:00Z"},
				"verification": {"verified": True, "reason": "valid"}}},
	{"sha": "def456", "author": {"login": "dyturralbe"},
	 "commit": {"message": "arreglo rapido",
				"committer": {"date": "2026-08-29T10:00:00Z"},
				"verification": {"verified": False, "reason": "unsigned"}}},
]

WORKFLOWS = {"workflows": [
	{"name": "tests", "path": ".github/workflows/tests.yml", "state": "active"},
	{"name": "pre-commit", "path": ".github/workflows/pre-commit.yml", "state": "active"},
]}


class TransporteAuditoria:
	"""Devuelve fixtures según la URL pedida, e imita la paginación (sin cabecera Link)."""

	def __init__(self, repos):
		self.repos = repos
		self.llamadas = []

	def post(self, url, headers=None, timeout=None):
		return RespuestaFalsa(201, {"token": "ghs_test"})

	def get(self, url, headers=None, timeout=None):
		self.llamadas.append(url)
		if "/installation/repositories" in url:
			# Igual que GitHub: la lista viene ENVUELTA, no como array suelto.
			return RespuestaFalsa(200, {
				"total_count": len(self.repos), "repositories": self.repos})
		if "/users/" in url and "/repos" in url:
			# El endpoint equivocado: sólo públicos. Si el módulo vuelve a usarlo, el
			# repo privado desaparece del enumerado y el test lo caza.
			return RespuestaFalsa(
				200, [r for r in self.repos if not r.get("private")])
		if "/branches?" in url or url.endswith("/branches"):
			return RespuestaFalsa(200, BRANCHES)
		if "/protection" in url:
			return RespuestaFalsa(404, {"message": "Not Found"})
		if "/collaborators" in url:
			return RespuestaFalsa(200, COLABORADORES)
		if "/pulls" in url:
			return RespuestaFalsa(200, [])
		if "/commits" in url:
			return RespuestaFalsa(200, COMMITS)
		if "/actions/workflows" in url:
			return RespuestaFalsa(200, WORKFLOWS)
		if "/rulesets" in url:
			return RespuestaFalsa(200, [])
		for repo in self.repos:
			if url.endswith("/repos/%s" % repo["full_name"]):
				return RespuestaFalsa(200, repo)
		return RespuestaFalsa(404, {"message": "Not Found"})


class TestSync(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Test %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected",
		})
		self.backend.private_key = self.clave
		self.transporte = TransporteAuditoria([REPO_PRIVADO_SIN_ADMIN, REPO_FORK])
		# Se inyecta el transporte en el cliente para no tocar GitHub.
		self.backend_client = lambda: self.backend.client(transport=self.transporte)

	def _sincronizar(self):
		"""Corre el enumerado y el sync de cada repo con el transporte falso."""
		Repo = self.env["repo.repository"]
		original = type(self.backend).client
		type(self.backend).client = lambda s, transport=None: original(
			s, transport=self.transporte)
		try:
			repos = Repo._sync_from_backend(self.backend)
			for repo in repos:
				repo._job_sync_repository(False)
			return repos
		finally:
			type(self.backend).client = original

	# --- idempotencia, criterio de aceptación del encargo ---

	def test_auditar_dos_veces_no_duplica(self):
		primera = self._sincronizar()
		conteos = {
			"repos": len(primera),
			"ramas": len(primera.mapped("branch_ids")),
			"colaboradores": len(primera.mapped("collaborator_ids")),
			"commits": len(primera.mapped("commit_sample_ids")),
			"workflows": len(primera.mapped("workflow_ids")),
		}
		segunda = self._sincronizar()
		self.assertEqual(len(segunda), conteos["repos"])
		self.assertEqual(len(segunda.mapped("branch_ids")), conteos["ramas"])
		self.assertEqual(len(segunda.mapped("collaborator_ids")), conteos["colaboradores"])
		self.assertEqual(len(segunda.mapped("commit_sample_ids")), conteos["commits"])
		self.assertEqual(len(segunda.mapped("workflow_ids")), conteos["workflows"])

	# --- el enumerado mira TODO lo que abarca la instalación ---

	def test_el_enumerado_incluye_los_privados(self):
		"""`/users/{login}/repos` devuelve sólo públicos: perdía los 31 privados de
		primateuy y la auditoría terminaba en verde igual. Se enumera por la instalación."""
		repos = self._sincronizar()

		self.assertEqual(len(repos), 2)
		self.assertIn("primateuy/LocalizacionUy", repos.mapped("full_name"),
					  "el repo privado tiene que estar en el enumerado")
		self.assertTrue(
			any("/installation/repositories" in u for u in self.transporte.llamadas),
			"el enumerado debe pedir /installation/repositories")
		self.assertFalse(
			any("/users/" in u and "/repos" in u for u in self.transporte.llamadas),
			"no se puede volver a enumerar por /users/{login}/repos: oculta los privados")

	def test_una_respuesta_envuelta_inesperada_no_pasa_como_vacia(self):
		"""Si GitHub cambia la forma de la respuesta, el recorrido falla y lo dice; no
		devuelve cero repos como si la cuenta estuviera vacía."""
		from odoo.addons.primate_repo_manager.models.github_client import GithubError

		class TransporteRaro(TransporteAuditoria):
			def get(self, url, headers=None, timeout=None):
				self.llamadas.append(url)
				if "/installation/repositories" in url:
					return RespuestaFalsa(200, {"total_count": 2, "repos": self.repos})
				return super().get(url, headers=headers, timeout=timeout)

		self.transporte = TransporteRaro([REPO_PRIVADO_SIN_ADMIN, REPO_FORK])
		with self.assertRaises(GithubError):
			self._sincronizar()

	# --- techo de plan en una lectura suelta ---

	def test_el_limite_de_plan_en_rulesets_no_tumba_el_repo(self):
		"""Un privado en plan free devuelve 403 «Upgrade» en /rulesets. Es un techo sobre
		esa lectura, no un repositorio inauditable: el resto se audita igual y la causa
		queda anotada. Antes el job entero moría y el repo salía como «no se pudo auditar»."""
		UPGRADE = {"message": "Upgrade to GitHub Pro or make this repository public "
							  "to enable this feature."}

		class TransportePlanFree(TransporteAuditoria):
			def get(self, url, headers=None, timeout=None):
				if "/rulesets" in url:
					self.llamadas.append(url)
					return RespuestaFalsa(403, UPGRADE)
				return super().get(url, headers=headers, timeout=timeout)

		self.transporte = TransportePlanFree([REPO_PRIVADO_SIN_ADMIN, REPO_FORK])
		repos = self._sincronizar()
		loca = repos.filtered(lambda r: r.name == "LocalizacionUy")

		self.assertEqual(loca.sync_state, "done",
						 "el repo se audita igual: el techo de plan es de una lectura")
		self.assertIn("rulesets", loca.unreadable_json or "")
		self.assertTrue(loca.branch_ids, "las ramas se leen aunque no se lean los rulesets")

	def test_sin_permiso_de_actions_el_repo_se_audita_igual(self):
		"""403 «Resource not accessible by integration» en /actions/workflows: le falta el
		permiso de Actions a la App. Es una lectura menos, no un repo perdido."""
		SIN_PERMISO = {"message": "Resource not accessible by integration"}

		class TransporteSinActions(TransporteAuditoria):
			def get(self, url, headers=None, timeout=None):
				if "/actions/workflows" in url:
					self.llamadas.append(url)
					return RespuestaFalsa(403, SIN_PERMISO)
				return super().get(url, headers=headers, timeout=timeout)

		self.transporte = TransporteSinActions([REPO_PRIVADO_SIN_ADMIN, REPO_FORK])
		repos = self._sincronizar()

		self.assertEqual(set(repos.mapped("sync_state")), {"done"})
		for repo in repos:
			self.assertIn("workflows", repo.unreadable_json or "")
		self.assertTrue(repos.mapped("branch_ids"),
						"lo leído antes del workflow no se pierde")

	# --- los tres estados de protección ---

	def test_sin_admin_la_proteccion_queda_como_no_legible(self):
		"""El caso que no puede colapsarse: 404 sin permiso NO es 'sin protección'."""
		repos = self._sincronizar()
		loca = repos.filtered(lambda r: r.name == "LocalizacionUy")
		rama = loca.branch_ids.filtered(lambda b: b.name == "17.0")

		self.assertEqual(len(rama), 1)
		self.assertFalse(rama.protection_readable,
						 "sin admin no se puede afirmar nada sobre la protección")
		self.assertIn("branch_protection", loca.unreadable_json or "")

	def test_con_admin_un_404_si_significa_sin_proteccion(self):
		repos = self._sincronizar()
		fork = repos.filtered(lambda r: r.name == "webOCA")
		rama = fork.branch_ids.filtered(lambda b: b.name == "17.0")

		self.assertEqual(len(rama), 1)
		self.assertTrue(rama.protection_readable)
		self.assertFalse(rama.protected)

	# --- lo que se persiste y lo que no ---

	def test_las_feature_branches_no_se_persisten(self):
		repos = self._sincronizar()
		nombres = repos.mapped("branch_ids.name")
		self.assertIn("17.0", nombres)
		self.assertIn("17.0.Staging", nombres)
		self.assertNotIn("feature/1234-algo", nombres,
						 "las ramas de trabajo son efímeras y serían ruido")

	def test_el_rol_de_las_ramas_sale_de_las_reglas(self):
		repos = self._sincronizar()
		ramas = repos.mapped("branch_ids").filtered(lambda b: b.name == "17.0.Staging")
		self.assertTrue(ramas, "la rama de staging tiene que persistirse")
		self.assertEqual(set(ramas.mapped("role")), {"staging"})

	# --- clasificación y forks ---

	def test_el_fork_se_clasifica_y_guarda_su_upstream(self):
		repos = self._sincronizar()
		fork = repos.filtered(lambda r: r.name == "webOCA")
		self.assertEqual(fork.classification, "fork_upstream")
		self.assertEqual(fork.upstream_full_name, "OCA/web")
		self.assertEqual(fork.governance_status, "pending_migration")

	def test_la_clasificacion_manual_sobrevive_a_una_auditoria(self):
		repos = self._sincronizar()
		loca = repos.filtered(lambda r: r.name == "LocalizacionUy")
		loca.write({"classification": "cliente", "classification_source": "manual"})

		self._sincronizar()

		self.assertEqual(loca.classification, "cliente",
						 "una auditoría no puede revertir lo que una persona fijó")

	# --- formato y firma ---

	def test_la_muestra_de_commits_evalua_formato_y_firma(self):
		repos = self._sincronizar()
		muestras = repos.mapped("commit_sample_ids")
		bueno = muestras.filtered(lambda c: c.sha == "abc123")[:1]
		malo = muestras.filtered(lambda c: c.sha == "def456")[:1]

		self.assertTrue(bueno.message_ok)
		self.assertTrue(bueno.signed)
		self.assertFalse(malo.message_ok, "«arreglo rapido» no cumple la convención")
		self.assertFalse(malo.signed)
		self.assertEqual(malo.signature_reason, "unsigned")

	# --- propuesta de checks con datos ---

	def test_la_propuesta_de_checks_sale_de_lo_que_corre_hoy(self):
		self._sincronizar()
		propuesta = self.env["repo.workflow"].propose_required_checks(self.backend)

		self.assertIn("fork_upstream", propuesta)
		candidatos = propuesta["fork_upstream"]["candidatos"]
		nombres = [c["workflow"] for c in candidatos]
		self.assertIn("tests", nombres)
		self.assertIn("pre-commit", nombres)
		# Trae los números para decidir, no una recomendación a ciegas.
		self.assertEqual(candidatos[0]["repos"], 1)
		self.assertEqual(candidatos[0]["cobertura"], 100.0)

	def test_traduce_el_vocabulario_de_roles_de_github(self):
		"""GitHub mezcla dos vocabularios: role_name dice "write", los permisos "push".

		Este test nace de un bug real: el sync reventaba con
		`Wrong value for repo.collaborator.permission: 'write'` y, como cada repo se
		sincroniza en su propio job que traga el error, la auditoría habría terminado
		"bien" con cero colaboradores relevados.
		"""
		Colaborador = self.env["repo.collaborator"]
		self.assertEqual(Colaborador.permission_from_role_name("write"), "push")
		self.assertEqual(Colaborador.permission_from_role_name("read"), "pull")
		self.assertEqual(Colaborador.permission_from_role_name("admin"), "admin")
		# Un rol desconocido cae al MÁS restrictivo: nunca conceder de más por descuido.
		self.assertEqual(Colaborador.permission_from_role_name("rol_nuevo_de_github"), "pull")

	def test_los_colaboradores_se_relevan_con_su_permiso(self):
		repos = self._sincronizar()
		loca = repos.filtered(lambda r: r.name == "LocalizacionUy")
		por_login = {c.member_id.github_login: c.permission for c in loca.collaborator_ids}

		self.assertEqual(por_login.get("dyturralbe"), "push")
		self.assertEqual(por_login.get("primateuy"), "admin")
