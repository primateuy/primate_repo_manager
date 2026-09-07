# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""De una plantilla de política al JSON de un ruleset de GitHub. SIN ESCRIBIR NADA.

Este archivo no toca GitHub ni la base: recibe un repositorio y devuelve lo que habría
que mandar. Se puede llamar mil veces sin consecuencias, y por eso se puede probar sin
dobles y mirar en pantalla antes de que exista el apply. Escribir es B1.3.

LAS CONDICIONES SALEN DE LAS RAMAS OBSERVADAS, NO DE LOS PATRONES DE ROL
=======================================================================
El rol de una rama se decide con expresiones REGULARES (`repo.branch.role.rule`:
`^\\d+\\.\\d+$`, `(?i)(^|[._-])staging($|[._-])`). Las condiciones de un ruleset de GitHub
son fnmatch —`refs/heads/release/*`—, que es un lenguaje más pobre. **Traducir regex a
fnmatch no se puede en general**, y aproximarlo sería inventar el alcance de una regla que
bloquea merges: de más, frena repositorios que nadie quiso frenar; de menos, deja sin
proteger ramas que la política sí gobierna.

Así que el ruleset nombra **las ramas que el espejo vio**, una por una y completas
(`refs/heads/19.0`). Es un hecho, con su fecha, y no una interpretación.

**El agujero que eso deja, dicho en voz alta:** una rama creada DESPUÉS de la última
auditoría y que caiga en el mismo rol **no queda cubierta** hasta que la próxima corrida
la vea y el ruleset se reaplique. Es exactamente el caso que los webhooks de F4 cierran.
Mientras tanto la pantalla lo dice; lo que no hace es taparlo con un glob inventado.

LO QUE LA PLANTILLA NO DECLARA NO SE EXIGE
==========================================
La API de rulesets obliga a mandar todas las claves de `pull_request`, incluidas tres que
la plantilla no modela. Van en `False`, y eso significa **«esta política no lo exige»** —
nunca «lo exigimos por defecto». Un default silencioso que endurece es peor que uno que
afloja: el que afloja se ve en la comparación «Exige … · Tiene …»; el que endurece bloquea
merges que nadie decidió bloquear.

QUÉ NO TRADUCE, Y POR QUÉ SE DEVUELVE EN VEZ DE IGNORARSE
=========================================================
Lo que no sabe traducir viaja en `no_traducido` y la pantalla lo muestra. Pasar de largo
en silencio produce un ruleset que parece la política entera y es una parte, que es la
forma más cara de mentir: el informe diría «aplicado» sobre algo incompleto.
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .repo_rules import ROLES_GOBERNADOS

# El mismo normalizador que usa el apply. Compartido y no reimplementado: si el
# espejo guardara los campos con otro criterio que el que verifica la escritura,
# el drift compararía dos cosas que no son la misma.

_logger = logging.getLogger(__name__)


def _comparable(definicion):
	from .repo_write_apply import _definicion_comparable
	return _definicion_comparable(definicion)

# El prefijo es lo que hace reconocible un ruleset NUESTRO entre los que ya había en el
# repositorio. B1.3 lo necesita para no tocar lo ajeno: un ruleset sin este prefijo no se
# actualiza ni se borra jamás, aunque se parezca.
RULESET_PREFIX = "primate"


def nombre_de_ruleset(codigo_plantilla, rol):
	"""Nombre estable de un ruleset nuestro: `primate/<plantilla>/<rol>`.

	Estable a propósito: es la identidad por la que B1.3 lo va a encontrar para
	actualizarlo en vez de crear uno nuevo al lado en cada aplicación.
	"""
	return "%s/%s/%s" % (RULESET_PREFIX, codigo_plantilla, rol)


class RepoRulesetBuilder(models.AbstractModel):
	_name = "repo.ruleset.builder"
	_description = "Traducción de una plantilla de política a rulesets de GitHub"

	# ------------------------------------------------------------------
	# Entrada
	# ------------------------------------------------------------------

	@api.model
	def payloads_for_repository(self, repo):
		"""Los rulesets que le corresponden a un repositorio, uno por rol gobernado.

		Args:
			repo: registro de `repo.repository`.

		Returns:
			list: un dict por rol CON RAMAS OBSERVADAS, con las claves ``role``,
			``name``, ``branches``, ``payload`` y ``no_traducido``. Un rol sin ramas
			vistas no genera ruleset — un ruleset sin condiciones no se aplica a nada
			y sólo ensucia el repositorio.
		"""
		repo.ensure_one()
		plantilla = repo.plantilla_efectiva()
		if not plantilla:
			return []

		bypass = self._bypass_actors(repo.backend_id)
		salida = []
		for rol in ROLES_GOBERNADOS:
			ramas = repo.branch_ids.filtered(lambda r: r.role == rol)
			if not ramas:
				continue
			salida.append(self.payload_for_role(plantilla, rol, ramas, bypass))
		salida.extend(self._roles_sin_traduccion(repo, plantilla))
		return salida

	# ------------------------------------------------------------------
	# Un rol
	# ------------------------------------------------------------------

	@api.model
	def payload_for_role(self, plantilla, rol, ramas, bypass_actors):
		"""El ruleset de un rol de rama, listo para mandar.

		Args:
			plantilla: registro de `repo.policy.template`.
			rol: uno de `BRANCH_ROLES`.
			ramas: recordset de `repo.branch` observadas con ese rol.
			bypass_actors: lo que devuelve `_bypass_actors`.

		Returns:
			dict: ``role``, ``name``, ``branches``, ``payload``, ``no_traducido``.
		"""
		regla = plantilla.rule_for_role(rol)
		no_traducido = []
		reglas = []

		if regla.get("require_pr"):
			reglas.append({
				"type": "pull_request",
				"parameters": {
					"required_approving_review_count": regla.get("required_approvals") or 0,
					"require_code_owner_review": bool(regla.get("require_codeowner_review")),
					# Las tres que la plantilla no modela. False = no se exige.
					"dismiss_stale_reviews_on_push": False,
					"require_last_push_approval": False,
					"required_review_thread_resolution": False,
				},
			})
		if regla.get("block_force_push"):
			reglas.append({"type": "non_fast_forward"})
		if regla.get("block_deletion"):
			reglas.append({"type": "deletion"})
		if regla.get("require_signed_commits"):
			reglas.append({"type": "required_signatures"})

		# LOS CHECKS SÓLO SI ESTÁN DEFINIDOS. Un nombre de check que no existe bloquea
		# TODOS los merges del repositorio para siempre, así que mientras la plantilla
		# diga que no los sabe, el ruleset sale sin ellos y se dice que salió sin ellos.
		if plantilla.status_checks_defined and plantilla.required_check_ids:
			reglas.append({
				"type": "required_status_checks",
				"parameters": {
					"strict_required_status_checks_policy": False,
					"required_status_checks": [
						{"context": check.name}
						for check in plantilla.required_check_ids
					],
				},
			})
		elif plantilla.required_check_ids and not plantilla.status_checks_defined:
			no_traducido.append(_(
				"Los checks de CI no entran: la plantilla los lista pero todavía no los "
				"da por confirmados, y un nombre equivocado bloquea todos los merges."))

		if regla.get("commit_message_pattern") or plantilla.commit_message_pattern:
			patron = regla.get("commit_message_pattern") or plantilla.commit_message_pattern
			reglas.append({
				"type": "commit_message_pattern",
				"parameters": {
					"operator": "regex",
					"pattern": patron,
					"negate": False,
					"name": _("Formato de mensaje de commit de Primate"),
				},
			})

		# EL PATRÓN DE NOMBRE DE RAMA NO VA ACÁ, y no es un olvido. Gobierna cómo se
		# llaman las ramas NUEVAS —`feature/1234-lo-que-sea`— o sea todas, no las cuatro
		# que este ruleset nombra. Meterlo acá lo aplicaría sólo sobre `19.0` y `main`,
		# que es donde nunca se crea una feature branch: parecería aplicado y no haría
		# nada. Es un ruleset propio, con condición `~ALL`, y tiene su lugar en B.
		if plantilla.branch_name_pattern:
			no_traducido.append(_(
				"El patrón de nombre de rama no entra en este ruleset: gobierna las ramas "
				"nuevas, no las de este rol. Va en un ruleset propio sobre todas."))

		if regla.get("block_human_push"):
			no_traducido.append(_(
				"«Sólo el job de sync avanza esta rama» todavía no se traduce a un "
				"ruleset. Llega con el bloque de forks."))

		return {
			"role": rol,
			"name": nombre_de_ruleset(plantilla.code, rol),
			"branches": ramas.mapped("name"),
			"no_traducido": no_traducido,
			"payload": {
				"name": nombre_de_ruleset(plantilla.code, rol),
				"target": "branch",
				"enforcement": "active",
				"bypass_actors": bypass_actors,
				"conditions": {
					"ref_name": {
						"include": ["refs/heads/%s" % nombre for nombre in ramas.mapped("name")],
						"exclude": [],
					},
				},
				"rules": reglas,
			},
		}

	# ------------------------------------------------------------------
	# El bypass, que sale de la conexión y no del código
	# ------------------------------------------------------------------

	@api.model
	def _bypass_actors(self, backend):
		"""La App de escritura de ESTA conexión, exenta del ruleset que ella misma aplica.

		Por qué la exención es necesaria y no una comodidad: si el ruleset exige PR y la
		App no está exenta, el módulo no puede escribir en la rama que acaba de proteger
		—ni siquiera para aplicar el resto de la política—, y la guarda de «destino
		escribible» frenaría cada apply. El embudo plan → aprobación → bitácora es una
		revisión MÁS estricta que una PR, no menos.

		Por qué sale del backend y no de una constante: el App ID de escritura es otro en
		el sandbox (4808079) que en producción (prm-writer, 4811232). Escrito a mano, el
		día que se cambie la App el ruleset exime a una App que ya no es la que escribe, y
		eso no falla: aplica, y el siguiente apply se frena solo sin decir por qué.

		Raises:
			UserError: si la conexión no tiene App de escritura declarada. Un ruleset sin
				bypass es exactamente la clase de default silencioso que este módulo no
				se permite: se aplicaría bien y rompería el apply siguiente.
		"""
		app_id = (backend.write_app_id or "").strip()
		if not app_id:
			raise UserError(_(
				"La conexión «%s» no tiene App de escritura declarada, así que no se "
				"puede armar el ruleset: quedaría sin exención para la App que lo aplica "
				"y frenaría la próxima escritura sobre esas ramas."
			) % backend.display_name)
		if not app_id.isdigit():
			raise UserError(_(
				"El App ID de escritura de «%(conexion)s» no es un número (%(valor)s). "
				"GitHub identifica al actor exento por id numérico."
			) % {"conexion": backend.display_name, "valor": app_id})
		return [{
			"actor_id": int(app_id),
			"actor_type": "Integration",
			"bypass_mode": "always",
		}]

	# ------------------------------------------------------------------
	# Lo que se ve y no se traduce
	# ------------------------------------------------------------------

	@api.model
	def _roles_sin_traduccion(self, repo, plantilla):
		"""Roles con ramas observadas que la política gobierna y el ruleset todavía no.

		Se devuelven con `payload` en None: existen para que la pantalla los muestre
		apagados —qué es y con qué bloque llega— en vez de que desaparezcan.
		"""
		salida = []
		for rol in ("mirror", "patch"):
			ramas = repo.branch_ids.filtered(lambda r: r.role == rol)
			if not ramas:
				continue
			salida.append({
				"role": rol,
				"name": nombre_de_ruleset(plantilla.code, rol),
				"branches": ramas.mapped("name"),
				"payload": None,
				"no_traducido": [_(
					"Las ramas de fork —espejo y parches— no se gobiernan con un ruleset "
					"todavía. Llegan con el bloque C.")],
			})
		return salida


class RepoRuleset(models.Model):
	"""El espejo de un ruleset de GitHub. Sólo de los nuestros.

	POR QUÉ SÓLO LOS NUESTROS. Un repositorio puede tener rulesets de la organización o
	de otra herramienta, y traerlos al espejo invitaría a compararlos contra una política
	que no los gobierna. Lo ajeno se ve —el sync lo cuenta— pero no se copia: el módulo
	no vigila configuración que no puso.

	POR QUÉ ES UN MODELO Y NO UNA LECTURA AL VUELO. El drift compara lo que aplicamos
	contra lo que hay, y «lo que hay» tiene que tener fecha: sin `last_seen_at`, la
	pregunta «¿esto está desactualizado o es así?» no tiene respuesta. Con los webhooks de
	F4 conviviendo con las auditorías, esa pregunta se vuelve diaria.

	`present` EN VEZ DE BORRAR LA FILA. Un ruleset nuestro que desaparece de GitHub es el
	drift más grave que hay —alguien borró la protección entera—, y borrar la fila se
	llevaría puesto cuándo se lo vio por última vez, que es justo el dato que hace falta
	para contarlo.
	"""
	_name = "repo.ruleset"
	_description = "Ruleset de GitHub puesto por este módulo"
	_order = "repository_id, name"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	github_id = fields.Integer(string="Id en GitHub", required=True, index=True)
	name = fields.Char(string="Nombre", required=True, index=True)
	enforcement = fields.Char(string="Aplicación")
	definition_json = fields.Text(
		string="Definición observada (JSON)",
		help="La definición completa tal como la devolvió GitHub, normalizada a los "
			 "campos que gobernamos. Es contra esto que se compara lo aplicado.")
	present = fields.Boolean(
		string="Sigue en GitHub", default=True,
		help="Falso cuando el ruleset que este módulo aplicó ya no aparece. No se borra "
			 "la fila: cuándo se lo vio por última vez es el dato que hace falta.")
	last_seen_at = fields.Datetime(string="Visto por última vez", readonly=True)
	origin = fields.Selection(
		[("sync", "Auditoría"), ("webhook", "Evento de GitHub")],
		string="Por dónde entró", default="sync", required=True,
		help="Con qué mecanismo se supo. Hoy sólo la auditoría; los webhooks llegan en F4 "
			 "y van a escribir por este mismo upsert.")

	_ruleset_uniq = models.Constraint(
		"UNIQUE (repository_id, github_id)",
		"Ese ruleset ya está registrado en el repositorio.")

	@api.model
	def upsert(self, repo, definicion, origen="sync"):
		"""La ÚNICA forma de escribir el espejo de un ruleset.

		Existe por la segunda regla de construcción: un objeto del espejo, un método que
		lo actualiza. El día que un webhook traiga un ruleset cambiado va a entrar por
		acá, y no por un camino paralelo que diverja de éste.

		Args:
			repo: registro de `repo.repository`.
			definicion: el objeto tal como lo devolvió GitHub.
			origen: `sync` o `webhook`.

		Returns:
			repo.ruleset: la fila del espejo, creada o actualizada.
		"""
		valores = {
			"repository_id": repo.id,
			"github_id": definicion.get("id"),
			"name": definicion.get("name"),
			"enforcement": definicion.get("enforcement"),
			"definition_json": json.dumps(
				_comparable(definicion), sort_keys=True, default=str),
			"present": True,
			"last_seen_at": fields.Datetime.now(),
			"origin": origen,
		}
		fila = self.search([
			("repository_id", "=", repo.id),
			("github_id", "=", definicion.get("id")),
		], limit=1)
		if not fila:
			nueva = self.create(valores)
			# También en el alta, y sobre todo en el alta: el homónimo aparece justo
			# cuando GitHub da un id nuevo a un ruleset recreado.
			nueva._retirar_homonimos()
			return nueva
		# No se reescribe lo que no cambió: un `write` con los mismos datos igual genera
		# un UPDATE con su write_date, y sobre una fila que varios jobs tocan eso basta
		# para matar al de al lado. `last_seen_at` sí cambia siempre —es el dato de
		# cuándo se supo— así que se compara el resto y se escribe lo mínimo.
		iguales = all(fila[campo] == valores[campo]
					  for campo in ("name", "enforcement", "definition_json", "present"))
		fila.write({"last_seen_at": valores["last_seen_at"], "origin": origen}
				   if iguales else valores)
		fila._retirar_homonimos()
		return fila

	def _retirar_homonimos(self):
		"""Da de baja las filas VIEJAS con el mismo nombre y otro id de GitHub.

		LO ENCONTRÓ EL ENSAYO DE B4.4, CORRIENDO DOS VECES. Un ruleset borrado y vuelto a
		crear con el mismo nombre es, para la política, el MISMO objeto gobernado — pero
		GitHub le da un id nuevo, así que el espejo terminaba con dos filas homónimas: la
		vieja en `present = False` y la nueva viva. Y como el drift busca por NOMBRE, le
		tocaba la muerta y reportaba «el ruleset que aplicamos ya no está» sobre uno que
		estaba ahí, con severidad crítica.

		Es la peor forma del falso positivo: la que grita más fuerte. Una alarma crítica
		sobre algo sano enseña a desconfiar de las alarmas críticas.

		No se borran las filas viejas: dejan de estar presentes, que es lo que de verdad
		pasó, y conservan cuándo se las vio por última vez.
		"""
		self.ensure_one()
		homonimos = self.search([
			("repository_id", "=", self.repository_id.id),
			("name", "=", self.name),
			("id", "!=", self.id),
			("present", "=", True),
		])
		if homonimos:
			homonimos.write({"present": False})

	def definicion(self):
		"""La definición observada, ya normalizada."""
		self.ensure_one()
		try:
			return json.loads(self.definition_json or "{}")
		except ValueError:
			return {}
