# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La cadena de integridad de la bitácora, y los cuatro tipos de entrada.

La inmutabilidad que ya existía protege del CÓDIGO: `write` y `unlink` levantan excepción
siempre, incluso con `sudo()`. No protege de un `UPDATE` directo en Postgres, y contra eso
no hay defensa posible desde adentro de Odoo — lo único que se puede hacer es volverlo
DETECTABLE. Eso es la cadena.
"""
import contextlib

from odoo.tests.common import TransactionCase


class TestCadenaDeIntegridad(TransactionCase):
	"""CADA TEST TRABAJA SOBRE SU PROPIO TRAMO.

	La cadena es global —una sola tabla, un solo hilo de sellos— así que un test que
	verificara «la cadena» estaría verificando también lo que dejaron los demás y lo que
	haya en la base de la instalación. Ya pasó con las plantillas de política: un test que
	se pone rojo por algo legítimo enseña a ignorarlo.

	Así que cada test abre su tramo con `cerrar_tramo_y_reabrir`, y la verificación —que
	recorre desde el último génesis— mira exactamente lo que el test escribió. De paso,
	eso prueba el cierre de tramo, que es la herramienta que hay para cuando la cadena se
	rompe por una causa conocida.
	"""

	def setUp(self):
		super().setUp()
		self.Log = self.env["repo.audit.log"]
		self._sellar_en_esta_transaccion()
		self.Log.cerrar_tramo_y_reabrir("Tramo de prueba automatizada.")

	def _sellar_en_esta_transaccion(self):
		"""El sellador corre después del commit y en su propia conexión; en un test no hay
		commit y `postcommit` no corre. Se reemplaza la conexión por la del test y se
		sella a mano, que es lo que deja verificable QUÉ se sella y en qué orden.

		Lo que este reemplazo NO prueba es que el sello sobreviva a una caída entre el
		commit y el sellado. Eso se prueba contra el sandbox, en dos procesos.
		"""
		clase = self.env["repo.audit.log"].__class__
		original = clase._cursor_de_sellado
		clase._cursor_de_sellado = lambda s: contextlib.nullcontext(s.env.cr)
		self.addCleanup(lambda: setattr(clase, "_cursor_de_sellado", original))

	def _registrar(self, *args, **kw):
		"""Registra y sella, que es lo que en producción hace el commit."""
		entrada = self.Log.registrar(*args, **kw)
		self.Log.sellar_pendientes()
		return entrada

	def test_una_entrada_recien_creada_NO_esta_sellada_todavia(self):
		"""Y eso es correcto: el sello se pone al confirmar, porque la confirmación es el
		único momento con un orden total sobre el que todos los escritores coinciden."""
		entrada = self.Log.registrar("sync", "algo")
		self.assertFalse(entrada.entry_hash)
		self.assertEqual(self.Log.verificar_cadena()["pendientes"], 1)

	def test_al_sellar_queda_con_su_sello_y_su_posicion(self):
		entrada = self._registrar("sync", "algo")
		self.assertTrue(entrada.entry_hash)
		self.assertTrue(entrada.chain_seq)

	def test_cada_entrada_guarda_el_sello_de_la_anterior(self):
		una = self._registrar("sync", "una")
		otra = self._registrar("sync", "otra")
		self.assertEqual(otra.previous_hash, una.entry_hash)
		self.assertEqual(otra.chain_seq, una.chain_seq + 1)

	def test_varias_entradas_pendientes_se_sellan_en_UNA_sola_linea(self):
		"""El invariante que la corrección tiene que sostener: cualquiera sea el orden en
		que las entradas se crearon, el sellador las deja en una cadena, no en dos.

		LO QUE ESTE TEST NO PRUEBA, Y HAY QUE DECIRLO. El defecto real necesita DOS
		CONEXIONES con fotos distintas de la base: la de afuera confirma su entrada
		mientras la principal, en `REPEATABLE READ`, todavía no puede verla. Eso no se
		puede montar dentro de una transacción de test —no hay commit, y hay una sola
		conexión—, así que acá se verifica el invariante y no el escenario.

		El escenario se verifica contra el sandbox, en dos procesos, y es exactamente lo
		que hace un apply de verdad: la constancia de emisión sale por la conexión aparte
		y la entrada de aplicada por la principal. Después de un apply, la cadena tiene
		que verificar en verde.
		"""
		de_afuera = self.Log.registrar("write_emitted", "salió la escritura")
		de_adentro = self.Log.registrar("write_applied", "quedó aplicada")
		self.Log.sellar_pendientes()

		self.assertEqual(de_adentro.previous_hash, de_afuera.entry_hash)
		self.assertNotEqual(de_afuera.previous_hash, de_adentro.previous_hash)
		self.assertEqual(self.Log.verificar_cadena()["estado"], "ok")

	def test_la_cadena_verifica_en_verde_cuando_nadie_la_tocó(self):
		self._registrar("sync", "una")
		self._registrar("sync", "otra")
		self.assertEqual(self.Log.verificar_cadena()["estado"], "ok")

	# --- EL test: detectar lo que la inmutabilidad no puede impedir ---------

	def test_un_UPDATE_directo_en_la_base_ROMPE_la_cadena(self):
		"""Es el caso entero. Nadie puede impedir un UPDATE por fuera de Odoo; lo que sí
		se puede es que no pase desapercibido.

		MUTACIÓN OBLIGATORIA: si `_sellar` dejara de encadenar —usando siempre '' como
		hash previo, por ejemplo— este test seguiría pasando, pero el de abajo
		(`…detecta_una_entrada_BORRADA`) no. Los dos juntos son la garantía.
		"""
		una = self._registrar("sync", "la verdad")
		self._registrar("sync", "otra")
		self.assertEqual(self.Log.verificar_cadena()["estado"], "ok")

		self.env.cr.execute(
			"UPDATE repo_audit_log SET summary = %s WHERE id = %s",
			("otra cosa", una.id))
		self.Log.invalidate_model()

		resultado = self.Log.verificar_cadena()
		self.assertEqual(resultado["estado"], "rota")
		self.assertEqual(resultado["entrada"], una.id)
		self.assertIn("contenido", resultado["motivo"])

	def test_la_cadena_detecta_una_entrada_BORRADA(self):
		"""Borrar del medio deja al siguiente apuntando a un sello que ya no existe."""
		una = self._registrar("sync", "una")
		dos = self._registrar("sync", "dos")
		self._registrar("sync", "tres")
		self.env.cr.execute("DELETE FROM repo_audit_log WHERE id = %s", (dos.id,))
		self.Log.invalidate_model()
		resultado = self.Log.verificar_cadena()
		self.assertEqual(resultado["estado"], "rota")
		self.assertIn("falta una entrada", resultado["motivo"])

	def test_el_sello_cubre_el_estado_previo_que_usa_el_rollback(self):
		"""El punto de retorno es lo más delicado de la bitácora: si alguien lo cambiara,
		un rollback devolvería el sistema a un estado inventado."""
		entrada = self._registrar(
			"write_applied", "algo", previous_state={"permiso": "push"})
		self.env.cr.execute(
			"""UPDATE repo_audit_log SET previous_state_json = %s WHERE id = %s""",
			('{"permiso": "admin"}', entrada.id))
		self.Log.invalidate_model()
		self.assertEqual(self.Log.verificar_cadena()["estado"], "rota")

	# --- la génesis ---------------------------------------------------------

	def test_hay_una_genesis_y_dice_que_lo_viejo_NO_esta_encadenado(self):
		"""Sembrar la cadena sobre entradas viejas sería fabricar confianza: estaría
		«verificando» un pasado que nadie encadenó. Lo honesto es decir desde cuándo hay
		garantía."""
		genesis = self.Log.search(
			[("event_type", "=", "chain_genesis")], order="id", limit=1)
		self.assertTrue(genesis, "el módulo tiene que dejar su entrada cero")
		self.assertIn("NO están encadenadas", genesis.summary)

	def test_asegurar_genesis_no_crea_una_segunda(self):
		antes = self.Log.search_count([("event_type", "=", "chain_genesis")])
		self.Log.asegurar_genesis()
		self.assertEqual(
			self.Log.search_count([("event_type", "=", "chain_genesis")]), antes)

	def test_cerrar_un_tramo_EXIGE_un_motivo(self):
		"""Un corte sin motivo dice que hubo un corte y no dice por qué, que es la única
		parte que sirve. Y si el cierre fuera automático ante cualquier rotura, una
		manipulación quedaría tapada por el siguiente arranque."""
		from odoo.exceptions import UserError

		with self.assertRaises(UserError):
			self.Log.cerrar_tramo_y_reabrir("   ")

	def test_el_motivo_del_cierre_queda_sellado_en_la_entrada(self):
		entrada = self.Log.cerrar_tramo_y_reabrir("Bifurcada por el escritor de ayer.")
		self.assertIn("Bifurcada por el escritor de ayer.", entrada.summary)
		self.assertTrue(entrada.entry_hash)
		self.assertEqual(self.Log.verificar_cadena()["estado"], "ok")

	def test_la_verificacion_arranca_en_el_ULTIMO_genesis_y_cuenta_los_tramos(self):
		self._registrar("sync", "del tramo viejo")
		self.Log.cerrar_tramo_y_reabrir("Otro corte.")
		self._registrar("sync", "del tramo nuevo")
		resultado = self.Log.verificar_cadena()
		self.assertEqual(resultado["estado"], "ok")
		# El del setUp, el de este test, y los que hubiera antes en la base.
		self.assertGreaterEqual(resultado["segmentos_cerrados"], 2)

	# --- los cuatro tipos ---------------------------------------------------

	def test_cada_evento_cae_en_uno_de_los_cuatro_tipos(self):
		from ..models.repo_audit_log import (
			CLASE_POR_EVENTO, CLASES_DE_ENTRADA, EVENT_TYPES)

		validas = {c for c, _e in CLASES_DE_ENTRADA}
		for evento, _etiqueta in EVENT_TYPES:
			self.assertIn(evento, CLASE_POR_EVENTO,
						  "«%s» no tiene tipo de entrada asignado" % evento)
			self.assertIn(CLASE_POR_EVENTO[evento], validas)

	def test_lo_que_se_puede_revertir_y_lo_que_no_se_leen_distinto(self):
		aplicada = self._registrar("write_applied", "se aplicó")
		fallida = self._registrar("write_failed", "falló")
		lectura = self._registrar("sync", "se miró")
		afuera = self._registrar("drift_detected", "alguien tocó GitHub")
		self.assertEqual(aplicada.entry_class, "escritura")
		self.assertEqual(fallida.entry_class, "irreversible")
		self.assertEqual(lectura.entry_class, "lectura")
		self.assertEqual(afuera.entry_class, "externo")

	def test_el_diagnostico_de_ajustes_reporta_la_cadena(self):
		self.env.user.group_ids = [(4, self.env.ref(
			"primate_repo_manager.group_repo_admin").id)]
		ajustes = self.env["repo.settings"].create({})
		self.assertEqual(ajustes.chain_state, "ok")
		self.assertIn("Íntegra desde", ajustes.chain_detail)

	def test_una_cadena_rota_se_reporta_como_ROTA_en_el_diagnostico(self):
		entrada = self._registrar("sync", "algo")
		self.env.cr.execute(
			"UPDATE repo_audit_log SET summary = 'x' WHERE id = %s", (entrada.id,))
		self.Log.invalidate_model()
		self.env.user.group_ids = [(4, self.env.ref(
			"primate_repo_manager.group_repo_admin").id)]
		ajustes = self.env["repo.settings"].create({})
		self.assertEqual(ajustes.chain_state, "rota")
		self.assertIn("por fuera de la aplicación", ajustes.chain_detail)
