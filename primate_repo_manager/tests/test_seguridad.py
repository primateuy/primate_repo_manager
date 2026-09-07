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


class TestHallazgosDeSeguridad(TransactionCase):
	"""B6.2 · los dos tratamientos, el apagado, y el secreto que no viaja al hallazgo."""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Hallazgos %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "visibility": "public",
		})
		self.run = self.env["repo.audit.run"].create({
			"name": "Corrida", "backend_id": self.backend.id, "state": "done"})

	def _alerta(self, source, **datos):
		base = {"number": datos.pop("number", 1), "state": datos.pop("state", "open")}
		base.update(datos)
		return self.env["repo.security.alert"].upsert(self.repo, source, base)

	def _hallazgos(self, tipo):
		self.env["repo.audit.engine"].evaluate(self.run)
		return self.run.finding_ids.filtered(lambda h: h.finding_type == tipo)

	# ------------------------------------------------------------------
	# Secretos: uno por alerta, crítico siempre
	# ------------------------------------------------------------------

	def test_cada_secreto_es_un_hallazgo_propio(self):
		"""Un secreto filtrado es un incidente con nombre propio: no se agrupa."""
		self.env["repo.security.scan"].upsert(self.repo, "secret_scanning", "con_datos")
		self._alerta("secret_scanning", number=1, secret_type="aws_key", html_url="u1")
		self._alerta("secret_scanning", number=2, secret_type="github_pat", html_url="u2")
		self.assertEqual(len(self._hallazgos("secret_leaked")), 2)

	def test_la_seguridad_se_evalua_aunque_el_repo_NO_este_clasificado(self):
		"""Esconderla detrás de la clasificación callaría lo más grave que el módulo sabe
		decir, justo sobre los repositorios que nadie miró todavía."""
		self.assertFalse(self.repo.classification)
		self.env["repo.security.scan"].upsert(self.repo, "secret_scanning", "con_datos")
		self._alerta("secret_scanning", secret_type="aws_key", html_url="u")
		self.assertTrue(self._hallazgos("secret_leaked"))

	def test_un_secreto_es_CRITICO_siempre(self):
		self.env["repo.security.scan"].upsert(self.repo, "secret_scanning", "con_datos")
		self._alerta("secret_scanning", secret_type="aws_key", html_url="u")
		self.assertEqual(self._hallazgos("secret_leaked").severity, "critical")

	def test_el_hallazgo_NO_contiene_el_secreto(self):
		"""Ni el valor ni el fragmento: tipo, dónde y enlace. El módulo no replica la
		filtración que reporta."""
		secreto = "ghp_ESTONOPUEDEVIAJAR0987654321"
		self.env["repo.security.scan"].upsert(self.repo, "secret_scanning", "con_datos")
		self.env["repo.security.alert"].upsert(self.repo, "secret_scanning", {
			"number": 9, "state": "open", "secret_type": "github_pat",
			"secret": secreto, "fragment": secreto[:10],
			"resolution_comment": "lo rotamos, era %s" % secreto,
			"html_url": "https://github.com/org/sbx/security/secret-scanning/9"})
		hallazgo = self._hallazgos("secret_leaked")
		texto = " ".join(str(hallazgo[c] or "") for c in (
			"summary", "detail", "observed_json", "expected_json",
			"remediation_payload", "subject"))
		self.assertNotIn(secreto, texto)
		self.assertNotIn(secreto[:10], texto)
		self.assertIn("secret-scanning/9", texto, "el enlace sí tiene que estar")

	# ------------------------------------------------------------------
	# EL CICLO DE VIDA SIGUE A LA ALERTA
	# ------------------------------------------------------------------

	def test_un_secreto_RESUELTO_alla_deja_de_gritar_aca(self):
		"""Un secreto rotado y cerrado en GitHub no puede seguir siendo crítico acá: es
		la fábrica de ruido permanente en el lugar más sensible."""
		self.env["repo.security.scan"].upsert(self.repo, "secret_scanning", "con_datos")
		self._alerta("secret_scanning", number=1, state="resolved",
					 secret_type="aws_key", html_url="u")
		self.assertFalse(self._hallazgos("secret_leaked"))

	def test_un_secreto_DESCARTADO_alla_tampoco_grita(self):
		self.env["repo.security.scan"].upsert(self.repo, "secret_scanning", "con_datos")
		self._alerta("secret_scanning", number=1, state="dismissed",
					 secret_type="aws_key", html_url="u")
		self.assertFalse(self._hallazgos("secret_leaked"))

	def test_el_desenlace_viaja_al_espejo_CODIFICADO(self):
		"""`revoked` dice que se rotó. El comentario libre no viaja: puede tener el
		secreto pegado, que es donde la gente lo pega."""
		self.env["repo.security.alert"].upsert(self.repo, "secret_scanning", {
			"number": 1, "state": "resolved", "resolution": "revoked",
			"resolution_comment": "rotado, era ghp_SECRETO", "secret_type": "pat"})
		fila = self.env["repo.security.alert"].search(
			[("repository_id", "=", self.repo.id)])
		self.assertEqual(fila.resolution, "revoked")
		self.assertNotIn("resolution_comment", fila._fields)

	# ------------------------------------------------------------------
	# Dependencias: uno por repositorio
	# ------------------------------------------------------------------

	def test_cuarenta_vulnerabilidades_son_UN_hallazgo(self):
		"""Son un trabajo —actualizar—, no cuarenta. Cuarenta filas taparían el informe."""
		self.env["repo.security.scan"].upsert(self.repo, "dependabot", "con_datos")
		for n in range(40):
			self._alerta("dependabot", number=n,
						 security_vulnerability={"severity": "medium",
												 "package": {"name": "p%s" % n}})
		hallazgos = self._hallazgos("dependency_vulnerabilities")
		self.assertEqual(len(hallazgos), 1)
		self.assertIn("40", hallazgos.summary)

	def test_la_severidad_es_la_PEOR_y_la_mapea_github(self):
		self.env["repo.security.scan"].upsert(self.repo, "dependabot", "con_datos")
		self._alerta("dependabot", number=1, security_vulnerability={
			"severity": "low", "package": {"name": "a"}})
		self._alerta("dependabot", number=2, security_vulnerability={
			"severity": "critical", "package": {"name": "b"}})
		hallazgo = self._hallazgos("dependency_vulnerabilities")
		self.assertEqual(hallazgo.severity, "critical")
		self.assertIn("critical", hallazgo.summary)

	def test_las_de_dependabot_cerradas_no_cuentan(self):
		self.env["repo.security.scan"].upsert(self.repo, "dependabot", "con_datos")
		self._alerta("dependabot", number=1, state="fixed", security_vulnerability={
			"severity": "critical", "package": {"name": "a"}})
		self.assertFalse(self._hallazgos("dependency_vulnerabilities"))

	# ------------------------------------------------------------------
	# Apagado: informativo, con la causa distinguida
	# ------------------------------------------------------------------

	def test_apagado_gratis_propone_encenderlo(self):
		self.env["repo.security.scan"].upsert(
			self.repo, "dependabot", "apagado", cause="Dependabot alerts are disabled")
		hallazgo = self._hallazgos("security_feature_disabled")
		self.assertEqual(hallazgo.remediation_action, "enable_security_feature")
		self.assertIn("gratis", hallazgo.detail)

	def test_apagado_en_privado_manda_a_advanced_security_y_no_a_una_casilla(self):
		"""Mezclarlas mandaría a alguien a negociar una licencia para prender algo
		gratis, o al revés: a buscar una casilla que no existe."""
		self.repo.visibility = "private"
		self.env["repo.security.scan"].upsert(
			self.repo, "secret_scanning", "apagado", cause="Secret scanning is disabled")
		hallazgo = self._hallazgos("security_feature_disabled")
		self.assertEqual(hallazgo.remediation_action, "upgrade_plan")
		self.assertIn("Advanced Security", hallazgo.detail)

	def test_apagado_es_informativo_y_no_una_alarma(self):
		self.env["repo.security.scan"].upsert(
			self.repo, "dependabot", "apagado", cause="disabled")
		self.assertEqual(self._hallazgos("security_feature_disabled").severity, "info")

	def test_no_legible_no_afirma_nada_sobre_el_repositorio(self):
		self.env["repo.security.scan"].upsert(
			self.repo, "dependabot", "no_legible", cause="not accessible")
		hallazgo = self._hallazgos("security_feature_disabled")
		self.assertTrue(hallazgo, "tiene que haber un hallazgo que lo diga")
		self.assertIn("No se pudo leer", hallazgo.summary)
		self.assertIn("no se afirma nada", hallazgo.detail.lower())

	def test_ninguno_de_los_tres_se_ofrece_planificable(self):
		"""B6 lee. Encender seguridad desde acá cambiaría la postura de una cuenta sin
		que eso pase por ningún plan."""
		self.env["repo.security.scan"].upsert(self.repo, "secret_scanning", "con_datos")
		self._alerta("secret_scanning", secret_type="aws", html_url="u")
		self.env["repo.security.scan"].upsert(
			self.repo, "dependabot", "apagado", cause="disabled")
		for tipo in ("secret_leaked", "security_feature_disabled"):
			for hallazgo in self._hallazgos(tipo):
				self.assertFalse(hallazgo.can_be_planned, tipo)
				self.assertTrue(hallazgo.why_not_planned, tipo)


class TestPantallaDeSeguridad(TransactionCase):
	"""B6.3 · la pantalla, y que cada estado diga dónde se resuelve."""

	def setUp(self):
		super().setUp()
		self.accion = self.env.ref(
			"primate_repo_manager.action_repo_security_findings")

	def test_la_entrada_de_menu_ya_no_es_un_casillero_apagado(self):
		"""Dejó de prometer y pasó a mostrar. El menú no cambia de forma: se habilita."""
		menu = self.env.ref("primate_repo_manager.menu_repo_security_findings")
		self.assertEqual(menu.action.id, self.accion.id)
		self.assertNotEqual(self.accion.res_model, "repo.coming.soon")

	def test_la_pantalla_muestra_los_TRES_estados_y_nada_mas(self):
		tipos = self.accion.domain
		for tipo in ("secret_leaked", "dependency_vulnerabilities",
					 "security_feature_disabled"):
			self.assertIn(tipo, tipos)

	def test_el_domain_esta_en_UNA_sola_linea(self):
		"""El evaluador del navegador no acepta literales partidos; el servidor guarda
		ese texto sin mirarlo y la pantalla revienta recién al hacer clic."""
		self.assertNotIn("\\n", self.accion.domain or "")
		self.assertNotIn("\\n", self.accion.context or "")

	def _frase(self, accion):
		hallazgo = self.env["repo.audit.finding"].new({"remediation_action": accion})
		return hallazgo._remediation_label()

	def test_el_apagado_gratis_y_la_licencia_dicen_cosas_DISTINTAS(self):
		"""Las dos causas del apagado no pueden leerse igual: una es una casilla y la
		otra es plata."""
		gratis = self._frase("enable_security_feature")
		licencia = self._frase("upgrade_plan")
		self.assertIn("gratis", gratis.lower())
		self.assertIn("plan", licencia.lower())
		self.assertNotEqual(gratis, licencia)

	def test_cada_hallazgo_de_seguridad_dice_DONDE_se_resuelve(self):
		"""Ninguno se arregla en este módulo, y decirlo es la mitad del valor."""
		self.assertIn("rotar", self._frase("rotate_secret").lower())
		self.assertIn("pr", self._frase("update_dependencies").lower())
