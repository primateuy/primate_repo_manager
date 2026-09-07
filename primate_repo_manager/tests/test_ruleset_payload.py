# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La traducción de plantilla a ruleset, que todavía no escribe nada.

Los valores se arman en el test —no se leen de la base— por la misma razón que en
`test_policy.py`: las plantillas instaladas son configuración y el usuario puede
cambiarlas legítimamente. Acá se prueba la TRADUCCIÓN, no los valores de fábrica.
"""
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.primate_repo_manager.models.repo_ruleset import nombre_de_ruleset


class TestRulesetPayload(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Rulesets %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox",
			"write_app_id": "4808079", "write_installation_id": "9",
		})
		# La clasificación tiene que quedar libre ANTES de crear la plantilla del test.
		# `plantilla_efectiva()` busca por clasificación con limit=1, y la plantilla de
		# fábrica `cliente-estandar` ya ocupa «cliente»: sin esto el test escribe una
		# plantilla y verifica la traducción de OTRA, que es la forma más silenciosa de
		# que un test verde no pruebe nada.
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "De prueba", "code": "prueba-%s" % uuid.uuid4().hex[:6],
			"classification_default": "cliente",
			"require_pr": True, "required_approvals": 1,
			"block_force_push": True, "block_deletion": True,
		})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "un-repo", "full_name": "cuenta/un-repo",
			"classification": "cliente",
		})
		self.rama = self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": "19.0", "role": "base",
		})
		self.builder = self.env["repo.ruleset.builder"]

	def _payload(self, rol="base"):
		salida = [p for p in self.builder.payloads_for_repository(self.repo)
				  if p["role"] == rol]
		self.assertTrue(salida, "no se armó ruleset para el rol %s" % rol)
		return salida[0]

	def _reglas(self, payload):
		return {r["type"]: r.get("parameters", {}) for r in payload["payload"]["rules"]}

	# ------------------------------------------------------------------
	# Lo que la plantilla declara, traducido
	# ------------------------------------------------------------------

	def test_exigir_pr_viaja_con_el_numero_de_aprobaciones_declarado(self):
		self.plantilla.required_approvals = 2
		reglas = self._reglas(self._payload())
		self.assertIn("pull_request", reglas)
		self.assertEqual(reglas["pull_request"]["required_approving_review_count"], 2)

	def test_las_tres_claves_que_la_plantilla_no_modela_van_en_no_exigido(self):
		"""False significa «esta política no lo exige», nunca «lo exigimos por defecto»."""
		parametros = self._reglas(self._payload())["pull_request"]
		for clave in ("dismiss_stale_reviews_on_push", "require_last_push_approval",
					  "required_review_thread_resolution"):
			self.assertFalse(parametros[clave], clave)

	def test_force_push_borrado_y_firma_se_traducen_cada_uno_a_su_regla(self):
		self.plantilla.require_signed_commits = True
		reglas = self._reglas(self._payload())
		self.assertIn("non_fast_forward", reglas)
		self.assertIn("deletion", reglas)
		self.assertIn("required_signatures", reglas)

	def test_lo_que_la_plantilla_no_exige_no_aparece_como_regla(self):
		self.plantilla.write({
			"require_pr": False, "block_force_push": False,
			"block_deletion": False, "require_signed_commits": False,
			"commit_message_pattern": False,
		})
		self.assertEqual(self._reglas(self._payload()), {})

	def test_el_override_por_rol_le_gana_a_la_regla_general(self):
		self.env["repo.policy.branch.rule"].create({
			"template_id": self.plantilla.id, "branch_role": "prod",
			"require_pr": True, "required_approvals": 2,
		})
		self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": "produccion", "role": "prod",
		})
		self.assertEqual(
			self._reglas(self._payload("prod"))["pull_request"]
			["required_approving_review_count"], 2)
		self.assertEqual(
			self._reglas(self._payload("base"))["pull_request"]
			["required_approving_review_count"], 1)

	# ------------------------------------------------------------------
	# Los checks: la guarda que evita bloquear todos los merges
	# ------------------------------------------------------------------

	def test_sin_checks_confirmados_el_ruleset_sale_sin_checks_y_lo_dice(self):
		self.env["repo.policy.status.check"].create({
			"template_id": self.plantilla.id, "name": "no-confirmado"})
		self.plantilla.status_checks_defined = False
		payload = self._payload()
		self.assertNotIn("required_status_checks", self._reglas(payload))
		self.assertTrue(any("checks" in aviso for aviso in payload["no_traducido"]),
						"tiene que decir por qué salió sin checks")

	def test_con_checks_confirmados_viajan_con_el_nombre_exacto(self):
		self.env["repo.policy.status.check"].create({
			"template_id": self.plantilla.id, "name": "build (19.0)"})
		self.plantilla.status_checks_defined = True
		parametros = self._reglas(self._payload())["required_status_checks"]
		self.assertEqual(
			[c["context"] for c in parametros["required_status_checks"]], ["build (19.0)"])

	# ------------------------------------------------------------------
	# Las condiciones: ramas observadas, no patrones inventados
	# ------------------------------------------------------------------

	def test_las_condiciones_nombran_las_ramas_observadas_una_por_una(self):
		self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": "17.0", "role": "base"})
		incluidas = self._payload()["payload"]["conditions"]["ref_name"]["include"]
		self.assertEqual(sorted(incluidas), ["refs/heads/17.0", "refs/heads/19.0"])

	def test_un_rol_sin_ramas_observadas_no_genera_ruleset(self):
		"""Un ruleset sin condiciones no protege nada y ensucia el repositorio."""
		roles = [p["role"] for p in self.builder.payloads_for_repository(self.repo)]
		self.assertEqual(roles, ["base"])

	def test_el_patron_de_nombre_de_rama_no_entra_en_el_ruleset_del_rol(self):
		self.plantilla.branch_name_pattern = r"^(feature|fix)\/\d+-[a-z0-9-]+$"
		payload = self._payload()
		self.assertNotIn("branch_name_pattern", self._reglas(payload))
		self.assertTrue(any("nombre de rama" in aviso for aviso in payload["no_traducido"]))

	def test_el_nombre_del_ruleset_es_estable_y_lleva_el_prefijo(self):
		payload = self._payload()
		esperado = nombre_de_ruleset(self.plantilla.code, "base")
		self.assertEqual(payload["name"], esperado)
		self.assertEqual(payload["payload"]["name"], esperado)
		self.assertTrue(esperado.startswith("primate/"))

	# ------------------------------------------------------------------
	# El bypass sale de la conexión
	# ------------------------------------------------------------------

	def test_el_actor_exento_es_la_app_de_escritura_de_esa_conexion(self):
		exentos = self._payload()["payload"]["bypass_actors"]
		self.assertEqual(exentos, [{
			"actor_id": 4808079, "actor_type": "Integration", "bypass_mode": "always"}])

	def test_otra_conexion_exime_a_otra_app(self):
		"""Escrito a mano, el sandbox eximiría a la App de producción."""
		self.backend.write_app_id = "4811232"
		self.assertEqual(
			self._payload()["payload"]["bypass_actors"][0]["actor_id"], 4811232)

	def test_sin_app_de_escritura_no_se_arma_el_ruleset(self):
		"""Un ruleset sin exención aplica bien y frena el apply siguiente."""
		self.backend.write_app_id = False
		with self.assertRaises(UserError):
			self.builder.payloads_for_repository(self.repo)

	def test_un_app_id_no_numerico_se_rechaza(self):
		self.backend.write_app_id = "prm-writer"
		with self.assertRaises(UserError):
			self.builder.payloads_for_repository(self.repo)

	# ------------------------------------------------------------------
	# Lo que no traduce se ve
	# ------------------------------------------------------------------

	def test_las_ramas_de_fork_se_devuelven_apagadas_y_no_desaparecen(self):
		self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": "upstream/19.0", "role": "mirror"})
		espejo = [p for p in self.builder.payloads_for_repository(self.repo)
				  if p["role"] == "mirror"]
		self.assertTrue(espejo, "el rol espejo tiene que verse, aunque no se traduzca")
		self.assertIsNone(espejo[0]["payload"])
		self.assertTrue(espejo[0]["no_traducido"])

	def test_un_repositorio_sin_clasificacion_no_produce_nada(self):
		self.repo.classification = False
		self.assertEqual(self.builder.payloads_for_repository(self.repo), [])

	# ------------------------------------------------------------------
	# La propiedad que define este paso: no escribe
	# ------------------------------------------------------------------

	def test_armar_el_payload_no_deja_rastro_en_la_bitacora(self):
		"""B1.1 es traducción. Si esto escribe algo, dejó de ser una función pura."""
		antes = self.env["repo.audit.log"].search_count([])
		self.builder.payloads_for_repository(self.repo)
		self.builder.payloads_for_repository(self.repo)
		self.assertEqual(self.env["repo.audit.log"].search_count([]), antes)

	def test_dos_llamadas_seguidas_dan_exactamente_lo_mismo(self):
		self.assertEqual(self.builder.payloads_for_repository(self.repo),
						 self.builder.payloads_for_repository(self.repo))
