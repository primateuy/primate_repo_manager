# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B3.1 · el CODEOWNERS generado, y el owner que no se escribe porque no se verificó.

El test que más importa es el del owner sin acceso: **no falla al escribirse, falla en
silencio después**. La línea la ignora GitHub, las PRs no piden esa revisión, y el
repositorio parece gobernado mientras nadie revisa nada. Es el check-que-no-corrió en
versión personas.
"""
import uuid

from odoo.tests.common import TransactionCase

from odoo.addons.primate_repo_manager.models.repo_codeowners import MARCA


class TestCodeownersGenerado(TransactionCase):

	def setUp(self):
		super().setUp()
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		self.env.flush_all()
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "Clientes", "code": "co-%s" % uuid.uuid4().hex[:6],
			"classification_default": "cliente",
		})
		backend = self.env["repo.backend"].create({
			"name": "CO %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})
		self.repo = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "classification": "cliente",
		})
		self.lider = self.env["repo.member"].create({
			"github_login": "mrodriguez", "name": "Martín Rodríguez"})
		self.env["repo.collaborator"].create({
			"repository_id": self.repo.id, "member_id": self.lider.id,
			"permission": "maintain", "source": "direct"})

	def _regla(self, miembro, patron="*", reason=False, sequence=10):
		return self.env["repo.policy.codeowner"].create({
			"template_id": self.plantilla.id, "path_pattern": patron,
			"member_id": miembro.id, "reason": reason, "sequence": sequence})

	# ------------------------------------------------------------------
	# LA VALIDACIÓN CONTRA EL ESPEJO
	# ------------------------------------------------------------------

	def test_un_owner_SIN_ACCESO_al_repo_no_se_escribe(self):
		"""No falla al escribirse: falla en silencio después. No se escribe lo que no se
		verificó."""
		ajeno = self.env["repo.member"].create({"github_login": "sin-acceso"})
		self._regla(ajeno)
		salida = self.repo.generar_codeowners()
		self.assertEqual(salida["lineas"], [])
		self.assertEqual(salida["contenido"], "")
		self.assertEqual(len(salida["omitidos"]), 1)
		self.assertIn("no figura como colaborador", salida["omitidos"][0]["motivo"])

	def test_el_omitido_se_INFORMA_y_no_se_traga(self):
		"""Omitirlo en silencio sería el mismo defecto una capa más arriba."""
		ajeno = self.env["repo.member"].create({"github_login": "sin-acceso"})
		self._regla(self.lider, patron="*")
		self._regla(ajeno, patron="addons/")
		salida = self.repo.generar_codeowners()
		self.assertEqual(len(salida["lineas"]), 1)
		self.assertEqual(salida["omitidos"][0]["login"], "sin-acceso")
		self.assertEqual(salida["omitidos"][0]["patron"], "addons/")

	def test_una_persona_SIN_cuenta_de_github_no_puede_ni_existir(self):
		"""La garantía vive en el modelo, no en el generador.

		El generador tenía una rama para «sin cuenta de GitHub» y era código muerto:
		`repo.member` exige `github_login`. Una guarda que no puede dispararse es peor
		que ninguna, así que se quitó — y este test fija dónde está la garantía de
		verdad, para que quitar el `required` no pase inadvertido.
		"""
		from psycopg2 import IntegrityError

		from odoo.tools import mute_logger
		with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
			with self.env.cr.savepoint():
				self.env["repo.member"].create({"name": "Sin cuenta"})

	def test_el_que_SI_tiene_acceso_entra(self):
		self._regla(self.lider)
		salida = self.repo.generar_codeowners()
		self.assertEqual(salida["omitidos"], [])
		self.assertIn("* @mrodriguez", salida["contenido"])

	# ------------------------------------------------------------------
	# El archivo
	# ------------------------------------------------------------------

	def test_lleva_la_marca_que_lo_hace_reconocible_como_nuestro(self):
		"""Sin la marca, B3.2 no puede distinguir el nuestro de uno ajeno — y uno ajeno
		no se pisa nunca."""
		self._regla(self.lider)
		self.assertTrue(
			self.repo.generar_codeowners()["contenido"].startswith(MARCA))

	def test_cada_linea_dice_DE_DONDE_sale_su_owner(self):
		"""Un CODEOWNERS sin procedencia es un archivo que nadie se anima a tocar."""
		self._regla(self.lider, reason="líder técnico de la cuenta")
		contenido = self.repo.generar_codeowners()["contenido"]
		self.assertIn("# líder técnico de la cuenta", contenido)

	def test_sin_procedencia_declarada_dice_al_menos_de_que_plantilla_sale(self):
		self._regla(self.lider)
		self.assertIn(self.plantilla.name, self.repo.generar_codeowners()["contenido"])

	def test_respeta_el_orden_declarado(self):
		"""CODEOWNERS aplica la ÚLTIMA regla que coincide: el orden decide quién revisa."""
		otro = self.env["repo.member"].create({"github_login": "jperez"})
		self.env["repo.collaborator"].create({
			"repository_id": self.repo.id, "member_id": otro.id,
			"permission": "push", "source": "direct"})
		self._regla(self.lider, patron="*", sequence=10)
		self._regla(otro, patron="addons/", sequence=20)
		contenido = self.repo.generar_codeowners()["contenido"]
		self.assertLess(contenido.index("* @mrodriguez"),
						contenido.index("addons/ @jperez"))

	def test_los_owners_son_PERSONAS_y_el_archivo_lo_dice(self):
		"""Los teams no existen en una cuenta de usuario: una línea con team la ignora
		GitHub sin avisar. La decisión queda escrita donde alguien la va a leer."""
		self._regla(self.lider)
		contenido = self.repo.generar_codeowners()["contenido"]
		self.assertIn("PERSONAS", contenido)
		self.assertNotIn("@%s/" % self.repo.backend_id.owner_login, contenido)

	def test_sin_owners_declarados_no_hay_archivo(self):
		"""Un CODEOWNERS vacío no es neutro: reemplazaría a uno que hubiera."""
		self.assertEqual(self.repo.generar_codeowners()["contenido"], "")
