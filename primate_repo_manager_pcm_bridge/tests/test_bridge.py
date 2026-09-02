# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""El puente sólo agrega una entrada de menú, y el core no sabe que existe."""
from odoo.tests.common import TransactionCase


class TestBridge(TransactionCase):

	def test_el_menu_apunta_a_la_accion_del_core(self):
		menu = self.env.ref("primate_repo_manager_pcm_bridge.menu_pcm_repo_manager")
		self.assertEqual(
			menu.action.id,
			self.env.ref("primate_repo_manager.action_repo_repository").id)

	def test_el_core_no_referencia_a_pcm(self):
		"""El core tiene que instalar sin PCM. Si alguien mete una referencia, esto avisa."""
		import os

		core = os.path.join(os.path.dirname(__file__), "..", "..", "primate_repo_manager")
		encontradas = []
		for raiz, _dirs, archivos in os.walk(core):
			if "__pycache__" in raiz:
				continue
			for archivo in archivos:
				if not archivo.endswith((".py", ".xml", ".csv")):
					continue
				ruta = os.path.join(raiz, archivo)
				with open(ruta, encoding="utf-8") as fh:
					if "primate_cloud_manager" in fh.read():
						encontradas.append(os.path.relpath(ruta, core))
		self.assertEqual(
			encontradas, [],
			"el core no puede referenciar PCM; para eso está el puente: %s" % encontradas)
