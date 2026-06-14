<div align="center">

# 🧭 IdeaScout

### Profile-Guided Cross-Domain Research Idea Discovery with LLMs

<p>
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/Status-v0.1.0-orange" alt="Status">
  <img src="https://img.shields.io/badge/LLM-Codex%20CLI-purple" alt="LLM">
</p>

</div>

---

## ✨ What is IdeaScout?

**IdeaScout is a profile-guided toolkit for discovering transferable research ideas from large paper collections.**

Instead of only finding papers that already match your topic, IdeaScout helps you answer a more useful research question:

> **Can the core idea of this paper transfer to my own research problem?**

You define your own **research profile** — including your target tasks, preferred mechanisms, negative filters, and scoring criteria. IdeaScout then:

- filters a large paper collection into promising candidates,
- asks an LLM to infer each paper’s **core idea**,
- scores whether that idea is **transferable** to your research direction,
- and exports a ranked reading list for deeper study.

It is designed for researchers who want to mine ideas from **other fields**, not just their own.

---

## 🎯 Why IdeaScout?

Traditional paper search is often too narrow:

- keyword search finds papers **similar in topic**, but not necessarily **useful in mechanism**;
- reading thousands of papers manually is too slow;
- many of the best ideas come from **other domains** with different terminology.

IdeaScout is useful when you want to:

- 🔍 discover **cross-domain transferable ideas**
- 🧠 search for **mechanisms**, not just topics
- ⚙️ customize screening for **your own research profile**
- 📊 rank papers by **transferability, novelty, and feasibility**
- 🔁 run large-scale LLM scoring jobs with **resume** and **auto-retry**

---

## 🧩 At a glance

| Step | What it does |
|------|---------------|
| **1. Define a profile** | Describe your research task, preferred mechanisms, negative filters, and scoring dimensions. |
| **2. Filter candidates** | Quickly prune a large paper collection using rule-based heuristics. |
| **3. Score with an LLM** | Ask Codex to infer each paper’s idea and judge whether it transfers to your task. |
| **4. Export top papers** | Produce ranked CSV / JSONL outputs for reading, analysis, or portal integration. |

---

## 🧠 Core idea

IdeaScout separates idea discovery into **two stages**:

### 1) Rule-based candidate filtering
A fast filtering stage that keeps papers likely to contain useful transferable ideas.

It uses:
- profile keywords,
- preferred mechanisms,
- negative filters,
- and lightweight heuristic scoring.

### 2) LLM-based idea scoring
A slower but more meaningful scoring stage.

For each candidate paper, the LLM:
- reads the **title** and **abstract**,
- infers the paper’s **core idea**,
- identifies the **transferable mechanism**,
- and scores how well the idea fits **your research profile**.

---

## 🏗️ How the pipeline works

```text
Large paper collection (JSONL)
        ↓
Research profile (YAML)
        ↓
Rule-based candidate filtering
        ↓
Candidate papers
        ↓
LLM idea scoring (Codex CLI)
        ↓
Ranked idea list
        ↓
Top papers for reading / CSV / JSONL / portal
