# Technical addendum 003 — effective idleSlope source in SCA

Reprocessing the completed, route-correct B output exposed a second result-reader issue: the pilot checked only `par` rows for `idleSlope`, but the installed OMNeT++/INET result writes these resolved CLI/INI overrides as `config` rows. The B SCA contains all 24 expected effective overrides at the exact requested rates. Gate settings are recorded as `par` rows and have already passed their direct comparison. The application validator passed and is retained in `validation.json`.

The pilot exporter is corrected to validate CBS rates from the resolved SCA `config` rows and still requires exact agreement at every profile egress/class. The existing B simulation is reprocessed again; no simulation is repeated and no model setting changes.
