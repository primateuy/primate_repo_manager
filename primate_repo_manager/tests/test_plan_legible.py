# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""A4.4: un plan se lee antes de aprobarlo, y lo destructivo se confirma de a uno.

Aprobar mirando `{"required_approving_review_count": 2}` no es aprobar: es confiar en que
alguien más lo leyó. Y aprobar veinte revocaciones con un click tampoco — «nunca en lote»
de la spec de F2 se refiere a la decisión, no al armado.
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba


class BasePlan(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Plan %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox",
		})
		self.backend.private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "name": "sbx-uno",
			"full_name": "%s/sbx-uno" % self.backend.owner_login,
			"github_id": uuid.uuid4().hex[:8],
		})
		self.plan = self.env["repo.write.plan"].create({
			"name": "Plan de prueba", "backend_id": self.backend.id})
		self.env.user.group_ids = [(4, self.env.ref(
			"primate_repo_manager.group_repo_lead").id)]

	def _op(self, kind, target="17.0", payload=None, sequence=10):
		return self.env["repo.write.operation"].create({
			"plan_id": self.plan.id, "kind": kind, "sequence": sequence,
			"repository_id": self.repo.id, "target": target,
			"payload_json": json.dumps(payload) if payload else False,
		})


class TestDescripcionLegible(BasePlan):

	def test_una_proteccion_se_dice_en_castellano(self):
		op = self._op("branch_protection_apply", payload={
			"required_pull_request_reviews": {
				"required_approving_review_count": 2,
				"require_code_owner_reviews": True},
			"allow_force_pushes": False,
			"allow_deletions": False,
		})
		self.assertIn("sbx-uno", op.description)
		self.assertIn("17.0", op.description)
		self.assertIn("2 aprobación", op.description)
		self.assertIn("bloquear force-push", op.description)
		self.assertNotIn("required_approving_review_count", op.description,
						 "la frase es para leer, no el JSON con otro formato")

	def test_lo_destructivo_dice_QUÉ_se_pierde(self):
		"""«Quitar protección» no alcanza: hay que decir qué pasa a estar permitido."""
		op = self._op("branch_protection_remove")
		self.assertTrue(op.is_destructive)
		self.assertIn("SIN PROTECCIÓN", op.description)
		self.assertIn("force-push", op.description)

	def test_revocar_un_permiso_directo_aclara_lo_del_team(self):
		"""Es el matiz que ya nos mordió en F2: revertir un grant directo no deja a alguien
		sin acceso si además está en un team."""
		op = self._op("collaborator_revoke", target="alguien")
		self.assertIn("team", op.description)

	def test_un_tipo_sin_frase_propia_no_se_queda_mudo(self):
		"""Un vacío en la columna parece «no hace nada», que es lo peor que puede decir."""
		op = self._op("team_member_add", target="equipo",
					  payload={"username": "alguien"})
		self.assertTrue(op.description)
		self.assertIn("alguien", op.description)

	def test_las_destructivas_estan_marcadas(self):
		esperado = {
			"branch_protection_remove": True, "ruleset_delete": True,
			"collaborator_revoke": True, "team_repo_revoke": True,
			"team_member_remove": True,
			"branch_protection_apply": False, "ruleset_create": False,
			"collaborator_grant": False, "team_repo_grant": False,
			"team_member_add": False,
		}
		for kind, destructiva in esperado.items():
			op = self._op(kind, target="x")
			self.assertEqual(op.is_destructive, destructiva, kind)


class TestLaHuellaCongelaLaFrase(BasePlan):

	def test_la_descripcion_entra_en_la_huella(self):
		"""Hashear un valor derivado no detecta cambios en el origen —para eso está el
		payload— sino cambios EN QUIEN LO DERIVA. Si mañana cambia la redacción, los planes
		aprobados y sin aplicar mostrarían una frase distinta de la que se aprobó.

		MUTACIÓN: sacando `descripcion` del cuerpo de `_huella`, este test se pone rojo.
		"""
		op = self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		huella_antes = self.plan._huella()

		# Se fuerza una descripción distinta SIN tocar nada ejecutable, que es exactamente
		# lo que pasaría si cambiara el código que la deriva.
		op.sudo().write({"description": "otra frase"})
		self.plan.invalidate_recordset()
		self.assertNotEqual(self.plan._huella(), huella_antes,
							"cambiar la frase tiene que cambiar la huella")

	def test_cambiar_la_frase_saca_al_plan_de_la_aprobacion(self):
		op = self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		self.plan._aprobar()
		self.assertEqual(self.plan.state, "approved")
		self.assertTrue(self.plan.is_frozen)

		op.sudo().write({"description": "otra frase"})
		self.plan.invalidate_recordset()
		self.assertFalse(self.plan.is_frozen,
						 "lo que se aprobó fue la frase, no sólo el JSON")


class TestConfirmacionIndividual(BasePlan):

	def test_aprobar_sin_confirmar_una_destructiva_se_niega(self):
		"""EL test del paso. «Nunca en lote» es sobre la decisión, no sobre el armado.

		MUTACIÓN OBLIGATORIA: quitando la verificación de `faltan` en `_aprobar`, rojo.
		"""
		self._op("collaborator_revoke", target="alguien", sequence=10)
		with self.assertRaises(UserError) as ctx:
			self.plan._aprobar()
		self.assertIn("sin confirmar", str(ctx.exception))
		self.assertEqual(self.plan.state, "draft")

	def test_confirmar_UNA_de_DOS_tampoco_alcanza(self):
		"""Es el caso que una enumeración visual dejaría pasar."""
		una = self._op("collaborator_revoke", target="alguien", sequence=10)
		self._op("team_repo_revoke", target="equipo", sequence=20)
		with self.assertRaises(UserError) as ctx:
			self.plan._aprobar(confirmadas=una)
		self.assertIn("1 operación", str(ctx.exception))
		self.assertEqual(self.plan.state, "draft")

	def test_con_todas_confirmadas_aprueba(self):
		una = self._op("collaborator_revoke", target="alguien", sequence=10)
		otra = self._op("team_repo_revoke", target="equipo", sequence=20)
		self.plan._aprobar(confirmadas=una | otra)
		self.assertEqual(self.plan.state, "approved")

	def test_un_plan_sin_destructivas_no_pide_nada(self):
		"""La fricción es proporcional: aparece cuando hay algo que perder."""
		self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		self.plan._aprobar()
		self.assertEqual(self.plan.state, "approved")

	def test_la_guarda_no_vive_en_el_asistente(self):
		"""Un asistente es una pantalla, y una pantalla se saltea llamando al método."""
		import inspect

		from ..models import repo_write_plan

		fuente = inspect.getsource(repo_write_plan.RepoWritePlan._aprobar)
		self.assertIn("is_destructive", fuente)
		self.assertIn("faltan", fuente)

	def test_el_asistente_arma_una_linea_por_operacion(self):
		self._op("collaborator_revoke", target="alguien", sequence=10)
		self._op("branch_protection_apply", payload={"allow_force_pushes": False},
				 sequence=20)
		asistente = self.env["repo.plan.approve.wizard"].create({
			"plan_id": self.plan.id})
		self.assertEqual(len(asistente.line_ids), 2)
		self.assertEqual(asistente.destructive_count, 1)
		self.assertEqual(asistente.pending_count, 1)

		asistente.line_ids.filtered("is_destructive").confirmed = True
		asistente.invalidate_recordset()
		self.assertEqual(asistente.pending_count, 0)
		asistente.action_confirm()
		self.assertEqual(self.plan.state, "approved")
