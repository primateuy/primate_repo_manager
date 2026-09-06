# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La elección forzada cuando las copias divergen — página 5b.

LO QUE ESTOS TESTS DEFIENDEN: que el módulo NO elija por nadie. Ni con un default, ni con
un orden que sugiera, ni con una etiqueta de «recomendada». Y que la consecuencia —qué
desaparece si elegís ésta— se pueda leer ANTES de aprobar, no después.

Y que el diff, que es la única consulta cara, no se haga sola.
"""
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class BaseDivergencia(TransactionCase):

	def setUp(self):
		super().setUp()
		self.Promo = self.env["repo.module.promotion"]
		self.backend = self.env["repo.backend"].create({
			"name": "Divergencia %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})
		self.modulo = self.env["repo.module"].create({
			"backend_id": self.backend.id, "technical_name": "mi_modulo"})

	def _copia(self, repo_nombre, arbol, version="19.0.1.0.0"):
		repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": repo_nombre,
			"full_name": "%s/%s" % (self.backend.owner_login, repo_nombre)})
		rama = self.env["repo.branch"].create({
			"repository_id": repo.id, "name": "17.0", "role": "base"})
		return self.env["repo.module.copy"].create({
			"module_id": self.modulo.id, "repository_id": repo.id,
			"branch_id": rama.id, "line": "17.0", "path": "addons/mi_modulo",
			"tree_sha": arbol, "version": version, "manifest_readable": True})


class TestNadieEligePorVos(BaseDivergencia):

	def test_ninguna_copia_viene_marcada_como_elegida_ni_recomendada(self):
		"""EL test de esta pantalla. Preseleccionar es decidir por otro y después pedirle
		que confirme la decisión propia."""
		self._copia("uno", "AAA")
		self._copia("dos", "BBB")
		datos = self.Promo.opciones(self.modulo.id)
		for opcion in datos["opciones"]:
			self.assertNotIn("elegida", opcion)
			self.assertNotIn("recomendada", opcion)
			self.assertNotIn("referencia", opcion)

	def test_el_orden_es_por_REPOSITORIO_y_no_por_versión_ni_por_fecha(self):
		"""Ordenar por versión pondría una arriba, y lo de arriba se lee como lo
		recomendado. El orden tiene que ser estable y mudo."""
		self._copia("zeta", "AAA", version="19.0.9.9.9")
		self._copia("alfa", "BBB", version="19.0.0.0.1")
		nombres = [o["repositorio"] for o in
				   self.Promo.opciones(self.modulo.id)["opciones"]]
		self.assertEqual(nombres, sorted(nombres),
						 "el orden dejó de ser alfabético por repositorio")

	def test_armar_el_plan_SIN_elegir_se_niega_desde_el_modelo(self):
		"""La pantalla se saltea llamando al método: la obligación vive en el modelo.

		Y SE COMPRUEBA EL MENSAJE, no sólo que falle. Una mutación mostró que este test
		pasaba por el motivo equivocado: la comprobación genérica de «falta algo» saltaba
		antes que la guarda de la elección, así que sacar la guarda no rompía nada y el
		usuario recibía «falta el módulo, la copia o el destino» — que no dice cuál de las
		tres ni por qué importa.
		"""
		self._copia("uno", "AAA")
		destino = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "general",
			"full_name": "%s/general" % self.backend.owner_login})
		with self.assertRaises(UserError) as ctx:
			self.Promo.armar_plan(self.modulo.id, False, destino.id)
		self.assertIn("elegir qué copia gana", str(ctx.exception))
		self.assertIn("No hay opción por defecto", str(ctx.exception))


class TestLaConsecuenciaSeLeeANTES(BaseDivergencia):

	def _consecuencia_de(self, datos, repositorio):
		return next(o["consecuencia"] for o in datos["opciones"]
					if o["repositorio"].endswith(repositorio))

	def test_dice_QUÉ_DESAPARECE_si_elegís_esa(self):
		self._copia("uno", "AAA")
		self._copia("dos", "BBB")
		frase = self._consecuencia_de(self.Promo.opciones(self.modulo.id), "uno")
		self.assertIn("DESAPARECE", frase)
		self.assertIn("dos", frase, "tiene que nombrar de qué repositorio desaparece")

	def test_si_las_otras_son_IDÉNTICAS_no_dice_que_se_pierde_algo(self):
		"""Asustar donde no hay riesgo gasta la alarma que hace falta donde sí lo hay."""
		self._copia("uno", "MISMO")
		self._copia("dos", "MISMO")
		frase = self._consecuencia_de(self.Promo.opciones(self.modulo.id), "uno")
		self.assertIn("no se pierde nada", frase)

	def test_sin_divergencia_no_hay_nada_que_elegir_y_lo_dice(self):
		self._copia("uno", "MISMO")
		self._copia("dos", "MISMO")
		self.assertFalse(self.Promo.opciones(self.modulo.id)["hay_que_elegir"])

	def test_con_divergencia_la_elección_es_obligatoria(self):
		self._copia("uno", "AAA")
		self._copia("dos", "BBB")
		self.assertTrue(self.Promo.opciones(self.modulo.id)["hay_que_elegir"])

	def test_una_copia_con_manifiesto_ilegible_se_dice_asi_y_no_se_omite(self):
		"""Omitirla la sacaría de la decisión sin avisar, y es una copia que existe."""
		self._copia("uno", "AAA")
		mala = self._copia("dos", "BBB")
		mala.write({"manifest_readable": False, "version": False,
					"manifest_error": "el manifiesto no es válido"})
		opcion = next(o for o in self.Promo.opciones(self.modulo.id)["opciones"]
					  if o["repositorio"].endswith("dos"))
		self.assertFalse(opcion["legible"])
		self.assertIn("no es válido", opcion["por_que_no"])


class TestElDiffEsBajoPedido(BaseDivergencia):

	def test_abrir_la_pantalla_NO_consulta_github(self):
		"""La única consulta cara no puede dispararse sola: con seis copias serían quince
		comparaciones que nadie pidió."""
		self._copia("uno", "AAA")
		self._copia("dos", "BBB")

		Backend = type(self.backend)
		original = Backend.client

		def prohibido(self, transport=None):
			raise AssertionError("abrir la pantalla salió a GitHub")

		Backend.client = prohibido
		self.addCleanup(lambda: setattr(Backend, "client", original))
		self.Promo.opciones(self.modulo.id)

	def test_el_diff_compara_por_identificador_y_no_baja_los_archivos(self):
		"""Dos rutas con el mismo identificador son idénticas byte a byte: comparar los
		árboles alcanza, y evita descargar el módulo entero dos veces."""
		a = self._copia("uno", "AAA")
		b = self._copia("dos", "BBB")

		arboles = {
			a.repository_id.full_name: [
				{"type": "blob", "path": "addons/mi_modulo/__manifest__.py", "sha": "m1"},
				{"type": "blob", "path": "addons/mi_modulo/models.py", "sha": "x1"},
				{"type": "blob", "path": "addons/mi_modulo/solo_a.py", "sha": "s1"}],
			b.repository_id.full_name: [
				{"type": "blob", "path": "addons/mi_modulo/__manifest__.py", "sha": "m1"},
				{"type": "blob", "path": "addons/mi_modulo/models.py", "sha": "x2"}],
		}
		llamadas = []

		class ClienteFalso:
			def get(self, ruta, **kw):
				llamadas.append(ruta)
				repo = ruta.split("/repos/")[1].split("/git/")[0]
				return {"tree": arboles[repo], "truncated": False}

		Backend = type(self.backend)
		original = Backend.client
		Backend.client = lambda s, transport=None: ClienteFalso()
		self.addCleanup(lambda: setattr(Backend, "client", original))

		resultado = self.Promo.diff(a.id, b.id)
		self.assertEqual(len(llamadas), 2, "tienen que ser DOS lecturas de árbol y basta")
		self.assertFalse([l for l in llamadas if "/blobs/" in l],
						 "no se bajó ningún archivo, y no hace falta")
		por_ruta = {f["ruta"]: f["estado"] for f in resultado["filas"]}
		self.assertEqual(por_ruta, {"models.py": "distinto", "solo_a.py": "solo_en_a"})
		self.assertEqual(resultado["iguales"], 1)

	def test_el_diff_dice_QUÉ_alcance_tiene(self):
		"""Un diff que no aclara su alcance se lee como si mostrara todo."""
		a, b = self._copia("uno", "AAA"), self._copia("dos", "BBB")
		Backend = type(self.backend)
		original = Backend.client
		Backend.client = lambda s, transport=None: type("C", (), {
			"get": lambda self, ruta, **kw: {"tree": [], "truncated": False}})()
		self.addCleanup(lambda: setattr(Backend, "client", original))
		self.assertIn("línea por línea", self.Promo.diff(a.id, b.id)["alcance"])

	def test_un_arbol_truncado_NO_se_compara_a_medias(self):
		a, b = self._copia("uno", "AAA"), self._copia("dos", "BBB")
		Backend = type(self.backend)
		original = Backend.client
		Backend.client = lambda s, transport=None: type("C", (), {
			"get": lambda self, ruta, **kw: {"tree": [], "truncated": True}})()
		self.addCleanup(lambda: setattr(Backend, "client", original))
		with self.assertRaises(UserError):
			self.Promo.diff(a.id, b.id)


class TestLoQueLaElecciónProduce(BaseDivergencia):

	def test_arma_un_plan_en_BORRADOR_y_no_escribe_nada(self):
		elegida = self._copia("uno", "AAA")
		self._copia("dos", "BBB")
		destino = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "general",
			"full_name": "%s/general" % self.backend.owner_login})
		resultado = self.Promo.armar_plan(self.modulo.id, elegida.id, destino.id)
		plan = self.env["repo.write.plan"].browse(resultado["plan_id"])
		self.assertEqual(plan.state, "draft")
		self.assertEqual(len(plan.operation_ids), 2, "una copia y un retiro")

	def test_los_retiros_DEPENDEN_de_la_copia(self):
		"""La barrera de D2.0, armada desde acá: ningún borrado puede correr si la copia
		no quedó verificada."""
		elegida = self._copia("uno", "AAA")
		self._copia("dos", "BBB")
		destino = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "general",
			"full_name": "%s/general" % self.backend.owner_login})
		plan = self.env["repo.write.plan"].browse(
			self.Promo.armar_plan(self.modulo.id, elegida.id, destino.id)["plan_id"])
		copia = plan.operation_ids.filtered(lambda o: o.kind == "module_copy")
		for borrado in plan.operation_ids.filtered(lambda o: o.kind == "module_delete"):
			self.assertEqual(borrado.depends_on_ids, copia)

	def test_se_puede_promover_SIN_limpiar_y_entonces_no_hay_borrados(self):
		"""«No limpiar todavía» es una salida válida: el módulo queda duplicado y el
		inventario lo sigue marcando."""
		elegida = self._copia("uno", "AAA")
		self._copia("dos", "BBB")
		destino = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "general",
			"full_name": "%s/general" % self.backend.owner_login})
		plan = self.env["repo.write.plan"].browse(
			self.Promo.armar_plan(self.modulo.id, elegida.id, destino.id,
								  limpiar=False)["plan_id"])
		self.assertFalse(plan.operation_ids.filtered(
			lambda o: o.kind == "module_delete"))

	def test_el_plan_avisa_del_addons_path_ANTES_de_aprobarse(self):
		"""Un módulo que saca código de un repositorio y no dice que algo más tiene que
		cambiar rompe producciones ajenas en silencio."""
		elegida = self._copia("uno", "AAA")
		self._copia("dos", "BBB")
		destino = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "general",
			"full_name": "%s/general" % self.backend.owner_login})
		plan = self.env["repo.write.plan"].browse(
			self.Promo.armar_plan(self.modulo.id, elegida.id, destino.id)["plan_id"])
		cuerpos = " ".join(plan.message_ids.mapped("body"))
		self.assertIn("addons", cuerpos)
		self.assertIn("Repo Manager no hace ese cambio", cuerpos)
