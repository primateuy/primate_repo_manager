# Copyright 2026 - PrimateUY
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
{
	"name": "Primate Repo Manager — puente con PCM",
	"version": "19.0.1.0.0",
	"category": "Services/Project",
	"summary": "Entrada a Repo Manager desde el shell de Primate Cloud Manager",
	"author": "PrimateUY",
	"website": "https://primate.uy",
	"license": "AGPL-3",
	# auto_install: aparece solo cuando los DOS módulos están instalados, y desaparece si
	# falta alguno. Es lo que permite que el core no tenga NINGUNA referencia a PCM.
	"depends": ["primate_repo_manager", "primate_cloud_manager"],
	"auto_install": True,
	"data": ["views/pcm_bridge_menus.xml"],
	"installable": True,
}
