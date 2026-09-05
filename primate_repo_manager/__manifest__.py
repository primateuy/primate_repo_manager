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
		# `hr` es necesario para vincular cuentas de GitHub con empleados: el DoD de F1
	# pide reportar las cuentas sin ese vínculo.
	"depends": ["base", "mail", "bus", "hr", "queue_job"],
	"data": [
		"security/repo_security.xml",
		"security/ir.model.access.csv",
		"data/repo_queue_data.xml",
		"data/repo_rules_data.xml",
		"data/repo_policy_data.xml",
		"data/repo_config_data.xml",
		"views/repo_backend_views.xml",
		"views/repo_audit_views.xml",
		"views/repo_write_views.xml",
		"views/repo_plan_approve_views.xml",
		"views/repo_operation_builder_views.xml",
		"views/repo_policy_views.xml",
		"views/repo_member_views.xml",
		"views/repo_config_settings_views.xml",
		"views/repo_menus.xml",
		"report/repo_audit_report.xml",
		"wizards/repo_key_rotation_views.xml",
		"views/repo_write_enable_views.xml",
	],
	"external_dependencies": {
		# PyJWT: firma del JWT que pide el token de instalación de la GitHub App.
		# cryptography ya viene con Odoo — NO la declaramos ni la pineamos acá:
		# forzar su versión rompe el arranque de la instancia (pyOpenSSL del sistema).
		"python": ["PyJWT"],
	},
	"assets": {
		"web.assets_backend": [
			# Los tokens van PRIMERO: todo lo demás los usa.
			"primate_repo_manager/static/src/scss/tokens.scss",
			"primate_repo_manager/static/src/live_progress/live_progress.js",
			"primate_repo_manager/static/src/live_progress/live_progress.xml",
			"primate_repo_manager/static/src/live_progress/live_progress.scss",
		],
		# El tour vive en su propio bundle: no viaja a la pantalla de nadie, sólo se carga
		# cuando corren los tests.
		"web.assets_tests": [
			"primate_repo_manager/static/tests/tours/**/*",
		],
	},
	"installable": True,
	"application": True,
}
