/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Panel de salud — páginas 3a y 1b del entregable.
 *
 * TRES NÚMEROS, UNA FRASE Y UN BOTÓN. Es todo lo que ve alguien que no opera; el detalle
 * queda plegado debajo y lo abre quien lo necesita. No hay dos paneles: es la misma
 * pantalla, con el pliegue cerrado o abierto.
 *
 * EL PLIEGUE RECUERDA SU ESTADO, por usuario y en su propio navegador. Quien lo abrió una
 * vez lo encuentra abierto. Es una comodidad, no un dato: si el navegador lo pierde, la
 * pantalla abre plegada y no pasa nada.
 *
 * DÍA UNO SIN MAQUILLAJE. Lo que decide qué se muestra vive en el servidor —ahí está la
 * regla y su explicación— y esta pantalla no inventa un cero donde el servidor mandó un
 * guión. Un panel que en su primera corrida muestra buenos números sobre una organización
 * que todavía no gobierna nada enseña a no creerle.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Apagado } from "../apagado/apagado";

const CLAVE_PLIEGUE = "prm_panel_detalle_abierto";

export class PanelDeSalud extends Component {
	static template = "primate_repo_manager.PanelDeSalud";
	static components = { Apagado };
	static props = ["*"];

	setup() {
		this.orm = useService("orm");
		this.action = useService("action");
		this.state = useState({ datos: null, abierto: this.pliegueGuardado() });
		onWillStart(async () => {
			this.state.datos = await this.orm.call(
				"repo.health.panel", "datos", [], {});
		});
	}

	async cambiarConexion(ev) {
		this.state.datos = await this.orm.call(
			"repo.health.panel", "datos", [parseInt(ev.target.value, 10)], {});
	}

	// --- el pliegue ---------------------------------------------------------

	pliegueGuardado() {
		// El almacenamiento del navegador puede fallar —modo privado, permisos— y eso no
		// puede tumbar la pantalla: si no se puede leer, se abre plegada.
		try {
			return window.localStorage.getItem(CLAVE_PLIEGUE) === "1";
		} catch {
			return false;
		}
	}

	alternarPliegue() {
		this.state.abierto = !this.state.abierto;
		try {
			window.localStorage.setItem(CLAVE_PLIEGUE, this.state.abierto ? "1" : "0");
		} catch {
			// Ni se avisa: es una comodidad, no un dato.
		}
	}

	// --- lo que se pinta ----------------------------------------------------

	get datos() {
		return this.state.datos;
	}

	/** El valor de un número, o el guión cuando NO HAY NADA QUE MEDIR. */
	texto(numero) {
		return numero.valor === null || numero.valor === undefined
			? "—"
			: `${numero.valor}${numero.unidad || ""}`;
	}

	/**
	 * Hacia dónde va el número, que NO es lo mismo que si subió o bajó.
	 *
	 * Más ramas protegidas es mejor; más hallazgos abiertos es peor. Sin esta distinción
	 * el panel pintaría de verde una semana en la que aparecieron doce hallazgos nuevos,
	 * sólo porque el número creció.
	 */
	sentido(numero) {
		if (!numero.delta) {
			return "igual";
		}
		const masEsMejor = numero.clave !== "hallazgos";
		const subio = numero.delta > 0;
		return subio === masEsMejor ? "mejor" : "peor";
	}

	flecha(numero) {
		if (!numero.delta) {
			return "=";
		}
		return numero.delta > 0 ? "▲" : "▼";
	}

	sinMedida(numero) {
		return numero.valor === null || numero.valor === undefined;
	}

	get cuando() {
		const c = this.datos && this.datos.corrida;
		if (!c || !c.hubo) {
			return "";
		}
		return c.cuando ? c.cuando : "";
	}

	// --- las salidas --------------------------------------------------------

	verHallazgos() {
		this.action.doAction(
			"primate_repo_manager.action_repo_audit_finding", {});
	}

	verPlanes() {
		this.action.doAction("primate_repo_manager.action_repo_write_plan", {});
	}

	verPolitica() {
		this.action.doAction(
			"primate_repo_manager.action_repo_policy_template", {});
	}

	verRepositorios() {
		this.action.doAction("primate_repo_manager.action_repo_repository", {});
	}

	verCorrida() {
		if (this.datos.corrida.id) {
			this.action.doAction({
				type: "ir.actions.act_window",
				res_model: "repo.audit.run",
				res_id: this.datos.corrida.id,
				views: [[false, "form"]],
			});
		}
	}

	get tituloDetalle() {
		return this.state.abierto
			? _t("Ocultar el detalle")
			: _t("Ver el detalle: por gravedad, por tipo de repositorio, cuentas sin dueño");
	}
}

registry.category("actions").add("repo_panel_salud", PanelDeSalud);
