# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Cliente REST de GitHub para la Fase 1: SOLO LECTURA POR CONSTRUCCIÓN.

Que esta fase no escriba nada en GitHub es un criterio de aceptación, y no se garantiza
con disciplina ni con revisiones de código: se garantiza porque **el verbo no está
escrito**. `GithubReadClient` no tiene `post`, `patch`, `put` ni `delete`. Para escribir
habría que agregar un método nuevo, que es un cambio visible en el diff y no un descuido.
Hay un test (`test_read_only.py`) que lo verifica inspeccionando la clase.

La única excepción, y conviene decirla en voz alta en vez de esconderla: pedir el token de
instalación de la GitHub App **es** un POST, porque así lo define GitHub. Vive aislado en
`GithubAppAuth`, no toca ningún recurso de ningún repositorio y no puede usarse para otra
cosa: recibe un app_id y una private key, y devuelve un token. El cliente de recursos, que
es el que recorre repos y ramas, no tiene forma de escribir.
"""
import logging
import time
from urllib.parse import urlencode

import requests

_logger = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
ACCEPT = "application/vnd.github+json"
API_VERSION = "2022-11-28"
TIMEOUT = 30
# Tope de páginas por recorrido. Un repo con 20.000 commits no puede colgar una auditoría;
# lo que se necesita es una muestra acotada, no la historia entera.
MAX_PAGES = 50


class GithubError(Exception):
	"""Error de la API de GitHub. Nunca se traga: siempre llega con status y cuerpo."""

	def __init__(self, status, message, path=None):
		self.status = status
		self.message = message
		self.path = path
		super().__init__("GitHub %s en %s: %s" % (status, path or "?", message))


class GithubRateLimit(GithubError):
	"""Cuota agotada. Se distingue del resto para poder reintentar con criterio."""


class GithubPlanLimit(GithubError):
	"""La cuenta no tiene plan para esa función.

	NO SIMPLIFICAR ESTA CLASE SIN LEER ESTO. Parece redundante con GithubError y no lo es:
	distingue un caso que sólo se puede detectar por la FORMA de la respuesta, y de esa
	distinción depende que el informe diga la verdad.

	El endpoint de branch protection (`GET /repos/{owner}/{repo}/branches/{branch}/protection`)
	responde de tres maneras distintas que un lector apurado colapsa en una sola:

	  200  → la rama está protegida, y viene la configuración.
	  404  → dos cosas MUY distintas según quién pregunta:
	         · con permiso de admin  → la rama realmente no tiene protección.
	         · sin permiso de admin  → GitHub devuelve 404 en vez de 403 A PROPÓSITO, para
	           no revelar si el recurso existe. No significa "no hay protección":
	           significa "no te puedo decir". Ver la doc de la API: los endpoints de
	           branch protection requieren admin sobre el repositorio.
	  403 con mensaje de upgrade → la cuenta es gratuita y el repo es privado. En ese plan
	         GitHub no permite proteger ramas de repos privados, así que la función no
	         está disponible por PLAN, no por permisos.

	Las tres se resuelven de manera distinta, y por eso se guardan como causas distintas
	en `repo.branch.protection_cause`:

	  · sin protección real  → aplicar el ruleset (F3).
	  · sin permiso de admin → reinstalar la App con una cuenta que lo tenga.
	  · límite de plan       → decisión comercial; no hay arreglo técnico.

	Colapsar las tres en "no está protegida" produce un informe que afirma cosas que nadie
	verificó, y manda a alguien a "arreglar" repos que en realidad no se pudieron mirar.
	Ya pasó una vez en este proyecto, muestreando cuatro repos a mano.
	"""


class GithubAppAuth:
	"""Cambia la private key de la App por un token de instalación de corta vida.

	El token dura una hora; se renueva solo cuando falta poco para vencer. Nunca se
	persiste: vive en memoria del proceso y muere con él.
	"""

	def __init__(self, app_id, installation_id, private_key_pem, transport=None):
		self.app_id = str(app_id)
		self.installation_id = str(installation_id)
		self._private_key = private_key_pem
		self._transport = transport or requests
		self._token = None
		self._expires_at = 0.0

	def _build_jwt(self):
		"""JWT firmado con la private key de la App (RS256), válido 10 minutos."""
		import jwt  # PyJWT

		ahora = int(time.time())
		payload = {
			# 60 s de gracia hacia atrás: si el reloj del server adelanta, GitHub rechaza.
			"iat": ahora - 60,
			"exp": ahora + 540,
			"iss": self.app_id,
		}
		return jwt.encode(payload, self._private_key, algorithm="RS256")

	def token(self):
		"""Token de instalación vigente, renovándolo si falta menos de un minuto."""
		if self._token and time.time() < self._expires_at - 60:
			return self._token

		url = "%s/app/installations/%s/access_tokens" % (API_ROOT, self.installation_id)
		# ÚNICO POST del módulo en esta fase, y no toca ningún repositorio: es el
		# intercambio de credenciales que define GitHub. Ver el docstring del módulo.
		response = self._transport.post(
			url,
			headers={
				"Authorization": "Bearer %s" % self._build_jwt(),
				"Accept": ACCEPT,
				"X-GitHub-Api-Version": API_VERSION,
			},
			timeout=TIMEOUT,
		)
		if response.status_code != 201:
			raise GithubError(response.status_code, _cuerpo(response), "access_tokens")
		data = response.json()
		self._token = data["token"]
		# GitHub devuelve el vencimiento ISO; se guarda como epoch para no parsear después.
		self._expires_at = time.time() + 3300
		return self._token


class GithubReadClient:
	"""Lectura de la API de GitHub. No expone ningún verbo de escritura.

	:param token_provider: callable sin argumentos que devuelve el token vigente. Se pasa
		como función y no como string para que la renovación sea transparente en
		recorridos largos, donde el token puede vencer a mitad de camino.
	"""

	def __init__(self, token_provider, transport=None, api_root=API_ROOT):
		self._token_provider = token_provider
		self._transport = transport or requests
		self._api_root = api_root
		self.last_rate_remaining = None

	# ------------------------------------------------------------------
	# Lectura
	# ------------------------------------------------------------------

	def get(self, path, params=None, tolerar_404=False):
		"""GET de un recurso.

		:param tolerar_404: en GitHub un 404 muchas veces significa "no configurado" y no
			"no existe": una rama sin protección devuelve 404 en el endpoint de
			protección. Con este flag eso se traduce a None y el que llama decide, en
			vez de tratar una respuesta esperable como un error.
		"""
		url = path if path.startswith("http") else "%s/%s" % (self._api_root, path.lstrip("/"))
		if params:
			url = "%s?%s" % (url, urlencode(params))
		response = self._transport.get(url, headers=self._headers(), timeout=TIMEOUT)
		self._registrar_cuota(response)

		if response.status_code == 404 and tolerar_404:
			return None
		if response.status_code == 403 and self._sin_cuota(response):
			raise GithubRateLimit(403, "cuota de API agotada", path)
		if response.status_code == 403:
			mensaje = _cuerpo(response)
			if "upgrade" in mensaje.lower() or "plan" in mensaje.lower():
				raise GithubPlanLimit(403, mensaje, path)
		if response.status_code >= 400:
			raise GithubError(response.status_code, _cuerpo(response), path)
		return response.json()

	def paginate(self, path, params=None, max_items=None, envoltorio=None):
		"""Recorre una colección paginada siguiendo la cabecera Link.

		:param max_items: corta la lectura al llegar a esa cantidad. Se usa para las
			muestras de commits, donde no se quiere la historia sino los últimos N.
		:param envoltorio: clave bajo la cual viene la lista cuando el endpoint devuelve
			un objeto en vez de un array. `/installation/repositories` la envuelve en
			`repositories`; las búsquedas, en `items`. Sin este dato la respuesta se lee
			como vacía y el recorrido termina en silencio sin haber visto nada, que es
			exactamente el error que hay que hacer imposible acá.
		"""
		items = []
		params = dict(params or {})
		params.setdefault("per_page", 100)
		url = path if path.startswith("http") else "%s/%s" % (self._api_root, path.lstrip("/"))
		if params:
			url = "%s?%s" % (url, urlencode(params))

		for _pagina in range(MAX_PAGES):
			response = self._transport.get(url, headers=self._headers(), timeout=TIMEOUT)
			self._registrar_cuota(response)
			if response.status_code == 403 and self._sin_cuota(response):
				raise GithubRateLimit(403, "cuota de API agotada", path)
			if response.status_code >= 400:
				raise GithubError(response.status_code, _cuerpo(response), path)

			lote = response.json()
			if not isinstance(lote, list):
				# Endpoints que envuelven la lista, p. ej. búsquedas: {items: [...]}.
				clave = envoltorio or "items"
				if clave not in lote:
					raise GithubError(
						response.status_code,
						"la respuesta no es una lista ni trae la clave «%s» (claves: %s)"
						% (clave, ", ".join(sorted(lote))[:200]),
						path)
				lote = lote.get(clave) or []
			items.extend(lote)
			if max_items and len(items) >= max_items:
				return items[:max_items]

			url = _siguiente_pagina(response)
			if not url:
				break
		else:
			_logger.warning(
				"GitHub: %s superó las %s páginas; se devuelve lo leído hasta acá",
				path, MAX_PAGES,
			)
		return items

	# ------------------------------------------------------------------
	# Interno
	# ------------------------------------------------------------------

	def _headers(self):
		return {
			"Authorization": "Bearer %s" % self._token_provider(),
			"Accept": ACCEPT,
			"X-GitHub-Api-Version": API_VERSION,
		}

	def _registrar_cuota(self, response):
		restante = (response.headers or {}).get("X-RateLimit-Remaining")
		if restante is not None:
			try:
				self.last_rate_remaining = int(restante)
			except (TypeError, ValueError):
				self.last_rate_remaining = None

	@staticmethod
	def _sin_cuota(response):
		return (response.headers or {}).get("X-RateLimit-Remaining") == "0"


def _siguiente_pagina(response):
	"""URL de la página siguiente según la cabecera Link, o None si no hay más."""
	link = (response.headers or {}).get("Link") or ""
	for parte in link.split(","):
		trozos = parte.split(";")
		if len(trozos) < 2:
			continue
		if 'rel="next"' in trozos[1].replace(" ", "").replace("'", '"'):
			return trozos[0].strip().strip("<>")
	return None


def _cuerpo(response):
	"""Mensaje de error legible, sin reventar si la respuesta no es JSON."""
	try:
		data = response.json()
	except ValueError:
		return (response.text or "")[:300]
	if isinstance(data, dict):
		return data.get("message") or str(data)[:300]
	return str(data)[:300]
