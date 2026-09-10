# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E3.2b · los tres hallazgos de higiene.

LO QUE SE VIGILA ACÁ ES UNA SOLA COSA, Y ES LA QUE PUEDE HACER DAÑO: que el módulo nunca
ofrezca borrar una rama con trabajo que no está en ningún otro lado. Todo lo demás de este
archivo existe para sostener esa distinción.
"""
import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class BaseHigiene(TransactionCase):

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "Higiene %s" % uuid.uuid4().hex[:6],
			"owner_login": "cuenta-%s" % uuid.uuid4().hex[:8],
			"owner_type": "user", "app_id": "1", "installation_id": "2",
			"state": "connected"})
		self.repo = self.env["repo.repository"].create({
			"backend_id": self.backend.id, "github_id": uuid.uuid4().hex[:8],
			"name": "uno", "full_name": "cuenta/uno",
			"classification": "cliente",
			"pushed_at": fields.Datetime.now()})
		self.run = self.env["repo.audit.run"].create({
			"name": "H", "backend_id": self.backend.id, "state": "done"})

	def _rama(self, nombre, ahead=0, legible=True, contra="17.0", ultimo=None, rol="version"):
		return self.env["repo.branch"].create({
			"repository_id": self.repo.id, "name": nombre, "role": rol,
			"ahead_of_line": ahead, "line_comparison_readable": legible,
			"line_branch_name": contra,
			"last_commit_date": ultimo or fields.Datetime.now(),
			"last_commit_sha": "sha-%s" % nombre})

	def _hallazgos(self, tipo):
		self.env["repo.audit.engine"].evaluate(self.run)
		return self.env["repo.audit.finding"].search([
			("run_id", "=", self.run.id), ("finding_type", "=", tipo),
			("repository_id", "=", self.repo.id)])


class TestLosTresHallazgos(BaseHigiene):

	def test_una_rama_integrada_es_candidata_y_dice_CONTRA_QUE_se_midio(self):
		"""«Integrada a 17.0-prod» y «integrada a 17.0» son afirmaciones distintas, y
		quien decide borrar necesita saber cuál está leyendo."""
		self._rama("17.0_vieja", ahead=0, contra="17.0-prod")

		hallazgo = self._hallazgos("branch_integrated_candidate")

		self.assertEqual(len(hallazgo), 1)
		self.assertIn("17.0-prod", hallazgo.summary)
		self.assertIn("integrada", hallazgo.summary)
		self.assertEqual(hallazgo.subject, "17.0_vieja")

	def test_la_integrada_es_candidata_AUNQUE_SEA_DE_HOY(self):
		"""Ciclo de vida, no fecha: la rama integrada ayer es candidata legítima."""
		self._rama("17.0_recien", ahead=0, ultimo=fields.Datetime.now())
		self.assertTrue(self._hallazgos("branch_integrated_candidate"))

	def test_una_rama_con_trabajo_y_SIN_ACTIVIDAD_es_abandonada(self):
		self._rama("17.0_olvidada", ahead=7,
				   ultimo=fields.Datetime.now() - timedelta(days=300))

		hallazgo = self._hallazgos("branch_abandoned")

		self.assertEqual(len(hallazgo), 1)
		self.assertIn("7", hallazgo.summary)
		self.assertIn("nunca llegaron", hallazgo.summary)

	def test_una_rama_con_trabajo_y_ACTIVA_no_es_nada(self):
		"""Trabajo en curso no es higiene."""
		self._rama("17.0_en_curso", ahead=3, ultimo=fields.Datetime.now())
		self.assertFalse(self._hallazgos("branch_abandoned"))
		self.assertFalse(self._hallazgos("branch_integrated_candidate"))

	def test_lo_que_NO_SE_PUDO_COMPARAR_no_es_ninguna_de_las_dos(self):
		"""Sin `compare` no se sabe si tiene trabajo propio. Proponer borrar acá sería
		el error más caro que este módulo puede cometer."""
		self._rama("17.0_ilegible", ahead=0, legible=False,
				   ultimo=fields.Datetime.now() - timedelta(days=900))
		self.assertFalse(self._hallazgos("branch_integrated_candidate"))
		self.assertFalse(self._hallazgos("branch_abandoned"))

	def test_un_repositorio_sin_push_hace_mucho_es_archivable(self):
		self.repo.pushed_at = fields.Datetime.now() - timedelta(days=800)
		hallazgo = self._hallazgos("repository_archivable")
		self.assertEqual(len(hallazgo), 1)
		self.assertIn("push", hallazgo.summary)

	def test_un_repositorio_YA_ARCHIVADO_no_se_propone_archivar(self):
		self.repo.write({"archived": True,
						 "pushed_at": fields.Datetime.now() - timedelta(days=800)})
		self.assertFalse(self._hallazgos("repository_archivable"))

	def test_un_repositorio_activo_no_es_archivable(self):
		self.assertFalse(self._hallazgos("repository_archivable"))


class TestLaGuardaQueNoSeNegocia(BaseHigiene):
	"""Que la rama abandonada NUNCA aparezca como planificable.

	Es el único hallazgo del módulo donde «remediar» significaría OFRECER PERDER TRABAJO.
	"""

	def test_la_rama_abandonada_NO_es_planificable(self):
		self._rama("17.0_olvidada", ahead=7,
				   ultimo=fields.Datetime.now() - timedelta(days=300))
		hallazgo = self._hallazgos("branch_abandoned")
		self.assertTrue(hallazgo)
		self.assertFalse(hallazgo.can_be_planned,
						 "el módulo está ofreciendo borrar trabajo sin integrar")
		self.assertTrue(hallazgo.why_not_planned)
		self.assertIn("nunca llegaron", hallazgo.why_not_planned)

	def test_la_abandonada_no_entra_al_plan_NI_POR_LA_PUERTA_DE_ATRAS(self):
		"""`agregar_al_borrador` es la otra puerta —el arrastre y el botón de la lista—
		y tiene que negarse igual. Una guarda que vale en una sola de las dos puertas es
		una guarda que no vale."""
		self._rama("17.0_olvidada", ahead=7,
				   ultimo=fields.Datetime.now() - timedelta(days=300))
		hallazgo = self._hallazgos("branch_abandoned")

		resultado = hallazgo.agregar_al_borrador()

		self.assertEqual(resultado["agregadas"], 0)
		self.assertTrue(resultado["rechazados"])

	def test_la_INTEGRADA_si_se_puede_planificar(self):
		"""La exención es para la abandonada y sólo para ella: si esto también se negara,
		la higiene no serviría para nada y nadie lo notaría."""
		self._rama("17.0_vieja", ahead=0)
		hallazgo = self._hallazgos("branch_integrated_candidate")
		self.assertTrue(hallazgo.remediation_payload)
		self.assertEqual(hallazgo.remediation_action, "delete_branch")


class TestLosUmbralesSonConfigurables(BaseHigiene):

	def _poner(self, clave, valor):
		self.env["ir.config_parameter"].sudo().set_param(clave, str(valor))

	def test_el_umbral_de_abandono_se_lee_de_los_ajustes(self):
		self._rama("17.0_olvidada", ahead=7,
				   ultimo=fields.Datetime.now() - timedelta(days=100))
		self.assertFalse(self._hallazgos("branch_abandoned"),
						 "con 6 meses de fábrica, 100 días no es abandono")

		self._poner("repo_manager.branch_abandoned_months", 2)
		self.assertTrue(self._hallazgos("branch_abandoned"))

	def test_el_umbral_de_archivado_se_lee_de_los_ajustes(self):
		self.repo.pushed_at = fields.Datetime.now() - timedelta(days=200)
		self.assertFalse(self._hallazgos("repository_archivable"))

		self._poner("repo_manager.repo_archive_months", 3)
		self.assertTrue(self._hallazgos("repository_archivable"))
