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
		"data/repo_cron_data.xml",
		"views/repo_backend_views.xml",
		"views/repo_audit_views.xml",
		"views/repo_write_views.xml",
		"views/repo_plan_approve_views.xml",
		"views/repo_operation_builder_views.xml",
		"views/repo_policy_views.xml",
		"views/repo_member_views.xml",
		"views/repo_config_settings_views.xml",
		"views/repo_module_views.xml",
		"views/repo_panel_views.xml",
		"views/repo_pendientes_views.xml",
		# El asistente va ANTES del menú que lo referencia: una acción que todavía
		# no existe rompe la carga del menuitem.
		"wizards/repo_repository_create_views.xml",
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
			# El vocabulario compartido va después de los tokens y antes de todo lo demás:
			# chips, tarjetas, antes/después y el casillero apagado los usan las pantallas.
			"primate_repo_manager/static/src/scss/components.scss",
			"primate_repo_manager/static/src/apagado/apagado.js",
			"primate_repo_manager/static/src/apagado/apagado.xml",
			"primate_repo_manager/static/src/bitacora/bitacora.js",
			"primate_repo_manager/static/src/bitacora/bitacora.xml",
			"primate_repo_manager/static/src/bitacora/bitacora.scss",
			"primate_repo_manager/static/src/plan/plan_ops.js",
			"primate_repo_manager/static/src/plan/plan_ops.xml",
			"primate_repo_manager/static/src/plan/plan_ops.scss",
			"primate_repo_manager/static/src/barra/barra.js",
			"primate_repo_manager/static/src/barra/barra.xml",
			"primate_repo_manager/static/src/barra/barra.scss",
			"primate_repo_manager/static/src/delta/delta.js",
			"primate_repo_manager/static/src/delta/delta.xml",
			"primate_repo_manager/static/src/delta/delta.scss",
			"primate_repo_manager/static/src/hallazgos/hallazgos.js",
			"primate_repo_manager/static/src/hallazgos/hallazgos.xml",
			"primate_repo_manager/static/src/hallazgos/hallazgos.scss",
			"primate_repo_manager/static/src/checks/checks.js",
			"primate_repo_manager/static/src/checks/checks.xml",
			"primate_repo_manager/static/src/checks/checks.scss",
			"primate_repo_manager/static/src/exigencias/exigencias.js",
			"primate_repo_manager/static/src/exigencias/exigencias.xml",
			"primate_repo_manager/static/src/exigencias/exigencias.scss",
			"primate_repo_manager/static/src/ramas/ramas.js",
			"primate_repo_manager/static/src/ramas/ramas.xml",
			"primate_repo_manager/static/src/ramas/ramas.scss",
			"primate_repo_manager/static/src/panel/panel.js",
			"primate_repo_manager/static/src/panel/panel.xml",
			"primate_repo_manager/static/src/panel/panel.scss",
			"primate_repo_manager/static/src/promocion/promocion.js",
			"primate_repo_manager/static/src/promocion/promocion.xml",
			"primate_repo_manager/static/src/promocion/promocion.scss",
			"primate_repo_manager/static/src/live_progress/live_progress.js",
			"primate_repo_manager/static/src/live_progress/live_progress.xml",
			"primate_repo_manager/static/src/live_progress/live_progress.scss",
		],
		# ========= MODO OSCURO =========
		#
		# Odoo 19 Enterprise no resuelve el tema con una clase: compila un bundle aparte y
		# lo sirve según `res.users.settings.color_scheme`. Este archivo entra SÓLO ahí, y
		# redefine las mismas variables de `:root` que declara `tokens.scss`.
		#
		# Por eso no hace falta sacarlo del bundle claro: no está listado arriba. Y por eso
		# ningún componente del módulo pregunta en qué modo está.
		#
		# En una instalación Community este bundle no lo sirve nadie y el archivo
		# simplemente no se carga — el módulo se ve en claro, que es lo correcto: el tema
		# oscuro es de Enterprise.
		"web.assets_web_dark": [
			"primate_repo_manager/static/src/scss/tokens.dark.scss",
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
