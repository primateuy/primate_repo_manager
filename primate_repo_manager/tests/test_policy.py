# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Las cuatro plantillas, contra las decisiones escritas de la spec.

Cada aserción acá corresponde a una línea de la spec, y está para que un cambio de valor
no pase inadvertido: si alguien baja las aprobaciones de producción de 2 a 1, el test se
pone rojo en ese commit y no seis meses después.

POR QUÉ LOS VALORES SE LEEN DEL ARCHIVO Y NO DE LA BASE. Estos tests leían los registros
instalados, y eso los ponía a vigilar dos cosas distintas con la misma aserción: el valor
de fábrica que el equipo decidió, y el valor que el cliente tiene hoy. Son diferentes a
propósito — las plantillas son configuración, van con `noupdate="1"` justamente para que
editarlas no se pierda en la próxima actualización.

Pasó lo previsible: un usuario subió a 2 las aprobaciones de base de «cliente estándar»
desde la pantalla, que es exactamente lo que la pantalla existe para permitir, y la suite
se puso roja acusando un cambio de decisión que nadie hizo. Un test que se pone rojo por
un uso legítimo enseña a ignorarlo.

Así que quedan separados: **los valores de fábrica se verifican contra el XML de datos**
—ahí sí, bajarlos es un cambio de decisión y tiene que doler— y **la lógica se verifica
contra plantillas que el test se construye**, sin depender de lo que haya en la base.
"""
import ast
import uuid
from xml.etree import ElementTree

from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger
from odoo.tools.misc import file_path
from odoo.tools.sql import index_exists

from odoo.addons.primate_repo_manager.models.repo_policy import (
	_mensaje_de_clasificacion_ocupada,
)


class _Diagnostico:
	"""Lo único que la función del mensaje mira del error de Postgres."""

	def __init__(self, message_detail):
		self.message_detail = message_detail

ARCHIVO = "primate_repo_manager/data/repo_policy_data.xml"


def _valor(campo):
	"""El valor de un <field>, tal como lo entendería el cargador de datos."""
	if "eval" in campo.attrib:
		return ast.literal_eval(campo.attrib["eval"])
	if "ref" in campo.attrib:
		return campo.attrib["ref"]
	return campo.text or ""


def de_fabrica():
	"""Lo que el módulo INSTALA: {code: {campo: valor, "reglas": {rol: {...}}}}."""
	raiz = ElementTree.parse(file_path(ARCHIVO)).getroot()
	plantillas, por_xmlid = {}, {}
	for record in raiz.iter("record"):
		campos = {c.attrib["name"]: _valor(c) for c in record.findall("field")}
		if record.attrib["model"] == "repo.policy.template":
			campos["reglas"] = {}
			plantillas[campos["code"]] = campos
			por_xmlid[record.attrib["id"]] = campos
		elif record.attrib["model"] == "repo.policy.branch.rule":
			por_xmlid[campos["template_id"]]["reglas"][campos["branch_role"]] = campos
	return plantillas


class TestPolicyTemplates(TransactionCase):
	"""Los VALORES DE FÁBRICA, contra el archivo que los instala."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.fabrica = de_fabrica()

	def _plantilla(self, code):
		return self.env["repo.policy.template"].search([("code", "=", code)], limit=1)

	def test_las_cuatro_plantillas_existen(self):
		"""Ésta sí mira la base: que estén instaladas es sobre la instalación."""
		for code in ("cliente-estandar", "localizacion", "interno", "fork-upstream"):
			self.assertTrue(self._plantilla(code), code)

	# --- §4.3 tabla de plantillas ---

	def test_cliente_estandar_una_aprobacion_en_base_dos_en_prod(self):
		t = self.fabrica["cliente-estandar"]
		self.assertEqual(t["required_approvals"], "1")
		self.assertEqual(t["reglas"]["prod"]["required_approvals"], "2")

	def test_staging_y_support_heredan_base_SIN_override_propio(self):
		"""Decisión tomada: heredan PR + 1 aprobación. Que no tengan fila es el punto."""
		reglas = self.fabrica["cliente-estandar"]["reglas"]
		self.assertNotIn("staging", reglas)
		self.assertNotIn("support", reglas)

	def test_localizacion_es_la_mas_estricta(self):
		t = self.fabrica["localizacion"]
		self.assertTrue(t["require_codeowner_review"])
		self.assertTrue(t["require_signed_commits"])
		self.assertEqual(t["reglas"]["prod"]["required_approvals"], "2")

	def test_interno_exige_pr_pero_no_aprobaciones(self):
		"""Resolución de la contradicción de la spec: trazabilidad y CI sí, espera no."""
		t = self.fabrica["interno"]
		self.assertTrue(t["require_pr"])
		self.assertEqual(t["required_approvals"], "0")
		self.assertFalse(t["require_signed_commits"])

	def test_la_firma_solo_esta_activa_en_localizacion(self):
		"""§9: el rollout arranca por localización; activarla antes bloquearía gente."""
		activas = [c for c, t in self.fabrica.items() if t["require_signed_commits"]]
		self.assertEqual(activas, ["localizacion"])

	# --- §5 forks ---

	def test_la_rama_espejo_bloquea_el_push_de_humanos(self):
		espejo = self.fabrica["fork-upstream"]["reglas"]["mirror"]
		self.assertTrue(espejo["block_human_push"])
		self.assertFalse(espejo["require_pr"])

	def test_la_rama_de_parches_lleva_flujo_normal(self):
		parches = self.fabrica["fork-upstream"]["reglas"]["patch"]
		self.assertTrue(parches["require_pr"])
		self.assertEqual(parches["required_approvals"], "1")

	# --- lo que NO está decidido ---

	def test_ningun_check_requerido_esta_definido_todavia(self):
		"""La spec los hace obligatorios pero no nombra ninguno.

		Inventar un nombre acá sería peor que dejarlo vacío: en un ruleset, un check que
		no existe bloquea TODOS los merges del repo para siempre.
		"""
		for code, t in self.fabrica.items():
			self.assertFalse(t["status_checks_defined"], code)
			self.assertNotIn("required_check_ids", t, code)

	# --- patrones de la decisión 6 ---

	def test_el_patron_de_commit_es_el_de_la_convencion(self):
		for code, t in self.fabrica.items():
			self.assertEqual(t["commit_message_pattern"],
							 r"^\[(ADD|IMP|FIX)\]\[\d+\] .+", code)

	def test_el_patron_de_commit_acepta_lo_que_debe_y_rechaza_lo_que_no(self):
		muestra = self.env["repo.commit.sample"]
		patron = self.fabrica["cliente-estandar"]["commit_message_pattern"]
		self.assertTrue(muestra.message_matches("[ADD][2041] modelo de backend", patron))
		self.assertTrue(muestra.message_matches("[FIX][7] corrige el sync", patron))
		# Los de esta misma conversación, que NO cumplen: sin número de ticket.
		self.assertFalse(muestra.message_matches("[ADD] esqueleto del módulo", patron))
		self.assertFalse(muestra.message_matches("arreglo rápido", patron))
		self.assertFalse(muestra.message_matches("[WIP][12] a medio hacer", patron))


class TestHerenciaDeReglas(TransactionCase):
	"""La LÓGICA de `rule_for_role`, sobre plantillas que el test se arma.

	Separada de los valores de fábrica a propósito: acá se prueba que la herencia
	funcione, y eso tiene que seguir siendo cierto con cualquier número que un cliente
	configure. Cuando estas dos cosas estaban juntas, editar la plantilla desde la
	pantalla rompía la prueba de la herencia, que no tenía nada que ver.
	"""

	def _plantilla(self, **campos):
		valores = {
			"name": "De prueba", "code": "prueba-herencia",
			"require_pr": True, "required_approvals": 1,
		}
		valores.update(campos)
		return self.env["repo.policy.template"].create(valores)

	def test_un_rol_sin_fila_propia_hereda_la_general_y_lo_dice(self):
		t = self._plantilla()
		regla = t.rule_for_role("staging")
		self.assertTrue(regla["heredada"])
		self.assertTrue(regla["require_pr"])
		self.assertEqual(regla["required_approvals"], 1)

	def test_un_rol_con_fila_propia_la_usa_y_NO_dice_heredada(self):
		t = self._plantilla()
		self.env["repo.policy.branch.rule"].create({
			"template_id": t.id, "branch_role": "prod", "required_approvals": 2})
		regla = t.rule_for_role("prod")
		self.assertEqual(regla["required_approvals"], 2)
		self.assertFalse(regla.get("heredada"))
		# Y la general no se contagia: el override es de ese rol y de ninguno más.
		self.assertEqual(t.rule_for_role("base")["required_approvals"], 1)

	def test_bloquear_el_push_humano_solo_sale_de_una_fila_propia(self):
		"""Por default es False: una rama espejo se declara, no se adivina."""
		t = self._plantilla()
		self.assertFalse(t.rule_for_role("mirror")["block_human_push"])
		self.env["repo.policy.branch.rule"].create({
			"template_id": t.id, "branch_role": "mirror",
			"block_human_push": True, "require_pr": False})
		self.assertTrue(t.rule_for_role("mirror")["block_human_push"])


class TestPolicyAccess(TransactionCase):

	def _propia(self):
		"""Plantilla del test: el default es configuración, no una constante del código."""
		return self.env["repo.policy.template"].create({
			"name": "Acceso de prueba", "code": "prueba-acceso",
			"max_permission_default": "push"})

	def test_sin_excepcion_declarada_rige_el_default_de_la_plantilla(self):
		t = self._propia()
		miembro = self.env["repo.member"].create({"github_login": "alguien-test"})
		self.assertEqual(t.max_permission_for(miembro), "push")

	def test_el_default_DE_FABRICA_de_cliente_estandar_es_push(self):
		"""La decisión de fábrica, contra el archivo. Subirla es cambiar la spec."""
		self.assertEqual(de_fabrica()["cliente-estandar"]["max_permission_default"],
						 "push")

	def test_una_excepcion_declarada_manda_sobre_el_default(self):
		t = self._propia()
		miembro = self.env["repo.member"].create({"github_login": "lider-test"})
		self.env["repo.policy.access.rule"].create({
			"template_id": t.id, "member_id": miembro.id,
			"max_permission": "admin", "reason": "líder técnico",
		})
		self.assertEqual(t.max_permission_for(miembro), "admin")

	def test_la_escala_de_permisos_ordena_bien(self):
		"""Es la que decide si un permiso observado excede al esperado."""
		Colaborador = self.env["repo.collaborator"]
		self.assertGreater(Colaborador.level_of("admin"), Colaborador.level_of("push"))
		self.assertGreater(Colaborador.level_of("push"), Colaborador.level_of("pull"))
		self.assertEqual(Colaborador.level_of("inventado"), -1)


class TestUnaPlantillaActivaPorClasificacion(TransactionCase):
	"""La ambigüedad que `plantilla_efectiva()` resolvía por orden, prevenida en la fuente.

	Con dos plantillas activas para una clasificación, la resolución tomaba la primera por
	`sequence, name` y nadie se enteraba. Mientras eso decidía contra qué se COMPARABA era
	un empate silencioso; desde B1 decide qué se ESCRIBE en GitHub.

	La guarda es un índice único parcial y no un `@api.constrains`, así que lo que salta
	es un error de integridad: Postgres rechaza antes de que el ORM valide. El mensaje que
	ve la persona se prueba aparte, sobre la función que lo arma.
	"""

	def _crear(self, clasificacion, **extra):
		valores = {
			"name": "Plantilla %s" % uuid.uuid4().hex[:6],
			"code": "code-%s" % uuid.uuid4().hex[:6],
			"classification_default": clasificacion,
		}
		valores.update(extra)
		return self.env["repo.policy.template"].create(valores)

	def _prohibido(self):
		"""Lo que tiene que pasar cuando alguien intenta el empate."""
		return self.assertRaises(IntegrityError)

	def setUp(self):
		super().setUp()
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		# El write queda pendiente en el buffer del ORM y el INSERT de abajo llega
		# antes a Postgres: sin vaciarlo, el índice único salta sobre la plantilla de
		# fábrica en lugar de sobre lo que el test quiere probar.
		self.env.flush_all()
		self.vigente = self._crear("cliente")

	# ------------------------------------------------------------------
	# La guarda
	# ------------------------------------------------------------------

	def test_dos_activas_para_la_misma_clasificacion_no_se_pueden(self):
		with self._prohibido(), mute_logger("odoo.sql_db"):
			with self.env.cr.savepoint():
				self._crear("cliente")

	def test_activar_una_segunda_tampoco_se_puede(self):
		"""No alcanza con vigilar la creación: reactivar entra por otra puerta."""
		guardada = self._crear("cliente", active=False)
		with self._prohibido(), mute_logger("odoo.sql_db"):
			with self.env.cr.savepoint():
				guardada.active = True

	def test_mover_una_plantilla_a_una_clasificacion_ocupada_tampoco(self):
		"""Y la tercera puerta: no crear ni activar, sino mudar."""
		libre = self._crear(False)
		with self._prohibido(), mute_logger("odoo.sql_db"):
			with self.env.cr.savepoint():
				libre.classification_default = "cliente"

	# ------------------------------------------------------------------
	# Las salidas que la restricción deja abiertas a propósito
	# ------------------------------------------------------------------

	def test_archivada_no_compite(self):
		"""La salida para «plantilla en preparación»: se archiva, no se borra."""
		self.vigente.active = False
		self.env.flush_all()
		self.assertTrue(self._crear("cliente").exists())

	def test_pueden_convivir_muchas_archivadas(self):
		primera = self._crear("cliente", active=False)
		segunda = self._crear("cliente", active=False)
		self.env.flush_all()
		self.assertTrue(primera.exists() and segunda.exists())

	def test_sin_clasificacion_pueden_ser_todas_las_que_quieras(self):
		"""Una plantilla sin clasificación no gobierna a nadie: no hay a quién ambiguar."""
		self._crear(False)
		self._crear(False)
		self.env.flush_all()

	# ------------------------------------------------------------------
	# El mensaje, que es la mitad que le sirve a quien lo lee
	# ------------------------------------------------------------------

	def test_el_mensaje_nombra_a_la_que_ya_estaba_y_dice_que_hacer(self):
		mensaje = _mensaje_de_clasificacion_ocupada(
			self.env, _Diagnostico("Key (classification_default)=(cliente) already exists."))
		self.assertIn(self.vigente.name, mensaje)
		self.assertIn("rchiv", mensaje, "tiene que decir qué hacer, no sólo qué pasó")

	def test_si_el_detalle_no_se_entiende_el_mensaje_igual_sirve(self):
		"""Adornar el mensaje no puede romperlo: otra versión de Postgres, otro idioma."""
		mensaje = _mensaje_de_clasificacion_ocupada(self.env, _Diagnostico(""))
		self.assertIn("rchiv", mensaje)

	def test_la_guarda_vive_en_la_base_y_no_solo_en_el_orm(self):
		"""Dos transacciones a la vez no las para ninguna validación de Python."""
		self.assertTrue(index_exists(
			self.env.cr, "repo_policy_template_una_activa_por_clasificacion"))
