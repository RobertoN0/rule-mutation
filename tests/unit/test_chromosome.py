"""Unit tests for the full rule-set chromosome + rendering space.

Covers gene/allele resolution, priority-offset ordering (D13), the move
builders, and the cache-signature / chromosome-id contracts. No LLM, no Semgrep.
"""
from __future__ import annotations

import pytest

from src.optimizer.chromosome import (
    GeneState,
    RuleSetChromosome,
    RuleSetSpace,
    dominates,
)


@pytest.fixture
def space() -> RuleSetSpace:
    return RuleSetSpace(
        all_rule_ids=["a", "b", "c"],
        originals={"a": "A", "b": "B", "c": "C"},
    )


# ---------------------------------------------------------------------------
class TestGeneState:
    def test_depth_and_mutated(self):
        g0 = GeneState("a", "A", [])
        g2 = GeneState("a", "A''", ["m1", "m2"])
        assert g0.depth == 0 and not g0.is_mutated
        assert g2.depth == 2 and g2.is_mutated


# ---------------------------------------------------------------------------
class TestRenderOrder:
    def test_all_zero_preserves_retrieval_order(self, space):
        o = space.origin()
        # priority all 0 ⇒ stable sort keeps the given order exactly
        assert o.render_order(["b", "a", "c"]) == ["b", "a", "c"]
        assert space.render_prompt(o, ["b", "a"]) == "B\n\n---\n\nA"

    def test_positive_priority_moves_to_front(self, space):
        o = space.origin()
        c = o.with_priority("a", 5)
        assert c.render_order(["b", "a"]) == ["a", "b"]
        assert space.render_prompt(c, ["b", "a"]) == "A\n\n---\n\nB"

    def test_negative_priority_moves_to_back(self, space):
        o = space.origin()
        c = o.with_priority("b", -5)
        assert c.render_order(["b", "a", "c"]) == ["a", "c", "b"]

    def test_equal_priority_is_stable(self, space):
        o = space.origin()
        c = o.with_priority("a", 3).with_priority("b", 3)
        # a and b share priority 3 ⇒ retrieval order kept between them
        assert c.render_order(["b", "a", "c"]) == ["b", "a", "c"]

    def test_empty_prompt_renders_empty(self, space):
        assert space.render_prompt(space.origin(), []) == ""


# ---------------------------------------------------------------------------
class TestMoves:
    def test_with_gene_stacks_on_current_allele(self, space):
        o = space.origin()
        g1 = o.with_gene("a", "A1", "m1")
        g2 = g1.with_gene("a", "A2", "m2")
        assert g2.genes["a"].text == "A2"
        assert g2.genes["a"].mutation_path == ["m1", "m2"]
        assert g2.gene_depth("a") == 2
        # parent unchanged (structural sharing is safe)
        assert g1.genes["a"].mutation_path == ["m1"]

    def test_with_reverted_drops_gene(self, space):
        o = space.origin()
        g = o.with_gene("a", "A1", "m1")
        rev = g.with_reverted("a")
        assert "a" not in rev.genes
        assert space.allele(rev, "a") == "A"  # back to original

    def test_with_priority_zero_drops_override(self, space):
        o = space.origin()
        c = o.with_priority("a", 4)
        assert "a" in c.order_priority
        back = c.with_priority("a", 0)
        assert "a" not in back.order_priority

    def test_parent_id_lineage(self, space):
        o = space.stamp(space.origin())
        child = space.stamp(o.with_gene("a", "A1", "m1"))
        assert child.parent_id == o.cid
        assert child.cid != o.cid

    def test_mutated_rule_ids(self, space):
        o = space.origin()
        c = o.with_gene("a", "A1", "m").with_gene("c", "C1", "m")
        assert c.mutated_rule_ids() == {"a", "c"}


# ---------------------------------------------------------------------------
class TestSpace:
    def test_allele_falls_back_to_original(self, space):
        o = space.origin()
        assert space.allele(o, "a") == "A"
        c = o.with_gene("a", "A!", "m")
        assert space.allele(c, "a") == "A!"
        assert space.allele(c, "b") == "B"

    def test_origin_is_baseline_content(self, space):
        o = space.origin()
        assert o.genes == {} and o.order_priority == {}
        assert o.cid == space.chromosome_id(o)

    def test_signature_scopes_to_affected_prompts(self, space):
        o = space.stamp(space.origin())
        c = space.stamp(o.with_gene("c", "C!", "m"))
        # prompt without c: signature unchanged ⇒ cache hit
        assert space.prompt_signature(c, ["a", "b"]) == space.prompt_signature(o, ["a", "b"])
        # prompt with c: signature changes ⇒ rerun
        assert space.prompt_signature(c, ["a", "c"]) != space.prompt_signature(o, ["a", "c"])

    def test_signature_changes_with_order_only_when_pair_present(self, space):
        o = space.origin()
        c = o.with_priority("a", 9)  # a first globally
        # prompt with both a and b: order flips ⇒ different signature
        assert space.prompt_signature(c, ["b", "a"]) != space.prompt_signature(o, ["b", "a"])
        # prompt with only a: no relative order to change ⇒ same signature
        assert space.prompt_signature(c, ["a"]) == space.prompt_signature(o, ["a"])

    def test_chromosome_id_independent_of_dict_insertion_order(self, space):
        c1 = space.origin()
        c1.genes = {"a": GeneState("a", "A!", ["m"]), "c": GeneState("c", "C!", ["m"])}
        c2 = space.origin()
        c2.genes = {"c": GeneState("c", "C!", ["m"]), "a": GeneState("a", "A!", ["m"])}
        assert space.chromosome_id(c1) == space.chromosome_id(c2)

    def test_chromosome_id_distinguishes_order_from_text(self, space):
        o = space.origin()
        text_change = space.chromosome_id(o.with_gene("a", "A!", "m"))
        order_change = space.chromosome_id(o.with_priority("a", 1))
        assert o.cid != text_change != order_change != o.cid


# ---------------------------------------------------------------------------
class TestDominates:
    def _c(self, f1, f2, f3):
        c = RuleSetChromosome()
        c.f1, c.f2, c.f3 = f1, f2, f3
        return c

    def test_strict_domination(self):
        assert dominates(self._c(1, 1, 1), self._c(0, 0, 0))
        assert dominates(self._c(1, 0, 0), self._c(0, 0, 0))

    def test_equal_is_not_domination(self):
        assert not dominates(self._c(1, 1, 1), self._c(1, 1, 1))

    def test_tradeoff_is_not_domination(self):
        assert not dominates(self._c(1, 0, 0), self._c(0, 1, 0))
        assert not dominates(self._c(0, 1, 0), self._c(1, 0, 0))
