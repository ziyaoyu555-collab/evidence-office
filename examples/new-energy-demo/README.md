# Synthetic new-energy evidence demo

This example resembles an engineering result table but every value is synthetic and invented for testing. It is not a MATLAB, Simulink, vehicle, or field-test result.

Run it from the project root:

```bash
evidence-office build \
  examples/new-energy-demo/manifest.json \
  --out /tmp/evidence-office-new-energy-report

evidence-office audit \
  examples/new-energy-demo/manifest.json \
  --package /tmp/evidence-office-new-energy-report
```

Both commands should be `passed_with_warnings`: the verified claim has a real
CSV anchor, while the assumption and its review note stay visible. If the
manifest or CSV changes after the build, `audit` returns exit code `1` until the
package is rebuilt.
