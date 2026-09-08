# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Que TODA pantalla de asistente tenga permisos declarados.

Vive en su propio archivo porque no es de ningún bloque: es una propiedad del módulo
entero, y el asistente que se agregue mañana queda cubierto por existir.
"""
import uuid

from odoo.tests.common import TransactionCase, tagged


# post_install NO ES DECORACIÓN. Odoo borra los registros huérfanos —la fila de ACL
# cuyo renglón alguien sacó del csv— recién al terminar de cargar TODOS los módulos, y los
# tests at_install corren antes de eso. Con at_install este barrido miraba la fila vieja
# todavía viva y daba verde sobre un permiso que en la base ya no iba a existir: la
# mutación lo demostró. Es «el archivo no es el sistema» con la vuelta del momento.
@tagged("post_install", "-at_install")
class TestTodoAsistenteTieneACL(TransactionCase):
	"""El agujero del asistente de nacimiento, barrido de una — y para siempre.

	Los tests corren como SUPERUSUARIO, así que una pantalla sin permisos declarados
	anda perfecto en la suite y le explota en la cara a la primera persona que la abre.
	Este test recorre TODOS los modelos transitorios del módulo y exige que cada uno
	tenga su ACL: el asistente que se agregue mañana queda cubierto por existir.
	"""

	def setUp(self):
		super().setUp()
		self.backend = self.env["repo.backend"].create({
			"name": "ACL %s" % uuid.uuid4().hex[:6],
			"owner_login": "org-%s" % uuid.uuid4().hex[:8],
			"owner_type": "organization", "app_id": "1", "installation_id": "2",
			"state": "connected", "environment": "sandbox"})

	def test_una_PERSONA_con_rol_de_lider_puede_usar_el_asistente(self):
		"""Los tests corren como superusuario y la ACL no se ve: este lo hace como
		persona.

		Lo destapó el ensayo contra el sandbox, no la suite: el asistente no tenía ACL y
		cualquiera que lo abriera se comía un «No group currently allows this
		operation». Una pantalla sin permisos declarados es una pantalla que anda para
		el que la escribió y para nadie más.
		"""
		lider = self.env["res.users"].create({
			"name": "Líder de prueba", "login": "lider-%s" % uuid.uuid4().hex[:8],
			"group_ids": [(4, self.env.ref("primate_repo_manager.group_repo_lead").id),
						  (4, self.env.ref("base.group_user").id)],
		})
		asistente = self.env["repo.repository.create.wizard"].with_user(lider).create({
			"backend_id": self.backend.id, "base": "Mutualista Casmu",
			"classification": "cliente", "version": "19.0"})
		self.assertTrue(asistente.nombre_previsto)

	def test_ningun_asistente_del_modulo_se_queda_sin_ACL(self):
		sin_acl = []
		for nombre, modelo in self.env.registry.items():
			if not nombre.startswith("repo."):
				continue
			if not getattr(modelo, "_transient", False):
				continue
			if not self.env["ir.model.access"].search_count([
					("model_id.model", "=", nombre)]):
				sin_acl.append(nombre)
		self.assertFalse(
			sin_acl,
			"estos asistentes no tienen ACL y van a fallar con «No group currently "
			"allows this operation» para cualquiera que no sea superusuario: %s"
			% ", ".join(sorted(sin_acl)))

	def test_los_asistentes_se_pueden_usar_con_el_rol_que_corresponde(self):
		"""No alcanza con que exista una fila de ACL: tiene que darle a un rol del
		módulo, y no a un grupo que nadie tiene."""
		grupos = {
			self.env.ref("primate_repo_manager.group_repo_reader").id,
			self.env.ref("primate_repo_manager.group_repo_lead").id,
			self.env.ref("primate_repo_manager.group_repo_admin").id,
		}
		huerfanos = []
		for nombre, modelo in self.env.registry.items():
			if not nombre.startswith("repo.") or not getattr(modelo, "_transient", False):
				continue
			accesos = self.env["ir.model.access"].search([
				("model_id.model", "=", nombre), ("perm_create", "=", True)])
			if not accesos.filtered(lambda a: a.group_id.id in grupos):
				huerfanos.append(nombre)
		self.assertFalse(huerfanos, ", ".join(sorted(huerfanos)))
