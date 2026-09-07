# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La comparación «Exige … · Tiene …» de una rama, y sus TRES estados.

El test que más importa de este archivo es el del tercer estado. GitHub devuelve el mismo
404 cuando una rama no está protegida y cuando quien pregunta no puede saberlo; F1 se
construyó entero alrededor de no confundirlos. Dibujar una rama ilegible como «no tiene»
sería ese defecto volviendo por la ventana de la interfaz — y peor, porque la pantalla es
lo que la gente mira.
"""
import uuid

from odoo.tests.common import TransactionCase


class TestComparacionDeRama(TransactionCase):

	def setUp(self):
		super().setUp()
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		self.env.flush_all()
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "De prueba", "code": "prueba-%s" % uuid.uuid4().hex[:6],
			"classification_default": "cliente",
			"require_pr": True, "required_approvals": 1,
			"block_force_push": True, "block_deletion": True,
		})
		backend = self.env["repo.backend"].create({
			"name": "Ramas %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})
		self.repo = self.env["repo.repository"].create({
			"backend_id": backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "un-repo", "full_name": "cuenta/un-repo",
			"classification": "cliente",
		})

	def _rama(self, **valores):
		base = {"repository_id": self.repo.id, "name": "19.0", "role": "base"}
		base.update(valores)
		return self.env["repo.branch"].create(base)

	# ------------------------------------------------------------------
	# El tercer estado, que es el que este módulo defiende desde F1
	# ------------------------------------------------------------------

	def test_una_rama_ILEGIBLE_no_se_dibuja_como_sin_proteccion(self):
		rama = self._rama(protection_readable=False, protection_cause="no_admin_permission")
		comparacion = rama.comparacion_de_politica()
		self.assertEqual(comparacion["estado"], "ilegible")
		self.assertNotEqual(comparacion["estado"], "sin_proteccion")

	def test_de_una_rama_ilegible_no_se_afirma_que_incumple_nada(self):
		"""Ni que cumple ni que no: de lo que no se pudo leer no se afirma nada."""
		rama = self._rama(protection_readable=False, protection_cause="plan_limit")
		comparacion = rama.comparacion_de_politica()
		self.assertEqual(comparacion["tiene"], [])
		self.assertEqual(comparacion["faltan"], [])

	def test_la_rama_ilegible_dice_su_causa(self):
		"""Rayado, sí, pero con el motivo: el techo de plan y la falta de permiso se
		resuelven de maneras distintas."""
		rama = self._rama(protection_readable=False, protection_cause="plan_limit")
		fila = self._fila(rama)
		self.assertIn("plan", fila["legibilidad"].lower())

	# ------------------------------------------------------------------
	# Los otros cuatro
	# ------------------------------------------------------------------

	def test_sin_proteccion_dice_todo_lo_que_falta(self):
		rama = self._rama(protected=False)
		comparacion = rama.comparacion_de_politica()
		self.assertEqual(comparacion["estado"], "sin_proteccion")
		self.assertEqual(comparacion["tiene"], [])
		self.assertEqual(
			sorted(comparacion["faltan"]),
			["block_deletion", "block_force_push", "require_pr"])

	def test_parcial_separa_lo_que_tiene_de_lo_que_falta(self):
		"""Es la fila que justifica la pantalla: dice POR QUÉ incumple."""
		rama = self._rama(protected=True, protection_json=str({
			"allow_force_pushes": {"enabled": False},
			"allow_deletions": {"enabled": False},
		}))
		comparacion = rama.comparacion_de_politica()
		self.assertEqual(comparacion["estado"], "parcial")
		self.assertEqual(comparacion["faltan"], ["require_pr"])
		self.assertEqual(len(comparacion["tiene"]), 2)

	def test_completa_no_necesita_explicacion(self):
		rama = self._rama(protected=True, protection_json=str({
			"required_pull_request_reviews": {"required_approving_review_count": 1},
			"allow_force_pushes": {"enabled": False},
			"allow_deletions": {"enabled": False},
		}))
		comparacion = rama.comparacion_de_politica()
		self.assertEqual(comparacion["estado"], "completa")
		self.assertEqual(comparacion["faltan"], [])

	def test_una_rama_que_la_politica_no_gobierna_no_exige_nada(self):
		"""Una feature branch no incumple: no hay convención contra la cual medirla."""
		self.env["repo.policy.branch.rule"].create({
			"template_id": self.plantilla.id, "branch_role": "other",
			"require_pr": False, "required_approvals": 0,
			"block_force_push": False, "block_deletion": False,
		})
		rama = self._rama(name="feat/algo", role="other")
		self.assertEqual(rama.comparacion_de_politica()["estado"], "no_exige")

	def test_menos_aprobaciones_de_las_exigidas_no_alcanza(self):
		self.plantilla.required_approvals = 2
		rama = self._rama(protected=True, protection_json=str({
			"required_pull_request_reviews": {"required_approving_review_count": 1},
			"allow_force_pushes": {"enabled": False},
			"allow_deletions": {"enabled": False},
		}))
		self.assertIn("require_pr", rama.comparacion_de_politica()["faltan"])

	def test_los_checks_sin_confirmar_no_cuentan_como_incumplimiento(self):
		"""Misma guarda que en el ruleset: mientras la plantilla no los dé por buenos,
		no se exige ninguno — así que nadie incumple por no tenerlos."""
		self.env["repo.policy.status.check"].create({
			"template_id": self.plantilla.id, "name": "build"})
		self.plantilla.status_checks_defined = False
		rama = self._rama(protected=True, protection_json=str({
			"required_pull_request_reviews": {"required_approving_review_count": 1},
			"allow_force_pushes": {"enabled": False},
			"allow_deletions": {"enabled": False},
		}))
		self.assertEqual(rama.comparacion_de_politica()["estado"], "completa")

	def test_una_proteccion_ilegible_de_parsear_no_rompe_la_pantalla(self):
		"""Un JSON que no se entiende es «no lo tengo», nunca una traza en la cara."""
		rama = self._rama(protected=True, protection_json="{esto no es json ni repr")
		self.assertEqual(rama.comparacion_de_politica()["estado"], "sin_proteccion")

	# ------------------------------------------------------------------
	# Las filas que la pantalla dibuja
	# ------------------------------------------------------------------

	def _fila(self, rama):
		return next(f for f in self.repo.datos_de_ramas() if f["id"] == rama.id)

	def test_la_fila_dice_de_que_regla_salio_el_rol(self):
		"""Un rol sin su origen es una afirmación que nadie puede discutir."""
		rama = self._rama(name="19.0")
		self.assertTrue(self._fila(rama)["regla"])

	def test_el_atraso_solo_aparece_donde_hay_contra_que_compararse(self):
		normal = self._rama(name="19.0", role="base", ahead_upstream=3)
		self.assertIsNone(self._fila(normal)["atraso"])
		espejo = self._rama(name="upstream/19.0", role="mirror",
							ahead_upstream=4, behind_upstream=0)
		self.assertEqual(self._fila(espejo)["atraso"], "+4 / −0")


class TestIncumplenHoy(TransactionCase):
	"""B1.5 · cuántas ramas incumplen cada exigencia, y qué NO se cuenta."""

	def setUp(self):
		super().setUp()
		self.env["repo.policy.template"].search([
			("classification_default", "=", "cliente")]).classification_default = False
		self.env.flush_all()
		self.plantilla = self.env["repo.policy.template"].create({
			"name": "De prueba", "code": "cuenta-%s" % uuid.uuid4().hex[:6],
			"classification_default": "cliente",
			"require_pr": True, "required_approvals": 1,
			"block_force_push": True, "block_deletion": True,
		})
		self.backend = self.env["repo.backend"].create({
			"name": "Cuenta %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
		})

	def _repo_con_rama(self, **rama):
		repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "r-%s" % uuid.uuid4().hex[:6],
			"full_name": "cuenta/r-%s" % uuid.uuid4().hex[:6],
			"classification": "cliente",
		})
		base = {"repository_id": repo.id, "name": "19.0", "role": "base"}
		base.update(rama)
		self.env["repo.branch"].create(base)
		return repo

	def _por_clave(self):
		return {f["clave"]: f for f in self.plantilla.incumplimientos_por_exigencia()}

	def test_cuenta_las_ramas_a_las_que_les_falta_esa_exigencia(self):
		self._repo_con_rama(protected=False)
		self._repo_con_rama(protected=False)
		self.assertEqual(self._por_clave()["require_pr"]["incumplen"], 2)

	def test_una_rama_que_cumple_no_se_cuenta(self):
		self._repo_con_rama(protected=True, protection_json=str({
			"required_pull_request_reviews": {"required_approving_review_count": 1},
			"allow_force_pushes": {"enabled": False},
			"allow_deletions": {"enabled": False},
		}))
		self.assertEqual(self._por_clave()["require_pr"]["incumplen"], 0)

	def test_lo_ILEGIBLE_no_engrosa_el_numero_y_se_cuenta_aparte(self):
		"""Contarlo como incumplimiento acusa a repositorios sanos; dejarlo afuera en
		silencio los cuenta como sanos. Ninguna de las dos es cierta."""
		self._repo_con_rama(protection_readable=False,
							protection_cause="no_admin_permission")
		filas = self._por_clave()
		self.assertEqual(filas["require_pr"]["incumplen"], 0)
		self.assertEqual(filas["require_pr"]["ilegibles"], 1)
		self.assertEqual(filas["require_pr"]["evaluadas"], 0)

	def test_solo_se_miran_las_ramas_que_la_politica_gobierna(self):
		"""Una feature branch no incumple: no hay convención contra la cual medirla."""
		self._repo_con_rama(name="feat/algo", role="other", protected=False)
		self.assertEqual(self._por_clave()["require_pr"]["incumplen"], 0)

	def test_el_catalogo_lista_solo_lo_que_la_plantilla_exige(self):
		claves = set(self._por_clave())
		self.assertIn("require_pr", claves)
		self.assertNotIn("require_signed_commits", claves)
		self.plantilla.require_signed_commits = True
		self.assertIn("require_signed_commits", set(self._por_clave()))
