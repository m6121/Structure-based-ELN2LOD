# Structure-based Approach to Transfer ELN Protocols into RO-Crates

This repository contains the source code of a structure-based approach to transfer Electronic Lab Notebook (ELN) protocols including research data into a [Research Object Crates (RO-Crates)](https://w3id.org/ro/crate/1.1) bundle whereas the semantic model rerpresents retrospective provenance about the research data.

**Note that this software is a research prototype and may contain bugs and errors, i.e., do not use this in production.**

The approach has been used in order to create the RO-Crates at: https://github.com/SFB-ELAINE/Ca-imaging-RO-Crate

The approach is described in full detail in this article:

Max Schröder, Susanne Staehlke, Paul Groth, J. Barbara Nebe, Sascha Spors, Frank Krüger.<br>
**Structure-based knowledge acquisition from electronic lab notebooks for research data provenance documentation.**<br>
Journal of Biomedical Semantics 13, 4 (2022).<br>
https://doi.org/10.1186/s13326-021-00257-x

## License

[![Creative Commons License](https://i.creativecommons.org/l/by/4.0/88x31.png)](http://creativecommons.org/licenses/by/4.0/)

This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/).

In order to reference this software, please consider the information in the [CITATION.cff](CITATION.cff) file.

## Usage

In order to run the source code, install the python dependencies from `requirements.txt` and make sure that [Docker](https://www.docker.com/) is installed and running.

A minimum running example is as follows:

```python3
model = ELN2Crate(LOGGER, NAMESPACE_URL, ELABFTW_URL, ELABFTW_MANAGER, EXP_ID, PSEUDONYMIZE_PERSONS)

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