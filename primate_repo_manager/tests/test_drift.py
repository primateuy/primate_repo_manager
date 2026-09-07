# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B4.1 · el drift externo: alguien cambió por fuera lo que el módulo aplicó.

LOS HECHOS SE PRODUCEN POR EL CAMINO REAL. Las entradas `write_applied` que sirven de
referencia NO se fabrican a mano: se producen aplicando un plan con el transporte falso,
que es como se producen de verdad. Fabricarlas verificaría lo que el código debería hacer
en vez de lo que hace, y ahí el test absorbe justo el defecto que venía a buscar.
"""
import json
import uuid

from odoo import fields
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba
from .test_write_apply import (
	PROPIO,
	Respuesta,
	Transporte,
	_aprobar_plan,
	_definicion,
	_pedido,
	sin_cursor_aparte,
)


class TestDriftExterno(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Drift %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox",
		})
		self.backend.private_key = self.clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "classification": "cliente",
		})
		self.run = self.env["repo.audit.run"].create({
			"name": "Corrida", "backend_id": self.backend.id, "state": "done"})
		sin_cursor_aparte(self)
		self._aplicar_un_ruleset()

	def _aplicar_un_ruleset(self):
		"""La referencia del drift, producida por el camino real: un apply de verdad."""
		plan = self.env["repo.write.plan"].create({
			"name": "Aplicar", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "ruleset_update", "repository_id": self.repo.id,
			"target": "primate/cliente-estandar/base",
			"payload_json": json.dumps(_pedido(2)),
		})
		_aprobar_plan(plan)
		transporte = Transporte([
			Respuesta(200, [PROPIO]), Respuesta(200, _definicion(1)),
			Respuesta(200, [PROPIO]), Respuesta(200, _definicion(1)),
			Respuesta(200, [PROPIO]), Respuesta(200, _definicion(2)),
		])
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			plan.action_apply()
		finally:
			Backend.write_client = original
		self.assertEqual(plan.operation_ids.state, "applied",
						 plan.operation_ids.error or "")

	def _espejo(self, definicion, present=True):
		fila = self.env["repo.ruleset"].upsert(self.repo, definicion)
		if not present:
			fila.present = False
		return fila

	def _evaluar(self):
		self.env["repo.audit.engine"].evaluate(self.run)
		return self.run.finding_ids.filtered(
			lambda h: h.finding_type == "policy_drift_external")

	def _entradas(self, tipo):
		return self.env["repo.audit.log"].search([
			("repository_id", "=", self.repo.id), ("event_type", "=", tipo)])

	# ------------------------------------------------------------------
	# La referencia
	# ------------------------------------------------------------------

	def test_la_referencia_es_lo_aplicado_y_sale_de_la_bitacora(self):
		ultimas = self.env["repo.audit.log"]._ultimas_escrituras_de_ruleset(self.repo)
		self.assertEqual(len(ultimas), 1)
		self.assertEqual(ultimas[0]["target"], "primate/cliente-estandar/base")
		self.assertEqual(
			ultimas[0]["payload"]["rules"][0]["parameters"]
			["required_approving_review_count"], 2)

	# ------------------------------------------------------------------
	# Los dos resultados de comparar
	# ------------------------------------------------------------------

	def test_si_github_coincide_no_hay_hallazgo(self):
		self._espejo(_definicion(2))
		self.assertFalse(self._evaluar())

	def test_los_defaults_que_agrega_github_NO_son_drift(self):
		"""El mismo criterio que la verificación, compartido y no reimplementado.

		Sin esto, cada auditoría reportaría drift sobre rulesets intactos: el espejo trae
		`allowed_merge_methods`, que nadie mandó. Sería el defecto del ensayo de B1.6
		multiplicado por cada corrida.
		"""
		observada = _definicion(2)
		observada["rules"][0]["parameters"]["allowed_merge_methods"] = ["squash"]
		self._espejo(observada)
		self.assertFalse(self._evaluar())

	def test_si_cambio_lo_que_gobernamos_hay_hallazgo(self):
		self._espejo(_definicion(1))
		hallazgos = self._evaluar()
		self.assertEqual(len(hallazgos), 1)
		self.assertIn("required_approving_review_count", hallazgos.summary)

	def test_si_el_ruleset_desaparecio_es_lo_mas_grave(self):
		self._espejo(_definicion(2), present=False)
		hallazgos = self._evaluar()
		self.assertEqual(hallazgos.severity, "critical")
		self.assertIn("ya no está", hallazgos.summary)

	# ------------------------------------------------------------------
	# La remediación: el incidente se ofrece corregido por el embudo
	# ------------------------------------------------------------------

	def test_el_hallazgo_es_planificable_y_su_payload_es_ejecutable(self):
		"""La excepción a «el payload identifica, no configura», y por qué es una: este
		payload ES la definición que el módulo aplicó y verificó por relectura."""
		self._espejo(_definicion(1))
		hallazgo = self._evaluar()
		self.assertTrue(hallazgo.can_be_planned)
		payload = json.loads(hallazgo.remediation_payload)
		self.assertEqual(
			payload["rules"][0]["parameters"]["required_approving_review_count"], 2)

	def test_la_operacion_que_propone_es_ruleset_update(self):
		self._espejo(_definicion(1))
		hallazgo = self._evaluar()
		self.assertEqual(hallazgo.remediation_action, "reapply_ruleset")

	# ------------------------------------------------------------------
	# La bitácora: sólo el cambio de estado
	# ------------------------------------------------------------------

	def test_el_desvio_deja_una_entrada_de_bitacora(self):
		self._espejo(_definicion(1))
		self._evaluar()
		self.assertEqual(len(self._entradas("drift_detected")), 1)

	def test_auditar_diez_veces_el_mismo_desvio_deja_UNA_entrada(self):
		"""Una entrada por corrida convierte la bitácora en ruido."""
		self._espejo(_definicion(1))
		for _vez in range(3):
			self._evaluar()
		self.assertEqual(len(self._entradas("drift_detected")), 1)

	def test_cuando_vuelve_a_coincidir_se_cierra(self):
		self._espejo(_definicion(1))
		self._evaluar()
		self._espejo(_definicion(2))
		self._evaluar()
		self.assertEqual(len(self._entradas("drift_resolved")), 1)

	def test_no_se_cierra_lo_que_nunca_se_abrio(self):
		"""«No pasa nada» no se anota. Si no, cada corrida limpia dejaría rastro."""
		self._espejo(_definicion(2))
		self._evaluar()
		self.assertFalse(self._entradas("drift_resolved"))

	def test_el_estado_se_deriva_de_la_ultima_entrada_y_no_de_una_bandera(self):
		self._espejo(_definicion(1))
		self._evaluar()
		Log = self.env["repo.audit.log"]
		self.assertEqual(
			Log._estado_de_drift(self.repo, "primate/cliente-estandar/base"),
			"drift_detected")
		self._espejo(_definicion(2))
		self._evaluar()
		self.assertEqual(
			Log._estado_de_drift(self.repo, "primate/cliente-estandar/base"),
			"drift_resolved")

	def test_un_desvio_que_vuelve_despues_de_resuelto_se_anota_otra_vez(self):
		for definicion in (_definicion(1), _definicion(2), _definicion(1)):
			self._espejo(definicion)
			self._evaluar()
		self.assertEqual(len(self._entradas("drift_detected")), 2)
		self.assertEqual(len(self._entradas("drift_resolved")), 1)


class TestMetricasDeLaCorrida(TransactionCase):
	"""B4.1 · la historia se compra desde hoy, no se reconstruye."""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Métricas %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})
		self.run = self.env["repo.audit.run"].create({
			"name": "Corrida", "backend_id": self.backend.id, "state": "done",
			"finished_at": "2026-09-07 12:00:00",
		})

	def test_una_corrida_guarda_sus_numeros(self):
		filas = self.env["repo.metric"].registrar_corrida(self.run)
		self.assertTrue(filas)
		self.assertTrue(all(f.run_id == self.run for f in filas))

	def test_no_se_guardan_dos_veces_ni_se_reescriben(self):
		"""Una medición vieja reescrita con el estado de hoy arruina la serie entera."""
		primeras = self.env["repo.metric"].registrar_corrida(self.run)
		self.assertFalse(self.env["repo.metric"].registrar_corrida(self.run))
		self.assertEqual(
			self.env["repo.metric"].search_count([("run_id", "=", self.run.id)]),
			len(primeras))

	def test_solo_se_guardan_numeros_y_un_ausente_NO_es_un_cero(self):
		"""Un cero inventado es indistinguible de un cero medido dentro de seis meses."""
		metricas = self.env["repo.metric"]._metricas({"numeros": [
			{"clave": "protegidas", "valor": 42, "sin_leer": 3},
			{"clave": "sin_datos", "valor": None, "sin_leer": 0},
			{"clave": "frase", "valor": "todo bien"},
		]})
		self.assertEqual(metricas["protegidas"], 42.0)
		self.assertEqual(metricas["protegidas.sin_leer"], 3.0)
		self.assertNotIn("sin_datos", metricas, "un valor ausente no se guarda como cero")
		self.assertNotIn("frase", metricas)

	def test_el_tramo_sin_leer_viaja_con_su_numero(self):
		"""Sin él, un porcentaje de una corrida donde la mitad no se pudo leer se
		compararía de igual a igual con uno donde se leyó todo."""
		metricas = self.env["repo.metric"]._metricas({"numeros": [
			{"clave": "protegidas", "valor": 100, "sin_leer": 12}]})
		self.assertEqual(metricas["protegidas.sin_leer"], 12.0)


class TestPoliticaSinReaplicar(TransactionCase):
	"""B4.2 · la política se movió acá y los repositorios quedaron atrás.

	Las entradas `policy_changed` NO se fabrican: se producen editando la plantilla, que
	es como se producen de verdad. Y la entrada `write_applied` que marca «hasta acá
	estaba al día» se produce aplicando un plan.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		self.env.flush_all()
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "Vigente", "code": "vig-%s" % uuid.uuid4().hex[:6],
			"classification_default": "cliente",
			"require_pr": True, "required_approvals": 1,
		})
		self.backend = self.env["repo.backend"].create({
			"name": "Deuda %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox",
		})
		self.backend.private_key = self.clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "classification": "cliente",
		})
		self.run = self.env["repo.audit.run"].create({
			"name": "Corrida", "backend_id": self.backend.id, "state": "done"})
		sin_cursor_aparte(self)

	def _aplicar(self):
		"""Deja la marca de «hasta acá estaba al día», por el camino real."""
		nombre = "%s/%s/base" % ("primate", self.plantilla.code)
		plan = self.env["repo.write.plan"].create({
			"name": "Aplicar", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "ruleset_update", "repository_id": self.repo.id,
			"target": nombre,
			"payload_json": json.dumps(_pedido(2, nombre)),
		})
		_aprobar_plan(plan)
		propio = dict(PROPIO, name=nombre)
		transporte = Transporte([
			Respuesta(200, [propio]), Respuesta(200, _definicion(1, nombre)),
			Respuesta(200, [propio]), Respuesta(200, _definicion(1, nombre)),
			Respuesta(200, [propio]), Respuesta(200, _definicion(2, nombre)),
		])
		# El alcance que GitHub reporta para la App tiene que cubrir ESTE repositorio.
		transporte.abarca = [self.repo.full_name]
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			plan.action_apply()
		finally:
			Backend.write_client = original
		self.assertEqual(plan.operation_ids.state, "applied",
						 plan.operation_ids.error or "")
		# Y el espejo queda como quedaría después de la próxima auditoría: con el ruleset
		# que se acaba de aplicar. Sin esto el fixture describe un escenario imposible
		# —aplicamos y GitHub no lo tiene— y el sentido 1 dispara con razón, tapando lo
		# que este test viene a mirar.
		self.env["repo.ruleset"].upsert(self.repo, _definicion(2, nombre))

	def _hallazgos(self):
		self.env["repo.audit.engine"].evaluate(self.run)
		return self.run.finding_ids.filtered(
			lambda h: h.finding_type == "policy_not_reapplied")

	def _atrasar(self, dias=1):
		"""Empuja al pasado TODO lo que ya pasó, para que los cambios queden después.

		No sólo la aplicación: también los cambios de política que ya existen —el alta de
		la plantilla, sin ir más lejos—. Moviendo sólo el apply, la creación de la
		plantilla quedaba DESPUÉS de haberla aplicado, que es una línea de tiempo
		imposible, y el «primer cambio sin aplicar» salía siendo esa alta. El test miraba
		una fecha real de un escenario que no puede existir.
		"""
		entradas = self.env["repo.audit.log"].search([
			("event_type", "in", ("write_applied", "policy_changed"))])
		self.env.cr.execute(
			"UPDATE repo_audit_log SET create_date = create_date - interval '%s days' "
			"WHERE id IN %%s" % dias, (tuple(entradas.ids),))
		entradas.invalidate_recordset(["create_date"])

	# ------------------------------------------------------------------

	def test_sin_cambios_posteriores_no_hay_deuda(self):
		self._aplicar()
		self.assertFalse(self._hallazgos())

	def test_un_cambio_despues_de_aplicar_es_deuda(self):
		self._aplicar()
		self._atrasar()
		self.plantilla.required_approvals = 2
		hallazgos = self._hallazgos()
		self.assertEqual(len(hallazgos), 1)
		self.assertIn(self.plantilla.name, hallazgos.summary)

	def test_TRES_cambios_sin_reaplicar_son_UN_hallazgo_con_la_fecha_del_primero(self):
		"""La deuda es contra la política vigente, no contra cada versión intermedia.

		LOS TRES CAMBIOS TIENEN QUE CAER EN DÍAS DISTINTOS o el test no prueba nada: con
		los tres el mismo día, «el primero» y «el último» dan la misma fecha y la
		aserción pasa aunque el código tome el que no es. Lo destapó una mutación que
		invertía el orden de búsqueda y NO se cazó.
		"""
		self._aplicar()
		self._atrasar(dias=10)
		self.plantilla.required_approvals = 2
		primero = self._ultimo_cambio()
		self._retrasar_cambio(primero, dias=5)
		self.plantilla.require_codeowner_review = True
		self.plantilla.block_deletion = False
		hallazgos = self._hallazgos()
		self.assertEqual(len(hallazgos), 1, "tres cambios NO son tres deudas")
		self.assertIn(str(primero.create_date.date()), hallazgos.summary,
					  "la fecha tiene que ser la del PRIMER cambio sin aplicar")
		self.assertNotIn(str(fields.Date.today()), hallazgos.summary,
						 "no puede ser la fecha del último cambio")

	def test_con_DOS_repositorios_atrasados_la_fecha_es_la_mas_vieja(self):
		"""Con un solo repositorio, tomar el mínimo o tomar el último da lo mismo — y una
		mutación que cambiaba una cosa por la otra pasó en verde. Hacen falta dos."""
		self._aplicar()
		self._atrasar(dias=10)
		self.plantilla.required_approvals = 2
		viejo_cambio = self._ultimo_cambio()
		self._retrasar_cambio(viejo_cambio, dias=7)

		segundo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx2", "full_name": "org/sbx2", "classification": "cliente",
		})
		repo_original, self.repo = self.repo, segundo
		self._aplicar()
		self._atrasar(dias=1)
		self.repo = repo_original
		self.plantilla.require_codeowner_review = True

		hallazgos = self._hallazgos()
		self.assertEqual(len(hallazgos), 1)
		self.assertIn("2 repositorio", hallazgos.summary)
		self.assertIn(str(viejo_cambio.create_date.date()), hallazgos.summary,
					  "la fecha es la del cambio más viejo sin aplicar, no la del último")

	def _ultimo_cambio(self):
		return self.env["repo.audit.log"].search(
			[("event_type", "=", "policy_changed")], order="id desc", limit=1)

	def _retrasar_cambio(self, entrada, dias):
		self.env.cr.execute(
			"UPDATE repo_audit_log SET create_date = create_date - interval '%s days' "
			"WHERE id IN %%s" % dias, (tuple(entrada.ids),))
		entrada.invalidate_recordset(["create_date"])

	def test_el_hallazgo_dice_cuantos_repositorios_quedaron_atras(self):
		self._aplicar()
		self._atrasar()
		self.plantilla.required_approvals = 2
		self.assertIn("1 repositorio", self._hallazgos().summary)

	def test_un_repositorio_donde_NUNCA_se_aplico_no_cuenta_como_deuda(self):
		"""«Nunca se aplicó» no es «quedó atrás»: es la política entera sin escribir."""
		self.plantilla.required_approvals = 2
		self.assertFalse(self._hallazgos())

	def test_cambiar_una_regla_POR_ROL_tambien_mueve_la_politica(self):
		"""Tocar lo que cuelga de la plantilla cambia la política tanto como tocarla."""
		self._aplicar()
		self._atrasar()
		self.env["repo.policy.branch.rule"].create({
			"template_id": self.plantilla.id, "branch_role": "prod",
			"require_pr": True, "required_approvals": 2,
		})
		self.assertTrue(self._hallazgos())

	def test_la_deuda_NO_deja_entrada_en_la_bitacora(self):
		"""Que la política se movió acá ya lo registró A5. Anotarlo como «cambio fuera de
		la app» mentiría sobre dónde pasó."""
		self._aplicar()
		self._atrasar()
		self.plantilla.required_approvals = 2
		antes = self.env["repo.audit.log"].search_count([
			("event_type", "in", ("drift_detected", "drift_resolved"))])
		self._hallazgos()
		self.assertEqual(
			self.env["repo.audit.log"].search_count([
				("event_type", "in", ("drift_detected", "drift_resolved"))]), antes)

	def test_la_deuda_no_se_ofrece_planificable(self):
		"""Reaplicar la plantilla escribe la política VIGENTE sobre N repositorios: ese
		payload nunca se aplicó, así que no vale el argumento del drift externo."""
		self._aplicar()
		self._atrasar()
		self.plantilla.required_approvals = 2
		hallazgo = self._hallazgos()
		self.assertFalse(hallazgo.can_be_planned)
		self.assertTrue(hallazgo.why_not_planned)
