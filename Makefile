.PHONY: build test coverage run run-profile

build:
	$(MAKE) clean

setup:
	./tools/make/setup.sh

bytecode-check:
	./tools/make/bytecode_check.sh

rewrite:
	./tools/make/rewrite.sh

rewrite-no-tests:
	./tools/make/rewrite.sh no-tests

regen:
	cd src/contracts/mutator_set && make regen

steps:
	./tools/make/steps.sh

ci-e2e:
	./tools/make/ci_e2e.sh

ci-hydra:
	./tools/make/ci_hydra.sh

ci-cairo:
	./tools/make/ci_cairo.sh

ci-wasm:
	./tools/make/ci_wasm.sh

wasm:
	./tools/make/wasm.sh
clean:
	rm -rf build/compiled_cairo_files
	mkdir -p build
	mkdir build/compiled_cairo_files
