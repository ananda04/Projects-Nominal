"""Parse a gem5 Garnet (NoC) stats.txt into network/router/DRAM metrics.

Parsing is unchanged from the original script; it's just exposed as reusable
functions so the Connect runner and the Nominal pusher can share one parser:
  * parse_stats(stats_file)        -> FLAT dict of metrics
  * to_record(...) / cache_record(...) -> nested results.json entry + append
  * results(...) + CLI             -> unchanged usage:
        python gem5stats_core.py <stats_file> <topology> <injection_rate> [cycle]
"""
import sys
import re
import os
import json
from datetime import datetime

_NETWORK_KEYS = (
    "average_flit_latency",
    "average_packet_latency",
    "packets_injected::total",
    "packets_received::total",
)


def parse_stats(stats_file):
    """Read a gem5 stats.txt and return a FLAT dict of metrics (values float|int|None)."""
    metrics = {k: None for k in _NETWORK_KEYS}
    router_xbar = {}
    router_buf_w = {}
    router_buf_r = {}
    dram_avg_power = {}
    dram_total_energy = {}

    with open(stats_file) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            key_raw = parts[0]

            for key in metrics:
                if key_raw.endswith(key):
                    val = re.search(r'[\d.]+', parts[1])
                    if val:
                        metrics[key] = float(val.group())

            m = re.match(r'.*\.routers(\d+)\.(crossbar_activity|buffer_writes|buffer_reads)$', key_raw)
            if m:
                rid, stat = int(m.group(1)), m.group(2)
                val = re.search(r'[\d.]+', parts[1])
                if val:
                    v = float(val.group())
                    if stat == 'crossbar_activity':
                        router_xbar[rid] = v
                    elif stat == 'buffer_writes':
                        router_buf_w[rid] = v
                    elif stat == 'buffer_reads':
                        router_buf_r[rid] = v

            m = re.match(r'system\.mem_ctrls(\d+)\.dram\.rank(\d+)\.(averagePower|totalEnergy)$', key_raw)
            if m:
                ctrl, rank, stat = int(m.group(1)), int(m.group(2)), m.group(3)
                val = re.search(r'[\d.]+', parts[1])
                if val:
                    v = float(val.group())
                    if stat == 'averagePower':
                        dram_avg_power[(ctrl, rank)] = v
                    elif stat == 'totalEnergy':
                        dram_total_energy[(ctrl, rank)] = v

    # Derived metrics
    delivery = None
    if metrics["packets_received::total"] and metrics["packets_injected::total"]:
        delivery = metrics["packets_received::total"] / metrics["packets_injected::total"] * 100

    worst_xbar_router, worst_xbar_val = ((max(router_xbar, key=router_xbar.get), max(router_xbar.values())) if router_xbar else (None, None))
    worst_bufw_router, worst_bufw_val = ((max(router_buf_w, key=router_buf_w.get), max(router_buf_w.values())) if router_buf_w else (None, None))

    total_xbar  = sum(router_xbar.values())  if router_xbar  else None
    total_buf_w = sum(router_buf_w.values()) if router_buf_w else None

    total_dram_power_mw  = sum(dram_avg_power.values())    if dram_avg_power    else None
    total_dram_energy_pj = sum(dram_total_energy.values()) if dram_total_energy else None
    peak_ctrl_power = None
    peak_ctrl_id    = None
    if dram_avg_power:
        ctrl_power = {}
        for (ctrl, rank), p in dram_avg_power.items():
            ctrl_power[ctrl] = ctrl_power.get(ctrl, 0) + p
        peak_ctrl_id    = max(ctrl_power, key=ctrl_power.get)
        peak_ctrl_power = ctrl_power[peak_ctrl_id]

    return {
        "average_flit_latency": metrics["average_flit_latency"],
        "average_packet_latency": metrics["average_packet_latency"],
        "packets_injected": metrics["packets_injected::total"],
        "packets_received": metrics["packets_received::total"],
        "delivery_rate": delivery,
        "peak_crossbar_router": worst_xbar_router,
        "peak_crossbar_value": worst_xbar_val,
        "peak_bufwrite_router": worst_bufw_router,
        "peak_bufwrite_value": worst_bufw_val,
        "total_crossbar_act": total_xbar,
        "total_buffer_writes": total_buf_w,
        "dram_total_avg_power_mw": round(total_dram_power_mw, 2) if total_dram_power_mw else None,
        "dram_total_energy_pj": round(total_dram_energy_pj, 0) if total_dram_energy_pj else None,
        "dram_peak_ctrl_id": peak_ctrl_id,
        "dram_peak_ctrl_power_mw": round(peak_ctrl_power, 2) if peak_ctrl_power else None,
    }


def to_record(flat, topology, injection_rate, cycle):
    """Assemble the original nested results.json entry from a flat parse dict."""
    return {
        "topology": topology,
        "date": datetime.now().isoformat(),
        "injection_rate": injection_rate,
        "cycle (ticks)": cycle,
        "average_flit_latency": flat["average_flit_latency"],
        "average_packet_latency": flat["average_packet_latency"],
        "packets_injected": flat["packets_injected"],
        "packets_received": flat["packets_received"],
        "delivery_rate": flat["delivery_rate"],
        "worst_case_latency_proxy": {
            "peak_crossbar_router": flat["peak_crossbar_router"],
            "peak_crossbar_value": flat["peak_crossbar_value"],
            "peak_bufwrite_router": flat["peak_bufwrite_router"],
            "peak_bufwrite_value": flat["peak_bufwrite_value"],
            "total_crossbar_act": flat["total_crossbar_act"],
            "total_buffer_writes": flat["total_buffer_writes"],
        },
        "dram_power": {
            "total_avg_power_mw": flat["dram_total_avg_power_mw"],
            "total_energy_pj": flat["dram_total_energy_pj"],
            "peak_ctrl_id": flat["dram_peak_ctrl_id"],
            "peak_ctrl_power_mw": flat["dram_peak_ctrl_power_mw"],
        },
    }


def cache_record(record, json_path="results.json"):
    """Append one record to the JSON list at json_path (creates it if missing)."""
    if os.path.exists(json_path):
        with open(json_path) as f:
            all_results = json.load(f)
        if not isinstance(all_results, list):
            all_results = [all_results]
    else:
        all_results = []
    all_results.append(record)
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=4)
    return json_path


def results(stats_file, topology, injection_rate, cycle, json_path="results.json"):
    """Parse, pretty-print, and append to results.json. Returns the cached record."""
    flat = parse_stats(stats_file)

    print("\n===== Network Stats =====")
    print(f"  {'average_flit_latency':<35} {flat['average_flit_latency']}")
    print(f"  {'average_packet_latency':<35} {flat['average_packet_latency']}")
    print(f"  {'packets_injected::total':<35} {flat['packets_injected']}")
    print(f"  {'packets_received::total':<35} {flat['packets_received']}")
    if flat["delivery_rate"] is not None:
        print(f"  {'delivery_rate':<35} {flat['delivery_rate']:.1f}%")
    print("=========================\n")

    record = to_record(flat, topology, injection_rate, cycle)
    cache_record(record, json_path)
    return record


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python gem5stats_core.py <stats_file> <topology> <injection_rate> [cycle]")
        sys.exit(1)
    stats_file = sys.argv[1]
    topology = sys.argv[2]
    injection_rate = float(sys.argv[3])
    cycle = sys.argv[4] if len(sys.argv) > 4 else None
    results(stats_file, topology, injection_rate, cycle)