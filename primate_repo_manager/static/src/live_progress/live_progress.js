/** @odoo-module **/
/* Copyright 2026 - PrimateUY / License AGPL-3.0 or later */

/**
 * Avance en vivo de una corrida de auditoría.
 *
 * POR QUÉ ESTE COMPONENTE EXISTE. Una vista estándar muestra el valor que tenía el
 * registro cuando se cargó la página. Para ver avanzar una auditoría había que refrescar
 * a mano, y eso no es usable: el usuario no puede saber si el trabajo avanza o murió.
 *
 * EL REGISTRO ES LA BASE, EL BUS ES LA CAPA DE ENCIMA. Lo que se pinta sale SIEMPRE de
 * `props.record.data`, y los avisos del bus se superponen cuando los hay. La primera
 * versión hacía lo contrario —copiaba el registro a un estado interno en `setup()`— y eso
 * estaba mal por una razón que no se ve leyendo el código: `setup()` corre UNA vez, al
 * montar el componente, y no vuelve a correr cuando el registro cambia. Al apretar
 * «Auditar» el formulario recarga el registro pero el componente seguía mostrando la
 * copia vieja: la pantalla decía «todavía no se ejecutó» con la corrida corriendo.
 *
 * Y LA SUSCRIPCIÓN SE REHACE CUANDO CAMBIA EL REGISTRO. Mismo error, peor consecuencia:
 * un formulario abierto en «Nuevo» todavía no tiene id, así que en `setup()` no había a
 * qué canal suscribirse. Al guardar aparecía el id, pero nadie volvía a mirar. El
 * componente quedaba mudo para siempre — que es exactamente lo que pasó en el primer
 * recorrido real. Ahora la suscripción se revisa en cada cambio de props.
 *
 * NO RECARGA EL REGISTRO MIENTRAS CORRE. Recargar en cada repositorio haría parpadear el
 * formulario entero para mover un número. La única recarga es al terminar, una sola vez.
 *
 * DEGRADA DICIENDO LA VERDAD. Si no llegan avisos, no finge una barra que avanza ni se
 * queda muda: dice que hace rato que no recibe novedades y por qué puede pasar.
 */

import { Component, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

// Cuántos segundos sin novedades antes de avisar que algo puede estar mal.
//
// Estaba en 20 y era demasiado poco: en la primera corrida mirada en un navegador,
// `webOCA` —que es un fork con muchas ramas— tardó 37 segundos, y el aviso de «sin
// novedades» saltó en medio de un recorrido perfectamente sano. Un aviso que salta cuando
// no pasa nada malo enseña a ignorarlo, que es la peor cosa que le puede pasar a un aviso.
// 60 segundos deja pasar al repositorio más lento que se midió con holgura y sigue
// atrapando una corrida realmente detenida en el minuto.
const SILENCIO_SOSPECHOSO = 60;
const AVISO = "repo_manager.audit_progress";

// EL COMPONENTE NO SABE DE AUDITORÍAS. Sabe de «algo que avanza»: un total, cuántos van,
// cuántos fallaron y qué se está haciendo ahora. Los nombres de los campos donde vive eso
// llegan por opciones del widget, con los de la corrida de auditoría como default para que
// la vista que ya existía siga funcionando sin tocarla.
//
// Es lo que permite que el plan aplicándose reuse esta misma pieza en vez de tener una
// copia parecida: dos barras que se parecen divergen, y la que se mira menos envejece mal.
const CAMPOS_POR_DEFECTO = {
	total: "repos_total",
	done: "repos_done",
	error: "repos_error",
	findings: "finding_count",
	criticos: "critical_count",
	altos: "high_count",
	inicio: "started_at",
	fin: "finished_at",
	cuenta: "backend_id",
	modelo: "repo.audit.run",
	corriendo: "running",
	terminado: "done,partial",
};

export class LiveProgress extends Component {
    static template = "primate_repo_manager.LiveProgress";
    static props = { ...standardFieldProps, options: { type: Object, optional: true } };

    setup() {
        this.bus = useService("bus_service");
        this.action = useService("action");
        this.orm = useService("orm");

        // `vivo` es lo último que dijo el bus, o null si todavía no dijo nada. Nunca se
        // inicializa con el registro: para eso está el registro.
        this.state = useState({
            vivo: null,
            recibioAlgo: false,
            silencio: 0,
            ahora: Date.now(),
        });

        this.campos = { ...CAMPOS_POR_DEFECTO, ...(this.props.options || {}) };
        this.estadosTerminado = this.campos.terminado.split(",");
        this.corridaId = null;
        this.canal = null;
        this.yaRecargo = false;
        this._alRecibir = (payload) => this._recibir(payload);
        this.bus.subscribe(AVISO, this._alRecibir);

        // POR QUÉ `useEffect` Y NO `onWillUpdateProps`. El registro que llega por props es
        // SIEMPRE el mismo objeto: al guardar una corrida nueva, Odoo le pone el id
        // encima en vez de entregar otro. `onWillUpdateProps` puede no dispararse nunca
        // —los props no cambiaron, cambió lo de adentro— y entonces la suscripción se
        // queda esperando un id que ya llegó. Es el mismo error que dejó la pantalla muda
        // la primera vez, corrido un paso más adelante: ahí era `setup()`, acá sería el
        // hook equivocado. `useEffect` mira el VALOR del id después de cada render, que
        // es lo único que importa.
        useEffect(
            () => this._sincronizarCanal(),
            () => [this.props.record.resId],
        );

        // Un solo reloj para el cronómetro y para detectar el silencio.
        this.reloj = setInterval(() => {
            this.state.ahora = Date.now();
            if (this.corriendo) {
                this.state.silencio += 1;
            }
        }, 1000);

        onWillUnmount(() => {
            clearInterval(this.reloj);
            this.bus.unsubscribe(AVISO, this._alRecibir);
            this._dejarCanal();
        });
    }

    // --- suscripción -------------------------------------------------------

    _dejarCanal() {
        if (this.canal) {
            this.bus.deleteChannel(this.canal);
            this.canal = null;
        }
    }

    _sincronizarCanal() {
        const id = this.props.record.resId;
        if (id === this.corridaId) {
            return;
        }
        this._dejarCanal();
        this.corridaId = id;
        // Cambiar de corrida invalida todo lo que el bus había dicho de la anterior.
        this.state.vivo = null;
        this.state.recibioAlgo = false;
        this.state.silencio = 0;
        this.yaRecargo = false;
        if (id) {
            this.canal = `${this.campos.modelo}_${id}`;
            this.bus.addChannel(this.canal);
        }
    }

    _recibir(payload) {
        // Llegan avisos de todas las corridas suscritas; sólo interesa la de esta pantalla.
        if (!payload || payload.id !== this.corridaId) {
            return;
        }
        this.state.recibioAlgo = true;
        this.state.silencio = 0;
        this.state.vivo = payload;

        if (["done", "partial", "error"].includes(payload.state) && !this.yaRecargo) {
            // Una sola recarga, al final: el resto del formulario —fechas, chatter— tiene
            // que quedar al día, y esto ya no interrumpe nada porque terminó.
            this.yaRecargo = true;
            this.props.record.load();
        }
    }

    // --- lo que se pinta ---------------------------------------------------

    get datos() {
        const d = this.props.record.data;
        const c = this.campos;
        const base = {
            state: d.state,
            total: d[c.total] || 0,
            done: d[c.done] || 0,
            error: d[c.error] || 0,
            actual: null,
            findings: d[c.findings] || 0,
            criticos: d[c.criticos] || 0,
            altos: d[c.altos] || 0,
        };
        return this.state.vivo ? Object.assign(base, this.state.vivo) : base;
    }

    get nombreCuenta() {
        // En Odoo 19 un many2one llega como {id, display_name}; antes llegaba como
        // [id, nombre]. Se contemplan las dos: una regresión acá no rompe nada visible
        // —sólo deja de aparecer el nombre— y eso pasa desapercibido.
        const valor = this.props.record.data[this.campos.cuenta];
        if (!valor) {
            return "";
        }
        return Array.isArray(valor) ? valor[1] : valor.display_name || "";
    }

    get corriendo() {
        return this.datos.state === this.campos.corriendo;
    }

    get termino() {
        return this.estadosTerminado.includes(this.datos.state);
    }

    get porcentaje() {
        const { total, done, error } = this.datos;
        return total ? Math.round(((done + error) / total) * 100) : 0;
    }

    get hayErrores() {
        return this.datos.error > 0;
    }

    get sinNovedades() {
        return this.corriendo && this.state.silencio >= SILENCIO_SOSPECHOSO;
    }

    get tiempo() {
        // Se mide desde que arrancó la corrida, NO desde que se abrió la pantalla: quien
        // entra a mirar una auditoría a mitad de camino tiene que ver cuánto lleva, no
        // cuánto hace que está mirando.
        const d = this.props.record.data;
        const inicio = d[this.campos.inicio];
        if (!inicio) {
            return "";
        }
        const fin = d[this.campos.fin];
        const hasta = fin ? fin.toMillis() : this.state.ahora;
        const s = Math.max(0, Math.round((hasta - inicio.toMillis()) / 1000));
        return s < 60 ? _t("%s s", s) : _t("%s min %s s", Math.floor(s / 60), s % 60);
    }

    async volverAPreguntar() {
        // El servidor reemite su estado por el mismo canal de siempre. No se recarga la
        // pantalla: si la respuesta llega, entra por donde entran todas las demás.
        if (this.corridaId) {
            await this.orm.call(this.campos.modelo, "action_refresh_progress",
                                [[this.corridaId]]);
        }
    }

    verHallazgos() {
        // Acción armada acá y no declarada en XML: la pantalla propia de hallazgos es A2.
        // Con la lista que ya existe se pueden ver y filtrar; cuando A2 exista, esta misma
        // acción va a abrir las vistas buenas sin tocar el componente.
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Hallazgos de la auditoría"),
            res_model: "repo.audit.finding",
            views: [[false, "list"], [false, "form"]],
            domain: [["run_id", "=", this.corridaId]],
        });
    }
}

export const liveProgressField = {
    component: LiveProgress,
    supportedTypes: ["float", "integer"],
    // Los nombres de los campos llegan por `options` en la vista; ver CAMPOS_POR_DEFECTO.
    extractProps: ({ options }) => ({ options }),
};

registry.category("fields").add("repo_live_progress", liveProgressField);
