from collections import deque

from .build_topology import index_snapshot
from . import passive_collapse
from .error_types import (
    VerificationError,
    PHASE_KG,
    SEVERITY_CRITICAL,
    CAT_UNCONNECTED_PIN,
    CAT_SUPPLY_MISSING,
    CAT_SUPPLY_SHORT,
    CAT_GATE_FLOATING,
    CAT_KELVIN_VIOLATION,
    CAT_KELVIN_SHORT,
    CAT_DIFFERENTIAL_SHORT,
    CAT_VREF_GND_SHORT,
    CAT_MOSFET_PIN_UNCONNECTED,
    CAT_DECOUPLING_MISSING,
    CAT_BOOTSTRAP_MISSING,
    CAT_DRIVING_PAIR,
    CAT_OUTPUT_RESISTOR_MISSING,
    CAT_PIN_FLOATING,
)

from . import task_config_loader as tcfg


def run_phase2_checks(snapshot, kg_store, task_id=None):
    errors = []
    errors.extend(_check_constraints(snapshot, kg_store, task_id=task_id))
    errors.extend(_check_acs37010_ip_short(snapshot))
    errors.extend(_check_mgj2d_vin_short(snapshot))
    if task_id and tcfg.has_check(task_id, "tps54302_diode"):
        errors.extend(_check_tps54302_diode_pairs(snapshot))
    if task_id and tcfg.has_check(task_id, "strict_halfbridge"):
        errors.extend(_check_mosfet_pins_connected(snapshot))
        errors.extend(_check_kelvin_source_distinct(snapshot))
        errors.extend(_check_vbus_decoupling_caps(snapshot))
    if task_id and tcfg.has_check(task_id, "ks_source_rlc"):
        errors.extend(_check_kelvin_source_rlc_isolation(snapshot))
    if task_id and tcfg.has_check(task_id, "ucc5390e_vin_minus"):
        errors.extend(_check_ucc5390e_vin_minus(snapshot))
    if task_id and tcfg.has_check(task_id, "ucc27511_output"):
        errors.extend(_check_ucc27511_outputs(snapshot))
    return errors


def _check_constraints(snapshot, kg_store, task_id=None):
    errors = []
    index = index_snapshot(snapshot)
    nets = index["nets"]
    allow_gate_float = task_id is not None and tcfg.has_check(task_id, "gate_float_allowed")

    for comp in snapshot.get("components", []):
        part_id = comp.get("part_id", "")
        ref = comp.get("ref", "")
        constraints = kg_store.get_constraints(part_id) if kg_store else []
        if not constraints:
            continue

        for constraint in constraints:
            ctype = constraint.get("type")
            if ctype == "must_be_connected":
                pins = constraint.get("pins", [])
                for pin in pins:
                    pin_info = _find_pin(comp, pin)
                    if not pin_info:
                        continue
                    if not _is_connected(pin_info):
                        errors.append(VerificationError(
                            phase=PHASE_KG,
                            severity=SEVERITY_CRITICAL,
                            category=CAT_UNCONNECTED_PIN,
                            message=f"{ref}: pin {pin} is unconnected",
                            component=ref,
                            pin=str(pin),
                            constraint="must_be_connected",
                            suggestion=f"Connect pin {pin} on {ref} to the appropriate net.",
                        ))

            elif ctype == "supply_pair":
                vdd_pin = constraint.get("vdd_pin")
                gnd_pin = constraint.get("gnd_pin")
                vdd_info = _find_pin(comp, vdd_pin)
                gnd_info = _find_pin(comp, gnd_pin)
                if not vdd_info or not _is_connected(vdd_info):
                    errors.append(VerificationError(
                        phase=PHASE_KG,
                        severity=SEVERITY_CRITICAL,
                        category=CAT_SUPPLY_MISSING,
                        message=f"{ref}: supply pin {vdd_pin} missing net",
                        component=ref,
                        pin=str(vdd_pin),
                        constraint="supply_pair",
                        suggestion=f"Connect supply pin {vdd_pin} on {ref} to the power rail.",
                    ))
                if not gnd_info or not _is_connected(gnd_info):
                    errors.append(VerificationError(
                        phase=PHASE_KG,
                        severity=SEVERITY_CRITICAL,
                        category=CAT_SUPPLY_MISSING,
                        message=f"{ref}: ground pin {gnd_pin} missing net",
                        component=ref,
                        pin=str(gnd_pin),
                        constraint="supply_pair",
                        suggestion=f"Connect ground pin {gnd_pin} on {ref} to the ground net.",
                    ))
                if vdd_info and gnd_info:
                    vdd_net = vdd_info.get("net")
                    gnd_net = gnd_info.get("net")
                    if _is_connected(vdd_info) and _is_connected(gnd_info) and vdd_net == gnd_net:
                        errors.append(VerificationError(
                            phase=PHASE_KG,
                            severity=SEVERITY_CRITICAL,
                            category=CAT_SUPPLY_SHORT,
                            message=f"{ref}: supply pair shorted ({vdd_pin} and {gnd_pin} on {vdd_net})",
                            component=ref,
                            pin=str(vdd_pin),
                            net=str(vdd_net),
                            constraint="supply_pair",
                            suggestion=f"VDD pin {vdd_pin} and GND pin {gnd_pin} on {ref} must be on separate nets.",
                        ))

            elif ctype == "differential_pair_must_be_distinct":
                pins = constraint.get("pins", [])
                if len(pins) >= 2:
                    pin_a = _find_pin(comp, pins[0])
                    pin_b = _find_pin(comp, pins[1])
                    if pin_a and pin_b:
                        net_a = pin_a.get("net")
                        net_b = pin_b.get("net")
                        if _is_connected(pin_a) and _is_connected(pin_b) and net_a == net_b:
                            errors.append(VerificationError(
                                phase=PHASE_KG,
                                severity=SEVERITY_CRITICAL,
                                category=CAT_DIFFERENTIAL_SHORT,
                                message=f"{ref}: differential pins on same net ({pins[0]}={net_a})",
                                component=ref,
                                pin=str(pins[0]),
                                net=str(net_a),
                                constraint="differential_pair_must_be_distinct",
                                suggestion=f"Differential pins {pins[0]} and {pins[1]} on {ref} must be on separate nets.",
                            ))

            elif ctype == "driving_pair":
                gate_pin = constraint.get("gate_pin")
                gate_info = _find_pin(comp, gate_pin)
                if gate_info and _is_connected(gate_info):
                    if not allow_gate_float:
                        net_name = gate_info.get("net")
                        endpoint_count = len(nets.get(net_name, {}).get("endpoints", []))
                        if endpoint_count <= 1:
                            errors.append(VerificationError(
                                phase=PHASE_KG,
                                severity=SEVERITY_CRITICAL,
                                category=CAT_GATE_FLOATING,
                                message=f"{ref}: gate net appears floating ({gate_pin} on {net_name})",
                                component=ref,
                                pin=str(gate_pin),
                                net=str(net_name),
                                constraint="driving_pair",
                                suggestion=f"Gate pin {gate_pin} on {ref} is on net {net_name} with no other connections. Connect a gate driver to this net.",
                            ))
                else:
                    errors.append(VerificationError(
                        phase=PHASE_KG,
                        severity=SEVERITY_CRITICAL,
                        category=CAT_DRIVING_PAIR,
                        message=f"{ref}: gate pin {gate_pin} missing net",
                        component=ref,
                        pin=str(gate_pin),
                        constraint="driving_pair",
                        suggestion=f"Connect gate pin {gate_pin} on {ref} to the gate driver output.",
                    ))

    errors.extend(_check_acs37010_vref(snapshot))
    errors.extend(_check_kelvin_source_short(snapshot))
    errors.extend(_check_bootstrap_caps(snapshot))
    errors.extend(_check_ucc5390e_output_resistor(snapshot))

    return errors


def _check_acs37010_vref(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "ACS37010":
            continue
        ref = comp.get("ref", "")
        vref_info = _find_pin(comp, "VREF")
        gnd_info = _find_pin(comp, "GND")
        if not vref_info or not gnd_info:
            continue
        vref_net = vref_info.get("net")
        gnd_net = gnd_info.get("net")
        if vref_net and gnd_net and vref_net == gnd_net:
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_VREF_GND_SHORT,
                message=f"{ref}: VREF should not be tied to GND",
                component=ref,
                pin="VREF",
                net=str(vref_net),
                constraint="VREF must be separate from GND on ACS37010",
                suggestion=f"Connect VREF on {ref} to a separate voltage reference net, not GND.",
            ))
    return errors


def _check_acs37010_ip_short(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "ACS37010":
            continue
        ref = comp.get("ref", "")
        ipp_info = _find_pin(comp, "IP+")
        ipm_info = _find_pin(comp, "IP-")
        if not ipp_info or not ipm_info:
            continue
        if _is_connected(ipp_info) and _is_connected(ipm_info):
            net_p = ipp_info.get("net")
            net_m = ipm_info.get("net")
            if net_p == net_m:
                errors.append(VerificationError(
                    phase=PHASE_KG,
                    severity=SEVERITY_CRITICAL,
                    category=CAT_DIFFERENTIAL_SHORT,
                    message=f"{ref}: IP+ and IP- must not be shorted ({net_p})",
                    component=ref,
                    pin="IP+",
                    net=str(net_p),
                    constraint="ACS37010 IP+ and IP- must be on distinct nets",
                    suggestion=f"Connect IP+ and IP- on {ref} to separate current-sense nets.",
                ))
    return errors


def _check_mgj2d_vin_short(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "MGJ2D121505SC":
            continue
        ref = comp.get("ref", "")
        vplus = _find_pin(comp, "+VIN")
        vminus = _find_pin(comp, "-VIN")
        if not vplus or not vminus:
            continue
        if _is_connected(vplus) and _is_connected(vminus):
            net_p = vplus.get("net")
            net_m = vminus.get("net")
            if net_p == net_m:
                errors.append(VerificationError(
                    phase=PHASE_KG,
                    severity=SEVERITY_CRITICAL,
                    category=CAT_SUPPLY_SHORT,
                    message=f"{ref}: +VIN and -VIN must not be shorted ({net_p})",
                    component=ref,
                    pin="+VIN",
                    net=str(net_p),
                    constraint="MGJ2D121505SC +VIN and -VIN must be on distinct nets",
                    suggestion=f"Connect +VIN and -VIN on {ref} to separate supply nets.",
                ))
    return errors


def _check_tps54302_diode_pairs(snapshot):
    errors = []
    diode_pairs = set()
    for comp in snapshot.get("components", []):
        if not _is_passive_type(comp, "D"):
            continue
        nets = [pin.get("net") for pin in comp.get("pins", []) if _is_connected(pin)]
        if len(nets) != 2:
            continue
        net_a, net_b = nets
        if net_a and net_b:
            diode_pairs.add(tuple(sorted([net_a, net_b])))

    if not diode_pairs:
        return errors

    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "TPS54302":
            continue
        ref = comp.get("ref", "")
        for pin_a, pin_b in (("1", "2"), ("2", "3"), ("1", "6")):
            pin_a_info = _find_pin(comp, pin_a)
            pin_b_info = _find_pin(comp, pin_b)
            if not pin_a_info or not pin_b_info:
                continue
            if not (_is_connected(pin_a_info) and _is_connected(pin_b_info)):
                continue
            net_a = pin_a_info.get("net")
            net_b = pin_b_info.get("net")
            if not net_a or not net_b:
                continue
            if tuple(sorted([net_a, net_b])) in diode_pairs:
                errors.append(VerificationError(
                    phase=PHASE_KG,
                    severity=SEVERITY_CRITICAL,
                    category=CAT_SUPPLY_SHORT,
                    message=(
                        f"{ref}: diode detected between pins {pin_a} and {pin_b} "
                        f"({net_a} <-> {net_b})"
                    ),
                    component=ref,
                    pin=str(pin_a),
                    net=str(net_a),
                    constraint="TPS54302 must not have external diodes between certain pin pairs",
                    suggestion=f"Remove the diode between pins {pin_a} and {pin_b} on {ref}; the TPS54302 has an internal bootstrap diode.",
                ))
    return errors


def _check_kelvin_source_short(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        ref = comp.get("ref", "")
        kelvin_pins = [
            pin for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source"
        ]
        for pin in kelvin_pins:
            net = pin.get("net")
            if not net or str(net).upper() == "NC":
                pin_id = pin.get("pin_id") or pin.get("pin_name") or "?"
                errors.append(VerificationError(
                    phase=PHASE_KG,
                    severity=SEVERITY_CRITICAL,
                    category=CAT_KELVIN_VIOLATION,
                    message=f"{ref}: kelvin source pin must be connected to a net",
                    component=ref,
                    pin=str(pin_id),
                    constraint="Kelvin source pin must be connected",
                    suggestion=f"Connect the kelvin source pin on {ref} to the gate driver return path net.",
                ))
        source_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_source" and pin.get("net")
        }
        kelvin_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source" and pin.get("net")
        }
        if not source_nets or not kelvin_nets:
            continue
        if source_nets & kelvin_nets:
            net = sorted(source_nets & kelvin_nets)[0]
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_KELVIN_SHORT,
                message=f"{ref}: kelvin source should not be shorted to source net ({net})",
                component=ref,
                net=str(net),
                constraint="Kelvin source must be on a distinct net from power source",
                suggestion=f"Route the kelvin source on {ref} to a separate net from the power source pins. The kelvin source connects to the gate driver return, not the power path.",
            ))
    return errors


def _check_kelvin_source_distinct(snapshot):
    errors = []
    ks_by_ref = {}
    for comp in snapshot.get("components", []):
        if comp.get("category") != "MOSFET":
            continue
        ref = comp.get("ref", "")
        ks_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source" and _is_connected(pin)
        }
        if not ks_nets:
            continue
        if len(ks_nets) > 1:
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_KELVIN_VIOLATION,
                message=f"{ref}: kelvin source pins must be tied to a single net",
                component=ref,
                constraint="All kelvin source pins on one MOSFET must share one net",
                suggestion=f"Connect all kelvin source pins on {ref} to the same net.",
            ))
        ks_by_ref[ref] = ks_nets

    if len(ks_by_ref) < 2:
        return errors

    unique_nets = set()
    for nets in ks_by_ref.values():
        unique_nets.update(nets)

    if len(unique_nets) < len(ks_by_ref):
        errors.append(VerificationError(
            phase=PHASE_KG,
            severity=SEVERITY_CRITICAL,
            category=CAT_KELVIN_VIOLATION,
            message="Kelvin source nets must be distinct between MOSFETs",
            constraint="Each MOSFET must have a unique kelvin source net",
            suggestion="Ensure each MOSFET's kelvin source connects to its own dedicated gate driver return net.",
        ))
    return errors


def _check_kelvin_source_rlc_isolation(snapshot):
    errors = []
    graph = _build_bipartite_graph(snapshot)
    if not graph:
        return errors
    allowed = _allowed_rlc_nodes(snapshot, graph)
    for comp in snapshot.get("components", []):
        if comp.get("category") != "MOSFET":
            continue
        ref = comp.get("ref", "")
        ks_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source" and _is_connected(pin)
        }
        source_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_source" and _is_connected(pin)
        }
        if not ks_nets or not source_nets:
            continue
        for ks_net in ks_nets:
            for source_net in source_nets:
                if ks_net == source_net:
                    errors.append(VerificationError(
                        phase=PHASE_KG,
                        severity=SEVERITY_CRITICAL,
                        category=CAT_KELVIN_SHORT,
                        message=f"{ref}: kelvin source must not connect to source net ({ks_net})",
                        component=ref,
                        net=str(ks_net),
                        constraint="Kelvin source must be isolated from power source net",
                        suggestion=f"Route kelvin source on {ref} to a separate net from source net {ks_net}.",
                    ))
                    break
                if _has_rlc_path(graph, allowed, ks_net, source_net):
                    errors.append(VerificationError(
                        phase=PHASE_KG,
                        severity=SEVERITY_CRITICAL,
                        category=CAT_KELVIN_SHORT,
                        message=(
                            f"{ref}: kelvin source must not connect to source net via R/L/C network "
                            f"({ks_net} <-> {source_net})"
                        ),
                        component=ref,
                        net=str(ks_net),
                        constraint="Kelvin source must be isolated from power source even through passive networks",
                        suggestion=f"Remove any R/L/C path between kelvin source net {ks_net} and source net {source_net} on {ref}.",
                    ))
                    break
            if errors and str(errors[-1]).startswith(f"{ref}:"):
                break
    return errors


def _build_bipartite_graph(snapshot):
    graph = {}
    for comp in snapshot.get("components", []):
        comp_ref = comp.get("ref")
        if not comp_ref:
            continue
        comp_node = f"comp:{comp_ref}"
        graph.setdefault(comp_node, set())
        for pin in comp.get("pins", []):
            net_name = pin.get("net")
            if not net_name:
                continue
            net_node = f"net:{net_name}"
            graph.setdefault(net_node, set())
            graph[comp_node].add(net_node)
            graph[net_node].add(comp_node)
    return graph


def _allowed_rlc_nodes(snapshot, graph):
    allowed = {node for node in graph if node.startswith("net:")}
    for comp in snapshot.get("components", []):
        comp_ref = comp.get("ref")
        if not comp_ref:
            continue
        if any(_is_passive_type(comp, p) for p in ("R", "L", "C")):
            allowed.add(f"comp:{comp_ref}")
    return allowed


def _has_rlc_path(graph, allowed, start_net, end_net):
    start = f"net:{start_net}"
    end = f"net:{end_net}"
    if start not in graph or end not in graph:
        return False
    q = deque([start])
    visited = {start}
    while q:
        node = q.popleft()
        if node == end:
            return True
        for nb in graph.get(node, []):
            if nb in visited or nb not in allowed:
                continue
            visited.add(nb)
            q.append(nb)
    return False


def _check_mosfet_pins_connected(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("category") != "MOSFET":
            continue
        ref = comp.get("ref", "")
        for pin in comp.get("pins", []):
            net = pin.get("net")
            if not net or str(net).upper() in {"NC", "__NOCONNECT"}:
                pin_id = pin.get("pin_id") or pin.get("pin_name") or "?"
                errors.append(VerificationError(
                    phase=PHASE_KG,
                    severity=SEVERITY_CRITICAL,
                    category=CAT_MOSFET_PIN_UNCONNECTED,
                    message=f"{ref}: pin {pin_id} is unconnected (MOSFET pins must all connect)",
                    component=ref,
                    pin=str(pin_id),
                    constraint="All MOSFET pins must be explicitly connected",
                    suggestion=f"Connect pin {pin_id} on MOSFET {ref}. For TOLL/QFN packages, all parallel pads must be explicitly connected.",
                ))
                break
    return errors


def _check_vbus_decoupling_caps(snapshot):
    errors = []
    allowed_ground = {"GND", "PGND"}
    for comp in snapshot.get("components", []):
        if not _is_passive_type(comp, "C"):
            continue
        ref = comp.get("ref", "")
        nets = {pin.get("net") for pin in comp.get("pins", []) if _is_connected(pin)}
        nets_upper = {str(net).upper() for net in nets}
        if len(nets_upper) != 2:
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_DECOUPLING_MISSING,
                message=f"{ref}: decoupling cap must connect between VBUS+ and GND/PGND",
                component=ref,
                constraint="Decoupling capacitor must bridge VBUS+ and GND/PGND",
                suggestion=f"Connect capacitor {ref} with one terminal to VBUS+ and the other to GND or PGND.",
            ))
            continue
        if "VBUS+" not in nets_upper:
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_DECOUPLING_MISSING,
                message=f"{ref}: decoupling cap must connect between VBUS+ and GND/PGND",
                component=ref,
                constraint="Decoupling capacitor must bridge VBUS+ and GND/PGND",
                suggestion=f"Connect capacitor {ref} with one terminal to VBUS+ and the other to GND or PGND.",
            ))
            continue
        other = [n for n in nets_upper if n != "VBUS+"]
        if not other or other[0] not in allowed_ground:
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_DECOUPLING_MISSING,
                message=f"{ref}: decoupling cap must connect between VBUS+ and GND/PGND",
                component=ref,
                constraint="Decoupling capacitor must bridge VBUS+ and GND/PGND",
                suggestion=f"Connect capacitor {ref} with one terminal to VBUS+ and the other to GND or PGND.",
            ))
    return errors


def _check_ucc27511_outputs(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "UCC27511":
            continue
        ref = comp.get("ref", "")
        for label in ("OUTH", "OUTL"):
            pin_info = _find_pin(comp, label)
            if not pin_info or not _is_connected(pin_info):
                errors.append(VerificationError(
                    phase=PHASE_KG,
                    severity=SEVERITY_CRITICAL,
                    category=CAT_UNCONNECTED_PIN,
                    message=f"{ref}: {label} must be connected",
                    component=ref,
                    pin=label,
                    constraint=f"UCC27511 {label} output must be connected",
                    suggestion=f"Connect {label} on {ref} to the MOSFET gate net.",
                ))
                continue
            net = str(pin_info.get("net", "")).upper()
            if net in {"GND", "PGND"}:
                errors.append(VerificationError(
                    phase=PHASE_KG,
                    severity=SEVERITY_CRITICAL,
                    category=CAT_DRIVING_PAIR,
                    message=f"{ref}: {label} must not be tied to GND/PGND ({pin_info.get('net')})",
                    component=ref,
                    pin=label,
                    net=str(pin_info.get("net")),
                    constraint=f"UCC27511 {label} output must drive a gate, not be grounded",
                    suggestion=f"Connect {label} on {ref} to the MOSFET gate net instead of GND/PGND.",
                ))
    return errors


def _check_bootstrap_caps(snapshot):
    errors = []
    capacitors = []
    for comp in snapshot.get("components", []):
        if _is_passive_type(comp, "C"):
            nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
            capacitors.append(nets)

    for comp in snapshot.get("components", []):
        hb_info = _find_pin_by_role(comp, "halfbridge_hb")
        hs_info = _find_pin_by_role(comp, "halfbridge_hs")
        if not hb_info or not hs_info:
            continue
        hb_net = hb_info.get("net")
        hs_net = hs_info.get("net")
        if not hb_net or not hs_net:
            continue
        if not _has_cap_between(capacitors, hb_net, hs_net):
            ref = comp.get("ref", "")
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_BOOTSTRAP_MISSING,
                message=f"{ref}: bootstrap capacitor missing between HB and HS",
                component=ref,
                net=str(hb_net),
                constraint="Bootstrap capacitor required between HB and HS pins",
                suggestion=f"Add a bootstrap capacitor between the HB net ({hb_net}) and HS net ({hs_net}) on {ref}.",
            ))
    return errors


def _check_ucc5390e_output_resistor(snapshot):
    errors = []
    resistor_nets = []
    for comp in snapshot.get("components", []):
        if _is_passive_type(comp, "R"):
            nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
            resistor_nets.append(nets)

    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "UCC5390E":
            continue
        out_info = _find_pin(comp, "OUT")
        if not out_info or not out_info.get("net"):
            continue
        out_net = out_info.get("net")
        if not any(out_net in nets for nets in resistor_nets):
            ref = comp.get("ref", "")
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_OUTPUT_RESISTOR_MISSING,
                message=f"{ref}: output resistor missing on OUT net ({out_net})",
                component=ref,
                pin="OUT",
                net=str(out_net),
                constraint="UCC5390E OUT pin must have a series gate resistor",
                suggestion=f"Add a gate resistor on the OUT net ({out_net}) of {ref} to limit gate current.",
            ))
    return errors


def _check_ucc5390e_vin_minus(snapshot):
    errors = []
    index = index_snapshot(snapshot)
    nets = index["nets"]
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "UCC5390E":
            continue
        ref = comp.get("ref", "")
        pin_info = _find_pin(comp, "VEE2") or _find_pin(comp, "VIN-")
        if not pin_info:
            continue
        if not _is_connected(pin_info):
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_UNCONNECTED_PIN,
                message=f"{ref}: VEE2 (VIN-) must be connected",
                component=ref,
                pin="VEE2",
                constraint="UCC5390E VEE2/VIN- must be connected",
                suggestion=f"Connect VEE2 (VIN-) on {ref} to the negative supply rail.",
            ))
            continue
        net_name = pin_info.get("net")
        endpoint_count = len(nets.get(net_name, {}).get("endpoints", []))
        if endpoint_count <= 1:
            errors.append(VerificationError(
                phase=PHASE_KG,
                severity=SEVERITY_CRITICAL,
                category=CAT_PIN_FLOATING,
                message=f"{ref}: VEE2 (VIN-) net appears floating ({net_name})",
                component=ref,
                pin="VEE2",
                net=str(net_name),
                constraint="UCC5390E VEE2/VIN- net must have at least two endpoints",
                suggestion=f"Net {net_name} on {ref} VEE2 has only one endpoint. Connect it to another component.",
            ))
    return errors


def _find_pin_by_role(comp, role):
    for pin in comp.get("pins", []):
        if pin.get("pin_role") == role:
            return pin
    return None


def _is_passive_type(comp, passive_type):
    part_id = (comp.get("part_id") or "").strip()
    ref = (comp.get("ref") or "").strip()
    category = comp.get("category", "")
    if part_id == passive_type:
        return True
    if category != "passive":
        return False
    prefix = ref[:1].upper()
    return prefix == passive_type


def _has_cap_between(capacitors, net_a, net_b):
    for nets in capacitors:
        if net_a in nets and net_b in nets:
            return True
    return False


def _find_pin(comp, pin_key):
    pin_key = str(pin_key)
    for pin in comp.get("pins", []):
        if str(pin.get("pin_id", "")) == pin_key:
            return pin
        if str(pin.get("pin_name", "")) == pin_key:
            return pin
    return None


def _is_connected(pin_info):
    net = pin_info.get("net")
    if not net:
        return False
    if str(net).upper() in {"NC", "__NOCONNECT"}:
        return False
    return True
