# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Promover un módulo: elegir qué copia gana cuando divergen — página 5b del diseño.

LA DECISIÓN NO SE AUTOMATIZA, Y ÉSTE ES TODO EL PUNTO. Cuando las copias de un módulo no
son iguales, la promoción **no se puede armar sola**: alguien tiene que elegir cuál va a
existir de ahora en más, sabiendo qué se pierde. Este archivo se ocupa de que esa elección
sea explícita, informada y sin empujones.

TRES COSAS QUE NO HACE, Y POR QUÉ:

· **No preselecciona ninguna.** El botón de continuar nace deshabilitado. Preseleccionar es
  decidir por otro y después pedirle que confirme la decisión propia — que es la forma más
  educada de sacarle la decisión de las manos.

· **No usa «la más nueva» como criterio.** Ni como default ni como orden. La copia más
  reciente puede ser la que perdió un parche; la versión declarada en el manifiesto es un
  texto que alguien escribió a mano, no una verdad. Las tarjetas van ordenadas por nombre
  de repositorio, que es un orden estable y que no sugiere nada.

· **No etiqueta una como «referencia».** El mockup la etiqueta y acá no, por instrucción
  explícita: cualquier distintivo, por informativo que sea, funciona como recomendación.
  Queda anotado como desvío deliberado del diseño en `COBERTURA-DEL-DISENO.md`.

LO QUE SÍ HACE: decir, para cada opción, **qué desaparece si la elegís** — con los hechos
que tenemos y sin inventar los que no.

EL DIFF ES LA ÚNICA CONSULTA CARA, Y VA BAJO PEDIDO. Ver qué archivos difieren entre dos
copias cuesta dos lecturas de árbol, y sólo se hace cuando alguien lo pide sobre un par
concreto. Nunca al abrir la pantalla, y nunca para las N×N combinaciones.
"""
from odoo import _, api, models
from odoo.exceptions import UserError


class RepoModulePromotion(models.AbstractModel):
	_name = "repo.module.promotion"
	_description = "Elegir qué copia de un módulo gana"

	# ------------------------------------------------------------------
	# Lo que la pantalla lee
	# ------------------------------------------------------------------

	@api.model
	def opciones(self, module_id):
		"""Las copias del módulo, con sus hechos y su consecuencia.

		Todo lo de acá es BARATO: sale del inventario que ya se escaneó. Ninguna llamada a
		GitHub. Abrir la pantalla no puede costar una tanda de lecturas.
		"""
		modulo = self.env["repo.module"].browse(module_id)
		if not modulo.exists():
			raise UserError(_("Ese módulo no existe."))
		copias = modulo.copy_ids.sorted(
			# ORDEN ESTABLE Y SIN SUGERENCIA: por repositorio. Ordenar por versión o por
			# fecha pondría una arriba, y lo de arriba se lee como lo recomendado.
			lambda c: (c.repository_id.full_name or "", c.line or ""))

		# Las que son idénticas entre sí se agrupan por su SHA de subárbol: elegir entre
		# dos copias iguales no es una decisión, y presentarlas como si lo fuera hace
		# ruido sobre las que sí difieren.
		grupos = {}
		for copia in copias:
			grupos.setdefault(copia.tree_sha or "sin-leer", []).append(copia)

		opciones = []
		for copia in copias:
			iguales = [c for c in grupos.get(copia.tree_sha or "sin-leer", [])
					   if c != copia]
			opciones.append({
				"id": copia.id,
				"repositorio": copia.repository_id.full_name,
				"rama": copia.branch_id.name or copia.line or "",
				"ruta": copia.path,
				"version": copia.version or None,
				"arbol": copia.tree_sha or None,
				"legible": copia.manifest_readable,
				"por_que_no": copia.manifest_error or None,
				"identica_a": [c.repository_id.full_name for c in iguales],
				"consecuencia": self._consecuencia(copia, copias),
			})
		return {
			"modulo": {"id": modulo.id, "nombre": modulo.technical_name,
					   "divergen": modulo.divergent,
					   "detalle": modulo.divergence_detail},
			"opciones": opciones,
			# Sin divergencia no hay nada que elegir y la pantalla lo dice: la elección
			# forzada es para cuando hay algo que perder.
			"hay_que_elegir": modulo.divergent and len(grupos) > 1,
		}

	def _consecuencia(self, elegida, todas):
		"""«Si elegís ésta, qué desaparece» — con los hechos que hay.

		SIN INVENTAR LO QUE NO SABEMOS. El diseño muestra frases como «14 commits atrás»:
		eso exige comparar historias, que es otra consulta y de otro costo. Acá se dice lo
		que el inventario sostiene: qué copias se retiran, cuáles tenían contenido distinto
		—y por lo tanto pierden algo— y cuáles eran idénticas, que no pierden nada.
		"""
		distintas = [c for c in todas
					 if c != elegida and c.tree_sha != elegida.tree_sha]
		iguales = [c for c in todas
				   if c != elegida and c.tree_sha == elegida.tree_sha]
		if not distintas:
			return _(
				"Las otras %s copia(s) son idénticas a ésta: no se pierde nada, sólo dejan "
				"de estar duplicadas.") % len(iguales)
		nombres = ", ".join(c.repository_id.full_name for c in distintas)
		# La concordancia importa más de lo que parece: esta frase es lo último que
		# alguien lee antes de decidir un borrado, y una que suena mal se lee dos veces
		# por el motivo equivocado.
		if len(distintas) == 1:
			cuerpo = _(
				"Lo que %s tenga distinto de ésta DESAPARECE de ese repositorio") % nombres
		else:
			cuerpo = _(
				"Lo que %s tengan distinto de ésta DESAPARECE de esos repositorios"
			) % nombres
		return _(
			"Se retiran las otras %(cuantas)s copia(s). %(cuerpo)s: si hay algo ahí que "
			"quieras conservar, hay que llevarlo aparte antes."
		) % {"cuantas": len(distintas) + len(iguales), "cuerpo": cuerpo}

	# ------------------------------------------------------------------
	# El diff: la única consulta cara, y sólo cuando se pide
	# ------------------------------------------------------------------

	@api.model
	def diff(self, copia_a_id, copia_b_id):
		"""Qué archivos difieren entre dos copias. DOS lecturas de árbol, ni una más.

		POR QUÉ NO HACE FALTA BAJAR LOS ARCHIVOS. Git nombra cada archivo por el hash de su
		contenido, así que dos rutas con el mismo hash son idénticas byte a byte y dos
		hashes distintos son un cambio real. Comparar los árboles alcanza para decir qué
		archivos se agregaron, cuáles se quitaron y cuáles cambiaron — sin descargar una
		sola línea.

		Lo que esto NO da es el diff línea por línea: para eso sí habría que bajar los dos
		contenidos, y es otra decisión con otro costo. La pantalla dice qué archivos
		difieren y no finge mostrar más que eso.
		"""
		Copia = self.env["repo.module.copy"]
		a, b = Copia.browse(copia_a_id), Copia.browse(copia_b_id)
		if not (a.exists() and b.exists()):
			raise UserError(_("Alguna de las dos copias ya no existe."))
		if a.module_id != b.module_id:
			raise UserError(_("Son copias de módulos distintos: no hay nada que comparar."))

		cliente = a.repository_id.backend_id.client()
		archivos_a = self._archivos(cliente, a)
		archivos_b = self._archivos(cliente, b)

		rutas = sorted(set(archivos_a) | set(archivos_b))
		filas = []
		for ruta in rutas:
			en_a, en_b = archivos_a.get(ruta), archivos_b.get(ruta)
			if en_a == en_b:
				continue
			filas.append({
				"ruta": ruta,
				"estado": ("solo_en_a" if not en_b else
						   "solo_en_b" if not en_a else "distinto"),
			})
		return {
			"a": a.repository_id.full_name,
			"b": b.repository_id.full_name,
			"iguales": len(rutas) - len(filas),
			"filas": filas,
			# Se dice qué se comparó y qué no: un diff que no aclara su alcance se lee
			# como si mostrara todo.
			"alcance": _(
				"Comparación por archivo: dos archivos con el mismo contenido tienen el "
				"mismo identificador en git. No incluye el diff línea por línea."),
		}

	def _archivos(self, cliente, copia):
		"""{ruta relativa: identificador del contenido} para una copia."""
		rama = copia.branch_id.name or copia.line
		arbol = cliente.get("/repos/%s/git/trees/%s?recursive=1" % (
			copia.repository_id.full_name, rama)) or {}
		if arbol.get("truncated"):
			# Lo mismo que en todo el módulo: un árbol truncado no permite afirmar nada
			# sobre lo que no vino, así que no se afirma.
			raise UserError(_(
				"El árbol de %(repo)s@%(rama)s vino truncado: no se puede comparar sin "
				"ver todos los archivos.") % {
					"repo": copia.repository_id.full_name, "rama": rama})
		prefijo = copia.path + "/"
		return {
			e["path"][len(prefijo):]: e["sha"]
			for e in (arbol.get("tree") or [])
			if e.get("type") == "blob" and (e.get("path") or "").startswith(prefijo)
		}

	# ------------------------------------------------------------------
	# Lo que la elección produce: un plan, y nada más
	# ------------------------------------------------------------------

	@api.model
	def armar_plan(self, module_id, copia_elegida_id, destino_repo_id, limpiar=True):
		"""Arma el plan de promoción. NO escribe en GitHub: eso lo hace el apply.

		El asistente redacta; la aprobación en dos niveles y la aplicación son las de
		siempre. Un camino corto desde acá hasta GitHub sería una puerta de servicio a las
		mismas escrituras.
		"""
		import json

		# LA ELECCIÓN ES OBLIGATORIA, Y ESTA COMPROBACIÓN VA PRIMERA.
		#
		# Estaba más abajo y era código muerto: la comprobación genérica de «falta algo»
		# saltaba antes y respondía «falta el módulo, la copia o el destino», que es un
		# mensaje que no dice cuál de las tres ni por qué importa. Lo encontró una mutación
		# —sacar esta guarda no ponía ningún test en rojo—, que es justamente para lo que
		# sirven: un test puede pasar por el motivo equivocado.
		if not copia_elegida_id:
			raise UserError(_(
				"Hay que elegir qué copia gana. No hay opción por defecto: la que se "
				"elija es la que va a existir de ahora en más, y lo que las otras tengan "
				"distinto desaparece."))
		modulo = self.env["repo.module"].browse(module_id)
		elegida = self.env["repo.module.copy"].browse(copia_elegida_id)
		destino = self.env["repo.repository"].browse(destino_repo_id)
		if not (modulo.exists() and elegida.exists() and destino.exists()):
			raise UserError(_("Falta el módulo, la copia elegida o el destino."))
		if elegida.module_id != modulo:
			raise UserError(_("Esa copia no es de este módulo."))

		plan = self.env["repo.write.plan"].create({
			"name": _("Promoción de %s") % modulo.technical_name,
			"backend_id": modulo.backend_id.id,
			"note": _(
				"Gana la copia de %(repo)s. Las demás se retiran; lo que tuvieran distinto "
				"desaparece de sus repositorios."
			) % {"repo": elegida.repository_id.full_name},
		})
		rama_destino = elegida.branch_id.name or elegida.line
		copia_op = self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "module_copy", "sequence": 10,
			"repository_id": destino.id, "target": elegida.path,
			"payload_json": json.dumps({
				"origen_repo": elegida.repository_id.full_name,
				"origen_rama": rama_destino,
				"ruta": elegida.path, "modulo": modulo.technical_name,
				"destino_rama": rama_destino,
				"arbol_esperado": elegida.tree_sha,
			}),
		})
		if limpiar:
			for n, otra in enumerate(modulo.copy_ids - elegida):
				self.env["repo.write.operation"].create({
					"plan_id": plan.id, "kind": "module_delete", "sequence": 20 + n * 10,
					"repository_id": otra.repository_id.id, "target": otra.path,
					"depends_on_ids": [(6, 0, copia_op.ids)],
					"payload_json": json.dumps({
						"ruta": otra.path, "modulo": modulo.technical_name,
						"rama": otra.branch_id.name or otra.line,
						"arbol_esperado": otra.tree_sha,
						"copiado_a": destino.full_name,
					}),
				})
		# EL AVISO DE DESPLIEGUE, en el plan y no en un comentario: las instancias que
		# tomaban el módulo de esos repositorios necesitan un cambio de addons_path que
		# esta aplicación no hace. Un módulo que saca código sin decirlo rompe
		# producciones ajenas en silencio.
		plan.message_post(body=_(
			"<b>Tarea manual pendiente al aplicar este plan.</b> Las instancias que hoy "
			"cargan «%(modulo)s» desde %(repos)s van a necesitar un cambio en su "
			"configuración de addons para tomarlo de %(destino)s. Repo Manager no hace "
			"ese cambio."
		) % {
			"modulo": modulo.technical_name,
			"repos": ", ".join((modulo.copy_ids - elegida).mapped(
				"repository_id.full_name")) or _("(ninguno: no se limpia nada)"),
			"destino": destino.full_name,
		})
		return {"plan_id": plan.id, "operaciones": len(plan.operation_ids)}
