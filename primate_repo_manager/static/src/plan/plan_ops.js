/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Las operaciones de un plan, agrupadas por repositorio — página 2b del entregable.
 *
 * LA CONFIRMACIÓN VIVE EN LA FILA, Y ESO ES EL DISEÑO ENTERO. Antes vivía en un asistente
 * aparte: una lista de tildes que tapaba justamente lo que la lista describe. Acá cada
 * operación tiene, en la misma línea de lectura, la frase en castellano, el detalle
 * técnico en mono, si tiene vuelta atrás, y el control para confirmarla. Se lee junto a la
 * consecuencia.
 *
 * DOS NIVELES, SIEMPRE. Reversible: un tilde. Irreversible: escribir el nombre exacto de
 * lo que se destruye. Y las reversibles se pueden confirmar todas de una vez; las
 * irreversibles, nunca — es la línea que separa las dos y no es negociable por comodidad.
 *
 * LO QUE ESTA PANTALLA NO DECIDE. La guarda sigue en `repo.write.plan._aprobar`, que se
 * niega si falta una destructiva por confirmar venga de donde venga la llamada. Esta
 * pantalla ofrece el camino y muestra el estado; el modelo es el que dice sí o no. Una
 * pantalla es una pantalla, y una pantalla se saltea llamando al método.
 */

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Apagado } from "../apagado/apagado";

export class PlanOps extends Component {
	static template = "primate_repo_manager.PlanOps";
	static components = { Apagado };
	static props = { ...standardFieldProps };

	setup() {
		this.orm = useService("orm");
		this.action = useService("action");
		this.dialog = useService("dialog");
		this.notification = useService("notification");
		// Lo que se está escribiendo en cada irreversible, por id. No se guarda en el
		// servidor mientras se escribe: lo escrito a medias no es una confirmación.
		this.state = useState({ tipeo: {}, plegado: {} });
	}

	get operaciones() {
		const lista = this.props.record.data[this.props.name];
		return [...(lista.records || [])].sort(
			(a, b) => (a.data.sequence - b.data.sequence) || (a.resId - b.resId));
	}

	/** Agrupadas por repositorio, como el diseño: el encabezado cuenta lo que hay. */
	get grupos() {
		const grupos = new Map();
		for (const op of this.operaciones) {
			const repo = this.repo(op);
			if (!grupos.has(repo)) {
				grupos.set(repo, { repo, ops: [] });
			}
			grupos.get(repo).ops.push(op);
		}
		return [...grupos.values()].map((g) => {
			const irreversibles = g.ops.filter((o) => o.data.is_irreversible).length;
			const sinConfirmar = g.ops.filter((o) => !o.data.approval_ok).length;
			return {
				...g,
				irreversibles,
				sinConfirmar,
				// Se pliega solo cuando no hay nada que decidir ahí: es lo que hace el
				// diseño con los repositorios «todas reversibles, todas aprobadas».
				resumido: !sinConfirmar && !irreversibles,
			};
		});
	}

	repo(op) {
		const valor = op.data.repository_id;
		if (!valor) {
			return _t("(sin repositorio)");
		}
		// En Odoo 19 un many2one llega como objeto; antes, como par. Las dos.
		return Array.isArray(valor) ? valor[1] : valor.display_name || "";
	}

	// --- los contadores del pie --------------------------------------------
	//
	// DOS BARRAS SEPARADAS, no una suma. Sumarlas diría «10 de 12 confirmadas» y esconde
	// justamente el dato que importa: si lo que falta tiene vuelta atrás o no.

	get reversibles() {
		const ops = this.operaciones.filter((o) => !o.data.is_irreversible);
		return { total: ops.length, hechas: ops.filter((o) => o.data.approval_ok).length };
	}

	get irreversibles() {
		const ops = this.operaciones.filter((o) => o.data.is_irreversible);
		return { total: ops.length, hechas: ops.filter((o) => o.data.approval_ok).length };
	}

	get sinSoporte() {
		return this.operaciones.filter((o) => !o.data.is_supported);
	}

	get falta() {
		return this.operaciones.filter(
			(o) => o.data.is_destructive && !o.data.approval_ok);
	}

	get enBorrador() {
		return this.props.record.data.state === "draft";
	}

	get aplicandose() {
		return this.props.record.data.state === "applying";
	}

	/**
	 * LOS REPOSITORIOS QUE VAN A DEJAR DE TENER EL MÓDULO.
	 *
	 * Sale de las operaciones de retiro que el plan ya tiene: no es una lista aparte que
	 * alguien tenga que mantener sincronizada, es la misma información leída para otra
	 * pregunta. Si mañana se agrega o se saca un retiro, esto lo sigue solo.
	 */
	get retiros() {
		return this.operaciones
			.filter((o) => o.data.kind === "module_delete")
			.map((o) => ({
				repositorio: this.repo(o),
				modulo: o.data.target || "",
			}));
	}

	// --- qué va a pasar si aprobás -----------------------------------------

	get resumen() {
		const total = this.operaciones.length;
		const irreversibles = this.irreversibles.total;
		const repos = new Set(this.operaciones.map((o) => this.repo(o))).size;
		return { total, irreversibles, reversibles: total - irreversibles, repos };
	}

	// --- acciones ----------------------------------------------------------

	async recargar() {
		await this.props.record.load();
	}

	async confirmar(op) {
		try {
			await this.orm.call("repo.write.operation", "action_confirmar", [[op.resId]]);
		} catch (error) {
			// El error del servidor es el mensaje bueno: dice qué falta y por qué. No se
			// lo reemplaza por uno propio más corto.
			throw error;
		}
		await this.recargar();
	}

	async conciliar(op) {
		// Relee GitHub y cierra la cuenta abierta. La decisión sale de lo que se lea, no
		// de lo que la pantalla suponga: por eso no hay dos botones «contar como
		// aplicada» y «descartar» — no es una preferencia, es un hecho que se comprueba.
		await this.orm.call("repo.write.operation", "action_conciliar", [[op.resId]]);
		await this.recargar();
	}

	async desconfirmar(op) {
		await this.orm.call("repo.write.operation", "action_desconfirmar", [[op.resId]]);
		await this.recargar();
	}

	async confirmarIrreversible(op) {
		const escrito = this.state.tipeo[op.resId] || "";
		await this.orm.call(
			"repo.write.operation", "action_confirmar", [[op.resId]], { nombre: escrito });
		this.state.tipeo[op.resId] = "";
		await this.recargar();
	}

	async confirmarTodasLasReversibles() {
		const ids = this.operaciones
			.filter((o) => !o.data.is_irreversible && o.data.is_supported
						   && !o.data.approval_ok)
			.map((o) => o.resId);
		if (!ids.length) {
			return;
		}
		await this.orm.call(
			"repo.write.operation", "action_confirmar_reversibles", [ids]);
		await this.recargar();
	}

	/**
	 * El número de la fila, «01», «02»: la POSICIÓN en el plan, no el `sequence`.
	 *
	 * El `sequence` va de diez en diez —10, 20, 30— para poder intercalar sin renumerar
	 * todo, y eso es correcto adentro. Afuera no: el diseño numera las operaciones de un
	 * plan de 1 a N, y «la 04» es la cuarta, no la que tiene sequence 40. Alguien que dice
	 * «sacá la 04» está contando en la pantalla.
	 *
	 * Y vive acá y no en la plantilla porque QWeb NO tiene los globales de JavaScript en
	 * su contexto: `String(...)` allá adentro es `ctx.String`, que no existe, y la
	 * pantalla entera muere en el render. Compila sin quejarse y revienta al abrirla.
	 */
	numero(op) {
		const posicion = this.operaciones.findIndex((o) => o.resId === op.resId) + 1;
		return String(posicion).padStart(2, "0");
	}

	nombreEsperado(op) {
		return op.data.target || "";
	}

	alTipear(op, ev) {
		this.state.tipeo[op.resId] = ev.target.value;
	}

	tipeoCorrecto(op) {
		return (this.state.tipeo[op.resId] || "").trim() === this.nombreEsperado(op);
	}

	alternar(repo) {
		this.state.plegado[repo] = !this.state.plegado[repo];
	}

	plegado(grupo) {
		const forzado = this.state.plegado[grupo.repo];
		return forzado === undefined ? grupo.resumido : forzado;
	}

	/** El payload, en una línea de mono. Es el detalle técnico del diseño. */
	tecnico(op) {
		const crudo = op.data.payload_json;
		if (!crudo) {
			return "";
		}
		try {
			const datos = JSON.parse(crudo);
			return Object.entries(datos)
				.map(([k, v]) => `${k}=${typeof v === "object" && v !== null
					? JSON.stringify(v) : v}`)
				.join(" · ");
		} catch {
			return crudo;
		}
	}

	async verHallazgos() {
		this.action.doAction({
			type: "ir.actions.act_window",
			name: _t("Hallazgos que originaron el plan"),
			res_model: "repo.audit.finding",
			views: [[false, "list"], [false, "form"]],
			domain: [["planned_operation_id", "in",
					  this.operaciones.map((o) => o.resId)]],
		});
	}
}

export const planOpsField = {
	component: PlanOps,
	supportedTypes: ["one2many"],
	relatedFields: () => [
		{ name: "sequence", type: "integer" },
		{ name: "description", type: "char" },
		{ name: "kind", type: "selection" },
		{ name: "target", type: "char" },
		{ name: "payload_json", type: "text" },
		{ name: "repository_id", type: "many2one", relation: "repo.repository" },
		{ name: "is_destructive", type: "boolean" },
		{ name: "is_irreversible", type: "boolean" },
		{ name: "is_supported", type: "boolean" },
		{ name: "approved", type: "boolean" },
		{ name: "approval_ok", type: "boolean" },
		{ name: "approved_by_id", type: "many2one", relation: "res.users" },
		{ name: "state", type: "selection" },
		{ name: "error", type: "text" },
		{ name: "dependency_blocked_by", type: "char" },
	],
};

registry.category("fields").add("repo_plan_ops", planOpsField);
