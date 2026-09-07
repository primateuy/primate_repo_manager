# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""B3.1 · el CODEOWNERS generado, y el owner que no se escribe porque no se verificó.

El test que más importa es el del owner sin acceso: **no falla al escribirse, falla en
silencio después**. La línea la ignora GitHub, las PRs no piden esa revisión, y el
repositorio parece gobernado mientras nadie revisa nada. Es el check-que-no-corrió en
versión personas.
"""
import base64
import json
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.primate_repo_manager.models.repo_codeowners import MARCA


class TestCodeownersGenerado(TransactionCase):

	def setUp(self):
		super().setUp()
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		self.env.flush_all()
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "Clientes", "code": "co-%s" % uuid.uuid4().hex[:6],
			"classification_default": "cliente",
		})
		backend = self.env["repo.backend"].create({
			"name": "CO %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})
		self.repo = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "classification": "cliente",
		})
		self.lider = self.env["repo.member"].create({
			"github_login": "mrodriguez", "name": "Martín Rodríguez"})
		self.env["repo.collaborator"].create({
			"repository_id": self.repo.id, "member_id": self.lider.id,
			"permission": "maintain", "source": "direct"})

	def _regla(self, miembro, patron="*", reason=False, sequence=10):
		return self.env["repo.policy.codeowner"].create({
			"template_id": self.plantilla.id, "path_pattern": patron,
			"member_id": miembro.id, "reason": reason, "sequence": sequence})

	# ------------------------------------------------------------------
	# LA VALIDACIÓN CONTRA EL ESPEJO
	# ------------------------------------------------------------------

	def test_un_owner_SIN_ACCESO_al_repo_no_se_escribe(self):
		"""No falla al escribirse: falla en silencio después. No se escribe lo que no se
		verificó."""
		ajeno = self.env["repo.member"].create({"github_login": "sin-acceso"})
		self._regla(ajeno)
		salida = self.repo.generar_codeowners()
		self.assertEqual(salida["lineas"], [])
		self.assertEqual(salida["contenido"], "")
		self.assertEqual(len(salida["omitidos"]), 1)
		self.assertIn("no figura como colaborador", salida["omitidos"][0]["motivo"])

	def test_el_omitido_se_INFORMA_y_no_se_traga(self):
		"""Omitirlo en silencio sería el mismo defecto una capa más arriba."""
		ajeno = self.env["repo.member"].create({"github_login": "sin-acceso"})
		self._regla(self.lider, patron="*")
		self._regla(ajeno, patron="addons/")
		salida = self.repo.generar_codeowners()
		self.assertEqual(len(salida["lineas"]), 1)
		self.assertEqual(salida["omitidos"][0]["login"], "sin-acceso")
		self.assertEqual(salida["omitidos"][0]["patron"], "addons/")

	def test_una_persona_SIN_cuenta_de_github_no_puede_ni_existir(self):
		"""La garantía vive en el modelo, no en el generador.

		El generador tenía una rama para «sin cuenta de GitHub» y era código muerto:
		`repo.member` exige `github_login`. Una guarda que no puede dispararse es peor
		que ninguna, así que se quitó — y este test fija dónde está la garantía de
		verdad, para que quitar el `required` no pase inadvertido.
		"""
		from psycopg2 import IntegrityError

		from odoo.tools import mute_logger
		with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
			with self.env.cr.savepoint():
				self.env["repo.member"].create({"name": "Sin cuenta"})

	def test_el_que_SI_tiene_acceso_entra(self):
		self._regla(self.lider)
		salida = self.repo.generar_codeowners()
		self.assertEqual(salida["omitidos"], [])
		self.assertIn("* @mrodriguez", salida["contenido"])

	# ------------------------------------------------------------------
	# El archivo
	# ------------------------------------------------------------------

	def test_lleva_la_marca_que_lo_hace_reconocible_como_nuestro(self):
		"""Sin la marca, B3.2 no puede distinguir el nuestro de uno ajeno — y uno ajeno
		no se pisa nunca."""
		self._regla(self.lider)
		self.assertTrue(
			self.repo.generar_codeowners()["contenido"].startswith(MARCA))

	def test_cada_linea_dice_DE_DONDE_sale_su_owner(self):
		"""Un CODEOWNERS sin procedencia es un archivo que nadie se anima a tocar."""
		self._regla(self.lider, reason="líder técnico de la cuenta")
		contenido = self.repo.generar_codeowners()["contenido"]
		self.assertIn("# líder técnico de la cuenta", contenido)

	def test_sin_procedencia_declarada_dice_al_menos_de_que_plantilla_sale(self):
		self._regla(self.lider)
		self.assertIn(self.plantilla.name, self.repo.generar_codeowners()["contenido"])

	def test_respeta_el_orden_declarado(self):
		"""CODEOWNERS aplica la ÚLTIMA regla que coincide: el orden decide quién revisa."""
		otro = self.env["repo.member"].create({"github_login": "jperez"})
		self.env["repo.collaborator"].create({
			"repository_id": self.repo.id, "member_id": otro.id,
			"permission": "push", "source": "direct"})
		self._regla(self.lider, patron="*", sequence=10)
		self._regla(otro, patron="addons/", sequence=20)
		contenido = self.repo.generar_codeowners()["contenido"]
		self.assertLess(contenido.index("* @mrodriguez"),
						contenido.index("addons/ @jperez"))

	def test_los_owners_son_PERSONAS_y_el_archivo_lo_dice(self):
		"""Los teams no existen en una cuenta de usuario: una línea con team la ignora
		GitHub sin avisar. La decisión queda escrita donde alguien la va a leer."""
		self._regla(self.lider)
		contenido = self.repo.generar_codeowners()["contenido"]
		self.assertIn("PERSONAS", contenido)
		self.assertNotIn("@%s/" % self.repo.backend_id.owner_login, contenido)

	def test_sin_owners_declarados_no_hay_archivo(self):
		"""Un CODEOWNERS vacío no es neutro: reemplazaría a uno que hubiera."""
		self.assertEqual(self.repo.generar_codeowners()["contenido"], "")


class TestEscrituraDeCodeowners(TransactionCase):
	"""B3.2 · los cuatro estados del archivo, y el que carga más peso: el ajeno."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from .test_backend import _clave_rsa_de_prueba
		cls.clave = _clave_rsa_de_prueba()

	def setUp(self):
		super().setUp()
		from .test_write_apply import sin_cursor_aparte
		self.env.user.group_ids |= self.env.ref("primate_repo_manager.group_repo_lead")
		self.backend = self.env["repo.backend"].create({
			"name": "CO-W %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"environment": "sandbox"})
		self.backend.private_key = self.clave
		self.backend.write_app_id = "10"
		self.backend.write_installation_id = "20"
		self.backend.write_private_key = self.clave
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "sbx", "full_name": "org/sbx", "default_branch": "19.0"})
		sin_cursor_aparte(self)

	def _contenido(self, extra=""):
		return "%s\n# Repositorio: org/sbx\n\n* @mrodriguez\n%s" % (MARCA, extra)

	def _plan(self, contenido=None):
		plan = self.env["repo.write.plan"].create({
			"name": "CODEOWNERS", "backend_id": self.backend.id})
		self.op = self.env["repo.write.operation"].create({
			"plan_id": plan.id, "kind": "codeowners_write",
			"repository_id": self.repo.id, "target": "19.0",
			"payload_json": json.dumps(
				{"contenido": contenido or self._contenido()})})
		return plan

	def _archivo(self, contenido, ruta=".github/CODEOWNERS"):
		from .test_write_apply import Respuesta
		return Respuesta(200, {
			"sha": "abc123", "path": ruta,
			"content": base64.b64encode(contenido.encode()).decode()})

	def _correr(self, plan, por_ruta):
		from .test_write_apply import Respuesta

		class Transporte:
			def __init__(self):
				self.llamadas, self.cuerpos = [], []
				self.abarca = ["org/sbx"]

			def get(self, url, headers=None, timeout=None):
				self.llamadas.append(("GET", url))
				if "/installation/repositories" in url:
					return Respuesta(200, {"total_count": 1, "repositories": [
						{"full_name": r} for r in self.abarca]})
				for fragmento, respuesta in por_ruta.items():
					if fragmento in url:
						return respuesta
				return Respuesta(404, {"message": "Not Found"})

			def post(self, url, json=None, headers=None, timeout=None):
				self.llamadas.append(("POST", url))
				if "access_tokens" in url:
					return Respuesta(201, {"token": "ghs_test"})
				self.cuerpos.append(("POST", url, json))
				return Respuesta(201, {})

			def put(self, url, json=None, headers=None, timeout=None):
				self.llamadas.append(("PUT", url))
				self.cuerpos.append(("PUT", url, json))
				return Respuesta(200, {"content": {"sha": "nuevo"}})

			def delete(self, url, json=None, headers=None, timeout=None):
				self.llamadas.append(("DELETE", url))
				self.cuerpos.append(("DELETE", url, json))
				return Respuesta(200, {})

			def patch(self, url, json=None, headers=None, timeout=None):
				return Respuesta(200, {})

			def escrituras_hechas(self):
				return [c for c in self.llamadas if c[0] in ("PUT", "DELETE", "PATCH")
						or (c[0] == "POST" and "access_tokens" not in c[1])]

		from .test_write_apply import _aprobar_plan
		_aprobar_plan(plan)
		transporte = Transporte()
		Backend = type(self.backend)
		original = Backend.write_client
		Backend.write_client = lambda s, transport=None: original(
			s, transport=transporte)
		try:
			plan.action_apply()
		except Exception as exc:
			self.error = exc
		finally:
			Backend.write_client = original
		return transporte

	# ------------------------------------------------------------------
	# El estado que carga más peso
	# ------------------------------------------------------------------

	def test_un_CODEOWNERS_AJENO_no_se_pisa_jamas(self):
		"""El archivo es uno solo: escribirlo reemplaza la lista de revisores de otro."""
		plan = self._plan()
		transporte = self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo("* @otra-gente\n")})
		self.assertEqual(transporte.escrituras_hechas(), [])
		self.assertNotEqual(self.op.state, "applied")

	def test_se_miran_LAS_TRES_ubicaciones(self):
		"""GitHub usa la PRIMERA que encuentra. Escribir en la raíz mientras hay un
		ajeno en `.github/` no falla: aplica, verifica bien y no gobierna nada."""
		plan = self._plan()
		transporte = self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo("* @otra-gente\n")})
		urls = " ".join(u for _m, u in transporte.llamadas)
		self.assertIn("/contents/.github/CODEOWNERS", urls)
		self.assertEqual(transporte.escrituras_hechas(), [],
						 "el ajeno de .github/ tapa a cualquier otro")

	# ------------------------------------------------------------------
	# Los otros tres
	# ------------------------------------------------------------------

	def test_si_no_hay_ninguno_se_escribe(self):
		plan = self._plan()
		transporte = self._correr(plan, {})
		puts = [c for c in transporte.cuerpos if c[0] == "PUT"]
		self.assertEqual(len(puts), 1)
		self.assertIn("/contents/.github/CODEOWNERS", puts[0][1])

	def test_si_ya_esta_igual_NO_se_escribe(self):
		plan = self._plan()
		transporte = self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo(self._contenido())})
		self.assertEqual(transporte.escrituras_hechas(), [])
		self.assertEqual(self.op.state, "applied", self.op.error or "")

	def test_el_contenido_se_verifica_BYTE_A_BYTE(self):
		"""GitHub puede aceptar el commit y dejar otra cosa: fin de línea, encoding."""
		plan = self._plan()
		self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo(
				self._contenido().replace("\n", "\r\n"))})
		self.assertEqual(self.op.state, "failed")
		self.assertIn("byte a byte", self.op.error)

	def test_una_diferencia_de_SOLO_el_salto_final_tambien_falla(self):
		"""Byte a byte es byte a byte.

		Es la diferencia que un `.strip()` taparía, y es la más probable de todas: un
		archivo sin salto final y otro con él son distintos para git —cambian el blob y
		el diff— aunque se lean igual. Una verificación que los da por iguales dice
		«quedó lo que pedimos» sobre algo que no es lo que se pidió, y la próxima
		aplicación vuelve a escribir creyendo que hay un cambio.
		"""
		plan = self._plan()
		self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo(
				self._contenido().rstrip("\n"))})
		self.assertEqual(self.op.state, "failed")
		self.assertIn("byte a byte", self.op.error)

	# ------------------------------------------------------------------
	# La guarda del destino escribible, ahora de la familia
	# ------------------------------------------------------------------

	def test_una_rama_que_exige_PR_impide_ARMAR_el_plan(self):
		"""Nunca muere a mitad del apply: se niega antes."""
		self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": "19.0", "role": "base",
			"protected": True,
			"protection_json": json.dumps({"required_pull_request_reviews": {}})})
		plan = self._plan()
		with self.assertRaises(UserError) as capturado:
			plan._verificar_destino_escribible()
		self.assertIn("exige pull request", str(capturado.exception))

	def test_la_guarda_cubre_a_la_familia_y_no_a_un_tipo(self):
		"""Se escribió para module_copy; codeowners_write queda cubierto por contestar
		cuál es su rama de destino, no por estar en una lista."""
		plan = self._plan()
		self.assertEqual(plan.operation_ids._rama_de_destino(), "19.0")

	# ------------------------------------------------------------------
	# El estado intermedio: DRIFT DE ARCHIVO
	# ------------------------------------------------------------------

	def _con_referencia(self, contenido_aplicado):
		"""Deja en la bitácora la referencia de lo que escribimos la última vez."""
		self.env["repo.audit.log"].registrar(
			"write_applied", "CODEOWNERS aplicado",
			backend=self.backend, repository=self.repo,
			payload={"kind": "codeowners_write", "target": "19.0",
					 "payload": {"contenido": contenido_aplicado}})

	def test_editado_a_mano_NO_se_pisa_en_silencio(self):
		"""Lleva nuestra marca y el contenido difiere de lo que la bitácora dice que
		escribimos: no es ajeno ni es nuestro, es drift de archivo. Pisar la línea que
		alguien agregó a mano es el mismo daño que pisar el archivo de otro, en cuotas."""
		self._con_referencia(self._contenido())
		editado = self._contenido(extra="docs/ @alguien-que-agregaron-a-mano\n")
		plan = self._plan()
		transporte = self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo(editado)})
		self.assertEqual(transporte.escrituras_hechas(), [])
		self.assertNotEqual(self.op.state, "applied")

	def test_con_la_confirmacion_Y_la_diferencia_delante_si_se_pisa(self):
		self._con_referencia(self._contenido())
		editado = self._contenido(extra="docs/ @alguien\n")
		plan = self._plan()
		self.op.payload_json = json.dumps({
			"contenido": self._contenido(),
			"perder_ediciones": True,
			"ediciones_perdidas": "+ docs/ @alguien",
		})
		transporte = self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo(editado)})
		self.assertTrue([c for c in transporte.cuerpos if c[0] == "PUT"])

	def test_la_confirmacion_SIN_la_diferencia_no_alcanza(self):
		"""Sin el texto de lo que se pierde, la casilla se marca sin haber mirado nada."""
		self._con_referencia(self._contenido())
		plan = self._plan()
		self.op.payload_json = json.dumps({
			"contenido": self._contenido(), "perder_ediciones": True})
		transporte = self._correr(plan, {
			"/contents/.github/CODEOWNERS": self._archivo(
				self._contenido(extra="docs/ @alguien\n"))})
		self.assertEqual(transporte.escrituras_hechas(), [])

	def test_la_confirmacion_viaja_DENTRO_de_la_huella_aprobada(self):
		"""Fuera de la huella se podría prender después de aprobar, y aprobar habría sido
		firmar un cheque en blanco sobre el trabajo de otro."""
		plan = self._plan()
		from .test_write_apply import _aprobar_plan
		_aprobar_plan(plan)
		huella_aprobada = plan.approval_fingerprint
		self.assertEqual(plan._huella(), huella_aprobada)

		self.op.payload_json = json.dumps({
			"contenido": self._contenido(), "perder_ediciones": True,
			"ediciones_perdidas": "algo"})
		self.assertNotEqual(
			plan._huella(), huella_aprobada,
			"prender la confirmación tiene que invalidar la huella: si no, se podría "
			"prender DESPUÉS de aprobar")
