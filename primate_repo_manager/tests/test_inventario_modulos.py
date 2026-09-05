# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El inventario de módulos: qué hay, dónde, y si las copias siguen siendo lo mismo."""
import base64
import json
import uuid

from odoo.tests.common import TransactionCase

from .test_backend import RespuestaFalsa, _clave_rsa_de_prueba

MANIFIESTO = b"{'name': 'Cosa linda', 'version': '17.0.1.0.0', 'depends': ['base'], 'license': 'AGPL-3'}"


class TransporteArbol:
	"""Contesta árboles y blobs. Un árbol por rama, con los SHAs que se le pidan."""

	def __init__(self, arboles, blob=MANIFIESTO, truncado=False):
		self.arboles = arboles          # {rama: [(ruta, tipo, sha), ...]}
		self.blob = blob
		self.truncado = truncado
		self.pedidos = []

	def post(self, url, headers=None, timeout=None, **kw):
		return RespuestaFalsa(201, {"token": "ghs_test"})

	def get(self, url, headers=None, timeout=None, **kw):
		self.pedidos.append(url)
		if "/git/trees/" in url:
			rama = url.split("/git/trees/")[1].split("?")[0]
			entradas = [{"path": r, "type": t, "sha": s}
						for r, t, s in self.arboles.get(rama, [])]
			return RespuestaFalsa(200, {"tree": entradas, "truncated": self.truncado})
		if "/git/blobs/" in url:
			return RespuestaFalsa(200, {
				"content": base64.b64encode(self.blob).decode()})
		return RespuestaFalsa(200, {})


def _arbol(carpeta, sha_dir, sha_blob="b1"):
	return [
		(carpeta, "tree", sha_dir),
		("%s/__manifest__.py" % carpeta, "blob", sha_blob),
		("%s/models" % carpeta, "tree", "otro"),
	]


class TestInventarioDeModulos(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Inv %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.backend.private_key = self.clave

	def _repo(self, nombre, ramas=("17.0",)):
		repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "name": nombre,
			"full_name": "%s/%s" % (self.backend.owner_login, nombre),
			"github_id": uuid.uuid4().hex[:8]})
		for rama in ramas:
			self.env["repo.branch"].create({
				"repository_id": repo.id, "name": rama, "role": "base"})
		return repo

	def _escanear(self, repo, transporte):
		Backend = type(self.backend)
		original = Backend.client
		Backend.client = lambda s, transport=None: original(s, transport=transporte)
		try:
			repo._job_scan_modules()
		finally:
			Backend.client = original

	# --- lo que encuentra ---------------------------------------------------

	def test_encuentra_el_modulo_y_lee_su_manifiesto(self):
		repo = self._repo("uno")
		self._escanear(repo, TransporteArbol({"17.0": _arbol("addons/cosa", "sha-a")}))
		modulo = self.env["repo.module"].search([
			("backend_id", "=", self.backend.id), ("technical_name", "=", "cosa")])
		self.assertEqual(len(modulo), 1)
		self.assertEqual(modulo.display_name_manifest, "Cosa linda")
		copia = modulo.copy_ids
		self.assertEqual(copia.version, "17.0.1.0.0")
		self.assertEqual(copia.tree_sha, "sha-a")
		self.assertEqual(json.loads(copia.depends_json), ["base"])
		self.assertTrue(copia.last_seen_at, "regla 3: cuándo se supo")
		self.assertEqual(copia.source, "scan", "regla 3: por dónde entró")

	def test_solo_escanea_las_ramas_de_linea(self):
		"""Escanear todas las ramas sería inventariar cinco veces lo mismo."""
		repo = self._repo("uno", ramas=("17.0",))
		self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "feature/x", "role": "other"})
		t = TransporteArbol({"17.0": _arbol("addons/cosa", "sha-a")})
		self._escanear(repo, t)
		arboles = [u for u in t.pedidos if "/git/trees/" in u]
		self.assertEqual(len(arboles), 1)
		self.assertIn("/git/trees/17.0", arboles[0])

	# --- LA divergencia -----------------------------------------------------

	def test_dos_copias_con_el_mismo_hash_no_divergen(self):
		uno = self._repo("uno")
		otro = self._repo("otro")
		self._escanear(uno, TransporteArbol({"17.0": _arbol("addons/cosa", "IGUAL")}))
		self._escanear(otro, TransporteArbol({"17.0": _arbol("addons/cosa", "IGUAL")}))
		modulo = self.env["repo.module"].search([
			("backend_id", "=", self.backend.id), ("technical_name", "=", "cosa")])
		self.assertEqual(modulo.repository_count, 2)
		self.assertFalse(modulo.divergent)

	def test_dos_copias_con_distinto_hash_SI_divergen(self):
		"""No hace falta bajar nada: el SHA del subárbol es la evidencia."""
		uno = self._repo("uno")
		otro = self._repo("otro")
		self._escanear(uno, TransporteArbol({"17.0": _arbol("addons/cosa", "AAA")}))
		self._escanear(otro, TransporteArbol({"17.0": _arbol("addons/cosa", "BBB")}))
		modulo = self.env["repo.module"].search([
			("backend_id", "=", self.backend.id), ("technical_name", "=", "cosa")])
		self.assertTrue(modulo.divergent)
		self.assertIn("17.0", modulo.divergence_detail)

	def test_versiones_DISTINTAS_no_son_divergencia(self):
		"""Que 17.0 y 19.0 difieran es lo normal. Contarlo como divergencia marcaría a
		casi todo módulo que exista en dos versiones y el dato dejaría de valer."""
		repo = self._repo("uno", ramas=("17.0", "19.0"))
		self._escanear(repo, TransporteArbol({
			"17.0": _arbol("addons/cosa", "AAA"),
			"19.0": _arbol("addons/cosa", "BBB")}))
		modulo = self.env["repo.module"].search([
			("backend_id", "=", self.backend.id), ("technical_name", "=", "cosa")])
		self.assertEqual(modulo.copy_count, 2)
		self.assertFalse(modulo.divergent)

	# --- honestidad ---------------------------------------------------------

	def test_un_arbol_truncado_NO_dice_que_no_hay_modulos(self):
		"""Es la misma regla que los tres estados de protección de F1: «no pude ver» no
		es «no hay»."""
		repo = self._repo("grande")
		self._escanear(repo, TransporteArbol(
			{"17.0": _arbol("addons/cosa", "sha-a")}, truncado=True))
		self.assertEqual(self.env["repo.module"].search_count(
			[("backend_id", "=", self.backend.id)]), 0)
		self.assertTrue(repo.branch_ids[0].module_scan_truncated,
						"la rama tiene que quedar marcada, no en silencio")

	def test_un_manifiesto_ilegible_se_registra_igual(self):
		"""El módulo existe aunque su manifiesto no se pueda parsear."""
		repo = self._repo("uno")
		self._escanear(repo, TransporteArbol(
			{"17.0": _arbol("addons/cosa", "sha-a")}, blob=b"esto no es un dict"))
		copia = self.env["repo.module.copy"].search([("repository_id", "=", repo.id)])
		self.assertEqual(len(copia), 1)
		self.assertFalse(copia.manifest_readable)
		self.assertTrue(copia.manifest_error)

	def test_el_manifiesto_NUNCA_se_evalua_como_codigo(self):
		"""Viene de repositorios que no controlamos del todo. `literal_eval` acepta
		literales y nada más: si alguien mete una llamada, falla en vez de correrla.

		MUTACIÓN: cambiar `literal_eval` por `eval` y este test se pone rojo.
		"""
		import inspect

		from ..models import repo_module

		fuente = inspect.getsource(
			repo_module.RepoRepositoryModuleScan._leer_manifiesto)
		self.assertIn("literal_eval", fuente)
		self.assertNotIn("eval(", fuente.replace("literal_eval(", ""))

		# Y en los hechos: un manifiesto con una llamada no se ejecuta.
		repo = self._repo("uno")
		self._escanear(repo, TransporteArbol(
			{"17.0": _arbol("addons/cosa", "sha-a")},
			blob=b"{'name': __import__('os').getcwd()}"))
		copia = self.env["repo.module.copy"].search([("repository_id", "=", repo.id)])
		self.assertFalse(copia.manifest_readable)

	# --- los filtros --------------------------------------------------------

	def test_los_filtros_no_devuelven_lo_CONTRARIO_de_lo_que_dicen(self):
		"""Odoo normaliza `= True` a `in {True}` antes de llamar al método de búsqueda.
		La primera versión no lo contemplaba y devolvía el filtro invertido en silencio:
		«con copias divergentes» listaba justo las que no divergían.

		MUTACIÓN: sacar la rama de `in`/`not in` de `_pedido_booleano` y esto se pone rojo.
		"""
		uno = self._repo("uno")
		otro = self._repo("otro")
		self._escanear(uno, TransporteArbol({"17.0": _arbol("addons/rota", "AAA")}))
		self._escanear(otro, TransporteArbol({"17.0": _arbol("addons/rota", "BBB")}))
		self._escanear(uno, TransporteArbol({"17.0": _arbol("addons/sana", "IGUAL")}))

		Modulo = self.env["repo.module"].with_context(active_test=False)
		dominio = [("backend_id", "=", self.backend.id)]
		divergentes = Modulo.search(dominio + [("divergent", "=", True)])
		sanos = Modulo.search(dominio + [("divergent", "=", False)])
		self.assertEqual(divergentes.mapped("technical_name"), ["rota"])
		self.assertIn("sana", sanos.mapped("technical_name"))
		self.assertNotIn("rota", sanos.mapped("technical_name"))

	def test_un_comparador_desconocido_LEVANTA_en_vez_de_adivinar(self):
		"""Un filtro que devuelve lo contrario de lo que dice es peor que uno que no
		anda, porque el que no anda se nota."""
		with self.assertRaises(ValueError):
			self.env["repo.module"]._pedido_booleano("like", "cualquier cosa")

	def test_filtrar_por_cuantos_repositorios(self):
		uno = self._repo("uno")
		otro = self._repo("otro")
		self._escanear(uno, TransporteArbol({"17.0": _arbol("addons/dos_veces", "X")}))
		self._escanear(otro, TransporteArbol({"17.0": _arbol("addons/dos_veces", "X")}))
		self._escanear(uno, TransporteArbol({"17.0": _arbol("addons/una_vez", "Y")}))
		Modulo = self.env["repo.module"]
		dominio = [("backend_id", "=", self.backend.id)]
		self.assertEqual(
			Modulo.search(dominio + [("repository_count", ">", 1)]).mapped(
				"technical_name"), ["dos_veces"])

	# --- reescanear no duplica ni escribe de más ----------------------------

	def test_reescanear_actualiza_en_vez_de_duplicar(self):
		repo = self._repo("uno")
		t = TransporteArbol({"17.0": _arbol("addons/cosa", "sha-a")})
		self._escanear(repo, t)
		self._escanear(repo, t)
		self.assertEqual(self.env["repo.module.copy"].search_count(
			[("repository_id", "=", repo.id)]), 1)

	def test_solo_se_escribe_lo_que_cambio(self):
		"""Regla 4 de CLAUDE.md: un write con los mismos datos igual genera un UPDATE, y
		sobre filas que varios jobs tocan eso alcanza para que se maten entre sí."""
		import inspect

		from ..models import repo_module

		fuente = inspect.getsource(
			repo_module.RepoRepositoryModuleScan._registrar_copia)
		self.assertIn("cambios", fuente)
		self.assertIn("copia[c] != v", fuente)
