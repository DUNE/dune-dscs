# dune-dscs

The dune-dscs repository is the top-level repository for the Detector Slow Controls System.
Initially, it will contain code for bridges and emulators, but these may be refactored into other repositories in the future.
The DSCS code wiki will be hosted at this repository, and the DUNE wiki will be used for internal information.

## Setup

To make the python virtual environment consistent, we recommend using [uv](https://docs.astral.sh/uv/). To install uv without root on Linux or MacOS:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing uv, you may need to open a new shell to use it. Test with `uv --version`.

### With uv (recommended)

```bash
git clone https://github.com/DUNE/dune-dscs.git && cd dune-dscs
uv sync                                              # creates .venv
uv run python Tutorials/workshop2026/zmq_emulator.py # Or whatever script you want
```

### Without uv

Before running the following commands, check your python version with `python --version`. If you don't have python 3.10 or greater, install it. If you can't install it, use the uv instructions above (uv will automatically install a suitable python version). 

```bash
git clone https://github.com/DUNE/dune-dscs.git && cd dune-dscs
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python Tutorials/workshop2026/zmq_emulator.py # Or whatever script you want
```

### Updating dependencies (maintainers)

```bash
uv add <package>                  # updates pyproject.toml and uv.lock
uv export --frozen --no-hashes --no-dev --no-emit-project -o requirements.txt
# commit pyproject.toml, uv.lock and requirements.txt together
```

## Coding Style 

Python code should follow PEP 8 conventions.

https://peps.python.org/pep-0008/

Pull requests are automatically checked with PyLint using the repository's `.pylintrc` configuration.

## Copyright and Licensing
Copyright © 2026 FERMI NATIONAL ACCELERATOR LABORATORY for the benefit of the DUNE Collaboration.

This repository, and all software contained within, is licensed under
the Apache License, Version 2.0 (the "License"); you may not use this
file except in compliance with the License. You may obtain a copy of
the License at

https://www.apache.org/licenses/LICENSE-2.0

Copyright is granted to FERMI NATIONAL ACCELERATOR LABORATORY on behalf
of the Deep Underground Neutrino Experiment (DUNE). Unless required by
applicable law or agreed to in writing, software distributed under the
License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for
the specific language governing permissions and limitations under the
License.
