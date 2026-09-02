# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El ejecutor: convierte un plan aprobado en escrituras reales sobre GitHub.

EL CICLO DE CADA OPERACIÓN, Y POR QUÉ ESE ORDEN

  1. LEER el estado previo y guardarlo. Antes de tocar nada. Es lo que después permite
     revertir, y es además donde aparecen los techos: en un repositorio privado con plan
     gratuito, la lectura de la protección devuelve 403 «Upgrade to GitHub Pro», y ahí la
     operación se marca BLOQUEADA y **no se intenta escribir**. Detectar el techo es
     distinto de chocarlo: un 403 en la escritura sería un error; un 403 en la lectura
     previa es un dato que se reporta.
  2. EJECUTAR.
  3. VERIFICAR RELEYENDO. Lo que devolvió la escritura NO cuenta como verdad. GitHub
     puede responder 200 y dejar otra cosa —o dejar lo pedido a medias—, y una escritura
     que se cree a sí misma es la forma más común de un informe que miente.
  4. REGISTRAR en la bitácora inmutable, con el estado previo y la huella del plan. La
     huella deja constancia de QUÉ se aprobó cuando se aplicó esto, comparable después
     aunque el plan ya no exista.

EL ROLLBACK SALE DE LA BITÁCORA, NO DEL PLAN. El estado previo vive en `repo.audit.log`,
que es inmutable; si viviera en el plan, quien pueda editar el plan podría reescribir el
punto de retorno.
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .github_client import GithubError, GithubNotFound, GithubPlanLimit

_logger = logging.getLogger(__name__)

# Cuerpo mínimo que GitHub exige en el PUT de protección. El payload de la operación se
# funde encima; lo que no venga, queda en el default explícito y no en lo que GitHub
# decida suponer.
PROTECCION_BASE = {
	"required_status_checks": None,
	"enforce_admins": False,
	"required_pull_request_reviews": None,
	"restrictions": None,
}


class RepoWritePlanApply(models.Model):
	_inherit = "repo.write.plan"

	def action_apply(self):
		"""Ejecuta el plan. La guarda de congelamiento manda antes que nada."""
		self.ensure_one()
		self._verificar_congelado()

		cliente = self.backend_id.write_client()
		self.write({"state": "applying"})

		for operacion in self.operation_ids.sorted(lambda o: (o.sequence, o.id)):
			if operacion.state in ("applied", "blocked"):
				continue
			operacion._aplicar(cliente)

		# `blocked` NO cuenta como fracaso: es un techo conocido y reportado, no algo
		# que el sistema hizo mal. Sólo `failed` deja el plan en fallido.
		estados = set(self.operation_ids.mapped("state"))
		if "failed" in estados:
			self.state = "failed"
		else:
			self.state = "applied"
		self.message_post(body=_(
			"Plan aplicado. Aplicadas: %(ok)s · Bloqueadas: %(bloq)s · Fallidas: %(mal)s"
		) % {
			"ok": len(self.operation_ids.filtered(lambda o: o.state == "applied")),
			"bloq": len(self.operation_ids.filtered(lambda o: o.state == "blocked")),
			"mal": len(self.operation_ids.filtered(lambda o: o.state == "failed")),
		})
		return True

	def action_rollback(self):
		"""Revierte en ORDEN INVERSO. Una operación puede depender de la anterior.

		MISMO EMBUDO QUE EL APPLY. Revertir es escribir sobre GitHub, y no tiene por qué
		pedir menos por llamarse «deshacer»: pasa por la misma guarda de huella —el plan
		tiene que seguir siendo el que se aprobó—, por la misma compuerta de entorno, y
		deja el mismo tipo de rastro. Un camino más corto para el rollback sería una
		puerta de servicio a las mismas escrituras.
		"""
		self.ensure_one()
		self._verificar_congelado(estados=("applied", "failed"))
		cliente = self.backend_id.write_client()
		aplicadas = self.operation_ids.filtered(
			lambda o: o.state == "applied").sorted(lambda o: (o.sequence, o.id),
												   reverse=True)
		if not aplicadas:
			raise UserError(_("No hay operaciones aplicadas para revertir."))
		for operacion in aplicadas:
			operacion._revertir(cliente)
		self.state = "rolled_back"
		self.message_post(body=_("Plan revertido: %s operación(es).") % len(aplicadas))
		return True


class RepoWriteOperationApply(models.Model):
	_inherit = "repo.write.operation"

	state = fields.Selection(
		selection_add=[("blocked", "Bloqueada por el plan de GitHub")],
		ondelete={"blocked": "set default"})

	# ------------------------------------------------------------------
	# Ciclo
	# ------------------------------------------------------------------

	def _aplicar(self, cliente):
		self.ensure_one()
		manejador = self._manejador()

		# --- 1. estado previo, y detección de techos --------------------
		try:
			previo = getattr(self, manejador["leer"])(cliente)
		except GithubPlanLimit as exc:
			# NO se intenta escribir. Ver el docstring del módulo.
			self._registrar_bloqueo(str(exc))
			return False
		except GithubError as exc:
			self._registrar_falla(_("No se pudo leer el estado previo: %s") % exc)
			return False

		# --- 2. ejecutar ------------------------------------------------
		try:
			resultado = getattr(self, manejador["ejecutar"])(cliente)
		except GithubPlanLimit as exc:
			# El techo se detecta en la lectura; si aparece recién acá, es que la lectura
			# no lo vio y hay que saberlo, no taparlo como si fuera lo mismo.
			self._registrar_bloqueo(
				_("Techo de plan detectado recién al escribir: %s") % exc)
			return False
		except GithubError as exc:
			self._registrar_falla(str(exc), previo=previo)
			return False

		# --- 3. verificar releyendo -------------------------------------
		ok, detalle = getattr(self, manejador["verificar"])(cliente)
		if not ok:
			self._registrar_falla(
				_("La escritura respondió bien pero la relectura no lo confirma: %s")
				% detalle, previo=previo)
			return False

		# --- 4. bitácora --------------------------------------------------
		entrada = self.env["repo.audit.log"].registrar(
			"write_applied",
			_("%(op)s en %(repo)s/%(destino)s") % {
				"op": dict(self._fields["kind"].selection).get(self.kind, self.kind),
				"repo": self.repository_id.full_name, "destino": self.target or ""},
			backend=self.plan_id.backend_id, repository=self.repository_id,
			payload={
				"kind": self.kind, "target": self.target,
				"payload": _cargar(self.payload_json),
				"plan": self.plan_id.name,
				# La huella del plan que autorizó esto.
				"plan_fingerprint": self.plan_id.approval_fingerprint,
				"resultado": detalle,
			},
			previous_state=previo)
		self.write({
			"state": "applied",
			"result_json": json.dumps(resultado, default=str)[:8000],
			"error": False,
			"audit_log_id": entrada.id,
		})
		return True

	def _revertir(self, cliente):
		"""Restaura el estado previo guardado en la bitácora, y lo verifica releyendo."""
		self.ensure_one()
		if not self.audit_log_id or not self.audit_log_id.previous_state_json:
			raise UserError(_(
				"La operación «%s» no tiene estado previo registrado: no hay punto de "
				"retorno y no se revierte a ciegas.") % self.display_name)
		punto_de_retorno = json.loads(self.audit_log_id.previous_state_json)
		manejador = self._manejador()

		# El estado previo DE ESTA ESCRITURA es lo que hay ahora, no el punto de retorno.
		# Confundirlos dejaba en la bitácora una reversión cuyo "antes" era en realidad
		# su "después", y con eso no se puede reconstruir la secuencia después.
		antes_de_revertir = getattr(self, manejador["leer"])(cliente)

		getattr(self, manejador["revertir"])(cliente, punto_de_retorno)

		# Verificación byte a byte contra el punto de retorno guardado.
		actual = getattr(self, manejador["leer"])(cliente)
		if actual != punto_de_retorno:
			raise UserError(_(
				"La reversión de «%(op)s» no devolvió el estado exacto.\n\n"
				"Antes:  %(previo)s\n"
				"Ahora:  %(actual)s"
			) % {"op": self.display_name,
				 "previo": json.dumps(punto_de_retorno, sort_keys=True)[:400],
				 "actual": json.dumps(actual, sort_keys=True)[:400]})

		self.env["repo.audit.log"].registrar(
			"write_rolled_back",
			_("Revertida %(op)s en %(repo)s/%(destino)s") % {
				"op": self.kind, "repo": self.repository_id.full_name,
				"destino": self.target or ""},
			backend=self.plan_id.backend_id, repository=self.repository_id,
			payload={
				"kind": self.kind, "target": self.target,
				"plan": self.plan_id.name,
				"plan_fingerprint": self.plan_id.approval_fingerprint,
				"restaurado_a": punto_de_retorno,
				"revierte_a_la_entrada": self.audit_log_id.id,
			},
			previous_state=antes_de_revertir)
		self.state = "rolled_back"
		return True

	def action_rollback_operation(self):
		"""Revertir UNA operación, desde su propia línea.

		Pasa por el mismo embudo que el rollback del plan entero: no es un atajo, es el
		mismo camino con menos operaciones.
		"""
		self.ensure_one()
		self.plan_id._verificar_congelado(estados=("applied", "failed"))
		if self.state != "applied":
			raise UserError(_(
				"Sólo se revierte una operación aplicada; ésta está en «%s».") % self.state)
		self._revertir(self.plan_id.backend_id.write_client())
		if not self.plan_id.operation_ids.filtered(lambda o: o.state == "applied"):
			self.plan_id.state = "rolled_back"
		return True

	# ------------------------------------------------------------------
	# Registro de desenlaces
	# ------------------------------------------------------------------

	def _registrar_bloqueo(self, motivo):
		self.write({"state": "blocked", "error": motivo})
		self.env["repo.audit.log"].registrar(
			"write_blocked",
			_("Bloqueada por el plan de GitHub: %s/%s")
			% (self.repository_id.full_name, self.target or ""),
			backend=self.plan_id.backend_id, repository=self.repository_id,
			payload={"kind": self.kind, "motivo": motivo,
					 "plan_fingerprint": self.plan_id.approval_fingerprint})
		_logger.info("Repo Manager: operación bloqueada por plan — %s", motivo)

	def _registrar_falla(self, motivo, previo=None):
		self.write({"state": "failed", "error": motivo})
		self.env["repo.audit.log"].registrar(
			"write_failed",
			_("Falló %s en %s/%s") % (self.kind, self.repository_id.full_name,
									  self.target or ""),
			backend=self.plan_id.backend_id, repository=self.repository_id,
			payload={"kind": self.kind, "error": motivo,
					 "plan_fingerprint": self.plan_id.approval_fingerprint},
			previous_state=previo)

	# ------------------------------------------------------------------
	# Manejadores por tipo
	# ------------------------------------------------------------------

	def _manejador(self):
		self.ensure_one()
		manejadores = self._manejadores()
		if self.kind not in manejadores:
			raise UserError(_(
				"El tipo de operación «%(kind)s» todavía no está implementado.\n\n"
				"Se puede expresar en un plan pero no ejecutar: hacerlo pasar de largo "
				"en silencio dejaría un plan «aplicado» con operaciones que nunca "
				"ocurrieron."
			) % {"kind": self.kind})
		return manejadores[self.kind]

	@api.model
	def _manejadores(self):
		"""Los tipos implementados. Los demás fallan diciéndolo."""
		# Nombres de método, no referencias a funciones: así un addon que herede y
		# sobrescriba `_leer_proteccion` cambia el comportamiento de verdad, en vez de
		# quedar ignorado porque el diccionario apuntaba a la función original.
		return {
			"branch_protection_apply": {
				"leer": "_leer_proteccion",
				"ejecutar": "_aplicar_proteccion",
				"verificar": "_verificar_proteccion",
				"revertir": "_revertir_proteccion",
			},
			"collaborator_grant": {
				"leer": "_leer_grant",
				"ejecutar": "_aplicar_grant",
				"verificar": "_verificar_grant",
				"revertir": "_revertir_grant",
			},
			"collaborator_revoke": {
				"leer": "_leer_grant",
				"ejecutar": "_revocar_grant",
				"verificar": "_verificar_revocacion",
				"revertir": "_revertir_grant",
			},
		}

	# --- permisos directos de una persona -------------------------------
	#
	# EL ESTADO PREVIO DE UN GRANT NO ES UN PERMISO: SON TRES DATOS.
	#
	# Revertir un grant directo sobre un repositorio donde la persona ADEMÁS está en un
	# team no la deja sin acceso: la deja con el permiso del team. Guardar sólo el
	# permiso efectivo haría que el rollback verifique contra el número equivocado y
	# reporte una reversión fallida que en realidad salió bien — o peor, que dé por
	# revertido algo que dejó a alguien con más acceso del que tenía.
	#
	# Verificado contra el sandbox, que se sembró justo con los tres casos:
	#   sbx-localizacion     efectivo maintain · directo maintain · team push
	#   prm-sbx-interno      efectivo admin    · directo admin    · sin teams
	#   sbx-cliente-publico  efectivo maintain · SIN directo      · team maintain
	# El tercero es el que prueba que `affiliation=direct` distingue de verdad.

	def _leer_grant(self, cliente):
		"""Permiso efectivo, permiso directo y de qué teams viene. Los tres."""
		login = self.target
		full = self.repository_id.full_name
		try:
			efectivo = cliente.get(
				"/repos/%s/collaborators/%s/permission" % (full, login))
			role = efectivo.get("role_name")
		except GithubNotFound:
			role = None

		directos = cliente.paginate(
			"/repos/%s/collaborators" % full, params={"affiliation": "direct"})
		directo = next(
			(u.get("role_name") for u in directos
			 if (u.get("login") or "").lower() == (login or "").lower()), None)

		teams = cliente.get("/repos/%s/teams" % full, tolerar_404=True) or []
		return {
			"efectivo": role,
			"directo": directo,
			# `permission` acá viene en vocabulario de ESCRITURA («push»), a diferencia
			# de `/orgs/{org}/teams/{slug}/repos`, que devuelve role_name («write»).
			# Ver el mapa de vocabularios en github_client.
			"teams": sorted(
				[{"slug": t.get("slug"), "permission": t.get("permission")}
				 for t in teams], key=lambda t: t["slug"] or ""),
		}

	def _permiso_pedido(self):
		"""El permiso del payload, en vocabulario de escritura."""
		payload = _cargar(self.payload_json) or {}
		permiso = payload.get("permission")
		if not permiso:
			raise UserError(_(
				"La operación sobre «%s» no dice qué permiso dar: falta `permission` en "
				"el payload.") % (self.target or ""))
		return permiso

	def _aplicar_grant(self, cliente):
		return cliente.put(
			"/repos/%s/collaborators/%s" % (self.repository_id.full_name, self.target),
			{"permission": self._permiso_pedido()})

	def _revocar_grant(self, cliente):
		return cliente.delete(
			"/repos/%s/collaborators/%s" % (self.repository_id.full_name, self.target),
			tolerar_404=True)

	def _verificar_grant(self, cliente):
		estado = self._leer_grant(cliente)
		pedido = self._permiso_pedido()
		directo = _a_escritura(estado.get("directo"))
		if directo != pedido:
			return False, _("el permiso directo quedó en %(real)s y se pidió %(pedido)s") % {
				"real": directo or "ninguno", "pedido": pedido}
		return True, estado

	def _verificar_revocacion(self, cliente):
		"""Revocar quita el grant DIRECTO. Lo que venga del team sigue, y está bien."""
		estado = self._leer_grant(cliente)
		if estado.get("directo") is not None:
			return False, _("el permiso directo sigue siendo %s") % estado["directo"]
		return True, estado

	def _revertir_grant(self, cliente, previo):
		"""Vuelve al permiso DIRECTO que había, que puede ser ninguno.

		Si no había grant directo, se borra el que pusimos y la persona queda con lo que
		le dé su team. Volver «a nada» sería sacarle un acceso que tenía antes.
		"""
		ruta = "/repos/%s/collaborators/%s" % (
			self.repository_id.full_name, self.target)
		anterior = previo.get("directo")
		if anterior is None:
			cliente.delete(ruta, tolerar_404=True)
		else:
			cliente.put(ruta, {"permission": _a_escritura(anterior)})
		return True

	# --- protección de rama ---------------------------------------------

	def _ruta_proteccion(self):
		return "/repos/%s/branches/%s/protection" % (
			self.repository_id.full_name, self.target)

	def _leer_proteccion(self, cliente):
		"""Estado previo. Un 404 «Branch not protected» es un dato, no un error."""
		try:
			datos = cliente.get(self._ruta_proteccion())
			return {"protected": True, "config": _limpiar(datos)}
		except GithubNotFound as exc:
			if "not protected" in (exc.message or "").lower():
				return {"protected": False}
			raise

	def _aplicar_proteccion(self, cliente):
		cuerpo = dict(PROTECCION_BASE)
		cuerpo.update(_cargar(self.payload_json) or {})
		return cliente.put(self._ruta_proteccion(), cuerpo)

	def _verificar_proteccion(self, cliente):
		"""Releer y comprobar la INTENCIÓN, no ecos.

		GitHub normaliza y enriquece lo que devuelve, así que comparar la respuesta
		contra el cuerpo enviado daría falso negativo siempre. Se verifica lo que el
		payload afirmaba: que quede protegida, y que cada clave pedida esté presente.
		"""
		estado = self._leer_proteccion(cliente)
		if not estado.get("protected"):
			return False, _("la rama sigue sin protección")
		pedido = _cargar(self.payload_json) or {}
		config = estado.get("config") or {}
		faltantes = [k for k, v in pedido.items() if v is not None and k not in config]
		if faltantes:
			return False, _("faltan en la configuración: %s") % ", ".join(faltantes)
		return True, config

	def _revertir_proteccion(self, cliente, previo):
		if previo.get("protected"):
			cliente.put(self._ruta_proteccion(), previo.get("config") or {})
		else:
			cliente.delete(self._ruta_proteccion(), tolerar_404=True)
		return True


def _a_escritura(role_name):
	"""role_name (lectura) -> vocabulario del setter. Ver el mapa en github_client."""
	if role_name is None:
		return None
	return {"read": "pull", "write": "push"}.get(role_name, role_name)


def _cargar(texto):
	if not texto:
		return None
	try:
		return json.loads(texto)
	except (TypeError, ValueError):
		return None


def _limpiar(datos):
	"""Saca las URLs autorreferenciales de la respuesta de GitHub.

	No aportan al estado y sí a la comparación: son largas, cambian si el repositorio se
	renombra, y ensuciarían la verificación byte a byte del rollback sin decir nada sobre
	la configuración real.
	"""
	if isinstance(datos, dict):
		return {k: _limpiar(v) for k, v in datos.items() if not k.endswith("url")}
	if isinstance(datos, list):
		return [_limpiar(x) for x in datos]
	return datos
