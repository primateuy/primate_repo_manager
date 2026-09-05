# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Bitácora inmutable de todo lo que el módulo hace sobre GitHub.

LA INMUTABILIDAD ES DEL MODELO, NO DE LOS PERMISOS. `write()` y `unlink()` levantan
excepción SIEMPRE, incluso con `sudo()`. Los ACL son la segunda capa, no la primera.

El motivo es simple: un ACL protege del usuario, no del código. Cualquier método del
módulo —o de otro addon— que haga `.sudo().write(...)` pasa por encima de los permisos
sin que nada se entere. Una bitácora que un `sudo()` puede reescribir no es una bitácora:
es una tabla de notas que además da una falsa sensación de rastro.

LAS ENTRADAS SOBREVIVEN AL BORRADO DE LO QUE DESCRIBEN. Los enlaces a repositorio, backend
y persona son `ondelete="set null"`, y el nombre de cada uno se guarda ADEMÁS como texto
al crear la entrada. Con `ondelete="cascade"` habría un camino silencioso de destrucción:
Postgres borra en cascada a nivel base de datos, sin pasar por `unlink()`, así que borrar
un repositorio se llevaría puesta su bitácora sin que la guarda de inmutabilidad llegara
a enterarse. Verificado con un test.
"""
import hashlib
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EVENT_TYPES = [
	# Los de la spec §4.4.
	("apply_policy", "Aplicación de política"),
	("grant", "Alta de permiso"),
	("revoke", "Baja de permiso"),
	("promotion", "Promoción entre ramas"),
	("bypass_detected", "Bypass detectado"),
	("drift_detected", "Drift detectado"),
	("drift_resolved", "Drift resuelto"),
	("sync", "Sincronización"),
	("offboarding", "Offboarding"),
	("signing_change", "Cambio en la firma de commits"),
	# Los que agrega el ciclo plan -> aprobación -> apply de F2.
	("write_applied", "Escritura aplicada"),
	("write_failed", "Escritura fallida"),
	# Distinto de fallida a propósito: un techo de plan no es un error del sistema.
	("write_blocked", "Escritura bloqueada por el plan de GitHub"),
	# Paso 2b de las operaciones que crean identidad: el id que devolvió GitHub, guardado
	# antes de verificar nada. Ver la taxonomía en repo_write_apply.
	("write_identity", "Identidad creada, registrada antes de verificar"),
	("write_rolled_back", "Escritura revertida"),
	# Cambiar la política es la escritura más silenciosa de todas: no toca un solo
	# repositorio y sin embargo redefine qué cuenta como incumplimiento para todos los de
	# esa clasificación, en todas las auditorías que vengan. El chatter no alcanza —es
	# editable y se va con el registro—; el mismo argumento que hizo inmutable esta
	# bitácora para las escrituras a GitHub vale más acá, no menos.
	("policy_changed", "Cambio de política"),
	# A7: habilitar la escritura sobre producción es la decisión previa a cualquier
	# escritura, y la única que hoy no dejaba rastro de ningún tipo.
	("write_enabled", "Escritura habilitada"),
	("write_disabled", "Escritura deshabilitada"),
	# El eslabón cero de la cadena de hashes. Ver `_sellar`.
	("chain_genesis", "Inicio de la cadena de integridad"),
]

# LOS CUATRO TIPOS DE ENTRADA QUE LA PANTALLA DISTINGUE, del sistema de diseño.
#
# No es una clasificación decorativa: cada uno se lee distinto. Una escritura verificada se
# puede revertir; una irreversible o fallida no; una lectura no cambió nada y está para
# saber qué se miró y cuándo; y un cambio detectado fuera de la app es alguien que tocó
# GitHub por afuera, que es el caso que más importa y el único que el módulo no causó.
CLASES_DE_ENTRADA = [
	("escritura", "Escritura verificada, se puede revertir"),
	("irreversible", "Irreversible, o falló"),
	("lectura", "Lectura (auditoría), no cambia nada"),
	("externo", "Cambio detectado fuera de la app"),
]

CLASE_POR_EVENTO = {
	"write_applied": "escritura",
	"grant": "escritura",
	"revoke": "escritura",
	"promotion": "escritura",
	"apply_policy": "escritura",
	"write_rolled_back": "escritura",
	"offboarding": "escritura",
	# Irreversible o fallida: lo que no tiene vuelta atrás por el mismo camino.
	"write_failed": "irreversible",
	"write_blocked": "irreversible",
	"write_identity": "irreversible",
	# Lecturas y decisiones que no tocan GitHub.
	"sync": "lectura",
	"policy_changed": "lectura",
	"write_enabled": "lectura",
	"write_disabled": "lectura",
	"signing_change": "lectura",
	"chain_genesis": "lectura",
	# Lo que pasó afuera. `drift_detected` es el caso de hoy; B4 va a sumar los suyos.
	"drift_detected": "externo",
	"drift_resolved": "externo",
	"bypass_detected": "externo",
}


class RepoAuditLog(models.Model):
	_name = "repo.audit.log"
	_description = "Bitácora inmutable de operaciones sobre GitHub"
	_order = "id desc"

	timestamp = fields.Datetime(
		string="Momento", required=True, default=fields.Datetime.now, index=True)
	event_type = fields.Selection(
		EVENT_TYPES, string="Evento", required=True, index=True)

	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", ondelete="set null", index=True)
	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", ondelete="set null", index=True)
	member_id = fields.Many2one(
		"repo.member", string="Persona", ondelete="set null", index=True)

	# Copias en texto: lo que hace que la entrada siga contando la historia aunque el
	# registro enlazado ya no exista.
	repository_name = fields.Char(string="Repositorio (texto)")
	member_login = fields.Char(string="Persona (texto)")

	user_id = fields.Many2one(
		"res.users", string="Ejecutado por", default=lambda s: s.env.user,
		ondelete="set null", index=True,
		help="Quién lo disparó desde Odoo. Distinto de la persona de GitHub afectada.")

	summary = fields.Char(string="Resumen", required=True)
	payload_json = fields.Text(string="Detalle (JSON)")
	# El estado ANTES de la escritura. Es lo que hace posible el rollback, y por eso vive
	# en la bitácora inmutable y no en el plan: si viviera en el plan, quien pueda editar
	# el plan podría reescribir el punto de retorno.
	previous_state_json = fields.Text(string="Estado previo (JSON)")

	entry_class = fields.Selection(
		CLASES_DE_ENTRADA, string="Tipo de entrada", compute="_compute_entry_class",
		store=True, index=True,
		help="Los cuatro tipos que la pantalla distingue. Cada uno se lee distinto: uno "
			 "se puede revertir, otro no, otro no cambió nada, y el último no lo hizo "
			 "esta aplicación.")

	# --- cadena de integridad --------------------------------------------
	#
	# POR QUÉ NO ALCANZA CON LA INMUTABILIDAD QUE YA TENÍAMOS. `write` y `unlink` levantan
	# excepción siempre, incluso con `sudo()`, y eso protege del CÓDIGO: ningún método de
	# este módulo ni de otro addon puede reescribir una entrada. No protege de un `UPDATE`
	# directo en Postgres, que es otra cosa y necesita otra defensa.
	#
	# La cadena no lo impide —nada dentro de Odoo puede impedirlo— pero lo hace
	# DETECTABLE: cada entrada guarda el hash de la anterior, así que tocar una rompe todas
	# las que siguen y el diagnóstico lo dice.
	previous_hash = fields.Char(
		string="Hash de la anterior", readonly=True, copy=False, index=True)
	entry_hash = fields.Char(
		string="Hash de esta entrada", readonly=True, copy=False, index=True)

	# ------------------------------------------------------------------
	# Inmutabilidad
	# ------------------------------------------------------------------

	@api.depends("event_type")
	def _compute_entry_class(self):
		for entrada in self:
			entrada.entry_class = CLASE_POR_EVENTO.get(entrada.event_type, "lectura")

	# ------------------------------------------------------------------
	# Cadena de integridad
	# ------------------------------------------------------------------

	# Los campos que entran en el hash: todo lo que la entrada AFIRMA. Los que no están
	# —`entry_class`, que se deriva del tipo— no agregan información y meterlos haría que
	# un cambio de código en la clasificación rompiera cadenas viejas sin que nadie tocara
	# nada.
	#
	# CAMBIAR ESTA LISTA INVALIDA TODAS LAS CADENAS EXISTENTES, y hay que aceptarlo de
	# frente: los sellos viejos se calcularon sobre otro conjunto de campos, así que al
	# recalcularlos no van a coincidir y el diagnóstico va a decir «rota» sin que nadie
	# haya tocado la base. Se comprobó sin querer, mutando la lista para probar los tests.
	#
	# Si alguna vez hay que cambiarla, el camino honesto es el mismo que se eligió para
	# arrancar: una entrada de génesis nueva que declare desde cuándo vale el sello nuevo.
	# Recalcular los viejos en silencio sería, otra vez, fabricar confianza.
	CAMPOS_SELLADOS = (
		"timestamp", "event_type", "summary", "repository_name", "member_login",
		"payload_json", "previous_state_json", "user_id",
	)

	@api.model_create_multi
	def create(self, vals_list):
		"""Cada entrada se sella con el hash de la anterior, en orden y una por una.

		POR QUÉ DE A UNA Y NO EN LOTE. La cadena es, literalmente, una cadena: el eslabón
		N necesita el hash del N-1 ya calculado. Crearlas juntas y sellarlas después
		dejaría una ventana en la que existen entradas sin sello, y una entrada sin sello
		es un agujero por donde se puede insertar otra sin que se note.
		"""
		entradas = self.browse()
		for valores in vals_list:
			entrada = super().create([valores])
			entrada._sellar()
			entradas |= entrada
		return entradas

	def _sellar(self):
		"""Calcula y guarda el hash de esta entrada, encadenado con el de la anterior.

		Escribe por SQL directo y no con `write`, y no es una trampa: `write` está
		prohibido a propósito en este modelo y esta es la única excepción, acotada a los
		dos campos del sello y en el momento del alta. Hacerlo por el ORM obligaría a
		abrirle una puerta a `write`, y esa puerta después la usa cualquiera.
		"""
		self.ensure_one()
		anterior = self.search([("id", "<", self.id)], order="id desc", limit=1)
		previo = anterior.entry_hash or ""
		cuerpo = json.dumps(
			{c: str(self[c].id if c == "user_id" else self[c] or "")
			 for c in self.CAMPOS_SELLADOS},
			sort_keys=True, separators=(",", ":"))
		sello = hashlib.sha256(("%s|%s" % (previo, cuerpo)).encode()).hexdigest()
		self.env.cr.execute(
			"UPDATE repo_audit_log SET previous_hash = %s, entry_hash = %s WHERE id = %s",
			(previo or None, sello, self.id))
		self.invalidate_recordset(["previous_hash", "entry_hash"])
		return sello

	def _recalcular_sello(self):
		"""El hash que la entrada DEBERÍA tener, según lo que dice hoy."""
		self.ensure_one()
		cuerpo = json.dumps(
			{c: str(self[c].id if c == "user_id" else self[c] or "")
			 for c in self.CAMPOS_SELLADOS},
			sort_keys=True, separators=(",", ":"))
		return hashlib.sha256(
			("%s|%s" % (self.previous_hash or "", cuerpo)).encode()).hexdigest()

	@api.model
	def verificar_cadena(self):
		"""Recorre la cadena y devuelve dónde se rompe, si se rompe.

		Devuelve `{"estado": ok|rota|vacia, "desde": fecha, "entrada": id, "motivo": ...}`.

		Dos formas de romperse, y se distinguen porque significan cosas distintas:
		· **contenido**: la entrada dice algo distinto de lo que decía cuando se selló.
		· **eslabón**: el `previous_hash` no coincide con el sello de la anterior, o sea
		  que alguien borró o insertó una entrada en el medio.
		"""
		entradas = self.search([("entry_hash", "!=", False)], order="id")
		if not entradas:
			return {"estado": "vacia"}
		anterior = None
		for entrada in entradas:
			if entrada._recalcular_sello() != entrada.entry_hash:
				return {"estado": "rota", "entrada": entrada.id,
						"momento": entrada.timestamp,
						"motivo": _("el contenido de la entrada cambió desde que se selló")}
			esperado = anterior.entry_hash if anterior else ""
			if (entrada.previous_hash or "") != esperado:
				return {"estado": "rota", "entrada": entrada.id,
						"momento": entrada.timestamp,
						"motivo": _("falta una entrada anterior, o se insertó una")}
			anterior = entrada
		return {"estado": "ok", "desde": entradas[0].timestamp,
				"entradas": len(entradas)}

	def init(self):
		"""La entrada cero se asegura en cada actualización del módulo, no sólo al instalar.

		`post_init_hook` fue el primer intento y no alcanza: corre SÓLO en la instalación,
		y en una base donde el módulo ya estaba —que es el caso real, y el único que
		importa acá porque es el que tiene entradas viejas sin encadenar— nunca se ejecuta.
		`init()` corre en cada `-u`, que es cuando la cadena empieza a existir de verdad.
		"""
		super().init()
		self.asegurar_genesis()

	@api.model
	def asegurar_genesis(self):
		"""La entrada cero, que dice que lo anterior NO está encadenado.

		Se decidió no sembrar la cadena sobre las entradas viejas, y el motivo vale más
		que la comodidad: una cadena que «verificara» un pasado que nadie encadenó estaría
		fabricando confianza, que es exactamente lo contrario de para lo que existe. Lo
		honesto es decir desde cuándo hay garantía y desde cuándo no.
		"""
		if self.search_count([("event_type", "=", "chain_genesis")]):
			return self.browse()
		viejas = self.search_count([])
		return self.sudo().create({
			"event_type": "chain_genesis",
			"summary": _(
				"Inicio de la cadena de integridad. Las %s entradas anteriores a este "
				"momento NO están encadenadas: existen y son inmutables a nivel modelo, "
				"pero su integridad no se puede verificar hacia atrás.") % viejas,
			"payload_json": json.dumps({"entradas_previas": viejas}),
		})

	def write(self, vals):
		raise UserError(_(
			"La bitácora de auditoría no se modifica.\n\n"
			"Si el registro quedó mal, la corrección es una entrada NUEVA que lo explique, "
			"no la edición de la vieja: el valor de una bitácora es que lo escrito ahí no "
			"cambia después."))

	def unlink(self):
		raise UserError(_(
			"La bitácora de auditoría no se borra.\n\n"
			"Las entradas son el rastro de lo que el sistema hizo sobre GitHub, incluida "
			"la información de estado previo que permite revertir. Borrarlas dejaría "
			"operaciones aplicadas sin punto de retorno."))

	# ------------------------------------------------------------------
	# Alta
	# ------------------------------------------------------------------

	@api.model
	def registrar(self, event_type, summary, *, backend=None, repository=None,
				  member=None, payload=None, previous_state=None, extra=None):
		"""Única forma prevista de escribir en la bitácora.

		Rellena las copias en texto en el momento del alta, que es cuando los registros
		enlazados todavía existen.

		`extra` existe porque la entrada se escribe UNA VEZ y completa: como `write()`
		está prohibido, un campo que agregue otra capa —el enlace a la operación de
		escritura, por ejemplo— no se puede setear después. Se pasa acá o no se pasa.
		"""
		valores = {
			"event_type": event_type,
			"summary": summary[:255] if summary else "",
			"backend_id": backend.id if backend else False,
			"repository_id": repository.id if repository else False,
			"repository_name": repository.full_name if repository else False,
			"member_id": member.id if member else False,
			"member_login": member.github_login if member else False,
			"payload_json": json.dumps(payload, default=str) if payload else False,
			"previous_state_json": (
				json.dumps(previous_state, default=str) if previous_state else False),
		}
		valores.update(extra or {})
		return self.sudo().create(valores)

	def _compute_display_name(self):
		etiquetas = dict(EVENT_TYPES)
		for entrada in self:
			entrada.display_name = "[%s] %s" % (
				etiquetas.get(entrada.event_type, entrada.event_type), entrada.summary)
