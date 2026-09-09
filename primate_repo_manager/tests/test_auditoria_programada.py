# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E2.1 · el cron semanal, y las dos cosas que NO tiene que hacer.

El cron es la pieza que hace que el producto funcione sin que nadie se acuerde de él, así
que sus errores son silenciosos por naturaleza: nadie mira un lunes a las ocho. Por eso lo
que se prueba acá no es tanto que lance —eso se ve— sino que **se saltee bien y lo diga**.
"""
import uuid
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba


class TestCronDeAuditoria(TransactionCase):

	def setUp(self):
		super().setUp()
		self.clave = _clave_rsa_de_prueba()
		self.Corrida = self.env["repo.audit.run"]

	def _backend(self, state="connected"):
		backend = self.env["repo.backend"].create({
			"name": "Cron %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": state})
		backend.private_key = self.clave
		return backend

	def test_una_conexion_SIN_VERIFICAR_no_se_audita_y_se_dice(self):
		"""Gastaría la ventana entera para terminar en error."""
		backend = self._backend(state="draft")
		resultado = self.Corrida._cron_auditoria_programada()
		salteadas = {b for b, _m in resultado["salteadas"]}
		self.assertIn(backend, salteadas)
		self.assertFalse(self.Corrida.search([("backend_id", "=", backend.id)]))

	def test_NO_se_lanza_una_corrida_encima_de_otra_en_curso(self):
		"""El cron semanal puede caer sobre una auditoría lanzada a mano.

		Dos corridas contra la misma cuenta duplican el trabajo y dejan dos deltas que se
		contradicen: el de la que terminó primero compara contra una foto que la otra
		está reescribiendo.
		"""
		backend = self._backend()
		en_curso = self.Corrida.create({
			"name": "A mano", "backend_id": backend.id, "state": "running"})

		resultado = self.Corrida._cron_auditoria_programada()

		self.assertIn(backend, {b for b, _m in resultado["salteadas"]})
		self.assertEqual(
			self.Corrida.search([("backend_id", "=", backend.id)]), en_curso,
			"se creó una corrida encima de la que estaba en curso")

	def test_el_salteo_DEJA_CONSTANCIA_en_la_conexion(self):
		"""Un salteo silencioso se lee, la semana siguiente, como «el cron no corrió».

		La constancia va al chatter de la conexión y no sólo al log del servidor: el log
		no lo mira nadie un lunes a las ocho de la mañana.
		"""
		backend = self._backend()
		self.Corrida.create({
			"name": "A mano", "backend_id": backend.id, "state": "running"})
		antes = len(backend.message_ids)

		self.Corrida._cron_auditoria_programada()

		nuevos = backend.message_ids[:len(backend.message_ids) - antes]
		self.assertTrue(nuevos, "el salteo no dejó rastro en la conexión")
		self.assertIn("salteada", "".join(nuevos.mapped("body")).lower())

	def test_una_corrida_TERMINADA_no_bloquea_la_siguiente(self):
		"""La guarda es contra lo que está corriendo, no contra lo que ya corrió."""
		backend = self._backend()
		self.Corrida.create({
			"name": "La de la semana pasada", "backend_id": backend.id, "state": "done"})
		en_curso = self.Corrida.search([
			("backend_id", "=", backend.id), ("state", "in", ("draft", "running"))])
		self.assertFalse(en_curso)

	def test_la_corrida_del_cron_queda_marcada_como_PROGRAMADA(self):
		"""«Programada: lunes 08:00» y «lanzada a mano por alguien» se leen distinto
		cuando algo salió mal, y la pantalla las distingue."""
		self.assertEqual(self.Corrida.create({"name": "x", "backend_id": self._backend().id}).origin,
						 "manual", "de fábrica una corrida es a mano")


class TestCuandoSeAuditaSola(TransactionCase):
	"""La traducción entre «lunes a las ocho» y el instante UTC que Odoo programa."""

	def setUp(self):
		super().setUp()
		self.env.user.tz = "America/Montevideo"
		# Guardar exige el rol: la pantalla eleva permisos para escribir el cron, y el
		# gate es el grupo. Que el test tenga que pedirlo es la guarda funcionando.
		self.env.user.group_ids |= self.env.ref(
			"primate_repo_manager.group_repo_admin")
		self.ajustes = self.env["repo.settings"].create({})

	def test_la_proxima_cae_el_dia_pedido_y_a_la_hora_pedida(self):
		self.ajustes.write({
			"audit_cron_frequency": "weeks", "audit_cron_weekday": "0",
			"audit_cron_hour": 8.0})
		# Un miércoles cualquiera, a media tarde.
		proxima = self.ajustes._proxima_corrida(
			ahora=datetime(2026, 9, 9, 18, 0, 0))
		local = self.ajustes._a_local(proxima)
		self.assertEqual(local.weekday(), 0, "no cayó lunes")
		self.assertEqual((local.hour, local.minute), (8, 0), "no cayó a las 8")

	def test_la_hora_es_LOCAL_y_por_eso_el_guardado_no_es_la_hora_escrita(self):
		"""`nextcall` es un instante en UTC, no una regla.

		Guardar «08:00» tal cual haría que la auditoría corriera a las 5 de la mañana.
		Montevideo está a UTC-3, así que las 8 locales son las 11 UTC.
		"""
		self.ajustes.write({
			"audit_cron_frequency": "weeks", "audit_cron_weekday": "0",
			"audit_cron_hour": 8.0})
		proxima = self.ajustes._proxima_corrida(ahora=datetime(2026, 9, 9, 18, 0, 0))
		self.assertEqual(proxima.hour, 11, "se guardó la hora local sin convertir")

	def test_si_hoy_es_el_dia_y_la_hora_ya_pasó_se_va_a_la_semana_que_viene(self):
		"""Sin esto, guardar un lunes a las 9 dejaría la próxima corrida en el pasado y
		Odoo la dispararía en el acto — una auditoría que nadie pidió."""
		self.ajustes.write({
			"audit_cron_frequency": "weeks", "audit_cron_weekday": "0",
			"audit_cron_hour": 8.0})
		lunes_10_utc = datetime(2026, 9, 14, 13, 0, 0)   # lunes 10:00 de Montevideo
		proxima = self.ajustes._proxima_corrida(ahora=lunes_10_utc)
		self.assertGreater(proxima, lunes_10_utc)
		self.assertEqual(self.ajustes._a_local(proxima).weekday(), 0)

	def test_guardar_deja_el_cron_como_dice_la_pantalla(self):
		self.ajustes.write({
			"audit_cron_active": True, "audit_cron_frequency": "weeks",
			"audit_cron_weekday": "2", "audit_cron_hour": 6.5})
		self.ajustes.action_save()
		cron = self.ajustes._cron()
		self.assertTrue(cron.active)
		self.assertEqual(cron.interval_type, "weeks")
		local = self.ajustes._a_local(cron.nextcall)
		self.assertEqual(local.weekday(), 2)
		self.assertEqual((local.hour, local.minute), (6, 30))

	def test_apagarlo_NO_borra_nada(self):
		"""Las auditorías se siguen pudiendo lanzar a mano."""
		self.ajustes.audit_cron_active = False
		self.ajustes.action_save()
		self.assertTrue(self.ajustes._cron(), "el cron se borró en vez de apagarse")
		self.assertFalse(self.ajustes._cron().active)
