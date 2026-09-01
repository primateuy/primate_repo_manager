# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La Fase 1 no escribe en GitHub, y eso se verifica leyendo el código.

Es un criterio de aceptación del encargo. Un test que hiciera una auditoría y contara
requests probaría que ESA corrida no escribió; esto prueba algo más fuerte y más barato:
que el cliente de recursos **no tiene con qué** escribir. Si alguien agrega un `post()`
para resolver algo rápido, este test se pone rojo en el commit que lo agrega, no meses
después cuando alguien audite.
"""
import ast
import inspect

from odoo.tests.common import TransactionCase

from ..models import github_client

VERBOS_DE_ESCRITURA = ("post", "patch", "put", "delete", "merge", "create", "update")


class TestReadOnly(TransactionCase):

	def test_el_cliente_de_recursos_no_tiene_verbos_de_escritura(self):
		metodos = [
			nombre for nombre, _valor in
			inspect.getmembers(github_client.GithubReadClient, inspect.isfunction)
			if not nombre.startswith("__")
		]
		prohibidos = [m for m in metodos if m.lstrip("_") in VERBOS_DE_ESCRITURA]
		self.assertEqual(
			prohibidos, [],
			"GithubReadClient no puede tener verbos de escritura; aparecieron: %s" % prohibidos)

	def test_el_unico_post_del_modulo_es_el_de_credenciales(self):
		"""Pedir el token de instalación ES un POST, porque así lo define GitHub.

		No se esconde: se aísla en GithubAppAuth, no toca ningún repositorio, y este test
		fija que no aparezca ningún otro POST en el módulo del cliente.
		"""
		fuente = inspect.getsource(github_client)
		arbol = ast.parse(fuente)
		posts = []
		for nodo in ast.walk(arbol):
			if (isinstance(nodo, ast.Call)
					and isinstance(nodo.func, ast.Attribute)
					and nodo.func.attr in ("post", "patch", "put", "delete")):
				posts.append(nodo.func.attr)
		self.assertEqual(
			posts, ["post"],
			"El módulo del cliente debe tener exactamente una escritura HTTP (el token "
			"de instalación). Encontradas: %s" % posts)

	def test_el_post_de_credenciales_vive_en_la_clase_de_auth(self):
		"""Y está donde tiene que estar, no suelto en el cliente de recursos."""
		self.assertIn("access_tokens", inspect.getsource(github_client.GithubAppAuth))
		self.assertNotIn(".post(", inspect.getsource(github_client.GithubReadClient))
