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
from xml.etree import ElementTree

from odoo.tests.common import TransactionCase
from odoo.tools.misc import file_path

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
