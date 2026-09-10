/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Los dos avisos permanentes de la barra — página 2a del entregable.
 *
 * SON DOS Y NO MÁS, y ésa es la decisión. El diseño dice: «Solo dos cosas llegan por
 * campana: un plan que te toca aprobar y un plan que terminó de aplicarse. Los hallazgos
 * nuevos no notifican de a uno.» Acá vale lo mismo con más razón, porque la barra está
 * SIEMPRE a la vista: un aviso permanente que aparece seguido deja de leerse, y el día
 * que aparezca el que importa va a estar tapado por la costumbre.
 *
 *   · auditoría en curso — porque los números que estés mirando no son los de ahora;
 *   · un plan espera tu aprobación — porque es lo único que se frena esperando a alguien.
 *
 * NO SE CONSULTA SOLO EN UN BUCLE. Se pregunta al cargar y cuando el usuario vuelve a la
 * pestaña. Un aviso que se refresca cada diez segundos es una consulta por usuario por
 * diez segundos para decir «no pasa nada» el 99 % del tiempo.
 */

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class BarraRepoManager extends Component {
	static template = "primate_repo_manager.BarraRepoManager";
	static props = {};

	setup() {
		this.orm = useService("orm");
		this.action = useService("action");
		this.state = useState({ auditoria: null, plan: null });
		this.alVolver = () => {
			if (document.visibilityState === "visible") {
				this.cargar();
			}
		};
		onWillStart(() => this.cargar());
		document.addEventListener("visibilitychange", this.alVolver);
		onWillUnmount(() =>
			document.removeEventListener("visibilitychange", this.alVolver));
	}

	async cargar() {
		const datos = await this.orm.call("repo.audit.run", "avisos_de_barra", []);
		this.state.auditoria = datos.auditoria;
		this.state.plan = datos.plan;
	}

	abrirAuditoria() {
		this.action.doAction({
			type: "ir.actions.act_window", res_model: "repo.audit.run",
			res_id: this.state.auditoria.id, views: [[false, "form"]],
		});
	}

	abrirPlan() {
		this.action.doAction({
			type: "ir.actions.act_window", res_model: "repo.write.plan",
			res_id: this.state.plan.id, views: [[false, "form"]],
		});
	}
}

// El orden en la barra: los avisos del módulo van antes que la campana y el usuario.
registry.category("systray").add(
	"primate_repo_manager.barra", { Component: BarraRepoManager }, { sequence: 60 });
