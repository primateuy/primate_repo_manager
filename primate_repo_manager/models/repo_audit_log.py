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
	# La escritura SALIÓ y todavía no se verificó. Es el hecho que hace admisible una
	# reversión aunque la operación termine marcada como fallida. Ver `_persistir_emision`.
	("write_emitted", "Escritura emitida, sin verificar todavía"),
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
	"write_emitted": "escritura",
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
	# EL ORDEN DE LA CADENA ES EL ORDEN EN QUE SE SELLÓ, NO EL DE LOS IDS.
	#
	# Parece un detalle y es la corrección entera. Los ids salen de una secuencia, que los
	# entrega cuando la fila se INSERTA; el sello, en cambio, se pone después de que la
	# transacción confirma. Dos transacciones que empiezan en distinto orden y terminan al
	# revés producirían ids en un orden y sellos en el otro, y una cadena verificada por id
	# diría «rota» sin que nadie tocara nada.
	#
	# Con un contador propio, la cadena se lee en el orden en que realmente se encadenó,
	# que es el único que el hash respeta.
	chain_seq = fields.Integer(
		string="Posición en la cadena", readonly=True, copy=False, index=True)

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
		"""Crea las entradas SIN sello y pide que se sellen apenas la transacción confirme.

		POR QUÉ NO SE SELLA ACÁ, QUE ES LO QUE HACÍA ANTES. Sellar al crear supone que hay
		un solo escritor. Dejó de haberlo el día que la constancia de escritura pasó a
		escribirse en una conexión aparte —para que sobreviva a una caída, que es
		correcto—: esa conexión confirma su entrada mientras la transacción principal
		mantiene una foto anterior de la base, en la que esa entrada NO EXISTE. Las dos
		sellan contra la misma punta y la cadena se bifurca.

		No es hipotético: pasó en la corrida del 5 de septiembre de 2026 y dejó tres
		bifurcaciones. El diagnóstico dijo «rota», y tenía razón — sólo que el culpable
		era el propio módulo, no un `UPDATE` de nadie.

		La confirmación es el único momento en que existe un orden total sobre el que todos
		los escritores están de acuerdo. Ahí se sella, de a una, y serializado por un
		candado de Postgres.
		"""
		entradas = super().create(vals_list)
		self._pedir_sellado()
		return entradas

	@api.model
	def _pedir_sellado(self):
		"""Engancha el sellado al commit. Idempotente: `Callbacks` no repite la función."""
		self.env.cr.postcommit.add(self._sellar_pendientes_en_su_conexion)

	@api.model
	def _sellar_pendientes_en_su_conexion(self):
		"""El sellador, después del commit y en su propia conexión.

		Cualquier error acá NO puede tumbar la petición que ya confirmó: la escritura pasó
		y el usuario tiene que verla. Se registra y se sigue — y las entradas quedan sin
		sellar, que es un estado previsto y que la verificación sabe nombrar. El sellado
		siguiente las levanta, porque sella TODAS las pendientes, no sólo las suyas.
		"""
		try:
			with self._cursor_de_sellado() as cr:
				self.with_env(self.env(cr=cr)).sudo().sellar_pendientes()
		except Exception:
			_logger.exception(
				"No se pudieron sellar las entradas nuevas de la bitácora. Quedan sin "
				"sello y el próximo sellado las toma.")

	def _cursor_de_sellado(self):
		"""Conexión propia para sellar. Costura de test, igual que la del apply.

		En un test nada confirma —y `postcommit` ni siquiera corre—, así que los tests
		llaman a `sellar_pendientes()` a mano sobre el cursor de la transacción. Con eso
		se prueba QUÉ sella y en qué orden; que sobreviva a una caída se prueba contra el
		sandbox, en dos procesos.
		"""
		return self.pool.cursor()

	# Un número cualquiera pero FIJO: es la identidad del candado. Dos procesos que usen
	# números distintos no se serializan entre sí, que es justo lo que hay que evitar.
	CANDADO_DE_CADENA = 0x52504D31   # "RPM1"

	@api.model
	def sellar_pendientes(self):
		"""Sella, en orden y de a una, todas las entradas que todavía no tienen sello.

		SERIALIZADO POR UN CANDADO DE POSTGRES. Dos selladores simultáneos volverían a
		bifurcar la cadena, que es exactamente el defecto que esto viene a arreglar. El
		candado es de transacción: se suelta solo al confirmar, pase lo que pase.

		Sella TODAS las pendientes, no sólo las de quien lo llama. Así, si un proceso se
		cayó entre el commit y su sellado, el siguiente las recoge en vez de dejar un
		agujero permanente.
		"""
		self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (self.CANDADO_DE_CADENA,))
		self.env.cr.execute(
			"SELECT id FROM repo_audit_log WHERE entry_hash IS NULL ORDER BY id")
		pendientes = [fila[0] for fila in self.env.cr.fetchall()]
		for entrada in self.browse(pendientes):
			entrada._sellar()
		return len(pendientes)

	def _sellar(self):
		"""Calcula y guarda el sello de esta entrada, encadenado con el de la anterior.

		Escribe por SQL directo y no con `write`, y no es una trampa: `write` está
		prohibido a propósito en este modelo y esta es la única excepción, acotada a los
		campos del sello. Hacerlo por el ORM obligaría a abrirle una puerta a `write`, y
		esa puerta después la usa cualquiera.
		"""
		self.ensure_one()
		self.env.cr.execute(
			"SELECT entry_hash, chain_seq FROM repo_audit_log "
			"WHERE chain_seq IS NOT NULL ORDER BY chain_seq DESC LIMIT 1")
		fila = self.env.cr.fetchone()
		previo, posicion = (fila[0] or "", (fila[1] or 0) + 1) if fila else ("", 1)
		cuerpo = json.dumps(
			{c: str(self[c].id if c == "user_id" else self[c] or "")
			 for c in self.CAMPOS_SELLADOS},
			sort_keys=True, separators=(",", ":"))
		sello = hashlib.sha256(("%s|%s" % (previo, cuerpo)).encode()).hexdigest()
		self.env.cr.execute(
			"UPDATE repo_audit_log SET previous_hash = %s, entry_hash = %s, "
			"chain_seq = %s WHERE id = %s",
			(previo or None, sello, posicion, self.id))
		self.invalidate_recordset(["previous_hash", "entry_hash", "chain_seq"])
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

		Devuelve `{"estado": ok|rota|vacia|pendiente, ...}`.

		Dos formas de romperse, y se distinguen porque significan cosas distintas:
		· **contenido**: la entrada dice algo distinto de lo que decía cuando se selló.
		· **eslabón**: el `previous_hash` no coincide con el sello de la anterior, o sea
		  que alguien borró o insertó una entrada en el medio.

		SE RECORRE POR `chain_seq`, no por id: el orden de la cadena es el orden en que se
		selló. Y se recorre DESDE EL ÚLTIMO GÉNESIS, porque un génesis es exactamente eso
		— la declaración de que desde ahí hay garantía y de que lo anterior es otra cosa.
		Los segmentos cerrados se cuentan y se informan: que aparezca uno nuevo es visible,
		y tiene que serlo.

		Las entradas sin sellar NO son una rotura: son entradas que confirmaron y todavía
		no pasaron por el sellador. Se cuentan aparte y se dicen.
		"""
		selladas = self.search([("chain_seq", "!=", False)], order="chain_seq")
		pendientes = self.search_count([("entry_hash", "=", False)])
		if not selladas:
			return {"estado": "pendiente" if pendientes else "vacia",
					"pendientes": pendientes}

		genesis = [e for e in selladas if e.event_type == "chain_genesis"]
		desde = genesis[-1] if genesis else selladas[0]
		tramo = [e for e in selladas if e.chain_seq >= desde.chain_seq]

		anterior = None
		for entrada in tramo:
			if entrada._recalcular_sello() != entrada.entry_hash:
				return {"estado": "rota", "entrada": entrada.id,
						"momento": entrada.timestamp, "pendientes": pendientes,
						"motivo": _("el contenido de la entrada cambió desde que se selló")}
			# El primero del tramo encadena con lo de antes, que puede no estar verificado:
			# su eslabón hacia atrás no se exige, el resto sí.
			if anterior is not None:
				if (entrada.previous_hash or "") != (anterior.entry_hash or ""):
					return {"estado": "rota", "entrada": entrada.id,
							"momento": entrada.timestamp, "pendientes": pendientes,
							"motivo": _("falta una entrada anterior, o se insertó una")}
			anterior = entrada
		return {"estado": "ok", "desde": desde.timestamp, "entradas": len(tramo),
				"pendientes": pendientes,
				"segmentos_cerrados": max(len(genesis) - 1, 0)}

	def init(self):
		"""La entrada cero se asegura en cada actualización del módulo, no sólo al instalar.

		`post_init_hook` fue el primer intento y no alcanza: corre SÓLO en la instalación,
		y en una base donde el módulo ya estaba —que es el caso real, y el único que
		importa acá porque es el que tiene entradas viejas sin encadenar— nunca se ejecuta.
		`init()` corre en cada `-u`, que es cuando la cadena empieza a existir de verdad.
		"""
		super().init()
		# Lo que ya estaba sellado no tiene posición: se le pone la del id, que es el
		# orden en que se selló en aquel esquema —uno solo escribía—. Recalcular sus
		# hashes sería reescribir el pasado; acá sólo se les da un número para poder
		# recorrerlos.
		self.env.cr.execute(
			"UPDATE repo_audit_log SET chain_seq = id "
			"WHERE entry_hash IS NOT NULL AND chain_seq IS NULL")
		self.asegurar_genesis()
		# Y si quedó algo sin sellar de una caída anterior, se sella ahora.
		self.env["repo.audit.log"].sellar_pendientes()

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

	@api.model
	def cerrar_tramo_y_reabrir(self, motivo):
		"""Cierra el tramo actual de la cadena y abre uno nuevo, DICIENDO POR QUÉ.

		CUÁNDO SE USA, Y CUÁNDO NO. Se usa cuando la cadena quedó rota por una causa
		conocida y explicable —un defecto del propio módulo, una migración que cambió los
		campos sellados—: el tramo viejo no se puede reparar sin reescribir sellos, y
		reescribirlos sería fabricar la confianza que la cadena existe para no fabricar.
		Lo honesto es cerrar, declarar la causa, y volver a empezar desde una punta limpia.

		NO ES AUTOMÁTICO, Y ESO ES LO IMPORTANTE. Si el módulo cerrara el tramo solo cada
		vez que encuentra la cadena rota, cualquier manipulación quedaría tapada por el
		siguiente arranque: el diagnóstico diría «ok» sobre una base editada. Tiene que
		haber una persona, con un motivo escrito, que quede en la entrada.

		El motivo va en el resumen y se sella con la entrada: no se puede cambiar después.
		"""
		if not motivo or not motivo.strip():
			raise UserError(_(
				"Cerrar un tramo de la cadena exige un motivo. Sin él, la entrada diría "
				"que hubo un corte y no diría por qué, que es la única parte que sirve."))
		antes = self.verificar_cadena()
		entrada = self.sudo().create({
			"event_type": "chain_genesis",
			"summary": _("Tramo nuevo de la cadena de integridad. %s") % motivo.strip(),
			"payload_json": json.dumps({
				"motivo": motivo.strip(),
				"estado_al_cerrar": antes.get("estado"),
				"entrada_donde_se_rompia": antes.get("entrada"),
				"cerrado_por": self.env.user.login,
			}, default=str),
		})
		self.sellar_pendientes()
		return entrada

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
