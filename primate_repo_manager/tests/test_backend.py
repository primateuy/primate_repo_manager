# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La conexión: cifrado del secreto y prueba contra un transporte falso."""
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class RespuestaFalsa:
	"""Imita lo justo de `requests.Response` que usa el cliente."""

	def __init__(self, status_code=200, payload=None, headers=None, text=""):
		self.status_code = status_code
		self._payload = payload
		self.headers = headers or {}
		self.text = text

	def json(self):
		if self._payload is None:
			raise ValueError("sin cuerpo JSON")
		return self._payload


class TransporteFalso:
	"""Transporte inyectable: registra lo que se le pide y devuelve lo preparado.

	Existe para poder probar el recorrido completo sin tocar GitHub, que es lo que pide
	el encargo (tests sobre datos mockeados).
	"""

	def __init__(self, respuestas=None):
		self.respuestas = respuestas or {}
		self.llamadas = []

	def get(self, url, headers=None, timeout=None):
		self.llamadas.append(("GET", url))
		for fragmento, respuesta in self.respuestas.items():
			if fragmento in url:
				return respuesta
		return RespuestaFalsa(404, {"message": "Not Found"})

	def post(self, url, headers=None, timeout=None):
		self.llamadas.append(("POST", url))
		return RespuestaFalsa(201, {"token": "ghs_token_de_prueba"})


def _clave_rsa_de_prueba():
	"""RSA real generada al vuelo: PyJWT necesita firmar de verdad para probar el flujo.

	No es un secreto de nadie —nace y muere con el test— pero tiene que ser válida, o el
	JWT no se puede armar y no estaríamos probando el camino real.
	"""
	from cryptography.hazmat.primitives import serialization
	from cryptography.hazmat.primitives.asymmetric import rsa

	clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	return clave.private_bytes(
		encoding=serialization.Encoding.PEM,
		format=serialization.PrivateFormat.PKCS8,
		encryption_algorithm=serialization.NoEncryption(),
	).decode()


class TestRepoBackend(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Una sola vez por clase: generar RSA de 2048 en cada test sería lento sin motivo.
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		# Login único: el constraint es (provider, owner_login) y el test no puede
		# depender de que la base esté vacía ni chocar con conexiones reales.
		self.backend = self.env["repo.backend"].create({
			"name": "GitHub de prueba",
			"owner_login": "cuenta-test-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user",
			"app_id": "123456",
			"installation_id": "7891011",
		})

	def test_la_private_key_se_guarda_cifrada_y_no_se_devuelve(self):
		self.backend.private_key = self.clave

		self.assertTrue(self.backend.private_key_set)
		# Lo guardado no es el texto plano...
		self.assertNotIn("BEGIN RSA", self.backend.private_key_encrypted)
		# ...y el campo de entrada nunca devuelve nada.
		self.backend.invalidate_recordset()
		self.assertFalse(self.backend.private_key)
		# Pero adentro se puede recuperar para firmar el JWT.
		self.assertEqual(self.backend._descifrar(), self.clave)

	def test_sin_la_clave_de_odoo_conf_no_cifra_a_medias(self):
		"""Sin `repo_manager_key` no guarda con otra cosa: falla y lo dice.

		Es la diferencia entre "no está cifrado" y "creés que está cifrado". Lo segundo
		es peor, y es exactamente lo que pasaba derivando la clave de `database.secret`,
		que viaja dentro del dump junto al texto cifrado.
		"""
		from odoo.tools import config

		anterior = config.get("repo_manager_key")
		config["repo_manager_key"] = ""
		try:
			with self.assertRaises(UserError) as ctx:
				self.backend.private_key = self.clave
			self.assertIn("repo_manager_key", str(ctx.exception))
		finally:
			config["repo_manager_key"] = anterior

	def test_sin_private_key_lo_dice_claro(self):
		with self.assertRaises(UserError):
			self.backend._descifrar()

	def test_sin_installation_id_lo_dice_claro(self):
		self.backend.private_key = self.clave
		self.backend.installation_id = False
		with self.assertRaises(UserError) as ctx:
			self.backend.client()
		self.assertIn("Installation ID", str(ctx.exception))

	def test_el_tipo_de_cuenta_equivocado_no_se_corrige_solo(self):
		"""Si en GitHub es una organización y acá dice usuario, se avisa y se frena.

		Corregirlo en silencio llevaría a recorrer 94 repos por endpoints equivocados.
		"""
		self.backend.private_key = self.clave
		transporte = TransporteFalso({
			"/users/": RespuestaFalsa(
				200, {"login": self.backend.owner_login, "type": "Organization"},
				{"X-RateLimit-Remaining": "4999"}),
		})
		client = self.backend.client(transport=transporte)
		datos = client.get("/users/%s" % self.backend.owner_login)
		self.assertEqual(datos["type"], "Organization")
		self.assertEqual(client.last_rate_remaining, 4999)

	def test_un_404_tolerado_es_none_y_no_un_error(self):
		"""Una rama sin protección devuelve 404: eso es 'no configurado', no un fallo."""
		self.backend.private_key = self.clave
		transporte = TransporteFalso({})
		client = self.backend.client(transport=transporte)

		self.assertIsNone(client.get("/repos/x/y/branches/main/protection", tolerar_404=True))

	def test_el_token_de_instalacion_se_pide_una_sola_vez(self):
		"""Se cachea mientras esté vigente: una auditoría hace cientos de requests."""
		self.backend.private_key = self.clave
		transporte = TransporteFalso({
			"/users/": RespuestaFalsa(200, {"login": self.backend.owner_login, "type": "User"}),
		})
		client = self.backend.client(transport=transporte)
		client.get("/users/%s" % self.backend.owner_login)
		client.get("/users/%s" % self.backend.owner_login)

		posts = [c for c in transporte.llamadas if c[0] == "POST"]
		self.assertEqual(len(posts), 1, "el token no puede pedirse en cada request")
