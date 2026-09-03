# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Todo cambio de política queda en la bitácora inmutable.

POR QUÉ ACÁ Y NO EN EL CHATTER. Cambiar la política es la escritura más silenciosa que
tiene el módulo: no toca un solo repositorio y, sin embargo, redefine qué cuenta como
incumplimiento para todos los de esa clasificación y en todas las auditorías que vengan.
Bajar «aprobaciones requeridas» de 2 a 1 hace desaparecer hallazgos sin arreglar nada.

El chatter registra la conversación y sirve para eso, pero es editable y se va junto con
el registro que lo lleva. El argumento que hizo inmutable esta bitácora para las
escrituras a GitHub —«una bitácora que un `sudo()` puede reescribir no es una bitácora»—
vale más acá, no menos: un permiso cambiado se ve mirando GitHub, una política cambiada
sólo se ve si alguien la anotó.

QUÉ SE REGISTRA: campo, valor anterior, valor nuevo, quién y cuándo. Se registra TODO
campo que cambie, sin lista blanca. Una lista de «campos importantes» es una lista que
alguien va a olvidar de actualizar el día que agregue el campo que importaba.

B4 —detectar que una plantilla cambió y hay repositorios sin actualizar— va a leer de este
registro: es la única fuente que dice cuándo cambió la política y qué cambió.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class RepoPolicyAudited(models.AbstractModel):
	_name = "repo.policy.audited"
	_description = "Política cuyos cambios quedan en la bitácora inmutable"

	def _valor_legible(self, campo):
		"""El valor como lo leería una persona, no como lo guarda Postgres.

		Una entrada que diga «max_permission: push -> admin» se entiende; una que diga
		«2 -> 4» obliga a ir a buscar la tabla, y para entonces ya nadie la lee.
		"""
		self.ensure_one()
		definicion = self._fields.get(campo)
		valor = self[campo]
		if definicion and definicion.type == "selection":
			return dict(definicion._description_selection(self.env)).get(valor, valor)
		if definicion and definicion.type in ("many2one",):
			return valor.display_name if valor else False
		if definicion and definicion.type in ("one2many", "many2many"):
			return ", ".join(valor.mapped("display_name"))
		return valor

	def _registrar_cambio_de_politica(self, que_paso, cambios=None):
		self.ensure_one()
		if self.env.context.get("install_mode"):
			# Los datos que vienen con el módulo no son una decisión de nadie: anotarlos
			# llenaría la bitácora de ruido el día de la instalación y escondería, entre
			# cincuenta filas, la única que sí importa.
			return
		self.env["repo.audit.log"].registrar(
			"policy_changed",
			_("%(que)s: %(modelo)s «%(registro)s»") % {
				"que": que_paso,
				"modelo": self._description,
				"registro": self.display_name,
			},
			payload={
				"modelo": self._name,
				"registro_id": self.id,
				"registro": self.display_name,
				"cambios": cambios or {},
			},
			previous_state={c: v.get("antes") for c, v in (cambios or {}).items()},
		)

	@api.model_create_multi
	def create(self, vals_list):
		registros = super().create(vals_list)
		for registro in registros:
			registro._registrar_cambio_de_politica(_("Creada"))
		return registros

	def write(self, vals):
		# Se leen ANTES de escribir: después ya no hay con qué comparar.
		antes = {
			registro.id: {
				campo: registro._valor_legible(campo)
				for campo in vals if campo in registro._fields
			}
			for registro in self
		}
		resultado = super().write(vals)
		for registro in self:
			cambios = {}
			for campo, anterior in antes[registro.id].items():
				actual = registro._valor_legible(campo)
				if actual != anterior:
					etiqueta = registro._fields[campo].string or campo
					cambios[etiqueta] = {"antes": anterior, "después": actual}
			if cambios:
				registro._registrar_cambio_de_politica(_("Modificada"), cambios)
		return resultado

	def unlink(self):
		# Igual que en `write`: la entrada se arma con el registro todavía vivo. Después
		# de borrarlo no queda ni el nombre.
		for registro in self:
			registro._registrar_cambio_de_politica(_("Eliminada"))
		return super().unlink()
