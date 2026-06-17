# PCBSchemaGen — Benchmarks & Verifier

This repository provides the **two benchmark suites** and the **deterministic 5-layer verifier** from the paper
*PCBSchemaGen: Reward-Guided LLM Code Synthesis for Printed Circuit Board (PCB) Schematic Design with Structured Verification*.

It lets anyone (i) load the **227 PCB schematic-synthesis tasks**, and (ii) run the **deterministic structural verifier**
that scores a candidate SKiDL design against real-IC pin- and topology-level constraints — no LLM, no API key,
and no cached results required.

## What's included

```
PCBSchemaGen_v2/
├── benchmarks/
│   ├── pcbbench/benchmark.tsv                   # 62 hand-authored tasks (Easy/Medium/Hard)
│   └── open_schematics/ose_165_task_specs.json  # 165 tasks from public schematics
├── framework/
│   ├── topo/                                    # the deterministic 5-layer verifier (self-contained)
│   └── task_config.yaml                         # per-task verification parameters
├── kg/kg_open_schematics.json                   # schema-induced KG for Open-Schematics-Eval
├── component.json / kg_component.json / kg.json # schema-induced KG for PCBBench
├── requirements.txt
└── LICENSE
```

## Benchmarks at a glance

| Suite | Tasks | Difficulty split | Real ICs | Domains |
|---|---|---|---|---|
| PCBBench (`benchmarks/pcbbench/benchmark.tsv`) | 62 | 17 Easy / 28 Medium / 17 Hard | 41 commercial | 22 |
| Open-Schematics-Eval (`benchmarks/open_schematics/ose_165_task_specs.json`) | 165 | 40 Easy / 48 Medium / 77 Hard | 439 commercial | 22 |
| **Total** | **227** | 57 / 76 / 94 | 480 | 22 |

Each PCBBench task row specifies: task id, difficulty level, circuit type, the natural-language task,
input/output nodes, input/output voltages, and the required-component set.

## The deterministic 5-layer verifier

The verifier scores a candidate schematic against structural constraints derived from real IC datasheets —
fully deterministic, with no golden reference and no functional simulation:

1. **L1 ERC** — electrical invariants (VDD/GND disjointness, power reachability, ground integrity)
2. **L1b Role** — pin-role compatibility under the 32-role schema
3. **L2 Template** — per-IC subcategory connection templates
4. **L3 Topology** — subgraph isomorphism vs. canonical motifs (half-bridge, sync-buck, three-phase inverter, …)
5. **L4 Power** — domain-specific power rules (Kelvin source, decoupling, isolation, gate-resistor)

See the paper appendix (verification details) for the full predicate set and reward ladder.

## Install

```bash
python3 -m pip install -r requirements.txt   # networkx, pyyaml
```

## Using the verifier

The verifier is self-contained in `framework/topo/` (only depends on `networkx`). It exposes, among others:

```python
from framework.topo import (
    KGStore, index_snapshot,
    check_system_topology, is_complex_task,
    validate_complex_task, get_validation_feedback_for_llm,
)

# 1. Load the schema-induced KG (component.json + kg_component.json)
kg = KGStore(base_dir=".")

# 2. Index a candidate design snapshot (nets / parts extracted from a SKiDL build)
snapshot = index_snapshot(...)

# 3. Run the layered checks
#    - system-level validation for Hard / complex tasks:
report = validate_complex_task(...)
#    - or per-layer checks: check_system_topology(...), run_phase2_checks(...)
```

Per-task verification parameters (match mode, enabled checks, skipped rules) live in
`framework/task_config.yaml`. Exact function signatures are documented in each module's
docstring under `framework/topo/` and in the paper appendix.

## License

Released under the MIT License (see `LICENSE`). Open-Schematics-Eval tasks are derived from the
public `open-schematics` dataset (MIT). Vendor datasheets referenced during KG construction are
cited, not redistributed.

## Citation

```bibtex
@inproceedings{pcbschemagen2026,
  title     = {PCBSchemaGen: Reward-Guided LLM Code Synthesis for Printed Circuit Board (PCB)
               Schematic Design with Structured Verification},
  author    = {Zou, Huanghaohe and Han, Peng and Nazerian, Emad and
               Zhang, Mafu and Guo, Zhicheng and Huang, Alex Q.},
  year      = {2026},
}
```
