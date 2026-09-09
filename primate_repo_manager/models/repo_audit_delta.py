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

from odoo import _, api, models

_logger = logging.getLogger(__name__)

# Los estados de una corrida que se pueden comparar. Una corrida `error` se detuvo a
# mitad de camino: lo que no llegó a mirar no se distingue de lo que miró y estaba bien.
COMPARABLES = ("done", "partial")


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
	def calcular(self, corrida):
		"""El delta de una corrida contra la anterior comparable.

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

		anterior = self.corrida_anterior(corrida)
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
