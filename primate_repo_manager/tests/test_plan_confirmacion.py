# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La confirmación baja a la fila — página 2b del entregable.

Lo que cambia es DÓNDE se decide, no QUIÉN. La guarda sigue siendo
`repo.write.plan._aprobar`, que se niega si falta una destructiva por confirmar venga de
donde venga la llamada. Estos tests vigilan las dos mitades: que la fila guarde una
confirmación que signifique algo, y que el plan la siga exigiendo.
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba


class BasePlanFila(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Plan fila %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})
		self.backend.private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx"})
		self.plan = self.env["repo.write.plan"].create({
			"name": "Plan de prueba", "backend_id": self.backend.id})

	def _op(self, kind="collaborator_revoke", target="alguien", payload=None):
		return self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": kind, "repository_id": self.repo.id,
			"target": target,
			"payload_json": json.dumps(payload or {"permission": "pull"})})


class TestLaConfirmacionEnLaFila(BasePlanFila):

	def test_confirmar_una_fila_la_deja_escrita_con_quién_y_cuándo(self):
		op = self._op()
		op.action_confirmar()
		self.assertTrue(op.approved)
		self.assertTrue(op.approval_ok)
		self.assertEqual(op.approved_by_id, self.env.user)
		self.assertTrue(op.approved_at)

	def test_CAMBIAR_LA_OPERACIÓN_INVALIDA_SU_CONFIRMACIÓN(self):
		"""EL test de esta tanda. Sin esto, alguien confirma una fila, le cambia el
		payload, y la confirmación queda en pie sobre una operación que hace otra cosa.

		MUTACIÓN: sacando `approval_fingerprint` de la comparación, este test se pone rojo.
		"""
		op = self._op()
		op.action_confirmar()
		self.assertTrue(op.approval_ok)
		op.payload_json = json.dumps({"permission": "admin"})
		self.assertFalse(
			op.approval_ok,
			"la confirmación sobrevivió a un cambio de lo que la operación hace")

	def test_cambiar_la_FRASE_también_la_invalida(self):
		"""Lo que alguien confirmó fue la frase, no el JSON. Es la misma razón por la que
		la descripción entra en la huella del plan."""
		op = self._op()
		op.action_confirmar()
		huella = op.approval_fingerprint
		op.target = "otra-persona"
		self.assertNotEqual(op._huella_de_operacion(), huella)
		self.assertFalse(op.approval_ok)

	def test_desconfirmar_la_borra_entera(self):
		op = self._op()
		op.action_confirmar()
		op.action_desconfirmar()
		self.assertFalse(op.approved)
		self.assertFalse(op.approval_fingerprint)
		self.assertFalse(op.approved_by_id)

	def test_no_se_confirma_lo_que_no_tiene_implementación(self):
		"""Confirmarla no la haría aplicable: sólo escondería el problema hasta el apply,
		que es donde el plan quedaría a medio escribir."""
		op = self._op(kind="ruleset_delete")
		self.assertFalse(op.is_supported)
		with self.assertRaises(UserError):
			op.action_confirmar()

	def test_las_confirmaciones_son_de_BORRADOR(self):
		"""Después de aprobar, el plan está congelado: rehacer confirmaciones ahí sería
		cambiarle el sentido a la aprobación por la espalda.

		LAS DOS DIRECCIONES. Desconfirmar era el agujero: la confirmación de fila no entra
		en la huella del plan —no describe lo que se va a ejecutar—, así que sacarla
		después de aprobado no lo descongelaba y el plan se aplicaba igual, con una
		destructiva que según la pantalla ya nadie había confirmado.
		"""
		op = self._op()
		op.action_confirmar()
		self.plan._aprobar()
		with self.assertRaises(UserError):
			op.action_desconfirmar()
		with self.assertRaises(UserError):
			op.action_confirmar()
		self.assertTrue(op.approval_ok, "la confirmación tiene que seguir en pie")


class TestElLoteSoloAlcanzaALoReversible(BasePlanFila):

	def test_confirmar_todas_las_reversibles_de_una_vez(self):
		ops = self._op(target="uno") | self._op(target="dos") | self._op(target="tres")
		self.assertEqual(ops.action_confirmar_reversibles(), 3)
		self.assertTrue(all(ops.mapped("approval_ok")))

	def test_el_lote_NO_toca_las_irreversibles(self):
		"""La línea que separa las dos: lo reversible se puede aprobar en lote porque
		tiene vuelta; lo que no la tiene se confirma de a una, escribiendo su nombre.

		Hoy ningún tipo del catálogo es irreversible —todos los implementados declaran
		cómo revertirse—, así que el caso se arma agregando un manejador sin `revertir`.
		Es sintético y hay que decirlo: prueba la regla, no un tipo real. El día que exista
		uno de verdad, esta prueba ya lo cubre.
		"""
		Op = type(self.env["repo.write.operation"])
		original = Op._manejadores

		def con_uno_irreversible(self):
			manejadores = original(self)
			manejadores["branch_protection_remove"] = {
				"leer": "_leer_proteccion", "ejecutar": "_quitar_proteccion",
				"verificar": "_verificar_proteccion_quitada"}
			return manejadores

		Op._manejadores = con_uno_irreversible
		self.addCleanup(lambda: setattr(Op, "_manejadores", original))
		self.env["repo.write.operation"].invalidate_model()

		reversible = self._op(target="uno")
		irreversible = self._op(kind="branch_protection_remove", target="19.0")
		self.assertTrue(irreversible.is_irreversible)

		(reversible | irreversible).action_confirmar_reversibles()
		self.assertTrue(reversible.approval_ok)
		self.assertFalse(irreversible.approval_ok,
						 "el lote confirmó una irreversible")

	def test_una_irreversible_exige_el_NOMBRE_EXACTO(self):
		Op = type(self.env["repo.write.operation"])
		original = Op._manejadores

		def con_uno_irreversible(self):
			manejadores = original(self)
			manejadores["branch_protection_remove"] = {
				"leer": "_leer_proteccion", "ejecutar": "_quitar_proteccion",
				"verificar": "_verificar_proteccion_quitada"}
			return manejadores

		Op._manejadores = con_uno_irreversible
		self.addCleanup(lambda: setattr(Op, "_manejadores", original))
		self.env["repo.write.operation"].invalidate_model()

		op = self._op(kind="branch_protection_remove", target="19.0-prod")
		with self.assertRaises(UserError):
			op.action_confirmar()
		with self.assertRaises(UserError):
			op.action_confirmar(nombre="19.0")
		with self.assertRaises(UserError):
			op.action_confirmar(nombre="CONFIRMAR")
		op.action_confirmar(nombre="19.0-prod")
		self.assertTrue(op.approval_ok)


class TestLaGuardaSigueEnElModelo(BasePlanFila):
	"""Lo que la pantalla nueva no puede aflojar."""

	def test_aprobar_sin_confirmaciones_escritas_se_niega(self):
		self._op()
		with self.assertRaises(UserError):
			self.plan._aprobar()

	def test_con_las_filas_confirmadas_aprueba_sin_pasar_confirmadas(self):
		"""La pantalla no le pasa nada a `_aprobar`: el modelo lee lo que está escrito."""
		op = self._op()
		op.action_confirmar()
		self.plan._aprobar()
		self.assertEqual(self.plan.state, "approved")

	def test_una_confirmación_CADUCADA_no_alcanza_para_aprobar(self):
		"""El agujero que la huella por fila tapa: confirmar, cambiar, y aprobar igual."""
		op = self._op()
		op.action_confirmar()
		op.payload_json = json.dumps({"permission": "admin"})
		with self.assertRaises(UserError):
			self.plan._aprobar()

	def test_el_asistente_viejo_sigue_funcionando(self):
		"""Las dos formas entran por la misma guarda; ninguna la esquiva."""
		op = self._op()
		self.plan._aprobar(confirmadas=op)
		self.assertEqual(self.plan.state, "approved")
