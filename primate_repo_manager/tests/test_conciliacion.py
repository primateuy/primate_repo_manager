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

	# El estado previo se guarda con la FORMA QUE DEVUELVE EL MANEJADOR, no con la
	# respuesta cruda de GitHub. Importa: la conciliación compara ese estado con el que
	# lee ahora, y si el fixture usara otra forma nunca coincidirían — el test diría
	# «quedó algo distinto» sobre un caso donde no cambió nada. Es un doble que imita mal
	# la mitad de una interfaz, otra vez.
	SIN_PROTEGER = {"protected": False}

	def _huerfana(self, operacion, previo=None):
		"""Deja la operación como la deja una caída entre escribir y verificar: la
		constancia de que la escritura salió, y ningún desenlace."""
		return self.env["repo.audit.log"].registrar(
			"write_emitted", "salió la escritura",
			backend=self.backend, repository=self.repo,
			previous_state=previo if previo is not None else self.SIN_PROTEGER,
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

	def test_UN_APPLY_EXITOSO_NO_DEJA_CUENTAS_ABIERTAS(self):
		"""EL test que faltaba, y el defecto que dejó pasar por escribirlo mal.

		La primera versión de esta prueba creaba la entrada de desenlace A MANO, con el
		enlace a la operación puesto por el test. Con eso verificaba lo que el código
		DEBERÍA hacer y no lo que hacía: las entradas de «aplicada» y «falló» no llevaban
		ese enlace —la operación apuntaba a la entrada, pero no al revés—, así que la
		búsqueda de desenlaces no las encontraba nunca.

		Consecuencia: cada apply EXITOSO dejaba una cuenta abierta por operación, y el
		siguiente apply se habría frenado pidiendo conciliar algo que estaba perfecto. Un
		falso positivo en la guarda que existe para frenar, que es la peor clase.

		Lo encontró la primera corrida contra GitHub de verdad. Ahora el test aplica por
		el camino real y no fabrica ninguna entrada.
		"""
		plan = self._plan()
		operacion = plan.operation_ids
		self._correr(plan, Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA), Respuesta(200, PROTECCION)]))

		self.assertEqual(operacion.state, "applied")
		self.assertFalse(
			operacion._emisiones_sin_desenlace(),
			"un apply que salió bien no puede dejar una cuenta abierta")
		self.assertFalse(plan.was_interrupted)

	def test_un_apply_FALLIDO_tampoco_deja_la_cuenta_abierta(self):
		"""Falló, se registró, y eso ES un desenlace: se sabe cómo terminó. Lo que queda
		abierto es sólo aquello de lo que nadie sabe nada."""
		plan = self._plan()
		operacion = plan.operation_ids
		self._correr(plan, Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA), Respuesta(404, NO_PROTEGIDA)]))
		self.assertEqual(operacion.state, "failed")
		self.assertFalse(operacion._emisiones_sin_desenlace())
		# Pero SÍ hay efecto: la escritura salió aunque la relectura no la confirmara.
		self.assertTrue(operacion._tiene_efecto_en_github())

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
		transporte = Transporte(gets=[Respuesta(200, PROTECCION),
									  Respuesta(200, PROTECCION)])
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

		self._con_cliente(Transporte(gets=[Respuesta(200, PROTECCION),
										   Respuesta(200, PROTECCION)]),
						  operacion.action_conciliar)

		punto = json.loads(operacion.audit_log_id.previous_state_json or "{}")
		self.assertEqual(punto, antes_de_todo)

	def test_QUEDÓ_ALGO_DISTINTO_no_es_lo_mismo_que_no_quedó_nada(self):
		"""EL defecto que encontró la primera corrida contra GitHub de verdad.

		«La verificación no pasa» y «no se escribió nada» NO son lo mismo. La primera
		versión de esto los trataba igual: la operación quedaba «pendiente» y la bitácora
		decía «no hay nada que deshacer» mientras allá afuera había un cambio real. Es la
		misma absorción que toda esta función existe para evitar, un paso más adelante.

		Con transporte falso los dos casos se veían iguales; contra GitHub, no.

		MUTACIÓN: si la conciliación vuelve a decidir sólo por el resultado de la
		verificación —sin comparar con el estado previo—, este test se pone rojo.
		"""
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion, previo=self.SIN_PROTEGER)

		# La verificación no pasa —la protección que hay no es la que se pidió— pero HAY
		# una protección: algo quedó.
		otra_proteccion = {"enforce_admins": {"enabled": True}}
		self._con_cliente(Transporte(gets=[Respuesta(200, otra_proteccion),
										   Respuesta(200, otra_proteccion)]),
						  operacion.action_conciliar)

		self.assertEqual(operacion.state, "failed")
		self.assertIn("NO es lo que se aprobó", operacion.error)
		self.assertTrue(self.env["repo.audit.log"].search(
			[("operation_id", "=", operacion.id),
			 ("event_type", "=", "write_reconciled_other")]))
		# Y lo más importante: sigue habiendo algo que revertir, con el punto de retorno
		# de ANTES de la escritura.
		self.assertTrue(operacion._tiene_efecto_en_github())
		self.assertEqual(
			json.loads(operacion.audit_log_id.previous_state_json), self.SIN_PROTEGER)

	def test_si_no_quedó_nada_la_operación_vuelve_a_estar_pendiente(self):
		plan = self._plan()
		operacion = plan.operation_ids
		self._huerfana(operacion)
		self._con_cliente(Transporte(gets=[Respuesta(404, NO_PROTEGIDA),
										   Respuesta(404, NO_PROTEGIDA)]),
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

		self._con_cliente(Transporte(gets=[Respuesta(404, NO_PROTEGIDA),
										   Respuesta(404, NO_PROTEGIDA)]),
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
		self._con_cliente(Transporte(gets=[Respuesta(404, NO_PROTEGIDA),
										   Respuesta(404, NO_PROTEGIDA)]),
						  plan.operation_ids.action_conciliar)
		plan.invalidate_recordset()
		self.assertFalse(plan.was_interrupted)
