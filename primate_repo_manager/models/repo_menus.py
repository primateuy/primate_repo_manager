# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""E4.4 · las dos puertas de entrada del módulo, según quién abre.

EL DISEÑO LAS PIDE POR UNA RAZÓN CONCRETA: no todos entran a lo mismo. Quien dirige abre
para saber si mejoramos o empeoramos —tres números y una frase— y quien opera abre para
ver qué hay que arreglar hoy. Aterrizar a los dos en la misma pantalla obliga a uno de los
dos a navegar antes de empezar, todos los días.

    Líder y Administrador  →  Hallazgos   (lo que hay que arreglar)
    Lectura                →  Panel        (cómo venimos)

POR QUÉ EL ROL MÁS ALTO ATERRIZA EN LO TÉCNICO, que parece al revés. El rol de Lectura es
el de quien mira sin operar; los otros dos son de quien trabaja con esto. La jerarquía de
permisos no es la jerarquía de intenciones, y confundirlas es lo que haría que el técnico
—que entra veinte veces por día— empiece siempre por el panel que ya vio.

ES UN DEFAULT, NO UNA JAULA: el menú entero sigue estando, y quien quiera lo otro lo tiene
a un clic. Se implementa como acción de inicio del usuario, que es el mecanismo de Odoo
para esto y respeta que alguien la cambie después.
"""
from odoo import api, models


class ResUsers(models.Model):
	_inherit = "res.users"

	@api.model_create_multi
	def create(self, vals_list):
		usuarios = super().create(vals_list)
		usuarios._repo_manager_puerta_de_entrada()
		return usuarios

	def write(self, vals):
		resultado = super().write(vals)
		# También al DARLE el rol a alguien que ya existía, que es como pasa en la
		# práctica: los usuarios no se crean con el rol puesto, se les agrega después.
		if "group_ids" in vals or "groups_id" in vals:
			self._repo_manager_puerta_de_entrada()
		return resultado

	def _repo_manager_puerta_de_entrada(self):
		"""Deja la acción de inicio del usuario según su rol, si no eligió otra.

		NO SE PISA UNA ELECCIÓN AJENA. Si el usuario ya tiene una acción de inicio —la
		suya, o la de otro módulo— no se toca: un default que sobrescribe lo que alguien
		configuró deja de ser un default.
		"""
		panel = self.env.ref(
			"primate_repo_manager.action_repo_panel_salud", raise_if_not_found=False)
		hallazgos = self.env.ref(
			"primate_repo_manager.action_repo_audit_finding", raise_if_not_found=False)
		if not panel or not hallazgos:
			return
		lider = self.env.ref("primate_repo_manager.group_repo_lead",
							 raise_if_not_found=False)
		lectura = self.env.ref("primate_repo_manager.group_repo_reader",
							   raise_if_not_found=False)
		for usuario in self:
			if usuario.action_id:
				continue
			if lider and lider in usuario.group_ids:
				usuario.action_id = hallazgos.id
			elif lectura and lectura in usuario.group_ids:
				usuario.action_id = panel.id
