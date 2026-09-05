# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Qué módulos Odoo viven en cada repositorio, y cuáles están duplicados.

Es la base del ciclo de vida de módulos (bloque D): un módulo nace en el repo de un
cliente, se copia a otros porque sirve, y en algún momento conviene promoverlo a un repo
general y sacarlo de los particulares. Nada de eso se puede decidir sin saber primero
dónde está cada uno y si las copias siguen siendo la misma cosa.

CÓMO SE AVERIGUA SIN BAJAR MEDIO REPOSITORIO. El árbol recursivo de git
—`GET /git/trees/{rama}?recursive=1`— devuelve TODO el árbol de una rama en UNA llamada,
con la ruta y el SHA de cada entrada. De ahí salen los `__manifest__.py` por su ruta, sin
caminar directorios.

Y LA DIVERGENCIA SALE GRATIS. Ese mismo árbol trae, para cada subdirectorio, una entrada
de tipo `tree` con su propio SHA, que es un hash de contenido de TODO el subárbol. Dos
copias con el mismo SHA de directorio son idénticas byte a byte; dos SHAs distintos son
divergencia. Una comparación por copia y cero llamadas extra.

Lo que ese hash NO dice es en qué difieren ni cuál va adelante. Eso es caro —hay que bajar
las dos y compararlas— y es humano, así que se pide aparte y sólo sobre las que ya se sabe
que divergieron.
"""
import ast
import base64
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

MANIFIESTO = "__manifest__.py"

# Los roles de rama que representan una LÍNEA DE VERSIÓN. Es lo que se escanea: un módulo
# se promueve entre líneas (17.0, 19.0), no entre ramas de trabajo. Escanear todo sería
# multiplicar por cinco las llamadas para inventariar cinco veces lo mismo.
ROLES_DE_LINEA = ("base", "prod")


class RepoModule(models.Model):
	_name = "repo.module"
	_description = "Módulo Odoo, visto en uno o más repositorios"
	_order = "technical_name"

	backend_id = fields.Many2one(
		"repo.backend", string="Conexión", required=True, ondelete="cascade", index=True)
	technical_name = fields.Char(
		string="Nombre técnico", required=True, index=True,
		help="El nombre de la carpeta, que es como Odoo lo identifica.")
	display_name_manifest = fields.Char(string="Nombre en el manifiesto")

	copy_ids = fields.One2many("repo.module.copy", "module_id", string="Copias")
	copy_count = fields.Integer(string="Copias", compute="_compute_copias")
	repository_count = fields.Integer(
		string="Repositorios", compute="_compute_copias", search="_search_repository_count",
		help="En cuántos repositorios distintos aparece. Más de uno es candidato a "
			 "promoción.")
	divergent = fields.Boolean(
		string="Las copias divergieron", compute="_compute_copias",
		search="_search_divergent",
		help="Verdadero cuando dos copias de la misma línea de versión tienen distinto "
			 "SHA de subárbol, o sea distinto contenido.")
	divergence_detail = fields.Char(
		string="Dónde divergen", compute="_compute_copias")

	_name_uniq = models.Constraint(
		"UNIQUE (backend_id, technical_name)",
		"Ese módulo ya está registrado en esta conexión.")

	@api.depends("copy_ids.tree_sha", "copy_ids.repository_id", "copy_ids.line")
	def _compute_copias(self):
		"""La divergencia se compara DENTRO de cada línea de versión, no entre líneas.

		Que `17.0` y `19.0` del mismo módulo tengan distinto contenido no es divergencia:
		es que son versiones distintas, que es lo normal y lo esperable. Compararlas
		marcaría como divergente a todo módulo que exista en dos versiones, o sea a casi
		todos, y el dato dejaría de significar nada.
		"""
		for modulo in self:
			copias = modulo.copy_ids
			modulo.copy_count = len(copias)
			modulo.repository_count = len(copias.mapped("repository_id"))
			lineas_rotas = []
			for linea in set(copias.mapped("line")):
				de_la_linea = copias.filtered(lambda c, l=linea: c.line == l)
				shas = set(de_la_linea.mapped("tree_sha")) - {False}
				if len(shas) > 1:
					lineas_rotas.append(linea or _("sin línea"))
			modulo.divergent = bool(lineas_rotas)
			modulo.divergence_detail = ", ".join(sorted(lineas_rotas)) or False


	# POR QUÉ ESTOS CAMPOS TIENEN `search` Y NO `store=True`.
	#
	# Guardarlos parece más simple y es la trampa que ya pagamos en A10: un campo calculado
	# y almacenado hace que Odoo ESCRIBA la fila cada vez que cambia una dependencia, y
	# `repo.module` es una fila COMPARTIDA —el mismo módulo vive en varios repositorios—
	# que varios jobs de escaneo tocan en paralelo. Almacenarlos sería volver a poner a los
	# jobs a matarse entre sí, ahora en el inventario.
	#
	# Con `search` los filtros funcionan igual y no se escribe nada. El precio es que no se
	# puede ORDENAR por estas columnas, que es exactamente el mismo precio que se aceptó
	# para los contadores de la corrida.

	# COMPARADORES ACEPTADOS. Odoo NORMALIZA el dominio antes de llamar al método de
	# búsqueda: un `("divergent", "=", True)` escrito en una vista llega acá como
	# `("divergent", "in", OrderedSet([True]))`. La primera versión de estos métodos sólo
	# contemplaba `=` y `!=`, y con `in` caía en la rama del else: **devolvía el filtro
	# INVERTIDO en silencio**. El filtro «con copias divergentes» mostraba los 192 módulos
	# del sandbox, que son justamente los que NO divergen.
	#
	# De ahí la regla que queda: un método de búsqueda que no entiende el comparador
	# **levanta excepción**, nunca adivina. Un filtro que devuelve lo contrario de lo que
	# dice es peor que uno que no anda, porque el que no anda se nota.
	COMPARADORES = ("=", "!=", "in", "not in")

	@api.model
	def _pedido_booleano(self, operador, valor):
		"""Traduce el comparador normalizado a «se buscan los verdaderos, sí o no»."""
		if operador not in self.COMPARADORES:
			raise ValueError(
				"Comparador no soportado en este filtro: %r. Agregarlo acá a propósito, "
				"no dejar que caiga en un default." % operador)
		if operador in ("in", "not in"):
			buscado = True in set(valor)
			negado = operador == "not in"
		else:
			buscado = bool(valor)
			negado = operador == "!="
		return buscado != negado

	def _search_repository_count(self, operador, valor):
		"""Filtra por en cuántos repositorios distintos aparece el módulo."""
		if operador not in ("=", "!=", "<", "<=", ">", ">="):
			raise ValueError(
				"Comparador no soportado para «repositorios»: %r." % operador)
		self.env.cr.execute("""
			SELECT module_id FROM repo_module_copy
			GROUP BY module_id HAVING COUNT(DISTINCT repository_id) %s %%s
		""" % operador, (valor,))
		return [("id", "in", [f[0] for f in self.env.cr.fetchall()])]

	def _search_divergent(self, operador, valor):
		"""Filtra por divergencia. Se calcula en Python porque la comparación es POR
		LÍNEA de versión, y eso no se expresa en un GROUP BY simple."""
		divergentes = self.search([]).filtered("divergent").ids
		return [("id", "in" if self._pedido_booleano(operador, valor) else "not in",
				 divergentes)]


class RepoModuleCopy(models.Model):
	_name = "repo.module.copy"
	_description = "Aparición de un módulo en un repositorio y una rama"
	_order = "module_id, repository_id, line"

	module_id = fields.Many2one(
		"repo.module", string="Módulo", required=True, ondelete="cascade", index=True)
	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True, ondelete="cascade",
		index=True)
	branch_id = fields.Many2one(
		"repo.branch", string="Rama", ondelete="set null", index=True)
	line = fields.Char(
		string="Línea de versión", index=True,
		help="La línea a la que pertenece la rama: 17.0, 19.0. Es la unidad en la que "
			 "tiene sentido comparar dos copias.")
	path = fields.Char(string="Ruta dentro del repositorio", required=True)

	# EL DATO QUE HACE BARATA LA DIVERGENCIA. Es el SHA del subárbol del directorio del
	# módulo: un hash de contenido de todos sus archivos. No hay que bajar nada para
	# comparar dos copias.
	tree_sha = fields.Char(string="SHA del subárbol", index=True)

	version = fields.Char(string="Versión del manifiesto")
	license_id = fields.Char(string="Licencia")
	author = fields.Char(string="Autor")
	depends_json = fields.Text(string="Depende de (JSON)")
	manifest_readable = fields.Boolean(
		string="Manifiesto legible", default=True,
		help="Falso cuando el archivo existe pero no se pudo leer o parsear. NO es lo "
			 "mismo que no tener manifiesto.")
	manifest_error = fields.Char(string="Por qué no se pudo leer")

	# Reglas de construcción de CLAUDE.md: cuándo se supo y por dónde entró.
	last_seen_at = fields.Datetime(string="Visto por última vez", index=True)
	source = fields.Selection(
		[("scan", "Escaneo de módulos"), ("webhook", "Evento de GitHub")],
		string="Origen del dato", default="scan", required=True)

	_copia_uniq = models.Constraint(
		"UNIQUE (module_id, repository_id, line)",
		"Ese módulo ya está registrado en esa línea de ese repositorio.")


class RepoRepositoryModuleScan(models.Model):
	"""El escaneo, colgado del repositorio: es de quien es el árbol."""

	_inherit = "repo.repository"

	module_copy_ids = fields.One2many(
		"repo.module.copy", "repository_id", string="Módulos")
	module_count = fields.Integer(string="Módulos", compute="_compute_module_count")

	@api.depends("module_copy_ids")
	def _compute_module_count(self):
		for repo in self:
			repo.module_count = len(repo.module_copy_ids)

	def action_scan_modules(self):
		"""Escanea los módulos de este repositorio. Sólo lee.

		Va como job propio y no dentro de la auditoría, por dos razones: escanear ~730
		árboles duplicaría el tiempo de una auditoría que hoy dura siete minutos, y el
		inventario de módulos cambia mucho más lento que los permisos. Se lo dispara
		cuando importa, no cada vez.
		"""
		for repo in self:
			repo.with_delay(channel="root.repo_manager")._job_scan_modules()
		return True

	def _job_scan_modules(self):
		self.ensure_one()
		cliente = self.backend_id.client()
		for rama in self.branch_ids.filtered(lambda b: b.role in ROLES_DE_LINEA):
			self._escanear_rama(cliente, rama)

	def _escanear_rama(self, cliente, rama):
		"""Un árbol, una llamada, todos los módulos de esa línea."""
		self.ensure_one()
		from .github_client import GithubError

		try:
			arbol = cliente.get(
				"/repos/%s/git/trees/%s?recursive=1" % (self.full_name, rama.name)) or {}
		except GithubError as exc:
			_logger.warning(
				"Repo Manager: no se pudo leer el árbol de %s@%s: %s",
				self.full_name, rama.name, exc)
			return self.env["repo.module.copy"]

		if arbol.get("truncated"):
			# EL ÁRBOL VINO CORTADO. Se dice, no se supone: informar «no tiene módulos»
			# sobre un árbol truncado es exactamente la clase de afirmación de más que
			# este módulo no hace. Ver los tres estados de protección en repo_sync.
			_logger.warning(
				"Repo Manager: el árbol de %s@%s vino truncado; el inventario de esa "
				"rama queda incompleto", self.full_name, rama.name)
			self._marcar_arbol_incompleto(rama)
			return self.env["repo.module.copy"]

		entradas = arbol.get("tree") or []
		# El SHA de cada subdirectorio, indexado por ruta: es lo que hace barata la
		# comparación entre copias.
		shas = {e["path"]: e["sha"] for e in entradas if e.get("type") == "tree"}
		vistos = self.env["repo.module.copy"]
		for entrada in entradas:
			if entrada.get("type") != "blob":
				continue
			ruta = entrada.get("path") or ""
			if not ruta.endswith("/" + MANIFIESTO) and ruta != MANIFIESTO:
				continue
			carpeta = ruta[: -(len(MANIFIESTO) + 1)] if "/" in ruta else ""
			if not carpeta:
				continue          # un manifiesto en la raíz no es un módulo instalable
			vistos |= self._registrar_copia(
				cliente, rama, carpeta, entrada.get("sha"), shas.get(carpeta))
		return vistos

	def _marcar_arbol_incompleto(self, rama):
		"""Deja constancia en la rama de que su inventario no se pudo completar."""
		self.ensure_one()
		rama.module_scan_truncated = True

	def _registrar_copia(self, cliente, rama, carpeta, blob_sha, tree_sha):
		"""Upsert de la copia. UN método, como manda la regla 2 de CLAUDE.md."""
		self.ensure_one()
		nombre = carpeta.rstrip("/").split("/")[-1]
		datos = self._leer_manifiesto(cliente, blob_sha)
		Modulo = self.env["repo.module"]
		modulo = Modulo.search([
			("backend_id", "=", self.backend_id.id),
			("technical_name", "=", nombre)], limit=1)
		if not modulo:
			modulo = Modulo.create({
				"backend_id": self.backend_id.id, "technical_name": nombre,
				"display_name_manifest": datos.get("name")})
		elif datos.get("name") and modulo.display_name_manifest != datos["name"]:
			modulo.display_name_manifest = datos["name"]

		import json

		valores = {
			"module_id": modulo.id,
			"repository_id": self.id,
			"branch_id": rama.id,
			"line": rama.name,
			"path": carpeta,
			"tree_sha": tree_sha,
			"version": datos.get("version"),
			"license_id": datos.get("license"),
			"author": datos.get("author"),
			"depends_json": json.dumps(datos.get("depends") or []),
			"manifest_readable": datos.get("_legible", True),
			"manifest_error": datos.get("_error", False),
			"last_seen_at": fields.Datetime.now(),
			"source": "scan",
		}
		Copia = self.env["repo.module.copy"]
		copia = Copia.search([
			("module_id", "=", modulo.id), ("repository_id", "=", self.id),
			("line", "=", rama.name)], limit=1)
		if not copia:
			return Copia.create(valores)
		# Sólo se escribe lo que cambió: un `write` con los mismos datos igual genera un
		# UPDATE, y sobre filas que varios jobs tocan eso alcanza para que se maten entre
		# sí. Regla 4 de CLAUDE.md, aprendida midiendo en A10.
		cambios = {c: v for c, v in valores.items()
				   if c != "last_seen_at" and copia[c] != v}
		cambios["last_seen_at"] = valores["last_seen_at"]
		copia.write(cambios)
		return copia

	def _leer_manifiesto(self, cliente, blob_sha):
		"""Baja y parsea un manifiesto. NUNCA con `eval`.

		Un `__manifest__.py` es un diccionario de Python, y la tentación de evaluarlo es
		obvia. Pero viene de repositorios que no controlamos del todo —forks de OCA, repos
		de cliente— y evaluarlo sería ejecutar código ajeno dentro de Odoo. `literal_eval`
		acepta literales y nada más: si alguien mete una llamada, falla en vez de correrla.
		"""
		if not blob_sha:
			return {"_legible": False, "_error": _("sin SHA del archivo")}
		try:
			blob = cliente.get("/repos/%s/git/blobs/%s" % (self.full_name, blob_sha)) or {}
			crudo = base64.b64decode(blob.get("content") or "").decode("utf-8")
			datos = ast.literal_eval(crudo)
			if not isinstance(datos, dict):
				raise ValueError("el manifiesto no es un diccionario")
			return datos
		except Exception as exc:  # noqa: BLE001 - se reporta, nunca se traga
			return {"_legible": False, "_error": str(exc)[:200]}
