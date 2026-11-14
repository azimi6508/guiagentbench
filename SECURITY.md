# Security model

Evaluated agents and generated programs are untrusted. The trusted host controller provisions isolated containers and materializes workspaces from positive file allowlists. Private task data belongs only to the trusted controller and verifier. See [architecture](docs/architecture.md) for process, filesystem, tool and network boundaries.

Run the viewer on its default loopback interface. Keep provider credentials outside task packages and generated evidence. Give a runner a dedicated credential source; do not use a personal Android device or emulator.

For a suspected boundary violation, stop the affected evaluation, retain its evidence locally and report the issue privately through GitHub's private vulnerability reporting for this repository, or by e-mail to the corresponding author (yusaf.azimi@sabanciuniv.edu). Include a minimal reproduction with credentials and personal data removed.
