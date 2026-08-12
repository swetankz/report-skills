# Fresh-context prompts

Run each case from `evals.json` in a fresh context with only the named skill and synthetic fixture available. Do not include the expected result, suspected defect, or intended correction in the prompt.

Save the output, artifacts, tool trace, exact skill version, and environment. Score against `rubric.md`, revise canonical source when necessary, regenerate packages, and rerun from a clean context.

