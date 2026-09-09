# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E2.2a · qué cambió entre dos auditorías. El motor, sin pantalla.

LO QUE IMPORTA DE UNA CORRIDA NO ES LA LISTA. Doscientos setenta y tres hallazgos no se
leen; «tres cosas nuevas esta semana» sí. Este módulo es lo que convierte una cosa en la
otra, y es la pieza que hace que la auditoría programada valga la pena: sin delta, un
correo semanal con la lista completa se deja de leer al tercer lunes.

LA CLAVE ES `(tipo, repositorio, sujeto)` Y NO EL ID. Los hallazgos se borran y se rehacen
en cada corrida —el motor es idempotente a propósito—, así que el id de «la rama 19.0 de
tal repo no está protegida» cambia todas las semanas aunque el problema sea el mismo. La
clave es lo que el hallazgo AFIRMA, no el registro que lo guarda.

Esa clave es el contrato, y se eligió pensando en algo que todavía no existe: el día que
un webhook produzca hallazgos, esos no van a pertenecer a ninguna corrida. La comparación
no se apoya en `run_id` para nada más que para elegir los dos extremos.

LAS TRES CATEGORÍAS, Y POR QUÉ SON TRES. «Apareció» y «se resolvió» son las dos obvias. La
tercera es la que hace que las otras dos se puedan creer:

    Sin confirmar · 3 repos
    cliente-acme-erp, cliente-acme-web, legacy-v12: sus 5 hallazgos de #57 siguen
    abiertos porque no se pudieron volver a leer. No cuentan como resueltos ni como
    nuevos.

Un hallazgo que desaparece porque el repositorio no se pudo leer **no se resolvió**:
nadie lo miró. Contarlo como resuelto sería exactamente la mentira que este módulo existe
para no decir — y la más cómoda de todas, porque el número mejora solo.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Los estados de una corrida que se pueden comparar. Una corrida `error` se detuvo a
# mitad de camino: lo que no llegó a mirar no se distingue de lo que miró y estaba bien.
COMPARABLES = ("done", "partial")

# LOS HALLAZGOS QUE SE RESUELVEN **EN** ODOO, no en GitHub.
#
# Su remediación no es una escritura al repositorio sino un acto de esta aplicación:
# clasificar, vincular una cuenta, declarar los checks. No pasan por el embudo —no hay
# nada que escribir allá— así que no dejan entrada de escritura en la bitácora, y decir
# de ellos «se resolvió fuera de la app» sería exactamente al revés de lo que pasó.
#
# Cada uno trae CÓMO COMPROBARLO: la atribución se afirma sobre el hecho que quedó en la
# base, no sobre la suposición de que alguien hizo algo. Si el hecho no está, se cae a
# «fuera de la app» como cualquier otro.
ACTOS_EN_LA_APP = {
	"classification_missing": {
		"texto": "clasificación definida",
		"comprobar": lambda h: bool(h.repository_id.classification),
	},
	"member_without_employee": {
		"texto": "cuenta vinculada a una persona",
		# El hallazgo no enlaza la persona —va a nivel cuenta— así que se la busca por
		# su login, que es el sujeto. Buscar es más honesto que suponer.
		"comprobar": lambda h: bool(
			h.env["repo.member"].search([
				("github_login", "=", h.subject)], limit=1).employee_id),
	},
	"checks_not_evaluable": {
		"texto": "checks requeridos definidos",
		"comprobar": lambda h: bool(
			h.env["repo.policy.template"].search([
				("name", "=", h.subject)], limit=1).status_checks_defined),
	},
}

# `institutional_account` NO está en la lista y no es un olvido: no se resuelve con
# ningún acto, ni acá ni en GitHub. Es una nota permanente sobre la cuenta dueña. Si
# alguna vez desaparece será porque la cuenta dejó de existir, y eso no es «se resolvió».


class RepoAuditDelta(models.AbstractModel):
	_name = "repo.audit.delta"
	_description = "Comparación entre dos corridas de auditoría"

	@api.model
	def clave(self, hallazgo):
		"""Lo que un hallazgo AFIRMA, en forma de tupla comparable.

		El repositorio va por id y no por nombre: un repositorio renombrado en GitHub
		sigue siendo el mismo —el espejo lo sigue por `github_id`— y comparar por nombre
		habría reportado todos sus hallazgos como resueltos y vueltos a aparecer el día
		que alguien lo renombra.
		"""
		return (hallazgo.finding_type, hallazgo.repository_id.id or 0,
				hallazgo.subject or "")

	@api.model
	def corrida_anterior(self, corrida):
		"""La última corrida COMPARABLE del mismo backend, anterior a ésta.

		Una corrida `error` no se compara **ni cuenta como anterior**: si contara, el
		delta de la semana siguiente se mediría contra una foto que se sacó a medias, y
		media foto es peor que ninguna — parecería que aparecieron treinta hallazgos
		cuando lo que pasó es que la vez anterior no se llegó a mirar.
		"""
		corrida.ensure_one()
		return self.env["repo.audit.run"].search([
			("backend_id", "=", corrida.backend_id.id),
			("id", "<", corrida.id),
			("state", "in", COMPARABLES),
		], order="id desc", limit=1)

	@api.model
	def _releidos(self, corrida):
		"""Los repositorios que ESTA corrida llegó a recorrer entero.

		Se pregunta por la fila de la corrida y no por el espejo: el espejo dice cómo
		está el repositorio hoy, y acá hace falta saber si esta corrida lo miró. Un
		repositorio que falló, que quedó pendiente porque la corrida se detuvo, o que ni
		siquiera entró en el enumerado —porque desapareció de la cuenta— no fue releído,
		y las tres cosas significan lo mismo para el delta: no hay con qué afirmar.
		"""
		corrida.ensure_one()
		return corrida.line_ids.filtered(lambda l: l.state == "done").repository_id

	@api.model
	def _motivo_de_no_releido(self, corrida, repo):
		"""Por qué no se pudo volver a mirar. La pantalla lo muestra tal cual."""
		linea = corrida.line_ids.filtered(lambda l: l.repository_id == repo)[:1]
		if not linea:
			if not repo.present:
				return _("ya no viene en el listado de la conexión")
			return _("no entró en esta corrida")
		if linea.state == "error":
			return (linea.error or _("falló al recorrerlo")).splitlines()[0][:120]
		return _("la corrida se detuvo antes de llegar a él")

	@api.model
	def calcular(self, corrida, anterior=None):
		"""El delta de una corrida contra la anterior comparable, o contra la que se pida.

		Returns:
			dict:
				``comparable`` (bool) y ``motivo`` cuando no lo es;
				``anterior`` (corrida o vacío);
				``nuevos``, ``resueltos``, ``sin_confirmar`` (recordsets de hallazgos);
				``sin_base_anterior`` (ids de los nuevos que la corrida anterior no pudo
				mirar, así que no se puede afirmar que sean nuevos);
				``repos_sin_confirmar`` (lista de ``(repositorio, motivo)``).
		"""
		corrida.ensure_one()
		Hallazgo = self.env["repo.audit.finding"]
		vacio = Hallazgo.browse()

		if corrida.state not in COMPARABLES:
			return {
				"comparable": False,
				"motivo": _("No se compara una corrida incompleta: lo que no llegó a "
							"mirarse no se distingue de lo que estaba bien."),
				"anterior": self.env["repo.audit.run"].browse(),
				"nuevos": vacio, "resueltos": vacio, "sin_confirmar": vacio,
				"sin_base_anterior": set(), "repos_sin_confirmar": [],
			}

		anterior = anterior if anterior is not None else self.corrida_anterior(corrida)
		if not anterior:
			return {
				"comparable": False,
				"motivo": _("Es la primera auditoría comparable de esta conexión: no hay "
							"contra qué medirla todavía."),
				"anterior": anterior,
				"nuevos": vacio, "resueltos": vacio, "sin_confirmar": vacio,
				"sin_base_anterior": set(), "repos_sin_confirmar": [],
			}

		de_ahora = {self.clave(h): h for h in corrida.finding_ids}
		de_antes = {self.clave(h): h for h in anterior.finding_ids}

		releidos_ahora = self._releidos(corrida)
		releidos_antes = self._releidos(anterior)
		# Un hallazgo de cuenta —sin repositorio— se calcula sobre TODOS los repos, así
		# que sólo se puede afirmar sobre él si la corrida los miró a todos.
		cuenta_confiable_ahora = corrida.state == "done"

		nuevos, sin_base = vacio, set()
		for clave, hallazgo in de_ahora.items():
			if clave in de_antes:
				continue
			nuevos |= hallazgo
			repo = hallazgo.repository_id
			# NO SE PUEDE AFIRMAR QUE SEA NUEVO si la vez anterior no se miró ese
			# repositorio: pudo haber estado ahí todo el tiempo. Se informa igual —
			# esconderlo sería peor— pero con la salvedad puesta, que es lo mismo que se
			# hace del otro lado con «sin confirmar».
			if repo and repo not in releidos_antes:
				sin_base.add(hallazgo.id)
			elif not repo and anterior.state != "done":
				sin_base.add(hallazgo.id)

		resueltos, sin_confirmar, repos_sin_confirmar = vacio, vacio, []
		for clave, hallazgo in de_antes.items():
			if clave in de_ahora:
				continue
			repo = hallazgo.repository_id
			if repo:
				if repo in releidos_ahora:
					resueltos |= hallazgo
				else:
					sin_confirmar |= hallazgo
			elif cuenta_confiable_ahora:
				resueltos |= hallazgo
			else:
				sin_confirmar |= hallazgo

		for repo in sin_confirmar.repository_id:
			repos_sin_confirmar.append(
				(repo, self._motivo_de_no_releido(corrida, repo)))

		return {
			"comparable": True, "motivo": "",
			"anterior": anterior,
			"nuevos": nuevos,
			"resueltos": resueltos,
			"sin_confirmar": sin_confirmar,
			"sin_base_anterior": sin_base,
			"repos_sin_confirmar": repos_sin_confirmar,
		}


	# ------------------------------------------------------------------
	# Lo que la pantalla dibuja
	# ------------------------------------------------------------------

	@api.model
	def _fila(self, hallazgo, delta, nota=""):
		"""Un hallazgo como lo pinta la pantalla: severidad, dónde, qué, y la salvedad."""
		severidades = dict(self.env["repo.audit.finding"]._fields["severity"].selection)
		return {
			"id": hallazgo.id,
			"severidad": hallazgo.severity,
			"severidad_etiqueta": severidades.get(hallazgo.severity, hallazgo.severity),
			"repositorio": hallazgo.repository_id.name or _("toda la cuenta"),
			"titulo": hallazgo.summary,
			"nota": nota or (
				_("El repositorio no se pudo leer en la corrida anterior, así que puede "
				  "no ser nuevo.") if hallazgo.id in delta["sin_base_anterior"] else ""),
		}

	@api.model
	def _frase(self, delta):
		"""La narrativa del mockup, armada con los números de esta comparación.

		Se redacta en el servidor por la misma razón que las filas: es una afirmación
		sobre lo que se sabe y lo que no, y esa distinción no se decide en dos lugares.
		"""
		nuevos, resueltos = delta["nuevos"], delta["resueltos"]
		criticos = len(nuevos.filtered(lambda h: h.severity == "critical"))
		partes = []
		# Sin novedades es una noticia, y de las buenas. Decirlo es mejor que dejar
		# la pantalla en blanco: el silencio se lee como «no corrió».
		if not nuevos and not resueltos:
			partes.append(_("No apareció ni se resolvió nada desde la corrida anterior."))
		else:
			if nuevos:
				partes.append(_("Aparecieron %s hallazgo(s)") % len(nuevos)
							  + (_(", %s de ellos crítico(s)") % criticos if criticos else ""))
			if resueltos:
				partes.append((_("se resolvieron %s") % len(resueltos)) if nuevos
							  else (_("Se resolvieron %s hallazgo(s)") % len(resueltos)))
		frase = ", y ".join(partes) if len(partes) > 1 else partes[0]
		if not frase.endswith("."):
			frase += "."
		repos = delta["repos_sin_confirmar"]
		if repos:
			frase += " " + _(
				"%(n)s repositorio(s) no se pudieron leer esta vez, así que sus %(h)s "
				"hallazgo(s) anteriores se mantienen abiertos sin confirmar."
			) % {"n": len(repos), "h": len(delta["sin_confirmar"])}
		return frase

	@api.model
	def para_pantalla(self, corrida_id, anterior=None):
		"""Todo lo que la pantalla del delta dibuja, en una sola llamada.

		Recibe IDS y no recordsets porque quien llama es el navegador. Los dos se
		resuelven acá, y el acceso se comprueba explícitamente: una corrida que el
		usuario no puede leer no se dibuja aunque alguien mande su id a mano.
		"""
		Run = self.env["repo.audit.run"]
		corrida = Run.browse(int(corrida_id)).exists()
		if not corrida:
			raise UserError(_("Esa corrida ya no existe."))
		corrida.check_access("read")
		if anterior:
			anterior = Run.browse(int(anterior)).exists()
			anterior.check_access("read")
			if anterior.backend_id != corrida.backend_id:
				# Comparar dos cuentas distintas daría un delta donde todo es nuevo y
				# todo se resolvió: dos inventarios que no se comparan entre sí.
				raise UserError(_(
					"No se comparan corridas de conexiones distintas."))
		delta = self.calcular(corrida, anterior=anterior or None)
		comparables = self.env["repo.audit.run"].search([
			("backend_id", "=", corrida.backend_id.id),
			("id", "!=", corrida.id),
			("state", "in", COMPARABLES)], order="id desc", limit=20)
		base = {
			"comparable": delta["comparable"],
			"motivo": delta["motivo"],
			"corrida": {"id": corrida.id, "nombre": corrida.display_name,
						"cuando": self._cuando(corrida)},
			"anterior": ({"id": delta["anterior"].id,
						  "nombre": delta["anterior"].display_name,
						  "cuando": self._cuando(delta["anterior"])}
						 if delta["anterior"] else False),
			"otras": [{"id": c.id, "etiqueta": "%s · %s" % (c.display_name,
														   self._cuando(c))}
					  for c in comparables],
			"nuevos": [], "resueltos": [], "sin_confirmar": [],
			"frase": "", "hallazgos_sin_confirmar": 0,
		}
		if not delta["comparable"]:
			return base
		base.update({
			"frase": self._frase(delta),
			"nuevos": [self._fila(h, delta) for h in delta["nuevos"]],
			"resueltos": self._resueltos_con_atribucion(delta, corrida),
			"sin_confirmar": [{"repositorio": repo.name or repo.full_name,
							   "motivo": motivo}
							  for repo, motivo in delta["repos_sin_confirmar"]],
			"hallazgos_sin_confirmar": len(delta["sin_confirmar"]),
			"nuevos_ids": delta["nuevos"].ids,
		})
		return base

	@api.model
	def _resueltos_con_atribucion(self, delta, corrida):
		"""Cada resuelto con POR QUÉ dejó de estar. Una sola consulta por hallazgo."""
		filas = []
		for hallazgo in delta["resueltos"]:
			atribucion = self.atribucion(hallazgo, corrida, delta["anterior"])
			fila = self._fila(hallazgo, delta, nota=atribucion["texto"])
			fila["atribucion"] = atribucion["categoria"]
			filas.append(fila)
		return filas

	@api.model
	def _cuando(self, corrida):
		return (corrida.finished_at or corrida.started_at or corrida.create_date
				).strftime("%d/%m/%Y %H:%M")

	# ------------------------------------------------------------------
	# La historia de UN hallazgo
	# ------------------------------------------------------------------

	@api.model
	def historia(self, hallazgo, limite=8):
		"""En qué auditorías apareció este hallazgo y en cuáles no estaba.

		Sale de la MISMA clave que el delta: no hace falta ningún dato nuevo, sólo
		preguntar por `(tipo, repositorio, sujeto)` en las corridas comparables de la
		conexión. Por eso entra acá y no en un modelo aparte — dos definiciones de «es el
		mismo hallazgo» se separan el día que alguien toca una.

		Lo que devuelve dice tres cosas por corrida, no dos: **estaba**, **no estaba**, y
		**no se pudo mirar**. La tercera es la de siempre: en una corrida que no leyó ese
		repositorio, la ausencia del hallazgo no significa que no estuviera.
		"""
		hallazgo.ensure_one()
		clave = self.clave(hallazgo)
		corridas = self.env["repo.audit.run"].search([
			("backend_id", "=", hallazgo.run_id.backend_id.id),
			("state", "in", COMPARABLES),
		], order="id desc", limit=limite)
		salida = []
		for corrida in corridas:
			presente = any(self.clave(h) == clave for h in corrida.finding_ids)
			if presente:
				estado, motivo = "estaba", ""
			elif hallazgo.repository_id and hallazgo.repository_id not in self._releidos(corrida):
				estado = "sin_mirar"
				motivo = self._motivo_de_no_releido(corrida, hallazgo.repository_id)
			elif not hallazgo.repository_id and corrida.state != "done":
				estado, motivo = "sin_mirar", _("la corrida no leyó todos los repositorios")
			else:
				estado, motivo = "no_estaba", ""
			salida.append({
				"corrida_id": corrida.id,
				"corrida": corrida.display_name,
				"cuando": self._cuando(corrida),
				"estado": estado,
				"motivo": motivo,
			})
		return salida

	# ------------------------------------------------------------------
	# Por qué se resolvió — tres categorías, y ninguna se supone
	# ------------------------------------------------------------------

	@api.model
	def _ventana(self, corrida, anterior):
		"""Entre las dos fotos. Lo que pasó fuera de esa ventana no explica este delta.

		El borde de abajo es cuándo TERMINÓ la anterior y no cuándo empezó: un plan
		aplicado mientras la corrida anterior recorría repositorios ya está reflejado en
		lo que esa corrida vio, así que atribuirle este resuelto sería contarlo dos veces.
		"""
		desde = anterior.finished_at or anterior.create_date
		hasta = corrida.finished_at or fields.Datetime.now()
		return desde, hasta

	@api.model
	def _plan_que_lo_corrigio(self, hallazgo, desde, hasta):
		"""La entrada de la bitácora que explica este resuelto, si la hay.

		SE BUSCA POR EL ENLACE Y NO POR PARECIDO. La operación guarda el `finding_id` que
		la originó, así que cuando el plan se armó desde ESTE hallazgo la atribución es
		exacta. Recién si no hay enlace se cae a «misma cuenta, mismo repositorio, mismo
		sujeto», que es lo que cubre el caso de un plan armado desde una corrida más
		vieja con el mismo problema.

		«Verificado» no es un adorno: una entrada `write_applied` sólo existe después de
        que el apply releyó el estado y comprobó que quedó como se pedía. Es el paso 3 del
		ciclo, y es lo que hace que esta frase se pueda afirmar.

		UNA ESCRITURA REVERTIDA NO CORRIGE NADA. Si la misma operación tiene después una
		entrada de reversión dentro de la ventana, no se atribuye: lo que se aplicó se
		deshizo, y si el hallazgo igual desapareció fue por otra cosa.
		"""
		Log = self.env["repo.audit.log"]
		dominio = [
			("event_type", "=", "write_applied"),
			("timestamp", ">=", desde), ("timestamp", "<=", hasta),
		]
		entrada = Log.search(
			dominio + [("operation_id.finding_id", "=", hallazgo.id)],
			order="timestamp desc", limit=1)
		if not entrada and hallazgo.repository_id:
			entrada = Log.search(
				dominio + [
					("repository_id", "=", hallazgo.repository_id.id),
					("operation_id.target", "=", hallazgo.subject or ""),
				], order="timestamp desc", limit=1)
		if not entrada:
			return Log.browse()
		revertida = Log.search_count([
			("event_type", "=", "write_rolled_back"),
			("operation_id", "=", entrada.operation_id.id),
			("timestamp", ">=", entrada.timestamp), ("timestamp", "<=", hasta),
		])
		return Log.browse() if revertida else entrada

	@api.model
	def atribucion(self, hallazgo, corrida, anterior):
		"""Por qué dejó de estar. Tres categorías, en orden de cuánto se sabe.

		1. **Un plan de este módulo**, con su nombre y su verificación. Sale de la
		   bitácora, que es el registro.
		2. **Un acto en la app sin plan**: clasificar, vincular una cuenta. No hay
		   escritura a GitHub que registrar porque no la hubo, y el hecho se comprueba
		   contra la base antes de afirmarlo.
		3. **Fuera de la app.** Se afirma tal cual, y se puede: el embudo es el ÚNICO
		   camino por el que este módulo escribe en GitHub, así que si ningún plan lo
		   tocó y no fue un acto de acá, alguien lo cambió por otro lado. No es una
		   suposición: es lo que queda cuando las otras dos están descartadas.
		"""
		desde, hasta = self._ventana(corrida, anterior)
		entrada = self._plan_que_lo_corrigio(hallazgo, desde, hasta)
		if entrada:
			return {
				"categoria": "plan",
				"texto": _("Lo corrigió %(plan)s el %(cuando)s · verificado") % {
					"plan": (entrada.operation_id.plan_id.display_name
							 or entrada.plan_label or _("un plan")),
					"cuando": entrada.timestamp.strftime("%d/%m/%Y"),
				},
			}
		acto = ACTOS_EN_LA_APP.get(hallazgo.finding_type)
		if acto and acto["comprobar"](hallazgo):
			return {"categoria": "app",
					"texto": _("Se resolvió en la app: %s") % acto["texto"]}
		return {"categoria": "fuera",
				"texto": _("Se resolvió fuera de la app: alguien lo cambió en GitHub.")}
