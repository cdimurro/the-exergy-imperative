# Security policy

## Supported versions

Security fixes are applied to the latest released version. Upgrade before
reporting an issue that may already have been corrected.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's
private vulnerability reporting for this repository. Include the affected
version, a minimal reproduction, impact, and any suggested mitigation.

The maintainers will acknowledge a report as soon as practical, assess its
severity, coordinate a fix and disclosure, and credit reporters who want to be
named. Do not include confidential industrial data in a report.

## Data safety

Local dataset adapters read files from paths the user explicitly supplies. They
do not upload source files. Treat generated reports as potentially sensitive:
they can contain user-entered process, environmental, and economic information.
