/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * La bitácora como LÍNEA DE TIEMPO — página 2d del entregable de diseño.
 *
 * POR QUÉ UN RENDERER Y NO UNA PANTALLA APARTE. La búsqueda, los filtros y el agrupado de
 * Odoo son buenos y la gente ya sabe usarlos: lo que el diseño cambia es cómo se lee cada
 * entrada, no cómo se la busca. Así que se reemplaza el cuerpo de la lista y se deja
 * intacto todo el panel de control. Una pantalla propia habría obligado a reimplementar
 * los filtros, y los reimplementados siempre son peores.
 *
 * LO QUE SE VE, Y POR QUÉ ESTÁ ASÍ. Cada entrada es una tarjeta con la hora en mono a la
 * izquierda, un riel con su marca —redonda si se puede revertir, cuadrada si no—, y el
 * antes/después en dos columnas: gris a la izquierda, del color del resultado a la
 * derecha. La frase de arriba cuenta lo mismo en castellano, para quien no lee el mono.
 *
 * SÓLO LECTURA, SIEMPRE. No hay editar ni borrar, ni para administradores, y eso no es una
 * omisión de esta pantalla: el modelo levanta excepción en `write` y `unlink`.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Apagado } from "../apagado/apagado";

// Los días en castellano. `toLocaleDateString` depende del idioma del navegador, y el
// encabezado tiene que decir lo mismo en la máquina de cualquiera.
const DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
			   "septiembre", "octubre", "noviembre", "diciembre"];

export class BitacoraRenderer extends Component {
	static template = "primate_repo_manager.Bitacora";
	static components = { Apagado };
	static props = ["list", "archInfo", "openRecord", "*"];

	setup() {
		this.orm = useService("orm");
		this.action = useService("action");
		this.state = useState({ leyenda: [], cadena: null, abierta: null });

		onWillStart(async () => {
			// Las dos cosas que la pantalla dice sobre sí misma: qué significa cada marca
			// y si la cadena está entera. Las dos salen del servidor, no de una copia.
			const [leyenda, cadena] = await Promise.all([
				this.orm.call("repo.audit.log", "leyenda", []),
				this.orm.call("repo.audit.log", "estado_de_la_cadena", []),
			]);
			this.state.leyenda = leyenda;
			this.state.cadena = cadena;
		});
	}

	// --- agrupar por día ----------------------------------------------------

	get dias() {
		const porDia = new Map();
		for (const record of this.props.list.records) {
			const fecha = record.data.timestamp;
			const clave = fecha ? fecha.toFormat("yyyy-LL-dd") : "—";
			if (!porDia.has(clave)) {
				porDia.set(clave, { clave, titulo: this.tituloDelDia(fecha), entradas: [] });
			}
			porDia.get(clave).entradas.push(record);
		}
		return [...porDia.values()];
	}

	tituloDelDia(fecha) {
		if (!fecha) {
			return _t("Sin fecha");
		}
		const js = fecha.toJSDate();
		const hoy = new Date();
		const mismoDia = (a, b) => a.toDateString() === b.toDateString();
		const ayer = new Date(hoy.getTime() - 86400000);
		const largo = `${DIAS[js.getDay()]} ${js.getDate()} de ${MESES[js.getMonth()]}`;
		if (mismoDia(js, hoy)) {
			return `${_t("Hoy")} · ${largo}`;
		}
		if (mismoDia(js, ayer)) {
			return `${_t("Ayer")} · ${largo}`;
		}
		return largo.charAt(0).toUpperCase() + largo.slice(1);
	}

	// --- cada entrada -------------------------------------------------------

	hora(record) {
		const fecha = record.data.timestamp;
		return fecha ? fecha.toFormat("HH:mm:ss") : "—";
	}

	esIrreversible(record) {
		return record.data.entry_class === "irreversible";
	}

	/** La forma de la marca en el riel. Es lo que la leyenda explica. */
	formaDeLaMarca(record) {
		return {
			escritura: "punto", irreversible: "cuadrado",
			lectura: "hueco", externo: "rombo",
		}[record.data.entry_class] || "punto";
	}

	/**
	 * Quién lo hizo. En Odoo 19 un many2one llega como `{id, display_name}`; en versiones
	 * anteriores llegaba como `[id, nombre]`. Se contemplan las dos porque equivocarse acá
	 * no rompe nada visible —el nombre simplemente no aparece— y eso pasa desapercibido:
	 * pasó en esta misma pantalla, y sólo se vio abriéndola.
	 */
	quien(record) {
		const valor = record.data.user_id;
		if (!valor) {
			return "";
		}
		return Array.isArray(valor) ? valor[1] : valor.display_name || "";
	}

	/**
	 * El estado, como pares `clave: valor` en mono — que es como lo muestra el diseño, y
	 * no como un volcado de JSON con llaves y comillas. Los valores compuestos se
	 * serializan compactos: la idea es leer QUÉ cambió, no auditar el JSON.
	 *
	 * Si no hay nada, devuelve null y la plantilla LO DICE. Un bloque vacío en la columna
	 * del «antes» se leería como «no había nada antes», que es otra afirmación y a veces
	 * falsa: la misma regla del rayado de «no se pudo leer».
	 */
	pares(texto) {
		if (!texto) {
			return null;
		}
		let datos;
		try {
			datos = JSON.parse(texto);
		} catch {
			return [{ clave: "", valor: texto }];
		}
		if (datos === null || typeof datos !== "object" || Array.isArray(datos)) {
			return [{ clave: "", valor: JSON.stringify(datos) }];
		}
		return Object.entries(datos).map(([clave, valor]) => ({
			clave,
			valor: typeof valor === "object" && valor !== null
				? JSON.stringify(valor)
				: String(valor),
		}));
	}

	antes(record) {
		return this.pares(record.data.previous_state_json);
	}

	despues(record) {
		return this.pares(record.data.payload_json);
	}

	alternar(record) {
		this.state.abierta = this.state.abierta === record.resId ? null : record.resId;
	}

	abierta(record) {
		return this.state.abierta === record.resId;
	}

	// --- la única acción de la pantalla -------------------------------------

	async revertir(record) {
		// Pasa por el mismo embudo que todo lo demás: la acción del modelo vuelve a
		// comprobar la admisibilidad sobre los hechos y puede negarse. Esta pantalla no
		// decide nada, sólo ofrece el camino.
		await this.orm.call(
			"repo.write.operation", "action_rollback_operation",
			[[record.data.operation_id[0]]]);
		await this.props.list.load();
	}
}

export const bitacoraListView = { ...listView, Renderer: BitacoraRenderer };

registry.category("views").add("repo_bitacora", bitacoraListView);
