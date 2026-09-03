# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El congelamiento del plan aprobado.

Lo que se prueba acá no es que el flujo funcione, sino que NO funcione cuando el plan
cambió después de aprobarse. La guarda es la comparación de huellas; el volver a borrador
es cortesía.
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPlanCongelado(TransactionCase):

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref(
			"primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Plan %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox",
		})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "un-repo", "full_name": "cuenta/un-repo",
		})
		self.plan = self.env["repo.write.plan"].create({
			"name": "Proteger 19.0", "backend_id": self.backend.id,
		})
		self.op = self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "sequence": 10,
			"kind": "branch_protection_apply",
			"repository_id": self.repo.id, "target": "19.0",
			"payload_json": json.dumps({"required_approving_review_count": 1}),
		})

	def _aprobar(self):
		# `action_approve` abre el asistente desde A4.4; el modelo es el que aprueba.
		self.plan._aprobar(
			confirmadas=self.plan.operation_ids.filtered("is_destructive"))
		self.assertEqual(self.plan.state, "approved")
		self.assertTrue(self.plan.is_frozen)

	# --- la aprobación registra qué se aprobó -------------------------------

	def test_aprobar_guarda_huella_quien_y_cuando(self):
		self._aprobar()
		self.assertTrue(self.plan.approval_fingerprint)
		self.assertEqual(self.plan.approved_by_id, self.env.user)
		self.assertTrue(self.plan.approved_at)
		self.assertEqual(self.plan.approval_fingerprint, self.plan.current_fingerprint)

	def test_un_plan_vacio_no_se_aprueba(self):
		vacio = self.env["repo.write.plan"].create({
			"name": "Vacío", "backend_id": self.backend.id})
		# Vale por los dos caminos: el botón ni siquiera abre el asistente, y el modelo
		# tampoco aprueba si alguien lo llama directo.
		with self.assertRaises(UserError):
			vacio.action_approve()
		with self.assertRaises(UserError):
			vacio._aprobar()

	# --- qué invalida y qué no ----------------------------------------------

	def test_cambiar_un_payload_invalida_la_aprobacion(self):
		self._aprobar()
		self.op.payload_json = json.dumps({"required_approving_review_count": 2})

		self.assertFalse(self.plan.is_frozen)
		self.assertEqual(self.plan.state, "draft")
		self.assertFalse(self.plan.approval_fingerprint)

	def test_agregar_una_operacion_invalida_la_aprobacion(self):
		self._aprobar()
		self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "sequence": 20,
			"kind": "collaborator_grant", "repository_id": self.repo.id,
			"target": "alguien", "payload_json": json.dumps({"permission": "admin"}),
		})
		self.assertEqual(self.plan.state, "draft")

	def test_borrar_una_operacion_invalida_la_aprobacion(self):
		self._aprobar()
		self.op.unlink()
		self.assertEqual(self.plan.state, "draft")

	def test_reordenar_invalida_la_aprobacion(self):
		"""El orden importa: aplicar y después revertir no es lo mismo que al revés."""
		otra = self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "sequence": 20,
			"kind": "branch_protection_remove", "repository_id": self.repo.id,
			"target": "17.0",
		})
		self._aprobar()
		huella = self.plan.approval_fingerprint
		otra.sequence = 5

		self.assertNotEqual(self.plan.current_fingerprint, huella)
		self.assertEqual(self.plan.state, "draft")

	def test_renombrar_o_anotar_NO_invalida(self):
		"""La huella cubre lo que se ejecuta, no lo cosmético."""
		self._aprobar()
		huella = self.plan.approval_fingerprint

		self.plan.name = "Otro nombre"
		self.plan.note = "una nota cualquiera"

		self.assertEqual(self.plan.state, "approved")
		self.assertTrue(self.plan.is_frozen)
		self.assertEqual(self.plan.approval_fingerprint, huella)

	def test_cambiar_la_conexion_si_invalida(self):
		self._aprobar()
		otro_backend = self.env["repo.backend"].create({
			"name": "Otra %s" % uuid.uuid4().hex[:6],
			"owner_login": "otra-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"environment": "sandbox",
		})
		self.plan.backend_id = otro_backend
		self.assertEqual(self.plan.state, "draft")

	# --- la guarda dura ------------------------------------------------------

	def test_la_guarda_no_confia_en_el_estado(self):
		"""Aun forzando el estado a `approved`, la huella que no coincide manda.

		Es el escenario que un flag no cubre: alguien deja el estado en aprobado —por SQL,
		por un método que lo escriba, por un bug— y el contenido ya no es el aprobado.
		"""
		self._aprobar()
		huella_vieja = self.plan.approval_fingerprint
		self.op.payload_json = json.dumps({"required_approving_review_count": 9})
		# Se reconstruye la apariencia de un plan aprobado, con la huella VIEJA.
		self.plan.write({"state": "approved"})
		self.plan.approval_fingerprint = huella_vieja

		self.assertEqual(self.plan.state, "approved")
		with self.assertRaises(UserError) as ctx:
			self.plan._verificar_congelado()
		self.assertIn("cambió después de que lo aprobaran", str(ctx.exception))

	def test_sin_aprobacion_no_se_ejecuta(self):
		with self.assertRaises(UserError) as ctx:
			self.plan._verificar_congelado()
		self.assertIn("no tiene aprobación registrada", str(ctx.exception))

	def test_un_plan_intacto_pasa_la_guarda(self):
		self._aprobar()
		self.assertTrue(self.plan._verificar_congelado())

	# --- normalización del payload -------------------------------------------

	def test_reordenar_las_claves_del_json_no_cuenta_como_cambio(self):
		"""Dos JSON equivalentes tienen que dar la misma huella; si no, cualquier
		reserialización invalidaría aprobaciones sin que nada haya cambiado."""
		self.op.payload_json = json.dumps({"a": 1, "b": 2})
		self._aprobar()
		huella = self.plan.approval_fingerprint

		self.op.payload_json = json.dumps({"b": 2, "a": 1})
		self.assertEqual(self.plan.current_fingerprint, huella)

	def test_un_payload_roto_igual_entra_en_la_huella(self):
		"""Si los inválidos colapsaran en el mismo valor, cambiar uno por otro pasaría."""
		self.op.payload_json = "{no es json"
		h1 = self.plan.current_fingerprint
		self.op.payload_json = "{tampoco es json"
		self.assertNotEqual(self.plan.current_fingerprint, h1)
