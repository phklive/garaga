import random

import pytest

from garaga.definitions import CURVES, CurveID
from garaga.hints.multi_miller_witness import (
    get_final_exp_witness,
    get_lambda,
    get_miller_loop_output,
)
from garaga.hints.tower_backup import E12
from garaga.precompiled_circuits.multi_pairing_check import (
    MultiPairingCheckCircuit,
    WriteOps,
    get_max_Q_degree,
    get_pairing_check_input,
)


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("curve_id", [CurveID.BN254, CurveID.BLS12_381])
def test_final_exp_witness(seed, curve_id):
    random.seed(seed)
    ONE = E12.one(curve_id.value)
    λ = get_lambda(curve_id)
    q = CURVES[curve_id.value].p
    r = CURVES[curve_id.value].n
    h = (q**12 - 1) // r

    # Test correct case
    f_correct = get_miller_loop_output(curve_id=curve_id, will_be_one=True)
    root_correct_rust, w_full_correct_rust = get_final_exp_witness(
        curve_id.value, f_correct, use_rust=True
    )
    root_correct_python, w_full_correct_python = get_final_exp_witness(
        curve_id.value, f_correct, use_rust=False
    )

    # Compare Rust and Python implementations
    assert (
        root_correct_rust == root_correct_python
    ), "Roots should match between Rust and Python implementations"
    assert (
        w_full_correct_rust == w_full_correct_python
    ), "Scaling factors should match between Rust and Python implementations"

    # Test incorrect case
    f_incorrect = get_miller_loop_output(curve_id=curve_id, will_be_one=False)
    root_incorrect_rust, w_full_incorrect_rust = get_final_exp_witness(
        curve_id.value, f_incorrect, use_rust=True
    )
    root_incorrect_python, w_full_incorrect_python = get_final_exp_witness(
        curve_id.value, f_incorrect, use_rust=False
    )

    # Compare Rust and Python implementations
    assert (
        root_incorrect_rust == root_incorrect_python
    ), "Roots should match between Rust and Python implementations"
    assert (
        w_full_incorrect_rust == w_full_incorrect_python
    ), "Scaling factors should match between Rust and Python implementations"

    print(f"{seed}-th check ok")


@pytest.mark.parametrize("curve_id", [CurveID.BN254, CurveID.BLS12_381])
@pytest.mark.parametrize("n_pairs", [2, 3, 4, 5])
@pytest.mark.parametrize("include_m", [False, True])
def test_mpcheck(curve_id: CurveID, n_pairs: int, include_m: bool):
    c = MultiPairingCheckCircuit(name="mock", curve_id=curve_id.value, n_pairs=n_pairs)
    circuit_input, m = get_pairing_check_input(curve_id, n_pairs, include_m=include_m)
    c.write_p_and_q_raw(circuit_input)
    M = c.write_elements(m, WriteOps.INPUT) if m is not None else None
    c.multi_pairing_check(n_pairs, M)  # Check done implicitely here
    c.finalize_circuit()

    def total_cost(c):
        summ = c.summarize()
        summ["total_steps_cost"] = (
            summ["MULMOD"] * 8
            + summ["ADDMOD"] * 4
            + summ["ASSERT_EQ"] * 2
            + summ["POSEIDON"] * 17
            + summ["RLC"] * 28
        )
        return summ

    cost = total_cost(c)
    q_max_degree = max([q.degree() for q in c.accumulate_poly_instructions[0].Qis])

    # Assertions
    assert q_max_degree <= get_max_Q_degree(curve_id.value, n_pairs)

    print(f"\nTest {curve_id.name} {n_pairs=} {'with m' if include_m else 'without m'}")
    print(f"Total cost: {cost}")
    print(f"Q max degree: {q_max_degree}")
