# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
{
	"name": "Primate Repo Manager",
	"version": "19.0.1.0.0",
	"category": "Services/Project",
	"summary": "Gobernanza de repositorios GitHub desde Odoo: auditoría, permisos, "
			   "protección de ramas y gestión de PRs",
	"author": "PrimateUY",
	"website": "https://primate.uy",
	"license": "AGPL-3",
	"depends": ["base", "mail", "queue_job"],
	"data": [
		"security/repo_security.xml",
		"security/ir.model.access.csv",
		"views/repo_backend_views.xml",
		"views/repo_menus.xml",
		"wizards/repo_key_rotation_views.xml",
	],
	"external_dependencies": {
		# PyJWT: firma del JWT que pide el token de instalación de la GitHub App.
		# cryptography ya viene con Odoo — NO la declaramos ni la pineamos acá:
		# forzar su versión rompe el arranque de la instancia (pyOpenSSL del sistema).
		"python": ["PyJWT"],
	},
	"installable": True,
	"application": True,
}
