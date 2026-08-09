# Synthetic new-energy evidence demo

This example resembles an engineering result table but every value is synthetic and invented for testing. It is not a MATLAB, Simulink, vehicle, or field-test result.

Run it from the project root:

```bash
PYTHONPATH=src python3 -m evidence_office build \
  examples/new-energy-demo/manifest.json \
  --out /tmp/evidence-office-new-energy-report
```

The generated report should be `passed_with_warnings`: the verified claim has a real CSV anchor, while the assumption is kept visible as a warning.

