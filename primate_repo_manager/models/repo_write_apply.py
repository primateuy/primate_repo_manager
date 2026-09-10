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
    team_repo_grant · team_repo_revoke · ruleset_update · codeowners_write
    branch_create · dependabot_enable

Estas van con el ciclo de cuatro pasos y nada más. Si el apply muere a mitad, no hay nada
huérfano: o el destino tiene el valor viejo, o tiene el nuevo, y en los dos casos el
estado previo alcanza para volver.

**CREAN IDENTIDAD.** La escritura hace nacer un objeto que antes no existía y al que
GitHub le asigna un id que sólo se conoce DESPUÉS de crearlo: un ruleset, un repositorio,
un team, un webhook, una PR.

    ruleset_create · repository_create · (F3: crear team, alta de webhook)

**`ruleset_create` y `ruleset_update` son tipos distintos, y la diferencia es esta
taxonomía.** El primero hace nacer el ruleset y GitHub le pone un id que sólo se conoce
después: lleva el paso 2b. El segundo escribe sobre un ruleset que YA existe y tiene id
propio, así que su destino tiene nombre, escribir dos veces deja el mismo resultado, y
revertir es volver a poner la definición anterior sobre el MISMO ruleset — cuatro pasos y
nada más.

Sin `ruleset_update`, reaplicar una política obligaba a borrar y crear, que cambia el id.
Y con el id cambiado, el punto de retorno guardado en la bitácora apunta a un objeto que
ya no existe: el rollback queda apuntando al vacío justo cuando hace falta.

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


Y UNA TERCERA CLASE, QUE ESTRENA `repository_create`: LO IRREVERSIBLE
====================================================================

No es una cuarta forma de escribir sino una propiedad de la vuelta: **hay objetos que este
módulo se niega a deshacer**. Crear un repositorio es el primero. GitHub tiene endpoint
para borrarlo; no se usa nunca.

El motivo no es técnico sino de ventana: entre que el rollback lee y borra, cabe un push
de otro, y no hay verificación previa que cierre esa ventana. Un rollback que se lleva
trabajo ajeno es peor que un repositorio vacío y sin gobierno, que al menos se ve.

Se declara NO poniendo `revertir` en el manejador —`is_irreversible` se deriva de ese
hecho, no de una lista— y el embudo exige entonces escribir el nombre del objeto para
aprobarla. El resto del plan de nacimiento sí se deshace: las ramas que creamos se borran,
Dependabot se apaga.
"""
import base64
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .github_client import (
	GithubError,
	GithubFeatureDisabled,
	GithubNotFound,
	GithubPlanLimit,
)
from .repo_codeowners import MARCA as MARCA_CODEOWNERS
from .repo_ruleset import RULESET_PREFIX

_logger = logging.getLogger(__name__)

# Cuerpo mínimo que GitHub exige en el PUT de protección. El payload de la operación se
# funde encima; lo que no venga, queda en el default explícito y no en lo que GitHub
# decida suponer.
# Lo que `ejecutar` devuelve cuando NO hizo falta escribir. No es un valor de GitHub y no
# puede confundirse con uno: es un objeto único cuya identidad se compara con `is`.
SIN_CAMBIOS = object()

# Los campos de un ruleset que este módulo gobierna. GitHub devuelve además `id`,
# `source`, `node_id`, `created_at`, `_links` y `current_user_can_bypass`, que son suyos y
# cambian solos; compararlos haría que toda verificación fallara y que todo rollback
# escribiera de más.
CAMPOS_DE_RULESET = ("name", "target", "enforcement", "bypass_actors", "conditions",
					 "rules")


def _definicion_comparable(definicion):
	"""Un ruleset reducido a lo que gobernamos, en orden estable.

	El orden importa: GitHub no promete devolver las reglas ni los actores exentos en el
	mismo orden en que se mandaron, y comparar listas ordenadas distinto daría «no
	coincide» sobre dos definiciones idénticas — una verificación que falla sobre algo que
	salió bien enseña a desconfiar de la verificación.
	"""
	definicion = definicion or {}
	salida = {}
	for campo in CAMPOS_DE_RULESET:
		valor = definicion.get(campo)
		if isinstance(valor, list):
			valor = sorted(valor, key=lambda v: json.dumps(v, sort_keys=True))
		salida[campo] = valor
	return salida


def _coincide_con_lo_pedido(deseada, actual):
	"""¿Lo que quedó en GitHub es lo que se pidió?

	NO ES IGUALDAD EXACTA, Y LO APRENDIMOS CONTRA GITHUB. El ensayo de B1.6 mostró que
	GitHub **completa el objeto con parámetros que nadie mandó** —`allowed_merge_methods`
	dentro de la regla de pull request, por ejemplo— y los devuelve al releer. Comparando
	por igualdad, una escritura que salió EXACTAMENTE como se pidió se marcaba fallida:
	«la relectura no lo confirma», con la aprobación ya gastada y un cambio real allá
	afuera. Ningún test con doble lo vio, porque el doble devolvía lo mismo que recibía —
	que es la mitad de la interfaz que el doble no imitaba.

	Lo que se exige, entonces:

	· los campos sueltos que mandamos, iguales;
	· los MISMOS TIPOS de regla, ni uno más ni uno menos —una regla que aparece sola es
	  una diferencia real y tiene que fallar—;
	· y dentro de cada regla, cada parámetro QUE MANDAMOS con nuestro valor. Los que
	  GitHub agrega por su cuenta no se miran: no los pedimos y no los gobernamos.

	Sigue siendo una verificación fuerte: caza que GitHub haya guardado otra cosa de lo
	pedido, que es para lo que existe. Lo que deja de cazar es que GitHub tenga defaults.
	"""
	deseada, actual = deseada or {}, actual or {}
	for campo in ("name", "target", "enforcement"):
		if deseada.get(campo) != actual.get(campo):
			return False, campo

	if _ordenado(deseada.get("bypass_actors")) != _ordenado(actual.get("bypass_actors")):
		return False, "bypass_actors"
	if (deseada.get("conditions") or {}) != (actual.get("conditions") or {}):
		return False, "conditions"

	reglas_deseadas = {r.get("type"): (r.get("parameters") or {})
					   for r in (deseada.get("rules") or [])}
	reglas_actuales = {r.get("type"): (r.get("parameters") or {})
					   for r in (actual.get("rules") or [])}
	if set(reglas_deseadas) != set(reglas_actuales):
		return False, "rules"
	for tipo, parametros in reglas_deseadas.items():
		for clave, valor in parametros.items():
			if reglas_actuales[tipo].get(clave) != valor:
				return False, "%s.%s" % (tipo, clave)
	return True, None


def _ordenado(valor):
	return sorted(valor or [], key=lambda v: json.dumps(v, sort_keys=True))


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
		self._verificar_alcance(cliente)
		# Escritura normal, en esta transacción. Marcarlo desde una conexión aparte fue el
		# primer intento y es un error: actualizar la MISMA FILA desde dos conexiones
		# dentro de una sola operación lógica termina en «could not serialize access due
		# to concurrent update». Y no hace falta: si una caída se lleva este estado, la
		# admisibilidad del rollback no depende de él.
		self.write({"state": "applying", "started_at": fields.Datetime.now(),
					"finished_at": False})
		self._emitir_avance(inmediato=True)

		for operacion in self.operation_ids.sorted(lambda o: (o.sequence, o.id)):
			if operacion.state in ("applied", "blocked"):
				continue
			# LA BARRERA. Se pregunta ANTES de leer nada de GitHub: una operación
			# bloqueada por dependencia no tiene que gastar ni una llamada, y sobre todo
			# no tiene que empezar. Ver `depends_on_ids`.
			faltan = operacion._dependencias_incumplidas()
			if faltan:
				operacion.write({
					"state": "blocked_by_dependency",
					"dependency_blocked_by": ", ".join(faltan)[:255],
				})
				self._emitir_avance(actual=operacion.description, inmediato=True)
				continue
			# El aviso de apertura sale fuera de la transacción por el mismo motivo que en
			# la auditoría: el apply entero corre en UNA transacción, así que un aviso
			# emitido por el camino normal llegaría recién al final —todos juntos— y la
			# pantalla no mostraría avance sino un salto. Ver `repo.audit.run._emitir_avance`.
			self._emitir_avance(actual=operacion.description, inmediato=True)
			operacion._aplicar(cliente)
			self._emitir_avance(actual=operacion.description, inmediato=True)

		# `blocked` NO cuenta como fracaso: es un techo conocido y reportado, no algo
		# que el sistema hizo mal. Sólo `failed` deja el plan en fallido.
		estados = set(self.operation_ids.mapped("state"))
		# Una operación bloqueada por dependencia cuenta como plan FALLIDO: algo que se
		# aprobó no se hizo. Que no se haya intentado es la razón, no una atenuante.
		#
		# Y una PENDIENTE DE CONCILIACIÓN, también. Lo encontró un test: con la operación
		# frenada por una cuenta abierta, el plan se marcaba «aplicado» —no había fallado
		# nada, técnicamente— y con eso quedaba cerrado y no se podía volver a aplicar
		# después de conciliar. Un plan que no hizo lo que se aprobó no está aplicado,
		# aunque el motivo sea una precaución nuestra y no un error de GitHub.
		if estados & {"failed", "blocked_by_dependency", "needs_reconciliation"}:
			self.state = "failed"
		else:
			self.state = "applied"
		self.finished_at = fields.Datetime.now()
		# Éste SÍ va por el camino normal: el «terminé» sólo vale si el apply confirmó.
		self._emitir_avance()
		self.message_post(body=_(
			"Plan aplicado. Aplicadas: %(ok)s · Bloqueadas: %(bloq)s · Fallidas: %(mal)s"
		) % {
			"ok": len(self.operation_ids.filtered(lambda o: o.state == "applied")),
			"bloq": len(self.operation_ids.filtered(lambda o: o.state == "blocked")),
			"mal": len(self.operation_ids.filtered(lambda o: o.state == "failed")),
		})
		return True

	def _verificar_alcance(self, cliente):
		"""Ningún destino del plan puede estar fuera del alcance de la instalación.

		Se comprueba ANTES de empezar. Sin esto, un plan que toca un repositorio fuera del
		alcance se entera con un 404 a mitad de camino, con las operaciones anteriores ya
		aplicadas — y un 404 de GitHub no distingue «no existe» de «no lo podés ver», así
		que el mensaje tampoco ayudaría.

		Preguntarle a la instalación qué abarca cuesta una llamada y convierte un fallo
		confuso a mitad de plan en un rechazo claro antes de tocar nada.
		"""
		self.ensure_one()
		abarcados = {r.get("full_name") for r in cliente.paginate(
			"/installation/repositories", envoltorio="repositories")}
		destinos = {op.repository_id.full_name for op in self.operation_ids
					if op.repository_id}
		afuera = sorted(destinos - abarcados)
		if afuera:
			raise UserError(_(
				"El plan «%(nombre)s» toca repositorios que la App de escritura no "
				"abarca:\n\n  %(afuera)s\n\n"
				"El alcance de la instalación es deliberado: la escritura se habilita por "
				"tandas. Agregá esos repositorios a la instalación de la App —o sacalos "
				"del plan— y volvé a aprobarlo."
			) % {"nombre": self.name, "afuera": "\n  ".join(afuera)})
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
		# LA ADMISIBILIDAD SALE DE LOS HECHOS, NO DEL CAMPO DE ESTADO. Si el plan tuviera
		# que estar en cierto estado, una caída que se lleve esa escritura dejaría objetos
		# vivos en GitHub sin forma de limpiarlos: pasó, y así se descubrió. Lo que
		# habilita revertir es que existan operaciones cuyo objeto EXISTE —`applied` o
		# `created`—, que es lo que la caída no puede borrar porque se guardó aparte.
		# La huella se sigue exigiendo: eso no se negocia.
		self._verificar_congelado(estados=None)
		cliente = self.backend_id.write_client()
		self._verificar_alcance(cliente)
		# `created` entra: el objeto existe en GitHub aunque el ciclo no haya terminado, y
		# no poder revertirlo sería dejarlo huérfano.
		aplicadas = self.operation_ids.filtered(
			lambda o: o._tiene_efecto_en_github()).sorted(
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

	def _dependencias_incumplidas(self):
		"""Las dependencias que NO quedaron aplicadas. Vacío significa vía libre.

		«Aplicada» y nada más: una dependencia bloqueada por techo de plan tampoco
		habilita. Que GitHub no nos haya dejado hacer algo por una razón entendible no
		cambia el hecho de que no se hizo, y lo que viene después contaba con que sí.
		"""
		self.ensure_one()
		return [
			d.description or d.display_name
			for d in self.depends_on_ids
			if d.state != "applied"
		]

	def _aplicar(self, cliente):
		self.ensure_one()
		manejador = self._manejador()

		# --- 0. LA CUENTA ABIERTA SE SALDA ANTES DE ESCRIBIR OTRA VEZ ----
		#
		# Si esta operación ya emitió una escritura y nunca se supo cómo terminó, el
		# estado previo que está por leerse INCLUYE esa escritura, y con eso el punto de
		# retorno queda contaminado para siempre. Se para acá y se pide conciliar.
		abiertas = self._emisiones_sin_desenlace()
		if abiertas:
			self.write({
				"state": "needs_reconciliation",
				"error": _(
					"Esta operación ya emitió %(n)s escritura(s) hacia GitHub sin que se "
					"registrara cómo terminaron —lo habitual es una caída entre escribir "
					"y verificar—. Aplicarla de nuevo leería como «estado previo» lo que "
					"esa escritura dejó, y el punto de retorno quedaría contaminado.\n\n"
					"Conciliar: releer GitHub y decidir si eso cuenta como aplicado o se "
					"revierte."
				) % {"n": len(abiertas)},
			})
			return False

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
		except UserError as exc:
			if not manejador.get("falla_sola"):
				raise
			self._registrar_falla(str(exc))
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
		except UserError as exc:
			# EL MANEJADOR DECIDE SI SU GUARDA TUMBA EL PLAN O SÓLO SU OPERACIÓN, y las
			# dos posturas son correctas en su lugar.
			#
			# Las guardas viejas —«este ruleset no lleva nuestro prefijo», «el payload no
			# trae permiso»— dicen que el plan está MAL ARMADO: seguir aplicando las
			# demás sería seguir ejecutando algo que ya se sabe equivocado, y por eso
			# abortan.
			#
			# La de borrar ramas dice otra cosa: que el mundo cambió debajo de UNA
			# operación —alguien empujó a esa rama después de la auditoría— y las otras
			# siete del lote siguen siendo válidas. Abortar ahí dejaría las dos primeras
			# aplicadas, ésta sin registro y las cinco últimas sin intentar ni explicar.
			#
			# Lo declara el manejador y no una lista aparte: el día que se agregue otra
			# guarda de esta clase, decidirlo es parte de escribirla.
			if not manejador.get("falla_sola"):
				raise
			self._registrar_falla(str(exc), previo=previo)
			return False
		except GithubError as exc:
			self._registrar_falla(str(exc), previo=previo)
			return False

		# --- 2a. DEJAR CONSTANCIA DE QUE LA ESCRITURA SALIÓ ---------------
		#
		# Es el mismo argumento del paso 2b, aplicado a TODAS las operaciones y no sólo a
		# las que crean identidad. Entre que GitHub acepta la escritura y que la
		# verificación la confirma hay una ventana; si el ciclo termina ahí —porque la
		# relectura no cuadra, o porque el proceso se cae— la operación queda marcada como
		# fallida y allá afuera hay un cambio real.
		#
		# Sin esta constancia, la admisibilidad del rollback se decidía mirando el ESTADO
		# de la operación, y «fallida» decía «no hay nada que revertir» cuando sí lo había.
		# Pasó: un apply cuyo payload no era una configuración escribió una protección que
		# nadie diseñó, la verificación la rechazó con razón, y el embudo se quedó sin
		# camino de vuelta para su propio efecto.
		#
		# La admisibilidad sale de los HECHOS —¿salió una escritura?— y no de un campo que
		# describe cómo terminó el intento. Es la doctrina del paso 3e, aplicada al lugar
		# donde se había esquivado.
		# SI NO HIZO FALTA ESCRIBIR, NO SE DEJA CONSTANCIA DE UNA EMISIÓN. La constancia
		# afirma «salió una escritura hacia GitHub», y no salió ninguna: anotarla igual
		# abriría una cuenta que después alguien tiene que conciliar contra un efecto que
		# no existe, y la guarda de frenar se dispararía sobre una operación impecable.
		# Un falso positivo en una guarda es la peor clase — la guarda que grita sin razón
		# termina ignorada.
		sin_cambios = resultado is SIN_CAMBIOS
		if not sin_cambios:
			self._persistir_emision(previo)

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
				# Aplicada y sin escribir NO es lo mismo que aplicada: el estado deseado
				# ya estaba. Queda dicho en la entrada para que la bitácora no afirme una
				# escritura que no ocurrió.
				"sin_cambios": sin_cambios,
			},
			previous_state=previo,
			# EL ENLACE, que faltaba. La operación apuntaba a la entrada pero la entrada no
			# apuntaba a la operación, y con eso `_emisiones_sin_desenlace` no encontraba
			# los desenlaces: cada apply EXITOSO dejaba cuentas abiertas falsas, y el
			# siguiente apply se habría frenado pidiendo conciliar algo que estaba
			# perfecto. Lo encontró la primera corrida contra GitHub.
			extra={"operation_id": self.id})
		self.write({
			"state": "applied",
			"result_json": json.dumps(
				"sin cambios: ya estaba como se pedía" if sin_cambios else resultado,
				default=str)[:8000],
			"error": False,
			"audit_log_id": entrada.id,
		})
		return True

	def _revertir(self, cliente):
		"""Restaura el estado previo guardado en la bitácora, y lo verifica releyendo."""
		self.ensure_one()
		if not self.audit_log_id and self.state in ("created", "pending"):
			# Se cayó antes de dejar la entrada final. El punto de retorno es el que se
			# guardó en el paso 2b, que está en su propia entrada.
			self.audit_log_id = self._entrada_de_identidad()
		if not self.audit_log_id and self.state == "failed":
			# Falló DESPUÉS de escribir: la constancia de emisión tiene el punto de
			# retorno. Sin esto, el efecto de una operación fallida se quedaba afuera del
			# embudo y había que deshacerlo a mano en GitHub.
			self.audit_log_id = (
				self._entrada_de_emision() or self._entrada_de_identidad())
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
			previous_state=antes_de_revertir, extra={"operation_id": self.id})
		self.state = "rolled_back"
		return True

	def action_rollback_operation(self):
		"""Revertir UNA operación, desde su propia línea.

		Pasa por el mismo embudo que el rollback del plan entero: no es un atajo, es el
		mismo camino con menos operaciones.
		"""
		self.ensure_one()
		self.plan_id._verificar_congelado(estados=None)
		if not self._tiene_efecto_en_github():
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

	def _persistir_emision(self, previo):
		"""Deja constancia, en su propia conexión, de que la escritura ya salió.

		En conexión aparte por lo mismo que la identidad del paso 2b: si la transacción se
		cae, esta constancia tiene que sobrevivir — es lo único que le va a decir al
		rollback que hay algo que deshacer.
		"""
		self.ensure_one()
		datos = {
			"repo_id": self.repository_id.id,
			"repo_name": self.repository_id.full_name,
			"backend_id": self.plan_id.backend_id.id,
			"kind": self.kind,
			"target": self.target or "",
		}
		with self._cursor_durable() as cr:
			entorno = self.env(cr=cr)
			entorno["repo.audit.log"].sudo().registrar(
				"write_emitted",
				_("Escritura emitida sobre %(repo)s/%(destino)s, sin verificar todavía")
				% {"repo": datos["repo_name"], "destino": datos["target"]},
				backend=entorno["repo.backend"].browse(datos["backend_id"]),
				repository=self._repositorio_visible_en(entorno, datos["repo_id"]),
				payload=datos,
				previous_state=previo,
				extra={"operation_id": self.id})

	def _repositorio_visible_en(self, entorno, repo_id):
		"""El repositorio, SÓLO si esa conexión puede verlo.

		ODOO ABRE SUS TRANSACCIONES EN REPEATABLE READ, así que la conexión durable no ve
		una fila que la transacción principal creó y todavía no confirmó. Pasa con el
		nacimiento gobernado: el repositorio se acaba de crear en esta misma corrida, y
		la constancia —que va por la conexión aparte— reventaba con «Record does not
		exist» sobre una fila perfectamente existente.

		Se pasa el enlace cuando se puede y se omite cuando no. **La entrada no pierde
		nada importante**: la bitácora guarda el nombre del repositorio COMO TEXTO
		justamente para sobrevivir a que el enlace no esté — es la misma previsión que la
        hace resistir al borrado de lo que describe, usada acá para el caso inverso.
		"""
		if not repo_id:
			return None
		return entorno["repo.repository"].browse(repo_id).exists() or None

	def _entrada_de_emision(self):
		"""La constancia de que la escritura de esta operación salió, si la hubo."""
		self.ensure_one()
		return self.env["repo.audit.log"].search([
			("event_type", "=", "write_emitted"),
			("operation_id", "=", self.id)], order="id desc", limit=1)

	# ------------------------------------------------------------------
	# CONCILIACIÓN — el punto de retorno no se contamina
	# ------------------------------------------------------------------
	#
	# EL PROBLEMA, EN UNA FRASE: una escritura que salió y cuyo ciclo no terminó deja un
	# efecto en GitHub del que la base no sabe nada, y si la operación se vuelve a aplicar,
	# LEE ESE EFECTO COMO SU ESTADO PREVIO. A partir de ahí el punto de retorno está
	# contaminado: el rollback devuelve las cosas a un estado que ya incluía lo que había
	# quedado suelto, y el resultado final tiene un objeto que ningún plan aplicado
	# explica. Ningún paso miente y el conjunto igual queda mal.
	#
	# Es la versión distribuida del «antes invertido» —cuando una reversión guardaba como
	# su estado previo el estado que ella misma había dejado—, con la diferencia de que acá
	# el estado contaminado viene de otro proceso y de otra transacción.
	#
	# LA REGLA: una operación con emisiones sin desenlace NO SE APLICA. Se para y pide
	# conciliar. Absorber lo huérfano como si fuera el paisaje es exactamente lo que no se
	# puede hacer, y es lo que pasaba.

	DESENLACES = ("write_applied", "write_failed", "write_rolled_back",
				  "write_reconciled_applied", "write_reconciled_none",
				  "write_reconciled_other")

	def _emisiones_sin_desenlace(self):
		"""Las escrituras que salieron y de las que no se sabe cómo terminaron.

		Se comparan por id: la constancia de emisión se inserta ANTES que la entrada del
		desenlace —la emisión va por su propia conexión, en el medio del ciclo, y el
		desenlace se escribe al final—, así que una emisión sin ninguna entrada de
		desenlace posterior es una cuenta abierta.
		"""
		self.ensure_one()
		Log = self.env["repo.audit.log"].sudo()
		entradas = Log.search(
			[("operation_id", "=", self.id),
			 ("event_type", "in", ("write_emitted",) + self.DESENLACES)],
			order="id")
		abiertas = Log.browse()
		for entrada in entradas:
			if entrada.event_type == "write_emitted":
				abiertas |= entrada
			else:
				# Un desenlace cierra TODAS las emisiones anteriores: describe cómo
				# terminó el ciclo, no una emisión puntual.
				abiertas = Log.browse()
		return abiertas

	def action_conciliar(self):
		"""Mira qué hay realmente en GitHub y cierra la cuenta abierta, diciendo qué pasó.

		NO decide por gusto: relee. Si el efecto está, la operación pasa a «aplicada» y
		queda disponible el rollback —con el punto de retorno de la emisión, que es el
		bueno: el de ANTES de esa escritura—. Si no está, no quedó nada y la operación
		vuelve a «pendiente» para poder intentarse de nuevo.

		Las dos salidas dejan su entrada en la bitácora. La conciliación es una decisión
		sobre un efecto real en GitHub, y una decisión así no puede no quedar registrada.
		"""
		self.ensure_one()
		abiertas = self._emisiones_sin_desenlace()
		if not abiertas:
			raise UserError(_(
				"«%s» no tiene escrituras emitidas sin desenlace: no hay nada que "
				"conciliar.") % self.display_name)
		cliente = self.plan_id.backend_id.write_client()
		manejador = self._manejador()
		emision = abiertas[-1]
		previo = json.loads(emision.previous_state_json or "{}")

		ok, detalle = getattr(self, manejador["verificar"])(cliente)
		# LO QUE HAY AHORA, comparado con lo que había antes de la escritura. Es lo único
		# que distingue los dos «no» que la verificación mete en la misma bolsa.
		ahora = getattr(self, manejador["leer"])(cliente)
		datos = {"emisiones": abiertas.ids, "detalle": str(detalle),
				 "leido_al_conciliar": ahora}

		if ok:
			self.write({"state": "applied", "error": False})
			entrada = self.env["repo.audit.log"].registrar(
				"write_reconciled_applied",
				_("La escritura de «%s» sí había quedado en GitHub") % self.display_name,
				backend=self.plan_id.backend_id, repository=self.repository_id,
				payload=datos, previous_state=previo,
				extra={"operation_id": self.id})
			# El punto de retorno pasa a ser el de la emisión, que es el de ANTES de la
			# escritura huérfana. Es la parte que evita que el rollback devuelva las cosas
			# a un estado que ya la contenía.
			self.audit_log_id = entrada
		elif ahora == previo:
			# NADA CAMBIÓ desde antes de la escritura: salió, pero no llegó a quedar. No
			# hay nada que deshacer y la operación puede volver a intentarse.
			self.write({"state": "pending", "error": False})
			self.env["repo.audit.log"].registrar(
				"write_reconciled_none",
				_("La escritura de «%s» no llegó a quedar: no hay nada que deshacer")
				% self.display_name,
				backend=self.plan_id.backend_id, repository=self.repository_id,
				payload=datos, extra={"operation_id": self.id})
		else:
			# EL TERCER CASO, Y EL QUE CASI NO EXISTE.
			#
			# «La verificación no pasa» y «no se escribió nada» NO son lo mismo, y la
			# primera versión de esto los trataba igual: la operación quedaba «pendiente»
			# y la bitácora decía «no hay nada que deshacer» mientras allá afuera había un
			# cambio real. Es exactamente la absorción que toda esta función existe para
			# evitar, corrida un paso más adelante.
			#
			# Lo encontró la PRIMERA CORRIDA CONTRA GITHUB DE VERDAD. Con transporte falso
			# los dos casos se veían iguales.
			#
			# Acá hay efecto y no es el aprobado: la operación queda fallida —con el
			# efecto registrado, así que el rollback sigue disponible y su punto de
			# retorno es el de antes de la escritura— y nadie la vuelve a aplicar encima.
			entrada = self.env["repo.audit.log"].registrar(
				"write_reconciled_other",
				_("En «%s» quedó algo DISTINTO de lo aprobado: hay efecto, y no es el que "
				  "se pidió") % self.display_name,
				backend=self.plan_id.backend_id, repository=self.repository_id,
				payload=datos, previous_state=previo,
				extra={"operation_id": self.id})
			self.audit_log_id = entrada
			self.write({
				"state": "failed",
				"error": _(
					"La escritura salió y lo que quedó en GitHub NO es lo que se aprobó: "
					"%(detalle)s. Hay un efecto real allá afuera: se puede revertir desde "
					"acá —el punto de retorno es el de antes de esta escritura— o "
					"resolverlo a mano y armar un plan nuevo. Lo que no se puede es "
					"aplicar esto de nuevo encima."
				) % {"detalle": detalle},
			})
		return True

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
				# SÓLO SI ESTA CONEXIÓN LO VE. Con el nacimiento gobernado la fila del
				# repositorio se acaba de crear en la transacción principal y todavía no
				# está confirmada: en REPEATABLE READ la durable no la ve, y la clave
				# foránea quedaría esperando a que la otra confirme —que a su vez espera
				# a ésta—. El nombre en texto, que va siempre, es lo que hace que la
				# entrada no pierda nada por omitir el enlace.
				"repository_id": (
					self._repositorio_visible_en(entorno, datos["repo_id"]).id
					if self._repositorio_visible_en(entorno, datos["repo_id"]) else False),
				"repository_name": datos["repo_name"],
				"operation_id": self.id,
				"payload_json": json.dumps({
					"kind": self.kind, "target": self.target,
					"identidad": identidad, "plan_fingerprint": datos["huella"],
				}, default=str),
				"previous_state_json": json.dumps(previo, default=str),
			})
			entorno.flush_all()
		# Y SE ANOTA TAMBIÉN EN LA TRANSACCIÓN PRINCIPAL. La verificación que viene
		# enseguida no puede leer lo que la conexión durable acaba de confirmar —
		# REPEATABLE READ—, así que sin esto buscaría la identidad donde no la va a
		# encontrar. Ver `_identidad_guardada`.
		self.result_json = json.dumps({"identidad": identidad}, default=str)
		# El estado va por la transacción NORMAL. La conexión durable sólo INSERTA filas
		# nuevas: actualizar desde ella una fila que después toca la transacción
		# principal provoca un fallo de serialización. Si una caída se lleva este estado,
		# la entrada insertada arriba alcanza para saber que el objeto existe.
		self.state = "created"
		return identidad

	def _tiene_efecto_en_github(self):
		"""¿Esta operación dejó algo escrito allá afuera?

		El estado es la respuesta cuando sobrevivió. Cuando no —una caída se lo llevó— lo
		que queda es la entrada de identidad, que se insertó en su propia conexión
		justamente para eso. Se miran los dos: el campo dice lo que cree el sistema, la
		entrada dice lo que pasó.
		"""
		self.ensure_one()
		# LOS HECHOS, no el estado. Una operación «fallida» puede haber escrito: si la
		# relectura no confirmó, el intento fracasó pero el cambio existe. Preguntarle al
		# campo `state` es preguntarle al sistema qué CREE; preguntarle a la bitácora es
		# preguntarle qué PASÓ.
		return (self.state in ("applied", "created")
				or bool(self._entrada_de_identidad())
				or self._emision_con_efecto())

	def _emision_con_efecto(self):
		"""¿Alguna escritura emitida sigue teniendo efecto allá afuera?

		Una emisión sola dice «salió algo». Lo que vino DESPUÉS dice si ese algo sigue
		estando: una conciliación que releyó y no encontró nada cierra el asunto, y una
		reversión lo deshizo. En los dos casos ya no hay efecto que revertir, y seguir
		diciendo que sí ofrecería deshacer algo que no existe.

		Lo encontró el camino de la conciliación: una emisión conciliada como «no quedó
		nada» seguía contando como efecto para siempre, y con eso el plan quedaba marcado
		como «ejecutó algo» y no podía volver a borrador.
		"""
		self.ensure_one()
		entradas = self.env["repo.audit.log"].sudo().search(
			[("operation_id", "=", self.id),
			 ("event_type", "in", ("write_emitted",) + self.DESENLACES)],
			order="id")
		if not entradas or not any(e.event_type == "write_emitted" for e in entradas):
			return False
		return entradas[-1].event_type not in (
			"write_reconciled_none", "write_rolled_back")

	def _entrada_de_identidad(self):
		"""La entrada del paso 2b de esta operación, si la hubo."""
		self.ensure_one()
		return self.env["repo.audit.log"].search(
			[("operation_id", "=", self.id), ("event_type", "=", "write_identity")],
			order="id desc", limit=1)

	def _identidad_guardada(self):
		"""La identidad que GitHub devolvió: primero la de esta corrida, después la
		bitácora.

		POR QUÉ HACEN FALTA LAS DOS. La entrada se escribe en la conexión durable —para
		que sobreviva a una caída— y **Odoo abre sus transacciones en REPEATABLE READ**,
		así que la transacción que está aplicando NO PUEDE LEER lo que esa conexión
		acaba de confirmar. La verificación buscaba la identidad ahí mismo y no la
		encontraba: la escritura salía bien, el objeto quedaba creado en GitHub, y la
		operación se marcaba fallida.

		Lo encontró el ensayo de B5.4, y hay que decir por qué recién ahora:
		`ruleset_create` nunca se había ejercitado contra GitHub. El ensayo de B1.6 usó
		`ruleset_update`, que no crea identidad. El defecto estaba desde que se escribió.

		El campo de resultado sirve para ESTA corrida; la bitácora, para la que retoma
		después de una caída. Ninguna reemplaza a la otra.
		"""
		try:
			en_curso = json.loads(self.result_json or "{}")
		except (TypeError, ValueError):
			en_curso = {}
		if isinstance(en_curso, dict) and en_curso.get("identidad"):
			return en_curso["identidad"]
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
			previous_state=previo, extra={"operation_id": self.id})

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
			"team_member_remove": {
				"leer": "_leer_membresia",
				"ejecutar": "_sacar_del_team",
				"verificar": "_verificar_sin_membresia",
				"revertir": "_revertir_membresia",
			},
			"team_member_add": {
				"leer": "_leer_membresia",
				"ejecutar": "_poner_en_el_team",
				"verificar": "_verificar_membresia",
				"revertir": "_revertir_membresia",
			},
			# La única que CREA IDENTIDAD hasta ahora: lleva el paso 2b.
			"ruleset_create": {
				"leer": "_leer_rulesets",
				"ejecutar": "_crear_ruleset",
				"identidad": "_id_del_ruleset",
				"verificar": "_verificar_ruleset_creado",
				"revertir": "_revertir_ruleset_creado",
			},
			# B1.3 · IDEMPOTENTE POR DESTINO: el ruleset ya existe y tiene id propio, así
			# que van los cuatro pasos y NO el 2b. Ver la taxonomía arriba.
			# B5 · CREA IDENTIDAD y es IRREVERSIBLE: no declara `revertir`, y de ahí
			# sale su marca en la pantalla. Ver la taxonomía arriba.
			"repository_create": {
				"leer": "_leer_repositorio_a_crear",
				"ejecutar": "_crear_repositorio",
				"identidad": "_id_del_repositorio",
				"verificar": "_verificar_repositorio_creado",
			},
			# Idempotente por destino: la ref tiene nombre propio. Revertir es borrar la
			# rama, y SÓLO si el estado previo dice que no existía.
			"branch_create": {
				"leer": "_leer_rama",
				"ejecutar": "_crear_rama",
				"verificar": "_verificar_rama_creada",
				"revertir": "_revertir_rama_creada",
			},
			# Idempotente por destino: la rama por defecto es una sola. Revertir es
			# volver a poner la que estaba.
			"default_branch_set": {
				"leer": "_leer_rama_por_defecto",
				"ejecutar": "_fijar_rama_por_defecto",
				"verificar": "_verificar_rama_por_defecto",
				"revertir": "_revertir_rama_por_defecto",
			},
			# Idempotente por destino y reversible: encender es PUT, apagar es DELETE.
			"dependabot_enable": {
				"leer": "_leer_dependabot",
				"ejecutar": "_encender_dependabot",
				"verificar": "_verificar_dependabot",
				"revertir": "_revertir_dependabot",
			},
			# B3.2 · IDEMPOTENTE POR DESTINO: el destino es una ruta, y escribir dos
			# veces deja el mismo archivo. Revertir es volver a poner el contenido
			# anterior — o borrar el archivo, si antes no había ninguno.
			# E3.2 · BORRAR UNA RAMA. Destructiva y reversible, con una salvedad que no
			# es letra chica: revertir es recrear la ref en el MISMO commit, y eso
			# funciona mientras GitHub todavía conserve el objeto. No lo controlamos, y
			# por eso esta operación exige el tipeo aunque tenga vuelta.
			#
			# El punto de retorno es el SHA leído en el paso 1, no el que el hallazgo
			# traía: entre que se armó el plan y se aplica, alguien pudo haber empujado
			# a esa rama. Leer antes de ejecutar es el paso 1 del ciclo justamente por
			# esto.
			"branch_delete": {
				# Su guarda falla SÓLO SU OPERACIÓN: ver el comentario de `falla_sola`
				# en `_aplicar`. Que alguien haya empujado a una rama no invalida las
				# otras siete del lote.
				"falla_sola": True,
				"leer": "_leer_rama_a_borrar",
				"ejecutar": "_borrar_rama",
				"verificar": "_verificar_rama_borrada",
				"revertir": "_recrear_rama",
			},
			"codeowners_write": {
				"leer": "_leer_codeowners",
				"ejecutar": "_escribir_codeowners",
				"verificar": "_verificar_codeowners",
				"revertir": "_revertir_codeowners",
			},
			"ruleset_update": {
				"leer": "_leer_ruleset_propio",
				"ejecutar": "_actualizar_ruleset",
				"verificar": "_verificar_ruleset_actualizado",
				"revertir": "_revertir_ruleset_actualizado",
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

	# --- rulesets: actualizar el que ya existe ---------------------------
	#
	# DOS GUARDAS CON NOMBRE, Y LAS DOS TIENEN QUE PODER FALLAR SOLAS:
	#
	# 1. NO SE TOCA UN RULESET AJENO. Un repositorio puede tener rulesets que no pusimos
	#    nosotros —de la organización, de otra herramienta, de alguien a mano— y una
	#    escritura sobre uno de ésos no es un error nuestro: es pisarle la configuración a
	#    otro. Se reconoce por el prefijo del nombre, que es lo que B1.1 fija justamente
	#    para esto, y se verifica DOS VECES: al leer el estado previo y otra vez al
	#    revertir. La segunda no es redundante — entre una y otra pasó una escritura y
	#    pudo pasar cualquier cosa, incluido que alguien renombrara el ruleset.
	#
	# 2. EL ROLLBACK DEVUELVE, NUNCA BORRA. Revertir una actualización es volver a poner
	#    la definición anterior sobre el MISMO ruleset. Borrarlo sería destruir un objeto
	#    que existía antes de que llegáramos y que el plan sólo venía a modificar: el
	#    rollback dejaría el repositorio PEOR que antes de aplicar, que es exactamente lo
	#    contrario de para lo que existe. Por eso este manejador no tiene ningún `delete`.

	def _exigir_ruleset_propio(self, nombre, cuando):
		"""La guarda 1. Levanta si el ruleset no lo puso este módulo.

		Args:
			nombre: el nombre del ruleset tal como lo devuelve GitHub.
			cuando: en qué momento se está comprobando, para que el mensaje lo diga.

		Raises:
			UserError: si el nombre no lleva el prefijo del módulo.
		"""
		if (nombre or "").startswith(RULESET_PREFIX + "/"):
			return
		raise UserError(_(
			"«%(nombre)s» no es un ruleset de este módulo, así que no se toca (%(cuando)s). "
			"Los nuestros llevan el prefijo «%(prefijo)s/»; el resto es configuración de "
			"otro y modificarla desde acá sería pisarla."
		) % {"nombre": nombre or "?", "cuando": cuando, "prefijo": RULESET_PREFIX})

	def _leer_ruleset_propio(self, cliente):
		"""Estado previo: la definición COMPLETA del ruleset que se va a actualizar.

		Completa y no un resumen: es el punto de retorno. Un rollback que restaure «lo que
		nos acordamos» en vez de lo que había deja el ruleset distinto de como estaba y
		nadie se entera hasta el próximo merge bloqueado.
		"""
		full = self.repository_id.full_name
		lista = cliente.paginate("/repos/%s/rulesets" % full)
		encontrado = next(
			(r for r in lista if (r.get("name") or "") == self.target), None)
		if not encontrado:
			raise UserError(_(
				"No hay ningún ruleset llamado «%(nombre)s» en %(repo)s. Actualizar es "
				"sobre algo que existe; crearlo es otra operación."
			) % {"nombre": self.target or "?", "repo": full})
		self._exigir_ruleset_propio(encontrado.get("name"), _("al leer el estado previo"))

		definicion = cliente.get("/repos/%s/rulesets/%s" % (full, encontrado["id"]))
		return {
			"id": encontrado["id"],
			"name": encontrado.get("name"),
			"definicion": _definicion_comparable(definicion),
			# La lista completa, por el mismo motivo que en `ruleset_create`: sin ella no
			# hay cómo distinguir después lo nuestro de lo que ya estaba.
			"rulesets": sorted(
				[{"id": r.get("id"), "name": r.get("name")} for r in lista],
				key=lambda r: r["id"] or 0),
		}

	def _actualizar_ruleset(self, cliente):
		"""Escribe la definición nueva — salvo que ya sea la que está.

		EL DIFF ES CONTRA LO EXISTENTE. Un PUT con los mismos valores igual cuenta como
		escritura: genera un evento en GitHub, gasta cuota y aparece en la auditoría de la
		organización como un cambio que nadie hizo. Y sobre todo, deja constancia de una
		escritura emitida en la bitácora — que después alguien tiene que conciliar.
		"""
		deseada = _cargar(self.payload_json) or {}
		if not deseada.get("name"):
			raise UserError(_("El ruleset a actualizar necesita al menos un `name`."))

		previo = self._leer_ruleset_propio(cliente)
		# Mismo criterio que la verificación, y por el mismo motivo: comparando por
		# igualdad exacta, el objeto de GitHub NUNCA coincide con el nuestro —trae sus
		# defaults— y este atajo no se tomaría jamás. La idempotencia habría quedado
		# escrita y muerta.
		ya_esta, _donde = _coincide_con_lo_pedido(
			_definicion_comparable(deseada), previo["definicion"])
		if ya_esta:
			return SIN_CAMBIOS
		return cliente.put(
			"/repos/%s/rulesets/%s" % (self.repository_id.full_name, previo["id"]),
			deseada)

	def _verificar_ruleset_actualizado(self, cliente):
		"""Relee y compara. Lo que devolvió el PUT no cuenta como verdad."""
		deseada = _definicion_comparable(_cargar(self.payload_json) or {})
		actual = self._leer_ruleset_propio(cliente)
		coincide, donde = _coincide_con_lo_pedido(deseada, actual["definicion"])
		if not coincide:
			return False, _(
				"la definición releída no coincide con la que se pidió, en «%s»") % donde
		return True, actual["definicion"]

	def _revertir_ruleset_actualizado(self, cliente, previo):
		"""La guarda 2: devuelve la definición anterior. NUNCA borra."""
		identidad = (previo or {}).get("id")
		anterior = (previo or {}).get("definicion")
		if not identidad or not anterior:
			raise UserError(_(
				"No se guardó la definición anterior de este ruleset, así que no hay a "
				"qué volver. No se borra para «dejarlo limpio»: el ruleset existía antes "
				"de esta operación."))
		# Segunda comprobación, con el nombre que tiene AHORA: entre leer y revertir pasó
		# una escritura, y pudo pasar cualquier otra cosa.
		self._exigir_ruleset_propio(previo.get("name"), _("al revertir"))

		full = self.repository_id.full_name
		if _definicion_comparable(cliente.get(
				"/repos/%s/rulesets/%s" % (full, identidad))) == anterior:
			# Ya está como estaba: escribir los mismos valores es una escritura que no
			# cambia nada y que igual queda en la auditoría de la organización.
			return True
		cliente.put("/repos/%s/rulesets/%s" % (full, identidad), anterior)
		return True

	# --- B5: el nacimiento gobernado -------------------------------------
	#
	# CREAR UN REPOSITORIO ES IRREVERSIBLE, Y ES UNA DECISIÓN, NO UNA LIMITACIÓN TÉCNICA.
	# GitHub tiene endpoint para borrar repositorios. **Este módulo no lo usa nunca.** Un
	# rollback que borra un repositorio puede llevarse trabajo que alguien empujó entre el
	# apply y la reversión, y no hay verificación previa que cierre esa ventana: entre que
	# se lee y se borra, cabe un push. El mockup dice «9 operaciones, todas reversibles» y
	# acá la realidad corrige al diseño hacia la honestidad — ocho lo son; ésta no, y se
	# muestra como lo que es, con el tipeo del nombre que el embudo exige para las
	# irreversibles.
	#
	# LO QUE SÍ SE PUEDE DESHACER se deshace: las ramas que creamos se borran, Dependabot
	# se apaga. El repositorio queda, vacío y sin gobierno, y eso es visible — que es
	# mejor que un borrado silencioso que nadie puede auditar después.

	def _leer_repositorio_a_crear(self, cliente):
		"""¿Ya existe un repositorio con ese nombre? El estado previo es esa respuesta."""
		datos = _cargar(self.payload_json) or {}
		nombre = datos.get("name")
		if not nombre:
			raise UserError(_("La operación no dice qué repositorio crear."))
		cuenta = self.plan_id.backend_id.owner_login
		existente = cliente.get(
			"/repos/%s/%s" % (cuenta, nombre), tolerar_404=True)
		return {
			"cuenta": cuenta,
			"nombre": nombre,
			"ya_existia": bool(existente),
			"id_existente": (existente or {}).get("id"),
		}

	def _crear_repositorio(self, cliente):
		"""Lo crea en la ORGANIZACIÓN. En una cuenta de usuario no se puede, y se dice.

		Un token de instalación de App no puede crear repositorios en una cuenta de
		usuario: no hay endpoint. `POST /user/repos` es del usuario autenticado, que no
		es la App. Así que el nacimiento gobernado espera la migración a organización, y
		negarse acá con el motivo es mejor que un 404 que nadie sabe leer.
		"""
		previo = self._leer_repositorio_a_crear(cliente)
		if previo["ya_existia"]:
			raise UserError(_(
				"«%(cuenta)s/%(nombre)s» ya existe. Crear no es idempotente: si ya está, "
				"lo que corresponde es gobernarlo, no volver a crearlo."
			) % {"cuenta": previo["cuenta"], "nombre": previo["nombre"]})
		if self.plan_id.backend_id.owner_type != "organization":
			raise UserError(_(
				"«%s» es una cuenta de usuario, y un token de App no puede crear "
				"repositorios ahí: GitHub no expone ese endpoint. El nacimiento "
				"gobernado espera la migración a organización."
			) % previo["cuenta"])

		datos = _cargar(self.payload_json) or {}
		return cliente.post("/orgs/%s/repos" % previo["cuenta"], {
			"name": previo["nombre"],
			"private": datos.get("private", True),
			"description": datos.get("description") or "",
			# CON README, y no es un adorno: un repositorio vacío no tiene rama por
			# defecto, y sin rama no hay dónde crear las demás ni qué proteger.
			"auto_init": True,
		})

	def _id_del_repositorio(self, resultado):
		"""El paso 2b, que acá hace DOS cosas y las dos son de identidad.

		Guarda el id que devolvió GitHub —sin eso, un apply que muera acá dejaría un
		repositorio nuevo del que Odoo no sabe nada— y, además, **le da destino al resto
		del plan**.

		POR QUÉ ES ACÁ Y NO AL ARMAR EL PLAN. Cuando el plan se arma, el repositorio no
		existe: las ramas, los rulesets y el grant se declaran sin `repository_id` porque
		no hay fila del espejo a la cual apuntar. Recién en este instante la hay. Sin este
		paso, las operaciones que siguen aplicarían sobre `repository_id` vacío y
		pedirían `/repos//git/refs` — una URL sin repositorio, que GitHub contesta con un
		404 que no explica nada.

		El espejo se escribe por el MISMO upsert que usa el sync: dos caminos que escriben
		el mismo objeto divergen, y el día del webhook habría tres.
		"""
		identidad = (resultado or {}).get("id")
		if not identidad:
			raise UserError(_(
				"GitHub no devolvió el id del repositorio creado. Sin identidad no se "
				"puede registrar qué se creó, y la operación no continúa."))

		# EL ESPEJO SE ESCRIBE EN LA TRANSACCIÓN PRINCIPAL, Y NO EN LA DURABLE. Lo
		# intenté al revés —el repositorio existe en GitHub, así que su fila «debería»
		# sobrevivir a un rollback— y el ensayo mostró por qué no se puede: **Odoo abre
		# sus transacciones en REPEATABLE READ**, de modo que una fila creada y
		# confirmada por otra conexión es INVISIBLE para la transacción en curso. El
		# apply enlazaba las operaciones a un id que no podía leer y todo lo que después
		# tocara ese campo moría con «Record does not exist».
		#
		# Lo que garantiza que no perdamos de vista un repositorio recién creado NO es la
		# fila del espejo: es la ENTRADA DE IDENTIDAD en la bitácora, que sí va por la
		# conexión durable y guarda el id que devolvió GitHub. Si el apply se cae, el
		# espejo lo vuelve a traer la próxima auditoría; la constancia de qué creamos ya
		# está escrita y es inmutable. El espejo es una copia; la bitácora es el registro.
		repo = self.env["repo.repository"]._upsert(self.plan_id.backend_id, resultado)
		# El resto del plan ya tiene a dónde apuntar. Sólo las que no lo tienen: una
		# operación que llegó con su repositorio puesto no se toca.
		hermanas = self.plan_id.operation_ids.filtered(
			lambda o: o.id != self.id and not o.repository_id)
		if hermanas:
			hermanas.write({"repository_id": repo.id})
		identidad_repo = repo.id
		_logger.info(
			"Repo Manager: repositorio %s creado y espejado (id de espejo %s)",
			resultado.get("full_name"), identidad_repo)
		return identidad

	def _verificar_repositorio_creado(self, cliente):
		previo = self._leer_repositorio_a_crear(cliente)
		if not previo["ya_existia"]:
			return False, _("el repositorio no aparece al releer")
		return True, {"id": previo["id_existente"], "nombre": previo["nombre"]}

	# --- ramas -----------------------------------------------------------

	def _leer_rama(self, cliente):
		datos = _cargar(self.payload_json) or {}
		nombre = self.target or datos.get("name")
		full = self.repository_id.full_name
		ref = cliente.get(
			"/repos/%s/git/ref/heads/%s" % (full, nombre), tolerar_404=True)
		# LA RAMA DE LA QUE NACE. En un repositorio recién creado el espejo puede no
		# tenerla todavía: la respuesta de creación de GitHub no siempre trae
		# `default_branch` con `auto_init`, porque la rama se materializa un instante
		# después. Se le pregunta a GitHub en vez de suponer «main» — suponerlo haría
		# nacer las cuatro ramas de un commit que quizá no es el que se cree.
		desde = datos.get("desde") or self.repository_id.default_branch
		if not desde:
			ficha = cliente.get("/repos/%s" % full, tolerar_404=True) or {}
			desde = ficha.get("default_branch")
			if desde and not self.repository_id.default_branch:
				self.repository_id.default_branch = desde
		origen = cliente.get(
			"/repos/%s/git/ref/heads/%s" % (full, desde), tolerar_404=True)
		return {
			"nombre": nombre,
			"ya_existia": bool(ref),
			"sha_actual": (ref or {}).get("object", {}).get("sha"),
			"desde": desde,
			"sha_origen": (origen or {}).get("object", {}).get("sha"),
		}

	def _crear_rama(self, cliente):
		previo = self._leer_rama(cliente)
		if previo["ya_existia"]:
			return SIN_CAMBIOS
		if not previo["sha_origen"]:
			raise UserError(_(
				"No se encontró la rama «%(desde)s» de la que nace «%(nombre)s»."
			) % {"desde": previo["desde"], "nombre": previo["nombre"]})
		return cliente.post("/repos/%s/git/refs" % self.repository_id.full_name, {
			"ref": "refs/heads/%s" % previo["nombre"],
			"sha": previo["sha_origen"],
		})

	def _verificar_rama_creada(self, cliente):
		actual = self._leer_rama(cliente)
		if not actual["ya_existia"]:
			return False, _("la rama no aparece al releer")
		return True, {"rama": actual["nombre"], "sha": actual["sha_actual"]}

	def _revertir_rama_creada(self, cliente, previo):
		"""Borra la rama SÓLO si el estado previo dice que no existía.

		Si ya estaba antes de que llegáramos, no es nuestra y no se toca — la misma
		regla del ruleset ajeno y del CODEOWNERS ajeno, aplicada a una ref.
		"""
		if (previo or {}).get("ya_existia"):
			return True
		nombre = (previo or {}).get("nombre")
		if not nombre:
			raise UserError(_(
				"No se guardó qué rama se creó: no se borra ninguna por las dudas."))
		cliente.delete(
			"/repos/%s/git/refs/heads/%s" % (self.repository_id.full_name, nombre),
			tolerar_404=True)
		return True

	# --- la rama por defecto ---------------------------------------------

	def _leer_rama_por_defecto(self, cliente):
		ficha = cliente.get("/repos/%s" % self.repository_id.full_name) or {}
		return {"anterior": ficha.get("default_branch")}

	def _fijar_rama_por_defecto(self, cliente):
		deseada = (_cargar(self.payload_json) or {}).get("branch") or self.target
		if self._leer_rama_por_defecto(cliente)["anterior"] == deseada:
			return SIN_CAMBIOS
		return cliente.patch("/repos/%s" % self.repository_id.full_name,
							 {"default_branch": deseada})

	def _verificar_rama_por_defecto(self, cliente):
		deseada = (_cargar(self.payload_json) or {}).get("branch") or self.target
		actual = self._leer_rama_por_defecto(cliente)["anterior"]
		if actual != deseada:
			return False, _("la rama por defecto quedó en «%s»") % actual
		return True, {"default_branch": actual}

	def _revertir_rama_por_defecto(self, cliente, previo):
		anterior = (previo or {}).get("anterior")
		if not anterior:
			raise UserError(_(
				"No se guardó cuál era la rama por defecto: no se adivina."))
		cliente.patch("/repos/%s" % self.repository_id.full_name,
					  {"default_branch": anterior})
		return True

	# --- Dependabot -------------------------------------------------------

	def _leer_dependabot(self, cliente):
		"""El endpoint contesta 204 si está encendido y 404 si no. Nada de cuerpo.

		Fue el que destapó que `get` trataba un 204 como error de parseo, y por eso acá
		se comprueba con una excepción y no con el contenido.
		"""
		full = self.repository_id.full_name
		try:
			cliente.get("/repos/%s/vulnerability-alerts" % full)
			return {"encendido": True}
		except (GithubNotFound, GithubFeatureDisabled):
			# LAS DOS SON «apagado». El 404 puede venir con «Not Found» o con un mensaje
			# que dice «disabled», y desde B6 el segundo levanta `GithubFeatureDisabled`.
			# Atrapar sólo uno hacía fallar el paso previo del ciclo sobre un repositorio
			# recién creado, que es justo donde Dependabot siempre está apagado.
			return {"encendido": False}

	def _encender_dependabot(self, cliente):
		if self._leer_dependabot(cliente)["encendido"]:
			return SIN_CAMBIOS
		return cliente.put(
			"/repos/%s/vulnerability-alerts" % self.repository_id.full_name)

	def _verificar_dependabot(self, cliente):
		if not self._leer_dependabot(cliente)["encendido"]:
			return False, _("Dependabot sigue apagado al releer")
		return True, {"encendido": True}

	def _revertir_dependabot(self, cliente, previo):
		"""Lo apaga sólo si estaba apagado antes. Si ya estaba encendido, no era nuestro."""
		if (previo or {}).get("encendido"):
			return True
		cliente.delete(
			"/repos/%s/vulnerability-alerts" % self.repository_id.full_name,
			tolerar_404=True)
		return True

	# --- CODEOWNERS: el archivo que NO admite coexistencia ---------------
	#
	# CUATRO ESTADOS, Y CADA UNO TIENE UNA RESPUESTA DISTINTA. Con los rulesets alcanzaba
	# con «nuestro / ajeno» porque en un repositorio conviven muchos; acá el archivo es UNO
	# y el que está tapa a cualquier otro.
	#
	#   ausente   → no hay ninguno: se escribe.
	#   ajeno     → existe y NO lleva nuestra marca: NO SE PISA JAMÁS. El plan se niega.
	#   editado   → lleva nuestra marca y el contenido NO es el que la bitácora dice que
	#               escribimos: es DRIFT DE ARCHIVO. Se detecta, se muestra la diferencia,
	#               y sobrescribir exige que quien aprueba vea qué ediciones manuales se
	#               pierden. Pisar en silencio la línea que alguien agregó a mano es el
	#               mismo daño que pisar el archivo entero de otro, servido en cuotas.
	#   nuestro   → lleva la marca y coincide con lo aplicado: no se escribe nada.
	#
	# Y SE MIRAN LAS TRES UBICACIONES. GitHub busca CODEOWNERS en `.github/`, en la raíz y
	# en `docs/`, y usa **la primera que encuentra**. Escribir el nuestro en la raíz
	# mientras hay uno ajeno en `.github/` no falla: aplica, verifica bien, y no gobierna
	# nada — el de `.github/` sigue mandando. Es la misma familia del owner que GitHub
	# ignora: no falla al escribirse, falla en silencio después.

	UBICACIONES_CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")

	# --- E3.2 · borrar una rama -------------------------------------------

	def _leer_rama_a_borrar(self, cliente):
		"""EL PUNTO DE RETORNO: en qué commit está la rama AHORA.

		No se usa el SHA que traía el hallazgo. Entre que se armó el plan y se aplica,
		alguien pudo haber empujado a esa rama —y si lo hizo, la rama ya no está
		integrada y borrarla perdería ese commit—. La verificación de que sigue
		integrada la hace `_borrar_rama`; acá se registra dónde estaba.
		"""
		rama = self._rama_objetivo()
		try:
			ref = cliente.get("/repos/%s/git/ref/heads/%s" % (
				self.repository_id.full_name, rama))
		except GithubNotFound:
			# QUE NO ESTÉ ES UN ESTADO VÁLIDO, no un error. El rollback llama a este
			# mismo método para saber «qué hay ahora» ANTES de restaurar, y para entonces
			# la rama está borrada — que es el punto. Levantar acá haría que revertir un
			# borrado exitoso fuera imposible.
			return {"anterior": {"sha": None, "rama": rama, "existe": False}}
		return {"anterior": {"sha": (ref.get("object") or {}).get("sha"),
							 "rama": rama, "existe": True}}

	def _borrar_rama(self, cliente):
		"""Borra la ref. Antes vuelve a comprobar que siga integrada.

		LA COMPROBACIÓN NO ES REDUNDANTE. El hallazgo dijo «integrada» cuando corrió la
		auditoría; entre eso y el apply pueden pasar días. Un push a esa rama la vuelve
		«con trabajo sin integrar», que es justamente la que este módulo no borra nunca.
		Sin esta relectura, el embudo terminaría haciendo lo que el motor se niega a
		proponer.
		"""
		datos = _cargar(self.payload_json) or {}
		contra = datos.get("integrated_into")
		rama = self._rama_objetivo()
		if contra:
			comparacion = cliente.get("/repos/%s/compare/%s...%s" % (
				self.repository_id.full_name, contra, rama)) or {}
			adelante = comparacion.get("ahead_by") or 0
			if adelante:
				raise UserError(_(
					"«%(rama)s» ya no está integrada a «%(contra)s»: tiene %(n)s commit(s) "
					"propio(s) que no están del otro lado. Alguien empujó a esa rama "
					"después de la auditoría. NO se borra."
				) % {"rama": rama, "contra": contra, "n": adelante})
		cliente.delete("/repos/%s/git/refs/heads/%s" % (
			self.repository_id.full_name, rama))
		# El punto de retorno NO se copia acá. Lo escribe el paso 4 en la bitácora, que
		# es de donde sale el rollback: si viviera además en el resultado habría dos
		# copias del mismo dato y la de la bitácora dejaría de ser la fuente.
		return {"borrada": rama}

	def _verificar_rama_borrada(self, cliente):
		"""Releer es el paso 3: que la escritura no haya devuelto error no alcanza."""
		try:
			cliente.get("/repos/%s/git/ref/heads/%s" % (
				self.repository_id.full_name, self._rama_objetivo()))
		except GithubNotFound:
			return True, {"branch": self._rama_objetivo(), "deleted": True}
		return False, _("la rama «%s» sigue existiendo") % self._rama_objetivo()

	def _recrear_rama(self, cliente, previo):
		"""La vuelta: la ref otra vez en EL MISMO commit que tenía.

		Si el SHA no está registrado no se inventa uno: recrear la rama en otro commit
		sería peor que no recrearla, porque dejaría algo con el nombre correcto y el
		contenido equivocado — y nadie lo miraría dos veces.
		"""
		sha = (previo or {}).get("anterior", {}).get("sha")
		if not sha:
			raise UserError(_(
				"No hay punto de retorno registrado para «%s»: sin el commit original no "
				"se recrea la rama. Recrearla en otro commit sería dejar el nombre "
				"correcto con el contenido equivocado.") % self._rama_objetivo())
		cliente.post("/repos/%s/git/refs" % self.repository_id.full_name,
					 {"ref": "refs/heads/%s" % self._rama_objetivo(), "sha": sha})
		return {"recreada": self._rama_objetivo(), "sha": sha}

	def _rama_objetivo(self):
		datos = _cargar(self.payload_json) or {}
		return datos.get("branch") or self.target

	def _leer_codeowners(self, cliente):
		"""Estado previo: qué CODEOWNERS hay hoy, dónde, y de quién es."""
		full = self.repository_id.full_name
		rama = self._rama_de_destino()
		encontrados = []
		for ruta in self.UBICACIONES_CODEOWNERS:
			datos = cliente.get(
				"/repos/%s/contents/%s" % (full, ruta),
				params={"ref": rama}, tolerar_404=True)
			if not datos:
				continue
			contenido = base64.b64decode(datos.get("content") or "").decode(
				"utf-8", "replace")
			encontrados.append({
				"ruta": ruta, "sha": datos.get("sha"), "contenido": contenido,
				"es_nuestro": contenido.startswith(MARCA_CODEOWNERS),
			})

		# El que manda es el PRIMERO de la lista de precedencia de GitHub.
		vigente = encontrados[0] if encontrados else None
		return {
			"rama": rama,
			"vigente": vigente,
			"todos": encontrados,
			"estado": self._estado_de_codeowners(vigente),
		}

	def _estado_de_codeowners(self, vigente):
		if not vigente:
			return "ausente"
		if not vigente["es_nuestro"]:
			return "ajeno"
		if vigente["contenido"] != (self._ultimo_codeowners_aplicado() or
									vigente["contenido"]):
			return "editado"
		return "nuestro"

	def _ultimo_codeowners_aplicado(self):
		"""Lo que la bitácora dice que escribimos la última vez. La misma referencia
		inmutable que usa el drift de rulesets: si viviera en el plan, quien edita el
		plan movería la vara del desvío."""
		self.ensure_one()
		entradas = self.env["repo.audit.log"].search([
			("repository_id", "=", self.repository_id.id),
			("event_type", "=", "write_applied"),
		], order="id desc")
		for entrada in entradas:
			datos = entrada._payload() or {}
			if datos.get("kind") == "codeowners_write":
				return (datos.get("payload") or {}).get("contenido")
		return None

	def _escribir_codeowners(self, cliente):
		"""Commitea el archivo. Se niega sobre uno ajeno y sobre uno editado sin ver."""
		previo = self._leer_codeowners(cliente)
		deseado = (_cargar(self.payload_json) or {}).get("contenido")
		if not deseado:
			raise UserError(_("La operación no trae contenido para el CODEOWNERS."))

		if previo["estado"] == "ajeno":
			raise UserError(_(
				"«%(repo)s» ya tiene un CODEOWNERS en «%(ruta)s» que no puso este "
				"módulo, y el archivo es uno solo: escribirlo reemplazaría la lista de "
				"revisores de otro. No se pisa."
			) % {"repo": self.repository_id.full_name,
				 "ruta": previo["vigente"]["ruta"]})

		if previo["estado"] == "editado" and not self._confirmo_perder_ediciones():
			raise UserError(_(
				"El CODEOWNERS de «%s» lo escribimos nosotros pero fue editado a mano "
				"después. Sobrescribirlo pierde esas ediciones, y quien aprueba tiene "
				"que verlas antes: el plan trae la diferencia para eso."
			) % self.repository_id.full_name)

		if previo["estado"] == "nuestro" and previo["vigente"]["contenido"] == deseado:
			return SIN_CAMBIOS

		ruta = previo["vigente"]["ruta"] if previo["vigente"] else \
			self.UBICACIONES_CODEOWNERS[0]
		cuerpo = {
			"message": "[IMP] CODEOWNERS generado por Primate Repo Manager",
			"content": base64.b64encode(deseado.encode()).decode(),
			"branch": previo["rama"],
		}
		if previo["vigente"]:
			cuerpo["sha"] = previo["vigente"]["sha"]
		return cliente.put(
			"/repos/%s/contents/%s" % (self.repository_id.full_name, ruta), cuerpo)

	def _confirmo_perder_ediciones(self):
		"""¿Quien aprobó vio qué ediciones manuales se pierden?

		LA CONFIRMACIÓN VIAJA EN EL PAYLOAD, Y ESO NO ES UN DETALLE DE IMPLEMENTACIÓN.
		El payload entra en la huella que congela el plan al aprobarlo, así que «sí,
		descarto estas ediciones» queda dentro de lo que se aprobó, con la diferencia al
		lado. Una bandera fuera de la huella se podría prender después de aprobar, y
		aprobar habría sido firmar un cheque en blanco sobre el trabajo de otro.

		Y SE EXIGEN LAS DOS COSAS: la decisión y la diferencia que la fundamenta. Sin el
		texto de lo que se pierde, la confirmación se podría marcar sin haber mirado
		nada — que es exactamente lo que esta guarda existe para impedir.
		"""
		self.ensure_one()
		payload = _cargar(self.payload_json) or {}
		return bool(payload.get("perder_ediciones")
					and payload.get("ediciones_perdidas"))

	def _verificar_codeowners(self, cliente):
		"""Relee el archivo y compara BYTE A BYTE. Lo que devolvió el PUT no cuenta."""
		deseado = (_cargar(self.payload_json) or {}).get("contenido")
		actual = self._leer_codeowners(cliente)
		if not actual["vigente"]:
			return False, _("el archivo no aparece al releer")
		if actual["vigente"]["contenido"] != deseado:
			return False, _("el contenido releído no es byte a byte el que se escribió")
		return True, {"ruta": actual["vigente"]["ruta"]}

	def _revertir_codeowners(self, cliente, previo):
		"""Devuelve el archivo anterior. Si antes no había, borra el que creamos."""
		full = self.repository_id.full_name
		actual = self._leer_codeowners(cliente)
		if not actual["vigente"]:
			return True
		ruta = actual["vigente"]["ruta"]
		anterior = (previo or {}).get("vigente")
		if not anterior:
			# No había ninguno: lo creamos nosotros y se saca. Es la única baja de
			# contenido de esta operación, y sólo ocurre sobre un archivo que no existía
			# antes de que llegáramos.
			cliente.delete("/repos/%s/contents/%s" % (full, ruta), {
				"message": "[REM] se revierte el CODEOWNERS que este módulo creó",
				"sha": actual["vigente"]["sha"],
				"branch": (previo or {}).get("rama"),
			})
			return True
		cliente.put("/repos/%s/contents/%s" % (full, anterior["ruta"]), {
			"message": "[REV] se restaura el CODEOWNERS anterior",
			"content": base64.b64encode(anterior["contenido"].encode()).decode(),
			"sha": actual["vigente"]["sha"],
			"branch": (previo or {}).get("rama"),
		})
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

	# --- membresía de team ------------------------------------------------
	#
	# QUÉ SIGNIFICA «CERO ACCESOS» EN UN OFFBOARDING, que no es lo que parece.
	#
	# Después de quitar todos los grants directos y sacar a la persona de sus teams, el
	# permiso EFECTIVO que devuelve GitHub sobre un repositorio PÚBLICO sigue siendo
	# `read`. No es un acceso que le quedó: es la visibilidad del repositorio, y ninguna
	# operación de permisos la puede quitar — sólo hacerlo privado, o sacar a la persona
	# de la organización.
	#
	# Por eso la métrica del offboarding es CERO ACCESOS CONCEDIDOS, y se comprueba en
	# tres lecturas separadas, no en el efectivo:
	#
	#   · sin entrada en `/collaborators?affiliation=direct`
	#   · sin membresía en ningún team con acceso al repositorio
	#   · sobre los repositorios PRIVADOS, sin acceso de ninguna clase
	#
	# Medirlo por el permiso efectivo da un falso negativo garantizado en cuanto haya un
	# repositorio público, y llevaría a concluir que el offboarding falló cuando salió
	# bien. Verificado contra el sandbox el 2-sep-2026.
	#
	# Hace falta para un offboarding honesto: quitar los grants directos de alguien no lo
	# saca de sus teams, y por el team puede seguir entrando a todo. Es idempotente por
	# destino —la persona y el team ya existen— así que va con el ciclo de cuatro pasos.
	#
	# El estado previo guarda el ROL además de la pertenencia: quien era `maintainer` del
	# team no puede volver como `member`, que sería devolverle menos de lo que tenía y
	# dar el rollback por bueno.

	def _ruta_membresia(self):
		return "/orgs/%s/teams/%s/memberships/%s" % (
			self.plan_id.backend_id.owner_login, self.target,
			(_cargar(self.payload_json) or {}).get("login"))

	def _leer_membresia(self, cliente):
		datos = cliente.get(self._ruta_membresia(), tolerar_404=True)
		if not datos:
			return {"miembro": False, "rol": None, "estado": None}
		return {"miembro": True, "rol": datos.get("role"),
				"estado": datos.get("state")}

	def _sacar_del_team(self, cliente):
		return cliente.delete(self._ruta_membresia(), tolerar_404=True)

	def _poner_en_el_team(self, cliente):
		rol = (_cargar(self.payload_json) or {}).get("role", "member")
		return cliente.put(self._ruta_membresia(), {"role": rol})

	def _verificar_sin_membresia(self, cliente):
		estado = self._leer_membresia(cliente)
		if estado["miembro"]:
			return False, _("sigue en el team con rol %s") % estado["rol"]
		return True, estado

	def _verificar_membresia(self, cliente):
		estado = self._leer_membresia(cliente)
		rol = (_cargar(self.payload_json) or {}).get("role", "member")
		if not estado["miembro"] or estado["rol"] != rol:
			return False, _("quedó como %s y se pidió %s") % (
				estado["rol"] or "no miembro", rol)
		return True, estado

	def _revertir_membresia(self, cliente, previo):
		if previo.get("miembro"):
			cliente.put(self._ruta_membresia(), {"role": previo.get("rol") or "member"})
		else:
			cliente.delete(self._ruta_membresia(), tolerar_404=True)
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
