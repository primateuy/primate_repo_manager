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


class TestRemediarDesdeUnHallazgo(BasePlan):
	"""A4.1: el botón arma la operación y termina. Nada escribe en GitHub."""

	def _hallazgo(self, tipo="permission_exceeded", payload=None, sujeto="alguien"):
		"""Pasa por `build`, que es quien deriva la acción de remediación del tipo.

		Crear el hallazgo con `create()` directo se saltea esa derivación y deja
		`remediation_action` vacío: el test pasaría a probar un hallazgo que la auditoría
		nunca produce.
		"""
		corrida = self.env["repo.audit.run"].create({
			"name": "Corrida", "backend_id": self.backend.id, "state": "done"})
		return self.env["repo.audit.finding"].build(
			corrida, tipo, "algo", repository=self.repo, severity="high",
			subject=sujeto, remediation_payload=payload or {"permission": "pull"})

	# --- la doctrina --------------------------------------------------------

	def test_remediar_NO_escribe_en_github(self):
		"""La tentación de que «remediar» remedie de una es la que saltearía las tres
		guardas de F2.

		MUTACIÓN: hacer que `action_remediate` llame a `write_client`, y este test avisa.
		"""
		import inspect

		from ..models import repo_audit_finding

		fuente = inspect.getsource(
			repo_audit_finding.RepoAuditFinding.action_remediate)
		for prohibido in ("write_client", "action_apply", "_aplicar", "post(", "put("):
			self.assertNotIn(prohibido, fuente)

	def test_remediar_deja_el_plan_en_borrador(self):
		hallazgo = self._hallazgo()
		hallazgo.action_remediate()
		operacion = hallazgo.planned_operation_id
		self.assertTrue(operacion)
		self.assertEqual(operacion.plan_id.state, "draft")
		self.assertEqual(operacion.state, "pending")
		self.assertEqual(operacion.kind, "collaborator_revoke")
		self.assertEqual(operacion.finding_id, hallazgo)

	# --- no duplicar --------------------------------------------------------

	def test_remediar_dos_veces_no_crea_dos_operaciones(self):
		"""El doble clic, y las dos personas mirando la misma lista."""
		hallazgo = self._hallazgo()
		hallazgo.action_remediate()
		primera = hallazgo.planned_operation_id
		accion = hallazgo.action_remediate()
		self.assertEqual(len(hallazgo.operation_ids), 1)
		self.assertEqual(hallazgo.planned_operation_id, primera)
		self.assertIn("ya está en el plan", accion["context"]["prm_aviso"])
		self.assertEqual(accion["res_id"], primera.plan_id.id,
						 "y lleva ahí en vez de dejar a alguien buscándolo")

	def test_la_base_lo_impide_aunque_alguien_saltee_la_comprobacion(self):
		"""Entre comprobar y crear hay una ventana. El índice único la cierra."""
		from psycopg2 import IntegrityError

		from odoo.tools.misc import mute_logger

		hallazgo = self._hallazgo()
		hallazgo.action_remediate()
		valores = hallazgo._valores_de_operacion(hallazgo.planned_plan_id)
		with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
			self.env["repo.write.operation"].create(valores)
			self.env.flush_all()

	def test_una_operacion_ya_aplicada_no_bloquea_una_nueva(self):
		"""Si el hallazgo volvió a aparecer, tiene que poder planificarse otra vez."""
		hallazgo = self._hallazgo()
		hallazgo.action_remediate()
		hallazgo.planned_operation_id.state = "applied"
		# El flush es necesario y dice algo: el índice es de la BASE, así que mira lo que
		# está escrito, no lo que el ORM tiene pendiente. En la vida real esto son dos
		# transacciones distintas —se aplica un plan, y más tarde una auditoría nueva
		# vuelve a encontrar el problema— y el flush es lo que reproduce esa separación.
		self.env.flush_all()
		hallazgo.invalidate_recordset()
		self.assertFalse(hallazgo.planned_operation_id)
		hallazgo.action_remediate()
		self.assertEqual(len(hallazgo.operation_ids), 2)

	# --- acumular -----------------------------------------------------------

	def test_dos_hallazgos_van_al_MISMO_borrador(self):
		"""Veinte planes de una operación son veinte aprobaciones."""
		uno = self._hallazgo(sujeto="alguien")
		otro = self._hallazgo(sujeto="otro")
		uno.action_remediate()
		otro.action_remediate()
		self.assertEqual(uno.planned_plan_id, otro.planned_plan_id)
		self.assertEqual(len(uno.planned_plan_id.operation_ids), 2)

	def test_un_plan_ya_aprobado_no_recibe_operaciones_nuevas(self):
		"""Acumular en un plan aprobado le rompería la aprobación por la espalda."""
		uno = self._hallazgo(sujeto="alguien")
		uno.action_remediate()
		plan = uno.planned_plan_id
		plan._aprobar(confirmadas=plan.operation_ids.filtered("is_destructive"))
		otro = self._hallazgo(sujeto="otro")
		otro.action_remediate()
		self.assertNotEqual(otro.planned_plan_id, plan)

	# --- lo que no se puede planificar --------------------------------------

	def test_lo_que_no_se_remedia_con_un_plan_lo_dice(self):
		hallazgo = self._hallazgo("classification_missing")
		self.assertFalse(hallazgo.can_be_planned)
		self.assertIn("Odoo", hallazgo.why_not_planned)
		with self.assertRaises(UserError) as ctx:
			hallazgo.action_remediate()
		self.assertIn("Clasificación", str(ctx.exception))

	def test_toda_accion_de_remediacion_tiene_camino_o_explicacion(self):
		"""Un botón ausente sin explicación se lee como un olvido del producto."""
		from ..models.repo_audit_finding import (
			PLANIFICABLES, POR_QUE_NO_PLANIFICABLE, REMEDIATION_ACTIONS)

		for accion, _etiqueta in REMEDIATION_ACTIONS:
			self.assertTrue(
				accion in PLANIFICABLES or accion in POR_QUE_NO_PLANIFICABLE,
				"«%s» no dice ni cómo se planifica ni dónde se resuelve" % accion)

	# --- el lote ------------------------------------------------------------

	def test_el_lote_no_se_cae_por_uno_que_no_aplica(self):
		"""Negarse entero porque uno de veinte no aplicaba obliga a ir de a uno, que es
		justo lo que este botón evita."""
		bueno = self._hallazgo(sujeto="alguien")
		otro_bueno = self._hallazgo(sujeto="otro")
		malo = self._hallazgo("classification_missing")
		ya = self._hallazgo(sujeto="tercero")
		ya.action_remediate()

		(bueno | otro_bueno | malo | ya).action_remediate_many()
		self.assertTrue(bueno.planned_operation_id)
		self.assertTrue(otro_bueno.planned_operation_id)
		self.assertFalse(malo.planned_operation_id)
		self.assertEqual(len(ya.operation_ids), 1, "el que ya estaba no se duplicó")

	def test_un_lote_donde_nada_aplica_lo_dice_en_vez_de_no_hacer_nada(self):
		malo = self._hallazgo("classification_missing")
		with self.assertRaises(UserError) as ctx:
			malo.action_remediate_many()
		self.assertIn("no se remedian", str(ctx.exception))
