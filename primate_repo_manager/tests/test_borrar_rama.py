# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E3.2c · borrar una rama: destructiva, reversible, y con el nombre escrito a mano.

LA OPERACIÓN QUE OBLIGÓ A SEPARAR DOS COSAS QUE VENÍAN JUNTAS. Hasta acá, «exige escribir
el nombre» era lo mismo que «no tiene vuelta atrás». Borrar una rama tiene vuelta —se
recrea la ref en el mismo commit— pero esa vuelta depende de que GitHub todavía conserve
el objeto, y eso no lo controlamos. Con una vuelta que depende de un tercero, el tilde no
alcanza.
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import RespuestaFalsa as Respuesta
from .test_backend import _clave_rsa_de_prueba
from .test_write_apply import Transporte, _aprobar_plan, sin_cursor_aparte


class TestBorrarRama(TransactionCase):

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Borrar %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})
		clave = _clave_rsa_de_prueba()
		self.backend.private_key = clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx"})
		sin_cursor_aparte(self)

	def _plan(self, payload=None, rama="17.0_vieja"):
		plan = self.env["repo.write.plan"].create({
			"name": "Higiene", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "branch_delete",
			"repository_id": self.repo.id, "target": rama,
			"payload_json": json.dumps(payload if payload is not None else {
				"repository": "org/sbx", "branch": rama, "sha": "sha-viejo",
				"integrated_into": "17.0"})})
		return plan

	# --- lo que la operación ES ---

	def test_es_destructiva_y_REVERSIBLE(self):
		operacion = self._plan().operation_ids
		self.assertTrue(operacion.is_destructive)
		self.assertFalse(operacion.is_irreversible,
						 "tiene manejador de reversión: no es irreversible")

	def test_exige_escribir_el_nombre_AUNQUE_sea_reversible(self):
		"""La fricción no está atada a «no tiene vuelta» sino a «hay que mirar qué se
		está por tocar». Un tilde se marca sin leer."""
		self.assertTrue(self._plan().operation_ids.requires_typed_name)

	def test_la_frase_de_la_aprobacion_LLEVA_LA_SALVEDAD(self):
		"""Quien aprueba la lee. Sin ella, «reversible» se entiende como una garantía
		que este módulo no puede dar."""
		frase = self._plan().operation_ids.description
		self.assertIn("SE BORRA", frase)
		self.assertIn("mismo commit", frase)
		self.assertIn("mientras GitHub conserve el objeto", frase)
		self.assertIn("no lo controlamos", frase)

	def test_la_frase_dice_contra_qué_estaba_integrada(self):
		self.assertIn("integrada a 17.0", self._plan().operation_ids.description)

	def test_aprobar_EN_BLOQUE_lo_reversible_NO_la_confirma(self):
		"""El botón «aprobar todo lo reversible» existe para no pedir veinte tildes por
		veinte protecciones. Borrar una rama no entra ahí aunque sea reversible: si
		entrara, el tipeo no serviría de nada.
		"""
		plan = self._plan()
		asistente = self.env["repo.plan.approve.wizard"].create({"plan_id": plan.id})
		asistente.action_approve_reversibles()
		linea = asistente.line_ids.filtered(
			lambda l: l.operation_id.kind == "branch_delete")
		self.assertFalse(linea.confirmed,
						 "se confirmó sola una operación que exige escribir el nombre")

	# --- el ciclo de cuatro pasos ---

	def _con_transporte(self, transporte, hacer):
		"""Se reemplaza el método de la CLASE, como el resto de los tests del apply: el
		cliente se construye adentro y no hay otra costura por donde entrar."""
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			hacer()
		finally:
			Backend.write_client = original

	def _aplicar(self, transporte, plan):
		self._con_transporte(transporte, plan.action_apply)
		return plan

	def test_el_ciclo_lee_el_SHA_borra_y_verifica_releyendo(self):
		plan = _aprobar_plan(self._plan())
		transporte = Transporte(gets=[
			Respuesta(200, {"object": {"sha": "sha-de-ahora"}}),   # 1 · estado previo
			Respuesta(200, {"ahead_by": 0}),                       # sigue integrada
			Respuesta(404, {"message": "Not Found"}),              # 3 · verificación
		])

		self._aplicar(transporte, plan)

		self.assertEqual(plan.operation_ids.state, "applied")
		self.assertTrue(any(m == "DELETE" for m, _u in transporte.llamadas))
		# EL PUNTO DE RETORNO SALE DE LA BITÁCORA, que es el registro. Y es el SHA
		# LEÍDO en el paso 1, no el que traía el payload del hallazgo: entre que se armó
		# el plan y se aplica, alguien pudo haber empujado a esa rama.
		entrada = plan.operation_ids.audit_log_id
		self.assertTrue(entrada, "el apply no dejó entrada en la bitácora")
		previo = json.loads(entrada.previous_state_json or "{}")
		self.assertEqual(previo["anterior"]["sha"], "sha-de-ahora")

	def test_la_reversion_recrea_la_rama_EN_EL_MISMO_COMMIT(self):
		"""Recrearla en otro commit sería dejar el nombre correcto con el contenido
		equivocado, y nadie lo miraría dos veces."""
		plan = _aprobar_plan(self._plan())
		transporte = Transporte(gets=[
			Respuesta(200, {"object": {"sha": "sha-de-ahora"}}),
			Respuesta(200, {"ahead_by": 0}),
			Respuesta(404, {"message": "Not Found"}),
		])
		self._aplicar(transporte, plan)

		# El rollback lee DOS veces: qué hay ahora —la rama borrada, o sea 404— y, ya
		# recreada, la verificación byte a byte contra el punto de retorno.
		transporte.gets = [
			Respuesta(404, {"message": "Not Found"}),
			Respuesta(200, {"object": {"sha": "sha-de-ahora"}}),
		]
		self._con_transporte(transporte, plan.action_rollback)

		creaciones = [(u, cuerpo) for m, u, cuerpo in transporte.cuerpos
					  if m == "POST" and "/git/refs" in u]
		self.assertTrue(creaciones, "no se recreó la rama")
		self.assertEqual(creaciones[-1][1]["sha"], "sha-de-ahora")
		self.assertEqual(creaciones[-1][1]["ref"], "refs/heads/17.0_vieja")

	def test_sin_punto_de_retorno_NO_se_recrea_en_cualquier_commit(self):
		operacion = self._plan().operation_ids
		with self.assertRaises(UserError):
			operacion._recrear_rama(None, {"anterior": {}})

	# --- la guarda que vuelve a mirar ---

	def test_si_alguien_EMPUJO_a_la_rama_despues_de_la_auditoria_NO_se_borra(self):
		"""El hallazgo dijo «integrada» cuando corrió la auditoría; entre eso y el apply
		pueden pasar días. Sin esta relectura, el embudo terminaría haciendo lo que el
		motor se niega a proponer: borrar trabajo que no está en ningún otro lado.
		"""
		plan = _aprobar_plan(self._plan())
		transporte = Transporte(gets=[
			Respuesta(200, {"object": {"sha": "sha-de-ahora"}}),
			Respuesta(200, {"ahead_by": 3}),    # alguien empujó
		])

		self._aplicar(transporte, plan)

		self.assertEqual(plan.operation_ids.state, "failed")
		self.assertIn("ya no está integrada", plan.operation_ids.error)
		self.assertFalse(any(m == "DELETE" for m, _u in transporte.llamadas),
						 "se borró una rama con trabajo sin integrar")

	def test_la_guarda_falla_SU_operacion_y_no_el_plan_entero(self):
		"""Que alguien haya empujado a una rama no invalida las otras del lote.

		Las guardas viejas del apply —«este ruleset no lleva nuestro prefijo»— abortan el
		plan a propósito: dicen que el plan está MAL ARMADO. Ésta dice otra cosa: que el
		mundo cambió debajo de UNA operación. Abortar acá dejaría las anteriores
		aplicadas, ésta sin registro y las siguientes sin intentar ni explicar.
		"""
		plan = self.env["repo.write.plan"].create({
			"name": "Higiene de a dos", "backend_id": self.backend.id})
		Operacion = self.env["repo.write.operation"]
		for rama, sequence in (("17.0_empujada", 10), ("17.0_limpia", 20)):
			Operacion.create({
				"plan_id": plan.id, "kind": "branch_delete", "sequence": sequence,
				"repository_id": self.repo.id, "target": rama,
				"payload_json": json.dumps({
					"repository": "org/sbx", "branch": rama, "sha": "sha-viejo",
					"integrated_into": "17.0"})})
		_aprobar_plan(plan)
		transporte = Transporte(gets=[
			Respuesta(200, {"object": {"sha": "sha-1"}}),   # previo de la primera
			Respuesta(200, {"ahead_by": 4}),               # alguien empujó → se frena
			Respuesta(200, {"object": {"sha": "sha-2"}}),   # previo de la segunda
			Respuesta(200, {"ahead_by": 0}),               # sigue integrada
			Respuesta(404, {"message": "Not Found"}),      # verificación de la segunda
		])

		self._aplicar(transporte, plan)

		primera = plan.operation_ids.filtered(lambda o: o.target == "17.0_empujada")
		segunda = plan.operation_ids.filtered(lambda o: o.target == "17.0_limpia")
		self.assertEqual(primera.state, "failed")
		self.assertIn("ya no está integrada", primera.error)
		self.assertEqual(segunda.state, "applied",
						 "la guarda de una operación se llevó puesta a la otra")
