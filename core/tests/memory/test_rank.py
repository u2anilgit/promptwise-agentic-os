from core.memory.rank import reciprocal_rank_fusion


def test_fusion_ranks_an_id_in_both_lists_above_one_in_a_single_list():
    # id 1: rank 1 in both lists. id 2: rank 2 in bm25 only. id 3: rank 2 in vector only.
    bm25_ids = [1, 2]
    vector_ids = [1, 3]
    fused = reciprocal_rank_fusion(bm25_ids, vector_ids)
    assert fused[0] == 1  # appears in both, highest fused score


def test_fusion_deduplicates_ids():
    fused = reciprocal_rank_fusion([1, 2, 3], [1, 2, 3])
    assert fused == [1, 2, 3]  # same relative order preserved, no duplicates


def test_fusion_handles_disjoint_lists():
    fused = reciprocal_rank_fusion([1, 2], [3, 4])
    assert set(fused) == {1, 2, 3, 4}
    assert len(fused) == 4


def test_fusion_handles_one_empty_list():
    assert reciprocal_rank_fusion([], [1, 2]) == [1, 2]
    assert reciprocal_rank_fusion([1, 2], []) == [1, 2]


def test_fusion_handles_both_empty():
    assert reciprocal_rank_fusion([], []) == []
