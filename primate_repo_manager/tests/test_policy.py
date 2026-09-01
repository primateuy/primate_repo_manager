# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Las cuatro plantillas, contra las decisiones escritas de la spec.

Cada aserción acá corresponde a una línea de la spec, y está para que un cambio de valor
no pase inadvertido: si alguien baja las aprobaciones de producción de 2 a 1, el test se
pone rojo en ese commit y no seis meses después.
"""
from odoo.tests.common import TransactionCase


class TestPolicyTemplates(TransactionCase):

	def _plantilla(self, code):
		return self.env["repo.policy.template"].search([("code", "=", code)], limit=1)

	def test_las_cuatro_plantillas_existen(self):
		for code in ("cliente-estandar", "localizacion", "interno", "fork-upstream"):
			self.assertTrue(self._plantilla(code), code)

	# --- §4.3 tabla de plantillas ---

	def test_cliente_estandar_una_aprobacion_en_base_dos_en_prod(self):
		t = self._plantilla("cliente-estandar")
		self.assertEqual(t.rule_for_role("base")["required_approvals"], 1)
		self.assertEqual(t.rule_for_role("prod")["required_approvals"], 2)

	def test_staging_y_support_heredan_base(self):
		"""Decisión tomada: heredan PR + 1 aprobación, sin override propio."""
		t = self._plantilla("cliente-estandar")
		for rol in ("staging", "support"):
			regla = t.rule_for_role(rol)
			self.assertTrue(regla["heredada"], rol)
			self.assertTrue(regla["require_pr"], rol)
			self.assertEqual(regla["required_approvals"], 1, rol)

	def test_localizacion_es_la_mas_estricta(self):
		t = self._plantilla("localizacion")
		self.assertTrue(t.require_codeowner_review)
		self.assertTrue(t.require_signed_commits)
		prod = t.rule_for_role("prod")
		self.assertEqual(prod["required_approvals"], 2)
		self.assertTrue(prod["require_codeowner_review"])

	def test_interno_exige_pr_pero_no_aprobaciones(self):
		"""Resolución de la contradicción de la spec: trazabilidad y CI sí, espera no."""
		t = self._plantilla("interno")
		self.assertTrue(t.require_pr)
		self.assertEqual(t.required_approvals, 0)
		self.assertFalse(t.require_signed_commits)

	def test_la_firma_solo_esta_activa_en_localizacion(self):
		"""§9: el rollout arranca por localización; activarla antes bloquearía gente."""
		activas = [
			t.code for t in self.env["repo.policy.template"].search([])
			if t.require_signed_commits
		]
		self.assertEqual(activas, ["localizacion"])

	# --- §5 forks ---

	def test_la_rama_espejo_bloquea_el_push_de_humanos(self):
		t = self._plantilla("fork-upstream")
		espejo = t.rule_for_role("mirror")
		self.assertTrue(espejo["block_human_push"])
		self.assertFalse(espejo["require_pr"])

	def test_la_rama_de_parches_lleva_flujo_normal(self):
		t = self._plantilla("fork-upstream")
		parches = t.rule_for_role("patch")
		self.assertTrue(parches["require_pr"])
		self.assertEqual(parches["required_approvals"], 1)

	# --- lo que NO está decidido ---

	def test_ningun_check_requerido_esta_definido_todavia(self):
		"""La spec los hace obligatorios pero no nombra ninguno.

		Inventar un nombre acá sería peor que dejarlo vacío: en un ruleset, un check que
		no existe bloquea TODOS los merges del repo para siempre.
		"""
		for t in self.env["repo.policy.template"].search([]):
			self.assertFalse(t.status_checks_defined, t.code)
			self.assertFalse(t.required_check_ids, t.code)

	# --- patrones de la decisión 6 ---

	def test_el_patron_de_commit_es_el_de_la_convencion(self):
		for code in ("cliente-estandar", "localizacion", "interno", "fork-upstream"):
			t = self._plantilla(code)
			self.assertEqual(t.commit_message_pattern, r"^\[(ADD|IMP|FIX)\]\[\d+\] .+", code)

	def test_el_patron_de_commit_acepta_lo_que_debe_y_rechaza_lo_que_no(self):
		muestra = self.env["repo.commit.sample"]
		patron = self._plantilla("cliente-estandar").commit_message_pattern
		self.assertTrue(muestra.message_matches("[ADD][2041] modelo de backend", patron))
		self.assertTrue(muestra.message_matches("[FIX][7] corrige el sync", patron))
		# Los de esta misma conversación, que NO cumplen: sin número de ticket.
		self.assertFalse(muestra.message_matches("[ADD] esqueleto del módulo", patron))
		self.assertFalse(muestra.message_matches("arreglo rápido", patron))
		self.assertFalse(muestra.message_matches("[WIP][12] a medio hacer", patron))


class TestPolicyAccess(TransactionCase):

	def test_el_permiso_maximo_por_defecto_es_push(self):
		t = self.env["repo.policy.template"].search([("code", "=", "cliente-estandar")])
		miembro = self.env["repo.member"].create({"github_login": "alguien-test"})
		self.assertEqual(t.max_permission_for(miembro), "push")

	def test_una_excepcion_declarada_manda_sobre_el_default(self):
		t = self.env["repo.policy.template"].search([("code", "=", "cliente-estandar")])
		miembro = self.env["repo.member"].create({"github_login": "lider-test"})
		self.env["repo.policy.access.rule"].create({
			"template_id": t.id, "member_id": miembro.id,
			"max_permission": "admin", "reason": "líder técnico",
		})
		self.assertEqual(t.max_permission_for(miembro), "admin")

	def test_la_escala_de_permisos_ordena_bien(self):
		"""Es la que decide si un permiso observado excede al esperado."""
		Colaborador = self.env["repo.collaborator"]
		self.assertGreater(Colaborador.level_of("admin"), Colaborador.level_of("push"))
		self.assertGreater(Colaborador.level_of("push"), Colaborador.level_of("pull"))
		self.assertEqual(Colaborador.level_of("inventado"), -1)
