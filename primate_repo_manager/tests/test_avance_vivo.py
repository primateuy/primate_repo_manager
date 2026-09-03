# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Los avisos de avance: cuándo se emiten, qué llevan y quién puede escucharlos.

Se prueba del lado del servidor, que es donde se puede probar bien. Que la pantalla PINTE
lo que llega es otra cosa y se verifica aparte —tour o revisión visual—; conviene no
confundir las dos garantías.
"""
import contextlib
import inspect
import uuid

from odoo.tests.common import TransactionCase

from ..models import repo_sync

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

		# Costura: el aviso de apertura sale por una conexión propia para que llegue
		# ANTES de que el job confirme. En un test no hay nada confirmado —una conexión
		# nueva ni vería la corrida— así que se la reemplaza por el cursor actual. Lo que
		# queda verificado acá es QUÉ se manda; que salga antes de confirmar se prueba
		# contra el sandbox, mirando la pantalla.
		original_cursor = Run._cursor_de_avisos
		Run._cursor_de_avisos = lambda s: contextlib.nullcontext(s.env.cr)
		self.addCleanup(lambda: setattr(Run, "_cursor_de_avisos", original_cursor))

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


	# --- por qué el aviso de apertura no puede ir en la transacción del job ---

	def test_el_aviso_de_apertura_sale_por_una_conexion_propia(self):
		"""Si fuera por el camino normal llegaría al confirmar el job, o sea junto con el
		«terminé»: la pantalla diría «Ahora: X» con X ya terminado. Es una mentira
		silenciosa —se ve bien, dice mal— y por eso hay un test que la vigila.
		"""
		fuente = inspect.getsource(repo_sync.RepoRepositorySync._job_sync_repository)
		self.assertIn("inmediato=True", fuente,
					  "el aviso de apertura tiene que salir fuera de la transacción")

	def test_el_cierre_de_cada_repositorio_SÍ_va_en_la_transacción(self):
		"""Lo contrario del anterior, y es igual de deliberado: el «terminé» tiene que
		valer sólo si el repositorio quedó realmente guardado. Un aviso de cierre que
		sobreviviera al rollback del job dejaría la pantalla contando repos que no se
		recorrieron."""
		fuente = inspect.getsource(
			self.env["repo.audit.run"].__class__._register_repo_done)
		self.assertIn("self._emitir_avance()", fuente)
		self.assertNotIn("inmediato", fuente)

	def test_la_conexion_de_avisos_solo_inserta(self):
		"""Una conexión aparte que ACTUALICE filas que la transacción principal también
		toca termina en «could not serialize access» — así se descubrió en el paso 3e.
		Los avisos sólo crean filas en `bus.bus`, y este test lo deja escrito."""
		fuente = inspect.getsource(
			self.env["repo.audit.run"].__class__._emitir_avance)
		cuerpo = fuente.split("if not inmediato:")[1]
		for prohibido in (".write(", "self.state =", ".unlink("):
			self.assertNotIn(prohibido, cuerpo)

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
		"""Éste es el test que destapó el AccessError: `search` no filtra, LEVANTA, y sin
		atajarlo el bus se caía entero para cualquier usuario sin acceso al módulo.

		Usa un usuario que YA EXISTE en vez de crear uno. Crear un usuario arrastra la
		creación de un partner, y un partner en una base real arrastra medio ERP
		—contabilidad, ventas, localización— que no tiene nada que ver con lo que se está
		probando acá. `base.public_user` existe en toda base de Odoo y no tiene ni de
		lejos acceso al módulo, que es la única condición que este test necesita.
		"""
		ajeno = self.env.ref("base.public_user")
		self.assertFalse(ajeno.has_group("primate_repo_manager.group_repo_reader"),
						 "el usuario del test tiene que NO tener acceso al módulo")
		canales = self._canales(["repo.audit.run_%s" % self.run.id], usuario=ajeno)
		self.assertNotIn(self.run, canales)

	def test_otros_canales_pasan_intactos(self):
		"""No se rompe lo que pidan otros módulos."""
		canales = self._canales(["algo_de_otro_modulo"])
		self.assertIn("algo_de_otro_modulo", canales)
