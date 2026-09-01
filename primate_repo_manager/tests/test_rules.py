# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Las heurísticas, contra nombres REALES de la cuenta primateuy.

Los casos no son inventados: salen de leer 503 ramas de 40 repos el 1-sep-2026. Un test
con nombres de laboratorio (`main`, `develop`, `release`) habría pasado sin encontrar
ninguno de los problemas que estos fijan.
"""
from odoo.tests.common import TransactionCase


class TestBranchRoleRules(TransactionCase):

	def _rol(self, nombre):
		return self.env["repo.branch.role.rule"].role_for(nombre)

	def test_las_tres_grafias_de_staging_conviven(self):
		"""En los repos reales conviven `.staging`, `_staging` y `.Staging`."""
		for nombre in ("17.0.staging", "17.0_staging", "17.0.Staging", "19.0.Staging"):
			self.assertEqual(self._rol(nombre), "staging", nombre)

	def test_staging_con_sufijo_y_sin_version(self):
		self.assertEqual(self._rol("19.0.Staging_12082026_1036"), "staging")
		self.assertEqual(self._rol("19.0_staging_fix_warnings"), "staging")
		self.assertEqual(self._rol("staging-uruguay"), "staging")

	def test_produccion_en_espanol(self):
		"""La única rama de producción encontrada está en español, no en inglés."""
		self.assertEqual(self._rol("17.0.Produccion"), "prod")

	def test_product_domain_no_es_produccion(self):
		"""LA TRAMPA. Un patrón de `prod` sin anclar clasificaría esto como producción.

		`17.0.product_domain` existe de verdad en los repos, y es una rama de trabajo.
		Marcarla como producción le pondría expectativas de doble aprobación a una rama
		cualquiera, y el informe señalaría un incumplimiento que no existe.
		"""
		self.assertEqual(self._rol("17.0.product_domain"), "version")

	def test_support_con_segmento_en_mayusculas(self):
		self.assertEqual(self._rol("17.0.PRIMATE_support"), "support")

	def test_support_staging_gana_staging(self):
		"""Decisión tomada: el rol determina las protecciones esperadas, y esa rama se
		comporta como staging. `support` ahí es linaje, no rol."""
		self.assertEqual(self._rol("17.0_support_staging"), "staging")

	def test_ramas_base_y_de_trabajo(self):
		self.assertEqual(self._rol("17.0"), "base")
		self.assertEqual(self._rol("19.0"), "base")
		self.assertEqual(self._rol("17.0_pos_voucher"), "version")
		self.assertEqual(self._rol("feature/pos-mercadopago-updates"), "other")
		self.assertEqual(self._rol("main"), "other")


class TestClassificationRules(TransactionCase):

	def _clasificar(self, **datos):
		base = {"name": "x", "fork": False, "private": False}
		base.update(datos)
		return self.env["repo.classification.rule"].classify(base)

	def test_un_fork_se_clasifica_como_fork(self):
		self.assertEqual(self._clasificar(name="webOCA", fork=True), "fork_upstream")

	def test_el_fork_gana_sobre_el_nombre(self):
		"""60 de 94 repos son forks: es la señal más confiable y va primero."""
		self.assertEqual(
			self._clasificar(name="LocalizacionUy", fork=True), "fork_upstream")

	def test_localizacion_por_nombre(self):
		self.assertEqual(self._clasificar(name="LocalizacionUy"), "localizacion")

	def test_herramienta_interna(self):
		for nombre in ("primate_IA_hub", "primate_repo_manager", "PCM-algo"):
			self.assertEqual(self._clasificar(name=nombre), "interno", nombre)

	def test_lo_no_reconocido_queda_sin_clasificar(self):
		"""A propósito NO hay catch-all: sin clasificar es un finding de la auditoría.

		Adivinar "cliente" por descarte escondería justamente lo que hay que revisar.
		"""
		self.assertFalse(self._clasificar(name="grupofernandez"))
		self.assertFalse(self._clasificar(name="motosrack"))
