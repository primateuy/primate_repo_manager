# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Rotación del secreto de cifrado.

El escenario que estos tests fijan es el que rompe en silencio: alguien cambia
`repo_manager_key` en odoo.conf, todo sigue andando aparentemente, y semanas después una
auditoría falla porque la private key guardada ya no se puede descifrar.
"""
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tools import config

from .test_backend import _clave_rsa_de_prueba

SECRETO_VIEJO = "secreto-anterior-de-al-menos-32-caracteres-abcdef"
SECRETO_NUEVO = "secreto-nuevo-de-al-menos-32-caracteres-1234567890"


class TestKeyRotation(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave_pem = _clave_rsa_de_prueba()

	def _backend_cifrado_con(self, secreto):
		"""Crea una conexión con la private key cifrada usando el secreto indicado."""
		anterior = config.get("repo_manager_key")
		config["repo_manager_key"] = secreto
		try:
			backend = self.env["repo.backend"].create({
				"name": "Rotación %s" % uuid.uuid4().hex[:6],
				"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
				"app_id": "1", "installation_id": "2",
			})
			backend.private_key = self.clave_pem
			return backend
		finally:
			config["repo_manager_key"] = anterior

	def test_tras_cambiar_el_secreto_la_clave_no_se_descifra(self):
		"""El daño que la rotación viene a evitar, y que el error tiene que explicar."""
		backend = self._backend_cifrado_con(SECRETO_VIEJO)
		anterior = config.get("repo_manager_key")
		config["repo_manager_key"] = SECRETO_NUEVO
		try:
			with self.assertRaises(UserError) as ctx:
				backend._descifrar()
			mensaje = str(ctx.exception)
			# El mensaje tiene que ser accionable, no un traceback de Fernet.
			self.assertIn("repo_manager_key", mensaje)
			self.assertIn("Rotar secreto", mensaje)
		finally:
			config["repo_manager_key"] = anterior

	def test_la_rotacion_recifra_y_la_clave_vuelve_a_leerse(self):
		backend = self._backend_cifrado_con(SECRETO_VIEJO)
		cifrado_viejo = backend.private_key_encrypted
		anterior = config.get("repo_manager_key")
		config["repo_manager_key"] = SECRETO_NUEVO
		try:
			wizard = self.env["repo.key.rotation"].create({
				"previous_key": SECRETO_VIEJO,
				"backend_ids": [(6, 0, backend.ids)],
			})
			wizard.action_rotate()

			self.assertNotEqual(backend.private_key_encrypted, cifrado_viejo)
			# Y lo que importa: el contenido sigue siendo el mismo PEM.
			self.assertEqual(backend._descifrar(), self.clave_pem)
		finally:
			config["repo_manager_key"] = anterior

	def test_verificar_no_escribe_nada(self):
		"""Primero mirar, después tocar: el botón de verificar es inocuo."""
		backend = self._backend_cifrado_con(SECRETO_VIEJO)
		cifrado_original = backend.private_key_encrypted
		anterior = config.get("repo_manager_key")
		config["repo_manager_key"] = SECRETO_NUEVO
		try:
			wizard = self.env["repo.key.rotation"].create({
				"previous_key": SECRETO_VIEJO,
				"backend_ids": [(6, 0, backend.ids)],
			})
			wizard.action_verify()

			self.assertEqual(backend.private_key_encrypted, cifrado_original)
			self.assertIn("✓", wizard.preview)
		finally:
			config["repo_manager_key"] = anterior

	def test_rotar_dos_veces_no_rompe(self):
		"""Idempotencia: si ya estaba recifrada, se saltea en vez de arruinarla."""
		backend = self._backend_cifrado_con(SECRETO_NUEVO)
		anterior = config.get("repo_manager_key")
		config["repo_manager_key"] = SECRETO_NUEVO
		try:
			wizard = self.env["repo.key.rotation"].create({
				"previous_key": SECRETO_VIEJO,
				"backend_ids": [(6, 0, backend.ids)],
			})
			wizard.action_rotate()

			self.assertEqual(backend._descifrar(), self.clave_pem)
			self.assertIn("Ya estaban al día", wizard.preview)
		finally:
			config["repo_manager_key"] = anterior

	def test_una_clave_irrecuperable_se_avisa_y_no_se_deja_a_medias(self):
		backend = self._backend_cifrado_con("un-tercer-secreto-distinto-de-32-caracteres")
		anterior = config.get("repo_manager_key")
		config["repo_manager_key"] = SECRETO_NUEVO
		try:
			wizard = self.env["repo.key.rotation"].create({
				"previous_key": SECRETO_VIEJO,
				"backend_ids": [(6, 0, backend.ids)],
			})
			with self.assertRaises(UserError) as ctx:
				wizard.action_rotate()
			self.assertIn("volver a cargar el .pem", str(ctx.exception))
		finally:
			config["repo_manager_key"] = anterior
