# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El ciclo del apply: leer previo, ejecutar, verificar releyendo, registrar.

El transporte falso REGISTRA cada llamada. Es lo que permite probar la afirmación más
importante de todas —«se bloquea y no intenta escribir»— mirando que la escritura no
ocurrió, en vez de conformarse con que el estado final diga «bloqueada».
"""
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from .test_backend import _clave_rsa_de_prueba

UPGRADE = {"message": "Upgrade to GitHub Pro or make this repository public to "
					  "enable this feature."}
NO_PROTEGIDA = {"message": "Branch not protected"}
PROTECCION = {
	"required_pull_request_reviews": {"required_approving_review_count": 1},
	"enforce_admins": {"enabled": False},
	"url": "https://api.github.com/repos/x/y/branches/z/protection",
}


class Respuesta:
	def __init__(self, status_code, payload=None):
		self.status_code = status_code
		self._payload = payload
		self.headers = {}
		self.text = ""
		self.content = b"x" if payload is not None else b""

	def json(self):
		if self._payload is None:
			raise ValueError("sin cuerpo")
		return self._payload


class Transporte:
	"""Devuelve respuestas guionadas y anota TODA llamada que recibe."""

	def __init__(self, gets, escrituras=None):
		# `gets` es una lista: se van consumiendo en orden, para poder simular que el
		# estado cambia entre la lectura previa y la verificación.
		self.gets = list(gets)
		self.escrituras = escrituras or {}
		self.llamadas = []

	def post(self, url, json=None, headers=None, timeout=None):
		self.llamadas.append(("POST", url))
		if "access_tokens" in url:
			return Respuesta(201, {"token": "ghs_test"})
		return self.escrituras.get("POST", Respuesta(201, {}))

	def get(self, url, headers=None, timeout=None):
		self.llamadas.append(("GET", url))
		return self.gets.pop(0) if self.gets else Respuesta(404, NO_PROTEGIDA)

	def put(self, url, json=None, headers=None, timeout=None):
		self.llamadas.append(("PUT", url))
		return self.escrituras.get("PUT", Respuesta(200, PROTECCION))

	def patch(self, url, json=None, headers=None, timeout=None):
		self.llamadas.append(("PATCH", url))
		return self.escrituras.get("PATCH", Respuesta(200, {}))

	def delete(self, url, json=None, headers=None, timeout=None):
		self.llamadas.append(("DELETE", url))
		return self.escrituras.get("DELETE", Respuesta(204, None))

	def escrituras_hechas(self):
		return [c for c in self.llamadas
				if c[0] in ("PUT", "PATCH", "DELETE")
				or (c[0] == "POST" and "access_tokens" not in c[1])]


class TestApply(TransactionCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "Apply %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox",
		})
		self.backend.private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx",
		})

	def _plan(self, kind="branch_protection_apply", payload=None):
		plan = self.env["repo.write.plan"].create({
			"name": "Proteger", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": kind, "repository_id": self.repo.id,
			"target": "19.0",
			"payload_json": json.dumps(payload or {
				"required_pull_request_reviews": {
					"required_approving_review_count": 1}}),
		})
		plan.action_approve()
		return plan

	def _correr(self, plan, transporte):
		"""Inyecta el transporte en la única puerta y aplica."""
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(
			s, transport=transporte)
		try:
			plan.action_apply()
		finally:
			Backend.write_client = original

	# --- EL caso del orden: techo de plan ------------------------------------

	def test_privado_con_plan_gratuito_se_bloquea_y_NO_intenta_escribir(self):
		"""La lectura del estado previo devuelve 403 «Upgrade» y ahí se corta.

		Detectar el techo es distinto de chocarlo. Este test no se conforma con que el
		estado diga «bloqueada»: comprueba que no salió ninguna escritura.
		"""
		plan = self._plan()
		transporte = Transporte(gets=[Respuesta(403, UPGRADE)])
		self._correr(plan, transporte)

		op = plan.operation_ids
		self.assertEqual(op.state, "blocked")
		self.assertIn("Upgrade", op.error)
		self.assertEqual(
			transporte.escrituras_hechas(), [],
			"no puede haber salido ninguna escritura: el techo se detecta, no se choca")

		entrada = self.env["repo.audit.log"].search(
			[("event_type", "=", "write_blocked")], limit=1)
		self.assertTrue(entrada)
		self.assertEqual(entrada.repository_id, self.repo)

	def test_un_plan_bloqueado_no_queda_como_fallido(self):
		"""Un techo de plan no es un fracaso del sistema."""
		plan = self._plan()
		self._correr(plan, Transporte(gets=[Respuesta(403, UPGRADE)]))
		self.assertEqual(plan.state, "applied")

	# --- camino feliz ---------------------------------------------------------

	def test_lee_previo_ejecuta_y_verifica_releyendo(self):
		plan = self._plan()
		huella = plan.approval_fingerprint
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA),      # estado previo
			Respuesta(200, PROTECCION),        # verificación
		])
		self._correr(plan, transporte)

		op = plan.operation_ids
		self.assertEqual(op.state, "applied")
		self.assertEqual(plan.state, "applied")

		entrada = op.audit_log_id
		self.assertTrue(entrada)
		self.assertEqual(json.loads(entrada.previous_state_json), {"protected": False})
		payload = json.loads(entrada.payload_json)
		self.assertEqual(payload["plan_fingerprint"], huella,
						 "la bitácora tiene que decir qué se aprobó al aplicar esto")

	def test_la_url_no_entra_en_el_estado_previo(self):
		"""Las URLs autorreferenciales ensuciarían la comparación del rollback."""
		plan = self._plan()
		self._correr(plan, Transporte(gets=[
			Respuesta(200, PROTECCION), Respuesta(200, PROTECCION)]))
		previo = json.loads(plan.operation_ids.audit_log_id.previous_state_json)
		self.assertNotIn("url", previo["config"])

	# --- la escritura no cuenta como verdad -----------------------------------

	def test_si_la_relectura_no_confirma_la_operacion_falla(self):
		"""GitHub responde 200 al PUT pero la rama sigue sin protección."""
		plan = self._plan()
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA),      # previo
			Respuesta(404, NO_PROTEGIDA),      # verificación: no quedó
		])
		self._correr(plan, transporte)

		op = plan.operation_ids
		self.assertEqual(op.state, "failed")
		self.assertIn("relectura no lo confirma", op.error)
		self.assertEqual(plan.state, "failed")

	def test_si_falta_una_clave_pedida_la_verificacion_no_pasa(self):
		plan = self._plan()
		self._correr(plan, Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA),
			Respuesta(200, {"enforce_admins": {"enabled": False}}),
		]))
		self.assertEqual(plan.operation_ids.state, "failed")
		self.assertIn("required_pull_request_reviews", plan.operation_ids.error)

	# --- rollback --------------------------------------------------------------

	def test_el_rollback_restaura_el_estado_previo_exacto(self):
		plan = self._plan()
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA),      # previo: sin protección
			Respuesta(200, PROTECCION),        # verificación del apply
			Respuesta(404, NO_PROTEGIDA),      # relectura post-rollback
		])
		self._correr(plan, transporte)
		self.assertEqual(plan.operation_ids.state, "applied")

		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			plan.action_rollback()
		finally:
			Backend.write_client = original

		self.assertEqual(plan.operation_ids.state, "rolled_back")
		self.assertEqual(plan.state, "rolled_back")
		self.assertIn(("DELETE", "https://api.github.com/repos/org/sbx/branches/19.0/"
					   "protection"), transporte.llamadas)

	def test_el_rollback_falla_si_no_vuelve_al_estado_exacto(self):
		"""Byte a byte: si la relectura no coincide con lo guardado, se dice."""
		plan = self._plan()
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA),
			Respuesta(200, PROTECCION),
			Respuesta(200, PROTECCION),        # post-rollback: quedó protegida igual
		])
		self._correr(plan, transporte)

		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			with self.assertRaises(UserError) as ctx:
				plan.action_rollback()
		finally:
			Backend.write_client = original
		self.assertIn("no devolvió el estado exacto", str(ctx.exception))

	def test_no_se_revierte_sin_estado_previo_registrado(self):
		plan = self._plan()
		plan.operation_ids.write({"state": "applied"})
		with self.assertRaises(UserError) as ctx:
			plan.action_rollback()
		self.assertIn("no hay punto de retorno", str(ctx.exception).lower())

	# --- las guardas de arriba siguen mandando ---------------------------------

	def test_un_plan_que_cambio_despues_de_aprobar_no_se_aplica(self):
		plan = self._plan()
		plan.operation_ids.payload_json = json.dumps({"enforce_admins": True})
		with self.assertRaises(UserError) as ctx:
			plan.action_apply()
		self.assertIn("no tiene aprobación registrada", str(ctx.exception))

	def test_produccion_no_puede_aplicar(self):
		"""Las dos guardas son capas distintas y esto lo demuestra.

		`environment` NO entra en la huella del plan —la huella cubre `backend_id`, no los
		campos del backend—, así que pasar la conexión a producción deja el plan aprobado
		e intacto: la guarda de congelamiento lo deja pasar, correctamente. Lo que corta
		es la compuerta de entorno, que es la que tiene que cortar acá.
		"""
		plan = self._plan()
		self.backend.environment = "production"

		self.assertTrue(plan.is_frozen, "el plan sigue intacto: no lo tocó nadie")
		self.assertTrue(plan._verificar_congelado(), "la guarda de congelamiento pasa")

		with self.assertRaises(UserError) as ctx:
			plan.action_apply()
		self.assertIn("sólo lectura", str(ctx.exception))

	def test_un_tipo_no_implementado_falla_diciendolo(self):
		plan = self._plan(kind="ruleset_create", payload={"name": "x"})
		with self.assertRaises(UserError) as ctx:
			self._correr(plan, Transporte(gets=[]))
		self.assertIn("todavía no está implementado", str(ctx.exception))
