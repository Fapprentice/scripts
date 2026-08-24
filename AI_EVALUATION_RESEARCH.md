# AI quality evaluation for Task Verge

## Executive recommendation

Task Verge should evaluate the **alignment and evidence at every handoff**, not assign one opaque score to the final answer. The smallest robust design is a versioned local eval corpus plus a deterministic-first runner:

1. represent each case as `goal -> success criteria -> tasks -> materials -> answer key/rubric -> submitted evidence -> acceptance decision`;
2. run schema, traceability, contradiction, file, code, and invariant checks first;
3. use a rubric-bound LLM judge only where meaning cannot be checked deterministically;
4. retain the complete run record (inputs, outputs, model/prompt versions, component scores, reasons, cost/latency);
5. calibrate judge scores and release thresholds against a small, double-reviewed human set.

Use Task Verge's existing Python tests and acceptance bench as the initial runner. Borrow Inspect AI's data/solver/scorer/log separation rather than adding a framework immediately. Add Inspect AI only when repeated runs, multiple models, sandboxed agent tasks, or richer log analysis justify it. Do not build around the hosted OpenAI Evals platform: OpenAI says it becomes read-only on 31 October 2026 and shuts down on 30 November 2026, while its open-source Evals repository remains useful as a design case ([OpenAI Evals guide](https://developers.openai.com/api/docs/guides/evals), [OpenAI Evals repository](https://github.com/openai/evals)).

## 1. Design foundation: claims, evidence, and alignment

Evidence-centered design (ECD) starts from the inference an assessment is meant to support and works backward to the observations that would warrant it. Its core layers are a **student/competency model** (what capability is claimed), **evidence model** (what observable work supports the claim), and **task model** (what situation elicits that evidence). The associated four-process architecture separates activity selection, presentation, response processing, and summary scoring ([Mislevy, Steinberg, Almond et al., 2001](https://www.ets.org/research/policy_research_reports/publications/report/2001/cmjw.html); [Almond, Steinberg & Mislevy, 2002](https://ejournals.bc.edu/index.php/jtla/article/view/1671)).

Constructive alignment makes the complementary instructional-design point: intended outcomes should be stated as performances, learning activities should elicit those performances, and assessment should test the same performances ([Biggs, 1996](https://doi.org/10.1007/BF00138871)).

For Task Verge, these ideas map directly:

| Assessment concept | Task Verge artifact | Required question |
|---|---|---|
| Intended construct/outcome | Goal, final outcome, success criteria | What real-world change or capability is being claimed? |
| Task model | Task instruction and constraints | Will doing this task elicit evidence for that claim? |
| Presentation/input | Task materials | Are all inputs present, usable, and appropriate? |
| Response/evidence | Page answer, files, links, process evidence | Is the evidence authentic, sufficient, and inspectable? |
| Evidence model | Answer key, rubric, acceptance criteria | What observations distinguish pass from fail? |
| Summary decision | Acceptance result and review | Does the evidence warrant the decision, with uncertainty exposed? |

The practical consequence is important: a polished answer cannot rescue a task unrelated to the goal, and a good task cannot be fairly rejected by an answer key that tests something else. Evaluation must therefore include **vertical alignment** across the chain and **local quality** at each node.

## 2. What mature eval systems contribute

### OpenAI Evals

The open-source project models an eval as a dataset plus an eval class/template, gives evals explicit split/version names, and says runs under the same eval name should produce similar results; changing an eval should bump its version ([building an OpenAI eval](https://github.com/openai/evals/blob/main/docs/build-eval.md)). It supports exact/match-style and model-graded patterns and private task-specific datasets ([repository README](https://github.com/openai/evals)).

Useful for Task Verge: versioned cases, reusable graders, comparable runs, and regression testing. Avoid copying its registry machinery wholesale; Task Verge already has a local bench and pytest.

### UK AISI Inspect AI

Inspect's composable unit is dataset + solver/agent + scorer, with tools, sandboxes, model providers, retries/limits, and structured logs ([Inspect overview](https://inspect.aisi.org.uk/)). Scorers can extract answers, compare text, invoke a judge model, or apply arbitrary executable validation. Metrics aggregate per-sample scores and commonly report accuracy/mean with standard error ([Inspect scorers](https://inspect.aisi.org.uk/scorers.html), [scoring metrics](https://inspect.aisi.org.uk/metrics.html)). Logs preserve samples, transcripts, scores, metadata, and can be re-scored without rerunning generation ([Inspect log files](https://inspect.aisi.org.uk/eval-logs.html), [scoring workflow](https://inspect.aisi.org.uk/scoring.html)).

This is the best architectural reference for Task Verge because it keeps generation, evidence, scoring, and aggregation separable. It is also the sensible later dependency if Task Verge needs sandboxed execution or multi-model experiments.

### promptfoo

promptfoo expresses a matrix of prompts, providers, test cases, and assertions in YAML. Assertions include deterministic checks, custom code, semantic similarity, and LLM rubrics; cases can carry metadata and thresholds ([configuration guide](https://github.com/promptfoo/promptfoo/blob/main/site/docs/configuration/guide.md), [configuration reference](https://github.com/promptfoo/promptfoo/blob/main/site/docs/configuration/reference.md)). Its CLI has machine-readable outputs and a failing exit code suitable for CI ([CLI reference](https://github.com/promptfoo/promptfoo/blob/main/site/docs/usage/command-line.md), [output formats](https://github.com/promptfoo/promptfoo/blob/main/site/docs/configuration/outputs.md)).

It is a good lightweight prompt/model comparison tool, but not a sandbox: its own security policy says local custom assertions, scripts, hooks, providers, and transforms may execute with the user's permissions ([promptfoo security model](https://github.com/promptfoo/promptfoo/blob/main/SECURITY.md)). For Task Verge, use it only if YAML authoring and provider matrices become more valuable than keeping the current Python test path.

### Ragas and DeepEval

Ragas provides useful names for retrieval/generation failure modes: context precision/recall, response relevancy, faithfulness, factual correctness, and agent goal/tool-call accuracy ([official metrics catalog](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/)). Its faithfulness metric explicitly decomposes an answer into claims and scores the proportion supported by retrieved context ([official faithfulness definition](https://github.com/vibrantlabsai/ragas/blob/main/docs/concepts/metrics/available_metrics/faithfulness.md)); the original RAGAS paper frames these as reference-free metrics for retrieval focus, grounding, and generation quality ([Es et al., 2023](https://arxiv.org/abs/2309.15217)).

DeepEval supplies ready-made answer relevancy and other LLM metrics and a pytest-like usage model ([official metric documentation](https://deepeval.com/docs/metrics-introduction)). Neither dependency is necessary initially: Task Verge's chain is broader than RAG, while its domain rubrics and executable acceptance checks should remain first-class. Reuse the metric concepts, not another abstraction layer.

## 3. Metric system for the full chain

Store every component result separately. A weighted grand score is useful for dashboards but unsafe as the release gate because averages can hide a broken handoff. Gate on critical invariants first, then report distributions and slices.

### Goal quality

- **Outcome observability:** proportion of goals with a concrete final outcome that can produce inspectable evidence.
- **Criterion verifiability:** verifiable success criteria / all success criteria. A criterion is verifiable only if its observable, threshold, and evidence source are identifiable.
- **Constraint completeness:** required known dimensions captured (deadline, time/capacity, tools/environment, budget where applicable); report missing fields rather than inventing them.
- **Non-contradiction:** zero incompatible statements among outcome, criteria, and constraints. Contradictions are a hard fail until clarified.

### Goal -> task alignment

- **Criterion coverage (recall):** success criteria addressed by at least one task / all success criteria.
- **Task relevance (precision):** tasks that contribute to at least one success criterion / all tasks.
- **Traceability completeness:** task-to-criterion links present / expected links. Require explicit IDs, not inferred prose, in the canonical eval record.
- **Actionability:** tasks with a specific action, deliverable, estimate, and acceptance rule / all tasks.
- **Dependency/order validity:** prerequisite violations and cycles; both are deterministic hard failures.
- **Budget feasibility:** total planned duration against available capacity, plus per-task limit violations.

### Task -> materials alignment

- **Material sufficiency:** material-dependent tasks with every required input attached / all material-dependent tasks.
- **Material relevance:** relevant material units / supplied units (the analogue of context precision).
- **Information coverage:** required facts/items represented in materials / facts/items needed by the answer key (the analogue of context recall).
- **Integrity/usability:** referenced files exist, decode, have allowed types/sizes, and can be opened; executable content runs only in a sandbox.
- **Leakage:** materials revealing the answer or hidden acceptance rule when that would invalidate the learning task.

### Materials -> answer key/rubric alignment

- **Support/grounding:** answer-key claims supported by materials / all answer-key claims. This adapts Ragas faithfulness.
- **Key completeness:** required material concepts represented by the key/rubric / all required concepts.
- **Rubric observability:** rubric dimensions tied to observable evidence rather than style impressions.
- **Scorability:** independent graders can apply the rubric without extra assumptions; measure agreement on a calibration set.
- **No impossible requirements:** every acceptance condition is achievable from the supplied task, materials, tools, and constraints.

### Answer/evidence -> acceptance

- **Deterministic compliance:** required evidence exists; formats parse; schemas validate; code compiles/tests; explicit values and counts meet thresholds.
- **Answer correctness:** criterion-level score against the key. Use exact/executable checks when possible; semantic rubric scoring only for open-ended work.
- **Evidence faithfulness:** submitted claims supported by cited material or artifacts / all checkable claims.
- **Acceptance precision:** human-confirmed passes / system passes. This protects against false acceptance.
- **Acceptance recall:** system passes / human-confirmed passes. This protects against unfair rejection.
- **False-pass rate:** failed human cases accepted / all failed human cases. Treat this as the primary safety gate.
- **Coverage/deferral:** automatically decided cases / all cases, with an explicit `needs_review` outcome instead of forcing uncertain cases into pass/fail.

### End-to-end consistency and robustness

- **Chain integrity:** percentage of cases passing every required handoff. Also show the first failing stage; this is more diagnostic than an average.
- **Repeat stability:** rerun each stochastic case `k` times and report per-criterion pass rate, task-set overlap, and acceptance flip rate. For task sets, use Jaccard overlap on normalized criterion IDs rather than wording.
- **Perturbation robustness:** score change under meaning-preserving rewrites, item order changes, irrelevant material insertion, and equivalent file names/formats.
- **Slice performance:** all metrics by goal type, language, material type, task difficulty, model, and acceptance path. Overall means can hide weak slices.
- **Operational metrics:** latency, token/call count, judge cost, execution errors, and deferral rate.

For every aggregate, include sample count and uncertainty. Inspect provides mean/accuracy and standard-error aggregation as a practical precedent ([Inspect metrics](https://inspect.aisi.org.uk/metrics.html)). Do not set universal numeric thresholds before collecting Task Verge baseline and human labels.

## 4. Judge design and validation

Use the following scoring order:

1. hard invariants and executable checks;
2. structured comparisons (IDs, sets, counts, schemas);
3. narrow criterion-level LLM rubrics;
4. human review for disagreement, low confidence, high-impact goals, or sampled audits.

An LLM judge should receive the exact criterion, relevant materials, candidate evidence, and a small ordinal rubric with anchored descriptions. It should return structured fields: criterion ID, score, pass/fail, cited evidence, reason, and uncertainty. Never ask for a single holistic "quality" score.

LLM judges are useful but not ground truth. G-Eval found better correlation with human judgments from criteria-driven, form-filled LLM scoring, while also flagging possible bias toward LLM-generated text ([Liu et al., 2023](https://aclanthology.org/2023.emnlp-main.153/)). MT-Bench found strong-judge agreement with human preferences but documented position, verbosity, self-enhancement, and reasoning biases ([Zheng et al., 2023](https://proceedings.neurips.cc/paper_files/paper/2023/file/91f18a1287b398d378ef22505bf41832-Paper-Datasets_and_Benchmarks.pdf)). Mitigations for Task Verge:

- score criteria independently and blind model/provider identity;
- randomize pair order for comparisons and repeat swapped order;
- do not reward length unless completeness requires it;
- pin judge model, prompt, rubric, and decoding settings in the run record;
- calibrate against double-reviewed human labels and track agreement, acceptance precision/recall, and confusion matrices;
- route judge/human disagreement into the regression corpus;
- keep a held-out release set separate from examples used to tune prompts or rubrics.

## 5. Recommended local architecture

```text
Versioned EvalCase JSON
  -> generator adapter (current Task Verge path)
  -> immutable ArtifactBundle for every stage
  -> deterministic scorers
  -> optional rubric judge
  -> decision policy: pass | fail | needs_review
  -> JSONL EvalRun + compact Markdown/console report
```

Minimal records:

- `EvalCase`: stable ID, slice tags, goal/constraints, expected invariants, reference links, and optional human label.
- `ArtifactBundle`: generated goal details, tasks, materials, key/rubric, answer/evidence, acceptance result, plus prompt/model/config versions.
- `ComponentScore`: stage, criterion ID, scorer version, value, pass, reason, and evidence pointers.
- `EvalRun`: timestamp, code revision, environment, all component scores, latency/cost/errors, and aggregate metrics.

Keep scorers pure where possible so saved artifacts can be re-scored without another model call, following Inspect's re-scoring pattern. Preserve raw outputs and component reasons; aggregate reports are derived data. The existing no-evidence, missing-file, syntax, execution, and multi-file cases should remain deterministic acceptance tests, but add cases that expose alignment failures and false passes.

## 6. Phased rollout

### Phase 0 — define the contract (1–2 days)

- Freeze canonical IDs for goals, criteria, tasks, materials, rubric items, and evidence.
- Add 15–25 hand-authored cases covering happy paths and known failures across the complete chain.
- Label hard invariants; do not add LLM scoring yet.
- Baseline current behavior and preserve every artifact.

Exit: every acceptance decision can be traced to criterion IDs and evidence, and the suite runs locally in one command.

### Phase 1 — deterministic regression gate

- Implement stage scorers for schema, completeness, traceability, contradictions, files, code/tests, budgets, and dependency order.
- Report first-failing stage, false-pass rate, slice metrics, latency, and errors.
- Gate changes on zero critical invariant regressions; use baseline-relative gates for noncritical metrics.

Exit: seeded defects fail for the intended reason and deterministic reruns are identical.

### Phase 2 — calibrated semantic scoring

- Add narrow rubric judges only for goal/task relevance, material/key support, and open-ended answer quality.
- Build a double-reviewed human calibration set; adjudicate disagreements.
- Measure confusion matrices and judge-human agreement by slice; introduce `needs_review` for uncertain cases.
- Add order-swap and paraphrase robustness tests.

Exit: predeclared acceptance precision/false-pass targets are met on a held-out set, with no materially weak slice hidden by the average.

### Phase 3 — production sampling and learning loop

- Sample privacy-safe production traces locally, prioritize failures/disagreements, redact secrets, and require consent for retained user content.
- Convert confirmed incidents into versioned regression cases.
- Compare candidate vs baseline with identical cases and configs; report deltas with uncertainty.
- Add Inspect AI only if multi-model/epoch runs, sandboxing, or log analysis now saves more code than it adds.

Exit: releases are blocked by reproducible regressions, and production failures continuously improve the held-out corpus without contaminating it.

## 7. Immediate Task Verge test additions

The highest-value next cases are:

1. a task that is well formed but covers no success criterion;
2. one success criterion omitted by all tasks;
3. a material-dependent task with plausible but incomplete materials;
4. an answer key containing a claim absent from the materials;
5. evidence that exists and compiles but does not satisfy the acceptance behavior;
6. contradictory goal constraints;
7. the same semantic goal paraphrased and reordered, checked for stable criterion coverage and acceptance;
8. an ambiguous semantic case that must return `needs_review`, not pass.

These cases test the actual product risk: internal consistency and false acceptance, not merely whether an LLM can produce fluent task text.
