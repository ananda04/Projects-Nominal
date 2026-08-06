# gem5 NoC Simulation Runner & Nominal Core Integration

Automates gem5 Garnet Network-on-Chip (NoC) synthetic traffic sweeps within Nominal Connect and Docker, parses simulation statistics, and uploads output data to Nominal Core for post-evaluation.

## Repository Structure

* `app.connect`: Nominal Connect UI layout and parameter configuration.
* `autotest_connect.py`: Main sweep runner executing gem5 in Docker.
* `gem5stats_core.py`: Stat parser extracting metrics from gem5 `stats.txt` output.
* `gem5_nominal.py`: Core integration library for pushing batch and live runs to Nominal.
* `send_to_core.py`: Action script triggered from Connect UI to upload cached results.
* `results.json`: Local storage cache for parsed simulation metrics.

## Workflow

1. Configure sweep parameters (topology, cpus, injection rate range) in the Nominal Connect interface.
2. Execute simulation sweep via `autotest_connect.py`, which invokes gem5 inside a Docker container.
3. `gem5stats_core.py` automatically parses latency, contention, and power stats into `results.json`.
4. Batch upload results to Nominal Core by triggering `send_to_core.py`.

## Configuration Options (app.connect)

| Parameter Key | Default Value | Description |
| :--- | :--- | :--- |
| `gem5_binary` | `./build/NULL/gem5.opt` | Path to compiled gem5 binary in container. |
| `config_script` | `configs/example/garnet_synth_traffic.py` | Garnet synthetic traffic script path. |
| `program` | `""` | Workload path for SE mode (blank for synthetic). |
| `topology` | `""` (defaults to `Mesh_XY`) | NoC layout topology. |
| `output_dir` | `./gem5_runs` | Host output directory for run stats. |
| `num_nodes` | `32` | Number of CPUs / network nodes. |
| `injection_start` | `0.02` | Starting packet injection rate. |
| `injection_stop` | `0.5` | Ending packet injection rate. |
| `injection_step` | `0.02` | Injection rate increment step. |
| `enable_power_models` | `false` | Enable power model calculation. |

## Extracted Metrics

* **Latency & Throughput:** Flit/packet latency, packets injected/received, delivery rate.
* **Router Contention:** Peak crossbar & buffer write routers and values, total activity.
* **DRAM Power:** Average power (mW), total energy (pJ), peak controller power.

## Usage

### Nominal Connect UI
1. Open **GEM5 RUNNER** in Nominal Connect.
2. Set configuration parameters and click **Run gem5**.
3. Click **Send to core** to batch upload results to Nominal Core.

### Command Line
```bash
# Upload results.json directly
python gem5_nominal.py results.json

# Upload specific topology or profile
python gem5_nominal.py results.json --topology Torus --profile default
