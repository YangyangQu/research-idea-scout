# Research Idea Scout

**Research Idea Scout** is a configurable toolkit for screening large paper collections and identifying cross-domain ideas that may transfer to **your own research direction**.

It is **not** a toolkit for one fixed topic. The intended workflow is:

```text
Define your research profile
→ filter a large paper pool with lightweight rules
→ ask Codex to infer each paper's core idea
→ score whether the idea transfers to your own task
→ export ranked lists for manual reading
```

The key design principle is: **reward transferable mechanisms, not keyword overlap**.

For example, a researcher working on speech privacy may look for ideas about latent editing, concept erasure, or temporal style transfer. A researcher working on visual domain generalization may look for ideas about invariant representations, style/content disentanglement, or test-time adaptation. The same code supports both by changing a YAML profile.

---

## What this tool does

Given a JSONL file of papers, each with at least `title` and `abstract`, this toolkit can:

1. Apply a lightweight rule-based filter using a user-defined profile.
2. Ask Codex to infer each paper's **core idea** from title and abstract.
3. Ask Codex to judge whether that idea can transfer to the user's research tasks.
4. Produce compact scores, short explanations, and rankings.
5. Resume automatically if interrupted.
6. Wait on quota/rate-limit errors and stop cleanly on authentication errors.
7. Export top-ranked papers to CSV for reading or browsing.

It does **not** require the research direction to be speech, privacy, fairness, or accent conversion. Those are only example profiles.

---

## Repository structure

```text
research-idea-scout/
├── README.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── configs/
│   ├── profile_template.yaml
│   ├── profile_speechprivacy_accent_example.yaml
│   └── profile_cv_domain_adaptation_example.yaml
├── examples/
│   └── example_input.jsonl
├── scripts/
│   ├── filter_candidates.py
│   ├── score_with_codex.py
│   ├── run_autoretry.py
│   ├── export_rankings.py
│   ├── prepare_portal_ready.py
│   └── check_progress.py
└── idea_scout/
    ├── io_utils.py
    ├── profile.py
    ├── filter_candidates.py
    ├── codex_idea_score.py
    ├── run_autoretry.py
    ├── export_rankings.py
    ├── prepare_portal_ready.py
    └── check_progress.py
```

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/research-idea-scout.git
cd research-idea-scout

python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

You also need the Codex CLI available on your system if you want LLM-based scoring:

```bash
codex login --device-auth
printf 'Reply only OK\n' | codex exec -
```

If the test returns `OK`, Codex is ready.

---

## Input format

The input should be a JSONL file. Each line is one paper:

```json
{"title":"Paper title","abstract":"Paper abstract","venue":"ICLR","year":2026,"url":"https://..."}
```

Required fields:

- `title`
- `abstract`

Recommended fields:

- `venue`
- `year`
- `url` or `pdf_url`
- `paper_id` or `doi`, if available

Example:

```bash
head examples/example_input.jsonl
```

---

## Step 1: Write your own research profile

Copy the template:

```bash
cp configs/profile_template.yaml configs/my_profile.yaml
```

Then edit:

```yaml
name: my_research_profile

description: >
  Describe your research direction here.

target_tasks:
  - What task are you working on?
  - What kind of ideas are you looking for?
  - What would count as useful transfer?

prefer:
  - Transferable mechanisms rather than surface topic similarity.
  - Reusable representation, objective, architecture, editing, evaluation, or theory ideas.

downweight:
  - Generic benchmark/dataset/survey papers without a reusable mechanism.

positive_keywords:
  - representation learning
  - latent space
  - controllable generation
  - adapter
  - subspace
  - editing

negative_keywords:
  - survey
  - benchmark
  - dataset

scoring_dimensions:
  - key: transferability_to_my_task
    description: Whether the paper's core idea can be adapted to my research task.
    weight: 2.0
  - key: method_novelty
    description: Whether the paper has a genuinely interesting method or theory idea.
    weight: 1.2
```

The most important part is `scoring_dimensions`. These become the fields that Codex scores.

---

## Step 2: Optional rule-based filtering

If your paper pool is very large, first run a cheap filter:

```bash
python scripts/filter_candidates.py \
  --input examples/example_input.jsonl \
  --profile configs/my_profile.yaml \
  --output-keep data/candidates.jsonl \
  --output-reject data/rejected.jsonl \
  --output-summary reports/filter_summary.json \
  --target-total 2000 \
  --min-score 1.0
```

If you already have a curated candidate list, you can skip this step.

---

## Step 3: Test Codex scoring on one paper

Always test one paper before running thousands:

```bash
python -u scripts/score_with_codex.py \
  --input examples/example_input.jsonl \
  --profile configs/my_profile.yaml \
  --output data/test_score.jsonl \
  --failures-output data/test_failures.jsonl \
  --top-k 1 \
  --codex-cmd "codex exec" \
  --max-new-items 1 \
  --timeout 900 \
  --abstract-max-chars 3000
```

A successful run prints something like:

```text
[RUN ] 1/1 ...
[OK  ] added=1 rank=... overall=... priority=keep
[DONE] added=1 output=data/test_score.jsonl
```

---

## Step 4: Run resumable scoring

For a larger run:

```bash
nohup python -u scripts/run_autoretry.py \
  --input data/candidates.jsonl \
  --profile configs/my_profile.yaml \
  --output data/idea_scores.jsonl \
  --failures-output data/idea_score_failures.jsonl \
  --top-k 2000 \
  --codex-cmd "codex exec" \
  --batch-size 1 \
  --sleep-between-rounds 2 \
  --sleep-on-quota 3600 \
  --sleep-on-error 600 \
  --timeout 900 \
  --abstract-max-chars 3000 \
  > logs/run_idea_scores_$(date +%F-%H%M%S).out 2>&1 &
```

The runner writes one JSON object per completed paper. If the run stops, simply rerun the same command. It will skip papers that are already present in the output file.

---

## Step 5: Monitor progress

```bash
python scripts/check_progress.py \
  --output data/idea_scores.jsonl \
  --target-total 2000
```

Or inspect the latest log:

```bash
tail -f logs/run_idea_scores_*.out
```

Normal messages:

```text
[RUN ] ...
[OK  ] added=1 rank=... overall=... priority=...
[ROUND RESULT] newly_added=1 total_done=...
```

Quota/rate-limit waiting is also normal:

```text
[SLEEP_QUOTA] sleeping 3600s
```

Authentication errors require manual login:

```text
[STOP_AUTH] Codex auth/session problem.
```

Fix with:

```bash
codex logout || true
codex login --device-auth
printf 'Reply only OK\n' | codex exec -
```

Then rerun the same scoring command.

---

## Step 6: Export ranked papers

Export top 100 by the default ranking score:

```bash
python scripts/export_rankings.py \
  --input data/idea_scores.jsonl \
  --profile configs/my_profile.yaml \
  --output data/top100_overall.csv \
  --top-k 100
```

Sort by specific dimensions from your profile:

```bash
python scripts/export_rankings.py \
  --input data/idea_scores.jsonl \
  --profile configs/my_profile.yaml \
  --output data/top100_transferability.csv \
  --top-k 100 \
  --sort-by score_transferability_to_my_task score_overall_fit score_theory_novelty
```

The exported CSV includes:

- title
- venue/year
- URL
- priority
- overall fit score
- profile-specific dimension scores
- core idea
- transferable mechanism
- fit reason
- risk or limitation

---

## Output fields

Each scored paper contains fields like:

```json
{
  "is_suitable": true,
  "priority": "keep",
  "idea_core": "The paper discovers editable representation subspaces.",
  "transferable_mechanism": "Subspace intervention can be reused for controlled representation editing.",
  "fit_reason": "The mechanism aligns with the profile's need for controllable latent interventions.",
  "risk_or_limitation": "The abstract does not show whether edits preserve all required constraints.",
  "score_overall_fit": 8,
  "score_theory_novelty": 7,
  "scores": {
    "transferability_to_my_task": 8,
    "method_novelty": 7
  },
  "rank_score": 7.75
}
```

Dimension scores are also flattened as:

```text
score_transferability_to_my_task
score_method_novelty
...
```

---

## How to adapt it to your own field

You only need to change the YAML profile.

For example, if your research is medical imaging, define dimensions such as:

```yaml
scoring_dimensions:
  - key: segmentation_transfer_value
    description: Whether the idea can improve robust medical image segmentation.
    weight: 2.0
  - key: annotation_efficiency
    description: Whether the idea reduces annotation requirements.
    weight: 1.5
  - key: clinical_evaluation_value
    description: Whether the idea suggests useful clinical evaluation metrics.
    weight: 1.0
```

If your research is recommender systems, define dimensions such as:

```yaml
scoring_dimensions:
  - key: user_preference_modeling
    description: Whether the idea helps model user preferences or intent.
    weight: 2.0
  - key: cold_start_or_retrieval_value
    description: Whether the idea helps retrieval, cold-start, or candidate generation.
    weight: 1.5
  - key: online_evaluation_value
    description: Whether it suggests better online or counterfactual evaluation.
    weight: 1.0
```

The toolkit remains the same.

---

## Notes and limitations

- The scorer uses title and abstract by default, not the full PDF.
- The output is a triage signal, not a final literature review.
- Scores are meant for ranking and prioritization.
- Always manually inspect high-ranked papers.
- If you need full-paper analysis, add a paper-fetching stage and pass extracted method sections into the prompt.

---

## Citation / acknowledgement

If you use this toolkit, please cite or acknowledge the repository URL once published.

