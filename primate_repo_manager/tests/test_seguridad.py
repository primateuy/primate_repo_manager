# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B6.1 · las alertas de seguridad, sus tres estados, y el secreto que NO se copia.

Los tres estados se midieron contra la cuenta real antes de escribir esto: de 25
repositorios, 4 devolvieron la lista, 21+25 contestaron «disabled» y CERO dijeron «not
accessible by integration». Los mensajes que usan estos tests son los que devolvió GitHub,
no inventados.
"""
import uuid

from odoo.tests.common import TransactionCase

# Los mensajes REALES, tal como los devolvió la API el 7-sep-2026.
SECRET_APAGADO = {"message": "Secret scanning is disabled on this repository."}
DEPENDABOT_APAGADO = {"message": "Dependabot alerts are disabled for this repository."}
SIN_PERMISO = {"message": "Resource not accessible by integration"}


class Respuesta:
	def __init__(self, status_code, payload=None, headers=None):
		self.status_code = status_code
		self._payload = payload
		self.headers = headers or {}
		self.text = ""
		self.content = b"x" if payload is not None else b""

	def json(self):
		return self._payload


class Transporte:
	"""Contesta por ruta, como GitHub: cada endpoint tiene su propia respuesta."""

	def __init__(self, por_ruta):
		self.por_ruta = por_ruta
		self.llamadas = []

	def get(self, url, headers=None, timeout=None):
		self.llamadas.append(url)
		for fragmento, respuesta in self.por_ruta.items():
			if fragmento in url:
				return respuesta
		return Respuesta(200, [])

	def post(self, url, json=None, headers=None, timeout=None):
		return Respuesta(201, {"token": "ghs_test"})


class TestLecturaDeAlertas(TransactionCase):

	def setUp(self):
		super().setUp()
		from .test_backend import _clave_rsa_de_prueba
		self.backend = self.env["repo.backend"].create({
			"name": "Seguridad %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})
		self.backend.private_key = _clave_rsa_de_prueba()
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "visibility": "public",
		})

	def _leer(self, por_ruta):
		self.repo._sync_security_alerts(self.backend.client(
			transport=Transporte(por_ruta)))
		return {f.source: f for f in self.env["repo.security.scan"].search(
			[("repository_id", "=", self.repo.id)])}

	# ------------------------------------------------------------------
	# Los tres estados
	# ------------------------------------------------------------------

	def test_con_alertas_se_lee_y_se_cuenta(self):
		estados = self._leer({"secret-scanning": Respuesta(200, [
			{"number": 1, "state": "open", "secret_type": "aws_access_key",
			 "html_url": "https://github.com/org/sbx/security/secret-scanning/1"}])})
		self.assertEqual(estados["secret_scanning"].state, "con_datos")
		self.assertEqual(estados["secret_scanning"].alert_count, 1)

	def test_una_lista_VACIA_es_un_dato_y_no_una_ausencia(self):
		"""«Miré y no hay» es distinto de «no miré», y las dos cosas se ven igual si el
		estado se dedujera de que la lista está vacía."""
		estados = self._leer({"secret-scanning": Respuesta(200, [])})
		self.assertEqual(estados["secret_scanning"].state, "con_datos")
		self.assertEqual(estados["secret_scanning"].alert_count, 0)

	def test_apagado_en_el_repo_NO_es_cero_alertas(self):
		"""La peor pantalla posible: «cero secretos filtrados» sobre algo que nunca miró."""
		estados = self._leer({"secret-scanning": Respuesta(404, SECRET_APAGADO)})
		self.assertEqual(estados["secret_scanning"].state, "apagado")
		self.assertNotEqual(estados["secret_scanning"].state, "con_datos")
		self.assertIn("disabled", estados["secret_scanning"].cause)

	def test_dependabot_apagado_llega_con_403_y_tampoco_es_falta_de_permiso(self):
		"""El mismo 403 significa «apagado» y «no tenés permiso». Los separa el mensaje."""
		estados = self._leer({"dependabot": Respuesta(403, DEPENDABOT_APAGADO)})
		self.assertEqual(estados["dependabot"].state, "apagado")

	def test_sin_permiso_es_NO_LEGIBLE_y_no_apagado(self):
		estados = self._leer({"dependabot": Respuesta(403, SIN_PERMISO)})
		self.assertEqual(estados["dependabot"].state, "no_legible")

	# ------------------------------------------------------------------
	# Advanced Security: un hecho nuestro, no una respuesta de GitHub
	# ------------------------------------------------------------------

	def test_en_un_repo_PRIVADO_apagado_se_marca_que_exige_advanced_security(self):
		self.repo.visibility = "private"
		estados = self._leer({"secret-scanning": Respuesta(404, SECRET_APAGADO)})
		self.assertTrue(estados["secret_scanning"].needs_advanced_security)

	def test_en_uno_PUBLICO_el_mismo_mensaje_NO_exige_advanced_security(self):
		"""GitHub dice lo mismo en los dos casos: la diferencia sale de la visibilidad,
		que es un hecho que ya tenemos, y por eso se marca aparte."""
		estados = self._leer({"secret-scanning": Respuesta(404, SECRET_APAGADO)})
		self.assertFalse(estados["secret_scanning"].needs_advanced_security)

	def test_dependabot_apagado_NUNCA_exige_advanced_security(self):
		"""Se enciende gratis: mezclarlo con el techo de plan mandaría a alguien a
		negociar una licencia para prender una casilla."""
		self.repo.visibility = "private"
		estados = self._leer({"dependabot": Respuesta(403, DEPENDABOT_APAGADO)})
		self.assertFalse(estados["dependabot"].needs_advanced_security)

	# ------------------------------------------------------------------
	# EL SECRETO NO SE COPIA
	# ------------------------------------------------------------------

	def test_el_espejo_NO_tiene_ningun_campo_donde_guardar_un_secreto(self):
		"""La garantía es estructural: no hay dónde ponerlo, aunque alguien quisiera."""
		Alerta = self.env["repo.security.alert"]
		for prohibido in Alerta.CAMPOS_PROHIBIDOS:
			self.assertNotIn(prohibido, Alerta._fields,
							 "el espejo no puede tener un campo «%s»" % prohibido)

	def test_el_secreto_que_manda_github_NO_queda_en_ningun_campo(self):
		"""GitHub lo manda entero y en fragmento. Ni uno ni otro entran."""
		secreto = "ghp_UNSECRETODEVERDAD1234567890"
		self.env["repo.security.alert"].upsert(self.repo, "secret_scanning", {
			"number": 7, "state": "open", "secret_type": "github_pat",
			"secret": secreto, "fragment": secreto[:12],
			"html_url": "https://github.com/org/sbx/security/secret-scanning/7",
		})
		fila = self.env["repo.security.alert"].search(
			[("repository_id", "=", self.repo.id)])
		guardado = " ".join(
			str(fila[c] or "") for c in fila._fields if fila._fields[c].type in
			("char", "text"))
		self.assertNotIn(secreto, guardado)
		self.assertNotIn(secreto[:12], guardado)

	def test_lo_que_SI_se_guarda_alcanza_para_actuar(self):
		self.env["repo.security.alert"].upsert(self.repo, "secret_scanning", {
			"number": 7, "state": "open",
			"secret_type_display_name": "GitHub Personal Access Token",
			"secret": "ghp_x",
			"html_url": "https://github.com/org/sbx/security/secret-scanning/7",
		})
		fila = self.env["repo.security.alert"].search(
			[("repository_id", "=", self.repo.id)])
		self.assertEqual(fila.secret_type, "GitHub Personal Access Token")
		self.assertIn("secret-scanning/7", fila.html_url)

	def test_una_alerta_de_dependabot_guarda_severidad_y_paquete(self):
		self.env["repo.security.alert"].upsert(self.repo, "dependabot", {
			"number": 3, "state": "open",
			"security_advisory": {"summary": "RCE en la librería"},
			"security_vulnerability": {
				"severity": "critical", "package": {"name": "lodash"}},
			"html_url": "https://github.com/org/sbx/security/dependabot/3",
		})
		fila = self.env["repo.security.alert"].search(
			[("repository_id", "=", self.repo.id)])
		self.assertEqual(fila.severity, "critical")
		self.assertEqual(fila.package_name, "lodash")

	# ------------------------------------------------------------------
	# Las reglas de construcción del espejo
	# ------------------------------------------------------------------

	def test_leer_dos_veces_actualiza_y_no_duplica(self):
		por_ruta = {"secret-scanning": Respuesta(200, [
			{"number": 1, "state": "open", "secret_type": "aws",
			 "html_url": "u"}])}
		self._leer(por_ruta)
		self._leer(por_ruta)
		self.assertEqual(self.env["repo.security.alert"].search_count(
			[("repository_id", "=", self.repo.id)]), 1)

	def test_cada_fila_dice_cuando_se_supo_y_por_donde_entro(self):
		estados = self._leer({"secret-scanning": Respuesta(200, [])})
		self.assertTrue(estados["secret_scanning"].last_seen_at)
		self.assertEqual(estados["secret_scanning"].origin, "sync")
