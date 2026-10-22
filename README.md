# ELN2Crate: Structure-based Approach to Transfer ELN Protocols into RO-Crates

This repository contains the source code of a structure-based approach to transfer Electronic Lab Notebook (ELN) protocols including research data into a [Research Object Crates (RO-Crates)](https://w3id.org/ro/crate/1.1) bundle whereas the semantic model rerpresents retrospective provenance about the research data.

**Note that this software is a research prototype and may contain bugs and errors, i.e., do not use this in production.**

The approach has been used in order to create the RO-Crates at: https://github.com/m6121/Infrastructure-based-Provenance-Tracking

The approach is described in full detail in this article:
TBD

## License

This work is licensed under the [MIT License](LICENSE).

In order to reference this software, please consider the information in the [CITATION.cff](CITATION.cff) file.

## Usage

### Software Requirements

Installation of the python package is required, e.g. by installing via pip:

```bash
pip install git+https://github.com/m6121/Structure-based-ELN2LOD.git
```

Note that in order to integrate the signature-based file format output of [siegfried](https://github.com/richardlehane/siegfried), [docker](https://www.docker.com/) must be installed and must be able to be invoked by the user executing the python commands.

### Running

A minimum running example is as follows:

```python3
model = ELN2Crate(LOGGER, NAMESPACE_URL, ELABFTW_URL, ELABFTW_MANAGER, EXP_ID, PSEUDONYMIZE_PERSONS, SIEGFRIED_IMAGE)

try:
    model.write_files()
    model.create_model()
    model.write_crate('./ro-crate_%i' % (EXP_ID))
except ProtocolElementUnknown as e:
    print('Protocol element is unknown: ' + str(e), file=sys.stderr)
```

where the following variables have been set:

* `LOGGER` contains an initialized python-logger using the package `logging`
* `NAMESPACE_URL` is the base URL of the namespace of the semantic model
* `ELABFTW_URL` URL of the elabFTW instance that is used for the documentation of the experiments
* `ELABFTW_MANAGER` an initialized version of the `elabapy.Manager()` with read permissions on the experiment and the corresponding inventory items
* `EXP_ID` the experiment ID that should be bundled
* `PSEUDONYMIZE_PERSONS` is an array of strings that should be replaced by pseudonymized before bundling in order to protect privacy.
* *Optional* `SIEGFRIED_IMAGE` is a string with the docker image to be used to invoke [siegfried](https://github.com/richardlehane/siegfried) for the file format identification. In order to disable the integration of the siegfried output, use `None`. By default the following image is used: `'sfbelaine/common:siegfried_latest'` **Note: pulling the image is not enforced, i.e. if it is already present at the docker host, the local image will be used**