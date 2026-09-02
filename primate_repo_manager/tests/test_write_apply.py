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
# Los tres datos de un grant, con la forma real que devolvió el sandbox.
PERM_MAINTAIN = {"role_name": "maintain", "permission": "write"}
PERM_ADMIN = {"role_name": "admin", "permission": "admin"}
DIRECTO_MAINTAIN = [{"login": "primateuy", "role_name": "maintain"}]
DIRECTO_ADMIN = [{"login": "primateuy", "role_name": "admin"}]
SIN_DIRECTOS = []
TEAM_MAINTAIN = [{"slug": "desarrollo", "permission": "maintain"}]
# Un ruleset preexistente que NO es nuestro y que ninguna reversión puede tocar.
AJENO = {"id": 111, "name": "ajeno-no-tocar", "enforcement": "active"}
NUESTRO = {"id": 999, "name": "sonda", "enforcement": "active"}
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
		# Los cuerpos, aparte: verificar que «hubo un PUT» no dice CON QUÉ, y ahí se
		# esconde toda una clase de bug —restaurar algo distinto de lo que había—.
		self.cuerpos = []

	def post(self, url, json=None, headers=None, timeout=None):
		self.llamadas.append(("POST", url))
		if "access_tokens" not in url:
			self.cuerpos.append(("POST", url, json))
		if "access_tokens" in url:
			return Respuesta(201, {"token": "ghs_test"})
		return self.escrituras.get("POST", Respuesta(201, {}))

	def get(self, url, headers=None, timeout=None):
		self.llamadas.append(("GET", url))
		return self.gets.pop(0) if self.gets else Respuesta(404, NO_PROTEGIDA)

	def put(self, url, json=None, headers=None, timeout=None):
		self.llamadas.append(("PUT", url))
		self.cuerpos.append(("PUT", url, json))
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
		self._sin_cursor_aparte()

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

	def _sin_cursor_aparte(self):
		"""En un test nada está confirmado, así que una conexión nueva no vería los
		registros. Se reemplaza por la actual: con eso se prueba QUÉ se guarda y que el
		rollback lo use, NO la durabilidad — eso va contra el sandbox, en dos procesos."""
		import contextlib
		def falso(self):
			return contextlib.nullcontext(self.env.cr)

		# Sólo la operación: el plan ya no usa conexión aparte —marcar su estado desde
		# otra conexión colisionaba con la transacción principal— y no tiene el método.
		clase = self.env["repo.write.operation"].__class__
		original = clase._cursor_durable
		clase._cursor_durable = falso
		self.addCleanup(lambda: setattr(clase, "_cursor_durable", original))

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
			Respuesta(404, NO_PROTEGIDA),      # previo del apply: sin protección
			Respuesta(200, PROTECCION),        # verificación del apply
			Respuesta(200, PROTECCION),        # antes de revertir: quedó protegida
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
			Respuesta(200, PROTECCION),        # antes de revertir
			Respuesta(200, PROTECCION),        # post-rollback: NO se fue la protección
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
		plan.write({"state": "applied"})   # pasa la guarda de estado, no la del retorno
		with self.assertRaises(UserError) as ctx:
			plan.action_rollback()
		self.assertIn("no hay punto de retorno", str(ctx.exception).lower())

	# --- el rollback pasa por el mismo embudo, no por una puerta de servicio ---

	def _aplicado(self, transporte):
		plan = self._plan()
		self._correr(plan, transporte)
		self.assertEqual(plan.operation_ids.state, "applied")
		return plan

	def _revertir(self, plan, transporte):
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			return plan.action_rollback()
		finally:
			Backend.write_client = original

	def test_el_rollback_exige_la_huella_igual_que_el_apply(self):
		"""Revertir es escribir. Si el plan cambió desde que se aprobó, tampoco revierte.

		Sin esto, «deshacer» sería una puerta de servicio a las mismas escrituras: se
		aprueba un plan, se aplica, se le cambia el payload y el rollback lo usaría como
		instrucción sin que nadie lo haya aprobado así.
		"""
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA), Respuesta(200, PROTECCION),
			Respuesta(200, PROTECCION), Respuesta(404, NO_PROTEGIDA)])
		plan = self._aplicado(transporte)

		plan.operation_ids.payload_json = json.dumps({"enforce_admins": True})

		# Un plan YA APLICADO no vuelve a borrador —el registro de qué se aprobó y se
		# aplicó tiene que quedar en pie— así que la aprobación sigue ahí. La que lo caza
		# es la HUELLA, que se recalcula y ya no coincide. Es justamente el caso donde un
		# flag no alcanzaría.
		self.assertEqual(plan.state, "applied")
		self.assertTrue(plan.approval_fingerprint)
		self.assertFalse(plan.is_frozen)

		with self.assertRaises(UserError) as ctx:
			self._revertir(plan, transporte)
		self.assertIn("cambió después de que lo aprobaran", str(ctx.exception))

	def test_el_rollback_no_corre_sobre_un_plan_en_borrador(self):
		plan = self._plan()
		plan.action_back_to_draft()
		with self.assertRaises(UserError):
			plan.action_rollback()

	def test_el_rollback_registra_su_propio_estado_previo(self):
		"""El «antes» de la reversión es lo que había, no el punto de retorno.

		Confundirlos dejaba en la bitácora una entrada cuyo «antes» era en realidad su
		«después», y con eso no se puede reconstruir la secuencia.
		"""
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA),      # previo del apply
			Respuesta(200, PROTECCION),        # verificación del apply
			Respuesta(200, PROTECCION),        # antes de revertir: está protegida
			Respuesta(404, NO_PROTEGIDA),      # post-rollback
		])
		plan = self._aplicado(transporte)
		self._revertir(plan, transporte)

		entrada = self.env["repo.audit.log"].search(
			[("event_type", "=", "write_rolled_back")], order="id desc", limit=1)
		antes = json.loads(entrada.previous_state_json)
		self.assertTrue(antes["protected"],
						"el estado previo de la reversión es la rama YA protegida")
		payload = json.loads(entrada.payload_json)
		self.assertEqual(payload["restaurado_a"], {"protected": False})
		self.assertEqual(payload["plan_fingerprint"], plan.approval_fingerprint)

	def test_revertir_una_sola_operacion_usa_el_mismo_embudo(self):
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA), Respuesta(200, PROTECCION),
			Respuesta(200, PROTECCION), Respuesta(404, NO_PROTEGIDA)])
		plan = self._aplicado(transporte)

		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(s, transport=transporte)
		try:
			plan.operation_ids.action_rollback_operation()
		finally:
			Backend.write_client = original

		self.assertEqual(plan.operation_ids.state, "rolled_back")
		self.assertEqual(plan.state, "rolled_back")

	def test_revertir_una_operacion_tambien_exige_la_huella(self):
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA), Respuesta(200, PROTECCION)])
		plan = self._aplicado(transporte)
		plan.operation_ids.payload_json = json.dumps({"enforce_admins": True})
		with self.assertRaises(UserError):
			plan.operation_ids.action_rollback_operation()

	def test_produccion_tampoco_puede_revertir(self):
		transporte = Transporte(gets=[
			Respuesta(404, NO_PROTEGIDA), Respuesta(200, PROTECCION)])
		plan = self._aplicado(transporte)
		self.backend.environment = "production"
		with self.assertRaises(UserError) as ctx:
			plan.action_rollback()
		self.assertIn("sólo lectura", str(ctx.exception))

	# --- grants directos: el estado previo son TRES datos ---------------------

	def _plan_grant(self, permiso="admin"):
		plan = self.env["repo.write.plan"].create({
			"name": "Grant", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "collaborator_grant",
			"repository_id": self.repo.id, "target": "primateuy",
			"payload_json": json.dumps({"permission": permiso}),
		})
		plan.action_approve()
		return plan

	def test_revertir_un_grant_donde_hay_team_vuelve_AL_TEAM_no_a_nada(self):
		"""El caso que rompe un rollback ingenuo.

		En un repositorio donde la persona ya tenía `maintain` POR TEAM y ningún grant
		directo, dar `admin` directo y después revertirlo NO la deja sin acceso: la deja
		con el maintain del team. Un estado previo que guardara sólo el permiso efectivo
		—o que asumiera «volver a nada»— daría por fallida una reversión correcta, o
		dejaría a alguien con más acceso del que tenía.
		"""
		transporte = Transporte(gets=[
			# estado previo: efectivo maintain, SIN directo, team maintain
			Respuesta(200, PERM_MAINTAIN), Respuesta(200, SIN_DIRECTOS),
			Respuesta(200, TEAM_MAINTAIN),
			# verificación del apply: quedó admin directo
			Respuesta(200, PERM_ADMIN), Respuesta(200, DIRECTO_ADMIN),
			Respuesta(200, TEAM_MAINTAIN),
			# antes de revertir
			Respuesta(200, PERM_ADMIN), Respuesta(200, DIRECTO_ADMIN),
			Respuesta(200, TEAM_MAINTAIN),
			# post-rollback: vuelve al maintain DEL TEAM, sin directo
			Respuesta(200, PERM_MAINTAIN), Respuesta(200, SIN_DIRECTOS),
			Respuesta(200, TEAM_MAINTAIN),
		])
		plan = self._plan_grant()
		self._correr(plan, transporte)
		op = plan.operation_ids
		self.assertEqual(op.state, "applied")

		previo = json.loads(op.audit_log_id.previous_state_json)
		self.assertEqual(previo["efectivo"], "maintain")
		self.assertIsNone(previo["directo"], "no había grant directo")
		self.assertEqual(previo["teams"],
						 [{"slug": "desarrollo", "permission": "maintain"}],
						 "normalizado al vocabulario de escritura, como todo el previo")

		self._revertir(plan, transporte)
		self.assertEqual(op.state, "rolled_back")
		# Revertir un grant que no existía se hace BORRANDO el directo, no poniendo otro.
		self.assertIn(
			("DELETE", "https://api.github.com/repos/org/sbx/collaborators/primateuy"),
			transporte.llamadas)

	def test_revertir_un_grant_que_ya_existia_lo_restaura_no_lo_borra(self):
		transporte = Transporte(gets=[
			Respuesta(200, PERM_MAINTAIN), Respuesta(200, DIRECTO_MAINTAIN),
			Respuesta(200, TEAM_MAINTAIN),
			Respuesta(200, PERM_ADMIN), Respuesta(200, DIRECTO_ADMIN),
			Respuesta(200, TEAM_MAINTAIN),
			Respuesta(200, PERM_ADMIN), Respuesta(200, DIRECTO_ADMIN),
			Respuesta(200, TEAM_MAINTAIN),
			Respuesta(200, PERM_MAINTAIN), Respuesta(200, DIRECTO_MAINTAIN),
			Respuesta(200, TEAM_MAINTAIN),
		])
		plan = self._plan_grant()
		self._correr(plan, transporte)
		previo = json.loads(plan.operation_ids.audit_log_id.previous_state_json)
		self.assertEqual(previo["directo"], "maintain")

		self._revertir(plan, transporte)
		self.assertEqual(plan.operation_ids.state, "rolled_back")
		self.assertNotIn(
			("DELETE", "https://api.github.com/repos/org/sbx/collaborators/primateuy"),
			transporte.llamadas,
			"había un grant directo antes: se restaura, no se borra")
		puts = [c for c in transporte.cuerpos
				if c[0] == "PUT" and c[1].endswith("/collaborators/primateuy")]
		self.assertEqual(puts[-1][2], {"permission": "maintain"},
						 "y se restaura con el permiso que había, no con otro")

	def test_el_grant_se_verifica_por_el_permiso_DIRECTO(self):
		"""Si se verificara por el efectivo, un team que ya diera admin haría pasar un
		grant que no se escribió."""
		transporte = Transporte(gets=[
			Respuesta(200, PERM_MAINTAIN), Respuesta(200, SIN_DIRECTOS),
			Respuesta(200, TEAM_MAINTAIN),
			# el efectivo dice admin (por team) pero NO hay directo
			Respuesta(200, PERM_ADMIN), Respuesta(200, SIN_DIRECTOS),
			Respuesta(200, TEAM_MAINTAIN),
		])
		plan = self._plan_grant()
		self._correr(plan, transporte)
		self.assertEqual(plan.operation_ids.state, "failed")
		self.assertIn("permiso directo quedó en ninguno", plan.operation_ids.error)

	def test_un_grant_sin_permiso_en_el_payload_falla_diciendolo(self):
		plan = self.env["repo.write.plan"].create({
			"name": "Grant sin permiso", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "collaborator_grant",
			"repository_id": self.repo.id, "target": "primateuy",
			"payload_json": json.dumps({}),
		})
		plan.action_approve()
		with self.assertRaises(UserError) as ctx:
			self._correr(plan, Transporte(gets=[
				Respuesta(200, PERM_MAINTAIN), Respuesta(200, SIN_DIRECTOS),
				Respuesta(200, TEAM_MAINTAIN)]))
		self.assertIn("falta `permission`", str(ctx.exception))

	# --- grants por team: el espejo del mismo problema ------------------------

	def _plan_team(self, kind="team_repo_grant", permiso="admin"):
		plan = self.env["repo.write.plan"].create({
			"name": "Team grant", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": kind,
			"repository_id": self.repo.id, "target": "desarrollo",
			"payload_json": json.dumps({"permission": permiso}),
		})
		plan.action_approve()
		return plan

	def _gets_team(self, secuencia):
		"""Cada lectura de estado de team son 2 GETs: teams del repo y directos."""
		gets = []
		for teams, directos in secuencia:
			gets += [Respuesta(200, teams), Respuesta(200, directos)]
		return Transporte(gets=gets)

	def test_revertir_un_team_grant_no_toca_los_directos(self):
		"""Quitarle acceso a un team no se lo quita a quien lo tiene directo.

		Los directos van en el estado previo justamente para que la comparación byte a
		byte lo demuestre: si la reversión los rozara, no coincidirían.
		"""
		TEAM_PUSH = [{"slug": "desarrollo", "permission": "push"}]
		TEAM_ADMIN = [{"slug": "desarrollo", "permission": "admin"}]
		DIRECTOS = [{"login": "primateuy", "role_name": "maintain"}]
		transporte = self._gets_team([
			(TEAM_PUSH, DIRECTOS),      # previo
			(TEAM_ADMIN, DIRECTOS),     # verificación del apply
			(TEAM_ADMIN, DIRECTOS),     # antes de revertir
			(TEAM_PUSH, DIRECTOS),      # post-rollback
		])
		plan = self._plan_team()
		self._correr(plan, transporte)
		op = plan.operation_ids
		self.assertEqual(op.state, "applied")

		previo = json.loads(op.audit_log_id.previous_state_json)
		self.assertEqual(previo["permiso_del_team"], "push")
		self.assertEqual(previo["directos"],
						 [{"login": "primateuy", "permission": "maintain"}])

		self._revertir(plan, transporte)
		self.assertEqual(op.state, "rolled_back")

	def test_revertir_un_team_que_no_tenia_acceso_lo_quita(self):
		SIN_TEAMS = []
		TEAM_ADMIN = [{"slug": "desarrollo", "permission": "admin"}]
		transporte = self._gets_team([
			(SIN_TEAMS, []), (TEAM_ADMIN, []), (TEAM_ADMIN, []), (SIN_TEAMS, []),
		])
		plan = self._plan_team()
		self._correr(plan, transporte)
		previo = json.loads(plan.operation_ids.audit_log_id.previous_state_json)
		self.assertIsNone(previo["permiso_del_team"])

		self._revertir(plan, transporte)
		self.assertIn(
			("DELETE", "https://api.github.com/orgs/%s/teams/desarrollo/repos/org/sbx"
			 % self.backend.owner_login), transporte.llamadas)

	def test_el_team_grant_se_verifica_por_el_permiso_DEL_TEAM(self):
		"""No por el efectivo de nadie: son capas distintas."""
		TEAM_PUSH = [{"slug": "desarrollo", "permission": "push"}]
		DIRECTOS = [{"login": "primateuy", "role_name": "admin"}]
		transporte = self._gets_team([
			(TEAM_PUSH, DIRECTOS),
			# alguien tiene admin directo, pero el TEAM sigue en push: no se escribió.
			(TEAM_PUSH, DIRECTOS),
		])
		plan = self._plan_team()
		self._correr(plan, transporte)
		self.assertEqual(plan.operation_ids.state, "failed")
		self.assertIn("el team quedó con push", plan.operation_ids.error)

	def test_los_otros_teams_entran_en_el_estado_previo(self):
		VARIOS = [{"slug": "desarrollo", "permission": "push"},
				  {"slug": "owners", "permission": "admin"}]
		transporte = self._gets_team([
			(VARIOS, []),
			([{"slug": "desarrollo", "permission": "admin"},
			  {"slug": "owners", "permission": "admin"}], []),
		])
		plan = self._plan_team()
		self._correr(plan, transporte)
		previo = json.loads(plan.operation_ids.audit_log_id.previous_state_json)
		self.assertEqual(previo["otros_teams"],
						 [{"slug": "owners", "permission": "admin"}])

	# --- rulesets: la clase que crea identidad --------------------------------

	def _plan_ruleset(self):
		plan = self.env["repo.write.plan"].create({
			"name": "Ruleset", "backend_id": self.backend.id})
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "ruleset_create",
			"repository_id": self.repo.id, "target": "19.0",
			"payload_json": json.dumps({"name": "sonda", "target": "branch",
										"enforcement": "active"}),
		})
		plan.action_approve()
		return plan

	def test_la_identidad_se_guarda_antes_de_verificar(self):
		transporte = Transporte(
			gets=[Respuesta(200, [AJENO]),            # previo
				  Respuesta(200, [AJENO, NUESTRO])],  # verificación
			escrituras={"POST": Respuesta(201, NUESTRO)})
		plan = self._plan_ruleset()
		self._correr(plan, transporte)

		op = plan.operation_ids
		self.assertEqual(op.state, "applied")
		identidad = self.env["repo.audit.log"].search(
			[("operation_id", "=", op.id), ("event_type", "=", "write_identity")])
		self.assertEqual(len(identidad), 1)
		self.assertEqual(json.loads(identidad.payload_json)["identidad"], 999)

	def test_si_muere_entre_crear_y_verificar_el_rollback_encuentra_el_id(self):
		"""EL escenario del paso 2b.

		El apply crea el ruleset y se cae antes de verificar. La identidad ya quedó
		guardada en su propia entrada, así que el rollback sabe exactamente qué borrar —y
		el ruleset ajeno que estaba antes no se toca.
		"""
		class TransporteQueMuere(Transporte):
			"""Muere en la SEGUNDA lectura de rulesets, que es la verificación.

			La primera es el estado previo y tiene que salir bien: el escenario que
			importa es el de un objeto YA CREADO cuyo ciclo no llegó a terminar.
			"""

			def __init__(self, *a, **kw):
				super().__init__(*a, **kw)
				self.lecturas_de_rulesets = 0

			def get(self, url, headers=None, timeout=None):
				if "/rulesets" in url:
					self.lecturas_de_rulesets += 1
					if self.lecturas_de_rulesets == 2:
						raise RuntimeError("se cortó la red a mitad del ciclo")
				return super().get(url, headers=headers, timeout=timeout)

		transporte = TransporteQueMuere(
			gets=[Respuesta(200, [AJENO])],
			escrituras={"POST": Respuesta(201, NUESTRO)})
		plan = self._plan_ruleset()
		# try/except PLANO, y no `assertRaises`: el de Odoo abre un savepoint y hace
		# rollback al capturar la excepción, que es exactamente lo que el cursor durable
		# existe para sobrevivir. Como en un test la conexión durable es la actual (ver
		# `_sin_cursor_aparte`), ese savepoint se llevaría puesta la identidad y el test
		# probaría lo contrario de lo que quiere probar.
		murio = False
		try:
			self._correr(plan, transporte)
		except RuntimeError:
			murio = True
		self.assertTrue(murio, "el apply tenía que morir en la verificación")

		op = plan.operation_ids
		self.assertEqual(op.state, "created",
						 "el objeto existe en GitHub: el estado tiene que decirlo")
		self.assertEqual(op._identidad_guardada(), 999)

		# El rollback, con la red de vuelta.
		transporte2 = Transporte(gets=[
			Respuesta(200, [AJENO, NUESTRO]),   # antes de revertir
			Respuesta(200, [AJENO]),            # post-rollback: sólo queda el ajeno
		])
		self._revertir(plan, transporte2)

		self.assertEqual(op.state, "rolled_back")
		self.assertIn(
			("DELETE", "https://api.github.com/repos/org/sbx/rulesets/999"),
			transporte2.llamadas, "borra POR ID el que creamos")
		self.assertFalse(
			[c for c in transporte2.llamadas if c[1].endswith("/rulesets/111")],
			"el ruleset ajeno no se toca ni de casualidad")

	def test_no_se_borra_un_ruleset_que_ya_existia(self):
		"""Si el id registrado estaba en la lista previa, no lo creamos nosotros."""
		transporte = Transporte(
			gets=[Respuesta(200, [AJENO]), Respuesta(200, [AJENO])],
			escrituras={"POST": Respuesta(201, AJENO)})   # GitHub devuelve el id ajeno
		plan = self._plan_ruleset()
		self._correr(plan, transporte)

		with self.assertRaises(UserError) as ctx:
			self._revertir(plan, Transporte(gets=[Respuesta(200, [AJENO])]))
		self.assertIn("ya existía antes", str(ctx.exception))

	def test_sin_identidad_devuelta_la_operacion_no_sigue(self):
		transporte = Transporte(
			gets=[Respuesta(200, [AJENO])],
			escrituras={"POST": Respuesta(201, {"name": "sonda"})})   # sin id
		plan = self._plan_ruleset()
		with self.assertRaises(UserError) as ctx:
			self._correr(plan, transporte)
		self.assertIn("no devolvió el id", str(ctx.exception))

	def test_el_estado_previo_de_un_ruleset_es_la_lista_con_ids(self):
		transporte = Transporte(
			gets=[Respuesta(200, [AJENO]), Respuesta(200, [AJENO, NUESTRO])],
			escrituras={"POST": Respuesta(201, NUESTRO)})
		plan = self._plan_ruleset()
		self._correr(plan, transporte)
		previo = json.loads(plan.operation_ids.audit_log_id.previous_state_json)
		self.assertEqual(previo["rulesets"],
						 [{"id": 111, "name": "ajeno-no-tocar",
						   "enforcement": "active"}])

	# --- membresía de team: el rol también es estado previo -------------------

	def _plan_membresia(self, kind="team_member_remove", rol=None):
		plan = self.env["repo.write.plan"].create({
			"name": "Membresía", "backend_id": self.backend.id})
		payload = {"login": "primateuy"}
		if rol:
			payload["role"] = rol
		self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": kind, "repository_id": self.repo.id,
			"target": "desarrollo", "payload_json": json.dumps(payload),
		})
		plan.action_approve()
		return plan

	def test_sacar_del_team_y_revertir_devuelve_EL_MISMO_ROL(self):
		"""Quien era `maintainer` no puede volver como `member`.

		Sería devolverle menos de lo que tenía y dar el rollback por bueno igual, que es
		la forma silenciosa de degradar a alguien en un offboarding mal revertido.
		"""
		MAINTAINER = {"role": "maintainer", "state": "active"}
		transporte = Transporte(gets=[
			Respuesta(200, MAINTAINER),        # previo
			Respuesta(404, {}),                # verificación: ya no está
			Respuesta(404, {}),                # antes de revertir
			Respuesta(200, MAINTAINER),        # post-rollback
		])
		plan = self._plan_membresia()
		self._correr(plan, transporte)
		op = plan.operation_ids
		self.assertEqual(op.state, "applied")

		previo = json.loads(op.audit_log_id.previous_state_json)
		self.assertEqual(previo, {"miembro": True, "rol": "maintainer",
								  "estado": "active"})

		self._revertir(plan, transporte)
		self.assertEqual(op.state, "rolled_back")
		puts = [c for c in transporte.cuerpos
				if c[0] == "PUT" and "memberships/primateuy" in c[1]]
		self.assertTrue(puts, "se restaura poniéndolo de vuelta")
		self.assertEqual(
			puts[-1][2], {"role": "maintainer"},
			"con SU rol, no con el default: volver como `member` sería degradarlo")

	def test_revertir_a_quien_no_estaba_en_el_team_lo_saca(self):
		transporte = Transporte(gets=[
			Respuesta(404, {}),                                  # previo: no estaba
			Respuesta(200, {"role": "member", "state": "active"}),  # verificación
			Respuesta(200, {"role": "member", "state": "active"}),  # antes de revertir
			Respuesta(404, {}),                                  # post-rollback
		])
		plan = self._plan_membresia(kind="team_member_add", rol="member")
		self._correr(plan, transporte)
		self.assertEqual(plan.operation_ids.state, "applied")

		self._revertir(plan, transporte)
		self.assertTrue(
			[c for c in transporte.llamadas
			 if c[0] == "DELETE" and "memberships/primateuy" in c[1]])

	def test_si_sigue_en_el_team_la_baja_no_se_da_por_buena(self):
		transporte = Transporte(gets=[
			Respuesta(200, {"role": "member", "state": "active"}),
			Respuesta(200, {"role": "member", "state": "active"}),   # sigue ahí
		])
		plan = self._plan_membresia()
		self._correr(plan, transporte)
		self.assertEqual(plan.operation_ids.state, "failed")
		self.assertIn("sigue en el team", plan.operation_ids.error)

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
		plan = self._plan(kind="ruleset_delete", payload={"name": "x"})
		with self.assertRaises(UserError) as ctx:
			self._correr(plan, Transporte(gets=[]))
		self.assertIn("todavía no está implementado", str(ctx.exception))
