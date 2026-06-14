---
name: auditable-incremental-problem-solving
description: Use this skill for complex data, code, document, media, or workflow cleanup tasks where a direct one-shot change is risky. It guides small reversible steps, preserving before/after artifacts, deleted data, visual comparisons, automated checks, human validation, rollback points, and reusable rules.
---

# Auditable Incremental Problem Solving

Use this skill when a problem is too risky for a single large change. The method is: move in small steps, preserve evidence, validate each step, and only then continue.

This applies broadly to data cleaning, file conversion, code migrations, document transformations, visual output repair, extraction pipelines, and rule discovery.

## Core Principle

Do not optimize for the shortest path. Optimize for recoverable progress.

Each step must answer:

1. What exact input did I start from?
2. What exact operation did I apply?
3. What data did I remove or change?
4. What output did I produce?
5. What checks prove I did not break the target behavior?
6. Can I roll back to the previous accepted state?

## When To Use

Use this workflow when:

- The input is large, noisy, or poorly understood.
- The useful content and useless content are mixed together.
- A one-shot transformation might destroy valuable data.
- The user needs reusable cleanup logic, not just one final output.
- Visual output matters and screenshots/images can catch regressions.
- Human validation is needed at key milestones.
- Future AI agents must continue the work without losing context.

## Required Artifacts

For every step, create a self-contained folder:

```text
steps/NNN_action_name/
  input_original.ext
  candidate_after.ext
  accepted_after.ext or rejected_after.ext
  removed_or_changed_data.json
  before_stats.json
  after_stats.json
  automated_check.json
  visual_check.json
  before.png
  after.png
  diff.png
  comparison.png
  report.html
```

Adapt extensions and file names to the domain. The important rule is that a future agent can inspect the step without reconstructing hidden state.

## Step Lifecycle

### 1. Baseline

Before changing anything, produce a baseline:

- Source file size, counts, schema, sections, object types, or record groups.
- Reference output if one exists.
- Current failure mode or quality problem.
- Known constraints and user validation criteria.
- Initial visual render or screenshot when applicable.

Keep this baseline immutable.

### 2. Candidate Selection

Select exactly one candidate action. Good candidates are:

- Easy to describe.
- Easy to count.
- Reversible.
- Independently testable.
- Low blast radius.

Avoid combining several speculative changes in one step.

### 3. Execute One Step

Copy the current accepted input into the step folder, apply the action, and write:

- Candidate output.
- Removed or changed data.
- Before/after stats.
- Report explaining the change.

Never overwrite the previous accepted output.

### 4. Automated Validation

Use checks appropriate to the domain:

- Parser/load check.
- Schema validation.
- Count invariants.
- Semantic invariants.
- Unit or regression tests.
- File size or performance improvement.
- Pixel/image diff.
- Round-trip read/write check.

Checks should be specific. Prefer “protected geometry count unchanged” or “record IDs preserved” over vague “looks OK”.

### 5. Visual Validation

If users judge the result visually, generate images:

- `before.png`
- `after.png`
- `diff.png`
- `comparison.png`

Use stable viewport/crop/alignment. If before and after are comparable, render with the same coordinate frame or viewport. If they are not comparable, record why.

Visual AI can help inspect images, but do not claim AI validation unless a real model is called. A dry-run placeholder is not validation.

### 6. Human Validation

Use human validation for high-risk milestones:

- Opening a transformed file in the real target application.
- Checking that visual content is acceptable.
- Confirming a candidate rule does not remove useful data.
- Approving a new reusable rule.

Record who/what validated it, when, and what artifact was validated.

### 7. Accept or Reject

Accept the step only when validation passes. On accept:

- Copy `candidate_after` to `accepted_after`.
- Update current pointer.
- Record rollback point.
- Add rule to accepted rules.

Reject when:

- No useful change occurred.
- Checks failed.
- Visual output changed unexpectedly.
- Human validation failed.
- The candidate relied on a known-bad strategy.

On reject:

- Keep the rejected artifact for diagnosis.
- Do not advance current pointer.
- Add rule to rejected rules.

## Iteration Strategy

Work from low-risk to high-risk:

1. Remove clearly unused or invisible data.
2. Remove duplicate or unreachable data.
3. Remove metadata with no semantic effect.
4. Remove auxiliary or construction data.
5. Re-run earlier analyses because new unused data may appear.
6. Stop before deleting data whose purpose is unclear.

The key insight: cleanup is often iterative. Removing one class of noise can reveal the next class of removable data.

## Rollback Model

Maintain a manifest:

```json
{
  "current_step": 12,
  "current_artifact": "steps/012_action/accepted_after.ext",
  "steps": [],
  "accepted_rules": [],
  "rejected_rules": [],
  "rollback_points": []
}
```

Rollback must be mechanical:

- Pick an accepted step.
- Copy its `accepted_after` to current.
- Continue from there.

Never require memory of the conversation to recover state.

## Report Requirements

Each HTML or Markdown report should include:

- Step name and status.
- Input and output paths.
- File size or key metric delta.
- Removed/changed data summary.
- Automated checks and pass/fail.
- Visual images or links.
- Human validation state.
- Rollback target.

Reports are not just user-facing. They are memory for the next AI agent.

## Reusable Rule Discovery

After a step passes, write the rule in a reusable form:

- Condition: when this rule applies.
- Action: exactly what to remove or transform.
- Protection checks: what must remain unchanged.
- Evidence: examples and reports.
- Risk level.
- Rollback strategy.

Do not generalize a rule from one sample without stating that it is sample-proven only.

## Stop Criteria

Stop when one of these is true:

- The user’s target quality is reached.
- Further changes provide small benefit but high risk.
- Remaining data has unclear semantic purpose.
- Human validation passes the current accepted artifact.
- A rejected step shows that the next compression/refactor path is unsafe.

Stopping is a valid engineering decision when the next step would trade reliability for marginal improvement.

## Anti-Patterns

Avoid:

- One huge cleanup with no intermediate outputs.
- Deleting data without preserving what was deleted.
- Trusting a visual thumbnail with bad crop/alignment.
- Calling a dry-run “AI validation”.
- Continuing after human validation has identified a broken candidate.
- Reusing a rejected strategy because it produced a smaller file.
- Making future agents depend on conversation memory instead of artifacts.

## Human/AI Collaboration Pattern

Use the AI for:

- Finding differences.
- Proposing small candidates.
- Running scripts.
- Generating reports.
- Comparing images.
- Maintaining manifests.
- Summarizing rules.

Use the human for:

- Validating domain-specific correctness.
- Opening outputs in proprietary or target applications.
- Approving high-risk deletions.
- Deciding stop points when tradeoffs are qualitative.

## Example Adaptations

Data files:

- Preserve original records.
- Save removed records.
- Validate schema and counts.
- Compare aggregate metrics.

Images or rendered documents:

- Preserve source.
- Export before/after images.
- Compare pixels or layout boxes.
- Ask human to verify visual quality.

Code migrations:

- Change one subsystem.
- Save test output.
- Run unit/integration tests.
- Keep rejected attempts as notes or commits only if useful.

Extraction pipelines:

- Preserve raw input and extracted output.
- Compare against reference labels.
- Add one rule at a time.
- Track precision/recall or issue counts.

## Minimal Command Pattern

When building a tool for this workflow, support commands like:

```text
run-one-step
mark-step-accepted
mark-step-rejected
rollback-to-step
write-audit-report
render-step-images
```

The exact implementation depends on the project. The workflow does not.
