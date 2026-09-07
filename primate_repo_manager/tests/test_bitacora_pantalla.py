# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La bitácora como línea de tiempo — página 2d del entregable de diseño.

Dos capas, y hacen falta las dos. Acá se prueba lo que el servidor le da a la pantalla:
las etiquetas, la leyenda y el estado de la cadena ya redactados, que viven en el modelo
justamente para que no haya una segunda copia en JavaScript que se desincronice. El tour
de `test_tour_bitacora` prueba lo otro: que eso se dibuje.
"""
import contextlib
import uuid

from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba


class BaseBitacora(TransactionCase):

	def setUp(self):
		super().setUp()
		self.Log = self.env["repo.audit.log"]
		clase = self.Log.__class__
		original = clase._cursor_de_sellado
		clase._cursor_de_sellado = lambda s: contextlib.nullcontext(s.env.cr)
		self.addCleanup(lambda: setattr(clase, "_cursor_de_sellado", original))
		self.Log.cerrar_tramo_y_reabrir("Tramo de prueba de la pantalla.")

	def _registrar(self, *args, **kw):
		entrada = self.Log.registrar(*args, **kw)
		self.Log.sellar_pendientes()
		return entrada


class TestLoQueLaPantallaLee(BaseBitacora):

	def test_la_leyenda_sale_del_MODELO_y_son_los_cuatro_tipos(self):
		"""Si un día son cinco, son cinco en la clasificación y en la leyenda, o en
		ninguna. Una copia en el componente se desincroniza — pasó con `write_emitted`."""
		from ..models.repo_audit_log import CLASES_DE_ENTRADA

		leyenda = self.Log.leyenda()
		self.assertEqual([i["clase"] for i in leyenda],
						 [c for c, _e in CLASES_DE_ENTRADA])
		self.assertTrue(all(i["forma"] for i in leyenda),
						"cada tipo necesita su forma: el color solo no alcanza")

	def test_cada_evento_dice_CÓMO_TERMINÓ_y_con_qué_tono(self):
		aplicada = self._registrar("write_applied", "se aplicó")
		fallida = self._registrar("write_failed", "falló")
		emitida = self._registrar("write_emitted", "salió, sin verificar")
		self.assertEqual(aplicada.result_label, "Verificado en GitHub")
		self.assertEqual(aplicada.result_kind, "done")
		self.assertEqual(fallida.result_kind, "error")
		self.assertEqual(emitida.result_kind, "live")

	def test_un_evento_sin_resultado_propio_NO_se_queda_mudo(self):
		"""Se dice lo que se sabe. Un chip vacío se lee como «no pasó nada»."""
		entrada = self._registrar("sync", "se miró")
		self.assertTrue(entrada.result_label)

	def test_la_entrada_sin_operación_no_inventa_un_plan(self):
		self.assertFalse(self._registrar("sync", "algo").plan_label)

	def test_el_estado_de_la_cadena_viene_REDACTADO(self):
		"""Lo muestran Ajustes y la bitácora: dos redacciones del mismo hecho terminan
		diciendo cosas distintas del mismo problema."""
		self._registrar("sync", "algo")
		estado = self.Log.estado_de_la_cadena()
		self.assertEqual(estado["estado"], "ok")
		self.assertEqual(estado["tono"], "done")
		self.assertIn("Íntegra desde", estado["detalle"])

	def test_las_entradas_sin_sellar_NO_se_reportan_como_rotura(self):
		"""Es una falsa alarma que se resuelve sola: el sellado corre al confirmar."""
		self.Log.registrar("sync", "recién creada")
		estado = self.Log.estado_de_la_cadena()
		self.assertNotEqual(estado["estado"], "rota")
		self.assertIn("1", estado["detalle"])

	def test_una_cadena_rota_se_dice_rota_y_acusa(self):
		entrada = self._registrar("sync", "la verdad")
		self.env.cr.execute(
			"UPDATE repo_audit_log SET summary = 'otra' WHERE id = %s", (entrada.id,))
		self.Log.invalidate_model()
		estado = self.Log.estado_de_la_cadena()
		self.assertEqual(estado["estado"], "rota")
		self.assertEqual(estado["tono"], "error")
		self.assertIn("por fuera de la aplicación", estado["detalle"])

	def test_el_diagnóstico_de_ajustes_acepta_TODOS_los_estados(self):
		"""«Pendiente» apareció con el sellado post-commit y la selección de Ajustes tenía
		tres valores: asignar uno que no está levanta excepción. Es un estado nuevo del
		modelo que la pantalla no conocía, y es la clase de rotura que nadie ve venir."""
		from ..models.repo_audit_log import EVENT_TYPES  # noqa: F401

		posibles = {"ok", "rota", "vacia", "pendiente"}
		declarados = set(dict(
			self.env["repo.settings"]._fields["chain_state"].selection))
		self.assertFalse(posibles - declarados,
						 "faltan estados en la selección de Ajustes: %s"
						 % (posibles - declarados))


class TestSePuedeRevertirDesdeLaBitacora(BaseBitacora):
	"""El único camino de escritura que la pantalla ofrece."""

	def test_una_lectura_no_ofrece_revertir(self):
		self.assertFalse(self._registrar("sync", "se miró").can_revert)

	def test_una_escritura_sin_operación_tampoco(self):
		"""No hay a qué volver: la reversión es de una operación, no de una frase."""
		self.assertFalse(self._registrar("write_applied", "algo").can_revert)


@tagged("post_install", "-at_install")
class TestTourBitacora(HttpCase):
	"""Y que todo eso SE DIBUJE. Ver el comentario del tour: los tres defectos de la
	primera corrida cargaban sin un solo error."""

	def setUp(self):
		super().setUp()
		clave = _clave_rsa_de_prueba()
		backend = self.env["repo.backend"].create({
			"name": "GitHub — tour bitácora",
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox"})
		backend.private_key = clave
		repo = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx-tour", "full_name": "cuenta/sbx-tour"})
		Log = self.env["repo.audit.log"]
		Log.registrar("write_applied", "Se protegió la rama 17.0", backend=backend,
					  repository=repo, payload={"required_reviews": 1},
					  previous_state={"required_reviews": None})
		Log.registrar("write_failed", "No se pudo bajar el permiso", backend=backend,
					  repository=repo, previous_state={"permission": "admin"})
		# B4.3 · una entrada «Fuera de la app». Se produce por el método que la produce
		# de verdad —el que llama el motor al detectar el desvío—, no con un `create` a
		# mano: una entrada fabricada llevaría los campos que el test quiera y no los que
		# el código pone.
		Log._abrir_drift(
			repo, "primate/cliente-estandar/base",
			"Alguien quitó la protección de 17.0 directamente en GitHub",
			{"required_reviews": 1}, {"required_reviews": None},
			donde="rules", detectado_por="la auditoría #58")
		# El tour necesita entrar. `base.user_admin` existe en toda base de Odoo; en ésta
		# está desactivado, así que se lo despierta para el test. Todo vive dentro de la
		# transacción y se deshace al terminar.
		self.env.ref("base.user_admin").write({
			"active": True, "password": "admin",
			"group_ids": [
				(4, self.env.ref("primate_repo_manager.group_repo_admin").id),
				(4, self.env.ref("primate_repo_manager.group_repo_lead").id),
				(4, self.env.ref("primate_repo_manager.group_repo_reader").id)]})

	def test_la_bitacora_se_dibuja_como_linea_de_tiempo(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_audit_log",
			"prm_bitacora", login="admin")
