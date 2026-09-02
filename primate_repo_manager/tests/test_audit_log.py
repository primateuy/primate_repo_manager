# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La bitácora es inmutable de verdad, no por permisos.

Los tests van con `sudo()` a propósito: probar la inmutabilidad con un usuario limitado
sólo demostraría que los ACL funcionan, que es la capa que el propio código del módulo
se saltea cada vez que hace `.sudo()`.
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestAuditLogInmutable(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Bitácora %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
		})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "un-repo", "full_name": "cuenta/un-repo",
		})
		self.miembro = self.env["repo.member"].create({"github_login": "alguien"})
		self.entrada = self.env["repo.audit.log"].registrar(
			"write_applied", "Protección aplicada en 19.0",
			backend=self.backend, repository=self.repo, member=self.miembro,
			payload={"branch": "19.0"}, previous_state={"protected": False})

	# --- lo central ---------------------------------------------------------

	def test_ni_el_superusuario_puede_modificar_una_entrada(self):
		with self.assertRaises(UserError):
			self.entrada.sudo().write({"summary": "otra cosa"})

	def test_ni_el_superusuario_puede_borrar_una_entrada(self):
		with self.assertRaises(UserError):
			self.entrada.sudo().unlink()

	def test_tampoco_en_lote(self):
		"""Una guarda que sólo cubre el registro suelto deja abierta la puerta grande."""
		otra = self.env["repo.audit.log"].registrar("sync", "Otra cosa")
		lote = (self.entrada | otra).sudo()
		with self.assertRaises(UserError):
			lote.write({"summary": "x"})
		with self.assertRaises(UserError):
			lote.unlink()
		self.assertEqual(len(lote.exists()), 2, "no se borró ninguna")

	# --- los ACL, como segunda capa ----------------------------------------

	def test_ningun_acl_concede_write_ni_unlink(self):
		modelo = self.env["ir.model"].search([("model", "=", "repo.audit.log")])
		accesos = self.env["ir.model.access"].search([("model_id", "=", modelo.id)])
		self.assertTrue(accesos, "el modelo tiene que tener ACLs declarados")
		for acceso in accesos:
			self.assertFalse(acceso.perm_write, "%s concede write" % acceso.name)
			self.assertFalse(acceso.perm_unlink, "%s concede unlink" % acceso.name)

	# --- el camino silencioso de destrucción --------------------------------

	def test_borrar_el_repositorio_no_se_lleva_la_bitacora(self):
		"""Con ondelete='cascade' Postgres borraría en cascada SIN pasar por unlink().

		Sería una destrucción silenciosa que la guarda de inmutabilidad ni se entera.
		Los enlaces son 'set null' y el nombre queda copiado en texto.
		"""
		entrada_id = self.entrada.id
		self.repo.unlink()

		entrada = self.env["repo.audit.log"].browse(entrada_id)
		# exists() sobre un id borrado devuelve vacío: si esto pasa, la entrada murió.
		self.assertTrue(entrada.exists(), "la entrada tiene que sobrevivir al repositorio")
		self.assertFalse(entrada.repository_id, "el enlace queda en nulo")
		self.assertEqual(entrada.repository_name, "cuenta/un-repo",
						 "y el nombre sigue contando de qué repositorio hablaba")

	def test_borrar_la_persona_no_se_lleva_la_bitacora(self):
		entrada_id = self.entrada.id
		self.miembro.unlink()

		entrada = self.env["repo.audit.log"].browse(entrada_id)
		self.assertTrue(entrada.exists())
		self.assertFalse(entrada.member_id)
		self.assertEqual(entrada.member_login, "alguien")

	# --- lo que sí tiene que guardar ---------------------------------------

	def test_guarda_el_estado_previo_que_permite_revertir(self):
		self.assertEqual(json.loads(self.entrada.previous_state_json),
						 {"protected": False})
		self.assertEqual(json.loads(self.entrada.payload_json), {"branch": "19.0"})
		self.assertEqual(self.entrada.user_id, self.env.user)
		self.assertTrue(self.entrada.timestamp)
