# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""A7: escribir en producción exige un acto deliberado, no unas credenciales cargadas.

Durante toda la F2 `write_client()` rechazaba cualquier escritura desde una conexión de
producción, sin excepción. Esa compuerta se levantó al pasar a la arquitectura de dos Apps
—el alcance de la instalación acota el radio del daño y GitHub lo hace cumplir— pero el
reemplazo NO exigía que nadie decidiera nada: cargar las credenciales alcanzaba, y el
primer apply real salió sin ninguna confirmación adicional.

Esto es esa decisión, con su rastro.
"""
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import RespuestaFalsa, _clave_rsa_de_prueba


class TransporteAlcance:
	"""Contesta el listado de la instalación y nada más."""

	def __init__(self, repos):
		self.repos = repos
		self.pedidos = []

	def post(self, url, headers=None, timeout=None, **kw):
		self.pedidos.append(("POST", url))
		return RespuestaFalsa(201, {"token": "ghs_test"})

	def get(self, url, headers=None, timeout=None, **kw):
		self.pedidos.append(("GET", url))
		return RespuestaFalsa(200, {
			"repositories": [{"full_name": r} for r in self.repos]})


class TestHabilitacionDeEscritura(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def _backend(self, entorno="production", con_app=True):
		backend = self.env["repo.backend"].create({
			"name": "Conexión %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": entorno,
		})
		backend.private_key = self.clave
		if con_app:
			backend.write_app_id = "10"
			backend.write_installation_id = "20"
			backend.write_private_key = self.clave
		return backend

	# --- la puerta ----------------------------------------------------------

	def test_en_produccion_las_credenciales_NO_alcanzan(self):
		"""El defecto que A7 cierra: con credenciales cargadas, se escribía sin más.

		MUTACIÓN OBLIGATORIA: quitando la condición de `write_enabled` de `write_client`,
		este test se pone rojo.
		"""
		backend = self._backend("production")
		self.assertFalse(backend.write_enabled)
		with self.assertRaises(UserError) as ctx:
			backend.write_client()
		self.assertIn("PRODUCCIÓN", str(ctx.exception))
		self.assertIn("acto deliberado", str(ctx.exception))

	def test_habilitada_la_puerta_se_abre(self):
		backend = self._backend("production")
		backend._habilitar_escritura()
		cliente = backend.write_client(transport=TransporteAlcance([]))
		self.assertTrue(cliente)

	def test_en_sandbox_la_habilitacion_no_se_exige(self):
		"""El sandbox existe para ensayar sin ceremonia. La ceremonia es de producción."""
		backend = self._backend("sandbox")
		self.assertFalse(backend.write_enabled)
		self.assertTrue(backend.write_client(transport=TransporteAlcance([])))

	def test_sin_App_de_escritura_sigue_mandando_la_guarda_estructural(self):
		"""Habilitar no inventa credenciales: la compuerta dura sigue primero."""
		backend = self._backend("production", con_app=False)
		backend._habilitar_escritura()
		with self.assertRaises(UserError) as ctx:
			backend.write_client()
		self.assertIn("App de escritura", str(ctx.exception))

	# --- el flag no se edita a mano ----------------------------------------

	def test_el_flag_NO_se_puede_poner_a_mano(self):
		"""Sin esto, todo el mecanismo se saltea con un write desde cualquier lado y la
		entrada de bitácora nunca ocurre.

		MUTACIÓN: quitando la guarda del `write`, este test se pone rojo.
		"""
		backend = self._backend("production")
		with self.assertRaises(UserError) as ctx:
			backend.write_enabled = True
		self.assertIn("no se edita", str(ctx.exception))
		self.assertFalse(backend.write_enabled)

	def test_ni_siquiera_con_sudo(self):
		backend = self._backend("production")
		with self.assertRaises(UserError):
			backend.sudo().write({"write_enabled": True})

	# --- el rastro ----------------------------------------------------------

	def test_habilitar_deja_entrada_en_la_bitacora_con_quien_y_cuando(self):
		backend = self._backend("production")
		antes = self.env["repo.audit.log"].search_count(
			[("event_type", "=", "write_enabled")])
		backend._habilitar_escritura(alcance={"cuenta/uno", "cuenta/dos"})

		entradas = self.env["repo.audit.log"].search(
			[("event_type", "=", "write_enabled")], order="id desc")
		self.assertEqual(len(entradas), antes + 1)
		entrada = entradas[0]
		self.assertEqual(entrada.backend_id, backend)
		self.assertIn(backend.name, entrada.summary)
		self.assertEqual(entrada.create_uid, self.env.user)

		import json
		payload = json.loads(entrada.payload_json)
		self.assertEqual(payload["alcance"], ["cuenta/dos", "cuenta/uno"],
						 "queda registrado sobre QUÉ se habilitó, no sólo que se habilitó")
		self.assertEqual(backend.write_enabled_by_id, self.env.user)
		self.assertTrue(backend.write_enabled_at)

	def test_deshabilitar_tambien_se_registra(self):
		backend = self._backend("production")
		backend._habilitar_escritura()
		antes = self.env["repo.audit.log"].search_count(
			[("event_type", "=", "write_disabled")])
		backend.action_disable_writes()
		self.assertEqual(
			self.env["repo.audit.log"].search_count(
				[("event_type", "=", "write_disabled")]), antes + 1)
		self.assertFalse(backend.write_enabled)
		self.assertFalse(backend.write_enabled_by_id)

	def test_la_entrada_dice_sobre_que_alcance_se_habilito_y_eso_no_cambia_despues(self):
		"""Si mañana alguien amplía la instalación, la entrada sigue diciendo sobre qué se
		habilitó. Es la pregunta que se hace después de un incidente."""
		import json

		backend = self._backend("production")
		backend._habilitar_escritura(alcance={"cuenta/uno"})
		entrada = self.env["repo.audit.log"].search(
			[("event_type", "=", "write_enabled")], order="id desc", limit=1)
		self.assertEqual(json.loads(entrada.payload_json)["alcance"], ["cuenta/uno"])


class TestAsistenteDeHabilitacion(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		# Login único: la base de staging ya tiene la conexión real de `primateuy` y
		# `owner_login` es único por proveedor.
		self.login = "cuenta-%s" % uuid.uuid4().hex[:8]
		self.backend = self.env["repo.backend"].create({
			"name": "Con asistente", "owner_login": self.login,
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "production",
		})
		self.backend.private_key = self.clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = self.clave

		self.transporte = TransporteAlcance(
			["%s/uno" % self.login, "%s/dos" % self.login])
		Backend = type(self.backend)
		original = Backend._alcance_para_confirmar
		Backend._alcance_para_confirmar = (
			lambda s, transport=None: original(s, transport=self.transporte))
		self.addCleanup(
			lambda: setattr(Backend, "_alcance_para_confirmar", original))

	def _asistente(self):
		return self.env["repo.write.enable.wizard"].create({
			"backend_id": self.backend.id})

	def test_muestra_el_alcance_real_preguntado_a_github(self):
		"""Se pregunta, no se supone: es la información que debería hacer dudar."""
		asistente = self._asistente()
		self.assertEqual(asistente.scope_count, 2)
		self.assertIn("%s/uno" % self.login, asistente.scope_text)
		self.assertFalse(asistente.scope_error)

	def test_sin_escribir_el_nombre_no_habilita(self):
		asistente = self._asistente()
		with self.assertRaises(UserError):
			asistente.action_confirm()
		self.assertFalse(self.backend.write_enabled)

	def test_con_el_nombre_mal_tampoco(self):
		asistente = self._asistente()
		asistente.confirmation = "otra-cosa"
		with self.assertRaises(UserError):
			asistente.action_confirm()
		self.assertFalse(self.backend.write_enabled)

	def test_con_el_nombre_exacto_habilita_y_guarda_el_alcance(self):
		import json

		asistente = self._asistente()
		asistente.confirmation = self.login
		asistente.action_confirm()
		self.assertTrue(self.backend.write_enabled)
		entrada = self.env["repo.audit.log"].search(
			[("event_type", "=", "write_enabled")], order="id desc", limit=1)
		self.assertEqual(sorted(json.loads(entrada.payload_json)["alcance"]),
						 ["%s/dos" % self.login, "%s/uno" % self.login])

	def test_si_no_se_pudo_leer_el_alcance_NO_habilita(self):
		"""Habilitar sin saber sobre qué es exactamente lo que esta pantalla evita."""
		Backend = type(self.backend)

		def revienta(s, transport=None):
			raise UserError("GitHub no contesta")

		original = Backend._alcance_para_confirmar
		Backend._alcance_para_confirmar = revienta
		self.addCleanup(
			lambda: setattr(Backend, "_alcance_para_confirmar", original))

		asistente = self._asistente()
		self.assertTrue(asistente.scope_error)
		asistente.confirmation = self.login
		with self.assertRaises(UserError) as ctx:
			asistente.action_confirm()
		self.assertIn("no hay forma de saber sobre qué", str(ctx.exception))
		self.assertFalse(self.backend.write_enabled)
