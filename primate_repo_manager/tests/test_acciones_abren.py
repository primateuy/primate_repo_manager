# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Toda acción de menú del módulo tiene que poder abrirse. Sin excepciones.

POR QUÉ ESTE TEST EXISTE. Se entregó un menú con diez entradas cuyo `context` traía
literales partidos en varias líneas —`'una parte' 'otra parte'`—, que es Python válido y
el servidor guarda sin mirar. El evaluador de expresiones del NAVEGADOR no lo entiende:
las diez pantallas reventaban con «Can not parse python expression» al hacer clic, y ningún
test lo vio porque el módulo carga perfecto.

Lo que se prueba acá es lo mínimo que hay que garantizar de una acción: que su contexto y
su dominio se puedan evaluar, y que el modelo y las vistas que declara existan. No prueba
que la pantalla se vea bien —para eso están los tours— pero sí que se pueda abrir, que es
lo que falló.
"""
import ast

from odoo.tests.common import TransactionCase


class TestLasAccionesAbren(TransactionCase):

	def _acciones(self):
		datos = self.env["ir.model.data"].search([
			("module", "=", "primate_repo_manager"),
			("model", "=", "ir.actions.act_window")])
		return self.env["ir.actions.act_window"].browse(datos.mapped("res_id")).exists()

	def test_hay_acciones_que_probar(self):
		"""Si el módulo dejara de declarar acciones, este archivo pasaría vacío y en
		silencio. Se comprueba que haya algo que probar."""
		self.assertGreater(len(self._acciones()), 10)

	def test_el_contexto_de_cada_accion_es_evaluable(self):
		"""El evaluador del navegador NO acepta concatenación implícita de literales.

		`ast.literal_eval` tampoco la acepta sobre un diccionario ya escrito en una sola
		expresión con literales adyacentes... pero sí la acepta Python. Por eso además de
		evaluar se comprueba que el texto NO tenga saltos de línea reales: un contexto
		partido en varias líneas es la forma en que este defecto llega.
		"""
		for accion in self._acciones():
			crudo = (accion.context or "{}").strip()
			with self.subTest(accion=accion.xml_id or accion.name):
				self.assertNotIn(
					"\n", crudo,
					"el contexto de «%s» está partido en varias líneas; el evaluador del "
					"navegador no lo va a poder leer" % accion.name)
				valor = ast.literal_eval(crudo) if crudo else {}
				self.assertIsInstance(valor, dict)

	def test_el_dominio_de_cada_accion_es_evaluable(self):
		for accion in self._acciones():
			crudo = (accion.domain or "[]").strip()
			with self.subTest(accion=accion.xml_id or accion.name):
				self.assertNotIn("\n", crudo, accion.name)
				if crudo and not crudo.startswith("["):
					continue          # dominios dinámicos, con variables: no se evalúan
				self.assertIsInstance(ast.literal_eval(crudo or "[]"), list)

	def test_cada_accion_apunta_a_un_modelo_que_existe(self):
		for accion in self._acciones():
			with self.subTest(accion=accion.xml_id or accion.name):
				self.assertIn(accion.res_model, self.env,
							  "«%s» apunta a un modelo inexistente" % accion.name)

	def test_cada_accion_puede_armar_sus_vistas(self):
		"""`get_views` es lo que hace el cliente al abrir: si una vista está rota o el
		modelo no la tiene, falla acá y no en la cara del usuario."""
		for accion in self._acciones():
			with self.subTest(accion=accion.xml_id or accion.name):
				modos = [m.strip() for m in (accion.view_mode or "list").split(",")]
				vistas = [(False, m if m != "tree" else "list") for m in modos]
				self.env[accion.res_model].get_views(vistas)

	def test_toda_entrada_de_menu_tiene_accion(self):
		"""Un menú sin acción no hace nada al clickearlo, que es la peor respuesta
		posible: parece roto sin decir por qué."""
		datos = self.env["ir.model.data"].search([
			("module", "=", "primate_repo_manager"), ("model", "=", "ir.ui.menu")])
		menus = self.env["ir.ui.menu"].browse(datos.mapped("res_id")).exists()
		self.assertTrue(menus)
		for menu in menus:
			hojas = not self.env["ir.ui.menu"].search_count(
				[("parent_id", "=", menu.id)])
			if hojas:
				with self.subTest(menu=menu.complete_name):
					self.assertTrue(
						menu.action,
						"«%s» es una hoja del menú y no abre nada" % menu.complete_name)
