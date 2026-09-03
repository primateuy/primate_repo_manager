# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Qué canales del bus puede escuchar el navegador.

El cliente pide suscribirse mandando NOMBRES DE CANAL como texto, y eso es texto que llega
de afuera: si se aceptara tal cual, cualquiera podría escuchar el canal de cualquier
registro. Por eso Odoo obliga a traducir ese texto a un registro acá, del lado del
servidor, y esa traducción es el lugar donde se comprueba el permiso.

Acá se admite un solo patrón —`repo.audit.run_<id>`— y sólo si el usuario puede LEER esa
corrida. Un id de una corrida que no puede ver, o de una que no existe, se descarta en
silencio: no se le dice al que pregunta cuál de las dos cosas era.
"""
import re

from odoo import models
from odoo.exceptions import AccessError

CANAL_CORRIDA = re.compile(r"^repo\.audit\.run_(\d+)$")


class IrWebsocket(models.AbstractModel):
	_inherit = "ir.websocket"

	def _build_bus_channel_list(self, channels):
		return super()._build_bus_channel_list(self._traducir_corridas(channels))

	def _traducir_corridas(self, channels):
		"""Cambia los nombres pedidos por los registros que el usuario puede leer.

		VIVE APARTE DE `_build_bus_channel_list` para poder probarse: la implementación
		base necesita una petición HTTP viva —usa `request`/`wsrequest`— y en un test no
		hay ninguna. Separar la traducción deja verificable la parte que decide QUIÉN
		ESCUCHA QUÉ, que es la única con consecuencias de seguridad.
		"""
		channels = list(channels)
		pedidos = []
		for canal in list(channels):
			if isinstance(canal, str) and CANAL_CORRIDA.match(canal):
				channels.remove(canal)
				pedidos.append(int(CANAL_CORRIDA.match(canal).group(1)))
		if not pedidos:
			return channels
		try:
			# `search` filtra por reglas de registro, pero LANZA si al usuario le falta el
			# permiso de lectura sobre el modelo entero. Las dos cosas significan lo mismo
			# acá —no se suscribe— y por eso la excepción se traduce a lista vacía en vez
			# de dejar que reviente la conexión del bus de toda la sesión.
			corridas = self.env["repo.audit.run"].search([("id", "in", pedidos)])
		except AccessError:
			return channels
		channels.extend(corridas)
		return channels
