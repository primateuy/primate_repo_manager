# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La cadena de integridad de la bitácora, y los cuatro tipos de entrada.

La inmutabilidad que ya existía protege del CÓDIGO: `write` y `unlink` levantan excepción
siempre, incluso con `sudo()`. No protege de un `UPDATE` directo en Postgres, y contra eso
no hay defensa posible desde adentro de Odoo — lo único que se puede hacer es volverlo
DETECTABLE. Eso es la cadena.
"""
from odoo.tests.common import TransactionCase


class TestCadenaDeIntegridad(TransactionCase):

	def setUp(self):
		super().setUp()
		self.Log = self.env["repo.audit.log"]

	def test_cada_entrada_se_sella_al_crearse(self):
		entrada = self.Log.registrar("sync", "algo")
		self.assertTrue(entrada.entry_hash)

	def test_cada_entrada_guarda_el_sello_de_la_anterior(self):
		una = self.Log.registrar("sync", "una")
		otra = self.Log.registrar("sync", "otra")
		self.assertEqual(otra.previous_hash, una.entry_hash)

	def test_la_cadena_verifica_en_verde_cuando_nadie_la_tocó(self):
		self.Log.registrar("sync", "una")
		self.Log.registrar("sync", "otra")
		self.assertEqual(self.Log.verificar_cadena()["estado"], "ok")

	# --- EL test: detectar lo que la inmutabilidad no puede impedir ---------

	def test_un_UPDATE_directo_en_la_base_ROMPE_la_cadena(self):
		"""Es el caso entero. Nadie puede impedir un UPDATE por fuera de Odoo; lo que sí
		se puede es que no pase desapercibido.

		MUTACIÓN OBLIGATORIA: si `_sellar` dejara de encadenar —usando siempre '' como
		hash previo, por ejemplo— este test seguiría pasando, pero el de abajo
		(`…detecta_una_entrada_BORRADA`) no. Los dos juntos son la garantía.
		"""
		una = self.Log.registrar("sync", "la verdad")
		self.Log.registrar("sync", "otra")
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
		una = self.Log.registrar("sync", "una")
		dos = self.Log.registrar("sync", "dos")
		self.Log.registrar("sync", "tres")
		self.env.cr.execute("DELETE FROM repo_audit_log WHERE id = %s", (dos.id,))
		self.Log.invalidate_model()
		resultado = self.Log.verificar_cadena()
		self.assertEqual(resultado["estado"], "rota")
		self.assertIn("falta una entrada", resultado["motivo"])

	def test_el_sello_cubre_el_estado_previo_que_usa_el_rollback(self):
		"""El punto de retorno es lo más delicado de la bitácora: si alguien lo cambiara,
		un rollback devolvería el sistema a un estado inventado."""
		entrada = self.Log.registrar(
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
		genesis = self.Log.search([("event_type", "=", "chain_genesis")])
		self.assertTrue(genesis, "el módulo tiene que dejar su entrada cero")
		self.assertIn("NO están encadenadas", genesis[0].summary)
		self.assertTrue(genesis[0].entry_hash)

	def test_asegurar_genesis_no_crea_una_segunda(self):
		antes = self.Log.search_count([("event_type", "=", "chain_genesis")])
		self.Log.asegurar_genesis()
		self.assertEqual(
			self.Log.search_count([("event_type", "=", "chain_genesis")]), antes)

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
		aplicada = self.Log.registrar("write_applied", "se aplicó")
		fallida = self.Log.registrar("write_failed", "falló")
		lectura = self.Log.registrar("sync", "se miró")
		afuera = self.Log.registrar("drift_detected", "alguien tocó GitHub")
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
		entrada = self.Log.registrar("sync", "algo")
		self.env.cr.execute(
			"UPDATE repo_audit_log SET summary = 'x' WHERE id = %s", (entrada.id,))
		self.Log.invalidate_model()
		self.env.user.group_ids = [(4, self.env.ref(
			"primate_repo_manager.group_repo_admin").id)]
		ajustes = self.env["repo.settings"].create({})
		self.assertEqual(ajustes.chain_state, "rota")
		self.assertIn("por fuera de la aplicación", ajustes.chain_detail)
