# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El chequeo de cierre: «¿producción sigue cerrada?».

Se prueba la LÓGICA del chequeo, no la respuesta de GitHub — para eso está la corrida
real, que es la que vale. Lo que se vigila acá es que el chequeo no mienta en las dos
direcciones: que no dé por bueno lo que no puede ver, y que no grite por algo que está
bien. Su primera corrida hizo lo segundo.
"""
import uuid

from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba


class BaseChequeo(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		# El chequeo mira TODAS las conexiones, así que las de la base entran en el
		# resultado. No se las toca: se apaga lo que sale a la red y cada test busca su
		# propio punto por el nombre de su conexión.

	def _backend(self, **campos):
		valores = {
			"name": "Conexión %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "4805796",
			"installation_id": "1", "environment": "production",
		}
		valores.update(campos)
		return self.env["repo.backend"].create(valores)


class TestElChequeoNoMiente(BaseChequeo):

	def _punto(self, resultado, clase, contiene=None):
		for punto in resultado["puntos"]:
			if punto["punto"] == clase and (
					contiene is None or contiene in punto["sujeto"]):
				return punto
		return None

	def _sin_red(self):
		"""Los puntos que salen a GitHub se responden con un resultado fijo: acá se prueba
		la lógica del chequeo, no la API."""
		Backend = self.env["repo.backend"].__class__
		original = Backend._permisos_de_la_app
		Backend._permisos_de_la_app = lambda s: {
			"punto": "permisos_de_lectura", "sujeto": s.name, "ok": True,
			"evidencia": {"permisos": {"metadata": "read"}}}
		self.addCleanup(lambda: setattr(Backend, "_permisos_de_la_app", original))

		# El alcance de escritura también sale a la red. Un doble que devuelve
		# repositorios de la propia cuenta: lo que se prueba acá es la lógica del chequeo.
		original_cliente = Backend.write_client

		class ClienteFalso:
			def __init__(self, cuenta):
				self.cuenta = cuenta

			def paginate(self, ruta, **kw):
				return [{"full_name": "%s/uno" % self.cuenta}]

		Backend.write_client = lambda s, transport=None: ClienteFalso(s.owner_login)
		self.addCleanup(lambda: setattr(Backend, "write_client", original_cliente))

	def test_una_produccion_con_credenciales_de_escritura_sale_en_ROJO(self):
		self._sin_red()
		backend = self._backend()
		backend.write_app_id = "4811232"
		resultado = self.env["repo.backend"].chequeo_de_cierre()
		punto = self._punto(resultado, "produccion_sin_escritura", backend.name)
		self.assertFalse(punto["ok"])
		self.assertEqual(punto["evidencia"]["write_app_id"], "4811232")

	def test_una_produccion_limpia_sale_en_verde_con_su_evidencia(self):
		self._sin_red()
		backend = self._backend()
		punto = self._punto(
			self.env["repo.backend"].chequeo_de_cierre(),
			"produccion_sin_escritura", backend.name)
		self.assertTrue(punto["ok"])
		self.assertFalse(punto["evidencia"]["write_key_set"])
		self.assertFalse(punto["evidencia"]["write_enabled"])

	def test_lo_que_NO_se_puede_verificar_no_cuenta_como_verde(self):
		"""La App de producción no tiene credenciales acá a propósito, así que su alcance
		no se puede consultar. Darlo por bueno sería contar como verde lo que no se pudo
		leer — la trampa que este módulo evita en todos lados."""
		self._sin_red()
		resultado = self.env["repo.backend"].chequeo_de_cierre()
		punto = self._punto(resultado, "alcance_no_verificable")
		self.assertIsNotNone(punto, "el punto no verificable tiene que aparecer")
		self.assertIsNone(punto["ok"], "«no se sabe» no es «está bien»")
		self.assertIn("dónde_mirarlo", punto["evidencia"])
		self.assertGreaterEqual(resultado["no_verificables"], 1)

	def test_el_veredicto_NO_se_come_lo_no_verificable(self):
		self._sin_red()
		resultado = self.env["repo.backend"].chequeo_de_cierre()
		self.assertTrue(resultado["no_verificables"])

	def test_una_App_en_uso_sin_declarar_sale_en_ROJO(self):
		"""El registro se mantiene a mano; sin esto envejecería en silencio, que es
		exactamente cómo una App queda fuera del radar."""
		self._sin_red()
		self._backend(app_id="9999999")
		punto = self._punto(
			self.env["repo.backend"].chequeo_de_cierre(), "registro_al_día")
		self.assertFalse(punto["ok"])
		self.assertIn("9999999", punto["evidencia"]["en_uso_sin_declarar"])

	def test_cada_App_se_nombra_con_su_ID_su_instalación_y_su_cuenta(self):
		"""Tres Apps se confundieron una con otra al preguntar por «prm-writer»: dos se
		llaman parecido. Un identificador suelto no alcanza."""
		nombre = self.env["repo.backend"]._nombrar_app("4808079", "158565221", "x")
		self.assertIn("4808079", nombre)
		self.assertIn("158565221", nombre)
		self.assertIn("prm-sandbox", nombre)

	def test_una_App_en_uso_que_no_está_declarada_se_nombra_como_tal(self):
		self.assertIn("SIN DECLARAR",
					  self.env["repo.backend"]._nombrar_app("9999999", "1", "x"))


class TestLaReglaDeLosPermisos(BaseChequeo):
	"""El falso positivo de la primera corrida: el chequeo marcaba en rojo la App del
	sandbox por tener permisos de escritura, siendo que es la que escribe.

	La regla vive separada de la consulta a GitHub justamente para poder probarla."""

	SOLO_LECTURA = {"metadata": "read", "contents": "read"}
	CON_ESCRITURA = {"metadata": "read", "contents": "write",
					 "administration": "write"}

	def test_una_App_de_auditoría_con_un_permiso_de_escritura_sale_en_ROJO(self):
		veredicto = self._backend()._juzgar_permisos(self.CON_ESCRITURA)
		self.assertFalse(veredicto["ok"])
		self.assertEqual(veredicto["evidencia"]["no_son_read"],
						 ["administration", "contents"])

	def test_una_App_de_auditoría_toda_en_read_sale_en_verde(self):
		self.assertTrue(self._backend()._juzgar_permisos(self.SOLO_LECTURA)["ok"])

	def test_la_MISMA_App_que_escribe_puede_tener_escritura_en_sandbox(self):
		backend = self._backend(app_id="4808079", write_app_id="4808079",
								environment="sandbox")
		veredicto = backend._juzgar_permisos(self.CON_ESCRITURA)
		self.assertTrue(veredicto["ok"], "gritar por esto es un falso positivo")
		self.assertIn("lee Y escribe", veredicto["sujeto"])

	def test_pero_en_PRODUCCIÓN_la_misma_App_con_escritura_sale_en_ROJO(self):
		"""Es la línea que separa un caso esperable de uno que hay que mirar ya."""
		backend = self._backend(app_id="4808079", write_app_id="4808079",
								environment="production")
		self.assertFalse(backend._juzgar_permisos(self.CON_ESCRITURA)["ok"])
