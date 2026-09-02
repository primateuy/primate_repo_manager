# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
"""Permiso OBSERVADO de una persona sobre un repo.

Es la foto de lo que GitHub dice hoy, no lo que la política declara. La comparación
entre ambas cosas es la que produce el finding de "permiso excedido".
"""
from odoo import api, fields, models

# Orden de menor a mayor: se usa para decidir si un permiso excede al esperado.
PERMISSION_LEVELS = ["pull", "triage", "push", "maintain", "admin"]

# GitHub habla DOS vocabularios para lo mismo y los mezcla según el endpoint: el campo
# `role_name` de /collaborators devuelve "read"/"write", mientras que el objeto
# `permissions` y los endpoints de permisos usan "pull"/"push". Verificado contra la API
# real: dyturralbe figura como "write" en primateuy/primate_IA_hub.
#
# EL MAPA COMPLETO ESTÁ EN github_client.py, arriba de todo: los tres vocabularios, los
# tres episodios en que nos mordió, y la regla práctica. Antes de comparar un permiso
# contra otro, leelo — el campo `permission` colapsa roles y no sirve para comparar.
ROLE_NAME_TO_PERMISSION = {
	"read": "pull",
	"write": "push",
	"triage": "triage",
	"maintain": "maintain",
	"admin": "admin",
}

PERMISSIONS = [
	("pull", "Lectura (pull)"),
	("triage", "Triage"),
	("push", "Escritura (push)"),
	("maintain", "Mantenimiento"),
	("admin", "Administrador"),
]


class RepoCollaborator(models.Model):
	_name = "repo.collaborator"
	_description = "Permiso observado de una persona sobre un repositorio"
	_order = "repository_id, member_id"

	repository_id = fields.Many2one(
		"repo.repository", string="Repositorio", required=True,
		ondelete="cascade", index=True)
	member_id = fields.Many2one(
		"repo.member", string="Persona", required=True, ondelete="cascade", index=True)
	permission = fields.Selection(PERMISSIONS, string="Permiso", required=True)
	source = fields.Selection(
		[("direct", "Directo"), ("organization", "Por la organización")],
		string="Origen", default="direct")

	_collaborator_uniq = models.Constraint(
		"UNIQUE (repository_id, member_id)",
		"Esa persona ya figura como colaboradora del repositorio.")

	@staticmethod
	def level_of(permission):
		"""Posición del permiso en la escala. -1 si es desconocido."""
		try:
			return PERMISSION_LEVELS.index(permission)
		except ValueError:
			return -1

	@api.model
	def permission_from_role_name(self, role_name):
		"""Traduce el vocabulario de roles de GitHub al de permisos.

		Ante un valor desconocido devuelve el más restrictivo, nunca uno permisivo: si
		GitHub agrega un rol nuevo, el peor error posible sería asumir que da más acceso
		del que da y no reportar un permiso excedido.
		"""
		return ROLE_NAME_TO_PERMISSION.get((role_name or "").strip().lower(), "pull")
