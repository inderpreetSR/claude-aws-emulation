# MLOps track

SageMaker training-job, model and endpoint APIs, and a Step Functions refresh pipeline with an AUC quality gate. No containers run, so nothing is trained or served.

Start the emulator, then from the repository root:

```bash
jupyter lab labs/mlops/lab.ipynb
```

The notebook builds its own data, ends with exercises, and its saved outputs come from a tested run. Browse what it creates with `python dashboard/server.py`.
