# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Los dos caminos del botón «Auditar».

Lo que se prueba no es que la auditoría funcione —eso ya está cubierto— sino que el botón
DECIDA bien y que el camino sincrónico TERMINE. Antes de esto, apretarlo dejaba la corrida
en «en curso» para siempre si no había un procesador de tareas corriendo.
"""
import uuid

from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba
from .test_sync import REPO_FORK, REPO_PRIVADO_SIN_ADMIN, TransporteAuditoria


class TestLanzarAuditoria(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Lanzar %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected",
		})
		self.backend.private_key = self.clave
		self.transporte = TransporteAuditoria(
			[REPO_PRIVADO_SIN_ADMIN, REPO_FORK])
		Backend = type(self.backend)
		original = Backend.client
		Backend.client = lambda s, transport=None: original(s, transport=self.transporte)
		self.addCleanup(lambda: setattr(Backend, "client", original))

	def _umbral(self, valor):
		self.env["ir.config_parameter"].sudo().set_param(
			"repo_manager.sync_threshold", str(valor))

	def _corrida(self):
		return self.env["repo.audit.run"].create({
			"name": "Prueba", "backend_id": self.backend.id})

	def test_bajo_el_umbral_la_corrida_TERMINA_sola(self):
		"""El caso que estaba roto: el botón dejaba todo esperando."""
		self._umbral(25)
		run = self._corrida()
		run.action_start()

		self.assertEqual(run.repos_total, 2)
		self.assertEqual(run.state, "done",
						 "la corrida tiene que estar terminada al volver del botón")
		self.assertEqual(run.repos_done, 2)
		self.assertTrue(run.finding_ids, "y con sus hallazgos ya calculados")

	def test_sobre_el_umbral_se_encola(self):
		self._umbral(1)
		run = self._corrida()
		antes = self.env["queue.job"].search_count([])
		run.action_start()

		self.assertEqual(run.repos_total, 2)
		self.assertEqual(run.state, "running", "queda en curso hasta que corran los jobs")
		self.assertEqual(self.env["queue.job"].search_count([]) - antes, 2,
						 "un job por repositorio")

	def test_el_umbral_se_decide_con_LO_ENUMERADO_no_con_el_espejo(self):
		"""El espejo y el enumerado no son lo mismo, y la diferencia decide mal.

		El espejo conserva repositorios de corridas anteriores que ya no están en el
		alcance de la instalación. Si el umbral se evaluara sobre él, una cuenta que hoy
		tiene 2 repositorios podría irse al camino encolado por 5 que ya no existen —y con
		el procesador de tareas apagado, la corrida quedaría esperando para siempre.

		Nota sobre la primera versión de este test: comprobaba que el espejo arrancara
		vacío, y eso no distingue nada, porque el enumerado corre ANTES de la decisión y lo
		llena. Pasaba en verde con la lógica equivocada. Lo encontró una mutación que no se
		cazó.
		"""
		# Cinco repositorios viejos que el enumerado de hoy no va a devolver.
		for i in range(5):
			self.env["repo.repository"].create({
				"backend_id": self.backend.id, "github_id": "viejo-%s" % i,
				"name": "viejo-%s" % i, "full_name": "cuenta/viejo-%s" % i,
			})
		self._umbral(3)
		run = self._corrida()
		run.action_start()

		self.assertEqual(run.repos_total, 2, "el enumerado de hoy trae 2")
		self.assertEqual(
			run.state, "done",
			"2 <= 3, así que va por el camino sincrónico: los 5 viejos no cuentan")

	def test_una_conexion_sin_probar_no_audita(self):
		self.backend.state = "draft"
		from odoo.exceptions import UserError
		with self.assertRaises(UserError):
			self._corrida().action_start()
