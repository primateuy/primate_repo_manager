# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Copiar un módulo de un repositorio a otro, en UN commit.

LA PRIMERA OPERACIÓN QUE ESCRIBE CONTENIDO. Todas las anteriores tocan configuración
—protecciones, permisos, teams, rulesets— que GitHub guarda aparte del código. Ésta toca
el código, y eso cambia dos cosas.

UN COMMIT, NO N ARCHIVOS. La API de contenidos escribe un archivo por llamada: un módulo
de cuarenta archivos serían cuarenta commits, y una interrupción en el medio dejaría un
módulo a la mitad — que no compila, que nadie pidió y que no está en ningún estado
previsto. La API de datos de git permite construir el árbol entero y crear **un solo
commit**: o está completo o no está. Es más código y es la única forma correcta.

Y SIN FORCE. La referencia se mueve con `PATCH` sin `force`, así que si alguien empujó a
esa rama entre que leímos y escribimos, GitHub rechaza. Perder nuestro commit es molesto;
pisar el de otro es inaceptable.

CÓMO SE VERIFICA, Y POR QUÉ ES EXACTO. Git nombra cada árbol por su contenido: dos
directorios con los mismos archivos tienen el MISMO SHA de árbol, en cualquier repositorio.
Así que verificar la copia es comparar un hash contra otro — no hay que bajar nada ni
confiar en que la API hizo lo que dijo. Es la misma propiedad que hace barata la detección
de divergencia en el inventario, usada acá como condición de seguridad.
"""
import base64
import json
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from .github_client import GithubError


def _falla(mensaje):
	"""Un problema de ESTA operación, en el idioma que el motor entiende.

	El ciclo de `_aplicar` atrapa `GithubError` y lo convierte en «operación fallida»,
	dejando que el resto del plan siga su curso. Levantar `UserError` en cambio abortaría
	el apply entero: una operación rota tumbaría a las demás, que es justo lo contrario de
	lo que el motor decidió en F2. El idioma importa.
	"""
	return GithubError(422, mensaje)

_logger = logging.getLogger(__name__)


class RepoWriteOperationModule(models.Model):
	_inherit = "repo.write.operation"

	# ------------------------------------------------------------------
	# El payload
	# ------------------------------------------------------------------
	#   {"origen_repo": "org/uno", "origen_rama": "17.0",
	#    "ruta": "addons/mi_modulo", "modulo": "mi_modulo",
	#    "destino_rama": "17.0", "arbol_esperado": "<sha del subárbol en el origen>"}
	#
	# `repository_id` es el DESTINO: es el repositorio sobre el que se escribe, y es lo que
	# el resto del motor —el chequeo de alcance de la instalación, entre otros— espera
	# encontrar ahí.

	def _datos_modulo(self):
		self.ensure_one()
		try:
			datos = json.loads(self.payload_json or "{}")
		except (TypeError, ValueError) as exc:
			raise UserError(_("El payload de la copia no es JSON válido: %s") % exc)
		faltan = [c for c in ("origen_repo", "origen_rama", "ruta", "destino_rama")
				  if not datos.get(c)]
		if faltan:
			raise UserError(_(
				"Al payload de la copia le faltan datos: %s.") % ", ".join(faltan))
		return datos

	# ------------------------------------------------------------------
	# Leer: el estado previo del DESTINO
	# ------------------------------------------------------------------

	def _leer_modulo_destino(self, cliente):
		"""Dónde está la rama de destino y si el módulo ya está ahí.

		El punto de retorno es el SHA del commit de la rama. Es lo que después permite
		revertir sin adivinar: volver la referencia exactamente adonde estaba, y sólo si
		nadie la movió.
		"""
		self.ensure_one()
		datos = self._datos_modulo()
		rama = datos["destino_rama"]
		ref = cliente.get("/repos/%s/git/ref/heads/%s" % (
			self.repository_id.full_name, rama))
		if not ref or not (ref.get("object") or {}).get("sha"):
			raise _falla(_(
				"No se pudo leer la rama «%(rama)s» de %(repo)s. Sin saber dónde está no "
				"hay punto de retorno, así que no se escribe.")
				% {"rama": rama, "repo": self.repository_id.full_name})
		cabeza = ref["object"]["sha"]
		return {
			"rama": rama,
			"commit": cabeza,
			"arbol_del_modulo": self._sha_del_subarbol(
				cliente, self.repository_id.full_name, rama, datos["ruta"]),
		}

	@api.model
	def _sha_del_subarbol(self, cliente, repo, rama, ruta):
		"""El SHA del directorio, o False si no está. La evidencia de la verificación."""
		try:
			arbol = cliente.get(
				"/repos/%s/git/trees/%s?recursive=1" % (repo, rama)) or {}
		except GithubError:
			return False
		if arbol.get("truncated"):
			# Un árbol truncado no permite afirmar nada sobre lo que no vino. Se dice, no
			# se supone: es la misma regla que en el inventario y en las protecciones.
			raise _falla(_(
				"El árbol de %(repo)s@%(rama)s vino truncado, así que no se puede "
				"verificar la copia. No se escribe a ciegas.")
				% {"repo": repo, "rama": rama})
		for entrada in arbol.get("tree") or []:
			if entrada.get("type") == "tree" and entrada.get("path") == ruta:
				return entrada.get("sha")
		return False

	# ------------------------------------------------------------------
	# Ejecutar: un árbol, un commit, una referencia
	# ------------------------------------------------------------------

	def _copiar_modulo(self, cliente):
		self.ensure_one()
		datos = self._datos_modulo()
		destino = self.repository_id.full_name
		origen = datos["origen_repo"]
		ruta = datos["ruta"]

		# 1 · los archivos del módulo en el origen
		arbol_origen = cliente.get(
			"/repos/%s/git/trees/%s?recursive=1" % (origen, datos["origen_rama"])) or {}
		if arbol_origen.get("truncated"):
			raise _falla(_(
				"El árbol de %s vino truncado: no se puede copiar un módulo sin ver todos "
				"sus archivos.") % origen)
		archivos = [
			e for e in (arbol_origen.get("tree") or [])
			if e.get("type") == "blob" and (e.get("path") or "").startswith(ruta + "/")
		]
		if not archivos:
			raise _falla(_(
				"No hay archivos bajo «%(ruta)s» en %(origen)s. Copiar cero archivos "
				"dejaría un commit vacío que después parecería una copia hecha.")
				% {"ruta": ruta, "origen": origen})

		# 2 · los blobs, uno por uno, al repositorio DESTINO
		#
		# Los blobs son por repositorio: un SHA del origen no existe en el destino aunque
		# el contenido sea idéntico. Hay que bajarlos y volver a subirlos. Es la parte cara
		# —dos llamadas por archivo— y no hay atajo.
		entradas = []
		for archivo in archivos:
			contenido = cliente.get("/repos/%s/git/blobs/%s" % (origen, archivo["sha"]))
			nuevo = cliente.post("/repos/%s/git/blobs" % destino, {
				"content": contenido.get("content"),
				"encoding": contenido.get("encoding", "base64"),
			})
			entradas.append({
				"path": archivo["path"], "mode": archivo.get("mode", "100644"),
				"type": "blob", "sha": nuevo["sha"],
			})

		# 3 · el árbol nuevo, sobre el que ya está en el destino
		previo = self._leer_modulo_destino(cliente)
		arbol_nuevo = cliente.post("/repos/%s/git/trees" % destino, {
			"base_tree": previo["commit"], "tree": entradas,
		})

		# 4 · UN commit
		commit = cliente.post("/repos/%s/git/commits" % destino, {
			"message": _("[ADD] %(modulo)s: promovido desde %(origen)s\n\n"
						 "Copiado por Repo Manager desde %(origen)s@%(rama)s, ruta "
						 "%(ruta)s. Plan «%(plan)s».")
					   % {"modulo": datos.get("modulo") or ruta.split("/")[-1],
						  "origen": origen, "rama": datos["origen_rama"], "ruta": ruta,
						  "plan": self.plan_id.name},
			"tree": arbol_nuevo["sha"], "parents": [previo["commit"]],
		})

		# 5 · mover la rama SIN force
		#
		# Sin `force`, GitHub rechaza si alguien empujó entre que leímos la cabeza y ahora.
		# Perder nuestro commit es molesto; pisar el de otro es inaceptable.
		cliente.patch("/repos/%s/git/refs/heads/%s" % (destino, datos["destino_rama"]), {
			"sha": commit["sha"], "force": False,
		})
		return {"commit": commit["sha"], "archivos": len(entradas)}

	# ------------------------------------------------------------------
	# Verificar: el hash contra el hash
	# ------------------------------------------------------------------

	def _verificar_modulo_copiado(self, cliente):
		"""La copia vale si el subárbol del destino tiene el MISMO SHA que el del origen.

		No es «parece igual»: git nombra los árboles por su contenido, así que dos
		directorios con el mismo SHA son idénticos byte a byte, en cualquier repositorio.
		Es lo que permite que la barrera de los borrados se abra sobre una certeza y no
		sobre la palabra de la API.
		"""
		self.ensure_one()
		datos = self._datos_modulo()
		esperado = datos.get("arbol_esperado") or self._sha_del_subarbol(
			cliente, datos["origen_repo"], datos["origen_rama"], datos["ruta"])
		obtenido = self._sha_del_subarbol(
			cliente, self.repository_id.full_name, datos["destino_rama"], datos["ruta"])
		# El contrato del motor: `(ok, detalle)`. No se levanta excepción — una
		# verificación que falla NO es un error del sistema, es un resultado, y el motor
		# sabe qué hacer con él.
		if not esperado:
			return False, _(
				"no se pudo leer el módulo en el origen, así que no hay contra qué "
				"verificar la copia")
		if obtenido != esperado:
			return False, _(
				"la copia NO quedó idéntica — esperado %(esperado)s, obtenido "
				"%(obtenido)s. Lo que venga después contaba con esta copia."
			) % {"esperado": esperado, "obtenido": obtenido or _("(no está)")}
		return True, esperado

	# ------------------------------------------------------------------
	# Revertir: la rama vuelve donde estaba, y sólo si nadie la movió
	# ------------------------------------------------------------------

	def _revertir_modulo_copiado(self, cliente, punto_de_retorno):
		"""Devuelve la rama al commit que tenía, con condición de avance rápido.

		LA CONDICIÓN NO ES OPCIONAL. Si alguien empujó a esa rama después de nuestra copia,
		volver la referencia atrás **borraría su trabajo**. Un rollback que destruye lo de
		otro es peor que no revertir: el módulo se niega y explica, que es lo que una
		persona puede resolver.
		"""
		self.ensure_one()
		datos = self._datos_modulo()
		destino = self.repository_id.full_name
		rama = datos["destino_rama"]
		nuestro = json.loads(self.result_json or "{}").get("commit")
		ref = cliente.get("/repos/%s/git/ref/heads/%s" % (destino, rama)) or {}
		actual = (ref.get("object") or {}).get("sha")
		if nuestro and actual and actual != nuestro:
			raise UserError(_(
				"La rama «%(rama)s» de %(repo)s se movió después de la copia: ahora está "
				"en %(actual)s y nosotros la dejamos en %(nuestro)s.\n\n"
				"Revertir la pisaría y se perdería lo que empujó otra persona. Hay que "
				"deshacerlo a mano, mirando qué se agregó en el medio."
			) % {"rama": rama, "repo": destino, "actual": actual[:8],
				 "nuestro": nuestro[:8]})
		cliente.patch("/repos/%s/git/refs/heads/%s" % (destino, rama), {
			"sha": punto_de_retorno["commit"], "force": True,
		})
		return True

	# ------------------------------------------------------------------

	@api.model
	def _manejadores(self):
		manejadores = super()._manejadores()
		manejadores["module_copy"] = {
			"leer": "_leer_modulo_destino",
			"ejecutar": "_copiar_modulo",
			"verificar": "_verificar_modulo_copiado",
			"revertir": "_revertir_modulo_copiado",
		}
		return manejadores


class RepoWriteOperationModuleDelete(models.Model):
	"""Retirar un módulo de un repositorio: LA PRIMERA OPERACIÓN QUE BORRA CONTENIDO.

	NUNCA CORRE SOLA. Depende, por la barrera de D2.0, de que la copia al destino haya
	quedado **verificada por hash**. Si la copia falló, ésta no se intenta y queda en «no
	ejecutada por dependencia». El peor caso que este diseño permite es que el módulo
	quede en dos lados —duplicación benigna, molesta y arreglable—; el que no permite es
	que no quede en ninguno.

	Y ADEMÁS COMPRUEBA POR SU CUENTA. La barrera dice «la copia salió bien»; esta
	operación pregunta algo distinto: «¿lo que voy a borrar es lo mismo que se copió?».
	Entre que se armó el plan y se aplica, alguien pudo tocar el módulo en el origen. Si
	el subárbol ya no tiene el SHA que el plan declaró, se niega: borraría trabajo que
	nunca se copió a ningún lado. Dos preguntas distintas necesitan dos comprobaciones.

	LA REVERSIÓN ES POR AVANCE RÁPIDO, igual que la de la copia. Se guarda el commit donde
	estaba la rama; si alguien empujó después, revertir pisaría lo suyo y el módulo se
	niega y explica en vez de hacerlo.
	"""
	_inherit = "repo.write.operation"

	# El payload:
	#   {"ruta": "addons/mi_modulo", "modulo": "mi_modulo", "rama": "17.0",
	#    "arbol_esperado": "<sha del subárbol que se copió>",
	#    "copiado_a": "org/general"}   ← sólo para la frase y la bitácora
	#
	# `repository_id` es el repositorio DEL QUE SE SACA.

	def _datos_borrado(self):
		self.ensure_one()
		try:
			datos = json.loads(self.payload_json or "{}")
		except (TypeError, ValueError) as exc:
			raise UserError(_("El payload del borrado no es JSON válido: %s") % exc)
		faltan = [c for c in ("ruta", "rama") if not datos.get(c)]
		if faltan:
			raise UserError(_(
				"Al payload del borrado le faltan datos: %s.") % ", ".join(faltan))
		return datos

	# ------------------------------------------------------------------
	# Leer: dónde está la rama y qué se va a sacar
	# ------------------------------------------------------------------

	def _leer_modulo_a_borrar(self, cliente):
		self.ensure_one()
		datos = self._datos_borrado()
		repo = self.repository_id.full_name
		rama = datos["rama"]
		ref = cliente.get("/repos/%s/git/ref/heads/%s" % (repo, rama))
		if not ref or not (ref.get("object") or {}).get("sha"):
			raise _falla(_(
				"No se pudo leer la rama «%(rama)s» de %(repo)s. Sin punto de retorno no "
				"se borra nada.") % {"rama": rama, "repo": repo})
		# LA LECTURA REPORTA HECHOS, NO DECIDE. Que el módulo no esté es un hecho válido
		# —es el estado normal DESPUÉS de un borrado— y este mismo método es el que el
		# motor usa para fotografiar la situación antes de revertir. Negarse acá dejaba al
		# borrado sin reversión posible: el rollback moría leyendo, antes de intentar
		# nada. La negativa a escribir sobre una ruta vacía vive en `_borrar_modulo`, que
		# es el paso que escribe.
		return {
			"rama": rama,
			"commit": ref["object"]["sha"],
			"arbol_del_modulo": self._sha_del_subarbol(cliente, repo, rama, datos["ruta"]),
		}

	# ------------------------------------------------------------------
	# Ejecutar: un árbol sin el módulo, un commit, la referencia
	# ------------------------------------------------------------------

	def _borrar_modulo(self, cliente):
		self.ensure_one()
		datos = self._datos_borrado()
		repo = self.repository_id.full_name
		rama = datos["rama"]
		ruta = datos["ruta"]
		previo = self._leer_modulo_a_borrar(cliente)

		if not previo["arbol_del_modulo"]:
			# NO es un éxito silencioso. Que no haya nada puede significar que ya se borró
			# —y entonces no hay nada que hacer— o que la ruta está mal escrita y el
			# borrado apuntaba a otro lado. Las dos cosas se ven igual desde acá, así que
			# se para y se dice, en vez de reportar «listo» sobre algo que no se hizo.
			raise _falla(_(
				"En %(repo)s@%(rama)s no hay nada en «%(ruta)s». O ya se borró, o la ruta "
				"no es ésa: en cualquier caso no se escribe sin saber cuál de las dos.")
				% {"repo": repo, "rama": rama, "ruta": ruta})

		# LA SEGUNDA COMPROBACIÓN, la propia. La barrera ya dijo que la copia quedó bien;
		# esto pregunta si lo que está acá AHORA es lo que se copió. Si alguien tocó el
		# módulo en el origen después de armar el plan, su cambio no está en ninguna copia
		# y borrarlo lo perdería para siempre.
		esperado = datos.get("arbol_esperado")
		if esperado and previo["arbol_del_modulo"] != esperado:
			raise _falla(_(
				"El módulo en %(repo)s@%(rama)s cambió después de armarse el plan: se "
				"copió %(esperado)s y ahora hay %(actual)s. Lo que cambió no está en la "
				"copia, así que borrarlo lo perdería. Hay que volver a promover."
			) % {"repo": repo, "rama": rama, "esperado": esperado[:8],
				 "actual": (previo["arbol_del_modulo"] or "")[:8]})

		# Los archivos que se van. En la API de datos de git, un `sha: null` en el árbol
		# borra esa ruta; hay que nombrarlos uno por uno, porque `base_tree` conserva todo
		# lo que no se menciona — que es justamente lo que se quiere para el resto del
		# repositorio.
		arbol = cliente.get("/repos/%s/git/trees/%s?recursive=1" % (repo, rama)) or {}
		if arbol.get("truncated"):
			raise _falla(_(
				"El árbol de %(repo)s@%(rama)s vino truncado: no se puede borrar un "
				"módulo sin ver todos sus archivos.") % {"repo": repo, "rama": rama})
		entradas = [
			{"path": e["path"], "mode": e.get("mode", "100644"), "type": "blob",
			 "sha": None}
			for e in (arbol.get("tree") or [])
			if e.get("type") == "blob" and (e.get("path") or "").startswith(ruta + "/")
		]
		if not entradas:
			raise _falla(_(
				"No hay archivos bajo «%(ruta)s» en %(repo)s@%(rama)s. Un commit que no "
				"borra nada quedaría en la historia pareciendo un borrado hecho.")
				% {"ruta": ruta, "repo": repo, "rama": rama})

		arbol_nuevo = cliente.post("/repos/%s/git/trees" % repo, {
			"base_tree": previo["commit"], "tree": entradas,
		})
		commit = cliente.post("/repos/%s/git/commits" % repo, {
			"message": _("[REM] %(modulo)s: retirado, ahora vive en %(destino)s\n\n"
						 "Retirado por Repo Manager: la copia en %(destino)s quedó "
						 "verificada por hash antes de este borrado. Plan «%(plan)s».\n"
						 "OJO: las instancias que tomaban el módulo de este repositorio "
						 "necesitan un cambio de addons_path que Repo Manager no hace.")
					   % {"modulo": datos.get("modulo") or ruta.split("/")[-1],
						  "destino": datos.get("copiado_a") or _("el repositorio común"),
						  "plan": self.plan_id.name},
			"tree": arbol_nuevo["sha"], "parents": [previo["commit"]],
		})
		# SIN force, por lo mismo que la copia: si alguien empujó en el medio, que rechace.
		cliente.patch("/repos/%s/git/refs/heads/%s" % (repo, rama), {
			"sha": commit["sha"], "force": False,
		})
		return {"commit": commit["sha"], "archivos": len(entradas),
				"arbol_borrado": previo["arbol_del_modulo"]}

	# ------------------------------------------------------------------
	# Verificar: que YA NO ESTÉ
	# ------------------------------------------------------------------

	def _verificar_modulo_borrado(self, cliente):
		"""El borrado vale si el subárbol dejó de existir. Se relee, no se supone."""
		self.ensure_one()
		datos = self._datos_borrado()
		quedo = self._sha_del_subarbol(
			cliente, self.repository_id.full_name, datos["rama"], datos["ruta"])
		if quedo:
			return False, _(
				"el módulo sigue estando en «%(ruta)s» (%(sha)s). El commit de borrado "
				"puede no haber movido la rama."
			) % {"ruta": datos["ruta"], "sha": quedo[:8]}
		return True, _("«%s» ya no está en la rama") % datos["ruta"]

	# ------------------------------------------------------------------
	# Revertir: el módulo vuelve, si nadie empujó encima
	# ------------------------------------------------------------------

	def _revertir_modulo_borrado(self, cliente, punto_de_retorno):
		self.ensure_one()
		datos = self._datos_borrado()
		repo = self.repository_id.full_name
		rama = datos["rama"]
		nuestro = json.loads(self.result_json or "{}").get("commit")
		ref = cliente.get("/repos/%s/git/ref/heads/%s" % (repo, rama)) or {}
		actual = (ref.get("object") or {}).get("sha")
		if nuestro and actual and actual != nuestro:
			raise UserError(_(
				"La rama «%(rama)s» de %(repo)s se movió después del borrado: ahora está "
				"en %(actual)s y nosotros la dejamos en %(nuestro)s.\n\n"
				"Devolverla atrás borraría lo que empujó otra persona. El módulo está "
				"guardado en el commit %(previo)s: se restaura a mano desde ahí."
			) % {"rama": rama, "repo": repo, "actual": actual[:8],
				 "nuestro": nuestro[:8], "previo": punto_de_retorno["commit"][:8]})
		cliente.patch("/repos/%s/git/refs/heads/%s" % (repo, rama), {
			"sha": punto_de_retorno["commit"], "force": True,
		})
		return True

	# ------------------------------------------------------------------

	@api.model
	def _manejadores(self):
		manejadores = super()._manejadores()
		manejadores["module_delete"] = {
			"leer": "_leer_modulo_a_borrar",
			"ejecutar": "_borrar_modulo",
			"verificar": "_verificar_modulo_borrado",
			"revertir": "_revertir_modulo_borrado",
		}
		return manejadores
