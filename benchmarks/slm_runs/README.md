# Actual SLM before/after runs

Use the same benchmark request, document type, model, and project settings for
both runs. Change only the code or prompt version being evaluated.

1. Generate each case in DocuGen.
2. Export the project into `before` or `after`:

```bat
scripts\export-slm-candidate.bat --project-id PROJECT_ID --case-id CASE_ID --output-dir data\slm-eval\before --run-label before --commit OLD_COMMIT
```

3. Repeat after the change, using `data\slm-eval\after`.
4. Build the automatic comparison and blinded human form:

```bat
scripts\compare-slm-runs.bat --before-dir data\slm-eval\before --after-dir data\slm-eval\after --output-dir data\slm-eval\report
```

Give only `human_evaluation.json` to the evaluator. Keep `blind_key.json`
hidden until scoring is complete. The evaluator assigns 1-5 scores for task
fulfillment, structure, coherence, genre fit, readability, and factual support,
then chooses A, B, or tie and records a short rationale and critical issues.

After filling the evaluation file, aggregate it without changing the blind key:

```bat
scripts\compare-slm-runs.bat --before-dir data\slm-eval\before --after-dir data\slm-eval\after --output-dir data\slm-eval\report --human-results data\slm-eval\report\human_evaluation.json
```

Generated run files and reports belong under `data/` and should not be committed.
