# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Cliente de ESCRITURA de GitHub. Fase 2 en adelante.

POR QUÉ ESTÁ EN UN ARCHIVO APARTE Y NO JUNTO AL DE LECTURA. `github_client.py` tiene un
test que parsea el módulo entero y exige que contenga **exactamente una** escritura HTTP:
el POST que pide el token de instalación. Esa garantía es un criterio de aceptación de F1
y no se negocia. Metiendo los verbos de escritura ahí habría que aflojar el test, y un
test aflojado deja de probar lo que probaba.

Acá el cliente de lectura sigue siendo demostrablemente incapaz de escribir, y la
capacidad de escritura aparece en un archivo nuevo — visible de un vistazo en el diff que
la introduce, que era el punto.

CÓMO SE LLEGA A ESTA CLASE. Por una sola puerta: `repo.backend.write_client()`, que se
niega a abrirla si el backend no es de entorno `sandbox`. Hay un test que lee el código y
falla si alguien la instancia desde otro lado.
"""
import logging

from .github_client import (
	GithubError,
	GithubNotFound,
	GithubPlanLimit,
	GithubRateLimit,
	GithubReadClient,
	_cuerpo,
	_exigido,
)

_logger = logging.getLogger(__name__)

# Los únicos verbos que esta clase expone. La lista es explícita para que el test que
# la vigila compare contra algo declarado y no contra lo que haya quedado en el archivo.
VERBOS = ("post", "patch", "put", "delete")


class GithubWriteClient(GithubReadClient):
	"""Lectura (heredada) + los cuatro verbos de escritura.

	Hereda de `GithubReadClient` a propósito: casi toda escritura necesita leer antes
	—para conocer el estado previo, que es lo que después permite revertir— y leer
	después, para verificar que quedó lo que se quiso. Dos clientes separados obligarían
	a pasear dos objetos por todos lados sin ganar nada.
	"""

	def _escribir(self, metodo, path, cuerpo=None, tolerar_404=False):
		"""Ejecuta una escritura y traduce los errores igual que la lectura.

		NO reintenta nunca por su cuenta. Un reintento automático sobre una escritura
		puede aplicar dos veces algo que no es idempotente; quién reintenta y cuándo es
		decisión de la capa de arriba, que sabe si la operación lo tolera.
		"""
		url = path if path.startswith("http") else "%s/%s" % (
			self._api_root, path.lstrip("/"))
		response = getattr(self._transport, metodo)(
			url, json=cuerpo, headers=self._headers(), timeout=30)
		self._registrar_cuota(response)

		exigido = _exigido(response)
		if response.status_code == 404:
			if tolerar_404:
				return None
			raise GithubNotFound(404, _cuerpo(response), path, exigido)
		if response.status_code == 403 and self._sin_cuota(response):
			raise GithubRateLimit(403, "cuota de API agotada", path, exigido)
		if response.status_code == 403:
			mensaje = _cuerpo(response)
			if "upgrade" in mensaje.lower() or "plan" in mensaje.lower():
				raise GithubPlanLimit(403, mensaje, path, exigido)
		if response.status_code >= 400:
			raise GithubError(response.status_code, _cuerpo(response), path, exigido)
		if response.status_code == 204 or not response.content:
			return {}
		return response.json()

	def post(self, path, cuerpo=None, tolerar_404=False):
		return self._escribir("post", path, cuerpo, tolerar_404)

	def patch(self, path, cuerpo=None, tolerar_404=False):
		return self._escribir("patch", path, cuerpo, tolerar_404)

	def put(self, path, cuerpo=None, tolerar_404=False):
		return self._escribir("put", path, cuerpo, tolerar_404)

	def delete(self, path, cuerpo=None, tolerar_404=False):
		return self._escribir("delete", path, cuerpo, tolerar_404)
