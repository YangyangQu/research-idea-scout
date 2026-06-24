import unittest

from idea_scout.profile import Dimension, Profile


class AutoCollectTests(unittest.TestCase):
    def profile(self) -> Profile:
        return Profile(
            name="proassist",
            language="English",
            description="Streaming egocentric proactive assistants.",
            target_tasks=[
                "Improve speak/silence intervention timing for streaming egocentric procedural assistants."
            ],
            positive_keywords=[
                "proactive assistant",
                "intervention timing",
                "egocentric video",
                "procedural mistake detection",
                "task progress",
                "dialogue state",
                "benchmark",
            ],
            negative_keywords=["survey", "benchmark", "dataset only"],
            prefer=["online task monitoring and recovery tracking"],
            downweight=["generic video question answering"],
            scoring_dimensions=[
                Dimension("intervention_timing_value", "Timing value", 2.0),
                Dimension("streaming_feasibility", "Streaming feasibility", 1.0),
            ],
        )

    def test_build_queries_prioritizes_profile_phrases_and_caps_count(self):
        from idea_scout.auto_collect import build_queries

        queries = build_queries(self.profile(), max_queries=4, extra_queries=["recovery tracking"])

        self.assertEqual(4, len(queries))
        self.assertEqual("recovery tracking", queries[0])
        self.assertIn("intervention timing", queries)
        self.assertIn("egocentric video", queries)
        self.assertNotIn("benchmark", queries)

    def test_reconstructs_openalex_abstract_from_inverted_index(self):
        from idea_scout.auto_collect import reconstruct_openalex_abstract

        abstract = reconstruct_openalex_abstract(
            {
                "Streaming": [0],
                "assistants": [1],
                "need": [2],
                "timely": [3],
                "interventions": [4],
            }
        )

        self.assertEqual("Streaming assistants need timely interventions", abstract)

    def test_deduplicate_papers_prefers_abstract_and_citation_rich_record(self):
        from idea_scout.auto_collect import deduplicate_papers

        rows = [
            {"title": "A Study on Proactive Assistance", "abstract": "", "citation_count": 20},
            {
                "title": "A Study on Proactive Assistance",
                "abstract": "Detailed abstract",
                "citation_count": 2,
                "url": "https://example.test/paper",
            },
        ]

        deduped = deduplicate_papers(rows)

        self.assertEqual(1, len(deduped))
        self.assertEqual("Detailed abstract", deduped[0]["abstract"])
        self.assertEqual("https://example.test/paper", deduped[0]["url"])

    def test_prefilter_keeps_diverse_top_papers_under_total_cap(self):
        from idea_scout.auto_collect import prefilter_papers

        rows = [
            {
                "title": "Proactive intervention timing for egocentric video",
                "abstract": "A streaming assistant predicts when to intervene during procedural tasks.",
                "source_query": "intervention timing",
                "venue": "CVPR",
                "year": 2025,
                "citation_count": 8,
            },
            {
                "title": "Another proactive assistant intervention model",
                "abstract": "An online procedural assistant uses task progress to decide when to speak.",
                "source_query": "intervention timing",
                "venue": "ICLR",
                "year": 2024,
                "citation_count": 5,
            },
            {
                "title": "Dialogue state for task assistance",
                "abstract": "Dialogue state and task progress are tracked for grounded assistance.",
                "source_query": "dialogue state",
                "venue": "ACL",
                "year": 2023,
                "citation_count": 12,
            },
            {
                "title": "A survey benchmark dataset",
                "abstract": "A survey and benchmark dataset only.",
                "source_query": "dialogue state",
                "venue": "Workshop",
                "year": 2025,
                "citation_count": 30,
            },
        ]

        keep, reject, summary = prefilter_papers(
            rows,
            self.profile(),
            keep_total=2,
            per_query_keep=1,
        )

        self.assertEqual(2, len(keep))
        self.assertEqual(2, len(reject))
        self.assertEqual({"dialogue state", "intervention timing"}, {p["source_query"] for p in keep})
        self.assertNotIn("A survey benchmark dataset", [p["title"] for p in keep])
        self.assertEqual(2, summary["kept"])

    def test_cheap_score_prefers_domain_anchored_paper_over_broad_high_citation_match(self):
        from idea_scout.auto_collect import cheap_score

        profile = Profile(
            name="egocentric_assistance",
            language="English",
            description="Streaming egocentric proactive assistance.",
            target_tasks=["Understand procedural steps and intervention timing."],
            positive_keywords=["intervention timing", "egocentric video"],
            negative_keywords=[],
            prefer=["egocentric procedural assistance"],
            downweight=["medical or public-health intervention papers without AI video assistance"],
            scoring_dimensions=[Dimension("fit", "Fit", 1.0)],
        )
        broad = {
            "title": "Optimal timing of public health interventions for cancer treatment",
            "abstract": "We study intervention timing and progress monitoring in a clinical public health setting.",
            "venue": "Nature",
            "year": 2024,
            "citation_count": 5000,
            "source_query": "intervention timing",
        }
        anchored = {
            "title": "Streaming egocentric video step transition detection for proactive assistants",
            "abstract": "An online egocentric video assistant detects procedural step transitions for proactive assistance.",
            "venue": "arXiv",
            "year": 2024,
            "citation_count": 0,
            "source_query": "egocentric video",
        }

        self.assertGreater(
            cheap_score(anchored, profile)["cheap_score"],
            cheap_score(broad, profile)["cheap_score"],
        )

    def test_cheap_score_rewards_soft_profile_phrase_overlap(self):
        from idea_scout.auto_collect import cheap_score

        profile = Profile(
            name="egocentric_assistance",
            language="English",
            description="Streaming egocentric proactive assistance.",
            target_tasks=["Understand procedural steps and intervention timing."],
            positive_keywords=[
                "procedural mistake detection",
            ],
            negative_keywords=[],
            prefer=["egocentric procedural assistance"],
            downweight=["generic multimodal monitoring without procedural assistance"],
            scoring_dimensions=[Dimension("fit", "Fit", 1.0)],
        )
        generic = {
            "title": "A Cybertwin Based Multimodal Network for ECG Patterns Monitoring Using Deep Learning",
            "abstract": "This multimodal deep learning network monitors ECG patterns and includes an assistant for healthcare data.",
            "venue": "Nature",
            "year": 2024,
            "citation_count": 5000,
            "source_query": "multimodal assistant",
        }
        procedural = {
            "title": "Differentiable Task Graph Learning: Procedural Activity Representation and Online Mistake Detection from Egocentric Videos",
            "abstract": "The method learns task graphs for procedural activities and performs online mistake detection from egocentric videos.",
            "venue": "arXiv",
            "year": 2024,
            "citation_count": 6,
            "source_query": "procedural mistake detection",
        }

        self.assertGreater(
            cheap_score(procedural, profile)["cheap_score"],
            cheap_score(generic, profile)["cheap_score"],
        )

    def test_cheap_score_penalizes_off_topic_medical_monitoring(self):
        from idea_scout.auto_collect import cheap_score

        profile = Profile(
            name="egocentric_proactive_timing",
            language="English",
            description="Streaming egocentric proactive assistance.",
            target_tasks=["Detect procedural step completion and proactive intervention timing."],
            positive_keywords=[
                "streaming egocentric video understanding",
                "online procedural activity recognition",
                "step completion detection",
                "step transition detection",
                "workflow state tracking",
                "proactive assistance timing",
                "egocentric task assistance",
                "procedural step anticipation",
                "human activity workflow recognition",
                "context aware proactive assistant",
            ],
            negative_keywords=[],
            prefer=["online procedural state modeling for egocentric video assistants"],
            downweight=["medical monitoring without egocentric procedural assistance"],
            scoring_dimensions=[Dimension("fit", "Fit", 1.0)],
        )
        off_topic = {
            "title": "A Cybertwin Based Multimodal Network for ECG Patterns Monitoring Using Deep Learning",
            "abstract": (
                "In next-generation network architecture, the Cybertwin drove the sixth generation "
                "of cellular networks sixth-generation (6G) to play an active role in many "
                "applications, such as healthcare and computer vision. This article introduces "
                "a possible Cybertwin based multimodal network for electrocardiogram (ECG) "
                "patterns monitoring during daily activity. The Cybertwin nodes combine data "
                "caching, behavior logger, and communications assistant in the edge cloud. "
                "We present a novel deep convolutional neural network based human activity "
                "recognition classifier. The healthcare monitoring values and potential clinical "
                "medicine are provided by the Cybertwin based network for ECG patterns observing."
            ),
            "venue": "IEEE Transactions on Industrial Informatics",
            "year": 2022,
            "citation_count": 123,
            "source_query": "multimodal assistant",
        }
        on_topic = {
            "title": "AURA: Always-On Understanding and Real-Time Assistance via Video Streams",
            "abstract": (
                "Video Large Language Models have achieved strong performance on many video "
                "understanding tasks, but most existing systems remain offline and are not "
                "well-suited for live video streams that require continuous observation and "
                "timely response. We propose AURA, an end-to-end streaming visual interaction "
                "framework that enables a unified VideoLLM to continuously process video streams "
                "and support both real-time question answering and proactive responses."
            ),
            "venue": "arXiv",
            "year": 2026,
            "citation_count": 0,
            "source_query": "streaming video assistance",
        }

        self.assertGreater(
            cheap_score(on_topic, profile)["cheap_score"],
            cheap_score(off_topic, profile)["cheap_score"],
        )

    def test_cheap_score_requires_core_topic_anchor_over_generic_video_detection(self):
        from idea_scout.auto_collect import cheap_score

        profile = Profile(
            name="egocentric_proactive_timing",
            language="English",
            description="Streaming egocentric proactive assistance.",
            target_tasks=[
                "Online step completion detection in egocentric task videos",
                "Step transition and workflow phase boundary recognition",
                "Proactive assistant intervention timing during procedural activities",
            ],
            positive_keywords=[
                "streaming egocentric video understanding",
                "online procedural activity recognition",
                "step completion detection",
                "step transition detection",
                "workflow state tracking",
                "proactive assistance timing",
                "egocentric task assistance",
                "procedural step anticipation",
                "first person activity forecasting",
                "instructional video state modeling",
                "temporal action segmentation online",
                "task progress estimation",
                "human activity workflow recognition",
                "context aware proactive assistant",
            ],
            negative_keywords=[],
            prefer=["proactive procedural assistance with recovery tracking"],
            downweight=["generic surveillance video detection"],
            scoring_dimensions=[Dimension("fit", "Fit", 1.0)],
        )
        generic_video_detection = {
            "title": "VD-Net: An Edge Vision-Based Surveillance System for Violence Detection",
            "abstract": (
                "The automation of surveillance systems, driven by the rapid development of "
                "computer vision technology, has significantly enhanced the analysis of "
                "surveillance videos, particularly in recognition of human activity, including "
                "behavior analysis and violence detection, thereby bolstering public and "
                "industrial security. Despite these advancements, detecting and analyzing "
                "violent actions remains challenging, especially for real-time surveillance "
                "systems with limited computing power. We propose an artificial "
                "intelligence-based framework called VD-Net."
            ),
            "venue": "IEEE Access",
            "year": 2024,
            "citation_count": 47,
            "source_query": "procedural mistake detection",
        }
        procedural_assistance = {
            "title": "Plan, Watch, Recover: A Benchmark and Architectures for Proactive Procedural Assistance",
            "abstract": (
                "We envision a proactive multi-modal assistant system which gives users real-time "
                "step-by-step guidance on a procedural task, autonomously deciding when to "
                "interrupt, and how to coach. Progress is limited by the absence of large-scale, "
                "cross-domain benchmarks that reflect realistic conditions, particularly the "
                "common case in which users deviate from the expected step sequence. We release "
                "EgoProactive, a large-scale wearable-egocentric dataset for proactive "
                "procedural assistance with explicit Out-of-Plan annotations and recovery steps."
            ),
            "venue": "arXiv",
            "year": 2026,
            "citation_count": 0,
            "source_query": "proactive assistant",
        }

        self.assertGreater(
            cheap_score(procedural_assistance, profile)["cheap_score"],
            cheap_score(generic_video_detection, profile)["cheap_score"],
        )

    def test_cheap_score_prefers_proactive_procedural_assistance_over_egocentric_ar_only(self):
        from idea_scout.auto_collect import cheap_score

        profile = Profile(
            name="egocentric_proactive_timing",
            language="English",
            description="Streaming egocentric proactive assistance.",
            target_tasks=[
                "Online step completion detection in egocentric task videos",
                "Step transition and workflow phase boundary recognition",
                "Proactive assistant intervention timing during procedural activities",
            ],
            positive_keywords=[
                "streaming egocentric video understanding",
                "online procedural activity recognition",
                "step completion detection",
                "step transition detection",
                "workflow state tracking",
                "proactive assistance timing",
                "egocentric task assistance",
                "procedural step anticipation",
                "first person activity forecasting",
                "instructional video state modeling",
                "temporal action segmentation online",
                "task progress estimation",
                "human activity workflow recognition",
                "context aware proactive assistant",
            ],
            negative_keywords=[],
            prefer=["step-aware proactive assistance for long-horizon procedural tasks"],
            downweight=["egocentric AR infrastructure without procedural assistance"],
            scoring_dimensions=[Dimension("fit", "Fit", 1.0)],
        )
        egocentric_ar_only = {
            "title": "A real-time wearable AR system for egocentric vision on the edge",
            "abstract": (
                "Real-time performance is critical for Augmented Reality (AR) systems as it "
                "directly affects responsiveness and enables the timely rendering of virtual "
                "content superimposed on real scenes. We present the DARLENE wearable AR system, "
                "analysing its specifications, overall architecture and core algorithmic "
                "components. DARLENE comprises AR glasses and a wearable computing node "
                "responsible for several time-critical computation tasks. These include computer "
                "vision modules developed for the real-time analysis of dynamic scenes supporting "
                "functionalities for instance segmentation, tracking and pose estimation. The "
                "proposed system further supports real-time video streaming and interconnection "
                "with external IoT nodes. The proposed system targets time-critical security "
                "applications where it can be used to enhance police officers' situational "
                "awareness."
            ),
            "venue": "Virtual Reality",
            "year": 2024,
            "citation_count": 12,
            "source_query": "streaming egocentric video understanding",
        }
        proactive_procedural = {
            "title": (
                "Pro$^2$Assist: Continuous Step-Aware Proactive Assistance with Multimodal "
                "Egocentric Perception for Long-Horizon Procedural Tasks"
            ),
            "abstract": (
                "Procedural tasks with multiple ordered steps are ubiquitous in daily life. "
                "Recent advances in multimodal large language models have enabled personal "
                "assistants that support daily activities. Existing systems primarily provide "
                "reactive guidance triggered by user queries, or limited proactive assistance "
                "for isolated short-term events rather than long-horizon procedural tasks. "
                "Pro$^2$Assist is a step-aware proactive assistant that continuously tracks "
                "fine-grained task progress and reasons over the user's evolving state to "
                "provide timely assistance throughout tasks. It extracts step-oriented "
                "procedural context from multi-scale temporal dynamics and task-specific expert "
                "knowledge. Evaluations show that Pro$^2$Assist achieves up to 2.29x the "
                "proactive timing accuracy of baselines."
            ),
            "venue": "arXiv",
            "year": 2026,
            "citation_count": 0,
            "source_query": "proactive assistant",
        }
        procedural_benchmark = {
            "title": "Plan, Watch, Recover: A Benchmark and Architectures for Proactive Procedural Assistance",
            "abstract": (
                "We envision a proactive multi-modal assistant system which gives users "
                "real-time step-by-step guidance on a procedural task, autonomously deciding "
                "when to interrupt, and how to coach. Progress is limited by the absence of "
                "large-scale, cross-domain benchmarks that reflect realistic conditions, "
                "particularly the common case in which users deviate from the expected step "
                "sequence. We release EgoProactive, a large-scale wearable-egocentric dataset "
                "for proactive procedural assistance with explicit Out-of-Plan annotations "
                "and recovery steps."
            ),
            "venue": "arXiv",
            "year": 2026,
            "citation_count": 0,
            "source_query": "proactive assistant",
        }

        self.assertGreater(
            cheap_score(proactive_procedural, profile)["cheap_score"],
            cheap_score(egocentric_ar_only, profile)["cheap_score"],
        )
        self.assertGreater(
            cheap_score(procedural_benchmark, profile)["cheap_score"],
            cheap_score(egocentric_ar_only, profile)["cheap_score"],
        )

    def test_cheap_score_uses_profile_topic_anchors(self):
        from idea_scout.auto_collect import cheap_score

        profile = Profile(
            name="agent_memory",
            language="English",
            description="LLM agent memory research.",
            target_tasks=["Find reusable agent memory mechanisms."],
            positive_keywords=["agent memory", "memory retrieval"],
            negative_keywords=[],
            prefer=["episodic memory and retrieval mechanisms"],
            downweight=["generic chatbot applications"],
            scoring_dimensions=[Dimension("fit", "Fit", 1.0)],
            topic_anchors={
                "high_value": ["episodic memory", "memory retrieval"],
                "required_any": ["agent memory"],
                "broad_ai": ["large language model"],
                "off_topic_domains": ["database indexing"],
            },
        )
        row = {
            "title": "Episodic Memory Retrieval for LLM Agents",
            "abstract": "A large language model uses agent memory, episodic memory, and memory retrieval to solve long-horizon tasks.",
            "venue": "arXiv",
            "year": 2025,
            "citation_count": 0,
            "source_query": "agent memory",
        }

        scored = cheap_score(row, profile)

        self.assertIn("episodic memory", scored["core_topic_hits"])
        self.assertIn("agent memory", scored["core_topic_hits"])

    def test_preset_can_be_overridden(self):
        from idea_scout.auto_collect import resolve_preset

        preset = resolve_preset("frugal", raw_collect_limit=123, score_top_k=9)

        self.assertEqual(123, preset.raw_collect_limit)
        self.assertEqual(9, preset.score_top_k)
        self.assertLess(preset.score_top_k, preset.prefilter_keep)


if __name__ == "__main__":
    unittest.main()
