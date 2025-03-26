#!/bin/bash

# Function to clean directories
clean_dirs() {
    rm -rf src/src/circuits/*.cairo
    rm -rf src/contracts/groth16_example_bls12_381/*
    rm -rf src/contracts/groth16_example_bn254/*
    rm -rf src/contracts/risc0_verifier_bn254/*
    rm -rf src/contracts/noir_ultra_keccak_honk_example/*
    rm -rf src/contracts/noir_ultra_starknet_honk_example/*
}

# Function to run generators without tests
run_generators() {
    set -e  # Exit immediately if a command exits with a non-zero status

    python hydra/garaga/starknet/honk_contract_generator/generator_honk.py || { echo "Error in generator_honk.py"; exit 1; }
    python hydra/garaga/precompiled_circuits/all_circuits.py || { echo "Error in all_circuits.py"; exit 1; }
    python hydra/garaga/starknet/groth16_contract_generator/generator.py || { echo "Error in generator.py"; exit 1; }
    python hydra/garaga/starknet/groth16_contract_generator/generator_risc0.py || { echo "Error in generator_risc0.py"; exit 1; }
}

# Function to run generators with tests
run_generators_with_tests() {
    rm -rf src/src/tests/autogenerated/*
    run_generators
    python hydra/garaga/starknet/tests_and_calldata_generators/test_writer.py || { echo "Error in test_writer.py"; exit 1; }
}

# Main script
clean_dirs

start_time=$(date +%s.%N)

if [ "$1" = "no-tests" ]; then
    run_generators
else
    run_generators_with_tests
fi

end_time=$(date +%s.%N)
elapsed_time=$(echo "$end_time - $start_time" | bc)

printf "Total time taken: %.2f seconds\n" "$elapsed_time"
