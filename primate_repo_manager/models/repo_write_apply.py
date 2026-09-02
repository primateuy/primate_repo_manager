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


DOS CLASES DE OPERACIÓN, Y CUÁL LLEVA UN PASO MÁS
=================================================

Antes de implementar un tipo nuevo, ubicarlo en una de estas dos clases. La diferencia no
es de estilo: decide si el ciclo lleva cuatro pasos o cinco.

**IDEMPOTENTES POR DESTINO.** El destino de la escritura ya existe y tiene nombre propio:
una rama, una persona sobre un repositorio, un team sobre un repositorio. Escribir dos
veces deja el mismo resultado, y revertir es volver a escribir el valor anterior sobre el
MISMO destino, que sigue estando donde estaba.

    branch_protection_apply · collaborator_grant · collaborator_revoke
    team_repo_grant · team_repo_revoke

Estas van con el ciclo de cuatro pasos y nada más. Si el apply muere a mitad, no hay nada
huérfano: o el destino tiene el valor viejo, o tiene el nuevo, y en los dos casos el
estado previo alcanza para volver.

**CREAN IDENTIDAD.** La escritura hace nacer un objeto que antes no existía y al que
GitHub le asigna un id que sólo se conoce DESPUÉS de crearlo: un ruleset, un repositorio,
un team, un webhook, una PR.

    ruleset_create · (F3: crear repositorio, crear team, alta de webhook)

Estas llevan un paso extra, y va ANTES de verificar:

    1. leer el estado previo
    2. ejecutar
    2b. PERSISTIR LA IDENTIDAD DEVUELTA, en su propia entrada de bitácora y en su propia
        transacción, antes de cualquier otra cosa
    3. verificar releyendo
    4. registrar

El motivo es el escenario que arruina todo lo demás: **el apply crea el objeto y se cae
antes de terminar.** Si el id sólo vivió en memoria, GitHub queda con un objeto nuevo y
Odoo sin saber cuál es. El rollback entonces no tiene a qué apuntar, y las salidas de
apuro son todas malas: borrar «el último de la lista» o buscar «el que se llama como el
nuestro» puede borrar un objeto ajeno y preexistente que nadie pidió tocar.

Por eso el estado previo de estas operaciones incluye la LISTA COMPLETA con ids, y por
eso la identidad se guarda apenas GitHub la devuelve, en una transacción propia para que
sobreviva al rollback de la transacción que se cae.

REGLA PRÁCTICA: ¿el objeto que escribo ya existía y lo estoy modificando, o lo estoy
haciendo nacer? Si nace, lleva el paso 2b.
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


class RepoAuditLogWriteLink(models.Model):
	"""El enlace del registro a la operación lo agrega la capa de escritura.

	Va acá y no en `repo_audit_log.py` para que la bitácora genérica no tenga que conocer
	los planes de escritura. Y es `set null` como todos los demás: la entrada sobrevive
	aunque el plan se borre — que es justamente cuando su información de identidad se
	vuelve más necesaria, no menos.
	"""
	_inherit = "repo.audit.log"

	operation_id = fields.Many2one(
		"repo.write.operation", string="Operación", ondelete="set null", index=True)


class RepoWritePlanApply(models.Model):
	_inherit = "repo.write.plan"

	def action_apply(self):
		"""Ejecuta el plan. La guarda de congelamiento manda antes que nada."""
		self.ensure_one()
		self._verificar_congelado()

		cliente = self.backend_id.write_client()
		# Durable: si esto se escribiera sólo en la transacción del apply, una caída lo
		# devolvería a «aprobado» y el plan mentiría sobre lo que llegó a pasar.
		self._marcar_aplicando()

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

	def _cursor_durable(self):
		"""Ver el homónimo en la operación: conexión aparte, y por qué."""
		return self.pool.cursor()

	def _marcar_aplicando(self):
		self.ensure_one()
		with self._cursor_durable() as cr:
			entorno = self.env(cr=cr)
			entorno["repo.write.plan"].browse(self.id).state = "applying"
			entorno.flush_all()
		self.invalidate_recordset(["state"])

	def action_rollback(self):
		"""Revierte en ORDEN INVERSO. Una operación puede depender de la anterior.

		MISMO EMBUDO QUE EL APPLY. Revertir es escribir sobre GitHub, y no tiene por qué
		pedir menos por llamarse «deshacer»: pasa por la misma guarda de huella —el plan
		tiene que seguir siendo el que se aprobó—, por la misma compuerta de entorno, y
		deja el mismo tipo de rastro. Un camino más corto para el rollback sería una
		puerta de servicio a las mismas escrituras.
		"""
		self.ensure_one()
		# LA ADMISIBILIDAD SALE DE LOS HECHOS, NO DEL CAMPO DE ESTADO. Si el plan tuviera
		# que estar en cierto estado, una caída que se lleve esa escritura dejaría objetos
		# vivos en GitHub sin forma de limpiarlos: pasó, y así se descubrió. Lo que
		# habilita revertir es que existan operaciones cuyo objeto EXISTE —`applied` o
		# `created`—, que es lo que la caída no puede borrar porque se guardó aparte.
		# La huella se sigue exigiendo: eso no se negocia.
		self._verificar_congelado(estados=None)
		cliente = self.backend_id.write_client()
		# `created` entra: el objeto existe en GitHub aunque el ciclo no haya terminado, y
		# no poder revertirlo sería dejarlo huérfano.
		aplicadas = self.operation_ids.filtered(
			lambda o: o.state in ("applied", "created")).sorted(
				lambda o: (o.sequence, o.id), reverse=True)
		if not aplicadas:
			raise UserError(_(
				"No hay operaciones con efecto en GitHub para revertir en «%s».")
				% self.name)
		for operacion in aplicadas:
			operacion._revertir(cliente)
		self.state = "rolled_back"
		self.message_post(body=_("Plan revertido: %s operación(es).") % len(aplicadas))
		return True


class RepoWriteOperationApply(models.Model):
	_inherit = "repo.write.operation"

	state = fields.Selection(
		selection_add=[
			("blocked", "Bloqueada por el plan de GitHub"),
			# El objeto YA EXISTE en GitHub pero el ciclo no llegó a terminar. Es un
			# estado reversible a propósito: si no lo fuera, un apply caído a mitad
			# dejaría el objeto huérfano y sin forma de limpiarlo desde el módulo.
			("created", "Creada, sin verificar"),
		],
		ondelete={"blocked": "set default", "created": "set default"})

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

		# --- 2b. persistir la identidad creada, ANTES de verificar --------
		# Ver la taxonomía en el docstring del módulo. Si el ciclo muere entre acá y el
		# final, esto es lo único que le dice al rollback qué objeto borrar.
		identidad = manejador.get("identidad")
		if identidad:
			self._persistir_identidad(getattr(self, identidad)(resultado), previo)

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
		if not self.audit_log_id and self.state == "created":
			# Se cayó antes de dejar la entrada final. El punto de retorno es el que se
			# guardó en el paso 2b, que está en su propia entrada.
			self.audit_log_id = self._entrada_de_identidad()
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
		self.plan_id._verificar_congelado(estados=None)
		if self.state not in ("applied", "created"):
			raise UserError(_(
				"Sólo se revierte una operación con efecto en GitHub; ésta está en «%s».")
				% self.state)
		self._revertir(self.plan_id.backend_id.write_client())
		if not self.plan_id.operation_ids.filtered(lambda o: o.state == "applied"):
			self.plan_id.state = "rolled_back"
		return True

	# ------------------------------------------------------------------
	# Paso 2b: la identidad, en su propia transacción
	# ------------------------------------------------------------------

	def _cursor_durable(self):
		"""La conexión donde se escribe la identidad: SEPARADA de la transacción actual.

		Tiene que ser otra conexión para que la entrada sobreviva al rollback de la
		transacción que se cae — que es el escenario entero del paso 2b. Es además lo que
		recomienda el propio Odoo, que prohíbe `cr.commit()` dentro de una transacción de
		test justamente porque deja el cursor roto.

		ESTA COSTURA EXISTE PARA PODER PROBAR LA LÓGICA, y conviene ser claro sobre su
		precio: una conexión nueva no ve lo que la transacción actual todavía no confirmó,
		así que en los tests —donde nada está confirmado— se la reemplaza por el cursor
		actual. Con ese reemplazo los tests verifican QUÉ se guarda y que el rollback lo
		usa, pero **no** verifican la durabilidad. Eso se prueba contra el sandbox, en dos
		procesos distintos, matando el apply en el medio.

		En producción no hay reemplazo: cuando se aprieta Aplicar, el plan y sus
		operaciones vienen confirmados de requests anteriores y la conexión nueva los ve.
		"""
		return self.pool.cursor()

	def _persistir_identidad(self, identidad, previo):
		"""Guarda el id devuelto por GitHub, en una transacción que sobreviva a la caída.

		Si el id sólo viviera en memoria, un apply que muere entre crear y verificar
		dejaría un objeto vivo en GitHub que Odoo no sabe identificar, y el rollback sin a
		qué apuntar. Ver la taxonomía en el docstring del módulo.
		"""
		self.ensure_one()
		# Se leen ANTES de abrir la otra conexión: son datos de esta transacción.
		datos = {
			"repo_id": self.repository_id.id,
			"repo_name": self.repository_id.full_name,
			"backend_id": self.plan_id.backend_id.id,
			"huella": self.plan_id.approval_fingerprint,
		}
		with self._cursor_durable() as cr:
			entorno = self.env(cr=cr)
			entorno["repo.audit.log"].sudo().create({
				"event_type": "write_identity",
				"summary": (_("Creado %(que)s en %(repo)s") % {
					"que": identidad, "repo": datos["repo_name"]})[:255],
				"backend_id": datos["backend_id"],
				"repository_id": datos["repo_id"],
				"repository_name": datos["repo_name"],
				"operation_id": self.id,
				"payload_json": json.dumps({
					"kind": self.kind, "target": self.target,
					"identidad": identidad, "plan_fingerprint": datos["huella"],
				}, default=str),
				"previous_state_json": json.dumps(previo, default=str),
			})
			entorno["repo.write.operation"].browse(self.id).state = "created"
			# El flush va DENTRO del bloque: sin él la escritura queda en caché, y el
			# `invalidate_recordset` de abajo la descartaría en vez de releerla.
			entorno.flush_all()
		self.invalidate_recordset(["state"])
		return identidad

	def _entrada_de_identidad(self):
		"""La entrada del paso 2b de esta operación, si la hubo."""
		self.ensure_one()
		return self.env["repo.audit.log"].search(
			[("operation_id", "=", self.id), ("event_type", "=", "write_identity")],
			order="id desc", limit=1)

	def _identidad_guardada(self):
		entrada = self._entrada_de_identidad()
		if not entrada:
			return None
		return json.loads(entrada.payload_json or "{}").get("identidad")

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
			"team_repo_grant": {
				"leer": "_leer_team_grant",
				"ejecutar": "_aplicar_team_grant",
				"verificar": "_verificar_team_grant",
				"revertir": "_revertir_team_grant",
			},
			"team_repo_revoke": {
				"leer": "_leer_team_grant",
				"ejecutar": "_revocar_team_grant",
				"verificar": "_verificar_team_revocacion",
				"revertir": "_revertir_team_grant",
			},
			# La única que CREA IDENTIDAD hasta ahora: lleva el paso 2b.
			"ruleset_create": {
				"leer": "_leer_rulesets",
				"ejecutar": "_crear_ruleset",
				"identidad": "_id_del_ruleset",
				"verificar": "_verificar_ruleset_creado",
				"revertir": "_revertir_ruleset_creado",
			},
		}

	# --- rulesets: la clase que crea identidad ---------------------------
	#
	# EL ESTADO PREVIO ES LA LISTA COMPLETA CON IDS, y no un objeto. En un repositorio
	# puede haber rulesets preexistentes que no son nuestros y que no se tocan; sin la
	# lista, el rollback no tendría cómo distinguir el que creamos de los que ya estaban.
	#
	# Y el borrado apunta al ID DEVUELTO Y GUARDADO, nunca «al último de la lista» ni «al
	# que se llama como el nuestro». Los dos atajos borran un ruleset ajeno el día que
	# alguien cree uno con el mismo nombre o justo después que nosotros.

	def _leer_rulesets(self, cliente):
		rulesets = cliente.paginate(
			"/repos/%s/rulesets" % self.repository_id.full_name)
		return {
			"rulesets": sorted(
				[{"id": r.get("id"), "name": r.get("name"),
				  "enforcement": r.get("enforcement")} for r in rulesets],
				key=lambda r: r["id"] or 0),
		}

	def _crear_ruleset(self, cliente):
		cuerpo = _cargar(self.payload_json) or {}
		if not cuerpo.get("name"):
			raise UserError(_("El ruleset a crear necesita al menos un `name`."))
		return cliente.post(
			"/repos/%s/rulesets" % self.repository_id.full_name, cuerpo)

	def _id_del_ruleset(self, resultado):
		"""La identidad que devolvió GitHub. Sin esto no hay paso 2b posible."""
		identidad = (resultado or {}).get("id")
		if not identidad:
			raise UserError(_(
				"GitHub no devolvió el id del ruleset creado. Sin identidad no se puede "
				"garantizar el rollback, así que la operación no continúa."))
		return identidad

	def _verificar_ruleset_creado(self, cliente):
		esperado = self._identidad_guardada()
		estado = self._leer_rulesets(cliente)
		encontrado = next(
			(r for r in estado["rulesets"] if r["id"] == esperado), None)
		if not encontrado:
			return False, _("el ruleset %s no aparece al releer") % esperado
		return True, encontrado

	def _revertir_ruleset_creado(self, cliente, previo):
		"""Borra POR ID el que creamos. Los preexistentes ni se miran."""
		identidad = self._identidad_guardada()
		if not identidad:
			raise UserError(_(
				"No hay identidad registrada para esta operación: no se sabe qué ruleset "
				"borrar y no se va a adivinar."))
		previos = {r["id"] for r in (previo.get("rulesets") or [])}
		if identidad in previos:
			raise UserError(_(
				"El ruleset %s ya existía antes de esta operación. No se borra: no lo "
				"creamos nosotros.") % identidad)
		cliente.delete(
			"/repos/%s/rulesets/%s" % (self.repository_id.full_name, identidad),
			tolerar_404=True)
		return True

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
			"efectivo": _a_escritura(role),
			"directo": _a_escritura(directo),
			# `permission` acá viene en vocabulario de ESCRITURA («push»), a diferencia
			# de `/orgs/{org}/teams/{slug}/repos`, que devuelve role_name («write»).
			# Ver el mapa de vocabularios en github_client.
			"teams": _teams_normalizados(teams),
		}

	# --- permisos por team: el espejo del mismo problema -----------------
	#
	# Quitarle el acceso a un team NO deja sin acceso a sus integrantes: los que además
	# tengan grant directo lo conservan. Y al revés, el permiso efectivo de una persona
	# no dice nada sobre el permiso DEL TEAM. Por eso el estado previo guarda el permiso
	# del team por separado, los otros teams con acceso, y la lista de directos — que la
	# operación no toca y por eso tienen que quedar idénticos después de revertir.
	#
	# Es la misma lección del grant directo, vista desde el otro lado: se verifica la
	# capa exacta que se tocó, no el agregado.

	def _ruta_team(self):
		return "/orgs/%s/teams/%s/repos/%s" % (
			self.plan_id.backend_id.owner_login, self.target,
			self.repository_id.full_name)

	def _leer_team_grant(self, cliente):
		full = self.repository_id.full_name
		teams = _teams_normalizados(
			cliente.paginate("/repos/%s/teams" % full))
		propio = next(
			(t["permission"] for t in teams if t["slug"] == self.target), None)
		directos = cliente.paginate(
			"/repos/%s/collaborators" % full, params={"affiliation": "direct"})
		return {
			"team": self.target,
			"permiso_del_team": propio,
			"otros_teams": [t for t in teams if t["slug"] != self.target],
			# No se tocan; están acá para que la comparación byte a byte lo demuestre.
			"directos": sorted(
				[{"login": u.get("login"),
				  "permission": _a_escritura(u.get("role_name"))} for u in directos],
				key=lambda u: u["login"] or ""),
		}

	def _aplicar_team_grant(self, cliente):
		return cliente.put(self._ruta_team(), {"permission": self._permiso_pedido()})

	def _revocar_team_grant(self, cliente):
		return cliente.delete(self._ruta_team(), tolerar_404=True)

	def _verificar_team_grant(self, cliente):
		estado = self._leer_team_grant(cliente)
		pedido = _a_escritura(self._permiso_pedido())
		if estado["permiso_del_team"] != pedido:
			return False, _("el team quedó con %(real)s y se pidió %(pedido)s") % {
				"real": estado["permiso_del_team"] or "ninguno", "pedido": pedido}
		return True, estado

	def _verificar_team_revocacion(self, cliente):
		estado = self._leer_team_grant(cliente)
		if estado["permiso_del_team"] is not None:
			return False, _("el team sigue con %s") % estado["permiso_del_team"]
		return True, estado

	def _revertir_team_grant(self, cliente, previo):
		anterior = previo.get("permiso_del_team")
		if anterior is None:
			cliente.delete(self._ruta_team(), tolerar_404=True)
		else:
			cliente.put(self._ruta_team(), {"permission": anterior})
		return True

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
		directo = estado.get("directo")
		if directo != _a_escritura(pedido):
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
			cliente.put(ruta, {"permission": anterior})
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


def _teams_normalizados(teams):
	"""Lista de teams con su permiso, ordenada y en un solo vocabulario."""
	return sorted(
		[{"slug": t.get("slug"),
		  "permission": _a_escritura(t.get("permission") or t.get("role_name"))}
		 for t in (teams or [])],
		key=lambda t: t["slug"] or "")


def _a_escritura(valor):
	"""Normaliza CUALQUIER permiso al vocabulario del setter (pull/triage/push/…).

	TODO lo que se guarda como estado previo pasa por acá, venga del endpoint que venga.
	El motivo es la razón de ser del mapa de vocabularios de github_client: los grants
	directos se leen en vocabulario de lectura («write») y los de team, según el
	endpoint, en el de escritura («push»). Guardar cada uno como vino dejaría dos
	vocabularios conviviendo dentro del mismo punto de retorno, y la próxima comparación
	entre ellos sería una trampa esperando.

	Es idempotente: un valor que ya está en vocabulario de escritura pasa igual.
	"""
	if valor is None:
		return None
	return {"read": "pull", "write": "push"}.get(valor, valor)


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
