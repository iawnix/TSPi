---
name: ts-backend-ase
description: Private ASE execution guidance for the isolated TS backend operator.
---

# ASE Backend

- Treat images, calculator settings, endpoints, constraints, and expected artifacts as immutable task inputs.
- Use only the bound typed operation; do not invent Python snippets or alter the calculator.
- Return trajectory and optimizer facts without promoting an image to a validated transition state.
- Keep endpoint mapping and connectivity conclusions outside the backend result.
- Local collected artifacts are authoritative; remote state is only an execution mirror.
