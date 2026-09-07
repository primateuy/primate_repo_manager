# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El panel de salud — páginas 3a y 1b del entregable de diseño.

TRES NÚMEROS, UNA FRASE Y UN BOTÓN. Es todo lo que ve alguien que no opera. El detalle
queda plegado debajo y lo abre quien lo necesita.

LA REGLA QUE MANDA EN TODO ESTE ARCHIVO: **el día uno se muestra sin maquillaje.** 0 % es
0 %, y cuando no hay regla contra la cual medir se muestra un guión y se dice por qué —
nunca un cero que parezca un logro ni un verde que parezca salud. Un panel que en su
primera corrida muestra buenos números sobre una organización que todavía no gobierna nada
enseña a no creerle, y después no hay forma de recuperar eso.

Y LO QUE NO SE PUDO LEER NO SE CUENTA COMO BUENO. Los repositorios que la auditoría no
alcanzó a leer no entran en los porcentajes: se nombran aparte, con su causa. Meterlos en
el denominador los contaría como incumplidores; sacarlos sin decirlo los contaría como
sanos. Ninguna de las dos es cierta.
"""
from odoo import api, fields, models, _

# Las ramas que la política gobierna vienen de `repo_rules`: la misma lista que usa el
# armado de rulesets. Medir el cumplimiento contra un conjunto de roles y aplicarlo
# sobre otro es la clase de desfase que no se ve hasta que alguien compara los dos
# números.
from .repo_rules import ROLES_GOBERNADOS  # noqa: F401

# Cuántos días mira la métrica de convención. Sale del entregable: «últimos 30 días».
VENTANA_CONVENCION = 30


class RepoHealthPanel(models.AbstractModel):
	_name = "repo.health.panel"
	_description = "Panel de salud de los repositorios"

	# ------------------------------------------------------------------
	# Lo que la pantalla pide, en una sola llamada
	# ------------------------------------------------------------------

	@api.model
	def datos(self, backend_id=None):
		"""Todo el panel de una vez.

		Una llamada y no seis: la pantalla se abre entera o no se abre, y seis llamadas
		que se resuelven a distinto tiempo dan una pantalla que se arma a pedazos delante
		de quien la mira.
		"""
		conexiones = self.env["repo.backend"].search([])
		if not conexiones:
			return {"hay_conexion": False}
		# CUÁL CONEXIÓN. Con más de una, elegir la primera alfabéticamente es arbitrario y
		# se nota: el panel mostraba producción cuando quien miraba venía de trabajar en el
		# sandbox. Se ofrece elegir, y por defecto se abre la que TIENE algo que mostrar —
		# la de la auditoría más reciente—, que es la que casi siempre se quiere ver.
		backend = self.env["repo.backend"].browse(backend_id) if backend_id else None
		if not backend or backend not in conexiones:
			ultima = self.env["repo.audit.run"].search(
				[("state", "in", ("done", "partial"))], order="id desc", limit=1)
			backend = ultima.backend_id or conexiones[0]

		Run = self.env["repo.audit.run"]
		corridas = Run.search(
			[("backend_id", "=", backend.id), ("state", "in", ("done", "partial"))],
			order="id desc", limit=2)
		corrida = corridas[:1]
		anterior = corridas[1:2]

		return {
			"hay_conexion": True,
			"conexion": {"id": backend.id, "nombre": backend.name,
						 "cuenta": backend.owner_login},
			"conexiones": [{"id": c.id, "nombre": c.name, "cuenta": c.owner_login}
						   for c in conexiones],
			"corrida": self._resumen_de_corrida(corrida, anterior),
			"numeros": self._tres_numeros(backend, corrida, anterior),
			"estado": self._frase_de_estado(backend, corrida),
			"detalle": self._detalle(backend, corrida),
		}

	# ------------------------------------------------------------------

	def _resumen_de_corrida(self, corrida, anterior):
		if not corrida:
			return {"hubo": False}
		lineas = corrida.line_ids
		sin_leer = lineas.filtered(lambda l: l.state == "error")
		return {
			"hubo": True,
			"id": corrida.id,
			"cuando": corrida.finished_at or corrida.started_at,
			"leidos": len(lineas) - len(sin_leer),
			"total": len(lineas),
			# UNA CORRIDA SIN DETALLE POR REPOSITORIO NO DICE «0 DE 0». Las corridas
			# anteriores al registro de líneas existen y sus hallazgos valen; lo que no
			# tienen es el desglose. Decir «0 de 0 leídos» sobre una auditoría que leyó
			# 47 repositorios es peor que no decir nada.
			"sin_detalle": not lineas,
			"es_la_primera": not anterior,
			"sin_leer": [
				{"repositorio": l.repository_id.full_name, "causa": l.error or _("sin causa registrada")}
				for l in sin_leer
			],
		}

	# ------------------------------------------------------------------
	# Los tres números
	# ------------------------------------------------------------------

	def _tres_numeros(self, backend, corrida, anterior):
		return [
			self._numero_protegidas(backend),
			self._numero_convencion(backend),
			self._numero_hallazgos(corrida, anterior,
								   self._hay_politica(backend)),
		]

	def _numero_protegidas(self, backend):
		"""Ramas principales protegidas. El tramo «sin leer» se muestra aparte."""
		Branch = self.env["repo.branch"]
		gobernadas = Branch.search([
			("repository_id.backend_id", "=", backend.id),
			("role", "in", ROLES_GOBERNADOS)])
		ilegibles = gobernadas.filtered(lambda b: not b.protection_readable)
		medibles = gobernadas - ilegibles
		protegidas = medibles.filtered("protected")
		return {
			"clave": "protegidas",
			"titulo": _("Ramas principales protegidas"),
			# 0 % ES 0 %. Sólo se muestra un guión cuando NO HAY NADA QUE MEDIR, que es
			# distinto de medir cero.
			"valor": round(100.0 * len(protegidas) / len(medibles)) if medibles else None,
			"unidad": "%",
			"pie": (_("%(n)s de %(total)s") % {"n": len(protegidas), "total": len(medibles)}
					if medibles else _("todavía no hay ramas de entorno relevadas")),
			"sin_leer": len(ilegibles),
			"explicacion": _(
				"Protegida significa que nadie puede escribir directo ni borrarla; los "
				"cambios pasan por revisión. Se cuentan las ramas de base, producción, "
				"staging y support."),
		}

	def _numero_convencion(self, backend):
		"""Commits con convención, últimos 30 días.

		SIN REGLA NO HAY NÚMERO. Si ningún repositorio tiene una plantilla con patrón de
		commit, no se muestra 0 % —que se leería como «todos incumplen»— sino un guión y
		el motivo.
		"""
		desde = fields.Datetime.subtract(fields.Datetime.now(), days=VENTANA_CONVENCION)
		muestras = self.env["repo.commit.sample"].search([
			("repository_id.backend_id", "=", backend.id),
			("committed_at", ">=", desde)])
		hay_regla = bool(self.env["repo.policy.template"].search_count(
			[("commit_message_pattern", "!=", False)]))
		if not hay_regla or not muestras:
			return {
				"clave": "convencion",
				"titulo": _("Commits con convención"),
				"valor": None,
				"unidad": "",
				"pie": (_("no hay convención definida: sin regla, no hay número")
						if not hay_regla
						else _("no hay commits relevados en los últimos %s días")
							 % VENTANA_CONVENCION),
				"explicacion": _(
					"Un commit con convención dice qué cambió y por qué, en un formato "
					"que se puede leer por máquina."),
			}
		buenos = muestras.filtered("message_ok")
		return {
			"clave": "convencion",
			"titulo": _("Commits con convención"),
			"valor": round(100.0 * len(buenos) / len(muestras)),
			"unidad": "%",
			"pie": _("%(n)s de %(total)s · últimos %(dias)s días") % {
				"n": len(buenos), "total": len(muestras), "dias": VENTANA_CONVENCION},
			"explicacion": _(
				"Un commit con convención dice qué cambió y por qué, en un formato que se "
				"puede leer por máquina."),
		}

	def _numero_hallazgos(self, corrida, anterior, hay_politica=True):
		if not corrida:
			return {"clave": "hallazgos", "titulo": _("Hallazgos abiertos"), "valor": None,
					"unidad": "", "pie": _("todavía no se auditó")}
		criticos = len(corrida.finding_ids.filtered(lambda f: f.severity == "critical"))
		return {
			"clave": "hallazgos",
			"titulo": _("Hallazgos abiertos"),
			"valor": len(corrida.finding_ids),
			"unidad": "",
			"criticos": criticos,
			# CERO NO ES SIEMPRE UNA BUENA NOTICIA, y el día uno hay que decirlo.
			# El chip de al lado ya dice cuántos críticos hay: repetirlo acá gasta la
			# línea que sirve para decir OTRA cosa.
			"pie": (_("cero porque nada se exige todavía, no porque todo esté bien")
					if not corrida.finding_ids and not hay_politica
					else _("en %s repositorio(s)")
						 % len(set(corrida.finding_ids.mapped("repository_id.id")))),
			"delta": (len(corrida.finding_ids) - len(anterior.finding_ids)
					  if anterior else None),
			"explicacion": _("Lo que la última auditoría encontró fuera de la política."),
		}

	def _hay_politica(self, backend):
		"""¿Esta conexión tiene algo contra qué medirse?

		POR CONEXIÓN Y NO GLOBAL. Con la pregunta global, una cuenta recién conectada
		heredaba el «sí hay política» de otra que sí estaba clasificada, y su día uno se
		mostraba como si tuviera reglas: exactamente el maquillaje que este panel evita.
		"""
		return bool(self.env["repo.repository"].search_count(
			[("backend_id", "=", backend.id), ("classification", "!=", False)]))

	# ------------------------------------------------------------------
	# La frase de estado
	# ------------------------------------------------------------------

	def _frase_de_estado(self, backend, corrida):
		"""Qué decir arriba, en una frase, y con qué chip.

		Se redacta desde los hallazgos críticos. Sin política asignada no se dice «todo
		bien»: se dice que no se puede saber, que es la verdad.
		"""
		if not corrida:
			return {"chip": _("SIN AUDITAR"), "tono": "quiet",
					"frase": _("Todavía no se auditó esta conexión. El panel no puede "
							   "decir nada hasta que haya una lectura.")}
		if not self._hay_politica(backend):
			return {
				"chip": _("SIN POLÍTICA"), "tono": "quiet",
				"frase": _(
					"Ya se leyeron los repositorios de %(cuenta)s. Hasta que no haya una "
					"plantilla de política asignada, este panel no puede decir qué está "
					"bien ni qué está mal."
				) % {"cuenta": backend.owner_login},
			}
		criticos = corrida.finding_ids.filtered(lambda f: f.severity == "critical")
		if not criticos:
			return {"chip": _("DENTRO DE LA POLÍTICA"), "tono": "done",
					"frase": _("No hay hallazgos críticos abiertos.")}
		repos = criticos.mapped("repository_id.full_name")
		return {
			"chip": _("REQUIERE ATENCIÓN"), "tono": "error",
			"frase": _(
				"Hay %(n)s hallazgo(s) crítico(s) abierto(s) en %(repos)s "
				"repositorio(s)."
			) % {"n": len(criticos), "repos": len(set(repos))},
		}

	# ------------------------------------------------------------------
	# El detalle, plegado
	# ------------------------------------------------------------------

	def _detalle(self, backend, corrida):
		if not corrida:
			return {"hay": False}
		return {
			"hay": True,
			"por_gravedad": self._por_gravedad(corrida),
			"por_tipo": self._por_tipo(backend),
			"sin_dueno": self._sin_dueno(backend),
		}

	def _por_gravedad(self, corrida):
		etiquetas = dict(
			self.env["repo.audit.finding"]._fields["severity"].selection)
		filas = []
		for clave in ("critical", "high", "medium", "info"):
			hallazgos = corrida.finding_ids.filtered(lambda f: f.severity == clave)
			if not hallazgos:
				continue
			filas.append({
				"clave": clave,
				"etiqueta": etiquetas.get(clave, clave),
				"cuantos": len(hallazgos),
				"repos": len(set(hallazgos.mapped("repository_id.full_name"))),
			})
		return filas

	def _por_tipo(self, backend):
		"""Por clasificación, con su porcentaje de ramas protegidas.

		Los repositorios SIN LEER van en su propia fila y no cuentan para ningún
		porcentaje: su estado es desconocido, y desconocido no es ni bueno ni malo.
		"""
		etiquetas = dict(
			self.env["repo.repository"]._fields["classification"].selection)
		filas = []
		Repo = self.env["repo.repository"]
		for clave, etiqueta in list(etiquetas.items()) + [(False, _("Sin clasificar"))]:
			repos = Repo.search([("backend_id", "=", backend.id),
								 ("classification", "=", clave)])
			if not repos:
				continue
			ramas = self.env["repo.branch"].search([
				("repository_id", "in", repos.ids),
				("role", "in", ROLES_GOBERNADOS)])
			medibles = ramas.filtered("protection_readable")
			filas.append({
				"etiqueta": etiqueta,
				"repos": len(repos),
				"protegidas": (round(100.0 * len(medibles.filtered("protected"))
									 / len(medibles)) if medibles else None),
				"sin_leer": len(ramas) - len(medibles),
			})
		return filas

	def _sin_dueno(self, backend):
		"""Cuentas con acceso a ESTA conexión que ninguna persona reconoce como propia.

		DE ESTA CONEXIÓN Y NO DE TODAS. Las personas son un modelo compartido —la misma
		cuenta de GitHub puede colaborar en varias— así que contarlas todas le atribuía a
		una conexión recién creada las 17 cuentas huérfanas de otra. El vínculo con la
		conexión pasa por los colaboradores de sus repositorios, que es lo que significa
		«tiene acceso acá».
		"""
		colaboraciones = self.env["repo.collaborator"].search(
			[("repository_id.backend_id", "=", backend.id)])
		miembros = colaboraciones.mapped("member_id")
		huerfanas = miembros.filtered(lambda m: not m.employee_id)
		return {
			"cuantas": len(huerfanas),
			"total": len(miembros),
			"quienes": huerfanas.mapped("github_login")[:8],
		}
