# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""La página honesta de lo que todavía no existe.

«Lo futuro se ve, no se toca», del sistema de diseño. El menú tiene sus **siete secciones
fijas desde hoy** y las etapas que faltan ya tienen su casillero, en gris y con su letra.
Cuando llega un bloque no se agrega un menú: **se habilita lo que estaba gris**, y nadie
tiene que reaprender dónde estaba nada.

Lo que hace que eso no sea una promesa vacía es esta pantalla: al hacer clic, la entrada
gris abre una página que dice **qué va a hacer y en qué bloque llega**. Un menú que no
responde se lee como algo roto; uno que explica se lee como un plan.
"""
from odoo import api, fields, models


class RepoComingSoon(models.TransientModel):
	_name = "repo.coming.soon"
	_description = "Funcionalidad de una etapa que todavía no llegó"

	name = fields.Char(string="Qué es", readonly=True)
	stage = fields.Char(string="Llega en", readonly=True)
	description = fields.Text(string="Qué va a hacer", readonly=True)

	@api.model
	def default_get(self, campos):
		valores = super().default_get(campos)
		ctx = self.env.context
		valores.update({
			"name": ctx.get("prm_titulo") or "",
			"stage": ctx.get("prm_bloque") or "",
			"description": ctx.get("prm_que") or "",
		})
		return valores
