# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Los avisos de avance: cuándo se emiten, qué llevan y quién puede escucharlos.

Se prueba del lado del servidor, que es donde se puede probar bien. Que la pantalla PINTE
lo que llega es otra cosa y se verifica aparte —tour o revisión visual—; conviene no
confundir las dos garantías.
"""
import uuid

from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba
from .test_sync import REPO_FORK, REPO_PRIVADO_SIN_ADMIN, TransporteAuditoria


class TestAvanceVivo(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Vivo %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected",
		})
		self.backend.private_key = self.clave
		self.transporte = TransporteAuditoria([REPO_PRIVADO_SIN_ADMIN, REPO_FORK])
		Backend = type(self.backend)
		original = Backend.client
		Backend.client = lambda s, transport=None: original(s, transport=self.transporte)
		self.addCleanup(lambda: setattr(Backend, "client", original))

		# Se intercepta el envío para poder mirar los mensajes uno por uno.
		self.avisos = []
		Run = self.env["repo.audit.run"].__class__
		envio = Run._bus_send

		def espia(s, tipo, mensaje, **kw):
			self.avisos.append((tipo, mensaje))
			return envio(s, tipo, mensaje, **kw)

		Run._bus_send = espia
		self.addCleanup(lambda: setattr(Run, "_bus_send", envio))

	def _correr(self):
		self.env["ir.config_parameter"].sudo().set_param(
			"repo_manager.sync_threshold", "25")
		run = self.env["repo.audit.run"].create({
			"name": "Prueba", "backend_id": self.backend.id})
		run.action_start()
		return run

	# --- qué se emite y cuándo -----------------------------------------

	def test_hay_un_aviso_al_empezar_cada_repositorio_y_otro_al_cerrarlo(self):
		run = self._correr()
		self.assertEqual(len(self.avisos), 4, "2 repositorios x (empieza + cierra)")
		self.assertTrue(all(t == run.AVISO for t, _m in self.avisos))

	def test_el_aviso_de_apertura_dice_QUÉ_repositorio(self):
		"""Es la señal de vida: sin ella, una corrida lenta y una colgada se ven igual."""
		self._correr()
		actuales = [m["actual"] for _t, m in self.avisos if m["actual"]]
		self.assertEqual(len(actuales), 2)
		self.assertTrue(all(a.startswith("primateuy/") for a in actuales))

	def test_cada_aviso_lleva_el_estado_COMPLETO_no_un_incremento(self):
		"""Si un aviso se pierde —pestaña dormida, reconexión— el siguiente tiene que
		dejar la pantalla al día igual. Con incrementos quedaría desfasada para siempre."""
		self._correr()
		for _t, m in self.avisos:
			for clave in ("id", "state", "total", "done", "error"):
				self.assertIn(clave, m)
		ultimo = self.avisos[-1][1]
		self.assertEqual(ultimo["done"], 2)
		self.assertEqual(ultimo["total"], 2)

	def test_el_ultimo_aviso_trae_el_resumen_de_hallazgos(self):
		"""Es lo que la pantalla muestra al terminar, sin recargar."""
		run = self._correr()
		ultimo = self.avisos[-1][1]
		self.assertIn(ultimo["state"], ("done", "partial"))
		self.assertEqual(ultimo["findings"], run.finding_count)
		self.assertGreater(ultimo["findings"], 0)

	def test_mientras_corre_no_se_manda_un_conteo_de_hallazgos_falso(self):
		"""Antes de terminar no hay hallazgos calculados: informar 0 es correcto, informar
		el conteo parcial de una evaluación a medias sería mentira."""
		self._correr()
		en_curso = [m for _t, m in self.avisos if m["state"] == "running"]
		self.assertTrue(en_curso)
		self.assertTrue(all(m["findings"] == 0 for m in en_curso))


class TestCanalDelBus(TransactionCase):
	"""Quién puede escuchar qué. El nombre del canal lo manda el navegador."""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Canal %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
		})
		self.run = self.env["repo.audit.run"].create({
			"name": "Prueba", "backend_id": self.backend.id})

	def _canales(self, pedidos, usuario=None):
		ws = self.env["ir.websocket"]
		if usuario:
			ws = ws.with_user(usuario)
		# Se prueba el traductor y no `_build_bus_channel_list`: la implementación base
		# necesita una petición HTTP viva, que en un test no existe.
		return ws._traducir_corridas(pedidos)

	def test_una_corrida_que_puedo_leer_se_convierte_en_canal(self):
		canales = self._canales(["repo.audit.run_%s" % self.run.id])
		self.assertIn(self.run, canales)

	def test_el_texto_crudo_NUNCA_queda_como_canal(self):
		"""Si el nombre pedido sobreviviera tal cual, cualquiera escucharía cualquier cosa
		nombrando el canal correcto."""
		pedido = "repo.audit.run_%s" % self.run.id
		self.assertNotIn(pedido, self._canales([pedido]))

	def test_una_corrida_inexistente_se_descarta_sin_decir_nada(self):
		canales = self._canales(["repo.audit.run_999999"])
		self.assertFalse([c for c in canales if getattr(c, "_name", None)
						  == "repo.audit.run"])

	def test_quien_no_puede_leer_la_corrida_no_se_suscribe(self):
		ajeno = self.env["res.users"].create({
			"name": "Ajeno", "login": "ajeno-%s" % uuid.uuid4().hex[:8],
			"group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
		})
		canales = self._canales(["repo.audit.run_%s" % self.run.id], usuario=ajeno)
		self.assertNotIn(self.run, canales)

	def test_otros_canales_pasan_intactos(self):
		"""No se rompe lo que pidan otros módulos."""
		canales = self._canales(["algo_de_otro_modulo"])
		self.assertIn("algo_de_otro_modulo", canales)
