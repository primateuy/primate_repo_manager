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
		"""«Quitar el acceso» no alcanza: hay que decir qué deja de poder hacer quién."""
		op = self._op("team_repo_revoke", target="equipo-x")
		self.assertTrue(op.is_destructive)
		self.assertIn("SE LE QUITA", op.description)
		self.assertIn("todos sus integrantes", op.description)

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


class TestArmarOperacionSinJSON(BasePlan):
	"""A4.3: el otro camino, el que no nace de un hallazgo."""

	def _asistente(self, **valores):
		rama = self.env["repo.branch"].search([
			("repository_id", "=", self.repo.id), ("name", "=", "17.0")], limit=1)
		if not rama:
			rama = self.env["repo.branch"].create({
				"repository_id": self.repo.id, "name": "17.0", "role": "base"})
		base = {"plan_id": self.plan.id, "kind": "branch_protection_apply",
				"repository_id": self.repo.id, "branch_id": rama.id}
		base.update(valores)
		return self.env["repo.operation.builder"].create(base)

	def test_las_casillas_se_vuelven_payload(self):
		a = self._asistente(require_pr=True, required_approvals=2,
							block_force_push=True, block_deletion=True)
		a.action_add()
		op = self.plan.operation_ids[-1]
		datos = json.loads(op.payload_json)
		self.assertEqual(
			datos["required_pull_request_reviews"]["required_approving_review_count"], 2)
		self.assertFalse(datos["allow_force_pushes"])
		self.assertFalse(datos["allow_deletions"])

	def test_la_vista_previa_usa_LA_MISMA_frase_que_el_plan(self):
		"""Dos redacciones parecidas son peores que una: la que se aprueba es la del plan.

		MUTACIÓN: si la vista previa se armara con una frase propia, este test avisa.
		"""
		a = self._asistente(required_approvals=3)
		previa = a.preview
		a.action_add()
		self.assertEqual(previa, self.plan.operation_ids[-1].description)

	def test_no_deja_a_medias_lo_que_falta(self):
		a = self._asistente(branch_id=False)
		with self.assertRaises(UserError):
			a.action_add()

	def test_la_rama_SE_ELIGE_y_no_se_escribe(self):
		"""Con Staging/staging/_staging conviviendo, un typo arma una operación contra una
		rama inexistente que se lee perfecta y muere al aplicar. Toda la ceremonia de
		aprobación funcionando sobre un dato que nunca existió.

		MUTACIÓN: volver `branch` a un Char editable y este test se pone rojo.
		"""
		campos = self.env["repo.operation.builder"]._fields
		self.assertEqual(campos["branch_id"].type, "many2one")
		self.assertEqual(campos["branch_id"].comodel_name, "repo.branch")
		self.assertFalse(campos["branch"].store,
						 "el nombre se deriva de la rama elegida, no se escribe")

	def test_la_rama_ofrecida_es_la_DEL_repositorio_elegido(self):
		otro = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "name": "otro",
			"full_name": "%s/otro" % self.backend.owner_login,
			"github_id": uuid.uuid4().hex[:8]})
		ajena = self.env["repo.branch"].create({
			"repository_id": otro.id, "name": "17.0", "role": "base"})
		a = self._asistente(branch_id=ajena.id)
		with self.assertRaises(UserError) as ctx:
			a.action_add()
		self.assertIn("no de", str(ctx.exception))

	def test_cambiar_de_repositorio_limpia_la_rama(self):
		"""Dejarla pegada sería el mismo error con otra cara: una rama que existe, pero en
		otro repositorio."""
		a = self._asistente()
		self.assertTrue(a.branch_id)
		otro = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "name": "otro2",
			"full_name": "%s/otro2" % self.backend.owner_login,
			"github_id": uuid.uuid4().hex[:8]})
		a.repository_id = otro
		a._onchange_repository()
		self.assertFalse(a.branch_id)

	def test_el_team_sigue_siendo_texto_Y_SE_DICE_POR_QUE(self):
		"""No es un descuido: el espejo no releva teams porque la cuenta no es una
		organización. Un desplegable vacío sería peor que un campo de texto."""
		ayuda = self.env["repo.operation.builder"]._fields["team_slug"].help or ""
		self.assertIn("no es una organización", ayuda)
		self.assertNotIn("repo.team", str(self.env.registry.models.keys()))

	def test_un_plan_aprobado_no_recibe_operaciones(self):
		self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		self.plan._aprobar()
		a = self._asistente()
		with self.assertRaises(UserError) as ctx:
			a.action_add()
		self.assertIn("aprobación", str(ctx.exception))

	def test_los_rulesets_NO_estan_en_el_asistente(self):
		"""Un ruleset se define por las reglas de una plantilla, no por un formulario
		suelto: dos lugares donde se decide lo mismo divergen. Es B1."""
		from ..wizards.repo_operation_builder import TIPOS_CON_FORMULARIO

		self.assertNotIn("ruleset_create", TIPOS_CON_FORMULARIO)
		self.assertNotIn("ruleset_delete", TIPOS_CON_FORMULARIO)


class TestAvanceDelPlan(BasePlan):
	"""A4.5: el plan aplicándose usa la misma pieza de pantalla que la auditoría."""

	def test_el_avance_se_deriva_de_las_operaciones(self):
		"""Un contador que alguien incrementa es una fila compartida que se pisa —A10— y
		además puede quedar mintiendo si algo se cae. Contar no puede desfasarse."""
		una = self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		otra = self._op("branch_protection_apply", sequence=20,
						payload={"allow_deletions": False})
		self.assertEqual(self.plan.progress, 0)
		una.state = "applied"
		self.plan.invalidate_recordset()
		self.assertEqual(self.plan.applied_count, 1)
		self.assertEqual(self.plan.progress, 50)
		otra.state = "failed"
		self.plan.invalidate_recordset()
		self.assertEqual(self.plan.failed_count, 1)
		self.assertEqual(self.plan.progress, 100)

	def test_lo_bloqueado_cuenta_como_hecho_y_no_como_error(self):
		"""Un techo de plan de GitHub es un límite conocido y reportado, no una falla."""
		op = self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		op.state = "blocked"
		self.plan.invalidate_recordset()
		self.assertEqual(self.plan.applied_count, 1)
		self.assertEqual(self.plan.failed_count, 0)

	def test_el_aviso_habla_el_idioma_del_componente(self):
		"""Las claves son las del componente y no las del modelo, para que la pieza de
		pantalla no tenga que saber quién la alimenta."""
		self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		avisos = []
		Plan = self.env["repo.write.plan"].__class__
		envio = Plan._bus_send
		Plan._bus_send = lambda s, t, m, **kw: avisos.append(m)
		self.addCleanup(lambda: setattr(Plan, "_bus_send", envio))
		self.plan._emitir_avance()
		self.assertEqual(
			set(avisos[0]), {"id", "state", "total", "done", "error", "actual",
							 "findings", "criticos", "altos"})

	def test_el_bus_acepta_el_canal_del_plan(self):
		"""Sin esto el componente se suscribe a un canal que el servidor descarta."""
		canales = self.env["ir.websocket"]._traducir_corridas(
			["repo.write.plan_%s" % self.plan.id])
		self.assertIn(self.plan, canales)

	def test_el_bus_NO_acepta_cualquier_modelo(self):
		"""La lista blanca es lo que impide que el navegador nombre un modelo cualquiera
		y el servidor se lo resuelva."""
		canales = self.env["ir.websocket"]._traducir_corridas(["res.users_1"])
		self.assertEqual(canales, ["res.users_1"],
						 "un modelo fuera de la lista pasa como texto y no se resuelve")


class TestReversibleVsIrreversible(BasePlan):
	"""El patrón del prototipo: lo que se puede deshacer y lo que no se leen distinto."""

	def test_irreversible_SE_DERIVA_de_si_el_manejador_sabe_revertir(self):
		"""No es una lista que alguien mantiene: se le pregunta al manejador. Así, el día
		que se agregue «borrar una rama», la pantalla se entera sola.

		MUTACIÓN: cablear `is_irreversible = False` y este test se pone rojo.
		"""
		import inspect

		from ..models import repo_write_plan

		fuente = inspect.getsource(
			repo_write_plan.RepoWriteOperation._compute_description)
		self.assertIn("_manejadores", fuente)
		self.assertIn("revertir", fuente)

	def test_ningun_tipo_IMPLEMENTADO_es_irreversible_todavia(self):
		"""El patrón de lo irreversible existe, pero todavía no hay tipo que lo dispare.
		El primero va a ser borrar una rama, en el bloque de higiene."""
		from ..models.repo_write_plan import OPERATION_KINDS

		for kind, _etiqueta in OPERATION_KINDS:
			op = self._op(kind, target="x")
			if not op.is_supported:
				continue
			self.assertFalse(
				op.is_irreversible,
				"«%s» quedó marcada como irreversible; si es a propósito, este test "
				"tiene que actualizarse a propósito también" % kind)

	def test_los_tipos_SIN_manejador_se_dicen_como_lo_que_son(self):
		"""«No implementado» NO es «irreversible». Confundirlos mentiría en la dirección
		tranquilizadora: diría «esto no tiene vuelta atrás» cuando la verdad es «esto ni
		siquiera se puede hacer»."""
		op = self._op("branch_protection_remove", target="17.0")
		self.assertFalse(op.is_supported)
		self.assertFalse(op.is_irreversible)
		self.assertIn("NO ESTÁ IMPLEMENTADO", op.description)

	def test_un_plan_con_un_tipo_sin_implementar_NO_se_aprueba(self):
		"""Se corta al aprobar y no al aplicar: fallar a mitad del apply dejaría parte del
		plan escrito en GitHub, que es el estado que todo el embudo existe para evitar."""
		self._op("branch_protection_remove", target="17.0")
		with self.assertRaises(UserError) as ctx:
			self.plan._aprobar()
		self.assertIn("no está implementado", str(ctx.exception))

	def test_el_asistente_no_ofrece_tipos_que_no_se_pueden_aplicar(self):
		"""Un formulario que arma algo que después no se puede aplicar es peor que no
		tenerlo: el plan se arma, se lee bien y muere al aplicar."""
		from ..wizards.repo_operation_builder import TIPOS_CON_FORMULARIO

		manejados = set(self.env["repo.write.operation"]._manejadores())
		for kind in TIPOS_CON_FORMULARIO:
			self.assertIn(kind, manejados,
						  "el asistente ofrece «%s», que no tiene manejador" % kind)

	def test_una_operacion_sin_reversion_pide_escribir_el_nombre(self):
		"""Se simula un tipo sin `revertir` en su manejador, que es el caso que viene."""
		op = self._op("collaborator_revoke", target="alguien")
		Operacion = type(op)
		original = Operacion._manejadores
		Operacion._manejadores = lambda s: {
			"collaborator_revoke": {"leer": "x", "ejecutar": "y", "verificar": "z"}}
		self.addCleanup(lambda: setattr(Operacion, "_manejadores", original))
		op.invalidate_recordset()
		op._compute_description()
		self.assertTrue(op.is_irreversible)

		asistente = self.env["repo.plan.approve.wizard"].create({
			"plan_id": self.plan.id})
		linea = asistente.line_ids[0]
		self.assertTrue(linea.is_irreversible)
		self.assertEqual(linea.target_name, "alguien")

		# Un nombre equivocado NO confirma.
		linea.typed_name = "otro"
		linea._onchange_typed_name()
		self.assertFalse(linea.confirmed)
		# El exacto, sí.
		linea.typed_name = "alguien"
		linea._onchange_typed_name()
		self.assertTrue(linea.confirmed)

	def test_aprobar_las_reversibles_en_bloque_NO_toca_las_irreversibles(self):
		"""«Nunca en lote» es sobre lo que puede sacarle el acceso a alguien. Pedir veinte
		tildes para veinte protecciones que se deshacen con un click no agrega criterio:
		agrega fatiga, y la fatiga es lo que hace que después se tilde sin leer."""
		self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		irreversible = self._op("collaborator_revoke", target="alguien", sequence=20)
		Operacion = type(irreversible)
		original = Operacion._manejadores
		def sin_revertir(s):
			m = dict(original(s))
			m["collaborator_revoke"] = {
				k: v for k, v in m["collaborator_revoke"].items() if k != "revertir"}
			return m
		Operacion._manejadores = sin_revertir
		self.addCleanup(lambda: setattr(Operacion, "_manejadores", original))
		self.plan.operation_ids.invalidate_recordset()
		self.plan.operation_ids._compute_description()

		asistente = self.env["repo.plan.approve.wizard"].create({
			"plan_id": self.plan.id})
		asistente.action_approve_reversibles()
		asistente.invalidate_recordset()
		irrev = asistente.line_ids.filtered("is_irreversible")
		self.assertTrue(irrev)
		self.assertFalse(irrev.confirmed,
						 "el bloque no puede haber confirmado lo que no tiene vuelta atrás")

	def test_las_dos_barras_cuentan_por_separado(self):
		"""Mezclarlas diría «vas por el 80%» cuando lo que falta es justo lo irreversible."""
		self._op("branch_protection_apply", payload={"allow_force_pushes": False})
		self._op("branch_protection_apply", sequence=20,
				 payload={"allow_deletions": False})
		asistente = self.env["repo.plan.approve.wizard"].create({
			"plan_id": self.plan.id})
		self.assertEqual(asistente.reversible_count, 2)
		self.assertEqual(asistente.irreversible_count, 0)
