# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B2 · la propuesta de checks requeridos, y por qué NO sale de los workflows.

MEDIDO CONTRA LA CUENTA REAL EL 7-SEP-2026: de 113 repositorios, 17 declaran workflows en
un archivo yml y **0** produjeron jamás un check run. La propuesta que dejó F1 habría
ofrecido «pre-commit» y «tests» —los nombres de esos yml— y exigirlos habría bloqueado
todos los merges de esos 17, para siempre, esperando checks que nadie reporta.
"""
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPropuestaDeChecks(TransactionCase):

	def setUp(self):
		super().setUp()
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		self.env.flush_all()
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "Clientes", "code": "cli-%s" % uuid.uuid4().hex[:6],
			"classification_default": "cliente",
		})
		self.backend = self.env["repo.backend"].create({
			"name": "Checks %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})

	def _repo(self, checks=(), workflows=()):
		repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "r-%s" % uuid.uuid4().hex[:6],
			"full_name": "org/r-%s" % uuid.uuid4().hex[:6],
			"classification": "cliente", "default_branch": "19.0",
		})
		for nombre in checks:
			self.env["repo.check.context"].upsert(repo, nombre, "success")
		for nombre in workflows:
			self.env["repo.workflow"].create({
				"repository_id": repo.id, "name": nombre,
				"path": ".github/workflows/%s.yml" % nombre})
		return repo

	# ------------------------------------------------------------------
	# La guarda que da nombre al bloque
	# ------------------------------------------------------------------

	def test_un_workflow_declarado_NO_es_un_candidato(self):
		"""El nombre del workflow no es el que el ruleset exige. Es la advertencia
		original por la que este hueco se dejó abierto."""
		self._repo(workflows=("pre-commit", "tests"))
		propuesta = self.plantilla.candidatos_de_check()
		self.assertEqual(propuesta["candidatos"], [])
		self.assertEqual(propuesta["con_workflows"], 1)
		self.assertEqual(propuesta["con_checks"], 0)

	def test_la_propuesta_vieja_de_F1_ya_no_se_puede_usar(self):
		"""Proponía nombres de workflow: aplicar eso bloquea todos los merges."""
		with self.assertRaises(UserError):
			self.env["repo.workflow"].propose_required_checks()

	def test_solo_entra_lo_que_GITHUB_reporto(self):
		self._repo(checks=("build (3.12)",), workflows=("CI",))
		nombres = [c["nombre"] for c in self.plantilla.candidatos_de_check()["candidatos"]]
		self.assertEqual(nombres, ["build (3.12)"])
		self.assertNotIn("CI", nombres)

	def test_el_nombre_se_guarda_VERBATIM(self):
		"""Byte por byte: el string que se guarda es el que se va a exigir."""
		nombre = "build (3.12, ubuntu-latest) / test"
		self._repo(checks=(nombre,))
		self.assertEqual(
			self.plantilla.candidatos_de_check()["candidatos"][0]["nombre"], nombre)

	# ------------------------------------------------------------------
	# Cobertura: candidato o excepción
	# ------------------------------------------------------------------

	def test_ordena_por_cobertura_de_mayor_a_menor(self):
		for _n in range(3):
			self._repo(checks=("tests",))
		self._repo(checks=("tests", "lint"))
		nombres = [c["nombre"] for c in self.plantilla.candidatos_de_check()["candidatos"]]
		self.assertEqual(nombres, ["tests", "lint"])

	def test_dice_en_cuantos_de_cuantos(self):
		for _n in range(3):
			self._repo(checks=("tests",))
		self._repo()
		fila = self.plantilla.candidatos_de_check()["candidatos"][0]
		self.assertEqual((fila["en_cuantos"], fila["de_cuantos"]), (3, 4))
		self.assertEqual(fila["cobertura"], 75.0)

	def test_lo_que_corre_en_pocos_se_marca_EXCEPCION(self):
		"""Exigirle a los 21 lo que corre en 2 bloquea a 19."""
		for _n in range(9):
			self._repo(checks=("tests",))
		self._repo(checks=("tests", "solo-de-este"))
		por_nombre = {c["nombre"]: c for c in
					  self.plantilla.candidatos_de_check()["candidatos"]}
		self.assertFalse(por_nombre["tests"]["es_excepcion"])
		self.assertTrue(por_nombre["solo-de-este"]["es_excepcion"])

	def test_la_propuesta_no_decide_NADA(self):
		"""Armar la propuesta no puede tocar la plantilla: la decisión es de una persona."""
		self._repo(checks=("tests",))
		self.plantilla.candidatos_de_check()
		self.assertFalse(self.plantilla.required_check_ids)
		self.assertFalse(self.plantilla.status_checks_defined)

	def test_marca_lo_que_ya_esta_exigido(self):
		self._repo(checks=("tests",))
		self.env["repo.policy.status.check"].create({
			"template_id": self.plantilla.id, "name": "tests"})
		self.assertTrue(
			self.plantilla.candidatos_de_check()["candidatos"][0]["ya_exigido"])

	def test_una_lista_vacia_viene_con_la_explicacion_al_lado(self):
		"""«No hay candidatos» y «no miramos» se distinguen con dos números."""
		self._repo(workflows=("tests",))
		self._repo()
		propuesta = self.plantilla.candidatos_de_check()
		self.assertEqual(propuesta["candidatos"], [])
		self.assertEqual(propuesta["repositorios"], 2)
		self.assertEqual(propuesta["con_workflows"], 1)
		self.assertEqual(propuesta["con_checks"], 0)
