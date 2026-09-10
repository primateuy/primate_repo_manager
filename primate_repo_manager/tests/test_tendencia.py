# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E4.1 · la tendencia de las últimas corridas.

LO QUE ESTE ARCHIVO VIGILA ES UN HUECO. Una corrida que falló no tiene medición, y unir el
punto anterior con el siguiente dibujaría una recta que afirma que esa semana se midió y
dio bien. Es la mentira más cómoda de un gráfico: queda más lindo y nadie la revisa.
"""
import uuid

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase


class TestTendencia(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Tend %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.Panel = self.env["repo.health.panel"]

	def _corrida(self, state="done", metricas=None):
		corrida = self.env["repo.audit.run"].create({
			"name": "C %s" % uuid.uuid4().hex[:4], "backend_id": self.backend.id,
			"state": state, "finished_at": fields.Datetime.now()})
		for clave, valor in (metricas or {}).items():
			self.env["repo.metric"].create({
				"run_id": corrida.id, "backend_id": self.backend.id,
				"key": clave, "value": valor,
				"measured_at": fields.Datetime.now()})
		return corrida

	def _tendencia(self):
		return self.Panel._tendencia(self.backend)

	def test_con_UNA_sola_corrida_no_hay_tendencia_y_lo_dice(self):
		"""Un panel de tendencia con un punto es un número con un gráfico alrededor."""
		self._corrida(metricas={"protegidas": 50.0})
		tendencia = self._tendencia()
		self.assertFalse(tendencia["hay"])
		self.assertIn("segunda auditoría", tendencia["motivo"])

	def test_la_serie_va_en_orden_y_trae_el_valor_guardado(self):
		self._corrida(metricas={"protegidas": 40.0})
		self._corrida(metricas={"protegidas": 82.0})

		puntos = self._tendencia()["series"]["protegidas"]

		self.assertEqual([p["valor"] for p in puntos], [40.0, 82.0])
		self.assertTrue(all(p["medida"] for p in puntos))

	def test_una_corrida_FALLIDA_deja_un_HUECO_y_no_un_cero(self):
		"""Un cero es una medición: diría «esa semana no había ninguna rama protegida».
		Lo que pasó es que nadie miró."""
		self._corrida(metricas={"protegidas": 40.0})
		self._corrida(state="error")
		self._corrida(metricas={"protegidas": 82.0})

		puntos = self._tendencia()["series"]["protegidas"]

		self.assertEqual(len(puntos), 3)
		self.assertIsNone(puntos[1]["valor"], "se inventó un valor para la fallida")
		self.assertFalse(puntos[1]["medida"])
		self.assertTrue(puntos[1]["fallida"])
		self.assertEqual([p["valor"] for p in puntos if p["medida"]], [40.0, 82.0])

	def test_una_corrida_TERMINADA_SIN_METRICA_tambien_es_hueco(self):
		"""Puede pasar con corridas viejas, anteriores a que se guardaran métricas. No
		tener el dato y tener el dato en cero son cosas distintas."""
		self._corrida(metricas={"protegidas": 40.0})
		self._corrida()  # terminó bien pero sin métricas
		self._corrida(metricas={"protegidas": 82.0})

		puntos = self._tendencia()["series"]["protegidas"]

		self.assertIsNone(puntos[1]["valor"])
		self.assertFalse(puntos[1]["fallida"], "no falló: no tiene el dato")

	def test_las_TRES_series_salen_juntas(self):
		self._corrida(metricas={"protegidas": 1.0, "convencion": 2.0, "hallazgos": 3.0})
		self._corrida(metricas={"protegidas": 4.0, "convencion": 5.0, "hallazgos": 6.0})
		series = self._tendencia()["series"]
		self.assertEqual(sorted(series), ["convencion", "hallazgos", "protegidas"])

	def test_se_miran_las_ULTIMAS_ocho_y_no_todas(self):
		"""Con una auditoría semanal son dos meses. Más puntos convierten el dibujo en un
		electrocardiograma que nadie lee de un vistazo."""
		for i in range(12):
			self._corrida(metricas={"protegidas": float(i)})
		puntos = self._tendencia()["series"]["protegidas"]
		self.assertEqual(len(puntos), 8)
		self.assertEqual([p["valor"] for p in puntos], [4.0, 5.0, 6.0, 7.0, 8.0, 9.0,
														10.0, 11.0])

	def test_los_valores_NO_se_recalculan_hoy_sino_que_salen_de_la_foto(self):
		"""Recalcular el pasado desde el espejo daría el estado de HOY repetido ocho
		veces, que es un gráfico plano y falso."""
		vieja = self._corrida(metricas={"protegidas": 10.0})
		self._corrida(metricas={"protegidas": 90.0})

		# El espejo cambia; la foto vieja NO.
		self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "nuevo", "full_name": "cuenta/nuevo"})

		puntos = self._tendencia()["series"]["protegidas"]
		self.assertEqual(puntos[0]["valor"], 10.0)
		self.assertEqual(puntos[0]["corrida_id"], vieja.id)

	def test_no_se_mezclan_las_corridas_de_OTRA_conexion(self):
		otro = self.env["repo.backend"].create({
			"name": "Otra", "owner_login": "otra", "owner_type": "user",
			"app_id": "1", "installation_id": "9", "state": "connected"})
		self.env["repo.audit.run"].create({
			"name": "Ajena", "backend_id": otro.id, "state": "done"})
		self._corrida(metricas={"protegidas": 1.0})
		self._corrida(metricas={"protegidas": 2.0})
		self.assertEqual(len(self._tendencia()["series"]["protegidas"]), 2)


@tagged("post_install", "-at_install")
class TestTourTendencia(HttpCase):
	"""Que el DIBUJO respete el hueco. Es lo único que Python no puede ver.

	Una polilínea que una los dos extremos saltándose el hueco pasa todos los tests de
	servidor y afirma en pantalla que esa semana se midió. Con tres corridas y la del
	medio fallida, la línea tiene que salir en DOS tramos.
	"""

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref(
			"primate_repo_manager.group_repo_admin")
		backend = self.env["repo.backend"].create({
			"name": "GitHub — tour tendencia",
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox"})
		repo = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "cuenta/sbx", "classification": "cliente"})
		Run = self.env["repo.audit.run"]
		Metric = self.env["repo.metric"]
		# CINCO CORRIDAS Y EL HUECO AL MEDIO. Con tres, cada lado queda con un solo punto
		# y no hay tramo que dibujar —una línea necesita dos puntos— así que el dibujo
		# saldría vacío y el tour no probaría nada. Con dos a cada lado, la pregunta que
		# importa se puede hacer: ¿son dos tramos o uno que cruza el hueco?
		for estado, valores in (
				("done", {"protegidas": 40.0, "convencion": 30.0, "hallazgos": 9.0}),
				("done", {"protegidas": 45.0, "convencion": 33.0, "hallazgos": 8.0}),
				("error", None),
				("done", {"protegidas": 70.0, "convencion": 60.0, "hallazgos": 4.0}),
				("done", {"protegidas": 82.0, "convencion": 67.0, "hallazgos": 3.0})):
			corrida = Run.create({
				"name": "Corrida", "backend_id": backend.id, "state": estado,
				"finished_at": fields.Datetime.now()})
			self.env["repo.audit.run.line"].create({
				"run_id": corrida.id, "repository_id": repo.id,
				"state": "done" if estado == "done" else "error"})
			for clave, valor in (valores or {}).items():
				Metric.create({
					"run_id": corrida.id, "backend_id": backend.id, "key": clave,
					"value": valor, "measured_at": fields.Datetime.now()})

	def test_la_linea_se_corta_en_la_corrida_sin_medicion(self):
		self.start_tour(
			"/odoo/action-primate_repo_manager.action_repo_panel_salud",
			"prm_tendencia", login="admin")


class TestLaMeta(TransactionCase):
	"""E4.2 · la meta es ASPIRACIÓN, no política.

	El panel la muestra; no la reclama. Lo que el módulo exige vive en la plantilla de
	política, que es donde se decide con alguien. Confundir las dos convertiría un deseo
	en un incumplimiento — y este módulo ya tiene un lugar para los incumplimientos.
	"""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Meta %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "uno", "full_name": "cuenta/uno", "classification": "cliente"})
		self.corrida = self.env["repo.audit.run"].create({
			"name": "C", "backend_id": self.backend.id, "state": "done",
			"finished_at": fields.Datetime.now()})
		self.Panel = self.env["repo.health.panel"]

	def _poner(self, clave, valor):
		self.env["ir.config_parameter"].sudo().set_param(clave, valor)

	def _numeros(self):
		return {n["clave"]: n
				for n in self.Panel.datos(backend_id=self.backend.id)["numeros"]}

	def test_de_fabrica_NO_hay_meta(self):
		"""Una meta que el producto elige por vos es una exigencia que nadie decidió."""
		for numero in self._numeros().values():
			self.assertIsNone(numero["meta"])

	def test_la_meta_puesta_aparece_en_su_numero(self):
		self._poner("repo_manager.meta_convencion", "85")
		numeros = self._numeros()
		self.assertEqual(numeros["convencion"]["meta"], 85.0)
		self.assertIsNone(numeros["protegidas"]["meta"], "la meta es POR número")

	def test_VACIO_NO_ES_CERO(self):
		"""«Sin meta» y «meta cero» son cosas distintas: la segunda es exigente, no
		ausente. Por eso las metas son texto y no enteros."""
		self._poner("repo_manager.meta_hallazgos", "0")
		self.assertEqual(self._numeros()["hallazgos"]["meta"], 0.0)
		self._poner("repo_manager.meta_hallazgos", "")
		self.assertIsNone(self._numeros()["hallazgos"]["meta"])

	def test_una_meta_ILEGIBLE_no_rompe_el_panel(self):
		"""El panel es lo primero que alguien abre: un valor mal tipeado en Ajustes no
		puede dejarlo en blanco."""
		self._poner("repo_manager.meta_protegidas", "ochenta y cinco")
		self.assertIsNone(self._numeros()["protegidas"]["meta"])

	# --- lo que la meta NO hace ---

	def test_la_meta_NO_genera_hallazgos(self):
		"""Es la guarda que separa aspiración de política."""
		self._poner("repo_manager.meta_protegidas", "100")
		self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": "19.0", "role": "base",
			"protected": False, "protection_readable": True})

		self.env["repo.audit.engine"].evaluate(self.corrida)

		tipos = set(self.corrida.finding_ids.mapped("finding_type"))
		self.assertFalse({t for t in tipos if "meta" in t},
						 "la meta generó un hallazgo: dejó de ser aspiración")

	def test_la_meta_NO_entra_en_el_delta(self):
		"""El delta compara dos corridas entre sí, no contra un deseo."""
		anterior = self.env["repo.audit.run"].create({
			"name": "Antes", "backend_id": self.backend.id, "state": "done",
			"finished_at": fields.Datetime.now()})
		self.env["repo.metric"].create({
			"run_id": anterior.id, "backend_id": self.backend.id,
			"key": "protegidas", "value": 40.0,
			"measured_at": fields.Datetime.now()})
		self._poner("repo_manager.meta_protegidas", "100")

		delta = self.corrida.delta()

		self.assertFalse(delta["nuevos"])
		self.assertFalse(delta["resueltos"])

	def test_la_meta_NO_cambia_el_valor_ni_el_delta_del_numero(self):
		self._poner("repo_manager.meta_protegidas", "100")
		numero = self._numeros()["protegidas"]
		self.assertIn("valor", numero)
		self.assertEqual(numero["meta"], 100.0)
		# El valor sigue siendo el medido, no la distancia a la meta.
		self.assertNotEqual(numero["valor"], 100.0)


class TestLoQueSoloSeVioMIRANDO(TransactionCase):
	"""E4.3 · lo que el repaso contra el mockup encontró abriendo el panel.

	Ninguno de estos cuatro lo habría encontrado un test: los cuatro son verdaderos en el
	sentido de «el dato es correcto» y falsos en el sentido de «lo que la pantalla afirma».
	Quedan escritos como tests para que no vuelvan.
	"""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Mirar %s" % uuid.uuid4().hex[:6],
			"owner_login": "primateuy-%s" % uuid.uuid4().hex[:6],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "uno", "full_name": "cuenta/uno", "classification": "cliente"})
		self.Panel = self.env["repo.health.panel"]

	def test_la_cuenta_DUEÑA_no_es_una_cuenta_sin_dueño(self):
		"""Detrás de ella no hay un empleado: es la identidad de la empresa, y el motor
		ya la exime. El panel la contaba igual y señalaba a la cuenta de la propia
		organización como «cuenta que nadie reconoce como propia»."""
		duena = self.env["repo.member"].create(
			{"github_login": self.backend.owner_login})
		ajena = self.env["repo.member"].create(
			{"github_login": "ext-%s" % uuid.uuid4().hex[:6]})
		for miembro in (duena, ajena):
			self.env["repo.collaborator"].create({
				"repository_id": self.repo.id, "member_id": miembro.id,
				"permission": "push"})

		sin_dueno = self.Panel._sin_dueno(self.backend)

		self.assertEqual(sin_dueno["cuantas"], 1)
		self.assertNotIn(self.backend.owner_login, sin_dueno["quienes"])

	def test_el_aviso_de_auditoria_EN_CURSO_dice_que_los_numeros_son_viejos(self):
		"""Es lo único que sólo puede decirse en el panel. Sin esa frase, quien lo abre
		mientras algo corre decide con datos de la semana pasada creyendo que son de hoy.
		"""
		self.env["repo.audit.run"].create({
			"name": "Terminada", "backend_id": self.backend.id, "state": "done",
			"finished_at": fields.Datetime.now()})
		corriendo = self.env["repo.audit.run"].create({
			"name": "En curso", "backend_id": self.backend.id, "state": "running",
			"started_at": fields.Datetime.now()})
		self.env["repo.audit.run.line"].create({
			"run_id": corriendo.id, "repository_id": self.repo.id, "state": "done"})

		datos = self.Panel.datos(backend_id=self.backend.id)

		self.assertTrue(datos["en_curso"]["hay"])
		self.assertEqual(datos["en_curso"]["leidos"], 1)
		self.assertTrue(datos["en_curso"]["los_numeros_son_de"])

	def test_sin_nada_corriendo_no_hay_aviso(self):
		self.env["repo.audit.run"].create({
			"name": "Terminada", "backend_id": self.backend.id, "state": "done",
			"finished_at": fields.Datetime.now()})
		self.assertFalse(
			self.Panel.datos(backend_id=self.backend.id)["en_curso"]["hay"])

	def test_el_panel_dice_cuantos_hallazgos_YA_ESTAN_en_un_plan(self):
		"""Es la diferencia entre una lista de problemas y una lista de problemas de los
		que alguien ya se ocupó."""
		corrida = self.env["repo.audit.run"].create({
			"name": "C", "backend_id": self.backend.id, "state": "done",
			"finished_at": fields.Datetime.now()})
		plan = self.env["repo.write.plan"].create(
			{"name": "P", "backend_id": self.backend.id})
		for i, con_plan in enumerate((True, False)):
			hallazgo = self.env["repo.audit.finding"].create({
				"run_id": corrida.id, "repository_id": self.repo.id,
				"finding_type": "permission_exceeded", "severity": "high",
				"subject": "quien-%s" % i, "summary": "algo %s" % i})
			if con_plan:
				self.env["repo.write.operation"].create({
					"plan_id": plan.id, "kind": "collaborator_revoke",
					"repository_id": self.repo.id, "target": hallazgo.subject,
					"payload_json": "{}", "finding_id": hallazgo.id})

		numeros = {n["clave"]: n
				   for n in self.Panel.datos(backend_id=self.backend.id)["numeros"]}

		self.assertEqual(numeros["hallazgos"]["en_plan"], 1)
