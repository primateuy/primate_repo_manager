# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La conciliación: el punto de retorno no se contamina.

EL PROBLEMA QUE ESTO RESUELVE, que el ensayo de D2 dejó a la vista. Una escritura que salió
hacia GitHub y cuyo ciclo no terminó —una caída entre escribir y verificar— deja un efecto
del que la base no sabe nada. Si la operación se vuelve a aplicar, LEE ESE EFECTO COMO SU
ESTADO PREVIO: a partir de ahí el punto de retorno incluye lo que había quedado suelto, y
el rollback devuelve las cosas a un estado que ya lo contenía. Ningún paso miente y el
conjunto igual queda mal.

Es la versión distribuida del «antes invertido» de la reversión, con el agravante de que el
estado contaminado viene de otro proceso y de otra transacción.

LA REGLA: una operación con emisiones sin desenlace no se aplica. Se para y pide conciliar.
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba
from .test_write_apply import (NO_PROTEGIDA, PROTECCION, Respuesta, Transporte,
							   _aprobar_plan, sin_cursor_aparte)


class BaseConciliacion(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Conciliación %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})
		self.backend.private_key = self.clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx"})
		sin_cursor_aparte(self)

	def _plan(self):
		plan = self.env["repo.write.plan"].create({
			"name": "Proteger", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "branch_protection_apply",
			"repository_id": self.repo.id, "target": "19.0",
			"payload_json": json.dumps({
				"required_pull_request_reviews": {
					"required_approving_review_count": 1}})})
		_aprobar_plan(plan)
		return plan

	def _huerfana(self, operacion, previo=None):
		"""Deja la operación como la deja una caída entre escribir y verificar: la
		constancia de que la escritura salió, y ningún desenlace."""
		return self.env["repo.audit.log"].registrar(
			"write_emitted", "salió la escritura",
			backend=self.backend, repository=self.repo,
			previous_state=previo if previo is not None else NO_PROTEGIDA,
			extra={"operation_id": operacion.id})

	def _correr(self, plan, transporte):
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(
			s, transport=transporte)
		try:
			plan.action_apply()
		finally:
			Backend.write_client = original

	def _con_cliente(self, transporte, fn):
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(
			s, transport=transporte)
		try:
			return fn()
		finally:
			Backend.write_client = original


class TestLaCuentaAbiertaFrena(BaseConciliacion):

	def test_una_operación_con_emisión_sin_desenlace_NO_SE_APLICA(self):
		"""EL test. Aplicar de nuevo leería como «estado previo» lo que la escritura
		huérfana dejó, y el punto de retorno quedaría contaminado para siempre.

		MUTACIÓN OBLIGATORIA: sacando la comprobación del paso 0 de `_aplicar`, la
		operación se aplica igual y este test se pone rojo.
		"""
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion)

		transporte = Transporte(gets=[Respuesta(404, NO_PROTEGIDA)])
		self._correr(plan, transporte)

		self.assertEqual(operacion.state, "needs_reconciliation")
		self.assertIn("conciliar", operacion.error.lower())
		# Y NO ESCRIBIÓ: es la mitad que importa. Un estado nuevo que igual escribe no
		# sirve de nada.
		self.assertFalse([e for e in transporte.llamadas if e[0] in ("PUT", "POST",
																	  "DELETE", "PATCH")
						  if "access_tokens" not in e[1]])

	def test_no_es_lo_mismo_que_fallida_ni_que_pendiente(self):
		"""«Fallida» diría que se intentó y salió mal; «pendiente», que no pasó nada. Lo
		que pasó es que hay una cuenta abierta allá afuera."""
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion)
		self._correr(plan, Transporte(gets=[Respuesta(404, NO_PROTEGIDA)]))
		self.assertNotIn(operacion.state, ("failed", "pending", "applied"))

	def test_un_desenlace_registrado_CIERRA_la_cuenta(self):
		"""Una emisión con su desenlace no es una cuenta abierta: así termina el 99 % de
		los ciclos y ninguno de ellos tiene que frenar nada."""
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion)
		self.env["repo.audit.log"].registrar(
			"write_applied", "quedó aplicada", backend=self.backend,
			extra={"operation_id": operacion.id})
		self.assertFalse(operacion._emisiones_sin_desenlace())

	def test_lo_que_depende_de_una_cuenta_abierta_tampoco_corre(self):
		"""La barrera de D2 se apoya en «aplicada» y nada más, así que esto sale gratis —
		pero se prueba, porque es la propiedad que hace que un borrado no corra detrás de
		una copia cuyo desenlace nadie conoce."""
		plan = self._plan()
		copia = plan.operation_ids
		self._huerfana(copia)
		segunda = self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "collaborator_revoke", "sequence": 20,
			"repository_id": self.repo.id, "target": "alguien",
			"payload_json": json.dumps({"permission": "pull"}),
			"depends_on_ids": [(6, 0, copia.ids)]})
		_aprobar_plan(plan)
		self._correr(plan, Transporte(gets=[Respuesta(404, NO_PROTEGIDA)]))
		self.assertEqual(copia.state, "needs_reconciliation")
		self.assertEqual(segunda.state, "blocked_by_dependency")


class TestConciliar(BaseConciliacion):

	def test_si_la_escritura_SÍ_había_quedado_cuenta_como_aplicada(self):
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion)
		transporte = Transporte(gets=[Respuesta(200, PROTECCION)])
		self._con_cliente(transporte, operacion.action_conciliar)

		self.assertEqual(operacion.state, "applied")
		entrada = self.env["repo.audit.log"].search(
			[("operation_id", "=", operacion.id),
			 ("event_type", "=", "write_reconciled_applied")])
		self.assertTrue(entrada, "la decisión tiene que quedar registrada")

	def test_EL_PUNTO_DE_RETORNO_es_el_de_ANTES_de_la_escritura_huérfana(self):
		"""El corazón del asunto. Si la conciliación dejara como punto de retorno lo que
		hay AHORA, revertir devolvería las cosas al estado que ya incluía la escritura
		suelta — que es exactamente el defecto que el ensayo encontró.
		"""
		plan = self._plan()
		operacion = plan.operation_ids
		antes_de_todo = {"required_pull_request_reviews": None, "marca": "el mundo previo"}
		self._huerfana(operacion, previo=antes_de_todo)

		self._con_cliente(Transporte(gets=[Respuesta(200, PROTECCION)]),
						  operacion.action_conciliar)

		punto = json.loads(operacion.audit_log_id.previous_state_json or "{}")
		self.assertEqual(punto, antes_de_todo)

	def test_si_no_quedó_nada_la_operación_vuelve_a_estar_pendiente(self):
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion)
		self._con_cliente(Transporte(gets=[Respuesta(404, NO_PROTEGIDA)]),
						  operacion.action_conciliar)

		self.assertEqual(operacion.state, "pending")
		self.assertTrue(self.env["repo.audit.log"].search(
			[("operation_id", "=", operacion.id),
			 ("event_type", "=", "write_reconciled_none")]))
		# Y ahora sí puede volver a intentarse: la cuenta quedó cerrada.
		self.assertFalse(operacion._emisiones_sin_desenlace())

	def test_el_camino_completo_pasa_por_VOLVER_A_APROBAR(self):
		"""Caída → freno → conciliación → volver a borrador → aprobar → aplicar.

		El plan queda FALLIDO cuando una operación se frena por una cuenta abierta, y un
		plan fallido no se re-aplica: hay que volverlo a borrador, lo que invalida la
		aprobación y obliga a confirmar de nuevo las destructivas.

		Es más molesto y es lo correcto. Entre que alguien aprobó y ahora pasaron dos
		cosas que no estaban en lo que aprobó: una escritura salió sin desenlace, y
		alguien decidió qué hacer con ella. Re-aplicar sin volver a leer el plan sería
		ejecutar bajo una aprobación que se dio para otra situación.
		"""
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion)
		self._correr(plan, Transporte(gets=[Respuesta(404, NO_PROTEGIDA)]))
		self.assertEqual(operacion.state, "needs_reconciliation")
		self.assertEqual(plan.state, "failed",
						 "un plan que no hizo lo que se aprobó no está «aplicado»")

		self._con_cliente(Transporte(gets=[Respuesta(404, NO_PROTEGIDA)]),
						  operacion.action_conciliar)
		self.assertEqual(operacion.state, "pending")

		with self.assertRaises(UserError):
			self._correr(plan, Transporte(gets=[Respuesta(404, NO_PROTEGIDA)]))

		plan.action_back_to_draft()
		_aprobar_plan(plan)
		self._correr(plan, Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA), Respuesta(200, PROTECCION)]))
		self.assertEqual(operacion.state, "applied")
		self.assertEqual(plan.state, "applied")

	def test_conciliar_sin_cuenta_abierta_se_niega_diciéndolo(self):
		plan = self._plan()
		with self.assertRaises(UserError):
			plan.operation_ids.action_conciliar()


class TestElPlanLoDiceEnLaPantalla(BaseConciliacion):
	"""Hallazgo 2 del ensayo: un plan que tuvo una ejecución interrumpida se veía idéntico
	a uno que nunca se ejecutó."""

	def test_un_plan_sin_cuentas_abiertas_no_avisa_nada(self):
		plan = self._plan()
		self.assertFalse(plan.was_interrupted)
		self.assertFalse(plan.interrupted_detail)

	def test_un_plan_con_una_cuenta_abierta_LO_DICE(self):
		plan = self._plan()
		self._huerfana(plan.operation_ids)
		plan.invalidate_recordset()
		self.assertTrue(plan.was_interrupted)
		self.assertIn("conciliarlas", plan.interrupted_detail)

	def test_el_aviso_se_apaga_al_conciliar(self):
		plan = self._plan()
		self._huerfana(plan.operation_ids)
		self._con_cliente(Transporte(gets=[Respuesta(404, NO_PROTEGIDA)]),
						  plan.operation_ids.action_conciliar)
		plan.invalidate_recordset()
		self.assertFalse(plan.was_interrupted)
