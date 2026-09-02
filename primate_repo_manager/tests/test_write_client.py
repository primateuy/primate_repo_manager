# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Las guardas del cliente de escritura, verificadas leyendo el código.

El mismo criterio que `test_read_only`: una guarda que depende de que nadie se olvide no
es una guarda. Estos tests fallan en el commit que las rompe, no meses después.
"""
import ast
import inspect
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models import github_client, github_write_client, repo_backend
from .test_backend import RespuestaFalsa, _clave_rsa_de_prueba


class TestGuardasDeEscritura(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def _backend(self, entorno):
		backend = self.env["repo.backend"].create({
			"name": "Escritura %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": entorno,
		})
		backend.private_key = self.clave
		return backend

	# --- guarda 1: el cliente de lectura sigue sin poder escribir -----------

	def test_el_cliente_de_lectura_no_heredo_verbos(self):
		"""Que exista un cliente de escritura no puede haberle dado verbos al de lectura.

		`GithubWriteClient` hereda de `GithubReadClient`, no al revés. Si algún día se
		invirtiera, el de lectura pasaría a tener post/put/patch/delete y la garantía de
		F1 se caería en silencio, porque el test de F1 mira métodos declarados.
		"""
		metodos = dict(inspect.getmembers(
			github_client.GithubReadClient, inspect.isfunction))
		for verbo in github_write_client.VERBOS:
			self.assertNotIn(verbo, metodos)
		self.assertTrue(
			issubclass(github_write_client.GithubWriteClient,
					   github_client.GithubReadClient),
			"la herencia va en este sentido y no al revés")

	def test_el_cliente_de_escritura_expone_exactamente_los_verbos_declarados(self):
		metodos = [
			n for n, _v in inspect.getmembers(
				github_write_client.GithubWriteClient, inspect.isfunction)
			if not n.startswith("_")
			and n not in dict(inspect.getmembers(
				github_client.GithubReadClient, inspect.isfunction))
		]
		self.assertEqual(sorted(metodos), sorted(github_write_client.VERBOS))

	# --- guarda 2: una sola puerta, y cerrada fuera del sandbox -------------

	def test_sin_app_de_escritura_no_hay_cliente(self):
		"""La compuerta es ESTRUCTURAL: sin credenciales de la App de escritura, nada.

		Vale para cualquier entorno. La App de auditoría no sirve para esto ni pasándola
		por acá: sus permisos son de lectura y GitHub la frena del otro lado.
		"""
		for entorno in ("production", "sandbox"):
			backend = self._backend(entorno)
			with self.assertRaises(UserError) as ctx:
				backend.write_client()
			mensaje = str(ctx.exception)
			self.assertIn("App de escritura", mensaje)
			self.assertIn("sólo lectura", mensaje,
						  "el mensaje explica que la de auditoría no se usa para esto")

	def test_con_app_de_escritura_si_hay_cliente(self):
		backend = self._backend("production")
		backend.write_app_id = "10"
		backend.write_installation_id = "20"
		backend.write_private_key = self.clave

		class Transporte:
			def post(self, url, headers=None, timeout=None):
				return RespuestaFalsa(201, {"token": "ghs_test"})

		cliente = backend.write_client(transport=Transporte())
		self.assertIsInstance(cliente, github_write_client.GithubWriteClient)

	def test_las_dos_credenciales_son_distintas_y_no_se_mezclan(self):
		"""Cada camino usa la suya. Si se cruzaran, la separación sería decorativa."""
		backend = self._backend("production")
		backend.write_app_id = "10"
		backend.write_installation_id = "20"
		backend.write_private_key = self.clave

		fuente = inspect.getsource(repo_backend.RepoBackend.client)
		self.assertIn("self.app_id", fuente)
		self.assertNotIn("write_app_id", fuente,
						 "el cliente de lectura no puede tocar la credencial de escritura")
		fuente_w = inspect.getsource(repo_backend.RepoBackend.write_client)
		self.assertIn("write_app_id", fuente_w)
		self.assertIn("_descifrar_escritura", fuente_w)

	def test_la_unica_puerta_es_write_client(self):
		"""Nadie más instancia GithubWriteClient.

		Sin esto, la compuerta por entorno se saltea con un import y una línea. El test
		recorre el árbol de los modelos y falla si aparece la construcción en cualquier
		lugar que no sea `repo.backend.write_client`.
		"""
		from .. import models

		import os
		import pkgutil

		carpeta = os.path.dirname(inspect.getfile(models))
		culpables = []
		for _finder, nombre, _pkg in pkgutil.iter_modules([carpeta]):
			if nombre == "github_write_client":
				continue          # su propia definición no cuenta
			ruta = os.path.join(carpeta, "%s.py" % nombre)
			with open(ruta, encoding="utf-8") as fh:
				arbol = ast.parse(fh.read(), filename=ruta)
			for nodo in ast.walk(arbol):
				if (isinstance(nodo, ast.Call)
						and isinstance(nodo.func, ast.Name)
						and nodo.func.id == "GithubWriteClient"):
					culpables.append((nombre, nodo.lineno))

		esperado = [("repo_backend", None)]
		self.assertEqual(
			[c[0] for c in culpables], [e[0] for e in esperado],
			"GithubWriteClient sólo puede construirse en repo_backend.write_client; "
			"apareció en: %s" % culpables)

	def test_la_compuerta_exige_las_credenciales_de_escritura(self):
		"""La puerta comprueba que la App de escritura exista, que es lo estructural.

		Hasta el cierre de F2 la compuerta miraba `environment` y prohibía producción sin
		excepción. Eso era un «todavía no», y se levantó con el criterio de salida
		cumplido: ahora lo que acota el daño es el ALCANCE de la instalación de la App de
		escritura, que GitHub hace cumplir del otro lado.
		"""
		fuente = inspect.getsource(repo_backend.RepoBackend.write_client)
		self.assertIn("write_private_key_encrypted", fuente)
		self.assertIn("write_installation_id", fuente)
