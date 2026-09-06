/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Promover un módulo: elegir qué copia gana — página 5b del entregable.
 *
 * SIN PRESELECCIÓN, Y ESO ES LA PANTALLA ENTERA. El botón de continuar nace deshabilitado
 * y las tarjetas tienen el mismo peso visual: mismo tamaño, mismo borde, mismo orden
 * estable por nombre de repositorio. Ninguna arriba, ninguna destacada, ninguna con un
 * distintivo de «recomendada».
 *
 * POR QUÉ NI SIQUIERA UNA ETIQUETA DE «REFERENCIA», que el mockup sí tiene: cualquier
 * marca funciona como recomendación, y el punto de esta pantalla es que la decisión sea de
 * quien mira. Es un desvío deliberado del diseño, anotado en el checklist de cobertura.
 *
 * LA CONSECUENCIA SE LEE ANTES DE ELEGIR, no después. Cada tarjeta dice qué desaparece si
 * se elige esa — con los hechos del inventario y sin inventar los que no tenemos.
 *
 * EL DIFF ES LO ÚNICO CARO Y VA BAJO PEDIDO: dos lecturas de árbol, sobre un par concreto,
 * cuando alguien lo pide. Nunca al abrir, nunca para todas las combinaciones.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class PromocionDeModulo extends Component {
	static template = "primate_repo_manager.PromocionDeModulo";
	static props = ["*"];

	setup() {
		this.orm = useService("orm");
		this.action = useService("action");
		this.state = useState({
			datos: null,
			elegida: null,      // nace en null: no hay opción por defecto
			destino: null,
			limpiar: true,
			diff: null,
			comparando: false,
			parA: null,
			parB: null,
		});
		this.moduleId = this.props.action.context.default_module_id
			|| this.props.action.params?.module_id;
		onWillStart(async () => {
			this.state.datos = await this.orm.call(
				"repo.module.promotion", "opciones", [this.moduleId]);
			this.destinos = await this.orm.searchRead(
				"repo.repository",
				[["backend_id", "=", this.state.datos.modulo.backend_id || false]],
				["display_name"], { limit: 200 });
			if (!this.destinos.length) {
				this.destinos = await this.orm.searchRead(
					"repo.repository", [], ["display_name"], { limit: 200 });
			}
		});
	}

	get opciones() {
		return this.state.datos ? this.state.datos.opciones : [];
	}

	elegir(opcion) {
		// Se puede cambiar de opinión: elegir de nuevo reemplaza, y volver a hacer clic en
		// la elegida la deselecciona. Nada queda trabado.
		this.state.elegida = this.state.elegida === opcion.id ? null : opcion.id;
	}

	get puedeContinuar() {
		return Boolean(this.state.elegida && this.state.destino);
	}

	// --- el diff, bajo pedido ------------------------------------------------

	async verDiff(a, b) {
		this.state.comparando = true;
		this.state.parA = a.repositorio;
		this.state.parB = b.repositorio;
		try {
			this.state.diff = await this.orm.call(
				"repo.module.promotion", "diff", [a.id, b.id]);
		} finally {
			this.state.comparando = false;
		}
	}

	cerrarDiff() {
		this.state.diff = null;
	}

	/** Con qué comparar: la elegida contra cada una de las otras. */
	get comparables() {
		if (!this.state.elegida) {
			return [];
		}
		const elegida = this.opciones.find((o) => o.id === this.state.elegida);
		return this.opciones
			.filter((o) => o.id !== elegida.id && o.arbol !== elegida.arbol)
			.map((o) => ({ elegida, otra: o }));
	}

	etiquetaEstado(fila) {
		return {
			solo_en_a: _t("sólo en la elegida"),
			solo_en_b: _t("sólo en la otra"),
			distinto: _t("distinto"),
		}[fila.estado] || fila.estado;
	}

	// --- lo que produce ------------------------------------------------------

	/**
	 * Salir sin promover. No crea nada, no cambia nada, y vuelve al módulo.
	 *
	 * Está acá y con su propio bloque porque «no elegir» es una decisión legítima: si
	 * cada copia tiene algo que vale, la respuesta correcta es unificarlas a mano y
	 * volver. Ofrecer sólo «elegí» empuja a decidir cuando la decisión correcta es no
	 * decidir todavía.
	 */
	abortar() {
		this.action.doAction({
			type: "ir.actions.act_window",
			res_model: "repo.module",
			res_id: this.moduleId,
			views: [[false, "form"]],
		});
	}

	async armarPlan() {
		const resultado = await this.orm.call(
			"repo.module.promotion", "armar_plan",
			[this.moduleId, this.state.elegida, parseInt(this.state.destino, 10),
			 this.state.limpiar]);
		this.action.doAction({
			type: "ir.actions.act_window",
			res_model: "repo.write.plan",
			res_id: resultado.plan_id,
			views: [[false, "form"]],
		});
	}

	alElegirDestino(ev) {
		this.state.destino = ev.target.value || null;
	}
}

registry.category("actions").add("repo_promocion_modulo", PromocionDeModulo);
