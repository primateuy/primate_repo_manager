/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Hallazgos con la bandeja del plan — página 2c, y el gesto según la 6d.
 *
 * QUÉ REEMPLAZA EL ARRASTRE, que es la única razón por la que existe. Hoy, sumar tres
 * hallazgos a un plan es: tildar cada uno, abrir el menú de acciones, elegir «remediar».
 * El gesto dice «estos van juntos» en un movimiento. La especificación es explícita en que
 * un arrastre que no reemplaza una secuencia concreta de clics no va.
 *
 * Y POR ESO MISMO, TODO LO ARRASTRABLE TIENE CAMINO POR CLIC. El enlace «Agregar al plan»
 * de cada fila hace exactamente lo mismo. El arrastre es un atajo, nunca la única puerta:
 * quien no puede arrastrar —teclado, lector de pantalla, un trackpad que no coopera— tiene
 * que poder armar el plan igual.
 *
 * NINGÚN ARRASTRE ESCRIBE EN GITHUB. Soltar un hallazgo en la bandeja crea una operación
 * en un plan EN BORRADOR y nada más. Escribir sigue pasando por aprobación explícita, con
 * su confirmación por fila. Un gesto de la mano no puede desencadenar una escritura, y
 * menos una destructiva.
 *
 * NADA SE GUARDA A MITAD DE GESTO. El estado se escribe al soltar; si se suelta afuera,
 * todo vuelve a su lugar y no se dice nada, porque no pasó nada.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Apagado } from "../apagado/apagado";

const SEVERIDADES = [
	{ clave: "critical", etiqueta: "Crítico" },
	{ clave: "high", etiqueta: "Alto" },
	{ clave: "medium", etiqueta: "Medio" },
	{ clave: "info", etiqueta: "Informativo" },
];

export class HallazgosRenderer extends Component {
	static template = "primate_repo_manager.Hallazgos";
	static components = { Apagado };
	static props = ["list", "archInfo", "openRecord", "*"];

	setup() {
		this.orm = useService("orm");
		this.action = useService("action");
		this.notification = useService("notification");
		this.state = useState({
			expandido: null,
			arrastrando: null,     // id del hallazgo en la mano
			levantado: null,       // id levantado por TECLADO
			sobreBandeja: false,
			invalido: null,        // id que no se puede soltar
			plan: null,            // el borrador de esta conexión
			enPlan: [],            // operaciones del borrador
			anuncio: "",           // para el lector de pantalla
			historia: {},          // id de hallazgo -> sus corridas, ya cargadas
		});
		onWillStart(() => this.cargarBandeja());
	}

	// --- la bandeja ---------------------------------------------------------

	async cargarBandeja() {
		const backend = this.backendId;
		if (!backend) {
			this.state.plan = null;
			this.state.enPlan = [];
			return;
		}
		const datos = await this.orm.call(
			"repo.write.plan", "bandeja_del_borrador", [backend]);
		this.state.plan = datos.plan;
		this.state.enPlan = datos.operaciones;
	}

	/** La conexión de los hallazgos que se están viendo. */
	get backendId() {
		for (const record of this.registros) {
			const run = record.data.run_id;
			if (run) {
				const backend = record.data.backend_id;
				if (backend) {
					return Array.isArray(backend) ? backend[0] : backend.id;
				}
			}
		}
		return null;
	}

	/**
	 * TODOS los registros, venga la lista agrupada o plana.
	 *
	 * La acción abre con «agrupar por severidad» puesto de fábrica, y en una lista
	 * agrupada `list.records` viene VACÍO: los registros cuelgan de cada grupo. La
	 * pantalla decía «no hay hallazgos que coincidan» con cuatro en el paginador — el
	 * peor tipo de error, porque afirma algo falso con toda calma.
	 *
	 * Esta pantalla agrupa por severidad ella misma, que es la estructura que el diseño
	 * le da; el agrupado del panel de control se aplana y no se pierde nada visible.
	 */
	get registros() {
		const lista = this.props.list;
		if (lista.isGrouped) {
			return lista.groups.flatMap((g) => g.list.records || []);
		}
		return lista.records;
	}

	get grupos() {
		return SEVERIDADES.map((sev) => {
			const items = this.registros.filter(
				(r) => r.data.severity === sev.clave);
			return {
				...sev,
				items,
				enPlan: items.filter((r) => r.data.planned_operation_id).length,
				// El renglón de contexto del encabezado. Los informativos dicen otra cosa
				// porque su diferencia es real: no proponen nada, así que no se arrastran.
				contexto: sev.clave === "info"
					? _t("· sin acción propuesta: no se pueden arrastrar")
					: _t("· clic en la fila para leerlo en castellano"),
			};
		}).filter((g) => g.items.length);
	}

	// --- cada fila ----------------------------------------------------------

	/** La etiqueta del chip. `severity_rank` es el valor de ORDEN —«1_critical»— y sirve
	 *  para ordenar, no para mostrarse: en pantalla salía «1_CRITICAL». */
	etiquetaSeveridad(record) {
		const sev = SEVERIDADES.find((s) => s.clave === record.data.severity);
		return sev ? sev.etiqueta : record.data.severity || "";
	}

	arrastrable(record) {
		// PREVENCIÓN ANTES QUE EXPLICACIÓN: lo que no se puede arrastrar no tiene mango.
		// La explicación es la segunda línea de defensa, para quien igual lo intenta.
		return record.data.can_be_planned && !record.data.planned_operation_id;
	}

	repo(record) {
		const valor = record.data.repository_id;
		if (!valor) {
			return "";
		}
		return Array.isArray(valor) ? valor[1] : valor.display_name || "";
	}

	alternar(record) {
		this.state.expandido =
			this.state.expandido === record.resId ? null : record.resId;
		if (this.state.expandido) {
			this.cargarHistoria(record.resId);
		}
	}

	/**
	 * E2.2b · «en qué auditoría apareció y en cuál no estaba».
	 *
	 * Se pide al desplegar y no al cargar la lista: son doscientos hallazgos y la
	 * historia de cada uno recorre las últimas ocho corridas. Se guarda por id para no
	 * volver a preguntar cada vez que alguien pliega y despliega la misma fila.
	 */
	async cargarHistoria(id) {
		if (this.state.historia[id]) {
			return;
		}
		this.state.historia[id] = await this.orm.call(
			"repo.audit.finding", "historia_del_hallazgo", [[id]]);
	}

	abierto(record) {
		return this.state.expandido === record.resId;
	}

	/**
	 * Abrir la ficha del hallazgo. NO es un adorno: es lo que evita un callejón.
	 *
	 * En la lista vieja, el clic en la fila abría el registro. Acá el clic despliega —que
	 * es lo que pide el diseño, «clic en la fila para leerlo en castellano»— y con eso
	 * desapareció la única forma de llegar a la ficha, y con ella el camino
	 * hallazgo → repositorio. Lo encontró el tour que se llama, justamente, «el camino de
	 * lectura no tiene callejones».
	 */
	abrirFicha(record) {
		this.props.openRecord(record);
	}

	// --- el gesto -----------------------------------------------------------

	alEmpezar(record, ev) {
		if (!this.arrastrable(record)) {
			return;
		}
		ev.dataTransfer.setData("text/plain", String(record.resId));
		ev.dataTransfer.effectAllowed = "copy";
		this.state.arrastrando = record.resId;
	}

	alTerminar() {
		// Se soltó afuera: todo vuelve a su lugar y no se dice nada, porque no pasó nada.
		this.state.arrastrando = null;
		this.state.sobreBandeja = false;
		this.state.invalido = null;
	}

	alSobrevolar(ev) {
		ev.preventDefault();
		const id = this.state.arrastrando;
		const record = this.buscar(id);
		const invalido = record && !this.arrastrable(record);
		this.state.sobreBandeja = !invalido;
		this.state.invalido = invalido ? id : null;
	}

	alSalir() {
		this.state.sobreBandeja = false;
		this.state.invalido = null;
	}

	async alSoltar(ev) {
		ev.preventDefault();
		const id = parseInt(ev.dataTransfer.getData("text/plain"), 10);
		this.state.sobreBandeja = false;
		this.state.invalido = null;
		this.state.arrastrando = null;
		const record = this.buscar(id);
		if (!record || !this.arrastrable(record)) {
			return;
		}
		await this.agregar([id]);
	}

	buscar(id) {
		return this.registros.find((r) => r.resId === id);
	}

	// --- el mismo camino, por teclado ---------------------------------------
	//
	// El mango es enfocable, espacio levanta, espacio suelta, Escape cancela. Las flechas
	// no mueven acá y hay que decirlo: en esta pantalla el destino es uno solo —la
	// bandeja—, así que no hay entre qué elegir. Las flechas son del uso de reordenar
	// reglas, que es otro.
	alTeclado(record, ev) {
		if (ev.key === "Escape") {
			this.state.levantado = null;
			this.state.anuncio = _t("Cancelado.");
			return;
		}
		if (ev.key !== " " && ev.key !== "Enter") {
			return;
		}
		ev.preventDefault();
		if (!this.arrastrable(record)) {
			this.state.anuncio = record.data.why_not_planned
				|| _t("Este hallazgo no propone ninguna acción.");
			return;
		}
		if (this.state.levantado === record.resId) {
			this.agregar([record.resId]);
			this.state.levantado = null;
		} else {
			this.state.levantado = record.resId;
			// OJO CON LAS CADENAS PARTIDAS. En Python dos literales pegados son una sola
			// cadena; en JavaScript son un ERROR DE SINTAXIS, y uno que no se ve: rompe
			// el bundle ENTERO —no sólo este módulo— y la pantalla queda en blanco sin un
			// error de consola, porque el fallo es al parsear. Es el mismo tropiezo que
			// el `context` partido en dos líneas que dejó diez pantallas rotas. Se
			// concatena con `+`, siempre.
			this.state.anuncio = _t(
				"«%s» levantado. Espacio otra vez para agregarlo al plan en borrador, " +
				"Escape para cancelar.", record.data.summary);
		}
	}

	// --- lo que el gesto hace, que es lo mismo que hace el enlace ------------

	async agregar(ids) {
		const resultado = await this.orm.call(
			"repo.audit.finding", "agregar_al_borrador", [ids]);
		await this.cargarBandeja();
		await this.props.list.load();
		this.state.anuncio = resultado.mensaje;
		if (resultado.rechazados && resultado.rechazados.length) {
			// La causa concreta, nunca «acción no permitida».
			this.notification.add(resultado.rechazados.join("\n"),
								  { type: "warning", title: _t("No entraron al plan") });
		}
	}

	async quitar(operacionId) {
		await this.orm.call("repo.write.operation", "unlink", [[operacionId]]);
		await this.cargarBandeja();
		await this.props.list.load();
	}

	abrirPlan() {
		if (!this.state.plan) {
			return;
		}
		this.action.doAction({
			type: "ir.actions.act_window",
			res_model: "repo.write.plan",
			res_id: this.state.plan.id,
			views: [[false, "form"]],
		});
	}

	// --- el pie de la bandeja -----------------------------------------------

	get resumenBandeja() {
		const total = this.state.enPlan.length;
		if (!total) {
			return _t(
				"Nada se ejecuta desde acá: el plan se lee y se aprueba en su propia " +
				"pantalla.");
		}
		const destructivas = this.state.enPlan.filter((o) => o.destructiva).length;
		return _t(
			"%(total)s operación(es), %(cuales)s. Nada se ejecuta desde acá.",
			{
				total,
				cuales: destructivas
					? _t("%s saca(n) algo", destructivas)
					: _t("todas reversibles"),
			});
	}
}

export const hallazgosListView = { ...listView, Renderer: HallazgosRenderer };

registry.category("views").add("repo_hallazgos", hallazgosListView);
