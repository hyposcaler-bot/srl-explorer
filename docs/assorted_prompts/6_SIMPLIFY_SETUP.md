# Integrate srl-telemetry-lab into srl-explorer

Add Makefile targets to clone, start, and stop the srl-telemetry-lab inside the srl-explorer project directory. The goal is a single-directory experience: clone srl-explorer, make setup, make lab-up, make run.

## Makefile changes

### Configuration variables (near existing YANG_MODELS vars)

Add:

    TELEMETRY_LAB_REPO ?= https://github.com/srl-labs/srl-telemetry-lab
    TELEMETRY_LAB_DIR  ?= srl-telemetry-lab

### New targets

**make lab** (clone only, follows the yang-models pattern):

Clone srl-telemetry-lab into the project directory if not already present. Same pattern as the existing yang-models target: check if directory exists, clone if not, print message if already present. No branch/tag pin needed, just clone main.

**make lab-up** (clone if needed, then start):

Depends on setup and lab targets (so deps get installed and lab gets cloned if needed). Then cd into the srl-telemetry-lab directory and run `containerlab deploy --reconfigure`.

**make lab-down** (stop the lab):

cd into the srl-telemetry-lab directory and run `containerlab destroy`.

**make lab-traffic** (start traffic generation):

cd into the srl-telemetry-lab directory and run `docker exec -d client1 bash /config/traffic.sh`. The lab starts with no traffic flowing between nodes, this script generates traffic so Prometheus has data to query.

### Update make setup

Add lab as a dependency alongside yang-models, so `make setup` clones both if not present.

## .gitignore changes

Add `srl-telemetry-lab/` to .gitignore, same section as `srlinux-yang-models/`.

## .dockerignore changes

Add `srl-telemetry-lab/` to .dockerignore.

## README changes

Update the Installation section to reflect the simplified workflow:

    git clone https://github.com/hyposcaler/srl-explorer.git
    cd srl-explorer
    make setup
    make lab-up
    make run

Update the Development table to include the new targets: make lab-up, make lab-down, make lab-traffic.

Add a note that containerlab requires Linux. The lab will not run on macOS or Windows natively.

## CLAUDE.md changes

Add a note: `srl-telemetry-lab/` is a cloned external repo like `srlinux-yang-models/`. Never modify files in it.

## What NOT to do

- Do not modify anything inside srl-telemetry-lab. It is an upstream repo cloned as-is.
- Do not add srl-telemetry-lab as a git submodule. Clone it via Makefile like yang-models.
- Do not change the containerlab topology file or any lab configs.
- Do not make srl-explorer depend on the lab at import time. The lab is optional for running the agent, only needed for having devices to query.