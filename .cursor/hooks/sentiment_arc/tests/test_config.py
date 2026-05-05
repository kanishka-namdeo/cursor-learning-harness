"""Tests for config.py — defaults and env var overrides."""

import os

import pytest

from sentiment_arc import config


class TestConfigDefaults:
    def test_sentiment_model_default(self):
        assert "roberta" in config.SENTIMENT_MODEL.lower()

    def test_embedding_model_default(self):
        assert "mpnet" in config.EMBEDDING_MODEL.lower()

    def test_fallback_embedding_model(self):
        assert "bge" in config.EMBEDDING_MODEL_FALLBACK.lower()

    def test_smoothing_alpha(self):
        assert config.SMOOTHING_ALPHA == 0.3

    def test_min_dip_depth(self):
        assert config.MIN_DIP_DEPTH == 0.1

    def test_min_turns(self):
        assert config.MIN_TURNS_FOR_ANALYSIS == 4

    def test_batch_sizes(self):
        assert config.SENTIMENT_BATCH_SIZE == 32
        assert config.EMBEDDING_BATCH_SIZE == 32

    def test_archetypes_list(self):
        assert "smooth_convergence" in config.ARCHETYPES
        assert "error" in config.ARCHETYPES

    def test_frustrating_archetypes(self):
        assert config.FRUSTRATING_ARCHETYPES == {
            "escalating_frustration",
            "mismatched_effort",
            "looping",
            "abandoned",
        }

    def test_smooth_archetypes(self):
        assert config.SMOOTH_ARCHETYPES == {
            "smooth_convergence",
            "rapid_resolution",
        }
