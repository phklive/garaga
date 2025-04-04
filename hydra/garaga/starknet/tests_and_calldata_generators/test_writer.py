import concurrent.futures
import json
import random
import subprocess

import garaga.modulo_circuit_structs as structs
from garaga.definitions import (
    CURVES,
    CurveID,
    G1G2Pair,
    G1Point,
    G2Point,
    get_base_field,
)
from garaga.precompiled_circuits.multi_pairing_check import get_pairing_check_input
from garaga.starknet.cli.utils import create_directory
from garaga.starknet.tests_and_calldata_generators.mpcheck import MPCheckCalldataBuilder
from garaga.starknet.tests_and_calldata_generators.msm import MSMCalldataBuilder
from garaga.starknet.tests_and_calldata_generators.signatures import (
    ECDSASignature,
    EdDSA25519Signature,
    SchnorrSignature,
)

TESTS_DIR = "src/src/tests/autogenerated"


def generate_pairing_test(curve_id, n_pairs, n_fixed_g2, include_m, seed):
    random.seed(seed)
    pairs, public_pair = get_pairing_check_input(
        curve_id=curve_id,
        n_pairs=n_pairs,
        include_m=include_m,
        return_pairs=True,
    )
    builder = MPCheckCalldataBuilder(
        curve_id=curve_id,
        pairs=pairs,
        n_fixed_g2=n_fixed_g2,
        public_pair=public_pair,
    )
    return builder.to_cairo_1_test()


def generate_msm_test(curve_id, n_points, seed):
    random.seed(seed)
    builder = MSMCalldataBuilder(
        curve_id=curve_id,
        points=[G1Point.gen_random_point(curve_id) for _ in range(n_points - 1)]
        + [G1Point.infinity(curve_id)],
        scalars=[0]
        + [random.randint(0, CURVES[curve_id.value].n) for _ in range(n_points - 1)],
    )
    return builder.to_cairo_1_test()


def generate_msm_test_edge_cases(curve_id, n_points, seed):
    random.seed(seed)
    builder = MSMCalldataBuilder(
        curve_id=curve_id,
        points=[G1Point.gen_random_point(curve_id) for _ in range(n_points - 1)]
        + [G1Point.infinity(curve_id)],
        scalars=[0]
        + [random.randint(0, CURVES[curve_id.value].n) for _ in range(n_points - 1)],
    )
    return builder.to_cairo_1_test(
        test_name=f"test_msm_{curve_id.name}_{n_points}P_edge_case"
    )


def generate_tower_pairing_test(curve_id, n_pairs, seed):
    random.seed(seed)
    pairs: list[G1G2Pair]
    if n_pairs == 1:
        pairs = [
            G1G2Pair(
                p=G1Point.get_nG(curve_id, 1),
                q=G2Point.get_nG(curve_id, 1),
            )
        ]
    else:
        pairs, _ = get_pairing_check_input(
            curve_id=curve_id, n_pairs=n_pairs, return_pairs=True
        )

    res = G1G2Pair.pair(pairs, curve_id)
    res = res.felt_coeffs
    e12t = structs.E12T(name="expected_result", elmts=res)
    i_s = list(range(n_pairs))
    code = f"""
#[test]
fn test_tower_pairing_{curve_id.name}_{n_pairs}P() {{
    let mut res:E12T = E12TOne::one();
"""
    for i, pair in enumerate(pairs):
        code += f"""
    {structs.G1PointCircuit.from_G1Point(f"p{i}", pair.p).serialize()}
    p{i}.assert_on_curve({curve_id.value});
    {structs.G2PointCircuit.from_G2Point(f"q{i}", pair.q).serialize()}
    q{i}.assert_on_curve({curve_id.value});
    let (tmp{i}) = miller_loop_{pair.p.curve_id.name.lower()}_tower(p{i}, q{i});
    let (res) = run_{pair.p.curve_id.name.upper()}_E12T_MUL_circuit(tmp{i}, res);"""
    code += f"""
    let final = final_exp_{curve_id.name.lower()}_tower(res);
    assert_eq!(final, {e12t.serialize(raw=True)});
}}
"""
    return code


def generate_tower_final_exp_test(curve_id, seed):
    from garaga.hints.tower_backup import E12

    random.seed(seed)
    field = get_base_field(curve_id)
    elmts = [field.random() for _ in range(12)]
    e12 = E12(elmts, curve_id.value)
    e12t = structs.E12T(name="input", elmts=elmts)
    expected = structs.E12T(name="expected", elmts=(e12.final_exp()).felt_coeffs)
    code = f"""
#[test]
fn test_tower_final_exp_{curve_id.name}() {{
    {e12t.serialize()}
    let res = final_exp_{curve_id.name.lower()}_tower(input);
    assert_eq!(res, {expected.serialize(raw=True)});
}}
"""
    return code


def generate_schnorr_test(curve_id, seed):
    random.seed(seed)
    schnorr_sig: SchnorrSignature = SchnorrSignature.sample(curve_id)
    T = "u384" if curve_id == CurveID.BLS12_381 else "u288"
    code = f"""
#[test]
fn test_schnorr_{curve_id.name}() {{
    let mut sch_sig_with_hints_serialized = array!{schnorr_sig.serialize_with_hints(as_str=True)}.span();
    let sch_with_hints = Serde::<SchnorrSignatureWithHint<{T}>>::deserialize(ref sch_sig_with_hints_serialized).expect('FailToDeserialize');
    let is_valid = is_valid_schnorr_signature(sch_with_hints, {curve_id.value});
    assert!(is_valid);
}}
"""
    return code


def generate_ecdsa_test(curve_id, seed):
    random.seed(seed)
    ecdsa_sig: ECDSASignature = ECDSASignature.sample(curve_id)
    T = "u384" if curve_id == CurveID.BLS12_381 else "u288"
    code = f"""
#[test]
fn test_ecdsa_{curve_id.name}() {{
    let mut ecdsa_sig_with_hints_serialized = array!{ecdsa_sig.serialize_with_hints(as_str=True)}.span();
    let ecdsa_with_hints = Serde::<ECDSASignatureWithHint<{T}>>::deserialize(ref ecdsa_sig_with_hints_serialized).expect('FailToDeserialize');
    let is_valid = is_valid_ecdsa_signature(ecdsa_with_hints, {curve_id.value});
    assert!(is_valid);
}}
"""
    return code


def write_test_file(
    file_path: str, header: str, test_generators: list, curve_ids: list, **kwargs
):
    """Write a test file with the given header and test generators.

    Args:
        file_path: Path to write the test file
        header: Module header with imports
        test_generators: List of (generator_fn, params) tuples
        curve_ids: List of curve IDs to generate tests for
        **kwargs: Additional arguments passed to generators
    """
    create_directory(TESTS_DIR)
    with open(f"{TESTS_DIR}/{file_path}", "w") as f:
        f.write(header)
        with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = []
            for gen_fn, params in test_generators:
                for curve_id in curve_ids:
                    for param in params:
                        futures.append(
                            executor.submit(
                                gen_fn, curve_id, *param, kwargs.get("seed", 0)
                            )
                        )

            results = [future.result() for future in futures]
            for result in results:
                f.write(result)
                f.write("\n")


def get_tower_pairing_config():
    """Configuration for tower pairing tests"""
    header = """
    use garaga::single_pairing_tower::{
        E12TOne, u384,G1Point, G2Point, E12T, miller_loop_bls12_381_tower,
        miller_loop_bn254_tower, final_exp_bls12_381_tower, final_exp_bn254_tower,
    };
    use garaga::ec_ops::{G1PointImpl};
    use garaga::ec_ops_g2::{G2PointImpl};
    use garaga::circuits::tower_circuits::{
        run_BN254_E12T_MUL_circuit, run_BLS12_381_E12T_MUL_circuit
    };
    """

    test_generators = [
        (generate_tower_pairing_test, [(n,) for n in [1, 2, 3]]),
        (generate_tower_final_exp_test, [()]),
    ]

    curve_ids = [CurveID.BN254, CurveID.BLS12_381]
    return "tower_pairing_tests.cairo", header, test_generators, curve_ids


def get_pairing_config():
    """Configuration for pairing tests"""
    header = """
        use garaga::pairing_check::{
            G1G2Pair, G1Point, G2Point, G2Line, E12D, MillerLoopResultScalingFactor,
            multi_pairing_check_bn254_2P_2F,
            multi_pairing_check_bls12_381_2P_2F,
            u384,
            MPCheckHintBN254,
            MPCheckHintBLS12_381,
            u288,
        };
        use garaga::groth16::{
            E12DMulQuotient,
            multi_pairing_check_bn254_3P_2F_with_extra_miller_loop_result,
            multi_pairing_check_bls12_381_3P_2F_with_extra_miller_loop_result,
        };
    """

    params = [(2, 2, False), (3, 2, True)]
    test_generators = [(generate_pairing_test, params)]
    curve_ids = [CurveID.BN254, CurveID.BLS12_381]
    return "pairing_tests.cairo", header, test_generators, curve_ids


def get_msm_config():
    """Configuration for MSM tests"""
    header = """
        use garaga::ec_ops::{G1Point, FunctionFelt, u384, msm_g1, MSMHint, DerivePointFromXHint};
    """

    msm_sizes = [1, 2, 3, 4, 10, 11, 12]
    edge_cases = [1, 2, 3]

    test_generators = [
        (generate_msm_test, [(n,) for n in msm_sizes]),
        (generate_msm_test_edge_cases, [(n,) for n in edge_cases]),
    ]

    curve_ids = [
        CurveID.BN254,
        CurveID.BLS12_381,
        CurveID.SECP256R1,
        CurveID.SECP256K1,
        CurveID.ED25519,
        CurveID.GRUMPKIN,
    ]
    return "msm_tests.cairo", header, test_generators, curve_ids


def get_schnorr_config():
    """Configuration for Schnorr signature tests"""
    header = """
        use garaga::signatures::schnorr::{
            SchnorrSignature, SchnorrSignatureWithHint, is_valid_schnorr_signature,
        };
        use garaga::definitions::{u288, u384};
        use garaga::core::circuit::u288IntoCircuitInputValue;
    """

    test_generators = [(generate_schnorr_test, [()])]
    curve_ids = [
        CurveID.BN254,
        CurveID.BLS12_381,
        CurveID.SECP256R1,
        CurveID.SECP256K1,
        CurveID.ED25519,
        CurveID.GRUMPKIN,
    ]
    return "schnorr_tests.cairo", header, test_generators, curve_ids


def get_ecdsa_config():
    """Configuration for ECDSA signature tests"""
    header = """
        use garaga::signatures::ecdsa::{
            ECDSASignature, ECDSASignatureWithHint, is_valid_ecdsa_signature,
        };
        use garaga::definitions::{u288, u384};
        use garaga::core::circuit::u288IntoCircuitInputValue;
    """

    test_generators = [(generate_ecdsa_test, [()])]
    curve_ids = [
        CurveID.BN254,
        CurveID.BLS12_381,
        CurveID.SECP256R1,
        CurveID.SECP256K1,
        CurveID.ED25519,
        CurveID.GRUMPKIN,
    ]
    return "ecdsa_tests.cairo", header, test_generators, curve_ids


def generate_eddsa_test(sig: EdDSA25519Signature, test_index: int) -> str:
    assert sig.is_valid()
    msg_bytes_len = len(sig.msg)
    code = f"""
#[test]
fn test_eddsa_{test_index}_{msg_bytes_len}B() {{
    let mut eddsa_sig_with_hints_serialized = array!{sig.serialize_with_hints(as_str=True)}.span();
    let eddsa_with_hints = Serde::<EdDSASignatureWithHint>::deserialize(ref eddsa_sig_with_hints_serialized).expect('FailToDeserialize');
    let is_valid = is_valid_eddsa_signature(eddsa_with_hints);
    assert!(is_valid);
}}
"""
    return code


def generate_test(index, vector):
    signature = EdDSA25519Signature.from_json(vector)
    return generate_eddsa_test(signature, index)


def generate_eddsa_test_file() -> str:
    """Configuration for EDDSA signature tests"""
    code = """
    use garaga::signatures::eddsa_25519::{
        EdDSASignature, EdDSASignatureWithHint, is_valid_eddsa_signature
    };
    """

    with open("tests/ed25519_test_vectors.json", "r") as f:
        test_vectors = json.load(f)

    test_vectors = test_vectors[0:64:2]

    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(generate_test, i, vec): i
            for i, vec in enumerate(test_vectors)
        }
        results = [None] * len(test_vectors)
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            results[index] = future.result()

    for result in results:
        code += result
    return code


def write_all_tests():
    """Generate all test files"""
    random.seed(0)

    # Generate each test file
    for config_fn in [
        get_tower_pairing_config,
        get_pairing_config,
        get_msm_config,
        get_schnorr_config,
        get_ecdsa_config,
    ]:
        file_path, header, test_generators, curve_ids = config_fn()
        write_test_file(file_path, header, test_generators, curve_ids, seed=0)

    with open("src/src/tests/autogenerated/eddsa_tests.cairo", "w") as f:
        f.write(generate_eddsa_test_file())
    subprocess.run(["scarb", "fmt", f"{TESTS_DIR}"], check=True)


if __name__ == "__main__":
    import time

    start = time.time()
    write_all_tests()
    end = time.time()
    print(f"Time taken: {end - start} seconds")
