# Zonal IVN TSN Simulation

OMNeT++/INET simulation project for evaluating Quality of Service (QoS),
Audio Video Bridging (AVB), and Time-Sensitive Networking (TSN) mechanisms
in a zonal automotive in-vehicle network.

The project models a zonal Ethernet-based automotive architecture with
heterogeneous traffic, including control, sensor, audio/video, diagnostic,
and best-effort flows. The simulations will compare different traffic
management configurations under multiple network load conditions.

## Project objectives

The main objectives are:

- model a realistic zonal automotive network architecture;
- define a traceable automotive traffic catalog;
- establish a conventional Ethernet baseline;
- evaluate IEEE 802.1Q strict priority;
- evaluate AVB Credit-Based Shaping with standard classes;
- evaluate custom AVB classes and idle slopes;
- evaluate an additional TSN mechanism supported by INET;
- analyze latency, jitter, deadline misses, link utilization, queueing,
  throughput, and packet loss;
- provide reproducible simulation campaigns and analysis scripts.

The experimental methodology is inspired by the progression used by Navet,
Villanueva, and Migge in their evaluation of AVB and TSN for automotive
applications. The goal is to reproduce the methodology and qualitative
questions in an INET-based zonal architecture, rather than reproduce their
numerical results exactly.

## Software environment

The project uses the following software versions:

- OMNeT++ 6.4.0
- INET Framework 4.7.0

The INET project must be imported and successfully built in the same
OMNeT++ workspace before building this project.

Qtenv is intended for model development, debugging, and visualization.
Cmdenv will be used for automated simulation campaigns.

## Repository structure

```text
src/
    Project-specific reusable NED and C++ modules.

simulations/
    Main zonal IVN model and OMNeT++ configuration files.

simulations/zonal/configs/
    Reusable configuration fragments for topology, traffic, TSN
    mechanisms, and result recording.

simulations/zonal/traffic/
    Input files describing traffic profiles and streams.

tests/validation/
    Minimal simulation scenarios used to validate topology, traffic
    generation, classification, queues, and shaping mechanisms.

scripts/run/
    Scripts for executing simulation campaigns.

scripts/analysis/
    Scripts for extracting, aggregating, and plotting simulation results.

docs/design/
    Architecture, model specification, and experimental design.

docs/decisions/
    Technical decision records.

docs/traffic-catalog/
    Traffic definitions, sources, and offered-load calculations.

docs/report/
    Project report sources.

docs/figures/
    Selected figures used in the report and presentation.

results/
    Generated simulation results. This directory is not versioned.
```

## Initial simulation configurations

The planned configuration progression is:

- `E0`: conventional Ethernet baseline;
- `E1`: IEEE 802.1Q strict priority;
- `E2`: AVB/CBS with standard traffic classes;
- `E3`: AVB/CBS with custom classes and idle slopes;
- `E4`: an additional TSN mechanism selected after evaluating INET support.

Each configuration will be evaluated under multiple load levels, ranging
from low load to controlled overload.

## Building the project

1. Install and configure OMNeT++ 6.4.0.
2. Import INET Framework 4.7.0 into the OMNeT++ workspace.
3. Build the INET project.
4. Import this repository as an OMNeT++ project.
5. Add `inet` as a project reference.
6. Build this project.

The main simulation configuration will be available at:

```text
simulations/omnetpp.ini
```

## Results and reproducibility

Raw OMNeT++ result files such as `.sca`, `.vec`, and `.vci` are not stored
in Git.

Simulation campaigns must record at least:

- source-code revision;
- simulation configuration;
- load level;
- random seed;
- replication number;
- simulation duration;
- relevant model parameters.

Final plots must be reproducible from the analysis scripts and the
corresponding simulation results.

## Project status

The project is currently in the detailed design and initial model
construction phase.
