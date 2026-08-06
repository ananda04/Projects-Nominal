"""
gem5_nominal.py
---------------
Push gem5 Garnet NoC synthetic-traffic sweep results to Nominal Core.

Entry points:
  * push_results_json(path)  -> BATCH: ONE run for ALL topologies, with metric
                                channels prefixed by topology
                                (Torus.average_packet_latency,
                                 Mesh_XY.average_packet_latency, ...) plus a
                                single shared `injection_rate` channel (scatter X).
  * start_stream(topology)   -> LIVE: stream one topology's sweep into an
                                open-ended run as it runs.

Pure library: stdlib + `nominal` only (no connect_python, no pandas).
CLI: python gem5_nominal.py results.json [--topology X] [--profile P] [--dry-run]
"""

import csv
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from nominal.core import NominalClient


# --------------------------------------------------------------------------- config
NOMINAL_PROFILE = os.environ.get("NOMINAL_PROFILE", "default")
NOMINAL_TOKEN = os.environ.get("NOMINAL_TOKEN")  # optional; profile is preferred

ASSET_NAME = "gem5 Garnet NoC"
ASSET_PROPS = {"simulator": "gem5", "network": "garnet"}

TIME_COLUMN = "t_inj_s"

# Unit map for channels (cosmetic — sets axis units in Nominal). The actual set
# of channels pushed is DISCOVERED from the data, so this only needs to be
# right for the units you care about. injection_rate is handled specially.
CHANNELS = {
    "injection_rate":          "",            # flits/node/cycle (0..1)
    "average_flit_latency":    "cycles",
    "average_packet_latency":  "cycles",
    "packets_injected":        "packets",
    "packets_received":        "packets",
    "delivery_rate":           "%",
    "peak_crossbar_value":     "activations",
    "peak_bufwrite_value":     "writes",
    "total_crossbar_act":      "activations",
    "total_buffer_writes":     "writes",
    "dram_total_avg_power_mw":  "mW",
    "dram_total_energy_pj":     "pJ",
    "dram_peak_ctrl_power_mw":  "mW",
}

# Keys that sit alongside metrics in a record but are NOT channels.
_META_KEYS = {
    "topology", "Topology", "injection_rate", "injectionrate", "inj_rate",
    "injection", "cycle", "cycles", "sim_cycles", "date", "timestamp",
    "num_cpus", "num_dirs", "mesh_rows", "vcs_per_vnet",
}
# Numeric fields that are identifiers, not measurements -> never plotted.
_EXCLUDE_METRIC_SUFFIXES = ("_router", "_id")


# --------------------------------------------------------------------------- results.json loading
def _coerce_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def flatten_results_json(path):
    """Read results.json (whatever nesting gem5stats_core wrote) into a list of
    flat records, each a dict with at least 'topology' and 'injection_rate'
    plus metric fields. Tolerates:
      * list of record dicts
      * {topology: {injection_rate: {<metrics>, ...}}}
      * {topology: [ {<metrics>, injection_rate, ...}, ... ]}
    """
    with open(path) as f:
        data = json.load(f)

    records = []

    def _emit(metrics, topology=None, injection_rate=None):
        if not isinstance(metrics, dict):
            return
        rec = dict(metrics)
        # unwrap a nested {"metrics": {...}} sub-dict if present
        if isinstance(rec.get("metrics"), dict):
            inner = rec.pop("metrics")
            for k, v in inner.items():
                rec.setdefault(k, v)
        if topology is not None and not rec.get("topology"):
            rec["topology"] = topology
        if not rec.get("topology") and rec.get("Topology"):
            rec["topology"] = rec["Topology"]
        if injection_rate is not None and rec.get("injection_rate") is None:
            rec["injection_rate"] = injection_rate
        if rec.get("injection_rate") is None:
            for alt in ("injectionrate", "inj_rate", "injection"):
                if rec.get(alt) is not None:
                    rec["injection_rate"] = rec[alt]
                    break
        records.append(rec)

    if isinstance(data, list):
        for rec in data:
            _emit(rec)
    elif isinstance(data, dict):
        looks_nested = any(isinstance(v, (dict, list)) for v in data.values())
        if not looks_nested:
            _emit(data)  # single flat record
        else:
            for topo, sweeps in data.items():
                if isinstance(sweeps, dict):
                    for rate_key, metrics in sweeps.items():
                        _emit(metrics, topology=topo,
                              injection_rate=_coerce_float(rate_key))
                elif isinstance(sweeps, list):
                    for metrics in sweeps:
                        _emit(metrics, topology=topo)
    return records


def _topo_of(rec):
    return rec.get("topology") or rec.get("Topology") or "unknown"


def _record_date(rec):
    return str(rec.get("date") or rec.get("timestamp") or "")


def latest_per_rate(records):
    """De-duplicate to the latest record per (topology, injection_rate)."""
    best = {}
    for rec in records:
        key = (_topo_of(rec), _coerce_float(rec.get("injection_rate")))
        prev = best.get(key)
        if prev is None or _record_date(rec) >= _record_date(prev):
            best[key] = rec
    return sorted(
        best.values(),
        key=lambda r: (_topo_of(r), _coerce_float(r.get("injection_rate")) or 0.0),
    )


def _channel_value(rec, name):
    """Numeric value of a field in a record, or None."""
    if name not in rec:
        return None
    return _coerce_float(rec.get(name))


def _discover_metrics(records):
    """Numeric, non-metadata, non-identifier fields seen across records.
    Ordered by CHANNELS first (nice grouping + units), then any extras."""
    seen = set()
    for r in records:
        for k, v in r.items():
            if k in _META_KEYS or k == "injection_rate":
                continue
            if any(str(k).endswith(s) for s in _EXCLUDE_METRIC_SUFFIXES):
                continue
            if _coerce_float(v) is not None:
                seen.add(k)
    ordered = [c for c in CHANNELS if c != "injection_rate" and c in seen]
    extras = [k for k in sorted(seen) if k not in CHANNELS]
    return ordered + extras


# --------------------------------------------------------------------------- nominal helpers
def _client(profile=None):
    if NOMINAL_TOKEN:
        return NominalClient.from_token(NOMINAL_TOKEN)
    return NominalClient.from_profile(profile or NOMINAL_PROFILE)


def _get_or_create_asset(client, log=print):
    try:
        found = list(client.search_assets(properties=ASSET_PROPS))
    except Exception as e:
        log(f"nominal: search_assets failed ({e}); creating a fresh asset")
        found = []
    for a in found:
        if getattr(a, "name", None) == ASSET_NAME:
            return a
    if found:
        return found[0]
    return client.create_asset(
        name=ASSET_NAME, description="gem5 Garnet NoC sweeps", properties=ASSET_PROPS
    )


def _safe(name):
    # keep alnum/_/- only, so the only '.' in a channel name is the tree delimiter
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in str(name))


def _rid_suffix(obj, n=6):
    rid = getattr(obj, "rid", "") or ""
    return rid.replace(".", "_")[-n:] if rid else "xxxxxx"


def _unique_ref(topology, dataset):
    """Ref-name unique per dataset (avoids Scout:RefNamesAlreadyUsed across runs
    sharing an asset)."""
    return f"noc_{_safe(topology)}_{_rid_suffix(dataset)}"


def _unit_of(chan):
    u = CHANNELS.get(chan, "")
    if isinstance(u, dict):
        return u.get("unit", "") or ""
    return u or ""


def _upload_tabular(dataset, csv_path):
    fn = (getattr(dataset, "add_tabular_data", None)
          or getattr(dataset, "add_tabular_data_to_dataset", None))
    if fn is None:
        raise AttributeError("Dataset has no add_tabular_data[_to_dataset] method")
    return fn(csv_path, timestamp_column=TIME_COLUMN, timestamp_type="epoch_seconds")


# --------------------------------------------------------------------------- BATCH push (Option B)
def _write_combined_csv(records, topologies, metrics, has_inj, path):
    header = [TIME_COLUMN]
    if has_inj:
        header.append("injection_rate")
    header += [f"{_safe(t)}.{c}" for t in topologies for c in metrics]

    base = datetime.now().timestamp()
    idx = 0
    rows = []
    for topo in topologies:
        recs = [r for r in records if _topo_of(r) == topo]
        recs.sort(key=lambda r: (_channel_value(r, "injection_rate") or 0.0))
        for rec in recs:
            row = {TIME_COLUMN: base + idx}
            if has_inj:
                iv = _channel_value(rec, "injection_rate")
                if iv is not None:
                    row["injection_rate"] = iv
            for c in metrics:
                v = _channel_value(rec, c)
                if v is not None:
                    row[f"{_safe(topo)}.{c}"] = v
            rows.append(row)
            idx += 1

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return base, idx


def push_results_json(path, topology=None, profile=None, dry_run=False, log=print):
    """BATCH: push cached gem5 results as ONE run whose metric channels are
    prefixed by topology, so a single workbook's channel tree separates by
    topology. `injection_rate` is one shared channel (use it as the scatter X)."""
    records = latest_per_rate(flatten_results_json(path))
    if topology:
        records = [r for r in records if _topo_of(r) == topology]
    if not records:
        log("nominal: no records to push")
        return []

    topologies = []
    for r in records:
        t = _topo_of(r)
        if t not in topologies:
            topologies.append(t)
    metrics = _discover_metrics(records)
    has_inj = any(_channel_value(r, "injection_rate") is not None for r in records)

    if dry_run:
        log(f"nominal (dry-run): {len(records)} rows, topologies={topologies}")
        log(f"nominal (dry-run): channels = "
            f"{'injection_rate + ' if has_inj else ''}"
            f"{{{', '.join(topologies)}}} x {metrics}")
        return []

    client = _client(profile)
    asset = _get_or_create_asset(client, log)

    tmp = os.path.join(tempfile.gettempdir(),
                       f"gem5_combined_{int(datetime.now().timestamp())}.csv")
    base, nrows = _write_combined_csv(records, topologies, metrics, has_inj, tmp)

    label = " + ".join(topologies)
    dataset = client.create_dataset(
        name=f"gem5 NoC sweep — {label}",
        description="gem5 Garnet synthetic-traffic sweep; metrics prefixed by topology",
        properties=ASSET_PROPS,
        prefix_tree_delimiter=".",
    )
    _upload_tabular(dataset, tmp)

    units = {}
    if has_inj and _unit_of("injection_rate"):
        units["injection_rate"] = _unit_of("injection_rate")
    for t in topologies:
        for c in metrics:
            u = _unit_of(c)
            if u:
                units[f"{_safe(t)}.{c}"] = u
    if units:
        try:
            dataset.set_channel_units(units, validate_schema=False)
        except Exception as e:
            log(f"nominal: set_channel_units skipped ({e})")

    start = datetime.fromtimestamp(base)
    end = datetime.fromtimestamp(base + max(nrows - 1, 0))
    run = client.create_run(
        name=f"gem5 NoC — {label}",
        description="Single run; metrics prefixed by topology for in-workbook comparison",
        start=start,
        end=end,
        asset=asset.rid,
    )
    run.add_dataset(_unique_ref("all", dataset), dataset)

    log(f"nominal: run {run.rid}")
    log(f"nominal: asset {asset.rid}  dataset {dataset.rid}")
    log(f"nominal: 1 run, {len(topologies)} topolog(ies), {len(metrics)} metric channel(s) each")
    return [run.rid]


# --------------------------------------------------------------------------- LIVE streaming (one topology)
class SweepStream:
    """Live writer for a single topology's sweep. Each .send() enqueues one
    injection-rate point at wall-clock 'now'. Channels are tagged with topology
    (live runs are one topology each, so no prefixing is needed)."""

    def __init__(self, client, dataset, run, stream_cm, stream, topology, log=print):
        self._client = client
        self.dataset = dataset
        self.run = run
        self._cm = stream_cm
        self._stream = stream
        self.topology = topology
        self._log = log

    def send(self, flat, injection_rate):
        ts = datetime.now(timezone.utc)
        tags = {"topology": self.topology}
        if injection_rate is not None:
            self._stream.enqueue(channel_name="injection_rate", timestamp=ts,
                                 value=float(injection_rate), tags=tags)
        for chan, v in ((c, _channel_value(flat, c)) for c in CHANNELS):
            if chan == "injection_rate" or v is None:
                continue
            self._stream.enqueue(channel_name=chan, timestamp=ts, value=v, tags=tags)

    def close(self):
        try:
            self._cm.__exit__(None, None, None)
        except Exception as e:
            self._log(f"nominal: stream close warning ({e})")


def start_stream(topology, profile=None, max_wait_s=2, log=print):
    """Create an open-ended run + dataset and return a SweepStream you can
    .send(flat, injection_rate) into live, then .close()."""
    client = _client(profile)
    asset = _get_or_create_asset(client, log)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    dataset = client.create_dataset(
        name=f"gem5 NoC live — {topology} — {stamp}",
        description="gem5 Garnet synthetic-traffic live sweep",
        properties=ASSET_PROPS,
        prefix_tree_delimiter=".",
    )
    run = client.create_run(
        name=f"gem5 NoC — {topology} — {stamp} (live)",
        description="Live gem5 Garnet sweep",
        start=datetime.now(),
        end=None,
        asset=asset.rid,
    )
    run.add_dataset(_unique_ref(topology, dataset), dataset)

    cm = dataset.get_write_stream(max_wait=timedelta(seconds=max_wait_s))
    stream = cm.__enter__()
    log(f"nominal: live run {run.rid}")
    log(f"nominal: asset {asset.rid}  dataset {dataset.rid}")
    return SweepStream(client, dataset, run, cm, stream, topology, log)


# --------------------------------------------------------------------------- CLI
def _main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Push gem5 results.json to Nominal Core")
    p.add_argument("path", help="path to results.json")
    p.add_argument("--topology", default=None, help="push only this topology")
    p.add_argument("--profile", default=None, help="Nominal profile name")
    p.add_argument("--dry-run", action="store_true", help="show what would be pushed")
    args = p.parse_args(argv)

    rids = push_results_json(args.path, topology=args.topology,
                             profile=args.profile, dry_run=args.dry_run)
    if rids:
        print("done: pushed 1 run to Nominal (all topologies, channels prefixed by topology)")
        for rid in rids:
            print(f"  run {rid}")


if __name__ == "__main__":
    _main()