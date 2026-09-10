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
	// --- E4.1 · la tendencia, dibujada acá y sin librería ------------------
	//
	// SVG INLINE Y NADA MÁS. Odoo no trae una librería de gráficos en el backend y sumar
	// una para dibujar ocho puntos es peso, superficie y una dependencia que alguien va a
	// tener que actualizar. Ocho puntos y una polilínea se calculan en veinte líneas.
	//
	// LA LÍNEA SE CORTA EN EL HUECO. Una corrida que falló no tiene medición, y unir el
	// punto anterior con el siguiente dibujaría una recta que afirma que esa semana se
	// midió. Se parte la serie en tramos y cada tramo se dibuja aparte; el hueco queda
	// marcado con su propia señal.

	get ancho() { return 260; }
	get alto() { return 48; }

	/** Los puntos de una serie, ya en coordenadas del dibujo. */
	puntos(clave) {
		const serie = ((this.state.datos.detalle.tendencia || {}).series || {})[clave];
		if (!serie || !serie.length) {
			return [];
		}
		const medidos = serie.filter((p) => p.medida).map((p) => p.valor);
		const max = Math.max(...medidos, 0);
		const min = Math.min(...medidos, 0);
		const rango = max - min || 1;
		const paso = serie.length > 1 ? this.ancho / (serie.length - 1) : 0;
		return serie.map((p, i) => ({
			...p,
			x: Math.round(i * paso),
			// El eje crece hacia arriba; el SVG, hacia abajo.
			y: p.medida
				? Math.round(this.alto - ((p.valor - min) / rango) * (this.alto - 8) - 4)
				: null,
		}));
	}

	/**
	 * Los TRAMOS continuos de la serie. Cada corte es una corrida sin medición.
	 *
	 * Devolver una sola polilínea con los huecos salteados es lo que haría cualquier
	 * librería por omisión, y es justamente lo que no se puede hacer acá.
	 */
	tramos(clave) {
		const salida = [];
		let actual = [];
		for (const punto of this.puntos(clave)) {
			if (punto.y === null) {
				if (actual.length > 1) {
					salida.push(actual);
				}
				actual = [];
				continue;
			}
			actual.push(punto);
		}
		if (actual.length > 1) {
			salida.push(actual);
		}
		return salida.map((tramo) =>
			tramo.map((p) => `${p.x},${p.y}`).join(" "));
	}

	/**
	 * Las tres marcas del eje: mínimo, medio y máximo de lo medido.
	 *
	 * El mockup dibuja «0 · 20 · 40» al costado. Son los valores REALES de la serie y no
	 * una escala fija: un gráfico de hallazgos que va de 3 a 9 dibujado sobre un eje de
	 * 0 a 100 se ve como una línea plana, y la tendencia —que es lo único que este
	 * gráfico tiene que contar— desaparece.
	 */
	escala(clave) {
		const medidos = this.puntos(clave).filter((p) => p.y !== null).map((p) => p.valor);
		if (!medidos.length) {
			return [];
		}
		const max = Math.max(...medidos, 0);
		const min = Math.min(...medidos, 0);
		if (max === min) {
			return [max];
		}
		return [max, Math.round((max + min) / 2), min];
	}

	/**
	 * Dónde cae la meta en el dibujo, o `null` si no hay meta o queda fuera de la escala.
	 *
	 * FUERA DE LA ESCALA SE OMITE, no se pega al borde. Una meta del 85 % dibujada al
	 * tope de un gráfico que va de 0 a 40 diría «estamos rozándola», que es lo contrario
	 * de lo que pasa. Cuando no entra, el número de arriba la sigue diciendo en palabras.
	 */
	yDeMeta(numero) {
		if (!numero.meta) {
			return null;
		}
		const serie = this.puntos(numero.clave).filter((p) => p.y !== null);
		if (!serie.length) {
			return null;
		}
		const valores = serie.map((p) => p.valor);
		const max = Math.max(...valores, 0);
		const min = Math.min(...valores, 0);
		if (numero.meta > max || numero.meta < min) {
			return null;
		}
		const rango = max - min || 1;
		return Math.round(
			this.alto - ((numero.meta - min) / rango) * (this.alto - 8) - 4);
	}

	/** Los huecos, para marcarlos: son corridas que existieron y no se pudieron medir. */
	huecos(clave) {
		return this.puntos(clave).filter((p) => p.y === null);
	}

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
